# Stage 6.3.5 — migration, konfigurasi, dan rencana Coolify

**Status 16 Oktober 2026:** panduan ini belum dijalankan pada production.
[Checkpoint Tahap E](stage635-stage-e-checkpoint-2026-10-16.md) lulus pada
lingkungan lokal TEST_ONLY. Build dan canary image Docker lokal juga telah
diverifikasi; rincian serta batasnya ada di
[checkpoint Tahap F](stage635-stage-f-checkpoint-2026-10-16.md). [Audit kesiapan
F terbaru](stage635-stage-f-readiness-audit-2026-10-16.md) tetap menyatakan
BLOCKED. Jangan gunakan
hasil lokal sebagai izin deploy. Provider live memerlukan opt-in
`MANDALA_EDITING_LIVE_ROLES_ENABLED=1`; canary memakai executor replay yang
disuntik eksplisit, tanpa panggilan provider.

**Belum dieksekusi pada Coolify atau PostgreSQL produksi.** Panduan ini hanya
untuk tahap persetujuan/deployment berikutnya.

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

## Environment service baru

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
| `MANDALA_EDITING_LIVE_ROLES_ENABLED` | Opt-in executor live; jangan aktifkan untuk canary atau sebelum izin inference dan review konfigurasi |

Jangan menyimpan URL DB/token dalam repo, log, body n8n, atau domain publik.
Tanpa DSN editing, image masih melayani `/health` dengan `roles_ready=false`
seperti Stage 6.3.4. Tanpa proof atau migration, `/health/ready` memberi 503.
Proof dibuat dengan CLI Stage 5 `run_automatic_editing_v01.py proof` pada
image/volume editing yang sama, lalu direplay readiness; proof harus dibuat
ulang bila kode/lingkungan berubah. Proof sintetis tidak memberi izin publish.
`/health` adalah liveness dan selalu membawa `roles_ready=false`; gunakan
`/health/ready` sebagai gate operasional. Dalam canary lokal, CMD default
memberi health 200 dan ready 503 karena executor live tidak diaktifkan;
executor replay TEST_ONLY memberi ready 200 setelah DB, storage, dan proof
lulus. Lima temuan audit transitive pada paket `npm` (tiga high, dua moderate)
telah diklasifikasi di audit kesiapan F, tetapi belum dimitigasi dalam
image; uji `npm audit fix` pada salinan lockfile tidak menghilangkannya.

## Checklist deploy setelah izin pengguna

1. Pastikan service baru tetap menggunakan build context root,
   `backend/Dockerfile`, `backend/compose.yaml`, mount originals read-only di
   `/data` dan `/app/original-store`, serta output terpisah read-write di
   `/app/data`. Media Worker `:3002` tetap di resource lama.
2. Periksa ulang kapasitas VPS dan limit service `3584 MiB`/`1.5 CPU` sebelum
   build. Tetap internal port 3003 tanpa domain; auto-deploy OFF.
3. Review dan terapkan migration editing pada DB/scheme yang dipilih; buat
   credential source SELECT-only. Masukkan secret melalui Coolify saja.
4. Build image baru, jalankan proof sintetis pada output volume, set path proof,
   restart service baru. Tunggu `/health` 200 dan `/health/ready` 200.
5. Jalankan admission mock/synthetic lebih dulu. Tinjau log queue, state DB,
   mount RO/RW, RAM/CPU, lalu coba satu job nyata hanya setelah persetujuan
   manual inference dan budget/biaya disetujui.
6. Integrasi sembilan node pada satu workflow utama n8n adalah Stage 6.3.6;
   workflow produksi belum diubah pada Stage 6.3.5.

Jika task berstatus `RECONCILIATION_REQUIRED`, jangan kirim role POST dengan
key baru. Periksa raw provider receipt, reservation `OUTCOME_UNKNOWN`, permit,
MP4, dan SHA-256 secara manual. Kode tidak mengulang panggilan ambigu secara
otomatis; job tersebut tetap terblokir sampai ada prosedur rekonsiliasi operator.
