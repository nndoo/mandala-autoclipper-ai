# Migrasi lokal selesai — 14 Oktober 2026

Checkout: `/home/nndoo/Projects/mandala-autoclipper-ai`. Pipeline offline sudah
berjalan pada device ini. Konfigurasi inference lokal tersedia dan router bisa
diakses; inference berbayar, review editorial, serta deployment tidak dijalankan.

## Environment yang dipasang

| Komponen | Hasil |
| --- | --- |
| Python | CPython 3.14.2 melalui uv, virtualenv baru `.venv-av` tanpa system-site-packages |
| Dependency Python | NumPy 2.5.4, SciPy 1.18.1, jsonschema 4.25.1; dependency lengkap dalam `requirements-av.lock.txt` |
| FFmpeg/FFprobe | Paket Ubuntu 6.1.1-3ubuntu5; libx264, AAC, seluruh filter renderer, dan font DejaVuSans tersedia |
| Ruff | 0.17.0 melalui uv tool, command di `~/.local/bin` |
| Adapter | Dependency dipasang ulang dengan `npm ci`; dist dibangun ulang |
| OpenClaw | 2026.9.9 (bcfc888), dipasang di `~/.local/share/mandala-openclaw-runtime` |
| Bundled Node | 24.21.0, arsip Linux x64 diverifikasi terhadap SHASUMS256 resmi Node |
| Panduan agent | Skill personal `~/.codex/skills/mandala-video-workflow/SKILL.md` direkonstruksi dari dokumen proyek; validasi Skill Creator lulus |

Virtualenv lama dicadangkan sebagai `.venv-av.before-migration-20261014` dan
di-ignore Git. Jangan aktifkan backup ini: symlink interpreter masih mengarah ke
device lama. Tool uv dan Ruff tersedia melalui PATH pengguna yang sudah ada.

## Penyesuaian source

- `requirements-av.txt` kini menyertakan jsonschema secara eksplisit; lockfile
  mencatat dependency transitive. `.python-version` memilih baseline 3.14.2.
- Script audit timeline dan tiga live POC menentukan root dari lokasi file,
  menggantikan asumsi `~/projects/mandala-autoclipper-ai`.
- `renderer_core_v01.py` menjalankan proses yang dibatasi prlimit dengan
  `MALLOC_ARENA_MAX=2`. Reservasi arena glibc pada host ini sebelumnya menyebabkan
  libx264 gagal membuka encoder. Memory/file/CPU limits tetap aktif; tes subprocess
  nyata memeriksa batas tersebut bersama pengaturan allocator.
- Ignore Git mencakup bytecode, backup virtualenv, dan log migrasi lokal.
- README root dan adapter menjelaskan setup/checks yang dapat diulang.

## Konfigurasi OpenClaw

Wrapper yang dipakai runner:
`~/.local/share/mandala-openclaw-runtime/bin/openclaw`. Wrapper menggunakan
bundled Node melalui path absolut; Node lain di PATH tidak menggantikannya.

`~/.openclaw/openclaw.json` mendaftarkan workspace Analyst, Director, dan Reviewer
dari checkout ini, provider/model alias existing, serta plugin Mandala melalui
path lokal. Config memakai roster dengan ownership explicit. Tidak ada daemon,
heartbeat, atau channel messaging yang diaktifkan.

Provider menggunakan endpoint yang sama dengan config remote ASR proyek.
Kredensial proyek existing diterapkan melalui private `~/.openclaw/.env`, dengan
referensi environment dalam config. `.env.asr`, `.openclaw/.env`, dan
`.openclaw/openclaw.json` memiliki mode 0600. Credential tidak ditulis ke laporan,
source, argumen command, atau Git. Saat mengganti key, perbarui kedua file privat
atau gunakan environment sesuai mekanisme masing-masing runner.

Konfigurasi ini merekonstruksi kebutuhan runner dari source dan dokumen proyek;
ini bukan salinan seluruh konfigurasi OpenClaw device lama. Context window dan
maxTokens dalam config lokal adalah konfigurasi client, bukan kemampuan backend
yang diverifikasi. Model alias tidak membuktikan identitas weights server.

