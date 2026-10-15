# Stage 5.4.6.5B — Laporan implementasi dan validasi final

Catatan setelah laporan awal: pada 12 Oktober 2026 pengguna menyetujui model ASR API dan penghapusan file yang tergantikan. API Pak Fuad berhasil HTTP 200, generation recorded, text unverified/timing unavailable. Runtime lokal, script transkripsi lama dan bundle blocked-model kemudian dihapus. Laporan di bawah merupakan snapshot sebelum perubahan tersebut; kondisi terkini dan cleanup ada di [remote-speech-asr-v01.md](remote-speech-asr-v01.md).

## 1. IMPLEMENTATION SUMMARY

Implementasi Stage 5B selesai untuk seluruh pekerjaan yang dapat dilakukan tanpa model baru. Pipeline reusable, provenance, validator transcript/timing, review terpisah, penanganan showcase, automated tests, dan regresi tersedia. **Real ASR Pak Fuad: BLOCKED_MODEL_NOT_AVAILABLE; belum menjalankan transkripsi dan bukan PASS.** Tidak melanjutkan Stage 5C.

## 2. FILES CREATED / MODIFIED

Semua perubahan merupakan file baru; tidak ada file baseline yang dimodifikasi:

- `scripts/generate_speech_evidence_v01.py`: CLI generate/validate/accept-review, reuse validator/gate, PCM, source-relative timing, quality, receipt dan publication.
- `scripts/speech_asr_worker.py`: worker Faster-Whisper offline dengan preflight model, pembatasan resource dan raw output.
- `tests/test_speech_evidence_generation_v01.py`: 85 tes Stage 5B.
- `docs/speech-evidence-generation-v01.md`: kontrak, cara penggunaan, hash boundaries, resource dan review.
- `docs/stage-5.4.6.5b-implementation-report.md`: laporan ini.

Masing-masing direktori `data/analyses/speech-v01/pak-fuad.v01/` dan `data/analyses/speech-v01/showcase.v01/` berisi tiga file baru: `generation-provenance.v01.json`, `stage5a-provenance.v01.json`, `validation-eligibility.v01.json`. Snapshot integritas/hasil tes disimpan terpisah di `data/analyses/speech-v01/stage5b-integrity-and-tests.v01.json`.

## 3. SPEECH PIPELINE ARCHITECTURE

MP4 → SHA-256/FFprobe/sidecar → canonical schema dan semantic validator → regional speech requirements Stage 5A → speech/context selection → PCM mono 16 kHz s16le → fingerprint → offline model preflight → bounded local Faster-Whisper → raw/draft/timing/review leaves → generation manifest → Stage 5A eligibility/report.

Referensi: `verified_inputs` baris 70, `select_regions` 106, `capture_pcm` 125, `project_transcript` 183, `assess` 245, `generate` 335, `validate_bundle` 462, `accept_review` 571 pada generator. Worker: `offline_limits` 27, `local_model` 47, `execute` 81. Kontradiksi, unknown, uncertain, audio belum diperiksa atau coverage tidak lengkap menghentikan keputusan ASR otomatis dengan `needs_review`. Speech di atas music tetap diproses secara regional.

## 4. GENERATION PROVENANCE RESULTS

Kedua video mempunyai source/audio integrity `verified`. Hash MP4, sidecar/canonical, PCM, stream index, tool versions, generator/worker hashes, parameter, region dan timestamp penilaian tercatat. Manifest meng-hash leaf; report meng-hash manifest; tidak ada hash yang merujuk dirinya sendiri.

Untuk Pak Fuad, worker preflight mencatat Python 3.14.2, Faster-Whisper 1.2.1, CTranslate2 4.8.2 dan NumPy 2.5.3. Model inventory null karena model tidak ditemukan; generation provenance `unavailable`. Showcase tidak memanggil worker; runtime/model null dan provenance generation juga `unavailable`. Provenance `recorded` untuk completed ASR telah diuji melalui mock, bukan dicatat sebagai real generation pada kedua output tersebut.

Kedua bundle lolos read-only integrity validator. Hash bukan bukti kebenaran text, acoustic classification, timing, atau autentikasi receipt secara independen.

## 5. REAL PAK FUAD ASR TEST RESULTS

