# Hasil instalasi tooling — 12 Oktober 2026

Tools dan skills lokal yang direkomendasikan sudah dipasang. Sesuai instruksi pengguna terbaru, koneksi yang memerlukan data atau login pengguna dilewati. Tidak ada akun layanan proyek yang diklaim terhubung hanya karena skill atau client terpasang.

## Tools dan MCP

| Komponen | Versi/lokasi | Pemeriksaan |
| --- | --- | --- |
| Ruff | 0.17.0, pipx environment terisolasi; command `~/.local/bin/ruff` | Binary berjalan; `ruff check scripts tests` dengan konfigurasi konservatif menghasilkan 0 temuan. |
| GitHub CLI | 2.102.0, `~/.local/bin/gh` | Binary berjalan. Arsip Linux amd64 dari release resmi diverifikasi SHA-256 terhadap checksums release. Login CLI belum tersedia; GitHub connector existing merupakan koneksi berbeda. |
| PostgreSQL client | 16.15, `~/.local/bin/psql`, `pg_dump`, `pg_restore`, `pg_isready` | `psql --version` berhasil. Paket Ubuntu client/libpq diunduh lewat apt dan diekstrak ke direktori pengguna. Tidak memasang server database. Database proyek belum dihubungkan. |
| Playwright CLI | 0.1.22, `~/.local/bin/playwright-cli` | Chromium headless dibuka pada about:blank; halaman uji sementara menerima klik dan berubah dari 0 menjadi 1 sesuai assertion. Session uji ditutup. |
| Chromium headless | Chrome Headless Shell 155.0.8059.12 / Playwright build 1247 | Binary di `~/.cache/ms-playwright/chromium_headless_shell-1247`. Playwright memakai fallback build Ubuntu 24.04; uji browser berhasil pada host ini. |
| Context7 MCP | 4.3.0, server stdio pada `~/.local/share/mandala-dev-tools/node_modules/@upstash/context7-mcp/dist/index.js` | Initialize berhasil, dua alat terdeteksi, dan pemanggilan resolve-library-id menemukan `/python-jsonschema/jsonschema` termasuk versi 4.25.1. Tidak memakai API key/login. |
| REA | Registrasi 6.4.0 existing | Dipertahankan; sudah diuji pada pemasangan sebelumnya. Tidak diuji ulang pada instalasi tooling ini. |

Paket Node developer disimpan di `~/.local/share/mandala-dev-tools`, dengan versi langsung dipin dalam package.json dan dependency lockfile. Semua empat command utama ditemukan pada PATH. FFmpeg sistem dan environment numerik proyek tetap digunakan oleh pipeline existing.

Konfigurasi MCP Codex saat selesai memuat `node_repl`, `rea`, dan `context7`. Context7 diluncurkan dengan `/usr/bin/node` melalui stdio. Registrasi HTTP awal memicu OAuth otomatis; alur itu dihentikan setelah instruksi skip dan diganti server lokal. Callback dari alur lama tidak digunakan kembali.

## Skills

Sebanyak 22 skills personal baru tersedia pada `~/.codex/skills`, di samping skills plugin/system yang sudah ada. Semua 22 lolos quick_validate dari Skill Creator.

- `mandala-video-workflow`: dibuat khusus proyek, dengan routing ke dokumen analysis, speech, Director, renderer, QA, dan adapter.
- Lima skills curated OpenAI: `security-best-practices`, `security-threat-model`, `gh-fix-ci`, `gh-address-comments`, `playwright`.
- Empat belas skills official n8n, termasuk `using-n8n-skills-official`, lifecycle, node configuration, expressions, binary/data, credentials/security, error handling, debugging, loops, subworkflows, Code nodes, agents, data tables, dan MCP extension.
- Dua skills Cloudinary: `cloudinary-docs`, `cloudinary-transformations`.

n8n skills berasal dari commit `180b8415e3b73f78828cfa01e908e67f89f2a139`. Instalasi menggunakan direktori skills personal, sehingga tidak memerlukan plugin hooks atau hook-trust prompt. Marketplace n8n yang sementara ditambahkan untuk discovery sudah dilepas setelah skill dipasang; salinan skills personal tetap tersedia.

## Panduan proyek

- `AGENTS.md` root menjelaskan environment yang benar, perintah pemeriksaan, receipt/evidence invariants, dan pemilihan skills.
- `ruff.toml` memilih pemeriksaan syntax dan name resolution (`E9`, `F821`, `F822`, `F823`) dengan target Python 3.14. Ini bukan klaim seluruh aturan Ruff atau seluruh kualitas kode sudah lulus.
- `.gitignore` mencakup `.ruff_cache/`.
- `~/.playwright/cli.config.json` memilih Chromium dan headless mode agar CLI dapat memakai browser yang baru diunduh. Tidak ada konfigurasi global Playwright sebelumnya yang ditimpa.

Konfigurasi Codex sebelum perubahan dicadangkan di `~/.codex/config.toml.before-mandala-tooling-20261012T152132Z`. Backup REA sebelumnya juga tetap ada.

## Dilewati sesuai instruksi pengguna

- Koneksi MCP instance n8n: perlu URL instance dan autentikasi.
- Koneksi Cloudinary asset-management MCP: perlu login/credentials environment proyek. Skills dokumentasinya sudah terpasang.
- Akses PostgreSQL proyek: client siap, tetapi host/database/credentials belum diberikan.
- Akses Coolify API/SSH: perlu URL/host dan autentikasi. Client SSH existing tersedia.
- Login `gh`: belum dilakukan karena memerlukan akun/login pengguna. Connector GitHub existing dapat digunakan untuk kemampuan yang disediakannya.
- Remote Git, commit baseline, dan workflow CI: ini pekerjaan repository terpisah, bukan instalasi tool; tidak dilakukan dalam tugas ini dan tidak ada repository tujuan yang diasumsikan.

## Pemakaian berikutnya

Skills personal tersedia pada giliran berikutnya. Mulai percakapan baru atau restart Codex untuk memastikan MCP Context7 dimuat pada sesi agent. Tools lokal tersedia melalui PATH sekarang.

Tidak menjalankan inference berbayar, ASR proyek, rendering ulang media proyek, perubahan workflow remote, push, deploy, atau publish. Verifikasi di atas menguji instalasi/konfigurasi, bukan menggantikan suite regresi produk atau review editorial.

## Sumber instalasi

- [Ruff](https://docs.astral.sh/ruff/) dan registry PyPI melalui pipx.
- [GitHub CLI release 2.102.0](https://github.com/cli/cli/releases/tag/v2.102.0).
- [Playwright CLI](https://github.com/microsoft/playwright-cli), paket npm `@playwright/cli` dan browser CDN resmi.
- [Context7](https://github.com/upstash/context7), paket npm `@upstash/context7-mcp`.
- [OpenAI skills](https://github.com/openai/skills/tree/main/skills/.curated), dipasang melalui helper Skill Installer.
- [Official n8n Skills](https://github.com/n8n-io/skills).
- [Cloudinary Skills](https://github.com/cloudinary-devs/skills), ditautkan oleh [dokumentasi Cloudinary](https://cloudinary.com/documentation/cloudinary_llm_mcp).
