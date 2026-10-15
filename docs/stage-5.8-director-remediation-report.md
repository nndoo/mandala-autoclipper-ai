# Stage 5.8 Director remediation — Pak Fuad

Tanggal 13 Oktober 2026. **PARTIAL untuk penetapan akar kegagalan historis; diagnostik diimplementasikan dan satu pemanggilan live berhasil.** Sumber dan prompt identik dengan request lama. Respons baru valid, tetapi plan belum layak dirender. Tidak ada render real-content, ASR, Analyst, Reviewer, deployment, publikasi, commit atau Stage 5.9.

Semua artifact baru ada di `/home/kentung/projects/mandala-autoclipper-ai/data/benchmarks/stage58/pak-fuad-director-remediation.v01/` (selanjutnya `R`). File historis tidak ditimpa.

## 1. ROOT CAUSE — CONFIRMED VS HYPOTHESIS

Terbukti: runner lama membuang stderr pada `scripts/run_adaptive_director_v03.py:124`, menghilangkan detail nonzero pada baris 138, dan baru mempublikasikan bundle setelah ekstraksi/validasi. Wrapper benchmark sebelumnya mengubah exception berbeda menjadi `PLANNING_FAILURE`. Ini menyebabkan hilangnya bukti diagnostik.

**Penyebab internal percobaan historis tetap UNRESOLVED.** Raw response/exit code/PID tidak tersedia. Transport/provider error, respons kosong/malformed, envelope tidak didukung, dan resource failure tetap hipotesis. Tidak ada alasan mengklaim 9Router atau model sebagai penyebab. Tidak ada blind retry untuk merekonstruksi kejadian lama.

Proof: `R/root-cause-analysis.v01.json`, `R/offline-forensic-trace.v01.json`.

## 2. EXACT FAILURE PHASE

Historis: exception tercatat dalam `run_benchmark_v01.plan`, setelah reservasi Director dan sebelum generation receipt. Detail fase invocation/extraction/validation tidak bisa dipastikan. Durasi action sekitar 90,296 s; ini tidak membuktikan timeout subprocess 180 s.

Baru: invocation **PASS**, extraction **PASS**, schema **PASS**, grounding independen tidak mempunyai blocking findings. Blokir terjadi pada guard speech Stage 5.8: `missing_speech_evidence:disconnected_speech_selection`. Artifact diagnostic memakai kelompok fase `schema_and_evidence_validation`; `speech_safety_blockers` mengidentifikasi subfase yang tepat.

## 3. DIAGNOSTIC EVIDENCE

`R/runtime-call-trace.v01.json` menelusuri benchmark → prepared request → OpenClaw `runModelRun` → agent/provider/model selection → simple completion → envelope `outputs[0].text` → extractor/validator existing → generation receipt → readiness.

Log lama pada 07:02:14 WIB menyebut HTTP 200 pada waktu yang cocok, tetapi tidak mengandung PID/request ID untuk mengikatnya ke job: hubungan tetap UNKNOWN. Tidak ada saved failure response untuk reproduksi offline. Historical plan lama dapat direplay dan diperiksa; ini bukan respons percobaan gagal Stage 5.8.

`R/sanitized-failure-evidence.v01.json` menghubungkan laporan historis, log terpilih, error inspeksi CLI lokal yang tidak melakukan inference, hasil inspeksi yang benar, dan blokir speech baru. Tidak ada fabricated historical diagnostics.

## 4. FILES MODIFIED

Baru:

- `/home/kentung/projects/mandala-autoclipper-ai/scripts/director_diagnostics_v01.py` — capture, kategori, artifact, ledger dan CLI.
- `/home/kentung/projects/mandala-autoclipper-ai/tests/test_director_diagnostics_v01.py` — 40 tes offline.
- `/home/kentung/projects/mandala-autoclipper-ai/docs/stage-5.8-director-remediation-report.md` — laporan ini.

Modified:

- `/home/kentung/projects/mandala-autoclipper-ai/scripts/run_benchmark_v01.py:222` — route live planning ke diagnostic wrapper, simpan ref diagnostic dan kategori typed failure pada baris 247.
- `/home/kentung/projects/mandala-autoclipper-ai/scripts/benchmark_evidence_v01.py:29` — tambahkan diagnostic producer ke code receipts.
- `/home/kentung/projects/mandala-autoclipper-ai/tests/test_benchmark_v01.py:238` — mock target baru; assertion budget/status tetap.

