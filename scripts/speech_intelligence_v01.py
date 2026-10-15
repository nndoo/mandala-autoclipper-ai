#!/usr/bin/env python3
"""Offline generalized speech assessment and operation-scoped semantic checks."""
import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path
import sys

import adaptive_director_evidence_v03 as intake

base, av, shared, gate = intake.base, intake.av, intake.shared, intake.gate
SCHEMA = 'speech-intelligence.v0.1.schema.json'
STATUSES = ('SAFE_SUPPORTED_OPERATION', 'NEEDS_HUMAN_REVIEW', 'INSUFFICIENT_EVIDENCE',
            'BLOCKED_UNSAFE_OPERATION', 'NOT_APPLICABLE')
FLAGS = {'render_approved': False, 'publish_approved': False}
MAX_BYTES = 524288
MAX_ITEMS = 4096
MAX_BOUNDARY_ERROR_SEC = .05
LIMITATIONS = [
    'Canonical speech/music classifications are model interpretations, not independent acoustic detection',
    'ASR segment/word timestamps remain estimates; structural checks do not prove acoustic alignment',
    'Local generation receipts establish consistency, not independent server/model authentication',
    'Accepted human reviews are explicit local attestations, not cryptographic identity authentication',
    'Semantic correctness cannot be established by punctuation, confidence scores or model self-report',
    'Operation safety is scoped to exact source selections, never render/publish approval',
]


def digest(value):
    return __import__('hashlib').sha256(intake.bounded_json(value, MAX_BYTES).encode()).hexdigest()


@lru_cache(maxsize=32)
def compiled(kind, schema_sha256):
    from jsonschema import Draft202012Validator
    schema = base.load_schema(SCHEMA)
    selected = {'$schema': schema['$schema'], '$ref': '#/$defs/'+kind, '$defs': schema['$defs']}
    Draft202012Validator.check_schema(selected)
    return Draft202012Validator(selected)


def check(kind, value):
    from jsonschema import ValidationError
    from run_adaptive_director_v03 import safe_text
    safe_text(intake.bounded_json(value, MAX_BYTES), MAX_BYTES)
    try: compiled(kind, gate.sha256_file(base.ROOT/'src/schemas'/SCHEMA)).validate(value)
    except ValidationError: raise base.AdapterError('Invalid speech intelligence contract') from None
    return value


def read(path):
    from renderer_core_v01 import safe_path
    path = safe_path(path, 'Speech intelligence input')
    if path.stat().st_size > MAX_BYTES: raise base.AdapterError('Speech intelligence byte limit')
    from run_adaptive_director_v03 import safe_text
    safe_text(path.read_text(), MAX_BYTES)
    return av.read(path)


def refs():
    return [av.reference(Path(__file__).resolve()), av.reference(base.ROOT/'src/schemas'/SCHEMA)]


def finite(value):
    try: return type(value) in (int, float) and math.isfinite(value)
    except OverflowError: return False


def range_ok(start, end, duration):
    return finite(start) and finite(end) and 0 <= start < end <= duration


def reviewed_edges(review, windows, duration):
    measured = list(review['boundary_reviews']) + [
        {'time_sec': r[k], 'max_error_sec': r['max_error_sec'], 'accuracy_confirmed': r['accuracy_confirmed']}
        for r in review.get('subtitle_source_reviews', []) for k in ('source_start_sec', 'source_end_sec')]
    return all(edge in (0, duration) or any(abs(r['time_sec']-edge) <= 1e-6 and
        r['max_error_sec'] <= MAX_BOUNDARY_ERROR_SEC and r['accuracy_confirmed']
        for r in measured) for window in windows for edge in window)


