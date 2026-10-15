# Stage 6.3.5 Recovery — checkpoint Tahap B

Tanggal: 15 Oktober 2026 (Asia/Jakarta). Branch `wip/stage-6.3.5-recovery`,
HEAD `0c92c6a61703`. Status: **Tahap B selesai untuk PostgreSQL 16 lokal dan
data TEST_ONLY**. Tidak ada perubahan Media Worker, engine Stage 5, VPS,
Coolify, n8n, atau database production; tidak ada inference, commit, push,
atau deploy.

## Environment dan batas isolasi

- Docker daemon lokal aktif. Akun `nndoo` tercatat pada grup `docker`, tetapi
  proses shell ini belum mewarisi grup tersebut; akses Docker dilakukan dengan
  `sg docker`. Tidak ada perubahan konfigurasi host atau daemon.
- Container `mandala-stage635-pg16-local` menggunakan image
  `postgres:16-alpine` dan server PostgreSQL **16.15**. Port hanya diterbitkan
  pada loopback `127.0.0.1:32768`; data PG berada pada mount `tmpfs` di
  `/var/lib/postgresql/data`, dengan batas memori container 1 GiB dan 1 CPU.
  Container memakai `--rm`, sehingga data TEST_ONLY hilang saat dihentikan.
  Container lokal tetap berjalan untuk inspeksi lanjutan; port sementara harus
  ditemukan kembali dengan `docker port` bila container dibuat ulang.
- Database lokal bernama `mandala_stage635_test`. Kredensial acak sementara
  disimpan di `/tmp/mandala-stage635-pg16.env` dengan mode `0600`; nilainya
  tidak dicatat di dokumen/log. Test menolak DSN yang bukan host
  `127.0.0.1`, nama database tersebut, atau server major 16.
- Pengujian memakai `.venv-av/bin/python` 3.14.2, `psycopg` dari lockfile,
  dan MP4 sintetis 1,2 detik yang dibuat dengan FFmpeg dalam direktori
  sementara. Tidak ada media/receipt historis yang dijadikan fixture.

## Implementasi

- `backend/migrations/001_editing_jobs.sql`: schema `mandala_engine` dengan
  `jobs`, `tasks`, `call_reservations`, `artifacts`, `permits`, `job_events`,
  `schema_migrations`, dan `idempotency_keys`. Tabel kedelapan diperlukan
  untuk namespace idempotency global per principal, lintas admission dan
  task. FK, check constraint, unique source, satu task aktif per job,
  reservation attempt, serta permit per job/attempt dijaga di database.
- `backend/editing_store.py`: migration ber-checksum dan lock transaksi;
  job state/version/next action dan event dalam transaksi yang sama;
  idempotency replay sebelum version check; claim dengan
  `FOR UPDATE SKIP LOCKED`; lease epoch, heartbeat, fencing, dan recovery
  konservatif; ledger paid call sebelum efek; manifest file relatif/hash;
  permit private-preview sekali pakai. Reservasi tak definitif tidak dapat
  menyelesaikan task sebagai sukses. Flag human/production/publishing tetap
  `false` oleh constraint.
- `backend/source_admission.py`: request admission sesuai kontrak
  `stage6.3.5-v1`; baca `public.source_videos` dengan role SELECT-only dan
  transaksi read-only; pakai `backend.media_worker.intake_adapter.prepare_intake`
  Stage 6.3.2 tanpa modifikasi; baca ulang row sebelum persist. Adapter
  memeriksa `ORIGINAL_READY`, identitas/path original, SHA-256, FFprobe,
  batas 20 MiB dan 180 detik. Admission yang idempotent tidak memeriksa ulang
  media bila key+body sama karena respons awalnya telah dicatat.
- `tests/test_stage635_postgres_integration.py`: fixture source/role/database
  TEST_ONLY, MP4 sintetis, dan pengujian transaksi PostgreSQL nyata.

## Bukti pengujian

| Pemeriksaan | Hasil |
| --- | --- |
| Migration pertama pada DB lokal kosong | PASS: terpasang sekali, 8 tabel schema `mandala_engine` |
| Migration kedua dan test idempotensi/checksum | PASS: tidak mengulang migration; 1 row `schema_migrations` |
| Integration PostgreSQL 16 | **16 PASS**, 0 FAIL, 0 SKIP; server 16.15 |
| Intake Adapter Stage 6.3.2 existing | **10 PASS**, 0 FAIL |
| `ruff check scripts tests backend` | PASS |
| `git diff --check` | PASS |

Integration mencakup source `ORIGINAL_READY` dan snapshot FFprobe/hash,
penolakan status/path/hash/ukuran/durasi/resolusi salah, perubahan byte MP4
dengan ukuran tetap, perubahan row saat admission, role source SELECT-only,
duplicate admission dan transaksi paralel, idempotency lintas route,
optimistic version, claim paralel, epoch fencing, lease expiry tanpa efek
dan dengan efek, reservation budget/unknown outcome, manifest path/hash,
serta permit sekali pakai. Kasus batas 20 MiB/180 detik diuji melalui row
metadata yang melampaui batas; tidak ada paid inference atau render historis.

## Batas dan tindak lanjut Tahap C

- Ini bukti **integrasi lokal TEST_ONLY**, bukan bukti kesesuaian schema/izin
  source database production, koneksi layanan, atau readiness deploy. Mapping
  source row production perlu diperiksa tanpa mengubah DB tersebut sebelum
  wiring layanan.
- Belum ada HTTP API, autentikasi operator/workflow, orkestrasi sembilan role,
  atau panggilan provider. Fungsi persetujuan paid inference baru berupa
  transisi persistence; otorisasi operator wajib dipasang di Tahap C sebelum
  dipanggil dari layanan.
- Recovery mendeteksi marker efek, reservation, permit terpakai, dan artifact
  terdaftar. File output yatim tanpa row DB setelah crash harus ditemukan
  melalui rekonsiliasi filesystem pada orkestrasi Tahap C; worker harus
  menulis marker efek **sebelum** efek/file pertama. Source harus diverifikasi
  ulang saat eksekusi karena file dan DB tidak memiliki transaksi bersama.
- Ledger membatasi jumlah call per kind/region dan menyimpan outcome
  terstruktur. Bukti bahwa source Reviewer hanya dipanggil setelah putaran
  ASR yang admitted, pemetaan receipt Stage 5, serta klasifikasi outcome
  provider harus diikat oleh orkestrator Tahap C sebelum paid call diizinkan.
- `permit` DB belum terhubung ke `Stage 5 admit()` dan writer
  `permit-consumed.json`; sambungan dan uji crash antarlangkah termasuk
  Tahap C. Tidak ada production/publishing gate yang dibuka.

**Kesiapan Tahap C:** persistence dan admission lokal tersedia serta integration
PASS. Tahap C boleh dimulai hanya dengan fokus pada wiring API/role,
autentikasi, pengikatan evidence dan recovery file, tanpa menganggap hasil
lokal ini sebagai izin inference atau deploy.
