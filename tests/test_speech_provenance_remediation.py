"""Offline regressions for classification consistency and bounded metadata probing."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_adaptive_director_input_v03 as adapter_tests
import test_speech_evidence_provenance as speech_tests

adapter = adapter_tests.adapter
gate = speech_tests.gate


def setUpModule():
    global network_guard
    network_guard = patch("socket.socket.connect", side_effect=AssertionError("Offline tests forbid network"))
    network_guard.start()


def tearDownModule():
    network_guard.stop()


class SpeechConflictRemediationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = speech_tests.GateTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.duration = self.fixture.source["duration_sec"]

    def configure(self, profile, regions=None, *, examined=True):
        analysis = self.fixture.analysis
        analysis["content_profile"]["speech_presence"] = profile
        analysis["analysis_meta"]["audio_examined"] = examined
        template = analysis["segments"][0]
        if regions is None:
            regions = [(0, self.duration, ["music"])]
        analysis["segments"] = [
            {**template, "segment_id": f"region_{i}", "start_sec": start, "end_sec": end, "audio_layers": layers}
            for i, (start, end, layers) in enumerate(regions)
        ]
        self.fixture.save()

    def check(self, overall, regional, **optional):
        report = self.fixture.inspect(**optional)
        requirements = report["speech_requirements"]
        self.assertEqual(requirements["overall_requirement"], overall)
        self.assertEqual([r["requirement"] for r in requirements["regions"]], regional)
        self.assertEqual(requirements["basis"], "canonical_analysis_unverified")
        self.assertEqual(report["canonical_analysis"]["findings_status"], "unverified")
        for name in ("transcript", "alignment"):
            self.assertFalse(report[name]["eligible_for_attachment"])
        self.assertFalse(report["evidence_eligibility"]["transcript"])
        self.assertFalse(report["evidence_eligibility"]["speech_alignment"])
        return report

    def test_absent_profile_with_speech_is_explicit_conflict(self):
        self.configure("absent", [(0, self.duration, ["speech"])])
        report = self.check("required", ["required"])
        self.assertEqual(report["speech_requirements"]["classification_conflicts"], ["absent_profile_with_regional_speech"])
        self.assertIn("Speech marked absent but speech audio layer exists", report["warnings"])
        self.assertIn("speech_classification_conflict:absent_profile_with_regional_speech", report["evidence_eligibility"]["blocking_reasons"])

    def test_present_complete_music_requires_review(self):
        self.configure("present", [(0, 10, ["music"]), (10, self.duration, ["music"])])
        report = self.check("needs_review", ["not_required", "not_required"])
        self.assertEqual(report["evidence_eligibility"]["status"], "needs_review")
        self.assertEqual(report["speech_requirements"]["classification_conflicts"], ["present_profile_without_regional_speech"])
        self.assertIn("Speech marked present but complete known audio regions contain no speech", report["warnings"])
        self.assertIn("speech_classification_conflict:present_profile_without_regional_speech", report["evidence_eligibility"]["blocking_reasons"])

    def test_present_complete_speech_requires_speech(self):
        self.configure("present", [(0, self.duration, ["speech"])])
        report = self.check("required", ["required"])
        self.assertEqual(report["speech_requirements"]["classification_conflicts"], [])
        self.assertEqual(report["speech_requirements"]["temporal_coverage"], {"status": "complete", "uncovered_regions": []})

    def test_absent_complete_music_stays_not_required(self):
        self.configure("absent")
        report = self.check("not_required", ["not_required"], transcript=None, alignment=None)
        self.assertEqual(report["evidence_eligibility"]["status"], "not_required")
        self.assertEqual(report["evidence_eligibility"]["blocking_reasons"], [])

    def test_uncertain_music_preserves_review(self):
        self.configure("uncertain")
        self.check("needs_review", ["not_required"])

    def test_uncertain_speech_preserves_review_and_regional_requirement(self):
        self.configure("uncertain", [(0, self.duration, ["speech"])])
        report = self.check("needs_review", ["required"], transcript=None, alignment=None)
        self.assertIn("required_transcript_unavailable", report["evidence_eligibility"]["blocking_reasons"])

    def test_mixed_known_content_is_regional(self):
        self.configure("present", [(0, 10, ["music"]), (10, self.duration, ["speech", "music"])])
        self.check("required", ["not_required", "required"])

    def test_mixed_unknown_preserves_review_and_speech_requirements(self):
        self.configure("present", [(0, 5, ["music"]), (5, 10, ["speech"]), (10, self.duration, ["unknown"])])
        report = self.check("needs_review", ["not_required", "required", "needs_review"], transcript=None, alignment=None)
        self.assertIn("required_transcript_unavailable", report["evidence_eligibility"]["blocking_reasons"])

    def test_unknown_region_cannot_substantiate_reverse_conflict(self):
        self.configure("present", [(0, self.duration, ["unknown"])])
        report = self.check("needs_review", ["needs_review"])
        self.assertEqual(report["speech_requirements"]["classification_conflicts"], [])

    def test_empty_audio_layers_remain_unknown(self):
        self.configure("present", [(0, self.duration, [])])
        report = self.check("needs_review", ["needs_review"])
        self.assertEqual(report["speech_requirements"]["classification_conflicts"], [])

    def test_incomplete_music_cannot_prove_speech_absence(self):
        self.configure("absent", [(0, 10, ["music"])])
        report = self.check("needs_review", ["not_required"], transcript=None, alignment=None)
        self.assertEqual(report["speech_requirements"]["temporal_coverage"]["uncovered_regions"], [{"start_sec": 10, "end_sec": self.duration}])
        self.assertIn("Speech review required: incomplete segment temporal coverage", report["warnings"])
        self.assertIn("speech_temporal_coverage_incomplete", report["evidence_eligibility"]["blocking_reasons"])

    def test_incomplete_present_does_not_invent_reverse_conflict(self):
        self.configure("present", [(0, 10, ["music"])])
        report = self.check("needs_review", ["not_required"])
        self.assertEqual(report["speech_requirements"]["classification_conflicts"], [])

    def test_leading_and_interior_gaps_are_reported(self):
        self.configure("absent", [(2, 5, ["music"]), (7, self.duration, ["music"])])
        report = self.check("needs_review", ["not_required", "not_required"])
        self.assertEqual(report["speech_requirements"]["temporal_coverage"]["uncovered_regions"], [{"start_sec": 0, "end_sec": 2}, {"start_sec": 5, "end_sec": 7}])

    def test_unsorted_overlapping_intervals_use_union_coverage(self):
        self.configure("absent", [(10, self.duration, ["music"]), (0, 13, ["music"])])
        report = self.check("not_required", ["not_required", "not_required"], transcript=None, alignment=None)
        self.assertEqual(report["speech_requirements"]["temporal_coverage"]["status"], "complete")

    def test_overlap_cannot_hide_missing_coverage(self):
        self.configure("absent", [(0, 20, ["music"]), (0, 20, ["music"])])
        report = self.check("needs_review", ["not_required", "not_required"])
        self.assertEqual(report["speech_requirements"]["temporal_coverage"]["uncovered_regions"], [{"start_sec": 20, "end_sec": self.duration}])

    def test_unexamined_audio_does_not_prove_reverse_conflict(self):
        self.configure("present", examined=False)
        report = self.check("needs_review", ["not_required"])
        self.assertEqual(report["speech_requirements"]["classification_conflicts"], [])

    def test_missing_segments_report_full_uncovered_interval(self):
        self.configure("absent", [])
        report = self.check("needs_review", [])
        self.assertEqual(report["speech_requirements"]["temporal_coverage"]["uncovered_regions"], [{"start_sec": 0, "end_sec": self.duration}])

    def test_conflict_cannot_promote_claimed_verified_legacy_evidence(self):
        self.configure("present")
        self.fixture.transcript.update(eligible_for_attachment=True, text_verification_status="verified", timing_status="frame_verified")
        self.fixture.transcript["provenance"] = {"source_sha256": self.fixture.digest, "audio_pcm_sha256": self.fixture.pcm["sha256"], "generation_verified": True}
        self.fixture.save()
        report = self.check("needs_review", ["not_required"])
        for field in ("source_association_status", "generation_provenance_status", "text_verification_status", "timing_verification_status"):
            self.assertEqual(report["transcript"][field], "unverified")

    def test_successful_conflict_cli_is_not_attachment_approval(self):
        self.configure("present")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = gate.main(self.fixture.cli_args())
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["inspection_status"], "complete")
        self.assertEqual(report["evidence_eligibility"]["status"], "needs_review")
        self.assertFalse(report["evidence_eligibility"]["transcript"])
        self.assertFalse(report["evidence_eligibility"]["speech_alignment"])


class BoundedMetadataRemediationTests(unittest.TestCase):
    metadata = {"format": {"duration": "1.2345"}, "streams": [{"codec_type": "video", "width": 16, "height": 32, "avg_frame_rate": "30000/1001"}]}

    @contextlib.contextmanager
    def controlled_probe(self, program):
        """Run a safe Python child through the actual FFprobe bounded execution path."""
        real_popen = subprocess.Popen
        processes = []
        def spawn(command, **options):
            self.assertEqual(command[0], "ffprobe")
            self.assertEqual(options, {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL})
            process = real_popen([sys.executable, "-B", "-c", program], **options)
            processes.append(process)
            return process
        try:
            with patch.object(adapter.subprocess, "Popen", side_effect=spawn):
                yield processes
        finally:
            for process in processes:
                alive = process.poll() is None
                if alive:
                    process.kill()
                    process.wait()
                self.assertFalse(alive, "Helper left a running subprocess")
                self.assertTrue(process.stdout.closed, "Helper left stdout open")
                with self.assertRaises(ChildProcessError):
                    os.waitpid(process.pid, os.WNOHANG)

    def test_normal_metadata_json_and_rounding(self):
        with self.controlled_probe("print(" + repr(json.dumps(self.metadata)) + ")"):
            result = adapter.probe_video(Path("source.mp4"))
        self.assertEqual(result, {"duration_sec": 1.235, "width": 16, "height": 32, "fps": 29.97})

    def test_invalid_metadata_json_is_sanitized(self):
        with self.controlled_probe("print('private-media-content')"):
            with self.assertRaisesRegex(adapter.AdapterError, "invalid video metadata") as error:
                adapter.probe_video(Path("source.mp4"))
        self.assertNotIn("private-media-content", str(error.exception))

    def test_invalid_utf8_is_sanitized(self):
        with self.controlled_probe("import os;os.write(1,b'\\xff')"):
            with self.assertRaisesRegex(adapter.AdapterError, "invalid UTF-8"):
                adapter.probe_video(Path("source.mp4"))

    def test_nonzero_exit_is_sanitized_and_reaped(self):
        with self.controlled_probe("import sys;sys.stderr.write('private-secret');sys.exit(3)") as processes:
            with self.assertRaisesRegex(adapter.AdapterError, "FFprobe.*failed") as error:
                adapter.probe_video(Path("source.mp4"))
        self.assertEqual(processes[0].returncode, 3)
        self.assertNotIn("private-secret", str(error.exception))

    def test_metadata_timeout_kills_and_reaps(self):
        with self.controlled_probe("import time;time.sleep(5)") as processes, patch.object(adapter, "PROBE_TIMEOUT_SEC", 0.1):
            with self.assertRaisesRegex(adapter.AdapterError, "FFprobe.*timeout"):
                adapter.probe_video(Path("source.mp4"))
        self.assertLess(processes[0].returncode, 0)

    def test_timeout_after_stdout_eof_kills_and_reaps(self):
        with self.controlled_probe("import os,time;os.close(1);time.sleep(5)") as processes, patch.object(adapter, "PROBE_TIMEOUT_SEC", 0.1):
            with self.assertRaisesRegex(adapter.AdapterError, "timeout"):
                adapter.probe_video(Path("source.mp4"))
        self.assertLess(processes[0].returncode, 0)

    def test_oversized_stdout_kills_and_reaps(self):
        program = "import os,time;os.write(1,b'x'*(1048576+65536));time.sleep(5)"
        with self.controlled_probe(program) as processes:
            with self.assertRaisesRegex(adapter.AdapterError, "FFprobe.*resource limit"):
                adapter.probe_video(Path("source.mp4"))
        self.assertLess(processes[0].returncode, 0)

    def test_large_stderr_is_discarded_without_deadlock(self):
        program = "import os;os.write(2,b'private-secret'*700000);print(" + repr(json.dumps(self.metadata)) + ")"
        with self.controlled_probe(program) as processes:
            result = adapter.probe_video(Path("source.mp4"))
        self.assertEqual(processes[0].returncode, 0)
        self.assertEqual(result["width"], 16)

    def test_missing_ffprobe_is_identifiable(self):
        with patch.object(adapter.subprocess, "Popen", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(adapter.AdapterError, "FFprobe.*unavailable"):
                adapter.probe_video(Path("source.mp4"))

    def test_probe_uses_shared_bounded_helper_and_limits(self):
        def emit(command, consume, **limits):
            encoded = json.dumps(self.metadata).encode()
            consume(encoded)
            return len(encoded)
        with patch.object(adapter, "bounded_run", side_effect=emit) as helper:
            adapter.probe_video(Path("source.mp4"))
        self.assertIs(gate.bounded_run, adapter.bounded_run)
        self.assertIs(gate.small_output, adapter.small_output)
        self.assertEqual(helper.call_args.kwargs, {"max_bytes": 1024 * 1024, "timeout": 30})

    def test_probe_failure_cli_preserves_inputs_and_publishes_nothing(self):
        real_probe = adapter.probe_video
        fixture = adapter_tests.AdapterTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        paths = [fixture.video, fixture.metadata_path, fixture.analysis_path]
        before = {p: p.read_bytes() for p in paths}
        args = ["--video", str(fixture.video), "--metadata", str(fixture.metadata_path), "--analysis", str(fixture.analysis_path), "--output", str(fixture.output)]
        error = io.StringIO()
        with patch.object(adapter, "probe_video", real_probe), self.controlled_probe("import sys;sys.stderr.write('private-secret');sys.exit(3)"), contextlib.redirect_stderr(error):
            code = adapter.main(args)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(error.getvalue())["status"], "BLOCKED")
        self.assertNotIn("private-secret", error.getvalue())
        self.assertFalse(fixture.output.exists())
        self.assertEqual(list(fixture.root.rglob(".adaptive-input-*.tmp")), [])
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_existing_output_is_preserved_before_metadata_probe(self):
        fixture = adapter_tests.AdapterTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.output.parent.mkdir()
        fixture.output.write_bytes(b"existing output")
        paths = [fixture.video, fixture.metadata_path, fixture.analysis_path, fixture.output]
        before = {p: p.read_bytes() for p in paths}
        with patch.object(adapter.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(adapter.AdapterError, "already exists"):
                fixture.build()
        popen.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_atomic_writer_failure_removes_temporary_resource(self):
        fixture = adapter_tests.AdapterTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        with patch.object(adapter.os, "link", side_effect=OSError("controlled link failure")):
            with self.assertRaises(OSError):
                adapter.write_exclusive(fixture.output, "complete JSON")
        self.assertFalse(fixture.output.exists())
        self.assertEqual(list(fixture.root.rglob(".adaptive-input-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
