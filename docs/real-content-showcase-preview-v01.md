# One local real-content Showcase preview

This task authorizes one private local candidate from the existing original
Showcase MP4 only. It does not approve production, publication, music rights,
editorial quality, or Stage 5.6 review. No remote AI/ASR request is made.

## Separate admission, shared engine

`scripts/render_showcase_preview_v01.py` prepares a distinct manual V0.3 plan,
replays source-bound Stage 5C/speech evidence through the existing Director intake,
and independently validates the plan. Structural or temporal blockers refuse
execution. NEEDS_REVIEW is permitted only for this scoped private preview.
V0.3 `render_approved`, `publish_approved`, `publish_ready`, and production gate
remain false; `render_readiness` stays BLOCKED_FOR_RENDER. They are not promoted.

The core encoder has a separate REAL_CONTENT_PREVIEW admission branch. It calls
the scoped permit validator, then uses the same timeline compiler, filter graph,
FFmpeg encoder, resource controls, and technical output verifier as TEST_ONLY.
The production admission function and its refusal behavior are unchanged.
There are no force, ignore-validation, arbitrary source, or arbitrary plan flags.

The source allowlist SHA-256 is
`58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f`.
It must resolve to the original project source path without symlinks/traversal.
The existing BLOCKED live plan/report have independently pinned byte hashes and
remain editorial references. The original plan itself is refused as execution
input. A modified original plan/report also refuses preview execution.

The new authorization binds manual-plan canonical JSON digest, execution-spec
digest, Director packet digest, source identity, capability file SHA, code/schema
receipts, original blocked references, and one versioned destination. Canonical
JSON digests differ from pretty-printed file-byte SHA and are named accordingly.
Capability receipts must pass current-code/environment replay and actual fixture
measurements. Availability alone is insufficient. Older Stage 5.5 receipts are
unchanged historical proofs; changed code requires new synthetic proofs.

The persistent exclusive `real-preview-audit.v01/preview-attempt.v01.json` reserves
the task before encoding. It prevents unrecorded retries. One bounded recovery
is allowed solely for the evidenced failed HEVC allocation attempt with no final
candidate: the original marker, failure receipt and diagnostics remain unchanged,
the source and creative plan must match the earlier grant, a read-only replay
must deliver all 312 frames at 3072 MiB without errors, and no completed preview
manifest may exist. The memory recovery gets exclusive `preview-attempt.v02.json`.
Its failure after approximately 92 seconds, under the 90-second subprocess budget,
is preserved separately; the cause is inferred from elapsed time because the
internal exception was suppressed. A final same-plan recovery at the schema's
180-second maximum requires that failure/spec/authorization chain and gets
exclusive `preview-attempt.v03.json`. No fourth attempt or second final candidate
is permitted. No marker is deleted or
overwritten. Preconditions failing before reservation never start encoding. Unit tests use
private markers and synthetic media; they do not consume or render the real source.

## Manual recipe and limitations

The three candidate source ranges are 0.6–4.1, 14.5–17.5, and 21.2–25.1 s,
preserved chronologically at speed 1, no freeze/crossfade: expected output 10.4 s.
These are manual selections based on existing evidence and sampled source imagery,
not newly inferred AI decisions or verified speech/beat/frame boundaries.

The selected imagery contains a frontal vehicle, wide showroom, and a close view
with an existing return transition. Vehicle/model labels remain unverified
canonical interpretations. Source samples contradict the canonical assertion
that total black begins at 25.1 s; that timestamp is an editorial out-point only.
The renderer adds no flash, neon, title, subtitle, CTA, factual copy, color grade,
external music, or beat synchronization. Source effects inside retained windows
remain in the output.

Source audio is retained with explicit -8 dB gain per shot and 100 ms fade-in/out
per retained audio section. The measured 48 kHz mono downmix peak is 1.639118;
stereo decoded peak is 1.222565. Attenuation supplies encoding headroom, without
claiming to repair existing distortion. Sung phrases may be cut; short fade dips
do not establish musically seamless continuity. Listen at output 3.5 and 6.5 s.

A newly exposed engine bug was fixed: `afade` now uses the operation's enable
window. Without that window, a middle fade-out would silence all later audio,
and a middle fade-in would silence all earlier audio. A real synthetic PCM test
checks signal presence before/after the middle splice and attenuation within it.
Existing endpoint fade behavior remains covered by renderer regressions.

## Files, checks, and resources

Prepared final inputs: `data/render-tests/stage55/real-preview-audit.v01/prepared.v06`.
Current capability receipt: `real-preview-audit.v01/capabilities.v05.json`, backed
by `capability-proofs.v04/{audio,basic,fullhd}`. Development preparations/receipts
are superseded; their code bindings deliberately fail after code changes.

Final bundle: `data/render-tests/stage55/real-content-showcase.v01`. The MP4,
contact sheet, review notes, plan, spec, packet, authorization, independent
validation, timeline, and preview-specific manifest are saved exclusively using
existing atomic writers. Manifest-last marks completion. No original artifacts
are overwritten. Temporary encoding work is restricted to private directories
under the project audit root and removed on completion/failure.

Preview limits: 2 codec threads, 1 filter thread, 180 s per subprocess, 3072 MiB
address space, 64 MiB file limit, 64 MiB FFmpeg allocation limit, 16 MiB disk
reserve plus the output ceiling. CLI deadline 600 s. Stdout is bounded, stderr
discarded, children terminated/reaped on failure. One project render lock prevents
concurrent encodes. This is not an adversarial filesystem sandbox or VPS benchmark.

Verification checks H.264/yuv420p, AAC stereo 48 kHz, 1080x1920, 30 FPS, expected
duration with frame/AAC tolerance, monotonic continuous decoded PTS, full decode,
output peak/RMS, and output byte SHA. All decoded output frames are additionally
downscaled to 54x96 luma; frames with >=98% pixels below 26/255 block completion.
This threshold scan cannot prove semantic quality or identify every local defect.
Geometry preserves source portrait aspect ratio; no new bars or stretching is
requested. Presentation sampling at 1/30 s is not editorial frame verification.

The manifest records PREVIEW_ONLY, NOT_APPROVED_FOR_PUBLICATION, production and
publish approvals false, and PENDING_MANUAL_REVIEW. Contact sheets are sampled
inspection aids, not playback, auditory review, or artistic certification.

The one authorized render is run only after preparation and tests:

```sh
.venv-av/bin/python scripts/render_showcase_preview_v01.py render \
  --prepared data/render-tests/stage55/real-preview-audit.v01/prepared.v06
```

After completion this command is intentionally non-repeatable under the consumed
permit. Open the saved result rather than rerendering it.
