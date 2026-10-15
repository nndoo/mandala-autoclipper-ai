# Stage 5.6 Remediation — Live Multimodal Reviewer

Status: **implementasi dan uji live selesai; menunggu audit ChatGPT**.
Scope berhenti pada Stage 5.6. Tidak menjalankan Stage 5.7.

## 1. ROOT CAUSE ANALYSIS

Tiga masalah terkonfirmasi selama remediasi:

1. Runner sebelumnya membuang stderr ke DEVNULL, sehingga dua kegagalan historis tidak memiliki diagnostik yang cukup untuk menentukan penyebab masing-masing. Penyebab historis tersebut tidak dapat dibuktikan secara retrospektif hanya dari exit code.
2. Reproduksi dengan diagnostik baru mengembalikan `QA request outside project`, exit code 1, sebelum plugin mengirim request upstream. File request sebenarnya berada dalam root proyek. Guard sebelumnya mengambil root dari lokasi modul melalui `import.meta.url`; boundary ini tidak cocok pada pemuatan plugin dalam CLI nyata. Setelah root eksplisit dari caller digunakan, request berhasil mencapai provider dan memperoleh respons. Detail bagaimana loader mengubah lokasi modul tetap hipotesis; tidak ada trace loader yang membuktikan transformasi persisnya. Tes relokasi modul membuktikan guard baru tidak bergantung pada lokasi modul.
3. Respons pertama setelah perbaikan path lolos parsing JSON tetapi gagal validasi semantik. Model menggunakan `signal_measurement`/`deterministic_validation`, ID evidence berupa nama field/JSON path yang tidak terdaftar, factual_safety PASS, dan issue observasi tanpa referensi media terlampir. Kontrak schema yang dikirim sebelumnya masih mengizinkan provenance umum milik laporan teknis/manusia, sedangkan validator Reviewer melarangnya. Kontrak model sekarang mencerminkan larangan yang telah ada dan mengikat ID evidence ke ledger.

Binding provider/model telah diperbaiki sebelum remediasi ini. Binding sekarang teruji live, tetapi tidak diklaim sebagai satu-satunya penyebab dua kegagalan lama.

Urutan bukti baru:

| Run | Titik berhenti / hasil | Calls CLI |
|---|---|---:|
| `showcase.remediation.diagnostic.v01` | Guard path plugin; tidak mencapai pengiriman upstream | 1 |
| `showcase.remediation.live.v01` | Respons diterima, ditolak validator semantik; source tidak dipanggil | 1 |
| `showcase.remediation.live.v02` | Dua respons tervalidasi, laporan gabungan tervalidasi | 2 |

Total remediasi: **4 invocation CLI**, terdiri dari satu kegagalan sebelum transport dan tiga invocation yang memperoleh respons upstream. Tidak ada retry otomatis. Dua invocation historis berada di luar angka ini. Receipt tidak berisi bukti tagihan provider, sehingga jumlah transaksi/kredit aktual tidak diklaim.

Bukti: [diagnostic receipt](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/showcase.remediation.diagnostic.v01/review-generation-provenance.v01.json), [rejection audit](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/remediation-audit.v01/response-rejection.v01.json), [final generation receipt](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/showcase.remediation.live.v02/review-generation-provenance.v01.json).

## 2. FILES MODIFIED

Enam file baseline diubah:

- [Reviewer runner](/home/kentung/projects/mandala-autoclipper-ai/scripts/review_video_quality_v01.py:27): diagnostik bounded, cwd/root eksplisit, kontrak model sesuai validator.
- [QA prompt bridge](/home/kentung/projects/mandala-autoclipper-ai/openclaw/plugins/mandala-9router-video/src/qa-prompt.ts:6): root dari trusted caller; guard path/hash/symlink tetap berlaku.
- [Compiled bridge](/home/kentung/projects/mandala-autoclipper-ai/openclaw/plugins/mandala-9router-video/dist/qa-prompt.js): hasil build TypeScript existing.
- [Independent Reviewer prompt](/home/kentung/projects/mandala-autoclipper-ai/openclaw/prompts/video-quality-reviewer-v01.md:44): instruksi field provenance, ID evidence, fakta/hak, dan media role diperjelas.
- [QA tests](/home/kentung/projects/mandala-autoclipper-ai/tests/test_video_quality_v01.py:156): mock dipindah ke helper baru, assertion root, dua tes kontrak model. Assertion keselamatan lama dipertahankan.
- [Plugin QA tests](/home/kentung/projects/mandala-autoclipper-ai/openclaw/plugins/mandala-9router-video/tests/quality-mode.test.mjs): tiga tes root/relokasi dan assertion payload identik byte demi byte.

