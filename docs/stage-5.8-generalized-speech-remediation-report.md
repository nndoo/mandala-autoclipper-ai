# Stage 5.8 — Generalized Speech Evidence Remediation

Tanggal: 13 Oktober 2026, Asia/Jakarta. Engineering offline diimplementasikan. **Real speech acceptance dan real dialogue preview belum siap.** Tidak ada paid ASR/Director/Reviewer baru atau render real-content pada assignment ini.

Artifact root (`R`): `/home/kentung/projects/mandala-autoclipper-ai/data/benchmarks/stage58/generalized-speech-remediation.v01/`.

## 1. Root Cause of Existing Speech Ineligibility

Pak Fuad mempunyai respons ASR `json` text-only: satu recognized region, segments/words kosong. Upload context 0–37,2694375 s adalah batas audio, bukan utterance timestamps. Format remote text-only valid untuk penyimpanan draft, tetapi tidak memenuhi kontrak timed transcript Stage 5A.

Reason lama tetap `transcript:malformed_transcript_segments_or_timestamps` dan `transcript:generation_not_independently_observed`. Gate 5A hanya memeriksa declared hashes dan tidak mempunyai verifier generation client yang terintegrasi untuk eligibility. Pipeline baru mereplay receipt Stage 5B sebagai **client_recorded**, bukan independent server authentication. Tidak mengubah reason/status artefak lama.

## 2. Generalized Architecture

Verified MP4/sidecar/canonical → regional requirements existing → existing ASR bundle replay atau unavailable → normalized source-time transcript/words → structured assessment → explicit source-bound human review jika ada → operation-specific semantic checks → Director/independent validator/revision/benchmark readiness.

Tidak ada file-name routing, Pak Fuad dialogue/timestamp hardcode, grammar/punctuation template, fixed hook/shot recipe, model-derived semantic approval atau ASR word scores yang dikarang. Future sources menggunakan fungsi yang sama. Dokumentasi reusable: `/home/kentung/projects/mandala-autoclipper-ai/docs/generalized-speech-intelligence-v01.md`.

## 3. Files Created/Modified

Created:

- `/home/kentung/projects/mandala-autoclipper-ai/scripts/speech_intelligence_v01.py` — assessment, normalization, explicit review acceptance dan semantic evaluator.
- `/home/kentung/projects/mandala-autoclipper-ai/scripts/speech_planning_v01.py` — versioned Director preparation/plan/revision/render-readiness adapters.
- `/home/kentung/projects/mandala-autoclipper-ai/src/schemas/speech-intelligence.v0.1.schema.json` — strict versioned report/review/operation contracts.
- `/home/kentung/projects/mandala-autoclipper-ai/tests/test_speech_intelligence_v01.py` — 90 deterministic offline tests.
- Dua dokumen workflow/report baru.

Modified:

- `/home/kentung/projects/mandala-autoclipper-ai/scripts/adaptive_director_evidence_v03.py:45` — optional source-replayed speech intelligence attachment.
- `/home/kentung/projects/mandala-autoclipper-ai/scripts/run_adaptive_director_v03.py:69` — affected helper/schema receipts dan optional prepare CLI argument.
- `/home/kentung/projects/mandala-autoclipper-ai/scripts/validate_adaptive_director_plan_v03.py` — mandatory shared semantic gate, exact reviewed-subtitle support; existing structural/factual/capability gates tetap.
- `/home/kentung/projects/mandala-autoclipper-ai/scripts/benchmark_preview_v01.py:15` — generalized regional/all-variant safety, artifact replay dan established diagnostic-code compatibility.
- `/home/kentung/projects/mandala-autoclipper-ai/scripts/benchmark_evidence_v01.py:29` — new producers/schema receipts.

Stage 5A/5B ASR implementation/config/credentials, canonical/Universal prompts, model routing, renderer encoding, QA transports dan revision-loop code tidak diubah. Revision loop memakai shared independent validator yang diperbaiki. Original affected Director code disimpan di `R/*.py.before.txt` untuk audit producer sebelumnya.

## 4. Speech Detection and Classification

Reuse regional `speech_requirements`, conflict checks dan temporal coverage Stage 5A. Speech, music, mixed audio, unknown layers dan uncertain profiles dipertahankan terpisah di `classification`/`audio_content`.

Basis selalu `canonical_model_unverified`: **bukan independent acoustic detector atau fakta speaker/music yang verified**. Regional speech memerlukan treatment meskipun region lain hanya musik. Uncertain/gaps/conflicts tidak dibypass menjadi NO_SPEECH. Whole unchanged source dapat mempertahankan semua konteks dengan uncertainty tetap terlihat; affected trims membutuhkan support.

## 5. Transcript Validation

