"""Independent actual-MP4 Stage 5 decode, audio, black-frame and glyph checks."""

import os
import tempfile
from pathlib import Path

from backend.roles.common import RoleBlocked


def execute(ctx):
    import render_showcase_preview_v01 as preview
    import renderer_revision_v02 as audio
    import run_automatic_editing_v01 as workflow

    ctx.source()
    attempt = ctx.task['attempt']
    root = ctx.directory / f'proposal-{attempt:02d}'
    video = ctx.input('render_output')
    receipt = ctx.json_input('render_encode_receipt')
    plan = workflow.read(root / 'render/plan.json')
    spec = workflow.read(root / 'render/spec.json')
    graph = workflow.read(root / 'render/timeline.json')
    if (receipt['status'] != 'ENCODED_QA_PENDING' or
            receipt['output']['sha256'] != workflow.core.intake.gate.sha256_file(video) or
            receipt['output']['bytes'] != video.stat().st_size or
            audio.compile_timeline(plan, spec) != {k: v for k, v in graph.items()
                                                  if k != 'automatic_text_cues'}):
        raise RoleBlocked('Render receipt or graph mismatch')
    if plan['source']['sha256'] != ctx.job['source_sha256'].strip():
        raise RoleBlocked('Render source mismatch')
    try:
        limits = spec['visual_spec']['resources']
        verified = workflow.core.verify_output(video, graph, True, limits)
        if verified != receipt['verification']:
            raise workflow.core.Error('Independent decode differs from render receipt')
        black = preview.black_scan(video, graph, limits,
                                   decoded_frame_count=verified['frame_count'])
        mapping = audio.measure_audio_mapping(workflow.core.safe_path(plan['source']['path']),
                                               video, graph, spec)
        headroom = workflow.stereo_headroom(video, graph, limits)
        with tempfile.TemporaryDirectory(dir=ctx.directory, prefix='.qa-work-') as temporary:
            work = Path(temporary)
            visibility = workflow.visibility(video, graph, spec, work)
            # Preserve measured screenshot receipts without replacing the Stage 5 writer.
            for path in sorted(work.glob('caption-*.png')):
                output = root / 'render' / path.name
                os.link(path, output)
                ctx.artifact(output, 'qa_caption_sample')
    except (workflow.core.Error, OSError, ValueError, KeyError, TypeError):
        ctx.write_json(f'proposal-{attempt:02d}/technical-qa.json', {
            'status': 'BLOCKED', 'reason': 'ACTUAL_MEDIA_QA_BLOCKED',
            'human_verified': False, 'production_eligible': False}, 'technical_qa')
        return {'state': 'BLOCKED', 'failure_class': 'ACTUAL_MEDIA_QA_BLOCKED'}
    technical = {'decode': verified, 'audio_mapping': mapping,
                 'execution': receipt['execution'], 'black_frames': black,
                 'audio_headroom': headroom, 'text_visibility': visibility}
    manifest = {'status': 'PRIVATE_PREVIEW_COMPLETED', 'source': plan['source'],
                'output': receipt['output'], 'technical': technical,
                'code_receipts': workflow.validator.code_receipts(),
                'environment': workflow.core.environment(), 'human_verified': False,
                'production_eligible': False, 'publishing_eligible': False,
                'permit': workflow.reference(root / 'permit.json')}
    ctx.write_json(f'proposal-{attempt:02d}/render/manifest.json', manifest,
                   'render_manifest')
    ctx.write_json(f'proposal-{attempt:02d}/technical-qa.json', {
        'status': 'PASS', 'output_sha256': receipt['output']['sha256'],
        'checks': ['decode', 'black_scan', 'audio_mapping', 'headroom', 'glyph_visibility'],
        'human_verified': False, 'production_eligible': False}, 'technical_qa')
    return {'state': 'SUCCEEDED'}
