"""Authoritative transition policy; no n8n editorial or retry decisions."""

from backend.roles.common import RoleBlocked, action


def _row(ctx, kind, attempt=None):
    rows = ctx.rows(kind)
    if attempt is not None:
        prefix = f'{ctx.job["id"]}/proposal-{attempt:02d}/'
        rows = [r for r in rows if r['relative_path'].startswith(prefix)]
    if kind == 'speech_draft' and rows:
        rows = [max(rows, key=lambda row: (row['created_at'], str(row['id'])))]
    if len(rows) != 1:
        raise RoleBlocked(f'Expected exactly one {kind} artifact')
    ctx._verified_path(rows[0])
    return rows[0]


def _next(role, phase, attempt, *rows, **extra):
    return {'state': 'SUCCEEDED',
            'next_action': action(role, phase, attempt, rows, **extra)}


def _terminal():
    return {'state': 'SUCCEEDED', 'job_state': 'BLOCKED'}


def _retry_director(ctx, attempt, findings):
    if attempt >= 3:
        return _select(ctx)
    diagnosis = ctx.write_json(
        f'controller/{ctx.task["id"]}-diagnosis.json', {'findings': findings},
        'revision_diagnosis')
    return _next('director', 'propose', attempt + 1,
                 _row(ctx, 'automatic_request'), _row(ctx, 'director_packet'), diagnosis)


def _retry_asr(ctx, regions):
    if not regions:
        return _terminal()
    counts = {}
    for row in ctx.store.reservation_rows(ctx.job['id']):
        if row['kind'] == 'speech_asr':
            counts[row['region_key']] = counts.get(row['region_key'], 0) + 1
    if any(counts.get(region, 0) >= 2 for region in regions):
        return _terminal()
    retry = ctx.write_json(f'controller/{ctx.task["id"]}-asr-regions.json',
                           {'regions': sorted(regions)}, 'asr_retry_regions')
    return _next('speech-asr', 'transcribe', 0, _row(ctx, 'director_packet'), retry,
                 regions=sorted(regions))


def _select(ctx):
    import run_automatic_editing_v01 as workflow

    candidates = []
    for row in ctx.rows('candidate'):
        candidate = workflow.read(ctx._verified_path(row))
        if not candidate['blocking_findings']:
            try:
                workflow.verify_candidate(candidate, ctx.directory)
            except (workflow.core.Error, OSError, ValueError, KeyError, TypeError):
                continue
            candidates.append(candidate)
    best = workflow.select_candidate(candidates)
    if best is None:
        return _terminal()
    request = workflow.read(ctx.directory / 'request.json')
    reserved = sum(r['kind'] == 'director' for r in ctx.store.reservation_rows(ctx.job['id']))
    result = workflow.complete_candidate(ctx.directory, best, reserved, request)
    ctx.artifact(ctx.directory / 'completed.json', 'completion_receipt')
    return {'state': 'SUCCEEDED', 'job_state': result['status']}


def execute(ctx):
    import run_automatic_editing_v01 as workflow

    ctx.source()
    ctx.begin()
    tasks = [r for r in ctx.store.task_rows(ctx.job['id'])
             if r['role'] != 'revision-controller' and r['id'] != ctx.task['id']]
    if not tasks:
        raise RoleBlocked('No preceding role for Controller')
    previous = tasks[-1]
    role, phase, attempt = previous['role'], previous['phase'], previous['attempt']
    if previous['state'] not in ('SUCCEEDED', 'BLOCKED', 'FAILED'):
        raise RoleBlocked('Previous role outcome is not definitive')

    if previous['state'] != 'SUCCEEDED':
        if role == 'speech-asr':
            draft = workflow.read(ctx._verified_path(_row(ctx, 'speech_draft')))
            return _retry_asr(ctx, draft['blocked_regions'])
        if role == 'reviewer' and phase == 'source_speech':
            rows = ctx.rows('source_review_outcome')
            if not rows:
                return _terminal()
            outcome = workflow.read(ctx._verified_path(max(
                rows, key=lambda row: (row['created_at'], str(row['id'])))))
            return _retry_asr(ctx, outcome['affected_regions'])
        if role == 'validator':
            report = workflow.read(ctx._verified_path(_row(ctx, 'plan_validation', attempt)))
            return _retry_director(ctx, attempt, report['blocking_findings'])
        if role in ('director', 'renderer', 'technical-qa') or (role == 'reviewer' and phase == 'edited_output'):
            return _retry_director(ctx, attempt, [{'code': previous['failure_class'] or 'ROLE_BLOCKED'}])
        return _terminal()

    if role == 'analyst':
        return _next('av-evidence', 'measure', 0,
                     _row(ctx, 'source_metadata'), _row(ctx, 'canonical_analysis'))
    if role == 'av-evidence':
        return _next('speech-asr', 'transcribe', 0, _row(ctx, 'director_packet'))
    if role == 'speech-asr':
        if any(r['task_id'] == previous['id'] for r in ctx.rows('speech_evidence')):
            return _next('director', 'propose', 1,
                         _row(ctx, 'automatic_request'), _row(ctx, 'director_packet'))
        return _next('reviewer', 'source_speech', 0,
                     _row(ctx, 'director_packet'), _row(ctx, 'speech_draft'))
    if role == 'reviewer' and phase == 'source_speech':
        return _next('director', 'propose', 1,
                     _row(ctx, 'automatic_request'), _row(ctx, 'director_packet'))
    if role == 'director':
        return _next('validator', 'validate', attempt,
                     _row(ctx, 'director_packet'), _row(ctx, 'speech_evidence'),
                     _row(ctx, 'director_proposal', attempt))
    if role == 'validator':
        return _next('renderer', 'encode', attempt,
                     _row(ctx, 'automatic_request'), _row(ctx, 'director_proposal', attempt),
                     _row(ctx, 'plan_validation', attempt), _row(ctx, 'visual_plan', attempt),
                     _row(ctx, 'execution_spec', attempt))
    if role == 'renderer':
        return _next('technical-qa', 'inspect', attempt,
                     _row(ctx, 'render_output', attempt),
                     _row(ctx, 'render_encode_receipt', attempt))
    if role == 'technical-qa':
        return _next('reviewer', 'edited_output', attempt,
                     _row(ctx, 'render_manifest', attempt),
                     _row(ctx, 'plan_validation', attempt),
                     _row(ctx, 'technical_qa', attempt))
    if role == 'reviewer' and phase == 'edited_output':
        candidate = workflow.read(ctx._verified_path(_row(ctx, 'candidate', attempt)))
        if candidate['advisory_findings'] and attempt < 3:
            return _retry_director(ctx, attempt, candidate['advisory_findings'])
        return _select(ctx)
    raise RoleBlocked('Controller has no transition for role')
