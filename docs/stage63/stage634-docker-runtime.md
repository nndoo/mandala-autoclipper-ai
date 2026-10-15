# Stage 6.3.4 — persiapan Docker Runtime

> **Revisi 15 Oktober 2026:** keputusan deployment/cutover dan jumlah file di
> laporan ini adalah snapshot historis. Rancangan aktif memakai Media Worker
> permanen + service editing baru dengan originals RO dan output terpisah.
> Lihat [keputusan final dua worker](stage634-two-worker-architecture.md).

Tanggal audit: 15 Oktober 2026. Status: **source dan konfigurasi image disiapkan; image belum terbangun dan belum diuji di container**. Docker CLI lokal tersedia, tetapi Docker daemon/socket `/var/run/docker.sock` tidak ada. Tidak ada perubahan VPS, n8n, PostgreSQL, original media, commit, atau push.

## Hasil implementasi lokal

| Komponen | Lokasi dan keputusan |
| --- | --- |
| Image tunggal | [`backend/Dockerfile`](../../backend/Dockerfile): Python 3.14.2 dan Node 24.21.0 dari manifest linux/amd64 yang dipin berdasarkan digest; FFmpeg/FFprobe, `curl`, `prlimit`, font DejaVu; multi-stage build untuk adapter TypeScript |
| Python | [`backend/requirements.in`](../../backend/requirements.in) dan [`requirements.lock.txt`](../../backend/requirements.lock.txt): NumPy 2.5.4, SciPy 1.18.1, jsonschema 4.25.1, yt-dlp 2026.8.19, psycopg 3.3.6 dan transitif; install wheel-only dengan hash |
| OpenClaw | [`backend/openclaw-runtime/package.json`](../../backend/openclaw-runtime/package.json), `package-lock.json`, wrapper `bin/openclaw`: OpenClaw 2026.9.9 pada lokasi home dan Node terisolasi yang diharapkan runner Stage 5 |
| 9Router | Plugin `openclaw/plugins/mandala-9router-video` dibangun dari `npm ci` dan `tsc`; binding provider non-secret dibuat dari build argument melalui [`configure_plugin.py`](../../openclaw/plugins/mandala-9router-video/tools/configure_plugin.py). Mode lama yang membaca konfigurasi lokal tetap tersedia. `dist`, manifest, dan provider ID hasil build disalin ke runtime image |
| Aset Stage 5 | `scripts/`, `src/schemas/`, `config/`, `openclaw/prompts/`, `openclaw/agents/`, dan plugin source dimasukkan ke `/app`; source root Stage 5 tetap `/app` |
| Worker | `python -m backend.media_worker.app` pada port 3002. Kode empat endpoint `/health`, `/source/discover`, `/source/download`, `/source/file` tidak diubah |
| Validasi image | [`backend/runtime_check.py`](../../backend/runtime_check.py) memeriksa Python, versi paket, executable, schema/prompt, plugin dist/manifest, wrapper, font, dan kecocokan provider ID bila variabel runtime tersedia; opsi tambahan untuk env PostgreSQL dan tulis storage tanpa mencetak credential |
| Compose | [`backend/compose.yaml`](../../backend/compose.yaml): satu service dan satu named volume yang di-mount dua kali, `/data` untuk Worker dan `/app/data` untuk root Stage 5; tanpa salinan MP4. Profil canary 3584 MiB dan 1.5 CPU; ini konfigurasi lokal usulan, bukan limit VPS aktif |
| Build context | [`.dockerignore`](../../.dockerignore) mengeluarkan media, evidence, tests, docs, cache, private env, node_modules dan dist lokal. Aset plugin dist dibuat ulang di image |

Image ini menyediakan runtime dan source Stage 5; belum menjalankan AI role endpoint atau orkestrasi Stage 6.3.5. Tidak ada model/ASR lokal yang diklaim terpasang. Remote speech dan provider OpenClaw tetap bergantung pada konfigurasi private saat runtime.

## Kontrak operasi dan konfigurasi

`/data/source/originals` tetap lokasi original Worker. Mount alias `/app/data` menjaga aturan path `ROOT/data` dari Stage 5; sebelum cutover perlu membuktikan keduanya menunjuk inode/bytes yang sama pada volume target. File asli dan evidence historis tidak menjadi bagian image. Output baru harus memakai direktori eksklusif pada volume tersebut. Source Worker tetap berjalan sebagai root seperti image existing agar hak akses volume tidak berubah diam-diam; transisi UID non-root memerlukan uji ownership/migration terpisah.