def normalize(draft, duration):
    """Keep text/words unchanged. Upload context never becomes an utterance range."""
    segments, words, untimed, issues = [], [], [], []
    rows = draft.get('segments', [])
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        return [], [], [], ['malformed_or_excessive_segments']
    for i, row in enumerate(rows):
        if not isinstance(row, dict): issues.append('malformed_segment'); continue
        sid = row.get('segment_id', f'segment-{i+1:04d}')
        start, end, text = row.get('start_sec'), row.get('end_sec'), row.get('text')
        if not isinstance(sid, str) or not sid or not isinstance(text, str) or not text.strip() or not range_ok(start, end, duration):
            issues.append('invalid_transcript_segment_or_timing'); continue
        confidence = {k: row.get(k) for k in ('avg_logprob', 'no_speech_prob', 'compression_ratio')}
        if any(v is not None and not finite(v) for v in confidence.values()):
            issues.append('invalid_reported_confidence'); continue
        speaker = row.get('speaker', row.get('speaker_id'))
        language = row.get('language')
        segments.append({'segment_id': sid, 'start_sec': start, 'end_sec': end, 'text': text,
            'language': language if isinstance(language, str) else None,
            'reported_speaker': str(speaker) if type(speaker) in (str, int) else None,
            'reported_confidence': confidence})
        if i and segments and len(segments) > 1 and start < segments[-2]['start_sec']:
            issues.append('nonmonotonic_transcript_segments')
    if len({s['segment_id'] for s in segments}) != len(segments): issues.append('duplicate_segment_id')
    provider_words = draft.get('provider_words', [])
    if not isinstance(provider_words, list): issues.append('malformed_words'); provider_words = []
    word_rows = [(None, w) for w in provider_words] if provider_words else [
        (row.get('segment_id', f'segment-{i+1:04d}'), w)
        for i, row in enumerate(rows) if isinstance(row, dict) and isinstance(row.get('words', []), list)
        for w in row.get('words', [])]
    if len(word_rows) > MAX_ITEMS: issues.append('excessive_words'); word_rows = []
    for sid, word in word_rows:
        if not isinstance(word, dict): issues.append('malformed_word'); continue
        start, end = word.get('start_sec'), word.get('end_sec'); text = word.get('word'); probability = word.get('probability')
        if (not range_ok(start, end, duration) or not isinstance(text, str) or not text.strip()
                or probability is not None and (not finite(probability) or not 0 <= probability <= 1)):
            issues.append('invalid_word_timing_or_confidence'); continue
        parent = next((s for s in segments if s['segment_id'] == sid), None) if sid else None
        if sid and (not parent or not parent['start_sec'] <= start < end <= parent['end_sec']):
            issues.append('word_outside_segment'); continue
        association = 'reported_parent' if sid else 'unavailable'
        if sid is None:
            candidates = [s for s in segments if s['start_sec'] <= start < end <= s['end_sec']]
            if len(candidates) == 1: sid = candidates[0]['segment_id']; association = 'unique_timestamp_containment'
        words.append({'word_id': f'word-{len(words)+1:04d}', 'segment_id': sid,
            'start_sec': start, 'end_sec': end, 'word': text, 'reported_probability': probability,
            'segment_association_basis': association})
    if any(w['start_sec'] < words[i-1]['start_sec'] for i, w in enumerate(words) if i):
        issues.append('nonmonotonic_words')
    recognized = draft.get('recognized_regions', [])
    if not isinstance(recognized, list) or len(recognized) > MAX_ITEMS: issues.append('malformed_untimed_text'); recognized = []
    for row in recognized:
        if not isinstance(row, dict) or not isinstance(row.get('text'), str): issues.append('malformed_untimed_text'); continue
        if row['text'].strip(): untimed.append({'region_id': row.get('region_id', ''), 'text': row['text']})
    if any(isinstance(r, dict) and not isinstance(r.get('words', []), list) for r in rows): issues.append('malformed_segment_words')
    if any(s['reported_confidence']['no_speech_prob'] is not None and not 0 <= s['reported_confidence']['no_speech_prob'] <= 1 for s in segments):
        issues.append('invalid_reported_confidence')
    return segments, words, untimed, sorted(set(issues))


