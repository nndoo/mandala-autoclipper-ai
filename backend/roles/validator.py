"""Independent Stage 5 proposal and source/speech validation."""

from backend.roles.common import RoleBlocked


def execute(ctx):
    import automatic_editing_validation_v01 as validator
    import run_automatic_editing_v01 as workflow

    ctx.source()
    packet = ctx.json_input('director_packet')
    speech = ctx.json_input('speech_evidence')
    proposal = ctx.json_input('director_proposal')
    if proposal != workflow.read(ctx.directory / f'proposal-{ctx.task["attempt"]:02d}/proposal.json'):
        raise RoleBlocked('Director proposal artifact mismatch')
    workflow.core.intake.validate_packet(packet)
    workflow.verify_speech(packet, speech)
    report, plan, spec, graph = validator.validate(proposal, packet, speech)
    prefix = f'proposal-{ctx.task["attempt"]:02d}'
    ctx.write_json(f'{prefix}/validation.json', report, 'plan_validation')
    if report['status'] != 'AUTO_PREVIEW_ELIGIBLE':
        return {'state': 'BLOCKED', 'failure_class': 'PLAN_VALIDATION_BLOCKED'}
    ctx.write_json(f'{prefix}/visual-plan.json', plan, 'visual_plan')
    ctx.write_json(f'{prefix}/execution.json', spec, 'execution_spec')
    ctx.write_json(f'{prefix}/timeline.json', graph, 'validated_timeline')
    return {'state': 'SUCCEEDED'}
