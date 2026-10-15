# Stage 6.1 — audit repository dan cleanup

Tanggal: 14 Oktober 2026, Asia/Jakarta. Scope: audit source/config/kontrak/bukti,
cleanup lokal, dokumentasi, regression dan lint. Tidak ada deployment VPS,
integrasi n8n, inference live, publish, install dependency, commit atau push.

## Kesimpulan dan batas kesiapan

Pipeline Stage 5 adalah **engine private preview berbasis CLI dan bundle file**,
bukan service Media Worker production. Komponen utama dapat digunakan kembali
oleh worker Stage 6, tetapi API, admission production, durable job queue, lease,
callback delivery dan storage delivery belum tersedia. Folder API/services/tools
yang kosong telah dihapus agar struktur tidak memberi kesan layanan sudah ada.

Laporan Stage 5 terbaru dan bundle `data/revisions/stage59/automatic/e2e-showcase.v01/`
menyimpan preview dengan catatan editorial. Stage 6.1 tidak menjalankan ulang
inference/QA editorial dan tidak memberi pengesahan baru atas preview tersebut.
`production_eligible=false`, `publishing_eligible=false` dan review manusia belum
dilakukan tetap merupakan batas workflow. Technical PASS tidak mengubah batas ini.

## Audit komponen dan entry point

| Komponen/source | Kesiapan untuk digunakan kembali | Gap menuju service |
| --- | --- | --- |
| `run_automatic_editing_v01.py` | Entry point private editing: proof, prepare, run, revalidate-speech, reevaluate; max 3 proposal Director dan 2 ASR per region | Root job tetap `data/revisions/stage59/automatic`; `prepare` dapat melakukan ASR/review; `run` melakukan inference. Bukan API submit job; belum ada lease whole-job |
| Analyst: adapter + `normalize_universal_analysis_v02.py`, `validate_universal_analysis_v02.py` | Kontrak analisis, metadata/hash, schema dan pemeriksaan semantik | Belum ada admission ingest terpadu/API; observasi AI tetap model-unverified |
| Evidence: `analyze_adaptive_av_evidence_v01.py`, `build_adaptive_director_input_v03.py` | Evidence lokal dan packet source-bound | Perlu staging media, manifest intake dan path yang memenuhi guard existing |
| OpenClaw 2026.9.9 | Wrapper dan bundled Node tersedia lokal; source Director/Reviewer memilih runtime isolated | Path berbasis home, Node directory spesifik versi, agent workspace/config/plugin harus diprovision per host; CLI lokal bukan daemon Media Worker |
| Adapter `mandala-9router-video` | Build/type-check dan 23 offline tests lulus; metadata/prompt/transport bounded | Binding generated provider masih spesifik device; compatibility 9Router 0.5.95 perlu retest pada upgrade |
| AI Director: `run_adaptive_director_v03.py`, automatic prompt | Structured proposal, bounded subprocess, raw responses, lineage | Provider availability/latency/cost bukan dijamin offline tests; prompt automatic juga hidup di Python, bukan hanya `openclaw/prompts/` |
| Independent validator: `automatic_editing_validation_v01.py`, `validate_adaptive_director_plan_v03.py` | Source/evidence/schema/proof gates; blocker dan advisory dipisahkan | Hanya private-preview admission; policy version perlu disimpan pada job |
| Renderer: `renderer_core_v01.py`, `renderer_revision_v02.py`, `automatic_text_v01.py` | FFmpeg deterministic, typed text, bounded resources, exclusive publishing | Linux `resource`/`fcntl`/`prlimit`, font absolute DejaVu; lock lokal bersama. Hard links membutuhkan work/output pada filesystem yang sama |
| `render_video_v01.py production` | Fail-closed guard tersedia | **Tidak ada executable production admission**: setelah pemeriksaan, source tetap menolak karena kontrak approval production belum diimplementasikan |
| QA: `video_quality_qa_v01.py`, automatic QA | Decode/PTS/frame count/audio/black frames/glyph checks | Matched no-text control menambah biaya encode/storage; pixel visibility bukan OCR/human review |
| AI Reviewer: `review_video_quality_v01.py`, automatic `model_review` | Actual-media review, typed findings dan pemisahan model/human | Review model bukan independent factual/human certification; failure/cost perlu policy service |
| Speech remote: `generate_remote_speech_evidence_v01.py` | Config bounded, provenance, transcript/timing gate; conditional ASR | Config endpoint/provider spesifik host, kualitas speech nyata masih terbatas; key/time budget harus provision target |
| `speech_asr_worker.py` | Worker subprocess ASR lokal opsional, bukan worker media general | Model/runtime lokal tidak dibuktikan hanya dengan adanya source; bukan default dependency production |
| Revision/benchmark/recovery/showcase scripts | Regression/replay/historical tooling penting | Sebagian mengikat sumber dan path showcase tertentu; bukan API untuk arbitrary job |

