"""Stage 5.8 measured deltas and explicit visual/audio provenance; no inference."""
import copy
from functools import lru_cache
from fractions import Fraction
import math

import revision_intelligence_v01 as ri

core, qa = ri.core, ri.qa
ROOT = core.base.ROOT / 'data/benchmarks/stage58'
RENDER_ROOT = core.base.ROOT / 'data/render-tests/stage58'
VERSION = '0.1.0'
FLAGS = dict(production_eligible=False, publishing_eligible=False, render_approved=False, publish_approved=False)
SCHEMA = 'benchmark-workflow.v0.1.schema.json'


@lru_cache(maxsize=2)
def _schema(digest):
    return core.base.load_schema(SCHEMA)


def check(kind, value):
    schema = _schema(core.intake.gate.sha256_file(core.base.ROOT/'src/schemas'/SCHEMA))
    core.base.validate_object(value, {'$defs': schema['$defs'], '$ref': '#/$defs/'+kind}, 'Benchmark '+kind)
    core.director.safe_text(__import__('json').dumps(value, allow_nan=False), 2097152)
    return value


def receipts():
    return ri.code_receipts()+[qa.ref(core.base.ROOT/p) for p in (
        'scripts/benchmark_evidence_v01.py', 'scripts/run_benchmark_v01.py',
        'scripts/director_diagnostics_v01.py',
        'scripts/speech_intelligence_v01.py', 'scripts/speech_planning_v01.py',
        'src/schemas/speech-intelligence.v0.1.schema.json',
        'scripts/benchmark_preview_v01.py', 'src/schemas/'+SCHEMA)]


def window(a, b):
    return {'start_sec': round(a, 6), 'end_sec': round(b, 6)}


def validate_window(value, duration):
    if not isinstance(value, dict) or set(value) != {'start_sec', 'end_sec'}:
        raise core.Error('Invalid benchmark range')
    a, b = value['start_sec'], value['end_sec']
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (a, b)) or not 0 <= a < b <= duration:
        raise core.Error('Benchmark range outside output')
    return a, b


def gaps(a, b, components):
    intervals = sorted((c['output_range']['start_sec'], c['output_range']['end_sec']) for c in components)
    missing = []; cursor = a
    for start, end in intervals:
        if start > cursor+1e-6: missing.append(window(cursor, start))
        cursor = max(cursor, end)
    if cursor < b-1e-6: missing.append(window(cursor, b))
    return missing


def component(uid, kind, source, out, original, speed, treatment):
    return {'component_id': uid, 'kind': kind, 'source': source, 'output_range': out,
            'source_range': original, 'speed': speed, 'treatment': treatment,
            'timing_basis': 'declared_execution_mapping', 'acoustic_fact_verified': False}


