# MANDALA AUTO — Stage 5.5 Real-content Showcase Preview POC

## 1. IMPLEMENTATION SUMMARY

Satu kandidat MP4 real-content berhasil dibuat untuk inspeksi lokal/private. Implementasi memakai encoder Stage 5.5 existing, mode REAL_CONTENT_PREVIEW, plan manual terpisah, dan validasi independen. Technical success tidak sama dengan kualitas editorial atau approval production/publish. Stage 5.6 tidak dimulai; Pak Fuad tidak dirender.

## 2. FILES CREATED / MODIFIED

File existing yang dimodifikasi hanya [renderer_core_v01.py](/home/kentung/projects/mandala-autoclipper-ai/scripts/renderer_core_v01.py:332): fade dibatasi ke output operation window; cabang admission preview dan metadata preview ditambahkan di baris 364. Fungsi production_admission pada render_video_v01.py tidak berubah.

Baru: [render_showcase_preview_v01.py](/home/kentung/projects/mandala-autoclipper-ai/scripts/render_showcase_preview_v01.py:47), [preview authorization schema](/home/kentung/projects/mandala-autoclipper-ai/src/schemas/preview-authorization.v0.1.schema.json), [preview manifest schema](/home/kentung/projects/mandala-autoclipper-ai/src/schemas/render-preview-manifest.v0.1.schema.json), [54 offline tests](/home/kentung/projects/mandala-autoclipper-ai/tests/test_showcase_preview_v01.py), [workflow](/home/kentung/projects/mandala-autoclipper-ai/docs/real-content-showcase-preview-v01.md), laporan ini, dan artefak baru di real-preview-audit.v01 serta real-content-showcase.v01.

Bundle final memuat preview.mp4, preview-plan.v03.json, preview-authorization.v01.json, render-manifest.v01.json, validation-report.v01.json, preview-review-notes.md, execution-spec.v01.json, evidence-packet.v03.json, timeline.v01.json dan preview-contact.png. Input final prepared.v06; capability receipt capabilities.v05.json. Versi development disimpan sebagai history/superseded, bukan entry point final.

## 3. PREVIEW PLAN & EDITORIAL RATIONALE

[Plan manual final](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/preview-plan.v03.json). Kandidat rentang visual dipertahankan dari referensi proposal lama, bukan inference AI baru.

| Source seconds | Output seconds | Rationale manual |
|---|---|---|
| 0.6–4.1 | 0–3.5 | Frontal vehicle, melewati opening paling gelap |
| 14.5–17.5 | 3.5–6.5 | Perspektif wide showroom |
| 21.2–25.1 | 6.5–10.4 | Close view dan existing return transition, penutup pada showroom |

Speed 1; freeze/overlap 0; cut/concat. Departure tercatat: sync_basis=none menggantikan onset sync; prose-only color grade dihilangkan; gain -8 dB dan fade-in/out 100 ms per bagian audio ditentukan eksplisit. Tidak ada subtitle, CTA, fakta produk, musik eksternal atau flash tambahan. Source effects dalam rentang yang dipilih tetap ada.

Contact sheet sumber memperlihatkan gambar masih ada setelah 25.1 s, sehingga klaim canonical mengenai awal total black tidak dianggap fakta. Out-point 25.1 adalah pilihan editorial manual. Identifikasi model kendaraan, ketiadaan conversational speech dan interpretasi canonical lainnya tetap model-derived/unverified. Stage 5C events tetap signal candidates; timing plan approximate/signal_estimated, bukan editorial frame-verified.

## 4. ORIGINAL BLOCKED PLAN PROTECTION

[Original live plan](/home/kentung/projects/mandala-autoclipper-ai/data/analyses/director/adaptive-v03/showcase.live.v01/editing-plan.v03.json) dan report tetap byte-identical, BLOCKED/onset_sync_without_onset. SHA plan `afe679fb40c21ac3cd6ccbc5be5d75948c56209fc112cc986089dd08c273e86f`; SHA report `494ee2ab1d6d46748f57dfd3392ebc3cd8024dc0ee9de2c6c78002757e2394df`.

