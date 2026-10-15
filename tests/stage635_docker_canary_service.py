"""TEST_ONLY editing worker for a locally built Docker image.

Mount this file read-only at /canary.py. It injects replay responses rather
than enabling the environment-selected live provider. Never use with a real
source database or a public port.
"""

import hashlib
import json
import os
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

from backend.editing_api import EditingService
from backend.editing_worker import create_server
from backend.media_worker.intake_adapter import stage5
from backend.roles import Stage5RoleExecutor
from backend.roles.provider import TestOnlyReplayProvider


def main():
    if os.getenv('MANDALA_STAGE635_TEST_ONLY') != '1':
        raise SystemExit('TEST_ONLY guard missing')
    if os.getenv('MANDALA_EDITING_LIVE_ROLES_ENABLED') == '1':
        raise SystemExit('Live provider forbidden in canary')
    for name in ('MANDALA_EDITING_DATABASE_URL', 'MANDALA_SOURCE_DATABASE_URL'):
        dsn = conninfo_to_dict(os.environ[name])
        if (dsn.get('host') != '127.0.0.1' or
                dsn.get('dbname') != 'mandala_stage635_canary'):
            raise SystemExit('Refusing non-isolated database')
    video_id = os.environ['MANDALA_STAGE635_CANARY_VIDEO_ID']
    if not video_id.isdigit() or len(video_id) != 19:
        raise SystemExit('Invalid synthetic video ID')
    source = Path('/data/source/originals') / (video_id + '.mp4')
    from validate_universal_analysis_v02 import sample_analysis
    analysis = sample_analysis()
    media = stage5.probe_video(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    analysis['source'] = {'video_id': 'local-sha256-' + sha[:32], **media}
    analysis['segments'][0]['end_sec'] = media['duration_sec']
    analysis['editing_opportunities'][0].update(start_sec=.5, end_sec=2.5)

    service = EditingService.from_env()
    provider = TestOnlyReplayProvider({'analyst': [json.dumps(analysis)]})
    service.executor = Stage5RoleExecutor(
        service.store, service.admission, provider=provider,
        proof=service.proof_path)
    server = create_server(
        service, host='127.0.0.1', port=3003,
        start_dispatcher=os.getenv('MANDALA_STAGE635_CANARY_DISPATCH') == '1')
    server.serve_forever()


if __name__ == '__main__':
    main()