File baru: [14 tes diagnostik](/home/kentung/projects/mandala-autoclipper-ai/tests/test_video_quality_remediation_v01.py), dokumen ini, audit/proof/log baru pada `data/qa/stage56/remediation-audit.v01`, tiga bundle prepared baru, satu bundle diagnostik, serta dua bundle live versioned. Bundle live pertama menyimpan respons yang ditolak; bundle live kedua menyimpan respons tervalidasi. Tidak ada artefak historis yang ditimpa.

Schema JSON bersama, transport 9Router, Universal Analyst, runner Director, renderer, agent registration, dan konfigurasi provider tidak diubah.

## 3. FIXES IMPLEMENTED

Helper [capture_inference](/home/kentung/projects/mandala-autoclipper-ai/scripts/review_video_quality_v01.py:47) membaca stdout dan stderr secara bersamaan. Batas stdout 131.072 byte, stderr 16.384 byte, timeout CLI 180 detik. Ketika limit/timeout tercapai, process group dihentikan dan proses anak langsung di-wait/reap. Tidak menyimpan stderr mentah: receipt hanya menyimpan klasifikasi allowlist, exit code, jumlah byte, durasi, dan fase kegagalan. Stdout harus UTF-8 dan lulus guard credential sebelum disimpan sebagai respons untrusted. Stderr tidak mencemari parser JSON.

Caller mengikat `MANDALA_VIDEO_QA_PROJECT_ROOT` ke root proyek yang sudah digunakan utilitas source/path verification. Isi request tidak dapat memilih boundary ini. Request SHA, media SHA/byte count, prompt SHA, ukuran, traversal, symlink, dan path secret tetap diperiksa.

Kontrak model pada [make_request](/home/kentung/projects/mandala-autoclipper-ai/scripts/review_video_quality_v01.py:121) mempersempit provenance menjadi `model_unverified`/`unavailable`, memberikan enum ID evidence ledger yang tepat, melarang factual_safety PASS dan capability certification. Untuk original_source, kontrak mengecualikan `media.output` serta `audio.splice.*`. Ini menguatkan instruksi input; tidak memperbaiki atau mengubah respons model setelah diterima dan tidak melonggarkan validator.

Parsing tetap hanya menerima envelope OpenClaw yang dikenal dan JSON/fence JSON yang ketat. Validasi schema, media/packet hash, role, timestamp, provenance, audio access, rekomendasi, dan approval tetap berjalan sebelum hasil digabungkan.

## 4. OPENCLAW/9ROUTER COMPATIBILITY

Runtime yang benar diverifikasi: Node **v24.21.0**, OpenClaw **2026.9.9 (bcfc888)** pada `/home/kentung/.local/share/mandala-openclaw-runtime`.

Command invocation:

```text
/home/kentung/.local/share/mandala-openclaw-runtime/bin/openclaw infer video describe
  --agent mandala-video-analyst
  --model custom-ipt02mbjindt5ldise8woehy-43-129-33-7-sslip-io/openclaw
  --file <absolute verified MP4>
  --json
```

Agent existing hanya menjadi jalur auth/provider; prompt Reviewer independen tetap diikat ke request QA. Tidak mendaftarkan agent baru atau mengubah default model. Provider yang dikirim tetap existing, model alias tetap `openclaw`. Envelope live melaporkan **`gemini-3.8-flash-n`** pada kedua respons akhir; ini identitas yang dilaporkan upstream/CLI, bukan audit independen implementasi model backend.

Transport existing menggunakan endpoint `/chat/completions`, `stream=false`, teks prompt + `image_url` berisi `data:video/mp4;base64,...`. Ini kompatibilitas khusus proxy existing, bukan klaim semua endpoint OpenAI-compatible menerima video melalui image_url. Ekstraksi `choices[0].message.content` dan envelope OpenClaw berhasil pada uji nyata.

