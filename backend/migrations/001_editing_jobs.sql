-- Stage 6.3.5 editing-only state. Apply with an editing migration credential.
-- No statement reads or writes public.source_videos.
CREATE SCHEMA IF NOT EXISTS mandala_engine;

CREATE TABLE IF NOT EXISTS mandala_engine.schema_migrations (
    version integer PRIMARY KEY,
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS mandala_engine.jobs (
    id uuid PRIMARY KEY,
    source_key text NOT NULL UNIQUE,
    source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_snapshot jsonb NOT NULL,
    state text NOT NULL CHECK (state IN (
        'AWAITING_INFERENCE_APPROVAL', 'AWAITING_DISPATCH', 'QUEUED', 'RUNNING',
        'AUTO_PREVIEW_COMPLETED', 'AUTO_PREVIEW_COMPLETED_WITH_NOTES',
        'BLOCKED', 'FAILED', 'RECONCILIATION_REQUIRED')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    next_action jsonb,
    paid_inference_approved boolean NOT NULL DEFAULT false,
    technical_qa text NOT NULL DEFAULT 'NOT_RUN',
    model_assessment text NOT NULL DEFAULT 'NOT_RUN',
    human_verified boolean NOT NULL DEFAULT false CHECK (human_verified = false),
    production_eligible boolean NOT NULL DEFAULT false CHECK (production_eligible = false),
    publishing_eligible boolean NOT NULL DEFAULT false CHECK (publishing_eligible = false),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS mandala_engine.tasks (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES mandala_engine.jobs(id),
    role text NOT NULL,
    phase text NOT NULL,
    attempt integer NOT NULL CHECK (attempt BETWEEN 0 AND 3),
    state text NOT NULL CHECK (state IN (
        'QUEUED', 'RUNNING', 'SUCCEEDED', 'BLOCKED', 'FAILED',
        'RECONCILIATION_REQUIRED')),
    input_artifact_ids uuid[] NOT NULL DEFAULT '{}',
    result_artifact_ids uuid[] NOT NULL DEFAULT '{}',
    lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    lease_owner text,
    lease_until timestamptz,
    effect_started boolean NOT NULL DEFAULT false,
    failure_class text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((state = 'RUNNING') = (lease_owner IS NOT NULL AND lease_until IS NOT NULL)),
    UNIQUE (job_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_one_active_per_job
    ON mandala_engine.tasks(job_id) WHERE state IN ('QUEUED', 'RUNNING');
CREATE INDEX IF NOT EXISTS tasks_claim_queue
    ON mandala_engine.tasks(created_at, id) WHERE state = 'QUEUED';

CREATE TABLE IF NOT EXISTS mandala_engine.call_reservations (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES mandala_engine.jobs(id),
    task_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN (
        'analyst', 'director', 'speech_asr', 'reviewer_source', 'reviewer_edited')),
    region_key text NOT NULL DEFAULT '',
    attempt integer NOT NULL CHECK (attempt BETWEEN 1 AND 3),
    state text NOT NULL CHECK (state IN (
        'RESERVED', 'SENT', 'RECORDED', 'OUTCOME_UNKNOWN')),
    request_sha256 char(64) NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    outcome jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    sent_at timestamptz,
    finished_at timestamptz,
    UNIQUE (job_id, kind, region_key, attempt),
    FOREIGN KEY (job_id, task_id) REFERENCES mandala_engine.tasks(job_id, id)
);
CREATE INDEX IF NOT EXISTS reservations_budget
    ON mandala_engine.call_reservations(job_id, kind, region_key);

CREATE TABLE IF NOT EXISTS mandala_engine.artifacts (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES mandala_engine.jobs(id),
    task_id uuid,
    kind text NOT NULL,
    relative_path text NOT NULL CHECK (
        relative_path <> '' AND relative_path !~ '(^/|(^|/)\.\.(/|$))'),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_count bigint NOT NULL CHECK (byte_count > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (job_id, relative_path),
    FOREIGN KEY (job_id, task_id) REFERENCES mandala_engine.tasks(job_id, id)
);

CREATE TABLE IF NOT EXISTS mandala_engine.permits (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES mandala_engine.jobs(id),
    task_id uuid NOT NULL,
    attempt integer NOT NULL CHECK (attempt BETWEEN 1 AND 3),
    scope text NOT NULL DEFAULT 'STAGE59_PRIVATE_PREVIEW'
        CHECK (scope = 'STAGE59_PRIVATE_PREVIEW'),
    source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    proposal_sha256 char(64) NOT NULL CHECK (proposal_sha256 ~ '^[0-9a-f]{64}$'),
    execution_sha256 char(64) NOT NULL CHECK (execution_sha256 ~ '^[0-9a-f]{64}$'),
    request_sha256 char(64) NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (job_id, attempt),
    FOREIGN KEY (job_id, task_id) REFERENCES mandala_engine.tasks(job_id, id)
);

CREATE TABLE IF NOT EXISTS mandala_engine.job_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES mandala_engine.jobs(id),
    task_id uuid,
    job_version bigint NOT NULL CHECK (job_version > 0),
    kind text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (job_id, task_id) REFERENCES mandala_engine.tasks(job_id, id)
);
CREATE INDEX IF NOT EXISTS job_events_by_job
    ON mandala_engine.job_events(job_id, id);

-- One namespace across admission and task submission for a workflow principal.
CREATE TABLE IF NOT EXISTS mandala_engine.idempotency_keys (
    principal text NOT NULL,
    key text NOT NULL CHECK (length(key) BETWEEN 1 AND 128),
    method text NOT NULL,
    route text NOT NULL,
    request_sha256 char(64) NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    response_status integer NOT NULL,
    job_id uuid REFERENCES mandala_engine.jobs(id),
    task_id uuid REFERENCES mandala_engine.tasks(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (principal, key),
    CHECK ((job_id IS NOT NULL) <> (task_id IS NOT NULL))
);
