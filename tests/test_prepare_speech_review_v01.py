"""Offline review preparation, not human acceptance or recognition tests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import prepare_speech_review_v01 as review


def evidence():
    return {'source': {'sha256': 'a'*64, 'duration_sec': 8}, 'segments': [
        {'segment_id': 's1', 'start_sec': 0, 'end_sec': 2, 'text': ' Synthetic wrong word '},
        {'segment_id': 's2', 'start_sec': 3, 'end_sec': 5, 'text': 'Synthetic answer'}],
        'words': [], 'eligibility': {'reviewed_transcript': False, 'semantic_cuts': False}}


def feedback():
    return {'origin': 'user_supplied_feedback', 'source_sha256': 'a'*64, 'segment_id': 's1',
        'from': 'wrong', 'to': 'corrected', 'user_statement': 'Synthetic test feedback only'}


class ReviewProposalTests(unittest.TestCase):
    def test_feedback_changes_only_proposal(self):
        report=evidence(); original=copy.deepcopy(report)
        packet=review.proposal(report,[feedback()])
        self.assertEqual(report,original)
        self.assertEqual(packet['segments'][0]['text'],' Synthetic wrong word ')
        self.assertEqual(packet['segments'][0]['proposed_text'],'Synthetic corrected word')
        self.assertEqual(packet['segments'][0]['original_text_sha256'],review.speech.digest(report['segments'][0]['text']))

    def test_no_acceptance_or_word_timing_fabrication(self):
        packet=review.proposal(evidence(),[feedback()])
        self.assertIsNone(packet['human_review']); self.assertFalse(packet['render_approved'])
        self.assertFalse(packet['publish_approved']); self.assertFalse(packet['eligibility']['reviewed_transcript'])
        self.assertEqual(packet['word_timestamps'],'unavailable')
        self.assertEqual(packet['boundaries_sec'],[0,2,3,5])

    def test_cross_source_feedback_rejected(self):
        f=feedback(); f['source_sha256']='b'*64
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(evidence(),[f])

    def test_non_user_origin_rejected(self):
        f=feedback(); f['origin']='model_review'
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(evidence(),[f])

    def test_feedback_cannot_smuggle_approval(self):
        f=feedback(); f['accuracy_confirmed']=True
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(evidence(),[f])

    def test_unknown_segment_rejected(self):
        f=feedback(); f['segment_id']='unknown'
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(evidence(),[f])

    def test_missing_word_rejected(self):
        f=feedback(); f['from']='absent'
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(evidence(),[f])

    def test_substring_is_not_exact_word(self):
        f=feedback(); f['from']='wron'
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(evidence(),[f])

    def test_ambiguous_word_rejected(self):
        report=evidence(); report['segments'][0]['text']='wrong wrong'
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(report,[feedback()])

    def test_candidate_windows_remain_unverified(self):
        c={'candidate_id':'one','label':'Synthetic candidate','basis':'offline diagnostic','source_windows':[[0,2],[3,5]]}
        packet=review.proposal(evidence(),candidates=[c])
        self.assertNotIn('review_status',c)
        self.assertEqual(packet['candidates'][0]['review_status'],'PENDING_HUMAN_REVIEW')

    def test_invalid_candidate_timing_rejected(self):
        for window in [[-1,2],[0,9],[2,2],[True,2],[0,float('nan')]]:
            with self.subTest(window=window), self.assertRaises(review.speech.base.AdapterError):
                review.proposal(evidence(),candidates=[{'candidate_id':'x','label':'x','basis':'x','source_windows':[window]}])

    def test_duplicate_candidates_rejected(self):
        c={'candidate_id':'x','label':'x','basis':'x','source_windows':[[0,2]]}
        with self.assertRaises(review.speech.base.AdapterError): review.proposal(evidence(),candidates=[c,c])

    def test_ui_exports_notes_never_attestation(self):
        self.assertIn("origin:'human_review_notes_unaccepted'",review.PAGE)
        self.assertIn('accepted:false',review.PAGE)
        self.assertNotIn("origin:'human_source_review'",review.PAGE)

    def test_offline_real_source_packet_and_exclusive_output(self):
        path=ROOT/'data/analyses/speech-v01/pak-fuad.remote-timed.v01/speech-intelligence-assessment.v01.json'
        before=review.speech.gate.sha256_file(path)
        with tempfile.TemporaryDirectory(dir=ROOT/'data',prefix='review-tests-') as temporary, \
                patch('socket.socket.connect',side_effect=AssertionError('No network')):
            output=Path(temporary)/'packet'
            fresh=Path(temporary)/'current-assessment.json'
            request=json.loads(path.read_text())['request']
            review.speech.shared.write_json(fresh,review.speech.assess(**request))
            review.prepare(str(fresh),str(output))
            packet=json.loads((output/'review-packet.v01.json').read_text())
            page=(output/'review.html').read_text()
            self.assertEqual(len(packet['segments']),15)
            self.assertGreater(len(packet['waveform']['bins']),1800)
            self.assertIsNone(packet['human_review'])
            self.assertNotIn('@@PACKET@@',page); self.assertNotIn('@@VIDEO@@',page)
            with self.assertRaises(review.speech.base.AdapterError): review.prepare(str(fresh),str(output))
        self.assertEqual(review.speech.gate.sha256_file(path),before)


if __name__ == '__main__': unittest.main()
