"""Offline checks: audio equality must never promote legacy transcript provenance."""

import contextlib
import copy
import hashlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import check_speech_evidence_provenance as gate
from validate_universal_analysis_v02 import sample_analysis


def setUpModule():
    global network_guard
    network_guard = patch("socket.socket.connect", side_effect=AssertionError("Offline test forbids network"))
    network_guard.start()


def tearDownModule():
    network_guard.stop()


class GateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mandala-speech-test-")
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        (self.root / "src/schemas").mkdir(parents=True)
        for name in ("adaptive-director-input.v0.3.schema.json", "universal-video-analysis.v0.2.schema.json"):
            shutil.copyfile(PROJECT / "src/schemas" / name, self.root / "src/schemas" / name)
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"source fixture with mocked media decoding")
        self.digest = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.source = {"video_id": "local-sha256-" + self.digest[:32], "duration_sec": 26.533, "width": 1080, "height": 1920, "fps": 30}
        self.metadata = {"source": self.source.copy(), "verification": {"method": "ffprobe_and_sha256", "file_name": self.video.name, "sha256": self.digest}}
        self.analysis = sample_analysis()
        self.analysis["source"] = self.source.copy()
        self.analysis["segments"][0]["end_sec"] = self.source["duration_sec"]
        self.analysis["content_profile"]["speech_presence"] = "present"
        self.analysis["segments"][0]["audio_layers"] = ["speech"]
        self.transcript = {"source_video": self.video.name, "engine": "faster-whisper", "model": "small", "timing_status": "estimated_not_verified", "segments": [{"start_sec": 0.0, "end_sec": 1.0, "text": "unverified speech", "words": [{"start_sec": 0.0, "end_sec": 1.0, "word": "speech"}]}]}
        self.alignment = {"source_video": str(self.video), "analysis_sources": {"semantic": "canonical.json", "speech_timing": "transcript.json"}, "speech_timing_status": "estimated_not_frame_verified", "clips": [{"start_sec": 0, "end_sec": 1}]}
        self.review = {"windows": [{"review_status": "pending", "verified_transcript": None}]}
        self.paths = {name: self.root / filename for name, filename in (("metadata", "metadata.json"), ("analysis", "canonical.json"), ("transcript", "transcript.json"), ("alignment", "alignment.json"), ("review", "review.json"))}
        self.audio = self.root / "existing.wav"
        self.audio.write_bytes(b"WAV fixture decoded by mock")
        self.output = self.root / "reports/speech.json"
        self.save()
        self.pcm = {"sha256": "a" * 64, "byte_count": 32000, "sample_count": 16000, "duration_sec": 1.0}
        self.stream = {"index": 0, "codec_name": "aac", "sample_rate": "44100", "channels": 2, "channel_layout": "stereo"}
        for obj, name, kwargs in (
            (gate.base, "ROOT", {"new": self.root}),
            (gate.base, "probe_video", {"return_value": {k: v for k, v in self.source.items() if k != "video_id"}}),
            (gate, "audio_streams", {"return_value": [self.stream]}),
            (gate, "pcm_fingerprint", {"return_value": self.pcm.copy()}),
            (gate, "small_output", {"return_value": "test media tool version\n"}),
        ):
            guard = patch.object(obj, name, **kwargs)
            mock = guard.start()
            self.addCleanup(guard.stop)
            if name == "pcm_fingerprint":
                self.fingerprint = mock

    def save(self):
        for name in self.paths:
            self.paths[name].write_text(json.dumps(getattr(self, name)), encoding="utf-8")

    def inspect(self, **changes):
        arguments = {"video": self.video, "output": self.output, "audio": self.audio, **self.paths}
        arguments.update(changes)
        return gate.inspect_provenance(**arguments)

    def blocked(self, message, **changes):
        with self.assertRaisesRegex(gate.base.AdapterError, message):
            self.inspect(**changes)
        self.assertFalse(self.output.exists())

    def no_speech(self):
        self.analysis["content_profile"]["speech_presence"] = "absent"
        self.analysis["segments"][0]["audio_layers"] = ["music"]
        self.save()

    def test_correct_source_and_report(self):
        result = self.inspect()
        self.assertEqual(result, json.loads(self.output.read_text()))
        self.assertEqual(result["source"]["sha256"], self.digest)
        self.assertEqual(result["source"]["metadata"], self.source)
        self.assertEqual(result["source"]["association_status"], "verified")
        self.assertEqual(result["metadata_sidecar"]["sha256"], hashlib.sha256(self.paths["metadata"].read_bytes()).hexdigest())
        self.assertEqual(result["canonical_analysis"]["findings_status"], "unverified")
        self.assertEqual(result["transcript"]["sha256"], hashlib.sha256(self.paths["transcript"].read_bytes()).hexdigest())
        self.assertEqual(result["alignment"]["sha256"], hashlib.sha256(self.paths["alignment"].read_bytes()).hexdigest())
        self.assertEqual(result["inspection_status"], "complete")

    def test_source_hash_mismatch(self):
        self.metadata["verification"]["sha256"] = "0" * 64
        self.save()
        self.blocked("SHA-256 mismatch")
        self.fingerprint.assert_not_called()

    def test_missing_video(self):
        self.video.unlink()
        self.blocked("video.*missing")

    def test_metadata_mismatch(self):
        self.metadata["source"]["duration_sec"] = 27
        self.save()
        self.blocked("differs from FFprobe")

    def test_canonical_source_mismatch(self):
        self.analysis["source"]["video_id"] = "other-source"
        self.save()
        self.blocked("Canonical analysis source metadata mismatch")

    def test_canonical_timing_blocker(self):
        self.analysis["segments"][0]["end_sec"] = 100
        self.save()
        self.blocked("semantic/timing validation blocked")

    def test_audio_match_does_not_verify_transcript(self):
        result = self.inspect()
        self.assertEqual(result["audio"]["comparison_status"], "verified")
        self.assertEqual(result["audio"]["stream"]["index"], 0)
        self.assertEqual(result["transcript"]["source_association_status"], "unverified")
        self.assertEqual(result["transcript"]["text_verification_status"], "unverified")
        self.assertEqual(result["transcript"]["timing_verification_status"], "unverified")
        self.assertFalse(result["transcript"]["eligible_for_attachment"])

    def test_audio_mismatch_is_successful_inspection_of_failed_evidence(self):
        self.fingerprint.side_effect = [self.pcm, {**self.pcm, "sha256": "b" * 64}]
        result = self.inspect()
        self.assertEqual(result["inspection_status"], "complete")
        self.assertEqual(result["audio"]["comparison_status"], "failed")
        self.assertIn("extracted_audio_pcm_mismatch", result["evidence_eligibility"]["blocking_reasons"])
        self.assertFalse(result["evidence_eligibility"]["transcript"])

    def test_missing_audio_stream_no_speech(self):
        self.no_speech()
        with patch.object(gate, "audio_streams", return_value=[]):
            result = self.inspect(transcript=None, alignment=None)
        self.fingerprint.assert_not_called()
        self.assertEqual(result["audio"]["source_association_status"], "unavailable")
        self.assertIsNone(result["audio"]["source_pcm"])
        self.assertEqual(result["evidence_eligibility"]["status"], "not_required")

    def test_missing_audio_with_speech_is_ineligible(self):
        with patch.object(gate, "audio_streams", return_value=[]):
            result = self.inspect()
        self.assertIn("source_audio_stream_unavailable", result["evidence_eligibility"]["blocking_reasons"])

    def test_explicit_stream_selection(self):
        second = {**self.stream, "index": 3}
        with patch.object(gate, "audio_streams", return_value=[self.stream, second]):
            result = self.inspect(stream_index=3)
        self.assertEqual(result["audio"]["stream"]["index"], 3)
        self.assertEqual(result["audio"]["available_stream_indices"], [0, 3])
        self.assertEqual(self.fingerprint.call_args_list[0].args, (self.video, 3))

    def test_missing_selected_stream(self):
        self.blocked("Requested audio stream index is unavailable", stream_index=99)

    def test_legacy_transcript_without_binding(self):
        result = self.inspect()["transcript"]
        self.assertEqual(result["declared_binding"], {"source_sha256": None, "audio_pcm_sha256": None})
        self.assertTrue(result["source_filename_matches"])
        self.assertEqual(result["reported_generation"]["engine"], "faster-whisper")
        self.assertEqual(result["generation_provenance_status"], "unverified")
        self.assertIn("generation_not_independently_observed", result["blocking_reasons"])

    def test_transcript_malformed_fields(self):
        cases = [None, [], "bad", [{"text": "speech"}], [{"start_sec": 0, "end_sec": 1, "text": 42}], [{"start_sec": 0, "end_sec": 1, "text": "speech", "words": None}]]
        for segments in cases:
            with self.subTest(segments=segments):
                data = {**self.transcript, "segments": segments}
                self.paths["transcript"].write_text(json.dumps(data))
                result = gate.inspect_transcript(self.paths["transcript"], 26.533, self.digest, self.pcm, self.video.name)
                self.assertEqual(result["structure_status"], "failed")
                self.assertFalse(result["eligible_for_attachment"])

    def test_invalid_transcript_json_has_structured_failure(self):
        self.paths["transcript"].write_text('{"segments":NaN}')
        result = self.inspect()
        self.assertEqual(result["transcript"]["structure_status"], "failed")
        self.assertIn("invalid_evidence_json", result["transcript"]["blocking_reasons"])

    def test_missing_generation_fields_remain_unavailable(self):
        self.transcript = {"segments": self.transcript["segments"]}
        self.save()
        result = self.inspect()["transcript"]
        self.assertIsNone(result["reported_generation"])
        self.assertEqual(result["generation_provenance_status"], "unavailable")

    def test_malformed_generation_fields_are_failed(self):
        self.transcript["engine"] = 42
        self.save()
        result = self.inspect()["transcript"]
        self.assertEqual(result["generation_provenance_status"], "failed")
        self.assertIn("malformed_generation_information", result["blocking_reasons"])

    def test_matching_declared_hashes_do_not_prove_generation(self):
        self.transcript["provenance"] = {"source_sha256": self.digest, "audio_pcm_sha256": self.pcm["sha256"], "generation_verified": True}
        self.save()
        result = self.inspect()["transcript"]
        self.assertEqual(result["source_association_status"], "unverified")
        self.assertEqual(result["generation_provenance_status"], "unverified")
        self.assertFalse(result["eligible_for_attachment"])

    def test_mismatched_declared_hash_fails_association(self):
        self.transcript["provenance"] = {"source_sha256": "b" * 64}
        self.save()
        result = self.inspect()["transcript"]
        self.assertEqual(result["source_association_status"], "failed")
        self.assertIn("declared_source_sha256_invalid_or_mismatched", result["blocking_reasons"])

    def test_malformed_declared_provenance_fails_association(self):
        self.transcript["provenance"] = "not an object"
        self.save()
        result = self.inspect()["transcript"]
        self.assertEqual(result["source_association_status"], "failed")

    def test_invalid_transcript_timestamps(self):
        self.transcript["segments"][0]["end_sec"] = 100
        self.save()
        self.assertEqual(self.inspect()["transcript"]["structure_status"], "failed")

    def test_estimated_timestamps_are_not_promoted(self):
        result = self.inspect()
        self.assertEqual(result["transcript"]["reported_timing_status"], "estimated_not_verified")
        self.assertEqual(result["alignment"]["reported_timing_status"], "estimated_not_frame_verified")
        for key in ("transcript", "alignment"):
            self.assertEqual(result[key]["timing_verification_status"], "unverified")

    def test_claimed_manual_verification_is_not_trusted(self):
        self.transcript["text_verification_status"] = "manually_verified"
        self.transcript["timing_status"] = "frame_verified"
        self.save()
        result = self.inspect()["transcript"]
        self.assertEqual(result["text_verification_status"], "unverified")
        self.assertEqual(result["timing_verification_status"], "unverified")

    def test_alignment_stale_paths(self):
        self.alignment["source_video"] = "/old-home/source.mp4"
        self.alignment["analysis_sources"]["speech_timing"] = "/old-home/transcript.json"
        self.save()
        result = self.inspect()["alignment"]
        self.assertEqual(result["stale_or_unsafe_reference_fields"], ["source_video", "analysis_sources.speech_timing"])
        self.assertFalse(result["eligible_for_attachment"])
        self.assertEqual(result["source_association_status"], "unverified")

    def test_valid_legacy_paths_do_not_prove_alignment(self):
        result = self.inspect()["alignment"]
        self.assertEqual(result["stale_or_unsafe_reference_fields"], [])
        self.assertEqual(result["source_association_status"], "unverified")

    def test_alignment_duration_mismatch_is_failed(self):
        self.alignment["source_duration_sec"] = 99
        self.save()
        result = self.inspect()["alignment"]
        self.assertEqual(result["source_association_status"], "failed")
        self.assertIn("alignment_source_duration_mismatch", result["blocking_reasons"])

    def test_reviewed_text_claims_do_not_promote_accuracy(self):
        self.review["windows"][0] = {"review_status": "verified", "verified_transcript": "corrected text claim"}
        self.save()
        result = self.inspect()
        self.assertTrue(result["transcript_review"]["corrected_text_present"])
        self.assertTrue(result["transcript_review"]["all_windows_reviewed"])
        self.assertEqual(result["transcript_review"]["status"], "unverified")
        self.assertEqual(result["transcript"]["text_verification_status"], "unverified")

    def test_showcase_without_transcript_or_alignment(self):
        self.no_speech()
        result = self.inspect(audio=None, transcript=None, alignment=None, review=None)
        self.assertEqual(result["speech_requirements"]["overall_requirement"], "not_required")
        self.assertEqual(result["evidence_eligibility"]["status"], "not_required")
        self.assertEqual(result["evidence_eligibility"]["blocking_reasons"], [])
        self.assertEqual(result["transcript"]["file_identity_status"], "unavailable")

    def test_unknown_speech_remains_reviewable(self):
        self.no_speech()
        self.analysis["content_profile"]["speech_presence"] = "uncertain"
        self.save()
        result = self.inspect(transcript=None, alignment=None)
        self.assertEqual(result["evidence_eligibility"]["status"], "needs_review")
        self.assertFalse(result["evidence_eligibility"]["transcript"])

    def test_mixed_content_requirements_are_per_region(self):
        self.analysis["segments"] = [
            {**self.analysis["segments"][0], "segment_id": "music", "start_sec": 0, "end_sec": 2, "audio_layers": ["music"]},
            {**self.analysis["segments"][0], "segment_id": "speech", "start_sec": 2, "end_sec": 4, "audio_layers": ["speech", "music"]},
            {**self.analysis["segments"][0], "segment_id": "unknown", "start_sec": 4, "end_sec": 5, "audio_layers": ["unknown"]},
        ]
        self.save()
        result = self.inspect()
        self.assertEqual([r["requirement"] for r in result["speech_requirements"]["regions"]], ["not_required", "required", "needs_review"])

    def test_speech_layer_overrides_absent_profile_for_requirements(self):
        self.analysis["content_profile"]["speech_presence"] = "absent"
        self.save()
        result = self.inspect()
        self.assertEqual(result["speech_requirements"]["overall_requirement"], "required")
        self.assertIn("Speech marked absent but speech audio layer exists", result["warnings"])

    def test_unexamined_audio_remains_uncertain(self):
        self.no_speech()
        self.analysis["analysis_meta"]["audio_examined"] = False
        self.save()
        result = self.inspect(transcript=None, alignment=None)
        self.assertEqual(result["evidence_eligibility"]["status"], "needs_review")

    def test_missing_regions_remain_uncertain(self):
        self.no_speech()
        self.analysis["segments"] = []
        self.save()
        result = self.inspect(transcript=None, alignment=None)
        self.assertEqual(result["evidence_eligibility"]["status"], "needs_review")

    def test_json_resource_limit_blocks_inspection(self):
        with patch.object(gate, "MAX_JSON_BYTES", 10):
            self.blocked("Evidence JSON resource limit exceeded")

    def test_path_traversal_and_external_inputs(self):
        for key in ("video", "metadata", "analysis", "audio", "transcript", "alignment", "review", "output"):
            with self.subTest(path=key):
                self.blocked("escapes project root", **{key: pathlib.Path("../escape")})

    def test_unsafe_input_symlink(self):
        with tempfile.TemporaryDirectory() as external:
            target = pathlib.Path(external) / "transcript.json"
            target.write_text('{}')
            alias = self.root / "alias.json"
            alias.symlink_to(target)
            self.blocked("escapes project root", transcript=alias)

    def test_unsafe_output_parent_symlink(self):
        with tempfile.TemporaryDirectory() as external:
            alias = self.root / "alias"
            alias.symlink_to(external, target_is_directory=True)
            self.blocked("escapes project root", output=alias / "report.json")
            self.assertFalse((pathlib.Path(external) / "report.json").exists())

    def test_existing_output_is_preserved(self):
        self.output.parent.mkdir()
        self.output.write_text("existing report")
        with self.assertRaisesRegex(gate.base.AdapterError, "already exists"):
            self.inspect()
        self.assertEqual(self.output.read_text(), "existing report")
        self.fingerprint.assert_not_called()

    def test_missing_explicit_optional_path_is_execution_error(self):
        self.blocked("transcript.*missing", transcript=self.root / "missing.json")

    def cli_args(self):
        return ["--video", str(self.video), "--metadata", str(self.paths["metadata"]), "--analysis", str(self.paths["analysis"]), "--output", str(self.output), "--audio", str(self.audio), "--transcript", str(self.paths["transcript"])]

    def test_nonzero_cli_for_blocking_execution_error(self):
        self.video.unlink()
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = gate.main(self.cli_args())
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(error.getvalue())["inspection_status"], "failed")
        self.assertFalse(self.output.exists())

    def test_zero_cli_for_completed_ineligible_inspection(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = gate.main(self.cli_args())
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["inspection_status"], "complete")
        self.assertEqual(result["evidence_eligibility"]["status"], "ineligible")