Konfigurasi non-secret dan nama variabel ada di [`backend/.env.example`](../../backend/.env.example). `PGHOST`, `PGUSER`, dan `PGPASSWORD` wajib bagi operasi download/file. `AUTOCLIPPER_SOURCE_ROOT` harus berada di bawah `/data`; `PGPORT` serta `AUTOCLIPPER_WORKER_PORT` harus port valid. `python -m backend.runtime_check --require-service-env --check-storage` disediakan untuk memeriksa persyaratan itu pada container dengan volume dan env terpasang. Validasi default pada build sengaja tidak memerlukan secret atau volume. Build argument `MANDALA_PROVIDER_ID` dan variabel runtime `AUTOCLIPPER_OPENCLAW_PROVIDER_ID` harus sama; ini ID provider, bukan API key.

Konfigurasi private `~/.openclaw/openclaw.json` **tidak** dimasukkan ke Git/image. Pada deployment berikutnya Coolify harus memasangnya sebagai secret file pada `/root/.openclaw/openclaw.json`, dengan path plugin diarahkan ke `/app/openclaw/plugins/mandala-9router-video`, workspace agent ke `/app/openclaw/agents/`, dan provider ID cocok dengan manifest image. API key, base URL private, credential PostgreSQL, serta konfigurasi ASR harus disediakan melalui mekanisme private Coolify. `openclaw --version` dan file plugin saja tidak membuktikan registrasi plugin, transport 9Router, atau inference. Uji konfigurasi dan izin file mount masih merupakan gate berikutnya.

Healthcheck Compose hanya memanggil `/health`, sehingga membuktikan HTTP Worker hidup, bukan kesiapan DB/OpenClaw/volume atau editorial pipeline. Stage 6.3.5 perlu readiness/admission yang terpisah sebelum node n8n mengirim job AI. Pembatasan satu slot unduhan pada Worker existing tidak otomatis membatasi FFmpeg/AI role yang belum punya endpoint; concurrency bersama masih harus diimplementasikan.

## Verifikasi yang dilakukan

| Pemeriksaan | Hasil |
| --- | --- |
| `docker compose -f backend/compose.yaml config -q` | Lulus |
| `ruff check scripts tests backend openclaw/plugins/mandala-9router-video/tools` | Lulus |
| `.venv-av/bin/python -m compileall -q backend` | Lulus |
| Binding provider build: ID valid menghasilkan manifest/TS yang cocok; ID traversal ditolak | Lulus pada salinan sementara, tanpa private config |
| Plugin `tsc --noEmit`, `npm run build`, `npm test` dengan bundled Node 24.21.0 | Lulus; 23 test plugin |
| `test_media_worker_stage631.py` | 7 test lulus; parity endpoint offline dengan mock DB/eksekusi eksternal |
| `test_intake_adapter_stage632.py` | 10 test lulus |
| `test_automatic_editing_v01.py` | 19 test lulus |
| `test_stage54_planning_integration.py` | 32 test lulus |
| `docker compose -f backend/compose.yaml build` | **Terhalang** sebelum build: tidak dapat menghubungi Docker API di `/var/run/docker.sock` (`no such file or directory`) |

Test Python dijalankan pada `.venv-av` host, bukan di image. Karena image tidak terbangun, `RUN` check Dockerfile, `npm ci` OpenClaw dalam base image, endpoint smoke test container, akses volume, FFmpeg/font di image, dan kompatibilitas OpenClaw runtime **belum terverifikasi**. Ukuran image: **tidak terukur**. RAM idle/peak container: **tidak terukur**. Batas 3584 MiB/1.5 CPU dalam Compose adalah profil canary dari [audit kapasitas Stage 6.2](../stage62/resource-capacity.md), bukan hasil benchmark atau bukti aman di VPS 7.4 GB. Service VPS existing tetap pada 512 MiB.

## Batas reproducibility dan langkah verifikasi berikutnya

Base image linux/amd64 dipin ke digest, Python package ke versi+hash, npm dependency ke lockfile, dan plugin dibangun dari source. Paket Debian (`ffmpeg`, font, util-linux, dll.) masih mengikuti indeks apt Bookworm pada waktu build; karena tidak memakai snapshot apt bertanggal, hasil belum dijamin bit-identical antar waktu. Build juga memerlukan registry/network. Jika reproducibility forensik dibutuhkan sebelum deployment, pin snapshot apt serta rekam image digest/SBOM pada build CI.

Saat Docker daemon tersedia, jalankan build lokal, `docker compose up` dengan credential dan volume uji private, uji empat endpoint tanpa menyentuh originals produksi, lalu catat `docker image inspect --format '{{.Size}}'`, `docker stats`, `memory.peak`, OOM events, dan kompatibilitas OpenClaw/plugin/FFmpeg dalam container. Jangan cutover Worker 512 MiB sampai smoke test, parity download/file, uji path/permission, dan resource canary lolos. Jangan menganggap lulusnya test struktur atau decode sebagai approval editorial, production, atau publishing.
