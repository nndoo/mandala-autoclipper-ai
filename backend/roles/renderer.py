"""One-use DB permit plus existing Stage 5 private-preview encoder."""

import tempfile
from pathlib import Path

from backend.roles.common import RoleBlocked


def execute(ctx):
    import automatic_editing_validation_v01 as validator
    import renderer_revision_v02 as audio
    import render_video_v01 as renderer
    import run_automatic_editing_v01 as workflow

    source, _ = ctx.source()
    request = ctx.json_input('automatic_request')
    proposal = ctx.json_input('director_proposal')
    report = ctx.json_input('plan_validation')
    plan = ctx.json_input('visual_plan')
    spec = ctx.json_input('execution_spec')
    packet = workflow.read(ctx.directory / 'packet.json')
    speech = workflow.read(ctx.directory / 'speech.json')
    replay, p, s, graph = validator.validate(proposal, packet, speech)
    if report != replay or report['status'] != 'AUTO_PREVIEW_ELIGIBLE' or p != plan or s != spec:
        raise RoleBlocked('Independent render plan replay mismatch')
    workflow.check_proof(request['proof'])
    attempt = ctx.task['attempt']
    root = ctx.directory / f'proposal-{attempt:02d}'
    permit = {'scope': 'STAGE59_PRIVATE_PREVIEW', 'human_verified': False,
              'production_eligible': False, 'source_sha256': plan['source']['sha256'],
              'proposal_sha256': workflow.core.digest_object(proposal),
              'execution_sha256': workflow.core.digest_object(spec),
              'request_sha256': workflow.core.digest_object(request)}
    ctx.fence()
    permit_id = ctx.store.issue_permit(ctx.task['id'], ctx.worker_id, ctx.epoch,
        attempt=attempt, proposal_sha256=permit['proposal_sha256'],
        execution_sha256=permit['execution_sha256'], request_sha256=permit['request_sha256'])
    ctx.write_json(f'proposal-{attempt:02d}/permit.json', permit, 'render_permit')
    ctx.source()
    ctx.store.consume_permit(permit_id, ctx.worker_id, ctx.epoch)
    with renderer.render_lock(), tempfile.TemporaryDirectory(
            dir=ctx.directory, prefix='.revision-work-') as temporary:
        video, timeline, verified, mapping, execution = audio.encode(
            source, plan, spec, Path(temporary), mode='AUTOMATIC_PRIVATE_PREVIEW',
            context={'job': str(ctx.directory), 'attempt': str(root)})
        output = root / 'render'
        output_ref = {'path': str(output / 'preview.mp4'),
                      'sha256': workflow.core.intake.gate.sha256_file(video),
                      'bytes': video.stat().st_size}
        audio.publish(output, {'preview.mp4': video}, {
            'plan.json': plan, 'spec.json': spec, 'timeline.json': timeline,
            'encode-result.json': {'status': 'ENCODED_QA_PENDING', 'output': output_ref,
                'verification': verified, 'audio_mapping': mapping,
                'execution': execution, 'human_verified': False,
                'production_eligible': False}}, workflow.ROOT)
    ctx.artifact(root / 'render/preview.mp4', 'render_output')
    ctx.artifact(root / 'render/encode-result.json', 'render_encode_receipt')
    for name in ('plan.json', 'spec.json', 'timeline.json'):
        ctx.artifact(root / 'render' / name, 'render_receipt')
    ctx.artifact(root / 'permit-consumed.json', 'render_permit_consumed')
    return {'state': 'SUCCEEDED'}
