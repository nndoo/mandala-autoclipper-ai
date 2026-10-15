# Stage 6.3.5 Recovery — checkpoint Tahap E

Tanggal: 16 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`. **Tahap E PASS untuk integrasi sintetis lokal
TEST_ONLY.** Tahap D telah lulus dalam [checkpoint penyelesaian
D](stage635-stage-d-completion-2026-10-16.md). Status ini tidak memberi izin
inference live, produksi, human approval, atau publishing.

## Perubahan

- `tests/test_stage635_roles_integration.py` menambahkan alur HTTP nyata dari
  `POST /v1/jobs` hingga private preview. Server `:3003` lokal memakai
  `EditingService`, `Dispatcher`, sembilan role Stage 5, PostgreSQL 16
  terisolasi, source role SELECT-only, proof fisik Stage 5, dan replay provider
  `TEST_ONLY`. Test memeriksa bearer workflow, operator approval terpisah,
  idempotency, polling task, serta setiap hash dan ukuran artifact terdaftar.
- `tests/test_stage635_postgres_integration.py` menambahkan batas crash setelah
  reservation tersimpan tetapi sebelum call ditandai `SENT`. Lease yang habis
  mengubah reservation menjadi `OUTCOME_UNKNOWN` dan job menjadi
  `RECONCILIATION_REQUIRED`, tanpa retry otomatis.
- Tidak ada perubahan kontrak HTTP, migration, engine Stage 5, atau service
  Media Worker.

## Matriks verifikasi

| Persyaratan | Bukti test lokal |
| --- | --- |
| Source admission → private preview tanpa speech | `test_http_end_to_end_real_role_executor`, `test_synthetic_private_preview_role_chain` |
| Speech/timing, ASR kondisional, dua putaran source Reviewer | `test_speech_asr_source_review_retry`, `test_speech_private_preview`; audio sumber sintetis dari FFmpeg `flite`, respons ASR/review replay |
| Director invalid, Validator rejection sebelum permit | `test_invalid_director_response_consumes_one_budget_slot`, `test_validator_rejection_stops_before_permit` |
| FFmpeg MP4 aktual, manifest, QA PASS | Test private preview dan HTTP; hash/ukuran MP4 serta semua artifact dibandingkan dengan manifest/database |
| QA BLOCKED sesudah render | `test_technical_qa_blocked_is_separate_from_render`; kegagalan QA **diinjeksi TEST_ONLY**, bukan cacat media yang ditemukan independen |
| Reviewer `source_speech` dan `edited_output` | Test speech dua putaran dan private preview; tidak ada pengamatan model live |
| Batas tiga proposal, kandidat terbaik, `WITH_NOTES` | `test_revision_loop_selects_best_private_preview_with_notes`; attempt 2 terpilih dari tiga reservation/render |
| Duplicate API dan idempotency | Test HTTP baru dan `test_concurrent_submission_and_idempotency_replay` Tahap C |
| Restart `QUEUED`/`RUNNING`, lease fencing | Test dispatcher/worker restart, expired lease, separate process crash Tahap B/C |
| Sebelum reservation, sesudah reservation, sesudah `SENT` | Effect-free requeue; reservation belum dikirim menjadi unknown; `SENT` tanpa outcome menjadi unknown; semua memakai batas transaksi durabel dan lease expiry TEST_ONLY |
| Crash sesudah render permit dikonsumsi | `test_crash_after_render_permit_consumption_never_retries`; DB dan Stage 5 permit satu pakai |
| Orphan, mismatch SHA, source mutation | Test Tahap C/D menahan task atau mengarantina job sebelum efek baru |
| Readiness fail-closed | HTTP test menurunkan proof checker → `/health/ready` 503; test Tahap C mencakup migration, source privilege, runtime, executor, token separation |

## Hasil pengujian

| Suite | PASS | FAIL | SKIP |
| --- | ---: | ---: | ---: |
| `test_stage635_roles_integration.py` (termasuk HTTP E2E) | 13 | 0 | 0 |
| `test_stage635_postgres_integration.py` | 17 | 0 | 0 |
| `test_stage635_api_integration.py` | 14 | 0 | 0 |

Total integrasi lokal B–E: **44 PASS, 0 FAIL, 0 SKIP**. PostgreSQL 16 lokal
berada dalam container loopback dengan data `tmpfs`; tidak memakai database
VPS. Source dan MP4 dibuat khusus test dan dibersihkan setelahnya. Tidak ada
paid inference. Proof fisik Stage 5 direplay pada host test yang sama sebelum
render. `human_verified`, `production_eligible`, dan `publishing_eligible`
tetap false. Output sintetis ini **bukan historical evidence** PC lama.

Recovery menjaga akibat ambigu sebagai `RECONCILIATION_REQUIRED`. Test crash
provider menguji marker transaksi, lease expiry, dan replay terlarang; tidak
membuktikan perilaku jaringan/provider live yang memang dilarang pada tahap
ini. Test HTTP menyuntik `runtime_check=True` untuk host lokal; pemeriksaan
mount/image nyata menjadi tugas Tahap F.

## Batas dan kelanjutan

Fixture/evidence historis dari PC lama belum tersedia untuk full historical
regression. Tahap E membuktikan alur sintetis lokal, bukan deployment Coolify,
live model/ASR accuracy, atau review editorial manusia. **Tahap F boleh
dimulai** untuk build image, regression dengan fixture valid, volume TEST_ONLY,
proof di container, dan readiness Docker. Jangan memulai Stage 6.3.6 dari
checkpoint ini.
