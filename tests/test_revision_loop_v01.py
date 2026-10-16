"""Offline Stage 5.7 checks. All model/human objects below are synthetic fixtures."""
import atexit
import copy
from functools import cache
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'scripts'))
import run_revision_loop_v01 as loop
import revision_quality_v01 as quality
import renderer_revision_v02 as audio
import adaptive_director_v03_fixtures as fixtures

ri,core,qa=loop.ri,loop.core,loop.qa


def setUpModule():
    global network
    network=patch('socket.socket.connect',side_effect=AssertionError('Stage57 tests must remain offline'));network.start()


def tearDownModule():network.stop()


@cache
def source_fixture():
    ri.ROOT.mkdir(parents=True,exist_ok=True)
    temporary=tempfile.TemporaryDirectory(dir=ri.ROOT,prefix='stage57-source-test-')
    atexit.register(temporary.cleanup)
    source=Path(temporary.name)/'source.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
        'testsrc2=size=64x64:rate=30:duration=12','-f','lavfi','-i',
        'sine=frequency=440:sample_rate=48000:duration=12','-c:v','libx264',
        '-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],
        check=True,timeout=30)
    return source


def reference(uid):return {'path':'data/'+uid+'.json','sha256':'a'*64}


def sample():
    packet=fixtures.packet('absent','present')
    source=source_fixture()
    packet['source'].update(path=str(source.relative_to(PROJECT)),
        sha256=core.intake.gate.sha256_file(source))
    parent=fixtures.plan(packet)
    brief={'revision_id':'offline-revision','source':packet['source'],'parent_plan':reference('parent-plan'),
        'parent_render':reference('v1'),'qa_report':reference('qa'),'issues':[{'issue_id':'audio-1'}],
        'required_reviews':['Fresh human audiovisual review'],'inputs':{}}
    sound=audio.original_audio(packet['source']);sound.update(mode='continuous_source',
        source_range={'start_sec':0,'end_sec':12},gain_db=-8,fade_in_sec=.2,fade_out_sec=.3,
        evidence_refs=['canonical.segments.0'])
    plan=copy.deepcopy(parent);plan['editorial_concept']='OFFLINE MOCK revision; no live inference'
    proposal={'contract_version':'0.1.0','revision_id':brief['revision_id'],'new_plan_id':'offline-plan-2',
        'parent_plan':brief['parent_plan'],'parent_render':brief['parent_render'],'qa_report':brief['qa_report'],
        'brief_sha256':core.digest_object(brief),'plan':plan,'audio_timeline':sound,'operation_parameters':{},
        'change_log':[{'change':'Continuous source soundtrack candidate','issue_ids':['audio-1'],
            'expected_improvement':'Technical source mapping only; listening pending'}],
        'unresolved_risks':['OFFLINE MOCK; no actual quality assessment'],'required_reviews':['Human review'],
        'render_approved':False,'publish_approved':False}
    spec=audio.spec_for(parent,audio.original_audio(parent['source']))['visual_spec']
    registry={'operations':{'trim':{'status':'verified'},'concat':{'status':'verified'}}}
    return packet,parent,brief,proposal,spec,registry


