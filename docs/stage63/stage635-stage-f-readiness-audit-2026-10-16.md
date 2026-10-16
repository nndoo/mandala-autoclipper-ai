# Stage 6.3.5F — audit regresi dan dependensi runtime

Tanggal: 16 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`. **Deployment readiness: BLOCKED.** D/E tetap
PASS dalam cakupan lokal TEST_ONLY. Build dan canary Docker pada [checkpoint
F](stage635-stage-f-checkpoint-2026-10-16.md) tetap merupakan bukti untuk
image yang sama. Tidak ada deploy, paid inference, atau perubahan production.

## Audit regresi

| Kelompok dari run awal | Jumlah | Diagnosis dan tindakan |
| --- | ---: | --- |
| Parent `data/analyses` belum ada | 23 ERROR | Setup Stage 5.4 diperbaiki pada checkpoint F; modulnya 32/32 PASS |
| Fixture historis hilang | 32 ERROR | Media asli, packet/QA Showcase, bundle Director/Renderer, speech assessment dan checkpoint benchmark belum dipulihkan |
| Parent audit Showcase belum ada | 1 ERROR | Setup test kini membuat parent sementara; selanjutnya tetap gagal karena packet Showcase historis hilang |
| Revision Loop offline menunjuk media lama | 8 FAIL | Fixture test kini membuat MP4 TEST_ONLY sementara dengan SHA-256 nyata; suite 137 PASS, 0 FAIL/ERROR/SKIP |
| Canary benchmark mock menunjuk video lama | 1 FAIL | Test kini membuat video sintetis sementara; targeted test PASS |
| Validasi plan benchmark | 1 FAIL | Membutuhkan receipt capability Stage 5.5 `capabilities.v05.json` yang belum ada; tidak dibuat palsu |
| Speech provenance real media | 2 FAIL | `mandala-original.mp4` dan `cinematic-*.mp4` asli belum ada |

Untuk FAIL benchmark, trace terarah menunjukkan `preview.validate_plan`
berhasil, lalu `qa.ref` meminta `capabilities.v05.json` yang tidak ada dan
job menjadi `PLANNING_FAILURE`. Ini membedakannya dari kegagalan validator.

Full discover sebelum perbaikan direktori: **1.305 test, 12 FAIL, 56 ERROR**.
Sesudah perbaikan direktori dengan PostgreSQL 16 lokal TEST_ONLY: **1.305
test dalam 540,494 detik, 12 FAIL, 33 ERROR, 0 SKIP**. Run itu mengimpor
test sebelum perbaikan fixture offline. Run berikutnya, sesudah perbaikan
fixture pertama, menjalankan **1.305 test dalam 537,025 detik: 3 FAIL,
37 ERROR, 0 SKIP**. Delapan FAIL Revision Loop dan satu FAIL canary hilang;
empat ERROR baru adalah `NameError` karena tiga test Creative Text dan satu
test Speech mengimpor helper `sample()` sebelum setup modul Revision Loop.
Helper kini membuat media secara lazy; targeted Revision Loop **137 PASS**,
empat test pengimpor **4 PASS**, dan canary benchmark **1 PASS**, masing-masing
0 FAIL/ERROR/SKIP. Full
discover **belum dijalankan lagi sesudah koreksi lazy helper**; jadi 3 FAIL/
37 ERROR adalah hasil full terakhir, bukan klaim hitungan final tersisa.
Angka PASS total tidak disimpulkan dari output unittest yang hanya mencatat
jumlah test, FAIL, ERROR dan SKIP.
Synthetic media berada di direktori sementara TEST_ONLY dan dibersihkan;
tidak mengisi path asli atau mengubah receipt historis. Validator dan engine
Stage 5 tidak diubah.

Ke-33 ERROR historis pasca perbaikan direktori tersebar sebagai berikut:
`test_video_quality_v01` 20 (packet QA Showcase), `test_benchmark_v01` 4,
`test_adaptive_director_input_v03` 2, `test_renderer_ffmpeg_v01` 2,
`test_speech_intelligence_v01` 2, serta masing-masing 1 di
`test_director_diagnostics_v01`, `test_prepare_speech_review_v01`, dan
`test_showcase_preview_v01`. Jejak error terakhir menunjukkan path
historis yang tidak tersedia; ini **bukan** bukti semua test akan lulus
jika file tersebut nanti dipulihkan.
Traceback yang ada tidak menunjukkan regresi engine/backend aktif sebagai
akar kegagalan tersisa, tetapi fixture yang hilang dapat menutupi kegagalan
lanjutan. Karena itu source aktif belum mendapat full historical PASS.

## Audit lima temuan npm pada image

`npm audit --omit=dev --json` pada OpenClaw di image
`sha256:51c3a402aec72abf0d51cea1c081eb54872f083b31c02c98bbf16c049eec091b`
masih melaporkan **3 high, 2 moderate, 0 critical**. `openclaw@2026.9.9`
menarik `npm@11.20.0` sebagai dependency langsung; semua node terdampak
berada di `node_modules/npm/node_modules/`. `undici` milik OpenClaw sendiri
adalah 8.10.2, terpisah dari `undici@6.28.0` di bawah npm.

| Paket dan jalur dependency | Dampak/prasyarat menurut advisori | Keterjangkauan dari role |
| --- | --- | --- |
| [`brace-expansion@5.0.9`](https://github.com/advisories/GHSA-qhr7-859c-m2p7), npm/minimatch; high | Pola glob bersarang dapat menghabiskan stack/CPU; [advisori terlapor terbaru](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) memerlukan 5.0.12 | Perlu operasi npm dengan pola tak tepercaya; tidak tampak pada endpoint/role yang diuji |
| [`http-cache-semantics@4.2.0`](https://github.com/advisories/GHSA-ch52-4w7c-c8xp), npm/make-fetch-happen; high | Cache HTTP bersama dapat membocorkan respons lintas pengguna via `max-stale`; advisori belum mencantumkan patch | Perlu cache HTTP npm lintas pengguna, bukan cache response editing worker |
| [`undici@6.28.0`](https://github.com/advisories/GHSA-rfgv-xxqx-mfg5), npm/node-gyp; high | Respons handshake WebSocket bermasalah dapat menghentikan proses; fixed 6.28.1 | Perlu WebSocket melalui node-gyp/npm; tidak terlihat pada jalur role |
| [`ip-address@10.5.0`](https://github.com/advisories/GHSA-j6r3-76f7-8jcv), npm/socks; moderate | Perbandingan subnet IPv4/IPv6 dapat melewati allowlist; fixed 10.7.1 | Perlu parsing alamat tak tepercaya melalui proxy SOCKS/npm |
| [`postcss-selector-parser@7.1.4`](https://github.com/advisories/GHSA-rj75-hqrm-r3gf), npm/@npmcli/query; moderate | Selector panjang dapat menghabiskan CPU; fixed 7.1.6 | Perlu npm query dengan selector tak tepercaya |

Reachability ini **inferensi** dari lockfile, tree dependency, dan command
role (`openclaw infer`), bukan bukti bahwa semua fitur OpenClaw tak dapat
memanggil npm. Paket rentan masih ada dalam image. Endpoint editing tidak
menjalankan package install/query; command role dibatasi timeout dan budget,
tetapi itu bukan patch. Menghapus atau override npm/OpenClaw tanpa uji
kompatibilitas 9Router dan proof baru berisiko merusak Stage 5, sehingga
tidak dilakukan. Sebelum deploy, triase versi upstream/reachability,
remediasi dependency yang kompatibel, lalu ulangi audit, build, proof,
canary, dan regression. Temuan high yang belum ditutup tetap blocker.

## Image dan keputusan

Perubahan audit ini hanya pada test dan dokumentasi. Dockerfile, lockfile,
OpenClaw, 9Router, backend role, dan engine Stage 5 tetap. Image ID lama
terverifikasi sama; `python -m backend.runtime_check` pada image kembali
PASS dengan Python 3.14.2. Tidak ada klaim build/canary baru.
File test yang diubah: `tests/test_revision_loop_v01.py`,
`tests/test_benchmark_v01.py`, dan `tests/test_showcase_preview_v01.py`.
Navigasi dokumentasi, laporan recovery sebelumnya, dan audit ini diperbarui.
`ruff check scripts tests backend`, pemeriksaan whitespace Git, katalog
Markdown 88/88, dan tautan lokal dokumen lulus.

**Stage 6.3.5F tetap BLOCKED:** regresi historis memerlukan media dan
receipt asli yang belum tersedia; audit npm menyisakan 3 high dan 2 moderate.
Tidak ada production eligibility, human review, publishing approval, atau
izin deployment. Pulihkan evidence dengan provenance asli, jangan isi path
historis dengan media sintetis. Berhenti sebelum Stage 6.3.6.
