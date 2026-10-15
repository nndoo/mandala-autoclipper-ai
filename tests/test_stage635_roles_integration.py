"""PostgreSQL 16 + synthetic media + injected replay; never invoke live providers."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.conninfo import conninfo_to_dict

from backend.editing_dispatch import Dispatcher
from backend.editing_store import EditingStore, apply_migration
from backend.roles import Stage5RoleExecutor
from backend.roles.provider import TestOnlyReplayProvider
from backend.source_admission import SourceAdmission

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class Stage635RolesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.getenv('MANDALA_STAGE635_TEST_ADMIN_DSN')
        if not cls.dsn:
            raise unittest.SkipTest('Isolated PostgreSQL 16 DSN not supplied')
        fields = conninfo_to_dict(cls.dsn)
        if fields.get('host') != '127.0.0.1' or fields.get('dbname') != 'mandala_stage635_test':
            raise RuntimeError('Refusing non-isolated PostgreSQL DSN')
        with psycopg.connect(cls.dsn) as conn:
            version = int(conn.execute('SHOW server_version_num').fetchone()[0])
        if not 160000 <= version < 170000:
            raise RuntimeError('PostgreSQL 16 required')
        apply_migration(cls.dsn)
        cls.test_root = ROOT / 'data' / ('stage635-test-only-' + uuid.uuid4().hex)
        cls.source_root = cls.test_root / 'source'
        (cls.source_root / 'originals').mkdir(parents=True)
        cls.proof = cls.test_root / 'TEST_ONLY-proof.json'
        cls.proof.write_text('{"test_only":true}\n')
        cls.addClassCleanup(lambda: shutil.rmtree(cls.test_root))
        cls.output_root = ROOT / 'data/revisions/stage59/automatic'
        cls.output_root.mkdir(parents=True, exist_ok=True)
        cls.video_id = '9' + str(uuid.uuid4().int % 10**18).zfill(18)
        cls.source_key = 'tiktok:' + cls.video_id
        cls.video = cls.source_root / 'originals' / (cls.video_id + '.mp4')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'testsrc2=size=320x480:rate=30', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=48000', '-t', '4', '-c:v', 'mpeg4',
            '-q:v', '10', '-c:a', 'aac', '-shortest', str(cls.video)],
            check=True, timeout=60)
        from backend.media_worker.intake_adapter import stage5
        cls.media = stage5.probe_video(cls.video)
        cls.sha = hashlib.sha256(cls.video.read_bytes()).hexdigest()
        with psycopg.connect(cls.dsn) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS public.source_videos (
                source_key text PRIMARY KEY, platform text NOT NULL,
                username text NOT NULL, video_id text NOT NULL, status text NOT NULL,
                original_local_path text NOT NULL, original_size_bytes bigint NOT NULL,
                original_sha256 text NOT NULL, original_duration_seconds numeric NOT NULL,
                original_width integer NOT NULL, original_height integer NOT NULL)''')
            conn.execute('''INSERT INTO public.source_videos
                (source_key, platform, username, video_id, status, original_local_path,
                 original_size_bytes, original_sha256, original_duration_seconds,
                 original_width, original_height)
                VALUES (%s, 'tiktok', 'mandala.auto.kediri', %s, 'ORIGINAL_READY',
                        %s, %s, %s, %s, %s, %s)''',
                (cls.source_key, cls.video_id, str(cls.video), cls.video.stat().st_size,
                 cls.sha, cls.media['duration_sec'], cls.media['width'], cls.media['height']))
        cls.addClassCleanup(cls._clean_source)

    @classmethod
    def _clean_source(cls):
        with psycopg.connect(cls.dsn) as conn:
            conn.execute('DELETE FROM public.source_videos WHERE source_key = %s',
                         (cls.source_key,))

    def setUp(self):
        from validate_universal_analysis_v02 import sample_analysis
        analysis = sample_analysis()
        analysis['source'] = {'video_id': 'local-sha256-' + self.sha[:32], **self.media}
        analysis['segments'][0]['end_sec'] = self.media['duration_sec']
        analysis['editing_opportunities'][0].update(start_sec=.5, end_sec=2.5)
        self.provider = TestOnlyReplayProvider({'analyst': [json.dumps(analysis)]})
        self.store = EditingStore(self.dsn, output_root=self.output_root)
        self.admission = SourceAdmission(self.dsn, self.store,
                                         storage_root=self.source_root)
        self.executor = Stage5RoleExecutor(self.store, self.admission,
                                           provider=self.provider, proof=self.proof)
        self.dispatch = Dispatcher(self.store, self.admission, executor=self.executor,
                                   ready=lambda: True)
        request = {'contract_version': 'stage6.3.5-v1', 'source_key': self.source_key,
                   'expected_sha256': self.sha}
        self.job, _ = self.admission.admit(request, principal='workflow',
                                           key='test-only-' + uuid.uuid4().hex)
        self.job_id = self.job['id']
        self.addCleanup(self._cleanup_job)
        self.store.approve_paid_inference(self.job_id)

    def _cleanup_job(self):
        with psycopg.connect(self.dsn) as conn:
            for table in ('idempotency_keys', 'job_events', 'artifacts', 'call_reservations',
                          'permits', 'tasks', 'jobs'):
                if table == 'idempotency_keys':
                    conn.execute('DELETE FROM mandala_engine.idempotency_keys WHERE job_id = %s '
                                 'OR task_id IN (SELECT id FROM mandala_engine.tasks WHERE job_id = %s)',
                                 (self.job_id, self.job_id))
                elif table == 'jobs':
                    conn.execute('DELETE FROM mandala_engine.jobs WHERE id = %s',
                                 (self.job_id,))
                else:
                    conn.execute(f'DELETE FROM mandala_engine.{table} WHERE job_id = %s',
                                 (self.job_id,))
        shutil.rmtree(self.output_root / str(self.job_id), ignore_errors=True)

    def step(self):
        job = self.store.get_job(self.job_id)
        action = job['next_action']
        self.assertIsNotNone(action)
        task, _ = self.store.submit_task(self.job_id, principal='workflow',
            key='test-only-task-' + uuid.uuid4().hex,
            expected_version=job['version'], role=action['role'], phase=action['phase'],
            attempt=action['attempt'], input_artifact_ids=action['input_artifact_ids'],
            regions=action.get('regions'))
        self.assertEqual(self.dispatch.run_once(), task['id'])
        return self.store.get_task(task['id'])

    def test_analyst_av_speech_free_path(self):
        analyst = self.step()
        self.assertEqual(analyst['state'], 'SUCCEEDED', analyst)
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        av = self.step()
        self.assertEqual(av['state'], 'SUCCEEDED', av)
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        speech = self.step()
        self.assertEqual(speech['state'], 'SUCCEEDED', speech)
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], 'director')

    def test_synthetic_private_preview_role_chain(self):
        import renderer_core_v01 as core
        import run_automatic_editing_v01 as workflow
        from test_automatic_editing_v01 import proposal

        for expected in ('analyst', 'revision-controller', 'av-evidence',
                         'revision-controller', 'speech-asr', 'revision-controller'):
            self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], expected)
            self.assertEqual(self.step()['state'], 'SUCCEEDED')
        packet = workflow.read(self.output_root / str(self.job_id) / 'packet.json')
        candidate = proposal(packet)
        self.provider.replies['director'] = [json.dumps(candidate)]
        proof = {'verified_capabilities': list(core.FILTERS)}
        with patch.object(workflow, 'check_proof', return_value=proof):
            seen = []
            for _ in range(12):
                job = self.store.get_job(self.job_id)
                if not job['next_action']:
                    break
                role = job['next_action']['role']
                if role == 'reviewer':
                    manifest = workflow.read(self.output_root / str(self.job_id) /
                                             'proposal-01/render/manifest.json')
                    self.provider.replies['reviewer'] = [json.dumps({
                        'media_sha256': manifest['output']['sha256'],
                        'video_examined': True, 'audio_examined': True,
                        'revision_required': False, 'issues': [],
                        'assessment': 'Synthetic TEST_ONLY review response; no actual model observation.',
                        'human_verified': False, 'production_eligible': False})]
                if role == 'renderer':
                    original_execute = self.executor.execute
                    def debug_execute(task, job):
                        try:
                            return original_execute(task, job)
                        except Exception as error:
                            print('TEST_ONLY renderer diagnostic:', type(error).__name__, str(error)[:300])
                            raise
                    self.executor.execute = debug_execute
                task = self.step()
                seen.append((role, task['state'], task['failure_class']))
                if task['state'] != 'SUCCEEDED':
                    break
            self.assertEqual([r for r, _, _ in seen], [
                'director', 'revision-controller', 'validator', 'revision-controller',
                'renderer', 'revision-controller', 'technical-qa',
                'revision-controller', 'reviewer', 'revision-controller'], seen)
            self.assertIn(self.store.get_job(self.job_id)['state'],
                          ('AUTO_PREVIEW_COMPLETED', 'AUTO_PREVIEW_COMPLETED_WITH_NOTES'))


if __name__ == '__main__':
    unittest.main()