class ProposalValidation(unittest.TestCase):
    def setUp(self):
        self.packet,self.parent,self.brief,self.proposal,self.spec,self.registry=sample()
        helper=patch.object(audio,'validate_source_audio',return_value={'audio_present':True});helper.start();self.addCleanup(helper.stop)
    def check(self):return loop.validate_proposal(self.proposal,self.brief,self.packet,self.parent,self.spec,self.registry)
    def blocked(self,reason=None):
        result=self.check();self.assertEqual(result['preview_status'],'BLOCKED')
        if reason:self.assertIn(reason,result['blocking_reasons'])
    def test_valid_revision_needs_preview_permission(self):self.assertEqual(self.check()['preview_status'],'NEEDS_SOURCE_BOUND_PREVIEW_PERMISSION')
    def test_audio_only_revision_is_meaningful(self):self.assertIn('independent_continuous_source_soundtrack',self.check()['actual_changes'])
    def test_no_production_approval(self):r=self.check();self.assertFalse(r['render_approved']);self.assertFalse(r['independent_plan_validation']['render_gate_passed'])
    def test_source_mismatch(self):self.proposal['plan']['source']['sha256']='b'*64;self.blocked('independent_plan_validation_blocked')
    def test_evidence_packet_mismatch(self):self.proposal['plan']['evidence_packet_sha256']='b'*64;self.blocked('independent_plan_validation_blocked')
    def test_parent_plan_substitution(self):self.proposal['parent_plan']=reference('wrong');self.blocked('revision_lineage_mismatch')
    def test_parent_output_substitution(self):self.proposal['parent_render']=reference('wrong');self.blocked('revision_lineage_mismatch')
    def test_brief_digest_substitution(self):self.proposal['brief_sha256']='b'*64;self.blocked('revision_lineage_mismatch')
    def test_unknown_plan_evidence(self):self.proposal['plan']['variants'][0]['shots'][0]['evidence_refs']=['invented'];self.blocked('independent_plan_validation_blocked')
    def test_unknown_soundtrack_evidence(self):self.proposal['audio_timeline']['evidence_refs']=['invented'];self.blocked('soundtrack_evidence_unknown')
    def test_missing_passage_evidence(self):self.proposal['audio_timeline']['evidence_refs']=[];self.blocked('soundtrack_passage_evidence_missing')
    def test_change_log_unknown_issue(self):self.proposal['change_log'][0]['issue_ids']=['invented'];self.blocked('change_log_ungrounded')
    def test_change_log_missing(self):self.proposal['change_log']=[];self.blocked('change_log_missing')
    def test_no_cosmetic_name_only_difference(self):self.proposal['audio_timeline']=audio.original_audio(self.packet['source']);self.blocked('no_meaningful_revision')
    def test_fabricated_beats_rejected(self):self.proposal['plan']['variants'][0]['audio_strategy']['sync_basis']='verified_beat_grid';self.blocked('independent_plan_validation_blocked')
    def test_unavailable_rhythm_rejected(self):self.proposal['plan']['variants'][0]['audio_strategy']['sync_basis']='estimated_rhythm';self.blocked('independent_plan_validation_blocked')
    def test_timing_precision_promotion_rejected(self):self.proposal['plan']['variants'][0]['shots'][0]['timing_precision']='frame_verified';self.blocked('independent_plan_validation_blocked')
    def test_model_renderer_certification_rejected(self):self.proposal['plan']['renderer_capabilities']['verification_status']='verified';self.blocked('independent_plan_validation_blocked')
    def test_model_passage_review_promotion_rejected(self):self.proposal['audio_timeline']['selection_basis']='human_reviewed_candidate';self.blocked('model_cannot_claim_fixture_or_human_passage_review')
    def test_missing_renderer_capability(self):self.registry['operations']['trim']['status']='available';self.blocked('capability_unverified:trim')
    def test_short_soundtrack(self):self.proposal['audio_timeline']['source_range']['end_sec']=10;self.blocked('execution_or_audio_mapping_invalid')
    def test_other_audio_asset(self):self.proposal['audio_timeline']['source']['sha256']='b'*64;self.blocked('execution_or_audio_mapping_invalid')
    def test_speech_replacement_blocked(self):self.packet['speech']['requirements']['overall_requirement']='required';self.proposal['plan']['evidence_packet_sha256']=loop.validator.packet_digest(self.packet);self.blocked('speech_audio_replacement_requires_separate_context_review')
    def test_self_authorized_render(self):self.proposal['render_approved']=True;self.blocked('revision_proposal_schema_invalid')
    def test_self_authorized_publish(self):self.proposal['publish_approved']=True;self.blocked('revision_proposal_schema_invalid')
    def test_no_phrase_verification(self):self.proposal['audio_timeline']['phrase_verified']=True;self.blocked('revision_proposal_schema_invalid')
    def test_no_rights_verification(self):self.proposal['audio_timeline']['publication_rights_verified']=True;self.blocked('revision_proposal_schema_invalid')
    def test_invalid_duration(self):self.proposal['plan']['variants'][0]['estimated_output_duration_sec']=11;self.blocked('independent_plan_validation_blocked')


class AudioContracts(unittest.TestCase):
    def setUp(self):self.packet,self.parent,_,self.proposal,_,_=sample();self.spec=audio.spec_for(self.proposal['plan'],self.proposal['audio_timeline'])
    def compile(self):return audio.compile_timeline(self.proposal['plan'],self.spec)
    def test_explicit_audio_source_output_mapping(self):m=self.compile()['audio_timeline'];self.assertEqual((m['source_start_sec'],m['output_start_sec'],m['output_end_sec']),(0,0,12))
    def test_audio_duration_equal_output(self):m=self.compile()['audio_timeline'];self.assertEqual(m['source_end_sec']-m['source_start_sec'],m['output_end_sec'])
    def test_missing_range_refused(self):self.spec['audio_timeline']['source_range']=None;self.assertRaises(core.Error,self.compile)
    def test_out_of_range_refused(self):self.spec['audio_timeline']['source_range']={'start_sec':1,'end_sec':13};self.assertRaises(core.Error,self.compile)
    def test_infinite_parameter_refused(self):self.spec['audio_timeline']['gain_db']=float('inf');self.assertRaises(core.Error,self.compile)
    def test_positive_gain_refused(self):self.spec['audio_timeline']['gain_db']=6;self.assertRaises(core.Error,self.compile)
    def test_missing_audio_stream_refused(self):self.assertRaises(core.Error,audio.filter_graph,self.compile(),False,PROJECT/'data/revisions/stage57',self.spec)
    def test_original_audio_preserves_legacy_timeline(self):spec=audio.spec_for(self.parent,audio.original_audio(self.parent['source']));t=audio.compile_timeline(self.parent,spec);t.pop('audio_timeline');self.assertEqual(t,core.compile_timeline(self.parent,spec['visual_spec']))
    def test_original_mode_orphan_range_rejected(self):self.spec['audio_timeline']['mode']='original';self.assertRaises(core.Error,self.compile)
    def test_silent_mode_with_bed_rejected(self):self.spec['visual_spec']['output']['audio_mode']='silent';self.assertRaises(core.Error,self.compile)
    def test_disabled_mix_cannot_carry_orphan_gain(self):self.spec['audio_timeline']['original_gain_db']=-60;self.assertRaises(core.Error,self.compile)
    def test_no_per_visual_join_audio_concat(self):g=audio.filter_graph(self.compile(),True,PROJECT/'data/revisions/stage57',self.spec)[0];self.assertNotIn('concat=n=2:v=0:a=1',g);self.assertIn('[0:a]atrim=start=0:end=12',g)
    def test_audio_qa_uses_continuous_not_visual_mapping(self):ctx={'timeline':self.compile(),'spec':self.spec};t,_=quality.audio_analysis_context(ctx);self.assertEqual(len(t['shots']),1);self.assertEqual(t['shots'][0]['source_start_sec'],0)