Sumber asli terverifikasi: 37.3 detik, 576 × 1024, 30 FPS. Stream 0 AAC 44.1 kHz stereo dinormalisasi menjadi PCM mono 16 kHz: 596311 sample, 1192622 byte, 37.2694375 detik. Perbedaan durasi container/decode dicatat melalui batas sample; timestamp ASR tidak disnap.

PCM SHA-256: `9735285baac2a110355a3d0c9b81f2fb697cbd9e8314920667fb1091bcb160d1`. Sesuai fingerprint yang sudah diketahui. Semua empat region speech canonical tercakup; extraction context digabung menjadi satu region.

Preflight sekali pada pipeline sumber asli menghasilkan **BLOCKED_MODEL_NOT_AVAILABLE** untuk model `small`. Pencarian read-only mencakup cache HF/config, `.cache`, `.local/share`, `.huggingface`, direktori model/proyek, `/opt`, `/mnt`, cache lokal root/var dan referensi script/config ASR lama. Tidak ditemukan model Faster-Whisper lengkap. Tidak ada download, install, model substitution atau ASR rerun legacy.

Pertukaran “2 hari sekali ya?” / “Iya, sangat terjaga, Pak.” belum dapat dinilai recognition maupun batas waktunya. Kalimat tersebut tetap target review manusia, bukan ground truth, bukan prompt/hardcode implementasi.

Model yang dibutuhkan: multilingual `small` dalam format CTranslate2, dengan `model.bin`, `config.json`, `tokenizer.json`, vocabulary dan metadata terkait. Estimasi perencanaan: sekitar 0.5 GB disk, sekitar 1–2 GiB RAM CPU/int8 (bergantung runtime); cap address space 4 GiB, 4 thread, timeout 300 detik. Angka ini bukan hasil benchmark real ASR saat ini.

## 6. SHOWCASE NO-SPEECH RESULTS

Sumber asli terverifikasi: 26.533 detik, 1080 × 1920, 30 FPS. PCM 424275 sample/848550 byte/26.5171875 detik; SHA-256 `19fcffe277258d4208802db4ac9bea3865d7ceb29077715489d2f469e9273f59` cocok.

Profile absent + delapan regional music/silence, coverage lengkap tanpa konflik, menghasilkan `not_required`. ASR tidak dipanggil, tidak ada transcript/timing yang dibuat. Ini keputusan berdasarkan canonical analysis yang tetap unverified; bukan sertifikasi akustik independen atau klaim bahwa singing menjadi dialogue.

## 7. TRANSCRIPT & TIMING QUALITY ASSESSMENT

Validator dan estimated timing telah diuji dengan mock/synthetic fixtures: source-relative offsets, finite/nonnegative/range checks, word order, overlap, gap, missing/empty/repeated text, suspicious Unicode, language change, low confidence, music-context hallucination dan utterance boundaries. Raw text/token/metrics tetap dipertahankan, tanpa rewriting atau timestamp snapping.

Real Pak Fuad: tidak ada raw/draft transcript atau timing baru; kualitas text/timing `unavailable`, bukan verified. Output completed-ASR yang kelak berhasil akan memiliki raw/draft/timing/review artifacts, text/timing `unverified`, serta review `pending`.

Tidak ditemukan WhisperX/torch/torchaudio/aligner yang lebih kuat pada runtime. Metode yang diimplementasikan adalah Faster-Whisper word timestamps sebagai `ASR_estimate`; belum diverifikasi sebagai frame-accurate atau sentence-accurate alignment.

## 8. EVIDENCE ELIGIBILITY DECISION

Pak Fuad: `evidence_eligibility.status = ineligible`, blocking reason `required_transcript_unavailable`. Showcase: status `not_required`, tanpa blocking reason. Pada keduanya `evidence_eligibility.transcript = false`, `evidence_eligibility.speech_alignment = false`; `director_attachments.transcript` dan `director_attachments.speech_alignment` null.

Kontrak gate Stage 5A tetap utuh. CLI exit 0 menandakan penilaian selesai; konsumen wajib membaca field eligibility/status tersebut. Generation yang tercatat tidak otomatis memverifikasi text atau timing. Review correction diterima hanya sebagai artifact attestation terpisah dengan approval identity, tanpa mengubah raw, mengklaim review independen, atau mengaktifkan attachment.

## 9. NEW AUTOMATED TEST RESULTS

