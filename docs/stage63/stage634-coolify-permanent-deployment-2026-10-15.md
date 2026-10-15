# Stage 6.3.4 — deployment runtime permanen di Coolify

**Tanggal:** 15 Oktober 2026 (Asia/Jakarta)

**Status:** **PASS — runtime healthy, `roles_ready=false`**

## Resource dan source

| Item | Hasil |
| --- | --- |
| Project / environment | `Mandala Auto - Autonomous AI Autoclipper` / `production` |
| Resource baru | [mandala-ai-editing-worker](http://43.129.33.7:8000/project/u7ekomrm0kyiy9cw69180qss/environment/qjjwm5j7fa4qa1wotn1gxq3a/application/tu5ry6txikxtpn4lge27opii) (`tu5ry6txikxtpn4lge27opii`), terpisah dari Media Worker |
| Git source | `nndoo/mandala-autoclipper-ai`, branch `main`, commit `17e1becc1c5f38cdda6b942d40a2f9a0db8bba41` |
| Build | Docker Compose dari `backend/compose.yaml`; Base directory `/backend`, Compose location `/compose.yaml`, sehingga `build.context: ..` adalah root repository dan Dockerfile `backend/Dockerfile` |
| Deploy akhir | [Log deployment `vz5qp6ondpsv1dimfqzletp1`](http://43.129.33.7:8000/project/u7ekomrm0kyiy9cw69180qss/environment/qjjwm5j7fa4qa1wotn1gxq3a/application/tu5ry6txikxtpn4lge27opii/deployment/vz5qp6ondpsv1dimfqzletp1), dimulai 13:43:05 WIB, selesai sekitar 13:46:44 WIB |
| Akses | Hanya `expose: 3003`; tidak ada domain publik atau host port binding (`PortBindings={}`) |
| Otomasi | Auto deploy: **Manual deployments only**; restart policy container: `unless-stopped` |
| Batas | 3584 MiB (`3758096384` byte) RAM dan 1.5 CPU (`1500000000` NanoCPUs) |

## Kapasitas dan isolasi storage

Sebelum penerapan limit, VPS memiliki 2 CPU, RAM total 7623 MiB dengan 4673 MiB available, swap total 1987 MiB, dan disk root 79 GiB dengan 25 GiB tersedia (68% terpakai). Sesudah deploy, `free -m` menunjukkan 4715 MiB available dan swap terpakai 1088 MiB. Ini sampel idle, bukan pengukuran beban puncak.

Volume Media Worker existing `muxr6rvojjjdrjrp24yjimak_autoclipper-data` terverifikasi ada melalui `docker volume inspect`, terpasang RW pada `/data` **hanya di Media Worker lama**, dan berisi originals. `docker inspect` pada editing worker membuktikan:

| Volume Docker | Path editing worker | RW |
| --- | --- | --- |
| `muxr6rvojjjdrjrp24yjimak_autoclipper-data` | `/data` | `false` |
| `muxr6rvojjjdrjrp24yjimak_autoclipper-data` | `/app/original-store` | `false` |
| `mandala-ai-editing-output` | `/app/data` | `true` |

Satu file originals existing terlihat dari `/data/source/originals` pada editing worker. Preflight membuktikan kedua alias originals menunjuk direktori yang sama, mount tersebut RO, dan output terpisah dapat ditulis melalui file sementara. File sementara hanya dibuat di output dan dihapus otomatis. Media Worker lama tetap `Up ... (healthy)` pada pemeriksaan sesudah deploy. Tidak ada perubahan pada Media Worker, n8n, database, atau OpenClaw Instagram.

## Verifikasi runtime

| Pemeriksaan | Hasil |
| --- | --- |
| Docker/Coolify | Container `tu5ry6txikxtpn4lge27opii-mandala-ai-editing-worker-1` `Running` dan `(healthy)`; Coolify menampilkan `Running` |
| Preflight | `python -m backend.runtime_check --check-storage --require-service-env` menghasilkan `status: PASS`, `errors: []` |
| Dependency | Python 3.14.2; NumPy 2.5.4; SciPy 1.18.1; jsonschema 4.25.1; psycopg 3.3.6; Node v24.21.0; FFmpeg 5.1.9; OpenClaw 2026.9.9. Preflight juga memeriksa `ffprobe`, binary runtime, manifest provider 9Router, dan berkas yang diperlukan |
| Endpoint internal | `GET http://127.0.0.1:3003/health` → HTTP 200, `status=ok`, `phase=runtime-preparation`, `roles_ready=false` |
| Log | [Runtime Logs Coolify](http://43.129.33.7:8000/project/u7ekomrm0kyiy9cw69180qss/environment/qjjwm5j7fa4qa1wotn1gxq3a/application/tu5ry6txikxtpn4lge27opii/logs) mencatat startup `PASS` dan healthcheck HTTP 200 berulang |
| Resource idle | Satu sampel `docker stats --no-stream`: 45.9 MiB / 3.5 GiB (1.28%) RAM, CPU 0.01% |

Tidak ada role endpoint yang diimplementasikan atau dipanggil. Tidak ada paid inference, render, publish, atau canary.

## Insiden konfigurasi dan catatan operasional

Deploy pertama gagal karena Base directory `/` membuat `build.context: ..` menunjuk ke luar checkout. Setelah Base directory diubah ke `/backend`, build berhasil, tetapi mode **Managed by Coolify** mengganti volume external originals dengan volume baru `tu5ry6txikxtpn4lge27opii_originals`; startup ditolak oleh preflight storage. Deploy berikutnya dalam mode Managed masih mengalami masalah yang sama. Mode **Raw (deploy file as-is)** kemudian disimpan dan dideploy ulang; Docker memakai volume originals existing serta membuat hanya output `mandala-ai-editing-output`.

Halaman **Persistent Storage** Coolify masih memperlihatkan nama hasil parsing Managed (`tu5ry6txikxtpn4lge27opii_originals` dan `tu5ry6txikxtpn4lge27opii_editing-data`). Itu tidak cocok dengan mount container Raw yang sedang berjalan. Gunakan `docker inspect` sebagai bukti mount aktual sebelum perubahan storage berikutnya. Volume yang dibuat pada percobaan Managed tidak dihapus otomatis dalam pekerjaan ini. Penggunaan RAM/CPU di bawah beban editing belum diuji; limit awal perlu dipantau saat job sungguhan kelak diaktifkan.
