# Stage 5.8 benchmark V0.1

Use `.venv-av/bin/python scripts/run_benchmark_v01.py`. This CLI reuses existing
Universal/AV/speech intake, Director, independent validator, renderer compiler,
bounded subprocesses, technical QA and multimodal Reviewer. It adds registration,
benchmark admission/checkpoints, source mapping and evaluation; no server or
alternate editing policy is introduced.

## Versioned source mapping

The Stage 5.7 defect originates in assigning `qa.source_ranges(...visual timeline)`
to every finding. The normalized audio measurement used the independent soundtrack,
but the finding producer subsequently attached visual source timing. Existing
reports and receipt-bound code remain unchanged.

`benchmark_evidence_v01.quality_v02` emits a new contract with the exact historical
report reference and per-issue digest. Every mapping contains `output_range`,
`visual_components`, `audio_components`, separate mapping status and unmapped
intervals. Audio consumers must use `audio_components`; legacy `source_ranges`
remains historical visual context. Independent replay rejects changed mappings.

Per-shot passage mappings preserve speed and overlap. Held visual frames are
declared out-point references, not newly frame-verified PTS; their freeze audio
is explicit planned silence when supported. A continuous bed has its own source
passage/gain/fades. Original audio mixed with a bed and external asset components
stay separate; nonlinear treatments are disclosed, without waveform-equivalence
claims. No temporal range means unavailable mapping. Missing audio provenance
produces unavailable/partial intervals, never a visual range substituted for audio.

## Dataset and evaluation

Register validated prepared Director bundles for actual sources within
`data/test-videos`. Preparation replays Universal Analysis, metadata/FFprobe,
SHA-256, AV and speech contracts through the existing intake. Registry entries
preserve uncertain/mixed characteristics and their model-derived basis. Rights
remain UNKNOWN. Unclassified local MP4s are discovery records, not invented
editorial genres. Additional real categories remain NOT_TESTED.
The existing local canary is 256×448, 9 seconds, 5 FPS. It is recorded as
BLOCKED_MEDIA_POLICY under the unchanged 10–60 FPS renderer policy; an ineligible
discovery record does not prevent registration of the two qualified real sources.

Criteria relevance follows speech/music presence and uncertainty. It does not
prescribe shot order, effects, transitions, duration or a dialogue/cinematic
template. Technical, content preservation, editorial, grounding and human layers
are separate. No aggregate grade fills unavailable dimensions with positive scores.

Synthetic control generation uses the existing closed TEST_ONLY color/tone
fixtures, including continuous bed and explicit mixing. They prove technical
behavior, not actual dialogue preservation or promotional editing quality.

## Replay and comparison

Showcase replay verifies V1/V2 receipts, current source/bytes, full decode, PTS,
audio mapping, capability proofs and historical model response generation.
Cached outputs are explicitly historical, never fresh inference. New QA V0.2
and comparison artifacts are exclusive outputs.
Showcase V1 visual selection was a manual Stage 5.5 POC. Its initial live Director
plan was blocked. Stage 5.7 supplied a genuine live AI audio-only revision. This
history does not demonstrate autonomous initial visual selection or multi-genre
editorial success.

Visual differences use actual full decoded `framemd5` records: frame pixel hash,
PTS, duration and size. Identical frames/timing prohibit visual improvement
claims. Timestamps and durations are normalized using the decoded stream's time
base and exact rational arithmetic. Missing time bases are blocked. Pixel/timing
change alone does not prove quality improvement. Declared
shot/audio processing differences remain separate from actual media differences.
Absolute model judgments and disagreements are preserved. Technical audio
mapping is separate from unverified phrasing and subjective overall quality.

Human scorecards bind exact MP4 and optional baseline SHA. Ratings begin null,
permit NOT_APPLICABLE/UNAVAILABLE, and allow timestamped comments. Comparative
audio/visual/overall judgments are separate. An overall positive judgment cannot
become an audio improvement claim. Old feedback cannot transfer to another output.
To consume a completed scorecard, save it as a new file and replay with
`--human-scorecard <file>` into a new output bundle; templates/history are not
overwritten. Human declarations are not authenticated production approval.
Completed human data is embedded in comparison and its input file is referenced
in the replay receipt. Timestamped comments must fit actual output duration;
inconsistent comparative judgments are rejected. `absolute_quality_dimensions`
retains each assessment's model/signal/deterministic provenance.

