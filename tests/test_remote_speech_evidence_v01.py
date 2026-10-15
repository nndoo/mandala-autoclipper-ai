"""Remote adapter tests use mock HTTP only; no service calls or real credentials."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_remote_speech_evidence_v01 as remote
import test_speech_evidence_generation_v01 as fixtures


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GenerationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.output = self.root / "remote/new.v01"
        project = Path(__file__).resolve().parents[1]
        self.config_path = self.root / "remote-config.json"
        self.config_path.write_bytes((project / remote.DEFAULT_CONFIG).read_bytes())
        self.config = json.loads(self.config_path.read_text())
        self.payload = {"text": "Synthetic interview only", "x_groq": {"id": "test-request"}}
        self.calls = []
        mock = patch.object(remote, "remote_call", side_effect=self.fake_call)
        mock.start()
        self.addCleanup(mock.stop)

    def fake_call(self, config, upload, temporary):
        self.calls.append((copy.deepcopy(config), upload))
        return {"status": "complete", "http_status": 200, "elapsed_sec": 0.1,
                "credential_source": "synthetic-test-only", "payload": copy.deepcopy(self.payload)}

    def generate(self, **kwargs):
        fixture = self.fixture.fixture
        return remote.generate(fixture.video, fixture.paths["metadata"], fixture.paths["analysis"], self.output,
                               config=self.config_path, **kwargs)

    def artifact(self, name):
        return json.loads((self.output / name).read_text())

    def test_json_text_only_no_invented_timestamps(self):
        report = self.generate()
        self.assertEqual(report["generation_status"], "complete")
        self.assertEqual(report["timing_verification_status"], "unavailable")
        self.assertEqual(self.artifact(remote.local.DRAFT)["segments"], [])
        self.assertEqual(self.artifact(remote.local.DRAFT)["recognized_regions"][0]["text"], self.payload["text"])
        self.assertIsNone(self.artifact(remote.local.REVIEW)["windows"][0]["start_sec"])
        self.assertEqual(remote.validate_bundle(self.output)["integrity_status"], "checked")

    def test_verbose_provider_timing_source_offset(self):
        self.fixture.mixed()
        self.payload.update(language="id", segments=[copy.deepcopy(self.fixture.segment)], words=self.fixture.segment["words"])
        report = self.generate()
        segment = self.artifact(remote.local.DRAFT)["segments"][0]
        self.assertEqual(segment["start_sec"], 4.45)
        self.assertEqual(segment["words"][1]["end_sec"], 5.45)
        self.assertEqual(report["timing_verification_status"], "unverified")
        remote.validate_bundle(self.output)

    def test_timestamp_invalid_remains_ineligible(self):
        self.payload["segments"] = [{**self.fixture.segment, "start": -3, "end": 90}]
        report = self.generate()
        self.assertEqual(report["quality_assessment"]["structure_status"], "failed")
        self.assertFalse(report["evidence_eligibility"]["transcript"])

    def test_music_does_not_call_remote(self):
        self.fixture.fixture.no_speech()
        self.assertEqual(self.generate()["generation_status"], "not_required")
        self.assertFalse(self.calls)
        remote.validate_bundle(self.output)

    def test_uncertain_does_not_call_remote(self):
        self.fixture.change_analysis(lambda a: a["content_profile"].update(speech_presence="uncertain"))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def test_conflict_does_not_call_remote(self):
        self.fixture.change_analysis(lambda a: a["content_profile"].update(speech_presence="absent"))
        self.assertEqual(self.generate()["generation_status"], "needs_review")
        self.assertFalse(self.calls)

    def test_empty_text_flagged(self):
        self.payload["text"] = ""
        flags = self.generate()["quality_assessment"]["flags"]
        self.assertIn("empty_remote_transcript", {f["code"] for f in flags})

    def test_unicode_and_repetition_flagged(self):
        self.payload["text"] = "repeat repeat repeat repeat \ufffd"
        codes = {f["code"] for f in self.generate()["quality_assessment"]["flags"]}
        self.assertIn("invalid_or_suspicious_encoding", codes)
        self.assertIn("repeated_or_suspicious_text", codes)

    def test_reported_model_mismatch_flagged(self):
        self.payload["model"] = "different-model"
        codes = {f["code"] for f in self.generate()["quality_assessment"]["flags"]}
        self.assertIn("reported_model_mismatch", codes)

    def test_attachment_and_review_safety(self):
        report = self.generate()
        self.assertEqual(report["generation_provenance_status"], "recorded")
        self.assertEqual(report["text_verification_status"], "unverified")
        self.assertEqual(report["human_review_status"], "pending")
        self.assertFalse(report["evidence_eligibility"]["transcript"])
        self.assertFalse(report["evidence_eligibility"]["speech_alignment"])
        self.assertEqual(report["director_attachments"], {"transcript": None, "speech_alignment": None})
        manifest = self.artifact(remote.local.MANIFEST)
        self.assertIsNone(manifest["remote_model_artifact_sha256"])
        self.assertIsNone(manifest["remote_runtime_versions"])

    def test_no_retry_on_http_failure(self):
        with patch.object(remote, "remote_call", return_value={"status": "blocked", "reason": "remote_http_error", "http_status": 400}) as call:
            report = self.generate()
        self.assertEqual(call.call_count, 1)
        self.assertEqual(report["generation_status"], "remote_asr_failed")
        self.assertFalse((self.output / remote.local.DRAFT).exists())
        remote.validate_bundle(self.output)

    def test_partial_success_is_preserved_if_next_region_fails(self):
        self.fixture.mixed()
        analysis = self.fixture.fixture.analysis
        tail = analysis["segments"].pop()
        analysis["segments"].extend([{**tail, "segment_id": "music-gap", "end_sec": 15},
                                     {**tail, "segment_id": "speech-tail", "start_sec": 15, "audio_layers": ["speech"]}])
        self.fixture.fixture.save()
        responses = [{"status": "complete", "http_status": 200, "elapsed_sec": 0.1, "credential_source": "mock", "payload": self.payload},
                     {"status": "blocked", "reason": "remote_http_error", "http_status": 503}]
        with patch.object(remote, "remote_call", side_effect=responses) as call:
            report = self.generate()
        self.assertEqual(call.call_count, 2)
        self.assertEqual(report["generation_status"], "remote_asr_failed")
        self.assertEqual(self.artifact(remote.local.RAW)["regions"][0]["payload"]["text"], self.payload["text"])
        self.assertFalse((self.output/remote.local.DRAFT).exists())
        remote.validate_bundle(self.output)

    def test_upload_and_temp_cleanup(self):
        self.generate()
        self.assertFalse(self.calls[0][1].exists())
        self.assertFalse(self.calls[0][1].parent.exists())

    def test_overwrite_rejected(self):
        self.generate()
        with self.assertRaisesRegex(remote.base.AdapterError, "already exists"):
            self.generate()
        self.assertEqual(len(self.calls), 1)

    def test_http_endpoint_rejected(self):
        self.config["endpoint"] = self.config["endpoint"].replace("https:", "http:")
        self.config_path.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(remote.base.AdapterError, "Invalid remote ASR configuration"):
            self.generate()
        self.assertFalse(self.calls)

    def test_url_secret_and_query_rejected(self):
        self.config["endpoint"] += "?api_key=not-a-real-key"
        self.config_path.write_text(json.dumps(self.config))
        with self.assertRaises(remote.base.AdapterError):
            self.generate()

    def test_response_limit_config_rejected(self):
        self.config["max_response_bytes"] = 100 * 1048576
        self.config_path.write_text(json.dumps(self.config))
        with self.assertRaises(remote.base.AdapterError):
            self.generate()

    def test_upload_limit_prevents_request(self):
        self.config["max_upload_bytes"] = 1024
        self.config_path.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(remote.base.AdapterError, "upload resource limit"):
            self.generate()
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())

    def test_config_unknown_fields_not_recorded(self):
        self.config["unwanted_field"] = "ignored"
        self.config_path.write_text(json.dumps(self.config))
        self.generate()
        self.assertNotIn("unwanted_field", self.artifact(remote.local.MANIFEST)["remote_request"])

    def test_offline_validation_does_not_read_credentials_or_call_service(self):
        self.generate()
        with patch.object(remote, "credentials", side_effect=AssertionError("No credentials for validation")), \
                patch.object(remote, "remote_call", side_effect=AssertionError("No remote request for validation")):
            remote.validate_bundle(self.output)

    def test_raw_tamper_rejected(self):
        self.generate()
        (self.output / remote.local.RAW).write_text("{}")
        with self.assertRaisesRegex(remote.base.AdapterError, "artifact integrity"):
            remote.validate_bundle(self.output)

    def test_false_text_verification_rejected(self):
        self.generate()
        report = self.artifact(remote.local.REPORT)
        report["text_verification_status"] = "verified"
        (self.output / remote.local.REPORT).write_text(json.dumps(report))
        with self.assertRaisesRegex(remote.base.AdapterError, "false verification"):
            remote.validate_bundle(self.output)

    def test_cli_default_remote_and_validate_dispatch(self):
        fixture = self.fixture.fixture
        args = ["generate", "--remote-config", str(self.config_path), "--video", str(fixture.video),
                "--metadata", str(fixture.paths["metadata"]), "--analysis", str(fixture.paths["analysis"]), "--output-dir", str(self.output)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(remote.local.main(args), 0)
            self.assertEqual(remote.local.main(["validate", "--bundle", str(self.output)]), 0)


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.upload = Path(self.temporary.name) / "upload.wav"
        self.upload.write_bytes(b"synthetic WAV")
        project = Path(__file__).resolve().parents[1]
        self.config = json.loads((project / remote.DEFAULT_CONFIG).read_text())
        self.response = MagicMock()
        self.response.__enter__.return_value = self.response
        self.response.status = 200
        self.response.read.return_value = b'{"text":"synthetic result"}'

    def request(self):
        with patch.object(remote, "credentials", return_value=("test-secret-only", "mock")), \
                patch.object(remote.urllib.request, "build_opener") as factory:
            factory.return_value.open.return_value = self.response
            self.opener = factory.return_value
            return remote.request_transcription(self.config, self.upload)

    def test_multipart_model_json_and_no_prompt(self):
        result = self.request()
        self.assertEqual(result["status"], "complete")
        request = self.opener.open.call_args.args[0]
        self.assertIn(b"groq/whisper-large-v3", request.data)
        self.assertIn(b'name="file"', request.data)
        self.assertNotIn(b'name="prompt"', request.data)
        self.assertNotIn(b"test-secret-only", request.data)
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 90)

    def test_verbose_requests_word_granularity(self):
        self.config["response_format"] = "verbose_json"
        self.request()
        self.assertIn(b'timestamp_granularities[]', self.opener.open.call_args.args[0].data)

    def test_http_error_body_suppressed(self):
        error = urllib.error.HTTPError(self.config["endpoint"], 401, "private", {}, io.BytesIO(b"test-secret-only"))
        with patch.object(remote, "credentials", return_value=("test-secret-only", "mock")), \
                patch.object(remote.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = error
            result = remote.request_transcription(self.config, self.upload)
        self.assertEqual(result, {"status": "blocked", "reason": "remote_http_error", "http_status": 401})

    def test_timeout_suppressed(self):
        with patch.object(remote, "credentials", return_value=("test-secret-only", "mock")), \
                patch.object(remote.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = TimeoutError()
            self.assertEqual(remote.request_transcription(self.config, self.upload)["reason"], "remote_transport_error")

    def test_response_byte_cap(self):
        self.config["max_response_bytes"] = 1024
        self.response.read.return_value = b"x" * 1025
        result = self.request()
        self.assertEqual(result, {"status": "blocked", "reason": "remote_response_resource_limit"})
        self.assertNotIn("payload", result)

    def test_success_response_cannot_persist_echoed_key(self):
        self.response.read.return_value = b'{"text":"test-secret-only"}'
        result = self.request()
        self.assertEqual(result, {"status": "blocked", "reason": "remote_response_sensitive_content"})
        self.assertNotIn("test-secret-only", json.dumps(result))

    def test_duplicate_or_nonfinite_response_rejected(self):
        for data in (b'{"text":"one","text":"two"}', b'{"text":"one","x":NaN}'):
            self.response.read.return_value = data
            self.assertEqual(self.request()["reason"], "malformed_remote_response")

    def test_redirect_disabled(self):
        self.assertIsNone(remote.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid"))

    def test_job_does_not_contain_credentials_and_bounded_execution(self):
        def run(command, consume, **limits):
            self.assertEqual(limits, {"max_bytes": self.config["max_response_bytes"] + 65536, "timeout": 90})
            job = json.loads(Path(command[-1]).read_text())
            self.assertEqual(set(job), {"config", "upload"})
            self.assertNotIn("apiKey", json.dumps(job))
            consume(b'{"status":"blocked","reason":"mock"}')
        with patch.object(remote.base, "bounded_run", side_effect=run):
            self.assertEqual(remote.remote_call(self.config, self.upload, Path(self.temporary.name))["reason"], "mock")

    def test_private_env_and_permissions(self):
        root = Path(self.temporary.name)
        private = root / ".env.asr"
        private.write_text(self.config["api_key_env"] + "=test-secret-only\n")
        private.chmod(0o600)
        with patch.object(remote.base, "ROOT", root), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(remote.credentials(self.config), ("test-secret-only", "project_private_env"))
            private.chmod(0o644)
            with self.assertRaisesRegex(remote.base.AdapterError, "private"):
                remote.credentials(self.config)


if __name__ == "__main__":
    unittest.main()