class ContractComposition(unittest.TestCase):
    def setUp(self):self.packet,self.parent,self.brief,self.proposal,_,self.registry=sample()
    def test_embedded_plan_operation_refs_resolve_offline(self):self.proposal['plan']['variants'][0]['operations']=[fixtures.operation()];ri.check('proposal',self.proposal)
    def test_factored_schema_accepts_same_valid_operations(self):
        from render_test_fixtures_v01 import definition,NAMES
        original=ri.contracts()['$defs']['proposal'];factored=loop.model_schema()
        for name in NAMES:
            for operation in definition(name)['operations']:
                with self.subTest(name=name,kind=operation['kind']):
                    data=copy.deepcopy(self.proposal);data['plan']['variants'][0]['operations']=[operation]
                    core.base.validate_object(data,original,'original');core.base.validate_object(data,factored,'factored')
    def test_factoring_does_not_admit_invalid_parameters(self):
        from render_test_fixtures_v01 import definition,NAMES
        for name in NAMES:
            for operation in definition(name)['operations']:
                data=copy.deepcopy(self.proposal);bad=copy.deepcopy(operation);bad['parameters']['unsupported_filter']='OFFLINE injection fixture';data['plan']['variants'][0]['operations']=[bad]
                with self.subTest(name=name,kind=bad['kind']):
                    self.assertRaises(core.Error,core.base.validate_object,data,ri.contracts()['$defs']['proposal'],'original')
                    self.assertRaises(core.Error,core.base.validate_object,data,loop.model_schema(),'factored')
    def test_factored_schema_smaller_without_relaxed_fields(self):self.assertLess(len(json.dumps(loop.model_schema())),len(json.dumps(ri.contracts()['$defs']['proposal'])))
    def test_unsupported_operation_rejected_in_both(self):
        data=copy.deepcopy(self.proposal);op=fixtures.operation();op['kind']='arbitrary_script';data['plan']['variants'][0]['operations']=[op]
        for schema in (loop.model_schema(),ri.contracts()['$defs']['proposal']):self.assertRaises(core.Error,core.base.validate_object,data,schema,'offline fixture')


class IntelligenceProvenance(unittest.TestCase):
    def item(self,category='audio',origin='human_feedback',confirmation='confirmed_user_handoff',severity='high'):
        return {'issue_id':'fixture-issue','category':category,'origin':origin,'human_confirmation':confirmation,'severity':severity}
    def test_only_confirmed_audio_is_user_confirmed(self):self.assertEqual(ri.classified(self.item()),'confirmed_user')
    def test_earlier_visual_not_promoted(self):self.assertEqual(ri.classified(self.item('visual')),'prior_editorial_unverified')
    def test_unconfirmed_handoff_not_promoted(self):self.assertEqual(ri.classified(self.item(confirmation='not_confirmed')),'prior_editorial_unverified')
    def test_model_not_human(self):self.assertEqual(ri.classified(self.item(origin='model_unverified',confirmation='not_confirmed')),'model_unverified')
    def test_signal_not_human(self):self.assertEqual(ri.classified(self.item(origin='signal_measurement',confirmation='not_confirmed')),'signal_measurement')
    def test_integrity_priority_before_music(self):self.assertLess(ri.priority(self.item('integrity',severity='critical')),ri.priority(self.item()))
    def test_music_priority_before_cosmetics(self):self.assertLess(ri.priority(self.item()),ri.priority(self.item('visual',severity='low')))
    def test_identifier_path_traversal(self):self.assertRaises(core.Error,ri.identifier,'../escape')
    def test_identifier_filter_injection(self):self.assertRaises(core.Error,ri.identifier,'foo;bar')
    def test_duplicate_issues_rejected_by_qa_contract(self):
        p=qa.empty_report();i=qa.issue('audio','fixture','fixture',evidence=['fixture']);i['issue_id']='same';p['evidence_ledger']['fixture']={};p['issues']=[i,i];self.assertRaises(core.Error,qa.validate_report,p)
    def test_unknown_issue_reference_rejected(self):p=qa.empty_report();i=qa.issue('audio','fixture','fixture',evidence=['invented']);i['issue_id']='one';p['issues']=[i];self.assertRaises(core.Error,qa.validate_report,p)


