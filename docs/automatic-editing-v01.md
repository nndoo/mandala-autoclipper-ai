# Stage 5.9 automatic private editing

Run with `.venv-av/bin/python scripts/run_automatic_editing_v01.py`.
This workflow uses the existing source analysis/evidence intake, isolated
OpenClaw Director/Reviewer, remote ASR configuration, bounded FFmpeg renderer,
exclusive bundle writers and renderer lock. It does not grant production or
publication permission. Historical plans, raw responses and receipts remain intact.

`proof --output data/revisions/stage59/automatic/capabilities.VERSION` creates
fresh synthetic visual, audio and text capability proofs. Code or environment
changes invalidate them. The visual registry replays existing closed fixtures;
text proof checks actual fade, pop, short slide, safe-area pixels and moving
word color. Audio proof checks full decode and source-waveform correlation.

`prepare --packet PATH --proof PATH/proof.json --job
data/revisions/stage59/automatic/JOB --compare V4_MP4` replays the existing
source-bound evidence packet, saves timestamped source images and reserves ASR
calls where source classification requires speech. `run --job JOB` starts or
continues the bounded job. Prepare requires already authorized private media/API
scope. Both commands can make paid calls; proof is synthetic/offline.

The Director sees image attachments, source observations, allowed evidence IDs,
speech units, bounded capabilities and concrete prior diagnoses. Its complete
proposal selects shot count/duration, source ranges/speeds/reframes, optional
numeric grading, transitions, typography, relative text layout, animations,
creative captions, speech grouping and audio treatment. No fixed four-shot or
duration recipe is injected. Cinematic captions are Indonesian, cover more
than half of selected shots and leave text-free breathing room.

Independent admission validates JSON, source identity, evidence IDs, existing
visual-plan validation, speech timing/coverage and executable text/animation parameters.
Policy `automatic-preview-policy-0.2.0` reports `blocking_findings` separately
from `advisory_findings`; each carries code, category, severity and diagnosis.
Caption density, text-free pauses, the preferred 22 characters/second reading
rate, conservative safe-area envelopes and estimated collisions are advisories.
They guide the Director and actual-MP4 review, not automatic rejection.
The deterministic conversion copies AI choices into the existing visual/audio
compiler. Text uses a typed libass compiler; arbitrary ASS tags, filters, paths,
fonts and expressions are rejected. Dialogue phrase text stays visible while
active word color follows only actual provider word intervals. Word highlighting
does not claim forced alignment or human verification. Relative layout and
animation choices apply to the whole phrase without resetting on each word.

Only `AUTO_PREVIEW_ELIGIBLE` can obtain a new one-use Stage 5.9 private permit.
ASR with valid segment times falls back to phrase subtitles. Longer segments
can be wrapped into at most three short lines using AI-selected word boundaries;
all lines retain the one actual provider interval. No word timestamps are invented.
Segments too long for that layout block admission. The actual source MP4 and transcript are assessed by an independent
model before automatic speech admission; this remains `model_unverified`.
Dialogue currently uses real-time straight cuts outside timed units and original
shot audio. A music-only continuous source bed is independently checked for
range length/headroom and decoded sample mapping.

The old human source-review and publishing gates remain unchanged. The new
automatic contract records `human_verified=false`, `production_eligible=false`
and `publishing_eligible=false`. Model conclusions never populate human review.
Legacy speech gates are reported separately; unrelated legacy blockers remain
blocking. This contract permits automatic private evaluation only.

Every Director invocation reserves its slot before API use (maximum three,
including malformed/failed/interrupted responses). ASR reserves at most two
calls per source region; successful regions are retained and only concretely
problematic regions retry. Raw responses, uploaded-audio fingerprints, request
bindings, timing checks, per-call usage, permits and consumption markers are
append-only. Provider-reported usage is retained; unavailable monetary cost is
explicit, never invented. An interrupted Director reservation is not replayed.
An exhausted job with no eligible candidate emits `stopped.json`, a CLI notification and exit 20.
It does not ask a user to edit individual shots or silently replenish a budget.
`revalidate-speech --old-job JOB --output NEW_BUNDLE` creates a fresh validation
lineage using immutable cached ASR bytes after a validator correction. It performs
zero ASR calls and preserves exhausted region budgets; one independent source
Reviewer call checks the cached transcript before any eligibility is claimed.

Each accepted plan gets a fresh permit. Actual encoded MP4s are preserved even
if later QA fails. Technical QA includes full decode, CFR timestamp checks,
duration/resolution/codecs, stereo sample headroom, continuous audio mapping,
every-frame near-black scan, and text visibility against a matched no-text
control. Several samples per cue (including active word centers) are checked.
Pixel visibility is not OCR or semantic certification. The AI Reviewer receives
the actual MP4 and provides typed issues. Framing, repetition, jump cuts, pacing,
text styling, caption density, audio balance and ending are editorial advisories.
Actual unreadable, clipped or invisible text, uncertain subtitles, unsupported
claims, decode errors, clipping and audio discontinuities remain blockers;
model severity cannot downgrade them. `revision_required` expresses a recommendation,
not admission. The workflow tries to improve any remaining advisory within three
Director reservations. At exhaustion it selects an eligible candidate with the
fewest major editorial notes, then fewest total notes, then newest attempt.
It saves `AUTO_PREVIEW_COMPLETED_WITH_NOTES` when advisories remain. A malformed
later proposal does not erase an earlier eligible candidate. Candidates must
replay their source, validation, MP4, current code/environment and Reviewer bindings.
Reviewer output and technical
measurements are separate from the unperformed human review. V4 comparison
uses decoded frames from both actual MP4s; pixel change is not artistic superiority.

There is no deployment, publication, Stage 6 transition or human approval API.

`reevaluate --job HISTORICAL_JOB --proof CURRENT_PROOF --output NEW_BUNDLE`
replays stored MP4s and projects saved Reviewer issues through the current policy.
It creates new reports only: no inference, original-content rendering, permit,
budget reset or historical receipt edit. Technical decode, timestamps, black-frame
scan, stereo headroom and audio mapping are measured again. Historical matched-control
text measurements remain explicitly historical; no new visibility/OCR certification
is inferred. An old preview with an unsupported claim remains BLOCKED.

Conservative geometry warnings are checked using real output pixels and the model
readability review. A padded synthetic libass raster independently detects actual
glyphs beyond the frame; it does not reject text merely because a character-count
estimate is wide. The synthetic capability proof tests both a complete and a
deliberately clipped glyph layout.
