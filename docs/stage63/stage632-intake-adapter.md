# Stage 6.3.2 — Intake Adapter

## Hasil implementasi

[`backend/media_worker/intake_adapter.py`](../../backend/media_worker/intake_adapter.py)
menjembatani row Stage 3 `public.source_videos` berstatus `ORIGINAL_READY`
dengan metadata source Stage 5. Fungsi `prepare_intake(record, storage_root=...)`
hanya membaca original MP4 pada persistent storage; tidak mengunduh,
menyalin, mengubah, atau menulis file media/sidecar. Hasilnya memuat path
original, identitas upstream, canonical `source`, dan sidecar `metadata` yang
siap ditulis secara eksklusif oleh job writer pada tahap berikutnya.

Kontrak input adalah snapshot row Stage 3, bukan body langsung dari
`POST /source/download`. Row wajib memiliki `source_key`, `platform`,
`username`, `video_id`, `status`, `original_local_path`,
`original_size_bytes`, `original_sha256`, `original_duration_seconds`,
`original_width`, dan `original_height`. Ini mengikuti kolom yang diaudit pada
Stage 6.2. Worker mengembalikan bentuk camelCase lebih awal; n8n baru menulis
status `ORIGINAL_READY` setelah save metadata. Adapter hanya boleh dipanggil
setelah state itu ada. `original_video_codec` dan `original_audio_present`
tetap data Stage 3, tetapi bukan field canonical source Stage 5. Stage 3 tidak
menyimpan FPS; adapter mengukurnya dengan FFprobe.

| Pemeriksaan | Ketentuan |
| --- | --- |
| Identity | `platform=tiktok`, akun yang dikonfigurasi, `source_key=tiktok:<video_id>`, ID numerik 15–25 digit, status `ORIGINAL_READY` |
| Path | Harus persis `<storage_root>/originals/<video_id>.mp4`, file reguler, bukan symlink, resolve tetap di root persistent |
| Batas POC | 1.024–20.971.520 byte dan durasi Stage 3 maupun probe maksimal 180 detik |
| Media binding | Ukuran aktual sama dengan row; SHA-256 file sama dengan row; durasi dan resolusi probe sama dengan row |
| FPS | `avg_frame_rate` FFprobe menjadi FPS canonical; bila row kelak menyertakan `fps`, nilainya juga harus cocok |
| Stage 5 | `video_id=local-sha256-<32 hex awal SHA>`, durasi/FPS dibulatkan tiga desimal dengan aturan Stage 5, source schema V0.3 dan `verify_source()` existing dipanggil kembali |
| Race | Device, inode, ukuran, dan mtime file diperiksa sebelum/sesudah verifikasi; perubahan selama intake diblokir |

Output `metadata` memakai `verification.method=ffprobe_and_sha256`,
`file_name`, dan hash penuh sesuai validator Stage 5. Identitas TikTok tetap
`upstream_video_id`/`source_key`; tidak menggantikan content-hash ID yang
dipakai Stage 5. Pemanggilan berulang dengan row dan byte original yang sama
menghasilkan output identik dan tidak membuat salinan media. Deduplikasi job
durable lintas permintaan belum dilakukan karena tabel job Stage 6 belum ada;
Stage 5 `source.video_id`/SHA penuh dapat menjadi kunci konten pada layer job.

`validate_canonical_analysis(intake_result, analysis)` adalah gerbang untuk
hasil Analyst yang datang kemudian: ia memakai schema Universal V0.2 dan
validator semantik/timing Stage 5, lalu memastikan `analysis.source` sama
persis dengan hasil intake. Intake sendiri **tidak menghasilkan** temuan AI,
transkrip, timing editorial, approval render, atau izin publish. Fungsi
existing Stage 5 tidak diubah.

## Batas path Stage 5

`verify_source()` menerima path original persistent secara langsung. Namun
runner Stage 5 lain memakai `project_path()` yang menolak file di luar root
proyek, termasuk symlink yang resolve keluar. Sebelum workflow end-to-end
dijalankan di container, volume `autoclipper_data` yang sama perlu terlihat
di bawah root proyek Stage 5 (misalnya mount tambahan ke `/app/data` sehingga
original ada di `/app/data/source/originals/...`) dan identitas inode/hash
alias harus diverifikasi. Ini mount kedua ke volume yang sama, bukan copy atau
download baru. Mount, runner, API, n8n, dan database belum diubah pada tahap
ini. Image backend Stage 6.3.1 juga belum berisi seluruh runtime Stage 5;
deployment/eksekusi role tetap tahap berikutnya.

## Verifikasi

- `test_intake_adapter_stage632.py`: **8 lulus**. Integration test membuat MP4
  sintetis kecil dengan FFmpeg di direktori sementara, lalu menjalankan FFprobe
  dan validator Stage 5 sesungguhnya. Kasus invalid mencakup identity/state,
  path, ukuran, SHA, durasi, resolusi, FPS, serta canonical analysis yang tidak
  cocok. Kasus duplicate memeriksa output deterministik dan satu file original.
- Regresi Stage 5 `test_adaptive_director_input_v03.py`: **39 lulus**.
- Regresi Stage 5 `test_stage54_planning_integration.py`: **32 lulus**.
- Regresi backend Stage 6.3.1 `test_media_worker_stage631.py`: **7 lulus**.
- `ruff check scripts tests backend`: **lulus**.

Semua uji bersifat lokal/offline. MP4 sintetis adalah fixture teknis, bukan
media produksi atau bukti editorial. Tidak ada akses PostgreSQL/TikTok live,
perubahan VPS/n8n/database, deployment, commit, atau push.
