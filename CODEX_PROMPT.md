# Mandala Auto — konteks awal untuk AI agent

Bekerja dari root repository. Baca [`AGENTS.md`](AGENTS.md),
[panduan baca](docs/AGENT_GUIDE.md), dan
[katalog Markdown](docs/markdown-catalog.md), lalu kontrak, checkpoint,
source, dan test yang terkait tugas pengguna. Selalu cek `git status` dan
branch sebelum mengubah file; checkout dapat memuat pekerjaan lokal yang belum
di-commit.

## Konteks pemulihan Stage 6.3.5

Source Stage 6.3.5 di PC Windows lama tidak ikut di-push. Laporan implementasi
dan checkpoint rekonstruksi yang dipulihkan adalah riwayat, bukan salinan source.
Pada checkout Linux ini, Tahap A–E lulus dalam cakupan test lokal TEST_ONLY.
[Checkpoint Tahap F terbaru](docs/stage63/stage635-stage-f-checkpoint-2026-10-16.md)
mencatat build dan canary Docker lokal yang lulus, tetapi keputusan deployment
readiness **BLOCKED** karena regresi historis belum dapat diverifikasi penuh
dan audit dependensi belum ditriase. Checkpoint D 15 Oktober adalah riwayat
blocker sebelumnya. Status ini harus diverifikasi ulang terhadap source dan
test terbaru; provider live belum diuji.

## Urutan kerja

1. Tentukan scope dari pesan pengguna terbaru. Baca [kontrak HTTP](docs/stage63/stage635-api-contract.md),
   [checkpoint A–F](docs/stage63/README.md), dan dokumentasi Stage 5 yang
   spesifik pada komponen.
2. Bandingkan kontrak dengan source dan test saat ini. Laporkan celah dengan
   bukti; jangan mengulang engine Stage 5 yang telah ada.
3. Gunakan PostgreSQL lokal, media sintetis, dan replay `TEST_ONLY` untuk test
   yang relevan. Jangan memakai historical evidence sebagai fixture baru atau
   menganggap proof sintetis sebagai izin inference, production, atau publish.
4. Pisahkan status structural validation, render/QA, model, human review,
   readiness service, dan production. Pertahankan receipt dan prompt historis.

Jangan mengubah Media Worker `:3002`, VPS/Coolify, n8n, database production,
atau menjalankan paid inference/publish tanpa tugas dan otorisasi tersendiri.
Ikuti batasan tugas pengguna terbaru. Permintaan finalisasi Stage 6.3.5 pada
16 Oktober 2026 mengizinkan checkpoint commit/push **hanya** ke
`wip/stage-6.3.5-recovery`; izin itu bukan izin deployment ke Coolify atau
instruksi otomatis untuk pekerjaan berikutnya.
