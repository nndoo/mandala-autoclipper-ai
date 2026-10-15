# Stage 6.3.5 Recovery — checkpoint Tahap A

Tanggal: 15 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`, HEAD `0c92c6a617033e57b9b7fcc1b9388f5b81ccca12`.
Status: **TAHAP A SELESAI; desain dibekukan untuk Tahap B, belum diimplementasikan**.
Dokumen ini melengkapi `stage635-api-contract.md` dan
`stage635-deployment-guide.md` yang dipulihkan. Laporan implementasi Windows
adalah riwayat, bukan bukti source tersedia di checkout ini.

## Environment dan baseline yang benar-benar diuji

| Pemeriksaan | Hasil Tahap A |
| --- | --- |
| Python | `.venv-av` baru, CPython 3.14.2 (`.python-version`) |
| Dependency | Sembilan paket dari `backend/requirements.lock.txt`, wheel-only dan `--require-hashes`; NumPy 2.5.4, SciPy 1.18.1, jsonschema 4.25.1, psycopg 3.3.6 berhasil diimpor |
| FFmpeg/FFprobe | Host 6.1.1-3ubuntu5; `renderer_core_v01.environment()` membuktikan filter wajib, libx264, AAC, libass, font normal/bold tersedia. Ini inventaris, bukan proof image Docker. |
| Node/OpenClaw | Node bundled 24.21.0; wrapper isolated melaporkan OpenClaw 2026.9.9 (bcfc888) dengan state/config sementara tanpa inference. Node PATH umum 24.19.0 tidak digunakan untuk verifikasi adapter. |
| Adapter 9Router | Binding non-secret dari provider ID default Compose diregenerasi; `npm ci --offline` dari package-lock, `npm run build`, `tsc --noEmit`, dan `npm test` PASS (23 tes). Binding, manifest, dist, dan node_modules adalah output lokal yang diabaikan Git. Tes transport memakai mock; tidak membuktikan koneksi/provider live. |
| Lint | `ruff check --no-cache scripts tests backend` PASS. |
| Docker | CLI 29.7.2 tersedia, tetapi daemon lokal tidak aktif. Context `default` dan `desktop-linux` sama-sama tidak memiliki socket yang dapat dihubungi. Full image build belum dapat dijalankan sebelum daemon lokal tersedia. |

Tes Python dijalankan dengan `.venv-av/bin/python -B -m unittest`:

| Suite | PASS |
| --- | ---: |
| `test_automatic_editing_v01.py` | 19 |
| `test_automatic_preview_policy_v02.py` | 14 |
| `test_adaptive_av_evidence_v01.py` | 78 |
| `test_remote_speech_evidence_v01.py` | 33 |
| `test_renderer_v01.py` | 94 |
| `test_video_quality_remediation_v01.py` | 14 |
| `test_intake_adapter_stage632.py` | 10 |
| `test_editing_worker_runtime.py` | 10 |
| `FFmpegIntegrationTests` dalam `test_renderer_ffmpeg_v01.py` | 51 |
| **Total targeted** | **323** |

Pada suite FFmpeg, dua kasus yang membaca bundle `pak-fuad.live.v01` dan
`showcase.live.v01` tidak dijalankan; 51 kasus yang dijalankan membuat sumber dan
MP4 sintetis sendiri, lalu memeriksa decode, PTS, audio, efek, receipt, dan
penolakan. Tidak ada tes Tahap A yang memanggil paid inference. Perintah full
regression belum dijalankan karena `data/` historis belum tersedia.

## Kontrak Tahap B yang dibekukan

Source Stage 5 (`scripts/`, schema, prompt, adapter) digunakan kembali. Sembilan
role tetap satu service port 3003, satu endpoint per role; AV Evidence/ASR dan
Renderer/Technical QA terpisah. Reviewer memiliki phase `source_speech` dan
`edited_output`. n8n kelak hanya mengikuti `next_action`; backend menjadi
pemilik state, budget, permit, dan keputusan kandidat. Tahap B tidak perlu
menambah layanan/model baru atau mengganti Media Worker port 3002.

### HTTP dan trust boundary

- Versi `stage6.3.5-v1`, JSON UTF-8 maksimal 64 KiB, UUID untuk job/task,
  `Content-Type: application/json`. Semua `/v1/*` memerlukan bearer workflow;
  endpoint approval juga memerlukan `X-Operator-Token` berbeda. Keduanya minimal
  32 karakter, dibandingkan dengan cara yang tidak membocorkan perbedaan waktu,
  tidak ditulis ke log, respons, atau artifact. Tidak ada endpoint publish.
- `GET /health` tetap liveness dan murah. `GET /health/ready` memberi 200 hanya
  bila migrasi editing, DB, mount originals RO pada kedua alias, output RW
  terpisah, dan proof Stage 5 pada code/environment image itu lolos; selainnya
  503. Role POST saat belum ready memberi 503. Proof direplay lagi saat render.
- `POST /v1/jobs`: body persis `contract_version`, `source_key`,
  `expected_sha256`. Baca `public.source_videos` memakai credential SELECT-only
  dan transaksi read-only; row wajib ORIGINAL_READY. Pakai
  `prepare_intake()` existing untuk identity, path, byte/hash, FFprobe, dan batas
  20 MiB/180 detik. Baca ulang row/source saat eksekusi sebelum efek.
  Admission sukses: 201 dengan job baru pada `AWAITING_INFERENCE_APPROVAL`.
  Source yang sudah admitted dengan key lain: 409, agar tidak ada job berbayar
  ganda untuk original yang sama. Source berbeda pada key yang sama: 409.
- `POST /v1/jobs/{id}/approve-inference`: body persis
  `{"decision":"approve_paid_inference","human_reviewed":true}`. Aksi manual
  operator per job, menghasilkan approval event sekali dan mengubah job menjadi
  `AWAITING_DISPATCH` dengan next action `analyst/analyze`. Panggilan identik
  berikutnya mengembalikan 200 tanpa approval kedua. Approval inference tidak
  mengubah `human_verified`, `production_eligible`, atau
  `publishing_eligible`.
- `POST /v1/jobs/{id}/roles/{role}`: body persis `contract_version`,
  `expected_job_version`, `phase`, `attempt`, `input_artifact_ids`, dan hanya
  untuk retry ASR `regions` bila `next_action` memuatnya. Role, phase, attempt,
  regions, version, dan daftar artifact harus identik dengan `next_action`
  authoritative. Sukses 202 dengan task QUEUED; tidak menjalankan role inline.
  Satu job maksimal satu task aktif.
- `GET /v1/tasks/{id}` dan `GET /v1/jobs/{id}` hanya menampilkan ID, state,
  version, status gate terpisah, failure class, dan `next_action` job terkini.
  `GET /v1/jobs/{id}/artifacts` mengembalikan ID, path relatif di output root,
  SHA-256, dan byte; tidak ada absolute source path, credential, atau raw secret.
  Setiap GET 200 tetap harus dibaca dari field status, bukan dianggap QA PASS.
- Respons gagal: 401 auth, 404 ID tak ditemukan, 409 konflik state/key/version,
  413 body terlalu besar, 415 media type salah, 422 schema/range/contract salah,
  503 readiness/dependency. Respons JSON memiliki `error.code` stabil dan
  `error.message` aman tanpa secret atau raw provider response.

Role/phase: `analyst/analyze`, `av-evidence/measure`,
`speech-asr/transcribe`, `director/propose`, `validator/validate`,
`renderer/encode`, `technical-qa/inspect`, `reviewer/source_speech`,
`reviewer/edited_output`, `revision-controller/decide`. Controller/role awal/ASR
memakai `attempt=0`; proposal, validator, renderer, QA, dan output Reviewer
memakai attempt 1–3. Nomor panggilan ASR per region disimpan di reservation
internal 1–2; tidak ditulis ulang menjadi attempt HTTP. Source Reviewer boleh
diulang hanya sebagai akibat putaran ASR yang sah. Semua input task adalah ID
artifact terbitan server, tanpa URL, path, FFmpeg argument, atau filter dari n8n.

### Idempotency dan state

- `Idempotency-Key` wajib pada POST admission/role, 1–128 karakter aman. Namespace
  unik per workflow principal; simpan key, method+path, digest JSON canonical,
  response ID, dan hasil awal secara durable. Periksa idempotency **sebelum**
  expected version. Key+route+body identik mengembalikan job 201 atau task 202
  yang sama walaupun version kini lebih tinggi. Key sama dengan route/body lain
  memberi 409. Key baru untuk role saat task masih aktif atau version lama juga
  409. Tidak ada expiry key selama job disimpan.
- Job: `AWAITING_INFERENCE_APPROVAL` -> `AWAITING_DISPATCH` -> `QUEUED` ->
  `RUNNING` -> `AWAITING_DISPATCH` setelah outcome role definitif dan Controller
  menentukan langkah berikut. Outcome terakhir hanya
  `AUTO_PREVIEW_COMPLETED`, `AUTO_PREVIEW_COMPLETED_WITH_NOTES`, `BLOCKED`,
  `FAILED`, atau `RECONCILIATION_REQUIRED`. Terminal immutable. Paid role tidak
  mendapat `next_action` saat approval belum ada. Semua perubahan state menaikkan
  `job.version` dan menambah `job_events` dalam transaksi yang sama.
- Setelah role non-Controller selesai secara definitif, backend menerbitkan
  `revision-controller/decide` sebagai next action, termasuk bila role BLOCKED.
  Controller yang menentukan retry terbatas, kandidat terbaik tanpa blocker,
  atau terminal. Task `SUCCEEDED` berarti output role valid, bukan human/QA PASS.
  Task terminal adalah `SUCCEEDED`, `BLOCKED`, `FAILED`, atau
  `RECONCILIATION_REQUIRED`; task GET menyalin next action job terkini.
- Status `technical_qa`, `model_assessment`, `human_verified`,
  `production_eligible`, `publishing_eligible` dipisah. Dua flag terakhir dan
  human verification tetap false pada Stage 6.3.5. Model self-report tidak
  menaikkan gate teknis atau manusia.

### Reservation, lease, permit, dan recovery

- Semua paid call mempunyai baris `call_reservations` sebelum invocation:
  `RESERVED` -> `SENT` -> `RECORDED`, atau `OUTCOME_UNKNOWN`. Reservation
  menghabiskan budget sejak `RESERVED`, termasuk respons rusak/gagal. Maksimal
  satu Analyst per job, tiga Director proposals, dua ASR call **per region**,
  satu edited Reviewer per proposal, dan source Reviewer hanya per putaran ASR
  admitted. Tidak ada retry otomatis pada outcome provider ambigu. Riwayat raw
  yang aman, usage provider-reported, serta error class disimpan; nominal biaya
  tidak dikarang.
- Worker mengklaim task QUEUED dengan transaksi `FOR UPDATE SKIP LOCKED`, satu
  worker aktif per container pada awalnya. Claim menaikkan `lease_epoch` dan
  memasang lease berbasis waktu DB 60 detik; heartbeat tiap 15 detik. Hanya
  epoch/current owner yang boleh commit hasil. Hasil terlambat ditolak, tidak
  boleh membuat artifact terdaftar/next action. Job punya maksimal satu task
  aktif melalui constraint DB, bukan hanya pemeriksaan Python.
- Setelah restart, task QUEUED tetap dapat diklaim. RUNNING yang lease-nya
  kedaluwarsa hanya dapat diulang dengan epoch baru bila durable marker
  menyatakan efek belum dimulai dan tidak ada output/reservation yang ambigu.
  Setelah marker `SENT`, konsumsi permit, atau penulisan artifact yang belum
  terkonfirmasi, task/job menjadi `RECONCILIATION_REQUIRED` dan reservation
  menjadi `OUTCOME_UNKNOWN` bila perlu. Key baru dan Controller tidak membuka
  jalan retry otomatis. Tidak ada endpoint operator untuk menyatakan efek aman
  dalam v1; investigasi manual memakai DB event, raw receipt, permit, MP4, dan
  SHA-256, lalu prosedur terpisah yang ditinjau operator.
- Render memakai permit DB unik per job/attempt, hanya untuk private preview.
  Konsumsi DB dilakukan sebelum memanggil Stage 5 `admit()` yang masih menulis
  `permit-consumed.json` secara eksklusif. Crash di antara dua langkah ini
  tetap ambigu dan tidak membuat permit baru otomatis. Renderer menghasilkan
  `ENCODED_QA_PENDING`; Technical QA terpisah memeriksa MP4 aktual sebelum
  edited Reviewer. Bundle Stage 5 tetap di path output baru dan tidak
  menimpa bundle historis.
- Artifact didaftarkan setelah file baru selesai ditulis, ditutup, dan di-hash;
  path selalu relatif terhadap output root yang dijaga. DB row tidak membuat
  file historis mutable. File tanpa row atau row/hash tidak cocok setelah crash
  masuk rekonsiliasi, bukan diregistrasi ulang tanpa pemeriksaan.

## Fixture yang belum ada dan strategi pengganti

Isi `data/` historis absen dalam clone ini; `.gitignore` memang
mengecualikannya. Tes sintetis Tahap A membuat direktori kerja kosong di bawah
`data/render-tests/stage55`, tanpa media atau receipt historis. Yang diperlukan
oleh full regression meliputi setidaknya:

- `data/test-videos/mandala-original.mp4` dan
  `cinematic-7693770515172887829.mp4`, beserta metadata/canonical Universal V0.2;
- speech/alignment/raw review bundle di `data/analyses/speech-v01/` dan
  `data/analyses/aligned-v2/`;
- director packets/plans di `data/analyses/director/adaptive-v03/`, termasuk
  `pak-fuad.live.v01` dan `showcase.live.v01`;
- QA/render/revision/benchmark evidence historis di `data/qa/stage56/`,
  `data/render-tests/stage55/`, `data/render-tests/stage57/`,
  `data/revisions/stage57/`, `data/revisions/stage59/`, dan
  `data/benchmarks/stage58/`.

Setidaknya 10 modul test mereferensikan `data/` historis secara eksplisit;
sebagian kasus dalam modul itu tetap mandiri. Full regression tidak dianggap
PASS sebelum fixture yang tepat dipulihkan dan diverifikasi hash/provenance.
Jangan mengisi path/receipt lama dengan hasil sintetis untuk membuat tes lolos.

Untuk Tahap B, buat fixture baru dengan ID, direktori, dan label `TEST_ONLY`
sendiri: MP4 sintetis speech-free dan speech-like, row source PostgreSQL 16
isolated, provider mock yang menghasilkan response/usage atau timeout, dan
output bundle baru. Uji jalur source hash/probe, idempotency/concurrency,
reservation, lease fencing, permit sekali pakai, QA aktual, serta restart/crash
di setiap batas efek. Hasilnya hanya bukti rekonstruksi sintetis, bukan bukti
akurasi ASR, mutu editorial nyata, kesiapan production, atau pengganti riwayat
Stage 5. Full image build dan full Stage 5 Linux regression tetap gerbang
terpisah sebelum kesiapan deploy.

## Batas checkpoint

Tahap A siap menjadi dasar Tahap B pada lingkungan lokal. Daemon Docker lokal
perlu diaktifkan sebelum PostgreSQL 16 isolated atau image build berbasis
container. Migration, API, role, DB 16 isolated, image build, proof image, synthetic E2E Stage 6.3.5,
restart/recovery, full regression Stage 5, provider live, dan deployment **belum
dijalankan**. Source Stage 6.3.4 serta Media Worker tidak diubah; tidak ada
commit, push, deploy, atau paid inference.