class BriefIntake(unittest.TestCase):
    def setUp(self):
        packet,plan,_,_,spec,_=sample();self.timeline=core.compile_timeline(plan,spec)
        self.ctx={'plan':plan,'timeline':self.timeline,'inputs':{'source':{k:plan['source'][k] for k in ('path','sha256')},
            'rendered_output':{'path':'data/mock-v1.mp4','sha256':'b'*64},'plan':reference('mock-parent-plan'),
            'spec':reference('mock-spec'),'timeline':reference('mock-timeline'),'manifest':reference('mock-manifest')}}
        self.report=qa.empty_report();self.report.update(source=self.ctx['inputs']['source'],rendered_output=self.ctx['inputs']['rendered_output'],
            inputs={**self.ctx['inputs'],'capabilities':reference('mock-capabilities')})
        self.report['technical']={'duration_sec':12,'timeline':self.timeline}
        self.report['human']['performed']=True;self.report['evidence_ledger']['human.feedback']={}
        issue=qa.issue('audio','fixture','OFFLINE synthetic user music concern',{'start_sec':3.35,'end_sec':3.65},
            origin='human_feedback',severity='high',evidence=['human.feedback']);issue.update(issue_id='audio-1',human_confirmation='confirmed_user_handoff')
        issue['source_ranges']=qa.source_ranges(issue['output_range'],self.timeline)
        earlier=copy.deepcopy(issue);earlier.update(issue_id='old-hook',category='hook',human_confirmation='not_confirmed',description='OFFLINE earlier editorial concern')
        self.report['issues']=[issue,earlier];qa.assess(self.report)
        self.report['ai']['output_review']={'dimensions':{'hook':{'status':'PASS'}}}  # Offline disagreement fixture, never a live receipt.
        p=patch.object(ri,'refs_match');p.start();self.addCleanup(p.stop)
    def brief(self):return ri.make_brief('offline-brief',self.report,self.ctx,reference('mock-qa'),reference('mock-audio-proof'))
    def test_valid_qa_intake(self):b=self.brief();self.assertEqual(len(b['issues']),2);self.assertEqual(b['parent_plan'],self.ctx['inputs']['plan'])
    def test_source_hash_contamination(self):self.report['source']={**self.report['source'],'sha256':'c'*64};self.assertRaises(core.Error,self.brief)
    def test_output_hash_contamination(self):self.report['rendered_output']={**self.report['rendered_output'],'sha256':'c'*64};self.assertRaises(core.Error,self.brief)
    def test_parent_plan_mismatch(self):self.report['inputs']['plan']=reference('wrong-plan');self.assertRaises(core.Error,self.brief)
    def test_parent_manifest_mismatch(self):self.report['inputs']['manifest']=reference('wrong-render');self.assertRaises(core.Error,self.brief)
    def test_duplicate_selected_issues(self):self.report['issues'].append(copy.deepcopy(self.report['issues'][0]));self.assertRaises(core.Error,self.brief)
    def test_unknown_issue_evidence(self):self.report['issues'][0]['evidence_refs']=['unknown'];self.assertRaises(core.Error,self.brief)
    def test_conflict_preserves_both(self):c=self.brief()['conflicts'][0];self.assertEqual(c['model_status'],'PASS');self.assertEqual(c['historical_issue_ids'],['old-hook']);self.assertEqual(c['resolution'],'UNRESOLVED_PRESERVE_BOTH')
    def test_confirmed_audio_precedes_old_hook(self):b=self.brief();self.assertEqual(b['issues'][0]['provenance'],'confirmed_user');self.assertEqual(b['issues'][1]['provenance'],'prior_editorial_unverified')
    def test_source_output_timestamps_preserved(self):b=self.brief();self.assertEqual(b['issues'][0]['source_ranges'],self.report['issues'][0]['source_ranges']);self.assertEqual(b['issues'][0]['output_range'],self.report['issues'][0]['output_range'])
    def test_reviews_are_required(self):b=self.brief();self.assertTrue(b['constraints']['human_audio_review_required']);self.assertTrue(b['required_reviews']);self.assertFalse(b['render_approved'])