def review_data(submission, report, approved_by):
    check('review_submission', submission)
    if submission['review_method'] == 'user_supplied_review_notes' and any(
            submission.get(k) for k in ('boundary_reviews', 'word_reviews', 'subtitle_reviews', 'subtitle_source_reviews', 'selection_reviews', 'context_links')):
        raise base.AdapterError('Qualitative text notes cannot certify timing or semantic selections')
    if (submission['origin'] != 'human_source_review' or submission['reviewer_identity'] != approved_by
            or not approved_by.strip() or submission['source_sha256'] != report['source']['sha256']
            or submission['evidence_sha256'] != digest(report)):
        raise base.AdapterError('Human review/source/evidence binding mismatch')
    duration = report['source']['duration_sec']; ids = {s['segment_id']: s for s in report['segments']}
    for row in submission['text_reviews']:
        if row['segment_id'] not in ids or row['original_text_sha256'] != digest(ids[row['segment_id']]['text']):
            raise base.AdapterError('Human text review mismatch')
    if len({r['segment_id'] for r in submission['text_reviews']}) != len(submission['text_reviews']):
        raise base.AdapterError('Duplicate text review')
    for row in submission['boundary_reviews']:
        if not finite(row['time_sec']) or not 0 <= row['time_sec'] <= duration:
            raise base.AdapterError('Human boundary outside source')
    for row in submission['word_reviews']:
        word = next((w for w in report['words'] if w['word_id'] == row['word_id']), None)
        if word is None or row['word_sha256'] != digest(word): raise base.AdapterError('Word review mismatch')
    if len({r['word_id'] for r in submission['word_reviews']}) != len(submission['word_reviews']):
        raise base.AdapterError('Duplicate word review')
    if len({r['time_sec'] for r in submission['boundary_reviews']}) != len(submission['boundary_reviews']):
        raise base.AdapterError('Conflicting duplicate boundary reviews')
    if len({digest(r['source_windows']) for r in submission['selection_reviews']}) != len(submission['selection_reviews']):
        raise base.AdapterError('Conflicting duplicate selection reviews')
    for selection in submission['selection_reviews']:
        if any(not range_ok(a, b, duration) for a, b in selection['source_windows']):
            raise base.AdapterError('Review selection outside source')
    for link in submission['context_links']:
        if any(sid not in ids for sid in link['segment_ids']): raise base.AdapterError('Unknown semantic context segment')
    for row in submission.get('subtitle_reviews', []):
        if not range_ok(row['source_start_sec'], row['source_end_sec'], duration):
            raise base.AdapterError('Subtitle review outside source')
    subtitle_ids = [(r['variant_id'],r['operation_id']) for r in submission.get('subtitle_reviews', [])]
    if len(set(subtitle_ids)) != len(subtitle_ids): raise base.AdapterError('Duplicate subtitle review')
    source_cues=submission.get('subtitle_source_reviews',[])
    if len({r['segment_id'] for r in source_cues})!=len(source_cues):
        raise base.AdapterError('Duplicate source subtitle review')
    reviewed_text={r['segment_id']:r for r in submission['text_reviews']}
    for row in source_cues:
        text=reviewed_text.get(row['segment_id'])
        if (row['segment_id'] not in ids or not text or not text['accuracy_confirmed']
                or ' '.join(text['reviewed_text'].split())!=' '.join(row['text'].split())
                or not range_ok(row['source_start_sec'],row['source_end_sec'],duration)):
            raise base.AdapterError('Source subtitle text/timing binding mismatch')
    return submission


def accepted_review(path, expected):
    receipt = check('review_receipt', read(path))
    for name in ('report', 'submission'):
        ref = receipt[name]; p = av.checked_path(ref['path'], 'Review reference')
        if av.reference(p) != ref: raise base.AdapterError('Human review reference changed')
    raw_original = check('report', read(receipt['report']['path']))
    if raw_original['request'].get('human_review') or raw_original['source'] != expected['source']:
        raise base.AdapterError('Review must bind unrevised speech assessment')
    original = load_report(receipt['report']['path'])
    comparable = copy.deepcopy(expected); comparable['request']['human_review'] = None
    if original != comparable or receipt['code_receipts'] != refs(): raise base.AdapterError('Human review assessment/code mismatch')
    return review_data(read(receipt['submission']['path']), original, receipt['accepted_by'])


