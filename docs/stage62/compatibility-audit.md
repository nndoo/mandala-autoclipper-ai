# Audit kompatibilitas Stage 5 dengan Media Worker existing

14 Oktober 2026, Asia/Jakarta. Kesimpulan: **ADAPTATION_REQUIRED**. Reuse intake,
PostgreSQL, volume dan network existing; jangan mengganti downloader dengan engine
editing atau menganggap service healthy sebagai qualification AI.

## Metode dan bukti

Repository dibaca langsung: requirements/lockfile, schema, adapter TypeScript,
entry points, renderer admission, speech, QA dan revision logic. Dependency
Requires-Python dibaca dari metadata package lokal. Hash source audit ada di
`local-inventory.json`.

Skill mandala-video-workflow digunakan. `using-n8n-skills-official` tidak ditemukan
pada installed skills/plugins yang ditelusuri; audit/desain n8n memakai dokumentasi
resmi. Tidak ada workflow editing/implementation yang bergantung pada skill tersebut.

SSH langsung memakai existing local configuration, BatchMode dan strict host-key
checking gagal sebelum login: ssh-agent tidak mempunyai identity dan host key
ED25519 VPS belum dikenal. Tidak menambahkan key, mencoba password, mengganti
known_hosts atau menonaktifkan pemeriksaan host key. Audit container dilakukan
melalui sesi terminal Coolify yang sudah authenticated, bukan melalui SSH lokal.

Coolify resource `autoclipper-media-worker` diperiksa lewat UI, editor Compose
read-only dan terminal container. Source `/tmp/worker.py`: 409 baris, SHA-256
`718d15e45ad4fb24935e65e6bc227ac7b3bd12e1b070844c24aecf9120c5e975`.
Source dibaca dengan redaksi baris credential; secret environment tidak dicetak.
Database diperiksa melalui connection dengan `default_transaction_read_only=on`:
versi, nama database dan information_schema, tanpa perubahan atau isi row sumber.

