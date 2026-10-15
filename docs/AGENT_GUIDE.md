# Panduan baca untuk AI agent

Dokumen ini adalah pintu masuk navigasi, bukan bukti eksekusi. Diperbarui pada
16 Oktober 2026 dari checkpoint A–F; periksa `git status`, source, dan hasil
test terbaru sebelum menganggap status di bawah masih berlaku.

## Mulai dari sini

1. Baca [`AGENTS.md`](../AGENTS.md) untuk aturan kerja, runtime, dan preservasi evidence.
2. Baca [`README.md`](../README.md) untuk struktur proyek dan setup. Gunakan [`HANDOFF_README.md`](../HANDOFF_README.md) bila melanjutkan dari perangkat/chat lain.
3. Untuk Stage 6.3.5, mulai dari [laporan akhir recovery](stage63/stage635-final-report.md) dan [kontrak API](stage63/stage635-api-contract.md), lalu [checkpoint A](stage63/stage635-stage-a-checkpoint-2026-10-15.md), [B](stage63/stage635-stage-b-checkpoint-2026-10-15.md), [C](stage63/stage635-stage-c-checkpoint-2026-10-15.md), [D selesai lokal](stage63/stage635-stage-d-completion-2026-10-16.md), [E sintetis lokal](stage63/stage635-stage-e-checkpoint-2026-10-16.md), dan [F terblokir untuk deployment](stage63/stage635-stage-f-checkpoint-2026-10-16.md). Selalu cocokkan klaim checkpoint dengan source dan test saat ini.
4. Baca source komponen yang akan diubah. Jika dokumen dan source berbeda, laporkan selisihnya; jangan diam-diam menganggap laporan lama sebagai implementasi aktif.

## Status yang tidak boleh disatukan

| Lapisan | Bukti yang diperlukan | Status pada checkpoint terakhir |
| --- | --- | --- |
| Stage 6.3.4 editing worker | Laporan deployment/health yang tercatat | Runtime-only `:3003` pernah di-deploy; bukan bukti role Stage 6.3.5 live |
| Tahap A/B/C Stage 6.3.5 | Checkpoint dan test lokal | PASS sesuai cakupan lokal masing-masing |
| Tahap D Stage 6.3.5 | Uji role, render, QA, recovery dan proof | PASS lokal TEST_ONLY pada checkpoint 16 Oktober; belum proof Docker/provider live |
| Tahap E Stage 6.3.5 | Alur HTTP dan regresi B–E dengan media sintetis | PASS lokal TEST_ONLY; belum pemeriksaan mount/image Docker |
| Tahap F Stage 6.3.5 | Build, canary Docker, regression, audit readiness | Build/canary PASS lokal; keputusan tahap BLOCKED oleh regresi historis dan audit dependensi |
| Inference provider live | Receipt call yang terikat source dan approval | Belum diuji dalam recovery ini |
| Human/produksi/publishing | Persetujuan dan bukti terpisah | Tidak diberikan oleh test, model, atau private preview |

[Laporan implementasi](stage63/stage635-implementation-report.md) dan
[checkpoint rekonstruksi](stage63/PROJECT_CHECKPOINT_RECONSTRUCTED.md)
menggambarkan pekerjaan di PC lama yang tidak ikut ter-push. Keduanya
**riwayat**, bukan bukti bahwa kode yang sama ada pada checkout ini.

## Pilih dokumen menurut tugas

| Tugas | Baca lebih dulu |
| --- | --- |
| Source admission dan original | [Intake Adapter](stage63/stage632-intake-adapter.md), [kontrak API](stage63/stage635-api-contract.md), `backend/source_admission.py`, `backend/media_worker/intake_adapter.py` |
| Job/API/queue/recovery | [Checkpoint B](stage63/stage635-stage-b-checkpoint-2026-10-15.md), [C](stage63/stage635-stage-c-checkpoint-2026-10-15.md), [D](stage63/stage635-stage-d-completion-2026-10-16.md), [E terbaru](stage63/stage635-stage-e-checkpoint-2026-10-16.md), `backend/editing_store.py`, `backend/editing_api.py`, `backend/editing_dispatch.py` |
| Sembilan role | [Kontrak API](stage63/stage635-api-contract.md), [role map](../backend/roles/README.md), [Stage 5 otomatis](automatic-editing-v01.md), source `backend/roles/` dan `scripts/run_automatic_editing_v01.py` |
| Speech/timing | [Remote ASR](remote-speech-asr-v01.md), [speech provenance](speech-evidence-provenance-gate.md), source generator/validator terkait |
| Render, QA, Reviewer | [Renderer](renderer-v01.md), [QA Stage 5.6](stage-5.6-qa-workflow.md), [private preview](real-content-showcase-preview-v01.md), source renderer/QA dan receipt validator |
| Docker/Coolify | [Dua worker](stage63/stage634-two-worker-architecture.md), [checkpoint F](stage63/stage635-stage-f-checkpoint-2026-10-16.md), [deployment guide 6.3.5](stage63/stage635-deployment-guide.md), Dockerfile/Compose aktual dan bukti runtime terbaru |
| Sejarah/arsip | [Katalog seluruh Markdown](markdown-catalog.md); buka laporan bertanggal hanya untuk klaim tahap dan waktu tersebut |

## Aturan membaca evidence

- `data/` dan arsip berisi media/receipt historis yang tidak otomatis ikut clone. Jangan mengisi path historis dengan fixture sintetis.
- Hash receipt dapat mengikat prompt, instruksi agent OpenClaw, schema, source, dan environment. Perubahan file-file itu perlu proof/lineage baru; jangan menulis ulang receipt lama.
- `TEST_ONLY`, validasi struktur, decode, pengamatan model, human review, dan izin publish adalah hasil berbeda. Pertahankan labelnya dalam laporan.
- Jangan menyalin secret atau URL berkredensial ke Markdown. Semua perubahan deployment/production memerlukan bukti dan otorisasi terpisah.