def assess(video, metadata, analysis, *, speech_bundle=None, human_review=None):
    paths, source, sha, canonical, _ = shared.verified_inputs(video, metadata, analysis)
    binding = {**source, 'path': shared.relative(paths['video']), 'sha256': sha}
    requirement = gate.speech_requirements(canonical)
    inputs = {k: av.reference(p) for k, p in paths.items()}
    generation, pcm, draft = 'unavailable', None, {}
    legacy_eligibility = None; generation_quality_flags = []
    if speech_bundle:
        speech_bundle = shared.directory(speech_bundle)
        manifest, old = intake.validate_speech_bundle(speech_bundle)
        if manifest['source'] != source or manifest['speech_requirements'] != requirement:
            raise base.AdapterError('Speech bundle cross-source/requirements mismatch')
        generation = 'client_recorded' if old['generation_status'] == 'complete' else 'unavailable'
        pcm = manifest['audio']['source_pcm']; legacy_eligibility = old['evidence_eligibility']
        generation_quality_flags = copy.deepcopy((old.get('quality_assessment') or {}).get('flags', []))
        for name in (shared.MANIFEST, shared.REPORT, shared.GATE, shared.DRAFT):
            p = speech_bundle/name
            if p.is_file(): inputs['speech:'+name] = av.reference(av.checked_path(p, 'Speech artifact'))
        if (speech_bundle/shared.DRAFT).is_file(): draft = av.read(speech_bundle/shared.DRAFT)
        if draft and draft.get('provenance', {}).get('source_sha256') != sha:
            raise base.AdapterError('Draft source association mismatch')
    segments, words, untimed, issues = normalize(draft, source['duration_sec'])
    overlap = any(a['end_sec'] > b['start_sec'] for a, b in zip(segments, segments[1:]))
    speakers = sorted({s['reported_speaker'] for s in segments if s['reported_speaker'] is not None})
    uncertainties = []
    if overlap: uncertainties.append('overlapping_segments_not_independently_verified')
    if any(a['end_sec'] > b['start_sec'] for a,b in zip(words,words[1:])):
        uncertainties.append('overlapping_word_timing_not_independently_verified')
    if len(speakers) > 1: uncertainties.append('multiple_reported_speakers')
    if segments and any(s['reported_speaker'] is None for s in segments): uncertainties.append('speaker_identity_unavailable')
    if any(w['reported_probability'] is not None and w['reported_probability'] < .5 for w in words): uncertainties.append('low_provider_word_probability')
    if segments and not words: uncertainties.append('word_alignment_unavailable')
    if untimed and not segments: uncertainties.append('text_without_utterance_timestamps')
    uncertainties += ['generation_quality:'+r['code'] for r in generation_quality_flags if isinstance(r,dict) and isinstance(r.get('code'),str)]
    request = {k: shared.relative(v) for k, v in paths.items()}
    request.update(speech_bundle=shared.relative(speech_bundle) if speech_bundle else None,
        human_review=shared.relative(av.checked_path(human_review, 'Human review')) if human_review else None)
    report = {'contract_version': '0.1.0', 'source': binding, 'request': request, 'inputs': inputs,
        'method': 'source_bound_speech_assessment_v01', 'code_receipts': refs(),
        'classification': requirement, 'classification_basis': 'canonical_model_unverified',
        'audio_content': {'reported_music_presence':canonical['content_profile']['music_presence'],
            'reported_speech_presence':canonical['content_profile']['speech_presence'],
            'regions':[{'segment_id':r['segment_id'],'start_sec':r['start_sec'],'end_sec':r['end_sec'],
                'reported_audio_layers':r['audio_layers']} for r in canonical['segments']]},
        'generation_provenance': generation, 'pcm': pcm, 'pcm_parameters': gate.PCM_PARAMETERS,
        'segments': segments, 'words': words, 'untimed_text': untimed,
        'structure_status': 'failed' if issues else 'checked', 'structure_issues': issues,
        'transcription_confidence': 'provider_reported_or_unavailable',
        'alignment_confidence': 'unverified' if segments or words else 'unavailable',
        'timestamp_precision': 'asr_estimate' if segments or words else 'unavailable',
        'uncertainties': uncertainties, 'human_review': None, 'legacy_eligibility': legacy_eligibility,
        'eligibility': {'status': 'NOT_APPLICABLE' if requirement['overall_requirement'] == 'not_required' else 'INSUFFICIENT_EVIDENCE',
            'transcript_for_review': bool(segments or untimed) and not issues and generation == 'client_recorded',
            'reviewed_transcript': False, 'segment_alignment': False, 'word_alignment': False,
            'semantic_cuts': False}, 'limitations': LIMITATIONS, **FLAGS}
    if human_review:
        review = accepted_review(human_review, report)
        report['inputs']['human_review'] = av.reference(av.checked_path(human_review, 'Accepted review'))
        report['human_review'] = review
        text_ids = {r['segment_id'] for r in review['text_reviews'] if r['accuracy_confirmed']}
        word_ids = {r['word_id'] for r in review['word_reviews'] if r['accuracy_confirmed'] and r['max_error_sec'] <= MAX_BOUNDARY_ERROR_SEC}
        adequate = not issues and generation == 'client_recorded'
        text_eligible = adequate and bool(segments) and text_ids == {s['segment_id'] for s in segments}
        complete_words = all(any(w['segment_id'] == segment['segment_id'] for w in words) and any(
            r['segment_id'] == segment['segment_id'] and r.get('word_coverage_confirmed') is True
            for r in review['text_reviews']) for segment in segments)
        report['eligibility'].update(reviewed_transcript=text_eligible,
            segment_alignment=text_eligible and reviewed_edges(review, [[r['start_sec'],r['end_sec']] for r in segments], source['duration_sec']),
            word_alignment=text_eligible and complete_words and bool(words) and word_ids == {w['word_id'] for w in words},
            semantic_cuts=text_eligible and any(reviewed_edges(review,r['source_windows'],source['duration_sec']) and
                r['decision'] == 'supported' and all(r[k] for k in ('sentence_complete','qa_context_preserved',
                'meaning_preserved','multi_speaker_reviewed','music_overlap_reviewed')) for r in review['selection_reviews']))
        if adequate: report['eligibility']['status'] = 'NEEDS_HUMAN_REVIEW'
        source_cues=review.get('subtitle_source_reviews',[])
        if (text_eligible and {r['segment_id'] for r in source_cues}=={r['segment_id'] for r in segments}
                and all(r['accuracy_confirmed'] and r['max_error_sec']<=MAX_BOUNDARY_ERROR_SEC for r in source_cues)):
            # Human corrected source spans are a separate layer; raw ASR times remain estimates.
            report['eligibility']['segment_alignment']=True
    check('report', report)
    if inputs['video']['sha256'] != sha: raise base.AdapterError('Source changed during speech assessment')
    from run_adaptive_director_v03 import recheck_inputs
    recheck_inputs(report)
    return report