class CheckpointsAndLoop(unittest.TestCase):
    def setUp(self):
        ri.ROOT.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=ri.ROOT,prefix='offline-loop-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        root_patch=patch.object(ri,'ROOT',self.root);root_patch.start();self.addCleanup(root_patch.stop)
        self.job=self.root/'job';self.job.mkdir();self.packet,self.parent,self.brief,self.proposal,self.parent_spec,self.registry=sample()
        core.shared.write_json(self.job/'parent.json',self.parent);core.shared.write_json(self.job/'parent-spec.json',self.parent_spec)
        core.shared.write_json(self.job/'registry.json',self.registry)
        self.brief.update(parent_plan=qa.ref(self.job/'parent.json'),renderer_capabilities=qa.ref(self.job/'registry.json'),audio_capability=reference('mock-audio-capability'),inputs={'spec':qa.ref(self.job/'parent-spec.json')})
        self.proposal.update(parent_plan=self.brief['parent_plan'],brief_sha256=core.digest_object(self.brief))
        core.shared.write_json(self.job/loop.BRIEF,self.brief)
        core.shared.write_json(self.job/loop.REQUEST,{'initial_director_calls':1,'initial_reviewer_calls':1,'initial_renders':1,'target_output':'data/render-tests/stage57/offline-mock'})
        core.base.write_exclusive(self.job/loop.PROMPT,'OFFLINE MOCK; no live model access')
        self.state=loop.checkpoint(self.job,None,status='WAITING_FOR_APPROVAL',reason='Offline fixture')
        self.response=self.root/'response.json';self.save_response()
        for name,target,value in [('load_job',loop,None),('validate_capability',audio,{}),('validate_source_audio',audio,{'audio_present':True})]:
            if name=='load_job':p=patch.object(target,name,side_effect=lambda job:(self.job,loop.load_state(self.job)[1],qa.read(self.job/loop.REQUEST),self.brief,self.packet))
            else:p=patch.object(target,name,return_value=value)
            p.start();self.addCleanup(p.stop)
    def save_response(self):self.response.write_text(json.dumps(self.proposal))
    def submit(self,**kw):return loop.submit(self.job,response_file=self.response,**kw)
    def test_one_successful_offline_iteration(self):s=self.submit();self.assertEqual(s['state'],'READY_FOR_PREVIEW');self.assertEqual(s['attempt_count'],1)
    def test_offline_generation_never_claims_live(self):self.submit();g=qa.read(self.job/'attempt.01'/loop.GENERATION);self.assertEqual(g['mode'],'offline_fixture');self.assertFalse(g['live_inference_performed']);self.assertEqual(g['wrapper_invocations'],0)
    def test_original_raw_response_preserved(self):self.submit();self.assertEqual((self.job/'attempt.01/untrusted-response.v01.txt').read_text(),self.response.read_text())
    def test_independent_validation_persisted(self):self.submit();v=qa.read(self.job/'attempt.01'/loop.VALIDATION);self.assertFalse(v['independent_plan_validation']['render_gate_passed'])
    def test_no_network_for_offline_plan(self):
        with patch.object(loop.director,'live_response',side_effect=AssertionError('network forbidden')):self.assertEqual(self.submit()['state'],'READY_FOR_PREVIEW')
    def test_missing_paid_authorization_stops_without_call(self):
        with patch.object(loop.director,'live_response') as fn:s=loop.submit(self.job);fn.assert_not_called()
        self.assertEqual(s['state'],'PERMISSION_BLOCKED');self.assertEqual(s['attempt_count'],0)
    def test_permission_blocked_can_resume_offline(self):loop.submit(self.job);self.assertEqual(self.submit()['state'],'READY_FOR_PREVIEW')
    def test_model_failure_consumes_call_not_attempt(self):
        with patch.object(loop.director,'live_response',side_effect=core.Error('offline simulated provider failure')) as fn:s=loop.submit(self.job,permission_text='OFFLINE simulated human authorization');self.assertEqual(fn.call_count,1)
        self.assertEqual(s['state'],'INFERENCE_UNAVAILABLE');self.assertEqual(s['remaining_budget']['director_calls'],0);self.assertEqual(s['attempt_count'],0)
    def test_budget_exhaustion_before_call(self):
        loop.checkpoint(self.job,self.state,status='WAITING_FOR_APPROVAL',reason='Offline exhausted budget',budget={**self.state['remaining_budget'],'director_calls':0})
        with patch.object(loop.director,'live_response') as fn:s=loop.submit(self.job,permission_text='OFFLINE');fn.assert_not_called()
        self.assertEqual(s['state'],'BLOCKED')
    def test_invalid_plan_counted_at_validation(self):self.proposal['plan']['source']['sha256']='b'*64;self.save_response();s=self.submit();self.assertEqual(s['state'],'PLAN_REJECTED');self.assertEqual(s['attempt_count'],1)
    def test_two_bounded_distinct_attempts(self):
        self.proposal['plan']['evidence_packet_sha256']='b'*64;self.save_response();self.assertEqual(self.submit()['state'],'PLAN_REJECTED')
        self.proposal['plan']['evidence_packet_sha256']=loop.validator.packet_digest(self.packet);self.save_response();s=self.submit();self.assertEqual(s['attempt_count'],2)
        self.assertEqual(self.submit()['state'],'BLOCKED');self.assertEqual(len(loop.lineage_records(self.brief)[1]),2)
    def test_repeated_rejected_plan_stops(self):self.proposal['plan']['evidence_packet_sha256']='b'*64;self.save_response();self.submit();s=self.submit();self.assertEqual(s['state'],'BLOCKED');self.assertEqual(s['attempt_count'],1)
    def test_malformed_response_not_presented_as_plan(self):self.response.write_text('{bad');s=self.submit();self.assertEqual(s['state'],'PLANNING_FAILED');self.assertEqual(s['attempt_count'],0);self.assertFalse((self.job/'attempt.01').exists())
    def test_secret_like_response_not_persisted(self):self.response.write_text('Bearer synthetic-secret-value');self.assertEqual(self.submit()['state'],'PLANNING_FAILED');self.assertFalse((self.job/'attempt.01').exists())
    def test_offline_proposal_cannot_authorize_real_render(self):self.submit();self.assertRaises(core.Error,loop.authorize_preview,self.job,'OFFLINE simulated permission')
    def test_missing_preview_permission_stops_before_encoder(self):
        self.submit()
        with patch.object(audio,'encode') as fn:s=loop.render_preview(self.job);fn.assert_not_called()
        self.assertEqual(s['state'],'PERMISSION_BLOCKED')
    def test_resource_exhaustion_stops(self):s=copy.deepcopy(self.state);s['remaining_budget']['processing_sec']=0;self.assertEqual(loop.allowed_next(s,'plan'),'RESOURCE_BUDGET_EXHAUSTED')
    def test_two_attempt_limit_even_when_budget_remains(self):s=copy.deepcopy(self.state);s['attempt_count']=2;self.assertEqual(loop.allowed_next(s,'plan'),'MAXIMUM_ATTEMPTS_EXHAUSTED')
    def test_render_failure_cannot_silently_retry(self):s=copy.deepcopy(self.state);s['state']='RENDER_FAILED';self.assertEqual(loop.allowed_next(s,'render'),'PLAN_NOT_READY_FOR_PRIVATE_PREVIEW')
    def test_qa_without_new_mp4_rejected(self):self.assertEqual(loop.allowed_next(self.state,'qa'),'NO_NEW_RENDER_TO_REVIEW')
    def test_pending_human_review_cannot_accept(self):s=loop.checkpoint(self.job,self.state,status='NEEDS_REVIEW',reason='Offline pending human');self.assertTrue(s['human_review_pending']);self.assertFalse(s['production_eligible'])
    def test_attempt_history_tamper_rejected(self):p=self.job/'checkpoint.001.json';data=qa.read(p);data['attempt_count']=1;p.write_text(json.dumps(data));self.assertRaises(core.Error,loop.load_state,self.job)
    def test_initial_budget_tamper_rejected(self):p=self.job/'checkpoint.001.json';data=qa.read(p);data['remaining_budget']['director_calls']=2;p.write_text(json.dumps(data));self.assertRaises(core.Error,loop.load_state,self.job)
    def test_checkpoint_chain_tamper_rejected(self):loop.checkpoint(self.job,self.state,status='WAITING_FOR_APPROVAL',reason='Offline');p=self.job/'checkpoint.001.json';data=qa.read(p);data['reason']='tampered';p.write_text(json.dumps(data));self.assertRaises(core.Error,loop.load_state,self.job)
    def test_fake_production_state_rejected(self):state=copy.deepcopy(self.state);state['production_eligible']=True;self.assertRaises(core.Error,ri.check,'state',state)
    def test_checkpoint_overwrite_refused(self):self.assertRaises(core.Error,loop.checkpoint,self.job,None,status='WAITING_FOR_APPROVAL',reason='No overwrite')
    def test_advance_without_authorizations_does_no_work(self):
        with patch.object(loop,'submit') as fn:s=loop.advance(self.job);fn.assert_not_called()
        self.assertEqual(s['state'],'WAITING_FOR_APPROVAL')
    def test_global_baseline_limit_cannot_reset_with_new_job(self):
        loop.reserve_attempt(self.job,self.brief,'b'*64);loop.reserve_attempt(self.job,self.brief,'c'*64)
        self.assertRaises(core.Error,loop.reserve_attempt,self.root/'new-job',self.brief,'d'*64)
    def test_cli_lock_reusable_after_release(self):
        with loop.revision_lock():self.assertTrue((self.root/'.loop.lock').is_file())
        with loop.revision_lock():self.assertTrue((self.root/'.loop.lock').is_file())


