# Stage 5.4: Adaptive Creative Director & independent plan validation V0.3

The local entry point is `scripts/run_adaptive_director_v03.py`. It reuses canonical analysis, enriched Director Input, Stage 5A/5B receipts and Stage 5C bundles. It does not rerun ASR, Gemini analysis or audio/visual generation, and does not render/publish. Stage 5C validation replays local source measurements to check derivation. Use the existing `.venv-av/bin/python`; no new dependencies are required.

## Prepare a source-bound request (offline)

```sh
.venv-av/bin/python scripts/run_adaptive_director_v03.py prepare \
  --video data/test-videos/mandala-original.mp4 \
  --metadata data/analyses/universal/mandala-original.media.json \
  --analysis data/analyses/universal/pak-fuad-universal-v02.canonical.json \
  --director-input data/analyses/av-v01/pak-fuad.final.v01/director-input.enriched.v03.json \
  --av-bundle data/analyses/av-v01/pak-fuad.final.v01 \
  --speech-bundle data/analyses/speech-v01/pak-fuad.remote.v01 \
  --output data/analyses/director/adaptive-v03/pak-fuad.prepared.NEW
```

Every output directory must be new. Substitute arbitrary verified source/evidence paths to reuse the same workflow. Original and enriched Director Input fixtures remain separate and unchanged. Regional canonical segments are required for the planning intake; a schema-valid empty regional timeline is rejected rather than treated as meaningful semantic context.

Artifacts: `evidence-packet.v03.json`, bounded `director-request.v03.txt`, and `request-provenance.v03.json`. The packet includes full canonical descriptions, explicit speech eligibility, selected measured events and references. Canonical `transcript_text` remains an unverified model claim; ineligible ASR draft text is quarantined and excluded from eligible text. Draft file hashes are retained for audit. The existing Stage 5A gate cannot certify transcript/alignment attachments: V0.3 refuses any attempt to promote its false eligibility flags. A future gate update requires explicit code/contract changes, never an exit-code shortcut.

Selection limits are 12 measured events per modality, deterministically ranked by transition kind and measurement magnitude. Entire source-bound artifacts remain referenced by hash. This truncation can omit a useful hook; it is not a semantic quality ranking. Correlation event references may point to events outside the prompt selection; Stage 5C replay checks the full artifact. Local hashes establish consistency, not independent authentication.

## Offline response replay

```sh
.venv-av/bin/python scripts/run_adaptive_director_v03.py run \
  --prepared data/analyses/director/adaptive-v03/pak-fuad.prepared.NEW \
  --response-file data/analyses/director/adaptive-v03/offline-response-fixtures/pak-fuad.mock.v03.json \
  --output data/analyses/director/adaptive-v03/pak-fuad.offline.NEW
```

Offline fixtures are explicitly labeled `offline_fixture`. For previously saved model output, use `--replay-kind saved_response_replay`. Neither mode claims new inference. Legacy V0.2 JSON/envelopes remain readable as untrusted saved outputs but are not auto-upgraded: their schema fails V0.3, the original stays intact, and the rejected output is quarantined beside a BLOCKED report. The legacy agent contract and V0.2 validator retain their original behavior for legacy requests.

## Approved model inference

Only after the human approves the specific intended call:

```sh
.venv-av/bin/python scripts/run_adaptive_director_v03.py run \
  --prepared data/analyses/director/adaptive-v03/pak-fuad.prepared.NEW \
  --live-approved --output data/analyses/director/adaptive-v03/pak-fuad.live.NEW
```

Uses existing isolated OpenClaw 2026.9.9 and Node v24.21.0 with `openclaw infer model run --agent mandala-video-director --local --json --prompt ...`. Local means local transport to the configured model provider, not an offline model. It is billable and requires approval. No second framework or provider client is introduced. The lean command does not load agent tools/bootstrap/MCP/session; the prompt explicitly supplies V0.3 instructions and the full output schema. No videos are uploaded by this Director invocation. Credentials are resolved internally by OpenClaw; this code never opens `.env.asr` or prints provider config.

One wrapper invocation, no automatic retry/repair. Internal provider behavior is not independently observed; wrapper count does not certify network request/billing count. Provider/model identifiers in the receipt are provider-reported, not independent model-weight proof. Editing choices belong to the model prompt; production code has no sample-specific genre routes, named hooks or manual editing templates.

## Contract and independent checks

`adaptive-editing-plan.v0.3.schema.json` defines one/two variants, concept/message, evidence-bound first-shot hook, ordered source windows, precision, speed/freeze/crossfade parameters, structured overlay/subtitle/zoom/crop/audio/effect proposals, caption provenance, claims, review requirements and explicit approvals. Unsupported custom operations require implementation review. Other unknown operation kinds are rejected. No FFmpeg filter availability is used to assert renderer support.

