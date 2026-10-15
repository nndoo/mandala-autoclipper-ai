# Stage 6.3.4 — finalisasi sebelum build pertama Coolify

15 Oktober 2026. **READY_FOR_FIRST_COOLIFY_BUILD_AFTER_APPROVED_PUSH.**
Source lokal siap direview dan di-push setelah persetujuan. Ini bukan hasil build
image, pengujian container VPS, atau approval production/publishing. GitHub main
diverifikasi read-only masih `7e6021a5265a451bbd870c00173cecb465258ab0`, cocok
dengan `origin/main`. Tidak ada commit, push, deploy, atau perubahan Media Worker
VPS, n8n dan PostgreSQL pada finalisasi ini.

## Keputusan dan cakupan final

- Media Worker lama `:3002` adalah service **permanen** untuk source discovery,
  download, validation/hash dan file delivery existing. Source lokalnya identik
  dengan baseline GitHub; Compose baru tidak membuat atau mengganti service itu.
- AI Editing Worker `mandala-ai-editing-worker:3003` adalah service permanen
  terpisah dengan satu container untuk sembilan role. Saat ini hanya startup
  preflight dan `/health`; `/source/*`, `/v1/jobs` dan role routes tetap 404.
- Satu workflow utama n8n kelak memanggil dua worker sesuai tugas. Sembilan node
  editing: **Analyst, AV Evidence, Speech/ASR, Creative Director, Validator,
  Renderer, Technical QA, Reviewer, Revision Controller**. Admission/status/Wait/
  Switch bukan role tambahan. AV Evidence dan Speech/ASR memakai file, endpoint
  dan node terpisah; tidak membuat workflow ASR atau workflow editing kedua.
- Seluruh I/O, prasyarat, status dan revisi diperbarui di
  [role-endpoint-map](../stage62/role-endpoint-map.md). Tidak ada implementasi
  role endpoint, migrasi job DB atau perubahan workflow n8n pada tahap ini.

## Audit build dan startup

| Komponen | Hasil finalisasi |
| --- | --- |
| Dockerfile/context | `backend/Dockerfile`, context root `/`; entrypoint `python -m backend.editing_worker`, expose 3003. Seluruh COPY source tersedia dalam daftar source Git |
| Python | Python 3.14.2; sembilan dependency terkunci dengan hash. Lock dipasang wheel-only ke environment sementara terisolasi; NumPy/SciPy/jsonschema/psycopg dan enam modul/entry Stage 5/editing berhasil diimpor |
| Wheel compatibility | Resolver binary-only untuk Python 3.14.2, linux x86_64/manylinux_2_36 (glibc Bookworm) berhasil; tetap belum pengujian shared library pada image Debian aktual |
| Node/OpenClaw | Pin Node 24.21.0 sesuai engine OpenClaw 2026.9.9 (`>=24.16.0 <25`). Wrapper dan layout home terisolasi dipertahankan; npm manifests/locks tidak diubah. Instalasi npm/native dependencies dalam base image masih gate build pertama |
| Adapter plugin | Provider binding/manifest/dist diregenerasi dalam builder pada layout project `/app`; tidak bergantung pada binding/dist lokal ignored. Build, 23 tests dan type check lulus |
| FFmpeg/fonts | Docker build sekarang memanggil inventory existing `renderer_core_v01.environment()` dan memeriksa seluruh filter dari `FILTERS`, libx264, AAC, libass, font normal+bold; tidak melakukan render. Command lulus pada host dalam environment Python terisolasi |
| Runtime preflight | Memeriksa versi **dan import** Python; `timeout` ikut tool wajib; port harus tepat 3003; provider ID harus cocok dengan manifest. Binary import failure dan mismatch port/provider dibuktikan ditolak oleh tests |
| Startup | Menolak dependency/storage/env invalid sebelum membuka HTTP. Tidak membutuhkan credential DB/provider untuk runtime canary. `/health` memuat identitas editing dan `roles_ready=false` |
| `.dockerignore` | Default-deny; source API lama, private config, media, cache, snapshot dan generated local plugin tidak ikut image. Config/intake existing tetap direuse |

Perubahan yang sudah benar dari revisi sebelumnya dipertahankan: builder dengan
layout repository, fixture QA mandiri, root `requirements-av*.txt` untuk receipt
producer, dependencies downloader dikeluarkan, serta stdlib server editing
terpisah. Tidak ada perubahan engine/validator/provenance/permit/budget/revision
Stage 5 atau transport TypeScript.

