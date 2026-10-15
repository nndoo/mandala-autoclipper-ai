# Mandala Stage 5.5 renderer V0.1

The renderer executes explicit structured operations; it does not choose a story, invent effects, repair blocked plans, or perform AI quality review. Entry point: `scripts/render_video_v01.py`. Existing Stage 5.4 code/contracts/evidence are unchanged. Use `.venv-av/bin/python`; NumPy/SciPy already installed for Stage 5C are reused for technical fixture measurements. No new dependencies, fonts, assets or models are downloaded.

## Admission boundary

There are two separate CLI commands:

- `self-test` accepts only a closed fixture ID, generates controlled local media, rechecks its source/schema/plan/spec/recipe fingerprints, and writes below `data/render-tests/stage55`. It cannot accept a `--plan`, source override or production authorization. Every render is TEST_ONLY in the manifest and MP4 container title, with publishing/production approval false.
- `production` validates the supplied immutable V0.3 plan and Stage 5.4 report, checks plan/packet/source SHA binding and hard approvals, then rejects current plans before encoding. It never routes a blocked plan through the fixture generator. A synthetic identity cannot become a production authorization.

The current V0.3 schema makes `render_approved=false` and `BLOCKED_FOR_RENDER` mandatory; the independent Stage 5.4 validator also never grants rendering. Therefore **no current production V0.3 plan can be executed**, even with a renderer capability receipt. This is intentional preservation of the existing safety boundary, not permission to change those fields. A separately approved planning/review/authorization contract will be required before production execution is enabled. This stage demonstrates real engine execution exclusively through approved controlled fixtures. No Stage 5.4 gate is weakened or replaced.

Width/height/FPS/fit/CRF/preset and thread/memory/wall-time settings can be supplied through bounded execution specs; the self-test CLI exposes these as optional flags while keeping the source and editorial operations closed. H.264/AAC are the initially verified codecs; other codecs are rejected rather than substituted. Decoder/verification helpers obey the configured thread/memory/time ceilings too.

Examples (output paths must be new):

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv-av/bin/python \
  scripts/render_video_v01.py self-test --fixture dynamic \
  --output data/render-tests/stage55/my-run/dynamic

.venv-av/bin/python scripts/render_video_v01.py production \
  --plan data/analyses/director/adaptive-v03/pak-fuad.live.v01/editing-plan.v03.json \
  --packet data/analyses/director/adaptive-v03/pak-fuad.live.v01/evidence-packet.v03.json \
  --validation data/analyses/director/adaptive-v03/pak-fuad.live.v01/plan-validation.v03.json \
  --output data/renders/NOT_AUTHORIZED \
  --report data/render-tests/stage55/my-run/production-refusal.json
```

Production refusal exits 20 and creates only the rejection JSON. No MP4/output rendering directory is created. Renderer validation/resource/publication failures exit 1. Self-test render or capability replay success exits 0 and is explicitly TEST_ONLY. There are no force/ignore-validation/skip-approval flags.

## Contracts and compiler

`render-execution.v0.1.schema.json` binds the exact canonical JSON plan digest, chosen variant, explicit output fit/size/FPS/quality, resource limits, executable operation parameters and approved asset records. This is a separate renderer specification; it does not change the Director's V0.3 speed limits or artistic decisions.

The V0.3 `color_grade` operation contains only prose. It is refused without explicit brightness/contrast/saturation numeric execution parameters. Two specifically named V0.3 custom operations can represent `renderer.audio_fade.v01` and `renderer.normalize.v01`; their numeric parameters must be explicit in the bound execution specification. Arbitrary custom names/filter scripts remain unsupported.

The deterministic compiler uses rational arithmetic for source/playback/output clocks:

- Playback duration `(source_end-source_start)/speed`, with speed 0.8–1.25.
- Freeze 0–2 s adds cloned last retained CFR presentation frame and silence; it does not advance source time.
- Each crossfade subtracts its requested overlap from total length, and must fit both neighbors and combined incoming/outgoing overlap.
- Output operation windows must fit their named shot and total timeline. Effects are explicitly scoped to the output composite, so both shots may be visible during a transition.
- Source caption windows map to `shot_output_start + (source_time-shot_source_start)/speed`. Subtitle text is allowed only for known verified synthetic fixture timing; arbitrary unverified text/ASR cannot become an eligible subtitle.
- Sub-frame source ranges, freeze and crossfade requests are refused before encoding. Requested supported ranges are retained unchanged. Decoding/constant-frame-rate sampling naturally quantizes presentation at 1/output_FPS; verification uses a documented frame/AAC tolerance. Nothing is relabeled frame-verified or speech-safe by rounding.

Only zero presentation-origin, aligned audio/video source clocks and square sample aspect ratio are currently supported. Rotation metadata, nonzero origins/audio offsets, very large source dimensions, impossible overlaps and unsupported combinations are refused, never normalized silently. Source duration is capped at 180 s, FPS 10–60, source area at 8,294,400 pixels and maximum source dimension 4096.

## Actual operations

Trim, reorder, explicit reuse, concat, atempo speed, silence-backed end freeze, hard cut and xfade/acrossfade are implemented. Zoom/crop are normalized static viewports, applied only in requested output windows via a composed branch. Viewports outside the frame are rejected rather than clamped. Fit is explicitly pad or center crop; stretching and tracking are not introduced.

Caption/hook/CTA text is burned with locally available DejaVu Sans/drawtext, outline/shadow, bounded font size, maximum three lines, conservative margins and positioning. Text goes into a private generated text file with `expansion=none`, so quotes, colons, brackets, braces, backslashes and `%{...}` are literal content, not filter expressions. Control/credential-like text and oversized layouts are refused. No user-supplied font or subtitle path is interpolated into a filter.

Supported audio treatment includes timed gain, fixed explicit duck attenuation, FFT denoise, explicit fades, requested whole-output single-pass dynamic loudnorm, and local rights-bound asset mixing. Ducking is not automatic sidechain speech detection. Mixing into a silent source is allowed only when an audio asset is explicitly requested and authorized; the underlying silence is a technical timing base, not unrequested replacement music. Missing/short/orphan assets, wrong hashes or scope/rights are blocked. Existing music rights are never inferred from presence in a source.

Denoise verification proves filter execution/decodability, not human speech intelligibility or echo removal. Loudnorm fixture verification is not a broadcast loudness-compliance certificate. No output is claimed artistically good based on these signal checks.

## Capability receipts

`renderer-capabilities.v0.1.schema.json` separates available filters from verified operations and unsupported/not-tested features. The environment receipt records actual FFmpeg/FFprobe executable SHA/version, encoder/filter inventory and installed font SHA. Missing font blocks text only; filter listing does not certify execution.

Capability verification reopens successful TEST_ONLY bundles, validates their source/plan/spec identity, compiles the same graph, checks output/receipt SHA, decodes the MP4, and remeasures frame/audio fixture behavior. A claimed verified status that cannot be reproduced from these proofs is refused. Capability status is scoped to controlled local technical tests, not production approval or universal combination support.

```sh
.venv-av/bin/python scripts/render_video_v01.py capabilities \
  --bundles data/render-tests/stage55/my-run/basic data/render-tests/stage55/my-run/dynamic \
  --output data/render-tests/stage55/my-run/capabilities.v01.json