Source utama: `scripts/run_automatic_editing_v01.py` (prepare/run/reservation,
completion), `scripts/automatic_editing_validation_v01.py` (ROOT/code receipts,
policy), `scripts/render_video_v01.py` (render_lock, production_admission),
`scripts/renderer_core_v01.py` (safe_path, resources, environment), adapter source
dan README; kontrak dalam `src/schemas/`. Dokumentasi component yang diperiksa
meliputi automatic editing, renderer, remote speech dan ringkasan Stage 5.

## Dependencies dan environment

Baseline lokal diperiksa: Python 3.14.2, Node 24.21.0, OpenClaw package 2026.9.9,
FFmpeg 6.1.1-3ubuntu5, Ruff 0.17.0. Python runtime memakai NumPy 2.5.4,
SciPy 1.18.1 dan jsonschema 4.25.1; transitive pins ada di
`requirements-av.lock.txt`. Adapter memakai TypeScript/@types/node development
dependencies dan `package-lock.json`; OpenClaw merupakan instalasi isolated di
luar repository. Lock Python belum memuat hash wheel; reproducibility penuh juga
memerlukan pin image/OS/fonts/runtime, bukan hanya dependency Python.

Secrets `.env.asr`, `~/.openclaw/.env`, `~/.openclaw/openclaw.json` hadir dengan mode
0600. Key ASR tidak exported pada process audit; source mempunyai fallback private
config sehingga ini sendiri bukan bukti auth gagal. Isi secret tidak disalin ke
laporan atau arsip. Endpoint/provider non-secret dalam config dan generated binding
tetap host-specific. Stage 6.1 tidak menguji authenticated connectivity maupun
inference 9Router/ASR. Keberadaan config/runtime dan keberhasilan mocks bukan
bukti layanan sedang operasional.

| Kebutuhan target | Mekanisme existing / pekerjaan berikutnya |
| --- | --- |
| Python | Rebuild `.venv-av` atau environment image dari pins; jangan copy venv lokal |
| OS media | FFmpeg/FFprobe dengan libx264/AAC/libass/filters, DejaVu regular/bold, util-linux prlimit; jalankan proof target baru |
| OpenClaw/Node | Provision wrapper isolated, bundled Node, private config dan workspace aktif; jangan bergantung pada PATH host |
| Provider | Generate binding via `tools/configure_plugin.py`, rebuild dist; simpan API key pada runtime secrets |
| ASR | `MANDALA_ASR_API_KEY`; provision config remote endpoint/model/limits sesuai target, bukan invent environment override yang belum didukung |
| Budget | Reservation per call existing; tambahan quota money/time per job/global, karena biaya provider dapat tidak dilaporkan |
| Storage | Writable data root, work dan final bundle pada filesystem sama; backup originals, evidence, permits/ledger, results |
| Internal API | Auth token, database connection, allowed storage roots, callback policy merupakan kebutuhan baru, **belum dibaca source sekarang** |

## Temuan integrasi prioritas

1. **Production admission belum executable.** Stage 6 harus memilih private-preview
   service lebih dahulu atau mendefinisikan kontrak approval terpisah. Jangan
   mengubah false flags/force render agar terlihat siap production.
2. **Belum ada API/queue/lease.** n8n tidak boleh mengeksekusi command arbitrary atau
   melakukan retry seluruh pipeline setelah timeout HTTP. `attempt.mkdir` dan
   exclusive writes menghindari overwrite tetapi tidak menggantikan lease job;
   renderer flock hanya mengunci render pada shared filesystem lokal.
3. **Mount/path dan lineage.** Source guard menolak symlink/traversal, akar output
   dibatasi Stage 5, beberapa runner mengikat showcase. Relokasi ke VPS dapat
   mengubah environment/proof; regenerate proof source-bound baru, jangan rewrite
   historical receipts. Hindari work temp pada `/tmp` filesystem berbeda karena
   publisher memakai `os.link`.
