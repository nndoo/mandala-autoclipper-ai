"""Stage 6.3.5 durable editing state; no HTTP routes or model invocation."""

import hashlib
import json
import re
import stat
import uuid
from pathlib import Path, PurePosixPath

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


MIGRATION = Path(__file__).resolve().parent / 'migrations/001_editing_jobs.sql'
JOB_TERMINAL = frozenset({
    'AUTO_PREVIEW_COMPLETED', 'AUTO_PREVIEW_COMPLETED_WITH_NOTES',
    'BLOCKED', 'FAILED', 'RECONCILIATION_REQUIRED',
})
TASK_TERMINAL = frozenset({'SUCCEEDED', 'BLOCKED', 'FAILED', 'RECONCILIATION_REQUIRED'})
CALL_LIMITS = {'analyst': 1, 'director': 3, 'speech_asr': 2,
               'reviewer_source': 2, 'reviewer_edited': 1}
CALL_ROLES = {'analyst': ('analyst', 'analyze'),
              'director': ('director', 'propose'),
              'speech_asr': ('speech-asr', 'transcribe'),
              'reviewer_source': ('reviewer', 'source_speech'),
              'reviewer_edited': ('reviewer', 'edited_output')}
HEX = re.compile(r'[0-9a-f]{64}\Z')
KEY = re.compile(r'[A-Za-z0-9._:-]{1,128}\Z')


class Conflict(ValueError):
    """A duplicate, stale version, exhausted budget, or invalid transition."""


class Fenced(Conflict):
    """The lease owner/epoch cannot make a durable change."""


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _uuid(value):
    return uuid.UUID(str(value))


def _event(cur, job_id, version, kind, *, task_id=None, detail=None):
    cur.execute('''INSERT INTO mandala_engine.job_events
        (job_id, task_id, job_version, kind, detail) VALUES (%s, %s, %s, %s, %s)''',
                (job_id, task_id, version, kind, Jsonb(detail or {})))


def apply_migration(dsn):
    """Apply one reviewed SQL file atomically, refusing a changed version."""
    source = MIGRATION.read_bytes()
    checksum = hashlib.sha256(source).hexdigest()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(635, 1)')
            cur.execute("SELECT to_regclass('mandala_engine.schema_migrations')")
            if cur.fetchone()[0] is not None:
                cur.execute('SELECT sha256 FROM mandala_engine.schema_migrations WHERE version = 1')
                row = cur.fetchone()
                if row:
                    if row[0].strip() != checksum:
                        raise Conflict('Migration version 1 checksum changed')
                    return False
            cur.execute(source.decode('utf-8'))
            cur.execute('''INSERT INTO mandala_engine.schema_migrations
                (version, sha256) VALUES (1, %s)''', (checksum,))
    return True


def migration_ready(dsn):
    """Read-only checksum gate; service startup never applies a migration."""
    expected = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        row = conn.execute('''SELECT sha256 FROM mandala_engine.schema_migrations
            WHERE version = 1''').fetchone()
        tables = conn.execute('''SELECT
            to_regclass('mandala_engine.jobs'),
            to_regclass('mandala_engine.tasks'),
            to_regclass('mandala_engine.call_reservations'),
            to_regclass('mandala_engine.artifacts'),
            to_regclass('mandala_engine.permits'),
            to_regclass('mandala_engine.job_events'),
            to_regclass('mandala_engine.schema_migrations'),
            to_regclass('mandala_engine.idempotency_keys')''').fetchone()
    return row is not None and row[0].strip() == expected and all(tables)


