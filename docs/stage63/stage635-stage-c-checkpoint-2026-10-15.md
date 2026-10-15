# Stage 6.3.5 Recovery — checkpoint Tahap C

Tanggal: 15 Oktober 2026 (Asia/Jakarta). Branch
`wip/stage-6.3.5-recovery`, HEAD `0c92c6a61703`.
Status: **Tahap C selesai untuk API/queue/recovery lokal TEST_ONLY**.
Tidak ada commit, push, deploy, paid inference, render production, publish,
atau perubahan VPS, Coolify, n8n, database production, dan Media Worker :3002.

## File Tahap C

| File | Perubahan |
| --- | --- |
| `backend/editing_api.py` | HTTP routing, auth, validasi, respons aman, readiness |
| `backend/editing_dispatch.py` | Queue loop, heartbeat, source revalidation, orphan/recovery scan, kontrak sembilan role dan executor mock TEST_ONLY |
| `backend/editing_worker.py` | Entrypoint service :3003 dan pembuat server/dispatcher |
| `backend/editing_store.py` | Read-only migration gate, manifest/recovery query, quarantine transaksional |
| `backend/source_admission.py` | Revalidasi original source sebelum efek task |
| `backend/runtime_check.py` | Inventaris file runtime baru |
| `backend/requirements.in`, `backend/.env.example`, `backend/roles/README.md` | Koreksi komentar/dokumentasi agar sesuai Stage C; dependency tidak berubah |
| `tests/test_stage635_api_integration.py` | Integration HTTP, PostgreSQL 16, worker, dan recovery TEST_ONLY |
| `tests/test_editing_worker_runtime.py` | Liveness tetap 200 ketika readiness blocked |

Migration Tahap B tidak diubah. Stage 5 dan `backend/media_worker/` tidak diubah.

## Endpoint dan batas layanan

Delapan endpoint kontrak terimplementasi: `GET /health`, `GET /health/ready`,
`POST /v1/jobs`, `POST /v1/jobs/{id}/approve-inference`,
`POST /v1/jobs/{id}/roles/{role}`, `GET /v1/jobs/{id}`,
`GET /v1/tasks/{id}`, dan `GET /v1/jobs/{id}/artifacts`.
Semua endpoint `/v1/*` memakai bearer workflow; approval juga mensyaratkan
token operator terpisah. Token minimal 32 karakter dan berbeda, dibandingkan
sebagai digest SHA-256 melalui `hmac.compare_digest`. JSON UTF-8 wajib,
body maksimal 64 KiB, duplicate JSON key ditolak, dan respons gagal tidak
berisi secret/raw exception. Access log handler tidak menulis path/header.
Job/task GET tidak mengekspos absolute original path atau source snapshot.

`/health` adalah liveness murah dan selalu mengembalikan `roles_ready=false`.
Gate `/health/ready` mensyaratkan konfigurasi, runtime/storage checker,
checksum dan keberadaan tabel migration, koneksi serta hak SELECT-only source,
replay proof Stage 5, dan executor. Service yang dibuat dari environment
Tahap C **tidak memasang executor nyata**, sehingga readiness production
tetap 503 dan POST tetap fail-closed. Hanya test server dengan executor
mock TEST_ONLY dan proof/runtime checker terisolasi yang mencapai readiness
200. Tidak ada bukti proof Stage 5 aktual pada image/volume produksi.

Role/phase untuk sembilan role (Reviewer memiliki dua phase) divalidasi di
HTTP dan hanya `next_action` server yang boleh diterima store. Submission
merespons 202 setelah antrean DB ditulis; tidak menjalankan role inline.
Mock executor selalu menghasilkan status `BLOCKED` berlabel `TEST_ONLY_*`,
tanpa provider, render, artifact/evidence palsu, atau status QA/human PASS.

## Queue, recovery, dan security verification

- Queue menggunakan `FOR UPDATE SKIP LOCKED` dari Tahap B; constraint DB
  membatasi satu task aktif per job. Claim menaikkan lease epoch; heartbeat
  memperpanjang lease. Result lama ditolak oleh owner/epoch fencing.
