# Speech Evidence Generation V0.1 — Stage 5.4.6.5B

Setelah uji API nyata dan permintaan pengguna mengganti runtime lokal, default CLI menjadi remote Whisper Large v3; lihat [remote-speech-asr-v01.md](remote-speech-asr-v01.md). Dokumen di bawah menjelaskan mode `--backend local` yang tetap membutuhkan runtime/model tersendiri. Runtime `.venv-asr` yang tidak diperlukan jalur API dihapus atas permintaan pengguna; jangan memasang dependency/model otomatis.

`scripts/generate_speech_evidence_v01.py` runs offline and reuses source/schema/semantic checks and the authoritative Stage 5A speech provenance gate. It never edits Director Input, canonical data, legacy speech evidence, MP4 or WAV. Source and output paths must stay inside the project. An explicit Python executable and local model directory may be outside it (the existing ASR venv and Hugging Face cache are supported). New output directories are reserved exclusively; existing directories, traversal, escaped symlinks and existing output files are rejected.

## Commands

Run from the project root with the normal Python containing jsonschema. The ASR worker uses the existing `.venv-asr`, which does not need jsonschema:

```sh
python3 -B scripts/generate_speech_evidence_v01.py generate \
  --video data/test-videos/mandala-original.mp4 \
  --metadata data/analyses/universal/mandala-original.media.json \
  --analysis data/analyses/universal/pak-fuad-universal-v02.canonical.json \
  --output-dir data/analyses/speech-v01/pak-fuad.v01 \
  --backend local --model small --asr-python /path/to/approved-asr-runtime/bin/python \
  --language id --beam-size 5 --context 0.75 \
  --threads 4 --memory-mib 4096 --timeout 300

python3 -B scripts/generate_speech_evidence_v01.py validate \
  --bundle data/analyses/speech-v01/pak-fuad.v01
```

Use a different, previously nonexistent output directory for a future rerun. `--model` accepts an existing converted CTranslate2 model directory or a cached Faster-Whisper model identifier. `--language auto` enables detection. No model fallback or download occurs. Complete model files include nonempty `model.bin`, `config.json`, `tokenizer.json`, and `vocabulary.json` or `vocabulary.txt`; compatibility is ultimately tested by model loading. Hugging Face snapshot symlinks may reference blobs within the same cache. Other model file symlink escapes are rejected.

**Exit 0 means an assessment was written or validated. Consumers must read `generation_status` and `evidence_eligibility.transcript` / `evidence_eligibility.speech_alignment`; exit code does not imply transcription success or eligibility.** `BLOCKED_MODEL_NOT_AVAILABLE` means no real transcription occurred. Failed/blocked/no-speech runs contain the gate, generation assessment and validation report, with no invented raw/draft transcript, timing or review template. The absence of ASR never upgrades legacy evidence.

## Processing and artifacts

1. Check full source SHA-256, content-derived ID, FFprobe duration/resolution/FPS, metadata, canonical schema and semantic timing/source association.
2. Use Stage 5A regional requirements and conflict/coverage checks. Unknown, conflicting, unexamined or incomplete coverage becomes `needs_review`; ASR is not called. Complete, conflict-free canonical speech absence becomes `not_required`, based on unverified canonical findings rather than independently verified acoustics. Singing is not automatically converted into a speech requirement. Any regional speech keeps speech treatment required, including speech over music.
3. Select speech regions with configurable context (default 0.75 seconds), merge overlapping context, clip only extraction to decoded sample availability. Decode the selected audio stream deterministically to mono 16 kHz signed 16-bit little-endian PCM. Compare capture against the existing independent streaming fingerprint. PCM equality proves only equivalence under these normalization parameters, not historical transcript origin or accuracy.
4. Preflight local model inventory, then execute CPU/int8 Faster-Whisper once. Preserve all raw segment fields, tokens, words, probabilities, per-region language/detection and resolved decoding options. Requested decoding: beam 5, temperature 0, word timestamps on, VAD off, previous-text conditioning off. Installed defaults are recorded by the worker. Explicit language is `id` unless configured otherwise. Raw region timestamps remain unchanged; draft source timestamps are raw times plus the sample-exact source offset. Invalid times are preserved and flagged, never snapped or repaired.
5. Emit leaves `raw-asr.v01.json`, `draft-transcript.v01.json`, `speech-timing.v01.json`, `transcript-review.v01.json`, and `stage5a-provenance.v01.json` only for completed ASR (the gate is always present). Record input/PCM/region/model/script hashes, runtime/tool versions, timestamped execution status and parameters in `generation-provenance.v01.json`. This manifest hashes leaves, never itself or its parent report. `validation-eligibility.v01.json` hashes the manifest, preventing cyclic hashes.
6. The read-only `validate` command recomputes source identity, input/leaf hashes, PCM fingerprints, region extraction hashes/offsets, raw-to-draft/timing projections, quality assessment, review-template bindings and report state. It checks structural consistency, not independent accuracy or authentication. Unsigned local receipts cannot detect coordinated forgery by someone rewriting the entire bundle.

