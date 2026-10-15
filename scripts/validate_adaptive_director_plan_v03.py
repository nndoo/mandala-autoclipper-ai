#!/usr/bin/env python3
"""Independent Stage 5.4 plan inspection; never grants render/publish approval."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import adaptive_director_evidence_v03 as intake

base, shared, av = intake.base, intake.shared, intake.av
SCHEMA = 'adaptive-editing-plan.v0.3.schema.json'
REPORT_VERSION = '0.3.0'
# Detection is deliberately conservative and incomplete, not semantic authentication.
CLAIM_PATTERN = re.compile(r'\b(?:Rp\s*\d|IDR\s*\d|\d+\s*(?:unit|mobil|km|cc|hp|tahun|years|cars)|ratusan|hundreds|terbaik|best(?:[- ]in[- ]class)?|terawat|flawless|garansi|warranty|dijamin|guaranteed|bebas\s+(?:banjir|tabrakan)|milik\s+pertama|first\s+owner|harga\s+\d|lokasi\s+di)\b', re.I)
QUOTE_PATTERN = re.compile(r'["“”]|\b(?:kata\s+(?:pak|beliau)|says?|said|menjawab|kutipan)\b', re.I)
LIMITATIONS = [
    'Semantic checks and keyword screening cannot prove meaning, artistic quality or exhaustively detect false claims',
    'Canonical descriptions and speech/music regions remain unverified model interpretations',
    'No independently verified speech boundaries, beat grid or renderer capability receipt exists in this stage',
    'All proposals require human audiovisual review; validation never approves execution or publishing',
]


def packet_digest(packet):
    return hashlib.sha256(intake.bounded_json(packet).encode()).hexdigest()


def event_for(packet, ref):
    for events in (packet['audio']['selected_events'], packet['visual']['selected_events'], packet['correlation']):
        for event in events:
            if event['ref'] == ref:
                return event
    return None


def variant_signature(variant):
    """Ignore names and justifications; compare source selection and actual operations."""
    def creative_parameters(operation):
        params=copy.deepcopy(operation['parameters'])
        if 'caption' in params:
            params['caption'].pop('evidence_refs',None)
        return params
    cta=copy.deepcopy(variant['ending']['cta'])
    if cta: cta.pop('evidence_refs',None)
    return {'hook': [variant['hook']['source_start_sec'], variant['hook']['source_end_sec']],
            'shots': [[s['source_start_sec'], s['source_end_sec'], s['timing']] for s in variant['shots']],
            'operations': [[o['kind'], creative_parameters(o), o['output_start_sec'], o['output_end_sec']] for o in variant['operations']],
            'audio_sync': variant['audio_strategy']['sync_basis'], 'cta': cta}


def differentiation(a, b):
    sa, sb = variant_signature(a), variant_signature(b)
    dimensions = []
    if max(abs(x-y) for x,y in zip(sa['hook'], sb['hook'])) >= .5:
        dimensions.append('hook_source_window')
    if len(sa['shots']) != len(sb['shots']) or any(max(abs(x[0]-y[0]), abs(x[1]-y[1])) >= .5 for x,y in zip(sa['shots'], sb['shots'])):
        dimensions.append('source_selection_or_order')
    if abs(a['estimated_output_duration_sec']-b['estimated_output_duration_sec']) >= 1:
        dimensions.append('estimated_duration')
    treatments_a={json.dumps(s[2],sort_keys=True) for s in sa['shots']}
    treatments_b={json.dumps(s[2],sort_keys=True) for s in sb['shots']}
    if treatments_a != treatments_b:
        dimensions.append('timing_treatment')
    if sa['operations'] != sb['operations'] or sa['cta'] != sb['cta']:
        dimensions.append('overlay_effect_or_ending')
    if sa['audio_sync'] != sb['audio_sync']:
        dimensions.append('audio_sync')
    return dimensions


def validate_plan(plan, packet):
    """Pure independent checks against a replay-verified packet. CLI replays intake first."""
    blockers, reviews, capabilities, calculated = [], [], set(), {}
    def issue(code, location='', severity='blocking'):
        item = {'code': code, 'location': location}
        target = blockers if severity == 'blocking' else reviews
        if item not in target:
            target.append(item)
    schema = base.load_schema(SCHEMA)
    try:
        intake.bounded_json(plan, 131072)
        base.validate_object(plan, schema, 'Adaptive editing plan')
    except (base.AdapterError, ValueError, TypeError, RecursionError):
        return report('BLOCKED', False, [{'code':'schema_invalid','location':'plan'}], [], [], {}, [])
    if plan['source'] != packet['source']:
        issue('source_identity_mismatch', 'source')
    if plan['evidence_packet_sha256'] != packet_digest(packet):
        issue('evidence_packet_hash_mismatch', 'evidence_packet_sha256')
    if plan['proposed_variant_count'] != len(plan['variants']) or len(plan['variants']) > packet['editorial_policy']['max_variants']:
        issue('variant_count_mismatch', 'variants')
    if not packet['editorial_policy']['allow_fewer_variants'] and len(plan['variants']) != packet['editorial_policy']['max_variants']:
        issue('policy_variant_count', 'variants')
    if not set(packet['missing_evidence']).issubset(plan['missing_evidence']):
        issue('missing_evidence_omitted', 'missing_evidence')
    import speech_intelligence_v01 as intelligence
    semantic = None
    try:
        attached = packet.get('speech_intelligence'); speech_report = None
        if attached:
            ref = attached['report']; path = av.checked_path(ref['path'], 'Speech intelligence reference')
            if av.reference(path) != ref or packet['inputs'].get('speech_intelligence') != ref:
                raise base.AdapterError('Speech intelligence reference mismatch')
            speech_report = intelligence.load_report(path)
        semantic = intelligence.evaluate_plan(plan, packet, speech_report)
    except (base.AdapterError,OSError,ValueError,TypeError,KeyError,RecursionError):
        issue('speech_intelligence:invalid_or_unreplayable_evidence','speech')
    reviewed_subtitles = {f['location'] for f in semantic['findings'] if f['code']=='source_reviewed_subtitle_mapping' and
        f['status']=='SAFE_SUPPORTED_OPERATION'} if semantic else set()
    if len({v['variant_id'] for v in plan['variants']}) != len(plan['variants']):
        issue('duplicate_variant_id', 'variants')
    ledger, duration = packet['evidence_ledger'], packet['source']['duration_sec']
    def refs_check(refs, location, start=None, end=None, precision=None):
        entries = []
        for ref in refs:
            entry = ledger.get(ref)
            if not entry:
                issue('unknown_evidence_reference', location)
                continue
            entries.append(entry)
        if precision in ('frame_verified','manual_verified','asr_estimate'):
            issue('unsupported_timing_precision', location)
        if precision == 'signal_estimated' and not any(e['basis']=='signal_candidate' for e in entries):
            issue('signal_precision_without_signal_evidence', location)
        if start is not None and end is not None:
            # Whole-source metadata is not an editorial hook or shot grounding.
            timed = [e for e in entries if e['basis']!='source_metadata_verified' and e['start_sec'] is not None and e['end_sec'] is not None]
            if not any(max(start,e['start_sec']) < min(end,e['end_sec']) or start <= e['start_sec'] <= end for e in timed):
                issue('source_range_without_relevant_evidence', location)
        return entries
    def caption_check(caption, location, subtitle=False):
        if caption is None:
            return
        refs_check(caption['evidence_refs'], location)
        if (caption['verification_status'] == 'verified' or caption['kind']=='verified_quote') and not (subtitle and location in reviewed_subtitles):
            issue('unverified_caption_promoted', location)
        if caption['kind']=='placeholder':
            if caption['text'] is not None:
                issue('placeholder_contains_text', location)
        elif subtitle or caption['kind'] in ('asr_draft','canonical_unverified','external_claim'):
            if caption['text'] is not None and location not in reviewed_subtitles:
                issue('ineligible_quote_or_claim', location)
        if caption['text'] and (CLAIM_PATTERN.search(caption['text']) or QUOTE_PATTERN.search(caption['text'])):
            issue('unsupported_copy_claim_or_quote', location)
        issue('caption_meaning_and_factual_review', location, 'review')
    for index, claim in enumerate(plan['factual_claims']):
        loc = f'factual_claims/{index}'
        refs_check(claim['evidence_refs'], loc)
        # No authenticated linguistic or business fact receipt. Metadata facts may
        # remain explicitly unverified proposal text, never publish-approved.
        if claim['verification_status']=='verified' or claim['kind']!='source_metadata':
            issue('unsupported_factual_claim', loc)
        issue('factual_claim_human_review', loc, 'review')
    regions = packet['speech']['requirements']['regions']
    speech_uncertain = packet['speech']['requirements']['overall_requirement'] != 'not_required'
    if packet['speech']['requirements']['classification_conflicts']:
        issue('conflicting_speech_classifications', 'speech', 'review')
    for v in plan['variants']:
        vid = v['variant_id']
        shots = v['shots']
        if len({s['shot_id'] for s in shots}) != len(shots):
            issue('duplicate_shot_id', vid)
        hook = v['hook']
        first = shots[0]
        if (hook['shot_id'] != first['shot_id'] or hook['source_start_sec'] != first['source_start_sec']
                or hook['source_end_sec'] != first['source_end_sec'] or hook['timing_precision'] != first['timing_precision']):
            issue('hook_first_shot_mismatch', vid)
        refs_check(hook['evidence_refs'], vid+'/hook', hook['source_start_sec'], hook['source_end_sec'], hook['timing_precision'])
        durations, offsets, clock = [], {}, 0.0
        for i, s in enumerate(shots):
            loc = vid+'/'+s['shot_id']
            start, end, timing = s['source_start_sec'], s['source_end_sec'], s['timing']
            if not all(math.isfinite(n) for n in (start,end,*[timing[k] for k in ('speed','freeze_sec','overlap_sec')])):
                issue('nonfinite_timing',loc)
            if not 0 <= start < end <= duration:
                issue('invalid_source_range',loc)
            if s['order'] != i+1:
                issue('shot_order_invalid',loc)
            refs_check(s['evidence_refs'],loc,start,end,s['timing_precision'])
            d = (end-start)/timing['speed'] + timing['freeze_sec']
            durations.append(d)
            offsets[s['shot_id']] = (clock, clock+d)
            clock += d-timing['overlap_sec']
            capabilities.add('trim')
            if len(shots)>1: capabilities.add('concat')
            if timing['speed']!=1: capabilities.add('speed')
            if timing['freeze_sec']: capabilities.add('freeze')
            if timing['transition_out']=='crossfade': capabilities.add('crossfade')
            if timing['transition_out']=='cut' and timing['overlap_sec']!=0:
                issue('cut_overlap_nonzero',loc)
            if timing['transition_out']=='crossfade' and timing['overlap_sec']<=0:
                issue('crossfade_overlap_missing',loc)
            if i==len(shots)-1 and (timing['transition_out']!='cut' or timing['overlap_sec']!=0):
                issue('final_transition_invalid',loc)
            issue('candidate_boundary_audiovisual_review',loc,'review')
            intersecting = [r for r in regions if r['requirement']!='not_required' and max(start,r['start_sec'])<min(end,r['end_sec'])]
            if intersecting or speech_uncertain:
                issue('speech_boundaries_unverified',loc,'review')
                if timing['speed']!=1 or timing['freeze_sec'] or timing['overlap_sec']:
                    issue('speech_timing_treatment_risk',loc,'review')
            for event in packet['canonical']['events']:
                if event['event_type'] in ('dialogue_exchange','closing_statement') and max(start,event['start_sec'])<min(end,event['end_sec']):
                    if start>event['start_sec'] or end<event['end_sec']:
                        issue('conversation_context_truncation_risk',loc,'review')
            for previous in shots[:i]:
                if max(start,previous['source_start_sec'])<min(end,previous['source_end_sec']):
                    issue('repeated_source_material',loc,'review')
            if i:
                previous = shots[i-1]
                if abs(start-previous['source_end_sec'])>1e-6:
                    issue('audio_visual_discontinuity',loc,'review')
                if speech_uncertain and start<previous['source_end_sec']:
                    issue('dialogue_reorder_or_repetition',loc,'review')
        for i,s in enumerate(shots):
            incoming = shots[i-1]['timing']['overlap_sec'] if i else 0
            outgoing = s['timing']['overlap_sec']
            if incoming+outgoing >= durations[i] or (i+1<len(shots) and outgoing>=durations[i+1]):
                issue('crossfade_infeasible',vid+'/'+s['shot_id'])
        total = round(sum(durations)-sum(s['timing']['overlap_sec'] for s in shots),2)
        calculated[vid] = total
        if abs(total-v['estimated_output_duration_sec'])>1e-6 or total<=0:
            issue('output_duration_mismatch',vid)
        if len({o['operation_id'] for o in v['operations']})!=len(v['operations']):
            issue('duplicate_operation_id',vid)
        for o in v['operations']:
            loc = vid+'/'+o['operation_id']
            refs_check(o['evidence_refs'],loc)
            capabilities.add(o['kind'])
            if o['capability_status']=='supported':
                issue('unverified_renderer_support',loc)
            window = offsets.get(o['shot_id'])
            if not window or not (0<=o['output_start_sec']<o['output_end_sec']<=max(0,total)+.005
                    and window[0]-.005<=o['output_start_sec'] and o['output_end_sec']<=window[1]+.005):
                issue('operation_output_range_invalid',loc)
            p=o['parameters']
            if o['kind'] in ('overlay','subtitle'):
                caption_check(p['caption'],loc,o['kind']=='subtitle')
            if o['kind']=='crop' and (p['x']+p['width']>1 or p['y']+p['height']>1):
                issue('crop_bounds_invalid',loc)
            if o['kind'] in ('music_bed','sound_effect'):
                issue('external_asset_provenance_and_rights_missing',loc,'review')
            if o['kind']=='custom':
                issue('custom_operation_requires_specification_review',loc,'review')
        audio = v['audio_strategy']
        refs_check(audio['evidence_refs'],vid+'/audio')
        if audio['sync_basis']=='verified_beat_grid':
            issue('fabricated_verified_beat_grid',vid+'/audio')
        if audio['sync_basis']=='estimated_rhythm' and packet['audio']['rhythm']['status']!='estimated':
            issue('rhythm_unavailable',vid+'/audio')
        if audio['sync_basis']=='onset_candidate' and not any((event_for(packet,r) or {}).get('kind')=='onset_candidate' for r in audio['evidence_refs']):
            issue('onset_sync_without_onset',vid+'/audio')
        if audio['sync_basis']!='none':
            issue('audio_sync_is_candidate_not_intentional_music_sync',vid+'/audio','review')
        caption_check(v['ending']['cta'],vid+'/ending')
    import adaptive_text_v01 as text_policy
    for variant in plan['variants']:
        for finding in text_policy.plan_findings(variant,packet):
            issue('adaptive_text:'+finding['code'],finding['location'])
    dimensions = differentiation(*plan['variants']) if len(plan['variants'])==2 else []
    if len(plan['variants'])==2 and not dimensions:
        issue('redundant_variants','variants')
    # Existing structure/factual/capability checks remain independent of the new speech contract.
    if semantic:
        for finding in semantic['findings']:
            if finding['status'] in ('SAFE_SUPPORTED_OPERATION','NOT_APPLICABLE'): continue
            issue('speech_intelligence:'+finding['code'], finding['location'], 'blocking' if finding['blocking'] else 'review')
    status = 'BLOCKED' if blockers else ('NEEDS_REVIEW' if reviews else 'VALID_FOR_EDITORIAL_REVIEW')
    return report(status,True,blockers,reviews,sorted(capabilities),calculated,dimensions)


def report(status,structural,blockers,reviews,capabilities,calculated,dimensions):
    result = {'contract_version':REPORT_VERSION,'inspection_completed':True,'structural_validity':structural,
            'status':status,'blocking_findings':blockers,'review_findings':reviews,
            'calculated_output_durations_sec':calculated,'variant_differentiation':dimensions,
            'renderer_requirements':[{'operation':op,'represented_in_plan':True,'verification_status':'unknown',
                                      'execution_status':'requires_implementation'} for op in capabilities],
            'render_readiness':'BLOCKED_FOR_RENDER','render_gate_passed':False,'publish_ready':False,
            'render_approved':False,'publish_approved':False,'limitations':LIMITATIONS}
    base.validate_object(result,base.load_schema('adaptive-plan-validation.v0.3.schema.json'),'Independent validation report')
    return result


def exit_code(result,enforce_render_ready=False):
    if enforce_render_ready: return 20
    if not result['structural_validity']: return 2
    if result['status']=='BLOCKED': return 3
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--packet',required=True);p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    p.add_argument('--enforce-render-ready',action='store_true')
    args=p.parse_args(argv)
    try:
        output=av.checked_path(args.output,'Report output',output=True)
        packet=intake.validate_packet(av.read(av.checked_path(args.packet,'Evidence packet')))
        plan=av.read(av.checked_path(args.plan,'Editing plan'))
        result=validate_plan(plan,packet)
        result.update(source=packet['source'],evidence_packet_sha256=packet_digest(packet))
        shared.write_json(output,result)
        print(json.dumps({'status':result['status'],'render_readiness':result['render_readiness'],'render_gate_passed':False}))
        return exit_code(result,args.enforce_render_ready)
    except (base.AdapterError,OSError,ValueError,TypeError,KeyError,RecursionError):
        print('BLOCKED: evidence intake or output failure; untrusted diagnostics suppressed',file=sys.stderr)
        return 1

if __name__=='__main__':
    with intake.processing_deadline():
        raise SystemExit(main())