def load_report(path):
    report = check('report', read(path))
    expected = assess(**report['request'])
    if report != expected: raise base.AdapterError('Speech intelligence differs from source-bound replay')
    return report


def evaluate_plan(plan, packet, report=None):
    """Deterministic risk checks, not an automatic natural-language meaning judge."""
    findings = []; duration = packet['source']['duration_sec']
    requirement = packet['speech']['requirements']
    if report:
        check('report', report)
        if report['source'] != packet['source'] or report['classification'] != requirement:
            raise base.AdapterError('Speech plan evidence/source mismatch')
    def add(code, location, status, blocking=True):
        findings.append({'code': code, 'location': location, 'status': status, 'blocking': blocking})
    if not plan.get('variants'): add('missing_variants', 'plan', 'BLOCKED_UNSAFE_OPERATION')
    review = report.get('human_review') if report else None
    for variant in plan.get('variants', []):
        vid = variant['variant_id']; shots = variant['shots']
        windows = [[s['source_start_sec'], s['source_end_sec']] for s in shots]
        if any(not range_ok(a, b, duration) for a, b in windows):
            add('invalid_source_timing', vid, 'BLOCKED_UNSAFE_OPERATION'); continue
        conflict = (bool(requirement['classification_conflicts']) or requirement['overall_requirement'] == 'needs_review'
            or requirement['overall_requirement'] == 'required' and not any(r['requirement']=='required' for r in requirement['regions']))
        speech_shots = [s for s in shots if conflict or any(r['requirement'] != 'not_required' and
            max(s['source_start_sec'], r['start_sec']) < min(s['source_end_sec'], r['end_sec']) for r in requirement['regions'])]
        whole = windows and windows[0][0] == 0 and windows[-1][1] == duration and all(
            windows[i-1][1] == windows[i][0] for i in range(1, len(windows))) and all(
            s['timing']['speed'] == 1 and s['timing']['freeze_sec'] == 0 and s['timing']['overlap_sec'] == 0 for s in shots)
        audio_ops = [o for o in variant['operations'] if o['kind'] in ('audio_gain', 'audio_duck', 'denoise', 'music_bed', 'sound_effect', 'custom')]
        temporal_treatment = any(s['timing']['speed'] != 1 or s['timing']['freeze_sec'] != 0 or s['timing']['overlap_sec'] != 0 for s in speech_shots)
        selection = next((r for r in review['selection_reviews'] if r['source_windows'] == windows), None) if review else None
        if not speech_shots:
            add('no_speech_required_by_canonical_regions', vid, 'NOT_APPLICABLE', False)
        elif whole and not audio_ops:
            add('complete_source_context_preserved', vid, 'SAFE_SUPPORTED_OPERATION', False)
        else:
            supported = bool(report and report['eligibility']['reviewed_transcript'] and selection)
            if selection and selection['decision'] == 'unsafe':
                add('human_review_rejects_exact_selection', vid, 'BLOCKED_UNSAFE_OPERATION'); supported = False
            elif supported:
                supported = reviewed_edges(review, windows, duration)
                if not all(selection[k] for k in ('sentence_complete', 'qa_context_preserved', 'meaning_preserved',
                    'multi_speaker_reviewed', 'music_overlap_reviewed')): supported = False
            supported = supported and not temporal_treatment
            if supported and not audio_ops and not conflict:
                add('exact_selection_supported_by_source_review', vid, 'SAFE_SUPPORTED_OPERATION', False)
            elif not selection or selection['decision'] != 'unsafe':
                status = 'NEEDS_HUMAN_REVIEW' if report and report['segments'] and not report['structure_issues'] else 'INSUFFICIENT_EVIDENCE'
                add('speech_selection_without_independent_boundary_and_context_support', vid, status)
            if len(windows) > 1 and any(windows[i][0] != windows[i-1][1] for i in range(1, len(windows))):
                add('noncontiguous_or_reordered_dialogue', vid, 'SAFE_SUPPORTED_OPERATION' if supported and not conflict and not audio_ops else 'INSUFFICIENT_EVIDENCE', not (supported and not conflict and not audio_ops))
            if audio_ops: add('speech_audio_treatment_not_independently_supported', vid, 'NEEDS_HUMAN_REVIEW')
            if temporal_treatment: add('speech_timing_treatment_not_independently_supported', vid, 'NEEDS_HUMAN_REVIEW')
            if report:
                for a, b in windows:
                    if any(s['start_sec'] < edge < s['end_sec'] for s in report['segments'] for edge in (a, b)) and not supported:
                        add('possible_interrupted_utterance_at_cut', vid, 'NEEDS_HUMAN_REVIEW')
        if conflict:
            preserved = whole and not audio_ops
            add('classification_conflict_or_uncertain_speech', vid,
                'NEEDS_HUMAN_REVIEW' if preserved else 'INSUFFICIENT_EVIDENCE', not preserved)
        if review:
            spans = {r['segment_id']: r for r in review.get('subtitle_source_reviews', [])
                if r['accuracy_confirmed'] and r['max_error_sec'] <= MAX_BOUNDARY_ERROR_SEC}
            selected_ids = set()
            for segment in report['segments']:
                span = spans.get(segment['segment_id'])
                start, end = (span['source_start_sec'], span['source_end_sec']) if span else (segment['start_sec'], segment['end_sec'])
                if any(a <= start and end <= b for a, b in windows): selected_ids.add(segment['segment_id'])
            for link in review['context_links']:
                wanted = set(link['segment_ids'])
                if selected_ids & wanted and not wanted <= selected_ids:
                    add('missing_question_answer_or_required_context', vid, 'BLOCKED_UNSAFE_OPERATION')
        for operation in variant['operations']:
            caption = operation['parameters'].get('caption')
            supported_subtitle = False
            if operation['kind'] == 'subtitle' and caption:
                if caption['text'] is None: add('subtitle_placeholder_requires_review', vid+'/'+operation['operation_id'], 'NEEDS_HUMAN_REVIEW', False)
                else:
                    approved = next((r for r in review.get('subtitle_reviews', []) if r['variant_id'] == vid and
                        r['operation_id'] == operation['operation_id']), None) if review else None
                    clock = 0; source_window = None
                    for shot in shots:
                        timing = shot['timing']; span = (shot['source_end_sec']-shot['source_start_sec'])/timing['speed']+timing['freeze_sec']
                        if shot['shot_id'] == operation['shot_id'] and timing['speed'] == 1 and not timing['freeze_sec'] and not timing['overlap_sec']:
                            source_window = [shot['source_start_sec']+operation['output_start_sec']-clock,
                                             shot['source_start_sec']+operation['output_end_sec']-clock]
                        clock += span-timing['overlap_sec']
                    reviewed_text = []
                    if source_window and report:
                        ids = {r['segment_id'] for r in report['segments'] if source_window[0] <= r['start_sec'] and r['end_sec'] <= source_window[1]}
                        reviewed_text = [r['reviewed_text'] for r in review['text_reviews'] if r['segment_id'] in ids and r['accuracy_confirmed']] if review else []
                    supported_subtitle = bool(approved and report['eligibility']['reviewed_transcript'] and source_window ==
                        [approved['source_start_sec'],approved['source_end_sec']] and ' '.join(approved['text'].split()) == ' '.join(caption['text'].split()) and
                        approved['accuracy_confirmed'] and approved['max_error_sec'] <= MAX_BOUNDARY_ERROR_SEC and
                        ' '.join(' '.join(reviewed_text).split()) == ' '.join(caption['text'].split()))
                    if not supported_subtitle and source_window and review and report['eligibility']['reviewed_transcript']:
                        # Source-reviewed words/times can be reused under a mechanically checked,
                        # unchanged-rate mapping. This never authenticates arbitrary edited captions.
                        supported_subtitle=any(r['accuracy_confirmed'] and r['max_error_sec']<=MAX_BOUNDARY_ERROR_SEC
                            and max(abs(a-b) for a,b in zip(source_window,[r['source_start_sec'],r['source_end_sec']]))<=1e-6
                            and ' '.join(r['text'].split())==' '.join(caption['text'].split())
                            for r in review.get('subtitle_source_reviews',[]))
                    add('source_reviewed_subtitle_mapping' if supported_subtitle else 'subtitle_text_requires_exact_reviewed_source_mapping',
                        vid+'/'+operation['operation_id'], 'SAFE_SUPPORTED_OPERATION' if supported_subtitle else 'BLOCKED_UNSAFE_OPERATION', not supported_subtitle)
            if caption and caption.get('verification_status') == 'verified' and not supported_subtitle:
                add('unsupported_caption_verification_claim', vid, 'BLOCKED_UNSAFE_OPERATION')
    for claim in plan.get('factual_claims', []):
        if claim.get('verification_status') == 'verified' or claim.get('kind') != 'source_metadata':
            add('transcript_does_not_authenticate_factual_claim', 'factual_claims', 'BLOCKED_UNSAFE_OPERATION')
    blocking = [f for f in findings if f['blocking']]
    priority = ('BLOCKED_UNSAFE_OPERATION', 'INSUFFICIENT_EVIDENCE', 'NEEDS_HUMAN_REVIEW', 'SAFE_SUPPORTED_OPERATION', 'NOT_APPLICABLE')
    status = next((s for s in priority if any(f['status'] == s for f in blocking or findings)), 'INSUFFICIENT_EVIDENCE')
    return check('plan_report', {'contract_version': '0.1.0', 'source': packet['source'],
        'plan_sha256': digest(plan), 'speech_evidence_sha256': digest(report) if report else None,
        'status': status, 'affected_operations_blocked': bool(blocking), 'findings': findings,
        'limitations': LIMITATIONS, **FLAGS})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    assess_parser = sub.add_parser('assess')
    for name in ('video', 'metadata', 'analysis', 'output'): assess_parser.add_argument('--'+name, required=True)
    for name in ('speech-bundle', 'human-review'): assess_parser.add_argument('--'+name)
    accept = sub.add_parser('accept-review')
    for name in ('report', 'submission', 'approved-by', 'output'): accept.add_argument('--'+name, required=True)
    args = parser.parse_args(argv)
    try:
        output = av.checked_path(args.output, 'Speech intelligence output', output=True)
        if args.command == 'assess':
            result = assess(args.video, args.metadata, args.analysis, speech_bundle=args.speech_bundle, human_review=args.human_review)
        else:
            report = load_report(args.report)
            if report['request']['human_review']: raise base.AdapterError('Review must bind original assessment')
            review_data(read(args.submission), report, args.approved_by)
            result = check('review_receipt', {'contract_version': '0.1.0', 'origin': 'explicit_human_acceptance',
                'accepted_by': args.approved_by, 'accepted_at': shared.now(),
                'report': av.reference(av.checked_path(args.report, 'Reviewed report')),
                'submission': av.reference(av.checked_path(args.submission, 'Review submission')), 'code_receipts': refs(), **FLAGS})
        shared.write_json(output, result); print(json.dumps({'status': result.get('eligibility', {}).get('status', 'REVIEW_RECORDED'), **FLAGS})); return 0
    except (base.AdapterError, OSError, ValueError, TypeError, KeyError, RecursionError):
        print('BLOCKED: speech source, contract, review or output integrity failure', file=sys.stderr); return 1


if __name__ == '__main__':
    with intake.processing_deadline(): raise SystemExit(main())