Fingerprint keduanya dipin; original plan atau perubahan byte pada plan/report ditolak. Tidak ada blocking finding dihapus, generic intensity event diubah menjadi onset, atau render_approved dinaikkan. Plan baru berstatus NEEDS_REVIEW, structural_validity=true, blocking_findings=[], 11 review findings. render_gate_passed dan seluruh production/publish approvals tetap false.

## 5. PREVIEW AUTHORIZATION BOUNDARY

[Authorization final](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/preview-authorization.v01.json); checks di [validate_context](/home/kentung/projects/mandala-autoclipper-ai/scripts/render_showcase_preview_v01.py:116) dan [admit](/home/kentung/projects/mandala-autoclipper-ai/scripts/render_showcase_preview_v01.py:200). Permit mengikat satu SHA/path sumber, exact manual plan, packet, spec, capability file, current code/schema receipts dan direktori preview. Path traversal, symlink, arbitrary source/plan/assets, unsupported operations, promotion approvals dan blocker ditolak.

Satu kandidat selesai diizinkan. Dua encoding sebelumnya gagal tanpa bundle final: allocation error HEVC direproduksi read-only pada limit 1536 MiB; limit 3072 MiB menghasilkan 312 frame lengkap. Pemulihan kedua berhenti 92.056 s setelah reservasi, mengarah ke timeout 90 s; penyebab internalnya tidak direkam sehingga diagnosis timeout saat itu adalah inferensi. Percobaan terakhir memakai timeout maksimum existing schema 180 s, RAM 3072 MiB, source dan creative plan sama, dan berhasil.

Ketiga reservation receipts serta kedua failure receipts dipertahankan; tidak ada marker dihapus/ditimpa. Pemulihan membutuhkan chain fingerprint failure/spec/authorization, tidak boleh ada completed preview, dan tidak memberi izin produksi. Guard menolak percobaan keempat atau kandidat selesai kedua. Tidak ada force/ignore-validation/approval override CLI.

Lihat [failure 1](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-preview-audit.v01/render-failure.v01.json), [failure 2](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-preview-audit.v01/render-failure.v02.json) dan [diagnostic assessment](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-preview-audit.v01/read-only-filter-assessment.v01.json). Null-sink diagnosis tidak meng-encode atau membuat MP4. Exit zero pada diagnostic awal tidak diterima sebagai replay PASS karena ada error allocation; replay berikutnya memerlukan count 312, progress=end dan tanpa error.

## 6. VERIFIED RENDER OPERATIONS

Trim, concat, audio_gain dan audio_fade memakai [current capability receipt](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-preview-audit.v01/capabilities.v05.json), direplay dari fixture audio/basic/fullhd pada current renderer code dan environment. Receipt ini memiliki 7 controlled capabilities verified; 4 dipakai preview. Historical Stage 5.5 receipts tidak diubah atau dipromosikan menjadi receipt kode terbaru.

Bug afade di tengah timeline diperbaiki melalui enable window, agar tidak membisukan audio di luar operation window. [Synthetic PCM middle-fade test](/home/kentung/projects/mandala-autoclipper-ai/tests/test_showcase_preview_v01.py:165) menguji attenuation lokal serta keberadaan audio sebelum/sesudahnya. Geometry 1080×1920 source/output sama; scale/pad mempertahankan aspect ratio tanpa bar tambahan/stretch.

## 7. ACTUAL SHOWCASE MP4 OUTPUT

[Preview MP4](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/preview.mp4)

Absolute path: `/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/preview.mp4`. Ukuran **5,409,645 bytes (5.159 MiB)**. Durasi actual/expected **10.400/10.400 s**. SHA-256 `338832fd9437d1195e52f2810536858f91a65cbef2f0caecd42cd33d06b89cf1`. Satu final candidate ditemukan; tidak ada bundle final dari dua encoding gagal.

