"""Synthetic ASR/review fixtures and real offline provenance regression. No paid calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT/'scripts'), str(PROJECT/'tests')]
import speech_intelligence_v01 as s
import speech_planning_v01 as planning
import run_adaptive_director_v03 as director
import adaptive_director_v03_fixtures as f
import benchmark_preview_v01 as preview


def setUpModule():
    global guard, live
    guard = patch('socket.socket.connect', side_effect=AssertionError('Offline synthetic fixture only')); guard.start()
    live = patch.object(director, 'live_response', side_effect=AssertionError('No live Director authorization')); live.start()


def tearDownModule(): live.stop(); guard.stop()


def draft():
    return {'segments': [
        {'segment_id': 'u1', 'start_sec': 0, 'end_sec': 2, 'text': 'Synthetic question?', 'language': 'xx',
         'words': [{'start_sec': .1, 'end_sec': .8, 'word': 'Synthetic', 'probability': .9},
                   {'start_sec': .9, 'end_sec': 1.9, 'word': 'question?', 'probability': None}]},
        {'segment_id': 'u2', 'start_sec': 4, 'end_sec': 6, 'text': 'Synthetic answer.', 'language': 'xx', 'words': []}],
        'provider_words': [], 'recognized_regions': []}


class Normalization(unittest.TestCase):
    def setUp(self): self.value = draft()
    def normalize(self): return s.normalize(self.value, 12)
    def test_clean_dialogue_text_exact(self): self.assertEqual(self.normalize()[0][0]['text'], self.value['segments'][0]['text'])
    def test_missing_word_probability_stays_null(self): self.assertIsNone(self.normalize()[1][1]['reported_probability'])
    def test_language_not_assumed(self): del self.value['segments'][0]['language']; self.assertIsNone(self.normalize()[0][0]['language'])
    def test_speaker_not_inferred(self): self.assertIsNone(self.normalize()[0][0]['reported_speaker'])
    def test_multiple_reported_speakers(self):
        for i, row in enumerate(self.value['segments']): row['speaker'] = i
        self.assertEqual([r['reported_speaker'] for r in self.normalize()[0]], ['0', '1'])
    def test_missing_alignment(self): self.value['segments'][0]['words'] = []; self.assertEqual(self.normalize()[1], [])
    def test_negative_timestamp(self): self.value['segments'][0]['start_sec'] = -1; self.assertIn('invalid_transcript_segment_or_timing', self.normalize()[3])
    def test_nonfinite_timestamp(self): self.value['segments'][0]['start_sec'] = float('nan'); self.assertTrue(self.normalize()[3])
    def test_boolean_timestamp(self): self.value['segments'][0]['start_sec'] = False; self.assertTrue(self.normalize()[3])
    def test_reversed_timestamp(self): self.value['segments'][0]['end_sec'] = 0; self.assertTrue(self.normalize()[3])
    def test_timestamp_outside_media(self): self.value['segments'][1]['end_sec'] = 13; self.assertTrue(self.normalize()[3])
    def test_word_outside_segment(self): self.value['segments'][0]['words'][0]['end_sec'] = 3; self.assertIn('word_outside_segment', self.normalize()[3])
    def test_invalid_probability(self): self.value['segments'][0]['words'][0]['probability'] = 2; self.assertIn('invalid_word_timing_or_confidence', self.normalize()[3])
    def test_invalid_confidence(self): self.value['segments'][0]['no_speech_prob'] = float('inf'); self.assertIn('invalid_reported_confidence', self.normalize()[3])
    def test_confidence_outside_probability_range(self): self.value['segments'][0]['no_speech_prob'] = 2; self.assertIn('invalid_reported_confidence', self.normalize()[3])
    def test_nonmonotonic_segments(self): self.value['segments'].reverse(); self.assertIn('nonmonotonic_transcript_segments', self.normalize()[3])
    def test_duplicate_id(self): self.value['segments'][1]['segment_id'] = 'u1'; self.assertIn('duplicate_segment_id', self.normalize()[3])
    def test_overlapping_segments_not_fake_verified(self): self.value['segments'][1]['start_sec'] = 1; self.assertEqual(self.normalize()[0][1]['start_sec'], 1)
    def test_text_only_does_not_borrow_upload_timestamps(self):
        self.value = {'recognized_regions': [{'region_id': 'r1', 'text': 'Source text', 'context_start_sec': 0, 'context_end_sec': 12}], 'segments': []}
        seg, words, text, issues = self.normalize(); self.assertEqual(seg, []); self.assertEqual(words, []); self.assertEqual(text[0], {'region_id': 'r1', 'text': 'Source text'}); self.assertEqual(issues, [])
    def test_provider_words_without_segments_preserved_unlinked(self):
        self.value['segments'] = []; self.value['provider_words'] = [{'start_sec': 1, 'end_sec': 2, 'word': 'raw'}]
        self.assertIsNone(self.normalize()[1][0]['segment_id'])
    def test_missing_transcript_text(self): del self.value['segments'][0]['text']; self.assertTrue(self.normalize()[3])
    def test_invalid_words_array(self): self.value['segments'][0]['words'] = 'not an array'; self.assertIn('malformed_segment_words', self.normalize()[3])
    def test_no_asr_data_no_fabrication(self): self.assertEqual(s.normalize({}, 180), ([], [], [], []))
    def test_varied_duration(self): self.value['segments'][1]['end_sec'] = 121; self.assertEqual(s.normalize(self.value, 180)[3], [])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT/'data'); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.paths = {k: self.root/(k+'.json' if k != 'video' else 'synthetic.mp4') for k in ('video', 'metadata', 'analysis')}
        for p in self.paths.values(): p.write_text('SYNTHETIC MOCK: no real ASR or human listening')
        self.packet = f.packet('present'); source = {k: v for k, v in self.packet['source'].items() if k not in ('path', 'sha256')}
        self.sha = s.gate.sha256_file(self.paths['video']); self.packet['source'].update(path=s.shared.relative(self.paths['video']), sha256=self.sha)
        self.value = draft(); self.bundle = self.root/'speech'; self.bundle.mkdir()
        self.value['provenance'] = {'source_sha256': self.sha, 'audio_pcm_sha256': 'a'*64}
        self.manifest = {'source': copy.deepcopy(source), 'speech_requirements': self.packet['speech']['requirements'], 'audio': {'source_pcm': {'sha256': 'a'*64}}}
        self.old = {'generation_status': 'complete', 'evidence_eligibility': {'status': 'ineligible', 'transcript': False, 'speech_alignment': False}}
        for name in (s.shared.MANIFEST, s.shared.REPORT, s.shared.GATE): (self.bundle/name).write_text('{}')
        p = patch.object(s.shared, 'verified_inputs', return_value=(self.paths, source, self.sha, self.packet['canonical'], [])); p.start(); self.addCleanup(p.stop)
        p = patch.object(s.intake, 'validate_speech_bundle', side_effect=lambda *_: (self.manifest, self.old)); p.start(); self.addCleanup(p.stop)
    def report(self):
        (self.bundle/s.shared.DRAFT).write_text(json.dumps(self.value))
        return s.assess(**self.paths, speech_bundle=self.bundle)
    def selection(self, windows, decision='supported'):
        return {'source_windows': windows, 'decision': decision, 'sentence_complete': True, 'qa_context_preserved': True,
            'meaning_preserved': True, 'multi_speaker_reviewed': True, 'music_overlap_reviewed': True}
    def review(self, report, windows):
        return {'contract_version': '0.1.0', 'origin': 'human_source_review', 'reviewer_identity': 'OFFLINE HUMAN FIXTURE',
            'source_sha256': self.sha, 'evidence_sha256': s.digest(report), 'review_method': 'source_audio_listening_and_waveform',
            'text_reviews': [{'segment_id': row['segment_id'], 'original_text_sha256': s.digest(row['text']),
                'reviewed_text': row['text'], 'accuracy_confirmed': True} for row in report['segments']],
            'boundary_reviews': [{'time_sec': t, 'max_error_sec': .02, 'accuracy_confirmed': True} for t in sorted({x for w in windows for x in w})],
            'word_reviews': [], 'selection_reviews': [self.selection(windows)], 'context_links': []}
    def accepted(self, windows, modify=None):
        report = self.report(); base = self.root/'base-report.json'; s.shared.write_json(base, report)
        review = self.review(report, windows)
        if modify: modify(review)
        submission = self.root/'submission.json'; s.shared.write_json(submission, review); receipt = self.root/'accepted.json'
        self.assertEqual(s.main(['accept-review', '--report', str(base), '--submission', str(submission),
            '--approved-by', 'OFFLINE HUMAN FIXTURE', '--output', str(receipt)]), 0)
        return s.assess(**self.paths, speech_bundle=self.bundle, human_review=receipt)
    def plan(self, windows):
        plan = f.plan(self.packet); variant = plan['variants'][0]
        variant['shots'] = [f.shot(a, b, 's'+str(i+1), i+1) for i, (a, b) in enumerate(windows)]
        variant['hook'].update({k: variant['shots'][0][k] for k in ('shot_id', 'source_start_sec', 'source_end_sec', 'timing_precision', 'evidence_refs')})
        variant['estimated_output_duration_sec'] = sum(b-a for a, b in windows)
        return plan
    def evaluate(self, windows, report=None): return s.evaluate_plan(self.plan(windows), self.packet, report)
    def test_valid_segment_timing_remains_estimate(self):
        report = self.report(); self.assertEqual(report['timestamp_precision'], 'asr_estimate'); self.assertFalse(report['eligibility']['segment_alignment']); self.assertFalse(report['eligibility']['word_alignment'])
    def test_provider_word_timing_not_verified(self): self.assertEqual(self.report()['alignment_confidence'], 'unverified')
    def test_draft_available_only_for_review(self): self.assertTrue(self.report()['eligibility']['transcript_for_review']); self.assertFalse(self.report()['eligibility']['semantic_cuts'])
    def test_failed_generation_cannot_promote(self): self.old['generation_status'] = 'failed'; self.assertFalse(self.report()['eligibility']['transcript_for_review'])
    def test_cross_source_draft_rejected(self): self.value['provenance']['source_sha256'] = '0'*64; self.assertRaises(s.base.AdapterError, self.report)
    def test_metadata_mismatch_rejected(self): self.manifest['source']['duration_sec'] = 99; self.assertRaises(s.base.AdapterError, self.report)
    def test_requirements_mismatch_rejected(self): self.manifest['speech_requirements'] = {}; self.assertRaises(s.base.AdapterError, self.report)
    def test_overlaps_preserve_uncertainty(self): self.value['segments'][1]['start_sec'] = 1; self.assertIn('overlapping_segments_not_independently_verified', self.report()['uncertainties'])
    def test_speakers_preserve_uncertainty(self):
        self.value['segments'][0]['speaker'] = 'a'; self.value['segments'][1]['speaker'] = 'b'; self.assertIn('multiple_reported_speakers', self.report()['uncertainties'])
    def test_low_reported_probability(self): self.value['segments'][0]['words'][0]['probability'] = .1; self.assertIn('low_provider_word_probability', self.report()['uncertainties'])
    def test_whole_context_supported_without_timing(self): self.assertFalse(self.evaluate([[0, 12]])['affected_operations_blocked'])
    def test_noncontiguous_unverified_selection(self): self.assertTrue(self.evaluate([[0, 2], [4, 6]], self.report())['affected_operations_blocked'])
    def test_partial_trim_without_alignment(self): self.assertTrue(self.evaluate([[1, 2]])['affected_operations_blocked'])
    def test_candidate_sentence_interruption(self): self.assertIn('possible_interrupted_utterance_at_cut', [r['code'] for r in self.evaluate([[1, 2]], self.report())['findings']])
    def test_exact_reviewed_selection_supported(self):
        report = self.accepted([[0, 2], [4, 6]]); result = self.evaluate([[0, 2], [4, 6]], report)
        self.assertFalse(result['affected_operations_blocked']); self.assertTrue(report['eligibility']['semantic_cuts']); self.assertFalse(report['eligibility']['word_alignment'])
    def test_review_is_not_global_cut_permission(self): report = self.accepted([[0, 2]]); self.assertTrue(self.evaluate([[4, 6]], report)['affected_operations_blocked'])
    def test_reordered_selection_needs_own_review(self): report = self.accepted([[0, 2], [4, 6]]); self.assertTrue(self.evaluate([[4, 6], [0, 2]], report)['affected_operations_blocked'])
    def test_known_unsafe_human_selection(self):
        report = self.accepted([[0, 2]], lambda r: r['selection_reviews'][0].update(decision='unsafe'))
        self.assertFalse(report['eligibility']['semantic_cuts']); self.assertEqual(self.evaluate([[0, 2]], report)['status'], 'BLOCKED_UNSAFE_OPERATION')
    def test_question_answer_context_missing(self):
        report = self.accepted([[0, 2]], lambda r: r['context_links'].append({'kind': 'question_answer', 'segment_ids': ['u1', 'u2']}))
        self.assertIn('missing_question_answer_or_required_context', [r['code'] for r in self.evaluate([[0, 2]], report)['findings']])
    def test_inaccurate_boundary_blocks(self):
        report = self.accepted([[0, 2]], lambda r: r['boundary_reviews'][1].update(max_error_sec=.5)); self.assertTrue(self.evaluate([[0, 2]], report)['affected_operations_blocked'])
    def test_missing_semantic_confirmation(self):
        report = self.accepted([[0, 2]], lambda r: r['selection_reviews'][0].update(meaning_preserved=False)); self.assertTrue(self.evaluate([[0, 2]], report)['affected_operations_blocked'])
    def test_unreviewed_multispeaker_selection(self):
        report = self.accepted([[0, 2]], lambda r: r['selection_reviews'][0].update(multi_speaker_reviewed=False)); self.assertTrue(self.evaluate([[0, 2]], report)['affected_operations_blocked'])
    def test_mixed_music_requires_context_review(self):
        self.packet['canonical']['content_profile']['music_presence'] = 'present'; self.packet['canonical']['segments'][0]['audio_layers'] = ['speech', 'music']
        self.packet['speech']['requirements'] = s.gate.speech_requirements(self.packet['canonical']); self.manifest['speech_requirements'] = self.packet['speech']['requirements']
        report = self.accepted([[0, 2]], lambda r: r['selection_reviews'][0].update(music_overlap_reviewed=False)); self.assertTrue(self.evaluate([[0, 2]], report)['affected_operations_blocked'])
    def test_music_only_no_transcript_block(self):
        packet = f.packet('absent', 'present'); result = s.evaluate_plan(f.plan(packet), packet)
        self.assertEqual(result['status'], 'NOT_APPLICABLE'); self.assertFalse(result['affected_operations_blocked'])
    def test_uncertain_speech_trim_not_no_speech(self):
        self.packet['speech']['requirements']['overall_requirement'] = 'needs_review'; self.assertEqual(self.evaluate([[0, 2]])['status'], 'INSUFFICIENT_EVIDENCE')
    def test_conflicting_profile_and_regions_block(self): self.packet['speech']['requirements']['classification_conflicts'] = ['contradiction']; self.assertTrue(self.evaluate([[0, 2]])['affected_operations_blocked'])
    def test_uncertain_complete_context_keeps_review(self):
        self.packet['speech']['requirements']['overall_requirement'] = 'needs_review'; result = self.evaluate([[0, 12]])
        self.assertFalse(result['affected_operations_blocked']); self.assertEqual(result['status'], 'NEEDS_HUMAN_REVIEW')
    def test_speed_change_not_safe(self): plan = self.plan([[0, 12]]); plan['variants'][0]['shots'][0]['timing']['speed'] = 1.1; self.assertTrue(s.evaluate_plan(plan, self.packet)['affected_operations_blocked'])
    def test_freeze_not_safe(self): plan = self.plan([[0, 12]]); plan['variants'][0]['shots'][0]['timing']['freeze_sec'] = 1; self.assertTrue(s.evaluate_plan(plan, self.packet)['affected_operations_blocked'])
    def test_invalid_source_timing(self): self.assertEqual(self.evaluate([[0, 13]])['status'], 'BLOCKED_UNSAFE_OPERATION')
    def test_unverified_subtitle_blocks_even_music(self):
        packet = f.packet('absent', 'present'); plan = f.plan(packet); operation = f.operation('subtitle'); operation['parameters']['caption'].update(text='Invented', kind='asr_draft'); plan['variants'][0]['operations'] = [operation]
        self.assertEqual(s.evaluate_plan(plan, packet)['status'], 'BLOCKED_UNSAFE_OPERATION')
    def test_placeholder_does_not_invent_words(self):
        plan = self.plan([[0, 12]]); plan['variants'][0]['operations'] = [f.operation('subtitle', {'text':None,'kind':'placeholder','verification_status':'unverified','evidence_refs':['canonical.segments.0'],'publish_ready':False})]
        result = s.evaluate_plan(plan, self.packet); self.assertFalse(result['affected_operations_blocked']); self.assertIn('subtitle_placeholder_requires_review', [r['code'] for r in result['findings']])
    def test_factual_claim_not_authenticated_by_asr(self):
        plan = self.plan([[0, 12]]); plan['factual_claims'] = [{'verification_status': 'verified', 'kind': 'spoken_statement'}]
        self.assertEqual(s.evaluate_plan(plan, self.packet)['status'], 'BLOCKED_UNSAFE_OPERATION')
    def test_second_variant_cannot_bypass_guard(self):
        plan = self.plan([[0, 12]]); second = self.plan([[0, 2]])['variants'][0]; second['variant_id'] = 'B'; plan['variants'].append(second)
        self.assertTrue(s.evaluate_plan(plan, self.packet)['affected_operations_blocked'])
    def test_model_semantic_self_report_not_proof(self):
        plan = self.plan([[0, 2]]); plan['variants'][0]['shots'][0]['speech_safe'] = True; self.assertTrue(s.evaluate_plan(plan, self.packet, self.report())['affected_operations_blocked'])
    def test_review_actor_binding(self): report = self.report(); self.assertRaises(s.base.AdapterError, s.review_data, self.review(report, [[0, 2]]), report, 'MODEL')
    def test_model_review_origin_rejected(self):
        report = self.report(); review = self.review(report, [[0, 2]]); review['origin'] = 'model'; self.assertRaises(s.base.AdapterError, s.review_data, review, report, review['reviewer_identity'])
    def test_review_source_binding(self):
        report = self.report(); review = self.review(report, [[0, 2]]); review['source_sha256'] = 'b'*64; self.assertRaises(s.base.AdapterError, s.review_data, review, report, review['reviewer_identity'])
    def test_review_exact_text_binding(self):
        report = self.report(); review = self.review(report, [[0, 2]]); review['text_reviews'][0]['original_text_sha256'] = 'b'*64; self.assertRaises(s.base.AdapterError, s.review_data, review, report, review['reviewer_identity'])
    def test_review_duplicate_selections(self):
        report = self.report(); review = self.review(report, [[0, 2]]); review['selection_reviews'] *= 2; self.assertRaises(s.base.AdapterError, s.review_data, review, report, review['reviewer_identity'])
    def test_report_tamper_rejected(self):
        report = self.report(); report['eligibility']['word_alignment'] = True; p = self.root/'tampered.json'; s.shared.write_json(p, report); self.assertRaises(s.base.AdapterError, s.load_report, p)
    def test_unknown_report_fields_rejected(self): report = self.report(); report['verified'] = True; self.assertRaises(s.base.AdapterError, s.check, 'report', report)
    def test_symlink_input_rejected(self): p = self.root/'link.json'; p.symlink_to(self.bundle/s.shared.MANIFEST); self.assertRaises(s.base.AdapterError, s.read, p)
    def test_traversal_rejected(self): self.assertRaises(s.base.AdapterError, s.read, 'data/../config/speech-asr.remote.v01.json')
    def test_existing_output_protected(self):
        out = self.root/'output.json'; out.write_text('original'); self.assertEqual(s.main(['assess', '--video', str(self.paths['video']), '--metadata', str(self.paths['metadata']), '--analysis', str(self.paths['analysis']), '--output', str(out)]), 1); self.assertEqual(out.read_text(), 'original')
    def test_explicit_eligibility_not_exit_code(self):
        out = self.root/'assessment.json'; self.assertEqual(s.main(['assess', '--video', str(self.paths['video']), '--metadata', str(self.paths['metadata']), '--analysis', str(self.paths['analysis']), '--output', str(out)]), 0)
        self.assertEqual(s.read(out)['eligibility']['status'], 'INSUFFICIENT_EVIDENCE')
    def test_independent_validator_blocks_dialogue_trim(self):
        result = director.validator.validate_plan(self.plan([[0, 2]]), self.packet)
        self.assertEqual(result['status'], 'BLOCKED'); self.assertTrue(any(r['code'].startswith('speech_intelligence:') for r in result['blocking_findings']))
    def test_revision_uses_shared_validator(self):
        proposal = {'plan': self.plan([[0, 2]])}; report = self.report()
        with patch('run_revision_loop_v01.validate_proposal', return_value={'blocking_reasons': []}) as legacy:
            result = planning.validate_revision(proposal, {}, self.packet, {}, {}, {}, report)
        legacy.assert_called_once(); self.assertTrue(result['affected_operations_blocked']); self.assertFalse(result['render_approved'])
    def test_benchmark_rejects_forged_report(self):
        report = self.report(); report['eligibility']['reviewed_transcript'] = True
        self.assertRaises(s.base.AdapterError, preview.speech_safety, self.plan([[0, 2]]), self.packet, report)
    def test_director_context_keeps_quarantine(self):
        report = self.report(); p = self.root/'report.json'; s.shared.write_json(p, report)
        packet = planning.enrich_packet(self.packet, report, p)
        self.assertEqual(packet['speech_intelligence']['reviewed_text'], []); self.assertFalse(packet['speech']['eligibility']['transcript'])
    def test_source_contamination_rejected(self):
        report = self.report(); report['source']['sha256'] = 'b'*64; self.assertRaises(s.base.AdapterError, s.evaluate_plan, self.plan([[0, 2]]), self.packet, report)
    def test_accepted_source_windows_do_not_allow_speed_change(self):
        report = self.accepted([[0, 2]]); plan = self.plan([[0, 2]]); plan['variants'][0]['shots'][0]['timing']['speed'] = 1.1
        self.assertTrue(s.evaluate_plan(plan, self.packet, report)['affected_operations_blocked'])
    def test_shared_validator_accepts_only_replayed_supported_selection(self):
        report = self.accepted([[0, 2], [4, 6]]); path = self.root/'reviewed-report.json'; s.shared.write_json(path, report)
        packet = planning.enrich_packet(self.packet, report, path); plan = self.plan([[0, 2], [4, 6]]); plan['evidence_packet_sha256'] = director.validator.packet_digest(packet)
        result = director.validator.validate_plan(plan, packet)
        self.assertEqual(result['status'], 'NEEDS_REVIEW'); self.assertEqual(result['blocking_findings'], []); self.assertFalse(result['render_approved'])
    def test_shared_validator_rejects_changed_report(self):
        report = self.accepted([[0, 2]]); path = self.root/'reviewed-report.json'; s.shared.write_json(path, report)
        packet = planning.enrich_packet(self.packet, report, path); plan = self.plan([[0, 2]]); plan['evidence_packet_sha256'] = director.validator.packet_digest(packet)
        report['eligibility']['word_alignment'] = True; path.write_text(json.dumps(report))
        self.assertEqual(director.validator.validate_plan(plan, packet)['status'], 'BLOCKED')
    def test_source_reviewed_subtitle_exact_mapping_supported(self):
        def annotate(r): r['subtitle_reviews'] = [{'variant_id':'A','operation_id':'o1','source_start_sec':0,'source_end_sec':2,
            'text':'Synthetic question?', 'max_error_sec':.02,'accuracy_confirmed':True}]
        report = self.accepted([[0, 2]], annotate); plan = self.plan([[0, 2]])
        op = f.operation('subtitle'); op['output_end_sec'] = 2; op['parameters']['caption'].update(text='Synthetic question?', kind='asr_draft')
        plan['variants'][0]['operations'] = [op]
        result = s.evaluate_plan(plan, self.packet, report); self.assertFalse(result['affected_operations_blocked'])
        path = self.root/'reviewed-report.json'; s.shared.write_json(path, report); packet = planning.enrich_packet(self.packet, report, path)
        plan['evidence_packet_sha256'] = director.validator.packet_digest(packet)
        self.assertEqual(director.validator.validate_plan(plan, packet)['blocking_findings'], [])
    def test_verified_quote_requires_exact_independent_subtitle_review(self):
        def annotate(r): r['subtitle_reviews']=[{'variant_id':'A','operation_id':'o1','source_start_sec':0,
            'source_end_sec':2,'text':'Synthetic question?','max_error_sec':.02,'accuracy_confirmed':True}]
        report=self.accepted([[0,2]],annotate); path=self.root/'reviewed-subtitle.json';s.shared.write_json(path,report)
        packet=planning.enrich_packet(self.packet,report,path); plan=self.plan([[0,2]])
        operation=f.operation('subtitle',{'text':'Synthetic question?','kind':'verified_quote','verification_status':'verified',
            'evidence_refs':['canonical.segments.0'],'publish_ready':False})
        operation['output_end_sec']=2;plan['variants'][0]['operations']=[operation]
        plan['evidence_packet_sha256']=director.validator.packet_digest(packet)
        result=director.validator.validate_plan(plan,packet)
        self.assertEqual(result['blocking_findings'],[]);self.assertFalse(result['render_approved'])
        operation['parameters']['caption']['text']='Different speech'
        self.assertEqual(director.validator.validate_plan(plan,packet)['status'],'BLOCKED')
    def test_reviewed_subtitle_line_wrapping_preserves_exact_words(self):
        def annotate(r): r['subtitle_reviews']=[{'variant_id':'A','operation_id':'o1','source_start_sec':0,
            'source_end_sec':2,'text':'Synthetic question?','max_error_sec':.02,'accuracy_confirmed':True}]
        report=self.accepted([[0,2]],annotate); plan=self.plan([[0,2]])
        operation=f.operation('subtitle',{'text':'Synthetic\nquestion?','kind':'verified_quote','verification_status':'verified',
            'evidence_refs':['canonical.segments.0'],'publish_ready':False})
        operation['output_end_sec']=2;plan['variants'][0]['operations']=[operation]
        self.assertFalse(s.evaluate_plan(plan,self.packet,report)['affected_operations_blocked'])
    def test_reviewed_caption_does_not_allow_new_text(self):
        report = self.accepted([[0, 2]]); plan = self.plan([[0, 2]]); op = f.operation('subtitle'); op['parameters']['caption']['text'] = 'Fabricated words'
        plan['variants'][0]['operations'] = [op]; self.assertTrue(s.evaluate_plan(plan, self.packet, report)['affected_operations_blocked'])
    def test_generalized_report_does_not_grant_render_permission(self):
        report = self.accepted([[0, 2]]); self.assertFalse(report['render_approved']); self.assertFalse(report['publish_approved'])
    def test_partial_boundary_review_does_not_certify_all_segments(self):
        report = self.accepted([[0, 2]]); self.assertFalse(report['eligibility']['segment_alignment']); self.assertTrue(report['eligibility']['semantic_cuts'])
    def test_complete_boundary_review_remains_distinct_from_words(self):
        report = self.accepted([[0, 2], [4, 6]]); self.assertTrue(report['eligibility']['segment_alignment']); self.assertFalse(report['eligibility']['word_alignment'])
    def test_unclear_reported_generation_flags_preserved(self):
        self.old['quality_assessment'] = {'flags':[{'code':'low_avg_logprob','segment_id':'u1'}]}
        self.assertIn('generation_quality:low_avg_logprob', self.report()['uncertainties'])
    def test_reviewed_words_require_each_exact_word_binding(self):
        self.value['segments'][1]['words'] = [{'start_sec':4,'end_sec':4.5,'word':'Synthetic'}, {'start_sec':4.6,'end_sec':5.9,'word':'answer.'}]
        def annotate(review):
            for row in review['text_reviews']: row['word_coverage_confirmed'] = True
            report = self.report(); review['word_reviews'] = [{'word_id':w['word_id'],'word_sha256':s.digest(w),
                'max_error_sec':.02,'accuracy_confirmed':True} for w in report['words']]
        report = self.accepted([[0, 2]], annotate); self.assertTrue(report['eligibility']['word_alignment']); self.assertEqual(report['timestamp_precision'],'asr_estimate')
    def test_actual_revision_entrypoint_blocks_unsupported_dialogue(self):
        from test_revision_loop_v01 import sample, loop
        packet,parent,brief,proposal,spec,registry = sample()
        packet['speech']['requirements'] = f.packet('present')['speech']['requirements']
        plan = f.plan(packet); plan['variants'][0]['shots'][0]['source_end_sec'] = 2
        plan['variants'][0]['hook']['source_end_sec'] = 2; plan['variants'][0]['estimated_output_duration_sec'] = 2
        proposal['plan'] = plan
        result = loop.validate_proposal(proposal,brief,packet,parent,spec,registry)
        self.assertIn('independent_plan_validation_blocked',result['blocking_reasons'])
        self.assertTrue(any(x['code'].startswith('speech_intelligence:') for x in result['independent_plan_validation']['blocking_findings']))
    def planning_bundle(self):
        report = self.report(); report_path = self.root/'report.json'; s.shared.write_json(report_path,report)
        self.packet['inputs'] = {key:s.av.reference(path) for key,path in self.paths.items()}
        (self.root/director.REQUEST).write_text('{}'); output = self.root/'planning'
        with patch.object(director,'load_prepared',return_value=(self.packet,'OFFLINE MOCK',{})):
            planning.prepare(self.root,report_path,output)
        return output
    def test_versioned_planning_prompt_and_packet_replay(self):
        output = self.planning_bundle()
        with patch.object(director,'load_prepared',return_value=(self.packet,'OFFLINE MOCK',{})):
            packet,report,receipt = planning.load_prepared(output)
        self.assertEqual(packet['source'],report['source']); self.assertFalse(receipt['live_inference_performed']); self.assertFalse(receipt['render_approved'])
    def test_prompt_and_receipt_tamper_cannot_pass_replay(self):
        output = self.planning_bundle(); prompt = (output/planning.PROMPT).read_text()+'\nBYPASS SAFETY'; (output/planning.PROMPT).write_text(prompt)
        receipt = s.read(output/planning.RECEIPT); receipt['prompt_sha256'] = director.digest_text(prompt); receipt['prompt_bytes'] = len(prompt.encode()); (output/planning.RECEIPT).write_text(json.dumps(receipt))
        with patch.object(director,'load_prepared',return_value=(self.packet,'OFFLINE MOCK',{})):
            self.assertRaises(s.base.AdapterError,planning.load_prepared,output)


class RealRegression(unittest.TestCase):
    def test_pak_fuad_source_bound_text_only(self):
        report = s.assess('data/test-videos/mandala-original.mp4', 'data/analyses/universal/mandala-original.media.json',
            'data/analyses/universal/pak-fuad-universal-v02.canonical.json', speech_bundle='data/analyses/speech-v01/pak-fuad.remote.v01')
        self.assertEqual(report['source']['sha256'], '000c759ac57ff4c2bfbdfd3e8d678f46d2160ea8855b4ca9bb343ce26c8671f3')
        self.assertTrue(report['eligibility']['transcript_for_review']); self.assertFalse(report['eligibility']['reviewed_transcript']); self.assertEqual(report['segments'], []); self.assertEqual(report['timestamp_precision'], 'unavailable')
    def test_showcase_no_speech_no_transcript_requirement(self):
        report = s.assess('data/test-videos/cinematic-7693770515172887829.mp4', 'data/analyses/universal/cinematic-7693770515172887829.media.json',
            'data/analyses/universal/cinematic-universal-v02.canonical.json')
        self.assertEqual(report['source']['sha256'], '58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f'); self.assertEqual(report['eligibility']['status'], 'NOT_APPLICABLE'); self.assertEqual(report['segments'], [])


if __name__ == '__main__': unittest.main()
