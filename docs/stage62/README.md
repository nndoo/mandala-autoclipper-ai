# Stage 6.2 — kompatibilitas dan desain modular

Tanggal audit: 14 Oktober 2026, Asia/Jakarta. **Audit/desain selesai; implementasi
dan deployment belum dilakukan.** Tidak menjalankan workflow n8n, download baru,
ASR/inference, render, migration database, restart, commit atau push.

Kesimpulan: Media Worker existing layak direuse untuk intake sumber, reservation,
download, probe/hash dan file delivery. Engine Stage 5 **belum kompatibel langsung**
dengan container worker saat ini. Dependencies AI/numerical belum ada, limit memory
512 MiB belum dikualifikasi untuk engine, dan kontrak path/metadata/async job berbeda.

- [Audit lokal vs VPS](compatibility-audit.md)
- [Arsitektur modular dan PostgreSQL](modular-architecture.md)
- [Role → modul → endpoint → node n8n](role-endpoint-map.md)
- [Audit dan perbandingan OpenClaw Instagram Autopost](instagram-comparison.md)
- [Audit kapasitas dan alokasi CPU/RAM](resource-capacity.md)
- [Rancangan GitHub → Coolify](github-coolify-deployment.md)
- [Perubahan dan urutan implementasi](implementation-plan.md)
- [Observasi VPS/n8n tersanitasi](observations.json)
- [Observasi tambahan Instagram/host/repository](followup-observations.json)
- [Inventory dan hash source lokal](local-inventory.json)
- [Verifikasi scope dan preservasi](scope-verification.json)

`observations.json` dan `scope-verification.json` mencatat snapshot audit awal
Media Worker. Audit host dan Instagram setelahnya dicatat sebagai addendum agar
riwayat observasi tidak ditulis ulang.

Endpoint `/source/*` dalam laporan adalah existing. Endpoint `/v1/*`, file
`backend/*`, tabel `mandala_engine.*` dan queue consumer dalam Media Worker adalah
**rancangan**; belum dibuat atau dipasang. Keputusan final setelah audit Instagram:
satu container backend modular dengan delapan role endpoints dan satu heavy slot
berbagi kapasitas dengan source download. Limit 512 MiB saat ini harus dievaluasi
ulang saat cutover; VPS 2 core/7.4 GB hanya kandidat canary, belum production PASS.
Diagram menggambarkan target, bukan koneksi operasional baru. Pengujian Stage 6.1
merupakan baseline historis, bukan regression VPS baru.
