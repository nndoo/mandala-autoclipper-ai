"""Stage 6.3.5 DB dispatcher with fenced Stage 5 role execution."""

import logging
import stat
import threading
import traceback
import uuid

from backend.editing_store import Fenced
from backend.media_worker.intake_adapter import IntakeError

logger = logging.getLogger(__name__)


def _safe_exception_frames(exc, limit=8):
    """Return frame locations without exception messages or local variables."""
    frames = traceback.extract_tb(exc.__traceback__, limit=limit)
    return " <- ".join(
        f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}:{frame.name}"
        for frame in frames
    ) or "unavailable"


ROLE_PHASES = {
    'analyst': frozenset({'analyze'}),
    'av-evidence': frozenset({'measure'}),
    'speech-asr': frozenset({'transcribe'}),
    'director': frozenset({'propose'}),
    'validator': frozenset({'validate'}),
    'renderer': frozenset({'encode'}),
    'technical-qa': frozenset({'inspect'}),
    'reviewer': frozenset({'source_speech', 'edited_output'}),
    'revision-controller': frozenset({'decide'}),
}


class TestOnlyMockExecutor:
    """Injected only by local tests; no provider, rendering or Stage 5 output."""

    def execute(self, task, job):
        if task['role'] not in ROLE_PHASES or task['phase'] not in ROLE_PHASES[task['role']]:
            raise ValueError('Unknown role contract')
        if task['role'] == 'revision-controller':
            return {'state': 'BLOCKED', 'job_state': 'BLOCKED',
                    'failure_class': 'TEST_ONLY_NO_ROLE_ENGINE'}
        return {'state': 'BLOCKED', 'failure_class': 'TEST_ONLY_MOCK_ROLE'}


class Dispatcher:
    def __init__(self, store, admission, *, executor, ready, worker_id=None,
                 heartbeat_seconds=15):
        self.store = store
        self.admission = admission
        self.executor = executor
        self.ready = ready
        self.worker_id = worker_id or 'editing-' + uuid.uuid4().hex
        if executor is not None and hasattr(executor, 'bind_worker'):
            executor.bind_worker(self.worker_id)
        self.heartbeat_seconds = heartbeat_seconds
        self.stop = threading.Event()

    def _artifact_problem(self, job_id):
        root = self.store.output_root.resolve(strict=True)
        directory = root / str(job_id)
        manifest = {row['relative_path']: row for row in self.store.artifact_rows(job_id)}
        if not directory.exists():
            return 'ARTIFACT_MISSING' if manifest else None
        if directory.is_symlink() or not directory.is_dir():
            return 'ARTIFACT_UNSAFE'
        seen = set()
        for path in directory.rglob('*'):
            if path.is_symlink() or not path.is_relative_to(root):
                return 'ARTIFACT_UNSAFE'
            if path.is_dir():
                continue
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                return 'ARTIFACT_UNSAFE'
            relative = path.relative_to(root).as_posix()
            row = manifest.get(relative)
            if row is None:
                return 'ARTIFACT_ORPHAN'
            try:
                sha256, size = self.store._file_reference(relative)
            except (OSError, ValueError, RuntimeError):
                return 'ARTIFACT_MISMATCH'
            if sha256 != row['sha256'].strip() or size != row['byte_count']:
                return 'ARTIFACT_MISMATCH'
            seen.add(relative)
        return 'ARTIFACT_MISSING' if seen != set(manifest) else None

    def recover_once(self):
        """Inspect files before requeueing an expired task with no DB marker."""
        for job in self.store.recovery_jobs():
            if job['state'] == 'RUNNING' and not job['expired']:
                continue
            problem = self._artifact_problem(job['id'])
            if problem:
                self.store.quarantine_job(job['id'], problem,
                                          expected_state=job['state'])
        return self.store.recover_expired()

    def _heartbeat(self, task, stop, lost):
        while not stop.wait(self.heartbeat_seconds):
            try:
                self.store.heartbeat(task['id'], self.worker_id, task['lease_epoch'])
            except Exception:
                lost.set()
                return

    def run_once(self):
        if self.executor is None or not self.ready():
            return None
        self.recover_once()
        task = self.store.claim_task(self.worker_id)
        if task is None:
            return None
        stop, lost = threading.Event(), threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(task, stop, lost), daemon=True)
        heartbeat.start()
        stage = 'load_job'
        try:
            job = self.store.get_job(task['job_id'])
            stage = 'revalidate_source'
            try:
                self.admission.revalidate(job)
            except (IntakeError, ValueError):
                if not lost.is_set():
                    self.store.finish_task(task['id'], self.worker_id, task['lease_epoch'],
                                           state='RECONCILIATION_REQUIRED',
                                           failure_class='SOURCE_CHANGED')
                return task['id']
            if lost.is_set():
                return task['id']
            stage = 'mark_effect_started'
            self.store.mark_effect_started(task['id'], self.worker_id, task['lease_epoch'])
            if lost.is_set():
                return task['id']
            stage = 'execute_role'
            outcome = self.executor.execute(task, job)
            if not lost.is_set():
                stage = 'persist_task_outcome'
                self.store.finish_task(task['id'], self.worker_id, task['lease_epoch'],
                                       **outcome)
        except Fenced:
            pass
        except Exception as exc:
            logger.error(
                "Editing task exception: task_id=%s job_id=%s role=%s phase=%s "
                "lease_epoch=%s stage=%s exception_type=%s frames=%s",
                task.get('id'), task.get('job_id'), task.get('role'),
                task.get('phase'), task.get('lease_epoch'), stage,
                type(exc).__name__, _safe_exception_frames(exc),
            )
            if not lost.is_set():
                try:
                    stage = 'persist_reconciliation'
                    self.store.finish_task(task['id'], self.worker_id,
                                           task['lease_epoch'],
                                           state='RECONCILIATION_REQUIRED',
                                           failure_class='EXECUTOR_UNCERTAIN')
                except Fenced:
                    pass
                except Exception as record_exc:
                    logger.error(
                        "Could not persist reconciliation state: task_id=%s "
                        "job_id=%s role=%s phase=%s lease_epoch=%s "
                        "exception_type=%s frames=%s",
                        task.get('id'), task.get('job_id'), task.get('role'),
                        task.get('phase'), task.get('lease_epoch'),
                        type(record_exc).__name__,
                        _safe_exception_frames(record_exc),
                    )
        finally:
            stop.set()
            heartbeat.join(timeout=1)
        return task['id']

    def run(self):
        while not self.stop.is_set():
            try:
                self.run_once()
            except Exception:
                # DB/storage downtime does not authorize claiming or retrying an effect.
                pass
            self.stop.wait(1)
