# Stage 5.7 — Source-bound private revision loop V0.1

Entry point: `scripts/run_revision_loop_v01.py`. Use `.venv-av/bin/python`.
The implementation adds revision intake, checkpoints and a versioned source-audio
adapter around the existing Director, Plan Validator, FFmpeg compiler and QA.
No service, database, queue, n8n, deployment or publishing is added.

## Contracts and lineage

`src/schemas/revision-workflow.v0.1.schema.json` defines brief, proposal, execution,
independent revision validation, private permit, checkpoint, comparison, audio
capability and real-preview manifest contracts. Schemas compose the unchanged
Editing Plan V0.3 and execution V0.1 contracts. The embedded plan has an explicit
URN resource ID so its local operation-field references resolve offline.

The brief references original source, parent MP4/plan, QA, timeline, speech/AV
evidence and capability receipts. Intake replays the Stage 5.6 generation, validates
responses against their original requests and reconstructs the final parent report.
Hash-valid but semantically altered QA is refused. Original media and all old
plans, reports and receipts are immutable inputs; output directories must be new.

Confirmed user audio feedback is prioritized separately from earlier editorial
notes. Model/signal findings stay unverified or measured according to their basis.
Positive model dimensions and historical criticisms remain separate conflicts.
Ghosting recommendations trigger source/renderer investigation, not an automatic
visual repair. No numeric quality average overrides a serious finding.

## Director and prompt budget

The same `mandala-video-director` and `run_adaptive_director_v03.live_response`
execute the revision request through existing isolated OpenClaw 2026.9.9 / Node
24.21.0. The invocation is text-only; no video is uploaded to the Director.
Canonical descriptions and measured candidates are source-bound context, not a
claim that the Director observed or heard the original.

The full evidence packet and brief are saved. The model view omits duplicate file
receipts/request paths and ledger artifact/pointer columns, keeps exact IDs,
source ranges, basis and precision, shows the first six selected correlations,
and summarizes repeated parent/review prose and source investigation metrics.
Complete artifacts remain hash-bound. These bounds can omit useful context and
are not a semantic ranking or video-specific editing template.

The full packet SHA is supplied literally; the model must not hash the shortened
view or invent a digest. Identical operation-schema fields are factored into a
common object plus the original parameter-discriminating oneOf branches. Tests
compare valid/invalid operations against the original schema; parameter rules
are not loosened. Prompt <=65,536 bytes, response <=131,072 bytes, one invocation
<=180 seconds, Node heap 256 MiB. Native RSS is not a kernel heap-equivalent cap.
Oversize/invalid input fails before billing; there is no automatic transport retry.

The proposal envelope adds revision/new-plan IDs, parent references, change log,
issue IDs, unresolved risks, audio timeline and numeric execution parameters.
Its nested plan remains V0.3. The original independent validator runs unchanged.
Actual changes compare source windows/order/timing/operations and audio mapping,
not IDs/titles. NEEDS_REVIEW remains NEEDS_REVIEW; production approval stays false.

## Source-audio capability extension V0.2

`renderer_revision_v02.py` uses the V0.1 timeline compiler, visual filter builder,
bounded FFmpeg runner and full-decode/PTS verifier. A separate versioned preview
admission and source-audio filter avoid changing receipt-bound legacy code.
It emits the same H.264/AAC encoder settings for the new admission; it does not
implement a second visual editing policy or alternate rendering engine.

`continuous_source` selects exactly one passage from the same verified original
MP4. Passage length must equal the compiled output duration, with deterministic
source_start + output_time mapping, speed 1, gain <=0 dB and optional endpoint
fades. No loop, padding, external music, hidden passage selection or per-cut fades
are substituted. Missing/short audio, wrong SHA, invalid ranges and contradictory
shot-audio operations are refused. Original mode delegates its behavior to the
legacy graph; legacy speed/freeze/crossfade/captions/effects/assets are unchanged.
Approved original-audio mixing is explicit and receives clipping verification;
mixing does not prove old discontinuities are solved.

Replacement/mix capability receipts require actual controlled color/tone MP4s,
reordered visuals, independent soundtrack frequencies, measured gain/fades,
decode/PTS/codec checks and source/output sample mapping. Validation replays proofs,
code/environment fingerprints and measurements, not just filter availability.
Lossy AAC correlation permits <=1024-sample lag within 200 ms windows; endpoints
inside fades are excluded. This is signal-mapping evidence, not PCM identity,
musical-bar verification, licensing clearance or artistic certification.