4. **Crash/retry dan admission budget.** Reservation interrupted tetap dihitung;
   terminal stopped job tidak dibuka kembali. Perlu state machine durable,
   reconcile partial bundles dan lease recovery tanpa mengulang paid invocation
   atau mengembalikan consumed permit ke kondisi awal.
5. **Transport/memory.** Video base64 `image_url` adalah compatibility path dengan
   input maximum 20 MiB; payload dan buffer menambah memory. Provision worker
   capacity berdasarkan benchmark target, concurrency awal 1; jangan mengasumsikan
   semua endpoint OpenAI-compatible menerima video ini.
6. **Regression memerlukan data terpisah.** Banyak tests membaca media/evidence
   ignored Git. CI clone kosong tidak mereproduksi full suite; siapkan fixture
   bundle berhash dengan kontrol akses/backup, laporkan skip/missing secara eksplisit.
7. **Source control belum menjadi distribusi.** `git ls-files` = 0, belum ada commit
   dan remote. GitHub-to-Coolify tidak bisa dipakai dari checkout ini tanpa langkah
   versioning yang terpisah. Stage 6.1 tidak membuat commit/remote.
8. **Kualitas dan observability.** Stage 5 melaporkan candidate gagal audio headroom
   dan frame count; report historical tidak menjadi diagnosis akar masalah baru.
   Catat failure class, subprocess exit, reserved calls, elapsed time, disk dan
   unavailable cost per job; investigasi pola gagal tersebut sebelum launch umum.

## Rekomendasi arsitektur Stage 6 (belum diimplementasikan)

Mulai dengan satu Media Worker yang memanggil engine existing, internal API kecil,
dan PostgreSQL durable jobs. PostgreSQL dapat menjadi queue awal sehingga Redis
tidak wajib. n8n mengirim referensi sumber dan brief, mendapat job ID segera, lalu
poll status atau menerima callback. FFmpeg/inference berjalan di worker, tidak
menahan request n8n. API/worker bisa berbagi image; n8n dan DB layanan terpisah.

Kontrak API yang disarankan: `POST /internal/jobs` mengembalikan 202 dengan
idempotency key + canonical request digest; `GET /internal/jobs/{id}` untuk status;
`GET /internal/jobs/{id}/artifacts` mengembalikan manifest authorized, bukan path
filesystem/URL provider. `GET /health/live` dan `/health/ready` memeriksa process
dan runtime/storage configuration tanpa inference berbayar. Semua ini proposal,
bukan route yang tersedia.

Job admission menerima source ID/hash, brief dan policy/budget; server memetakan
storage path terkontrol. Jangan menerima shell command, filter FFmpeg, arbitrary
font path, credential URL atau output directory client. Worker claim atomik dengan
lease/heartbeat, concurrency 1 awal; deduplicate request sama dan tolak pemakaian
idempotency key dengan digest berbeda. Retry callback terpisah dari execution.

State yang disarankan: QUEUED → RUNNING → PREVIEW_COMPLETED / WITH_NOTES / BLOCKED /
FAILED; stage/checkpoint dan failure reason field terpisah. Simpan technical QA,
model editorial review, human review, production eligibility dan publishing
eligibility sebagai field berbeda. Restart reconciliation membaca manifest marker,
reservations/consumed permits; partial output bukan completed. Stop tidak reset
budget. Cancellation mematikan subprocess group dan mencatat state akhir.

Originals/evidence/result bundles disimpan pada persistent volume; PostgreSQL
menyimpan metadata/reference/hash/job transitions, bukan blob MP4. Untuk delivery
kemudian, object storage atau Cloudinary dapat ditambahkan dengan uploader
idempotent setelah eligibility/authorization yang sesuai. Pertahankan checksum dan
access private; retention job operational berbeda dari evidence audit. Restore test
harus mencakup DB dan files bersama. Cloudinary client/integration belum tersedia.

## Kebutuhan Coolify

