# Stage 5.9 — evidence-grounded editing quality

The Director prompts now ask for a source-specific hook, progression, pacing,
ending, and restrained treatment. A second variant must differ in actual source
selection or treatment, not merely wording. The revision prompt reads issues and
speech eligibility from the supplied packet; it no longer assumes Showcase music,
ghosting, or a 10–15 second target for every source. Prompt changes apply only to
new requests. Historical model responses and their receipts remain untouched.

The existing plan validator, adaptive-text roles, renderer capabilities, and
speech gate remain authoritative. The renderer currently supports cuts,
crossfades, static crop/zoom, bounded speed, color adjustment, audio gain/fades,
and burn-in text with position and font size. It does not claim animated
trajectories, speed ramps, selectable text colors, word highlights, or independent
word timing. New effects require a validated plan, an execution contract,
synthetic physical proof, and a new source-bound preview authorization. No effect
was added simply to increase the feature count.

`revision_quality_v01.compare` now includes optional `measured_changes` in the
existing comparison contract. When both QA reports contain decoded PCM and
sampled video measurements, it reports RMS/peak, source audio-jump counts,
fingerprint changes, and duration. Missing measurements yield `UNAVAILABLE`.
Different fingerprints or lower RMS do not establish better storytelling, better
music, or better speech intelligibility. The existing independent validator and
human-review requirement still decide whether a preview can advance.

`data/benchmarks/stage59/quality-baseline.v01/baseline.v01.json` is a new,
source-bound offline comparison of the historical Showcase V1 and V2 previews.
Those videos predate Stage 5.9. Pak Fuad has text review but no reviewed segment
alignment or semantic-cut eligibility; Stage 5.8B remains partial. This stage
does not run paid inference or create a new real-content render without separate
authorization, and it does not grant production or publishing approval.