def map_ranges(value, timeline, source, spec, *, source_has_audio=None):
    """Map each contributing component; overlapping sources never collapse to one."""
    duration = timeline['expected_duration_sec']
    if value is None:
        return check('mapping', {'output_range': None, 'visual_components': [], 'audio_components': [],
            'visual_status': 'UNAVAILABLE', 'audio_status': 'UNAVAILABLE', 'unmapped_visual': [],
            'unmapped_audio': [], 'limitations': ['Issue has no temporal range; no source timing invented']})
    a, b = validate_window(value, duration)
    visual = []; shot_audio = []
    visual_spec = spec.get('visual_spec', spec)
    output = visual_spec.get('output', {})
    sound = spec.get('audio_timeline')
    if sound and sound['source'] != source:raise core.Error('Audio source identity differs from verified source')
    operations = timeline.get('operations', [])
    treatments = [copy.deepcopy(op) for op in operations if op.get('effective_kind') in
        ('audio_gain', 'audio_duck', 'audio_fade', 'normalization', 'denoise')]
    for shot in timeline['shots']:
        start = max(a, shot['output_start_sec']); end = min(b, shot['output_end_sec'])
        if start >= end: continue
        moving_end = shot.get('freeze_output_start_sec', shot['output_end_sec'])
        if start < min(end, moving_end):
            stop = min(end, moving_end)
            src = window(shot['source_start_sec']+(start-shot['output_start_sec'])*shot['speed'],
                min(shot['source_end_sec'], shot['source_start_sec']+(stop-shot['output_start_sec'])*shot['speed']))
            c = component(shot['shot_id'], 'source_passage', source, window(start, stop), src, shot['speed'],
                {'transition': shot['transition_out'], 'overlap_sec': shot['overlap_sec']})
            visual.append(c)
            shot_audio.append({**copy.deepcopy(c), 'treatment': {'operations': treatments,
                'transition': shot['transition_out'], 'overlap_sec': shot['overlap_sec']}})
        if end > max(start, moving_end):
            out = window(max(start, moving_end), end)
            visual.append(component(shot['shot_id']+':freeze', 'held_frame', source, out,
                window(shot['source_end_sec'], shot['source_end_sec']), 0, {'freeze': True}))
            if output.get('freeze_audio') == 'silence':
                shot_audio.append(component(shot['shot_id']+':freeze-silence', 'planned_silence', None, out, None, 0, {}))
    audio = []
    if sound and sound['mode'] == 'continuous_source':
        if sound['source'] != source: raise core.Error('Audio source identity differs from verified source')
        passage = sound['source_range']
        if not passage or abs(passage['end_sec']-passage['start_sec']-duration)>1e-6:
            raise core.Error('Independent audio passage length mismatch')
        audio.append(component('continuous-source-bed', 'continuous_audio_bed', source, window(a, b),
            window(passage['start_sec']+a, passage['start_sec']+b), 1,
            {k: sound[k] for k in ('gain_db', 'fade_in_sec', 'fade_out_sec', 'mix_original', 'original_gain_db')}))
        if sound['mix_original']:
            for c in shot_audio: c['treatment']['original_gain_db'] = sound['original_gain_db']
            audio += shot_audio
    elif output.get('audio_mode') == 'silent':
        audio = [component('declared-silent-output', 'planned_silence', None, window(a, b), None, 0, {})]
    elif output.get('audio_mode') == 'preserve':
        audio = shot_audio
    for op in operations:
        if op.get('effective_kind') not in ('music_bed', 'sound_effect'): continue
        if sound and sound['mode'] == 'continuous_source' and not sound['mix_original']:
            raise core.Error('Replacement bed cannot hide mixed assets')
        start = max(a, op['output_start_sec']); end = min(b, op['output_end_sec'])
        if start >= end: continue
        record = visual_spec.get('assets', {}).get(op['parameters']['asset_reference'])
        if not record: raise core.Error('Mixed audio asset provenance missing')
        ref = {k: record[k] for k in ('path', 'sha256')}
        audio.append(component(op['operation_id'], 'mixed_asset', ref, window(start, end),
            window(start-op['output_start_sec'], end-op['output_start_sec']), 1, {'operation': copy.deepcopy(op)}))
    if source_has_audio is not True:
        audio=[c for c in audio if c['kind'] in ('planned_silence','mixed_asset')]
    vg, ag = gaps(a, b, visual), gaps(a, b, audio)
    return check('mapping', {'output_range': value, 'visual_components': visual, 'audio_components': audio,
        'visual_status': 'COMPLETE' if not vg else 'PARTIAL' if visual else 'UNAVAILABLE',
        'audio_status': 'SILENT' if audio and all(c['kind']=='planned_silence' for c in audio) else
            'COMPLETE' if not ag else 'PARTIAL' if audio else 'UNAVAILABLE',
        'unmapped_visual': vg, 'unmapped_audio': ag,
        'limitations': ['Execution mappings are declarations checked against manifests, not transcript/phrase verification',
            'Mixed/overlapping components stay separate; nonlinear processing does not establish waveform equivalence']})


