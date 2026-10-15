# Stage 6.3.3 — kompatibilitas original MP4 nyata

Tanggal audit: 15 Oktober 2026 (Asia/Jakarta). Pengamatan VPS melalui terminal
Coolify Media Worker dan query PostgreSQL read-only. Tidak ada penulisan ke VPS,
database, n8n, atau media. Uji Stage 5 berjalan lokal tanpa inference dan render.

## Original dan metadata Stage 3

Di volume service Media Worker ditemukan satu original:
`/data/source/originals/7694493856326274356.mp4`. Query read-only terhadap
`public.source_videos` untuk `video_id` tersebut menghasilkan:

| Field | Nilai teramati |
| --- | --- |
| `source_key`, platform, akun | `tiktok:7694493856326274356`, `tiktok`, `mandala.auto.kediri` |
| status | `ORIGINAL_READY` |
| `original_local_path` | `/data/source/originals/7694493856326274356.mp4` |
| `original_size_bytes` | `2,949,952` |
| `original_sha256` | `000c759ac57ff4c2bfbdfd3e8d678f46d2160ea8855b4ca9bb343ce26c8671f3` |
| duration, width, height | `37.3` detik, `576 × 1024` |
| codec, audio | `h264`, audio ada |

`sha256sum` terhadap file aktif di VPS mengembalikan hash yang sama. `ffprobe`
file aktif melaporkan durasi `37.300000`, video `576 × 1024` dengan
`avg_frame_rate=30/1`, serta stream audio. `stat` dan inventaris file
menunjukkan ukuran yang sama dengan row DB. Batas POC 20 MiB/180 detik
terpenuhi; Stage 3 belum menyimpan FPS di row, sehingga FFprobe adalah sumber
FPS canonical.

Checkout lokal sudah memiliki
[`data/test-videos/mandala-original.mp4`](../../data/test-videos/mandala-original.mp4)
dengan **ukuran dan SHA-256 persis sama**. Ini membuktikan kesamaan byte untuk
uji lokal; bukan bukti bahwa path lokal dan volume VPS berbagi inode. Tidak ada
unduhan atau salinan MP4 baru. Adapter dijalankan dengan row PostgreSQL yang
diamati, `storage_root=/data/source`, dan `verified_mirror_path` yang menunjuk
file lokal tersebut. Opsi ini mempertahankan validasi path logis Stage 3,
kemudian memverifikasi byte mirror terhadap ukuran/hash/FFprobe DB. Opsi
`stage5_video_path` menunjuk path lokal yang sama; pemeriksaan inode lulus.

## Hasil adapter dan Stage 5

Canonical source yang dihasilkan:

```json
{
  "video_id": "local-sha256-000c759ac57ff4c2bfbdfd3e8d678f46",
  "duration_sec": 37.3,
  "width": 576,
  "height": 1024,
  "fps": 30.0
}
```

Adapter menjalankan FFprobe dan `verify_source()` Stage 5 terhadap media nyata;
schema source V0.3, SHA, filename, dan metadata cocok. Source sidecar existing
`data/analyses/universal/mandala-original.media.json` dan source pada
`pak-fuad-universal-v02.canonical.json` sama dengan hasil adapter. Canonical
analysis existing berstatus `DRAFT_UNVERIFIED` dan melewati validator
schema/semantik/timing Universal V0.2. Peringatannya tetap: schema tidak
memverifikasi fakta audiovisual atau timing frame-accurate.

`build_director_input()` Stage 5 dijalankan secara offline dengan MP4 lokal
yang byte-identik, **sidecar yang dihasilkan adapter**, dan canonical analysis
existing. Sidecar/output sementara dibuat di direktori baru di bawah `data/`, diperiksa, lalu
dibersihkan; historical evidence tidak diubah. Hasilnya **`NEEDS_REVIEW`**,
source cocok, `render_approved=false`, dan `publish_approved=false`. Tidak ada
model call, ASR, atau render. Hasil ini adalah kompatibilitas kontrak/source
dan validasi struktural, bukan validasi editorial independen.

## Masalah path dan perbaikan lokal

Stage 5 `project_path()` hanya menerima media di bawah root proyek. Path VPS
`/data/source/originals/...` berada di luar root tersebut, sedangkan path
mirror lokal `data/test-videos/mandala-original.mp4` diterima. Pemeriksaan
lokal pada path VPS menghasilkan
`Source MP4: path escapes project root (including symlinks)`. Untuk integrasi
container, original harus tersedia melalui **mount kedua volume
yang sama** di bawah root proyek, misalnya `/app/data/source/originals/...`.
Tidak cukup membuat symlink karena `project_path()` memeriksa path hasil
`resolve()`. [Compose lokal](../../backend/compose.yaml) sekarang menyatakan
`autoclipper_data:/data` dan `autoclipper_data:/app/data`; belum dideploy.
[`prepare_intake()`](../../backend/media_worker/intake_adapter.py) juga dapat
memeriksa alias Stage 5 terhadap device/inode/ukuran file yang diverifikasi,
sehingga alias tidak boleh menunjuk salinan berbeda. Mirror audit lokal adalah
jalur eksplisit dan tidak mengubah kontrak produksi normal.

Image backend lokal saat ini baru menyalin paket `backend`, belum keseluruhan
scripts/schema/dependency Stage 5. Dengan demikian uji input lokal lulus,
tetapi runtime end-to-end di VPS **belum siap** dan belum diklaim lulus.

## Regresi setelah perbaikan

| Pemeriksaan | Hasil |
| --- | --- |
| `test_intake_adapter_stage632.py` | 10 lulus, termasuk mirror logis dan alias inode |
| `test_adaptive_director_input_v03.py` | 39 lulus |
| `test_stage54_planning_integration.py` | 32 lulus |
| `test_media_worker_stage631.py` | 7 lulus |
| `ruff check scripts tests backend` | lulus |
| `docker compose -f backend/compose.yaml config -q` | lulus |

Tidak ada deployment, commit, atau push.
