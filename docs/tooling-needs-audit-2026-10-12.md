# Audit kebutuhan tools Mandala Auto — 12 Oktober 2026

Audit ini memeriksa kode, dokumen proyek, executable lokal, paket Python pada environment yang benar, katalog skill resmi, katalog plugin, dan dokumentasi penyedia. Ini bukan audit keamanan atau hasil menjalankan seluruh test suite. Rekomendasi belum berarti paket sudah dipasang atau layanan sudah terhubung.

**Kondisi proyek yang teramati**

- Pipeline utama berupa script Python, JSON Schema, FFmpeg/FFprobe, dan plugin TypeScript OpenClaw untuk 9Router. README juga menyebut n8n, PostgreSQL, Cloudinary, dan deployment melalui Coolify; penyebutan tersebut belum membuktikan integrasi remote aktif.
- Dokumen remediasi Stage 5.6 melaporkan Reviewer live sudah berjalan, tetapi hasil editorial masih REVISE. Penambahan tools tidak otomatis memperbaiki musik, ending, ghosting, atau membuktikan kemampuan audio backend.
- Jalur ASR utama sudah remote. Dokumen ASR mencatat respons text-only dan timing unavailable pada sampel yang diuji. Mengaktifkan runtime Whisper lokal bukan kebutuhan saat ini.
- GitHub connector tersedia dan autentikasinya berhasil diperiksa. Checkout lokal belum memiliki commit atau remote. Tidak ditemukan workflow GitHub Actions maupun Dockerfile di root.
- Belum ada AGENTS.md di root proyek. AGENTS.md yang ditemukan berada pada workspace agent OpenClaw; dokumen itu memiliki peran berbeda dari panduan kerja Codex di root.

**Yang sudah tersedia**

| Kemampuan | Bukti/status | Implikasi |
| --- | --- | --- |
| Terminal, edit file, Git, pencarian kode | Tersedia | Pekerjaan repository biasa tidak membutuhkan MCP filesystem atau Git tambahan. |
| Node/npm, TypeScript, Node tests | Node/npm pada PATH; node_modules plugin tersedia; scripts build/test tercatat di package.json | Gunakan compiler dan test runner existing. |
| Python dan unittest | Python tersedia; test memakai unittest | pytest tidak diperlukan untuk menjalankan suite existing. |
| jsonschema, NumPy, SciPy | .venv-av memuat 4.25.1, 2.5.4, 1.18.1 | Jalankan pekerjaan numerik melalui .venv-av, bukan Python system yang tidak memiliki NumPy/SciPy. |
| FFmpeg/FFprobe | FFmpeg 6.1.1; loudnorm, ebur128, silencedetect, blackdetect, freezedetect, PSNR, SSIM tersedia | QA media existing dapat memakai alat yang sudah ada. libvmaf tidak terdeteksi pada build ini, tetapi bukan prasyarat pipeline sekarang. |
| GitHub | Plugin terpasang; autentikasi connector berhasil | Tidak perlu memasang GitHub MCP kedua. |
| REA | Registrasi rea dan skill reverse-engineer-anything ada | Berguna untuk artifact aplikasi/binary; bukan alat utama untuk membaca source proyek ini. Uji MCP REA sebelumnya berhasil, tidak diulang pada audit ini. |
| Browser, frontend, desain, PostgreSQL guidance | Kemampuan browser dan skill frontend/design/Postgres tersedia dalam sesi | Tambahan baru hanya jika ada kebutuhan yang belum tercakup. Ketersediaan kontrol browser belum membuktikan ada sesi browser aktif. |

**Paket awal yang direkomendasikan**

| Item | Jenis | Alasan khusus proyek | Status dan persiapan |
| --- | --- | --- | --- |
| Panduan root AGENTS.md dan skill mandala-video-workflow | Panduan proyek + skill custom | Menyatukan environment Python/Node yang benar, perintah test, urutan schema/provenance/render/QA, dan cara membaca receipt tanpa menyamakan technical pass dengan kualitas editorial. | Perlu dibuat berdasarkan workflow existing. Nama skill adalah usulan, bukan paket marketplace. |
| Ruff | Tool pengembangan Python | Pemeriksaan cepat untuk nama tidak terdefinisi, import bermasalah, dan kesalahan Python dasar pada banyak script. | Belum terpasang. Pasang secara terisolasi sebagai tool development; mulai pemeriksaan tanpa auto-fix atau format seluruh kode. |
| security-best-practices | Skill resmi OpenAI | Panduan review Python/TypeScript ketika mengerjakan input media, subprocess, batas path, credentials, dan API. | Ada di katalog curated; belum dipasang. Gunakan untuk pekerjaan keamanan yang relevan, bukan menjalankan audit otomatis pada setiap tugas. |
| Context7 | Plugin atau MCP dokumentasi | Mengambil dokumentasi library menurut versi untuk membantu pekerjaan adapter dan integrasi. Coverage OpenClaw/9Router harus diperiksa; source SDK dan docs resmi tetap diperlukan bila library tidak diindeks. | Ditemukan pada katalog, belum terpasang/terhubung. Pilih satu jalur plugin atau MCP. Usulan pemasangan plugin sudah disediakan; pengguna perlu menyelesaikan pemasangan/koneksi. |

**Integrasi berikutnya menurut pekerjaan yang dilakukan**