## Live mode and admission

One run has maximum one submitted plan, one Director call, two Reviewer calls,
one render, and 1,800 seconds processing. Each command is bounded to 900 seconds
and remaining processing budget. Model wrappers retain their own 180-second,
request/response/heap/output limits. Media helpers enforce AS/CPU/file/output,
thread, timeout, kill/reap and temporary cleanup limits.

Session permission text is stored as `permission_text`, not a credential field.
It records a real user instruction; passing a CLI string alone does not establish
human permission. Live mode requires a registered eligible sample and permission.
Source/input verification occurs before model invocation. Reservations consume
budget before side effects, persist across failure, and never silently refill.
Interrupted reservations require investigation; no automatic retry occurs.

Checkpoints are immutable and chained. Repeated completed/stopped commands return
their existing state. Files and bundles cannot be overwritten, source substitutions
or symlink/path traversal escape the project/approved roots. Preparation and status
are read-only with respect to original artifacts.

Showcase is HISTORICAL_ONLY: no new Director call/render, no reset of the exhausted
Stage 5.7 ledger, including at low-level benchmark admission.

Pak Fuad speech eligibility remains false, text unverified and timing unavailable.
Without independent semantic/boundary review, a trim, reordered dialogue, speed
change or audio modification is blocked. Only a single whole unchanged source can
pass the additional context guard; it must still pass the existing independent
validator and capability checks. No existing BLOCKED plan is renamed or repaired
into an eligible plan. New raw model decisions remain genuinely model-generated.

An eligible preview receives a new source/registry/plan/spec/validator/generation/
capability/destination-bound private permit and one-use consumption marker. The
new admission emits encoder arguments using the same existing compiler and filter
graph; it does not implement a second renderer. All production/publishing flags
stay false. Output is private only, including unknown rights.

Fresh technical QA reuses existing measurements. Its legacy-shaped report is
wrapped immediately in the explicit QA V0.2 mapping contract before benchmark
consumption. Reviewer source and output observations are separate MP4 calls,
strict-validated and stored unchanged; model access remains self-reported.
No ASR or fresh Analyst calls are automatic. Missing canonical/evidence is an
analysis blocker; supplied prepared bundles must already replay-validate.

## Commands

Use new destinations for every command producing a bundle:

```sh
.venv-av/bin/python scripts/run_benchmark_v01.py register \
  --dataset-id showcase --prepared data/analyses/director/adaptive-v03/showcase.prepared.v03 \
  --dataset-id pak-fuad --prepared data/analyses/director/adaptive-v03/pak-fuad.prepared.v03 \
  --output data/benchmarks/stage58/dataset.NEW

.venv-av/bin/python scripts/run_benchmark_v01.py controls \
  --output data/render-tests/stage55/stage58-controls.NEW

.venv-av/bin/python scripts/run_benchmark_v01.py replay-showcase \
  --output data/benchmarks/stage58/showcase-replay.NEW

.venv-av/bin/python scripts/run_benchmark_v01.py prepare \
  --registry data/benchmarks/stage58/dataset.NEW/dataset-registry.v01.json \
  --dataset-id pak-fuad --mode live_e2e --authorization '<actual current session instruction>' \
  --output data/benchmarks/stage58/pak-fuad.NEW

.venv-av/bin/python scripts/run_benchmark_v01.py advance --job data/benchmarks/stage58/pak-fuad.NEW
.venv-av/bin/python scripts/run_benchmark_v01.py status --job data/benchmarks/stage58/pak-fuad.NEW

.venv-av/bin/python scripts/run_benchmark_v01.py summarize \
  --registry data/benchmarks/stage58/dataset.NEW/dataset-registry.v01.json \
  --run data/benchmarks/stage58/showcase-replay.NEW --run data/benchmarks/stage58/pak-fuad.NEW \
  --output data/benchmarks/stage58/summary.NEW
```

Exit 20 denotes PLAN_BLOCKED or pending human review for an execution command;
failure exit 1 does not imply source/plan approval. Explicit JSON state is decisive.
Offline summary completion is engineering completion, not editorial acceptance.
Stage 5.9, publishing, deployment, credentials, models, ASR, n8n and VPS are untouched.
