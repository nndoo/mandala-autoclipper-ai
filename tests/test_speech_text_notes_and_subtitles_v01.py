"""Synthetic text-only review and source/output caption mapping; no fake human timing."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import accept_speech_text_notes_v01 as notes
import prepare_segment_subtitles_v01 as subtitles


def report():
    return {'source':{'sha256':'a'*64,'duration_sec':10},'request':{'human_review':None},
        'code_receipts':[], 'words':[], 'segments':[
            {'segment_id':'s1','start_sec':1,'end_sec':3,'text':'Original question'},
            {'segment_id':'s2','start_sec':5,'end_sec':7,'text':'Original answer'}],
        'eligibility':{'reviewed_transcript':False,'segment_alignment':False,'semantic_cuts':False}}


def user_notes(r):
    return {'origin':'human_review_notes_unaccepted','source_sha256':r['source']['sha256'],
        'evidence_sha256':notes.speech.digest(r),'reviewer_identity':'',
        'text_notes':[{'segment_id':s['segment_id'],'original_text_sha256':notes.speech.digest(s['text']),
            'proposed_text':s['text'],'notes':'Synthetic explicitly endorsed feedback'} for s in r['segments']]}


class TextNotesTests(unittest.TestCase):
    def test_valid_text_only_submission_preserves_unknowns(self):
        r=report(); human=notes.submission(user_notes(r),r,r,'synthetic-reviewer')
        self.assertEqual(human['review_method'],'user_supplied_review_notes')
        self.assertTrue(all(s['accuracy_confirmed'] for s in human['text_reviews']))
        for key in ['boundary_reviews','word_reviews','selection_reviews','context_links','subtitle_reviews']:
            self.assertEqual(human[key],[])
        notes.speech.review_data(human,r,'synthetic-reviewer')

    def test_blank_identity_rejected(self):
        r=report()
        with self.assertRaises(notes.speech.base.AdapterError): notes.submission(user_notes(r),r,r,'')

    def test_cross_source_rejected(self):
        r=report(); n=user_notes(r);n['source_sha256']='b'*64
        with self.assertRaises(notes.speech.base.AdapterError): notes.submission(n,r,r,'x')

    def test_stale_text_hash_rejected(self):
        r=report();n=user_notes(r);n['text_notes'][0]['original_text_sha256']='c'*64
        with self.assertRaises(notes.speech.base.AdapterError): notes.submission(n,r,r,'x')

    def test_evidence_semantic_change_rejected(self):
        r=report();current=copy.deepcopy(r);current['segments'][0]['end_sec']=4
        with self.assertRaises(notes.speech.base.AdapterError):notes.submission(user_notes(r),r,current,'x')

    def test_only_receipt_revision_can_rebind_same_evidence(self):
        r=report();current=copy.deepcopy(r);current['code_receipts']=[{'path':'synthetic','sha256':'c'*64}]
        self.assertEqual(notes.submission(user_notes(r),r,current,'x')['evidence_sha256'],notes.speech.digest(current))

    def test_unreviewed_and_duplicate_segments_rejected(self):
        r=report()
        for change in ('missing','duplicate','blank'):
            n=user_notes(r)
            if change=='missing':n['text_notes'].pop()
            elif change=='duplicate':n['text_notes'][1]=n['text_notes'][0]
            else:n['text_notes'][0]['notes']=''
            with self.subTest(change=change),self.assertRaises(notes.speech.base.AdapterError):notes.submission(n,r,r,'x')

    def test_qualitative_method_cannot_certify_boundaries(self):
        r=report();h=notes.submission(user_notes(r),r,r,'x')
        h['boundary_reviews']=[{'time_sec':1,'accuracy_confirmed':True,'max_error_sec':.01}]
        with self.assertRaises(notes.speech.base.AdapterError):notes.speech.review_data(h,r,'x')

    def test_qualitative_method_cannot_certify_semantics(self):
        r=report();h=notes.submission(user_notes(r),r,r,'x')
        h['selection_reviews']=[{'source_windows':[[1,3]],'decision':'supported',
            **{k:True for k in ['sentence_complete','qa_context_preserved','meaning_preserved','multi_speaker_reviewed','music_overlap_reviewed']}}]
        with self.assertRaises(notes.speech.base.AdapterError):notes.speech.review_data(h,r,'x')


class SubtitleTests(unittest.TestCase):
    def setUp(self):
        self.r=report();self.r['human_review']=notes.submission(user_notes(self.r),self.r,self.r,'synthetic-reviewer')
        self.r['eligibility']['reviewed_transcript']=True

    def test_whole_source_timeline_preserved(self):
        result=subtitles.captions(self.r,[[0,10]])
        self.assertEqual([(c['output_start_sec'],c['output_end_sec']) for c in result['cues']],[(1,3),(5,7)])
        self.assertEqual(result['status'],'DRAFT_NOT_EXECUTABLE');self.assertFalse(result['segment_alignment'])
        self.assertFalse(result['render_approved']);self.assertFalse(result['publish_approved'])
        self.assertEqual(result['word_timestamps'],'unavailable')

    def test_reorder_maps_each_segment_to_output(self):
        result=subtitles.captions(self.r,[[5,7],[1,3]])
        self.assertEqual([(c['segment_id'],c['output_start_sec'],c['output_end_sec']) for c in result['cues']],
            [('s2',0,2),('s1',2,4)])

    def test_trim_retains_source_audio_video_clock_mapping(self):
        cue=subtitles.captions(self.r,[[4,8]])['cues'][0]
        self.assertEqual((cue['source_start_sec'],cue['source_end_sec']),(5,7))
        self.assertEqual((cue['output_start_sec'],cue['output_end_sec']),(1,3))

    def test_partial_segment_selection_rejected(self):
        for windows in [[[2,3]],[[1,2]],[[0,2],[2,10]]]:
            with self.subTest(windows=windows),self.assertRaises(subtitles.core.Error):subtitles.captions(self.r,windows)

    def test_no_dialogue_subtitles_for_empty_or_silent_selection(self):
        with self.assertRaises(subtitles.core.Error):subtitles.captions(self.r,[[8,10]])

    def test_unreviewed_text_cannot_supply_caption(self):
        self.r['eligibility']['reviewed_transcript']=False
        with self.assertRaises(subtitles.core.Error):subtitles.captions(self.r,[[0,10]])

    def test_missing_reviewed_segment_rejected(self):
        self.r['human_review']['text_reviews'].pop()
        with self.assertRaises(subtitles.core.Error):subtitles.captions(self.r,[[0,10]])

    def test_overlapping_cues_need_separate_review(self):
        self.r['segments'][1]['start_sec']=2
        with self.assertRaises(subtitles.core.Error):subtitles.captions(self.r,[[0,10]])

    def test_safe_line_layout_and_srt_millisecond_precision(self):
        result=subtitles.captions(self.r,[[0,10]])
        for cue in result['cues']:self.assertLessEqual(len(cue['display_text'].splitlines()),3)
        self.assertIn('00:00:01,000 --> 00:00:03,000',subtitles.srt(result['cues']))
        self.assertEqual(subtitles.clock(59.9996),'00:01:00,000')

    def test_invalid_windows_rejected(self):
        for windows in [[],[[-1,3]],[[0,11]],[[True,3]]]:
            with self.subTest(windows=windows),self.assertRaises(subtitles.core.Error):subtitles.captions(self.r,windows)


if __name__=='__main__':unittest.main()
