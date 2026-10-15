# Laporan akhir pekerjaan recovery Stage 6.3.5

Tanggal: 16 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`. **Tahap D PASS, Tahap E PASS, Tahap F BLOCKED.**
PASS D/E berlaku untuk integrasi lokal dengan media sintetis, PostgreSQL 16
terisolasi, dan provider replay `TEST_ONLY`. Build serta canary Docker F lulus,
tetapi Stage 6.3.5 belum dinyatakan siap deploy. Laporan ini merangkum hasil
yang dapat diverifikasi; rincian dan batas masing-masing ada di [checkpoint
D](stage635-stage-d-completion-2026-10-16.md), [E](stage635-stage-e-checkpoint-2026-10-16.md),
dan [F](stage635-stage-f-checkpoint-2026-10-16.md). Checkpoint D parsial
15 Oktober tetap merupakan riwayat blocker sebelum penyelesaian lokal.

## Status tahapan dan sembilan role

| Tahap | Keputusan | Cakupan yang terbukti |
| --- | --- | --- |
| D | **PASS lokal TEST_ONLY** | Sembilan role, physical proof Stage 5, MP4 sintetis, permit satu pakai, QA terpisah, Reviewer dua phase, dan keputusan Revision Controller |
| E | **PASS lokal TEST_ONLY** | Alur HTTP → PostgreSQL → dispatcher → private preview, termasuk replay provider, recovery, idempotency dan pemeriksaan artifact |
| F | **BLOCKED untuk kesiapan deployment** | Image/canary lokal lulus; full historical regression gagal dan temuan audit dependensi belum ditriase |

| Role | Hasil lokal TEST_ONLY |
| --- | --- |
| AI Video Analyst | Respons replay terikat source; reservation mendahului invocation |
| AV Evidence | Packet dan storyboard melalui engine Stage 5 |
| Speech / ASR | Jalur no-speech dan speech sintetis; retry terpilih sampai dua call per region |
| AI Creative Director | Proposal valid/invalid dan batas tiga proposal diuji |
| Independent Validator | Klaim tidak didukung ditolak sebelum render permit |
| FFmpeg Renderer | Physical capability proof Stage 5, permit DB dan `admit()` satu pakai, MP4 aktual sintetis |
| Technical QA | Pemeriksaan mandiri MP4 hasil render PASS; cabang BLOCKED diinjeksi khusus test |
| AI Quality Reviewer | `source_speech` dan `edited_output` terpisah dengan respons replay |
| Revision Controller | Memilih kandidat attempt 2 dari tiga dengan `AUTO_PREVIEW_COMPLETED_WITH_NOTES` |

Output MP4 sintetis melewati FFprobe/decode, QA teknis, hash/ukuran manifest,
dan pencocokan artifact terhadap file/database. Ini membuktikan jalur teknis
TEST_ONLY, bukan akurasi model/ASR live, penilaian editorial manusia, atau
historical evidence dari PC lama. `human_verified`, `production_eligible`,
dan `publishing_eligible` tetap false; tidak ada publish.

## Hasil test dan runtime

Angka pada baris berbeda berasal dari run/cakupan berbeda; jangan dijumlahkan
sebagai satu full regression PASS.

| Pengujian | PASS | FAIL | ERROR | SKIP | Keputusan |
| --- | ---: | ---: | ---: | ---: | --- |
| D role integration + crash permit | 12 | 0 | 0 | 0 | PASS lokal TEST_ONLY |
| D regresi B/C | 30 | 0 | 0 | 0 | PASS lokal |
| D targeted Stage 5 | 33 | 0 | 0 | 0 | PASS dengan fixture valid |
| E integrasi B–E PostgreSQL/API/role | 44 | 0 | 0 | 0 | PASS lokal TEST_ONLY; mencakup ulang role D |
| F Stage 5 fixture valid terpilih | 323 | 0 | 0 | 0 | PASS; dua kasus renderer historis dikecualikan eksplisit |
| F Stage 5.4 planning sesudah perbaikan parent directory | 32 | 0 | 0 | 0 | PASS sintetis mandiri |
| F full unittest discover sebelum perbaikan parent directory | Tidak diklaim | 12 | 56 | Tidak diklaim | **FAILED**, 1.305 test dijalankan; tidak diulang sesudah perbaikan |

Run full discover mengandung 23 ERROR akibat parent `data/analyses` yang
belum ada. Setelah parent dibuat oleh test, modul terkait 32/32 PASS.
Kegagalan lain menunjuk source MP4 asli, bundle Director/Renderer lama,
checkpoint benchmark, dan speech/showcase evidence yang tidak ikut pulih.
Delapan FAIL revision loop, dua benchmark, dan dua speech provenance terkait
path historis yang hilang menurut traceback. Klasifikasi ini tidak
membuktikan bahwa seluruh kasus akan PASS setelah evidence dipulihkan.
Synthetic test tidak dipakai untuk mengisi atau menamai ulang fixture historis.

Image Docker dibangun dari root repository memakai `backend/Dockerfile`:
`mandala-stage635-editing:test-only`, amd64, 2,66 GB, image ID
`sha256:51c3a402aec72abf0d51cea1c081eb54872f083b31c02c98bbf16c049eec091b`.
Python 3.14.2, Node 24.21.0, OpenClaw 2026.9.9 (bcfc888), FFmpeg/FFprobe
5.1.9, libx264, AAC, libass, font DejaVu, adapter 9Router TypeScript build,
dan 23 Node tests lulus di build. Dua peringatan lint Dockerfile untuk
`FROM --platform=linux/amd64` konstan tidak menggagalkan build.

PostgreSQL 16.15 canary lokal memakai database `mandala_stage635_canary`
dalam container/volume TEST_ONLY, bukan database VPS. Migration terpasang
sekali, pengulangan no-op, dan checksum database cocok dengan source. Role
source tetap SELECT-only. Mount original ganda dari volume yang sama
read-only; output memakai volume lain read-write. Proof fisik Stage 5 dibuat
dan direplay di image/output volume yang sama. `runtime_check` lulus.

CMD image default memberi `/health` 200 dan `/health/ready` 503 karena
executor live tidak diaktifkan. Harness replay TEST_ONLY terpisah memberi
`/health/ready` 200 setelah seluruh gate lolos. Canary menguji bearer
workflow/operator terpisah, admission, duplicate request, polling task,
restart container saat task `QUEUED`, dan penyelesaian task Analyst. Keempat
artifact terdaftar cocok byte dan SHA-256 dengan database. Mutasi source
sebelum task berikutnya menghasilkan `RECONCILIATION_REQUIRED`. DB tidak
terjangkau, checksum migration salah, proof hilang, original alias writable,
privilege UPDATE pada source role, dan executor default tanpa opt-in
masing-masing mengembalikan readiness 503. Resource canary dibatasi 3584 MiB
dan 1,5 CPU; satu snapshot 121,8 MiB/102,77% CPU bukan pengukuran peak atau
bukti kapasitas VPS.

## Risiko, file, dan penyimpanan Git

Full historical regression tetap **FAILED**. Evidence asli yang belum ada
meliputi `data/test-videos/mandala-original.mp4`, `cinematic-*.mp4`, bundle
Director/Renderer lama, checkpoint benchmark, dan beberapa bukti speech serta
showcase. Jangan menggantinya dengan media sintetis. `npm audit --omit=dev`
pada image menemukan **3 high dan 2 moderate** dalam dependensi npm
terbundel (`brace-expansion`, `http-cache-semantics`, `ip-address`,
`postcss-selector-parser`, `undici`). Percobaan pembaruan lockfile pada
salinan sementara tidak menyelesaikannya; lockfile repository tidak berubah.
Versi/upstream serta reachability harus ditriase sebelum keputusan deploy.

File source/test yang diubah dalam D–F: `backend/roles/director.py`,
`backend/roles/revision_controller.py`, `backend/roles/speech_asr.py`,
`tests/test_stage635_roles_integration.py`,
`tests/test_stage635_postgres_integration.py`,
`tests/test_stage54_planning_integration.py`; harness baru
`tests/stage635_docker_canary_service.py`. Dokumentasi aktif yang diperbarui:
`AGENTS.md`, `CODEX_PROMPT.md`, `HANDOFF_README.md`, `README.md`,
`backend/roles/README.md`, `backend/.env.example`, `docs/AGENT_GUIDE.md`,
`docs/markdown-catalog.md`, `docs/repository-structure.md`,
`docs/stage63/README.md`, kontrak API dan deployment guide Stage 6.3.5,
checkpoint D/E/F, serta laporan ini. Tidak ada perubahan Media Worker,
schema migration, prompt OpenClaw, historical receipt, atau engine Stage 5.

Commit milestone pada branch WIP:

| Milestone | Commit SHA | Status push |
| --- | --- | --- |
| D | `40102caa8a673c1c3e59289952d96a49ab595edb` | Diterima `origin/wip/stage-6.3.5-recovery` |
| E | `4b9cf4ad5f7787968563191728474948735e39a5` | Diterima `origin/wip/stage-6.3.5-recovery` |
| F BLOCKED | `b735977f4284f451dc159902caf40fcaee713c7c` | Remote branch diverifikasi menunjuk commit ini sesudah push F |

Commit laporan ini diverifikasi terpisah setelah push; SHA-nya tidak dapat
dicantumkan dalam file yang sama tanpa mengubah SHA tersebut.

**Keputusan berikutnya:** integrasi lokal D/E dan runtime Docker sintetis
memiliki bukti PASS sesuai cakupannya. Kesiapan deployment Coolify,
production eligibility, human review, dan publishing approval **belum ada**.
Pulihkan evidence historis asli, jalankan ulang regresi yang tertahan,
triase audit dependensi, lalu minta keputusan deployment terpisah. Jangan
mulai Stage 6.3.6, inference berbayar, perubahan n8n/Coolify/VPS/production
DB, atau deploy dari laporan ini.
