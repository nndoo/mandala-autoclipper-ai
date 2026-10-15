# Mandala Autoclipper — Stage 6.3.5 handoff antar-perangkat

## Kondisi kode (15 Oktober 2026)
- GitHub private: `nndoo/mandala-autoclipper-ai`; `main` HEAD yang terakhir dicek: `0c92c6a617033e57b9b7fcc1b9388f5b81ccca12`.
- `main` menyimpan Stage 6.3.4 (`:3002` Media Worker dan `:3003` runtime-only AI Editing Worker).
- Perubahan source code Stage 6.3.5 dibuat **hanya di PC lama**, **tidak di-commit/push**, dan **tidak disertakan dalam paket ini**. Tidak bisa direstore dari GitHub. File tiga dokumen di paket ini berasal dari lampiran percakapan, bukan salinan source code.
- Stage 6.3.5 harus direkonstruksi dari source Stage 5 di GitHub, dokumen kontrak, dan bukti pengujian. Tidak boleh mengklaim source Stage 6.3.5 sudah dipulihkan.
- VPS Coolify menggunakan `backend/compose.yaml` dengan Base Directory `/backend`, Compose location `/compose.yaml`, mode Compose **Raw** agar originals volume existing tetap terpasang. Jangan mengubah deployment ini.

## Cara melanjutkan di PC baru

Clone repositori PRIVATE dengan autentikasi GitHub yang sah.

### Linux / Ubuntu
```bash
git clone https://github.com/nndoo/mandala-autoclipper-ai.git
cd mandala-autoclipper-ai
git switch -c wip/stage-6.3.5-recovery
# Copy folder docs/stage63 dari ZIP ini ke folder docs/stage63 repo.
git status --short
```

### Windows PowerShell
```powershell
git clone https://github.com/nndoo/mandala-autoclipper-ai.git
cd mandala-autoclipper-ai
git switch -c wip/stage-6.3.5-recovery
# Copy folder docs\stage63 dari ZIP ini ke docs\stage63 repo.
git status --short
```

Kemudian buka `CODEX_PROMPT.md` dan jalankan Codex **dari root repo**. Gunakan Linux/WSL2 untuk tes yang memerlukan `resource`, FFmpeg, dan Docker Engine. Jangan masukkan secrets atau media original dalam commit. Saat ingin push, audit dulu file staged; tidak ada kewajiban push/deploy dalam langkah pemulihan.

## Bukti yang ikut paket
- `docs/stage63/stage635-implementation-report.md`: apa yang pernah dibuat di PC lama; bukan kode.
- `docs/stage63/stage635-api-contract.md`: endpoint dan aturan sembilan role.
- `docs/stage63/stage635-deployment-guide.md`: migration/secret/storage dan batas deployment.
- `docs/stage63/PROJECT_CHECKPOINT_RECONSTRUCTED.md`: rekonstruksi dari log terakhir di chat; **bukan** file asli PC lama.

Jangan menulis migration ke PostgreSQL production, jangan melakukan panggilan 9Router berbayar atau publishing tanpa izin eksplisit.
