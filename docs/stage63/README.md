# Stage 6.3 documentation

For current navigation, start with the [AI agent reading guide](../AGENT_GUIDE.md).
Stage 6.3.5 recovery has a [final recovery report](stage635-final-report.md),
the [API contract](stage635-api-contract.md),
[deployment guide](stage635-deployment-guide.md), and local checkpoints
[A](stage635-stage-a-checkpoint-2026-10-15.md),
[B](stage635-stage-b-checkpoint-2026-10-15.md),
[C](stage635-stage-c-checkpoint-2026-10-15.md),
[D](stage635-stage-d-completion-2026-10-16.md),
[E](stage635-stage-e-checkpoint-2026-10-16.md), and
[F terbaru](stage635-stage-f-checkpoint-2026-10-16.md). A–E passed only their stated
local scopes; F is BLOCKED for deployment readiness. The [partial D checkpoint](stage635-stage-d-checkpoint-2026-10-15.md)
records the earlier Renderer blocker. The recovered
[project checkpoint](PROJECT_CHECKPOINT_RECONSTRUCTED.md) and
[implementation report](stage635-implementation-report.md) describe prior PC
work and are not evidence of the current source or deployment. Verify current
code and tests for operational status.

## Stage 6.3.1 — historical import record

**Keputusan pada Stage 6.3.4:**
[Media Worker permanen + editing worker baru](stage634-two-worker-architecture.md).
[Finalisasi sembilan role dan kesiapan build](stage634-final-readiness.md).
Dokumen di bawah menyimpan riwayat import dan pengujian sebelumnya.

Tahap lanjutan: [Stage 6.3.2 Intake Adapter](stage632-intake-adapter.md).
Audit media nyata: [Stage 6.3.3](stage633-real-original-compatibility.md).
Persiapan image tunggal: [Stage 6.3.4 Docker Runtime](stage634-docker-runtime.md).
Audit uji di VPS: [Stage 6.3.4 Coolify Runtime Test](stage634-coolify-runtime-test.md).
Persiapan source GitHub: [Git readiness](git-readiness.md).

## Hasil

Source `/tmp/worker.py` yang berjalan di VPS tersimpan utuh sebagai
[`backend/vps_snapshot/worker.py`](../../backend/vps_snapshot/worker.py).
SHA-256 salinan lokal **sama** dengan hash yang dibaca dari container:
`718d15e45ad4fb24935e65e6bc227ac7b3bd12e1b070844c24aecf9120c5e975`.
Keduanya berukuran 17.957 byte dan 409 baris. Snapshot tidak diedit.

Versi yang akan dikembangkan ada di
[`backend/media_worker/app.py`](../../backend/media_worker/app.py). Source ini
berawal dari salinan tersebut; perilaku endpoint tetap sama, sedangkan nilai
konfigurasi non-secret dipindahkan ke
[`backend/media_worker/config.py`](../../backend/media_worker/config.py).
Credential PostgreSQL tetap dibaca dari environment saat diperlukan. Tidak
ada credential atau hasil media VPS yang disimpan di repository.

## Struktur

| Lokasi | Fungsi |
| --- | --- |
| `backend/vps_snapshot/worker.py` | Bukti source VPS byte-identik; jangan ubah untuk pengembangan |
| `backend/media_worker/app.py` | Implementasi API lokal dengan empat endpoint existing |
| `backend/media_worker/config.py` | Username/channel, root storage, batas ukuran, port dan default DB melalui environment |
| `backend/roles/` | Tempat modul AI role Stage 6.3 berikutnya; belum aktif |
| `backend/Dockerfile` | Build Git-backed yang setara dengan dependency image VPS |
| `backend/compose.yaml` | Compose lokal calon pengganti inline source; belum digunakan VPS |
| `backend/.env.example` | Nama variable dan default non-secret; nilai private ada di environment lokal/Coolify |
| `docs/stage63/vps-dockerfile-observed.Dockerfile` | Transkripsi Dockerfile inline yang diamati |
| `docs/stage63/vps-compose-observed.md` | Konfigurasi runtime Compose yang diamati, tanpa nilai credential |

Pada Stage 6.3.1 Docker build memakai `python:3.12-slim-bookworm`, FFmpeg/FFprobe, `yt-dlp[default,curl-cffi]==2026.8.19`, `curl-cffi>=0.11,<0.17`, dan `psycopg[binary]>=3.2,<4`, sesuai konfigurasi VPS saat itu. Dockerfile kemudian diperluas pada Stage 6.3.4; lihat laporan tahap tersebut untuk rancangan image terkini. Volume `/data` dan port internal `3002` dipertahankan. Struktur baru menjalankan `python -m backend.media_worker.app`, bukan menulis source heredoc ke `/tmp/worker.py` saat boot. Tidak ada role endpoint baru pada tahap ini.

## Kontrak yang dipertahankan

| Endpoint | Perilaku existing |
| --- | --- |
| `GET /health` | JSON `status=ok`, `service=autoclipper-media-worker` |
| `POST /source/discover` | Terima `username`, `maxVideos`; jalankan yt-dlp; kembalikan daftar TikTok `videoId`, `url`, `title` |
| `POST /source/download` | Validasi `videoId`/`claimToken`, reservasi PostgreSQL, satu unduhan pada satu waktu, validasi ffprobe/decode/checksum, simpan original di `/data/source/originals` |
| `POST /source/file` | Validasi claim dan metadata PostgreSQL, cocokkan ukuran/SHA-256 file, stream MP4 ke n8n |

Respons JSON, status HTTP, direktori persistent, lock, batas media, dan mekanisme claim berasal dari source VPS. Variabel konfigurasi tambahan memakai default yang sama, sehingga tanpa override perilakunya setara. `PGHOST`, `PGUSER`, dan `PGPASSWORD` tetap wajib untuk operasi file/download; `PGPORT` dan `PGDATABASE` punya default yang sama.

## Verifikasi lokal

- `sha256sum backend/vps_snapshot/worker.py`: cocok dengan VPS.
- `.venv-av/bin/python -m unittest discover -s tests -p 'test_media_worker_stage631.py' -q`: **7 test lulus**. Test membandingkan output HTTP source VPS dan source lokal untuk health/404, discovery, admission download/file, file streaming sukses, dan unduhan original yang sudah ada. Eksekusi eksternal dan database diganti mock; tidak ada TikTok, PostgreSQL, atau media VPS yang disentuh.
- `ruff check scripts tests backend`: **lulus**.
- `docker compose -f backend/compose.yaml config -q`: **lulus**.

Pengujian ini membuktikan kesetaraan jalur yang diuji secara offline. Image Docker belum dibangun, dependency `psycopg` tidak terpasang pada `.venv-av`, dan jalur unduhan TikTok baru serta transaksi PostgreSQL live belum diuji. Itu menjadi gerbang verifikasi sebelum mengganti service VPS pada tahap berikutnya, bukan status deploy-ready. Stage 6.3.1 tidak mengubah VPS, workflow n8n, atau database; tidak ada deploy, commit, atau push.
