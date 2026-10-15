"""Offline Director remediation checks; no provider calls or real-content renders."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT/'scripts'))
import director_diagnostics_v01 as x
import adaptive_director_v03_fixtures as f
import benchmark_preview_v01 as preview


def setUpModule():
    global guard
    guard = patch('socket.socket.connect', side_effect=AssertionError('Offline only'))
    guard.start()


def tearDownModule(): guard.stop()


class CaptureTests(unittest.TestCase):
    def invoke(self, script, **kw): return x.capture([sys.executable, '-c', script], **kw)
    def test_success(self):
        raw, diag = self.invoke('print("hello")')
        self.assertEqual(raw, 'hello\n'); self.assertIsNone(diag['error_category'])
        self.assertEqual(diag['process_exit_code'], 0); self.assertTrue(diag['process_started'])
    def test_nonzero_upstream(self):
        raw, diag = self.invoke('import sys;print("HTTP 429 upstream quota",file=sys.stderr);sys.exit(3)')
        self.assertEqual(diag['error_category'], 'UPSTREAM_MODEL_FAILURE'); self.assertEqual(diag['process_exit_code'], 3)
        self.assertIn('429', diag['stderr_excerpt']); self.assertEqual(raw, '')
    def test_nonzero_transport(self):
        _, diag = self.invoke('import sys;print("fetch failed ECONNREFUSED",file=sys.stderr);sys.exit(1)')
        self.assertEqual(diag['error_category'], 'TRANSPORT_FAILURE')
    def test_missing_provider(self):
        _, diag = self.invoke('import sys;print("Unknown model",file=sys.stderr);sys.exit(1)')
        self.assertEqual(diag['error_category'], 'PROVIDER_CONFIGURATION_FAILURE')
    def test_empty(self):
        _, diag = self.invoke('pass'); self.assertEqual(diag['error_category'], 'EMPTY_RESPONSE')
    def test_stderr_secrets(self):
        _, diag = self.invoke('import sys;print("Authorization: Bearer abcdef",file=sys.stderr);print("sk-SYNTHETIC_123456789",file=sys.stderr);sys.exit(1)')
        self.assertNotIn('abcdef', diag['stderr_excerpt']); self.assertNotIn('SYNTHETIC', diag['stderr_excerpt'])
    def test_private_url(self): self.assertNotIn('password', x.sanitize('network https://u:password@host/error'))
    def test_secret_stdout_not_preserved(self):
        raw, diag = self.invoke('print("sk-SYNTHETIC_123456789")')
        self.assertEqual(raw, ''); self.assertEqual(diag['error_category'], 'INVOCATION_FAILURE')
    def test_stdout_limit(self):
        _, diag = self.invoke('print("a"*1000)', max_bytes=16)
        self.assertEqual(diag['resource_reason'], 'stdout_limit'); self.assertEqual(diag['stdout_bytes'], 16)
    def test_stderr_limit(self):
        _, diag = self.invoke('import sys;print("a"*1000,file=sys.stderr)', max_stderr=16)
        self.assertEqual(diag['resource_reason'], 'stderr_limit'); self.assertEqual(diag['stderr_bytes'], 16)
    def test_exact_output_limit(self):
        raw, diag = self.invoke('import sys;sys.stdout.write("a"*16)', max_bytes=16)
        self.assertEqual(raw, 'a'*16); self.assertIsNone(diag['error_category'])
    def test_spawn_failure(self):
        _, diag = x.capture(['/not/a/binary'])
        self.assertEqual(diag['error_category'], 'INVOCATION_FAILURE'); self.assertFalse(diag['process_started'])
    def test_timeout_kills_descendants(self):
        with tempfile.TemporaryDirectory(dir=PROJECT/'data') as tmp:
            pidpath = Path(tmp)/'pid'
            script = ('import subprocess,time;from pathlib import Path;'
                      'p=subprocess.Popen(["sleep","30"]);'
                      f'Path({str(pidpath)!r}).write_text(str(p.pid));time.sleep(30)')
            _, diag = self.invoke(script, timeout=.4)
            self.assertEqual(diag['error_category'], 'TIMEOUT'); self.assertEqual(diag['process_signal'], 9)
            pid = int(pidpath.read_text()); stat = Path(f'/proc/{pid}/stat')
            for _ in range(20):
                try: state = stat.read_text().split()[2]
                except FileNotFoundError: break
                if state == 'Z': break
                time.sleep(.02)
            else: self.fail('Descendant still active')
    def test_parent_exit_reaps(self):
        _, diag = self.invoke('import os;os.kill(os.getpid(),9)')
        self.assertEqual(diag['process_signal'], 9)
    def test_unknown_nonzero(self):
        _, diag = self.invoke('raise SystemExit(7)'); self.assertEqual(diag['error_category'], 'INVOCATION_FAILURE')
    def test_http_count_unknown(self):
        _, diag = self.invoke('print("ok")'); self.assertEqual(diag['actual_upstream_http_count'], 'UNKNOWN')
    def test_invalid_encoding(self):
        raw, diag = self.invoke('import sys;sys.stdout.buffer.write(bytes([255]))')
        self.assertEqual(raw, ''); self.assertEqual(diag['resource_reason'], 'encoding_or_credential_policy')


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT/'data'); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.out = self.root/'out'; self.packet = f.packet('present')
        self.plan = f.plan(self.packet); (self.root/x.d.REQUEST).write_text('{}')
        patcher = patch.object(x.d, 'load_prepared', return_value=(self.packet, 'OFFLINE MOCK', {'code_receipts': x.d.code_receipts()}))
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(x.d, 'recheck_inputs'); patcher.start(); self.addCleanup(patcher.stop)
    def run_raw(self, raw, category=None):
        try:
            value = json.loads(raw)
            if 'contract_version' in value:
                raw = json.dumps({'provider': x.PROVIDER, 'model': 'openclaw', 'transport': 'local',
                    'capability': 'model.run', 'outputs': [{'text': raw}]})
        except ValueError: pass
        with patch.object(x, 'capture', return_value=(raw, {'error_category': category, 'duration_sec': 1, 'response_presence': bool(raw)})) as call:
            result = x.run(self.root, self.out, live_approved=True)
        self.assertEqual(call.call_count, 1); return result
    def diagnostic(self): return json.loads((self.out/'invocation-diagnostic.v01.json').read_text())
    def test_success_preserves_raw_generation(self):
        raw = json.dumps({'provider': x.PROVIDER, 'model': 'openclaw', 'transport': 'local',
            'capability': 'model.run', 'outputs': [{'text': json.dumps(self.plan)}]})
        _, result = self.run_raw(raw)
        self.assertTrue(result['structural_validity']); self.assertEqual((self.out/'raw-response.v01.txt').read_text(), raw)
        receipt = x.d.av.read(self.out/x.d.RECEIPT)
        self.assertEqual(receipt['saved_response'], x.d.av.reference(self.out/'raw-response.v01.txt'))
        self.assertEqual(receipt['wrapper_invocations'], 1); self.assertFalse(receipt['render_approved'])
    def test_malformed_json(self):
        self.assertRaises(x.Failure, self.run_raw, '{broken')
        self.assertEqual(self.diagnostic()['error_category'], 'RESPONSE_EXTRACTION_FAILURE')
        self.assertFalse((self.out/x.d.RECEIPT).exists()); self.assertEqual((self.out/'raw-response.v01.txt').read_text(), '{broken')
    def test_unknown_envelope(self):
        self.assertRaises(x.Failure, self.run_raw, '{"unknown":1}')
        self.assertEqual(self.diagnostic()['parsing_status'], 'NOT_RUN')
    def test_schema_invalid(self):
        _, result = self.run_raw('{"contract_version":"0.3.0"}')
        self.assertFalse(result['structural_validity']); self.assertEqual(self.diagnostic()['error_category'], 'RESPONSE_SCHEMA_FAILURE')
        self.assertFalse((self.out/x.d.PLAN).exists()); self.assertTrue((self.out/'rejected-output.v03.json').exists())
    def test_grounding_invalid(self):
        self.plan['evidence_packet_sha256'] = '0'*64
        _, result = self.run_raw(json.dumps(self.plan)); self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(self.diagnostic()['error_category'], 'EVIDENCE_GROUNDING_FAILURE')
    def test_upstream_no_retry(self):
        self.assertRaises(x.Failure, self.run_raw, '', 'UPSTREAM_MODEL_FAILURE')
        self.assertEqual(self.diagnostic()['generation_receipt_status'], 'NOT_CREATED')
    def test_wrong_model_rejected(self):
        raw = json.dumps({'provider': x.PROVIDER, 'model': 'unauthorized', 'transport': 'local',
            'capability': 'model.run', 'outputs': [{'text': json.dumps(self.plan)}]})
        self.assertRaises(x.Failure, self.run_raw, raw)
        self.assertEqual(self.diagnostic()['error_category'], 'PROVIDER_CONFIGURATION_FAILURE')
        self.assertFalse((self.out/x.d.RECEIPT).exists())
    def test_preparation_before_invocation(self):
        with patch.object(x.d, 'load_prepared', side_effect=x.d.base.AdapterError('bad identity')), patch.object(x, 'capture') as call:
            self.assertRaises(x.Failure, x.run, self.root, self.out, live_approved=True)
        call.assert_not_called(); self.assertEqual(self.diagnostic()['error_category'], 'REQUEST_PREPARATION_FAILURE')
    def test_no_approval(self):
        with patch.object(x, 'capture') as call: self.assertRaises(x.d.base.AdapterError, x.run, self.root, self.out)
        call.assert_not_called()
    def test_existing_output(self):
        self.out.mkdir(); (self.out/'keep').write_text('intact')
        with patch.object(x, 'capture') as call: self.assertRaises(x.d.base.AdapterError, x.run, self.root, self.out, live_approved=True)
        call.assert_not_called(); self.assertEqual((self.out/'keep').read_text(), 'intact')
    def test_speech_is_planning_block_not_invocation(self):
        self.plan['variants'][0]['shots'][0]['source_start_sec'] = 1
        _, result = self.run_raw(json.dumps(self.plan)); self.assertTrue(result['structural_validity'])
        self.assertTrue(preview.speech_safety(self.plan, self.packet)); self.assertFalse(result['render_gate_passed'])
    def test_source_changed_after_response(self):
        with patch.object(x.d, 'recheck_inputs', side_effect=x.d.base.AdapterError('changed')):
            self.assertRaises(x.Failure, self.run_raw, json.dumps(self.plan))
        self.assertEqual(self.diagnostic()['generation_receipt_status'], 'NOT_CREATED')
    def test_command_existing_model_no_override(self):
        cmd, env = x.command('test'); self.assertNotIn('--model', cmd)
        self.assertIn('mandala-video-director', cmd); self.assertEqual(env['NODE_OPTIONS'], '--max-old-space-size=256')


class LedgerTests(unittest.TestCase):
    def setUp(self):
        RunTests.setUp(self); patcher = patch.object(x, 'ROOT', self.root); patcher.start(); self.addCleanup(patcher.stop)
        scope = {'maximum_director_invocations': 2, 'automatic_retries': 0, 'user_approved': True,
            'provider_alias': x.PROVIDER, 'model_alias': 'openclaw', 'source_sha256': self.packet['source']['sha256'], **x.FLAGS}
        x.d.shared.write_json(self.root/'inspection.json', {'diagnostic': {'process_exit_code': 0},
            'inventory': {'provider': x.PROVIDER, 'id': 'openclaw'}, 'inference_performed': False})
        scope['provider_inspection'] = x.d.av.reference(self.root/'inspection.json')
        x.d.shared.write_json(self.root/'live-scope.v01.json', scope)
    def test_exhausted(self):
        for n in (1, 2): (self.root/f'reservation.{n:02}.json').write_text('{}')
        with patch.object(x, 'run') as call: self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root)
        call.assert_not_called()
    def test_reserved_failure_consumed(self):
        with patch.object(x, 'run', side_effect=x.d.base.AdapterError('crash')) as call:
            self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root)
        self.assertEqual(call.call_count, 1); self.assertTrue((self.root/'reservation.01.json').exists())
        with patch.object(x, 'run') as call: self.assertRaises(OSError, x.live_attempt, self.root)
        call.assert_not_called()
    def test_second_requires_fix(self):
        (self.root/'reservation.01.json').write_text('{}'); (self.root/'call.01').mkdir()
        x.d.shared.write_json(self.root/'call.01/invocation-diagnostic.v01.json', {'generation_receipt_status': 'NOT_CREATED'})
        with patch.object(x, 'run') as call: self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root)
        call.assert_not_called()
    def test_success_prevents_second(self):
        (self.root/'reservation.01.json').write_text('{}'); (self.root/'call.01').mkdir()
        x.d.shared.write_json(self.root/'call.01/invocation-diagnostic.v01.json', {'generation_receipt_status': 'CREATED'})
        self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root, fix_record='anything')
    def test_preparation_failure_does_not_spend(self):
        with patch.object(x.d, 'load_prepared', side_effect=x.d.base.AdapterError('invalid')):
            self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root)
        self.assertEqual(list(self.root.glob('reservation.*.json')), [])
    def test_old_budget_untouched(self):
        p = PROJECT/'data/benchmarks/stage58/pak-fuad.live.v01/checkpoint.003.json'
        before = p.read_bytes()
        with patch.object(x, 'run', side_effect=x.d.base.AdapterError('mock')):
            self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root)
        self.assertEqual(p.read_bytes(), before); self.assertEqual(json.loads(before)['remaining_budget']['director_calls'], 0)
    def test_scope_cannot_raise_cap(self):
        p = self.root/'live-scope.v01.json'; scope = json.loads(p.read_text()); scope['maximum_director_invocations'] = 3
        p.write_text(json.dumps(scope))
        with patch.object(x, 'run') as call: self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root)
        call.assert_not_called()
    def test_wrong_provider_inventory(self):
        p = self.root/'inspection.json'; value = json.loads(p.read_text()); value['inventory']['provider'] = 'other'
        p.write_text(json.dumps(value))
        with patch.object(x, 'run') as call: self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root)
        call.assert_not_called()
    def test_unapplied_second_fix(self):
        code = x.d.av.reference(Path(x.__file__).resolve())
        x.d.shared.write_json(self.root/'reservation.01.json', {'diagnostic_code': code})
        (self.root/'call.01').mkdir(); p = self.root/'call.01/invocation-diagnostic.v01.json'
        x.d.shared.write_json(p, {'generation_receipt_status': 'NOT_CREATED', 'error_category': 'RESPONSE_EXTRACTION_FAILURE'})
        fix = self.root/'fix.json'; x.d.shared.write_json(fix, {'previous_diagnostic': x.d.av.reference(p),
            'previous_code': code, 'current_code': code, 'rationale': 'Unchanged code is not a fix'})
        with patch.object(x, 'run') as call: self.assertRaises(x.d.base.AdapterError, x.live_attempt, self.root, fix_record=fix)
        call.assert_not_called(); self.assertFalse((self.root/'reservation.02.json').exists())
    def test_cli_failure_nonzero(self):
        with patch.object(x, 'live_attempt', side_effect=x.d.base.AdapterError('failed')):
            self.assertEqual(x.main(['--prepared', str(self.root)]), 1)


if __name__ == '__main__': unittest.main()
