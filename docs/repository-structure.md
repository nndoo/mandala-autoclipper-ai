# Struktur repository setelah Stage 6.1

This page preserves the Stage 6.1 and 6.3.4 layout record below. For the
current local Stage 6.3.5 recovery, see the [agent guide](AGENT_GUIDE.md),
[Stage 6.3 index](stage63/README.md), and source in `backend/editing_api.py`,
`backend/editing_store.py`, `backend/editing_dispatch.py`, and `backend/roles/`.
The Stage 6.3.5 [Tahap D checkpoint](stage63/stage635-stage-d-checkpoint-2026-10-15.md)
is incomplete; older statements below such as "roles placeholder" are historical.

Revisi aktif Stage 6.3.4: [dua worker](stage63/stage634-two-worker-architecture.md).
`backend/editing_worker.py` adalah entrypoint service editing baru;
`backend/compose.yaml` hanya mengelola service baru, dan `compose.canary.yaml`
memakai volume fixture terpisah. Source API existing dipertahankan tanpa perubahan
dan tidak dimasukkan ke image editing. Layout sebelumnya di bawah adalah riwayat.

Tanggal: 14 Oktober 2026. Struktur ini memisahkan kebutuhan runtime, development,
dan penyimpanan evidence tanpa mengubah path kontrak Stage 5.

| Lokasi | Peran | Perlakuan deployment |
| --- | --- | --- |
| `scripts/` | CLI Python, compiler, validators, orchestration, QA; juga utilitas replay/benchmark historis | Pertahankan seluruh modul untuk image pertama; dependency antar-script belum menjadi package terpisah |
| `src/schemas/` | Kontrak JSON aktif dan kontrak historis | Sertakan; jangan menghapus schema berdasarkan nomor versi |
| `openclaw/plugins/mandala-9router-video/src/` | Adapter transport TypeScript | Build dari lockfile; binding provider harus cocok dengan target |
| `openclaw/plugins/mandala-9router-video/dist/` | Output build lokal | Rebuild dalam image; bukan source canonical |
| `openclaw/plugins/mandala-9router-video/tests/`, `tests/` | Regression, fixtures, tiga live `poc_*` | Development/CI; POC tidak dijalankan oleh offline discovery |
| `openclaw/agents/`, `openclaw/prompts/` | Instruksi Analyst, Director, Reviewer | Sertakan file aktif; snapshot `.before-*` adalah bukti historis |
| `config/` | Konfigurasi ASR non-secret, masih spesifik endpoint host | Perlu provisioning target; credentials dari private environment |
| `requirements-av*.txt`, `.python-version` | Dependency dan interpreter baseline | Rebuild environment; lockfile bukan berisi hash wheel |
| `data/test-videos/` | Media asli dan fixtures dengan identitas hash | Backup terpisah; dibutuhkan beberapa regression tests; bukan image layer |
| `data/analyses/`, `data/render-tests/`, `data/qa/`, `data/revisions/`, `data/benchmarks/`, `data/backups/` | Evidence, receipts, plans, raw responses, render, permits dan ledger | Retain path asli; volume/backup terpisah; status historis bukan admission baru |
| `docs/` | Panduan workflow dan laporan historis | Development/reference; Stage 6.1 dalam `docs/stage61/` |
| `docs/migration-local/` | Log/baseline migrasi lokal | Retain path asli karena laporan merujuknya; ignored Git |
| `archive/stage61/` | Arsip lokal berindeks hash dan backup environment lama | Bukan runtime; ignored Git dan Docker; backup terpisah |
| `.venv-av/`, adapter `node_modules/` | Dependency aktif lokal | Pertahankan untuk development; recreate di target |

Folder kosong `src/api`, `src/services`, `src/tools` tidak merupakan implementasi
layanan. Stage 6.1 menghapus placeholder kosong tersebut; API/Media Worker masih
pekerjaan Stage 6 berikutnya.

## Aturan arsip

`docs/stage61/cleanup-manifest.json` mencatat setiap pemindahan, salinan arsip,
dan penghapusan cache. Arsip mempertahankan bytes asli. Snapshot atau artefak
yang terikat baseline/path historis tetap di lokasi semula; salinan arsip adalah
indeks preservasi, bukan evidence baru dan bukan pengganti receipt.

Backup environment `.venv-av.before-migration-20261014` dipindahkan ke
`archive/stage61/environments/.venv-av.before-migration-20261014`.
Path lama di laporan migrasi tetap merupakan catatan historis. Backup ini tidak
boleh diaktifkan; symlink/interpreter dari device lama bukan environment portable.

Source aktif, POC yang terikat baseline, tests, schema, config dan media asli tidak
direlokasi. Cache yang dapat diregenerasi dibersihkan; lock kosong dan file evidence
kosong tetap dipertahankan. File berukuran nol sendiri bukan alasan penghapusan.

`.dockerignore` adalah kebijakan konteks build awal, bukan deployment recipe.
Tidak ada Dockerfile, endpoint API, workflow n8n, atau konfigurasi Coolify yang
diimplementasikan di Stage 6.1. Build mendatang harus membangun adapter dan
memasang runtime/font/tool OS yang diperlukan.

## Addendum Stage 6.3.4 — source untuk Git dan Coolify

`backend/media_worker/` sekarang memuat source API existing dan Intake Adapter;
`backend/roles/` masih placeholder pengembangan. `backend/Dockerfile`,
`backend/compose.yaml`, `backend/runtime_check.py`, lock Python backend dan
`backend/openclaw-runtime/` adalah source build/runtime. Snapshot
`backend/vps_snapshot/worker.py` tetap masuk Git sebagai evidence Stage 6.3.1,
tetapi dikeluarkan dari image. Laporan lengkap ada di
[Git readiness](stage63/git-readiness.md), dengan
[daftar calon file Git](stage63/git-safe-files.txt) dan
[daftar build context](stage63/coolify-build-context.txt).

Snapshot `.before-*` kini di-ignore Git dan Docker; file asli tetap di tempatnya,
dan 10 salinan arsip Stage 6.1 telah diverifikasi byte-identik. Tests aktif, tiga
source POC, laporan pengujian `.txt`, manifest cleanup dan baseline preservasi
tetap masuk Git. Nama file yang memuat `test` tidak menjadi alasan mengeluarkan
source: `scripts/render_test_fixtures_v01.py` dipakai proof/capability Stage 5 dan
tetap wajib masuk image. Media/hasil eksekusi di `data/` serta arsip di `archive/`
tetap memerlukan backup terpisah.

`.dockerignore` sekarang memakai allowlist dengan default deny, lalu pengecualian
credential/cache/media/backup. Binding provider lokal dan manifest plugin juga
dikeluarkan dari context; Docker builder membuatnya kembali pada struktur
`/app/openclaw/plugins/mandala-9router-video`. Tidak ada perubahan receipt,
original media, atau status historis akibat persiapan source ini.
