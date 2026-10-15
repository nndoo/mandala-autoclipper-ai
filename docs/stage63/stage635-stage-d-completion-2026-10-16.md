# Stage 6.3.5 Recovery — checkpoint penyelesaian Tahap D

Tanggal: 16 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`. **Tahap D PASS untuk integrasi lokal TEST_ONLY.**
Checkpoint [parsial 15 Oktober](stage635-stage-d-checkpoint-2026-10-15.md)
tetap utuh sebagai catatan sebelum blocker diselesaikan. Ini belum membuktikan
readiness image Docker, provider live, deployment, human review, atau publishing.

## Perubahan dan penyebab

- `tests/test_stage635_roles_integration.py` membuat dan mereplay physical
  capability proof dengan `run_automatic_editing_v01.proof()` serta
  `check_proof()`. Stub yang sebelumnya hanya berisi daftar filter dihapus.
  Proof memuat source/MP4 sintetis, visual registry, pengukuran piksel dan
  audio, hash code/recipe, dan fingerprint environment. Stage 5 `admit()`
  tetap memeriksa kemampuan plan lalu mengonsumsi permit sekali sebelum
  FFmpeg; gate tidak dilewati.
- `backend/roles/revision_controller.py`, `backend/roles/speech_asr.py`, dan
  `backend/roles/director.py`: daftar region retry ASR dan diagnosis revisi
  disimpan sebagai objek JSON (`regions` / `findings`). Pembaca Stage 5
  menolak JSON array sebagai root; bentuk lama membuat task ambigu masuk
  `RECONCILIATION_REQUIRED`. Kontrak HTTP `next_action` tetap sama.
- Panduan aktif, katalog Markdown, dan checkpoint ini menyatakan status
  terbaru tanpa mengubah laporan historis, prompt OpenClaw, atau receipt.

## Status sembilan role

| Role | Bukti lokal TEST_ONLY |
| --- | --- |
| Analyst | Replay respons terikat source; reservation sebelum invocation |
| AV Evidence | Engine Stage 5 menghasilkan packet dan storyboard source-bound |
| Speech/ASR | Jalur no-speech dan speech sintetis; dua call per region dengan retry terpilih |
| Creative Director | Proposal valid, respons rusak, dan batas tiga proposal diuji |
| Validator | Plan valid serta klaim tidak didukung ditolak sebelum permit |
| Renderer | Proof fisik Stage 5, DB permit dan `Stage 5 admit()` satu pakai; MP4 sintetis di-encode |
| Technical QA | MP4 aktual lulus decode/hash/size/audio/text checks; cabang BLOCKED diinjeksi khusus test |
| Reviewer | `source_speech` dua putaran dan `edited_output` terpisah memakai replay, bukan model live |
| Revision Controller | Transisi terminal dan pemilihan kandidat terbaik dari tiga percobaan berstatus `WITH_NOTES` |

## Verifikasi

PostgreSQL 16 lokal hanya terbit pada loopback dengan data `tmpfs` TEST_ONLY.
MP4 sumber dibuat melalui FFmpeg (jalur speech memakai filter `flite` offline),
dan output preview melewati hash/ukuran manifest, FFprobe/decode Stage 5,
Technical QA, serta verifikasi ulang setiap artifact terdaftar. Test menghapus
job/media/proof sementara sesudah assertion; MP4 ini **bukan historical evidence**.

| Pemeriksaan | Hasil |
| --- | --- |
| Integrasi sembilan role, no-speech/speech, revisi, failure boundary | **11 PASS**, 0 FAIL, 0 SKIP dalam satu suite |
| Crash setelah konsumsi DB dan Stage 5 render permit | **1 PASS**, 0 FAIL, 0 SKIP |
| Regresi PostgreSQL Tahap B/C | **30 PASS**, 0 FAIL, 0 SKIP |
| Targeted Stage 5 automatic editing + preview policy | **33 PASS**, 0 FAIL, 0 SKIP |
| `ruff check scripts tests backend`; `git diff --check` | PASS |

Kasus batas mencakup source mutation sebelum provider, reservation provider
`OUTCOME_UNKNOWN` tanpa retry, artifact hash mismatch, invalid Director,
Validator rejection, QA BLOCKED yang terpisah dari render, permit terpakai,
dan crash setelah permit Stage 5 dikonsumsi. Idempotency, lease fencing,
restart task, serta orphan scan tetap ditanggung tes Tahap B/C yang diregresi.
Setelah crash/efek ambigu, status tetap `RECONCILIATION_REQUIRED`.

## Batas dan kesiapan Tahap E

Tidak ada paid inference, Media Worker/VPS/Coolify/n8n/DB production yang
diubah, render media production, atau izin publish. Model Reviewer dan ASR
adalah replay `TEST_ONLY`; hasilnya tidak membuktikan pengamatan model nyata
atau akurasi transkrip manusia. Full historical Stage 5 regression masih
terbatas oleh fixture/evidence PC lama. Proof dihasilkan pada host lokal,
belum di image/volume Docker. **Tahap E boleh dimulai** untuk pengujian E2E
dan recovery yang lebih luas; Tahap F/deployment belum dinilai.