`normalize:81` mempertahankan text/words asli dan nullable probability/language/speaker. Memeriksa finite non-boolean timestamps, source bounds, segment/word structure, word containment, order, duplicate IDs, confidence bounds, excessive arrays dan overlaps. Quality flags generation existing dipertahankan. Low probability hanya uncertainty dari provider, bukan skor linguistic quality baru.

Untimed recognized text terpisah dari segments. Upload context tidak dipromosikan menjadi timing. Legacy artifacts tidak otomatis upgraded. `transcript_for_review` berbeda dari `reviewed_transcript`/editorial support. Exit 0 assessment bukan eligibility.

## 6. Alignment and Timestamp Accuracy

Underlying segment/word timestamps tetap **asr_estimate/unverified**. Word-to-segment association menyebut reported_parent, unique_timestamp_containment, atau unavailable; containment bukan linguistic alignment verification.

Human acceptance membutuhkan exact source/report/text/word hashes, source listening/waveform procedure dan explicit reviewer approval. Segment alignment memerlukan semua endpoint yang relevan didukung. Word alignment additionally memerlukan every-word review dan explicit complete word coverage setiap segment. Partial boundary/word coverage tidak certify whole transcript.

Cut support menggunakan exact reviewed boundaries dengan declared error ≤0,05 s. Angka 0,05 adalah policy limit, bukan confidence/error aktual sampel real. Actual review error harus dicatat manusia. Tidak ada frame_verified label atau word timing dari energy peaks. Human receipts adalah local attestations; identity/listening tidak diautentikasi kriptografis oleh software.

## 7. Semantic Continuity Validation

`evaluate_plan:279` memeriksa semua variant dan operasi. Lima statuses: SAFE_SUPPORTED_OPERATION, NEEDS_HUMAN_REVIEW, INSUFFICIENT_EVIDENCE, BLOCKED_UNSAFE_OPERATION, NOT_APPLICABLE.

Noncontiguous/reordered cuts membutuhkan exact ordered source selections, independently reviewed text/boundaries, sentence completeness, QA context, meaning, speaker dan music-overlap confirmations. Interval intersection menandai **possible interrupted utterance**, bukan klaim otomatis sentence parsing. Accepted context links menolak question/answer atau phrase dependency yang hilang. Human rejection/invalid timing/unsupported caption/factual claims memblokir operasi.

Selection review tidak mengesahkan speed/freeze/crossfade/audio processing. Subtitle additionally membutuhkan exact source/output mapping, exact reviewed text dan matching subtitle review. Mengubah text/window/operation tidak dapat meminjam approval. ASR bukan business-fact authentication. Tidak ada render/publish approval otomatis.

## 8. Integration with Creative Director

Regular Stage 5.4 `prepare --speech-intelligence` mereplay assessment dan menambah source-bound reference/context pada packet. Ineligible draft tetap quarantined; legacy transcript/alignment attachments tetap null/false. Human-reviewed text, jika benar-benar ada, terpisah dan ledger pointer mengacu pada human review, dengan precision explicit.

Fresh current-code bundles: `R/{pak-fuad,showcase}.prepared-base.v03` dan `R/{pak-fuad,showcase}.prepared-speech.v03`. Enriched prompt sizes **54.960 / 57.645 byte**, di bawah 65.536. Packet/prompt/source provenance replay PASS. Tidak ada inference.

Versioned speech-planning adapter mempunyai additional policy prompt dan deterministic reconstruction. Test mengubah prompt sekaligus hash tetap ditolak. Prepared code receipts lama memang historical setelah perubahan producer; tidak dipaksa valid lewat hash rewrite. Development v01/v02 bundles dipertahankan, final acceptance memakai v03.

## 9. Independent Validator Integration

Existing `validate_adaptive_director_plan_v03.validate_plan` sekarang memanggil shared evaluator dan mereplay attached speech report. Blocking semantic findings menjadi blocking findings dalam kontrak report 0.3 existing. Existing source/packet/schema/factual/beat/capability checks tetap berjalan. Real historical Pak Fuad yang sebelumnya NEEDS_REVIEW kini direplay menjadi **BLOCKED**, tanpa mengubah plan/receipt historis.

Stage 5.7 `validate_proposal` memakai validator tersebut; actual revision entry-point regression menolak unsupported dialogue. Stage 5.8 readiness memakai evaluator sama dan source-replayed reports. Render-facing validation tetap terpisah dari execution authorization. `/scripts/speech_planning_v01.py` menyediakan structured combined plan/revision/readiness reports. Renderer production gates tetap false/unavailable.

## 10. Music-Only and Mixed-Content Behavior

Complete conflict-free canonical no-speech tidak memerlukan transcript. Music-only fixture/sampel menghasilkan NOT_APPLICABLE untuk speech; absence adalah model basis, bukan independently verified acoustic fact. Vocal music tidak otomatis dianggap conversation.