def quality_v02(report_ref, report, timeline, spec):
    qa.same_reference(report_ref); qa.validate_report(report)
    if qa.read(report_ref['path'])!=report:raise core.Error('QA body differs from referenced historical report')
    source = report['source']; findings = []
    for old in report['issues']:
        stream=report['technical'].get('verification',{}).get('metadata',{}).get('audio_present')
        mapping = map_ranges(old['output_range'], timeline, source, spec,source_has_audio=stream)
        modality = 'audio' if old['category'] in ('audio', 'speech', 'ending') else 'visual' if old['category'] in ('visual', 'hook', 'pacing') else 'context'
        # An ending may have both visual and acoustic context; never substitute
        # a visual component for an audio component regardless of category.
        findings.append({'issue_id': old['issue_id'], 'category': old['category'], 'origin': old['origin'],
            'modality_hint': modality, 'legacy_issue_sha256': core.digest_object(old), 'mapping': mapping})
    return check('quality', {'contract_version': '0.2.0', 'legacy_report': report_ref, 'source': source,
        'rendered_output': report['rendered_output'], 'issue_mappings': findings,
        'method_version':'source-components-0.1.0','validation_scope':'STRUCTURE_AND_REFERENCE_BOUND_MAPPING_REPLAY',
        'derivation_refs':{k:report['inputs'][k] for k in ('manifest','spec','timeline') if k in report['inputs']},
        'code_receipts':receipts(),
        'overall_decision': report['overall_decision'], 'human_review_pending': True,
        'consumer_contract': 'Use mapping.audio_components for audio; legacy source_ranges remain historical visual mapping', **FLAGS})


def validate_quality(value, report, timeline, spec):
    check('quality', value)
    if value != quality_v02(value['legacy_report'], report, timeline, spec):
        raise core.Error('QA audio/visual source mapping differs from independent replay')
    return value


def frame_records(path):
    info = core.media_info(path)
    if info['duration_sec'] > 180 or info['fps'] > 60: raise core.Error('Benchmark frame comparison resource limit')
    raw, elapsed = core.run(['ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe',
        '-i', str(core.safe_path(path)), '-map', '0:v:0', '-an', '-f', 'framemd5', 'pipe:1'],
        {**core.DEFAULT_RESOURCES, 'memory_mib': 3072, 'timeout_sec': 180}, max_bytes=2097152)
    decoded=raw.decode('ascii').splitlines()
    try:
        timebase=Fraction(next(line.split(':',1)[1].strip() for line in decoded if line.startswith('#tb 0:')))
        if timebase<=0:raise ValueError('nonpositive timebase')
    except (StopIteration,ValueError,ZeroDivisionError):raise core.Error('Decoded frame timebase unavailable') from None
    lines = [line.split(',') for line in decoded if line and not line.startswith('#')]
    if not lines or any(len(row)!=6 for row in lines): raise core.Error('Invalid decoded frame comparison')
    try:
        records = [tuple(str(Fraction(x.strip())*timebase) for x in row[1:4])+
            tuple(x.strip() for x in row[4:]) for row in lines]
    except (ValueError,ZeroDivisionError):raise core.Error('Invalid decoded frame timestamp') from None
    return {'reference': qa.ref(path), 'records': records, 'elapsed_sec': elapsed, 'metadata': info}