Gunakan image Dockerfile yang direproduksi dari lockfiles, runtime version dan
OS/font dependencies, sebagai pekerjaan berikutnya. Coolify mendukung Dockerfile,
runtime environment, networks, health checks dan persistent mounts; rujukan resmi:
[Dockerfile](https://coolify.io/docs/applications/builds/dockerfile),
[configuration](https://coolify.io/docs/applications/configuration/overview),
[health checks](https://coolify.io/docs/applications/configuration/health-checks).
Rekomendasi desain ini belum diuji pada VPS.

Build adapter di image; generated provider binding harus cocok target tanpa
memasukkan credential ke layer. Runtime non-root memakai home yang konsisten
dengan wrapper/config source. Mount writable data serta private config; jangan
menyalin `.env*`, venv, `node_modules`, history/media ke image. HTTP hanya internal
network untuk n8n; 9Router/ASR outbound sesuai config. Jangan membuka worker command
interface ke internet. Resource cap container harus mengakomodasi Python, Node,
FFmpeg dan QA controls bersamaan; baseline subprocess memory 1536 MiB/2 threads
bukan sizing total VPS. Ukur CPU/RAM/disk dan timeout pada target sebelum capacity
decision. Readiness tidak menjalankan inference atau menyatakan editorial PASS.

Belum ada Dockerfile/Compose, database migrations, health endpoint atau Coolify
resource. `.dockerignore` hanya menyiapkan batas konteks build. Tidak ada deployment
atau perubahan koneksi external di Stage 6.1.

## Cleanup dan preservasi

- Memindahkan satu backup virtualenv nonportable ke
  `archive/stage61/environments/.venv-av.before-migration-20261014`; metadata
  file/hash dan symlink target tercatat. `.venv-av` aktif tetap di tempat.
- Membuat 49 salinan arsip berhash dari snapshot OpenClaw, live POC, log migrasi
  dan `data/backups`, di `archive/stage61/historical/` dengan struktur asal.
  Original tetap di path lama karena terikat baseline atau referensi laporan.
- Menghapus 76 file cache/bytecode (2.441.306 bytes), direktori cache terkait,
  serta tiga placeholder kosong `src/api`, `src/services`, `src/tools`.
- Memperbarui `.gitignore`, menambah `.dockerignore`, dokumentasi struktur dan
  tautan README. Tidak memindahkan source aktif, schema, tests atau bundle data.
- Semua zero-byte evidence/log/diagnostic MP4 dan lock historis tetap disimpan;
  ukurannya bukan pembuktian bahwa file aman dihapus. Tidak menghapus seluruh
  `render-tests`, benchmarks, failed attempts, raw responses, ledger atau permits.

Daftar lengkap: `cleanup-manifest.json`. Baseline preservasi:
`preservation-baseline.json`; verification awal **2.127 files unchanged** di
`preservation-verification.json`. Archive ignored Git/Docker dan membutuhkan backup
terpisah. Cleanup memindahkan backup 222 MiB dari root ke arsip pada disk yang sama;
ini merapikan struktur, bukan penghematan 222 MiB disk.

## Verification

Full offline regression sebelum cleanup: **1.323 tests PASS**, 94,529 detik.
Full offline regression setelah cleanup: **1.323 tests PASS**, 94,335 detik,
exit 0; hasil dicatat pada `test-results.json` dan `python-regression.txt`.
Preservasi 2.127 files, seluruh salinan arsip dan isi backup environment diperiksa
ulang setelah regression: PASS. Ruff conservative checks (E9/F821/F822/
F823) PASS; ini bukan audit style/security/dependencies vulnerability penuh.
Adapter 23 tests PASS dan `tsc --noEmit` exit 0; universal analysis self-test PASS.
Tidak ada perubahan implementation adapter, sehingga dist tidak direbuild.

Regression mencakup synthetic FFmpeg tests, bukan inference live atau render baru
media asli. Test diagnostics BLOCKED/REVISE adalah keluaran fixture negative cases;
kesimpulan suite harus mengikuti exit code dan unittest result, bukan satu baris
diagnostic. Semua log baru berada di `docs/stage61/`; log historis tidak ditimpa.

## Urutan pekerjaan berikutnya

1. Sepakati contract private-preview service, intake manifest, job identity,
   budget, states, DB lease/recovery dan artifact access.
2. Implement wrapper API/worker minimal memakai engine existing; tests job retry,
   crash, concurrency, idempotency dan non-publishing eligibility.
3. Package reproducible image; proof fresh pada environment target dan fixture CI
   terpisah. Selesaikan failure patterns/real speech quality sesuai scope berikutnya.
4. Setelah scope deployment diotorisasi, lakukan smoke test VPS dan n8n internal
   delivery dengan job private-preview; production/publishing admission tetap gate
   terpisah. Stage 6.1 hanya menyelesaikan audit dan cleanup.
