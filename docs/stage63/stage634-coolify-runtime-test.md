# Stage 6.3.4 — audit uji runtime Coolify

Audit 15 Oktober 2026. **Status: BLOCKED_SOURCE_DELIVERY.** Docker Engine VPS siap, tetapi source lokal Stage 6.3.4 belum tersedia untuk Coolify. Tidak ada canary yang dibuat, image yang dibangun, atau runtime container yang diuji. Media Worker production, PostgreSQL, workflow n8n, dan volume originals tidak diubah.

## Bukti akses dan kesiapan source

| Pemeriksaan | Hasil teramati |
| --- | --- |
| Checkout lokal | Cabang `main`; `git rev-parse --verify HEAD` gagal (`Needed a single revision`); semua 220 file yang tidak di-ignore masih untracked; `git remote -v` kosong. Karena itu belum ada commit/branch GitHub yang memuat Dockerfile Stage 6.3.4 |
| Coolify | Sesi autentikasi UI berfungsi. GitHub App `web-mandala-auto` tersedia, tetapi pilihan repository yang terlihat hanya `nndoo/Mandala-Auto-Kediri`. Hubungannya dengan checkout ini belum terbukti; tidak dipilih sebagai source canary |
| Jalur Dockerfile tanpa Git | Coolify menawarkan resource `Dockerfile`, tetapi Dockerfile ini memakai `COPY backend`, `scripts`, `src/schemas`, `config`, `openclaw/prompts`, `openclaw/agents`, dan plugin dari **root build context**. Menempelkan isi Dockerfile saja tidak menyediakan source tersebut |
| SSH langsung | ED25519 host key yang dibaca dari terminal Coolify cocok dengan `ssh-keyscan` lokal. Koneksi `BatchMode` sebagai `root` dan `nndoo` ditolak `Permission denied (publickey,password)`; tidak ada kunci/akun baru dibuat |
| Docker host | `docker info` menunjukkan Server 29.7.2, arsitektur x86_64 |
| Kapasitas host | `free -m`: 7623 MiB RAM total, 4720 MiB available, swap 1987 MiB dengan 935 MiB terpakai. `df -h / /var/lib/docker`: filesystem 79 GiB, 25 GiB tersedia, 68% terpakai. Ini satu sampel, bukan peak |
| Worker production | `docker stats --no-stream`: `autoclipper-media-worker-muxr6rvojjjdrjrp24yjimak` 52.28 MiB / 512 MiB, CPU 0.01% pada satu sampel. Container tetap berjalan |

Jalur transfer source via SSH memerlukan perubahan akses server yang tidak dilakukan. Coolify tidak bisa membangun perubahan yang hanya ada pada checkout lokal dari repository GitHub lain. Tidak ada inferensi, render, download source baru, atau publish.

## Rancangan canary yang siap diterapkan setelah source tersedia

Gunakan **resource aplikasi Coolify terpisah** dari Media Worker production. Pilih GitHub App yang diberi akses ke repository Mandala yang benar dan branch yang berisi Stage 6.3.4. Build strategy `Dockerfile`, Dockerfile path `backend/Dockerfile`, build context `/` (root repository), build argument `MANDALA_PROVIDER_ID` sesuai ID provider non-secret yang disetujui. Matikan auto-deploy untuk canary awal dan catat commit SHA yang benar-benar dibangun. Jangan gunakan repo `nndoo/Mandala-Auto-Kediri` hanya karena ia tampak di daftar.

Atur internal port `3002` tanpa domain publik dan tanpa koneksi n8n. Beri named volume canary baru, misalnya `mandala-stage634-canary-data`, di-mount pada `/data` dan `/app/data` pada container yang sama. **Jangan** memilih volume production `/data` atau bind path originals production. Untuk uji `/health` dan pemeriksaan runtime, `PGHOST`, `PGUSER`, `PGPASSWORD`, kredensial OpenClaw/9Router, dan konfigurasi ASR tidak diperlukan; jangan salin secret production ke canary. `AUTOCLIPPER_SOURCE_ROOT=/data/source`, `AUTOCLIPPER_WORKER_PORT=3002`, dan `AUTOCLIPPER_OPENCLAW_PROVIDER_ID` harus cocok dengan build argument. Endpoint `/source/download` dan `/source/file` yang memerlukan reservasi DB tidak boleh dipanggil pada canary tanpa DB uji terpisah.

