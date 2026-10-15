# Reusable offline speech review checkpoint

Use `.venv-av/bin/python -B scripts/prepare_speech_review_v01.py --report NEW_SOURCE_BOUND_ASSESSMENT --output-dir NEW_REVIEW_DIRECTORY`.

Optional `--feedback` and `--candidates` accept bounded JSON objects containing `items`. Feedback must have origin `user_supplied_feedback`, matching source_sha256, exact segment_id, from/to lexical correction, and user_statement. Each correction must match exactly one whole word. Candidate fields are candidate_id, label, basis, source_windows; these remain review suggestions, not an AI-generated plan. All files use existing guarded project paths and exclusive writers.

HTML uses the original video and source-relative timings, plus a bounded PCM waveform with 20 ms min/max bins. It creates no audio/video derivative. Exported human_review_notes_unaccepted are intentionally incompatible with review_submission: a renderer cannot treat notes as an accepted human review. No automatic statement about listening, boundary accuracy, sentence context or speaker identity is emitted. Reviewers must supply these themselves. Existing speech_intelligence_v01 accept-review and source-bound replay remain authoritative after actual feedback is received.

Missing words are never synthesized. Per-segment subtitles and final plan/admission remain deferred until real source review. A lexical correction is not full-transcript approval. Source-relative subtitle mapping must later follow validated output trim/reorder; future engine changes must preserve operation-specific review and existing independent plan gates. No fixed dialogue genre or real-video timing recipe is introduced.

Current real checkpoint: data/benchmarks/stage58/stage58b-speech-preview.v01/report.md. Stage 5.9 must not start.
