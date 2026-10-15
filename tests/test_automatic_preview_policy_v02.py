"""Flexible quality policy must preserve genuine blockers and bounded fallback selection."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
import automatic_editing_validation_v01 as v
import run_automatic_editing_v01 as w
import test_automatic_editing_v01 as fixtures
import adaptive_director_v03_fixtures as f


def response(code='poor_framing',severity='major'):
    return {'issues':[{'code':code,'category':v.REVIEW_CODES[code],'severity':severity,
        'start_sec':0,'end_sec':1,'diagnosis':'Concrete synthetic test diagnosis'}],'revision_required':True}


def candidate(n,issues=None,blockers=None):
    return {'attempt':n,'advisory_findings':issues or [],'blocking_findings':blockers or []}


class FlexiblePreviewTests(unittest.TestCase):
    def test_reviewer_preferences_are_advisory_even_if_model_demands_block(self):
        for code in ('poor_framing','weak_ending','pacing','jump_cut','text_style'):
            result=v.review_findings(response(code,'blocker'))
            self.assertEqual(result['blocking_findings'],[])
            self.assertEqual(result['advisory_findings'][0]['severity'],'major')

    def test_model_cannot_downgrade_real_defects_or_evidence_to_minor(self):
        for code in ('text_unreadable','text_clipped','text_invisible','subtitle_uncertain','unsupported_claim','decode_failure','audio_clipping','audio_discontinuity'):
            result=v.review_findings(response(code,'minor'))
            self.assertEqual(len(result['blocking_findings']),1);self.assertFalse(result['advisory_findings'])

    def test_historical_response_is_projected_without_modifying_raw(self):
        r={'issues':[{'category':'ending','start_sec':0,'end_sec':1,'diagnosis':'Abrupt ending'}]}
        old=copy.deepcopy(r);self.assertFalse(v.review_findings(r)['blocking_findings']);self.assertEqual(r,old)
        r['issues'][0]['category']='subtitle';self.assertTrue(v.review_findings(r)['blocking_findings'])
        r['issues'][0].update(category='text',diagnosis='Inconsistent font and color hierarchy')
        self.assertEqual(v.review_findings(r)['advisory_findings'][0]['code'],'text_style')
        r['issues'][0]['diagnosis']='The font is unreadable and clipped'
        self.assertTrue(v.review_findings(r)['blocking_findings'])
        r['issues'][0]['diagnosis']='KONDISI PRIMA is an unsupported condition claim'
        self.assertEqual(v.review_findings(r)['blocking_findings'][0]['code'],'unsupported_claim')

    def test_ranking_major_editorial_then_total_notes_then_latest(self):
        major=v.finding('poor_framing','editorial','major','Framing issue')
        minor=v.finding('caption_density','editorial','minor','Density preference')
        self.assertEqual(w.select_candidate([candidate(1,[major]),candidate(2,[minor,minor])])['attempt'],2)
        self.assertEqual(w.select_candidate([candidate(1,[minor]),candidate(2,[minor,minor])])['attempt'],1)
        self.assertEqual(w.select_candidate([candidate(1,[minor]),candidate(3,[minor])])['attempt'],3)
        self.assertIsNone(w.select_candidate([candidate(1,blockers=[major])]))

    def test_estimates_are_advisory_and_renderer_parameters_remain_bounded(self):
        packet=f.packet(music='present');p=fixtures.proposal(packet);speech=fixtures.speech(packet)
        p['overlays'][0].update(text='i'*30,start_sec=.5,end_sec=1.5)
        p['overlays'][0]['style'].update(x=.25,enter_sec=.05,exit_sec=.05)
        report,_,_,_=v.validate(p,packet,speech)
        self.assertEqual(report['status'],'AUTO_PREVIEW_ELIGIBLE',report)
        self.assertEqual({i['code'] for i in report['advisory_findings']},{'estimated_safe_area','estimated_reading_rate'})
        p['overlays'][0]['style']['enter_sec']=2
        self.assertEqual(v.validate(p,packet,speech)[0]['status'],'BLOCKED')

    def test_simultaneous_hierarchy_does_not_double_count_text_presence(self):
        packet=f.packet(music='present');p=fixtures.proposal(packet)
        second=copy.deepcopy(p['overlays'][0]);second['id']='t2';second['style']['y']=.55
        p['overlays'].append(second)
        report,_,_,_=v.validate(p,packet,fixtures.speech(packet))
        self.assertFalse(report['blocking_findings'])
        self.assertNotIn('text_free_pause',[i['code'] for i in report['advisory_findings']])

    def test_actual_synthetic_glyphs_disprove_estimated_clipping_and_detect_real_clipping(self):
        w.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=w.ROOT,prefix='glyph-policy-test-') as temp:
            cue=w.synthetic_cues()[0];cue['text']='i'*15;cue['style'].update(x=.25,size_px=50)
            self.assertLess(v.envelope(cue)[0],0)
            self.assertEqual(w.glyph_clipping(cue,.8,Path(temp),w.audio.LIMITS,'safe'),0)
            cue['text']='W'*15;cue['style'].update(x=.08,size_px=96)
            self.assertGreater(w.glyph_clipping(cue,.8,Path(temp),w.audio.LIMITS,'clipped'),0)

    def run_mocked_job(self,third_bad=False,all_blocked=False):
        w.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=w.ROOT,prefix='quality-budget-test-') as temp:
            job=Path(temp);packet=f.packet(music='present');p=fixtures.proposal(packet)
            w.write(job/'request.json',{'inputs':[],'code_receipts':[],'environment':{},'storyboard':[]})
            w.write(job/'packet.json',packet);w.write(job/'speech.json',fixtures.speech(packet))
            results=[json.dumps(p)]*3
            if third_bad:results[-1]='{"incomplete":'
            reviews=[response('subtitle_uncertain' if all_blocked else 'poor_framing')]*3
            def store_candidate(attempt,report,manifest,r):
                findings=v.review_findings(r);return candidate(int(attempt.name.split('-')[-1]),findings['advisory_findings'],findings['blocking_findings'])
            def complete(job,c,n,request):
                result={'status':'AUTO_PREVIEW_COMPLETED_WITH_NOTES','selected_attempt':c['attempt'],'director_proposals_reserved':n}
                w.write(job/'completed.json',result);return result
            with patch.object(v,'code_receipts',return_value=[]),patch.object(w.core,'environment',return_value={}),patch.object(w,'prompt_for',return_value='test'),patch.object(w.core.director,'live_response',side_effect=results) as calls,patch.object(w,'render_attempt',return_value=({'output':{'path':'synthetic.mp4'},'technical':{}},{'shots':[],'automatic_text_cues':[]})),patch.object(w.core,'safe_path',wraps=w.core.safe_path) as safe,patch.object(w,'model_review',side_effect=reviews),patch.object(w,'candidate_for',side_effect=store_candidate),patch.object(w,'complete_candidate',side_effect=complete):
                # Only mock the synthetic output path; real job path guards remain exercised.
                safe.side_effect=lambda value,*args,**kwargs:Path('synthetic.mp4') if str(value)=='synthetic.mp4' else safe._mock_wraps(value,*args,**kwargs)
                result=w.run(job)
                self.assertEqual(calls.call_count,3)
                self.assertEqual(len(list(job.glob('proposal-*/reservation.json'))),3)
                if all_blocked:self.assertEqual(result['status'],'BLOCKED')
                else:
                    self.assertEqual(result['status'],'AUTO_PREVIEW_COMPLETED_WITH_NOTES')
                    self.assertEqual(result['selected_attempt'],2 if third_bad else 3)
                self.assertTrue((job/'proposal-03/outcome.json').exists())

    def test_budget_returns_best_preview_with_editorial_notes(self):self.run_mocked_job()
    def test_malformed_last_correction_does_not_discard_valid_previous_preview(self):self.run_mocked_job(third_bad=True)
    def test_no_candidate_with_evidence_blocker_can_be_selected(self):self.run_mocked_job(all_blocked=True)

    def test_exhausted_resume_selects_saved_best_without_more_api_calls(self):
        w.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=w.ROOT,prefix='saved-best-test-') as temp:
            job=Path(temp);packet=f.packet(music='present')
            w.write(job/'request.json',{'inputs':[],'code_receipts':[],'environment':{},'storyboard':[],'comparison':None,'proof':{}})
            w.write(job/'packet.json',packet);w.write(job/'speech.json',fixtures.speech(packet))
            for i in range(1,4):
                attempt=job/f'proposal-{i:02d}';attempt.mkdir();w.write(attempt/'reservation.json',{'api_calls':1})
                w.write(attempt/'outcome.json',{'diagnosis':[]})
                if i<3:
                    c=candidate(i,[v.finding('poor_framing','editorial','major' if i==1 else 'minor','Concrete framing note')])
                    c.update(output={'path':'synthetic.mp4'},reviewer={});w.write(attempt/'candidate.json',c)
            graph={'expected_duration_sec':4,'output_settings':{'width':1080,'height':1920}}
            with patch.object(v,'code_receipts',return_value=[]),patch.object(w.core,'environment',return_value={}),patch.object(w,'check_proof',return_value={}),patch.object(w,'verify_candidate',return_value=graph),patch.object(w.core.director,'live_response') as call:
                result=w.run(job)
                self.assertEqual(result['status'],'AUTO_PREVIEW_COMPLETED_WITH_NOTES');self.assertEqual(result['selected_attempt'],2)
                self.assertFalse(result['human_verified']);self.assertFalse(result['production_eligible']);self.assertFalse(result['publishing_eligible'])
                call.assert_not_called()
                # A completed resume does not duplicate ledger writes or make calls.
                self.assertEqual(w.run(job),result);call.assert_not_called()

    def test_saved_reviewer_for_another_video_is_not_a_candidate(self):
        w.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=w.ROOT,prefix='review-boundary-test-') as temp:
            attempt=Path(temp);(attempt/'review').mkdir()
            r={'media_sha256':'a'*64,'video_examined':True,'audio_examined':True,'human_verified':False,'production_eligible':False,'issues':[]}
            w.write(attempt/'review/response.json',r);w.save_text(attempt/'review/raw-response.json',json.dumps(r))
            w.write(attempt/'review/request.json',{'media':{'sha256':'a'*64,'bytes':100},'prompt':'test','prompt_sha256':w.core.director.digest_text('test')})
            with self.assertRaises(w.core.Error):w.saved_review(attempt,{'sha256':'b'*64,'bytes':100})

    def test_absolute_manifest_and_relative_receipt_paths_bind_same_bytes(self):
        w.ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=w.ROOT,prefix='output-reference-test-') as temp:
            job=Path(temp);video=job/'preview.mp4';video.write_bytes(b'closed unit-test bytes')
            output={**w.reference(video),'path':str(video),'bytes':video.stat().st_size}
            self.assertEqual(w.verify_output_reference(output,job),video)
            output['path']=w.reference(video)['path'];self.assertEqual(w.verify_output_reference(output,job),video)
            output['sha256']='b'*64
            with self.assertRaises(w.core.Error):w.verify_output_reference(output,job)

    def test_historical_integer_zero_has_own_digest_without_rewriting_receipts(self):
        packet=f.packet(music='present');p=fixtures.proposal(packet)
        p['shots'][0]['grade']={'brightness':0,'contrast':1,'saturation':1}
        plan,spec=v.convert(p,packet);plan['variants'][0]['operations'][0]['output_start_sec']=0
        spec['visual_spec']['plan_sha256']=w.core.digest_object(plan)
        original=copy.deepcopy((plan,spec));w.replay_render_decisions(p,packet,plan,spec)
        self.assertEqual((plan,spec),original)
        spec['visual_spec']['plan_sha256']='b'*64
        with self.assertRaises(w.core.Error):w.replay_render_decisions(p,packet,plan,spec)


if __name__=='__main__':unittest.main()