Limit transport tetap: MP4 maksimum 20 MiB, upstream response 2 MiB, abort/timeout bounded existing, tanpa retry otomatis. Node heap 256 MiB dipertahankan; batas heap ini bukan batas RSS total proses. Tidak ada service, instalasi dependency, atau upgrade runtime.

## 5. AUDIO/VIDEO INPUT CAPABILITY

Request menyertakan MP4 lengkap dengan track audio/video yang telah diverifikasi FFprobe, bukan hanya metadata, transcript, atau contact sheet. Guard plugin mengikat buffer ke source hash/byte count. Tes transport memeriksa bahwa decode payload base64 identik dengan buffer input.

Kedua respons akhir menyatakan `video_examined=true`, `audio_examined=true`, `audio_access=model_self_reported_available`. Laporan mencatat `video_observation=MODEL_SELF_REPORTED_UNVERIFIED` dan `audio_listening=MODEL_SELF_REPORTED_UNVERIFIED`. Tidak mengubahnya menjadi fakta verified.

Pengiriman payload dari sisi client telah teruji. Tidak tersedia telemetry backend yang membuktikan bagaimana proxy/model mendekode track audio/video, serta tidak ada uji kemampuan audio independen yang terpisah dari metadata/packet. Temuan musical phrase dan ghosting tetap interpretasi model. Waktu temuan approximate. Observasi dua video dilakukan terpisah, bukan perbandingan bersama dalam satu context.

## 6. OFFLINE TEST RESULTS

Run akhir QA + diagnostik: **150 passed / 0 failed / 0 errored / 0 skipped** (47,086 detik): 136 QA, termasuk dua tes baru kontrak, dan 14 tes diagnostik subprocess. Coverage meliputi model/provider/root binding, audio/video observation claims, parser/schema invalid, source/output contamination, provenance promotion, credential guard, output limits, timeout, process-group termination, tidak ada network pada mock, serta preservation human findings dan approval gates.

Plugin: **23 passed / 0 failed / 0 errored / 0 skipped**, cancelled 0: tujuh legacy/universal existing dan 16 QA. Coverage tambahan: root hilang/relatif, relokasi loader, symlink/traversal, exact media/prompt binding, payload byte equality. TypeScript build existing **exit 0**.

Logs: [QA + diagnostics](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/remediation-audit.v01/qa-and-diagnostics-regression.v03.txt), [plugin](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/remediation-audit.v01/plugin-regression.v03.txt).

## 7. REGRESSION RESULTS

| Suite run akhir | Passed | Failed | Errored | Skipped |
|---|---:|---:|---:|---:|
| Stage 5.6 QA | 136 | 0 | 0 | 0 |
| Diagnostik baru | 14 | 0 | 0 | 0 |
| Plugin legacy/universal + QA | 23 | 0 | 0 | 0 |
| Stage 5.4 Creative Director | 46 | 0 | 0 | 0 |
| Stage 5.4 Plan Validator | 73 | 0 | 0 | 0 |
| Stage 5.4 Planning Integration | 32 | 0 | 0 | 0 |
| **Total relevan** | **324** | **0** | **0** | **0** |

Tidak menghitung ulang run perantara. Angka 822 pada laporan Stage 5.6 sebelumnya adalah run historis; seluruh 822 tes tersebut tidak direrun dalam remediasi ini. Suite regresi relevan yang diwajibkan handoff dijalankan; tidak ada suite dalam tabel yang dilewatkan. Test helper `test_adaptive_director_execution_v03.py` memiliki nol test case mandiri.

Bukti counts dan hash log: [test-results final](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/remediation-audit.v01/test-results.v02.json).

Validasi live tambahan selesai: request sama dengan generator/current code receipts; schema model-facing dan validator semantik keduanya lulus; raw response yang diparse sama dengan response JSON tersimpan; hashes response/report diperiksa. [Live validation proof](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/remediation-audit.v01/live-validation.v01.json).

## 8. SOURCE AND ARTIFACT INTEGRITY

