# Audit migrasi device — 14 Oktober 2026

Folder tujuan: `/home/nndoo/Projects/mandala-autoclipper-ai`.
Source dan sebagian media/evidence tersedia, tetapi pipeline belum siap dijalankan di device ini. Audit ini memeriksa kondisi lokal; tidak menguji koneksi remote, melakukan inference, memasang dependency, atau mengubah evidence lama.

## Temuan

| Prioritas | Temuan saat audit | Dampak |
| --- | --- | --- |
| Penghambat | `.venv-av/bin/python3` menunjuk `/home/kentung/.pyenv/versions/3.14.2/bin/python3`, target tidak tersedia. `pyvenv.cfg` juga memakai lokasi device lama. | Python proyek tidak bisa dieksekusi; virtualenv harus dibuat ulang. |
| Penghambat | `ffmpeg`, `ffprobe`, dan `ruff` tidak ditemukan di PATH. `prlimit` dan font DejaVuSans tersedia. | Decode/render/QA media dan lint belum bisa diverifikasi. |
| Penghambat | `~/.local/share/mandala-openclaw-runtime` tidak tersedia. Runner Director memilih runtime ini dan Node `tools/node-v24.21.0/bin`. | Node di PATH (v24.19.0) tidak menggantikan runtime inference tersebut. |
| Tinggi | Git memiliki nol tracked files, belum ada commit, dan nol remote. Source muncul sebagai untracked. | Folder ini belum membawa riwayat repository; pemulihan history dari device lama perlu dilakukan jika history memang ada. |
| Tinggi | `requirements-av.txt` hanya memuat NumPy dan SciPy; `jsonschema` sebelumnya diwarisi melalui `--system-site-packages`. | Instalasi dari manifest saja belum menjamin environment lengkap. System Python saat audit adalah 3.12.3, dengan jsonschema, tanpa NumPy/SciPy; runtime lama Python 3.14.2. |
| Tinggi | Konfigurasi/provider/registrasi agent OpenClaw berada di luar folder proyek. Generator binding membaca `~/.openclaw/openclaw.json`. | Memindahkan folder source saja tidak cukup untuk inference. Migrasi konfigurasi harus menyesuaikan lokasi baru dan menjaga credential privat. |
| Sedang | Referensi `/home/kentung` masih ditemukan dalam laporan dan JSON evidence historis. | Artifact tersebut membuktikan eksekusi lama, bukan readiness device baru. Jangan mengganti path massal dalam receipt/evidence. |
| Sedang | README menyebut n8n, PostgreSQL, Cloudinary, dan Coolify tanpa bukti koneksi lokal dalam audit ini. | Status layanan belum diverifikasi; tidak boleh dianggap operasional. |
| Sedang | Skill personal `mandala-video-workflow` yang direferensikan panduan tidak ditemukan dalam lokasi skill lokal yang diperiksa. | Tooling/panduan personal dari device lama belum seluruhnya dibawa. |

## Komponen yang sudah diperiksa

- Adapter: `npm test` berhasil, Node test runner melaporkan 4 test entries lulus; `node_modules/.bin/tsc --noEmit` exit 0. Ini pemeriksaan adapter lokal, bukan integrasi 9Router/OpenClaw.
- Data sekitar 76 MiB tersedia, termasuk `mandala-original.mp4`, video cinematic, canary, analysis, QA, render-test, revision, dan backup. Keberadaan file tidak membuktikan seluruh transfer lengkap atau decode media berhasil.
- `.env.asr` tersedia dengan mode 0600 dan pola ignore `.env.*`. Isi/key tidak dicetak atau diuji; keberadaan file tidak membuktikan credential masih valid.
- `.venv-av` sekitar 222 MiB dan folder OpenClaw proyek sekitar 27 MiB. Dependency hasil salinan bukan instalasi yang reproducible.
- Tes Python tidak dijalankan karena interpreter wajib proyek rusak. Ruff tidak dijalankan karena command belum tersedia. Klaim kelulusan tes dalam dokumen lama tetap merupakan hasil device lama.

## Urutan migrasi

1. Pertahankan salinan folder saat ini sebagai bukti transfer. Jika device lama masih tersedia, bandingkan manifest nama, ukuran, dan SHA-256 file source/media/evidence; audit ini tidak memiliki manifest pembanding sehingga kelengkapan transfer belum dapat disimpulkan.
2. Ambil history Git/remote dari device lama bila tersedia. Jika proyek lama juga belum memiliki commit, buat baseline setelah memeriksa file yang akan dilacak. `data/`, media, `.env.*`, virtualenv, `node_modules/`, dan `dist/` di-ignore sehingga clone Git tidak membawa komponen tersebut.
3. Buat ulang `.venv-av` dari interpreter yang kompatibel. Python 3.14.2 adalah baseline lama; versi lain memerlukan regresi. Pasang NumPy/SciPy sesuai manifest dan jsonschema secara eksplisit; catat versi jsonschema yang dipakai. Jangan mengandalkan symlink virtualenv hasil salinan.
4. Pasang FFmpeg/FFprobe dan Ruff. Verifikasi encoder libx264/AAC serta filter renderer dan font melalui pemeriksaan capability proyek.
5. Bangun ulang dependency adapter dengan lockfile (`npm ci`), kemudian `npm run build`, `npm test`, dan `node_modules/.bin/tsc --noEmit`.
6. Pulihkan/pasang runtime OpenClaw terisolasi yang sesuai baseline adapter, bundled Node, konfigurasi provider, dan registrasi agent/plugin. Konfigurasi privat harus disesuaikan ke user/lokasi baru; jangan menyertakan credential dalam laporan atau Git. Jangan menjalankan generator binding sebelum provider tujuan benar.
7. Jalankan `.venv-av/bin/python -m unittest discover -s tests -p 'test_*.py'` dan `ruff check scripts tests`; `poc_*` bukan tes offline rutin. Validasi bundle historis secara offline terlebih dahulu. Untuk receipt yang terikat environment, buat proof/output bundle baru melalui writer proyek, bukan mengubah bundle lama.
8. Verifikasi koneksi 9Router/remote ASR dan layanan deployment secara terpisah setelah konfigurasi tersedia. Inference, review editorial, serta publish/deploy memiliki status terpisah dari keberhasilan tes lokal.

## Yang dibawa dari device lama

- Source/config non-secret/docs/schema/prompts dan history Git bila ada.
- Media asli beserta seluruh evidence yang ingin dipertahankan, termasuk file yang di-ignore Git.
- Konfigurasi privat ASR/OpenClaw/provider melalui mekanisme privat, beserta pemetaan agent/plugin; bukan salinan token dalam source.
- Manifest versi runtime OpenClaw/Node/Python/FFmpeg dan dependency, serta skill personal yang masih digunakan.
- Konfigurasi layanan eksternal bila layanan tersebut memang digunakan. PostgreSQL client tidak membuktikan database ada; workflow n8n dan konfigurasi Coolify tidak otomatis berada di folder ini.

Audit ini tidak melakukan perbaikan instalasi atau perubahan source. Laporan ini adalah daftar readiness migrasi, bukan audit keamanan menyeluruh atau sertifikasi kualitas editorial.
