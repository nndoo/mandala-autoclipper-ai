"""Stage 5C offline signals, source replay, enrichment and synthetic-media checks."""

from array import array
import contextlib
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT/"scripts"))
import analyze_adaptive_av_evidence_v01 as av
import test_adaptive_director_input_v03 as fixtures
from validate_universal_analysis_v02 import sample_analysis


def setUpModule():
    global network_guard
    network_guard = patch("socket.socket.connect", side_effect=AssertionError("Stage 5C tests forbid network"))
    network_guard.start()


def tearDownModule():
    network_guard.stop()


def context(music="present", layers=None, speech="absent", duration=12):
    a = sample_analysis()
    a["source"]["duration_sec"] = duration
    a["content_profile"].update(music_presence=music, speech_presence=speech)
    a["segments"][0].update(start_sec=0, end_sec=duration, audio_layers=layers or ["music"])
    return av.region_context(a)


def signal_windows(onsets, duration=12):
    return [{"start_sec": i/50, "end_sec": (i+1)/50,
             "rms": 0.7 if any(0 <= i/50-t < 0.04-1e-8 for t in onsets) else 0.008,
             "spectral_flux": 0.0, "spectral_centroid_hz": 0.0,
             "dbfs": 20*math.log10(0.7 if any(0 <= i/50-t < 0.04-1e-8 for t in onsets) else 0.008)}
            for i in range(int(duration*50))]


def features(frames, step=0.125):
    result, previous = [], None
    for i, frame in enumerate(frames):
        pixels, histogram, metrics = av.pixels_feature(frame, previous)
        result.append({"frame_index": i, "pts_sec": i*step, **metrics})
        previous = pixels, histogram, metrics["brightness"]
    return result


def patterned_frame(bright=False, shift=0):
    return b"".join(bytes((230, 160, 80) if (x+shift)%16 < 8 else (180, 80, 50)) if bright else
                    bytes((20, 70, 120) if (x+shift)%16 < 8 else (60, 110, 170))
                    for y in range(64) for x in range(64))


