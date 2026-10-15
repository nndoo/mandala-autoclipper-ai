# Kapasitas VPS dan alokasi Media Worker

> **Revisi 15 Oktober 2026:** keputusan deployment/cutover dan jumlah file di
> laporan ini adalah snapshot historis. Rancangan aktif memakai Media Worker
> permanen + service editing baru dengan originals RO dan output terpisah.
> Lihat [keputusan final dua worker](../stage63/stage634-two-worker-architecture.md).

Snapshot read-only 14 Oktober 2026 dari halaman server Coolify dan terminal host.
Coolify menampilkan Ubuntu 24.04.4 x86_64, **2 CPU cores, RAM 7.4 GB**. `free -m`
pada host: total 7623 MiB, used 2981 MiB, `MemAvailable` 4642 MiB, swap total
1987 MiB dengan 933 MiB terpakai. `uptime` saat snapshot: load average
4.82/1.86/1.10. Angka load dan `docker stats --no-stream` hanyalah satu sampel;
metrics historis Coolify belum enabled, jadi tidak ada p95/puncak harian.

| Container | Snapshot RAM | Batas teramati |
| --- | ---: | --- |
| Media Worker | 46.91 MiB | 512 MiB hard cgroup |
| n8n | 471.1 MiB | host-visible 7.445 GiB |
| n8n task runners | 74.12 MiB | host-visible 7.445 GiB |
| PostgreSQL n8n/worker | 134.7 MiB | host-visible 7.445 GiB |
| Instagram autopost | 103.1 MiB | `memory.max=max`; Coolify memory limit unset |
| Coolify application | 268.9 MiB | host-visible 7.445 GiB |

Ada layanan lain di host (termasuk Hermes dan service platform); total host `used`
dan `MemAvailable` lebih relevan daripada hanya menjumlah baris pilihan. Angka
`7.445 GiB` pada `docker stats` adalah denominator host untuk container tanpa
limit, bukan alokasi RAM yang dijamin. Media Worker saat ini punya FFmpeg dan
Python 3.12, tetapi tidak punya NumPy/SciPy/jsonschema maupun runtime Node/OpenClaw
Stage 5. Cgroup 512 MiB tidak bisa menjalankan engine Stage 5 yang belum diuji
di sana.

## Rekomendasi alokasi Stage 6.3

1. Pertahankan limit 512 MiB untuk source worker hingga cutover image baru lolos
   offline parity, render/QA synthetic dan uji recovery. Image baru memakai **satu
   container** dan satu heavy slot untuk download/decode *atau* role media engine.
2. Profil canary awal: limit container **3.5 GiB**, CPU quota **1.25–1.5 vCPU**,
   worker task concurrency 1, API/status tetap responsif. Angka 3.5 GiB adalah
   batas percobaan, **bukan** ukuran RSS terukur; batas AS Stage 5 mencapai 3072
   MiB untuk revision/QA, dan Python/Node/API ikut memakan memori. Jangan menaikkan
   limit tanpa mengukur peak proses dan seluruh cgroup.
3. Simpan headroom host minimal sekitar **1.5 GiB MemAvailable** saat task berat.
   Admission menahan task baru bila headroom di bawah ambang yang dibuktikan oleh
   canary; jangan menganggap swap sebagai RAM produktif. Dalam snapshot 4642 MiB
   tersedia, job yang benar-benar memakai 3 GiB menyisakan kira-kira 1.5 GiB,
   sebelum lonjakan n8n/Coolify lainnya. Ini **borderline**, bukan production PASS.
4. FFmpeg, QA dan source download tidak overlap pada host 2 core. Batas subprocess
   Stage 5 (`prlimit`, waktu, file size, `MALLOC_ARENA_MAX=2`) tetap berlaku; CPU
   quota container membatasi keseluruhan worker. Uji waktu tunggu job serta
   respons `/health/ready` di bawah beban. Load 1 menit 4.82 saat audit memberi
   alasan memeriksa kontensi CPU, tetapi satu sampel tidak membuktikan pola tetap.
5. Untuk operasi production dengan ruang aman saat layanan lain memuncak,
   rekomendasi kapasitas **minimal 12 GiB RAM** atau host terpisah bagi video bila
   canary 7.4 GiB gagal menjaga headroom/latensi. Angka 12 GiB adalah target
   perencanaan, bukan kewajiban vendor atau hasil benchmark engine di VPS ini.

Gate keputusan setelah implementasi: catat `memory.peak`, OOM events,
`MemAvailable`, CPU/load, disk temp/output, durasi dan respons API selama kasus
Analyst, ASR, Director, render serta QA termasuk sumber 20 MiB/180 detik.
Bandingkan hasil dengan batas 3.5 GiB dan headroom. Jika tidak lolos, naikkan
kapasitas host atau pisahkan executor; jangan menandai preview/provenance PASS dari
`docker stats` idle atau sekadar filter FFmpeg tersedia.
