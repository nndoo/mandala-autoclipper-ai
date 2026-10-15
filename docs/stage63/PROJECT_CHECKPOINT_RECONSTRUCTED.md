# PROJECT CHECKPOINT — reconstructed from user-provided Codex logs

**Ini bukan file asli PC lama.** Catatan ini dibuat ulang dari log yang pengguna paste di chat tanggal 15 Oktober 2026. Semua perubahan kode Stage 6.3.5 di PC lama dianggap TIDAK TERSEDIA.

## Status tahap
- Stage 6.3.4: GitHub dan Coolify AI Worker `:3003` healthy; `roles_ready=false`. Old Media Worker `:3002` unchanged.
- Stage 6.3.5: kode belum commit/push/deploy, dan tidak bisa diakses dari PC lama; harus direkonstruksi dari code Stage 5 dan tiga dokumen Stage 6.3.5 terlampir.
- Target implementasi sebelumnya: PostgreSQL `mandala_engine` migration, jobs/tasks/reservations/artifacts/permits/events, admission, auth+manual operator approval, async queue/poll, lease fencing/recovery/idempotency, nine modular role endpoints, Stage 5 integration; single n8n workflow kelak Stage 6.3.6.
- Tes pernah dilaporkan: enam tes PostgreSQL/API PASS pada lingkungan lokal isolated PostgreSQL 17, satu synthetic media test SKIP; **hasil test ini milik PC lama dan tidak otomatis membuktikan implementasi rekonstruksi**.
- `compileall` dan `git diff --check` pernah PASS. Linux Stage 5 regression, mock provider E2E, full image build **belum PASS**.

## Observasi masalah build
- Build Windows Docker Desktop mencapai pemeriksaan `renderer_core_v01.environment()` dan mengalami timeout 10 s di `scripts/renderer_core_v01.py` pada subprocess `ffmpeg/ffprobe -version`.
- `openclaw --version` sebelumnya gagal akibat wrapper CRLF; Codex memperbaikinya secara lokal. **Perbaikan lokal ini tidak tersedia di main GitHub.** Pada Coolify Stage 6.3.4 `OpenClaw 2026.9.9` bekerja, tetapi **tidak membuktikan Dockerfile Stage 6.3.5 siap**.
- Pengguna menguji Stage 6.3.4 di Coolify: `renderer_core_v01.environment()` PASS 0.34 s dengan libx264/AAC/libass True.
- Codex mengukur cold start `ffmpeg -version`: WSL Ubuntu pertama ~4.40 s lalu ~0.10 s; local Docker container pertama 2.303 s lalu 0.091 s; BuildKit pertama 5.53 s lalu 0.093 s; ffprobe ~0.09-0.215 s. Gagal >10 s tidak terekonstruksi dalam probe terbatas.
- Codex menambahkan 2 baris warm-up pada Dockerfile **lokal** tanpa verifikasi full build; perubahan itu hilang bersama source PC lama. Jangan menyalinnya tanpa diagnosis.
- Tidak ada dasar untuk meningkatkan timeout engine Stage 5 hanya karena lambatnya host lokal.

## Invarians
- Media Worker lama port 3002 permanen dan tidak disentuh.
- AI Editing Worker baru port 3003 permanen dan terpisah, originals RO alias `/data` dan `/app/original-store`; output RW terpisah `/app/data`.
- Satu canvas n8n dengan 9 node terpisah; n8n dispatcher, backend authoritative atas budgets/state/permit/recovery.
- Inference berbayar perlu manual operator approval; no auto publish; retries ambigu harus `RECONCILIATION_REQUIRED`.
- Jangan edit Coolify, n8n, Postgres production, GitHub main, atau menyimpan token dalam repo tanpa izin.