[Contact sheet](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/preview-contact.png) sudah diperiksa secara visual: kendaraan dan showroom asli, framing portrait, exposure berubah pada opening dan existing source transition tetap terlihat. Ini tidak menggantikan playback/listening review.

## 8. VIDEO METADATA & AUDIO CHECKS

[Manifest final](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/render-manifest.v01.json): H.264/yuv420p, 1080×1920, 30 FPS, AAC stereo 48 kHz; video/audio masing-masing 10.4 s. Full decode PASS, continuous PTS PASS, 312 video frames dan 488 audio frames. Duration tolerance 0.088 s; actual error 0.

Scan semua 312 decoded CFR frames pada luma 54×96: near-black timestamps=[], maximum fraction pixel gelap 0.499421; threshold >=98% pixel <26/255. Ini bukan defect scan semantik/full resolution. Peak mono PCM **0.813258**, RMS **0.249880**, di bawah clipping-risk guard 0.999.

[Audio splice assessment](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-preview-audit.v01/audio-splice-assessment.v01.json): mid-shot RMS gain sekitar -8.10/-8.04/-8.09 dB. RMS neighborhood splice 100 ms pada 3.5/6.5 s adalah 0.051249/0.086100. Fade mengurangi transien dan memberi dip singkat; kontinuitas frase/vokal lagu tetap UNVERIFIED_PENDING_LISTENING_REVIEW. Tidak ada klaim beat sync atau rights.

Encoding final **112.329 s**; CPU child user/system 51.763/7.544 s. Cumulative maximum child RSS 1,364,376 KiB (~1.301 GiB), bukan isolated per-render RSS. Batas: 2 codec threads, 1 filter thread, 3072 MiB address space, 180 s subprocess/182 s CPU, 64 MiB per-file/per-allocation, 16 MiB reserve + output ceiling, 600 s CLI. Temporary files cleaned, bounded stdout/diagnostics, child termination/reaping dan exclusive atomic file creation digunakan.

## 9. TEST RESULTS

New preview suite: **54 passed, 0 failed, 0 errors, 0 skipped**, standalone 16.065 s; rerun dalam final affected suites juga PASS. [Tests](/home/kentung/projects/mandala-autoclipper-ai/tests/test_showcase_preview_v01.py) mencakup allowlist/hash, cross-source, original blocked, unsupported/timing/spec/report tamper, production/publish isolation, no overwrite, traversal/symlink/work path, current capability/code receipts, bounded failure recovery, completed candidate refusal, input directory entry point, actual synthetic middle audio fades dan black scan.

## 10. REGRESSION RESULTS

Hasil terbaru per-suite (tanpa double-count rerun):

| Suite | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| test_adaptive_av_evidence_v01 | 78 | 0 | 0 | 0 |
| test_adaptive_director_input_v03 | 39 | 0 | 0 | 0 |
| test_adaptive_director_v03 | 46 | 0 | 0 | 0 |
| test_adaptive_editing_plan_v03 | 73 | 0 | 0 | 0 |
| test_remote_speech_evidence_v01 | 33 | 0 | 0 | 0 |
| test_renderer_ffmpeg_v01 | 52 | 0 | 0 | 0 |
| test_renderer_v01 | 93 | 0 | 0 | 0 |
| test_showcase_preview_v01 | 54 | 0 | 0 | 0 |
| test_speech_evidence_generation_v01 | 85 | 0 | 0 | 0 |
| test_speech_evidence_provenance | 51 | 0 | 0 | 0 |
| test_speech_provenance_remediation | 32 | 0 | 0 | 0 |
| test_stage54_planning_integration | 32 | 0 | 0 | 0 |
| Python unique total | **668** | **0** | **0** | **0** |
| OpenClaw plugin offline | **7** | **0** | **0** | **0** |
| Combined unique | **675** | **0** | **0** | **0** |