| Item | Manfaat | Yang perlu tersedia |
| --- | --- | --- |
| Official n8n Skills + MCP bawaan n8n | Membantu merancang node, expression, binary-data flow, penanganan error, dan membaca/menguji workflow Mandala. | URL instance, versi n8n, MCP enabled, akses workflow yang dipilih, dan OAuth/token. Dukungan membangun/mengubah workflow bergantung versi instance. Audit ini tidak mengakses atau mengubah instance. |
| Cloudinary cloudinary-docs dan cloudinary-transformations; MCP resmi saat perlu mengelola asset | Panduan upload, metadata, transformasi, signing, dan delivery video. | Akun/environment proyek dan autentikasi untuk operasi asset. Skills dokumentasi dapat digunakan tanpa memberi akses asset. Katalog pencarian plugin sesi ini tidak mengembalikan Cloudinary, tetapi dokumentasi resmi menyediakan opsi skills/MCP/plugin. |
| PostgreSQL client psql; akses database terbatas | Memeriksa schema, migrasi, metadata job, dan query saat database masuk scope. | Host/database dan akun dengan akses yang sesuai. psql belum ada pada PATH. Supabase/Neon bukan asumsi yang tepat untuk database proyek ini. MCP database bukan syarat wajib. |
| Coolify API dan bila diperlukan SSH | Memeriksa aplikasi, status deployment, dan diagnostik hosting. | URL instance dan credential; jangan memilih MCP komunitas sebelum ada kebutuhan yang tidak tercakup API/SSH. API resmi memiliki endpoint list aplikasi dengan bearer token. |
| GitHub CLI gh, CI, skill gh-fix-ci/gh-address-comments | Pemeriksaan PR/checks, pembacaan log CI, dan tindak lanjut review. | gh belum ada pada PATH. Tentukan remote repository dan baseline Git, lalu workflow CI. Credential connector tidak otomatis menjadi login gh. Kedua skill tersedia pada katalog, tetapi belum menjadi kebutuhan aktif checkout tanpa commit/remote/CI. |
| Playwright | Test UI dan interaksi dashboard ketika frontend dibangun. | Saat ini belum ditemukan aplikasi frontend utama. Gunakan browser capability existing; tambahkan Playwright runner/browser hanya ketika perlu test UI yang dapat diulang. |

**Batas kebutuhan saat ini**

Tidak ada alasan dari inspeksi ini untuk mengganti unittest dengan pytest, memasang semua skill frontend, mengunduh model ASR lokal, memasang CUDA/PyTorch, atau menambahkan Hopper/Ghidra/IDA. VMAF baru berguna bila ada tujuan evaluasi fidelity dengan reference yang sejajar; ia tidak menilai storytelling atau factual accuracy.

Tidak ditemukan plugin n8n atau Coolify pada pencarian katalog sesi ini. Itu bukan bukti layanan tersebut tidak dapat diintegrasikan: n8n memiliki MCP resmi, sedangkan Coolify dapat diakses lewat API resmi.

Kekurangan commit/remote/CI dan kebutuhan validasi timing speech adalah pekerjaan engineering yang nyata; memasang plugin saja tidak menyelesaikannya. Untuk perubahan yang mengubah source, receipts, atau artefak video, panduan proyek harus menjelaskan validasi dan regenerasi bukti yang diperlukan.

**Urutan pengerjaan yang disarankan**

1. Buat panduan/skill Mandala, tambahkan Ruff dan skill keamanan, lalu selesaikan koneksi Context7.
2. Tentukan repository GitHub yang benar, siapkan baseline Git, dan CI menggunakan suite existing.
3. Tambahkan n8n skills/MCP ketika workflow orchestration dikerjakan; gunakan autentikasi melalui mekanisme login atau penyimpanan credential lokal, bukan menempelkan token ke laporan.
4. Hubungkan Cloudinary, PostgreSQL, dan Coolify sesuai tugas integrasi. Verifikasi koneksi masing-masing sebelum mengklaim siap.

**Sumber utama**

- [Arsitektur plugin OpenAI](https://developers.openai.com/plugins/concepts/plugins) dan [Skills](https://developers.openai.com/plugins/concepts/skills): skills mengatur workflow, MCP memberi akses tool/layanan.
- [Ruff](https://docs.astral.sh/ruff/).
- [Context7](https://github.com/upstash/context7).
- [Official n8n Skills](https://github.com/n8n-io/skills) dan [MCP n8n](https://docs.n8n.io/connect/connect-to-n8n-mcp-server.md).
- [Cloudinary AI agent tools, skills dan MCP](https://cloudinary.com/documentation/cloudinary_llm_mcp).
- [Coolify API: list applications](https://coolify.io/docs/api/endpoints/applications/list-applications).
- [OpenAI curated skills](https://github.com/openai/skills/tree/main/skills/.curated): katalog diperiksa melalui helper Skill Installer; anotasi installed hanya memeriksa direktori personal, sehingga dibandingkan juga dengan daftar skill plugin yang tersedia dalam sesi.

Bukti lokal utama: README.md, requirements-av.txt, package.json plugin, docs/stage-5.6-remediation-report.md, docs/stage-5.6-qa-workflow.md, docs/remote-speech-asr-v01.md, test unittest, daftar MCP pada konfigurasi Codex, executable pada PATH, serta metadata paket .venv-av. File secret tidak dibaca.
