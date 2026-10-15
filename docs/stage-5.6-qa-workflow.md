# Stage 5.6 — Independent Video Quality Reviewer V0.1

QA memeriksa MP4 aktual dan receipt render. QA tidak mengubah plan, menjalankan revisi, merender preview ulang, atau memberi izin produksi/publikasi. Jenis manifest yang didukung mengikuti renderer saat ini: TEST_ONLY dan REAL_CONTENT_PREVIEW. Manifest produksi yang belum memiliki kontrak otorisasi tetap ditolak.

## Arsitektur dan kontrak

`scripts/video_quality_qa_v01.py` menggunakan source verification, bounded subprocess, FFprobe, PCM decoding, timeline compiler, capability receipt replay, path guard dan atomic exclusive writer existing. Manifest/plan/spec/timeline/SHA/source metadata/canonical evidence diperiksa ulang. Mode TEST_ONLY memerlukan fixture identity tertutup. Mode preview memerlukan receipt izin preview, packet sumber, validasi plan dan capability receipt sesuai kode existing.

Empat kontrak `src/schemas/video-quality-*.v0.1.schema.json` memisahkan report, feedback manusia, request AI dan response AI. Root/issue/dimension/recommendation memiliki field ketat; detail teknis memuat objek metode versi 0.1 dan dibatasi validator semantik serta batas 2 MiB. Schema struktural saja bukan bukti autentikasi. Consumers harus memeriksa generation receipt, SHA, code receipts, media binding dan validator semantik.

Output teknis: `quality-report.v01.json`, `technical-qa.v01.json`, `qa-packet.v01.json`, `qa-generation-provenance.v01.json` (marker terakhir). Tidak ada overwrite. Versi QA terdahulu tetap disimpan sebagai rekaman pengembangan; gunakan versi yang code receipts-nya cocok. Untuk acceptance saat ini gunakan `data/qa/stage56/showcase.v05`.

## Analisis teknis

Video: full decode dan kontinuitas PTS memakai verifier renderer. Analisis visual terpisah mengambil frame decoded dengan PTS asli, stride ceil(FPS/4), RGB 64×64. Pada 30 FPS sampling aktual 3,75 FPS, gap 0,266667 s. Near-black (98% piksel luma <26), kesamaan frame, histogram/centered differences dan perubahan brightness menghasilkan kandidat, bukan editorial boundary/defect yang otomatis verified. Freeze yang dinyatakan plan dikecualikan; static shot/lighting/flash/hard cut/reuse perlu konteks. Tidak ada OCR atau sertifikasi crop/raster pixel-perfect.

Audio: mono float32 48 kHz dengan fingerprint PCM; RMS/peak per 20 ms; FFT dengan Hann window 80 ms dan 24 band log, jarak cosine/positive spectral flux, delta antar sampel. Generic events dan setiap join timeline diperiksa. Window keluar/masuk ±250 ms mengecualikan pusat ±50 ms untuk membandingkan level/spektrum; pusat 100 ms memeriksa dip. Source out/in point, source time jump, fade, overlap dan source RMS dicatat. Quiet RMS <0,0001 selama ≥0,2 s dibandingkan dengan deklarasi silent/fade/freeze, gain/duck kuat dan mapped source quiet. Ending aktif menjadi kandidat review, tidak membuktikan frasa terpotong. Peak ≥0,999 adalah risiko clipping, bukan true-peak certification.

Fade, RMS hampir sama dan peak aman tidak membuktikan kontinuitas lagu/vokal/kalimat. Noncontiguous source audio tetap actionable meskipun fade ada. Speech alignment yang tidak eligible tetap tidak diverifikasi. Audio yang tidak ada menghasilkan NOT_APPLICABLE; tidak dibuat beat grid atau transkripsi baru.

Caption: periksa deklarasi text geometry dan source/output timing menggunakan utility renderer existing. Raster visibility, kata/transkrip dan inherited on-screen text tidak OCR-verified. Tanpa caption deklaratif, status NOT_APPLICABLE tidak berarti model boleh mengarang subtitle yang kurang.

## Reviewer multimodal

`scripts/review_video_quality_v01.py` prepare/review memakai isolated OpenClaw 2026.9.9 dan plugin existing. Logical Reviewer prompt/AGENTS terpisah dari Director; routing agent `mandala-video-analyst` digunakan untuk auth/provider existing tanpa registrasi/mutasi runtime agent baru. Mode plugin `quality_qa_v01` menggantikan prompt Analyst hanya untuk invocation tersebut; legacy dan universal_v02 tetap lulus regresi.