Mixed audio mempertahankan regional layers. Speech selections tidak mendapat bypass hanya karena music exists. Unverified speaker overlap, quality flags dan uncertain detection tetap explicit. Actual source could contain unfamiliar structures; no genre-specific edit recipe ditambahkan.

## 11. Pak Fuad Regression Results

Source SHA `000c759ac57ff4c2bfbdfd3e8d678f46d2160ea8855b4ca9bb343ce26c8671f3`, 37,3 s, 576×1024, 30 FPS. Source/sidecar/canonical/remote ASR generation/source PCM replay **PASS**.

`R/pak-fuad.speech-evidence.v02.json`: **INSUFFICIENT_EVIDENCE**, transcript_for_review=true, reviewed_transcript=false, segments=0, words=0, alignment/semantic_cuts=false. Generation client_recorded; timing unavailable; no human review.

Historical last Director response direplay offline: independent **BLOCKED**, semantic **INSUFFICIENT_EVIDENCE**. Reasons: missing independent boundary/context support, noncontiguous/reordered dialogue, unsupported speech audio treatment (denoise); subtitle placeholder masih review proposal. `R/pak-fuad.{semantic-plan-validation,real-regression}.v01.json`.

Saved-response replay generation wrapper_invocations=0/live_inference_performed=false; tidak diklaim sebagai model invocation baru. Plan/raw response asal utuh. Tidak ada real MP4 baru.

## 12. Showcase Regression Results

Source SHA `58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f`, 26,533 s, 1080×1920, 30 FPS. Source/canonical/existing no-ASR bundle replay **PASS**.

`R/showcase.speech-evidence.v02.json`: speech **NOT_APPLICABLE**, transcript tidak required. Historical Stage 5.4 plan keseluruhan tetap **BLOCKED** karena `onset_sync_without_onset` (A/audio), bukan transcript absence. Speech semantic findings hanya no_speech_required_by_canonical_regions. `R/showcase.{semantic-plan-validation,real-regression}.v01.json`.

Showcase V1/V2 tidak dirender/ditimpa. Speech remediation bukan certification kualitas editorial/visual/musical Showcase.

## 13. Synthetic Multi-Content Results

**90 focused tests PASS**, 0 failed/errored/skipped, 26,049 s (`R/speech-tests.v06.txt`). Clean/multi-speaker dialogue, interrupted cut, noncontiguous/reordered selections, speech+music, music-only, uncertain/conflicting speech, malformed timestamps, missing/valid segment data, partial/full manual boundary coverage, complete word coverage, rejected human selections, QA context, unsupported facts/subtitles, exact reviewed subtitles, source/hash/path/receipt tampering, no approval promotion, actual shared revision entry point, and prompt+receipt tampering.

Synthetic ASR/human review objects adalah **OFFLINE MOCK FIXTURES**, dengan source verification mocked; bukan actual human listening, actual ASR, atau independent acoustic correctness. Real tests hanya replay provenance/eligibility pada dua existing media. No paid calls.

## 14. Test and Regression Counts

Final current-code full regression: **1.204 passed, 0 failed, 0 errored, 0 skipped**, **670,620 s unittest / 673,586 s harness**. Logs: `R/full-regression.v02.txt` dan `R/full-regression-results.v02.json` (per-module counts).

| Kelompok | Passed | Failed / errored / skipped |
|---|---:|---|
| Director Input/Director/Plan/Integration Stage 5.4 | 190 | 0 / 0 / 0 |
| Speech Gate Stage 5A + remediation | 83 | 0 / 0 / 0 |
| Speech Generation Stage 5B + remote | 118 | 0 / 0 / 0 |
| AV Evidence Stage 5C | 78 | 0 / 0 / 0 |
| Renderer/FFmpeg/showcase Stage 5.5 | 199 | 0 / 0 / 0 |
| QA Stage 5.6 + remediation | 150 | 0 / 0 / 0 |
| Revision Stage 5.7 | 131 | 0 / 0 / 0 |
| Benchmark Stage 5.8 | 125 | 0 / 0 / 0 |
| Director diagnostic remediation | 40 | 0 / 0 / 0 |
| Generalized speech remediation | 90 | 0 / 0 / 0 |
| Total Python | 1.204 | 0 / 0 / 0 |

Run development v01: **1.202 passed, 0 failed/errored/skipped**, 610,913 s unittest (617,695 s harness); dua prompt replay tests ditambahkan setelah discovery, sehingga run itu tidak disebut final current-file coverage. Focused final speech suite mencakup semua 90. Log development/failure sebelumnya tetap disimpan.

