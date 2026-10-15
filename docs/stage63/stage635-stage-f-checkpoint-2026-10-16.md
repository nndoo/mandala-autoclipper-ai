# Stage 6.3.5 Recovery — checkpoint Tahap F

Tanggal: 16 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`. **Tahap F BLOCKED untuk kesiapan deployment.**
Build dan canary image lokal TEST_ONLY lulus, tetapi regresi historis penuh
belum dapat lulus tanpa fixture/evidence PC lama dan audit dependensi runtime
masih memiliki lima temuan. Tidak ada deployment, inference live, atau
perubahan production. [Tahap E](stage635-stage-e-checkpoint-2026-10-16.md)
tetap PASS dalam cakupan sintetis lokalnya.

## Perubahan dan image

- `tests/stage635_docker_canary_service.py` adalah harness **TEST_ONLY** yang
  menolak DSN selain database canary lokal, menolak opt-in live, menyuntik
  `TestOnlyReplayProvider`, dan hanya mendengar di loopback container.
  Image production/default tidak memuat harness ini; test memasangnya read-only.
- `tests/test_stage54_planning_integration.py` membuat parent directory
  `data/analyses` yang diabaikan Git sebelum `TemporaryDirectory`. Sebelumnya
  23 kasus ERROR karena parent direktori lokal hilang; setelah perbaikan,
  seluruh 32 kasus modul tersebut PASS. Tidak ada fixture/evidence historis
  yang dibuat.
- Kontrak API, contoh environment, panduan deployment, dan navigasi dokumen
  diperbarui sesuai hasil lokal. Tidak ada perubahan engine Stage 5, migration,
  Media Worker, atau endpoint.
- Full build dari root checkout dengan `backend/Dockerfile` dan provider ID
  non-secret PASS. Image TEST_ONLY lokal berarsitektur amd64, ID
  `sha256:51c3a402aec72abf0d51cea1c081eb54872f083b31c02c98bbf16c049eec091b`,
  ukuran 2.66 GB. Build mengeluarkan dua peringatan lint Dockerfile tentang
  `FROM --platform=linux/amd64` yang konstan; ini target arsitektur VPS yang
  didokumentasikan, bukan kegagalan build.

## Verifikasi Docker dan PostgreSQL

| Pemeriksaan | Hasil lokal TEST_ONLY |
| --- | --- |
| Python, Node, OpenClaw | 3.14.2; 24.21.0; 2026.9.9 (bcfc888) |
| FFmpeg/FFprobe, filter, codec, font | 5.1.9; libx264, AAC, libass dan font DejaVu normal/bold PASS |
| Adapter 9Router | Build TypeScript dan 23 test Node PASS saat image build; manifest cocok dengan provider ID non-secret |
| PostgreSQL 16.15 terisolasi | Database `mandala_stage635_canary`; migration pertama terpasang, kedua no-op, checksum tersimpan cocok dengan source |
| Storage | Dua mount original dari volume TEST_ONLY yang sama read-only; output volume terpisah read-write; `runtime_check` PASS |
| Proof Stage 5 | Physical proof dibuat dan direplay dalam image dan output volume yang sama; PASS, termasuk render media sintetis proof |
| CMD image default | `/health` 200, `/health/ready` 503 karena executor live tidak diaktifkan; fail-closed |
| Executor replay TEST_ONLY | `/health/ready` 200; bearer, token operator, admission original, duplicate key, queue/poll, dan restart container QUEUED → SUCCEEDED PASS |
| Mutasi source setelah queue | Setelah restart, job menjadi `RECONCILIATION_REQUIRED`, tanpa `next_action` baru; artifact sebelumnya (4) cocok byte/SHA-256 dengan DB |
| Readiness negatif | DB tidak terjangkau, checksum migration salah, proof hilang, original alias writable, source role mendapat UPDATE, dan executor default tanpa opt-in masing-masing memberi 503 |
| Konfigurasi Compose | `docker compose -f backend/compose.yaml config -q` PASS dengan nama volume TEST_ONLY |

Container canary dibatasi `3584 MiB` dan `1.5 CPU`, sama dengan batas Compose.
Satu snapshot `docker stats` menunjukkan 121.8 MiB dan 102.77% CPU; angka
ini **bukan** pengukuran peak atau bukti kapasitas VPS. Canary tidak membuka
port 3003 pada host, memakai network namespace PostgreSQL lokal, dan tidak
menyentuh Coolify. Token/DSN acak disimpan di file lokal mode 0600, tidak
ditulis ke repository/laporan.

## Regresi dan blocker

| Suite | Hasil | Makna |
| --- | --- | --- |
| Tahap B–E PostgreSQL/API/role | 44 PASS, 0 FAIL, 0 SKIP | PASS lokal TEST_ONLY dari checkpoint E |
| Stage 5 dengan fixture valid terpilih | 323 PASS, 0 FAIL, 0 SKIP | 2 kasus renderer yang membutuhkan bundle historis dikecualikan eksplisit |
| Stage 5.4 planning integration setelah parent-dir fix | 32 PASS, 0 FAIL, 0 SKIP | Fixture sintetis mandiri |
| Discover penuh sebelum parent-dir fix | 1.305 dijalankan; 12 FAIL, 56 ERROR | **FAILED**; angka PASS tidak diklaim dari run ini |

Discover penuh berjalan 533,819 detik. Dari 56 ERROR, 23 berasal dari parent
`data/analyses` yang tidak ada dan diperbaiki seperti di atas. ERROR lainnya
menunjuk antara lain media asli `mandala-original.mp4`/`cinematic-*.mp4`,
bundle Director/Renderer lama, checkpoint benchmark, dan direktori audit
showcase yang tidak dipulihkan. Delapan FAIL revision loop berasal dari fixture
yang menunjuk source historis yang hilang sehingga validasi audio/source
fail-closed. Dua FAIL benchmark juga berawal dari path renderer/evidence lama
yang hilang; dua FAIL speech provenance menunjuk video asli yang hilang.
Ini klasifikasi berdasarkan traceback, **bukan** pembuktian bahwa semua test
akan lulus setelah evidence dipulihkan. Full discover tidak dijalankan ulang
sesudah perbaikan parent directory; hasilnya tetap FAILED dan tidak boleh
ditampilkan sebagai PASS.

`npm audit --omit=dev` pada image melaporkan **3 high, 2 moderate** dalam
dependensi terbundel `npm` (`brace-expansion`, `http-cache-semantics`,
`ip-address`, `postcss-selector-parser`, `undici`). Percobaan
`npm audit fix --package-lock-only` pada salinan sementara tidak mengubah versi
paket dan masih melaporkan lima temuan; lockfile repository tidak diubah.
Perlu triase versi/upstream dan reachability sebelum izin deployment. Ini
tidak membuktikan eksploitabilitas pada worker, tetapi tidak boleh diabaikan.

## Keputusan

Local integration Tahap D/E dan Docker runtime sintetis Tahap F memiliki bukti
PASS sesuai batas di atas. **Tahap F keseluruhan BLOCKED** karena full
historical regression belum tervalidasi dan temuan audit dependensi belum
ditriase. Coolify deployment readiness dan production eligibility belum
diterbitkan; human review dan publishing approval tetap tidak ada. Lanjutkan
hanya setelah evidence historis yang benar dipulihkan dan diverifikasi,
hasil regresi/triase keamanan ditinjau, serta keputusan deployment terpisah
diambil. Jangan mulai Stage 6.3.6 dari checkpoint ini.
