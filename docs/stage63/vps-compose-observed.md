# Konfigurasi Compose Media Worker yang diamati di Coolify

Sumber: editor **Compose File** service `autoclipper-media-worker` di project
Mandala Auto, 14 Oktober 2026. Ini transkripsi struktur konfigurasi aktif;
source Python yang tertanam dalam `command` disimpan byte-identik di
[`backend/vps_snapshot/worker.py`](../../backend/vps_snapshot/worker.py).
Nilai credential tidak disalin. File ini adalah evidence, bukan Compose
yang dapat langsung dideploy.

| Bagian | Konfigurasi yang diamati |
| --- | --- |
| Service | `autoclipper-media-worker` |
| Build | `context: .`, `dockerfile_inline` sesuai `vps-dockerfile-observed.Dockerfile` |
| Restart/init | `unless-stopped`, `init: true` |
| Environment | `TZ=Asia/Jakarta`, `PYTHONUNBUFFERED=1`, `PGHOST`, `PGPORT` (default `5432`), `PGUSER`, `PGPASSWORD`, `PGDATABASE=mandala_autoclipper`; credential berasal dari interpolasi environment Coolify |
| Volume | named volume `autoclipper_data:/data` |
| Jaringan | `expose: 3002`; tidak ada `ports` publik pada Compose ini |
| Command | `/bin/sh -ec`; verifikasi `yt-dlp`, FFmpeg, FFprobe, `psycopg`/`curl_cffi`; tulis heredoc source ke `/tmp/worker.py`; `exec python /tmp/worker.py` |
| Healthcheck | Python `urllib.request.urlopen('http://127.0.0.1:3002/health', timeout=5)`; interval 30s, timeout 10s, retries 5, start period 120s |
| Memory | `mem_limit: 512m` |

Source aktif di container pada saat audit: `/tmp/worker.py`, 409 baris,
17.957 byte, SHA-256 `718d15e45ad4fb24935e65e6bc227ac7b3bd12e1b070844c24aecf9120c5e975`.
Hash ini dibaca di terminal container dengan `sha256sum /tmp/worker.py` dan
dicocokkan dengan salinan repository. Compose memang menanam seluruh source
dalam string `command`, sehingga pemindahan ke file source terpisah mengubah
cara build, bukan kontrak API.
