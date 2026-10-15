"""Internal Stage 6.3.5 HTTP API."""

import hashlib
import hmac
import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from backend.editing_dispatch import ROLE_PHASES
from backend.editing_store import Conflict, EditingStore, migration_ready
from backend.media_worker.intake_adapter import IntakeError
from backend.runtime_check import inspect
from backend.source_admission import CONTRACT, SourceAdmission

MAX_BODY = 64 * 1024
JOB = re.compile(r'/v1/jobs/([0-9a-fA-F-]{36})\Z')
TASK = re.compile(r'/v1/tasks/([0-9a-fA-F-]{36})\Z')
ARTIFACTS = re.compile(r'/v1/jobs/([0-9a-fA-F-]{36})/artifacts\Z')
APPROVE = re.compile(r'/v1/jobs/([0-9a-fA-F-]{36})/approve-inference\Z')
ROLE = re.compile(r'/v1/jobs/([0-9a-fA-F-]{36})/roles/([a-z-]+)\Z')


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _uuid(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ApiError(404, 'NOT_FOUND', 'Resource not found') from None


def _proof_replay(path):
    from run_automatic_editing_v01 import check_proof, reference
    check_proof(reference(path))


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


class EditingService:
    def __init__(self, *, store=None, admission=None, workflow_token=None,
                 operator_token=None, proof_path=None, runtime_check=None,
                 proof_check=None, executor=None):
        self.store, self.admission = store, admission
        self.workflow_token, self.operator_token = workflow_token, operator_token
        self.proof_path = Path(proof_path) if proof_path else None
        self.runtime_check = runtime_check or (lambda: inspect(
            check_storage=True, require_service_env=True)['status'] == 'PASS')
        self.proof_check = proof_check or _proof_replay
        self.executor = executor

    @classmethod
    def from_env(cls):
        editing_dsn = os.getenv('MANDALA_EDITING_DATABASE_URL')
        source_dsn = os.getenv('MANDALA_SOURCE_DATABASE_URL')
        role_root = Path('/app/data/revisions/stage59/automatic')
        store = EditingStore(editing_dsn, output_root=role_root) if editing_dsn else None
        admission = SourceAdmission(source_dsn, store, storage_root=os.getenv(
            'AUTOCLIPPER_SOURCE_ROOT', '/data/source')) if source_dsn and store else None
        executor = None
        if admission and os.getenv('MANDALA_EDITING_LIVE_ROLES_ENABLED') == '1':
            from backend.roles import Stage5RoleExecutor
            from backend.roles.provider import LiveProvider
            role_root.mkdir(parents=True, exist_ok=True)
            executor = Stage5RoleExecutor(store, admission,
                provider=LiveProvider(enabled=True), proof=os.getenv('MANDALA_EDITING_PROOF'))
        return cls(store=store, admission=admission,
                   workflow_token=os.getenv('MANDALA_EDITING_API_TOKEN'),
                   operator_token=os.getenv('MANDALA_EDITING_OPERATOR_TOKEN'),
                   proof_path=os.getenv('MANDALA_EDITING_PROOF'), executor=executor)

    def configured(self):
        return (self.store is not None and self.admission is not None and
                self.proof_path is not None and
                isinstance(self.workflow_token, str) and len(self.workflow_token) >= 32 and
                isinstance(self.operator_token, str) and len(self.operator_token) >= 32 and
                self.workflow_token != self.operator_token)

    def ready(self):
        if (not self.configured() or self.executor is None or
                (hasattr(self.executor, 'ready') and not self.executor.ready())):
            return False
        try:
            if not self.runtime_check() or not migration_ready(self.store.dsn):
                return False
            with psycopg.connect(self.admission.source_dsn, connect_timeout=5,
                                 options='-c default_transaction_read_only=on') as conn:
                conn.execute('SELECT 1 FROM public.source_videos LIMIT 0')
                rights = conn.execute('''SELECT has_table_privilege(
                    current_user, 'public.source_videos', 'SELECT'),
                    has_table_privilege(current_user, 'public.source_videos', 'INSERT'),
                    has_table_privilege(current_user, 'public.source_videos', 'UPDATE'),
                    has_table_privilege(current_user, 'public.source_videos', 'DELETE'),
                    has_table_privilege(current_user, 'public.source_videos', 'TRUNCATE')''').fetchone()
                if rights != (True, False, False, False, False):
                    return False
            self.proof_check(self.proof_path)
            return True
        except Exception:
            return False


def _job_view(row):
    return {'id': str(row['id']), 'source_key': row['source_key'],
            'source_sha256': row['source_sha256'].strip(), 'state': row['state'],
            'version': row['version'], 'next_action': row['next_action'],
            'paid_inference_approved': row['paid_inference_approved'],
            'technical_qa': row['technical_qa'], 'model_assessment': row['model_assessment'],
            'human_verified': row['human_verified'],
            'production_eligible': row['production_eligible'],
            'publishing_eligible': row['publishing_eligible']}


def _task_view(row, job):
    return {'id': str(row['id']), 'job_id': str(row['job_id']),
            'role': row['role'], 'phase': row['phase'], 'attempt': row['attempt'],
            'state': row['state'], 'failure_class': row['failure_class'],
            'lease_epoch': row['lease_epoch'], 'job_version': job['version'],
            'next_action': job['next_action']}


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # Avoid path, Authorization, operator token and DSN in access logs.
        pass

    @property
    def service(self):
        return getattr(self.server, 'service', None)

    def respond(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authenticate(self, *, operator=False):
        service = self.service
        if not service.configured():
            raise ApiError(503, 'NOT_READY', 'Editing service unavailable')
        headers = self.headers.get_all('Authorization', [])
        if len(headers) != 1 or len(headers[0]) > 4096 or not headers[0].startswith('Bearer '):
            raise ApiError(401, 'UNAUTHORIZED', 'Authentication required')
        presented = headers[0][7:]
        if not hmac.compare_digest(hashlib.sha256(presented.encode()).digest(),
                                   hashlib.sha256(service.workflow_token.encode()).digest()):
            raise ApiError(401, 'UNAUTHORIZED', 'Authentication required')
        if operator:
            values = self.headers.get_all('X-Operator-Token', [])
            if len(values) != 1 or len(values[0]) > 4096 or not hmac.compare_digest(
                    hashlib.sha256(values[0].encode()).digest(),
                    hashlib.sha256(service.operator_token.encode()).digest()):
                raise ApiError(401, 'UNAUTHORIZED', 'Operator authentication required')

    def _json_body(self):
        values = self.headers.get_all('Content-Type', [])
        if len(values) != 1 or values[0].lower().replace(' ', '') not in (
                'application/json', 'application/json;charset=utf-8'):
            raise ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Expected application/json UTF-8')
        if self.headers.get('Transfer-Encoding'):
            raise ApiError(422, 'INVALID_REQUEST', 'Chunked request body is unsupported')
        sizes = self.headers.get_all('Content-Length', [])
        if len(sizes) != 1 or len(sizes[0]) > 10 or not sizes[0].isdigit():
            raise ApiError(422, 'INVALID_REQUEST', 'Content-Length is required')
        size = int(sizes[0])
        if size > MAX_BODY:
            raise ApiError(413, 'BODY_TOO_LARGE', 'Request body exceeds 64 KiB')
        if size < 1:
            raise ApiError(422, 'INVALID_REQUEST', 'JSON object is required')
        try:
            body = json.loads(self.rfile.read(size).decode('utf-8'),
                              object_pairs_hook=_no_duplicates,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            raise ApiError(422, 'INVALID_REQUEST', 'Malformed JSON body') from None
        if not isinstance(body, dict):
            raise ApiError(422, 'INVALID_REQUEST', 'JSON object is required')
        return body

    def _idempotency_key(self):
        values = self.headers.get_all('Idempotency-Key', [])
        if len(values) != 1:
            raise ApiError(422, 'INVALID_REQUEST', 'Idempotency-Key is required')
        self.service.store._key('workflow', values[0])
        return values[0]

    def _role_body(self, body, role):
        required = {'contract_version', 'expected_job_version', 'phase',
                    'attempt', 'input_artifact_ids'}
        if (set(body) not in (required, required | {'regions'}) or
                body.get('contract_version') != CONTRACT or
                not isinstance(body.get('phase'), str) or
                body['phase'] not in ROLE_PHASES[role] or
                type(body.get('expected_job_version')) is not int or
                body['expected_job_version'] < 1 or
                type(body.get('attempt')) is not int or
                not isinstance(body.get('input_artifact_ids'), list) or
                not all(isinstance(value, str) for value in body['input_artifact_ids'])):
            raise ApiError(422, 'INVALID_REQUEST', 'Invalid role contract')
        zero = role in ('analyst', 'av-evidence', 'speech-asr', 'revision-controller') or (
            body['phase'] == 'source_speech')
        if ((zero and body['attempt'] != 0) or
                (not zero and not 1 <= body['attempt'] <= 3) or
                ('regions' in body and (role != 'speech-asr' or
                                        not isinstance(body['regions'], list)))):
            raise ApiError(422, 'INVALID_REQUEST', 'Invalid role attempt or regions')

    def _route(self, method):
        path = urlsplit(self.path)
        if path.query or path.fragment:
            raise ApiError(404, 'NOT_FOUND', 'Endpoint not found')
        if method == 'GET' and path.path == '/health':
            return 200, {'status': 'ok', 'service': 'mandala-ai-editing-worker',
                         'roles_ready': False}
        if method == 'GET' and path.path == '/health/ready':
            ready = bool(self.service and self.service.ready())
            return (200 if ready else 503), {'status': 'ready' if ready else 'blocked',
                                             'roles_ready': ready}
        if not path.path.startswith('/v1/') or self.service is None:
            raise ApiError(404, 'NOT_FOUND', 'Endpoint not found')
        operator = method == 'POST' and APPROVE.fullmatch(path.path) is not None
        self._authenticate(operator=operator)
        if method == 'POST':
            if not self.service.ready():
                raise ApiError(503, 'NOT_READY', 'Editing service unavailable')
            body = self._json_body()
            if path.path == '/v1/jobs':
                job, _ = self.service.admission.admit(
                    body, principal='workflow', key=self._idempotency_key())
                return 201, {'job': _job_view(job)}
            matched = APPROVE.fullmatch(path.path)
            if matched:
                if (set(body) != {'decision', 'human_reviewed'} or
                        body['decision'] != 'approve_paid_inference' or
                        body['human_reviewed'] is not True):
                    raise ApiError(422, 'INVALID_REQUEST', 'Invalid approval contract')
                job = self.service.store.approve_paid_inference(_uuid(matched[1]))
                return 200, {'job': _job_view(job)}
            matched = ROLE.fullmatch(path.path)
            if matched:
                job_id, role = _uuid(matched[1]), matched[2]
                if role not in ROLE_PHASES:
                    raise ApiError(422, 'INVALID_REQUEST', 'Unknown role')
                self._role_body(body, role)
                task, _ = self.service.store.submit_task(
                    job_id, principal='workflow', key=self._idempotency_key(),
                    expected_version=body['expected_job_version'], role=role,
                    phase=body['phase'], attempt=body['attempt'],
                    input_artifact_ids=body['input_artifact_ids'],
                    regions=body.get('regions'))
                job = self.service.store.get_job(job_id)
                return 202, {'task': _task_view(task, job)}
            raise ApiError(404, 'NOT_FOUND', 'Endpoint not found')
        matched = ARTIFACTS.fullmatch(path.path)
        if matched:
            job_id = _uuid(matched[1])
            if self.service.store.get_job(job_id) is None:
                raise ApiError(404, 'NOT_FOUND', 'Resource not found')
            rows = self.service.store.artifact_rows(job_id)
            return 200, {'artifacts': [
                {'id': str(row['id']), 'kind': row['kind'],
                 'relative_path': row['relative_path'],
                 'sha256': row['sha256'].strip(), 'byte_count': row['byte_count']}
                for row in rows]}
        matched = JOB.fullmatch(path.path)
        if matched:
            job = self.service.store.get_job(_uuid(matched[1]))
            if job is None:
                raise ApiError(404, 'NOT_FOUND', 'Resource not found')
            return 200, {'job': _job_view(job)}
        matched = TASK.fullmatch(path.path)
        if matched:
            task = self.service.store.get_task(_uuid(matched[1]))
            if task is None:
                raise ApiError(404, 'NOT_FOUND', 'Resource not found')
            return 200, {'task': _task_view(task, self.service.store.get_job(task['job_id']))}
        raise ApiError(404, 'NOT_FOUND', 'Endpoint not found')

    def _handle(self, method):
        try:
            status, payload = self._route(method)
            self.respond(status, payload)
        except ApiError as error:
            self.respond(error.status, {'error': {'code': error.code, 'message': error.message}})
        except Conflict:
            self.respond(409, {'error': {'code': 'CONFLICT',
                                        'message': 'Request conflicts with current job state'}})
        except (IntakeError, ValueError):
            self.respond(422, {'error': {'code': 'INVALID_REQUEST',
                                        'message': 'Source or request is invalid'}})
        except KeyError:
            self.respond(404, {'error': {'code': 'NOT_FOUND', 'message': 'Resource not found'}})
        except (psycopg.Error, OSError):
            self.respond(503, {'error': {'code': 'DEPENDENCY_UNAVAILABLE',
                                        'message': 'Editing dependency unavailable'}})
        except Exception:
            self.respond(503, {'error': {'code': 'INTERNAL_UNAVAILABLE',
                                        'message': 'Editing request unavailable'}})

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')
