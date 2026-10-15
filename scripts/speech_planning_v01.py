#!/usr/bin/env python3
"""Versioned speech-aware Director intake and independent plan/revision validation."""
import argparse
import copy
import json
from pathlib import Path
import sys

import run_adaptive_director_v03 as director
import speech_intelligence_v01 as speech

PACKET = 'evidence-packet.speech.v01.json'
PROMPT = 'director-request.speech.v01.txt'
RECEIPT = 'planning-provenance.speech.v01.json'
POLICY = ('\nGENERALIZED_SPEECH_POLICY: ASR timing is estimated; use only exact source-bound accepted selection reviews. '
    'Model self-report is not semantic proof. Ineligible text is quarantined. Propose alternatives freely, '
    'but trims/reorder/audio treatment/subtitles require operation-specific support. '
    'Speech intelligence does not approve rendering or publication.')


def receipts():
    return director.code_receipts()+speech.refs()+[speech.av.reference(Path(__file__).resolve())]


def context(prepared, report_path, *, enriched=False):
    packet, _, request = director.load_prepared(prepared)
    report = speech.load_report(report_path)
    if report['source'] != packet['source'] or report['classification'] != packet['speech']['requirements']:
        raise speech.base.AdapterError('Director speech/source classification mismatch')
    for name in ('video', 'metadata', 'analysis'):
        if report['inputs'][name] != packet['inputs'][name]:
            raise speech.base.AdapterError('Director speech/canonical reference mismatch')
    if enriched: packet = enrich_packet(packet, report, report_path)
    return packet, report, request


def enrich_packet(packet, report, report_path):
    packet = copy.deepcopy(packet)
    summary = {'report': speech.av.reference(speech.av.checked_path(report_path, 'Speech assessment')),
        'eligibility': report['eligibility'], 'timestamp_precision': report['timestamp_precision'],
        'alignment_confidence': report['alignment_confidence'], 'uncertainties': report['uncertainties'],
        'human_review_basis': 'explicit_local_source_review' if report['human_review'] else 'unavailable',
        'supported_selection_reviews': [], 'reviewed_text': []}
    if report['human_review']:
        summary['supported_selection_reviews'] = [r for r in report['human_review']['selection_reviews'] if r['decision'] == 'supported']
        if report['eligibility']['reviewed_transcript']:
            source_cues={r['segment_id']:r for r in report['human_review'].get('subtitle_source_reviews',[])
                if r['accuracy_confirmed'] and r['max_error_sec']<=speech.MAX_BOUNDARY_ERROR_SEC}
            summary['reviewed_text'] = [{'segment_id':r['segment_id'],'reviewed_text':r['reviewed_text'],
                'accuracy_confirmed':r['accuracy_confirmed'],**({'source_start_sec':source_cues[r['segment_id']]['source_start_sec'],
                'source_end_sec':source_cues[r['segment_id']]['source_end_sec'],
                'max_error_sec':source_cues[r['segment_id']]['max_error_sec'],
                'timing_basis':'explicit_source_audio_waveform_review'} if r['segment_id'] in source_cues else {})}
                for r in report['human_review']['text_reviews']]
            for i, segment in enumerate(report['segments']):
                review_index = next(j for j, r in enumerate(report['human_review']['text_reviews']) if r['segment_id'] == segment['segment_id'])
                cue=source_cues.get(segment['segment_id'])
                pointer=(f"/human_review/subtitle_source_reviews/{report['human_review']['subtitle_source_reviews'].index(cue)}"
                    if cue else f'/human_review/text_reviews/{review_index}')
                packet['evidence_ledger'][f'speech.reviewed_segments.{i}'] = {
                    'artifact': 'speech_intelligence', 'pointer': pointer,
                    'start_sec': cue['source_start_sec'] if cue else segment['start_sec'],
                    'end_sec': cue['source_end_sec'] if cue else segment['end_sec'],
                    'timing_precision': 'approximate',
                    'basis': 'human_source_timing_review_recorded' if cue else 'human_text_review_asr_timing_unverified'}
    packet['speech_intelligence'] = summary
    packet['inputs']['speech_intelligence'] = summary['report']
    director.intake.bounded_json(packet)
    return packet

def prepare(prepared, report_path, output):
    director.shared.directory(output, new=True)
    packet, report, request = context(prepared, report_path, enriched=True)
    prompt = director.make_prompt(packet)+POLICY
    director.safe_text(prompt, director.MAX_PROMPT_BYTES)
    receipt = {'contract_version': '0.1.0', 'mode': 'prepared_no_inference',
        'legacy_prepared': director.shared.relative(director.shared.directory(prepared)),
        'legacy_request': speech.av.reference(director.shared.directory(prepared)/director.REQUEST),
        'speech_report': speech.av.reference(speech.av.checked_path(report_path, 'Speech report')),
        'source': packet['source'], 'evidence_packet_sha256': director.validator.packet_digest(packet),
        'prompt_sha256': director.digest_text(prompt), 'prompt_bytes': len(prompt.encode()),
        'code_receipts': receipts(), 'live_inference_performed': False, **speech.FLAGS}
    return director.publish(output, {PACKET: packet, PROMPT: prompt, RECEIPT: receipt})