def compare_media(parent, current, old_report, new_report, old_timeline, new_timeline, human=None, audio_verification=None):
    if old_report['source'] != new_report['source']: raise core.Error('Cross-source comparison rejected')
    if parent['reference'] != old_report['rendered_output'] or current['reference'] != new_report['rendered_output']:
        raise core.Error('Comparison bytes not bound to reports')
    identical = parent['records'] == current['records']
    same_pixels = [r[-1] for r in parent['records']] == [r[-1] for r in current['records']]
    completed = human is not None
    if human: validate_human(human, current['reference'], parent['reference'])
    audio_changed = old_timeline.get('audio_timeline') != new_timeline.get('audio_timeline')
    selections=lambda t:[(s['source_start_sec'],s['source_end_sec']) for s in t.get('shots',[])]
    timing=lambda t:[(s['output_start_sec'],s['output_end_sec'],s['speed'],s['freeze_sec']) for s in t.get('shots',[])]
    audio_ops=lambda t:[op for op in t.get('operations',[]) if op.get('effective_kind') in
        ('audio_gain','audio_duck','audio_fade','normalization','denoise','music_bed','sound_effect')]
    return check('comparison', {'contract_version': VERSION, 'source': old_report['source'],
        'parent': parent['reference'], 'current': current['reference'], 'identical_visual_frames_and_timing': identical,
        'same_ordered_visual_pixels': same_pixels, 'visual_delta': 'IDENTICAL' if identical else 'TIMING_CHANGED' if same_pixels else 'PIXELS_CHANGED',
        'visual_improvement': 'NOT_ESTABLISHED_IDENTICAL' if identical else 'HUMAN_REPORTED' if human and human['improvements']['visual']=='yes' else 'UNVERIFIED',
        'audio_mapping_changed': audio_changed, 'audio_quality_improvement': 'HUMAN_REPORTED' if human and human['improvements']['audio']=='yes' else 'UNVERIFIED_REQUIRES_LISTENING',
        'declared_shot_selection_changed':selections(old_timeline)!=selections(new_timeline),
        'declared_visual_timing_changed':timing(old_timeline)!=timing(new_timeline),
        'audio_processing_changed':audio_ops(old_timeline)!=audio_ops(new_timeline) or
            {k:new_timeline.get('audio_timeline',{}).get(k) for k in ('gain_db','fade_in_sec','fade_out_sec')} !=
            {k:old_timeline.get('audio_timeline',{}).get(k) for k in ('gain_db','fade_in_sec','fade_out_sec')},
        'technical_audio_mapping_result':audio_verification['status'] if audio_verification else 'UNAVAILABLE',
        'overall_improvement': 'HUMAN_REPORTED' if human and human['better_than_baseline']=='yes' else 'NOT_ESTABLISHED',
        'absolute_quality_dimensions': new_report['dimensions'], 'human_review':human,
        'disagreements': [{'dimension': k, 'parent': old_report['dimensions'][k], 'current': v} for k, v in new_report['dimensions'].items() if v != old_report['dimensions'][k]],
        'human_review_pending': not completed, 'method': 'Full decoded frame hash/PTS/duration equality; model scores are absolute judgments, not measured improvements', **FLAGS})


def scorecard(output, baseline=None):
    return check('human', {'contract_version': VERSION, 'output': output, 'baseline': baseline,
        'performed': False, 'reviewer': None, 'reviewed_at': None,
        'ratings': {k: None for k in ('hook', 'clarity', 'cuts', 'audio', 'visual', 'overall')},
        'improvements': {k: None for k in ('visual', 'audio', 'overall')},
        'better_than_baseline': None, 'suitable_for_public_posting': None, 'comments': [], **FLAGS})


def validate_human(value, output, baseline=None):
    check('human', value)
    if value['output'] != output or value['baseline'] != baseline or not value['performed']:
        raise core.Error('Human review missing or belongs to different bytes')
    if not value['reviewer'] or not value['reviewed_at'] or any(v is None for v in value['ratings'].values()):
        raise core.Error('Human scorecard incomplete')
    qa.same_reference(output)
    if baseline: qa.same_reference(baseline)
    if value['improvements']['overall'] is not None and value['better_than_baseline']!=value['improvements']['overall']:
        raise core.Error('Human overall comparative judgments conflict')
    if any(c['range'] is not None for c in value['comments']):
        duration=core.media_info(core.safe_path(output['path']))['duration_sec']
        for comment in value['comments']:
            if comment['range'] is not None:validate_window(comment['range'],duration)
    return value