Untuk memeriksa tanpa inference:

```sh
~/.local/share/mandala-openclaw-runtime/bin/openclaw --version
~/.local/share/mandala-openclaw-runtime/bin/openclaw config validate --json
~/.local/share/mandala-openclaw-runtime/bin/openclaw infer model --agent mandala-video-director list --json
~/.local/share/mandala-openclaw-runtime/bin/openclaw infer video providers --agent mandala-video-analyst --json
```

Setelah folder dipindah lagi, perbarui workspace dan plugin load paths di config
privat. Untuk provider yang berbeda, jalankan generator binding adapter lalu build.
Paket OpenClaw harus tetap versi baseline ini sampai transport/semantic validation
diulang. Runtime npm memiliki package manifest dan lockfile sendiri di direktori
instalasi; source plugin tetap di checkout.

## Verifikasi device ini

- Regresi penuh: **1.276 tes Python lulus**, 86,502 detik, tanpa failure/error.
- Setelah penambahan pemeriksaan allocator: **94 tes renderer lulus**, termasuk
  subprocess nyata yang memeriksa memory/file/CPU limits tetap terpasang.
- **23 tes adapter lulus**, build dan `tsc --noEmit` berhasil.
- Ruff: **0 temuan** untuk aturan konservatif proyek.
- Universal analysis self-test: lulus; timestamp invalid ditolak.
- Tiga MP4 sumber: decode penuh exit 0. Decode tidak membuktikan kualitas editorial.
- Render sintetis baru: `data/render-tests/stage55/migration-basic-final-20261014`.
  Status `TEST_ONLY_COMPLETED`; proof menggunakan source dan environment saat ini.
  Registry `data/render-tests/stage55/migration-capabilities-20261014.json` lolos
  replay untuk trim, concat, dan reorder. Ketersediaan filter lain tidak diklaim
  sebagai proof capability oleh registry yang hanya memakai fixture basic ini.
- Bundle remote speech lama: offline integrity checked, generation complete;
  evidence tetap **ineligible**, independent verification false. Status timing/
  review tidak dipromosikan oleh migrasi.
- Router `/v1/models`: HTTP 200 dengan credential proyek, 104 model, alias
  `openclaw` tersedia. Ini permintaan inventory, bukan inference/transcription.
- Native OpenClaw model auth status: exit 0; config validate berhasil, plugin
  video tersedia melalui inventory CLI. Readiness auth bukan bukti model response.
- Hash seluruh **1.232 file data/evidence historis** yang dicatat sebelum migrasi
  tetap identik. Tidak ada file baseline yang hilang. Artefak render baru disimpan
  pada bundle baru; path lama di dalam laporan/receipt historis tetap dipertahankan.

Log dan manifest hash berada di `docs/migration-local/` yang di-ignore Git.
Audit awal di `docs/migration-audit-2026-10-14.md` tetap menjadi snapshot sebelum
perbaikan; hasil terkini adalah laporan ini.

## Batas migrasi yang masih eksternal

- Folder datang tanpa commit/history Git dan tanpa remote. History maupun URL
  repository tujuan tidak bisa direkonstruksi dari source. Source tetap berupa
  perubahan lokal; tidak dibuat identitas author atau remote yang diasumsikan.
- Kelengkapan transfer terhadap device lama belum dapat dibuktikan tanpa manifest
  pembanding. Hash di sini membuktikan keutuhan sejak audit device ini.
- n8n workflows, database PostgreSQL/data dump, akun Cloudinary, dan Coolify/GitHub
  deployment belum tersedia atau diverifikasi. Tidak membuat layanan kosong lalu
  menganggap data atau integrasi lama sudah pindah.
- Skill personal lain dan konfigurasi MCP dari device lama bukan dependency
  pipeline offline dan belum direstorasi dari backup aslinya.
- Inference video/Director/Reviewer, ASR upload, human review, dan production/
  publishing authorization tetap outcome terpisah. Migrasi ini tidak menerbitkan
  media atau mengubah gate persetujuan proyek.