## Storage dan isolasi layanan

Base Compose hanya mendefinisikan `mandala-ai-editing-worker`, tanpa DB, n8n,
source service, depend_on production atau port publik. `expose: 3003` hanya untuk
network internal. Original external volume wajib diberi nama eksplisit.

| Mount | Volume | Mode |
| --- | --- | --- |
| `/data` | Original existing | RO, nocopy |
| `/app/original-store` | Original yang sama, alias untuk root guard Stage 5 | RO, nocopy |
| `/app/data` | Output editing baru, berbeda dari originals | RW, nocopy |

Runtime gate memeriksa flag ST_RDONLY pada kedua source path, inode alias,
readability dan pemisahan output. Probe tulis hanya pada output. Docker inspect
tetap wajib saat canary untuk membuktikan nama sumber mount yang sebenarnya.
Intake existing mempertahankan logical path `/data/source/originals/...` dan
memverifikasi alias `/app/original-store/source/originals/...`, SHA/FPS/durasi/
resolusi/identity serta before-after stat. Tidak menyalin atau memindahkan media.

Canary overlay memakai **mandala-stage634-canary-originals** dan
**mandala-stage634-canary-output**, tanpa volume/credential production. Hasil
render Compose base/canary telah diperiksa: tepat satu service editing, sumber
RO, output RW berbeda dan tidak ada env PostgreSQL. Di dalam editing service
tidak ada source API; source Worker/snapshot/config/intake tidak diedit.

## Hasil pengujian

| Pemeriksaan | Hasil |
| --- | --- |
| Full offline `.venv-av/bin/python -m unittest discover -s tests -p 'test_*.py'` | **1350 tests PASS**, 106.033 detik, exit 0 |
| Adapter `npm run build`, `npm test`, `tsc --noEmit` memakai bundled Node | **23 tests PASS**, build/type check PASS |
| OpenClaw version dengan OPENCLAW_STATE_DIR/CONFIG_PATH sementara tanpa private config | OpenClaw 2026.9.9 (bcfc888), exit 0; host runtime, tanpa inference |
| `ruff check scripts tests backend` dan `git diff --check` | PASS |
| Isolated locked Python install/import + binary-only resolver | PASS |
| Reuse Stage 5 FFmpeg inventory di host | PASS, tanpa render |
| Base/canary Compose service/volume/env assertions | PASS |
| Sembilan role/module/node rows | PASS; AV Evidence dan Speech/ASR terpisah |
| Existing source Worker, intake, Stage 5 scripts/schema dan plugin runtime terhadap GitHub baseline | Tidak berubah |

Full regression mencakup test runtime editing, worker parity, intake, planning,
validator, renderer/QA/revision dan security/credential rejection. Live `poc_*`
tidak dijalankan. Hasil fixture/model mock bukan inference berbayar atau human
review. Log lengkap sementara ada di `/tmp/mandala-stage634-final-regression.txt`.
Tidak mengubah historical evidence untuk membuat test/proof lolos.

## Audit kandidat Git/staging

Index staging utama tetap kosong. Manifest [`git-safe-files.txt`](git-safe-files.txt)
memuat seluruh file source/reference yang eligible; dry-run staging dipakai tanpa
menulis index. Calon Git diperiksa untuk media/binary, private key, token/JWT,
URL bercredential, literal secret dan kecocokan nilai secret privat lokal tanpa
mencetak nilainya. String credential yang tersisa adalah fixture test, regex
penolakan atau referensi environment; tidak ada credential nyata teridentifikasi.
Originals, model/media, `.env.asr`, `.openclaw`, data/archive dan dependency cache
tetap ignored. Dokumen memuat metadata VPS/path operasional, sehingga target tetap
repository private. Daftar context ada di
[`coolify-build-context.txt`](coolify-build-context.txt).

## Gerbang build test pertama — sesudah persetujuan

1. Review revisi ini, lalu commit/push yang disetujui dan catat SHA. Main `7e6021a`
   belum memuat pemisahan service ini; jangan deploy commit lama sebagai editing
   worker. Aplikasi baru tidak boleh mengganti nama/resource Media Worker lama.
