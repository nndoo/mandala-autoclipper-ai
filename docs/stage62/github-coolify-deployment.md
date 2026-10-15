# Rancangan GitHub → Coolify untuk Stage 6.3

> **Revisi 15 Oktober 2026:** keputusan deployment/cutover dan jumlah file di
> laporan ini adalah snapshot historis. Rancangan aktif memakai Media Worker
> permanen + service editing baru dengan originals RO dan output terpisah.
> Lihat [keputusan final dua worker](../stage63/stage634-two-worker-architecture.md).

Audit lokal 14 Oktober 2026: checkout Mandala berada pada branch `main` **tanpa
HEAD/commit dan tanpa remote Git** (`git rev-parse --verify HEAD` gagal, `git
remote -v` kosong). Semua source/docs/config masih untracked. Tidak ada Dockerfile
atau Compose file di checkout. `.dockerignore` dan `.gitignore` sudah ada; file
`.env.asr`, `data/`, `archive/`, venv, node_modules dan dist ter-ignore. Tidak ada
aplikasi Coolify Mandala yang terbukti tersambung ke GitHub saat audit ini; Media
Worker existing adalah Compose dengan Dockerfile inline yang diamati pada Stage 6.2.
Karena itu **git add/commit/push belum dapat memicu deployment Mandala**.

Pola pembanding yang berjalan di Coolify adalah Instagram: GitHub app `autopost-ig`
terhubung ke `nndoo/social-media-automator` branch `main`; strategy Dockerfile,
base `/openclaw`, Dockerfile `/Dockerfile`, dan opsi auto deploy `Deploy on push
(webhooks)`. Pola webhook itu dapat direuse, tetapi status Running Instagram tidak
menjamin rollback, healthcheck atau kualitas engine Mandala.

## Bootstrap satu kali pada Stage 6.3 atau sesudahnya

1. Tentukan repository GitHub Mandala yang benar, lakukan audit isi yang akan
   distage (termasuk docs/logs) untuk secret/PII dan ukuran, buat commit awal,
   lalu set remote `origin` dan push branch `main`. Ini **belum dilakukan**.
2. Tambahkan Dockerfile di root checkout dengan build context root: image berisi
   runtime Python yang dipin dan diuji, FFmpeg/ffprobe/fonts, Node/OpenClaw runtime
   terisolasi, adapter TS yang dibangun dari lockfile, `scripts/`, `src/schemas`,
   `config/` non-secret dan `openclaw/prompts`. Container menjalankan API Worker
   port 3002 serta satu queue loop. Versikan source `/tmp/worker.py` existing ke
   repo sebelum mengganti image; pertahankan kontrak `/source/*`. Runtime OpenClaw
   lokal saat ini berada di home user, di luar Git: image harus memasang versi
   dan checksum yang ditetapkan secara reproducible, bukan mengandalkan host PATH.
3. Jadikan `.dockerignore` sebagai allowlist efektif build context: env/secrets,
   data/media/archive, tests, docs, venv, node_modules dan dist lokal tetap di luar
   image. Pastikan seluruh file yang ikut code/proof hash benar-benar dicopy dari
   Git commit build, bukan diambil dari volume atau host secara diam-diam. `data/`
   di-ignore Git dan memuat fixture/evidence lokal; uji CI dari fresh clone harus
   memakai fixture sintetis/versioned yang sah atau tahap test yang tidak
   membutuhkan historical media, lalu uji parity penuh pada lingkungan berizin.
4. Simpan credentials provider/OpenClaw/9Router/ASR/PostgreSQL dan service auth
   pada mekanisme Environment Variables/secret Coolify, bukan Git, Dockerfile
   `ARG`, n8n payload atau log. Lakukan pemeriksaan **nama/presence** variable
   tanpa menampilkan nilainya. Jangan mengandalkan `.env.asr` lokal di image.
5. Reuse named volume `muxr6rvojjjdrjrp24yjimak_autoclipper-data` dan network
   Coolify yang menghubungkan n8n, Worker dan PostgreSQL. Rencanakan migrasi mount
   `/data` ke namespace source engine secara eksplisit; uji bytes/hash/device,
   ownership, restore dan rollback tanpa mengganti original lama.
6. Di Coolify, sambungkan aplikasi Mandala ke repo/branch GitHub, build strategy
   Dockerfile/context yang sesuai, network/port 3002, persistent volume, env
   secrets, resource limit baru dan healthcheck `/health/ready`. Aktifkan webhook
   deploy-on-push setelah image+DB schema+compatibility smoke lolos. Pastikan GitHub
   app punya akses repo dan satu push uji menghasilkan deployment revision/commit
   SHA yang sama; lalu uji rollback ke image lama.

Setelah bootstrap dan gates di atas, alur rutin menjadi `git add` → `git commit`
→ `git push origin main` → GitHub webhook → Coolify build image dari commit SHA
→ health/readiness → canary/rollback bila gagal. CI/offline regression dan build
harus lulus sebelum push yang mengubah production. n8n workflow dan migrasi schema
tidak otomatis terdeploi oleh push source kecuali keduanya juga disimpan dan
diatur sebagai artefak versioned dengan prosedur migrasi terpisah. Coolify harus
memakai image immutable per commit, bukan source di volume lama.

Tidak ada GitHub connection, image build, secret setup, VPS change, migration,
workflow edit, commit atau push yang dilakukan pada Stage 6.2.
