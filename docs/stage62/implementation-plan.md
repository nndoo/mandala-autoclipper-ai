# Perubahan diperlukan dan urutan implementasi

> **Revisi 15 Oktober 2026:** keputusan deployment/cutover dan jumlah file di
> laporan ini adalah snapshot historis. Rancangan aktif memakai Media Worker
> permanen + service editing baru dengan originals RO dan output terpisah.
> Lihat [keputusan final dua worker](../stage63/stage634-two-worker-architecture.md).

Ini rencana setelah Stage 6.2; **tidak ada langkah implementasi/deploy dijalankan**.
Prioritas memelihara original, source worker, PostgreSQL, network dan komponen engine.

| Urutan | Perubahan | Reuse | Gate selesai yang dapat diuji |
| --- | --- | --- | --- |
| 1 | Version source worker existing dan catat build/release source hash; tentukan task envelope/private-preview scopes | Source `/tmp/worker.py`, downloader routes, PG claim verification | Existing source endpoints tetap kompatibel; source/config/runtime lineage jelas; tidak menyimpan secrets atau mengubah historical artifacts |
| 2 | Intake adapter: ORIGINAL_READY → exact Stage 5 metadata/canonical source identity + namespace mapping | Existing volume/original SHA/probe; Stage 5 probe/metadata validators | Same bytes/hash, FPS/rounding/source ID correct; reject >20 MiB/>180 s; traversal/symlink/path contamination tests |
| 3 | Rancang satu image Media Worker versi baru berisi runtime Stage 5 dan volume lama | Stage 5 Python lock, isolated OpenClaw/Node, TS plugin, fonts/FFmpeg, existing worker | Fresh physical capability proof pada target, offline parity tests; resource/disk measurements; source endpoints masih kompatibel |
| 4 | Schema jobs/tasks/reservations/artifacts/permits/events; minimal DB queue+reconciler | Existing PostgreSQL `mandala_autoclipper`, `public.source_videos`; existing source lease patterns | Idempotency/CAS/lease fencing/crash windows/partial artifact tests; migrations hanya setelah scope implementasi disetujui |
| 5 | Extract shared lifecycle/receipt/proof/context helpers, tetap CLI façade | Existing exclusive writers, strict JSON, current policy/gates | Code receipts mencakup file baru; old historical receipts intact; proof baru setelah final extraction, bukan sebelum perubahan selesai |
| 6 | Extract Analyst dan Speech/Evidence + Reviewer source mode | Adapter/universal schema, AV measurements, remote ASR/timing/source review | No-speech zero ASR; real phrase/word timing preserved; failed/malformed/interrupted region calls consume slots; no implicit paid reviewer call |
| 7 | Extract Director satu proposal/task dan independent Validator | Current prompt/parser/validation/compiler | Max 3 reservations enforced across n8n reruns; server loads source-bound artifacts; request/raw/schema semantic parity |
| 8 | Extract Renderer dan Technical QA, typed manifest phases | Existing encode/admit/permit/lock/QA measurements | Admit replays before encode; one-use permit; encoded ≠ completed; actual QA reports; same-filesystem exclusive writes; failed MP4 preserved |
| 9 | Extract edited-output Reviewer dan Revision Controller/selection | model_review/candidate_for/select_candidate/verify_candidate | Blocker remains blocker; advisories corrected within cap; earlier eligible candidate survives later failure; all eligibility flags stay separate |
| 10 | Add role routes dan satu queue loop dalam Media Worker container yang sama | Existing 3002 service/network/PG connectivity | POST returns durable202; authenticate; prerequisites/version errors409; GET status; no long work on HTTP handler; shared heavy slot melindungi download dan render |
| 11 | Extend n8n workflow dengan eight role HTTP Request nodes, reusable poll/Wait/Switch | Existing source pipeline dan credentials references | Transport retry same idempotency key; n8n resume does not reset budgets; no duplicate controller/scheduler; separate source speech branch |
| 12 | Resolve n8n/runners image mismatch dan source-expiry recovery; persist original/upload receipts bila diperlukan | Existing task-runners and source schema | Version alignment qualification; source reservation reaper/fencing; Cloudinary receipt persistence remains separate from editing result approval |
| 13 | Authorized live compatibility smoke, then VPS rollout/canary and n8n execution | Existing resources, additive queue/routes | Actual 9Router transport/semantic test, ASR/provider timestamps, private preview QA, restart/restore/concurrency tests; never promote to publish automatically |