Director Stage 5.4, schema, prompt, transport, plugin TypeScript, ASR dan credential tidak diubah. Perubahan receipt-bound benchmark berarti bundle Stage 5.8 lama tetap evidence versi lama; tidak ditulis ulang atau dipaksa lolos current-code validation.

## 5. IMPLEMENTED FIX

Diagnostic wrapper menggunakan perintah OpenClaw existing, extractor, validator, provenance replay dan exclusive writer existing. `capture:62` membatasi stdout 131.072 byte, stderr 16.384 byte, timeout 180 s; kill process group/reap/close pada semua jalur. Overflow diberi label bounded-prefix hash. Node heap 256 MiB; ini bukan hard RSS limit. CLI total deadline memakai helper existing 480 s.

`sanitize:36` membuang credential-bearing lines, meredaksi token/URL, dan membatasi excerpt 4.096 karakter. Raw response hanya dipersist jika lolos policy encoding/credential existing; sukses menyimpan seluruh raw tanpa perbaikan JSON/plan.

Kategori di `CATEGORIES:21`: REQUEST_PREPARATION_FAILURE, PROVIDER_CONFIGURATION_FAILURE, INVOCATION_FAILURE, TRANSPORT_FAILURE, UPSTREAM_MODEL_FAILURE, TIMEOUT, EMPTY_RESPONSE, RESPONSE_EXTRACTION_FAILURE, RESPONSE_SCHEMA_FAILURE, EVIDENCE_GROUNDING_FAILURE, SPEECH_ELIGIBILITY_BLOCKED, PLANNING_VALIDATION_BLOCKED dan UNKNOWN_FAILURE.

Diagnostic menyimpan invocation ID, source/packet/prompt hashes, alias, sanitized command structure, PID, exit/signal, timestamps/duration, stream sizes/hashes/excerpts, response presence, parsing/validation/generation status, dan next action. Request count/cost tetap UNKNOWN.

`live_attempt:198` memakai ledger terpisah, lock, exclusive reservation sebelum subprocess, maksimum dua panggilan termasuk failure. Crash tidak mengembalikan kuota. Panggilan kedua memerlukan diagnostic actionable dan fix yang terikat perubahan code hash; generation sukses menutup jalur panggilan kedua. Tidak ada automatic retry atau fungsi render pada remediation.

## 6. OFFLINE TEST RESULTS

Final focused: **40 passed, 0 failed, 0 errored, 0 skipped**, 3,139 s (`R/offline-tests.v05.txt`). Stage 5.8: **125 passed, 0 failed, 0 errored, 0 skipped**, 43,187 s (`R/stage58-regression.v01.txt`).

Mencakup success/nonzero CLI, HTTP/transport/provider errors, sanitized secrets/URLs, empty output, UTF-8/size caps, exact byte limit, timeout/group termination, malformed JSON/envelope, schema-invalid quarantine, unsupported evidence, wrong model, provenance absence, source change, speech-ineligible cuts, no retry, exhausted budget, separate cap, unapplied second fix, and original budget preservation. Mock selalu offline; socket connect diblokir. Tidak ada real-content render.

Log development v01–v03 yang gagal tetap disimpan; bug publication setelah source recheck dan fixture expectations diperbaiki sebelum focused v05. Assertion integrity/termination tidak dilonggarkan.

## 7. LIVE DIRECTOR TEST RESULTS

**Satu panggilan baru, generation berhasil, tidak memakai panggilan kedua.** Process exit 0, signal null, subprocess 66,646163 s; seluruh command 1:42,64, maximum RSS 456.032 KiB. Captured stdout 6.004 byte, stderr 221 byte. Diagnostic invocation ID `2c360418-9813-49c4-8012-5aa474395b5e`.

CLI remediation exit **20** karena speech guard, bukan karena model call gagal. Source-bound draft satu variant A, estimated duration 20,6 s, dengan source windows 0–5,2; 11–17,4; 27,5–36,5. Angka ini proposal model, bukan durasi video hasil render. Tidak ada MP4 baru.