[Workflow existing](https://n8n-lf4qpqzmntrt6iqw9hasvdfd.43.129.33.7.sslip.io/workflow/ZAeqJqTuH83tu5rY)
bernama **Mandala Auto - Autonomous AI Autoclipper** dibaca pada canvas dan parameter
SQL. Tidak menekan Execute, Publish, Save, Reset, Deploy, Restart atau backup.
Banner unsaved changes pada General Coolify sudah terlihat sebelum editor dibuka;
audit tidak menyimpan atau mereset perubahan tersebut.

## Lokal vs container VPS

| Aspek | Engine lokal | Media Worker VPS yang diamati | Implikasi |
| --- | --- | --- | --- |
| Python | Tested baseline 3.14.2 | 3.12.15, image `python:3.12-slim-bookworm` | Bukan konflik major otomatis: NumPy/SciPy pins memerlukan >=3.12, jsonschema >=3.9. Python 3.12 belum menjalani full regression engine; gunakan runtime isolated yang dikualifikasi |
| Packages | NumPy 2.5.4, SciPy 1.18.1, jsonschema 4.25.1 | Tidak ditemukan oleh package inventory; psycopg 3.3.6 dan requests 2.34.2 tersedia | Numerical/schema dependencies wajib ditambahkan ke image Worker versi baru; jangan bulk-upgrade host |
| Downloader packages | Bukan dependency utama editing | Compose memasang `yt-dlp[default,curl-cffi]==2026.8.19`, `curl-cffi>=0.11,<0.17`, `psycopg[binary]>=3.2,<4` | Preserve downloader behavior; range dependency dan tag base image belum reproducibility lock penuh |
| Node/npm | Bundled Node 24.21.0 | Tidak di PATH | OpenClaw runners existing tidak dapat dipanggil |
| OpenClaw | Isolated 2026.9.9; wrapper memakai home path dan Node directory spesifik | Tidak di PATH; expected isolated wrapper di home /root tidak ada | Provision runtime/agent/plugin target terpisah pada tahap implementasi; tidak ada klaim runtime AI VPS sudah tersedia |
| FFmpeg/FFprobe | FFmpeg 6.1.1-3ubuntu5 | FFmpeg 5.1.9-0+deb12u1; FFprobe tersedia | Environment/code-bound capability proofs lokal tidak berlaku di VPS |
| Filters/encoders/fonts | libx264/AAC/libass dan typed text | ass/subtitles/xfade/drawtext/eq/crop/scale/overlay/afade/atempo/concat, libx264/AAC serta kedua font DejaVu tersedia | Availability terverifikasi; decode/render/capability physical qualification engine belum dijalankan |
| Linux enforcement | prlimit, fcntl/resource, MALLOC_ARENA_MAX=2 | prlimit tersedia; root uid 0; Linux x86_64 | Pertahankan subprocess enforcement; worker user/permissions dan writable mounts perlu desain target |
| Memory/CPU | Base renderer AS cap 1536 MiB; automatic/revision dan QA memakai AS cap 3072 MiB; Node heap 256 MiB | cgroup memory.max 536870912; CPU `max 100000` | 512 MiB belum dikualifikasi. AS cap/Node heap bukan kebutuhan RSS aktual atau sizing VPS; ukur total concurrency sebelum menetapkan limit |
| Storage | Path dalam checkout; writers exclusive dan hard-link | Volume `muxr6rvojjjdrjrp24yjimak_autoclipper-data` → `/data`; `/data/source/{originals,tmp,locks,tests}` | Reuse volume; translate namespace dengan receipt baru, tanpa symlink/overwrite historical files |
| Disk | Dibatasi per proses/output | `/data` filesystem sekitar 78,6 GiB total, 24,3 GiB free saat audit; tmp/originals same device | Snapshot kapasitas, bukan quota atau jaminan cukup untuk concurrent jobs/retention |
| HTTP | CLI saja | ThreadingHTTPServer pada 0.0.0.0:3002 | Tambahkan routes modular + durable queue pada worker gateway; jangan menjalankan FFmpeg synchronously di handler |
| PostgreSQL | Tidak ada job DB engine | 16.15, database `mandala_autoclipper`; public table yang terdaftar: `source_videos` | Reuse instance/database; schema job editing terpisah belum ada pada public inventory |
| Provenance/admission | Hash source/code/environment, replay, one-use permit, reservations | Source SHA/bytes/metadata, DB claim/lease dan local locks | Fondasi kompatibel; source reservation tidak menggantikan render permit atau inference budget |

Scope runtime pada tabel ini adalah **container Media Worker**. Audit host VPS
melalui terminal server Coolify dilakukan sesudahnya dan dicatat di
[resource-capacity.md](resource-capacity.md); container Instagram dicatat di
[instagram-comparison.md](instagram-comparison.md). Tidak ada sesi SSH langsung,
backup restore test, outbound inference/ASR atau render synthetic VPS pada audit ini.

## API worker existing dan kontraknya

| Method/path | Input/output existing | Bukti dan batas |
| --- | --- | --- |
| GET `/health` | `{status: "ok", service: "autoclipper-media-worker"}` | GET loopback menghasilkan HTTP 200; handler hanya liveness, tidak memeriksa seluruh dependency/DB readiness |
| POST `/source/discover` | `username`, `maxVideos` 1–10 → success/count/videos `{videoId,url,title}` | Source membatasi akun TikTok existing; yt-dlp discovery synchronous dengan timeout 95 s. Tidak dipanggil dalam audit |
| POST `/source/download` | `videoId`, `claimToken` UUID → success/sourceKey/videoId/localPath/metadata/claimToken; `alreadyExists` pada reuse | Verifikasi row RESERVED+token+lease; semaphore 1 dan per-video flock; original dibatasi 150 MiB, duration 1–1200 s, dimensions >=320 |
| POST `/source/file` | `videoId`, `claimToken` → binary original setelah DB/file binding | Membutuhkan ORIGINAL_READY dan lease aktif, path/bytes/SHA sesuai; tidak dipanggil dalam audit |

Metadata `describe_media()` meliputi sizeBytes, sha256, durationSeconds, width,
height, videoCodec, audioPresent. **Tidak sama dengan metadata source Stage 5**:
Stage 5 memerlukan verification.method `ffprobe_and_sha256`, file_name, source ID
`local-sha256-<32 hex>`, FPS/duration rounding dan exact canonical source binding.
TikTok videoId tetap identitas upstream; jangan mengganti source ID content-hash
dengan platform ID. Reprobe/FPS dan sidecar canonical baru diperlukan pada intake.

Worker mengunduh ke temp pada volume yang sama, mengukur SHA/probe/full decode,
recheck DB claim dengan row lock, kemudian `os.replace` untuk promotion. Metadata
ORIGINAL_READY ditulis oleh node SQL n8n berikutnya. File promotion dan SQL node
berikutnya bukan satu transaksi atomik lintas sistem; crash di antara keduanya
harus direconcile. Full-decode source worker tidak menggantikan output QA Stage 5.

## Workflow dan DB yang sudah bisa direuse

Alur yang terlihat: manual trigger → Edit Fields → TikTok - Discover Videos →
Format Source Metadata → PostgreSQL - Upsert Source Videos → PostgreSQL - Select &
Reserve Video → Media Worker - Download Original → PostgreSQL - Save Original
Metadata → Original Saved? → Media Worker - Get Original File → Cloudinary - Upload
Original (true branch). False branch belum mempunyai kelanjutan terlihat.

Node `Execute a SQL query` berdiri terpisah tanpa input; isinya inspection terhadap
kolom Cloudinary/asset/upload, bukan scheduler editing atau heartbeat. Tidak ada
node Analyst/Director/Validator/Renderer/QA/Reviewer/revision pada canvas yang dibaca.
Workflow context menampilkan `active=false` dan manual trigger. Ini tidak menyangkal
bahwa layanan n8n berjalan; activation/scheduled autonomy workflow berbeda dari
service liveness. Tidak ada execution output baru yang dinilai dalam audit.

Reserve SQL sudah memakai SELECT candidate DISCOVERED, ordering, FOR UPDATE SKIP
LOCKED LIMIT 1, update RESERVED, gen_random_uuid claim, lease 30 menit, heartbeat
timestamp dan attempt_count. Save Original Metadata memakai parameter $1–$12,
memeriksa source_key/token/video/status RESERVED/lease/success dan SHA lama null
atau sama, lalu update ORIGINAL_READY dan memperpanjang lease 30 menit.

Tabel source_videos sudah menyimpan identity, statuses, timestamps, claim_token,
lease_expires_at, attempt_count, last_heartbeat_at, original path/bytes/SHA/duration/
dimensions/codec/audio. Kolom Cloudinary/upload tidak ditemukan pada inventory saat
audit; canvas berakhir pada upload original dan tidak menunjukkan node persistence
upload receipt sesudahnya. **Upload configured** belum menjadi **upload sukses atau
delivery receipt durable**; audit tidak menjalankan upload.

Coolify menampilkan n8n `n8nio/n8n:2.42.4`, task runners `n8nio/runners:2.10.2`,
PostgreSQL `postgres:16-alpine`, semuanya healthy. Tag n8n/runners berbeda; dokumentasi
resmi meminta matching image versions. Ini compatibility concern untuk Code nodes,
bukan bukti HTTP Request nodes rusak. Verifikasi/alignment berada di tahap berikutnya,
tanpa upgrade sekarang. [n8n task runners](https://docs.n8n.io/deploy/host-n8n/configure-n8n/set-up-task-runners.md)

## Compatibility issues yang perlu diatasi

1. Runtime OpenClaw/Node dan numerical/schema packages absen: blocker langsung.
2. 512 MiB dan concurrency ThreadingHTTPServer bukan policy execution AI; workload
   media perlu subprocess berbatas resource, satu heavy slot bersama downloader,
   admission resource dan qualification target. Desain final memakai satu container.
3. Input 150 MiB/1200 s vs transport <=20 MiB dan engine <=180 s: reject admission
   unsupported input secara eksplisit pada v1. Jangan diam-diam trim/compress original.
4. Metadata camelCase/platform ID dan absolute `/data/source/...` tidak memenuhi
   Stage 5 source sidecar/root guard. Adapter namespace dan receipt baru diperlukan.
5. Source-file lease 30 menit tidak cocok untuk keseluruhan editing/revision: validasi
   claim saat admission lalu gunakan durable editing job identity, bukan refresh token
   lama atau mengulang download untuk setiap AI role.
6. Monolith `prepare` melakukan storyboard+ASR+source Reviewer, `run` melakukan semua
   proposals/QA/review/selection, `render_attempt` menggabungkan encode dan QA. Routes
   per role tidak bisa sekadar menjalankan tiga CLI ini dengan nama berbeda.
7. FFmpeg/environment berbeda: fresh code/environment-bound proofs diperlukan setelah
   refactor/runtime target dikualifikasi. Historical receipts tidak diubah agar lolos.
8. Filesystem promotion dan DB completion membutuhkan reconciliation; bounded call
   reservations dan permits tidak dapat diganti oleh retry HTTP atau source lease.
9. User/health/API exposure belum qualified untuk AI task API. Existing health hanya
   liveness; task routes baru perlu service authentication, source ownership dan scopes.
10. n8n/runners mismatch, manual/inactive workflow dan receipt Cloudinary yang belum
    durable adalah work items terpisah dari compatibility engine.
11. Reserve SQL hanya mengambil DISCOVERED; expired RESERVED tidak otomatis
    direclaim oleh query itu. Tidak terlihat connected heartbeat/reaper node pada
    canvas audit. Desain recovery harus explicit dan menjaga fencing/attempt history.

Baseline tests lokal di `docs/stage61/test-results.json`: 1.323 Python tests,
23 adapter tests, Ruff/type-check/self-test PASS. Stage 6.2 tidak mengulang suite atau
render karena tidak mengubah implementation; **tidak ada regression VPS baru**.
