# Stage 6.3.5 Recovery — checkpoint sementara Tahap D

Tanggal 15 Oktober 2026. **Tahap D BELUM PASS.** Pekerjaan dihentikan atas permintaan laporan segera. Tidak ada commit, push, deploy, paid inference, publish, atau perubahan VPS, Coolify, n8n, database produksi, dan Media Worker :3002.

## Perubahan lokal

- Sembilan modul role baru pada `backend/roles/`: Analyst, AV Evidence, Speech/ASR, Director, Validator, Renderer, Technical QA, Reviewer, Revision Controller, beserta context/provider bersama. Provider live memerlukan opt-in `MANDALA_EDITING_LIVE_ROLES_ENABLED=1`; tes memakai `TestOnlyReplayProvider` tanpa network.
- `backend/editing_api.py`, `backend/editing_worker.py`, `backend/editing_dispatch.py`: wiring executor dan dispatcher Stage 5 dengan readiness fail-closed. Output role ditujukan ke writer Stage 5 di `data/revisions/stage59/automatic`.
- `backend/editing_store.py`: query riwayat task/reservation, result artifact IDs, dan status QA/model terpisah.
- `scripts/run_automatic_editing_v01.py`: satu argumen `invoke` opsional pada `model_review`, untuk mengikat Reviewer ke reservation DB sebelum transport; jalur default Stage 5 tetap sama.
- `tests/test_stage635_roles_integration.py`: MP4 sintetis dan replay TEST_ONLY di PostgreSQL 16 lokal.

## Bukti yang sudah ada

- `compileall`, `ruff check` untuk source yang berubah, dan `git diff --check`: PASS.
- Regresi Tahap B/C PostgreSQL 16 lokal: **30 PASS**.
- Test Stage D Analyst → AV Evidence → Speech tanpa speech, dengan Controller di antaranya: **PASS**.
- Test rantai synthetic private preview: Analyst, AV, Speech, Director, Validator dan Controller di antaranya sampai sebelum Renderer berjalan **PASS**. Renderer berhenti `RECONCILIATION_REQUIRED / EXECUTOR_UNCERTAIN`; diagnostic test menunjukkan `Plan uses capability without current physical proof`. Proof pada test ini adalah stub TEST_ONLY, sehingga kegagalan gate tidak boleh diubah menjadi klaim render atau QA PASS.

## Status dan blocker

| Role | Status verifikasi saat checkpoint |
| --- | --- |
| Analyst | Replay sintetis PostgreSQL PASS; provider live tidak dipanggil |
| AV Evidence | Stage 5 source-bound analysis sintetis PASS |
| Speech/ASR | Jalur no-speech PASS; panggilan ASR/retry per region belum diuji end-to-end |
| Creative Director | Replay satu proposal sintetis PASS sebelum render |
| Validator | Validasi proposal Stage 5 sintetis PASS |
| Renderer | **FAIL/BLOCKED** pada proof capability fixture; permit, encode dan output belum dibuktikan end-to-end |
| Technical QA | Modul ada; belum dieksekusi pada MP4 hasil Tahap D |
| Reviewer | Dua phase terpisah dalam kode; belum diuji end-to-end |
| Revision Controller | Transisi awal PASS; pemilihan kandidat dan terminal belum diuji |

Belum ada proof aktual pada image/volume service, uji sembilan role penuh, batas crash/efek menyeluruh, atau regresi Stage 5 historis. Readiness production **tidak terbukti**. Perlu diagnosis proof capability dan lanjut uji render sintetis, QA, Reviewer dua phase, Controller terminal, ASR retry, reservation ambigu, permit sekali pakai, artifact mismatch, source mutation, serta fencing. Tahap E **belum siap**.