Proof: `R/call.01/invocation-diagnostic.v01.json`, `R/live-call-01.performance.v01.txt`, `R/live-call-01.stdout.v01.txt`.

## 8. ACTUAL MODEL/PROVIDER

Runtime diverifikasi ulang **OpenClaw 2026.9.9 (bcfc888)**, **Node v24.21.0**. Executable wrapper memakai bundled Node yang resolve ke path yang sama. `R/runtime-version.v01.json`.

Inventory lokal dan response envelope menunjukkan provider `custom-ipt02mbjindt5ldise8woehy-43-129-33-7-sslip-io`, model alias **openclaw**, API **openai-completions**, transport local, capability model.run. Backend/model weights fisik **UNVERIFIED**. Tidak ada model/provider/config override.

Video plugin TypeScript hanya mendaftarkan video-describe provider; Director text inference memakai built-in completion runtime. Inspeksi CLI pertama salah posisi `--agent` dan exit 1, lalu diperbaiki ke parent `infer model --agent ... inspect`. Kedua inspeksi bukan model invocation.

## 9. API CALL AND COST ACCOUNTING

`R/live-scope.v01.json` merekam otorisasi capped baru. `R/reservation.01.json` immutable; tidak ada reservation.02. New Director wrapper calls **1/2**, successful generation **1**, retries **0**; Analyst/ASR/Reviewer/render **0**. Historical Director budget tetap **0** dan checkpoint tidak diubah.

Stderr milik subprocess baru mengandung satu client transport log HTTP **200**. Ini bukan independent server request-count/billing audit. Total HTTP upstream dan biaya aktual **UNKNOWN**; nilai nol tidak dikarang. `R/live-accounting.v01.json`.

## 10. RESPONSE EXTRACTION AND VALIDATION

Complete raw tersimpan immutable di `R/call.01/raw-response.v01.txt`, SHA-256 `dd89cc994c6d0549b974fcff7ed915b936b085c1d8a5feb49ce1c736d500d0fc`.

Extractor known-envelope existing berhasil; plan sesuai schema existing tanpa rewrite. Source/packet hashes dan evidence references lolos independent validator. Source/evidence replay ulang dan exact `parse_response(raw) == saved_plan` diverifikasi. Ini tidak mengesahkan factual claims/model interpretations atau speech boundaries.

## 11. GENERATION PROVENANCE

`R/call.01/generation-provenance.v03.json` merekam live_model_inference, wrapper_invocations=1, exact raw response reference/hash, prompt SHA, packet SHA, plan SHA, original Director code receipts, serta tambahan diagnostic_code_receipt. Hash tambahan mengidentifikasi producer baru secara eksplisit; receipt historis tidak diubah.

Prompt **53.861 byte**, SHA `2910d9cec9d0383824dde6ddb72a3c44d13171c4298c1891469ff8cc632a0b24`. Packet SHA `f5ae334c320a96e5e83cf7f75afe3b95e71edcab99a56fe422faf7a21e917544`. Exact saved plan canonical JSON SHA `b32e0695aed3b92b38aa281f3276f136d4c85f27404e828162e99d1db0b07199`.

Model identity provider-reported, bukan independen model authentication. Render/publish approval false.

## 12. INDEPENDENT PLAN VALIDATION

`R/call.01/plan-validation.v03.json`: structural_validity=true, status **NEEDS_REVIEW**, blocking_findings=[], sembilan review findings. Speech boundaries, discontinuity, candidate timing dan caption meaning/factual review tetap diperlukan. render_readiness=BLOCKED_FOR_RENDER, render_gate_passed=false, publish_ready=false.

`R/plan-readiness.v01.json` menjalankan Stage 5.8 readiness dengan capability registry existing: private_preview_eligible=false, precise speech blocker. Timeline compilation/operation execution tidak diteruskan setelah early speech block; tidak mengklaim denoise/subtitle renderer telah verified.

## 13. PAK FUAD SPEECH ELIGIBILITY

Offline remote speech bundle validator **PASS** untuk provenance/format remote. Draft adalah text-only format yang valid untuk penyimpanan provider response: recognized_regions=1, segments=[], provider_words=[], timing segments/words=[]. Upload context bukan utterance timing.

