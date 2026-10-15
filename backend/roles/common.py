"""Fenced Stage 5 job context. File writes are exclusive and manifest-bound."""

import json
from pathlib import Path

from backend.editing_store import Conflict, digest
from backend.media_worker.intake_adapter import IntakeError, stage5


class RoleBlocked(ValueError):
    """A definite validation failure; Controller may choose the next step."""


class Context:
    def __init__(self, task, job, store, admission, worker_id, provider, proof):
        self.task, self.job = task, job
        self.store, self.admission = store, admission
        self.worker_id, self.provider, self.proof = worker_id, provider, proof
        self.epoch = task['lease_epoch']
        self.directory = store.output_root / str(job['id'])

    def fence(self):
        with self.store.connect() as conn:
            with conn.cursor() as cur:
                self.store._fenced_task(cur, self.task['id'], self.worker_id, self.epoch)

    def source(self):
        """Recheck Stage 3 row and bytes, then bind the Stage 5 mount alias."""
        snapshot = self.admission.revalidate(self.job)
        original = Path(snapshot['original_path'])
        if original.is_relative_to(stage5.ROOT):
            candidate = original
        else:
            candidate = stage5.ROOT / 'original-store/source/originals' / original.name
        try:
            candidate = stage5.project_path(candidate, 'Stage 5 original MP4')
            left, right = original.stat(), candidate.stat()
        except (OSError, stage5.AdapterError):
            raise IntakeError('Stage 5 read-only original alias unavailable') from None
        if (left.st_dev, left.st_ino, left.st_size) != (right.st_dev, right.st_ino, right.st_size):
            raise IntakeError('Stage 5 alias differs from admitted original')
        return candidate, snapshot

    def begin(self):
        self.fence()
        if self.directory.exists():
            if self.directory.is_symlink() or not self.directory.is_dir():
                raise Conflict('Unsafe job artifact directory')
        else:
            self.directory.mkdir(parents=True)

    def artifact(self, path, kind):
        self.fence()
        path = Path(path)
        relative = path.relative_to(self.store.output_root).as_posix()
        row, _ = self.store.register_artifact(self.job['id'], relative, kind=kind,
                                               task_id=self.task['id'],
                                               worker_id=self.worker_id, epoch=self.epoch)
        return row

    def register_tree(self, directory, kind):
        """Register every completed file; leftovers after a crash remain orphans."""
        result = []
        for path in sorted(Path(directory).rglob('*')):
            if path.is_file():
                result.append(self.artifact(path, kind))
        return result

    def write_json(self, name, value, kind):
        from run_automatic_editing_v01 import write
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path, value)
        return self.artifact(path, kind)

    def write_text(self, name, value, kind):
        from run_automatic_editing_v01 import save_text
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        save_text(path, value)
        return self.artifact(path, kind)

    def rows(self, kind=None):
        rows = self.store.artifact_rows(self.job['id'])
        return [row for row in rows if kind is None or row['kind'] == kind]

    def input(self, kind, *, latest=True):
        allowed = set(self.task['input_artifact_ids'])
        rows = [r for r in self.rows(kind) if r['id'] in allowed]
        if len(rows) != 1 and latest:
            raise RoleBlocked(f'Missing or ambiguous {kind} input artifact')
        if not latest:
            return [self._verified_path(row) for row in rows]
        return self._verified_path(rows[0])

    def _verified_path(self, row):
        sha, size = self.store._file_reference(row['relative_path'])
        if sha != row['sha256'].strip() or size != row['byte_count']:
            raise Conflict('Input artifact bytes differ from manifest')
        path = self.store.output_root / row['relative_path']
        if not path.is_relative_to(self.directory):
            raise Conflict('Input artifact outside job')
        return path

    def paid(self, kind, request, invoke, *, region='', attempt=1):
        """Reserve before a call. An uncertain send never receives a retry."""
        self.source()
        self.fence()
        reservation = self.store.reserve_call(
            self.task['id'], self.worker_id, self.epoch, kind=kind,
            region_key=region, attempt=attempt, request_sha256=digest(request))
        self.store.mark_call_sent(reservation, self.worker_id, self.epoch)
        try:
            result = invoke()
        except Exception:
            self.store.record_call_outcome(reservation, self.worker_id, self.epoch,
                                           known=False, outcome={'class': 'INVOCATION_UNCERTAIN'})
            raise
        self.store.record_call_outcome(reservation, self.worker_id, self.epoch,
                                       known=True, outcome={'class': 'RESPONSE_RECEIVED',
                                                            'response_sha256': digest(result)})
        return result

    def json_input(self, kind):
        return json.loads(self.input(kind).read_text(encoding='utf-8'))


def action(role, phase, attempt, rows=(), **extra):
    value = {'role': role, 'phase': phase, 'attempt': attempt,
             'input_artifact_ids': [str(row['id']) for row in rows]}
    return {**value, **extra}