def load_prepared(bundle):
    bundle = director.shared.directory(bundle); receipt = speech.read(bundle/RECEIPT)
    if receipt.get('code_receipts') != receipts() or receipt.get('mode') != 'prepared_no_inference':
        raise speech.base.AdapterError('Speech planning producer changed')
    packet, report, _ = context(receipt['legacy_prepared'], receipt['speech_report']['path'], enriched=True)
    prompt = director.safe_text((bundle/PROMPT).read_text(), director.MAX_PROMPT_BYTES)
    if (speech.av.reference(director.shared.directory(receipt['legacy_prepared'])/director.REQUEST) != receipt['legacy_request']
            or speech.av.reference(speech.av.checked_path(receipt['speech_report']['path'], 'Speech assessment')) != receipt['speech_report']
            or speech.read(bundle/PACKET) != packet or director.validator.packet_digest(packet) != receipt['evidence_packet_sha256']
            or director.digest_text(prompt) != receipt['prompt_sha256']
            or prompt != director.make_prompt(packet)+POLICY or len(prompt.encode()) != receipt['prompt_bytes']):
        raise speech.base.AdapterError('Speech planning packet/prompt/input mismatch')
    return packet, report, receipt


def validate_plan(plan, packet, report):
    independent = director.validator.validate_plan(plan, packet)
    semantic = speech.evaluate_plan(plan, packet, report) if independent['structural_validity'] else None
    blocked = not independent['structural_validity'] or bool(independent['blocking_findings']) or bool(semantic and semantic['affected_operations_blocked'])
    return {'contract_version': '0.1.0', 'source': packet['source'], 'plan_sha256': speech.digest(plan),
        'evidence_packet_sha256': director.validator.packet_digest(packet), 'speech_evidence_sha256': speech.digest(report),
        'independent_plan_validation': independent, 'semantic_continuity': semantic,
        'status': 'BLOCKED_UNSAFE_OPERATION' if blocked else 'NEEDS_HUMAN_REVIEW',
        'affected_operations_blocked': blocked, 'render_readiness': 'BLOCKED_FOR_RENDER', **speech.FLAGS}


def validate_revision(proposal, brief, packet, parent, parent_spec, registry, report):
    # Existing revision contract/capabilities/lineage checks remain authoritative.
    import run_revision_loop_v01 as revision
    legacy = revision.validate_proposal(proposal, brief, packet, parent, parent_spec, registry)
    combined = validate_plan(proposal['plan'], packet, report)
    return {'contract_version': '0.1.0', 'legacy_revision_validation': legacy,
        'speech_plan_validation': combined,
        'affected_operations_blocked': bool(legacy['blocking_reasons']) or combined['affected_operations_blocked'],
        'source': packet['source'], 'revision_proposal_sha256': speech.digest(proposal), **speech.FLAGS}


def validate_render(plan, packet, report, spec, registry):
    import benchmark_preview_v01 as preview
    combined = validate_plan(plan, packet, report)
    readiness, _ = preview.validate_plan(plan, packet, registry, spec, speech_report=report)
    return {'contract_version': '0.1.0', 'source': packet['source'], 'speech_plan_validation': combined,
        'execution_validation': readiness, 'affected_operations_blocked': combined['affected_operations_blocked'] or not readiness['private_preview_eligible'],
        'render_readiness': 'BLOCKED_FOR_RENDER', **speech.FLAGS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'audit-plan', 'validate-plan', 'validate-revision'):
        p = sub.add_parser(name); p.add_argument('--prepared', required=True); p.add_argument('--output', required=True)
        if name != 'validate-plan': p.add_argument('--speech-report', required=True)
        if name in ('audit-plan', 'validate-plan'): p.add_argument('--plan', required=True)
        if name == 'validate-revision':
            for arg in ('proposal', 'brief', 'parent-plan', 'parent-spec', 'capabilities'): p.add_argument('--'+arg, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            bundle = prepare(args.prepared, args.speech_report, args.output)
            print(json.dumps({'status': 'PREPARED_NO_INFERENCE', 'bundle': director.shared.relative(bundle), **speech.FLAGS})); return 0
        output = speech.av.checked_path(args.output, 'Speech planning result', output=True)
        if args.command == 'validate-plan': packet, report, _ = load_prepared(args.prepared)
        else: packet, report, _ = context(args.prepared, args.speech_report)
        if args.command == 'validate-revision':
            result = validate_revision(speech.read(args.proposal), speech.read(args.brief), packet,
                speech.read(args.parent_plan), speech.read(args.parent_spec), speech.read(args.capabilities), report)
        else: result = validate_plan(speech.read(args.plan), packet, report)
        speech.shared.write_json(output, result); print(json.dumps({'affected_operations_blocked': result['affected_operations_blocked'], **speech.FLAGS}))
        return 20 if result['affected_operations_blocked'] else 0
    except (speech.base.AdapterError, OSError, ValueError, TypeError, KeyError, RecursionError):
        print('BLOCKED: generalized speech planning integrity/contract failure', file=sys.stderr); return 1


if __name__ == '__main__':
    with director.intake.processing_deadline(): raise SystemExit(main())
