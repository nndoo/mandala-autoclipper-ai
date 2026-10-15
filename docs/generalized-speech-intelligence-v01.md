# Generalized speech evidence and semantic continuity V0.1

This is an offline evidence/validation layer. It reuses Stage 5A regional classification, Stage 5B source/PCM/generation replay, the existing Director contract, independent plan validator, and exclusive JSON writers. It does not run ASR, infer semantic correctness, render, or publish.

## Assess a source

```sh
.venv-av/bin/python scripts/speech_intelligence_v01.py assess \
  --video data/test-videos/mandala-original.mp4 \
  --metadata data/analyses/universal/mandala-original.media.json \
  --analysis data/analyses/universal/pak-fuad-universal-v02.canonical.json \
  --speech-bundle data/analyses/speech-v01/pak-fuad.remote.v01 \
  --output data/analyses/NEW.speech-intelligence.v01.json
```

Supply arbitrary source-bound paths for future media. Omit `--speech-bundle` when no evidence exists. Source SHA, sidecar metadata, FFprobe duration/resolution/FPS, canonical schema/identity, existing generation leaves and normalized PCM are replayed through existing helpers. No credentials are read by offline validation. Source hashes are rechecked before publication.

`src/schemas/speech-intelligence.v0.1.schema.json` defines the report, human submission/receipt, and semantic operation report. Files must be new and within the project root. Existing sources/ASR/canonical artifacts are never changed.

The report preserves canonical regional speech/music/layers and their unverified model basis, profile conflicts, coverage gaps, original source timestamps, ASR text/words, nullable reported confidence/language/speaker labels, provider quality flags, overlap uncertainty and separate alignment limitations. Missing timing stays unavailable. Upload context is never converted to an utterance interval. Word-to-segment containment is explicitly labelled a numeric association, not independently verified semantics or diarization.

Eligibility fields:

| Field | Scope |
|---|---|
| `transcript_for_review` | Source-bound client-recorded text is available for inspection; no editorial accuracy certification. |
| `reviewed_transcript` | Every timed segment text has an explicitly accepted source review. |
| `segment_alignment` | All segment endpoints have adequate accepted boundary support; partial coverage does not certify all segments. |
| `word_alignment` | Every provided word is reviewed, every segment has word data, and complete word coverage is explicitly confirmed. Segment timestamps alone cannot satisfy this. |
| `semantic_cuts` | At least one exact selection has adequate accepted text/boundary/context support. It is never permission for arbitrary other cuts. |

`alignment_confidence`/`timestamp_precision` describe the underlying ASR measurement, which remains an estimate. Human review records/error bounds are separate. No frame verification is manufactured. Generation replay is client-recorded consistency, not server/model authentication. Legacy Stage 5A flags remain unchanged and false.

Assessment exit 0 means the report was produced. Read explicit eligibility; required speech can remain INSUFFICIENT_EVIDENCE. Complete conflict-free no-speech classification yields NOT_APPLICABLE based on canonical model findings; uncertain speech never becomes silently absent.

## Explicit human review

Use `$defs.review_submission` to prepare a source review with original report digest, source SHA, reviewer identity, listening/waveform procedure, exact original text hashes, reviewed text, boundary error estimates, optional per-word reviews/coverage, exact ordered selection windows, context dependencies and optional exact subtitle mappings. Accuracy/context booleans must reflect an actual review, not model confidence. Review every required question/answer dependency and overlapping/speaker/music ambiguity.

Only after that human explicitly supplies/approves the review:

```sh
.venv-av/bin/python scripts/speech_intelligence_v01.py accept-review \
  --report data/analyses/ORIGINAL.speech-intelligence.v01.json \
  --submission data/analyses/HUMAN.submission.v01.json \
  --approved-by HUMAN_IDENTITY \
  --output data/analyses/NEW.accepted-review.v01.json
```

Then create a new assessment with `--human-review` referencing that receipt. Its source/report/submission/code hashes are replayed. Duplicate or contradictory reviews, wrong actors/source/text references and changed artifacts are rejected. The acceptance receipt is an explicit local human attestation; the software does not cryptographically authenticate a person or prove they listened. AI-generated review statements are not independent proof and must not be submitted as human approval.

Stage 5.8B also supports `review_method=user_supplied_review_notes` for explicitly endorsed per-segment text notes. `accept_speech_text_notes_v01.py` requires exact source/report/text hashes, every segment reviewed, a reviewer identifier and a direct user text endorsement. It preserves the original notes, including `accepted=false`, and creates a separate text-only receipt. It never claims that listening or waveform inspection occurred. This method forbids boundary, word, selection, context-link and subtitle review assertions: qualitative notes cannot supply measured timing or detailed semantic proof. Text eligibility may become true while segment/word alignment and semantic cuts stay false. If producer receipts changed, the importer compares the original and freshly replayed assessments after removing only code receipts; all other source/evidence values must match.

`prepare_segment_subtitles_v01.py` prepares non-executable source-bound subtitle JSON and SRT from accepted text. It maps complete segment cues to selected output windows, including reorder/reuse, rejects windows that split a segment and rejects overlapping captions. Layout uses the existing safe-area/font/control-character validator. SRT rounds display timestamps to milliseconds; the underlying source/output values and ASR precision remain explicit in JSON. These drafts do not authorize rendering or bypass the independent subtitle timing gate.

The original remediation had no accepted human reviews for real samples. Stage 5.8B subsequently received explicit per-segment user text notes (including “panasi”); these support text only. Real source timing and detailed semantic selection attestations are still pending. Positive timing tests use clearly labelled synthetic fixtures with mocked source/ASR validation.