Gate existing tetap **ineligible**, transcript=false, speech_alignment=false; reasons `transcript:malformed_transcript_segments_or_timestamps` dan `transcript:generation_not_independently_observed`. Ini menunjukkan ketidakcukupan kontrak timed transcript, bukan bukti bahwa kata-kata provider pasti salah. Generation client recorded tidak sama dengan independent server authentication. Text accuracy **unverified**, timing **unavailable**, review **pending**.

`R/speech-assessment.v01.json`. Tidak ada word/timestamp buatan, ASR ulang, gate upgrade atau koreksi draft otomatis.

## 14. RENDER READINESS

**BLOCKED** untuk plan ini. Tiga selections terpisah tidak didukung alignment/semantic boundaries yang verified. Speech-safe flag model tidak menggantikan evidence. Guard existing juga menolak partial trim, reorder/multiple selections, speed/freeze, dan unreviewed speech audio treatments. Whole unchanged source hanya mempertahankan konteks; masih tunduk pada validator/capability/rights/authorization lainnya.

Remediation tidak mengotorisasi real-content render. Render/publish/production flags false; tidak ada render permit atau MP4 baru.

## 15. FULL REGRESSION RESULTS

Regresi penuh: **1.114 passed, 0 failed, 0 errored, 0 skipped**, **404,079 s**. `R/full-regression.v01.txt` dan `R/full-regression-results.v01.json` merekam hasil serta counts per module.

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
| Total Python | 1.114 | 0 / 0 / 0 |

Plugin: **23 passed**, 0 failed/cancelled/skipped, 634,352338 ms (`R/plugin-regression.v01.txt`). Total unik Python + plugin **1.137**, tidak menjumlahkan focused repeated runs. TypeScript `tsc --noEmit` exit 0; `ruff check scripts tests` **All checks passed**. Tidak ada required offline regression yang tidak dijalankan; `poc_*` live experiments tidak termasuk unittest dan tidak dipanggil.

## 16. HISTORICAL ARTIFACT INTEGRITY

Baseline remediation mencatat **1.001 files** sebelum perubahan. Perbandingan akhir: **998 unchanged, tiga expected code/test changes, 0 missing, 0 unexpected changes**. `R/integrity-baseline.v01.json` dan `R/integrity-final.v01.json` mengikat before/after hashes.

Source Pak Fuad SHA `000c759ac57ff4c2bfbdfd3e8d678f46d2160ea8855b4ca9bb343ce26c8671f3`; Showcase SHA `58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f`. Showcase V1 SHA `338832fd9437d1195e52f2810536858f91a65cbef2f0caecd42cd33d06b89cf1`, V2 SHA `7d78c3d3167110faf0da433a41f9e91d5215b95f5d5db4a80b77d617f33fa818`. Semua identik dengan baseline.

Historis tetap evidence original version: MP4 source/Showcase V1/V2, canonical, speech, QA, historical Director plan/receipt, checkpoints/budget. Hanya tiga file existing benchmark code/test di bagian 4 yang diizinkan berubah. Tidak ada credential read/log/modification atau dependency/model install.

## 17. REMAINING BLOCKERS

Root cause historis tidak terpulihkan dari bukti yang ada. Request baru berhasil tanpa transport/model switch, jadi persistent deterministic integration failure tidak teramati; penyebab transient tidak dapat ditetapkan.

Speech timing/accuracy/context, factual claims, operation capabilities, rights dan human editorial acceptance belum verified. Schema validity bukan successful editing. Runtime Node heap bukan OS memory hard cap. Unsigned local receipts membuktikan konsistensi lokal, bukan adversarial signed provenance/server authentication.

## 18. NEXT ENGINEERING ACTION

Architect audit atas diagnostic producer, ledger, live receipt dan speech block. Usulkan tugas speech terpisah: uji provider timestamp response lewat config baru `verbose_json` dengan provider/model existing, raw generation receipts dan source offsets; validasi dukungan proxy, timing/alignment dan content/boundary review manusia, serta kontrak acceptance remote yang eksplisit. Fresh ASR saja tidak otomatis menyelesaikan gate atau mengizinkan cut.

ASR proposal belum dijalankan. Tidak ada blind second Director call, plan patch manual, rendering, publishing atau Stage 5.9.

**STAGE 5.8 DIRECTOR REMEDIATION PARTIAL — WAITING FOR CHATGPT AUDIT**