2. Buat resource canary untuk image editing baru dengan Dockerfile/context di atas,
   provider ID non-secret yang sama pada build/runtime, auto-deploy off, port 3003
   tanpa domain publik, dan storage fixture terpisah. Tidak ada credential
   production, DB atau koneksi n8n yang diperlukan untuk runtime test.
   Verifikasi GitHub App **Coolify** dapat membaca repository baru; akses connector
   Codex tidak membuktikan installation Coolify sudah diberi akses repo itu.
3. Sebelum startup, siapkan direktori kosong pada **fixture canary saja**. Setelah
   image baru berhasil dibangun, contoh helper manual sekali pakai:

   ```sh
   : "${MANDALA_CANARY_IMAGE:?Set the newly built canary image tag or ID}"
   docker volume create mandala-stage634-canary-originals
   docker run --rm --network none \
     --mount type=volume,source=mandala-stage634-canary-originals,target=/fixture \
     --entrypoint python "$MANDALA_CANARY_IMAGE" \
     -c "from pathlib import Path; Path('/fixture/source/originals').mkdir(parents=True, exist_ok=True)"
   ```

   Helper ini tidak dijalankan sekarang dan tidak memasang volume production.
   Sesudahnya source mounts service harus RO. Tanpa direktori fixture, startup
   memang harus gagal; jangan mengatasinya dengan membuat originals writable.
4. Untuk overlay lokal/terminal canary, render dan periksa dahulu:

   ```sh
   MANDALA_ORIGINAL_VOLUME=canary-only docker compose \
     -f backend/compose.yaml -f backend/compose.canary.yaml config
   ```

   Pastikan kedua nama volume efektif adalah nama canary di atas, bukan volume
   existing. Coolify harus menerapkan mount yang setara; dukungan UI/Compose dan
   flags aktual perlu diverifikasi sebelum start.
5. Jalankan inventory Python/Node/OpenClaw/plugin/FFmpeg/font, runtime_check dengan
   `--check-storage --require-service-env`, health HTTP dan source routes 404 di
   container baru. Catat image size/digest, startup log, CPU, idle/peak RAM dan OOM
   events. Limit 3584 MiB/1.5 CPU adalah profil awal, bukan hasil benchmark.
6. Hanya setelah canary lolos dan izin berikutnya: uji mount originals existing RO
   dan intake read-only. Role endpoints, job DB, workflow n8n dan inference/render
   editorial memiliki tahap implementasi/approval terpisah.

Docker daemon lokal tidak tersedia. Ukuran image, RAM container, install apt/npm,
mount RO nyata, registrasi/auth plugin dan kompatibilitas FFmpeg Debian tetap
belum terbukti sampai build/run pertama. Paket apt belum memakai snapshot
bertanggal, sehingga hasil belum bit-identical antar waktu. Production readiness
tidak dinyatakan dari hasil source tests saja.

## File berubah terhadap main

Daftar berikut mencakup modifikasi dan file baru, tanpa staging/commit.

```text
MOD .dockerignore
MOD README.md
MOD backend/.env.example
MOD backend/Dockerfile
NEW backend/compose.canary.yaml
MOD backend/compose.yaml
NEW backend/editing_worker.py
MOD backend/requirements.in
MOD backend/requirements.lock.txt
MOD backend/roles/README.md
MOD backend/runtime_check.py
MOD docs/repository-structure.md
MOD docs/stage62/README.md
MOD docs/stage62/github-coolify-deployment.md
MOD docs/stage62/implementation-plan.md
MOD docs/stage62/modular-architecture.md
MOD docs/stage62/resource-capacity.md
MOD docs/stage62/role-endpoint-map.md
MOD docs/stage63/README.md
MOD docs/stage63/coolify-build-context.txt
MOD docs/stage63/git-readiness.md
MOD docs/stage63/git-safe-files.txt
MOD docs/stage63/stage634-coolify-runtime-test.md
MOD docs/stage63/stage634-docker-runtime.md
NEW docs/stage63/stage634-final-readiness.md
NEW docs/stage63/stage634-two-worker-architecture.md
NEW tests/test_editing_worker_runtime.py
```

Total 27 file berubah/baru terhadap main; index staging tetap kosong.
Inventaris source Git: 219 file. Static build context: 108 file, 1,554,995 byte sebelum kompresi; seluruh COPY tersedia.
