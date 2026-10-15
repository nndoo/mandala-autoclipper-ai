"""Two Stage 5 Reviewer phases; only the source phase can admit ASR."""

from backend.roles.common import RoleBlocked
from backend.roles.speech_asr import finalize_request


def _invoke(ctx, kind, region, attempt):
    def call(request, path, *, approved=False):
        if not approved:
            raise RoleBlocked('Reviewer approval missing')
        return ctx.paid(kind, request, lambda: ctx.provider.reviewer(request, path),
                        region=region, attempt=attempt)
    return call


def source_speech(ctx):
    import automatic_editing_validation_v01 as validator
    import run_automatic_editing_v01 as workflow

    video, _ = ctx.source()
    packet = ctx.json_input('director_packet')
    draft = ctx.json_input('speech_draft')
    if draft['status'] != 'AWAITING_SOURCE_REVIEW' or draft['blocked_regions']:
        raise RoleBlocked('ASR timing not ready for source review')
    rounds = max(draft['attempt_counts'].values(), default=0)
    if not 1 <= rounds <= 2:
        raise RoleBlocked('Source review has no admitted ASR round')
    previous = [r for r in ctx.store.reservation_rows(ctx.job['id'])
                if r['kind'] == 'reviewer_source' and r['region_key'] == 'source-speech']
    if len(previous) + 1 != rounds:
        raise RoleBlocked('Source Reviewer must follow the ASR round')
    dest = ctx.directory / f'speech-review-{rounds:02d}'
    try:
        response = workflow.model_review(video, dest, draft, speech=True,
            invoke=_invoke(ctx, 'reviewer_source', 'source-speech', rounds))
    except Exception:
        if dest.exists():
            ctx.register_tree(dest, 'source_reviewer_receipt')
        if any(r['state'] == 'OUTCOME_UNKNOWN' for r in ctx.store.reservation_rows(ctx.job['id'])
               if r['task_id'] == ctx.task['id']):
            raise
        raise RoleBlocked('Source Reviewer response blocked') from None
    ctx.register_tree(dest, 'source_reviewer_receipt')
    findings = validator.review_findings(response)
    affected = set()
    for issue in response['issues']:
        if issue.get('code') != 'subtitle_uncertain':
            continue
        for index, region in enumerate(packet['speech']['requirements']['regions']):
            if region['requirement'] != 'not_required' and max(
                    region['start_sec'], issue['start_sec']) < min(region['end_sec'], issue['end_sec']):
                affected.add(f'region-{index:02d}')
    if findings['blocking_findings']:
        ctx.write_json(f'speech-review-{rounds:02d}/outcome.json', {
            'status': 'BLOCKED', 'affected_regions': sorted(affected),
            'blocking_findings': findings['blocking_findings'],
            'human_verified': False}, 'source_review_outcome')
        return {'state': 'BLOCKED', 'failure_class': 'SOURCE_SPEECH_BLOCKED'}
    speech = {**draft, 'status': 'AUTO_PREVIEW_ELIGIBLE',
              'model_assessment': workflow.reference(dest / 'response.json')}
    speech.pop('blocked_regions', None)
    workflow.verify_speech(packet, speech)
    ctx.write_json('speech.json', speech, 'speech_evidence')
    finalize_request(ctx, packet, speech)
    return {'state': 'SUCCEEDED'}


def edited_output(ctx):
    import automatic_editing_validation_v01 as validator
    import run_automatic_editing_v01 as workflow

    ctx.source()
    attempt = ctx.task['attempt']
    root = ctx.directory / f'proposal-{attempt:02d}'
    manifest = ctx.json_input('render_manifest')
    report = ctx.json_input('plan_validation')
    qa = ctx.json_input('technical_qa')
    if qa['status'] != 'PASS' or manifest['output']['sha256'] != qa['output_sha256']:
        raise RoleBlocked('Independent Technical QA has not passed')
    video = workflow.verify_output_reference(manifest['output'], ctx.directory)
    packet = workflow.read(ctx.directory / 'packet.json')
    speech = workflow.read(ctx.directory / 'speech.json')
    graph = workflow.read(root / 'render/timeline.json')
    dest = root / 'review'
    context = {'source': packet['source'], 'proposal': workflow.read(root / 'proposal.json'),
               'technical': manifest['technical'], 'speech': speech,
               'timing': graph['shots'], 'text': graph['automatic_text_cues']}
    try:
        response = workflow.model_review(video, dest, context,
            invoke=_invoke(ctx, 'reviewer_edited', '', 1))
    except Exception:
        if dest.exists():
            ctx.register_tree(dest, 'edited_reviewer_receipt')
        if any(r['state'] == 'OUTCOME_UNKNOWN' for r in ctx.store.reservation_rows(ctx.job['id'])
               if r['task_id'] == ctx.task['id']):
            raise
        raise RoleBlocked('Edited output Reviewer response blocked') from None
    ctx.register_tree(dest, 'edited_reviewer_receipt')
    candidate = workflow.candidate_for(root, report, manifest, response)
    ctx.write_json(f'proposal-{attempt:02d}/candidate.json', candidate, 'candidate')
    findings = validator.review_findings(response)
    return {'state': 'BLOCKED' if findings['blocking_findings'] else 'SUCCEEDED',
            'failure_class': 'EDITED_REVIEW_BLOCKED' if findings['blocking_findings'] else None}


def execute(ctx):
    if ctx.task['phase'] == 'source_speech':
        return source_speech(ctx)
    if ctx.task['phase'] == 'edited_output':
        return edited_output(ctx)
    raise RoleBlocked('Unknown Reviewer phase')