class SignalTests(unittest.TestCase):
    def rhythm(self, windows, ctx=None):
        events, novelty = av.audio_events(windows)
        return av.rhythm_estimates(windows, events, novelty, ctx or context())

    def test_periodic_rhythm_produces_conditional_estimate(self):
        windows = signal_windows([i/2 for i in range(24)])
        result = self.rhythm(windows)
        self.assertEqual(result["status"], "estimated")
        estimate = result["estimates"][0]
        self.assertAlmostEqual(estimate["tempo_bpm"], 120, delta=1)
        self.assertFalse(estimate["musical_fact_verified"])
        self.assertFalse(result["grid_interpolation_performed"])
        onsets = {e["event_id"]:e["time_sec"] for e in av.audio_events(windows)[0]}
        self.assertGreater(len(estimate["candidate_beats"]), 8)
        for beat in estimate["candidate_beats"]:
            self.assertEqual(beat["time_sec"], onsets[beat["onset_event_id"]])

    def test_irregular_rhythm_has_no_fabricated_bpm(self):
        windows = signal_windows([0.1, 0.46, 1.28, 1.72, 2.4, 3.18, 3.44, 4.46, 5.1, 5.58, 6.4, 7.54, 7.82, 8.7, 9.12, 10.22, 11.5])
        result = self.rhythm(windows)
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["estimates"][0]["tempo_bpm"])
        self.assertEqual(result["estimates"][0]["candidate_beats"], [])

    def test_silence(self):
        windows = [{"start_sec": i/50, "end_sec": (i+1)/50, "rms": 0, "dbfs": -120,
                    "spectral_flux": 0.0, "spectral_centroid_hz": 0.0} for i in range(600)]
        events, novelty = av.audio_events(windows)
        self.assertEqual([e["kind"] for e in events], ["quiet_region"])
        self.assertEqual(events[0]["end_sec"], 12)
        self.assertEqual(self.rhythm(windows)["status"], "uncertain")

    def test_speech_like_periodic_peaks_never_become_beats(self):
        result = self.rhythm(signal_windows([i/2 for i in range(24)]), context("absent", ["speech"], "present"))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["estimates"], [])

    def test_unknown_music_never_promoted(self):
        result = self.rhythm(signal_windows([i/2 for i in range(24)]), context("uncertain", ["unknown"], "uncertain"))
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["estimates"], [])

    def test_mixed_speech_music_not_suitable(self):
        self.assertFalse(context("present", ["speech", "music"], "present")["regions"][0]["music_analysis_suitable"])

    def test_music_profile_conflict_preserved(self):
        c = context("absent", ["music"])
        self.assertIn("absent_music_profile_with_regional_music", c["music_classification_conflicts"])
        self.assertFalse(c["regions"][0]["music_analysis_suitable"])

    def test_uncertain_speech_cannot_supply_music_only_gate(self):
        self.assertFalse(context("present", ["unknown", "music"], "uncertain")["regions"][0]["music_analysis_suitable"])

    def test_uncertain_speech_even_with_music_layers_keeps_review(self):
        self.assertFalse(context("present", ["music"], "uncertain")["regions"][0]["music_analysis_suitable"])

    def test_unexamined_audio_blocks_music_attribution(self):
        a = sample_analysis(); a["analysis_meta"]["audio_examined"] = False
        self.assertFalse(av.region_context(a)["regions"][0]["music_analysis_suitable"])

    def test_onset_is_generic_signal_candidate(self):
        events, _ = av.audio_events(signal_windows([1, 4, 8]))
        onsets = [e for e in events if e["kind"] == "onset_candidate"]
        self.assertEqual(len(onsets), 3)
        self.assertTrue(all(not e["verified_fact"] for e in onsets))

    def test_energy_and_intensity_changes(self):
        events, _ = av.audio_events(signal_windows([1, 4, 8]))
        kinds = {e["kind"] for e in events}
        self.assertTrue({"energy_peak", "abrupt_audio_change", "intensity_change", "quiet_region"} <= kinds)

    def test_insufficient_periodic_duration(self):
        result = self.rhythm(signal_windows([0.5, 1, 1.5], duration=2), context(duration=2))
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["estimates"][0]["tempo_bpm"])

    def test_pcm_rms_and_source_offset(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/"audio.pcm"; path.write_bytes(array("h", [16384, -16384]*320).tobytes())
            windows = av.energy_windows(path, 2, 2.04)
        self.assertEqual(windows[0]["start_sec"], 2)
        self.assertEqual(windows[-1]["end_sec"], 2.04)
        self.assertAlmostEqual(windows[0]["rms"], .5)

    def test_incomplete_pcm_sample_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/"bad.pcm"; path.write_bytes(b"x")
            with self.assertRaisesRegex(av.base.AdapterError, "Incomplete"):
                av.energy_windows(path, 0, 1)

    def test_frequency_change_detected_without_energy_jump(self):
        samples=array('h',[int(15000*math.sin(2*math.pi*(440 if i<6400 else 2000)*i/16000)) for i in range(16000)])
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'tone.pcm'; path.write_bytes(samples.tobytes())
            windows=av.energy_windows(path,0,1)
        self.assertAlmostEqual(windows[19]['rms'],windows[20]['rms'],delta=.01)
        self.assertGreater(windows[20]['spectral_flux'],.3)
        self.assertGreater(windows[20]['spectral_centroid_hz'],1800)
        self.assertTrue(any(e['kind']=='onset_candidate' and abs(e['time_sec']-.4)<.04 for e in av.audio_events(windows)[0]))


class VisualTests(unittest.TestCase):
    def kinds(self, frames):
        return {e["kind"] for e in av.visual_events(features(frames), len(frames)/8)}

    def test_known_textured_hard_cut_is_candidate(self):
        events = av.visual_events(features([patterned_frame()]*8+[patterned_frame(True)]*8), 2)
        cut = next(e for e in events if e["kind"] == "hard_cut_candidate")
        self.assertFalse(cut["verified_fact"])
        self.assertEqual((cut["start_sec"], cut["end_sec"]), (.875, 1))

    def test_continuous_pan_no_verified_cut(self):
        kinds = self.kinds([patterned_frame(shift=i*4) for i in range(16)])
        self.assertNotIn("hard_cut_candidate", kinds)
        self.assertIn("high_motion_candidate", kinds)

    def test_uniform_lighting_change_not_cut(self):
        kinds = self.kinds([bytes([30])*12288]*8+[bytes([110])*12288]*8)
        self.assertIn("brightness_change", kinds)
        self.assertNotIn("hard_cut_candidate", kinds)

    def test_flash_recovery_not_hard_cut(self):
        frames = [bytes([80])*12288]*8+[bytes([250])*12288]+[bytes([80])*12288]*8
        events = av.visual_events(features(frames), len(frames)/8)
        flash = next(e for e in events if e["kind"] == "flash_candidate")
        self.assertEqual(flash["time_sec"], 1)
        self.assertNotIn("hard_cut_candidate", {e["kind"] for e in events})

    def test_monotonic_fade_candidate(self):
        self.assertIn("fade_candidate", self.kinds([bytes([10+i*10])*12288 for i in range(16)]))

    def test_stable_regions(self):
        self.assertEqual(self.kinds([patterned_frame()]*16), {"stable_region"})

    def test_large_same_histogram_change_remains_uncertain(self):
        frames = [patterned_frame()]*8+[patterned_frame(shift=8)]*8
        events = av.visual_events(features(frames), 2)
        self.assertTrue(all(e["verified_fact"] is False for e in events))
        self.assertNotIn("hard_cut_candidate", {e["kind"] for e in events})

    def test_pts_sampling_uses_decoded_times(self):
        times = [0, .03, .07, .11, .17, .22, .31, .41, .49, .58]
        def run(command, consume, **limits):
            # ceil(10/(.6*8))=3: selected indices 0,3,6,9
            self.assertIn("select=not(mod(n\\,3)),scale=64:64:flags=area", command)
            consume(patterned_frame()*4)
        with patch.object(av.base, "bounded_run", side_effect=run):
            fs, sampling = av.visual_features(Path("source.mp4"), times, .6)
        self.assertEqual([f["pts_sec"] for f in fs], [0, .11, .31, .58])
        self.assertEqual(sampling["sample_count"], 4)

    def test_incomplete_decoded_visual_output(self):
        with patch.object(av.base, "bounded_run", side_effect=lambda command, consume, **kw: consume(b"x")):
            with self.assertRaisesRegex(av.base.AdapterError, "samples/PTS mismatch"):
                av.visual_features(Path("source.mp4"), [0,.1,.2], .3)

    def test_missing_frame_pts_rejected(self):
        with patch.object(av, "json_probe", return_value={"frames": [{}]}):
            with self.assertRaisesRegex(av.base.AdapterError, "timestamps"):
                av.frame_times(Path("source.mp4"), "v:0", 0, 1)

    def test_invalid_or_nonmonotonic_pts(self):
        for times in ([0,1.5], [0,-.1], [0,0], [0,float("nan")]):
            with self.subTest(times=times), patch.object(av, "json_probe", return_value={"frames":[{"best_effort_timestamp_time":t} for t in times]}):
                with self.assertRaises(av.base.AdapterError):
                    av.frame_times(Path("source.mp4"), "v:0", 0, 1)

    def test_audio_discontinuity_rejected(self):
        with patch.object(av, "json_probe", return_value={"frames":[{"best_effort_timestamp_time":0,"nb_samples":1024},{"best_effort_timestamp_time":1,"nb_samples":1024}]}):
            with self.assertRaisesRegex(av.base.AdapterError, "Discontinuous"):
                av.frame_times(Path("source.mp4"), "a:0", 0, 2, sample_rate=48000)

    def test_nonzero_container_origin_normalized(self):
        with patch.object(av, "json_probe", return_value={"frames":[{"best_effort_timestamp_time":10},{"best_effort_timestamp_time":10.2}]}):
            self.assertEqual(av.frame_times(Path("source.mp4"), "v:0", 10, 1), [0, .1999999999999993])


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        self.a = av.event("a1", "onset_candidate", 1, 1.02)
        self.v = av.event("v1", "hard_cut_candidate", .95, 1.1, time=1.1, uncertainty=.15)

    def test_close_alignment_has_offset_and_uncertainty(self):
        match, = av.correlate([self.a], [self.v], 2, "available")
        self.assertAlmostEqual(match["measurements"]["offset_sec"], .1)
        self.assertEqual(match["relation_status"], "uncertain")
        self.assertFalse(match["intentional_sync_verified"])
        self.assertEqual(match["confidence"], "low")

    def test_nonmatch_has_no_fabrication(self):
        self.v.update(time_sec=1.9, end_sec=1.9)
        self.assertEqual(av.correlate([self.a], [self.v], 2, "available"), [])

    def test_music_absent_is_only_generic_acoustic_proximity(self):
        match, = av.correlate([self.a], [self.v], 2, "available")
        self.assertEqual(match["kind"], "temporal_proximity_candidate")
        self.assertNotIn("music", match)

    def test_unknown_audio_is_not_promoted(self):
        match, = av.correlate([self.a], [self.v], 2, "available")
        self.assertFalse(match["verified_fact"])

    def test_no_audio_returns_no_matches(self):
        self.assertEqual(av.correlate([], [self.v], 2, "unavailable"), [])

    def test_unavailable_audio_does_not_correlate_stray_events(self):
        self.assertEqual(av.correlate([self.a], [self.v], 2, "unavailable"), [])

    def test_quiet_regions_are_not_sync_onsets(self):
        self.a["kind"] = "quiet_region"
        self.assertEqual(av.correlate([self.a], [self.v], 2, "available"), [])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AdapterTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        for name in ("adaptive-av-evidence.v0.1.schema.json", "adaptive-av-validation.v0.1.schema.json"):
            shutil.copyfile(PROJECT/"src/schemas"/name, self.root/"src/schemas"/name)
        self.output = self.root/"av/new.v01"
        self.director = self.root/"director.json"
        self.fixture.build(output=self.director)
        (self.root/"implementation.py").write_text("# synthetic receipt, not production execution\n")
        self.data = array("h", [262]*int(self.fixture.source["duration_sec"]*16000)).tobytes()
        self.stream = {"index":1,"codec_name":"aac","sample_rate":"16000","channels":1}
        self.fs = features([patterned_frame()]*8+[patterned_frame(True)]*8)
        self.sampling = {"stride_frames":4,"decoded_frame_count":64,"sample_count":16,
                         "sample_rgb_sha256":"a"*64,"observed_max_gap_sec":.125,"presentation_origin_sec":None}
        for obj,name,kwargs in (
            (av,"code_receipts",{'return_value':[av.reference(self.root/"implementation.py")]}),
            (av.base,"small_output",{'return_value':'synthetic tool version\n'}),
            (av,"media_clock",{'return_value':0}),
            (av.gate,"audio_streams",{'return_value':[self.stream]}),
            (av,"frame_times",{'side_effect':self.times}),
            (av,"visual_features",{'side_effect':lambda *args:(copy.deepcopy(self.fs),self.sampling.copy())}),
            (av.shared,"capture_pcm",{'side_effect':self.capture}),
        ):
            guard = patch.object(obj,name,**kwargs); mock = guard.start(); self.addCleanup(guard.stop)
            if name == "audio_streams": self.stream_mock = mock
        self.original_hashes = {p:av.gate.sha256_file(p) for p in (self.fixture.video,self.fixture.metadata_path,self.fixture.analysis_path,self.director)}

    def capture(self, video, stream, path, limits):
        path.write_bytes(self.data)
        return {"sha256":hashlib.sha256(self.data).hexdigest(),"byte_count":len(self.data),"sample_count":len(self.data)//2,"duration_sec":len(self.data)/32000}

    def times(self, video, selector, origin, duration, **kw):
        if kw.get("sample_rate"):
            return {"start_sec":0,"end_sec":len(self.data)/32000,"decoded_duration_sec":len(self.data)/32000,"frame_count":100}
        return [f["pts_sec"] for f in self.fs]

    def generate(self, **kw):
        inputs = dict(video=self.fixture.video,metadata=self.fixture.metadata_path,analysis=self.fixture.analysis_path,
                      output_dir=self.output,director_input=self.director)
        inputs.update(kw)
        return av.generate(**inputs)

    def artifact(self, name): return av.read(self.output/name)

    def blocked(self, expression, **kw):
        with self.assertRaisesRegex(av.base.AdapterError, expression): self.generate(**kw)
        self.assertFalse(self.output.exists())

    def test_valid_generation_replay_and_attachment(self):
        report = self.generate()
        self.assertTrue(report["checks"]["source_sha256"])
        self.assertEqual(av.validate_bundle(self.output), report)
        e = self.artifact(av.ENRICHED)
        self.assertEqual(e["evidence"]["visual_timing"]["timing_precision"], "signal_estimated")
        self.assertFalse(e["editorial_policy"]["render_approved"])
        self.assertFalse(e["editorial_policy"]["publish_approved"])
        self.assertEqual(e["renderer_capabilities"], {"verification_status":"unknown","supported_operations":[]})
        self.assertIsNone(e["evidence"]["transcript"])
        self.assertIsNone(e["evidence"]["speech_alignment"])
        for p,h in self.original_hashes.items(): self.assertEqual(av.gate.sha256_file(p),h)

    def test_missing_source(self):
        self.fixture.video.unlink(); self.blocked("missing")

    def test_sha_mismatch(self):
        self.fixture.metadata["verification"]["sha256"] = "0"*64
        self.fixture.save_inputs(); self.blocked("SHA-256 mismatch")

    def test_metadata_mismatch(self):
        self.fixture.metadata["source"]["fps"] = 25
        self.fixture.save_inputs(); self.blocked("differs from FFprobe")

    def test_canonical_schema_invalid(self):
        del self.fixture.analysis["segments"]
        self.fixture.save_inputs(); self.blocked("schema violation")

    def test_canonical_timestamp_invalid(self):
        self.fixture.analysis["segments"][0]["end_sec"] = 100
        self.fixture.save_inputs(); self.blocked("semantic/timing")

    def test_canonical_source_mismatch(self):
        self.fixture.analysis["source"]["video_id"] = "other"
        self.fixture.save_inputs(); self.blocked("source metadata mismatch")

    def test_existing_output_is_protected(self):
        self.output.mkdir(parents=True); (self.output/"sentinel").write_text("keep")
        with self.assertRaisesRegex(av.base.AdapterError,"already exists"): self.generate()
        self.assertEqual((self.output/"sentinel").read_text(),"keep")

    def test_path_traversal(self): self.blocked("traversal", video="../source.mp4")

    def test_output_traversal(self): self.blocked("Unsafe", output_dir="../av")

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root/"escape").symlink_to(outside, target_is_directory=True)
            self.blocked("inside project", output_dir=self.root/"escape/av")

    def test_input_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            p=Path(outside)/'source.mp4'; p.write_bytes(b'outside')
            alias=self.root/'alias.mp4'; alias.symlink_to(p)
            self.blocked("escapes project",video=alias)

    def test_dangling_output_symlink(self):
        self.output.parent.mkdir(); self.output.symlink_to(self.root/"does-not-exist")
        with self.assertRaisesRegex(av.base.AdapterError, "Unsafe"): self.generate()

    def test_missing_audio_stream_visual_only(self):
        self.stream_mock.return_value = []
        self.generate()
        a = self.artifact(av.AUDIO)
        self.assertEqual(a["data"]["audio_status"], "unavailable")
        self.assertEqual(a["data"]["rhythm"]["status"], "unavailable")
        self.assertEqual(a["events"], [])
        self.assertIsNone(self.artifact(av.ENRICHED)["evidence"]["music_rhythm"])
        self.assertEqual(self.artifact(av.CORRELATION)["events"], [])
        av.validate_bundle(self.output)

    def test_invalid_generated_artifact_schema(self):
        self.fs[0]["brightness"] = 10
        self.blocked("schema violation")

    def test_invalid_audio_timestamps(self):
        with patch.object(av,"energy_windows",return_value=[{"start_sec":0,"end_sec":100,"rms":.03,"dbfs":20*math.log10(.03),
                                                           "spectral_flux":0.0,"spectral_centroid_hz":0.0}]):
            self.blocked("audio window timestamps")

    def test_invalid_visual_timestamps(self):
        self.fs[-1]["pts_sec"] = 100
        self.blocked("timestamp")

    def test_nonfinite_measurement(self):
        self.fs[-1]["brightness"] = float("nan")
        self.blocked("Nonfinite")

    def test_cross_source_artifact_rejected(self):
        self.generate()
        a = {n:self.artifact(n) for n in (av.AUDIO,av.VISUAL,av.CORRELATION)}
        a[av.VISUAL]["source"]["sha256"] = "0"*64
        with self.assertRaisesRegex(av.base.AdapterError,"Cross-source"): av.validate_artifacts(a)

    def test_tampered_event_rejected(self):
        self.generate(); p = self.output/av.VISUAL; d=av.read(p)
        d["events"][0]["time_sec"] += .01; p.write_text(json.dumps(d))
        with self.assertRaises(av.base.AdapterError): av.validate_bundle(self.output)

    def test_forged_features_cannot_pass_source_replay(self):
        self.generate(); p=self.output/av.VISUAL; d=av.read(p)
        d["data"]["sampling"]["sample_rgb_sha256"] = "b"*64; p.write_text(json.dumps(d))
        with self.assertRaisesRegex(av.base.AdapterError,"source replay"): av.validate_bundle(self.output)

    def test_artifact_symlink_escape_rejected(self):
        self.generate()
        with tempfile.TemporaryDirectory() as outside:
            p=Path(outside)/'visual.json'; p.write_text('{}')
            (self.output/av.VISUAL).unlink(); (self.output/av.VISUAL).symlink_to(p)
            with self.assertRaisesRegex(av.base.AdapterError,'escapes project'): av.validate_bundle(self.output)

    def test_provenance_file_change_blocks(self):
        self.generate(); (self.root/"implementation.py").write_text("changed")
        with self.assertRaisesRegex(av.base.AdapterError,"hash mismatch"): av.validate_bundle(self.output)

    def test_report_eligibility_cannot_be_promoted(self):
        self.generate(); p=self.output/av.REPORT; d=av.read(p)
        d["eligibility"]["music_rhythm"] = True; p.write_text(json.dumps(d))
        with self.assertRaisesRegex(av.base.AdapterError,"report binding"): av.validate_bundle(self.output)

    def test_renderer_fabrication_rejected(self):
        d=av.read(self.director); d["renderer_capabilities"]={"verification_status":"verified","supported_operations":["cut"]}
        self.director.write_text(json.dumps(d)); self.blocked("unknown renderer")

    def test_unsafe_speech_reference_rejected(self):
        d=av.read(self.director); d["evidence"]["transcript"]={"path":"../secret.json","timing_precision":"asr_estimate"}
        self.director.write_text(json.dumps(d)); self.blocked("traversal")

    def test_existing_speech_refs_preserved_exactly(self):
        p=self.root/"speech.json"; p.write_text('{}')
        d=av.read(self.director)
        for slot in ("transcript","speech_alignment"):
            d["evidence"][slot]={"path":"speech.json","timing_precision":"asr_estimate"}
        self.director.write_text(json.dumps(d)); self.generate()
        e=self.artifact(av.ENRICHED)
        for slot in ("transcript","speech_alignment"): self.assertEqual(e["evidence"][slot],d["evidence"][slot])

    def test_approval_true_rejected(self):
        for key in ("render_approved","publish_approved"):
            d=av.read(self.director); d["editorial_policy"][key]=True; self.director.write_text(json.dumps(d))
            self.blocked("schema violation")
            d["editorial_policy"][key]=False; self.director.write_text(json.dumps(d))

    def test_director_source_contamination_rejected(self):
        d=av.read(self.director); d["source"]["video_id"]="other"; self.director.write_text(json.dumps(d))
        self.blocked("Director Input source mismatch")

    def test_director_canonical_reference_contamination(self):
        p=self.root/"other-canonical.json"; p.write_text('{}')
        d=av.read(self.director); d["evidence"]["universal_analysis"]["path"]=p.name; self.director.write_text(json.dumps(d))
        self.blocked("canonical reference mismatch")

    def test_uncertain_audio_slot_remains_null(self):
        self.generate()
        self.assertEqual(self.artifact(av.AUDIO)["data"]["rhythm"]["status"],"uncertain")
        self.assertIsNone(self.artifact(av.ENRICHED)["evidence"]["music_rhythm"])

    def test_frame_verified_precision_cannot_be_fabricated(self):
        self.generate(); p=self.output/av.VISUAL; d=av.read(p)
        d['timestamp_precision']['label']='frame_verified'; p.write_text(json.dumps(d))
        with self.assertRaisesRegex(av.base.AdapterError,'schema violation'): av.validate_bundle(self.output)

    def test_enriched_policy_and_source_preserved(self):
        original=av.read(self.director)
        original['editorial_policy'].update(goal='Explore unfamiliar structures',max_variants=1)
        self.director.write_text(json.dumps(original)); self.generate()
        enriched=self.artifact(av.ENRICHED)
        self.assertEqual(enriched['editorial_policy'],original['editorial_policy'])
        self.assertEqual(enriched['source'],original['source'])
        self.assertEqual(enriched['evidence']['universal_analysis'],original['evidence']['universal_analysis'])

    def test_valid_periodic_music_attachment(self):
        n=int(self.fixture.source["duration_sec"]*16000)
        self.data=array("h", [22000 if i%8000<640 else 262 for i in range(n)]).tobytes()
        report=self.generate()
        self.assertTrue(report["eligibility"]["music_rhythm"])
        self.assertEqual(self.artifact(av.ENRICHED)["evidence"]["music_rhythm"]["timing_precision"],"signal_estimated")

    def test_nonzero_exit_on_cli_block(self):
        with contextlib.redirect_stderr(io.StringIO()), patch.object(av.base,"bounded_run", side_effect=av.base.AdapterError("timeout")):
            self.assertEqual(av.main(['validate','--bundle','none']),1)

    def test_cli_process_group_and_output_limits(self):
        def run(command, consume, **limits):
            self.assertEqual(command[1:4],["--signal=TERM","--kill-after=2s","240s"])
            self.assertEqual(limits,{"max_bytes":8388608,"timeout":245})
            consume(b'{"status":"passed"}\n')
        with contextlib.redirect_stdout(io.StringIO()), patch.object(av.base,"bounded_run",side_effect=run):
            self.assertEqual(av.main(['validate','--bundle','none']),0)

    def test_atomic_writer_failure_cleanup(self):
        original=av.shared.write_json
        def fail(path,data):
            if path.name==av.VISUAL: raise av.base.AdapterError("simulated write failure")
            original(path,data)
        with patch.object(av.shared,"write_json",side_effect=fail): self.blocked("simulated")
        self.assertEqual(list(self.root.rglob('.adaptive-input-*.tmp')),[])

    def test_pcm_timeout_cleans_temporary_directory(self):
        visited=[]
        def fail(video,stream,path,limits):
            visited.append(path.parent); path.write_bytes(b'temporary')
            raise av.base.AdapterError('Media subprocess timeout exceeded')
        with patch.object(av.shared,'capture_pcm',side_effect=fail): self.blocked('timeout')
        self.assertTrue(visited)
        self.assertTrue(all(not p.exists() for p in visited))

    def test_json_size_limit_rejected(self):
        self.generate()
        with (self.output/av.VISUAL).open('wb') as f: f.truncate(av.PARAMETERS['max_json_bytes']+1)
        with self.assertRaisesRegex(av.base.AdapterError,'resource limit'): av.validate_bundle(self.output)

    def test_reusable_enrich_validated_bundle(self):
        self.generate(director_input=None)
        output=self.root/"second.enriched.json"
        self.assertEqual(av.enrich(self.output,self.director,output)["status"],"passed")
        self.assertTrue(output.is_file())
        with self.assertRaisesRegex(av.base.AdapterError,"already exists"): av.enrich(self.output,self.director,output)


class SyntheticMediaTests(unittest.TestCase):
    def test_process_group_timeout_reaps_child(self):
        chunks=bytearray()
        script="""import subprocess,signal,time
child=subprocess.Popen(['sleep','30'])
print(child.pid,flush=True)
def stop(*args): raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,stop)
try:
    time.sleep(30)
except KeyboardInterrupt:
    pass
finally:
    child.wait(timeout=2)
    print('reaped',flush=True)
"""
        with self.assertRaises(av.base.AdapterError):
            av.base.bounded_run([shutil.which('timeout'),'--signal=TERM','--kill-after=2s','1s',sys.executable,'-B','-c',script],
                                chunks.extend,max_bytes=1024,timeout=5)
        self.assertIn(b'reaped',chunks)
        import os
        with self.assertRaises(ProcessLookupError): os.kill(int(chunks.splitlines()[0]),0)

    def test_actual_ffmpeg_synthetic_pts_flash_audio_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='.av-media-test-',dir=PROJECT) as t:
            root=Path(t); video=root/'source.mp4'
            # Actual offline media, not a mock: two textures, a brief bright flash,
            # and a 2 Hz pulsed tone. No network protocols enabled.
            graph=("testsrc2=size=128x128:rate=30:duration=8," 
                   "drawbox=color=white:t=fill:enable='between(t,3,3.12)'[v];"
                   "sine=frequency=440:sample_rate=16000:duration=8,"
                   "volume='if(lt(mod(t,0.5),0.08),1,0.01)':eval=frame[a]")
            result=subprocess.run(['ffmpeg','-nostdin','-v','error','-filter_complex',graph,
                                   '-map','[v]','-map','[a]','-c:v','mpeg4','-threads','1','-c:a','aac',str(video)],
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            self.assertEqual(result.returncode,0)
            source={'video_id':'local-sha256-'+av.gate.sha256_file(video)[:32],**av.base.probe_video(video)}
            metadata={'source':source,'verification':{'method':'ffprobe_and_sha256','file_name':video.name,'sha256':av.gate.sha256_file(video)}}
            canonical=sample_analysis(); canonical['source']=source; canonical['segments'][0]['end_sec']=8
            for name,data in [('metadata.json',metadata),('canonical.json',canonical)]: (root/name).write_text(json.dumps(data))
            report=av.generate(video,root/'metadata.json',root/'canonical.json',root/'evidence')
            self.assertEqual(av.validate_bundle(root/'evidence'),report)
            a=av.read(root/'evidence'/av.AUDIO); v=av.read(root/'evidence'/av.VISUAL)
            self.assertTrue(any(e['kind']=='onset_candidate' for e in a['events']))
            self.assertTrue(any(e['kind']=='flash_candidate' for e in v['events']))
            self.assertGreater(len(v['data']['frame_measurements']),40)
            self.assertFalse(v['timestamp_precision']['frame_verified'])
            self.assertTrue(all(e['end_sec']<=8 for e in v['events']))


if __name__ == '__main__':
    unittest.main()
