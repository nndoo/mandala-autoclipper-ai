"""Offline bounded invocation diagnostics. No provider/API/model requests."""
import json
import os
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import review_video_quality_v01 as r

class InvocationDiagnostics(unittest.TestCase):
    def run_command(self,code,**kw):return r.capture_inference([sys.executable,'-c',code],env=os.environ.copy(),timeout=2,**kw)
    def failed(self,code,**kw):
        with self.assertRaises(r.InferenceFailure) as context:self.run_command(code,**kw)
        return context.exception.diagnostic
    def test_valid_response(self):self.assertEqual(self.run_command('print("{}")').strip(),'{}')
    def test_stderr_does_not_pollute_json(self):self.assertEqual(self.run_command('import sys;print("warning",file=sys.stderr);print("{}")').strip(),'{}')
    def test_node_heap_failure_classification(self):self.assertEqual(self.failed('import sys;print("heap out of memory",file=sys.stderr);sys.exit(1)')['reason'],'node_heap_exhausted')
    def test_http_error_classification(self):self.assertEqual(self.failed('import sys;print("HTTP 400",file=sys.stderr);sys.exit(1)')['http_status'],400)
    def test_network_error_classification(self):self.assertEqual(self.failed('import sys;print("fetch failed",file=sys.stderr);sys.exit(1)')['reason'],'network_failure')
    def test_plugin_binding_classification(self):self.assertEqual(self.failed('import sys;print("QA media/prompt binding invalid",file=sys.stderr);sys.exit(1)')['reason'],'plugin_request_binding_failure')
    def test_exit_code_preserved(self):self.assertEqual(self.failed('raise SystemExit(7)')['process_exit_code'],7)
    def test_stderr_secret_never_preserved(self):
        diagnostic=self.failed('import sys;print("Bearer secret-test-value HTTP 403",file=sys.stderr);sys.exit(1)')
        self.assertNotIn('secret-test-value',json.dumps(diagnostic));self.assertNotIn('Bearer',json.dumps(diagnostic))
    def test_stdout_secret_rejected(self):self.assertEqual(self.failed('print("Bearer secret-test-value")')['reason'],'stdout_encoding_or_credential_policy')
    def test_stdout_limit(self):self.assertEqual(self.failed('print("x"*300)',max_bytes=64)['reason'],'stdout_limit_exceeded')
    def test_stderr_limit(self):self.assertEqual(self.failed('import sys;print("x"*300,file=sys.stderr)',max_stderr=64)['reason'],'stderr_limit_exceeded')
    def test_timeout(self):
        with self.assertRaises(r.InferenceFailure) as error:r.capture_inference([sys.executable,'-c','import time;time.sleep(2)'],env=os.environ.copy(),timeout=.05)
        self.assertEqual(error.exception.diagnostic['reason'],'invocation_timeout')
    def test_descendants_reaped(self):
        code='import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time;time.sleep(3)"]);print("{}")'
        with self.assertRaises(r.InferenceFailure) as error:r.capture_inference([sys.executable,'-c',code],env=os.environ.copy(),timeout=.1)
        self.assertEqual(error.exception.diagnostic['reason'],'invocation_timeout')
    def test_unclassified_error_does_not_preserve_path_or_payload(self):
        d=self.failed('import sys;print("private payload /private/file",file=sys.stderr);sys.exit(1)');self.assertEqual(d['reason'],'cli_exit_nonzero_unclassified');self.assertNotIn('private',json.dumps(d))

if __name__=='__main__':unittest.main()
