"""Offline Stage 5B tests. Synthetic ASR receipts are never real transcription."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
from dataclasses import make_dataclass
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_speech_evidence_v01 as pipeline
import speech_asr_worker as worker
import test_speech_evidence_provenance as gate_fixtures


class GenerationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing synthetic source/canonical fixture and media mocks.
        self.fixture = gate_fixtures.GateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.output = self.root / "speech/new.v01"
        self.data = b"\x01\x00" * int(self.fixture.source["duration_sec"] * 16000)
        self.pcm = {"sha256": hashlib.sha256(self.data).hexdigest(), "byte_count": len(self.data),
                    "sample_count": len(self.data) // 2, "duration_sec": len(self.data) / 32000}
        self.fixture.fingerprint.return_value = self.pcm
        self.calls = []
        self.model = {"identifier": "synthetic-test-only", "resolved_path": "/mock/local-model",
                      "files": [{"name": n, "sha256": "b" * 64, "byte_count": 100} for n in
                                ("model.bin", "config.json", "tokenizer.json", "vocabulary.json")]}
        self.runtime = {"faster-whisper": "mock", "ctranslate2": "mock", "numpy": "mock", "python": "mock"}
        self.segment = {"id": 0, "start": 0.2, "end": 1.2, "text": " Synthetic speech", "tokens": [1, 2],
                        "avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.0,
                        "words": [{"start": 0.2, "end": 0.6, "word": " Synthetic", "probability": 0.9},
                                  {"start": 0.6, "end": 1.2, "word": " speech", "probability": 0.8}]}
        self.segments = [self.segment]
        for target, name, method in ((pipeline, "capture_pcm", self.capture), (pipeline, "worker_call", self.fake_worker)):
            mock = patch.object(target, name, side_effect=method)
            mock.start()
            self.addCleanup(mock.stop)
        network = patch("socket.socket.connect", side_effect=AssertionError("Offline tests forbid network"))
        network.start()
        self.addCleanup(network.stop)

    def capture(self, video, stream, path, limits):
        path.write_bytes(self.data)
        return self.pcm.copy()

    def fake_worker(self, job, python, temporary):
        self.calls.append(copy.deepcopy(job))
        result = {"status": "complete", "action": job["action"], "model": self.model, "runtime": self.runtime}
        if job["action"] == "transcribe":
            result["elapsed_sec"] = 0.1
            result["regions"] = [{"region_id": r["region_id"], "pcm_sha256": r["pcm_sha256"],
                                  "sample_count": r["sample_end"] - r["sample_start"],
                                  "info": {"language": "id", "language_probability": 0.9, "duration": (r["sample_end"]-r["sample_start"])/16000},
                                  "segments": copy.deepcopy(self.segments)} for r in job["regions"]]
        return result

    def generate(self, **kwargs):
        return pipeline.generate(self.fixture.video, self.fixture.paths["metadata"], self.fixture.paths["analysis"], self.output, **kwargs)

    def artifact(self, name):
        return json.loads((self.output / name).read_text())

    def flags(self):
        return {f["code"] for f in self.generate()["quality_assessment"]["flags"]}

    def blocked(self, expression, **kwargs):
        with self.assertRaisesRegex(pipeline.base.AdapterError, expression):
            self.generate(**kwargs)
        self.assertFalse(self.output.exists())

    def change_analysis(self, change):
        change(self.fixture.analysis)
        self.fixture.save()

    def test_valid_generation_and_integrity(self):
        result = self.generate()
        self.assertEqual(result["generation_status"], "complete")
        self.assertEqual(pipeline.validate_bundle(self.output)["integrity_status"], "checked")
        self.assertEqual(len(self.calls), 2)

    def test_source_hash_mismatch(self):
        self.fixture.metadata["verification"]["sha256"] = "0"*64
        self.fixture.save()
        self.blocked("SHA-256 mismatch")

    def test_source_properties_mismatch(self):
        self.fixture.metadata["source"]["fps"] = 29
        self.fixture.save()
        self.blocked("differs from FFprobe")

    def test_source_id_mismatch(self):
        self.fixture.metadata["source"]["video_id"] = "wrong"
        self.fixture.save()
        self.blocked("source ID")

    def test_missing_video(self):
        self.fixture.video.unlink()
        self.blocked("required file is missing")

    def test_missing_metadata(self):
        self.fixture.paths["metadata"].unlink()
        self.blocked("required file is missing")

    def test_invalid_canonical_schema(self):
        self.change_analysis(lambda a: a.pop("segments"))
        self.blocked("schema violation")

    def test_invalid_canonical_timing(self):
        self.change_analysis(lambda a: a["segments"][0].update(end_sec=100))
        self.blocked("semantic/timing")

    def test_canonical_source_mismatch(self):
        self.change_analysis(lambda a: a["source"].update(video_id="other"))
        self.blocked("source metadata mismatch")

    def test_audio_fingerprint_match(self):
        self.assertEqual(self.generate(expected_pcm_sha256=self.pcm["sha256"])["audio_integrity_status"], "verified")

    def test_audio_fingerprint_mismatch(self):
        self.fixture.fingerprint.return_value = {**self.pcm, "sha256": "c"*64}
        self.blocked("Audio fingerprint mismatch")

    def test_expected_fingerprint_mismatch(self):
        self.blocked("Expected audio fingerprint mismatch", expected_pcm_sha256="c"*64)

    def test_music_optional(self):
        self.fixture.no_speech()
        result = self.generate()
        self.assertEqual(result["generation_status"], "not_required")
        self.assertEqual(result["evidence_eligibility"]["status"], "not_required")
        self.assertFalse(self.calls)
        self.assertFalse((self.output/pipeline.DRAFT).exists())
        pipeline.validate_bundle(self.output)

    def test_uncertain_cannot_bypass(self):
        self.change_analysis(lambda a: a["content_profile"].update(speech_presence="uncertain"))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def test_absent_with_speech_conflict(self):
        self.change_analysis(lambda a: a["content_profile"].update(speech_presence="absent"))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def test_present_without_regional_speech(self):
        self.change_analysis(lambda a: a["segments"][0].update(audio_layers=["music"]))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def test_incomplete_coverage(self):
        self.change_analysis(lambda a: a["segments"][0].update(start_sec=2))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def test_unknown_audio(self):
        self.change_analysis(lambda a: a["segments"][0].update(audio_layers=["unknown"]))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def test_audio_not_examined(self):
        self.change_analysis(lambda a: a["analysis_meta"].update(audio_examined=False))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def mixed(self):
        a = self.fixture.analysis
        segment = copy.deepcopy(a["segments"][0])
        first = {**segment, "segment_id": "music-before", "start_sec": 0, "end_sec": 5, "audio_layers": ["music"]}
        speech = {**segment, "segment_id": "speech-middle", "start_sec": 5, "end_sec": 9, "audio_layers": ["speech", "music"]}
        last = {**segment, "segment_id": "music-after", "start_sec": 9, "end_sec": a["source"]["duration_sec"], "audio_layers": ["music"]}
        a["segments"] = [first, speech, last]
        self.fixture.save()

    def test_mixed_regional_selection(self):
        self.mixed()
        self.generate()
        regions = self.artifact(pipeline.MANIFEST)["processing_regions"]
        self.assertEqual([(r["offset_sec"], r["processing_end_sec"]) for r in regions], [(4.25, 9.75)])

    def test_source_relative_words_and_segments(self):
        self.mixed()
        self.generate()
        segment = self.artifact(pipeline.DRAFT)["segments"][0]
        self.assertEqual(segment["start_sec"], 4.45)
        self.assertEqual(segment["words"][1]["end_sec"], 5.45)
        self.assertEqual(self.artifact(pipeline.RAW)["regions"][0]["segments"][0], self.segment)

    def test_context_music_hallucination_flag(self):
        self.mixed()
        self.segment.update(start=0.1, end=0.5, words=[])
        self.assertIn("speech_outside_candidate_possible_music_hallucination", self.flags())

    def test_negative_segment_timestamp(self):
        self.segment["start"] = -1
        self.assertIn("invalid_segment_timestamps", self.flags())

    def test_timestamp_exceeds_source(self):
        self.segment["end"] = 99
        self.assertIn("invalid_segment_timestamps", self.flags())

    def test_non_numeric_timestamp(self):
        self.segment["start"] = "invalid"
        self.assertIn("invalid_segment_timestamps", self.flags())

    def test_segment_order_and_overlap(self):
        self.segments.append(copy.deepcopy(self.segment))
        self.assertIn("segment_order_or_overlap", self.flags())

    def test_word_order(self):
        self.segment["words"].reverse()
        self.assertIn("invalid_word_timestamps_or_order", self.flags())

    def test_word_outside_segment(self):
        self.segment["words"][0]["end"] = 5
        self.assertIn("invalid_word_timestamps_or_order", self.flags())

    def test_large_gap(self):
        self.segment.update(start=5, end=6, words=[])
        self.assertIn("large_speech_gap", self.flags())

    def test_incomplete_utterance(self):
        self.segment["start"] = 0
        self.assertIn("possibly_incomplete_utterance", self.flags())

    def test_empty_asr_output(self):
        self.segments.clear()
        self.assertIn("missing_transcript_region:region-0001", self.flags())

    def test_empty_segment_text(self):
        self.segment["text"] = " "
        self.assertIn("missing_or_empty_text", self.flags())

    def test_repeated_text(self):
        self.segment["text"] = "repeat repeat repeat repeat"
        self.assertIn("repeated_or_suspicious_text", self.flags())

    def test_invalid_encoding(self):
        self.segment["text"] = "bad\ufffd\ud800"
        self.assertIn("invalid_or_suspicious_encoding", self.flags())

    def test_low_word_confidence(self):
        self.segment["words"][0]["probability"] = 0.1
        self.assertIn("word_probability_low_or_unavailable", self.flags())

    def test_silent_hallucination_confidence(self):
        self.segment["no_speech_prob"] = 0.95
        self.assertIn("suspicious_confidence:no_speech_prob", self.flags())

    def test_missing_model_records_blocker(self):
        with patch.object(pipeline, "worker_call", return_value={"status": "blocked", "reason": "BLOCKED_MODEL_NOT_AVAILABLE"}):
            result = self.generate()
        self.assertEqual(result["generation_status"], "BLOCKED_MODEL_NOT_AVAILABLE")
        self.assertFalse((self.output/pipeline.RAW).exists())
        self.assertEqual(result["generation_provenance_status"], "unavailable")
        pipeline.validate_bundle(self.output)

    def test_asr_failure_never_creates_transcript(self):
        original = self.fake_worker
        def fail(job, *args):
            return original(job, *args) if job["action"] == "preflight" else {"status": "blocked", "reason": "asr_execution_failed"}
        with patch.object(pipeline, "worker_call", side_effect=fail):
            self.assertEqual(self.generate()["generation_status"], "asr_execution_failed")
        self.assertFalse((self.output/pipeline.DRAFT).exists())

    def test_model_change_blocked(self):
        original = self.fake_worker
        def changed(job, *args):
            result = copy.deepcopy(original(job, *args))
            if job["action"] == "transcribe":
                result["model"]["identifier"] = "changed"
            return result
        with patch.object(pipeline, "worker_call", side_effect=changed):
            self.blocked("Model/runtime changed")

    def test_input_changed_during_execution(self):
        original = self.fake_worker
        def changed(job, *args):
            result = original(job, *args)
            if job["action"] == "transcribe":
                self.fixture.paths["analysis"].write_text("{}")
            return result
        with patch.object(pipeline, "worker_call", side_effect=changed):
            self.blocked("Inputs changed during execution")

    def test_raw_hash_and_noncyclic_manifest(self):
        self.generate()
        manifest = self.artifact(pipeline.MANIFEST)
        self.assertEqual(set(manifest["artifacts"]), pipeline.LEAVES)
        for name, record in manifest["artifacts"].items():
            self.assertEqual(record["sha256"], pipeline.gate.sha256_file(self.output/name))

    def test_leaf_tamper_rejected(self):
        self.generate()
        (self.output/pipeline.DRAFT).write_text("{}")
        with self.assertRaisesRegex(pipeline.base.AdapterError, "Artifact integrity mismatch"):
            pipeline.validate_bundle(self.output)

    def test_manifest_tamper_rejected(self):
        self.generate()
        (self.output/pipeline.MANIFEST).write_text("{}")
        with self.assertRaises(pipeline.base.AdapterError):
            pipeline.validate_bundle(self.output)

    def test_missing_manifest(self):
        self.generate()
        (self.output/pipeline.MANIFEST).unlink()
        with self.assertRaises(pipeline.base.AdapterError):
            pipeline.validate_bundle(self.output)

    def test_false_verification_report_rejected(self):
        self.generate()
        report = self.artifact(pipeline.REPORT)
        report["text_verification_status"] = "verified"
        (self.output/pipeline.REPORT).write_text(json.dumps(report))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "false verification"):
            pipeline.validate_bundle(self.output)

    def test_attachments_disabled_and_reviews_pending(self):
        report = self.generate()
        self.assertFalse(report["evidence_eligibility"]["transcript"])
        self.assertFalse(report["evidence_eligibility"]["speech_alignment"])
        self.assertEqual(report["director_attachments"], {"transcript": None, "speech_alignment": None})
        self.assertEqual(report["text_verification_status"], "unverified")
        self.assertEqual(report["timing_verification_status"], "unverified")
        self.assertIsNone(self.artifact(pipeline.REVIEW)["windows"][0]["reviewer_identity"])

    def submission(self):
        review = self.artifact(pipeline.REVIEW)
        window = review["windows"][0]
        window.update(review_status="reviewed", corrected_transcription="Human correction", reviewer_identity="reviewer-test",
                      review_method="listened to source", verified_at="2026-01-01T00:00:00+00:00")
        path = self.root / "submission.json"
        path.write_text(json.dumps(review))
        return path

    def test_separate_review_acceptance_preserves_raw(self):
        self.generate()
        before = {p.name: pipeline.gate.sha256_file(p) for p in self.output.iterdir()}
        result = pipeline.accept_review(self.output, self.submission(), self.root/"reviewed.v01.json", "reviewer-test")
        self.assertEqual(result["attestation_status"], "human_supplied_not_independently_verified")
        self.assertFalse(result["evidence_eligibility"]["transcript"])
        self.assertEqual(before, {p.name: pipeline.gate.sha256_file(p) for p in self.output.iterdir()})

    def test_blank_review_stays_pending(self):
        self.generate()
        with self.assertRaisesRegex(pipeline.base.AdapterError, "human review claim"):
            pipeline.accept_review(self.output, self.output/pipeline.REVIEW, self.root/"reviewed.json", "reviewer-test")

    def test_approval_identity_mismatch(self):
        self.generate()
        with self.assertRaisesRegex(pipeline.base.AdapterError, "human review claim"):
            pipeline.accept_review(self.output, self.submission(), self.root/"reviewed.json", "different")

    def test_review_timestamp_changes_rejected(self):
        self.generate()
        path = self.submission()
        data = json.loads(path.read_text())
        data["windows"][0]["end_sec"] += 1
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "original text/timing"):
            pipeline.accept_review(self.output, path, self.root/"reviewed.json", "reviewer-test")

    def test_overwrite_protection(self):
        self.generate()
        before = (self.output/pipeline.RAW).read_bytes()
        with self.assertRaisesRegex(pipeline.base.AdapterError, "already exists"):
            self.generate()
        self.assertEqual(before, (self.output/pipeline.RAW).read_bytes())

    def test_path_traversal(self):
        self.output = self.root/"speech/../escaped"
        self.blocked("Unsafe")

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root/"escape").symlink_to(outside, target_is_directory=True)
            self.output = self.root/"escape/bundle"
            self.blocked("inside project")

    def test_existing_symlink_bundle(self):
        (self.root/"existing").mkdir()
        self.output = self.root/"link"
        self.output.symlink_to(self.root/"existing", target_is_directory=True)
        with self.assertRaisesRegex(pipeline.base.AdapterError, "Unsafe"):
            self.generate()
        self.assertEqual(list((self.root/"existing").iterdir()), [])

    def test_temporary_pcm_cleanup(self):
        self.generate()
        self.assertFalse(Path(self.calls[-1]["regions"][0]["pcm_path"]).exists())
        self.assertFalse(any(p.suffix in (".tmp", ".pcm") for p in self.output.iterdir()))

    def test_publication_failure_cleans_own_files(self):
        with patch.object(pipeline.gate, "inspect_provenance", side_effect=pipeline.base.AdapterError("synthetic failure")):
            self.blocked("synthetic failure")

    def test_resource_settings_rejected(self):
        with self.assertRaises(pipeline.base.AdapterError):
            pipeline.limits_config(threads=99)
        with self.assertRaises(pipeline.base.AdapterError):
            pipeline.limits_config(memory=1)
        with self.assertRaises(pipeline.base.AdapterError):
            pipeline.limits_config(timeout=float("inf"))

    def refresh_manifest_hash(self):
        report = self.artifact(pipeline.REPORT)
        report["manifest_sha256"] = pipeline.gate.sha256_file(self.output/pipeline.MANIFEST)
        (self.output/pipeline.REPORT).write_text(json.dumps(report))

    def mutate_manifest(self, change):
        manifest = self.artifact(pipeline.MANIFEST)
        change(manifest)
        (self.output/pipeline.MANIFEST).write_text(json.dumps(manifest))
        self.refresh_manifest_hash()

    def test_malformed_model_provenance_despite_updated_manifest_hash(self):
        self.generate()
        self.mutate_manifest(lambda m: m.update(model={}))
        with self.assertRaises(pipeline.base.AdapterError):
            pipeline.validate_bundle(self.output)

    def test_missing_artifact_provenance(self):
        self.generate()
        self.mutate_manifest(lambda m: m["artifacts"].pop(pipeline.RAW))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "Missing or unexpected provenance"):
            pipeline.validate_bundle(self.output)

    def test_artifact_path_traversal_in_manifest(self):
        self.generate()
        self.mutate_manifest(lambda m: m["artifacts"][pipeline.RAW].update(path="../raw.json"))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "Malformed artifact"):
            pipeline.validate_bundle(self.output)

    def test_region_offset_tamper_despite_updated_hash(self):
        self.generate()
        self.mutate_manifest(lambda m: m["processing_regions"][0].update(offset_sec=1))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "Region PCM/offset"):
            pipeline.validate_bundle(self.output)

    def test_source_audio_provenance_tamper(self):
        self.generate()
        self.mutate_manifest(lambda m: m["audio"]["source_pcm"].update(sha256="f"*64))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "Audio provenance"):
            pipeline.validate_bundle(self.output)

    def test_unbounded_decode_limit_in_manifest_rejected(self):
        self.generate()
        self.mutate_manifest(lambda m: m["limits"].update(decode_timeout_sec=999999))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "resource limit provenance"):
            pipeline.validate_bundle(self.output)

    def test_internal_symlink_artifact_rejected(self):
        self.generate()
        path = self.output/pipeline.RAW
        backup = self.root/"same-raw.json"
        backup.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(backup)
        with self.assertRaisesRegex(pipeline.base.AdapterError, "symlink"):
            pipeline.validate_bundle(self.output)

    def test_malformed_asr_receipt_does_not_publish(self):
        with patch.object(pipeline, "worker_call", return_value={"status": "complete", "action": "preflight"}):
            self.blocked("malformed ASR generation provenance")

    def test_region_pcm_receipt_mismatch(self):
        original = self.fake_worker
        def mismatch(job, *args):
            result = original(job, *args)
            if job["action"] == "transcribe":
                result["regions"][0]["pcm_sha256"] = "e"*64
            return result
        with patch.object(pipeline, "worker_call", side_effect=mismatch):
            self.blocked("ASR region PCM mismatch")

    def test_language_change_and_unexpected_language(self):
        self.mixed()
        # Two separated candidate regions with different detected languages.
        a = self.fixture.analysis
        tail = a["segments"].pop()
        a["segments"].extend([{**tail, "segment_id": "music-gap", "end_sec": 15},
                              {**tail, "segment_id": "speech-tail", "start_sec": 15, "audio_layers": ["speech"]}])
        self.fixture.save()
        original = self.fake_worker
        def changed(job, *args):
            result = original(job, *args)
            if job["action"] == "transcribe":
                result["regions"][1]["info"]["language"] = "en"
            return result
        with patch.object(pipeline, "worker_call", side_effect=changed):
            codes = self.flags()
        self.assertIn("language_change", codes)
        self.assertIn("unexpected_language", codes)

    def test_future_review_timestamp_rejected(self):
        self.generate()
        path = self.submission()
        data = json.loads(path.read_text())
        data["windows"][0]["verified_at"] = "2999-01-01T00:00:00+00:00"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "review timestamp"):
            pipeline.accept_review(self.output, path, self.root/"reviewed.json", "reviewer-test")

    def test_review_wrong_transcript_hash(self):
        self.generate()
        path = self.submission()
        data = json.loads(path.read_text())
        data["transcript_sha256"] = "0"*64
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(pipeline.base.AdapterError, "binding mismatch"):
            pipeline.accept_review(self.output, path, self.root/"reviewed.json", "reviewer-test")

    def test_failed_decode_cleans_temp(self):
        seen = []
        def fail(video, stream, path, limits):
            path.write_bytes(b"partial")
            seen.append(path)
            raise pipeline.base.AdapterError("decode limit")
        with patch.object(pipeline, "capture_pcm", side_effect=fail):
            self.blocked("decode limit")
        self.assertFalse(seen[0].exists())

    def test_invalid_context(self):
        self.blocked("Context", context=-1)

    def test_missing_audio(self):
        with patch.object(pipeline.gate, "audio_streams", return_value=[]):
            result = self.generate()
            self.assertEqual(result["generation_status"], "source_audio_stream_unavailable")
            self.assertFalse(self.calls)


class WorkerBoundaryTests(unittest.TestCase):
    def test_worker_transcription_preserves_raw_dataclasses_and_parameters(self):
        # Exercise the real worker orchestration with an explicitly synthetic ASR engine.
        Segment = make_dataclass("Segment", [("id", int), ("start", float), ("end", float), ("text", str), ("tokens", list), ("words", list)])
        Options = make_dataclass("Options", [("word_timestamps", bool)])
        segment = Segment(1, 0.0, 0.1, "synthetic only", [1, 2], [])
        info = types.SimpleNamespace(language="id", language_probability=0.9, duration=0.1, duration_after_vad=0.1,
                                     all_language_probs=[("id", 0.9)], transcription_options=Options(True))
        engine = MagicMock()
        engine.transcribe.return_value = (iter([segment]), info)
        constructor = MagicMock(return_value=engine)
        model = {"identifier": "mock", "resolved_path": "/mock", "files": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"region.pcm"
            path.write_bytes(b"\x01\x00"*1600)
            job = {"action": "transcribe", "model": "/mock", "limits": pipeline.limits_config(),
                   "decoding_options": {"word_timestamps": True, "language": "id"},
                   "regions": [{"region_id": "r", "pcm_path": str(path), "pcm_sha256": pipeline.gate.sha256_file(path)}]}
            with patch.object(worker, "offline_limits"), patch.object(worker, "local_model", return_value=model), \
                    patch.object(worker.importlib.metadata, "version", return_value="synthetic"), \
                    patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=constructor), "numpy": MagicMock()}):
                result = worker.execute(job)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["regions"][0]["segments"][0]["tokens"], [1, 2])
        self.assertEqual(result["regions"][0]["sample_count"], 1600)
        self.assertEqual(engine.transcribe.call_args.kwargs, job["decoding_options"])
        self.assertEqual(constructor.call_args.kwargs, {"device": "cpu", "compute_type": "int8", "cpu_threads": 4,
                                                       "num_workers": 1, "local_files_only": True})

    def test_nonfinite_and_bool_timestamps(self):
        source = {"video_id": "fixture", "file_name": "fixture.mp4"}
        region = {"region_id": "region", "offset_sec": 0, "processing_end_sec": 3, "candidates": [{"start_sec": 0, "end_sec": 3}]}
        for bad in (float("nan"), float("inf"), True, None):
            draft = {"segments": [{"segment_id": "s", "region_id": "region", "start_sec": bad,
                                   "end_sec": 1, "text": "text", "words": []}]}
            codes = {f["code"] for f in pipeline.assess(draft, [region], 3, "id")["flags"]}
            self.assertIn("invalid_segment_timestamps", codes)

    def test_malformed_worker_stdout(self):
        def output(command, consume, **kwargs):
            consume(b'{"status":"complete","status":"blocked"}')
        with tempfile.TemporaryDirectory() as tmp, patch.object(pipeline.base, "bounded_run", side_effect=output):
            result = pipeline.worker_call({"action": "preflight", "limits": pipeline.limits_config()}, sys.executable, Path(tmp))
        self.assertEqual(result["reason"], "malformed_worker_result")

    def test_capture_pcm_byte_and_timeout_limits(self):
        def output(command, consume, **kwargs):
            self.assertEqual(kwargs, {"max_bytes": 2048, "timeout": 60})
            self.assertIn("file", command)
            consume(b"\x00\x00")
            return 2
        with tempfile.TemporaryDirectory() as tmp, patch.object(pipeline.base, "bounded_run", side_effect=output):
            result = pipeline.capture_pcm(Path("fixture.mp4"), {"index": 0}, Path(tmp)/"audio.pcm", pipeline.limits_config(pcm_bytes=2048))
        self.assertEqual(result["sample_count"], 1)

    def test_timeout_kills_and_reaps(self):
        with self.assertRaisesRegex(pipeline.base.AdapterError, "timeout"):
            pipeline.base.bounded_run([sys.executable, "-B", "-c", "import time; time.sleep(2)"], lambda _: None, max_bytes=100, timeout=0.05)

    def test_stdout_resource_limit(self):
        with self.assertRaisesRegex(pipeline.base.AdapterError, "resource limit"):
            pipeline.base.bounded_run([sys.executable, "-B", "-c", "print('x'*10000)"], lambda _: None, max_bytes=100, timeout=2)

    def test_stderr_discarded(self):
        chunks = []
        count = pipeline.base.bounded_run([sys.executable, "-B", "-c", "import sys; sys.stderr.write('x'*1000000); print('ok')"], chunks.append, max_bytes=100, timeout=2)
        self.assertEqual(count, 3)
        self.assertEqual(b"".join(chunks), b"ok\n")

    def test_worker_nonzero_exit(self):
        with self.assertRaisesRegex(pipeline.base.AdapterError, "failed"):
            pipeline.base.bounded_run([sys.executable, "-B", "-c", "raise SystemExit(9)"], lambda _: None, max_bytes=100, timeout=2)

    def test_worker_resource_limits_and_offline_guard(self):
        import socket
        import os
        with patch.object(worker.resource, "setrlimit") as limits, patch.dict(os.environ), patch.object(socket.socket, "connect"), patch.object(socket, "create_connection"):
            worker.offline_limits({"limits": pipeline.limits_config()})
            self.assertEqual(limits.call_count, 2)
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            with self.assertRaisesRegex(worker.WorkerBlocked, "network_forbidden"):
                socket.create_connection(("example.invalid", 443))

    def test_worker_invalid_memory_limit(self):
        with self.assertRaisesRegex(worker.WorkerBlocked, "invalid_resource_limits"):
            worker.offline_limits({"limits": {**pipeline.limits_config(), "memory_mib": 0}})

    def test_real_worker_missing_prerequisites_offline(self):
        # Local runtime is optional after the user's approved remote replacement.
        # Still run a real bounded worker: absent dependencies/model must block, never download.
        root = Path(__file__).resolve().parents[1]
        executable = root/".venv-asr/bin/python"
        if not executable.is_file():
            executable = Path(sys.executable)
        with tempfile.TemporaryDirectory() as tmp:
            result = pipeline.worker_call({"action": "preflight", "model": str(Path(tmp)/"absent-model"),
                                           "limits": pipeline.limits_config()}, executable, Path(tmp))
        self.assertEqual(result["status"], "blocked")
        self.assertIn(result["reason"], ("BLOCKED_MODEL_NOT_AVAILABLE", "runtime_dependencies_unavailable"))
        if result["reason"] == "BLOCKED_MODEL_NOT_AVAILABLE":
            self.assertIn("faster-whisper", result["runtime"])

    def test_worker_timeout_is_structured_blocker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(pipeline.base, "bounded_run", side_effect=pipeline.base.AdapterError("timeout")):
            result = pipeline.worker_call({"action": "preflight", "limits": pipeline.limits_config()}, sys.executable, Path(tmp))
            self.assertEqual(result["status"], "blocked")

    def test_worker_memory_exhaustion_is_structured_blocker(self):
        with patch.object(worker, "execute", side_effect=MemoryError), tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"job.json"
            path.write_text("{}")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(worker.main(["--job", str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue()), {"status": "blocked", "reason": "resource_limit"})


if __name__ == "__main__":
    unittest.main()
