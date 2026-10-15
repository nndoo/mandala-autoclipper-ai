"""Offline source-cue mapping tests with synthetic human-review fixtures."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
import speech_intelligence_v01 as s
import speech_planning_v01 as planning
import prepare_segment_subtitles_v01 as subtitles
import test_speech_intelligence_v01 as fixtures


def setUpModule():
    guard = patch('socket.socket.connect', side_effect=AssertionError('Offline review tests only'))
    guard.start(); unittest.addModuleCleanup(guard.stop)


class SourceCueTests(fixtures.EvidenceTests):
    # Reuse the existing synthetic source/ASR/receipt fixture, not real voice approval.
    def test_source_cues_remap_to_different_operation_id(self):
        def annotate(r):
            r['subtitle_source_reviews']=[{'segment_id':'u1','source_start_sec':0,'source_end_sec':2,
                'text':'Synthetic question?','max_error_sec':.02,'accuracy_confirmed':True}]
        report=self.accepted([[0,2]],annotate); plan=self.plan([[0,2]])
        op=fixtures.f.operation('subtitle',{'text':'Synthetic question?','kind':'verified_quote','verification_status':'verified',
            'evidence_refs':['canonical.segments.0'],'publish_ready':False})
        op['operation_id']='model-selected-caption';op['output_end_sec']=2
        plan['variants'][0]['operations']=[op]
        self.assertFalse(s.evaluate_plan(plan,self.packet,report)['affected_operations_blocked'])
        op['parameters']['caption']['text']='New invented words'
        self.assertTrue(s.evaluate_plan(plan,self.packet,report)['affected_operations_blocked'])

    def test_corrected_source_spans_preserve_raw_asr_and_word_limit(self):
        def annotate(r):
            r['subtitle_source_reviews']=[{'segment_id':sid,'source_start_sec':a,'source_end_sec':b,
                'text':text,'max_error_sec':.02,'accuracy_confirmed':True} for sid,a,b,text in
                [('u1',0,2.02,'Synthetic question?'),('u2',4,6.02,'Synthetic answer.')]]
        report=self.accepted([[0,2.02],[4,6.02]],annotate)
        self.assertEqual(report['segments'][0]['end_sec'],2)
        self.assertTrue(report['eligibility']['segment_alignment']);self.assertFalse(report['eligibility']['word_alignment'])
        draft=subtitles.captions(report,[[0,2.02],[4,6.02]])
        self.assertEqual(draft['cues'][0]['source_end_sec'],2.02)
        self.assertEqual(draft['timing_precision'],'human_source_review')
        path=self.root/'reviewed-report.json';s.shared.write_json(path,report)
        packet=planning.enrich_packet(self.packet,report,path)
        self.assertEqual(packet['evidence_ledger']['speech.reviewed_segments.0']['end_sec'],2.02)
        self.assertIn('subtitle_source_reviews',packet['evidence_ledger']['speech.reviewed_segments.0']['pointer'])

    def test_source_cue_wrong_text_rejected(self):
        report=self.report();review=self.review(report,[[0,2]])
        review['subtitle_source_reviews']=[{'segment_id':'u1','source_start_sec':0,'source_end_sec':2,
            'text':'Fiction','max_error_sec':.02,'accuracy_confirmed':True}]
        with self.assertRaises(s.base.AdapterError):s.review_data(review,report,'OFFLINE HUMAN FIXTURE')

    def test_source_cue_duplicates_rejected(self):
        report=self.report();review=self.review(report,[[0,2]])
        cue={'segment_id':'u1','source_start_sec':0,'source_end_sec':2,'text':'Synthetic question?',
            'max_error_sec':.02,'accuracy_confirmed':True}
        review['subtitle_source_reviews']=[cue,cue]
        with self.assertRaises(s.base.AdapterError):s.review_data(review,report,'OFFLINE HUMAN FIXTURE')

    def test_text_only_method_cannot_import_source_timing(self):
        report=self.report();review=self.review(report,[[0,2]])
        review['review_method']='user_supplied_review_notes';review['boundary_reviews']=[];review['selection_reviews']=[]
        review['subtitle_source_reviews']=[{'segment_id':'u1','source_start_sec':0,'source_end_sec':2,
            'text':'Synthetic question?','max_error_sec':.02,'accuracy_confirmed':True}]
        with self.assertRaises(s.base.AdapterError):s.review_data(review,report,'OFFLINE HUMAN FIXTURE')

    def test_corrected_source_edges_support_only_exact_measured_selection(self):
        def annotate(r):
            r['boundary_reviews']=[]
            r['subtitle_source_reviews']=[{'segment_id':'u1','source_start_sec':0,'source_end_sec':2.02,
                'text':'Synthetic question?','max_error_sec':.02,'accuracy_confirmed':True}]
        report=self.accepted([[0,2.02]],annotate)
        self.assertTrue(report['eligibility']['semantic_cuts'])
        self.assertFalse(self.evaluate([[0,2.02]],report)['affected_operations_blocked'])
        self.assertTrue(self.evaluate([[0,2]],report)['affected_operations_blocked'])

    def test_high_error_source_cues_do_not_certify_alignment(self):
        def annotate(r):
            r['boundary_reviews']=[]
            r['subtitle_source_reviews']=[{'segment_id':sid,'source_start_sec':a,'source_end_sec':b,
                'text':text,'max_error_sec':.5,'accuracy_confirmed':True} for sid,a,b,text in
                [('u1',0,2,'Synthetic question?'),('u2',4,6,'Synthetic answer.')]]
        report=self.accepted([[0,2]],annotate)
        self.assertFalse(report['eligibility']['segment_alignment'])
        self.assertFalse(report['eligibility']['semantic_cuts'])

    def test_out_of_source_cue_rejected(self):
        report=self.report();review=self.review(report,[[0,2]])
        review['subtitle_source_reviews']=[{'segment_id':'u1','source_start_sec':0,'source_end_sec':13,
            'text':'Synthetic question?','max_error_sec':.02,'accuracy_confirmed':True}]
        with self.assertRaises(s.base.AdapterError):s.review_data(review,report,'OFFLINE HUMAN FIXTURE')

    def test_corrected_context_spans_cannot_lose_question_answer(self):
        def annotate(r):
            r['boundary_reviews']=[]
            r['subtitle_source_reviews']=[{'segment_id':'u1','source_start_sec':0,'source_end_sec':2.02,
                'text':'Synthetic question?','max_error_sec':.02,'accuracy_confirmed':True}]
            r['context_links']=[{'kind':'question_answer','segment_ids':['u1','u2']}]
        report=self.accepted([[0,2.02]],annotate)
        self.assertIn('missing_question_answer_or_required_context',
            [r['code'] for r in self.evaluate([[0,2.02]],report)['findings']])


# Do not rediscover the inherited fixture's existing tests as new coverage.
for name in list(vars(fixtures.EvidenceTests)):
    if name.startswith('test_'): setattr(SourceCueTests,name,None)


if __name__ == "__main__": unittest.main()
