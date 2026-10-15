# Mandala Auto Autonomous AI Autoclipper

Python video analysis, speech evidence, editing plans, FFmpeg rendering, and QA,
with an OpenClaw TypeScript adapter for the tested 9Router video compatibility
transport. Run commands from the project root.

## Local setup

The current Linux environment uses Python 3.14.2, Node 24.21.0 for isolated
OpenClaw 2026.9.9, FFmpeg/FFprobe, and Ruff 0.17.0. Paths inside Python tools
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

n8n, PostgreSQL, Cloudinary, and GitHub → Coolify describe intended architecture.
Their deployment configurations and live connections are not supplied by this
checkout. Local regression success does not establish publishing authorization.

## Stage 6.1 audit and repository layout

See [repository structure](docs/repository-structure.md) and the
[Stage 6.1 audit](docs/stage61/audit-report.md) for runtime/development boundaries,
integration gaps, archive policy, cleanup manifest, and fresh regression results.
Historical evidence keeps its original paths; local archives and data need separate
backups. `.dockerignore` excludes local evidence, credentials and dependency caches
from a future build context. Stage 6.1 does not deploy or integrate n8n.

## Stage 6.3 source and Docker preparation

The existing Media Worker remains a permanent source/download service.
`backend/Dockerfile` now builds ONLY the new `mandala-ai-editing-worker` from
the repository root, with `backend.editing_worker` as its port 3003 entrypoint;
its builder regenerates the plugin binding. Runtime
dependencies are pinned in `backend/requirements.lock.txt` and the two npm
lockfiles. Nine editing roles are planned, with AV Evidence and Speech/ASR as
separate modules and HTTP nodes in the same main n8n workflow. AI role endpoints
remain future work; only runtime preflight and
`/health` exist in the editing service. Original storage is mounted read-only at
`/data` and `/app/original-store`; a separate editing volume owns `/app/data`.
See the [final two-worker architecture](docs/stage63/stage634-two-worker-architecture.md)
for Compose/canary setup and approval gates. No cutover of the old worker is planned.
The [final pre-push review](docs/stage63/stage634-final-readiness.md) records the
nine-role mapping, full regression and remaining image build gates.

See [Git source readiness](docs/stage63/git-readiness.md), the explicit
[safe file list](docs/stage63/git-safe-files.txt), and
[Docker runtime preparation](docs/stage63/stage634-docker-runtime.md).
`.dockerignore` admits runtime/build source only; private configuration, media,
historical archives, and generated outputs remain outside the image. A first Git
commit does not restore `data/` or prove a Docker build or VPS runtime test.
