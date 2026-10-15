"""Offline Stage 5.6 safety, signal controls, model grounding and decision tests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import video_quality_qa_v01 as q
import review_video_quality_v01 as r
c=q.core
REAL=c.TEST_ROOT/'real-content-showcase.v01'
BASIC=c.TEST_ROOT/'real-preview-audit.v01/capability-proofs.v04/basic'
CONTROLS=None


def setUpModule():
    global BASIC,CONTROLS
    temporary=tempfile.TemporaryDirectory(dir=c.TEST_ROOT,prefix='stage58b-qa-controls-')
    unittest.addModuleCleanup(temporary.cleanup)
    CONTROLS=Path(temporary.name)
    for name in ('basic','dynamic','captions','silent'):
        q.renderer.self_test(name,CONTROLS/name)
    BASIC=CONTROLS/'basic'


def timeline():
    return {'expected_duration_sec':2.,'output_settings':{'fps':30,'width':180,'height':320},'operations':[],
        'shots':[{'shot_id':'a','output_start_sec':0.,'output_end_sec':1.,'source_start_sec':0.,'source_end_sec':1.,'speed':1.,'freeze_sec':0.,'transition_out':'cut','overlap_sec':0.},
                 {'shot_id':'b','output_start_sec':1.,'output_end_sec':2.,'source_start_sec':1.,'source_end_sec':2.,'speed':1.,'freeze_sec':0.,'transition_out':'cut','overlap_sec':0.}]}


def tone():return .1*np.sin(np.arange(96000)*2*np.pi*440/48000)


class AudioControls(unittest.TestCase):
    def setUp(self):self.t=timeline();self.p=tone()
    def analyze(self,**kw):return q.audio_analysis(self.p,self.t,**kw)
    def test_clean_contiguous_no_discontinuous_selection(self):self.assertFalse(any(f['event_type']=='discontinuous_source_audio_selection' for f in self.analyze()[1]))
    def test_clean_transition_not_phrase_verified(self):self.assertFalse(self.analyze()[0]['musical_continuity_verified'])
    def test_actual_boundary_derived(self):self.assertEqual(self.analyze()[0]['boundaries'][0]['output_time_sec'],1.)
    def test_signal_peak_and_rms(self):a,_=self.analyze();self.assertAlmostEqual(a['peak'],.1,places=4);self.assertAlmostEqual(a['rms'],.1/np.sqrt(2),places=4)
    def test_waveform_jump_at_window_edge(self):self.p[48000:]=-.7;self.assertTrue(any(e['max_sample_delta']>.35 for e in self.analyze()[0]['events']))
    def test_spectral_change_candidate(self):self.p[48000:]=.1*np.sin(np.arange(48000)*2*np.pi*4400/48000);self.assertGreater(self.analyze()[0]['boundaries'][0]['spectral_distance'],.5)
    def test_equal_rms_different_spectrum(self):self.p[48000:]=.1*np.sin(np.arange(48000)*2*np.pi*4400/48000);a,_=self.analyze();self.assertLess(abs(a['boundaries'][0]['level_difference_db']),.01);self.assertFalse(a['musical_continuity_verified'])
    def test_unwanted_silence(self):self.p[12000:30000]=0;self.assertTrue(any(f['event_type']=='unexpected_silence_candidate' for f in self.analyze()[1]))
    def test_deliberate_silent_mode(self):self.p[:]=0;self.assertFalse(self.analyze(audio_mode='silent')[1])
    def test_source_quiet_not_renderer_defect(self):self.p[12000:30000]=0;self.assertFalse(any(f['event_type']=='unexpected_silence_candidate' for f in self.analyze(source_pcm=self.p)[1]))
    def test_gain_does_not_excuse_missing_audio(self):self.p[12000:30000]=0;op={'effective_kind':'audio_gain','parameters':{'gain_db':-8},'output_start_sec':0,'output_end_sec':2};self.assertTrue(any(f['event_type']=='unexpected_silence_candidate' for f in self.analyze(operations=[op])[1]))
    def test_planned_fade_quiet(self):self.p[:12000]=0;op={'effective_kind':'audio_fade','parameters':{},'output_start_sec':0,'output_end_sec':.25};self.assertFalse(any(f['event_type']=='unexpected_silence_candidate' for f in self.analyze(operations=[op])[1]))
    def test_fade_does_not_hide_source_jump(self):self.t['shots'][1]['source_start_sec']=5;self.t['shots'][1]['source_end_sec']=6;op={'effective_kind':'audio_fade','parameters':{},'output_start_sec':.9,'output_end_sec':1.1};a,f=self.analyze(operations=[op]);self.assertTrue(a['boundaries'][0]['fade_present']);self.assertTrue(any(x['event_type']=='discontinuous_source_audio_selection' for x in f))
    def test_clipping_candidate(self):self.p*=15;self.assertTrue(any(f['event_type']=='potential_clipping' for f in self.analyze()[1]))
    def test_active_ending_is_review_only(self):a,f=self.analyze();end=next(x for x in f if x['event_type']=='active_audio_ending_review');self.assertEqual(end['severity'],'low');self.assertIn('does not independently prove',end['description'])
    def test_nan_pcm_rejected(self):self.p[0]=np.nan;self.assertRaises(c.Error,self.analyze)
    def test_empty_pcm_rejected(self):self.p=[];self.assertRaises(c.Error,self.analyze)
    def test_bounded_windows(self):self.assertLessEqual(len(self.analyze()[0]['windows']),512)
    def test_pcm_fingerprint_reproducible(self):self.assertEqual(self.analyze()[0]['pcm_sha256'],self.analyze()[0]['pcm_sha256'])


class VisualControls(unittest.TestCase):
    def setUp(self):
        self.t=timeline();self.s=[{'time_sec':i*.25,'frame_index':i*8,'dark_fraction':0,'brightness':.5,'raw_difference':.2,'centered_difference':.05} for i in range(8)]
        self.sampling={'maximum_gap_sec':.25}
    def analyze(self):return q.visual_analysis(self.s,self.t,self.sampling)
    def test_clean_motion_no_freeze(self):self.assertEqual(self.analyze()[1],[])
    def test_dark_candidate_not_verified_black_error(self):
        for s in self.s:s['dark_fraction']=1
        f=self.analyze()[1][0];self.assertEqual(f['confidence'],'low');self.assertIn('dark source',f['description'])
    def test_static_not_certified_freeze(self):
        for s in self.s:s['raw_difference']=0
        self.assertEqual(self.analyze()[1][0]['event_type'],'static_or_duplicate_candidate')
    def test_planned_freeze_not_defect(self):
        self.t['shots']=self.t['shots'][:1];self.t['shots'][0].update(freeze_sec=1.75,freeze_output_start_sec=.25,output_end_sec=2)
        for s in self.s:s['raw_difference']=0
        self.assertEqual(self.analyze()[1],[]);self.assertEqual(self.analyze()[0]['events'][0]['kind'],'planned_freeze')
    def test_intentional_cut_event_not_defect(self):self.s[4]['centered_difference']=.9;v,f=self.analyze();self.assertEqual(f,[]);self.assertEqual(v['events'][0]['kind'],'planned_transition_candidate')
    def test_flash_candidate_not_overexposure_defect(self):self.s[2]['brightness']=.95;v,f=self.analyze();self.assertEqual(f,[]);self.assertTrue(v['events'])
    def test_repeated_source_interval_review(self):self.t['shots'][1].update(source_start_sec=0,source_end_sec=1);self.assertEqual(self.analyze()[1][0]['event_type'],'source_range_reuse')
    def test_mapping_across_cut(self):self.t['shots'][1].update(source_start_sec=5,source_end_sec=6);m=q.source_ranges({'start_sec':.9,'end_sec':1.1},self.t);self.assertEqual(m[1]['source_start_sec'],5);self.assertEqual(m[0]['source_end_sec'],1)
    def test_mapping_speed(self):self.t['shots'][0].update(speed=2,source_end_sec=2);self.assertEqual(q.source_ranges({'start_sec':0,'end_sec':.5},self.t)[0]['source_end_sec'],1)
    def test_mapping_freeze_clamped(self):self.t['shots'][0].update(source_end_sec=.5,freeze_sec=.5);self.assertEqual(q.source_ranges({'start_sec':.8,'end_sec':.9},self.t)[0]['source_end_sec'],.5)
    def test_caption_missing_not_fabricated(self):self.assertEqual(q.caption_analysis({},self.t)[0]['status'],'NOT_APPLICABLE')
    def test_invalid_pts_rejected(self):
        with patch.object(c,'run',return_value=(b'{"frames":[{"best_effort_timestamp_time":"0"},{"best_effort_timestamp_time":"0"}]}',{})):self.assertRaises(c.Error,q.frame_samples,BASIC/'render.mp4',2,30)
    def test_empty_pts_rejected(self):
        with patch.object(c,'run',return_value=(b'{"frames":[]}',{})):self.assertRaises(c.Error,q.frame_samples,BASIC/'render.mp4',2,30)


class DecisionSafety(unittest.TestCase):
    def setUp(self):self.p=q.empty_report();self.p['evidence_ledger']={'test':{}};self.p['technical']['duration_sec']=2
    def add(self,origin='human_feedback',severity='high'):
        f=q.issue('audio','test','test',{'start_sec':.9,'end_sec':1.1},origin=origin,severity=severity,evidence=['test']);f['issue_id']='one'
        if origin=='human_feedback':f['human_confirmation']='confirmed_user_handoff';self.p['human']['performed']=True
        self.p['issues']=[f];return q.assess(self.p)
    def test_human_issue_dominates(self):self.assertEqual(self.add()['overall_decision'],'REVISE')
    def test_critical_dominates_good_dimensions(self):self.p['ai_editorial_status']='PASS';self.assertEqual(self.add('deterministic_validation','critical')['overall_decision'],'BLOCKED')
    def test_no_inference_incomplete(self):self.assertEqual(q.assess(self.p)['overall_decision'],'INCOMPLETE')
    def test_no_publishing_upgrade(self):self.assertFalse(self.add()['publishing_eligible']);self.assertFalse(self.p['production_eligible'])
    def test_no_hidden_human_failure(self):self.add();self.p['overall_decision']='PASS';self.assertRaises(c.Error,q.validate_report,self.p)
    def test_no_hidden_critical(self):self.add('deterministic_validation','critical');self.p['overall_decision']='PASS';self.assertRaises(c.Error,q.validate_report,self.p)
    def test_cli_zero_not_approval(self):
        with patch.object(q,'save',return_value=self.add()):self.assertEqual(q.main(['--bundle','fixture','--output','fixture']),0)
    def test_cli_blocked_nonzero(self):
        with patch.object(q,'save',return_value=self.add('deterministic_validation','critical')):self.assertEqual(q.main(['--bundle','fixture','--output','fixture']),2)
    def test_fake_human_confirmation_rejected(self):self.add('signal_measurement');self.p['issues'][0]['human_confirmation']='confirmed_user_handoff';self.assertRaises(c.Error,q.validate_report,self.p)
    def test_duplicate_ids_rejected(self):self.add();self.p['issues']*=2;self.assertRaises(c.Error,q.validate_report,self.p)
    def test_invalid_output_time_rejected(self):self.add();self.p['issues'][0]['output_range']['end_sec']=3;self.assertRaises(c.Error,q.validate_report,self.p)
    def test_ungrounded_issue_rejected(self):self.add();self.p['issues'][0]['evidence_refs']=['missing'];self.assertRaises(c.Error,q.validate_report,self.p)
    def test_ungrounded_dimension_rejected(self):self.p['dimensions']['hook']['evidence_refs']=['missing'];self.assertRaises(c.Error,q.validate_report,self.p)
    def test_untrusted_extra_field_rejected(self):self.p['trusted']=True;self.assertRaises(c.Error,q.validate_report,self.p)
    def test_offline_cannot_promote_ai(self):self.p['ai']['mode']='offline_fixture';self.p['ai_editorial_status']='PASS';self.assertRaises(c.Error,q.validate_report,self.p)
    def test_saved_cannot_promote_ai(self):self.p['ai']['mode']='saved_response_replay';self.p['ai_editorial_status']='PASS';self.assertRaises(c.Error,q.validate_report,self.p)
    def test_source_range_mapping_rejected(self):self.add();self.p['technical']['timeline']=timeline();self.p['issues'][0]['source_ranges']=[];self.assertRaises(c.Error,q.validate_report,self.p)
    def test_model_origin_preserved(self):self.add('model_unverified');self.assertEqual(self.p['dimensions']['audio_continuity']['provenance'],'model_unverified')


class ModelGrounding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=q.read(c.base.ROOT/'data/qa/stage56/showcase.v01'/q.PACKET)
        cls.request=r.make_request(cls.packet,'edited_output')
    def setUp(self):self.req=copy.deepcopy(self.request);self.data=r.mock_response(self.req)
    def validate(self):return r.validate_response(self.data,self.req,self.packet)
    def observation(self,category='visual',role='edited_output'):
        self.data['media_observation']['video_examined']=True
        self.data['issues']=[{'issue_id':'x','category':category,'severity':'medium','media_range':{'start_sec':0,'end_sec':1},'event_type':'candidate',
            'evidence_refs':['media.output' if role=='edited_output' else 'media.source'],'basis':'model_media_observation','origin':'model_unverified','confidence':'low',
            'human_confirmation':'not_confirmed','description':'Subjective observation','possible_cause':'Uncertain',
            'recommendation':q.recommendation('plan_change','Review source context'),'timing_precision':'approximate'}]
    def test_mock_valid_but_no_observation(self):self.assertFalse(self.validate()['media_observation']['video_examined'])
    def test_wrong_media_sha(self):self.data['media_sha256']='0'*64;self.assertRaises(c.Error,self.validate)
    def test_wrong_packet_sha(self):self.data['packet_sha256']='0'*64;self.assertRaises(c.Error,self.validate)
    def test_wrong_role(self):self.data['media_role']='original_source';self.assertRaises(c.Error,self.validate)
    def test_human_dimension_not_model(self):self.data['dimensions']['hook']['provenance']='human_feedback';self.assertRaises(c.Error,self.validate)
    def test_verified_signal_dimension_not_model(self):self.data['dimensions']['hook']['provenance']='signal_measurement';self.assertRaises(c.Error,self.validate)
    def test_unavailable_audio_cannot_pass(self):self.data['dimensions']['audio_continuity']['status']='PASS';self.assertRaises(c.Error,self.validate)
    def test_audio_listening_without_delivery(self):self.req['media']['audio_offered']=False;self.data['media_observation'].update(audio_examined=True,audio_access='model_self_reported_available');self.assertRaises(c.Error,self.validate)
    def test_uncertain_audio_cannot_be_examined(self):self.data['media_observation'].update(audio_examined=True,audio_access='uncertain');self.assertRaises(c.Error,self.validate)
    def test_self_reported_listening_kept_unverified(self):self.data['media_observation'].update(audio_examined=True,audio_access='model_self_reported_available');self.assertEqual(self.validate()['media_observation']['audio_access'],'model_self_reported_available')
    def test_unseen_visual_dimension(self):self.data['dimensions']['hook']['status']='PASS';self.assertRaises(c.Error,self.validate)
    def test_factual_safety_not_certified(self):self.data['media_observation']['video_examined']=True;self.data['dimensions']['factual_safety']['status']='PASS';self.assertRaises(c.Error,self.validate)
    def test_unheard_audio_observation_rejected(self):self.observation('audio');self.assertRaises(c.Error,self.validate)
    def test_actual_media_grounded_issue(self):self.observation();self.assertEqual(len(self.validate()['issues']),1)
    def test_missing_media_ref(self):self.observation();self.data['issues'][0]['evidence_refs']=['timeline'];self.assertRaises(c.Error,self.validate)
    def test_unknown_ref(self):self.observation();self.data['issues'][0]['evidence_refs']=['fabricated'];self.assertRaises(c.Error,self.validate)
    def test_duplicate_issue_ids(self):self.observation();self.data['issues']*=2;self.assertRaises(c.Error,self.validate)
    def test_bad_time(self):self.observation();self.data['issues'][0]['media_range']['end_sec']=99;self.assertRaises(c.Error,self.validate)
    def test_inverted_time(self):self.observation();self.data['issues'][0]['media_range']={'start_sec':1,'end_sec':0};self.assertRaises(c.Error,self.validate)
    def test_model_cannot_confirm_human(self):self.observation();self.data['issues'][0]['human_confirmation']='confirmed_user_handoff';self.assertRaises(c.Error,self.validate)
    def test_model_cannot_verify_capability(self):self.observation();self.data['issues'][0]['recommendation']['feasibility']='verified_current_capability';self.assertRaises(c.Error,self.validate)
    def test_model_cannot_claim_frame_precision(self):self.observation();self.data['issues'][0]['timing_precision']='frame_verified';self.assertRaises(c.Error,self.validate)
    def test_source_observation_cannot_reference_output(self):
        self.req=r.make_request(self.packet,'original_source');self.data=r.mock_response(self.req);self.observation();self.assertRaises(c.Error,self.validate)
    def test_source_dimension_cannot_reference_output(self):
        self.req=r.make_request(self.packet,'original_source');self.data=r.mock_response(self.req);self.data['dimensions']['hook']['evidence_refs']=['media.output'];self.assertRaises(c.Error,self.validate)
    def test_no_paid_call_without_approval(self):
        with patch.object(r,'capture_inference') as fn:self.assertRaises(c.Error,r.invoke,self.req,'missing');fn.assert_not_called()
    def test_known_cli_envelope(self):self.assertEqual(c.director.parse_response(json.dumps({'text':json.dumps(self.data)})),self.data)
    def test_unknown_envelope_rejected(self):self.assertRaises(c.Error,c.director.parse_response,json.dumps({'arbitrary':self.data}))
    def test_secret_like_response_rejected(self):self.data['limitations']=['Bearer secret-test-value'];self.assertRaises(c.Error,self.validate)
    def test_oversized_response_rejected(self):self.data['limitations']=['x'*2001];self.assertRaises(c.Error,self.validate)
    def test_no_approval_upgrade(self):self.data['production_eligible']=True;self.assertRaises(c.Error,self.validate)
    def test_human_withheld(self):self.assertNotIn('human_feedback',self.packet['inputs']);self.assertNotIn('human.feedback',self.packet['evidence_ledger']);self.assertFalse(self.packet['human_feedback_supplied_to_model'])
    def test_prepared_prompt_media_bound(self):self.assertIn(self.req['media']['sha256'],self.req['prompt']);self.assertEqual(self.req['prompt_sha256'],c.director.digest_text(self.req['prompt']))
    def test_model_facing_contract_preserves_semantic_limits(self):
        schema=json.loads(self.req['prompt'].split('\nOUTPUT_SCHEMA=')[1])
        for key,dimension in schema['properties']['dimensions']['properties'].items():
            self.assertEqual(dimension['properties']['provenance']['enum'],['model_unverified','unavailable'])
            self.assertEqual(set(dimension['properties']['evidence_refs']['items']['enum']),set(self.packet['evidence_ledger']))
        self.assertNotIn('PASS',schema['properties']['dimensions']['properties']['factual_safety']['properties']['status']['enum'])
        self.assertNotIn('verified_current_capability',schema['properties']['issues']['items']['properties']['recommendation']['properties']['feasibility']['enum'])
    def test_source_model_contract_excludes_output_only_references(self):
        request=r.make_request(self.packet,'original_source');schema=json.loads(request['prompt'].split('\nOUTPUT_SCHEMA=')[1])
        refs=schema['properties']['issues']['items']['properties']['evidence_refs']['items']['enum']
        self.assertIn('media.source',refs);self.assertNotIn('media.output',refs)
        self.assertFalse(any(ref.startswith('audio.splice.') for ref in refs))
    def test_no_fake_live_merge(self):p=q.empty_report();p['technical']['duration_sec']=2;out=r.merge(p,{'edited_output':self.data},mode='offline_fixture');self.assertEqual(out['ai_editorial_status'],'INCOMPLETE');self.assertEqual(out['ai']['video_observation'],'UNAVAILABLE')


class IntegritySafety(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory(dir=q.QA_ROOT);self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
    def test_safe_existing_reference(self):q.same_reference(q.ref(BASIC/'render.mp4'))
    def test_sha_mismatch(self):ref=q.ref(BASIC/'render.mp4');ref['sha256']='0'*64;self.assertRaises(c.Error,q.same_reference,ref)
    def test_missing_media(self):self.assertRaises(c.Error,c.safe_path,self.root/'missing.mp4')
    def test_traversal(self):self.assertRaises(c.Error,c.safe_path,str(self.root/'../secret.mp4'))
    def test_symlink_escape(self):p=self.root/'link';p.symlink_to('/etc/passwd');self.assertRaises(c.Error,c.safe_path,p)
    def test_inroot_symlink(self):p=self.root/'link';p.symlink_to(BASIC/'render.mp4');self.assertRaises(c.Error,c.safe_path,p)
    def test_external_path(self):self.assertRaises(c.Error,c.safe_path,'/etc/passwd')
    def test_existing_output_protected(self):self.assertRaises(c.Error,q.save,BASIC,self.root)
    def test_duplicate_json_keys(self):p=self.root/'bad.json';p.write_text('{"x":1,"x":2}');self.assertRaises(c.Error,q.read,p)
    def test_nan_json(self):p=self.root/'bad.json';p.write_text('{"x":NaN}');self.assertRaises(c.Error,q.read,p)
    def test_secret_path_rejected(self):p=self.root/'.env.asr';self.assertRaises(c.Error,c.safe_path,p)
    def test_bad_receipt_mode(self):p=self.root/r.RECEIPT;c.shared.write_json(p,{'mode':'fake'});self.assertRaises(c.Error,r.load_qa,self.root)
    def test_media_size_limit(self):
        packet=q.read(c.base.ROOT/'data/qa/stage56/showcase.v01'/q.PACKET)
        from types import SimpleNamespace
        fake=SimpleNamespace(stat=lambda:SimpleNamespace(st_size=21*1024*1024))
        with patch.object(c,'safe_path',return_value=fake),patch.object(q,'same_reference'):
            self.assertRaises(c.Error,r.make_request,packet,'edited_output')
    def test_missing_manifest_blocks(self):p,ctx=q.evaluate(self.root);self.assertEqual(p['overall_decision'],'BLOCKED')
    def test_metadata_mismatch_blocks(self):
        original=c.media_info
        with patch.object(c,'media_info',side_effect=lambda path,limits:{**original(path,limits),'width':99}):self.assertRaises(c.Error,q.verify_bundle,BASIC)
    def test_output_tamper_blocks(self):
        original=c.intake.gate.sha256_file
        with patch.object(c.intake.gate,'sha256_file',side_effect=lambda path:'0'*64 if Path(path).name=='render.mp4' else original(path)):self.assertRaises(c.Error,q.verify_bundle,BASIC)
    def test_source_tamper_blocks(self):
        original=c.intake.gate.sha256_file
        with patch.object(c.intake.gate,'sha256_file',side_effect=lambda path:'0'*64 if Path(path).name=='source.mp4' else original(path)):self.assertRaises(c.Error,q.verify_bundle,BASIC)
    def test_manifest_timeline_mismatch(self):
        original=q.read
        def altered(path):
            data=original(path)
            if Path(path).name==q.renderer.MANIFEST:data['timeline']['expected_duration_sec']+=1
            return data
        with patch.object(q,'read',side_effect=altered):self.assertRaises(c.Error,q.verify_bundle,BASIC)
    def test_no_network_in_technical(self):
        with patch.object(c.director,'bounded_model_output',side_effect=AssertionError('Network forbidden')):
            p,_=q.evaluate(self.root);self.assertEqual(p['processing']['network_requests'],0)



class RealFixtureControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx=q.verify_bundle(CONTROLS/'captions')
    def test_actual_declared_captions_timing(self):result,findings=q.caption_analysis(self.ctx['plan'],self.ctx['timeline']);self.assertFalse(findings);self.assertEqual(len(result['checks']),4)
    def test_safe_area_failure(self):
        t=copy.deepcopy(self.ctx['timeline']);t['operations'][0]['execution_parameters']['font_size_px']=200
        self.assertTrue(q.caption_analysis(self.ctx['plan'],t)[1])
    def test_caption_output_time_failure(self):
        t=copy.deepcopy(self.ctx['timeline']);t['operations'][0]['output_end_sec']=100
        self.assertTrue(q.caption_analysis(self.ctx['plan'],t)[1])
    def test_caption_source_time_failure(self):
        t=copy.deepcopy(self.ctx['timeline']);op=next(o for o in t['operations'] if 'caption_source_window' in o['execution_parameters']);op['execution_parameters']['caption_source_window']['start_sec']+=.1
        self.assertTrue(q.caption_analysis(self.ctx['plan'],t)[1])
    def test_actual_decoded_pts_sampling(self):
        samples,meta=q.frame_samples(self.ctx['output'],self.ctx['timeline']['expected_duration_sec'],30)
        self.assertTrue(samples);self.assertEqual(meta['stride_frames'],8)
        self.assertTrue(all(abs(s['time_sec']-s['frame_index']/30)<1e-6 for s in samples))
    def test_current_basic_receipt(self):self.assertEqual(q.verify_bundle(BASIC)['manifest']['authorization_mode'],'TEST_ONLY')
    def test_current_dynamic_receipt(self):self.assertEqual(q.verify_bundle(CONTROLS/'dynamic')['manifest']['authorization_mode'],'TEST_ONLY')
    def test_actual_silent_no_audio_features(self):
        report,_=q.evaluate(CONTROLS/'silent');self.assertEqual(report['technical']['audio']['status'],'NOT_APPLICABLE');self.assertEqual(report['dimensions']['audio_continuity']['status'],'NOT_APPLICABLE')
    def test_preserve_human_audio_confirmations(self):
        report=q.read(c.base.ROOT/'data/qa/stage56/showcase.v02'/q.REPORT)
        audio=[f for f in report['issues'] if f['origin']=='human_feedback' and f['category']=='audio']
        self.assertEqual(len(audio),2);self.assertTrue(all(f['human_confirmation']=='confirmed_user_handoff' for f in audio))
    def test_showcase_splices_signal_not_phrase_verification(self):
        report=q.read(c.base.ROOT/'data/qa/stage56/showcase.v02'/q.REPORT)
        boundaries=report['technical']['audio']['boundaries'];self.assertEqual([b['output_time_sec'] for b in boundaries],[3.5,6.5]);self.assertTrue(all(b['fade_present'] and b['musical_phrase_continuity']=='UNVERIFIED_REQUIRES_LISTENING' for b in boundaries))
    def test_cross_source_human_feedback_rejected(self):
        ctx=copy.deepcopy(self.ctx);ctx['plan']['source']['sha256']='0'*64
        self.assertRaises(c.Error,q.human_findings,q.QA_ROOT/'human-feedback.showcase.v01.json',ctx)
    def test_renderer_capability_remains_unfabricated(self):
        report=q.empty_report();self.assertNotIn('renderer_verified',report);self.assertFalse(report['render_approved'])
    def test_ai_revision_cannot_be_averaged_away(self):
        p=q.empty_report();p['ai_editorial_status']='REVISE';self.assertEqual(q.assess(p)['overall_decision'],'REVISE')
    def test_technical_subprocess_bound(self):self.assertLessEqual(q.LIMITS['timeout_sec'],180);self.assertLessEqual(q.LIMITS['memory_mib'],3072);self.assertLessEqual(q.PARAMETERS['maximum_visual_samples'],1000)

class ReviewerPipelineSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=q.QA_ROOT);self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
        self.packet=q.read(q.QA_ROOT/'showcase.v02'/q.PACKET);self.report=q.read(q.QA_ROOT/'showcase.v02'/q.REPORT)
        self.requests={role:r.make_request(self.packet,role) for role in r.ROLES}
        for role,request in self.requests.items():c.shared.write_json(self.root/r.name(role),request)
        c.shared.write_json(self.root/r.PREPARED,{'offline_test':True})
        self.loader=patch.object(r,'load_prepared',return_value=(self.report,self.packet,{},self.requests));self.loader.start();self.addCleanup(self.loader.stop)
    def run_review(self,**kw):return r.review(self.root,self.root/'result',**kw)
    def test_complete_mock_pipeline_keeps_ai_incomplete(self):
        with patch.object(r,'invoke',side_effect=AssertionError('Offline forbids inference')):
            report=self.run_review();self.assertEqual(report['ai_editorial_status'],'INCOMPLETE');self.assertEqual(report['overall_decision'],'REVISE')
            receipt=q.read(self.root/'result/review-generation-provenance.v01.json');self.assertFalse(receipt['live_inference_performed']);self.assertEqual(len(receipt['attempts']),2)
    def test_saved_response_replay_not_live(self):
        saved={}
        for role in r.ROLES:
            data=r.mock_response(self.requests[role]);data['media_observation']['video_examined']=True
            p=self.root/(role+'.saved.json');c.shared.write_json(p,data);saved[role]=p
        report=self.run_review(mode='saved_response_replay',saved=saved);self.assertEqual(report['ai_editorial_status'],'INCOMPLETE');self.assertEqual(report['ai']['video_observation'],'UNAVAILABLE')
    def test_no_paid_attempt_before_approval(self):
        with patch.object(r,'invoke') as fn:self.assertRaises(c.Error,self.run_review,mode='live_multimodal');fn.assert_not_called();self.assertFalse((self.root/'result').exists())
    def test_no_retry_after_failed_attempt(self):
        with patch.object(r,'invoke',side_effect=c.Error('Simulated offline failure')) as fn:
            report=self.run_review(mode='live_multimodal',approved=True);self.assertEqual(fn.call_count,1);self.assertEqual(report['ai_editorial_status'],'INCOMPLETE')
            receipt=q.read(self.root/'result/review-generation-provenance.v01.json');self.assertEqual(receipt['attempts'][0]['status'],'FAILED_NO_RETRY')
    def test_no_overwrite_after_failed_attempt(self):
        with patch.object(r,'invoke',side_effect=c.Error('Simulated offline failure')) as fn:
            self.run_review(mode='live_multimodal',approved=True);self.assertRaises(c.Error,self.run_review,mode='live_multimodal',approved=True);self.assertEqual(fn.call_count,1)
    def test_invalid_saved_role_rejected(self):
        p=self.root/'wrong.json';c.shared.write_json(p,r.mock_response(self.requests['original_source']))
        result=self.run_review(mode='saved_response_replay',saved={'edited_output':p,'original_source':p});self.assertEqual(result['ai_editorial_status'],'INCOMPLETE');self.assertEqual(result['ai']['output_review'],None)
    def test_human_feedback_survives_mock(self):
        before=[f for f in self.report['issues'] if f['origin']=='human_feedback'];after=[f for f in self.run_review()['issues'] if f['origin']=='human_feedback'];self.assertEqual(before,after)
    def test_saved_response_cannot_overwrite_output(self):
        self.run_review();self.assertRaises(c.Error,self.run_review)
    def test_model_edit_does_not_change_source_plan(self):
        before=q.ref(REAL/'preview-plan.v03.json');self.run_review();self.assertEqual(before,q.ref(REAL/'preview-plan.v03.json'))
    def test_invalid_mode_rejected(self):self.assertRaises(c.Error,self.run_review,mode='auto_approve')

class ReviewerDiagnostics(unittest.TestCase):
    setUp=ReviewerPipelineSafety.setUp
    run_review=ReviewerPipelineSafety.run_review
    def test_preserve_safe_untrusted_response_without_promotion(self):
        raw=json.dumps({'contract_version':'0.1.0','unsupported':True})
        with patch.object(r,'invoke',return_value=raw) as fn:
            result=self.run_review(mode='live_multimodal',approved=True);self.assertEqual(fn.call_count,1);self.assertEqual(result['ai_editorial_status'],'INCOMPLETE')
            self.assertEqual((self.root/'result/edited_output.untrusted-response.v01.txt').read_text(),raw)
            receipt=q.read(self.root/'result/review-generation-provenance.v01.json');self.assertEqual(receipt['attempts'][0]['failure_phase'],'response_validation')
    def test_source_only_is_not_output_review(self):
        result=self.run_review(roles=('original_source',));self.assertIsNone(result['ai']['output_review']);self.assertIsNotNone(result['ai']['source_review']);self.assertEqual(result['ai_editorial_status'],'INCOMPLETE')
    def test_invalid_role_not_invoked(self):
        with patch.object(r,'invoke') as fn:self.assertRaises(c.Error,self.run_review,roles=('both',));fn.assert_not_called()
    def test_explicit_existing_provider_and_model_bound_in_cli(self):
        with patch.object(r,'capture_inference',return_value='{}') as fn:
            r.invoke(self.requests['edited_output'],self.root/r.name('edited_output'),approved=True)
            command=fn.call_args.args[0]
            self.assertEqual(command[command.index('--model')+1],r.PROVIDER+'/'+r.MODEL)
            self.assertEqual(fn.call_args.kwargs['env']['MANDALA_VIDEO_ANALYSIS_MODE'],'quality_qa_v01')
            self.assertEqual(fn.call_args.kwargs['env']['MANDALA_VIDEO_QA_PROJECT_ROOT'],str(c.base.ROOT))
    def test_no_secret_diagnostic_artifact(self):
        with patch.object(r,'invoke',return_value='Bearer secret-test-value'):
            result=self.run_review(mode='live_multimodal',approved=True);self.assertEqual(result['ai_editorial_status'],'INCOMPLETE');self.assertFalse((self.root/'result/edited_output.untrusted-response.v01.txt').exists())


class ReportAIProvenance(unittest.TestCase):
    def test_unknown_ai_mode_rejected(self):
        p=q.empty_report();p['ai']['mode']='invented';self.assertRaises(c.Error,q.validate_report,p)
    def test_live_status_without_bound_observation_rejected(self):
        p=q.empty_report();p['ai']['mode']='live_multimodal';p['ai_editorial_status']='PASS';self.assertRaises(c.Error,q.validate_report,p)
    def test_validated_model_issue_merge_preserves_human(self):
        p=q.read(q.QA_ROOT/'showcase.v02'/q.REPORT);packet=q.read(q.QA_ROOT/'showcase.v02'/q.PACKET)
        responses={role:r.mock_response(r.make_request(packet,role)) for role in r.ROLES}
        for data in responses.values():data['media_observation']['video_examined']=True
        data=responses['edited_output'];data['issues']=[{'issue_id':'x','category':'hook','severity':'high','media_range':{'start_sec':0,'end_sec':1},'event_type':'model_candidate','evidence_refs':['media.output'],'basis':'model_media_observation','origin':'model_unverified','confidence':'low','human_confirmation':'not_confirmed','description':'Mock-only subjective opening observation','possible_cause':'Uncertain','recommendation':q.recommendation('plan_change','Review opening'),'timing_precision':'approximate'}]
        for role,data in responses.items():r.validate_response(data,r.make_request(packet,role),packet)
        result=r.merge(p,responses,mode='live_multimodal')
        self.assertEqual(result['overall_decision'],'REVISE');self.assertEqual(result['issues'][-1]['origin'],'model_unverified')
        self.assertEqual(len([f for f in result['issues'] if f['origin']=='human_feedback']),7)


if __name__=='__main__':unittest.main()