## Bounded orchestration and permissions

Checkpoints are exclusive, immutable, chained by file hash and monotonic budgets.
One job starts with one Director call, one Reviewer call, one render and 1200 s
processing budget. A global ledger permits at most two distinct submitted proposals
per parent MP4, even across job directories. Attempt counting starts at independent
validation; invocation, rendering and QA are recorded separately. Repeated rejected
plans stop. A second proposal needs an actionable prior validation/comparison,
remaining budget and authorization; failures never create automatic retries.

`advance` runs permitted transitions until a failure, review requirement, missing
permission/budget or stop condition. Independent CLI actions allow checkpoints to
resume. A reusable project revision lock serializes commands; the existing render
lock separately prevents simultaneous encodes. CLI wall deadline is <=600 s and
remaining processing budget. FFmpeg/FFprobe inherit prlimit AS/CPU/file limits,
thread caps, bounded output, timeouts, direct-child reaping and temporary cleanup.

`--permission-text` records authorization received from the human session; a CLI
argument is not itself proof that permission was granted. Missing authorization
stops before paid inference. Synthetic fixtures never authorize real rendering.
The new private preview permit binds exact Showcase source SHA/path, new live
proposal/spec/validation, parent MP4, current capabilities and destination. A
one-use marker is written before encoding. Old Stage 5.5 authorization and blocked
live plans cannot authorize this render. No force or skip-validation flag exists.

The real-source permit is deliberately limited to the supplied Showcase SHA.
Revision intelligence and the audio/compiler checks are reusable; future real
sources need their own explicit admission scope. No production/publishing protocol
is introduced. All plan, permit, checkpoint, manifest and QA approval flags remain
false except the explicitly separate `local_preview_authorized` field.

## Independent V2 QA and comparison

`revision_quality_v01.py` verifies the new preview contract, then reuses Stage 5.6
sampling, visual/audio measurements, captions, issue assessment and strict response
validation. Audio analysis uses the independent audio timeline; visual joins are
not mislabeled as soundtrack splices when a replacement bed is present.

Only one new Reviewer call uploads the complete V2 MP4. The unchanged, previously
validated original-source response is cached context, revalidated with its OWN
original packet/request. Its packet digest is not rewritten. The merged report
explicitly records context reuse and separate observations. No fresh source call
or joint observation is claimed. Model video/audio access remains self-reported.

Technical QA, AI QA and V1/V2 comparison are separate artifacts. V1 human-confirmed
defects stay historical; fresh V2 human feedback must bind V2 SHA. Acceptance for
private preview requires completed fresh reviews and suitable QA. Without human
listening, NEEDS_REVIEW remains, even if source mapping improves. Critical new
defects block; high concerns request revision; V2 age alone proves no improvement.

## CLI usage

Every output bundle below must be new; authorization text must reflect a real
user instruction. Inspect prepared artifacts and validation before executing.

```sh
.venv-av/bin/python scripts/run_revision_loop_v01.py prepare \
  --qa-report data/qa/stage56/showcase.remediation.live.v02/quality-report.v01.json \
  --audio-capability data/revisions/stage57/audit.v01/audio-capability.v03.json \
  --output data/revisions/stage57/showcase-revision.NEW \
  --target data/render-tests/stage57/showcase-revision.NEW \
  --revision-id showcase-revision-new

.venv-av/bin/python scripts/run_revision_loop_v01.py status --job <job>
.venv-av/bin/python scripts/run_revision_loop_v01.py plan --job <job> --permission-text '<explicit user authorization>'
.venv-av/bin/python scripts/run_revision_loop_v01.py authorize-preview --job <job> --permission-text '<explicit new private preview authorization>'
.venv-av/bin/python scripts/run_revision_loop_v01.py render --job <job>
.venv-av/bin/python scripts/run_revision_loop_v01.py qa --job <job> --permission-text '<explicit V2 Reviewer authorization>'
```

`plan --response-file` is offline_fixture only; it cannot render real content.
`qa` can persist technical results and stop for missing inference authorization,
then resume from its saved technical checkpoint. Failed calls/renders retain
reservations. Current one-call budgets stop additional live revisions; additional
scope must be concretely authorized/prepared, never silently replenished.

The model/comparison's suggestions are not executed as renderer repairs. No
Stage 5.8, publishing, Cloudinary, Metricool, n8n, VPS, package installation,
external media download, commit or push occurs in this workflow.
