"""Offline preview boundary tests. Never encode real source in this suite."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import render_showcase_preview_v01 as p
import render_video_v01 as renderer

c=p.core


class PreviewSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p.AUDIT.mkdir(parents=True,exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=p.AUDIT,prefix='.preview-tests-')
        cls.root=Path(cls.tmp.name)
        cls.cap=cls.root/'capabilities.json';c.shared.write_json(cls.cap,{'offline_mock':True})
        cls.packet=c.read_json(p.LIVE/p.PACKET)
        cls.plan=p.manual_plan(cls.packet);cls.spec=p.execution_spec(cls.plan)
        cls.report=p.validator.validate_plan(cls.plan,cls.packet)
        cls.output=c.TEST_ROOT/'real-content-showcase.v99999999999'

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        self.plan=copy.deepcopy(self.__class__.plan);self.spec=copy.deepcopy(self.__class__.spec)
        self.context={'packet':copy.deepcopy(self.packet),'validation':copy.deepcopy(self.report),
            'capabilities':str(self.cap),'authorization':p.authorization(self.plan,self.spec,self.packet,self.cap,self.output)}
        self.replay=patch.object(c.intake,'validate_packet',return_value=self.packet);self.replay.start();self.addCleanup(self.replay.stop)
        self.registry=patch.object(renderer,'validate_registry',return_value={'operations':{k:{'status':'verified'} for k in p.ALLOWED}})
        self.mock_registry=self.registry.start();self.addCleanup(self.registry.stop)
        self.original_recovery=p.check_recovery
        self.recovery=patch.object(p,'check_recovery');self.recovery.start();self.addCleanup(self.recovery.stop)

    def check(self):return p.validate_context(self.context,self.plan,self.spec,p.SOURCE,self.output,{})
    def rejected(self):self.assertRaises(c.Error,self.check)
    def test_valid_separate_preview(self):self.assertEqual(self.check()[0]['expected_duration_sec'],10.4)
    def test_structural_validation(self):self.assertTrue(self.report['structural_validity']);self.assertEqual(self.report['blocking_findings'],[])
    def test_review_pending_only(self):self.assertEqual(self.report['status'],'NEEDS_REVIEW');self.assertFalse(self.report['render_gate_passed'])
    def test_original_plan_rejected(self):self.plan=c.read_json(p.LIVE/'editing-plan.v03.json');self.rejected()
    def test_original_plan_still_blocked(self):self.assertEqual(p.validator.validate_plan(c.read_json(p.LIVE/'editing-plan.v03.json'),self.packet)['blocking_findings'][0]['code'],'onset_sync_without_onset')
    def test_original_blocked_fingerprint_tamper(self):
        original=c.intake.gate.sha256_file
        with patch.object(c.intake.gate,'sha256_file',side_effect=lambda path:'0'*64 if Path(path).name=='plan-validation.v03.json' else original(path)):
            self.rejected()
    def test_wrong_source_path(self):self.assertRaises(c.Error,p.validate_context,self.context,self.plan,self.spec,c.base.ROOT/'data/test-videos/mandala-original.mp4',self.output,{})
    def test_wrong_source_fingerprint(self):
        with patch.object(c.intake.gate,'sha256_file',return_value='0'*64):self.rejected()
    def test_cross_source_packet(self):self.context['packet']['source']['sha256']='0'*64;self.rejected()
    def test_source_metadata_tamper(self):self.plan['source']['width']=576;self.rejected()
    def test_new_recipe_tamper(self):self.plan['variants'][0]['shots'][1]['source_start_sec']=14;self.rejected()
    def test_invalid_timing(self):self.plan['variants'][0]['shots'][0]['source_end_sec']=99;self.rejected()
    def test_unsupported_operation(self):self.plan['variants'][0]['operations'][0]['kind']='arbitrary_effect';self.rejected()
    def test_no_onset_sync(self):self.plan['variants'][0]['audio_strategy']['sync_basis']='onset_candidate';self.rejected()
    def test_no_caption(self):self.assertFalse(any(o['kind'] in ('subtitle','overlay') for o in self.plan['variants'][0]['operations']))
    def test_no_colour_or_flash_added(self):self.assertEqual(set(self.check()[0]['required_capabilities']),p.ALLOWED)
    def test_spec_tamper(self):self.spec['output']['width']=576;self.rejected()
    def test_external_asset_rejected(self):self.spec['assets']={'new':{}};self.rejected()
    def test_render_approval_promotion(self):self.plan['render_approved']=True;self.rejected()
    def test_publish_approval_promotion(self):self.context['authorization']['publish_approved']=True;self.rejected()
    def test_production_scope_rejected(self):self.context['authorization']['authorization_mode']='PRODUCTION';self.rejected()
    def test_production_approval_false(self):self.assertFalse(self.context['authorization']['production_approval_granted']);self.assertFalse(self.plan['publish_ready'])
    def test_capability_missing_verification(self):self.mock_registry.return_value['operations']['audio_fade']['status']='available';self.rejected()
    def test_capability_tamper(self):self.context['authorization']['capabilities']['sha256']='0'*64;self.rejected()
    def test_code_receipt_tamper(self):self.context['authorization']['code_receipts'][0]['sha256']='0'*64;self.rejected()
    def test_validation_report_tamper(self):self.context['validation']['blocking_findings']=[{'code':'blocked','location':'test'}];self.rejected()
    def test_review_report_approval_tamper(self):self.context['validation']['render_approved']=True;self.rejected()
    def test_no_unlimited_candidates(self):self.context['authorization']['maximum_final_candidates']=2;self.rejected()
    def test_output_auth_binding(self):self.context['authorization']['output_directory']='data/render-tests/stage55/real-content-showcase.v99';self.rejected()
    def test_wrong_destination(self):self.assertRaises(c.Error,p.destination,c.PRODUCTION_ROOT/'real-content-showcase.v01')
    def test_non_preview_destination(self):self.assertRaises(c.Error,p.destination,c.TEST_ROOT/'generic')
    def test_path_traversal(self):self.assertRaises(c.Error,p.destination,c.TEST_ROOT/'..'/'real-content-showcase.v01')
    def test_symlink_escape(self):
        target=self.root/'link';target.symlink_to('/tmp');self.assertRaises(c.Error,p.destination,target/'real-content-showcase.v01')
    def test_existing_output(self):self.assertRaises(c.Error,p.destination,self.root)
    def test_atomic_second_attempt_rejected(self):
        # Exercise real exclusive writer with a private marker; source replay is
        # already exercised by prepare/real admission, never render in unit tests.
        with patch.object(p,'AUDIT',self.root),patch.object(p,'validate_context'),patch.object(p,'check_recovery',side_effect=self.original_recovery),patch.object(p,'completed_candidate_exists',return_value=False):
            p.admit(self.context,self.plan,self.spec,p.SOURCE,self.output,{})
            self.assertRaises(c.Error,p.admit,self.context,self.plan,self.spec,p.SOURCE,self.output,{})
    def test_completed_candidate_prevents_any_admission(self):
        with patch.object(p,'completed_candidate_exists',return_value=True):
            self.assertRaises(c.Error,p.admit,self.context,self.plan,self.spec,p.SOURCE,self.output,{})
    def test_failed_recovery_is_bounded_and_preserves_original_marker(self):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            root=Path(tmp);c.shared.write_json(root/'preview-attempt.v01.json',{'failed_test_fixture':True})
            c.shared.write_json(root/p.FAILURE,{'offline_fixture':True})
            before=c.intake.gate.sha256_file(root/'preview-attempt.v01.json')
            with patch.object(p,'AUDIT',root),patch.object(p,'validate_context'),patch.object(p,'completed_candidate_exists',return_value=False):
                p.admit(self.context,self.plan,self.spec,p.SOURCE,self.output,{})
                self.assertTrue((root/'preview-attempt.v02.json').is_file())
                self.assertEqual(c.intake.gate.sha256_file(root/'preview-attempt.v01.json'),before)
                self.assertRaises(c.Error,p.admit,self.context,self.plan,self.spec,p.SOURCE,self.output,{})
    def test_recovery_wrong_candidate_rejected(self):self.assertRaises(c.Error,self.original_recovery,self.plan,self.output)
    def test_recovery_requires_complete_frame_diagnostic(self):
        original=c.read_json
        def forged(path):
            value=original(path)
            if Path(path).name=='read-only-filter-diagnostic.v02.json':value['actual_frames']=104
            return value
        with patch.object(c,'read_json',side_effect=forged):
            self.assertRaises(c.Error,self.original_recovery,self.plan,c.TEST_ROOT/'real-content-showcase.v01')
    def test_prior_failure_auth_hash_tamper_rejected(self):
        self.context['authorization']['prior_failure']['sha256']='0'*64;self.rejected()
    def test_time_recovery_rejects_any_completed_candidate_claim(self):
        original=c.read_json
        def forged(path):
            value=original(path)
            if Path(path).name==p.TIME_FAILURE:value['final_candidate_created']=True
            return value
        with patch.object(c,'read_json',side_effect=forged):
            self.assertRaises(c.Error,self.original_recovery,self.plan,c.TEST_ROOT/'real-content-showcase.v01')
    def test_time_recovery_rejects_unbounded_elapsed_claim(self):
        original=c.read_json
        def forged(path):
            value=original(path)
            if Path(path).name==p.TIME_FAILURE:value['elapsed_after_reservation_sec']=1000
            return value
        with patch.object(c,'read_json',side_effect=forged):
            self.assertRaises(c.Error,self.original_recovery,self.plan,c.TEST_ROOT/'real-content-showcase.v01')
    def test_production_cannot_accept_preview_permit(self):
        name=self.root/'authorization.json';c.shared.write_json(name,self.context['authorization'])
        report=renderer.production_admission(p.LIVE/'editing-plan.v03.json',p.LIVE/p.PACKET,p.LIVE/'plan-validation.v03.json',name)
        self.assertFalse(report['editing_started']);self.assertFalse(report['mp4_created'])
        self.assertTrue(report['reasons'])
    def test_low_level_production_refused_before_ffmpeg(self):
        with patch.object(c,'ffmpeg',side_effect=AssertionError('must not encode')):
            self.assertRaises(c.Error,c.encode,p.SOURCE,{},self.spec,self.root,{},'PRODUCTION',admission=(self.context,self.plan,self.output))
    def test_low_level_preview_without_permit_refused(self):self.assertRaises(c.Error,c.encode,p.SOURCE,{},self.spec,self.root,{},'REAL_CONTENT_PREVIEW')
    def test_low_level_work_path_escape_rejected(self):
        with patch.object(p,'admit',side_effect=AssertionError('must reject before consuming permit')):
            self.assertRaises(c.Error,c.encode,p.SOURCE,{},self.spec,Path('/tmp'),{},'REAL_CONTENT_PREVIEW',admission=(self.context,self.plan,self.output))
    def test_low_level_private_directory_reaches_encoder_without_encoding(self):
        graph=c.compile_timeline(self.plan,self.spec)
        with tempfile.TemporaryDirectory(dir=p.AUDIT,prefix='.preview-work-') as tmp:
            with patch.object(p,'admit'),patch.object(c,'ffmpeg',side_effect=RuntimeError('test interception; no encoding')) as mocked:
                self.assertRaises(RuntimeError,c.encode,p.SOURCE,graph,self.spec,Path(tmp),{},'REAL_CONTENT_PREVIEW',admission=(self.context,self.plan,self.output))
                mocked.assert_called_once()
    def test_render_entry_accepts_prepared_directory_before_admission(self):
        prepared=self.root/'prepared';prepared.mkdir()
        for name,obj in ((p.PLAN,self.plan),(p.SPEC,self.spec),(p.PACKET,self.packet),(p.REPORT,self.report),(p.AUTH,self.context['authorization'])):
            c.shared.write_json(prepared/name,obj)
        with patch.object(p,'validate_context',side_effect=RuntimeError('test admission interception; no render')) as mocked:
            self.assertRaises(RuntimeError,p.render,prepared)
            mocked.assert_called_once()
    def test_encoder_graph_tamper_never_encodes(self):
        with tempfile.TemporaryDirectory(dir=p.AUDIT,prefix='.preview-work-') as work:
            with patch.object(p,'admit'),patch.object(c,'ffmpeg',side_effect=AssertionError('must not encode')):
                self.assertRaises(c.Error,c.encode,p.SOURCE,{},self.spec,Path(work),{},'REAL_CONTENT_PREVIEW',admission=(self.context,self.plan,self.output))
    def test_black_scan_empty(self):
        with patch.object(c,'run',return_value=(bytes([100])*(54*96*312),.01)):
            self.assertEqual(p.black_scan(self.cap,self.check()[0],self.spec['resources'])['near_black_timestamps_sec'],[])
    def test_black_scan_rejects_black(self):
        with patch.object(c,'run',return_value=(bytes(54*96*312),.01)):
            self.assertRaises(c.Error,p.black_scan,self.cap,self.check()[0],self.spec['resources'])
    def test_black_scan_wrong_frame_count(self):
        with patch.object(c,'run',return_value=(bytes([100])*(54*96*311),.01)):
            self.assertRaises(c.Error,p.black_scan,self.cap,self.check()[0],self.spec['resources'])
    def test_real_synthetic_middle_fades_keep_audio_outside_windows(self):
        from array import array
        import math
        import render_test_fixtures_v01 as fixtures
        with tempfile.TemporaryDirectory(dir=self.root,prefix='.splice-test-') as tmp:
            work=Path(tmp)
            identity,plan,spec,source,assets=fixtures.create(work,'audio',work/'synthetic-final')
            variant=plan['variants'][0]
            variant['operations']=[fixtures.op('out','custom','s1',2.9,3,
                {'name':'renderer.audio_fade.v01','implementation_requirements':'Explicit synthetic middle fade'}),
                fixtures.op('in','custom','s1',3,3.1,
                {'name':'renderer.audio_fade.v01','implementation_requirements':'Explicit synthetic middle fade'})]
            spec['operation_parameters']={'out':{'fade':{'direction':'out','start_sec':2.9,'duration_sec':.1}},
                'in':{'fade':{'direction':'in','start_sec':3,'duration_sec':.1}}}
            spec['plan_sha256']=c.digest_object(plan)
            timeline=c.compile_timeline(plan,spec)
            graph,_,_,_=c.filter_graph(timeline,True,work,spec)
            raw,_=c.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-filter_complex',graph,
                '-map','[vout]','-f','null','/dev/null','-map','[aout]','-ac','1','-f','f32le','pipe:1'],
                spec['resources'],max_bytes=2000000)
            pcm=array('f');pcm.frombytes(raw)
            def rms(a,b):
                x=pcm[int(a*48000):int(b*48000)];return math.sqrt(sum(v*v for v in x)/len(x))
            self.assertGreater(rms(2.5,2.8),.05)
            self.assertGreater(rms(3.2,3.5),.05)
            self.assertGreater(rms(5,5.5),.05)
            self.assertLess(rms(2.97,3.03),.04)
    def test_approval_schema_rejects_extra_force_flag(self):self.context['authorization']['force']=True;self.rejected()


if __name__=='__main__':unittest.main()
