"""Deterministic Stage 5.8 tests; mocks/synthetic controls are not editorial evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'scripts'))
import benchmark_evidence_v01 as e
import benchmark_preview_v01 as preview
import run_benchmark_v01 as bench
import adaptive_director_v03_fixtures as fixtures
import renderer_revision_v02 as audio

core,qa=e.core,e.qa


def setUpModule():
    global network
    network=patch('socket.socket.connect',side_effect=AssertionError('Benchmark tests must stay offline'));network.start()


def tearDownModule():network.stop()


def ref(name):return {'path':'data/'+name,'sha256':'a'*64}


def context():
    packet=fixtures.packet('absent','present');plan=fixtures.plan(packet)
    spec=audio.spec_for(plan,audio.original_audio(plan['source']))
    timeline=audio.compile_timeline(plan,spec)
    source={k:plan['source'][k] for k in ('path','sha256')}
    return packet,plan,spec,timeline,source


class RangeMapping(unittest.TestCase):
    def setUp(self):self.packet,self.plan,self.spec,self.timeline,self.source=context()
    def mapping(self,a=1,b=2):return e.map_ranges(e.window(a,b),self.timeline,self.source,self.spec,source_has_audio=True)
    def continuous(self,mix=False):
        self.spec['audio_timeline'].update(mode='continuous_source',source_range=e.window(0,12),mix_original=mix,
            fade_in_sec=.1,fade_out_sec=.5,gain_db=-9)
        self.timeline=audio.compile_timeline(self.plan,self.spec)
    def test_per_shot_audio(self):m=self.mapping();self.assertEqual(m['audio_components'][0]['source_range'],m['visual_components'][0]['source_range'])
    def test_continuous_differs_from_visual(self):
        self.continuous();first=copy.deepcopy(self.timeline['shots'][0]);second=copy.deepcopy(first)
        first.update(source_start_sec=6,source_end_sec=12,output_end_sec=6,freeze_output_start_sec=6)
        second.update(shot_id='second',source_start_sec=0,source_end_sec=6,output_start_sec=6)
        self.timeline['shots']=[first,second];m=self.mapping(10,10.4)
        self.assertEqual(m['audio_components'][0]['source_range'],e.window(10,10.4));self.assertEqual(m['visual_components'][0]['source_range'],e.window(4,4.4))
    def test_continuous_contributes_one_component(self):self.continuous();self.assertEqual(len(self.mapping()['audio_components']),1)
    def test_mixed_preserves_each_component(self):self.continuous(True);m=self.mapping();self.assertEqual(len(m['audio_components']),2);self.assertEqual({c['kind'] for c in m['audio_components']},{'continuous_audio_bed','source_passage'})
    def test_mixed_gain_is_explicit(self):self.continuous(True);self.spec['audio_timeline']['original_gain_db']=-18;self.assertEqual(self.mapping()['audio_components'][1]['treatment']['original_gain_db'],-18)
    def test_fades_do_not_change_source_range(self):self.continuous();m=self.mapping(.01,.05)['audio_components'][0];self.assertEqual(m['source_range'],e.window(.01,.05));self.assertEqual(m['treatment']['fade_in_sec'],.1)
    def test_speed_adjusted_mapping(self):s=self.timeline['shots'][0];s['speed']=1.25;s['source_end_sec']=20;self.assertEqual(self.mapping()['audio_components'][0]['source_range'],e.window(s['source_start_sec']+1.25,s['source_start_sec']+2.5))
    def test_overlapping_shots_separate(self):s=copy.deepcopy(self.timeline['shots'][0]);s['shot_id']='overlap';self.timeline['shots'].append(s);self.assertEqual(len(self.mapping()['audio_components']),2)
    def test_freeze_visual_point_not_future_audio(self):s=self.timeline['shots'][0];s['freeze_output_start_sec']=1.5;self.assertEqual(self.mapping()['visual_components'][-1]['kind'],'held_frame');self.assertEqual(self.mapping()['audio_components'][-1]['kind'],'planned_silence')
    def test_missing_audio_provenance_unavailable(self):self.spec['visual_spec']['output'].pop('audio_mode');m=self.mapping();self.assertEqual(m['audio_status'],'UNAVAILABLE');self.assertEqual(m['unmapped_audio'],[e.window(1,2)])
    def test_silent_output_explicit(self):self.spec['visual_spec']['output']['audio_mode']='silent';self.assertEqual(self.mapping()['audio_status'],'SILENT')
    def test_no_timestamp_invented(self):m=e.map_ranges(None,self.timeline,self.source,self.spec);self.assertIsNone(m['output_range']);self.assertEqual(m['audio_components'],[])
    def test_cross_source_bed_refused(self):self.continuous();self.spec['audio_timeline']['source']['sha256']='b'*64;self.assertRaises(core.Error,self.mapping)
    def test_incorrect_passage_duration_refused(self):self.continuous();self.spec['audio_timeline']['source_range']['end_sec']=11;self.assertRaises(core.Error,self.mapping)
    def test_unknown_asset_provenance_refused(self):self.timeline['operations']=[{'effective_kind':'music_bed','output_start_sec':0,'output_end_sec':4,'parameters':{'asset_reference':'missing'}}];self.assertRaises(core.Error,self.mapping)
    def test_each_external_asset_separate(self):self.timeline['operations']=[{'operation_id':'music','effective_kind':'music_bed','output_start_sec':0,'output_end_sec':4,'parameters':{'asset_reference':'x'}}];self.spec['visual_spec']['assets']={'x':ref('asset.wav')};self.assertEqual(self.mapping()['audio_components'][-1]['source'],ref('asset.wav'))
    def test_partial_visual_mapping_explicit(self):self.timeline['shots']=[];self.assertEqual(self.mapping()['visual_status'],'UNAVAILABLE')
    def test_no_acoustic_certification(self):self.continuous();self.assertFalse(self.mapping()['audio_components'][0]['acoustic_fact_verified'])
    def test_source_without_audio_unavailable(self):m=e.map_ranges(e.window(1,2),self.timeline,self.source,self.spec,source_has_audio=False);self.assertEqual(m['audio_status'],'UNAVAILABLE');self.assertEqual(m['audio_components'],[])
    def test_unknown_stream_provenance_unavailable(self):self.assertEqual(e.map_ranges(e.window(1,2),self.timeline,self.source,self.spec)['audio_status'],'UNAVAILABLE')


def bad_window_test(value):
    def test(self):self.assertRaises(core.Error,e.validate_window,value,12)
    return test
for i,value in enumerate([e.window(-1,1),e.window(1,1),e.window(1,13),{'start_sec':True,'end_sec':2},
    {'start_sec':float('nan'),'end_sec':2},{'start_sec':0,'end_sec':float('inf')},{'start_sec':0},'invalid']):
    setattr(RangeMapping,f'test_invalid_window_{i}',bad_window_test(value))


class VersionedQA(unittest.TestCase):
    def setUp(self):
        _,_,self.spec,self.timeline,self.source=context()
        self.report=qa.empty_report();self.report.update(source=self.source,rendered_output=ref('out.mp4'))
        self.report['technical']['verification']={'metadata':{'audio_present':True}}
        finding=qa.issue('ending','active_audio_ending_review','MOCK signal finding',e.window(10,10.4),evidence=['audio.metrics'])
        finding['issue_id']='ending';finding['source_ranges']=qa.source_ranges(finding['output_range'],self.timeline)
        self.report['issues']=[finding];self.report['evidence_ledger']['audio.metrics']={'method':'MOCK'}
        self.spec['audio_timeline'].update(mode='continuous_source',source_range=e.window(0,12))
        self.guard=patch.object(qa,'same_reference');self.guard.start();self.addCleanup(self.guard.stop)
        reader=patch.object(qa,'read',side_effect=lambda path:self.report);reader.start();self.addCleanup(reader.stop)
    def make(self):return e.quality_v02(ref('legacy.json'),self.report,self.timeline,self.spec)
    def test_original_report_unchanged(self):old=copy.deepcopy(self.report);self.make();self.assertEqual(old,self.report)
    def test_new_contract_version(self):self.assertEqual(self.make()['contract_version'],'0.2.0')
    def test_audio_ending_mapping_correct(self):self.assertEqual(self.make()['issue_mappings'][0]['mapping']['audio_components'][0]['source_range'],e.window(10,10.4))
    def test_wrong_range_reference_refused(self):r=self.make();r['issue_mappings'][0]['mapping']['audio_components'][0]['source_range']=e.window(24.7,25.1);self.assertRaises(core.Error,e.validate_quality,r,self.report,self.timeline,self.spec)
    def test_cross_source_report_refused(self):r=self.make();r['source']=ref('other.mp4');self.assertRaises(core.Error,e.validate_quality,r,self.report,self.timeline,self.spec)
    def test_no_source_ranges_legacy_alias_in_contract(self):self.assertNotIn('source_ranges',self.make()['issue_mappings'][0])
    def test_approval_cannot_be_promoted(self):r=self.make();r['publish_approved']=True;self.assertRaises(core.Error,e.check,'quality',r)
    def test_incorrect_legacy_issue_digest_refused(self):r=self.make();r['issue_mappings'][0]['legacy_issue_sha256']='b'*64;self.assertRaises(core.Error,e.validate_quality,r,self.report,self.timeline,self.spec)


class MeasuredComparison(unittest.TestCase):
    def setUp(self):
        self.old=qa.empty_report();self.old.update(source=ref('source.mp4'),rendered_output=ref('old.mp4'))
        self.new=copy.deepcopy(self.old);self.new['rendered_output']=ref('new.mp4')
        self.a={'reference':self.old['rendered_output'],'records':[('0','0','1','100','pixels-a')]}
        self.b={'reference':self.new['rendered_output'],'records':copy.deepcopy(self.a['records'])}
        self.ta={};self.tb={}
    def compare(self,human=None):return e.compare_media(self.a,self.b,self.old,self.new,self.ta,self.tb,human)
    def test_identical_visual_no_improvement(self):self.assertEqual(self.compare()['visual_improvement'],'NOT_ESTABLISHED_IDENTICAL')
    def test_positive_ai_score_not_improvement(self):self.new['dimensions']['hook']['status']='PASS';self.assertEqual(self.compare()['overall_improvement'],'NOT_ESTABLISHED')
    def test_audio_only_mapping_change(self):self.tb['audio_timeline']={'mode':'continuous_source'};r=self.compare();self.assertTrue(r['audio_mapping_changed']);self.assertEqual(r['visual_delta'],'IDENTICAL')
    def test_timing_change_detected(self):self.b['records'][0]=('0','1','1','100','pixels-a');self.assertEqual(self.compare()['visual_delta'],'TIMING_CHANGED')
    def test_different_pixels_no_quality_proof(self):self.b['records'][0]=('0','0','1','100','pixels-b');r=self.compare();self.assertEqual(r['visual_delta'],'PIXELS_CHANGED');self.assertEqual(r['visual_improvement'],'UNVERIFIED')
    def test_different_shot_order(self):self.a['records'].append(('1','1','1','100','pixels-b'));self.b['records']=self.a['records'][::-1];self.assertEqual(self.compare()['visual_delta'],'PIXELS_CHANGED')
    def test_disagreement_retained(self):self.new['dimensions']['hook']['status']='PASS';self.assertEqual(self.compare()['disagreements'][0]['dimension'],'hook')
    def test_missing_human_pending(self):self.assertTrue(self.compare()['human_review_pending'])
    def test_old_feedback_rejected(self):h=e.scorecard(self.old['rendered_output']);h['performed']=True;self.assertRaises(core.Error,self.compare,h)
    def test_cross_source_rejected(self):self.new['source']=ref('other.mp4');self.assertRaises(core.Error,self.compare)
    def test_wrong_decoded_output_ref_rejected(self):self.b['reference']=ref('fake.mp4');self.assertRaises(core.Error,self.compare)
    def test_positive_overall_not_audio_claim(self):
        h=e.scorecard(self.new['rendered_output'],self.old['rendered_output']);h.update(performed=True,reviewer='OFFLINE MOCK',reviewed_at='2026-10-13',better_than_baseline='yes');h['ratings']={k:3 for k in h['ratings']}
        with patch.object(qa,'same_reference'):self.assertEqual(self.compare(h)['audio_quality_improvement'],'UNVERIFIED_REQUIRES_LISTENING')
    def test_operation_changes_not_visual_improvement(self):self.tb['operations']=[{'effective_kind':'audio_gain'}];self.assertTrue(self.compare()['audio_processing_changed']);self.assertEqual(self.compare()['visual_improvement'],'NOT_ESTABLISHED_IDENTICAL')
    def test_audio_verification_unavailable_not_success(self):self.assertEqual(self.compare()['technical_audio_mapping_result'],'UNAVAILABLE')
    def test_measured_audio_mapping_explicit(self):r=e.compare_media(self.a,self.b,self.old,self.new,self.ta,self.tb,audio_verification={'status':'CONTINUOUS_SOURCE_MAPPING'});self.assertEqual(r['technical_audio_mapping_result'],'CONTINUOUS_SOURCE_MAPPING')
    def reviewed(self):
        h=e.scorecard(self.new['rendered_output'],self.old['rendered_output']);h.update(performed=True,reviewer='OFFLINE MOCK',reviewed_at='2026-10-13',better_than_baseline='yes');h['ratings']={k:3 for k in h['ratings']};return h
    def test_human_scorecard_embedded_for_provenance(self):
        h=self.reviewed()
        with patch.object(qa,'same_reference'):self.assertEqual(self.compare(h)['human_review'],h)
    def test_no_human_scorecard_not_fabricated(self):self.assertIsNone(self.compare()['human_review'])
    def test_positive_overall_not_visual_delta(self):
        h=self.reviewed();self.b['records'][0]=('0','0','1','100','pixels-b')
        with patch.object(qa,'same_reference'):self.assertEqual(self.compare(h)['visual_improvement'],'UNVERIFIED')
    def test_human_comment_outside_actual_output_refused(self):
        h=self.reviewed();h['comments']=[{'range':e.window(10,12),'text':'OFFLINE MOCK'}]
        with patch.object(qa,'same_reference'),patch.object(core,'safe_path',return_value=PROJECT/'data/test-videos/mandala-original.mp4'),patch.object(core,'media_info',return_value={'duration_sec':10.4}):self.assertRaisesRegex(core.Error,'range outside output',self.compare,h)
    def test_conflicting_human_overall_refused(self):
        h=self.reviewed();h['improvements']['overall']='no'
        with patch.object(qa,'same_reference'):self.assertRaises(core.Error,self.compare,h)


class SpeechAndGrounding(unittest.TestCase):
    def setUp(self):self.packet,self.plan,self.spec,_,_=context();self.registry={'operations':{'trim':{'status':'verified'},'concat':{'status':'verified'}}}
    def validate(self):return preview.validate_plan(self.plan,self.packet,self.registry,self.spec['visual_spec'])[0]
    def dialogue(self):self.packet['speech']['requirements']['overall_requirement']='required';self.plan['evidence_packet_sha256']=core.director.validator.packet_digest(self.packet)
    def test_music_source_no_verified_beats(self):self.assertFalse(self.packet['speech']['eligibility']['speech_alignment']);self.assertTrue(self.validate()['private_preview_eligible'])
    def test_unverified_dialogue_trim_blocked(self):self.dialogue();self.plan['variants'][0]['shots'][0]['source_end_sec']=10;self.assertFalse(self.validate()['private_preview_eligible'])
    def test_whole_unchanged_speech_context_allowed_by_guard(self):self.dialogue();s=self.plan['variants'][0]['shots'][0];s.update(source_start_sec=0,source_end_sec=self.packet['source']['duration_sec']);s['timing'].update(speed=1,freeze_sec=0);self.plan['variants'][0]['shots']=[s];self.assertEqual(preview.speech_safety(self.plan,self.packet),[])
    def test_speed_change_speech_blocked(self):self.dialogue();self.plan['variants'][0]['shots'][0]['timing']['speed']=1.1;self.assertTrue(preview.speech_safety(self.plan,self.packet))
    def test_unsupported_beat_claim_blocked(self):self.plan['variants'][0]['audio_strategy']['sync_basis']='verified_beat_grid';self.assertFalse(self.validate()['private_preview_eligible'])
    def test_unsupported_factual_claim_blocked(self):self.plan['variants'][0]['operations']=[fixtures.operation()];self.plan['variants'][0]['operations'][0]['parameters']['text']='Guaranteed engine quality';self.assertFalse(self.validate()['private_preview_eligible'])
    def test_unsupported_operation_blocked(self):self.registry['operations']['trim']['status']='unknown';self.assertFalse(self.validate()['private_preview_eligible'])
    def test_model_renderer_certification_blocked(self):self.plan['renderer_capabilities']['verification_status']='verified';self.assertFalse(self.validate()['private_preview_eligible'])
    def test_invalid_schema_blocked(self):self.plan['variants']=[];self.assertFalse(self.validate()['private_preview_eligible'])


class RunControls(unittest.TestCase):
    def setUp(self):
        e.ROOT.mkdir(parents=True,exist_ok=True);self.tmp=tempfile.TemporaryDirectory(prefix='test-',dir=e.ROOT);self.addCleanup(self.tmp.cleanup);self.job=Path(self.tmp.name)
        self.config={'permission_text':'OFFLINE MOCK authorization'}
        self.state=bench.checkpoint(self.job,None,'PREPARED','OFFLINE MOCK',run_id='mock-run',registry=ref('registry.json'),entry_id='mock',mode='live_e2e',
            remaining_budget={'director_calls':1,'reviewer_calls':2,'renders':1,'processing_sec':100},attempts=0,action_reserved=None,artifacts={})
    def test_budget_decrement(self):r=bench.reserve(self.job,self.state,self.config,'director',{'director_calls':1});self.assertEqual(r['remaining_budget']['director_calls'],0)
    def test_model_budget_exhausted(self):self.state['remaining_budget']['director_calls']=0;self.assertRaises(core.Error,bench.reserve,self.job,self.state,self.config,'director',{'director_calls':1})
    def test_render_budget_exhausted(self):self.state['remaining_budget']['renders']=0;self.assertRaises(core.Error,bench.reserve,self.job,self.state,self.config,'render',{'renders':1})
    def test_time_budget_exhausted(self):self.state['remaining_budget']['processing_sec']=0;self.assertRaises(core.Error,bench.reserve,self.job,self.state,self.config,'director',{'director_calls':1})
    def test_permission_missing(self):self.config['permission_text']='';self.assertRaises(core.Error,bench.reserve,self.job,self.state,self.config,'director',{'director_calls':1})
    def test_offline_cannot_invoke(self):self.state['mode']='historical_replay';self.assertRaises(core.Error,bench.reserve,self.job,self.state,self.config,'director',{'director_calls':1})
    def test_interrupted_reservation_not_retried(self):self.state['action_reserved']='director';self.assertRaises(core.Error,bench.reserve,self.job,self.state,self.config,'director',{'director_calls':1})
    def test_exclusive_checkpoint(self):self.assertRaises(core.Error,bench.checkpoint,self.job,None,'PREPARED','duplicate',**{k:self.state[k] for k in ['run_id','registry','entry_id','mode','remaining_budget','attempts','action_reserved','artifacts']})
    def test_blocked_command_idempotent(self):self.state['state']='PLAN_BLOCKED';self.state['attempts']=1;self.assertEqual(e.check('state',self.state)['attempts'],1)
    def test_completed_action_not_executed_twice(self):
        self.state['state']='PLAN_BLOCKED'
        with patch.object(bench,'load',return_value=(self.job,self.state,self.config,{})),patch.object(core.director,'run') as run:
            self.assertEqual(bench.plan(self.job),self.state);run.assert_not_called()
    def test_safe_resume_render_failure(self):
        self.state['state']='VALIDATED_FOR_PRIVATE_PERMISSION';self.state['artifacts']={k:ref(k+'.json') for k in ['plan','validation','generation','spec','capabilities']}
        with patch.object(bench,'load',return_value=(self.job,self.state,self.config,{'source':ref('source.mp4')})),patch.object(preview,'render',side_effect=core.Error('OFFLINE MOCK renderer failure')):
            result=bench.render(self.job)
        self.assertEqual(result['state'],'RENDER_FAILURE');self.assertEqual(result['remaining_budget']['renders'],0)
    def test_finish_time_charge(self):
        r=bench.finish(self.job,self.state,__import__('time').monotonic()-2,'QA_FAILURE','mock failure');self.assertLess(r['remaining_budget']['processing_sec'],99)
    def test_second_attempt_schema_refused(self):r=copy.deepcopy(self.state);r['attempts']=2;self.assertRaises(core.Error,e.check,'state',r)
    def test_checkpoint_has_hash_chain(self):r=bench.finish(self.job,self.state,__import__('time').monotonic(),'PLAN_BLOCKED','mock');self.assertEqual(r['previous'],qa.ref(self.job/'checkpoint.001.json'))
    def test_approval_flags_false(self):self.assertTrue(all(self.state[k] is False for k in e.FLAGS))


class DatasetAndSecurity(unittest.TestCase):
    def test_ineligible_canary_does_not_block_real_dataset(self):
        e.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=e.ROOT,prefix='stage58-canary-test-') as tmp:
            source=Path(tmp)/'video-canary.mp4'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                'testsrc2=size=64x64:rate=1:duration=1','-c:v','mpeg4',str(source)],
                check=True,timeout=15)
            with patch.object(core,'media_info',side_effect=core.Error('MOCK FPS policy')),patch.object(core,'probe',return_value={'streams':[{'codec_type':'video','r_frame_rate':'1/1'}]}):result=bench.discovery_metadata(str(source.relative_to(PROJECT)))
        self.assertEqual(result['status'],'BLOCKED_MEDIA_POLICY');self.assertEqual(result['ffprobe_video'][0]['r_frame_rate'],'1/1')
    def test_valid_prepared_directory_registration(self):
        path=PROJECT/'data/analyses/director/adaptive-v03/showcase.prepared.v03'
        packet=qa.read(path/core.director.PACKET);info={k:packet['source'][k] for k in ['duration_sec','width','height','fps']}
        with patch.object(core.director,'load_prepared',return_value=(packet,'mock',{})),patch.object(core,'media_info',return_value=info):entry=bench.entry_from_prepared('showcase',path)
        self.assertEqual(entry['prepared'],qa.ref(path/core.director.REQUEST));self.assertEqual(entry['benchmark_eligibility'],'HISTORICAL_ONLY')
    def test_duplicate_dataset_ids(self):self.assertRaises(core.Error,bench.dataset,[{'dataset_id':'x','source':ref('a.mp4')},{'dataset_id':'x','source':ref('b.mp4')}],e.ROOT/'duplicate')
    def test_duplicate_sources(self):self.assertRaises(core.Error,bench.dataset,[{'dataset_id':'x','source':ref('a.mp4')},{'dataset_id':'y','source':ref('a.mp4')}],e.ROOT/'duplicate')
    def test_unknown_sample_refused(self):
        with patch.object(qa,'ref',return_value=ref('registry.json')),patch.object(bench,'load_registry',return_value={'entries':[]}):self.assertRaises(core.Error,bench.prepare,'registry','unknown',e.ROOT/'unknown')
    def test_exhausted_showcase_no_live_attempt(self):
        entry={'dataset_id':'showcase','source':{'path':'data/test-videos/showcase.mp4','sha256':bench.SHOWCASE},'benchmark_eligibility':'HISTORICAL_ONLY'}
        with patch.object(qa,'ref',return_value=ref('registry')),patch.object(bench,'load_registry',return_value={'entries':[entry]}):self.assertRaises(core.Error,bench.prepare,'registry','showcase',e.ROOT/'showcase-live',mode='live_e2e',authorization='authorized')
    def test_missing_categories_explicit(self):self.assertIn('mixed_speech_music',bench.MISSING)
    def test_failure_taxonomy_complete(self):self.assertEqual(len(bench.TAXONOMY),14);self.assertIn('qa_grounding_error',bench.TAXONOMY)
    def test_traversal_rejected(self):self.assertRaises(core.Error,core.safe_path,'data/../scripts')
    def test_secret_path_rejected(self):self.assertRaises(core.Error,core.safe_path,'.env.asr')
    def test_credential_text_rejected(self):self.assertRaises(core.Error,core.director.safe_text,'Bearer '+'dummyCredentialValue')
    def test_symlink_escape_rejected(self):
        e.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=e.ROOT) as tmp:
            p=Path(tmp)/'link';p.symlink_to('/tmp');self.assertRaises(core.Error,core.safe_path,p)
    def test_fake_receipt_rejected(self):self.assertRaises(core.Error,qa.same_reference,ref('missing-file.mp4'))
    def test_human_scores_not_invented(self):h=e.scorecard(ref('output.mp4'));self.assertFalse(h['performed']);self.assertTrue(all(v is None for v in h['ratings'].values()))
    def test_output_scope_rejected(self):self.assertRaises(core.Error,bench.output,PROJECT/'data/render-tests/stage55/arbitrary')
    def test_permit_no_force(self):self.assertRaises(core.Error,e.check,'permit',{'force':True})
    def test_mixed_characteristics_preserve_both_dimensions(self):r=bench.criteria({'speech_presence':'present','music_presence':'present'});self.assertEqual(r['speech_continuity'],'APPLICABLE');self.assertEqual(r['music_phrasing'],'APPLICABLE')
    def test_uncertain_content_not_positive_score(self):r=bench.criteria({'speech_presence':'uncertain','music_presence':'uncertain'});self.assertEqual(r['speech_continuity'],'UNCERTAIN');self.assertEqual(r['music_phrasing'],'UNCERTAIN')
    def test_dialogue_does_not_force_music_review(self):r=bench.criteria({'speech_presence':'present','music_presence':'absent'});self.assertEqual(r['music_phrasing'],'NOT_APPLICABLE')
    def test_promotional_context_is_not_editing_template(self):r=bench.criteria({'content_tags':['promotion'],'speech_presence':'absent','music_presence':'present'});self.assertNotIn('shot_order',r);self.assertEqual(r['content_clarity'],'APPLICABLE')
    def test_missing_characteristics_unavailable_basis(self):self.assertEqual(bench.criteria({})['classification_basis'],'UNAVAILABLE')


class PipelineFailureControls(unittest.TestCase):
    # Reuse the same checkpoint setup; these mock actions never create live proof.
    def setUp(self):RunControls.setUp(self)
    def setup_plan(self):
        packet,_,_,_,_=context();prepared=self.job/'prepared';prepared.mkdir();p=prepared/core.director.REQUEST;p.write_text('{}')
        self.entry={'source':{k:packet['source'][k] for k in ('path','sha256')},'prepared':qa.ref(p)}
        self.load_guard=patch.object(bench,'load',return_value=(self.job,self.state,self.config,self.entry));self.load_guard.start();self.addCleanup(self.load_guard.stop)
        guard=patch.object(core.director,'load_prepared',return_value=(packet,'OFFLINE MOCK bounded prompt',{}));guard.start();self.addCleanup(guard.stop)
    def test_invalid_model_call_records_failure_without_retry(self):
        self.setup_plan()
        with patch.object(bench.diagnostics,'run',side_effect=core.Error('OFFLINE MOCK invalid response')) as call:
            result=bench.plan(self.job)
        self.assertEqual(result['state'],'PLANNING_FAILURE');self.assertEqual(result['remaining_budget']['director_calls'],0);self.assertEqual(call.call_count,1)
    def test_schema_invalid_model_output_consumes_attempt(self):
        self.setup_plan();bundle=self.job/'mock-model';bundle.mkdir();(bundle/core.director.RECEIPT).write_text('{"mode":"offline_fixture"}');(bundle/core.director.REPORT).write_text('{}')
        with patch.object(bench.diagnostics,'run',return_value=(bundle,{'structural_validity':False})):
            result=bench.plan(self.job)
        self.assertEqual(result['state'],'MODEL_RESPONSE_INVALID');self.assertEqual(result['attempts'],1)
    def test_valid_offline_mock_plan_can_be_independently_validated(self):
        self.setup_plan();packet,plan,_,_,_=context();bundle=self.job/'mock-model';core.director.publish(bundle,{
            core.director.RECEIPT:{'mode':'offline_fixture'},core.director.REPORT:{'structural_validity':True},core.director.PLAN:plan})
        registry={'operations':{'trim':{'status':'verified'},'concat':{'status':'verified'}}}
        with patch.object(bench.diagnostics,'run',return_value=(bundle,{'structural_validity':True})),patch('render_video_v01.validate_registry',return_value=registry):
            result=bench.plan(self.job)
        self.assertEqual(result['state'],'VALIDATED_FOR_PRIVATE_PERMISSION');self.assertFalse(qa.read(result['artifacts']['validation']['path'])['render_approved'])
    def test_qa_failure_no_reviewer_call(self):
        self.state['state']='RENDERED';self.state['artifacts']={'render_manifest':ref('manifest.json')}
        with patch.object(bench,'load',return_value=(self.job,self.state,self.config,{})),patch.object(preview,'technical',side_effect=core.Error('MOCK decode failure')),patch.object(e.ri.reviewer,'invoke') as invoke:
            result=bench.review(self.job)
        self.assertEqual(result['state'],'QA_FAILURE');invoke.assert_not_called();self.assertEqual(result['remaining_budget']['reviewer_calls'],2)


class ProducerResourceControls(unittest.TestCase):
    def test_different_timebases_not_equal_timing(self):
        records=[]
        for fps in (30,60):
            raw=(f'#tb 0: 1/{fps}\n0, 0, 0, 1, 3, abcdef\n').encode()
            with patch.object(core,'media_info',return_value={'duration_sec':1,'fps':fps}),patch.object(core,'run',return_value=(raw,0)):
                records.append(e.frame_records('data/test-videos/cinematic-7693770515172887829.mp4')['records'])
        self.assertNotEqual(records[0],records[1]);self.assertEqual(records[0][0][2],'1/30');self.assertEqual(records[1][0][2],'1/60')
    def test_missing_frame_timebase_refused(self):
        with patch.object(core,'media_info',return_value={'duration_sec':1,'fps':30}),patch.object(core,'run',return_value=(b'0, 0, 0, 1, 3, abcdef\n',0)):
            self.assertRaises(core.Error,e.frame_records,'data/test-videos/cinematic-7693770515172887829.mp4')
    def test_media_commands_bounded(self):
        with patch.object(core.base,'bounded_run') as call:core.run(['ffmpeg','-v','error','-f','null','-'],max_bytes=1024)
        self.assertEqual(call.call_args.kwargs['max_bytes'],1024);self.assertIn('--as=1610612736',call.call_args.args[0]);self.assertEqual(call.call_args.kwargs['timeout'],90)
    def test_timeout_exception_propagates(self):
        with patch.object(core.base,'bounded_run',side_effect=core.Error('MOCK timeout')):self.assertRaises(core.Error,core.run,['ffmpeg','-f','null','-'])
    def test_missing_media_rejected(self):self.assertRaises(core.Error,core.media_info,'data/test-videos/missing-stage58.mp4')
    def test_declared_sha_mismatch_rejected(self):self.assertRaises(core.Error,qa.same_reference,{'path':'data/test-videos/mandala-original.mp4','sha256':'0'*64})
    def test_missing_transcript_never_fabricated(self):p=qa.read('data/analyses/director/adaptive-v03/pak-fuad.prepared.v03/evidence-packet.v03.json');self.assertIsNone(p['speech']['eligible_transcript']);self.assertFalse(p['speech']['eligibility']['speech_alignment'])
    def test_real_stage57_ending_regression(self):
        report=qa.read('data/revisions/stage57/showcase-revision.v03/qa.01/live.v01/quality-report.v01.json')
        manifest=qa.read('data/render-tests/stage57/showcase-revision.v01/render-revision-manifest.v02.json')
        spec=qa.read('data/render-tests/stage57/showcase-revision.v01/execution-spec.v02.json')
        fixed=e.quality_v02(qa.ref('data/revisions/stage57/showcase-revision.v03/qa.01/live.v01/quality-report.v01.json'),report,manifest['timeline'],spec)
        issue=next(i for i in fixed['issue_mappings'] if i['issue_id']=='v2-qa-0001')
        self.assertEqual(issue['mapping']['audio_components'][0]['source_range'],e.window(10,10.4))
        self.assertEqual(issue['mapping']['visual_components'][0]['source_range'],e.window(24.7,25.1))


class RealSyntheticControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.TEST_ROOT.mkdir(parents=True,exist_ok=True);cls.tmp=tempfile.TemporaryDirectory(prefix='stage58-controls-',dir=core.TEST_ROOT);cls.root=Path(cls.tmp.name)
        cls.manifest=audio.self_test('replace',cls.root/'continuous')
        cls.mix=audio.self_test('mix',cls.root/'mixed')
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_actual_continuous_audio_mapping(self):self.assertEqual(self.manifest['audio_mapping_verification']['status'],'CONTINUOUS_SOURCE_MAPPING')
    def test_actual_mixed_components(self):self.assertTrue(self.mix['fixture_measurements']['mix_original'])
    def test_actual_intentional_visual_hard_cuts(self):self.assertEqual(self.manifest['fixture_measurements']['visual_scene_order'],[2,0,1])
    def test_actual_visual_repetition_control(self):a=e.frame_records(self.root/'continuous/render.mp4');b=e.frame_records(self.root/'continuous/render.mp4');self.assertEqual(a['records'],b['records'])
    def test_actual_full_decode_and_pts(self):self.assertTrue(self.manifest['verification']['presentation_timestamps_continuous'])
    def test_actual_tones_not_editorial_performance(self):self.assertIn('TEST_ONLY',self.manifest['mode'])
    def test_actual_gain_and_fades(self):self.assertTrue(self.manifest['fixture_measurements']['endpoint_fades_measured'])
    def test_actual_no_phrase_verification(self):self.assertFalse(self.manifest['audio_mapping_verification']['musical_phrase_verified'])
    def test_actual_no_clipping(self):self.assertLess(self.mix['verification']['audio_signal']['peak_linear'],.999)
    def test_actual_tampered_capability_rejected(self):r=audio.capability([qa.ref(self.root/'continuous'/audio.MANIFEST),qa.ref(self.root/'mixed'/audio.MANIFEST)]);r['proofs'][0]['sha256']='b'*64;p=self.root/'bad.json';core.shared.write_json(p,r);self.assertRaises(core.Error,audio.validate_capability,p)
    def test_stage58_encoder_emission_actual_synthetic_only(self):
        # Mock only admission. Exercise real shared graph, encoder, decode and
        # exclusive publication. This fixture cannot pass real live admission.
        e.RENDER_ROOT.mkdir(parents=True,exist_ok=True);e.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='synthetic-test-',dir=e.RENDER_ROOT) as outroot,tempfile.TemporaryDirectory(prefix='synthetic-test-',dir=e.ROOT) as receiptroot:
            job=Path(receiptroot);destination=Path(outroot)/'new';bundle=self.root/'continuous'
            plan=qa.read(bundle/audio.PLAN);spec=qa.read(bundle/audio.SPEC)['visual_spec'];timeline=core.compile_timeline(plan,spec)
            (job/'generation.json').write_text('{"mode":"offline_fixture"}');(job/core.director.PACKET).write_text('{"mode":"offline_fixture"}');(job/'validation.json').write_text('{}');(job/'registry.json').write_text('{}');(job/'spec.json').write_text(json.dumps(spec))
            source=qa.ref(bundle/'source.mp4');entry={'source':source}
            permit=e.check('permit',{'contract_version':e.VERSION,'mode':'STAGE58_PRIVATE_PREVIEW','source':source,
                'registry':qa.ref(job/'registry.json'),'plan':qa.ref(bundle/audio.PLAN),'validation':qa.ref(job/'validation.json'),
                'generation':qa.ref(job/'generation.json'),'spec':qa.ref(job/'spec.json'),'capabilities':qa.ref(job/'registry.json'),
                'destination':core.shared.relative(destination),'permission_text':'OFFLINE MOCK synthetic admission only','created_at':core.shared.now(),**e.FLAGS})
            core.shared.write_json(job/'permit.json',permit)
            with patch.object(preview,'admit',return_value=({},timeline,core.media_info(bundle/'source.mp4'))):m=preview.render(qa.ref(job/'permit.json'),entry,destination)
            self.assertTrue(m['verification']['decoded_to_completion']);self.assertFalse(m['render_approved']);self.assertTrue((destination/'preview.mp4').exists())
    def test_abrupt_audio_discontinuity_control(self):
        import numpy as np
        pcm=np.concatenate([np.ones(48000)*.1,np.ones(48000)*-.4]);timeline=copy.deepcopy(self.manifest['timeline']);timeline['expected_duration_sec']=2
        timeline['shots']=[{'shot_id':'a','source_start_sec':0,'source_end_sec':1,'output_start_sec':0,'output_end_sec':1,'speed':1,'freeze_sec':0,'transition_out':'cut','overlap_sec':0},
            {'shot_id':'b','source_start_sec':4,'source_end_sec':5,'output_start_sec':1,'output_end_sec':2,'speed':1,'freeze_sec':0,'transition_out':'cut','overlap_sec':0}]
        result,_=qa.audio_analysis(pcm,timeline);self.assertEqual(result['boundaries'][0]['source_jump_sec'],3);self.assertEqual(result['boundaries'][0]['musical_phrase_continuity'],'UNVERIFIED_REQUIRES_LISTENING')


if __name__=='__main__':unittest.main()
