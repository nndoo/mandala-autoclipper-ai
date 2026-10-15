"""Per-region ASR; Source Reviewer is a separate task and budget."""

import tempfile
from pathlib import Path

from backend.roles.common import RoleBlocked


def _region_id(index):
    return f'region-{index:02d}'


def _latest(ctx, region_id):
    folders = sorted(ctx.directory.glob(f'asr-{region_id}-*/timing-validation.json'))
    if not folders:
        return None
    return folders[-1].parent


def assemble(ctx, packet):
    """Replay latest raw timing for every required region, without new calls."""
    import run_automatic_editing_v01 as workflow
    regions = [r for r in packet['speech']['requirements']['regions']
               if r['requirement'] != 'not_required']
    units, raws, uploads, counts, modes, blocked = [], [], [], {}, set(), []
    for index, region in enumerate(regions):
        rid = _region_id(index)
        folders = sorted(ctx.directory.glob(f'asr-{rid}-*/reservation.json'))
        counts[rid] = len(folders)
        latest = _latest(ctx, rid)
        if latest is None:
            blocked.append(rid)
            continue
        validation = workflow.read(latest / 'timing-validation.json')
        if validation['status'] != 'PASS':
            blocked.append(rid)
            continue
        raw, upload = workflow.read(latest / 'raw-response.json'), workflow.read(latest / 'upload.json')
        if upload['source_sha256'] != packet['source']['sha256'] or raw.get('status') != 'complete':
            raise RoleBlocked('ASR raw/source mismatch')
        mode, group = workflow.timed_units(raw['payload'], region['start_sec'], region['end_sec'], rid)
        if mode != validation['timing'] or group != validation['units']:
            raise RoleBlocked('ASR timing differs from raw replay')
        modes.add(mode)
        units.extend(group)
        raws.append(workflow.reference(latest / 'raw-response.json'))
        uploads.append(workflow.reference(latest / 'upload.json'))
    if len(modes) > 1:
        raise RoleBlocked('Mixed word/phrase timing cannot be merged')
    return {'required': True, 'status': 'AWAITING_SOURCE_REVIEW' if not blocked else 'BLOCKED_ASR',
            'source_sha256': packet['source']['sha256'], 'timing': next(iter(modes), 'none'),
            'units': units, 'raw_responses': raws, 'upload_receipts': uploads,
            'attempt_counts': counts, 'blocked_regions': blocked,
            'human_verified': False, 'production_eligible': False}


def finalize_request(ctx, packet, speech):
    """Create Stage 5 automatic request only after speech admission."""
    import automatic_editing_validation_v01 as validator
    import run_automatic_editing_v01 as workflow

    board = [workflow.reference(path) for path in sorted((ctx.directory / 'storyboard').glob('*.jpg'))]
    board = [{'time_sec': round((i + .5) * packet['source']['duration_sec'] / len(board), 3), **ref}
             for i, ref in enumerate(board)] if board else []
    if not board:
        raise RoleBlocked('Stage 5 storyboard absent')
    request = {'kind': 'automatic_stage59_private_job',
               'source_sha256': packet['source']['sha256'],
               'inputs': [workflow.reference(ctx.directory / 'packet.json'),
                          workflow.reference(ctx.directory / 'speech.json'),
                          workflow.reference(packet['source']['path']),
                          *[{'path': p['path'], 'sha256': p['sha256']} for p in board]],
               'storyboard': board, 'proof': workflow.reference(ctx.proof),
               'comparison': None, 'code_receipts': validator.code_receipts(),
               'environment': workflow.core.environment(),
               'maximum_director_proposals': 3, 'maximum_asr_attempts_per_region': 2,
               'human_verified': False, 'production_eligible': False,
               'publishing_eligible': False}
    return ctx.write_json('request.json', request, 'automatic_request')


