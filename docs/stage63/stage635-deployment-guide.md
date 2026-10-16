# Stage 6.3.5 — migration, konfigurasi, dan rencana Coolify

**Status 16 Oktober 2026:** deployment image Stage 6.3.5 masih perlu diverifikasi.
[Checkpoint F final](stage635-stage-f-final-checkpoint-2026-10-16.md) mencatat
PASS lokal TEST_ONLY untuk full regression, build/canary image, dan audit npm.
Hasil lokal belum menjadi izin deploy. Provider live memerlukan opt-in
`MANDALA_EDITING_LIVE_ROLES_ENABLED=1`; canary memakai executor replay yang
disuntik eksplisit, tanpa panggilan provider.

Checkpoint operator: backup production sudah diuji restore dan salinannya
diverifikasi di Windows; migration version 1 sudah diterapkan dengan 8 tabel,
owner schema `AdminMandala`, serta role `mandala_editing_app` dan
`mandala_source_reader`. Jangan menjalankan migration ulang pada deployment ini.
Verifikasi hak efektif role, koneksi dari jaringan editing, dan checksum
`b64482084069e22eb2367daa0090e7a134eeed53349b46bca8d85b7e85d9f78b`
sebelum mengganti image worker existing.

## Migration

Migration idempotent `backend/migrations/001_editing_jobs.sql` membuat schema
terpisah `mandala_engine` dengan tabel `jobs`, `tasks`, `call_reservations`,
`artifacts`, `permits`, `job_events`, `schema_migrations`, dan
`idempotency_keys`. Tidak ada ALTER atau write terhadap
`public.source_videos`. Terapkan memakai kredensial DB
editing khusus setelah backup dan review operator. Verifikasi
`schema_migrations.version=1` dan hak akses worker hanya pada schema editing.
Source DB harus memakai credential SELECT-only pada `public.source_videos`; kode
menjalankan `SET TRANSACTION READ ONLY` untuk kedua query source.

## Environment resource editing existing

| Variabel | Fungsi |
| --- | --- |
| `MANDALA_EDITING_DATABASE_URL` | PostgreSQL schema editing, hak baca/tulis schema `mandala_engine` |
| `MANDALA_SOURCE_DATABASE_URL` | Koneksi SELECT-only ke `public.source_videos` |
| `MANDALA_EDITING_API_TOKEN` | Secret panjang minimal 32 karakter untuk n8n |
| `MANDALA_EDITING_OPERATOR_TOKEN` | Secret operator berbeda, minimal 32 karakter; jangan masukkan ke n8n |
| `MANDALA_EDITING_PROOF` | Path `proof.json` sintetis Stage 5 yang valid pada volume output |
| `MANDALA_EDITING_PORT` | Tetap `3003` |
| `AUTOCLIPPER_SOURCE_ROOT` | Tetap `/data/source` |
| `MANDALA_OPENCLAW_PROVIDER_ID` | ID provider non-secret yang harus sama dengan manifest hasil build |
| `MANDALA_EDITING_LIVE_ROLES_ENABLED` | Default `0`; opt-in executor live hanya setelah izin inference dan review konfigurasi |

Pada Raw Compose, variabel privat Coolify harus diinterpolasi lewat entri
`environment` di `backend/compose.yaml`; menyimpannya hanya di form Coolify
tanpa entri Compose tidak meneruskannya ke container. Nilai kosong membuat
konfigurasi role tetap nonaktif. Jangan menyimpan URL DB/token dalam repo, log,
body n8n, atau domain publik.
Worker bergabung ke network default serta network PostgreSQL external
`MANDALA_DATABASE_NETWORK` (default `coolify`). Verifikasi PostgreSQL memang
terhubung ke network tersebut; gunakan hostname container yang unik pada DSN.
Tidak ada port host yang dipublikasikan. Override canary memakai network lokal
terpisah, tanpa koneksi PostgreSQL produksi. DSN dan token hanya untuk runtime,
bukan build argument.
Tanpa DSN editing, image masih melayani `/health` dengan `roles_ready=false`
seperti Stage 6.3.4. Tanpa proof atau migration, `/health/ready` memberi 503.
Proof dibuat dengan CLI Stage 5 `run_automatic_editing_v01.py proof` pada
image/volume editing yang sama, lalu direplay readiness; proof harus dibuat
ulang bila kode/lingkungan berubah. Proof sintetis tidak memberi izin publish.
`/health` adalah liveness dan selalu membawa `roles_ready=false`; gunakan
`/health/ready` sebagai gate operasional. Dalam canary lokal, CMD default
memberi health 200 dan ready 503 karena executor live tidak diaktifkan;
executor replay TEST_ONLY memberi ready 200 setelah DB, storage, dan proof
lulus. Lima temuan lama pada npm yang dibundel OpenClaw tidak lagi dilaporkan
oleh audit image setelah npm 11.21.1; batas advisori cache yang diperselisihkan
dan jalur yang diuji dicatat pada [checkpoint final](stage635-stage-f-final-checkpoint-2026-10-16.md).

## Checklist deploy setelah izin pengguna

1. Pastikan resource editing existing tetap menggunakan build context root,
   `backend/Dockerfile`, `backend/compose.yaml`, mount originals read-only di
   `/data` dan `/app/original-store`, serta output terpisah read-write di
   `/app/data`. Media Worker `:3002` tetap di resource lama.
2. Periksa ulang kapasitas VPS dan limit service `3584 MiB`/`1.5 CPU` sebelum
   build. Tetap internal port 3003 tanpa domain; auto-deploy OFF.
3. Verifikasi migration yang sudah diterapkan dan credential source SELECT-only.
   Simpan referensi image serta konfigurasi rollback. Masukkan secret melalui
   Coolify HTTPS saja; jangan menjalankan migration ulang.
4. Build image baru, jalankan proof sintetis pada output volume, set path proof,
   dan restart service. Verifikasi `/health` 200. Dengan executor live tetap
   nonaktif, `/health/ready` 503 adalah gate yang disengaja; jangan membuka
   role POST atau menyatakan service siap menerima job.
5. Tinjau log, migration, mount RO/RW, RAM/CPU, dan proof tanpa memanggil
   provider. Readiness 200 dan admission/role smoke baru dapat diuji setelah
   persetujuan terpisah untuk executor live serta konfigurasi provider.
6. Integrasi sembilan node pada satu workflow utama n8n adalah Stage 6.3.6;
   workflow produksi belum diubah pada Stage 6.3.5.

Jika task berstatus `RECONCILIATION_REQUIRED`, jangan kirim role POST dengan
key baru. Periksa raw provider receipt, reservation `OUTCOME_UNKNOWN`, permit,
MP4, dan SHA-256 secara manual. Kode tidak mengulang panggilan ambigu secara
otomatis; job tersebut tetap terblokir sampai ada prosedur rekonsiliasi operator.