Relevant focused runs: shared Director/plan **73 passed**, 31,375 s; Stage 5.8 benchmark **125 passed**, 75,997 s; Director diagnostics **40 passed**, 6,507 s. Plugin **23 passed**, 0 failed/cancelled/skipped, 1.919,160262 ms; `tsc --noEmit` exit 0 dan Ruff All checks passed. Total unik **1.227 Python + plugin tests**. Repeated runs tidak ditotal sebagai unique tests. Seluruh required offline regression dijalankan; `poc_*` live experiments tidak dipanggil.

## 15. Source and Historical Artifact Integrity

Baseline sebelum perubahan: **1.039 public project files**, termasuk dua sumber, canonical, transcript/raw/generation/timing/review, historical Director/QA, Showcase V1/V2 dan ledger/checkpoint. Final comparison: **1.034 unchanged, lima expected code changes, 0 missing, 0 unexpected changes**. `R/integrity-{baseline,final}.v01.json` merekam exact hashes.

Hanya lima existing code files pada bagian 3 yang berubah. Legacy Stage 5A/5B reports/eligibility, source MP4, existing ASR, current/historical render approvals dan Stage 5.8 exhausted budgets tidak diedit. Producer code versions sebelumnya disimpan; new evidence menggunakan exclusive versioned outputs. Tidak ada `.env.asr`/secret read-log-change, dependency/model install, external media download, deployment, n8n, publish, commit/push atau Stage 5.9.

## 16. Remaining Limitations

Canonical classification bukan acoustic fact. ASR client provenance/unsigned local receipts tidak authenticate server/model weights. Human acceptance membutuhkan actual reviewer procedure; local receipt bukan cryptographic identity proof. No automated model/grammar method dapat certify preserved meaning/factual truth.

Precision/word coverage yang belum tersedia tetap unavailable. Policy bounds inherited media processing; normalization mendukung varying durations/languages, tetapi longer file inputs perlu bounded chunking task, bukan unlimited decoding. Packet/prompt/report limits bisa menolak oversized contexts; tidak silently truncate untuk eligibility.

Engineering/fixture support tidak sama dengan real speech acceptance. No accepted human review real samples dan no word/timestamp estimates dikarang. Word-only provider response without utterance segments can remain insufficient; complete review/context masih diperlukan. Historical plans tidak diberi approval karena engine diperbaiki.

## 17. Exact ASR Authorization Request, If Needed

Concrete scope ada di `R/asr-authorization-request.v01.json`; non-secret config `R/asr-verbose-json.proposed.v01.json`. **Belum disetujui/dijalankan** pada assignment ini.

- Source `/home/kentung/projects/mandala-autoclipper-ai/data/test-videos/mandala-original.mp4`, exact SHA pada bagian 11.
- Existing 9Router provider `custom-ipt02mbjindt5ldise8woehy-43-129-33-7-sslip-io`, request model `groq/whisper-large-v3`; tidak switch route/model/credential.
- **Satu request maksimum**, 37,2694375 s audio terverifikasi, WAV mono 16 kHz s16le, 596.311 samples. Input audio only; video/text prompt tidak di-upload.
- `response_format=verbose_json`, `timestamp_granularities[]=word`. Expected provider text/word timing/segment timing jika dikembalikan. Dukungan proxy **UNVERIFIED**.
- Cost **UNKNOWN**, HTTP timeout 90 s, max upload 25 MiB, raw response 8 MiB, worker address space 512 MiB/CPU 60 s; no retry/fallback.
- New output `data/analyses/speech-v01/pak-fuad.remote-timed.v01`; existing artifacts tidak ditimpa.
- Validation existing source/WAV/PCM/raw/generation replay + new structural/timestamp checks; kemudian independent human text/boundary/context/word coverage review sebelum cut support.
- Director/semantic Reviewer/real render calls **0**; old Director diagnostic authorization tidak dipakai untuk ASR.

Persetujuan khusus diwajibkan oleh handoff pengguna `/home/kentung/.codex/attachments/e130e4dd-12ed-41ae-ab8f-9fdea2ba0910/Pasted text.txt`, bagian ASR AND LIVE INFERENCE POLICY: **“Wait for explicit approval before billable execution.”** Existing broad authorization sebelumnya tidak dipakai untuk mengabaikan batas terbaru.

## 18. Readiness for Real Dialogue Preview

**NOT READY.** Pak Fuad memerlukan timestamp-bearing source evidence dan actual independent text/alignment/context review untuk exact proposed cuts. Fresh ASR sukses saja tidak memenuhi semuanya. Renderer capability/quality/rights dan separate source-bound preview authorization tetap diperlukan.

Tidak ada speech-based edit, new MP4, publication atau Stage 5.9 yang diklaim berhasil. Engineering tersedia untuk audit dan future unseen sources dalam resource policy yang sama.

**STAGE 5.8 GENERALIZED SPEECH REMEDIATION — WAITING FOR CHATGPT AUDIT**
