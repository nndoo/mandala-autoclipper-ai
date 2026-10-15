"""Universal V0.2 Analyst: existing 9Router transport and Stage 5 validator."""

import copy
import hashlib
import json

from backend.media_worker.intake_adapter import IntakeError, validate_canonical_analysis
from backend.roles.common import RoleBlocked


def execute(ctx):
    import run_adaptive_director_v03 as director
    from normalize_universal_analysis_v02 import find_analysis

    video, intake = ctx.source()
    ctx.begin()
    metadata = ctx.write_json('source-metadata.json', intake['metadata'], 'source_metadata')
    request = {'role': 'analyst', 'source_sha256':ctx.job['source_sha256'].strip(),
               'metadata_sha256': metadata['sha256'].strip(),
               'video_sha256': intake['metadata']['verification']['sha256']}
    raw = ctx.paid('analyst', request, lambda: ctx.provider.analyst(video))
    if not isinstance(raw, str):
        raise RoleBlocked('Analyst response is not text')
    raw = director.safe_text(raw, 131072)
    ctx.write_text('analyst/raw-response.json', raw, 'analyst_raw')
    analysis = find_analysis(raw)
    if not isinstance(analysis, dict):
        raise RoleBlocked('Universal V0.2 analysis unavailable in response')
    analysis = copy.deepcopy(analysis)
    # Stage 5 normalization binds model findings to independently checked source metadata.
    analysis['source'] = copy.deepcopy(intake['source'])
    analysis['analysis_status'] = 'DRAFT_UNVERIFIED'
    try:
        warnings = validate_canonical_analysis(intake, analysis)
    except IntakeError:
        raise RoleBlocked('Stage 5 Universal analysis validation blocked') from None
    canonical = ctx.write_json('analyst/canonical.json', analysis, 'canonical_analysis')
    ctx.write_json('analyst/receipt.json', {
        'mode': 'TEST_ONLY_REPLAY' if getattr(ctx.provider, 'test_only', False) else 'LIVE_MODEL_INFERENCE',
        'source_sha256': request['source_sha256'],
        'raw_sha256': hashlib.sha256(raw.encode()).hexdigest(),
        'canonical_sha256': canonical['sha256'].strip(), 'warnings': warnings,
        'human_verified': False, 'production_eligible': False,
        'publishing_eligible': False}, 'analyst_receipt')
    return {'state': 'SUCCEEDED'}
