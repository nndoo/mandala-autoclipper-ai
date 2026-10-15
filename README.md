# Mandala Auto Autonomous AI Autoclipper

Python video analysis, speech evidence, editing plans, FFmpeg rendering, and QA,
with an OpenClaw TypeScript adapter for the tested 9Router video compatibility
transport. Run commands from the project root.

New agent or device? Start with the [AI agent reading guide](docs/AGENT_GUIDE.md),
[handoff](HANDOFF_README.md), and [Markdown catalog](docs/markdown-catalog.md).
The latest local [Stage 6.3.5 Tahap D checkpoint](docs/stage63/stage635-stage-d-completion-2026-10-16.md)
records TEST_ONLY integration PASS; local tests do not establish production readiness.

## Local setup

The Stage 6.3.5 Tahap A checkpoint verified Python 3.14.2, Node 24.21.0 for
isolated OpenClaw 2026.9.9, FFmpeg/FFprobe, and Ruff 0.17.0. Recheck versions
on the current host. Paths inside Python tools
resolve from this checkout, so the folder can be moved without editing source.
Use a fresh virtualenv when changing devices; copied virtualenvs are not portable.

```sh
uv python install 3.14.2
uv venv --python 3.14.2 .venv-av
uv pip install --python .venv-av/bin/python --only-binary :all: -r requirements-av.lock.txt
uv tool install ruff==0.17.0
sudo apt-get install ffmpeg
```

Build the adapter from its lockfile. Set `MANDALA_PROVIDER_ID` to the non-secret
provider ID matching your private OpenClaw configuration; do not use an API key.
The generated binding and manifest are intentionally excluded from Git.

```sh
: "${MANDALA_PROVIDER_ID:?Set the non-secret OpenClaw provider ID}"
.venv-av/bin/python openclaw/plugins/mandala-9router-video/tools/configure_plugin.py --provider-id "$MANDALA_PROVIDER_ID"
cd openclaw/plugins/mandala-9router-video
npm ci
npm run build
npm test
node_modules/.bin/tsc --noEmit
```

## Verification

```sh
.venv-av/bin/python -m unittest discover -s tests -p 'test_*.py'
ruff check scripts tests
.venv-av/bin/python scripts/validate_universal_analysis_v02.py --self-test
```

Files named `poc_*` are live experiments and are excluded from the offline suite.
The default speech backend is remote; a local Whisper model is optional and is
not installed by these setup commands. See [remote ASR](docs/remote-speech-asr-v01.md).

## Inference configuration

Runners use `~/.local/share/mandala-openclaw-runtime/bin/openclaw` and its bundled
`tools/node-v24.21.0/bin/node`. Provider configuration and agent/plugin paths live
in private `~/.openclaw/openclaw.json`. Provider credentials are environment-backed
through private `~/.openclaw/.env`; project ASR uses `.env.asr`. Both credential
files must remain mode 0600 and outside Git.

See [migration setup and verification](docs/local-migration-2026-10-14.md) for this
device's installed components and remaining external dependencies. Changing the
provider ID requires regenerating the adapter binding before building it:
`.venv-av/bin/python openclaw/plugins/mandala-9router-video/tools/configure_plugin.py`.

## Media and services

`data/` contains original media and historical evidence and is ignored by Git.
Back it up separately; a clone will not restore it. Historical receipts remain
bound to their original code/environment; new render proofs use new output bundles.

PostgreSQL 16 integration was tested against an isolated local `TEST_ONLY`
database during Tahap B/C. Production database, n8n, Cloudinary, and current
Coolify connections require separate verification. A deployment report is a
historical observation, not a live service check. Local regression success
does not establish publishing authorization.

## Stage 6.1 audit and repository layout

See [repository structure](docs/repository-structure.md) and the
[Stage 6.1 audit](docs/stage61/audit-report.md) for runtime/development boundaries,
integration gaps, archive policy, cleanup manifest, and fresh regression results.
Historical evidence keeps its original paths; local archives and data need separate
backups. `.dockerignore` excludes local evidence, credentials and dependency caches
from a future build context. Stage 6.1 does not deploy or integrate n8n.

## Stage 6.3 editing worker and recovery

The existing Media Worker remains the source/download service on `:3002`.
`backend/Dockerfile` builds the separate `mandala-ai-editing-worker` from the
repository root, with `backend.editing_worker` as its `:3003` entrypoint. Local
Stage 6.3.5 recovery added the PostgreSQL schema, source admission, authenticated
HTTP API, dispatcher, and nine role modules. Read the [API contract](docs/stage63/stage635-api-contract.md),
[role map](backend/roles/README.md), and [checkpoints A–D](docs/stage63/README.md)
before changing them. Tahap A–D passed their stated local TEST_ONLY scopes;
Tahap D now includes actual synthetic render, Technical QA, both Reviewer
phases, and bounded revision selection. Docker/image readiness, live provider,
full historical regression, and production readiness remain unproved. Recheck
source and tests for current state.

The [two-worker architecture](docs/stage63/stage634-two-worker-architecture.md)
and [deployment guide](docs/stage63/stage635-deployment-guide.md) describe the
intended mount and deployment boundaries, not authorization to deploy. No role
integration with production n8n is established by this checkout. Historical
[Git readiness](docs/stage63/git-readiness.md) and
[Docker runtime preparation](docs/stage63/stage634-docker-runtime.md) describe
Stage 6.3.4 preparation; they are not proof of the current image or service.
