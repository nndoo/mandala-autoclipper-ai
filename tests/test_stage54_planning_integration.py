"""Atomic orchestration, independent CLI gates and subprocess resource tests."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'scripts'))
import run_adaptive_director_v03 as run
import adaptive_director_evidence_v03 as intake
import validate_adaptive_director_plan_v03 as validator
import adaptive_director_v03_fixtures as f


def setUpModule():
    global guard
    guard=patch('socket.socket.connect',side_effect=AssertionError('Offline integration cannot call provider'))
    guard.start()
def tearDownModule():guard.stop()


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'data/analyses',prefix='stage54-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.out=self.root/'output';self.packet=f.packet('present');self.plan=f.plan(self.packet)
        self.response=self.root/'response.json';self.response.write_text(json.dumps(self.plan))
        self.prompt=run.make_prompt(self.packet)
        p=patch.object(run,'load_prepared',return_value=(self.packet,self.prompt,{'code_receipts':[]}))
        p.start();self.addCleanup(p.stop)
    def execute(self):return run.run(self.root,self.out,response_file=self.response)
    def test_workflow_no_remote_call(self):
        with patch.object(run,'live_response',side_effect=AssertionError('unexpected request')):
            _,r=self.execute()
        self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertFalse(r['render_gate_passed'])
    def test_provenance_offline_label(self):
        self.execute();r=json.loads((self.out/run.RECEIPT).read_text());self.assertEqual(r['mode'],'offline_fixture');self.assertFalse(r['live_inference_performed']);self.assertEqual(r['wrapper_invocations'],0)
    def test_independent_report_matches(self):self.execute();r=json.loads((self.out/run.REPORT).read_text());self.assertEqual(r['blocking_findings'],validator.validate_plan(self.plan,self.packet)['blocking_findings'])
    def test_schema_invalid_saved_response_is_quarantined(self):
        self.response.write_text(json.dumps({'schema_version':'0.2.0','variants':[]}));_,r=self.execute()
        self.assertFalse(r['structural_validity']);self.assertFalse((self.out/run.PLAN).exists());self.assertTrue((self.out/'rejected-output.v03.json').is_file());self.assertEqual(validator.exit_code(r),2)
    def test_existing_output_refused(self):self.out.mkdir();(self.out/'keep').write_text('keep');self.assertRaises(intake.base.AdapterError,self.execute);self.assertEqual((self.out/'keep').read_text(),'keep')
    def test_malformed_output_publishes_nothing(self):self.response.write_text('bad');self.assertRaises(intake.base.AdapterError,self.execute);self.assertFalse(self.out.exists())
    def test_secret_output_publishes_nothing(self):self.response.write_text(json.dumps({'text':'sk-SYNTHETIC_TEST_12345'}));self.assertRaises(intake.base.AdapterError,self.execute);self.assertFalse(self.out.exists())
    def test_saved_response_size_bound(self):self.response.write_text('x'*(run.MAX_RESPONSE_BYTES+1));self.assertRaises(intake.base.AdapterError,self.execute);self.assertFalse(self.out.exists())
    def test_response_selection_exclusive(self):self.assertRaises(intake.base.AdapterError,run.run,self.root,self.out,response_file=self.response,live_approved=True)
    def test_input_changed_before_publish(self):
        with patch.object(run,'recheck_inputs',side_effect=intake.base.AdapterError('input changed')):self.assertRaises(intake.base.AdapterError,self.execute)
        self.assertFalse(self.out.exists())
    def test_atomic_complete_files(self):
        self.execute()
        for name in (run.PACKET,run.PLAN,run.REPORT,run.RECEIPT):self.assertIsInstance(json.loads((self.out/name).read_text()),dict)
        self.assertEqual(list(self.out.glob('*.tmp')),[])
    def test_publication_failure_cleans_owned_files(self):
        original=run.shared.write_json
        def fail(path,data):
            if path.name==run.RECEIPT:raise OSError('synthetic publication error')
            return original(path,data)
        with patch.object(run.shared,'write_json',side_effect=fail):self.assertRaises(OSError,self.execute)
        self.assertFalse(self.out.exists());self.assertEqual(list(self.root.rglob('*.tmp')),[])
    def test_no_clobber_atomic_writer(self):
        path=self.root/'keep.json';run.shared.write_json(path,{'first':True})
        self.assertRaises(intake.base.AdapterError,run.shared.write_json,path,{'second':True});self.assertEqual(json.loads(path.read_text()),{'first':True})
    def test_output_path_traversal(self):self.assertRaises(intake.base.AdapterError,run.publish,self.root/'foo/../escape',{})
    def test_output_symlink_escape(self):
        outside=tempfile.TemporaryDirectory();self.addCleanup(outside.cleanup);link=self.root/'link';link.symlink_to(outside.name)
        self.assertRaises(intake.base.AdapterError,run.publish,link/'out',{})
    def test_cli_inspection_status(self):
        self.execute();destination=self.root/'check.json'
        with patch.object(intake,'validate_packet',return_value=self.packet),contextlib.redirect_stdout(io.StringIO()):
            code=validator.main(['--packet',str(self.out/run.PACKET),'--plan',str(self.out/run.PLAN),'--output',str(destination)])
        self.assertEqual(code,0);self.assertFalse(json.loads(destination.read_text())['render_gate_passed'])
    def test_cli_enforce_gate_nonzero(self):
        self.execute();destination=self.root/'check.json'
        with patch.object(intake,'validate_packet',return_value=self.packet),contextlib.redirect_stdout(io.StringIO()):
            code=validator.main(['--packet',str(self.out/run.PACKET),'--plan',str(self.out/run.PLAN),'--output',str(destination),'--enforce-render-ready'])
        self.assertEqual(code,20)
    def test_cli_invalid_plan_nonzero(self):
        self.execute();(self.out/run.PLAN).write_text(json.dumps({'invalid':'object'}))
        with patch.object(intake,'validate_packet',return_value=self.packet),contextlib.redirect_stdout(io.StringIO()):
            code=validator.main(['--packet',str(self.out/run.PACKET),'--plan',str(self.out/run.PLAN),'--output',str(self.root/'check.json')])
        self.assertEqual(code,2)
    def test_cli_safety_failure_nonzero(self):
        self.plan['source']['sha256']='b'*64;self.response.write_text(json.dumps(self.plan));self.execute()
        with patch.object(intake,'validate_packet',return_value=self.packet),contextlib.redirect_stdout(io.StringIO()):
            code=validator.main(['--packet',str(self.out/run.PACKET),'--plan',str(self.out/run.PLAN),'--output',str(self.root/'check.json')])
        self.assertEqual(code,3)
    def test_cli_failures_do_not_echo_untrusted_text(self):
        capture=io.StringIO()
        with contextlib.redirect_stderr(capture):code=run.main(['run','--prepared','missing','--output',str(self.out),'--response-file','SYNTHETIC_SECRET_NOT_LOGGED'])
        self.assertEqual(code,1);self.assertNotIn('SYNTHETIC_SECRET',capture.getvalue())
    def test_prepare_artifacts_no_inference(self):
        with patch.object(intake,'build_packet',return_value=self.packet),patch.object(run,'code_receipts',return_value=[]),patch.object(run,'live_response',side_effect=AssertionError('unexpected inference')):
            run.prepare({},self.out)
        self.assertTrue((self.out/run.PROMPT).is_file());self.assertFalse(json.loads((self.out/run.REQUEST).read_text())['live_inference_performed'])
    def test_load_prepared_tampering(self):
        # Remove the setUp mock for this test only.
        with patch.object(intake,'build_packet',return_value=self.packet),patch.object(run,'code_receipts',return_value=[]):run.prepare({},self.out)
        (self.out/run.PROMPT).write_text('changed')
        from importlib import reload
        # Call a captured original implementation, independent of setup's mock.
        with patch.object(intake,'validate_packet',return_value=self.packet):self.assertRaises(intake.base.AdapterError,ORIGINAL_LOAD,self.out)
    def test_code_receipt_invalidated_before_inference(self):
        with patch.object(intake,'build_packet',return_value=self.packet),patch.object(run,'code_receipts',return_value=[]):run.prepare({},self.out)
        with patch.object(intake,'validate_packet',return_value=self.packet):self.assertRaises(intake.base.AdapterError,ORIGINAL_LOAD,self.out)

ORIGINAL_LOAD=run.load_prepared


class ResourceTests(unittest.TestCase):
    def test_small_bounded_response(self):self.assertEqual(run.bounded_model_output([sys.executable,'-c','print("ok")'],timeout=2),'ok\n')
    def test_timeout_and_reaping(self):
        processes=[];original=run.subprocess.Popen
        def tracked(*a,**kw):p=original(*a,**kw);processes.append(p);return p
        with patch.object(run.subprocess,'Popen',side_effect=tracked):self.assertRaises(intake.base.AdapterError,run.bounded_model_output,[sys.executable,'-c','import time;time.sleep(10)'],timeout=.1)
        self.assertIsNotNone(processes[0].poll());self.assertTrue(processes[0].stdout.closed)
    def test_response_limit_and_reaping(self):self.assertRaises(intake.base.AdapterError,run.bounded_model_output,[sys.executable,'-c','print("x"*1000)'],timeout=2,max_bytes=20)
    def test_nonzero_subprocess(self):self.assertRaises(intake.base.AdapterError,run.bounded_model_output,[sys.executable,'-c','raise SystemExit(4)'],timeout=2)
    def test_stderr_is_discarded(self):self.assertEqual(run.bounded_model_output([sys.executable,'-c','import sys;sys.stderr.write("UNTRUSTED_DIAGNOSTIC"*10000);print("ok")'],timeout=2),'ok\n')
    def test_secret_subprocess_output(self):self.assertRaises(intake.base.AdapterError,run.bounded_model_output,[sys.executable,'-c','print("sk-SYNTHETIC_ONLY_TEST_12345")'],timeout=2)
    def test_prompt_bound(self):p=f.packet();p['extra']='x'*run.MAX_PROMPT_BYTES;self.assertRaises(intake.base.AdapterError,run.make_prompt,p)

    def test_pipeline_wall_clock_deadline(self):
        with self.assertRaises(intake.base.AdapterError):
            with intake.processing_deadline(.02):
                time.sleep(.2)
    def test_process_group_descendant_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile=Path(directory)/'child.pid'
            script='import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);Path(sys.argv[1]).write_text(str(p.pid));time.sleep(30)'
            self.assertRaises(intake.base.AdapterError,run.bounded_model_output,[sys.executable,'-c',script,str(pidfile)],timeout=.5)
            self.assertTrue(pidfile.exists())
            pid=int(pidfile.read_text())
            # A grandchild may remain a zombie until the host init reaps it; it
            # must never remain running after the process group is terminated.
            for _ in range(20):
                stat=Path('/proc')/str(pid)/'stat'
                try:state=stat.read_text().split()[2]
                except FileNotFoundError:break  # Host init reaped it between checks.
                if state=='Z':break
                time.sleep(.02)
            else:self.fail('model descendant remains active after group timeout')