class ComparisonSafety(unittest.TestCase):
    def setUp(self):
        self.packet,self.parent_plan,_,proposal,_,_=sample();self.new_plan=proposal['plan'];self.spec=audio.spec_for(self.new_plan,proposal['audio_timeline'])
        self.parent=qa.empty_report();self.parent['source']=reference('source');self.parent['rendered_output']=reference('v1');self.parent['technical']={'duration_sec':12,'audio':{'boundaries':[{'source_jump_sec':10.4}]}}
        self.new=copy.deepcopy(self.parent);self.new['rendered_output']={'path':'data/v2.mp4','sha256':'b'*64};self.new['integrity']={'status':'PASS'}
    def compare(self):return quality.compare(self.parent,self.new,reference('qa-v1'),reference('qa-v2'),self.parent_plan,self.new_plan,self.spec)
    def test_mapping_improvement_not_artistic_pass(self):r=self.compare();self.assertEqual(r['improvement_claim'],'TECHNICAL_MAPPING_IMPROVED_ONLY');self.assertEqual(r['decision'],'NEEDS_REVIEW')
    def test_human_review_pending(self):self.assertTrue(self.compare()['human_review_pending'])
    def test_old_confirmation_not_copied_to_new(self):
        i=qa.issue('audio','old','OFFLINE old human issue',origin='human_feedback',severity='high',evidence=['fixture']);i['issue_id']='old';i['human_confirmation']='confirmed_user_handoff';self.parent['evidence_ledger']['fixture']={};self.parent['issues']=[i];self.parent['human']['performed']=True;qa.assess(self.parent)
        r=self.compare();self.assertEqual(len(r['historical_human_findings']),1);self.assertEqual(r['new_issues'],[]);self.assertTrue(r['human_review_pending'])
    def test_source_substitution_rejected(self):self.new['source']=reference('wrong');self.assertRaises(core.Error,self.compare)
    def test_same_output_not_v2(self):self.new['rendered_output']=self.parent['rendered_output'];self.assertRaises(core.Error,self.compare)
    def test_new_critical_defect_blocks(self):
        self.new['evidence_ledger']['test']={};i=qa.issue('integrity','bad','OFFLINE corrupt result',severity='critical',origin='deterministic_validation',evidence=['test']);i['issue_id']='bad';self.new['issues']=[i];qa.assess(self.new)
        self.assertEqual(self.compare()['decision'],'BLOCKED');self.assertEqual(self.compare()['improvement_claim'],'REGRESSION_DETECTED')
    def test_new_high_model_issue_requires_revision_not_verified_regression(self):
        self.new['evidence_ledger']['test']={};i=qa.issue('audio','bad','OFFLINE unverified model concern',severity='high',origin='model_unverified',evidence=['test']);i['issue_id']='bad';self.new['issues']=[i];qa.assess(self.new)
        self.assertEqual(self.compare()['decision'],'REVISE');self.assertEqual(self.compare()['improvement_claim'],'NOT_ESTABLISHED')
    def test_original_audio_no_improvement_assumed(self):self.spec['audio_timeline']=audio.original_audio(self.new_plan['source']);self.assertEqual(self.compare()['improvement_claim'],'NOT_ESTABLISHED')
    def test_existing_continuous_audio_not_automatically_improved(self):self.parent['technical']['audio']['boundaries']=[];self.assertEqual(self.compare()['improvement_claim'],'NOT_ESTABLISHED')
    def test_acceptance_never_production(self):r=self.compare();self.assertFalse(r['production_eligible']);self.assertFalse(r['publish_approved'])
    def test_measured_media_changes_do_not_certify_editorial_quality(self):
        self.parent['technical']['video']={'sampling':{'sample_rgb_sha256':'a'*64}}
        self.new['technical']['video']={'sampling':{'sample_rgb_sha256':'b'*64}}
        self.parent['technical']['audio'].update(rms=.25,peak=.8,pcm_sha256='a'*64)
        self.new['technical']['audio'].update(rms=.125,peak=.7,pcm_sha256='b'*64,boundaries=[])
        result=self.compare();measured=result['measured_changes']
        self.assertEqual(measured['status'],'COMPARED')
        self.assertAlmostEqual(measured['audio_rms_change_db'],-6.021,places=3)
        self.assertEqual((measured['parent_audio_source_jumps'],measured['revised_audio_source_jumps']),(1,0))
        self.assertTrue(measured['decoded_audio_changed'])
        self.assertTrue(measured['sampled_video_changed'])
        self.assertEqual(result['decision'],'NEEDS_REVIEW')
    def test_missing_media_measurements_remain_unavailable(self):
        self.assertEqual(self.compare()['measured_changes']['status'],'UNAVAILABLE')
    def test_missing_source_jump_is_not_counted_as_continuity(self):
        for report,sha in ((self.parent,'a'),(self.new,'b')):
            report['technical']['video']={'sampling':{'sample_rgb_sha256':sha*64}}
            report['technical']['audio'].update(rms=.1,peak=.5,pcm_sha256=sha*64)
        self.parent['technical']['audio']['boundaries']=[{}]
        self.new['technical']['audio']['boundaries']=[]
        self.assertEqual(self.compare()['measured_changes']['status'],'UNAVAILABLE')
    def test_invalid_media_measurement_rejected(self):
        self.parent['technical']['video']={'sampling':{'sample_rgb_sha256':'a'*64}}
        self.new['technical']['video']={'sampling':{'sample_rgb_sha256':'b'*64}}
        self.parent['technical']['audio'].update(rms=float('nan'),peak=.8,pcm_sha256='a'*64)
        self.new['technical']['audio'].update(rms=.1,peak=.7,pcm_sha256='b'*64,boundaries=[])
        self.assertRaises((core.Error,ValueError),self.compare)

    def test_revision_prompt_has_no_showcase_specific_claim(self):
        prompt=(Path(__file__).resolve().parents[1]/'openclaw/prompts/adaptive-director-revision-v01.md').read_text()
        self.assertIn('Apply the actual speech eligibility',prompt)
        self.assertIn('Choose duration',prompt)
        self.assertNotIn('Two V1 music interruptions',prompt)
        self.assertNotIn('10–15 s',prompt)