def execute(ctx):
    import generate_remote_speech_evidence_v01 as asr
    import run_automatic_editing_v01 as workflow

    video, _ = ctx.source()
    packet = ctx.json_input('director_packet')
    workflow.core.intake.validate_packet(packet)
    ctx.begin()
    requirement = packet['speech']['requirements']
    if requirement['overall_requirement'] == 'not_required':
        speech = {'required': False, 'status': 'NOT_REQUIRED',
                  'source_sha256': packet['source']['sha256'], 'units': [],
                  'timing': 'none', 'human_verified': False}
        ctx.write_json('speech.json', speech, 'speech_evidence')
        finalize_request(ctx, packet, speech)
        return {'state': 'SUCCEEDED'}

    required = [(i, r) for i, r in enumerate(requirement['regions'])
                if r['requirement'] != 'not_required']
    if not required:
        raise RoleBlocked('Speech classification has no source regions')
    retry_rows = [r for r in ctx.rows('asr_retry_regions') if r['id'] in ctx.task['input_artifact_ids']]
    selected = None
    if retry_rows:
        if len(retry_rows) != 1:
            raise RoleBlocked('Ambiguous ASR retry regions')
        retry = workflow.read(ctx._verified_path(retry_rows[0]))
        if not isinstance(retry.get('regions'), list):
            raise RoleBlocked('Invalid ASR retry region list')
        selected = set(retry['regions'])
        if not selected or not selected <= {_region_id(i) for i, _ in required}:
            raise RoleBlocked('Invalid ASR retry region identity')
    _, config = asr.load_config(asr.DEFAULT_CONFIG)
    config = {**config, 'response_format': 'verbose_json'}
    for index, region in required:
        rid = _region_id(index)
        if selected is not None and rid not in selected:
            continue
        count = sum(r['kind'] == 'speech_asr' and r['region_key'] == rid
                    for r in ctx.store.reservation_rows(ctx.job['id']))
        if count >= 2:
            raise RoleBlocked('ASR region budget exhausted')
        attempt = count + 1
        dest = ctx.directory / f'asr-{rid}-{attempt:02d}'
        dest.mkdir()
        ctx.write_json(f'{dest.name}/reservation.json', {
            'region_id': rid, 'attempt': attempt, 'maximum_attempts': 2,
            'source_sha256': packet['source']['sha256'],
            'start_sec': region['start_sec'], 'end_sec': region['end_sec'],
            'api_calls': 1, 'human_verified': False}, 'asr_file_reservation')
        with tempfile.TemporaryDirectory(dir=ctx.directory, prefix='.asr-work-') as temporary:
            temp = Path(temporary)
            wav = temp / 'audio.wav'
            workflow.core.ffmpeg(['-i', str(video), '-ss', workflow.core.n(region['start_sec']),
                '-t', workflow.core.n(region['end_sec'] - region['start_sec']),
                '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)],
                temp, workflow.audio.LIMITS)
            request = {'source_sha256': packet['source']['sha256'], 'region': rid,
                       'attempt': attempt, 'wav_sha256': workflow.core.intake.gate.sha256_file(wav),
                       'config_sha256': workflow.core.digest_object(config)}
            result = ctx.paid('speech_asr', request,
                              lambda: ctx.provider.asr(config, wav, temp),
                              region=rid, attempt=attempt)
            ctx.write_json(f'{dest.name}/upload.json', {
                'sha256': request['wav_sha256'], 'bytes': wav.stat().st_size,
                'source_sha256': request['source_sha256'],
                'start_sec': region['start_sec'], 'end_sec': region['end_sec'],
                'config_sha256': request['config_sha256']}, 'asr_upload_receipt')
        ctx.write_json(f'{dest.name}/raw-response.json', result, 'asr_raw')
        try:
            if result.get('status') != 'complete':
                raise workflow.core.Error('ASR response incomplete')
            timing, units = workflow.timed_units(result['payload'], region['start_sec'],
                                                  region['end_sec'], rid)
            validation = {'status': 'PASS', 'timing': timing, 'units': units,
                          'human_verified': False}
        except (workflow.core.Error, KeyError, TypeError):
            validation = {'status': 'BLOCKED', 'reason': 'TIMING_UNAVAILABLE',
                          'human_verified': False}
        ctx.write_json(f'{dest.name}/timing-validation.json', validation, 'asr_timing')
    draft = assemble(ctx, packet)
    round_number = max(draft['attempt_counts'].values(), default=1)
    ctx.write_json(f'speech-draft-{round_number:02d}.json', draft, 'speech_draft')
    return {'state': 'BLOCKED' if draft['blocked_regions'] else 'SUCCEEDED',
            'failure_class': 'ASR_TIMING_BLOCKED' if draft['blocked_regions'] else None}
