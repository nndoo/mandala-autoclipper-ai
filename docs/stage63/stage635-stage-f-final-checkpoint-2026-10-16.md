# Stage 6.3.5F — checkpoint final lokal

Tanggal: 16 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`. **PASS lokal TEST_ONLY** untuk cakupan
regression, PostgreSQL 16, Docker build/canary, dan audit npm yang dijelaskan
di bawah. Ini bukan hasil deployment atau izin menjalankan provider live.
[Audit F sebelumnya](stage635-stage-f-readiness-audit-2026-10-16.md)
menyimpan keputusan BLOCKED sebelum evidence dipulihkan dan npm diperbarui.

## Evidence asli dan regresi

Checkout lama lokal `/home/nndoo/Projects/mandala-autoclipper-ai` masih
menyimpan evidence Stage 5. Manifest preservasi
`docs/stage61/preservation-baseline.json` di kedua checkout identik SHA-256
`9feeee398001b8735287704b89865a8d9f61aedd821cd6a3ae9fcc4c20407bc8`.
Sebanyak **1.963 file `data/`** (198.457.363 byte total) dicocokkan satu per
satu terhadap path, ukuran, dan SHA-256 manifest, baik di checkout lama maupun
checkout aktif: **1.963 cocok, 0 hilang, 0 berubah**. Pemulihan tidak menimpa
file yang sudah ada dan tidak memakai media sintetis sebagai evidence lama.
`data/` tetap diabaikan Git: bukti lokal ini tidak otomatis ikut clone baru.
Keutuhan byte tidak berarti receipt lama dapat diulang dengan code/environment
saat ini atau pekerjaan historis telah mendapat persetujuan baru.

Sebelum pemulihan, full regression setelah koreksi fixture test berakhir
**1.305 test, 3 FAIL, 33 ERROR**. Kegagalan yang tersisa menunjuk media asli,
packet QA/Director, proof capability, speech assessment, dan checkpoint
benchmark lama yang tidak ada di checkout saat itu. Setelah evidence asli
kembali, log `/tmp/mandala-stage635-regression-restored.log` mencatat
**1.394 test dalam 538,261 detik; OK**, pada Python 3.14.2 dan PostgreSQL
16 lokal TEST_ONLY. Jumlah kasus bertambah karena beberapa suite menemukan
fixture historis secara dinamis. Rerun independen setelah pemulihan kembali
menjalankan **1.394 test dalam 538,152 detik; OK; exit code 0; 0 traceback**.
Log `/tmp/mandala-stage635-final-independent-regression.log` memiliki SHA-256
`bf92ecaacda7d9a9e7d212c01472f138b8426b11198672f3d1f5939c7236c4bc`;
file `.exit` di sebelahnya berisi `0`. Tidak ada skip/error/fail pada hasil
`OK` tersebut. `ruff check scripts tests backend` juga PASS.

Test Revision Loop dan benchmark yang sebelumnya menunjuk path video hilang
sekarang menggunakan fixture MP4 sintetis sementara hanya untuk pengujian
mandiri. Fixture ini tetap diberi label TEST_ONLY, dibersihkan, dan tidak
disalinkan ke path/receipt historis. Full regression sesudah pemulihan kembali
menguji path historis yang asli; engine Stage 5 tidak diubah.

## Remediasi npm dan kompatibilitas

`openclaw@2026.9.9` tetap versi semula. Override terkunci menaikkan dependency
langsung OpenClaw `npm` dari 11.20.0 ke **11.21.1**. Docker stage Node
menaikkan npm global ke versi yang sama sebelum build adapter dan instalasi
runtime. Diff lockfile terbatas pada 13 node di bawah `node_modules/npm` dan
metadata root. Python, Node 24.21.0, 9Router, schema, prompt, dan kode role
tidak berubah. Release [npm 11.21.1](https://github.com/npm/cli/releases/tag/v11.21.1)
memuat versi dependency di bawah; `npm ci` di image dan build TypeScript +
**23/23 test 9Router** PASS.

| Temuan lama pada npm bundled | Lama → image baru | Hasil/risiko |
| --- | --- | --- |
| `brace-expansion` High | 5.0.9 → 5.0.12 | Versi di luar rentang tiga advisori recursion/quadratic lama |
| `http-cache-semantics` High | 4.2.0 → 4.3.0 | Audit tidak melaporkan; catatan perilaku di bawah tetap berlaku |
| `undici` High | 6.28.0 → 6.29.0 | Di atas versi patch 6.28.1 untuk handshake WebSocket |
| `ip-address` Moderate | 10.5.0 → 10.7.2 | Di atas versi patch 10.7.1 untuk pemeriksaan alamat |
| `postcss-selector-parser` Moderate | 7.1.4 → 7.1.6 | Versi patch parser |

`npm audit --omit=dev --json` pada runtime OpenClaw image baru:
**0 critical, 0 high, 0 moderate, 0 low, 0 total**. Audit lockfile adapter
juga nol. npm global dan npm OpenClaw masing-masing 11.21.1, dengan
**1.961 file reguler identik hash**. Image amd64 baru
`sha256:d72d8e08b365ee6355a500f174054e400f7913ad56c5ea6cb49d1618198039f0`
(2.658.592.784 byte) dibangun ulang dari root. `runtime_check` PASS untuk
Python 3.14.2, paket numerik, FFmpeg, font dan file wajib; OpenClaw CLI
2026.9.9 dan subcommand `infer video describe`/`infer model run` dikenali.
Tidak ada provider inference yang dipanggil.

[GHSA-ch52-4w7c-c8xp](https://github.com/advisories/GHSA-ch52-4w7c-c8xp)
masih mencantumkan "patched versions: none" walau rentang terkena berhenti
di 4.2.0. Maintainer [memperselisihkan laporan](https://github.com/kornelski/http-cache-semantics/issues/56)
karena cache bersama harus memakai `Cache-Control: private` untuk respons
privat. `tests/stage635_npm_cache_check.cjs` sengaja mereproduksi perilaku
`max-stale` pada cache bersama dalam 4.3.0 dan memastikan konsumen npm
`make-fetch-happen` memakai `shared: false`; `no-store` juga tidak disimpan.
Test offline ini PASS tanpa request jaringan. Jadi **audit nol bukan bukti
perubahan perilaku cache bersama**. Dari source yang ditelusuri, endpoint
editing memanggil OpenClaw `infer`, bukan npm install/query, dan tidak
menyediakan cache HTTP bersama. Ini penilaian reachability jalur yang diuji,
bukan jaminan semua fitur upstream OpenClaw tidak dapat mencapai npm.
Runtime OpenClaw terisolasi yang terpasang di host Linux masih memuat
`npm@11.20.0`; update ini berlaku pada **image baru**. Host runtime tersebut
tidak dipakai untuk canary image dan belum dinaikkan atau diaudit ulang.

## Docker canary pada image baru

Proof fisik Stage 5 dibuat lagi dari media sintetis melalui image baru dan
volume output TEST_ONLY yang sama; hasilnya PASS. Canary PostgreSQL 16 memakai
database lokal `mandala_stage635_canary`, original read-only ganda, output
terpisah read-write, dan replay provider TEST_ONLY. Migration ulang no-op.
Default image memberi `/health/ready` 503 karena executor live tidak aktif;
replay harness memberi 200 saat gate terpenuhi. Bearer/operator, batas body,
admission, duplicate request, task `QUEUED` → restart container → Analyst
`SUCCEEDED`, empat artifact cocok byte/SHA-256, dan mutasi source sebelum
task berikutnya → `RECONCILIATION_REQUIRED` semuanya PASS. Hak `UPDATE`
sementara pada source role dan checksum migration yang sengaja dirusak
masing-masing menghasilkan readiness 503; hak/checksum dipulihkan dan ready
kembali 200. `human_verified`, `production_eligible`, dan
`publishing_eligible` tetap false. Canary tidak membuka port publik.
Hasil terstruktur lokal ada di `/tmp/mandala-stage635-final-canary-result.json`;
credential tetap pada file env lokal mode 0600 dan tidak dimasukkan Git.

## Keputusan dan batas

Stage 6.3.5 Tahap A–F **PASS dalam cakupan lokal yang teruji**. Dua blocker
teknis audit F lama, yaitu fixture historis yang hilang dan lima temuan npm,
telah ditangani pada checkout/image lokal. Status ini tidak memvalidasi
inferensi provider/ASR berbayar, penilaian editorial manusia, kapasitas VPS,
migration/secret/permission production, koneksi 9Router live, atau deployment
Coolify. Fitur package management OpenClaw di luar jalur role dan advisori
cache yang diperselisihkan tetap perlu dipantau ketika upgrade upstream.

Keputusan pengguna berikutnya, jika menghendaki penggunaan di VPS, adalah
persetujuan **rencana deployment terpisah** setelah review backup DB,
credential/mount, kapasitas, dan langkah rollback. Tidak ada keputusan
human/production/publishing dari checkpoint ini. Stage 6.3.6 belum dimulai.