Final: **85 passed, 0 failed, 0 errors, 0 skipped**. Tes positive ASR memakai mock; satu tes subprocess nyata memeriksa preflight model lokal yang sengaja tidak tersedia, tanpa transcription. Worker orchestration positive diuji dengan engine dataclass sintetis, bukan model asli.

Cakupan mencakup source/metadata/canonical, PCM integrity, speech/music/mixed/uncertainty, timing/quality, model/worker failure, timeout/stdout/stderr/memory handling, generation fields, artifact/region hash tampering, review claims, attachment safety, output no-clobber, traversal/symlink dan temporary cleanup. Tes tambahan memastikan manifest tidak dapat menaikkan timeout decode melampaui batas yang ditetapkan.

## 10. FULL REGRESSION RESULTS

Command: `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py'`.

| Suite | Passed | Failed | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Stage 5.4.6.4 | 39 | 0 | 0 | 0 |
| Stage 5A | 51 | 0 | 0 | 0 |
| Stage 5A remediation | 32 | 0 | 0 | 0 |
| Stage 5B | 85 | 0 | 0 | 0 |
| Python total | 207 | 0 | 0 | 0 |
| Plugin | 7 | 0 | 0 | 0 |
| Total | 214 | 0 | 0 | 0 |

Final Python execution: `Ran 207 tests in 66.631s`, `OK`. Plugin: 7 passed, 0 failed/cancelled/skipped/todo, memakai Node v24.21.0 dari runtime OpenClaw terisolasi, transport fetch mock tanpa request Gemini/9Router. Kedua Director Input V0.3 existing fixtures lolos schema; kedua bundle baru lolos integrity validator.

## 11. SOURCE & CANONICAL ARTIFACT INTEGRITY

Seluruh **127 file baseline identik**, 0 changed, 0 missing, termasuk MP4/WAV, legacy transcript/alignment/review/provenance, canonical analyses, Director fixtures, gate/adapters dan transport plugin.

| Artifact | SHA-256 |
| --- | --- |
| mandala-original.mp4 | `000c759ac57ff4c2bfbdfd3e8d678f46d2160ea8855b4ca9bb343ce26c8671f3` |
| cinematic-7693770515172887829.mp4 | `58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f` |
| pak-fuad-universal-v02.canonical.json | `856a09adedd2074e88457362ff0ea6e6b636beca16592f4f99d829e8a40aab5f` |
| cinematic-universal-v02.canonical.json | `0756f435b57750aa9d5a9d7db6804219e8bdc480d7edad49cdfb914612f6b84a` |

## 12. REMAINING RISKS AND HUMAN REVIEW REQUIREMENTS

Blocker real ASR adalah model lokal belum tersedia. Model-compatible loading, ASR recognition, speed/memory aktual dan warming-routine acceptance belum diverifikasi. Offline mock menguji mekanisme pipeline, tidak menggantikan real ASR.

Setelah model tersedia dan run baru disetujui, hasil masih memerlukan review text, kedua utterance beserta konteks, language/confidence flags, word/sentence boundaries dan alignment. Review identity dari CLI merupakan attestation yang disuplai manusia, bukan autentikasi independen. Tidak ada rule baru yang mempromosikan gate eligibility atau artifact legacy.

FFprobe stdout 1 MiB/30 s; FFmpeg PCM 64 MiB/60 s; worker stdout 8 MiB/300 s. Stderr DEVNULL (tidak dibuffer). Worker RLIMIT_AS 4 GiB, CPU timeout × threads, CPU/int8/1 worker; seluruh proses bounded diterminasi dan direap. FFmpeg satu thread dan maximum individual allocation 64 MiB; flag ini bukan total-memory cap. Temporary PCM/jobs dibersihkan. Artifact publication exclusive/atomic; bundle failure hanya menghapus file milik run tersebut.

Tidak ada install/download/upgrade, external API, VPS/production action, commit/push, rendering/publishing atau proses background yang sengaja ditinggalkan.

## 13. RECOMMENDATION FOR STAGE 5.4.6.5C

Ajukan implementasi Stage 5B untuk audit arsitek dengan blocker real ASR yang eksplisit. Keputusan menyediakan/menyetujui model dan real-ASR acceptance berikutnya diperlukan sebelum mengklaim keberhasilan transcription. Stage 5C tidak dimulai; keputusan kelanjutan tetap menunggu architect review.

**STAGE 5.4.6.5B IMPLEMENTED — WAITING FOR CHATGPT AUDIT**
