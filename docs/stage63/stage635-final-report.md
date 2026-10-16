# Laporan akhir recovery Stage 6.3.5

Tanggal: 16 Oktober 2026 (Asia/Jakarta). Branch:
`wip/stage-6.3.5-recovery`. **Tahap A–F PASS lokal sesuai cakupan yang diuji.**
[Checkpoint F final](stage635-stage-f-final-checkpoint-2026-10-16.md)
memuat perintah, hasil dan batas verifikasi terakhir. [Audit F
sebelumnya](stage635-stage-f-readiness-audit-2026-10-16.md) mencatat kondisi
BLOCKED sebelum pemulihan evidence dan pembaruan npm; laporan itu tetap
berlaku sebagai riwayat, bukan status terkini.

## Hasil yang terverifikasi

| Area | Hasil lokal | Batas |
| --- | --- | --- |
| Tahap A–C | Environment Python 3.14.2, PostgreSQL 16, source admission, HTTP auth/queue/recovery PASS pada checkpoint masing-masing | Lingkungan lokal dan database TEST_ONLY |
| Tahap D | Sembilan role Stage 5 terhubung, proof fisik, permit, QA/Reviewer/Controller PASS | Provider replay TEST_ONLY; tidak ada inference berbayar |
| Tahap E | Alur HTTP → PostgreSQL → dispatcher → preview dengan media sintetis PASS | Human dan production gate tetap false |
| Evidence historis | 1.963/1.963 file, 198.457.363 byte, cocok path/ukuran/SHA-256 manifest asli | Berada di `data/` lokal yang diabaikan Git; keutuhan tidak mengizinkan replay job lama |
| Full Python regression | 1.394 test, `OK`, 0 FAIL/ERROR/SKIP; rerun independen 538,152 detik, exit code 0 | Offline dengan PostgreSQL 16 TEST_ONLY dan historical fixture asli lokal |
| Docker runtime | Image amd64 `sha256:d72d8e08b365ee6355a500f174054e400f7913ad56c5ea6cb49d1618198039f0`, build PASS; 23 test 9Router PASS; proof baru dan canary PASS | Image lokal; tidak di-deploy |
| npm audit | 0 critical/high/moderate/low pada image patched; npm global dan OpenClaw 11.21.1 | Audit database bukan jaminan semua perilaku dependency aman |

Canary image terbaru menguji readiness default 503, readiness replay 200,
autentikasi dan admission, idempotency, task Analyst melewati restart,
empat artifact yang cocok hash/ukuran, source mutation ke
`RECONCILIATION_REQUIRED`, serta fail-closed untuk hak tulis source dan
checksum migration. Proof Stage 5 dibuat ulang dalam image/volume yang sama.
Semua media canary dan provider replay berlabel TEST_ONLY.

## Perubahan final

- `backend/openclaw-runtime/package.json` dan lockfile menaikkan npm yang
  dibundel OpenClaw dari 11.20.0 ke 11.21.1 melalui override terarah.
  `backend/Dockerfile` menaikkan npm global ke versi sama untuk build.
  OpenClaw tetap 2026.9.9, Node 24.21.0, dan adapter 9Router tetap.
- `tests/stage635_npm_cache_check.cjs` memeriksa pemakaian cache npm yang
  tidak shared, kebijakan no-store, serta merekam perilaku `max-stale`
  shared-cache yang masih ada di `http-cache-semantics@4.3.0`.
- Test Stage 5 yang sudah diperbaiki sebelumnya memakai fixture sintetis
  sementara untuk kasus mandiri; media/receipt lama tidak diubah. Checkpoint
  dan panduan agent kini menunjuk bukti final ini.

Tidak ada perubahan pada engine Stage 5, schema migration, kode Media Worker
`:3002`, prompt OpenClaw, historical receipt, VPS, Coolify, n8n, atau
production database. Tidak ada paid inference, publish, atau Stage 6.3.6.

## Risiko dan keputusan berikutnya

`npm audit` bersih setelah update, tetapi [advisori cache yang
diperselisihkan](https://github.com/advisories/GHSA-ch52-4w7c-c8xp)
masih menyebut tidak ada versi patched. Test offline menunjukkan perilaku
`max-stale` pada cache bersama tetap dapat direproduksi; konsumen npm yang
terpasang memakai cache non-shared dan jalur role editing tidak menjalankan
operasi package management. Pantau keputusan upstream dan audit ulang saat
upgrade. Runtime OpenClaw pada host Linux masih memasang npm 11.20.0;
remediasi ini hanya berlaku untuk image baru. Jalur provider/ASR live,
akurasi penilaian editorial, kapasitas VPS,
permission/secret production, serta rollback belum diuji di lingkungan
tujuan. Keutuhan evidence tidak menyatakan job historis dapat dilanjutkan
atau receipt lama kompatibel dengan kode baru.

**Deployment readiness:** gerbang teknis lokal Stage 6.3.5F PASS;
persetujuan deployment dan verifikasi production adalah keputusan terpisah.
`human_verified`, `production_eligible`, dan `publishing_eligible` tetap
false. Jika ingin men-deploy, pengguna perlu menyetujui langkah produksi
secara terpisah setelah review backup, kapasitas, secret, dan rollback.

Commit final laporan ini diverifikasi terhadap branch remote setelah push;
SHA tidak ditulis di dalam laporan yang menjadi bagian commit itu sendiri.