CLI `infer video describe` menerima satu video, tanpa `--prompt`. Bridge `qa-prompt.ts` membaca request terikat SHA melalui env, menolak escape/symlink/secret path, memverifikasi MP4 bytes/SHA dan prompt SHA. Plugin menawarkan MP4 penuh lewat jalur kompatibilitas `image_url` data URI existing. Dua panggilan: edited_output dan original_source. Source-only review memberi konteks sumber, tidak boleh menjadi bukti observasi output. Tidak ada klaim bahwa model melihat kedua video bersama.

Human feedback sengaja tidak masuk prompt/packet AI agar tidak menjadi konfirmasi berulang. Request memuat intent, timeline, canonical context berstatus model/unverified, signal events, media identity dan response schema. Response divalidasi struktur, SHA/role/packet, waktu relatif media, evidence refs, audio/video availability, larangan human confirmation, capability/factual verification dan timing frame_verified. Model findings tetap `model_unverified`. Audio offered bukan audio delivery certification: `model_self_reported_available` tetap klaim model yang belum diverifikasi independen.

Modes `offline_fixture` dan `saved_response_replay` tidak pernah menjadi live PASS. Live hanya setelah explicit approval terpisah dan `--live-approved`. Invocation sekarang mengikat `--model` ke provider/model existing secara eksplisit; perbaikan binding setelah dua attempt gagal belum diuji remote. `--role original_source` membatasi invocation pada review sumber independen, bukan retry output. Response mentah yang lolos batas/credential guard disimpan sebagai untrusted diagnostic; parse/schema failure tidak dipromosikan menjadi evidence. Kegagalan menghasilkan receipt FAILED_NO_RETRY, AI INCOMPLETE, dan tidak memicu retry/call berikut otomatis. Output directory direservasi sebelum call; tidak boleh menimpa atau menggunakan ulang reservation. CLI flag bukan pengganti persetujuan manusia di sesi.

## Status dan handoff

Technical, AI editorial, human dan overall dinilai terpisah. Critical deterministic defect → BLOCKED, human high/medium → REVISE; model revision tidak disembunyikan oleh rata-rata. Tanpa review live lengkap AI tetap INCOMPLETE. Overall REVISE dapat tetap memiliki AI INCOMPLETE. CLI 0 berarti pemeriksaan selesai, bukan persetujuan. Semua `production_eligible`, `publishing_eligible`, `render_approved`, `publish_approved` false.

Issue memuat ID, category/severity, output_range, source_ranges, evidence_refs, origin/detection_method, confidence, human_confirmation, description, possible_cause/cause_confidence, recommendation target/change/required_operation/feasibility/review_required dan timing_precision. Stage 5.7 kelak harus replay integrity, memisahkan source-only context, menjaga temuan manusia, memperoleh bukti/capability untuk operasi baru dan menyiapkan revisi yang tetap memerlukan review. Stage 5.7 belum diimplementasikan.

## Runtime dan batas

FFmpeg/FFprobe: timeout 180 s per proses, prlimit AS 3072 MiB, dua thread, filter thread satu, max allocation 64 MiB, capped stdout sesuai helper, stderr DEVNULL, kill/wait/reap. Source/output duration ≤180 s, ≤1000 sampled frames, ≤10800 decoded PTS, frame stdout ≤12.288.000 byte, PCM stdout dibatasi utility existing, report ≤2 MiB. CLI memiliki deadline total 600 s. Tidak menyimpan dump full-frame atau temporary MP4 QA.

AI: ≤20 MiB MP4 per request, prompt ≤65536 byte, request ≤131072 byte, wrapper response ≤131072 byte, timeout 180 s, group kill/reap, Node heap 256 MiB. Native RSS Node tidak disertifikasi hard-kernel-cap; media/request/response caps membatasi data yang ditangani. Plugin response body existing ≤2 MiB. Tidak ada service baru atau dependencies/model baru.

## Perintah offline

Dari project root, setiap output harus nama baru:

```sh
.venv-av/bin/python scripts/video_quality_qa_v01.py --bundle data/render-tests/stage55/real-content-showcase.v01 --feedback data/qa/stage56/human-feedback.showcase.v01.json --output data/qa/stage56/showcase.vNEW
.venv-av/bin/python scripts/review_video_quality_v01.py prepare --qa-bundle data/qa/stage56/showcase.vNEW --output data/qa/stage56/showcase.prepared.vNEW
.venv-av/bin/python scripts/review_video_quality_v01.py review --prepared data/qa/stage56/showcase.prepared.vNEW --output data/qa/stage56/showcase.mock.vNEW
.venv-av/bin/python -m unittest discover -s tests -p 'test_video_quality_v01.py'
```

Regresi Python existing telah dijalankan terpisah dari 134 tes baru. Plugin dibuild dengan tsc existing dan Node isolated, tanpa npm install. Tidak ada remote request dalam tes offline. Hasil acceptance, live status, SHA dan performance berada pada laporan implementasi dan audit artifacts.
