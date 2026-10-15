# Speech Evidence Provenance Gate — Stage 5.4.6.5A

Offline inspection only: no ASR generation, alignment refinement, editing, or
Director Input updates. Requires the existing Python/jsonschema, FFprobe, and
FFmpeg installations. It reuses the V0.3 adapter's path checks, strict JSON
loader, source verification, schemas, and atomic no-overwrite writer.

## CLI

Relative paths start at the project root, regardless of working directory.
All supplied paths must resolve inside that root. Optional evidence may be
omitted; explicitly supplying a missing file is an execution error.

```sh
python3 -B scripts/check_speech_evidence_provenance.py \
  --video data/test-videos/mandala-original.mp4 \
  --metadata data/analyses/universal/mandala-original.media.json \
  --analysis data/analyses/universal/pak-fuad-universal-v02.canonical.json \
  --audio data/analyses/mandala-audio.wav \
  --transcript data/analyses/mandala-whisper.json \
  --alignment data/analyses/aligned-v2/aligned-timeline.json \
  --review data/analyses/transcript-review.json \
  --output data/analyses/provenance/pak-fuad.speech-provenance-v01.json

python3 -B scripts/check_speech_evidence_provenance.py \
  --video data/test-videos/cinematic-7693770515172887829.mp4 \
  --metadata data/analyses/universal/cinematic-7693770515172887829.media.json \
  --analysis data/analyses/universal/cinematic-universal-v02.canonical.json \
  --output data/analyses/provenance/showcase.speech-provenance-v01.json
```

Outputs are exclusive: use a new explicit name for retries. `--audio-stream-index`
selects the global FFprobe stream index; the default is the first audio stream.
No other streams are fingerprinted. Existing evidence formats supported here
are Whisper-style segment JSON and legacy aligned-timeline clip JSON.

## Record contract (`record_version: 0.1.0`)

| Section | Meaning |
|---|---|
| `source` | Full MP4 SHA-256, content-derived video ID, and independently probed media metadata. |
| `metadata_sidecar`, `canonical_analysis` | Input paths and hashes; canonical source-metadata match does not verify model findings. |
| `audio` | Selected stream metadata, available stream indices, normalized PCM fingerprints, existing audio file SHA-256, and comparison status. |
| `speech_requirements` | Required/not-required/review regions from canonical audio layers, classification conflicts, and temporal coverage; these model observations remain unverified. |
| `transcript`, `alignment` | Artifact paths/hashes; separate file identity, structure, source association, generation provenance, text accuracy, and timing statuses. |
| `transcript_review` | Whether review windows claim corrected text/review completion, without trusting those claims as proof. |
| `evidence_eligibility` | Attachment flags and blocking reasons, independent of inspection success. |
| `inspection_tools` | Actual local FFmpeg/FFprobe versions used for this inspection. |
| `warnings`, `limitations` | Preserved Universal validator warnings and limits of the inspection. |

Evidence statuses are `verified`, `unverified`, `unavailable`, or `failed`.
Verified artifact byte identity or structural validity does **not** verify
generation, words, speakers, or speech cuts. `reported_generation` copies only
known supported fields from the artifact and remains self-reported.

If present, declared `source_sha256` and `audio_pcm_sha256` are inspected at the
artifact root or in its `provenance` object. Invalid/mismatched declarations fail
association; matching declarations still cannot prove historical generation.
This stage has no independently observed/trusted generation receipt verifier.
Therefore supplied legacy transcript/alignment attachment flags remain false.
Review claims and claimed frame verification never promote accuracy statuses.
Legacy path references are checked without following references outside the
project or repairing their paths. Transcript/word ranges are checked only for
structural validity and source-duration bounds, not for accuracy.

## Exit codes and eligibility

- **0:** inspection completed and a report was written, including when evidence
  is mismatched, malformed, or ineligible. Consumers must inspect eligibility
  flags and blocking reasons, not treat exit 0 as attachment approval.
- **1:** blocking execution/provenance error, such as source hash mismatch,
  missing required/supplied file, unsafe path, resource limit, decode failure,
  timeout, or existing output. No new partial report is published.
- **2:** invalid CLI arguments.

Eligibility is `ineligible`, `needs_review`, or `not_required`. No-speech regions
do not require transcripts. Music vocals alone do not trigger ASR. Mixed content
uses segment audio layers; unknown or insufficient audio evidence stays under
review. This checker does not independently classify speech acoustically.

After the targeted 5A remediation, `speech_requirements` adds
`classification_conflicts` and `temporal_coverage` without removing prior fields.
Coverage uses the union of valid segment intervals from zero to source duration;
overlaps are not counted twice and any uncovered interval requires review. No
tolerance silently fills gaps in the model's approximate timestamps.

- `absent_profile_with_regional_speech`: an absent profile contradicts a speech
  region. The region remains required and the conflict is explicitly reported.
- `present_profile_without_regional_speech`: a present profile contradicts
  complete, examined, known non-speech regions. Overall handling becomes
  `needs_review`; music-only regions remain `not_required`.
- Uncertain profiles, unexamined audio, unknown layers, and incomplete coverage
  make overall handling `needs_review`. Known speech regions remain `required`
  and still produce `required_transcript_unavailable` when transcript is absent.

The Universal validator emits consistency/coverage warnings; the gate also adds
`speech_classification_conflict:<code>` and `speech_temporal_coverage_incomplete`
to existing eligibility blocking reasons. Coverage is a check of declared model
intervals, not independently verified acoustic coverage. Old provenance reports
are preserved as pre-remediation inspection records and are not regenerated.

## PCM verification and limits

FFmpeg decodes only selected audio to mono 16 kHz signed 16-bit little-endian
PCM. SHA-256 covers PCM bytes without WAV/container headers; byte count must
also match. This proves equality of the normalized audio representations only.
Different decoder versions/resampling builds can change fingerprints; reports
record tool versions. Different original channels can downmix to identical PCM.

Decode limits: 60 seconds, 64 MiB PCM output, one decoder/encoder/filter thread,
and FFmpeg's 64 MiB per-allocation limit (not a total process-memory cap).
Metadata probing, audio-stream probing, and tool-version stdout now share the
V0.3 adapter's bounded subprocess helper: 1 MiB maximum output, 30-second timeout,
streamed reads, and stderr discarded to `/dev/null` without buffering. On timeout
or output-limit breach, the child is killed, reaped, and stdout closed. The helper
uses no temporary files. Atomic report writing still cleans its temporary file
on handled errors and refuses overwrite. Optional JSON evidence has an 8 MiB
limit. Media input protocols are restricted to local files;
PCM is streamed through a pipe. No WAV/MP4 output is produced or overwritten.

## Tests and next-stage proposal

```sh
python3 -B -m unittest discover -s tests -p 'test_speech_evidence_provenance.py' -v
python3 -B -m unittest discover -s tests -p 'test_adaptive_director_input_v03.py' -v
python3 -B -m unittest discover -s tests -p 'test_speech_provenance_remediation.py' -v
```

Tests block Python socket connections and include bounded-subprocess checks,
mocked failure cases, and both actual source videos. Missing actual fixtures or
tools fails those integration tests rather than skipping them.

A future separately approved task could observe transcript generation directly
and capture immutable source/audio/transcript hashes, tool/model versions,
parameters, and execution information. Text/timing review must remain separate.
If report linkage later needs embedding, an optional provenance-report reference
and hash could be proposed for a future artifact schema version. V0.3 is unchanged
in this stage; no report automatically authorizes or attaches speech evidence.
