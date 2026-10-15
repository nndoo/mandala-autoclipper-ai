# Adaptive Evidence Adapter V0.3 — Stage 5.4.6.4

The offline adapter packages evidence for a future Creative Director. It does
not classify content, select edits, render, or contact OpenClaw/9Router.
Requirements: Python 3.11+ with the existing `jsonschema` dependency, and FFprobe.

The existing isolated Mandala runtime was verified as OpenClaw 2026.9.9 with
Node 24.21.0. Activate it for project commands; no installation or upgrade is needed:

```sh
export PATH="$HOME/.local/share/mandala-openclaw-runtime/tools/node-v24.21.0/bin:$HOME/.local/share/mandala-openclaw-runtime/bin:$PATH"
hash -r
```

The adapter itself does not invoke OpenClaw. Plugin build/regression checks use
the isolated Node runtime; live inference remains outside this offline stage.

## CLI

All four arguments are required. Relative paths are resolved from the project
root containing the script, regardless of the current working directory.
Inputs, schemas, and output must stay inside that root after symlink resolution.

Run from the project root:

```sh
python3 -B scripts/build_adaptive_director_input_v03.py \
  --video data/test-videos/mandala-original.mp4 \
  --metadata data/analyses/universal/mandala-original.media.json \
  --analysis data/analyses/universal/pak-fuad-universal-v02.canonical.json \
  --output data/analyses/director/adaptive-inputs/pak-fuad.director-input-v03.json

python3 -B scripts/build_adaptive_director_input_v03.py \
  --video data/test-videos/cinematic-7693770515172887829.mp4 \
  --metadata data/analyses/universal/cinematic-7693770515172887829.media.json \
  --analysis data/analyses/universal/cinematic-universal-v02.canonical.json \
  --output data/analyses/director/adaptive-inputs/showcase.director-input-v03.json
```

Success exits 0 and prints a JSON execution report to stdout, including full
source SHA-256, project-relative input/output references, and nonblocking
Universal validator warnings. Blocking failures exit nonzero. Existing outputs
are rejected, including dangling output symlinks; use a separately named output
for retries. Unsupported approval flags are rejected.

## Verification and output

- Verify source SHA-256, filename, metadata verification method, and the
  `local-sha256-<first 32 hex characters>` source ID.
- Independently probe duration, resolution, and FPS. Duration/FPS use the
  positive-number `Math.round(value * 1000) / 1000` convention of the plugin.
  Sidecar and canonical source metadata must match exactly at that precision.
- Reuse the Universal V0.2 schema and semantic/timing validator; reject actual
  blocking results. Validate the full Adaptive V0.3 payload before writing.
- Write a complete temporary file in the output directory, then publish with
  an atomic no-clobber hard link. Clean up temporary files on failure.
- Keep four optional evidence references null, renderer capabilities unknown
  and empty, and render/publish approvals false. Allow at most two variants,
  with fewer allowed; preserve utterances and disallow unverified claims.
- Universal evidence timing remains approximate without independent timing
  evidence, even if the analysis claims higher precision. No audiovisual
  finding, transcript, frame boundary, or beat position is independently verified.

The V0.3 payload references the canonical JSON rather than copying its findings.
These references are not immutable: consumers must revalidate evidence if files
change. The execution report is printed, not embedded in the schema-constrained
payload. Generated data fixtures remain ignored by the existing `.gitignore`.

## Offline tests

```sh
python3 -B -m unittest discover -s tests -p 'test_adaptive_director_input_v03.py' -v
```

Tests use temporary projects and mocked FFprobe for failure cases, plus two
real-media CLI checks that require the existing local POC videos. Python socket
connections are blocked during the suite; FFprobe is restricted to the `file`
protocol. Missing real media or FFprobe fails the checks rather than skipping.

Creative Director adaptation, evidence enrichment, rendering, quality review,
and OpenClaw runtime compatibility remain outside this stage.
