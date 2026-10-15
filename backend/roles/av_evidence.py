"""Offline Stage 5 AV signal evidence and source-bound Director packet."""

from backend.roles.common import RoleBlocked


def execute(ctx):
    import analyze_adaptive_av_evidence_v01 as av
    import adaptive_director_evidence_v03 as intake
    import build_adaptive_director_input_v03 as builder
    import run_automatic_editing_v01 as workflow

    video, _ = ctx.source()
    metadata = ctx.input('source_metadata')
    canonical = ctx.input('canonical_analysis')
    ctx.begin()
    base_director = ctx.directory / 'av/director-input.json'
    base_director.parent.mkdir(parents=True, exist_ok=True)
    builder.build_director_input(video, metadata, canonical, base_director)
    ctx.artifact(base_director, 'director_input')
    bundle = ctx.directory / 'av/bundle'
    report = av.generate(video, metadata, canonical, bundle, director_input=base_director)
    ctx.register_tree(bundle, 'av_receipt')
    if report['validation_status'] != 'passed':
        raise RoleBlocked('Stage 5 AV evidence validation blocked')
    packet = intake.build_packet(video, metadata, canonical, bundle / av.ENRICHED,
                                 bundle)
    intake.validate_packet(packet)
    ctx.write_json('packet.json', packet, 'director_packet')
    board = workflow.storyboard(video, ctx.directory, packet['source']['duration_sec'])
    ctx.register_tree(ctx.directory / 'storyboard', 'storyboard_frame')
    ctx.write_json('av/receipt.json', {
        'status': 'SOURCE_BOUND_AV_REPLAYED', 'source_sha256': packet['source']['sha256'],
        'board': board, 'human_verified': False, 'production_eligible': False},
        'av_role_receipt')
    return {'state': 'SUCCEEDED'}