Baseline berisi **729 file**. Recheck setelah live dan perubahan assertion terakhir: **723 identik**, **6 perubahan kode/tes yang diharapkan**, **0 hilang**, **0 perubahan tak terduga**.

SHA-256 source Showcase tetap:

`58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f`

SHA-256 preview tetap:

`338832fd9437d1195e52f2810536858f91a65cbef2f0caecd42cd33d06b89cf1`

Baseline membuktikan original media, canonical analyses, speech artifacts, Director plans, artefak render Stage 5.5, dan laporan/prepared/receipt QA historis tetap identik. File secret tidak dibaca atau dimasukkan baseline. Tidak membaca `.env.asr`, mengubah konfigurasi STT, rerun ASR, rerender preview, mengakses VPS/n8n/Cloudinary, install/download, commit/push, deploy, atau publish.

Final report mempertahankan **10 issue awal**, termasuk **7 human feedback** tanpa perubahan, lalu menambahkan dua issue output `model_unverified` (audio 3,3–3,7 detik dan visual 6,7–7,3 detik). Dua issue source disimpan sebagai context source, bukan verdict output. Interpretasi ghosting tidak membuktikan renderer defect; efek bisa sudah terdapat dalam source. Rekomendasi model tidak dieksekusi.

Status akhir:

```text
technical_qa_status = NEEDS_REVIEW
ai_editorial_status = NEEDS_REVIEW
human_review_status = REVISE
overall_decision = REVISE
production_eligible = false
publishing_eligible = false
render_approved = false
publish_approved = false
```

AI ending PASS tidak menghapus human ending issue. [Final quality report](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/showcase.remediation.live.v02/quality-report.v01.json), [integrity final](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/remediation-audit.v01/integrity.v02.json).

## 9. REMAINING BLOCKERS

Tidak ada blocker invocation/parsing/validasi yang tersisa untuk dua sampel live ini. Dua respons benar-benar dihasilkan lewat provider, bukan mock. Hal tersebut tidak menjamin setiap inference berikutnya mengikuti kontrak; respons future yang invalid tetap ditolak, tanpa retry otomatis.

Masih perlu review editorial/manusia atas musik, ghosting/efek source, ending dan factual/rights claims. Tidak ada sertifikasi independen audio listening/video decoding backend. Model-reported identity dan biaya/kredit belum diaudit dari sisi provider. Root relocation adalah mekanisme yang diuji secara offline; transformasi loader tepat yang menyebabkan boundary lama salah tetap belum ditrace.

Overall REVISE dan semua gate false tetap mencegah pemakaian hasil sebagai approval produksi/publishing. Implementasi ini memperbaiki Reviewer, bukan memperbaiki kualitas video atau melakukan autonomous revision.

## 10. EXACT LIVE TEST APPROVAL REQUEST — AUTHORIZATION ALREADY GIVEN

Instruksi user terbaru, “jika butuh pemanggilan api lakukan saja tidak perlu tanya/ minta ijin”, telah memberi persetujuan eksplisit baru untuk request yang diperlukan. Karena itu tidak ada permintaan persetujuan tambahan dan tidak ada live test yang menunggu izin.

Pair akhir menggunakan [prepared v03](/home/kentung/projects/mandala-autoclipper-ai/data/qa/stage56/showcase.remediation.prepared.v03/review-requests-provenance.v01.json), provider existing dan alias model di bagian 4. Media:

- Preview: **10,4 detik / 5.409.645 byte**, satu call.
- Original Showcase: **26,533 detik / 11.164.794 byte**, satu call.

Keduanya menawarkan audio/video MP4 lengkap; kemampuan mendengar hanya model self-report, belum certified. Maksimum dua calls per bundle, tanpa retry otomatis, timeout CLI 180 detik per call. Payload base64 media sekitar 7,21 MB dan 14,89 MB ditambah prompt/JSON. Biaya/kredit aktual tidak tersedia. Dua calls pair akhir sukses tervalidasi; tambahan diagnosis/perbaikan manual dan total scope dijelaskan pada bagian 1. Tidak ada perubahan model secara diam-diam, ASR, rendering, publishing, atau Stage 5.7.

**STAGE 5.6 REMEDIATION COMPLETE — WAITING FOR CHATGPT AUDIT**