Full discovery v04: 661/661, wrapper 293.507 s (unittest 290.154 s), termasuk versi preview 47 tests. Setelah perubahan scoped recovery, semua affected suites direpeat: 272/272, wrapper 142.053 s (unittest 138.052 s), terdiri atas latest preview 54, renderer 93+52 dan validator 73. Suite existing lainnya byte-identical terhadap full run. Total latest di atas mengganti hasil preview lama, bukan menjumlahkan duplicate reruns. Plugin 7/7, 628.614402 ms. Universal validator self-test PASS; invalid timestamp ditolak.

[Aggregated result](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-preview-audit.v01/regression-summary.v01.json). Development full v02 diinterupsi untuk perbaikan fade dan bukan final PASS. Kegagalan encoding real yang disebut bagian 5 tidak disamarkan sebagai unit test success.

## 11. SOURCE & ARTIFACT INTEGRITY

[Final integrity](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-preview-audit.v01/integrity-results.v02.json): baseline 279 files; **278 unchanged, 1 authorized existing change (renderer_core_v01.py), 0 missing**. Original MP4, sidecars, canonical, speech, AV, Director plans/input fixtures, existing renderer receipts dan existing tests/docs tetap identik. All final bundle schemas dan digest bindings PASS; frozen final code unchanged. Satu completed candidate; temporary preview/diagnostic work cleaned.

Showcase SHA `58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f`. Pak Fuad SHA `000c759ac57ff4c2bfbdfd3e8d678f46d2160ea8855b4ca9bb343ce26c8671f3`. Original source/canonical/speech/plan approvals tetap false. Tidak ada secret .env.asr dibaca/dilog, ASR/Gemini/9Router inference, dependency install, model download, VPS/n8n/Cloudinary modification, upload, publish, commit atau push.

## 12. REMAINING RISKS

Song/vocal frase dapat terpotong pada 3.5 dan 6.5 s; belum ada listening review. Exposure opening, hook strength, existing transition, repetisi framing dan pacing masih memerlukan review manusia. Canonical semantics dan candidate timings belum verified. Publication/music rights unknown. Local hashes unsigned membuktikan konsistensi, bukan independent authentication. Threshold dark scan tidak mendeteksi semua defect.

High-resolution HEVC/source fanout/encoding membutuhkan resource lebih besar dari fixture kecil; keberhasilan pada host ini bukan jaminan VPS. Address-space cap 3072 MiB berbeda dari RSS fisik. Encoding 112 s menandakan peluang optimasi decoder/input buffering selanjutnya, bukan alasan menonaktifkan limit. Failed-state recovery dibatasi hanya sumber/plan/task ini.

## 13. EXACT COMMAND TO OPEN THE VIDEO

```sh
xdg-open "/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/preview.mp4"
nemo "/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01"
```

xdg-open dan nemo tersedia lokal. Alternatif directory: `xdg-open "/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01"`. Open-in-Codex telah diminta (tool returned queued); path di atas selalu dapat digunakan langsung.

## 14. RECOMMENDATION FOR MANUAL VIDEO REVIEW

Putar video dengan audio, periksa pembuka/exposure, framing kendaraan, transisi existing sekitar output 7.4 s, penutup, serta sambungan lagu pada 3.5/6.5 s. [Review notes](/home/kentung/projects/mandala-autoclipper-ai/data/render-tests/stage55/real-content-showcase.v01/preview-review-notes.md) mempertahankan review pending. Metadata dan signal PASS tidak menyatakan edit berkualitas excellent. Preview hanya private; production/publish tetap false. Stage 5.6 memerlukan instruksi terpisah dan tidak dimulai.

**REAL-CONTENT SHOWCASE PREVIEW COMPLETE — WAITING FOR CHATGPT AUDIT**
