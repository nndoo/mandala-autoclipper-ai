# Prompt Codex — pemulihan Stage 6.3.5 setelah PC lama tidak dapat diakses

Lanjutkan Mandala Auto Autoclipper dari repository GitHub, di PC baru.

**KONTEKS KRITIS:** Kode Stage 6.3.5 di PC lama HILANG/TIDAK TERSEDIA, karena belum commit/push. Jangan berpura-pura bahwa modul API/migration/role yang dideskripsikan dokumen sudah ada. GitHub `main` hanya menyimpan Stage 6.3.4 yang berhasil berjalan di Coolify. Kita sedang di branch baru `wip/stage-6.3.5-recovery`.

Baca `AGENTS.md`, `docs/stage63/PROJECT_CHECKPOINT_RECONSTRUCTED.md`, `docs/stage63/stage635-implementation-report.md`, `docs/stage63/stage635-api-contract.md`, `docs/stage63/stage635-deployment-guide.md`, dan source Stage 5 serta backend di repo.

Tugas terarah:
1. Audit persis fungsi Stage 5 dan backend Stage 6.3.4 yang sudah ada. Buat gap matrix kebutuhan Stage 6.3.5 vs source Git saat ini. Jangan menulis implementasi sebelum audit selesai.
2. Rencanakan rekonstruksi minimal Stage 6.3.5 dari sumber existing, tanpa rewrite engine Stage 5. Sembilan role modular harus punya modul/endpoint terpisah, AV Evidence/ASR dan Renderer/Technical QA terpisah, Reviewer dapat phase source/edited. Gunakan kontrak API dari dokumen.
3. Rekonstruksi bertahap dengan test: schema `mandala_engine`, source original SELECT-only, jobs/tasks/reservations/leases/idempotency/permits/artifacts, operator approval ber-token berbeda, task API asynchronous, bounded retries & unknown outcomes. No DB production.
4. Uji di lingkungan Linux dengan mock provider, fixture sintetis, PostgreSQL isolated compatible dengan production PostgreSQL 16. Perbaiki Docker image/checks hanya bila bisa menjelaskan error nyata. Jangan klaim PASS sebelum full image + Stage 5 Linux regression + synthetic E2E + restart/recovery terverifikasi.
5. Jangan menyentuh Coolify, Media Worker lama, n8n, database production, OpenClaw Instagram. Jangan paid inference, render source nyata, publish, commit/push/deploy tanpa persetujuan user.

**Kerjakan audit + rencana GAP dahulu dan laporkan. Tunggu persetujuan user sebelum implementasi**, sehingga user dapat mengontrol scope pemulihan di PC baru.