class SecurityAndPublication(unittest.TestCase):
    def setUp(self):ri.ROOT.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=ri.ROOT,prefix='security-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_path_traversal(self):self.assertRaises(core.Error,core.new_directory,self.root/'foo/../out',ri.ROOT)
    def test_symlink_escape(self):p=self.root/'escape';p.symlink_to('/tmp');self.assertRaises(core.Error,core.new_directory,p/'out',ri.ROOT)
    def test_secret_path(self):self.assertRaises(core.Error,core.safe_path,self.root/'.env.asr',output=True)
    def test_existing_output_protected(self):out=self.root/'out';out.mkdir();(out/'keep').write_text('keep');self.assertRaises(core.Error,audio.publish,out,{}, {},ri.ROOT);self.assertEqual((out/'keep').read_text(),'keep')
    def test_atomic_publication_rollback(self):
        source=self.root/'binary';source.write_bytes(b'SYNTHETIC');out=self.root/'out'
        with patch.object(core.shared,'write_json',side_effect=OSError('OFFLINE write failure')):self.assertRaises(OSError,audio.publish,out,{'test.bin':source},{'test.json':{}},ri.ROOT)
        self.assertFalse(out.exists());self.assertEqual(source.read_bytes(),b'SYNTHETIC')
    def test_binary_filename_traversal(self):source=self.root/'binary';source.write_bytes(b'SYNTHETIC');self.assertRaises(core.Error,audio.publish,self.root/'out',{'../escape':source},{},ri.ROOT);self.assertFalse((self.root/'out').exists())
    def test_bounded_stdout(self):self.assertRaises(core.Error,core.run,[sys.executable,'-c','print("x"*10000)'],max_bytes=20)
    def test_subprocess_timeout(self):self.assertRaises(core.Error,core.run,[sys.executable,'-c','import time;time.sleep(2)'],{**core.DEFAULT_RESOURCES,'timeout_sec':.05})
    def test_cpu_and_memory_limits_are_in_command(self):cmd=core.prlimit_command(['true'],core.DEFAULT_RESOURCES);self.assertTrue(any(s.startswith('--as=') for s in cmd));self.assertTrue(any(s.startswith('--cpu=') for s in cmd))
    def test_audio_encoder_has_closed_admission(self):
        _,_,_,proposal,_,_=sample();spec=audio.spec_for(proposal['plan'],proposal['audio_timeline'])
        self.assertRaises(core.Error,audio.encode,PROJECT/'data/test-videos/cinematic-7693770515172887829.mp4',proposal['plan'],spec,self.root,mode='PRODUCTION',context={})


class RealSyntheticAudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.TEST_ROOT.mkdir(parents=True,exist_ok=True);cls.temp=tempfile.TemporaryDirectory(dir=core.TEST_ROOT,prefix='stage57-tests-');cls.addClassCleanup(cls.temp.cleanup);cls.root=Path(cls.temp.name)
        cls.manifests={name:audio.self_test(name,cls.root/name) for name in ('replace','mix')}
        cls.proofs=[qa.ref(cls.root/name/audio.MANIFEST) for name in ('replace','mix')]
        cls.registry=audio.capability(cls.proofs)
    def test_both_actual_mp4s(self):self.assertTrue(all((self.root/name/'render.mp4').stat().st_size>1024 for name in self.manifests))
    def test_visual_reordering_preserved(self):self.assertEqual(self.manifests['replace']['fixture_measurements']['visual_scene_order'],[2,0,1])
    def test_audio_tones_independent_of_visual_cuts(self):self.assertTrue(all(abs(a-b)<15 for a,b in zip(self.manifests['replace']['fixture_measurements']['audio_tones_hz'],[440,660,880])))
    def test_explicit_gain_measured(self):self.assertAlmostEqual(self.manifests['replace']['fixture_measurements']['gain_ratio'],10**(-8/20),delta=.02)
    def test_endpoint_fades_measured(self):self.assertTrue(self.manifests['replace']['fixture_measurements']['endpoint_fades_measured'])
    def test_mix_measured_and_no_clipping(self):m=self.manifests['mix']['fixture_measurements'];self.assertTrue(m['mix_original']);self.assertLess(m['peak_linear'],.999)
    def test_full_decode_pts_codecs_and_duration(self):
        for manifest in self.manifests.values():
            self.assertTrue(manifest['verification']['decoded_to_completion']);self.assertTrue(manifest['verification']['presentation_timestamps_continuous']);self.assertEqual(manifest['output']['duration_sec'],6);self.assertEqual(manifest['output']['audio_codec'],'aac');self.assertEqual(manifest['output']['video_codec'],'h264')
    def test_mapping_measured_near_visual_joins(self):m=self.manifests['replace']['audio_mapping_verification'];self.assertEqual(m['status'],'CONTINUOUS_SOURCE_MAPPING');self.assertTrue(any(r['output_time_sec']==2 for r in m['records']));self.assertTrue(all(r['correlation'] is None or r['correlation']>.9 for r in m['records']))
    def test_capability_proof_replayed_not_availability(self):self.assertEqual(self.registry['status'],'verified');self.assertEqual(len(self.registry['proofs']),2);self.assertFalse(self.registry['production_eligible'])
    def test_capability_tamper_refused(self):r=copy.deepcopy(self.registry);r['proofs'][0]['sha256']='0'*64;p=self.root/'tampered.json';core.shared.write_json(p,r);self.assertRaises(core.Error,audio.validate_capability,p)
    def test_no_musical_phrase_certification(self):self.assertFalse(self.manifests['replace']['audio_mapping_verification']['musical_phrase_verified'])
    def test_work_cleanup(self):self.assertEqual(list(self.root.glob('.revision-work-*')),[])
    def test_existing_output_refusal(self):self.assertRaises(core.Error,audio.self_test,'replace',self.root/'replace')
    def test_missing_audio_source_refused(self):
        from render_test_fixtures_v01 import generate_source
        with tempfile.TemporaryDirectory(dir=self.root,prefix='.revision-work-') as tmp:
            source=generate_source(Path(tmp),'silent',core.DEFAULT_RESOURCES);p=qa.read(self.root/'replace'/audio.PLAN);p['source']['sha256']=core.intake.gate.sha256_file(source);s=audio.spec_for(p,audio.fixture_audio(p['source'],'replace'));self.assertRaises(core.Error,audio.validate_source_audio,source,p,s)
    def test_replacement_audio_without_headroom_refused_before_render(self):
        plan=qa.read(self.root/'replace'/audio.PLAN);spec=qa.read(self.root/'replace'/audio.SPEC)
        spec['audio_timeline']['gain_db']=0
        with patch.object(core,'audio_pcm',return_value=np.full(6*48000,1.2,dtype=np.float32)):
            self.assertRaisesRegex(core.Error,'headroom',audio.validate_source_audio,self.root/'replace'/'source.mp4',plan,spec)


if __name__=='__main__':unittest.main()
