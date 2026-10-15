"""One reserved Creative Director proposal per HTTP task."""

from backend.roles.common import RoleBlocked


def execute(ctx):
    import automatic_editing_validation_v01 as validator
    import run_automatic_editing_v01 as workflow

    ctx.source()
    request = ctx.json_input('automatic_request')
    packet = ctx.json_input('director_packet')
    workflow.verify_inputs(request)
    workflow.check_proof(request['proof'])
    if (request['source_sha256'] != ctx.job['source_sha256'].strip() or
            request['code_receipts'] != validator.code_receipts() or
            request['environment'] != workflow.core.environment()):
        raise RoleBlocked('Stage 5 request lineage changed')
    attempt = ctx.task['attempt']
    if not 1 <= attempt <= 3:
        raise RoleBlocked('Director attempt outside budget')
    previous = None
    if attempt > 1:
        prior = ctx.directory / f'proposal-{attempt - 1:02d}/proposal.json'
        if prior.exists():
            previous = workflow.read(prior)
    diagnosis_rows = [r for r in ctx.rows('revision_diagnosis')
                      if r['id'] in ctx.task['input_artifact_ids']]
    diagnosis_record = (workflow.read(ctx._verified_path(diagnosis_rows[0]))
                        if diagnosis_rows else {'findings': []})
    diagnosis = diagnosis_record.get('findings')
    if len(diagnosis_rows) > 1 or not isinstance(diagnosis, list):
        raise RoleBlocked('Revision diagnosis is ambiguous')
    prompt = workflow.core.director.safe_text(
        workflow.prompt_for(ctx.directory, request, diagnosis, previous), 65536)
    root = ctx.directory / f'proposal-{attempt:02d}'
    root.mkdir()
    ctx.write_text(f'proposal-{attempt:02d}/prompt.txt', prompt, 'director_prompt')
    ctx.write_json(f'proposal-{attempt:02d}/reservation.json', {
        'attempt': attempt, 'maximum_proposals': 3, 'api_calls': 1,
        'prompt_sha256': workflow.core.director.digest_text(prompt),
        'request_sha256': workflow.core.digest_object(request),
        'attached_images': request['storyboard'],
        'correction_diagnosis': diagnosis, 'human_verified': False},
        'director_file_reservation')
    raw = ctx.paid('director', {
        'prompt_sha256': workflow.core.director.digest_text(prompt),
        'image_sha256': [p['sha256'] for p in request['storyboard']]},
        lambda: ctx.provider.director(prompt, [p['path'] for p in request['storyboard']]),
        attempt=attempt)
    if not isinstance(raw, str):
        raise RoleBlocked('Director response is not text')
    raw = workflow.core.director.safe_text(raw)
    ctx.write_text(f'proposal-{attempt:02d}/raw-response.json', raw, 'director_raw')
    try:
        proposal = workflow.core.director.parse_response(raw)
    except workflow.core.Error:
        raise RoleBlocked('Director response malformed') from None
    if proposal.get('source_sha256') != packet['source']['sha256']:
        raise RoleBlocked('Director proposal source mismatch')
    ctx.write_json(f'proposal-{attempt:02d}/proposal.json', proposal, 'director_proposal')
    return {'state': 'SUCCEEDED'}