Steps 3 dan 5–9 berkaitan: qualified base image dapat disiapkan lebih awal, tetapi
capability proofs admission harus terikat **final** extracted code/environment;
regenerate bila bytes/runtime berubah. Image provision bukan upgrade sistem Python
atau Node global pada host. Pilihan default mempertahankan tested Python
3.14.2 dalam image Worker; alternatif 3.12 hanya setelah full engine regression
berhasil. Metadata Requires-Python >=3.12 sendiri tidak membuktikan kompatibilitas.

## Keputusan yang tidak memerlukan rebuild layanan existing

- Keep `/source/discover`, `/source/download`, `/source/file`, `/health` dan public
  source_videos lifecycle. Additive role gateway dapat memasukkan modul existing
  ke layout source versioned; tidak menulis ulang downloader.
- Keep volume original dan shared predefined network. Image Worker versi baru
  memuat engine dengan satu heavy slot. Limit 512 MiB sekarang dipertahankan sampai
  cutover teruji; profil baru memerlukan audit kapasitas dan kenaikan limit.
- Keep deterministic FFmpeg compiler, validator, typed text, proof/permit replay;
  tidak mengganti dengan raw FFmpeg command dari model atau node Code n8n.
- PostgreSQL queue cukup untuk satu consumer awal; Redis/Kafka/Celery, microservice
  per role dan Kubernetes bukan prerequisite Stage 6 berikutnya.
- Original Cloudinary upload existing tetap terpisah. Belum perlu memindahkan
  rendering/analysis ke Cloudinary atau mengunduh kembali original dari URL cloud.

## Tests diperlukan pada implementasi berikutnya

1. Offline parity against Stage 5 baseline: source/plan/spec/timeline, policy issue
   categories, reservation counting, speech/word highlight gates, candidate selection.
2. API/DB concurrency: same-key duplicate submit, conflicting digest, prerequisites
   wrong, lease expiry, stale worker, submit commit followed by HTTP timeout.
3. Crash durability: reserved call before send/no response; raw response before
   DB pointer; permit consumed before encode; encoded MP4 before QA/final marker;
   callback duplicate. No slot/permit refund or historical overwrite.
4. Media: declared plan vs decoded frame/PTS/audio mappings, actual text visibility,
   clipped glyph negative case, >20 MiB/180 s admission reject, unsupported speech timing.
5. VPS qualification: FFmpeg filters availability **plus physical proofs**, fonts/
   exact binaries, memory/CPU/disk enforcement, mount/permissions/no-symlink,
   backup+restore. Separate offline proof from authorized real inference/editorial QA.
6. n8n continuation: task completion after n8n restart, HTTP node key preservation,
   source-review branch and bounded revised proposals, no hidden execution on GET.

## Status akhir Stage 6.2

Read-only health GET 200, runtime/tool inventory, source/API inspection, PostgreSQL
metadata connection dan n8n canvas/SQL inspection selesai. Engine VPS import/render/
capability tests belum dijalankan karena dependencies belum tersedia dan scope ini
audit/desain. Authenticated inference, paid cost, editorial quality, Cloudinary
upload execution, human review, production admission dan publishing belum diuji.

Source code engine/worker, workflow dan VPS configuration tidak diubah. Laporan baru
hanya di `docs/stage62/`. Tidak ada test yang mengklaim compatibility PASS berdasarkan
diagram atau service healthy. Desain final setelah audit Instagram dan kapasitas
tercantum di [perbandingan](instagram-comparison.md), [kapasitas](resource-capacity.md)
dan [rencana GitHub → Coolify](github-coolify-deployment.md).
