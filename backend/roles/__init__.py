"""Nine modular Stage 5 role adapters for the editing dispatcher."""

from backend.roles.common import Context, RoleBlocked


MODULES = {
    'analyst': 'analyst', 'av-evidence': 'av_evidence',
    'speech-asr': 'speech_asr', 'director': 'director',
    'validator': 'validator', 'renderer': 'renderer',
    'technical-qa': 'technical_qa', 'reviewer': 'reviewer',
    'revision-controller': 'revision_controller',
}


class Stage5RoleExecutor:
    def __init__(self, store, admission, *, provider, proof):
        self.store, self.admission = store, admission
        self.provider, self.proof = provider, proof
        self.worker_id = None

    def bind_worker(self, worker_id):
        self.worker_id = worker_id

    def ready(self):
        import automatic_editing_validation_v01 as validator
        return (self.provider.ready() and self.proof is not None and
                self.store.output_root.resolve() == validator.ROOT.resolve() and
                self.store.output_root.is_dir() and
                not self.store.output_root.is_symlink())

    def execute(self, task, job):
        from importlib import import_module
        from backend.editing_dispatch import ROLE_PHASES

        if not self.ready() or self.worker_id is None:
            raise RuntimeError('Stage 5 executor is not ready')
        if task['role'] not in ROLE_PHASES or task['phase'] not in ROLE_PHASES[task['role']]:
            raise ValueError('Unknown role/phase')
        ctx = Context(task, job, self.store, self.admission,
                      self.worker_id, self.provider, self.proof)
        try:
            outcome = import_module('backend.roles.' + MODULES[task['role']]).execute(ctx)
        except RoleBlocked:
            return {'state': 'BLOCKED', 'failure_class': 'ROLE_VALIDATION_BLOCKED'}
        if not isinstance(outcome, dict) or outcome.get('state') not in ('SUCCEEDED', 'BLOCKED'):
            raise RuntimeError('Role returned invalid outcome')
        return outcome