Generation provenance is `recorded` only after an actual completed worker execution. The Stage 5A gate remains unchanged and does not yet independently verify a trusted generation receipt. Its transcript generation provenance stays `unverified`. Text and timing also stay `unverified`; human review stays `pending`. The report copies the existing gate's `evidence_eligibility` contract, and `director_attachments.transcript` / `speech_alignment` remain null. Later consumers must enforce the gate; this stage supplies no rule for promoting attachment eligibility.

## Quality and review

The validator flags empty or missing regional output/text, repeats, suspicious Unicode, language changes, order/overlap, invalid segment/word ranges, unavailable or low confidence, potential music-context hallucination, large gaps and incomplete edge utterances. Thresholds are recorded in the report. These are heuristic review flags, not a guarantee of completeness or correctness. Every completed transcript requires review of utterance boundaries even when other flags are absent. Word timestamps are Faster-Whisper ASR estimates; no installed WhisperX/forced aligner was found. No frame-accurate alignment is claimed.

Keep the generated review template immutable. Copy it to a new submission and, for each reviewed window, retain segment ID, source times and original recognized text; supply `review_status: reviewed`, nonblank `corrected_transcription`, `reviewer_identity`, `review_method` and timezone-aware `verified_at`. Then explicitly approve the identity:

```sh
python3 -B scripts/generate_speech_evidence_v01.py accept-review \
  --bundle data/analyses/speech-v01/future-completed-run.v01 \
  --submission data/analyses/speech-v01/reviewer-submission.json \
  --output data/analyses/speech-v01/reviewer-attestation.v01.json \
  --approved-by 'actual reviewer identity'
```

This records a separate human-supplied attestation and coverage; it cannot authenticate a person merely from CLI strings. It never claims independently verified text/timing, changes raw ASR, or enables attachment. Partial or blank review cannot imply completion. Review claims need explicit actual reviewer approval; agents must not fill reviewer identities or corrections on behalf of a human. Timestamp corrections/alignment need a separate evidence procedure. Pak Fuad's warming-routine exchange is a human review target, never a hardcoded ASR prompt or ground truth.

## Bounded execution

No installation, remote API, model download or external alignment request. Worker sets HF/Transformers offline flags before library imports, disables telemetry and Python socket connections; Faster-Whisper uses `local_files_only=True`. FFprobe and FFmpeg use local file protocol. Metadata stdout is capped at 1 MiB/30 seconds by existing helpers; PCM decode stdout at 64 MiB/60 seconds; worker stdout at 8 MiB/300 seconds by default. Stderr is sent to DEVNULL (zero buffered diagnostic bytes). All subprocesses are killed and reaped on timeout/cap failure. Worker caps address space at 4096 MiB and CPU time at timeout × threads; 4 CPU threads and one model worker, no GPU. FFmpeg uses one thread and 64 MiB maximum individual allocation; PCM is streamed to private temporary files. Its maximum allocation flag is not a total-memory cap. No child processes are intentionally launched by the ASR worker. Temporary PCM/jobs are removed on success or failure. Publishing uses atomic no-clobber hard links and removes only this run's files if publication fails.

Expected legacy `small` multilingual converted model: roughly 0.5 GB disk and approximately 1–2 GiB CPU/int8 RAM, depending on runtime/decoding. These are planning estimates, not measurements of a current run; address-space overhead can be larger. The configured cap is 4 GiB; 300 seconds is a maximum wall time, not a promised speed. No complete model was found in the relevant local caches/configurations during this stage; real ASR remains blocked until an approved complete local model is provided.

## Offline validation

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py'
```

New tests use synthetic source/media/ASR mocks and a real offline missing-model preflight. A successful mock run demonstrates pipeline mechanics only; it is not Pak Fuad transcription or accuracy evidence. Existing Stage 5.4.6.4, Stage 5A/remediation and plugin tests must also remain passing. No Stage 5C or Director integration is implemented here.
