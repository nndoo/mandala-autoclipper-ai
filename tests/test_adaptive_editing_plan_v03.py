"""Independent temporal, factual, uncertainty, variation and approval tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import validate_adaptive_director_plan_v03 as v
import adaptive_director_v03_fixtures as f


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.packet=f.packet();self.plan=f.plan(self.packet)
        self.variant=self.plan['variants'][0];self.shot=self.variant['shots'][0]
    def check(self,code=None):
        r=v.validate_plan(self.plan,self.packet)
        if code:self.assertIn(code,[x['code'] for x in r['blocking_findings']+r['review_findings']],r)
        return r
    def blocked(self):
        r=self.check();self.assertEqual(r['status'],'BLOCKED');return r
    def test_one_variant(self):self.assertEqual(self.check()['status'],'NEEDS_REVIEW')
    def test_structure_separate_render_readiness(self):
        r=self.check();self.assertTrue(r['structural_validity']);self.assertEqual(r['render_readiness'],'BLOCKED_FOR_RENDER');self.assertFalse(r['render_gate_passed'])
    def test_deterministic(self):self.assertEqual(self.check(),self.check())
    def test_source_mismatch(self):self.plan['source']['sha256']='b'*64;self.check('source_identity_mismatch')
    def test_packet_hash_mismatch(self):self.plan['evidence_packet_sha256']='b'*64;self.check('evidence_packet_hash_mismatch')
    def test_missing_evidence_omitted(self):self.plan['missing_evidence']=[];self.check('missing_evidence_omitted')
    def test_count_mismatch(self):self.plan['proposed_variant_count']=2;self.check('variant_count_mismatch')
    def test_one_variant_policy(self):self.packet['editorial_policy']['allow_fewer_variants']=False;self.check('policy_variant_count')
    def test_hook_not_first(self):self.variant['hook']['source_start_sec']=1;self.check('hook_first_shot_mismatch')
    def test_unknown_reference(self):self.shot['evidence_refs']=['missing'];self.check('unknown_evidence_reference')
    def test_metadata_cannot_ground_hook(self):self.variant['hook']['evidence_refs']=['source.metadata'];self.check('source_range_without_relevant_evidence')
    def test_signal_precision_requires_signal(self):self.shot['timing_precision']='signal_estimated';self.check('signal_precision_without_signal_evidence')
    def test_invalid_frame_precision(self):self.shot['timing_precision']='frame_verified';self.check('unsupported_timing_precision')
    def test_invalid_manual_precision(self):self.shot['timing_precision']='manual_verified';self.check('unsupported_timing_precision')
    def test_invalid_asr_precision(self):self.shot['timing_precision']='asr_estimate';self.check('unsupported_timing_precision')
    def test_negative_source_time(self):self.shot['source_start_sec']=-1;self.blocked()
    def test_negative_duration(self):self.shot['source_start_sec']=11;self.shot['source_end_sec']=10;self.check('invalid_source_range')
    def test_zero_duration(self):self.shot['source_end_sec']=0;self.blocked()
    def test_out_of_range(self):self.shot['source_end_sec']=13;self.check('invalid_source_range')
    def test_nan(self):self.shot['source_end_sec']=float('nan');self.check('schema_invalid')
    def test_inf(self):self.shot['source_end_sec']=float('inf');self.check('schema_invalid')
    def test_invalid_speed(self):self.shot['timing']['speed']=0;self.blocked()
    def test_invalid_freeze(self):self.shot['timing']['freeze_sec']=3;self.blocked()
    def test_cut_overlap(self):self.shot['timing']['overlap_sec']=.2;self.check('cut_overlap_nonzero')
    def test_last_transition(self):self.shot['timing'].update(transition_out='crossfade',overlap_sec=.2);self.check('final_transition_invalid')
    def test_zero_crossfade(self):
        a,b=f.shot(0,6),f.shot(6,12,'s2',2);a['timing']['transition_out']='crossfade';f.set_shots(self.variant,[a,b]);self.check('crossfade_overlap_missing')
    def test_crossfade_next_too_short(self):
        a,b=f.shot(0,6),f.shot(6,6.2,'s2',2);a['timing'].update(transition_out='crossfade',overlap_sec=.3);f.set_shots(self.variant,[a,b]);self.check('crossfade_infeasible')
    def test_double_overlap(self):
        a,b,c=f.shot(0,2),f.shot(2,2.6,'s2',2),f.shot(3,7,'s3',3)
        for s in (a,b):s['timing'].update(transition_out='crossfade',overlap_sec=.4)
        f.set_shots(self.variant,[a,b,c]);self.check('crossfade_infeasible')
    def test_valid_duration_speed_freeze_crossfade(self):
        a,b=f.shot(0,6),f.shot(6,12,'s2',2);a['timing'].update(speed=1.2,freeze_sec=.5,transition_out='crossfade',overlap_sec=.3)
        f.set_shots(self.variant,[a,b]);r=self.check();self.assertEqual(r['calculated_output_durations_sec']['A'],11.2);self.assertNotEqual(r['status'],'BLOCKED')
    def test_duration_not_silently_fixed(self):self.variant['estimated_output_duration_sec']=11;self.check('output_duration_mismatch');self.assertEqual(self.variant['estimated_output_duration_sec'],11)
    def test_shot_order(self):self.shot['order']=2;self.check('shot_order_invalid')
    def test_duplicate_shot_id(self):f.set_shots(self.variant,[f.shot(0,6),f.shot(6,12,'s1',2)]);self.check('duplicate_shot_id')
    def test_repeated_material(self):f.set_shots(self.variant,[f.shot(0,6),f.shot(4,12,'s2',2)]);self.check('repeated_source_material')
    def test_gap_continuity(self):f.set_shots(self.variant,[f.shot(0,4),f.shot(6,12,'s2',2)]);self.check('audio_visual_discontinuity')
    def test_speech_uncertain_cuts(self):
        self.packet=f.packet('present');self.plan=f.plan(self.packet);self.check('speech_boundaries_unverified')
    def test_mixed_content(self):
        self.packet=f.packet('present','present');self.plan=f.plan(self.packet);self.assertEqual(self.check()['status'],'NEEDS_REVIEW');self.check('speech_boundaries_unverified')
    def test_unknown_format(self):
        self.packet=f.packet('uncertain','uncertain',['unfamiliar','spontaneous']);self.plan=f.plan(self.packet);self.assertEqual(self.check()['status'],'NEEDS_REVIEW')
    def test_conversation_truncated(self):
        self.packet['canonical']['events']=[{'event_type':'dialogue_exchange','start_sec':1,'end_sec':6}];self.shot['source_start_sec']=3;self.check('conversation_context_truncation_risk')
    def test_speech_treatment_risk(self):
        self.packet=f.packet('present');self.plan=f.plan(self.packet);self.plan['variants'][0]['shots'][0]['timing']['speed']=1.1;self.check('speech_timing_treatment_risk')
    def test_speech_safe_false(self):self.shot['speech_safe']=True;self.blocked()
    def test_unsupported_factual_claim(self):self.plan['factual_claims']=[{'text':'Showroom has hundreds of cars','kind':'vehicle_or_business_claim','verification_status':'unverified','evidence_refs':['canonical.segments.0']}];self.check('unsupported_factual_claim')
    def test_verified_fact_not_authenticated_by_hash(self):self.plan['factual_claims']=[{'text':'64 pixel width','kind':'source_metadata','verification_status':'verified','evidence_refs':['source.metadata']}];self.check('unsupported_factual_claim')
    def test_creative_copy_needs_review(self):self.variant['operations']=[f.operation()];self.check('caption_meaning_and_factual_review')
    def test_false_inventory_in_copy(self):self.variant['operations']=[f.operation()];self.variant['operations'][0]['parameters']['caption']['text']='Ratusan mobil siap pilih';self.check('unsupported_copy_claim_or_quote')
    def test_unsafe_quote(self):self.variant['operations']=[f.operation()];self.variant['operations'][0]['parameters']['caption'].update(text='Iya wajib',kind='verified_quote',verification_status='verified');self.check('unverified_caption_promoted')
    def test_unverified_subtitle_text_blocked(self):self.variant['operations']=[f.operation('subtitle')];self.check('ineligible_quote_or_claim')
    def test_subtitle_placeholder(self):self.variant['operations']=[f.operation('subtitle')];self.variant['operations'][0]['parameters']['caption'].update(text=None,kind='placeholder');self.assertNotEqual(self.check()['status'],'BLOCKED')
    def test_placeholder_not_quote_escape(self):self.variant['operations']=[f.operation()];self.variant['operations'][0]['parameters']['caption']['kind']='placeholder';self.check('placeholder_contains_text')
    def test_unknown_operation(self):self.variant['operations']=[f.operation('magic')];self.blocked()
    def test_supported_renderer_operation_forged(self):self.variant['operations']=[f.operation()];self.variant['operations'][0]['capability_status']='supported';self.check('unverified_renderer_support')
    def test_invalid_operation_range(self):self.variant['operations']=[f.operation()];self.variant['operations'][0]['output_end_sec']=20;self.check('operation_output_range_invalid')
    def test_unknown_shot_operation(self):self.variant['operations']=[f.operation()];self.variant['operations'][0]['shot_id']='missing';self.check('operation_output_range_invalid')
    def test_invalid_crop(self):o=f.operation('crop');o['parameters']={'x':.8,'y':0,'width':.5,'height':1};self.variant['operations']=[o];self.check('crop_bounds_invalid')
    def test_renderer_requirements(self):self.variant['operations']=[f.operation()];self.assertEqual({r['operation'] for r in self.check()['renderer_requirements']},{'trim','overlay'})
    def test_beat_grid_fabrication(self):self.variant['audio_strategy']['sync_basis']='verified_beat_grid';self.check('fabricated_verified_beat_grid')
    def test_rhythm_missing(self):self.variant['audio_strategy']['sync_basis']='estimated_rhythm';self.check('rhythm_unavailable')
    def test_onset_without_event(self):self.variant['audio_strategy']['sync_basis']='onset_candidate';self.check('onset_sync_without_onset')
    def test_onset_candidate_not_verified_beat(self):self.variant['audio_strategy'].update(sync_basis='onset_candidate',evidence_refs=['audio.events.0']);self.check('audio_sync_is_candidate_not_intentional_music_sync')
    def test_duplicate_variants(self):b=copy.deepcopy(self.variant);b['variant_id']='B';b['title']='Only different name';self.plan['variants'].append(b);self.plan['proposed_variant_count']=2;self.check('redundant_variants')
    def test_meaningful_variants(self):b=copy.deepcopy(self.variant);b['variant_id']='B';f.set_shots(b,[f.shot(2,8)]);self.plan['variants'].append(b);self.plan['proposed_variant_count']=2;r=self.check();self.assertNotEqual(r['status'],'BLOCKED');self.assertIn('hook_source_window',r['variant_differentiation'])
    def test_duplicate_variant_ids(self):self.plan['variants'].append(copy.deepcopy(self.variant));self.plan['proposed_variant_count']=2;self.check('duplicate_variant_id')
    def test_ready_for_render_forged(self):self.plan['render_readiness']='READY_FOR_RENDER';self.blocked()
    def test_render_approval_forged(self):self.plan['render_approved']=True;self.blocked()
    def test_publish_approval_forged(self):self.plan['publish_approved']=True;self.blocked()
    def test_verified_renderer_forged(self):self.plan['renderer_capabilities']['verification_status']='verified';self.blocked()
    def test_missing_field(self):del self.plan['source'];self.blocked()
    def test_unknown_field(self):self.plan['unsafe']='yes';self.blocked()
    def test_inspection_exit_zero_is_not_render_approval(self):r=self.check();self.assertEqual(v.exit_code(r),0);self.assertFalse(r['render_gate_passed'])
    def test_enforcement_nonzero(self):self.assertEqual(v.exit_code(self.check(),True),20)
    def test_invalid_exit(self):del self.plan['source'];self.assertEqual(v.exit_code(self.blocked()),2)
    def test_safety_exit(self):self.plan['source']['sha256']='b'*64;self.assertEqual(v.exit_code(self.blocked()),3)

    def test_variant_ref_renaming_not_creative_difference(self):
        self.variant['operations']=[f.operation()]
        b=copy.deepcopy(self.variant);b['variant_id']='B'
        b['operations'][0]['parameters']['caption']['evidence_refs']=['source.metadata']
        self.plan['variants'].append(b);self.plan['proposed_variant_count']=2
        self.check('redundant_variants')
    def test_source_count_difference_not_fake_treatment_change(self):
        b=copy.deepcopy(self.variant);b['variant_id']='B';f.set_shots(b,[f.shot(0,6),f.shot(6,12,'s2',2)])
        dimensions=v.differentiation(self.variant,b)
        self.assertIn('source_selection_or_order',dimensions);self.assertNotIn('timing_treatment',dimensions)
