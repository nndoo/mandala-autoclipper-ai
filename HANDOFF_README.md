# Mandala Auto — handoff Stage 6.3.5 recovery

Dokumen ini adalah pintu masuk **checkout Linux saat ini**, bukan instruksi
clone awal. Baca [panduan AI agent](docs/AGENT_GUIDE.md) dan
[katalog Markdown](docs/markdown-catalog.md) untuk memilih dokumen sesuai tugas.
Periksa branch, `git status`, source, dan test terbaru; pekerjaan lokal dapat
belum di-commit/push. Jangan menganggap checkout baru di perangkat lain akan
memuat perubahan tersebut.

## Status yang tercatat sampai 16 Oktober 2026

| Tahap | Bukti lokal terakhir | Batas |
| --- | --- | --- |
| A | [Environment dan baseline](docs/stage63/stage635-stage-a-checkpoint-2026-10-15.md) PASS | Bukan proof image/service production |
| B | [PostgreSQL 16 dan admission](docs/stage63/stage635-stage-b-checkpoint-2026-10-15.md) PASS | Database lokal `TEST_ONLY` |
| C | [HTTP, queue, recovery](docs/stage63/stage635-stage-c-checkpoint-2026-10-15.md) PASS | Mock executor dan readiness yang disuntik test |
| D | [Sembilan role](docs/stage63/stage635-stage-d-completion-2026-10-16.md) PASS lokal | Proof fisik, render/QA, Reviewer dan Controller diuji dengan replay TEST_ONLY; belum proof Docker/live |
| E | [Synthetic HTTP end-to-end](docs/stage63/stage635-stage-e-checkpoint-2026-10-16.md) PASS lokal | PostgreSQL dan provider replay TEST_ONLY, bukan evidence historis |
| F | [Finalisasi Docker dan regression](docs/stage63/stage635-stage-f-final-checkpoint-2026-10-16.md) PASS lokal TEST_ONLY | Evidence historis dipulihkan secara lokal; full regression dan audit npm PASS. Deployment tetap memerlukan keputusan terpisah |

Pada PC Windows lama, implementasi Stage 6.3.5 pernah dikerjakan tetapi tidak
di-push. [Laporan implementasi](docs/stage63/stage635-implementation-report.md)
dan [checkpoint rekonstruksi](docs/stage63/PROJECT_CHECKPOINT_RECONSTRUCTED.md)
adalah sumber sejarah, bukan bukti source yang sama ada atau berjalan di sini.
Stage 6.3.4 editing worker `:3003` pernah dicatat sebagai deployment runtime-only;
laporan itu tidak membuktikan sembilan role Stage 6.3.5 aktif di VPS.

## Batas kerja lanjutan

Kontrak internal ada di [API contract](docs/stage63/stage635-api-contract.md).
[Deployment guide](docs/stage63/stage635-deployment-guide.md) adalah rencana
untuk review berikutnya, belum instruksi eksekusi. Media Worker lama `:3002`,
VPS/Coolify, n8n, dan database production tidak diubah oleh recovery lokal.
Provider live, rendering media nyata, publishing, deployment, serta
production readiness perlu tugas dan bukti tersendiri. Commit/push checkpoint
WIP Stage 6.3.5 telah diminta secara eksplisit; audit file sensitif sebelum
setiap push. Jangan menyalin secret,
original media, atau historical receipt ke dokumentasi baru.
