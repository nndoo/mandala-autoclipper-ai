"""Offline adapter contract, provenance, path, and output safety checks."""

import contextlib
import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import build_adaptive_director_input_v03 as adapter
from validate_universal_analysis_v02 import sample_analysis


def setUpModule():
    global network_guard
    network_guard = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden in offline tests"))
    network_guard.start()


def tearDownModule():
    network_guard.stop()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mandala-adapter-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src/schemas").mkdir(parents=True)
        for name in ("universal-video-analysis.v0.2.schema.json", "adaptive-director-input.v0.3.schema.json"):
            shutil.copyfile(PROJECT / "src/schemas" / name, self.root / "src/schemas" / name)
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"synthetic media bytes: FFprobe mocked")
        digest = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.source = {
            "video_id": "local-sha256-" + digest[:32],
            "duration_sec": 26.533, "width": 1080, "height": 1920, "fps": 30.0,
        }
        self.metadata = {
            "source": copy.deepcopy(self.source),
            "verification": {"method": "ffprobe_and_sha256", "file_name": self.video.name, "sha256": digest},
        }
        self.analysis = sample_analysis()
        self.analysis["source"] = copy.deepcopy(self.source)
        self.analysis["segments"][0]["end_sec"] = self.source["duration_sec"]
        self.metadata_path = self.root / "metadata.json"
        self.analysis_path = self.root / "canonical.json"
        self.output = self.root / "outputs/director-input.json"
        self.save_inputs()
        root_guard = patch.object(adapter, "ROOT", self.root)
        root_guard.start()
        self.addCleanup(root_guard.stop)
        probe_guard = patch.object(adapter, "probe_video", return_value={k: v for k, v in self.source.items() if k != "video_id"})
        self.probe = probe_guard.start()
        self.addCleanup(probe_guard.stop)

    def save_inputs(self):
        self.metadata_path.write_text(json.dumps(self.metadata), encoding="utf-8")
        self.analysis_path.write_text(json.dumps(self.analysis), encoding="utf-8")

    def build(self, **overrides):
        paths = dict(video=self.video, metadata=self.metadata_path, analysis=self.analysis_path, output=self.output)
        paths.update(overrides)
        return adapter.build_director_input(**paths)

    def blocked(self, message, **overrides):
        with self.assertRaisesRegex(adapter.AdapterError, message):
            self.build(**overrides)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.rglob(".adaptive-input-*.tmp")), [])

    def test_arbitrary_content_has_valid_safe_output(self):
        self.analysis["content_profile"]["content_tags"] = ["unseen-format", "humor", "demonstration"]
        self.analysis["content_profile"]["speech_presence"] = "uncertain"
        self.save_inputs()
        report = self.build(video=Path("source.mp4"), metadata=Path("metadata.json"), analysis=Path("canonical.json"), output=Path("outputs/director-input.json"))
        payload = json.loads(self.output.read_text())
        schema = json.loads((self.root / "src/schemas/adaptive-director-input.v0.3.schema.json").read_text())
        Draft202012Validator(schema).validate(payload)
        self.assertEqual(payload["source"], self.source)
        self.assertEqual(payload["evidence"]["universal_analysis"], {"path": "canonical.json", "timing_precision": "approximate"})
        for key in ("transcript", "speech_alignment", "music_rhythm", "visual_timing"):
            self.assertIsNone(payload["evidence"][key])
        self.assertEqual(payload["renderer_capabilities"], {"verification_status": "unknown", "supported_operations": []})
        self.assertEqual(payload["editorial_policy"], {
            "goal": "Develop content-adaptive editing proposals from available evidence",
            "max_variants": 2, "allow_fewer_variants": True, "preserve_complete_utterances": True,
            "allow_unverified_claims": False, "render_approved": False, "publish_approved": False,
        })
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertEqual(report["warnings"], ["Schema validation does not verify audiovisual facts or frame-accurate timing"])

    def test_missing_source(self):
        self.video.unlink()
        self.blocked("Source MP4.*missing")

    def test_missing_metadata(self):
        self.metadata_path.unlink()
        self.blocked("Metadata sidecar.*missing")

    def test_missing_analysis(self):
        self.analysis_path.unlink()
        self.blocked("Canonical analysis.*missing")

    def test_sha256_mismatch(self):
        self.metadata["verification"]["sha256"] = "0" * 64
        self.save_inputs()
        self.blocked("SHA-256 mismatch")
        self.probe.assert_not_called()

    def test_filename_mismatch(self):
        self.metadata["verification"]["file_name"] = "other.mp4"
        self.save_inputs()
        self.blocked("filename mismatch")

    def test_sidecar_source_id_mismatch(self):
        self.metadata["source"]["video_id"] = "unrelated-source"
        self.save_inputs()
        self.blocked("source ID")

    def test_canonical_source_id_mismatch(self):
        self.analysis["source"]["video_id"] = "unrelated-source"
        self.save_inputs()
        self.blocked("Canonical analysis source metadata mismatch")

    def test_sidecar_duration_mismatch(self):
        self.metadata["source"]["duration_sec"] = 27
        self.save_inputs()
        self.blocked("differs from FFprobe")

    def test_sidecar_resolution_mismatch(self):
        self.metadata["source"]["width"] = 720
        self.save_inputs()
        self.blocked("differs from FFprobe")

    def test_sidecar_fps_mismatch(self):
        self.metadata["source"]["fps"] = 60
        self.save_inputs()
        self.blocked("differs from FFprobe")

    def test_canonical_metadata_mismatch(self):
        for field, value in (("duration_sec", 27), ("width", 720), ("height", 1080), ("fps", 60)):
            with self.subTest(field=field):
                self.analysis["source"] = {**self.source, field: value}
                self.save_inputs()
                self.blocked("Canonical analysis source metadata mismatch")

    def test_invalid_analysis_structure_does_not_echo_input(self):
        self.analysis["segments"] = "sensitive-test-value-do-not-log"
        self.save_inputs()
        self.blocked(r"schema violation at segments \(type\)")

    def test_invalid_analysis_timestamp(self):
        self.analysis["segments"][0]["end_sec"] = 100
        self.save_inputs()
        self.blocked("Timestamp exceeds source duration")

    def test_duplicate_segment_ids(self):
        self.analysis["segments"].append(copy.deepcopy(self.analysis["segments"][0]))
        self.save_inputs()
        self.blocked("Duplicate segment IDs")

    def test_unapproved_analysis_status(self):
        self.analysis["analysis_status"] = "APPROVED"
        self.save_inputs()
        self.blocked("schema violation at analysis_status")

    def test_review_status_and_warnings_preserved(self):
        self.analysis["analysis_status"] = "NEEDS_REVIEW"
        self.analysis["analysis_meta"]["video_examined"] = False
        self.save_inputs()
        report = self.build()
        self.assertIn("Video has not been directly examined", report["warnings"])

    def test_model_precision_claim_is_not_promoted(self):
        self.analysis["analysis_meta"]["timing_precision"] = "frame_verified"
        self.save_inputs()
        report = self.build()
        payload = json.loads(self.output.read_text())
        self.assertEqual(payload["evidence"]["universal_analysis"]["timing_precision"], "approximate")
        self.assertIn("No independent timing evidence attached; universal artifact precision remains approximate", report["warnings"])

    def test_existing_output_cannot_be_overwritten(self):
        self.output.parent.mkdir()
        self.output.write_text("existing content")
        with self.assertRaisesRegex(adapter.AdapterError, "already exists"):
            self.build()
        self.assertEqual(self.output.read_text(), "existing content")

    def test_output_outside_root(self):
        self.blocked("escapes project root", output=self.root.parent / "escape.json")

    def test_input_outside_root(self):
        with tempfile.TemporaryDirectory() as external:
            p = Path(external) / "external.mp4"
            p.write_bytes(b"external source")
            self.blocked("escapes project root", video=p)

    def test_input_symlink_escape(self):
        with tempfile.TemporaryDirectory() as external:
            for label, original in (("video", self.video), ("metadata", self.metadata_path), ("analysis", self.analysis_path)):
                with self.subTest(artifact=label):
                    target = Path(external) / original.name
                    shutil.copyfile(original, target)
                    alias = self.root / (label + "-alias")
                    alias.symlink_to(target)
                    self.blocked("escapes project root", **{label: alias})

    def test_output_parent_symlink_escape(self):
        with tempfile.TemporaryDirectory() as external:
            (self.root / "outside").symlink_to(external, target_is_directory=True)
            self.blocked("escapes project root", output=self.root / "outside/new.json")
            self.assertFalse((Path(external) / "new.json").exists())

    def test_dangling_output_symlink_is_rejected(self):
        self.output.parent.mkdir()
        target = self.root / "target.json"
        self.output.symlink_to(target)
        with self.assertRaisesRegex(adapter.AdapterError, "already exists"):
            self.build()
        self.assertTrue(self.output.is_symlink())
        self.assertFalse(target.exists())

    def test_relative_traversal_is_rejected(self):
        self.blocked("escapes project root", output=Path("../escape.json"))

    def test_blocking_error_has_nonzero_cli_status(self):
        self.metadata["verification"]["sha256"] = "0" * 64
        self.save_inputs()
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = adapter.main(self.cli_args())
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(error.getvalue())["status"], "BLOCKED")
        self.assertFalse(self.output.exists())

    def cli_args(self):
        return ["--video", str(self.video), "--metadata", str(self.metadata_path), "--analysis", str(self.analysis_path), "--output", str(self.output)]

    def test_approval_flags_cannot_bypass_policy(self):
        for flag in ("--render-approved", "--publish-approved", "--allow-unverified-claims", "--render", "--out"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    adapter.main(self.cli_args() + [flag, "true"])
                self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_invalid_json_and_nonfinite_numbers(self):
        for content in ('{', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":1,"x":2}', '[]'):
            with self.subTest(content=content):
                self.analysis_path.write_text(content)
                self.blocked("invalid JSON|expected a JSON object")

    def test_metadata_boolean_dimension_is_rejected(self):
        self.metadata["source"]["width"] = True
        self.save_inputs()
        self.blocked("Metadata source.*schema violation")

    def test_atomic_write_failure_leaves_no_partial_output(self):
        with patch.object(adapter.os, "fsync", side_effect=OSError("injected write failure")):
            with self.assertRaises(OSError):
                self.build()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_atomic_publish_race_preserves_other_writer(self):
        def competing_writer(_temporary, output):
            output.write_text("competing writer")
            raise FileExistsError()
        with patch.object(adapter.os, "link", side_effect=competing_writer):
            with self.assertRaisesRegex(adapter.AdapterError, "already exists"):
                self.build()
        self.assertEqual(self.output.read_text(), "competing writer")
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    def test_output_schema_checked_before_writing(self):
        path = self.root / "src/schemas/adaptive-director-input.v0.3.schema.json"
        schema = json.loads(path.read_text())
        schema["properties"]["contract_version"]["const"] = "different-version"
        path.write_text(json.dumps(schema))
        self.blocked("Adaptive Director Input V0.3.*schema violation")

    def test_invalid_project_schema_fails_cleanly(self):
        path = self.root / "src/schemas/adaptive-director-input.v0.3.schema.json"
        path.write_text('{"type":"invalid-json-schema-type"}')
        self.blocked("Schema: invalid JSON Schema")

    def test_analysis_cannot_inject_approval(self):
        self.analysis["render_approved"] = True
        self.save_inputs()
        self.blocked("Universal analysis.*schema violation")


class ProbeTests(unittest.TestCase):
    def test_probe_rounding_and_network_protocol_restriction(self):
        data = {"format": {"duration": "1.2345"}, "streams": [{"codec_type": "video", "width": 16, "height": 32, "avg_frame_rate": "30000/1001"}]}
        def output(command, consume, **options):
            encoded = json.dumps(data).encode()
            consume(encoded)
            return len(encoded)
        with patch.object(adapter, "bounded_run", side_effect=output) as run:
            result = adapter.probe_video(Path("source.mp4"))
        self.assertEqual(result, {"duration_sec": 1.235, "width": 16, "height": 32, "fps": 29.97})
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertEqual(run.call_args.kwargs["max_bytes"], 1024 * 1024)

    def test_probe_failures_are_clear(self):
        for message in ("ffprobe is unavailable", "Media subprocess timeout exceeded", "Media subprocess failed; raw diagnostics suppressed"):
            with self.subTest(failure=message), patch.object(adapter, "small_output", side_effect=adapter.AdapterError(message)):
                with self.assertRaisesRegex(adapter.AdapterError, "FFprobe"):
                    adapter.probe_video(Path("source.mp4"))

    def test_invalid_probe_metadata(self):
        base = {"format": {"duration": "1"}, "streams": [{"codec_type": "video", "width": 16, "height": 32, "avg_frame_rate": "30/1"}]}
        cases = ["not JSON", "[]", json.dumps({"streams": []}), json.dumps({"streams": ["invalid stream"]})]
        for field, value in (("avg_frame_rate", "0/0"), ("width", 0), ("height", True)):
            data = copy.deepcopy(base)
            data["streams"][0][field] = value
            cases.append(json.dumps(data))
        data = copy.deepcopy(base)
        data["format"]["duration"] = "nan"
        cases.append(json.dumps(data))
        for content in cases:
            with self.subTest(content=content), patch.object(adapter, "small_output", return_value=content):
                with self.assertRaisesRegex(adapter.AdapterError, "invalid video metadata"):
                    adapter.probe_video(Path("source.mp4"))


class RealMediaTests(unittest.TestCase):
    def check_real_media(self, video_name, analysis_name, speech_presence):
        video = PROJECT / "data/test-videos" / video_name
        metadata = PROJECT / "data/analyses/universal" / video_name.replace(".mp4", ".media.json")
        analysis = PROJECT / "data/analyses/universal" / analysis_name
        original_hashes = {}
        for path in (video, metadata, analysis):
            with path.open("rb") as file:
                original_hashes[path] = hashlib.file_digest(file, "sha256").hexdigest()
        with tempfile.TemporaryDirectory(prefix=".adapter-test-", dir=PROJECT) as temporary:
            output = Path(temporary) / "input.json"
            result = subprocess.run(
                [sys.executable, "-B", str(PROJECT / "scripts/build_adaptive_director_input_v03.py"),
                 "--video", str(video), "--metadata", str(metadata), "--analysis", str(analysis), "--output", str(output)],
                cwd=temporary, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            payload = json.loads(output.read_text())
            schema = json.loads((PROJECT / "src/schemas/adaptive-director-input.v0.3.schema.json").read_text())
            Draft202012Validator(schema).validate(payload)
            self.assertEqual(report["source_sha256"], original_hashes[video])
            self.assertEqual(payload["source"], json.loads(metadata.read_text())["source"])
            self.assertEqual(payload["source"], json.loads(analysis.read_text())["source"])
            self.assertEqual(json.loads(analysis.read_text())["content_profile"]["speech_presence"], speech_presence)
            self.assertFalse(Path(payload["evidence"]["universal_analysis"]["path"]).is_absolute())
            for key in ("transcript", "speech_alignment", "music_rhythm", "visual_timing"):
                self.assertIsNone(payload["evidence"][key])
            self.assertFalse(payload["editorial_policy"]["render_approved"])
            self.assertFalse(payload["editorial_policy"]["publish_approved"])
        for path, digest in original_hashes.items():
            with path.open("rb") as file:
                self.assertEqual(hashlib.file_digest(file, "sha256").hexdigest(), digest)

    def test_pak_fuad_original(self):
        self.check_real_media("mandala-original.mp4", "pak-fuad-universal-v02.canonical.json", "present")

    def test_showcase_without_transcript(self):
        self.check_real_media("cinematic-7693770515172887829.mp4", "cinematic-universal-v02.canonical.json", "absent")


if __name__ == "__main__":
    unittest.main()
