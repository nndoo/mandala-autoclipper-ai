"""PostgreSQL 16 only: isolated TEST_ONLY admission and durable state checks.

Set MANDALA_STAGE635_TEST_ADMIN_DSN to an isolated local test database.
No production DSN, provider credential, or historical media is used.
"""

import concurrent.futures
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from backend.editing_store import MIGRATION, Conflict, EditingStore, Fenced, apply_migration
from backend.media_worker.intake_adapter import IntakeError, MAX_POC_BYTES, stage5
from backend import source_admission as admission_module
from backend.source_admission import SourceAdmission


class Stage635PostgresTests(unittest.TestCase):
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
        cls.version = version
        cls.first_migration = apply_migration(cls.admin_dsn)
        cls.temp = tempfile.TemporaryDirectory(prefix='mandala-stage635-test-only-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.source_root = cls.root / 'source'
        (cls.source_root / 'originals').mkdir(parents=True)
        cls.output_root = cls.root / 'editing-output'
        cls.output_root.mkdir()
        cls.master = cls.root / 'synthetic.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x480:rate=30',
                        '-t', '1.2', '-c:v', 'mpeg4', '-q:v', '10', str(cls.master)],
                       check=True, timeout=30)
        cls.media = stage5.probe_video(cls.master)
        cls.sha256 = hashlib.sha256(cls.master.read_bytes()).hexdigest()
        cls.counter = 0
        cls.source_role = 'stage635_source_' + uuid.uuid4().hex[:8]
        cls.edit_role = 'stage635_edit_' + uuid.uuid4().hex[:8]
        source_password, edit_password = uuid.uuid4().hex, uuid.uuid4().hex
        with psycopg.connect(cls.admin_dsn) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS public.source_videos (
                source_key text PRIMARY KEY, platform text NOT NULL,
                username text NOT NULL, video_id text NOT NULL, status text NOT NULL,
                original_local_path text NOT NULL, original_size_bytes bigint NOT NULL,
                original_sha256 text NOT NULL, original_duration_seconds numeric NOT NULL,
                original_width integer NOT NULL, original_height integer NOT NULL
            )''')
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(cls.source_role), sql.Literal(source_password)))
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(cls.edit_role), sql.Literal(edit_password)))
            for role in (cls.source_role, cls.edit_role):
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

    def setUp(self):
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''TRUNCATE mandala_engine.idempotency_keys,
                mandala_engine.job_events, mandala_engine.permits,
                mandala_engine.artifacts, mandala_engine.call_reservations,
                mandala_engine.tasks, mandala_engine.jobs RESTART IDENTITY CASCADE''')
            conn.execute('TRUNCATE public.source_videos')
        type(self).counter += 1
        self.video_id = str(9000000000000000000 + self.counter)
        self.source_key = f'tiktok:{self.video_id}'
        self.video = self.source_root / 'originals' / f'{self.video_id}.mp4'
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
        self.admitter = SourceAdmission(self.source_dsn, self.store,
                                        storage_root=self.source_root)
        self.request = {'contract_version': 'stage6.3.5-v1',
                        'source_key': self.source_key,
                        'expected_sha256': self.sha256}

    def admit(self, key=None):
        return self.admitter.admit(self.request, principal='workflow',
                                  key=key or 'admit-' + self.video_id)

    def approved_task(self, key=None):
        job, _ = self.admit(key)
        job = self.store.approve_paid_inference(job['id'])
        action = job['next_action']
        task, _ = self.store.submit_task(job['id'], principal='workflow',
                                         key='task-' + self.video_id,
                                         expected_version=job['version'],
                                         role=action['role'], phase=action['phase'],
                                         attempt=action['attempt'],
                                         input_artifact_ids=[])
        return job, task

    def expire(self, task_id):
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute('''UPDATE mandala_engine.tasks SET
                lease_until = clock_timestamp() - interval '1 second' WHERE id = %s''',
                         (task_id,))

    def test_migration_is_idempotent_and_scoped(self):
        self.assertFalse(apply_migration(self.admin_dsn))
        with psycopg.connect(self.admin_dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM mandala_engine.schema_migrations').fetchone()[0], 1)
            stored_checksum = conn.execute('''SELECT sha256 FROM mandala_engine.schema_migrations
                WHERE version = 1''').fetchone()[0].strip()
            names = {row[0] for row in conn.execute('''SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'mandala_engine' ''')}
        self.assertEqual(stored_checksum, hashlib.sha256(MIGRATION.read_bytes()).hexdigest())
        self.assertEqual(names, {'jobs', 'tasks', 'call_reservations', 'artifacts',
                                 'permits', 'job_events', 'schema_migrations',
                                 'idempotency_keys'})

    def test_source_role_is_select_only_and_edit_role_cannot_write_public(self):
        with psycopg.connect(self.source_dsn) as conn:
            rights = conn.execute('''SELECT
                has_table_privilege(current_user, 'public.source_videos', 'SELECT'),
                has_table_privilege(current_user, 'public.source_videos', 'UPDATE')''').fetchone()
            self.assertEqual(rights, (True, False))
            self.assertEqual(conn.execute('SELECT status FROM public.source_videos WHERE source_key = %s',
                                          (self.source_key,)).fetchone()[0], 'ORIGINAL_READY')
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("UPDATE public.source_videos SET status='BAD' WHERE source_key = %s",
                             (self.source_key,))
        with psycopg.connect(self.edit_dsn) as conn:
            self.assertFalse(conn.execute('''SELECT has_table_privilege(
                current_user, 'public.source_videos', 'UPDATE')''').fetchone()[0])

    def test_original_ready_sha_probe_and_snapshot(self):
        before = hashlib.sha256(self.video.read_bytes()).hexdigest()
        job, replay = self.admit()
        self.assertFalse(replay)
        self.assertEqual(job['state'], 'AWAITING_INFERENCE_APPROVAL')
        self.assertEqual(job['version'], 1)
        self.assertEqual(job['source_sha256'].strip(), before)
        self.assertEqual(job['source_snapshot']['source']['fps'], self.media['fps'])
        self.assertEqual(job['source_snapshot']['source']['video_id'],
                         'local-sha256-' + before[:32])
        self.assertEqual(hashlib.sha256(self.video.read_bytes()).hexdigest(), before)
        self.assertFalse(job['human_verified'])
        self.assertFalse(job['production_eligible'])
        with psycopg.connect(self.edit_dsn) as conn:
            events = conn.execute('SELECT kind FROM mandala_engine.job_events WHERE job_id = %s',
                                  (job['id'],)).fetchall()
        self.assertEqual(events, [('SOURCE_ADMITTED',)])

    def test_duplicate_key_source_and_concurrent_admission(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.admit(), range(8)))
        self.assertEqual(len({job['id'] for job, _ in results}), 1)
        self.assertEqual(sum(not replay for _, replay in results), 1)
        job = results[0][0]
        self.assertTrue(self.admit()[1])
        with self.assertRaises(Conflict):
            self.admit('different-admission-key-' + self.video_id)
        changed = {**self.request, 'expected_sha256': '0' * 64}
        with self.assertRaises(Conflict):
            self.admitter.admit(changed, principal='workflow',
                                key='admit-' + self.video_id)
        with psycopg.connect(self.edit_dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM mandala_engine.jobs WHERE source_key = %s',
                                          (self.source_key,)).fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM mandala_engine.job_events WHERE job_id = %s',
                                          (job['id'],)).fetchone()[0], 1)

    def test_idempotency_namespace_spans_admission_and_task(self):
        job, _ = self.admit()
        job = self.store.approve_paid_inference(job['id'])
        action = job['next_action']
        with self.assertRaises(Conflict):
            self.store.submit_task(job['id'], principal='workflow',
                                   key='admit-' + self.video_id,
                                   expected_version=job['version'],
                                   role=action['role'], phase=action['phase'],
                                   attempt=action['attempt'], input_artifact_ids=[])
        self.assertEqual(self.store.get_job(job['id'])['state'], 'AWAITING_DISPATCH')

    def test_different_keys_racing_same_source_admit_once(self):
        def call(i):
            try:
                return self.admit(f'competing-{self.video_id}-{i}')[0]['id']
            except Conflict:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(call, range(6)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_invalid_source_rejected_without_job(self):
        cases = [
            ('status', 'RESERVED'),
            ('original_sha256', '0' * 64),
            ('original_size_bytes', self.video.stat().st_size + 1),
            ('original_size_bytes', MAX_POC_BYTES + 1),
            ('original_duration_seconds', 181),
            ('original_width', 321),
            ('original_local_path', '/tmp/not-the-original.mp4'),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=str(value)[:16]):
                with psycopg.connect(self.admin_dsn) as conn:
                    old = conn.execute(sql.SQL('SELECT {} FROM public.source_videos '
                                               'WHERE source_key = %s').format(
                        sql.Identifier(field)), (self.source_key,)).fetchone()[0]
                    conn.execute(sql.SQL('UPDATE public.source_videos SET {} = %s '
                                         'WHERE source_key = %s').format(sql.Identifier(field)),
                                 (value, self.source_key))
                with self.assertRaises((IntakeError, Conflict)):
                    self.admit()
                with psycopg.connect(self.admin_dsn) as conn:
                    conn.execute(sql.SQL('UPDATE public.source_videos SET {} = %s '
                                         'WHERE source_key = %s').format(sql.Identifier(field)),
                                 (old, self.source_key))
        with psycopg.connect(self.edit_dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM mandala_engine.jobs WHERE source_key = %s',
                                          (self.source_key,)).fetchone()[0], 0)

    def test_mutated_original_bytes_are_not_admitted(self):
        data = bytearray(self.video.read_bytes())
        data[-1] ^= 1
        self.video.write_bytes(data)
        self.assertEqual(self.video.stat().st_size, self.master.stat().st_size)
        with self.assertRaises(IntakeError):
            self.admit()
        with psycopg.connect(self.edit_dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM mandala_engine.jobs').fetchone()[0], 0)

    def test_source_row_changed_during_admission_is_rejected(self):
        original_prepare = admission_module.prepare_intake

        def change_after_verification(record, *, storage_root):
            intake = original_prepare(record, storage_root=storage_root)
            with psycopg.connect(self.admin_dsn) as conn:
                conn.execute('''UPDATE public.source_videos SET status = 'RESERVED'
                    WHERE source_key = %s''', (self.source_key,))
            return intake

        with patch.object(admission_module, 'prepare_intake', change_after_verification):
            with self.assertRaises(Conflict):
                self.admit()
        with psycopg.connect(self.edit_dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM mandala_engine.jobs').fetchone()[0], 0)

    def test_approval_task_idempotency_version_and_fencing(self):
        job, task = self.approved_task()
        self.assertEqual(task['state'], 'QUEUED')
        action = {'role': 'analyst', 'phase': 'analyze', 'attempt': 0,
                  'input_artifact_ids': []}
        same, replay = self.store.submit_task(job['id'], principal='workflow',
                                               key='task-' + self.video_id,
                                               expected_version=job['version'], **action)
        self.assertTrue(replay)
        self.assertEqual(same['id'], task['id'])
        with self.assertRaises(Conflict):
            self.store.submit_task(job['id'], principal='workflow',
                                   key='another-task-' + self.video_id,
                                   expected_version=job['version'], **action)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(self.store.claim_task, ['worker-a', 'worker-b']))
        claimed = next(value for value in claims if value)
        self.assertEqual(sum(value is not None for value in claims), 1)
        self.store.heartbeat(task['id'], claimed['lease_owner'], claimed['lease_epoch'])
        self.store.finish_task(task['id'], claimed['lease_owner'], claimed['lease_epoch'],
                               state='SUCCEEDED')
        final_job = self.store.get_job(job['id'])
        self.assertEqual(final_job['state'], 'AWAITING_DISPATCH')
        self.assertEqual(final_job['next_action']['role'], 'revision-controller')
        with self.assertRaises(Fenced):
            self.store.finish_task(task['id'], claimed['lease_owner'],
                                   claimed['lease_epoch'], state='SUCCEEDED')

    def test_expired_effect_free_task_requeues_with_new_epoch(self):
        job, task = self.approved_task()
        first = self.store.claim_task('worker-a')
        self.expire(task['id'])
        self.assertEqual(self.store.recover_expired(), [(task['id'], 'QUEUED')])
        second = self.store.claim_task('worker-b')
        self.assertEqual(second['lease_epoch'], first['lease_epoch'] + 1)
        with self.assertRaises(Fenced):
            self.store.mark_effect_started(task['id'], 'worker-a', first['lease_epoch'])
        self.store.finish_task(task['id'], 'worker-b', second['lease_epoch'],
                               state='SUCCEEDED')
        self.assertEqual(self.store.get_job(job['id'])['next_action']['role'],
                         'revision-controller')

    def test_expired_task_with_effect_marker_requires_reconciliation(self):
        job, task = self.approved_task()
        claimed = self.store.claim_task('worker-a')
        self.store.mark_effect_started(task['id'], 'worker-a', claimed['lease_epoch'])
        self.expire(task['id'])
        self.assertEqual(self.store.recover_expired(),
                         [(task['id'], 'RECONCILIATION_REQUIRED')])
        self.assertEqual(self.store.get_job(job['id'])['state'], 'RECONCILIATION_REQUIRED')

    def test_unresolved_reservation_cannot_finish_task(self):
        job, task = self.approved_task()
        claimed = self.store.claim_task('worker-a')
        reservation = self.store.reserve_call(task['id'], 'worker-a',
                                              claimed['lease_epoch'], kind='analyst',
                                              attempt=1, request_sha256='a' * 64)
        with self.assertRaises(Conflict):
            self.store.finish_task(task['id'], 'worker-a', claimed['lease_epoch'],
                                   state='SUCCEEDED')
        self.store.mark_call_sent(reservation, 'worker-a', claimed['lease_epoch'])
        with self.assertRaises(Conflict):
            self.store.finish_task(task['id'], 'worker-a', claimed['lease_epoch'],
                                   state='SUCCEEDED')
        self.store.record_call_outcome(reservation, 'worker-a', claimed['lease_epoch'],
                                       known=False, outcome={'status': 'unknown'})
        with self.assertRaises(Conflict):
            self.store.finish_task(task['id'], 'worker-a', claimed['lease_epoch'],
                                   state='SUCCEEDED')
        self.store.finish_task(task['id'], 'worker-a', claimed['lease_epoch'],
                               state='RECONCILIATION_REQUIRED')
        self.assertEqual(self.store.get_job(job['id'])['state'], 'RECONCILIATION_REQUIRED')

    def test_reserved_but_unsent_call_expiry_is_not_retried(self):
        job, task = self.approved_task()
        claimed = self.store.claim_task('crashed-before-send')
        reservation = self.store.reserve_call(
            task['id'], 'crashed-before-send', claimed['lease_epoch'],
            kind='analyst', attempt=1, request_sha256='a' * 64)
        self.expire(task['id'])
        self.assertEqual(self.store.recover_expired(),
                         [(task['id'], 'RECONCILIATION_REQUIRED')])
        self.assertEqual(self.store.get_job(job['id'])['state'],
                         'RECONCILIATION_REQUIRED')
        self.assertIsNone(self.store.claim_task('replacement-worker'))
        with psycopg.connect(self.edit_dsn) as conn:
            state = conn.execute(
                'SELECT state FROM mandala_engine.call_reservations WHERE id = %s',
                (reservation,)).fetchone()[0]
        self.assertEqual(state, 'OUTCOME_UNKNOWN')

    def test_reserved_paid_call_spends_budget_and_expiry_quarantines(self):
        job, task = self.approved_task()
        claimed = self.store.claim_task('worker-a')
        reservation = self.store.reserve_call(task['id'], 'worker-a',
                                              claimed['lease_epoch'], kind='analyst',
                                              attempt=1, request_sha256='a' * 64)
        with self.assertRaises(Conflict):
            self.store.reserve_call(task['id'], 'worker-a', claimed['lease_epoch'],
                                    kind='analyst', attempt=2, request_sha256='b' * 64)
        self.store.mark_call_sent(reservation, 'worker-a', claimed['lease_epoch'])
        self.expire(task['id'])
        self.assertEqual(self.store.recover_expired(),
                         [(task['id'], 'RECONCILIATION_REQUIRED')])
        self.assertEqual(self.store.get_job(job['id'])['state'], 'RECONCILIATION_REQUIRED')
        self.assertIsNone(self.store.claim_task('worker-b'))
        with psycopg.connect(self.edit_dsn) as conn:
            state = conn.execute('SELECT state FROM mandala_engine.call_reservations WHERE id = %s',
                                 (reservation,)).fetchone()[0]
        self.assertEqual(state, 'OUTCOME_UNKNOWN')
        with self.assertRaises(Fenced):
            self.store.record_call_outcome(reservation, 'worker-a',
                                           claimed['lease_epoch'], known=True,
                                           outcome={'status': 'late'})

    def test_artifact_manifest_hash_path_and_immutability(self):
        job, task = self.approved_task()
        claimed = self.store.claim_task('worker-a')
        relative = f'{job["id"]}/test-only.txt'
        path = self.output_root / relative
        path.parent.mkdir()
        path.write_text('TEST_ONLY synthetic artifact')
        artifact, replay = self.store.register_artifact(
            job['id'], relative, kind='TEST_ONLY', task_id=task['id'],
            worker_id='worker-a', epoch=claimed['lease_epoch'])
        self.assertFalse(replay)
        self.assertEqual(artifact['sha256'].strip(), hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(self.store.register_artifact(
            job['id'], relative, kind='TEST_ONLY', task_id=task['id'],
            worker_id='worker-a', epoch=claimed['lease_epoch'])[1])
        for unsafe in ('../outside.txt', f'{job["id"]}//test-only.txt'):
            with self.assertRaises(ValueError):
                self.store.register_artifact(job['id'], unsafe, kind='TEST_ONLY')
        link = path.parent / 'link.txt'
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            self.store.register_artifact(job['id'], f'{job["id"]}/link.txt',
                                         kind='TEST_ONLY')
        path.write_text('TEST_ONLY changed artifact')
        with self.assertRaises(Conflict):
            self.store.register_artifact(job['id'], relative, kind='TEST_ONLY',
                                         task_id=task['id'], worker_id='worker-a',
                                         epoch=claimed['lease_epoch'])

    def test_private_permit_consumes_once_and_is_fenced(self):
        job, analyst = self.approved_task()
        claimed = self.store.claim_task('worker-a')
        self.store.finish_task(analyst['id'], 'worker-a', claimed['lease_epoch'],
                               state='SUCCEEDED')
        job = self.store.get_job(job['id'])
        controller, _ = self.store.submit_task(
            job['id'], principal='workflow', key='controller-' + self.video_id,
            expected_version=job['version'], role='revision-controller',
            phase='decide', attempt=0, input_artifact_ids=[])
        claimed = self.store.claim_task('worker-a')
        self.store.finish_task(controller['id'], 'worker-a', claimed['lease_epoch'],
                               state='SUCCEEDED', next_action={
                                   'role': 'renderer', 'phase': 'encode', 'attempt': 1,
                                   'input_artifact_ids': []})
        job = self.store.get_job(job['id'])
        renderer, _ = self.store.submit_task(
            job['id'], principal='workflow', key='renderer-' + self.video_id,
            expected_version=job['version'], role='renderer', phase='encode',
            attempt=1, input_artifact_ids=[])
        claimed = self.store.claim_task('worker-a')
        permit = self.store.issue_permit(renderer['id'], 'worker-a', claimed['lease_epoch'],
                                         attempt=1, proposal_sha256='a' * 64,
                                         execution_sha256='b' * 64,
                                         request_sha256='c' * 64)
        with self.assertRaises(Conflict):
            self.store.issue_permit(renderer['id'], 'worker-a', claimed['lease_epoch'],
                                    attempt=1, proposal_sha256='a' * 64,
                                    execution_sha256='b' * 64,
                                    request_sha256='c' * 64)
        self.store.consume_permit(permit, 'worker-a', claimed['lease_epoch'])
        with self.assertRaises(Conflict):
            self.store.consume_permit(permit, 'worker-a', claimed['lease_epoch'])
        self.expire(renderer['id'])
        self.assertEqual(self.store.recover_expired(),
                         [(renderer['id'], 'RECONCILIATION_REQUIRED')])
        with psycopg.connect(self.edit_dsn) as conn:
            row = conn.execute('SELECT scope, consumed_at FROM mandala_engine.permits WHERE id = %s',
                               (permit,)).fetchone()
        self.assertEqual(row[0], 'STAGE59_PRIVATE_PREVIEW')
        self.assertIsNotNone(row[1])


if __name__ == '__main__':
    unittest.main()