Estimated duration = sum((end-start)/speed + freeze) - overlaps, rounded to two decimals. Speed 0.8..1.25, freeze 0..2 s, crossfade >0..0.5 s; overlap must fit both adjacent shots, and incoming+outgoing must fit each shot. Cut overlap is zero; final transition is cut/zero. Output operation windows must fit the named shot and output duration. No values are silently repaired. These mathematical rules preserve the legacy V0.2 timing convention without importing its side-effectful validator.

Independent `validate_adaptive_director_plan_v03.py` checks source/packet hashes, evidence IDs/ranges, precision promotion, ordered IDs, arithmetic, feasibility, source repetition/reordering, conversational event truncation, speech uncertainty, onset/beat claims, caption/claim provenance, meaningful variant differences and renderer honesty. Variant comparison uses source windows/order, duration, timing treatment, actual operations/CTA and audio synchronization; names and explanatory prose are ignored. Human review still decides whether differences are artistically meaningful and contextually faithful.

Keyword screening is a conservative supplementary safeguard, not an exhaustive semantic proof. No quote, business/vehicle claim or verified text can be authenticated from the current packet. Subtitle text from ineligible/AI-estimated evidence is blocked; null placeholders are review proposals. Creative copy remains unverified and unpublished. Canonical facts are never independently certified because their model confidence is high.

## Exit codes and approvals

| Code | Meaning |
|---|---|
| 0 | Offline request preparation or structurally safe inspection completed; read the explicit result fields. This is never render approval. |
| 1 | Provenance/path/parse/resource/publication failure. |
| 2 | Invalid plan structure; a parseable rejected output can have a quarantine report. |
| 3 | Structurally valid plan has blocking safety findings. |
| 20 | Explicit render-readiness enforcement failed. |

```sh
.venv-av/bin/python scripts/validate_adaptive_director_plan_v03.py \
  --packet data/analyses/director/adaptive-v03/pak-fuad.offline.NEW/evidence-packet.v03.json \
  --plan data/analyses/director/adaptive-v03/pak-fuad.offline.NEW/editing-plan.v03.json \
  --output data/analyses/director/adaptive-v03/pak-fuad.independent.NEW.json \
  --enforce-render-ready
```

The CLI replays intake before independent validation. `validate_plan(plan, packet)` is a pure library checker whose caller must supply a replay-verified packet; direct calls with invented packets do not establish source provenance. Report schema: `adaptive-plan-validation.v0.3.schema.json`.

`VALID_FOR_EDITORIAL_REVIEW`, `NEEDS_REVIEW`, and `BLOCKED` describe inspection, separately from `BLOCKED_FOR_RENDER`. Stage 5.4 never emits READY_FOR_RENDER. `render_gate_passed`, `render_approved`, `publish_ready`, and `publish_approved` remain false. Both supplied samples require boundary/meaning review. Word-level alignment and reliable musical beat grid are absent. Source-relative estimated timestamps cannot be upgraded by rounding to frames.

## Resource and publication safety

CLI wall-clock deadline: 480 s; one model subprocess: 180 s. Prompt maximum 65,536 UTF-8 bytes; packet 49,152 bytes; model response/plan 131,072 bytes. Existing canonical JSON read cap 8 MiB and Stage 5C source duration/decoding/sample limits apply. Model Node heap is capped at 256 MiB; native memory is not a hard RSS cgroup limit. Input summaries and subprocess output are bounded. Existing FFprobe/FFmpeg helper timeouts and cleanup remain unchanged. Model subprocesses run in a separate group; timeout/overflow/failure kills the group and reaps the direct child. Stderr is DEVNULL and cannot grow a diagnostic buffer. A host init process may need to reap terminated orphan grandchildren.

Reject traversal and symlink escapes beyond project root. Files are published exclusively using the existing fsync + atomic no-clobber hard-link writer. Only an invocation-owned new directory is cleaned on publication failure. Source/input hashes are rechecked before publishing, prepared code/schema/prompt receipts are checked before inference, and credentials in untrusted text are rejected without logging raw values. This is local consistency, not adversarial filesystem race-proof authentication or signed provenance. Never overwrite canonical/source/speech/AV/legacy artifacts.

## Exact Stage 5.5 handoff boundary

Inputs are the plan, replay-verified evidence packet, generation receipt and independent report. A renderer must implement an explicit supported-operation contract (trim/concat and any proposed speed/freeze/crossfade/overlay/subtitle/zoom/crop/audio/effects), validate output time mapping/assets/rights, preserve precision and missing evidence, resolve human speech/context/caption/factual reviews and receive separate execution approval. The current false render gate must stop it. Publishing requires its own future approval and implementation. No Stage 5.5 implementation is included here.