### Source timing review for Stage 5.8B

The reviewer supplies an actual listening/waveform procedure, measurements and semantic decisions. `subtitle_source_reviews` is an optional source-level layer: segment ID, exact accepted text, corrected source span, explicit error and accuracy confirmation. Confirmed source span endpoints can support exact cut boundaries with the same error bound. Full segment alignment requires adequate coverage of every segment. These spans never change raw ASR timestamps or create word alignment. Subtitle planning and the Director ledger use adequate corrected spans; ASR-only timing remains explicitly unverified.

Independent subtitle validation can reuse a confirmed source cue under an exact, unchanged-rate source/output mapping, without depending on a particular model operation ID. Changed words, source windows, speed/freeze/overlap or unsupported semantic selections remain blocked. Source cue confirmation is not global cut permission; reordered selections need their own explicit ordered context review.

Codex must receive the actual review decisions directly from the user, then use the existing `accept-review` receipt/assessment replay. Text hashes, source, original report and producer hashes stay authoritative. Reviewer statements must never be inferred from prior qualitative notes or an AI plan.

## Director and independent validator

Existing Director intake accepts optional `--speech-intelligence` on `run_adaptive_director_v03.py prepare`. It replays the report and binds its reference in the packet and generation inputs. Legacy transcript/alignment attachments retain their original contract. Ineligible ASR draft text is quarantined. Accepted reviewed text is separate and references the actual human review in the evidence ledger; precision remains explicit.

The existing `validate_adaptive_director_plan_v03.validate_plan` invokes the shared semantic evaluator. Stage 5.7 revision validation already calls that validator; Stage 5.8 readiness uses the same evaluator and replays attached reports. Thus unsupported speech cuts are blocked through the existing consumers. Plan schema, factual checks, operation capabilities, source identity and render/publish gates remain mandatory.

`scripts/speech_planning_v01.py` also supplies versioned `prepare`, `audit-plan`, `validate-plan`, and `validate-revision` CLI adapters and a render-readiness function. Prepared packet/prompt/receipt are deterministically replayed; modifying both prompt and hash cannot bypass the policy check. These adapters do not provide a second model transport.

```sh
.venv-av/bin/python scripts/speech_planning_v01.py audit-plan \
  --prepared data/analyses/CURRENT.prepared \
  --speech-report data/analyses/CURRENT.speech-intelligence.v01.json \
  --plan data/analyses/SAVED.editing-plan.v03.json \
  --output data/analyses/NEW.semantic-plan-validation.v01.json
```

Code receipts changed for the affected Director producers/validator. Historical requests and generation receipts remain evidence of their original implementation; do not rewrite their hashes or budgets. Prepare new versions offline. Replaying a saved model response is labelled `saved_response_replay`, never fresh inference or new human acceptance.

## Operation safety states

| Status | Meaning |
|---|---|
| SAFE_SUPPORTED_OPERATION | Exact operation preserves complete original context, or has adequate source-bound accepted review. No render approval. |
| NEEDS_HUMAN_REVIEW | Timing/content/speaker/music uncertainty requires review; executable affected operations stay blocked. Null subtitle proposals can remain non-executable review placeholders. |
| INSUFFICIENT_EVIDENCE | Required transcript, boundary, context or provenance support is absent. |
| BLOCKED_UNSAFE_OPERATION | Invalid ranges, rejected selections, missing required context, unsupported facts or unreviewed subtitle claims. |
| NOT_APPLICABLE | The selected regional evidence does not require speech treatment, with canonical limitations preserved. |

Checks cover every variant. Noncontiguous/reordered speech requires exact selection review, precise supported boundaries, sentence/context/meaning confirmation, and speaker/music review. ASR interval intersections identify **possible** interrupted utterances; they are not automatic sentence parsing. Explicit reviewed context links identify missing question/answer or phrase dependencies. Source-window reviews cannot approve speed/freeze/crossfade or audio changes. Unknown speech can preserve a whole unchanged source with uncertainty retained; affected trims remain blocked.

Subtitle support additionally requires exact source/output mapping, reviewed text equivalence, an explicit matching subtitle review and adequate timing accuracy. A different text/range/operation cannot borrow that review. Existing factual-claim checks remain; a transcript does not authenticate a business claim. No language-specific punctuation heuristic or genre editing template is used.

## Resource limits and unresolved evidence

Numerical checks support varying durations/languages/speakers. File intake retains the existing media/decode policies, including selected-stream PCM normalization to mono 16 kHz s16le, 60-second decoder timeout/64 MiB PCM cap and existing source duration limits. Longer sources need an independently bounded chunking intake, not an unlimited decode or relaxed policy.

New assessment JSON is bounded to 512 KiB; arrays to 4,096 items; Director packet/prompt caps remain 49,152/65,536 bytes. Schema validation caches are keyed by schema hash. New CLIs use the existing 480-second deadline, guarded paths, strict JSON, no-clobber writers and temporary cleanup. No new dependencies, models, services or API retries.

Fresh ASR requires a separate source-bound grant. The prepared Pak Fuad request is in `data/benchmarks/stage58/generalized-speech-remediation.v01/asr-authorization-request.v01.json`: one existing Whisper Large v3 request, `verbose_json`/word timestamps, 37.2694375 seconds normalized audio, cost UNKNOWN. Proxy timing support and physical model identity are unverified. API success alone cannot approve edits; independent source review remains required. Real-content preview has its own separate authorization.