class MediaResourceTests(unittest.TestCase):
    def test_bounded_stream_success(self):
        result = bytearray()
        count = gate.bounded_run([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'pcm-bytes')"], result.extend, max_bytes=100, timeout=5)
        self.assertEqual(count, 9)
        self.assertEqual(result, b"pcm-bytes")

    def test_bounded_stream_resource_limit(self):
        with self.assertRaisesRegex(gate.base.AdapterError, "resource limit"):
            gate.bounded_run([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*8192)"], lambda _: None, max_bytes=100, timeout=5)

    def test_bounded_stream_timeout(self):
        with self.assertRaisesRegex(gate.base.AdapterError, "timeout"):
            gate.bounded_run([sys.executable, "-c", "import time;time.sleep(5)"], lambda _: None, max_bytes=100, timeout=0.1)

    def test_subprocess_failure_does_not_echo_diagnostics(self):
        with self.assertRaisesRegex(gate.base.AdapterError, "raw diagnostics suppressed") as error:
            gate.bounded_run([sys.executable, "-c", "import sys;sys.stderr.write('private-diagnostic');sys.exit(3)"], lambda _: None, max_bytes=100, timeout=5)
        self.assertNotIn("private-diagnostic", str(error.exception))

    def test_missing_executable(self):
        with patch.object(gate.base.subprocess, "Popen", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(gate.base.AdapterError, "unavailable"):
                gate.bounded_run(["ffmpeg"], lambda _: None, max_bytes=100, timeout=1)

    def test_pcm_mapping_and_resource_flags(self):
        captured = []
        def decode(command, consume, **options):
            captured.append((command, options))
            consume(b"\x00\x01" * 4)
            return 8
        with patch.object(gate, "bounded_run", side_effect=decode):
            result = gate.pcm_fingerprint(pathlib.Path("source.mp4"), 3)
        command, options = captured[0]
        self.assertEqual(command[command.index("-map") + 1], "0:3")
        self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
        self.assertEqual(command[command.index("-threads") + 1], "1")
        self.assertEqual(options, {"max_bytes": gate.MAX_PCM_BYTES, "timeout": gate.DECODE_TIMEOUT_SEC})
        self.assertEqual(result["sha256"], hashlib.sha256(b"\x00\x01" * 4).hexdigest())

    def test_invalid_pcm_size(self):
        for count in (0, 3):
            with self.subTest(count=count), patch.object(gate, "bounded_run", return_value=count):
                with self.assertRaisesRegex(gate.base.AdapterError, "empty or.*incomplete"):
                    gate.pcm_fingerprint(pathlib.Path("source.mp4"))

    def test_audio_probe_malformed_metadata(self):
        for data in ("not JSON", '{"streams":null}', '{"streams":[{"index":-1}]}'):
            with self.subTest(data=data), patch.object(gate, "small_output", return_value=data):
                with self.assertRaisesRegex(gate.base.AdapterError, "invalid audio stream metadata"):
                    gate.audio_streams(pathlib.Path("source.mp4"))


class RealMediaTests(unittest.TestCase):
    def run_gate(self, video, analysis, **optional):
        with tempfile.TemporaryDirectory(prefix=".speech-test-", dir=PROJECT) as temporary:
            command = [sys.executable, "-B", str(PROJECT / "scripts/check_speech_evidence_provenance.py"), "--video", str(PROJECT / "data/test-videos" / video), "--metadata", str(PROJECT / "data/analyses/universal" / video.replace(".mp4", ".media.json")), "--analysis", str(PROJECT / "data/analyses/universal" / analysis), "--output", str(pathlib.Path(temporary) / "report.json")]
            for name, value in optional.items():
                command.extend(["--" + name, str(PROJECT / value)])
            result = subprocess.run(command, cwd=temporary, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report, json.loads((pathlib.Path(temporary) / "report.json").read_text()))
            return report

    def test_pak_fuad_source_wav_and_legacy_evidence(self):
        report = self.run_gate("mandala-original.mp4", "pak-fuad-universal-v02.canonical.json", audio="data/analyses/mandala-audio.wav", transcript="data/analyses/mandala-whisper.json", alignment="data/analyses/aligned-v2/aligned-timeline.json", review="data/analyses/transcript-review.json")
        self.assertEqual(report["audio"]["comparison_status"], "verified")
        self.assertEqual(report["audio"]["source_pcm"]["sha256"], "9735285baac2a110355a3d0c9b81f2fb697cbd9e8314920667fb1091bcb160d1")
        self.assertEqual(report["audio"]["source_pcm"], report["audio"]["existing_audio"]["pcm"])
        self.assertEqual(report["transcript"]["source_association_status"], "unverified")
        self.assertEqual(len(report["alignment"]["stale_or_unsafe_reference_fields"]), 3)
        self.assertFalse(report["transcript_review"]["corrected_text_present"])
        self.assertEqual(report["evidence_eligibility"]["status"], "ineligible")

    def test_showcase_missing_transcript_is_not_failure(self):
        report = self.run_gate("cinematic-7693770515172887829.mp4", "cinematic-universal-v02.canonical.json")
        self.assertEqual(report["evidence_eligibility"]["status"], "not_required")
        self.assertEqual(report["evidence_eligibility"]["blocking_reasons"], [])
        self.assertIsNone(report["transcript"]["path"])
        self.assertIsNone(report["alignment"]["path"])


if __name__ == "__main__":
    unittest.main()