- Dispatcher membaca ulang row dan original MP4 memakai Intake Adapter
  Stage 6.3.2 sebelum marker efek dan executor. Source berubah masuk
  `RECONCILIATION_REQUIRED`, tanpa menjalankan mock executor.
- Sebelum requeue task kedaluwarsa, dispatcher memeriksa file di direktori
  output job terhadap manifest DB: orphan, hilang, hash/ukuran berbeda, atau
  path tidak aman mengarantina job secara transaksional. Task RUNNING dengan
  lease masih aktif tidak dipindai agar output yang sedang ditulis tidak
  salah dianggap orphan. Marker efek, reservation, permit, dan artifact DB
  dari Tahap B tetap membuat recovery konservatif; efek ambigu tidak diulang.
- Approval inference tetap aksi manual melalui token operator. Tidak ada
  perubahan n8n dan tidak ada token operator yang diberikan ke workflow.

## Hasil pengujian

PostgreSQL lokal `mandala-stage635-pg16-local` (server 16.15, loopback,
tmpfs) digunakan kembali. Semua data baru berlabel TEST_ONLY dan memakai MP4
sintetis; integration test menolak DSN non-loopback, nama DB lain, dan major
version selain 16.

| Suite | Hasil |
| --- | ---: |
| Stage C HTTP/queue/recovery PostgreSQL integration | 14 PASS |
| Stage B PostgreSQL integration regresi | 16 PASS |
| Editing worker runtime/storage | 10 PASS |
| Intake Adapter Stage 6.3.2 | 10 PASS |
| **Total targeted** | **50 PASS, 0 FAIL, 0 SKIP** |

Integration Tahap C menguji auth tanpa/salah token, perbandingan digest,
approval operator, validasi JSON/64 KiB, admission dan duplicate request,
submission paralel/idempotency, background dispatcher, lease expiry,
worker ID baru, proses worker terpisah yang keluar setelah marker efek,
source mutation, orphan file, manifest mismatch, dan readiness fail-closed
ketika proof/migration/storage/source privilege/executor tidak memenuhi gate.
`ruff check scripts tests backend`, `py_compile`, dan `git diff --check`
PASS. Full regression Stage 5 berbasis historical evidence belum dijalankan.

## Batas dan kesiapan Tahap D

- Service produksi masih **roles_ready=false / HTTP 503** sampai executor
  role nyata dipasang dan proof Stage 5 direplay pada image, kode, environment,
  dan volume yang sama. Tes mock memakai proof/runtime checker suntikan;
  hasilnya bukan bukti mount Docker atau proof image PASS.
- Belum ada integrasi sembilan engine role, receipt/provider outcome,
  pengikatan ASR-source Reviewer, permit DB ke writer Stage 5, rendering,
  Technical QA aktual, atau provider call. Seluruhnya tetap Tahap D/lanjutan
  sesuai scope yang disetujui pengguna.
- Orphan scan mengarantina job nonterminal yang memiliki direktori output
  ber-ID job. Audit untuk file tanpa job ID, dan artifact job terminal yang
  berubah setelah selesai, tetap memerlukan prosedur/operator terpisah.
  Revalidasi source dan efek provider/file tidak dapat dijadikan satu
  transaksi; executor nyata harus mengulang gate sebelum setiap efek dan
  menghormati marker serta lease fencing.
- Source schema/privilege production, image build, mount RO/RW, proof aktual,
  kapasitas service, dan deployment belum diperiksa di VPS/Coolify. Tidak ada
  kesiapan inference berbayar atau production/publishing yang diklaim.

**Kesiapan Tahap D:** kontrak HTTP, persistence wiring, dispatcher, dan
recovery dasar siap sebagai fondasi lokal. Tahap D perlu menyambungkan role
nyata satu per satu dan memperoleh proof image serta pengujian efek/crash
tanpa melonggarkan gate readiness.
