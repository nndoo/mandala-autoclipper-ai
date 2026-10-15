"""Stage C HTTP/queue/recovery integration on isolated local PostgreSQL 16."""

import concurrent.futures
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from backend.editing_api import ApiError, EditingService, Handler
from backend.editing_dispatch import Dispatcher, ROLE_PHASES, TestOnlyMockExecutor
from backend.editing_store import EditingStore, apply_migration
from backend.editing_worker import create_server
from backend.media_worker.intake_adapter import stage5
from backend.source_admission import SourceAdmission


class Stage635ApiIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_dsn = os.getenv('MANDALA_STAGE635_TEST_ADMIN_DSN')
        if not cls.admin_dsn:
            raise unittest.SkipTest('Isolated PostgreSQL 16 DSN not supplied')
        fields = conninfo_to_dict(cls.admin_dsn)
        if fields.get('host') != '127.0.0.1' or fields.get('dbname') != 'mandala_stage635_test':
            raise RuntimeError('Refusing non-isolated PostgreSQL DSN')
        with psycopg.connect(cls.admin_dsn) as conn:
            version = int(conn.execute('SHOW server_version_num').fetchone()[0])
        if not 160000 <= version < 170000:
            raise RuntimeError('PostgreSQL 16 is required')
        apply_migration(cls.admin_dsn)
        cls.temp = tempfile.TemporaryDirectory(prefix='mandala-stage635-api-test-only-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.source_root = cls.root / 'source'
        (cls.source_root / 'originals').mkdir(parents=True)
        cls.output_root = cls.root / 'output'
        cls.output_root.mkdir()
        cls.proof = cls.root / 'TEST_ONLY-proof.json'
        cls.proof.write_text('{"test_only":true}')
        cls.master = cls.root / 'synthetic.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x480:rate=30',
                        '-t', '1.2', '-c:v', 'mpeg4', '-q:v', '10', str(cls.master)],
                       check=True, timeout=30)
        cls.media = stage5.probe_video(cls.master)
        cls.sha256 = hashlib.sha256(cls.master.read_bytes()).hexdigest()
        cls.source_role = 'stage635_api_source_' + uuid.uuid4().hex[:8]
        cls.edit_role = 'stage635_api_edit_' + uuid.uuid4().hex[:8]
        source_password, edit_password = uuid.uuid4().hex, uuid.uuid4().hex
        with psycopg.connect(cls.admin_dsn) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS public.source_videos (
                source_key text PRIMARY KEY, platform text NOT NULL,
                username text NOT NULL, video_id text NOT NULL, status text NOT NULL,
                original_local_path text NOT NULL, original_size_bytes bigint NOT NULL,
                original_sha256 text NOT NULL, original_duration_seconds numeric NOT NULL,
                original_width integer NOT NULL, original_height integer NOT NULL
            )''')
            for role, password in ((cls.source_role, source_password),
                                   (cls.edit_role, edit_password)):
                conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                    sql.Identifier(role), sql.Literal(password)))
                conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
                    sql.Identifier('mandala_stage635_test'), sql.Identifier(role)))
            conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(
                sql.Identifier(cls.source_role)))
            conn.execute(sql.SQL('GRANT SELECT ON public.source_videos TO {}').format(
                sql.Identifier(cls.source_role)))
            conn.execute(sql.SQL('GRANT USAGE ON SCHEMA mandala_engine TO {}').format(
                sql.Identifier(cls.edit_role)))
            conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON ALL TABLES '
                                 'IN SCHEMA mandala_engine TO {}').format(
                sql.Identifier(cls.edit_role)))
            conn.execute(sql.SQL('GRANT USAGE ON ALL SEQUENCES '
                                 'IN SCHEMA mandala_engine TO {}').format(
                sql.Identifier(cls.edit_role)))
        cls.source_dsn = make_conninfo(cls.admin_dsn, user=cls.source_role,
                                       password=source_password)
        cls.edit_dsn = make_conninfo(cls.admin_dsn, user=cls.edit_role,
                                     password=edit_password)
        cls.workflow_token = uuid.uuid4().hex + uuid.uuid4().hex
        cls.operator_token = uuid.uuid4().hex + uuid.uuid4().hex
        cls.counter = 0

    def setUp(self):
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''TRUNCATE mandala_engine.idempotency_keys,
                mandala_engine.job_events, mandala_engine.permits,
                mandala_engine.artifacts, mandala_engine.call_reservations,
                mandala_engine.tasks, mandala_engine.jobs RESTART IDENTITY CASCADE''')
            conn.execute('TRUNCATE public.source_videos')
        type(self).counter += 1
        self.video_id = str(8000000000000000000 + self.counter)
        self.source_key = 'tiktok:' + self.video_id
        self.video = self.source_root / 'originals' / (self.video_id + '.mp4')
        shutil.copyfile(self.master, self.video)
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''INSERT INTO public.source_videos
                (source_key, platform, username, video_id, status,
                 original_local_path, original_size_bytes, original_sha256,
                 original_duration_seconds, original_width, original_height)
                VALUES (%s, 'tiktok', 'mandala.auto.kediri', %s, 'ORIGINAL_READY',
                        %s, %s, %s, %s, %s, %s)''',
                         (self.source_key, self.video_id, str(self.video),
                          self.video.stat().st_size, self.sha256,
                          self.media['duration_sec'], self.media['width'],
                          self.media['height']))
        self.store = EditingStore(self.edit_dsn, output_root=self.output_root)
        self.admission = SourceAdmission(self.source_dsn, self.store,
                                         storage_root=self.source_root)
        self.service = EditingService(
            store=self.store, admission=self.admission,
            workflow_token=self.workflow_token, operator_token=self.operator_token,
            proof_path=self.proof, runtime_check=lambda: True,
            proof_check=lambda path: None if path.is_file() else (_ for _ in ()).throw(OSError()),
            executor=TestOnlyMockExecutor())
        self.server = create_server(self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.admission_body = {'contract_version': 'stage6.3.5-v1',
                               'source_key': self.source_key,
                               'expected_sha256': self.sha256}

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, *, key=None, workflow=True,
                operator=False, content_type='application/json', token_override=None):
        headers = {}
        if workflow:
            headers['Authorization'] = 'Bearer ' + (token_override or self.workflow_token)
        if operator:
            headers['X-Operator-Token'] = self.operator_token
        if key:
            headers['Idempotency-Key'] = key
        if body is not None:
            headers['Content-Type'] = content_type
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
        else:
            data = None
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.load(error)
            finally:
                error.close()

    def admit_approve_queue(self):
        status, body = self.request('POST', '/v1/jobs', self.admission_body,
                                    key='admit-' + self.video_id)
        self.assertEqual(status, 201)
        job = body['job']
        status, body = self.request('POST', f'/v1/jobs/{job["id"]}/approve-inference',
                                    {'decision': 'approve_paid_inference',
                                     'human_reviewed': True}, operator=True)
        self.assertEqual(status, 200)
        job = body['job']
        action = job['next_action']
        task_body = {'contract_version': 'stage6.3.5-v1',
                     'expected_job_version': job['version'],
                     'phase': action['phase'], 'attempt': action['attempt'],
                     'input_artifact_ids': action['input_artifact_ids']}
        status, body = self.request('POST', f'/v1/jobs/{job["id"]}/roles/analyst',
                                    task_body, key='task-' + self.video_id)
        self.assertEqual(status, 202)
        return job, body['task'], task_body

    def test_auth_validation_and_secret_free_errors(self):
        self.assertEqual(self.request('GET', '/health', workflow=False)[0], 200)
        self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 200)
        self.assertEqual(self.request('GET', '/v1/jobs/' + str(uuid.uuid4()),
                                      workflow=False)[0], 401)
        self.assertEqual(self.request('GET', '/v1/jobs/' + str(uuid.uuid4()),
                                      token_override='wrong-token-' * 4)[0], 401)
        status, error = self.request('POST', '/v1/jobs', self.admission_body,
                                     workflow=False, key='missing')
        self.assertEqual(status, 401)
        self.assertNotIn(self.workflow_token, json.dumps(error))
        self.assertNotIn(self.operator_token, json.dumps(error))
        self.assertEqual(self.request('POST', '/v1/jobs', b'{' + b'x' * 65536,
                                      key='large')[0], 413)
        self.assertEqual(self.request('POST', '/v1/jobs', self.admission_body,
                                      key='type', content_type='text/plain')[0], 415)
        self.assertEqual(self.request('POST', '/v1/jobs', b'{"x":1,"x":2}',
                                      key='duplicate')[0], 422)
        self.assertEqual(self.request('POST', '/v1/jobs', {**self.admission_body,
                                      'extra': 1}, key='extra')[0], 422)

    def test_admission_approval_operator_and_safe_gets(self):
        status, body = self.request('POST', '/v1/jobs', self.admission_body,
                                    key='admit-' + self.video_id)
        self.assertEqual(status, 201)
        job = body['job']
        self.assertEqual(job['state'], 'AWAITING_INFERENCE_APPROVAL')
        self.assertNotIn('original_path', json.dumps(body))
        self.assertFalse(job['production_eligible'])
        replay = self.request('POST', '/v1/jobs', self.admission_body,
                              key='admit-' + self.video_id)
        self.assertEqual(replay[1]['job']['id'], job['id'])
        self.assertEqual(self.request('POST', '/v1/jobs', self.admission_body,
                                      key='other-' + self.video_id)[0], 409)
        approval = {'decision': 'approve_paid_inference', 'human_reviewed': True}
        path = f'/v1/jobs/{job["id"]}/approve-inference'
        self.assertEqual(self.request('POST', path, approval)[0], 401)
        self.assertEqual(self.request('POST', path, {**approval, 'human_reviewed': 1},
                                      operator=True)[0], 422)
        self.assertEqual(self.request('POST', path, approval, operator=True)[0], 200)
        self.assertEqual(self.request('POST', path, approval, operator=True)[0], 200)
        self.assertEqual(self.request('GET', f'/v1/jobs/{job["id"]}')[1]['job']['version'], 2)
        self.assertEqual(self.request('GET', f'/v1/jobs/{job["id"]}/artifacts')[1],
                         {'artifacts': []})
        with psycopg.connect(self.edit_dsn) as conn:
            self.assertEqual(conn.execute('''SELECT count(*) FROM mandala_engine.job_events
                WHERE job_id = %s AND kind = 'PAID_INFERENCE_APPROVED' ''',
                (job['id'],)).fetchone()[0], 1)

    def test_auth_uses_constant_time_digest_comparison(self):
        with patch('backend.editing_api.hmac.compare_digest', wraps=hmac.compare_digest) as compare:
            self.assertEqual(self.request('GET', '/v1/jobs/' + str(uuid.uuid4()))[0], 404)
            self.assertGreaterEqual(compare.call_count, 1)
            self.assertTrue(all(len(call.args[0]) == len(call.args[1]) == 32
                                for call in compare.call_args_list))

    def test_concurrent_submission_and_idempotency_replay(self):
        job, task, body = self.admit_approve_queue()
        path = f'/v1/jobs/{job["id"]}/roles/analyst'
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.request('POST', path, body,
                                                           key='task-' + self.video_id), range(6)))
        self.assertTrue(all(status == 202 and item['task']['id'] == task['id']
                            for status, item in results))
        self.assertEqual(self.request('POST', path, body,
                                      key='another-task-' + self.video_id)[0], 409)
        self.assertEqual(self.request('GET', f'/v1/tasks/{task["id"]}')[1]['task']['state'],
                         'QUEUED')
        self.assertEqual(self.request('GET', '/v1/tasks/not-a-uuid')[0], 404)

    def test_mock_dispatch_and_worker_restart(self):
        job, task, _ = self.admit_approve_queue()
        first = Dispatcher(self.store, self.admission, executor=self.service.executor,
                           ready=self.service.ready, worker_id='mock-worker-1')
        self.assertEqual(first.run_once(), uuid.UUID(task['id']))
        task_state = self.request('GET', f'/v1/tasks/{task["id"]}')[1]['task']
        self.assertEqual(task_state['state'], 'BLOCKED')
        self.assertEqual(task_state['failure_class'], 'TEST_ONLY_MOCK_ROLE')
        current = self.request('GET', f'/v1/jobs/{job["id"]}')[1]['job']
        self.assertEqual(current['next_action']['role'], 'revision-controller')
        action = current['next_action']
        controller = {'contract_version': 'stage6.3.5-v1',
                      'expected_job_version': current['version'],
                      'phase': action['phase'], 'attempt': action['attempt'],
                      'input_artifact_ids': action['input_artifact_ids']}
        status, body = self.request('POST', f'/v1/jobs/{job["id"]}/roles/revision-controller',
                                    controller, key='controller-' + self.video_id)
        self.assertEqual(status, 202)
        second = Dispatcher(self.store, self.admission, executor=self.service.executor,
                            ready=self.service.ready, worker_id='mock-worker-2')
        second.run_once()
        self.assertEqual(self.request('GET', f'/v1/tasks/{body["task"]["id"]}')[1]['task']['state'],
                         'BLOCKED')
        self.assertEqual(self.request('GET', f'/v1/jobs/{job["id"]}')[1]['job']['state'],
                         'BLOCKED')

    def test_background_dispatcher_consumes_queue_asynchronously(self):
        _, task, _ = self.admit_approve_queue()
        background = create_server(self.service, start_dispatcher=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self.store.get_task(task['id'])['state'] == 'BLOCKED':
                    break
                time.sleep(0.05)
            self.assertEqual(self.store.get_task(task['id'])['state'], 'BLOCKED')
        finally:
            background.dispatcher.stop.set()
            background.dispatch_thread.join(timeout=5)
            background.server_close()

    def test_expired_lease_recovered_by_new_worker(self):
        job, task, _ = self.admit_approve_queue()
        old = self.store.claim_task('old-worker')
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''UPDATE mandala_engine.tasks SET
                lease_until = clock_timestamp() - interval '1 second' WHERE id = %s''',
                (task['id'],))
        new = Dispatcher(self.store, self.admission, executor=self.service.executor,
                         ready=self.service.ready, worker_id='new-worker')
        new.run_once()
        current = self.store.get_task(task['id'])
        self.assertEqual(current['lease_epoch'], old['lease_epoch'] + 1)
        self.assertEqual(current['state'], 'BLOCKED')
        self.assertEqual(self.store.get_job(job['id'])['state'], 'AWAITING_DISPATCH')

    def test_source_mutation_blocks_effect(self):
        job, task, _ = self.admit_approve_queue()
        self.video.write_bytes(self.video.read_bytes() + b'changed')
        worker = Dispatcher(self.store, self.admission, executor=self.service.executor,
                            ready=self.service.ready)
        worker.run_once()
        current = self.store.get_task(task['id'])
        self.assertEqual(current['state'], 'RECONCILIATION_REQUIRED')
        self.assertEqual(current['failure_class'], 'SOURCE_CHANGED')
        self.assertFalse(current['effect_started'])
        self.assertEqual(self.store.get_job(job['id'])['state'], 'RECONCILIATION_REQUIRED')

    def test_orphan_file_quarantines_before_claim(self):
        job, task, _ = self.admit_approve_queue()
        directory = self.output_root / job['id']
        directory.mkdir()
        (directory / 'unregistered.txt').write_text('TEST_ONLY orphan')
        worker = Dispatcher(self.store, self.admission, executor=self.service.executor,
                            ready=self.service.ready)
        worker.run_once()
        self.assertEqual(self.store.get_task(task['id'])['state'], 'RECONCILIATION_REQUIRED')
        self.assertEqual(self.store.get_task(task['id'])['lease_epoch'], 0)
        self.assertEqual(self.store.get_job(job['id'])['state'], 'RECONCILIATION_REQUIRED')

    def test_mismatched_manifest_quarantines_before_claim(self):
        job, task, _ = self.admit_approve_queue()
        directory = self.output_root / job['id']
        directory.mkdir()
        (directory / 'manifest.txt').write_text('TEST_ONLY changed bytes')
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''INSERT INTO mandala_engine.artifacts
                (id, job_id, task_id, kind, relative_path, sha256, byte_count)
                VALUES (%s, %s, %s, 'TEST_ONLY', %s, %s, %s)''',
                         (uuid.uuid4(), job['id'], task['id'],
                          job['id'] + '/manifest.txt', '0' * 64,
                          (directory / 'manifest.txt').stat().st_size))
        worker = Dispatcher(self.store, self.admission, executor=self.service.executor,
                            ready=self.service.ready)
        worker.run_once()
        self.assertEqual(self.store.get_task(task['id'])['state'], 'RECONCILIATION_REQUIRED')

    def test_incomplete_effect_on_restart_is_not_retried(self):
        job, task, _ = self.admit_approve_queue()
        old = self.store.claim_task('old-worker')
        self.store.mark_effect_started(task['id'], 'old-worker', old['lease_epoch'])
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''UPDATE mandala_engine.tasks SET
                lease_until = clock_timestamp() - interval '1 second' WHERE id = %s''',
                (task['id'],))
        restarted = Dispatcher(self.store, self.admission, executor=self.service.executor,
                               ready=self.service.ready, worker_id='new-worker')
        restarted.run_once()
        self.assertEqual(self.store.get_task(task['id'])['state'], 'RECONCILIATION_REQUIRED')
        self.assertEqual(self.store.get_job(job['id'])['state'], 'RECONCILIATION_REQUIRED')

    def test_separate_worker_process_crash_recovers_conservatively(self):
        job, task, _ = self.admit_approve_queue()
        script = (
            'import os; from backend.editing_store import EditingStore; '
            's=EditingStore(os.environ["TEST_EDIT_DSN"], '
            'output_root=os.environ["TEST_OUTPUT_ROOT"]); '
            't=s.claim_task("crashed-process"); '
            's.mark_effect_started(t["id"], "crashed-process", t["lease_epoch"]); '
            'os._exit(0)'
        )
        env = {**os.environ, 'TEST_EDIT_DSN': self.edit_dsn,
               'TEST_OUTPUT_ROOT': str(self.output_root)}
        subprocess.run([sys.executable, '-c', script], env=env, check=True,
                       capture_output=True, timeout=15)
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''UPDATE mandala_engine.tasks SET
                lease_until = clock_timestamp() - interval '1 second' WHERE id = %s''',
                (task['id'],))
        restarted = Dispatcher(self.store, self.admission, executor=self.service.executor,
                               ready=self.service.ready, worker_id='restart-process')
        restarted.run_once()
        self.assertEqual(self.store.get_task(task['id'])['state'], 'RECONCILIATION_REQUIRED')
        self.assertEqual(self.store.get_job(job['id'])['state'], 'RECONCILIATION_REQUIRED')

    def test_readiness_fails_closed(self):
        self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 200)
        with patch.object(self.service, 'proof_check', side_effect=ValueError('bad proof')):
            self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 503)
            self.assertEqual(self.request('POST', '/v1/jobs', self.admission_body,
                                          key='blocked')[0], 503)
        with patch('backend.editing_api.migration_ready', return_value=False):
            self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 503)
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute(sql.SQL('GRANT UPDATE ON public.source_videos TO {}').format(
                sql.Identifier(self.source_role)))
        try:
            self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 503)
        finally:
            with psycopg.connect(self.admin_dsn) as conn:
                conn.execute(sql.SQL('REVOKE UPDATE ON public.source_videos FROM {}').format(
                    sql.Identifier(self.source_role)))
        self.service.runtime_check = lambda: False
        self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 503)
        self.assertEqual(self.request('GET', '/health', workflow=False)[0], 200)
        self.service.runtime_check = lambda: True
        self.service.executor = None
        self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 503)
        self.service.executor = TestOnlyMockExecutor()
        self.service.operator_token = self.workflow_token
        self.assertEqual(self.request('GET', '/health/ready', workflow=False)[0], 503)

    def test_nine_role_contract_excludes_provider_calls(self):
        self.assertEqual(len(ROLE_PHASES), 9)
        self.assertEqual(ROLE_PHASES['reviewer'],
                         frozenset({'source_speech', 'edited_output'}))
        for role, phases in ROLE_PHASES.items():
            for phase in phases:
                attempt = 0 if role in ('analyst', 'av-evidence', 'speech-asr',
                                        'revision-controller') or phase == 'source_speech' else 1
                body = {'contract_version': 'stage6.3.5-v1',
                        'expected_job_version': 2, 'phase': phase,
                        'attempt': attempt, 'input_artifact_ids': []}
                Handler._role_body(None, body, role)
                with self.assertRaises(ApiError):
                    Handler._role_body(None, {**body, 'attempt': 99}, role)
        self.assertIsInstance(self.service.executor, TestOnlyMockExecutor)
        self.assertIsNone(EditingService.from_env().executor)


if __name__ == '__main__':
    unittest.main()
