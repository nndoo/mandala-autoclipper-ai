"""Trust boundaries, timing fallback, safe areas and durable automatic call budgets."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
import adaptive_director_v03_fixtures as f
import automatic_editing_validation_v01 as v
import automatic_text_v01 as text
import run_automatic_editing_v01 as workflow


def style():
    return {'font':'dejavu_sans_bold','size_px':50,'color':'#FFFFFF','active_color':'#FFE040','outline_px':2,
        'x':.45,'y':.2,'enter':'pop','exit':'fade','enter_sec':.2,'exit_sec':.2}


def proposal(packet):
    return {'contract_version':v.VERSION,'source_sha256':packet['source']['sha256'],'concept':'Synthetic editorial fixture',
        'decisions':{k:'Source-bound synthetic test choice' for k in ('hook','shot_selection','pacing','transitions','effects','text_hierarchy','branding','ending','audio')},
        'shots':[{'id':'s1','start_sec':0,'end_sec':4,'speed':1,'transition_out':'cut','overlap_sec':0,'scale':1,'center_x':.5,'center_y':.5,
            'rationale':'Source-bound candidate','evidence_refs':['canonical.segments.0']}],
        'overlays':[{'id':'t1','shot_id':'s1','start_sec':.5,'end_sec':3,'text':'Lihat detail','purpose':'Creative description',
            'evidence_refs':['canonical.segments.0'],'style':style()}],
        'subtitle_groups':[],'audio':{'mode':'continuous_source','start_sec':0,'gain_db':-6,'fade_in_sec':0,'fade_out_sec':.3},
        'production_eligible':False,'human_verified':False}


def speech(packet):return {'required':False,'status':'NOT_REQUIRED','source_sha256':packet['source']['sha256'],'units':[],'timing':'none','human_verified':False}


class AutomaticEditingTests(unittest.TestCase):
    def setUp(self):self.packet=f.packet(music='present');self.p=proposal(self.packet);self.s=speech(self.packet)

    def validate(self,p=None,s=None):return v.validate(p or self.p,self.packet,s or self.s)

    def test_private_eligibility_never_changes_human_or_production_gate(self):
        report,plan,_,graph=self.validate()
        self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE',report)
        self.assertFalse(report['human_verified']);self.assertFalse(plan['render_approved'])
        self.assertEqual(plan['render_readiness'],'BLOCKED_FOR_RENDER')
        self.assertEqual(graph['automatic_text_cues'][0]['role'],'creative_text_overlay')

    def test_subject_reframe_and_grade_are_explicit_compiled_choices(self):
        self.p['shots'][0].update(scale=1.5,center_y=.6,grade={'brightness':.02,'contrast':1.1,'saturation':.9})
        report,_,spec,graph=self.validate();self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE',report)
        self.assertEqual([o['effective_kind'] for o in graph['operations']],['zoom','color_grade'])
        self.assertEqual(spec['visual_spec']['operation_parameters']['grade-s1']['color']['contrast'],1.1)

    def test_fractional_speed_does_not_round_operation_start_outside_shot(self):
        first=self.p['shots'][0];first.update(end_sec=2.1,speed=.95,scale=1.5)
        second={**first,'id':'s2','start_sec':4,'end_sec':6.1};self.p['shots'].append(second)
        self.p['overlays'][0].update(end_sec=1.8)
        second_text=copy.deepcopy(self.p['overlays'][0]);second_text.update(id='t2',shot_id='s2',start_sec=2.5,end_sec=4)
        self.p['overlays'].append(second_text)
        report,_,_,graph=self.validate();self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE',report)
        self.assertEqual(graph['operations'][1]['output_start_sec'],graph['shots'][1]['output_start_sec'])

    def test_caption_density_and_breathing_are_validated(self):
        self.p['overlays']=[];self.assertEqual(self.validate()[0]['status'],'AUTO_PREVIEW_ELIGIBLE')
        self.assertEqual(self.validate()[0]['advisory_findings'][0]['code'],'caption_density')
        self.p=proposal(self.packet);self.p['overlays'][0].update(start_sec=0,end_sec=4)
        self.assertEqual(self.validate()[0]['advisory_findings'][0]['code'],'text_free_pause')

    def test_collision_includes_slide_envelope(self):
        cue=copy.deepcopy(self.p['overlays'][0]);cue['id']='t2';self.p['overlays'].append(cue)
        self.assertEqual(self.validate()[0]['status'],'AUTO_PREVIEW_ELIGIBLE')
        self.assertEqual(self.validate()[0]['advisory_findings'][0]['code'],'estimated_text_overlap')
        self.p['overlays']=self.p['overlays'][:1];self.p['overlays'][0]['style'].update(y=.09,enter='slide')
        self.assertEqual(self.validate()[0]['advisory_findings'][0]['code'],'estimated_safe_area')

    def test_ass_injection_and_arbitrary_paths_refused(self):
        for bad in ('{\\pos(0,0)}test','test\\Nbad'):
            self.p['overlays'][0]['text']=bad;self.assertEqual(self.validate()[0]['status'],'BLOCKED')
        self.p=proposal(self.packet);self.p['overlays'][0]['style']['font']='/tmp/font.ttf'
        self.assertEqual(self.validate()[0]['status'],'BLOCKED')

    def test_unbound_evidence_and_source_refused(self):
        self.p['overlays'][0]['evidence_refs']=['invented'];self.assertEqual(self.validate()[0]['status'],'BLOCKED')
        self.p=proposal(self.packet);self.p['source_sha256']='b'*64;self.assertEqual(self.validate()[0]['status'],'BLOCKED')

    def test_missing_word_times_never_generated_from_text(self):
        with self.assertRaises(v.core.Error):workflow.timed_units({'text':'One two three'},0,5,'r')
        with self.assertRaises(v.core.Error):workflow.timed_units({'words':[{'word':'one','start':0}]},0,5,'r')

    def test_provider_phrase_fallback_has_no_word_times(self):
        mode,units=workflow.timed_units({'segments':[{'text':'Ini mobil kita','start':.2,'end':2}]},10,13,'r')
        self.assertEqual(mode,'phrase');self.assertEqual(units[0]['start_sec'],10.2)
        with self.assertRaises(v.core.Error):workflow.timed_units({'segments':[{'text':' '.join(['panjang']*16),'start':0,'end':3}]},0,5,'r')

    def test_unverifiable_vehicle_condition_claim_refused(self):
        self.p['overlays'][0]['text']='KONDISI PRIMA';self.assertEqual(self.validate()[0]['status'],'BLOCKED')

    def test_word_order_and_low_confidence_refused(self):
        with self.assertRaises(v.core.Error):workflow.timed_units({'words':[{'word':'a','start':1,'end':2},{'word':'b','start':.5,'end':1}]},0,5,'r')
        with self.assertRaises(v.core.Error):workflow.timed_units({'segments':[{'text':'a b','start':0,'end':1,'no_speech_prob':.9}]},0,5,'r')
        with self.assertRaises(v.core.Error):workflow.timed_units({'text':'a b c','words':[{'word':'a','start':0,'end':1}]},0,5,'r')

    def test_only_problem_region_retries_and_stops_after_two_asr_calls(self):
        packet=f.packet(speech='present')
        workflow.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.ROOT,prefix='asr-budget-test-') as temp:
            job=Path(temp);source=job/'source.mp4';source.write_bytes(b'synthetic test stub')
            packet['source']['path']=str(source)
            def fake_ffmpeg(args,*unused):Path(args[-1]).write_bytes(b'synthetic WAV stub')
            with patch.object(workflow.asr,'load_config',return_value=(None,{})),patch.object(workflow.core,'ffmpeg',side_effect=fake_ffmpeg),patch.object(workflow.asr,'remote_call',return_value={'status':'complete','payload':{'text':'No timing here'}}) as call:
                with self.assertRaisesRegex(v.core.Error,'budget exhausted'):workflow.speech_evidence(packet,job)
                self.assertEqual(call.call_count,2)
                self.assertEqual(len(list(job.glob('asr-*/reservation.json'))),2)

    def dialogue(self,mode='word'):
        self.packet=f.packet(speech='present');self.p=proposal(self.packet);self.p['audio'].update(mode='original',gain_db=0,fade_out_sec=0)
        self.p['overlays']=[]
        _,units=workflow.timed_units({'words':[{'word':'Ini','start':.3,'end':1},{'word':'mobil','start':1.1,'end':1.8},{'word':'kita','start':1.9,'end':2.6}]} if mode=='word' else {'segments':[{'text':'Ini mobil kita','start':.3,'end':2.6}]},0,4,'r')
        self.s={'required':True,'status':'AUTO_PREVIEW_ELIGIBLE','source_sha256':self.packet['source']['sha256'],'timing':mode,'units':units,'human_verified':False}
        self.p['subtitle_groups']=[{'id':'sub1','shot_id':'s1','unit_ids':[u['id'] for u in units],'style':style()}]

    def test_dialogue_highlights_only_real_timestamps_and_keeps_legacy_gate(self):
        self.dialogue();report,plan,_,graph=self.validate()
        self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE',report)
        cue=graph['automatic_text_cues'][0];self.assertEqual(cue['words'][1]['start_sec'],1.1)
        self.assertFalse(cue['human_verified']);self.assertFalse(plan['publish_ready'])
        ass=text.document([cue],{'width':1080,'height':1920})
        self.assertIn('Ini',ass);self.assertIn('mobil',ass);self.assertIn('kita',ass)
        self.assertIn('0:00:01.10',ass)
        self.assertIn('\\fscx',ass) # AI-selected phrase animation remains supported with word events.

    def test_phrase_fallback_uses_whole_provider_segment(self):
        self.dialogue('phrase');report,_,_,graph=self.validate();self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE',report)
        self.assertEqual(graph['automatic_text_cues'][0]['words'],[])

    def test_long_provider_phrase_wraps_without_inventing_word_timestamps(self):
        self.dialogue('phrase');self.s['units'][0]['text']='Lagi proses apa ini Pak Fuad'
        self.p['subtitle_groups'][0]['line_breaks_after']=[3]
        report,_,_,graph=self.validate();self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE',report)
        cue=graph['automatic_text_cues'][0]
        self.assertEqual(cue['text'],'Lagi proses apa\nini Pak Fuad');self.assertEqual(cue['words'],[])
        self.assertEqual(cue['start_sec'],.3);self.assertEqual(cue['end_sec'],2.6)

    def test_cutting_word_or_dropping_subtitle_refused(self):
        self.dialogue();self.p['shots'][0]['start_sec']=.5;self.assertEqual(self.validate()[0]['status'],'BLOCKED')
        self.dialogue();self.p['subtitle_groups'][0]['unit_ids']=self.p['subtitle_groups'][0]['unit_ids'][:2]
        self.assertEqual(self.validate()[0]['status'],'BLOCKED')

    def test_existing_unsafe_human_rejection_or_receipt_error_stays_blocking(self):
        self.dialogue()
        for code in ('speech_intelligence:human_review_rejects_exact_selection','speech_intelligence:invalid_or_unreplayable_evidence'):
            with patch.object(v.core.director.validator,'validate_plan',return_value={'structural_validity':True,'blocking_findings':[{'code':code}]}):
                self.assertEqual(self.validate()[0]['status'],'BLOCKED')

    def test_three_reserved_failures_stop_without_resetting_ledger(self):
        workflow.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.ROOT,prefix='budget-test-') as temp:
            job=Path(temp);workflow.write(job/'request.json',{'inputs':[],'code_receipts':[],'environment':{},'storyboard':[]})
            workflow.write(job/'packet.json',self.packet);workflow.write(job/'speech.json',self.s)
            with patch.object(v,'code_receipts',return_value=[]),patch.object(workflow.core,'environment',return_value={}),patch.object(workflow,'prompt_for',return_value='test'),patch.object(workflow.core.director,'live_response',side_effect=v.core.Error('concrete test failure')) as call:
                result=workflow.run(job);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(call.call_count,3)
                self.assertEqual(len(list(job.glob('proposal-*/reservation.json'))),3)
                with self.assertRaises(v.core.Error):workflow.run(job)
                self.assertEqual(call.call_count,3)

    def test_exact_private_permit_is_consumed_once_and_never_reset(self):
        workflow.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.ROOT,prefix='permit-test-') as temp:
            job=Path(temp);source=job/'source.mp4';source.write_bytes(b'closed synthetic unit test')
            self.packet['source'].update(path=str(source),sha256=v.core.intake.gate.sha256_file(source))
            self.p=proposal(self.packet);self.s=speech(self.packet)
            report,plan,spec,graph=self.validate();self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE')
            request={'inputs':[],'code_receipts':[],'environment':{},'proof':{},'storyboard':[]}
            workflow.write(job/'request.json',request);workflow.write(job/'packet.json',self.packet);workflow.write(job/'speech.json',self.s)
            attempt=job/'proposal-01';attempt.mkdir();workflow.save_text(attempt/'prompt.txt','test')
            import json
            workflow.save_text(attempt/'raw-response.json',json.dumps(self.p))
            for name,value in [('proposal.json',self.p),('validation.json',report),('reservation.json',{'prompt_sha256':v.core.director.digest_text('test'),
                'request_sha256':v.core.digest_object(request),'attached_images':[],'attempt':1}),('permit.json',{
                    'scope':'STAGE59_PRIVATE_PREVIEW','human_verified':False,'production_eligible':False,
                    'source_sha256':self.packet['source']['sha256'],'proposal_sha256':v.core.digest_object(self.p),
                    'execution_sha256':v.core.digest_object(spec),'request_sha256':v.core.digest_object(request)})]:workflow.write(attempt/name,value)
            with patch.object(v,'code_receipts',return_value=[]),patch.object(workflow.core,'environment',return_value={}),patch.object(workflow,'check_proof',return_value={'verified_capabilities':graph['required_capabilities']}),patch.object(v.core.intake,'validate_packet',return_value=self.packet):
                v.admit({'job':str(job),'attempt':str(attempt)},plan,spec,source,graph)
                first=(attempt/'permit-consumed.json').read_bytes()
                with self.assertRaises(v.core.Error):v.admit({'job':str(job),'attempt':str(attempt)},plan,spec,source,graph)
                self.assertEqual((attempt/'permit-consumed.json').read_bytes(),first)


if __name__=='__main__':unittest.main()