```

ASS/libass may be available in FFmpeg, but the exposed, verified caption engine uses drawtext. ASS subtitle engine is recorded not_tested. Animated zoom trajectories, word highlighting/karaoke, arbitrary custom effects, subject tracking and execution from color-intent prose remain unsupported.

## Output and provenance

Each completed bundle contains `render.mp4`, the generated `source.mp4`, optional generated `asset.wav`, `synthetic-plan.v03.json`, `execution-spec.v01.json`, `synthetic-identity.v01.json`, `timeline.v01.json` and `render-manifest.v01.json`.

Manifest V0.1 records source/plan/spec/output SHA, code/tool/font receipts, requested/applied operations, capability scope, input/output mapping, duration, codec/resolution/FPS, execution limits/CPU/time/file size, FFprobe/full-decode/timestamp checks and fixture measurements. It is written last as a completed-bundle marker. It records `editorial_quality_review=NOT_PERFORMED`, production/publishing approval false, and TEST_ONLY authorization.

Verification checks H.264, yuv420p, resolution/FPS, expected duration, requested audio presence/AAC stereo 48 kHz, monotonically advancing decoded presentation times, stream continuity, full decode with `-xerror`, and bounded audio peak/RMS. A clipping-risk output is refused. These are technical checks, not Stage 5.6 AI review.

## Resources and file safety

Default FFmpeg limits: 2 codec threads, single filter/complex-filter thread, 90 s wall clock and CPU limit, 1536 MiB address-space limit, 64 MiB output-file limit, 64 MiB per FFmpeg allocation. Configured resources stay within bounded schema ceilings. CLI total wall clock is 600 s. `prlimit` execs FFmpeg in the same PID; the existing bounded subprocess helper kills/reaps it and discards stderr. Stdout is bounded; output verification caps decoded frame/PCM buffers. There is no queue/server or parallel encoding pool.

An advisory project lock allows one rendering operation at a time. Disk preflight reserves the configured output ceiling plus free-space reserve. Paths must stay in the project and designated test/production roots; all symlinks, traversal and secret `.env*` paths are refused. No network input protocols, downloads or shell commands are accepted.

MP4/source files are fsynced and atomically published via exclusive hard links. JSON uses the existing exclusive writer. Existing bundles cannot be overwritten. On failure, only invocation-owned output files/directories are removed; private temporary work is cleaned. Publication is atomic per file, with manifest-last completion marking; it is not an all-files directory transaction or an adversarial filesystem race-proof sandbox.

## Stage 5.6 boundary

Provide the test MP4s, manifests, timeline mappings, capability receipts and regression/integrity report for technical audit. Stage 5.6 may later assess editorial/audio/visual quality under separately approved scope; no such agent, inference or review is run here. Test results cannot approve existing real Director proposals, publishing, production deployment or workflow changes.