class EditingStore:
    def __init__(self, dsn, *, output_root):
        self.dsn = dsn
        self.output_root = Path(output_root)

    def connect(self):
        return psycopg.connect(self.dsn, connect_timeout=5, row_factory=dict_row)

    @staticmethod
    def _key(principal, key):
        if not isinstance(principal, str) or not KEY.fullmatch(principal):
            raise ValueError('Invalid workflow principal')
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValueError('Invalid Idempotency-Key')

    @staticmethod
    def _same_key(row, route, request_sha256):
        if row['method'] != 'POST' or row['route'] != route or row['request_sha256'].strip() != request_sha256:
            raise Conflict('Idempotency-Key conflicts with another request')
        return row

    def lookup_key(self, principal, key, route, request_sha256):
        self._key(principal, key)
        with self.connect() as conn:
            row = conn.execute('''SELECT * FROM mandala_engine.idempotency_keys
                WHERE principal = %s AND key = %s''', (principal, key)).fetchone()
        return self._same_key(row, route, request_sha256) if row else None

    def get_job(self, job_id):
        with self.connect() as conn:
            return conn.execute('SELECT * FROM mandala_engine.jobs WHERE id = %s',
                                (_uuid(job_id),)).fetchone()

    def get_task(self, task_id):
        with self.connect() as conn:
            return conn.execute('SELECT * FROM mandala_engine.tasks WHERE id = %s',
                                (_uuid(task_id),)).fetchone()

    def recovery_jobs(self):
        with self.connect() as conn:
            return conn.execute('''SELECT jobs.id, jobs.state,
                EXISTS(SELECT 1 FROM mandala_engine.tasks AS tasks
                    WHERE tasks.job_id = jobs.id AND tasks.state = 'RUNNING'
                    AND tasks.lease_until <= clock_timestamp()) AS expired
                FROM mandala_engine.jobs AS jobs
                WHERE jobs.state IN ('AWAITING_DISPATCH', 'QUEUED', 'RUNNING')''').fetchall()

    def artifact_rows(self, job_id):
        with self.connect() as conn:
            return conn.execute('''SELECT * FROM mandala_engine.artifacts
                WHERE job_id = %s''', (_uuid(job_id),)).fetchall()

    def task_rows(self, job_id):
        with self.connect() as conn:
            return conn.execute('''SELECT * FROM mandala_engine.tasks
                WHERE job_id = %s ORDER BY created_at, id''', (_uuid(job_id),)).fetchall()

    def reservation_rows(self, job_id):
        with self.connect() as conn:
            return conn.execute('''SELECT * FROM mandala_engine.call_reservations
                WHERE job_id = %s ORDER BY created_at, id''', (_uuid(job_id),)).fetchall()

    def quarantine_job(self, job_id, reason, *, expected_state=None):
        """Stop an ambiguous job without clearing its reservation history."""
        job_id = _uuid(job_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('''SELECT id FROM mandala_engine.tasks WHERE job_id = %s
                    AND state IN ('QUEUED', 'RUNNING')''', (job_id,))
                candidate = cur.fetchone()
                task = None
                if candidate:
                    cur.execute('SELECT * FROM mandala_engine.tasks WHERE id = %s FOR UPDATE',
                                (candidate['id'],))
                    task = cur.fetchone()
                    if task['state'] not in ('QUEUED', 'RUNNING'):
                        return False
                cur.execute('SELECT * FROM mandala_engine.jobs WHERE id = %s FOR UPDATE',
                            (job_id,))
                job = cur.fetchone()
                if job is None or job['state'] in JOB_TERMINAL:
                    return False
                if expected_state is not None and job['state'] != expected_state:
                    return False
                if task is not None and task['state'] == 'RUNNING':
                    cur.execute('SELECT lease_until <= clock_timestamp() AS expired '
                                'FROM mandala_engine.tasks WHERE id = %s', (task['id'],))
                    if not cur.fetchone()['expired']:
                        return False
                if task is None:
                    cur.execute('''SELECT 1 FROM mandala_engine.tasks WHERE job_id = %s
                        AND state IN ('QUEUED', 'RUNNING')''', (job_id,))
                    if cur.fetchone() is not None:
                        return False
                else:
                    cur.execute('''UPDATE mandala_engine.tasks SET
                        state = 'RECONCILIATION_REQUIRED', lease_owner = NULL,
                        lease_until = NULL, failure_class = %s,
                        updated_at = clock_timestamp() WHERE id = %s''',
                        (reason, task['id']))
                    cur.execute('''UPDATE mandala_engine.call_reservations SET
                        state = 'OUTCOME_UNKNOWN', finished_at = clock_timestamp()
                        WHERE task_id = %s AND state IN ('RESERVED', 'SENT')''',
                        (task['id'],))
                version = job['version'] + 1
                cur.execute('''UPDATE mandala_engine.jobs SET
                    state = 'RECONCILIATION_REQUIRED', next_action = NULL,
                    version = %s, updated_at = clock_timestamp() WHERE id = %s''',
                    (version, job_id))
                _event(cur, job_id, version, 'RECOVERY_RECONCILIATION_REQUIRED',
                       task_id=task['id'] if task else None,
                       detail={'reason': reason})
        return True

    def admit_verified(self, intake, *, principal, key, request_sha256):
        """Persist a source already checked by the read-only Stage 6.3.2 adapter."""
        self._key(principal, key)
        source_key = intake['source_key']
        source_sha256 = intake['metadata']['verification']['sha256']
        if not HEX.fullmatch(source_sha256):
            raise ValueError('Invalid source digest')
        route = '/v1/jobs'
        existing = self.lookup_key(principal, key, route, request_sha256)
        if existing:
            return self.get_job(existing['job_id']), True
        job_id = uuid.uuid4()
        try:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute('''INSERT INTO mandala_engine.jobs
                        (id, source_key, source_sha256, source_snapshot, state)
                        VALUES (%s, %s, %s, %s, 'AWAITING_INFERENCE_APPROVAL')
                        ON CONFLICT (source_key) DO NOTHING RETURNING id''',
                        (job_id, source_key, source_sha256, Jsonb(intake)))
                    if cur.fetchone() is None:
                        raise Conflict('Source already admitted under another key')
                    cur.execute('''INSERT INTO mandala_engine.idempotency_keys
                        (principal, key, method, route, request_sha256, response_status, job_id)
                        VALUES (%s, %s, 'POST', %s, %s, 201, %s)
                        ON CONFLICT DO NOTHING RETURNING key''',
                        (principal, key, route, request_sha256, job_id))
                    if cur.fetchone() is None:
                        raise Conflict('Idempotency-Key conflicts with another request')
                    _event(cur, job_id, 1, 'SOURCE_ADMITTED',
                           detail={'source_key': source_key, 'sha256': source_sha256})
        except Conflict:
            existing = self.lookup_key(principal, key, route, request_sha256)
            if existing:
                return self.get_job(existing['job_id']), True
            raise
        return self.get_job(job_id), False

    def approve_paid_inference(self, job_id):
        """Persistence action only; Stage C must authenticate the operator."""
        job_id = _uuid(job_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM mandala_engine.jobs WHERE id = %s FOR UPDATE', (job_id,))
                job = cur.fetchone()
                if job is None:
                    raise KeyError('Job not found')
                if job['paid_inference_approved']:
                    return job
                if job['state'] != 'AWAITING_INFERENCE_APPROVAL':
                    raise Conflict('Job cannot be approved in this state')
                version = job['version'] + 1
                action = {'role': 'analyst', 'phase': 'analyze', 'attempt': 0,
                          'input_artifact_ids': [], 'expected_job_version': version}
                cur.execute('''UPDATE mandala_engine.jobs SET
                    paid_inference_approved = true, state = 'AWAITING_DISPATCH',
                    next_action = %s, version = %s, updated_at = clock_timestamp()
                    WHERE id = %s''', (Jsonb(action), version, job_id))
                _event(cur, job_id, version, 'PAID_INFERENCE_APPROVED')
        return self.get_job(job_id)

    def submit_task(self, job_id, *, principal, key, expected_version, role,
                    phase, attempt, input_artifact_ids, regions=None):
        """Reserve one task from server-owned next_action; never run it inline."""
        self._key(principal, key)
        job_id = _uuid(job_id)
        ids = [_uuid(value) for value in input_artifact_ids]
        if len(ids) != len(set(ids)) or type(attempt) is not int:
            raise ValueError('Invalid task input')
        body = {'contract_version': 'stage6.3.5-v1',
                'expected_job_version': expected_version, 'phase': phase,
                'attempt': attempt, 'input_artifact_ids': [str(value) for value in ids]}
        if regions is not None:
            body['regions'] = regions
        route = f'/v1/jobs/{job_id}/roles/{role}'
        request_sha256 = digest(body)
        existing = self.lookup_key(principal, key, route, request_sha256)
        if existing:
            return self.get_task(existing['task_id']), True
        try:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT * FROM mandala_engine.jobs WHERE id = %s FOR UPDATE', (job_id,))
                    job = cur.fetchone()
                    if job is None:
                        raise KeyError('Job not found')
                    action = {'role': role, 'phase': phase, 'attempt': attempt,
                              'input_artifact_ids': [str(value) for value in ids],
                              'expected_job_version': expected_version}
                    if regions is not None:
                        action['regions'] = regions
                    if (job['state'] != 'AWAITING_DISPATCH' or not job['paid_inference_approved']
                            or job['version'] != expected_version or job['next_action'] != action):
                        raise Conflict('Task differs from current next_action')
                    if ids:
                        cur.execute('''SELECT count(*) AS n FROM mandala_engine.artifacts
                            WHERE job_id = %s AND id = ANY(%s)''', (job_id, ids))
                        if cur.fetchone()['n'] != len(ids):
                            raise Conflict('Task references foreign or missing artifact')
                    task_id = uuid.uuid4()
                    cur.execute('''INSERT INTO mandala_engine.tasks
                        (id, job_id, role, phase, attempt, state, input_artifact_ids)
                        VALUES (%s, %s, %s, %s, %s, 'QUEUED', %s)''',
                        (task_id, job_id, role, phase, attempt, ids))
                    cur.execute('''INSERT INTO mandala_engine.idempotency_keys
                        (principal, key, method, route, request_sha256, response_status, task_id)
                        VALUES (%s, %s, 'POST', %s, %s, 202, %s)
                        ON CONFLICT DO NOTHING RETURNING key''',
                        (principal, key, route, request_sha256, task_id))
                    if cur.fetchone() is None:
                        raise Conflict('Idempotency-Key conflicts with another request')
                    version = job['version'] + 1
                    cur.execute('''UPDATE mandala_engine.jobs SET state = 'QUEUED',
                        next_action = NULL, version = %s, updated_at = clock_timestamp()
                        WHERE id = %s''', (version, job_id))
                    _event(cur, job_id, version, 'TASK_QUEUED', task_id=task_id,
                           detail={'role': role, 'phase': phase, 'attempt': attempt})
        except (Conflict, psycopg.errors.UniqueViolation):
            existing = self.lookup_key(principal, key, route, request_sha256)
            if existing:
                return self.get_task(existing['task_id']), True
            raise Conflict('Task conflict or active task exists') from None
        return self.get_task(task_id), False

    def claim_task(self, worker_id, *, lease_seconds=60):
        if not worker_id or not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid lease claim')
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('''SELECT id, job_id FROM mandala_engine.tasks
                    WHERE state = 'QUEUED' ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED LIMIT 1''')
                task = cur.fetchone()
                if task is None:
                    return None
                cur.execute('SELECT version, state FROM mandala_engine.jobs WHERE id = %s FOR UPDATE',
                            (task['job_id'],))
                job = cur.fetchone()
                if job['state'] != 'QUEUED':
                    raise Conflict('Queued task has mismatched job state')
                cur.execute('''UPDATE mandala_engine.tasks SET state = 'RUNNING',
                    lease_epoch = lease_epoch + 1, lease_owner = %s,
                    lease_until = clock_timestamp() + make_interval(secs => %s),
                    updated_at = clock_timestamp() WHERE id = %s
                    RETURNING *''', (worker_id, lease_seconds, task['id']))
                claimed = cur.fetchone()
                version = job['version'] + 1
                cur.execute('''UPDATE mandala_engine.jobs SET state = 'RUNNING', version = %s,
                    updated_at = clock_timestamp() WHERE id = %s''',
                    (version, task['job_id']))
                _event(cur, task['job_id'], version, 'TASK_CLAIMED', task_id=task['id'],
                       detail={'lease_epoch': claimed['lease_epoch']})
                return claimed

    @staticmethod
    def _fenced_task(cur, task_id, worker_id, epoch):
        cur.execute('''SELECT * FROM mandala_engine.tasks WHERE id = %s AND state = 'RUNNING'
            AND lease_owner = %s AND lease_epoch = %s
            AND lease_until > clock_timestamp() FOR UPDATE''',
                    (_uuid(task_id), worker_id, epoch))
        task = cur.fetchone()
        if task is None:
            raise Fenced('Task lease is stale or expired')
        return task

    def heartbeat(self, task_id, worker_id, epoch, *, lease_seconds=60):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid lease duration')
        with self.connect() as conn:
            with conn.cursor() as cur:
                self._fenced_task(cur, task_id, worker_id, epoch)
                cur.execute('''UPDATE mandala_engine.tasks SET
                    lease_until = clock_timestamp() + make_interval(secs => %s),
                    updated_at = clock_timestamp() WHERE id = %s''',
                    (lease_seconds, _uuid(task_id)))

    def mark_effect_started(self, task_id, worker_id, epoch):
        with self.connect() as conn:
            with conn.cursor() as cur:
                task = self._fenced_task(cur, task_id, worker_id, epoch)
                cur.execute('''UPDATE mandala_engine.tasks SET effect_started = true,
                    updated_at = clock_timestamp() WHERE id = %s''', (task['id'],))
                cur.execute('SELECT version FROM mandala_engine.jobs WHERE id = %s',
                            (task['job_id'],))
                _event(cur, task['job_id'], cur.fetchone()['version'], 'EFFECT_STARTED',
                       task_id=task['id'])

    def finish_task(self, task_id, worker_id, epoch, *, state, next_action=None,
                    job_state=None, failure_class=None):
        if state not in TASK_TERMINAL:
            raise ValueError('Invalid task outcome')
        with self.connect() as conn:
            with conn.cursor() as cur:
                task = self._fenced_task(cur, task_id, worker_id, epoch)
                cur.execute('SELECT * FROM mandala_engine.jobs WHERE id = %s FOR UPDATE',
                            (task['job_id'],))
                job = cur.fetchone()
                if state != 'RECONCILIATION_REQUIRED':
                    cur.execute('''SELECT EXISTS(SELECT 1 FROM mandala_engine.call_reservations
                        WHERE task_id = %s AND state <> 'RECORDED') AS unresolved''',
                        (task['id'],))
                    if cur.fetchone()['unresolved']:
                        raise Conflict('Paid call outcome needs reconciliation')
                version = job['version'] + 1
                if state == 'RECONCILIATION_REQUIRED':
                    final_job_state = 'RECONCILIATION_REQUIRED'
                    action = None
                elif job_state in JOB_TERMINAL:
                    if task['role'] != 'revision-controller':
                        raise Conflict('Only Controller can select a terminal job result')
                    final_job_state, action = job_state, None
                else:
                    final_job_state = 'AWAITING_DISPATCH'
                    if task['role'] == 'revision-controller':
                        if not isinstance(next_action, dict):
                            raise ValueError('Controller needs a next action')
                        action = {**next_action, 'expected_job_version': version}
                    else:
                        action = {'role': 'revision-controller', 'phase': 'decide',
                                  'attempt': 0, 'input_artifact_ids': [],
                                  'expected_job_version': version}
                cur.execute('''UPDATE mandala_engine.tasks SET state = %s,
                    lease_owner = NULL, lease_until = NULL, failure_class = %s,
                    updated_at = clock_timestamp() WHERE id = %s''',
                    (state, failure_class, task['id']))
                if state == 'RECONCILIATION_REQUIRED':
                    cur.execute('''UPDATE mandala_engine.call_reservations SET
                        state = 'OUTCOME_UNKNOWN', finished_at = clock_timestamp()
                        WHERE task_id = %s AND state IN ('RESERVED', 'SENT')''',
                        (task['id'],))
                technical_qa = job['technical_qa']
                model_assessment = job['model_assessment']
                if task['role'] == 'revision-controller' and action and action['role'] == 'director':
                    technical_qa = 'NOT_RUN'
                    if action['attempt'] > 1:
                        model_assessment = 'NOT_RUN'
                if task['role'] == 'technical-qa':
                    technical_qa = 'PASS' if state == 'SUCCEEDED' else 'BLOCKED'
                if task['role'] == 'reviewer':
                    scope = 'SOURCE' if task['phase'] == 'source_speech' else 'OUTPUT'
                    model_assessment = (scope + '_MODEL_UNVERIFIED'
                                        if state == 'SUCCEEDED' else scope + '_BLOCKED')
                cur.execute('''UPDATE mandala_engine.jobs SET state = %s, next_action = %s,
                    technical_qa = %s, model_assessment = %s,
                    version = %s, updated_at = clock_timestamp() WHERE id = %s''',
                    (final_job_state, Jsonb(action) if action is not None else None,
                     technical_qa, model_assessment, version, task['job_id']))
                _event(cur, task['job_id'], version, 'TASK_' + state,
                       task_id=task['id'], detail={'failure_class': failure_class})
        return self.get_task(task_id)

    def recover_expired(self):
        """Requeue effect-free tasks; quarantine anything with uncertain effects."""
        recovered = []
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('''SELECT * FROM mandala_engine.tasks
                    WHERE state = 'RUNNING' AND lease_until <= clock_timestamp()
                    ORDER BY lease_until FOR UPDATE SKIP LOCKED''')
                for task in cur.fetchall():
                    cur.execute('SELECT version FROM mandala_engine.jobs WHERE id = %s FOR UPDATE',
                                (task['job_id'],))
                    version = cur.fetchone()['version'] + 1
                    cur.execute('''SELECT
                        EXISTS(SELECT 1 FROM mandala_engine.call_reservations WHERE task_id = %s)
                        OR EXISTS(SELECT 1 FROM mandala_engine.permits
                                  WHERE task_id = %s AND consumed_at IS NOT NULL)
                        OR EXISTS(SELECT 1 FROM mandala_engine.artifacts WHERE task_id = %s)
                        AS uncertain''', (task['id'], task['id'], task['id']))
                    uncertain = task['effect_started'] or cur.fetchone()['uncertain']
                    task_state = 'RECONCILIATION_REQUIRED' if uncertain else 'QUEUED'
                    job_state = task_state
                    cur.execute('''UPDATE mandala_engine.tasks SET state = %s,
                        lease_owner = NULL, lease_until = NULL, updated_at = clock_timestamp()
                        WHERE id = %s''', (task_state, task['id']))
                    cur.execute('''UPDATE mandala_engine.jobs SET state = %s,
                        next_action = NULL, version = %s, updated_at = clock_timestamp()
                        WHERE id = %s''', (job_state, version, task['job_id']))
                    if uncertain:
                        cur.execute('''UPDATE mandala_engine.call_reservations SET
                            state = 'OUTCOME_UNKNOWN', finished_at = clock_timestamp()
                            WHERE task_id = %s AND state IN ('RESERVED', 'SENT')''',
                            (task['id'],))
                    _event(cur, task['job_id'], version,
                           'TASK_OUTCOME_UNKNOWN' if uncertain else 'TASK_REQUEUED',
                           task_id=task['id'], detail={'expired_epoch': task['lease_epoch']})
                    recovered.append((task['id'], task_state))
        return recovered

    def reserve_call(self, task_id, worker_id, epoch, *, kind, region_key='',
                     attempt=1, request_sha256):
        if kind not in CALL_LIMITS or not HEX.fullmatch(request_sha256):
            raise ValueError('Invalid call reservation')
        with self.connect() as conn:
            with conn.cursor() as cur:
                task = self._fenced_task(cur, task_id, worker_id, epoch)
                if (task['role'], task['phase']) != CALL_ROLES[kind]:
                    raise Conflict('Call kind differs from task role')
                if kind == 'speech_asr' and not region_key:
                    raise ValueError('ASR needs a region key')
                if kind == 'reviewer_edited':
                    region_key = f'proposal-{task["attempt"]}'
                if kind in ('analyst', 'director'):
                    region_key = ''
                cur.execute('SELECT * FROM mandala_engine.jobs WHERE id = %s FOR UPDATE',
                            (task['job_id'],))
                job = cur.fetchone()
                if not job['paid_inference_approved']:
                    raise Conflict('Paid inference lacks operator approval')
                cur.execute('''SELECT count(*) AS n FROM mandala_engine.call_reservations
                    WHERE job_id = %s AND kind = %s AND region_key = %s''',
                    (task['job_id'], kind, region_key))
                count = cur.fetchone()['n']
                if count >= CALL_LIMITS[kind] or attempt != count + 1:
                    raise Conflict('Call budget exhausted or attempt is not next')
                reservation_id = uuid.uuid4()
                cur.execute('''INSERT INTO mandala_engine.call_reservations
                    (id, job_id, task_id, kind, region_key, attempt, state, request_sha256)
                    VALUES (%s, %s, %s, %s, %s, %s, 'RESERVED', %s)''',
                    (reservation_id, task['job_id'], task['id'], kind, region_key,
                     attempt, request_sha256))
                _event(cur, task['job_id'], job['version'], 'CALL_RESERVED',
                       task_id=task['id'], detail={'kind': kind, 'region': region_key,
                                                   'attempt': attempt})
        return reservation_id

    def mark_call_sent(self, reservation_id, worker_id, epoch):
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM mandala_engine.call_reservations WHERE id = %s',
                            (_uuid(reservation_id),))
                reservation = cur.fetchone()
                if reservation is None:
                    raise Conflict('Reservation is not available to send')
                task = self._fenced_task(cur, reservation['task_id'], worker_id, epoch)
                cur.execute('SELECT state FROM mandala_engine.call_reservations WHERE id = %s FOR UPDATE',
                            (_uuid(reservation_id),))
                if cur.fetchone()['state'] != 'RESERVED':
                    raise Conflict('Reservation is not available to send')
                cur.execute('''UPDATE mandala_engine.call_reservations SET
                    state = 'SENT', sent_at = clock_timestamp() WHERE id = %s''',
                    (_uuid(reservation_id),))
                cur.execute('''UPDATE mandala_engine.tasks SET effect_started = true
                    WHERE id = %s''', (task['id'],))
                cur.execute('SELECT version FROM mandala_engine.jobs WHERE id = %s',
                            (task['job_id'],))
                _event(cur, task['job_id'], cur.fetchone()['version'], 'CALL_SENT',
                       task_id=task['id'], detail={'kind': reservation['kind']})

    def record_call_outcome(self, reservation_id, worker_id, epoch, *, known, outcome):
        if not isinstance(outcome, dict):
            raise ValueError('Outcome must be a safe structured record')
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM mandala_engine.call_reservations WHERE id = %s',
                            (_uuid(reservation_id),))
                reservation = cur.fetchone()
                if reservation is None:
                    raise Conflict('Reservation was not sent')
                task = self._fenced_task(cur, reservation['task_id'], worker_id, epoch)
                cur.execute('SELECT state FROM mandala_engine.call_reservations WHERE id = %s FOR UPDATE',
                            (_uuid(reservation_id),))
                if cur.fetchone()['state'] != 'SENT':
                    raise Conflict('Reservation was not sent')
                state = 'RECORDED' if known else 'OUTCOME_UNKNOWN'
                cur.execute('''UPDATE mandala_engine.call_reservations SET
                    state = %s, outcome = %s, finished_at = clock_timestamp()
                    WHERE id = %s''', (state, Jsonb(outcome), _uuid(reservation_id)))
                cur.execute('SELECT version FROM mandala_engine.jobs WHERE id = %s',
                            (task['job_id'],))
                _event(cur, task['job_id'], cur.fetchone()['version'], 'CALL_' + state,
                       task_id=task['id'], detail={'kind': reservation['kind']})

    def _file_reference(self, relative_path):
        if not isinstance(relative_path, str) or '\\' in relative_path:
            raise ValueError('Invalid artifact path')
        parts = PurePosixPath(relative_path).parts
        if (not parts or relative_path.startswith('/') or
                str(PurePosixPath(relative_path)) != relative_path or
                any(part in ('', '.', '..') for part in parts)):
            raise ValueError('Invalid artifact path')
        root = self.output_root.resolve(strict=True)
        path = root.joinpath(*parts)
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Artifact escapes output root')
        if any(candidate.is_symlink() for candidate in (path, *path.parents) if candidate != root):
            raise ValueError('Artifact path includes a symlink')
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise ValueError('Artifact is not a nonempty regular file')
        with path.open('rb') as stream:
            sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Artifact changed while being hashed')
        return sha256, before.st_size

    def register_artifact(self, job_id, relative_path, *, kind, task_id=None,
                          worker_id=None, epoch=None):
        if task_id is None or worker_id is None or epoch is None:
            raise ValueError('Artifact registration requires a fenced task')
        sha256, size = self._file_reference(relative_path)
        job_id = _uuid(job_id)
        with self.connect() as conn:
            with conn.cursor() as cur:
                task = self._fenced_task(cur, task_id, worker_id, epoch)
                if task['job_id'] != job_id:
                    raise Conflict('Artifact belongs to another job')
                cur.execute('SELECT version FROM mandala_engine.jobs WHERE id = %s FOR UPDATE',
                            (job_id,))
                job = cur.fetchone()
                if job is None:
                    raise KeyError('Job not found')
                cur.execute('''SELECT * FROM mandala_engine.artifacts
                    WHERE job_id = %s AND relative_path = %s''', (job_id, relative_path))
                existing = cur.fetchone()
                if existing:
                    if (existing['task_id'] != task['id'] or existing['kind'] != kind or
                            existing['sha256'].strip() != sha256 or
                            existing['byte_count'] != size):
                        raise Conflict('Registered artifact bytes changed')
                    return existing, True
                artifact_id = uuid.uuid4()
                cur.execute('''INSERT INTO mandala_engine.artifacts
                    (id, job_id, task_id, kind, relative_path, sha256, byte_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (artifact_id, job_id, task['id'],
                     kind, relative_path, sha256, size))
                cur.execute('''UPDATE mandala_engine.tasks SET
                    result_artifact_ids = array_append(result_artifact_ids, %s)
                    WHERE id = %s''', (artifact_id, task['id']))
                _event(cur, job_id, job['version'], 'ARTIFACT_REGISTERED',
                       task_id=task['id'],
                       detail={'artifact_id': str(artifact_id), 'sha256': sha256})
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM mandala_engine.artifacts WHERE id = %s',
                               (artifact_id,)).fetchone()
        return row, False

    def issue_permit(self, task_id, worker_id, epoch, *, attempt,
                     proposal_sha256, execution_sha256, request_sha256):
        if any(not HEX.fullmatch(value) for value in
               (proposal_sha256, execution_sha256, request_sha256)):
            raise ValueError('Invalid permit fingerprint')
        with self.connect() as conn:
            with conn.cursor() as cur:
                task = self._fenced_task(cur, task_id, worker_id, epoch)
                if task['role'] != 'renderer' or task['phase'] != 'encode' or task['attempt'] != attempt:
                    raise Conflict('Permit requires matching renderer attempt')
                cur.execute('SELECT * FROM mandala_engine.jobs WHERE id = %s FOR UPDATE',
                            (task['job_id'],))
                job = cur.fetchone()
                if not job['paid_inference_approved']:
                    raise Conflict('Job is not approved for inference')
                cur.execute('''SELECT 1 FROM mandala_engine.permits
                    WHERE job_id = %s AND attempt = %s''', (task['job_id'], attempt))
                if cur.fetchone() is not None:
                    raise Conflict('Private preview permit already issued for this attempt')
                permit_id = uuid.uuid4()
                cur.execute('''INSERT INTO mandala_engine.permits
                    (id, job_id, task_id, attempt, source_sha256,
                     proposal_sha256, execution_sha256, request_sha256)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                    (permit_id, task['job_id'], task['id'], attempt,
                     job['source_sha256'], proposal_sha256, execution_sha256,
                     request_sha256))
                _event(cur, task['job_id'], job['version'], 'PRIVATE_PERMIT_ISSUED',
                       task_id=task['id'], detail={'attempt': attempt})
        return permit_id

    def consume_permit(self, permit_id, worker_id, epoch):
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM mandala_engine.permits WHERE id = %s FOR UPDATE',
                            (_uuid(permit_id),))
                permit = cur.fetchone()
                if permit is None or permit['consumed_at'] is not None:
                    raise Conflict('Permit is missing or already consumed')
                task = self._fenced_task(cur, permit['task_id'], worker_id, epoch)
                cur.execute('''UPDATE mandala_engine.permits SET consumed_at = clock_timestamp()
                    WHERE id = %s''', (_uuid(permit_id),))
                cur.execute('''UPDATE mandala_engine.tasks SET effect_started = true
                    WHERE id = %s''', (task['id'],))
                cur.execute('SELECT version FROM mandala_engine.jobs WHERE id = %s',
                            (task['job_id'],))
                _event(cur, task['job_id'], cur.fetchone()['version'], 'PRIVATE_PERMIT_CONSUMED',
                       task_id=task['id'], detail={'attempt': permit['attempt']})