Profil awal canary: batas RAM 3584 MiB, CPU 1.5, tanpa job AI atau FFmpeg berat. Pada host yang hanya memiliki 4720 MiB available saat snapshot, build OpenClaw dan container canary dapat menekan headroom; amati `MemAvailable` dan hentikan canary bila headroom/layanan lain terdampak. Angka 3584 MiB adalah limit usulan Stage 6.2, bukan RAM terukur. Tidak ada bukti image ini muat atau stabil di dalam limit tersebut.

## Matriks uji sesudah build

1. Simpan build log, image digest/ID, `docker image inspect --format '{{.Size}}'`, dan error apt/pip/npm/TypeScript bila ada. Build harus melewati `RUN python -m backend.runtime_check`, versi Node/OpenClaw, serta filter `drawtext`/`subtitles` dalam Dockerfile.
2. Dari terminal container canary, jalankan `python --version`, `node --version`, `openclaw --version`, `ffmpeg -version`, `ffprobe -version`, serta `python -m backend.runtime_check --check-storage`. Jalankan `--require-service-env` hanya bila DB uji sengaja dikonfigurasi. Cocokkan manifest provider 9Router dan `dist/index.js`; registrasi plugin dan koneksi provider tetap belum terbukti tanpa private config, dan tidak perlu inference berbayar.
3. Periksa `stat` dan uji tulis file sementara hanya pada volume canary di `/data` dan alias `/app/data`; pastikan keduanya mereferensikan storage canary yang sama dan tidak menunjuk volume production.
4. Panggil `GET http://127.0.0.1:3002/health` dari dalam container. Untuk smoke API tanpa database, uji respons validasi `POST /source/discover` dengan payload invalid dan `POST /source/download`/`/source/file` dengan payload invalid; jangan memicu TikTok atau DB production. Parity penuh download/file memerlukan DB/media fixture terisolasi.
5. Ukur `docker stats --no-stream`, `memory.peak`, OOM events, CPU dan `free -m` host saat idle dan selama smoke. Catat limit dan peak; jangan menyamakan statistik Worker production dengan canary.

## Langkah yang diperlukan dari pemilik repository

1. Pilih atau buat **repository GitHub private yang benar** untuk checkout `/home/nndoo/Projects/mandala-autoclipper-ai`, lalu atur `origin`. Jangan memakai repository web `nndoo/Mandala-Auto-Kediri` tanpa memastikan ia memang ditujukan untuk engine ini.
2. Tinjau file yang akan masuk commit pertama, termasuk 220 file untracked. `.gitignore` dan `.dockerignore` mengecualikan `data/`, `archive/`, media, virtualenv, caches, dan private `.env`; dokumentasi evidence yang bernilai tetap perlu dipilih dengan sengaja. Lakukan pemeriksaan final secret/PII sebelum staging. Pemindaian sederhana menemukan string menyerupai token di tiga file test sebagai kemungkinan fixture, tetapi belum merupakan audit secret yang lengkap.
3. Lakukan `git add`, commit, dan push **sendiri** sesuai instruksi pengguna. Pastikan branch/commit memuat `backend/Dockerfile`, `backend/requirements.lock.txt`, `backend/openclaw-runtime/package-lock.json`, plugin, scripts, schema, prompt, dan `.dockerignore`.
4. Beri GitHub App Coolify yang dipilih akses baca ke repository itu. Setelah commit terlihat di Coolify, canary dapat dibuat dengan pengaturan di atas; lakukan build dan uji, lalu perbaiki source lokal dan ulangi dari commit baru bila build gagal.

Tidak ada ukuran image, RAM/CPU canary, healthcheck canary, atau kompatibilitas runtime image yang dapat dilaporkan sebagai hasil. Semua itu menunggu source tersedia untuk build. Kondisi VPS dan autentikasi GitHub adalah bukti kesiapan platform saja, bukan PASS deployment atau pipeline Stage 5.
