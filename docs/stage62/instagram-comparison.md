# Audit OpenClaw Instagram Autopost dan pola yang direuse

Audit read-only 14 Oktober 2026 melalui Coolify resource
[`social-media-automator:main-i3tkxq8woins9mnat3yxpice`](http://43.129.33.7:8000/project/t7hqlwaliizg9ysl0hbrtqbo/environment/ylr0rgxtgsngwrn2ukydwfwu/application/i3tkxq8woins9mnat3yxpice)
dan workflow n8n [`kabar_otomotif.id`](https://n8n-lf4qpqzmntrt6iqw9hasvdfd.43.129.33.7.sslip.io/workflow/SwMvo47ATtCcRUuC).
Membaca halaman konfigurasi, terminal container dan canvas n8n; tidak menekan
Execute, Save, Deploy atau Publish. Halaman menunjukkan banner unsaved changes
sebelum audit; perubahan itu tidak disentuh. Repository GitHub private tidak dapat
dibaca dari browser tanpa sesi GitHub, sehingga detail source yang dilaporkan
berasal dari build/runtime container dan konfigurasi Coolify yang terlihat.

| Area | Instagram existing teramati | Implikasi Autoclipper |
| --- | --- | --- |
| Bentuk service | Satu aplikasi Coolify, status `Running (no healthcheck)`, Node process PID 1 `node dist/index.js` | Satu backend modular masuk akal; tambah health/readiness yang sungguh menguji DB/storage |
| Runtime | Node v22.23.2, npm 10.9.8; package `openclaw` v1.0.0, Express 4.21.2, axios, Puppeteer, dotenv; Python dan FFmpeg tidak ditemukan di PATH container | Pola endpoint direuse, runtime binary tidak cocok untuk engine video Python/FFmpeg/OpenClaw adapter Stage 5 |
| Modul | `dist/agents/{newsScorer,contentWriter,imageSearchStrategist,imageValidator,imageRenderer}.js`, `services/routerClient.js`, `config/env.js`, `index.js` | Pisahkan delapan role di file backend; shared routing, ledger dan artifact helpers tetap satu aplikasi |
| API | n8n memakai POST `/api/news/score`, `/api/content/generate`, `/api/image/search-strategy`, `/api/image/validate`, `/api/image/render` pada aplikasi yang sama | Satu endpoint per role dan satu node HTTP Request per role; kontrak video perlu async task dan persistent receipts |
| n8n | Workflow `kabar_otomotif.id` bertanda Published, Schedule Trigger tiap 4 jam, RSS, scoring/copy/image search/validation/render, PostgreSQL post history, IG create/check/publish nodes | Reuse pola satu workflow utama dengan node khusus role dan cabang/loop; status Published tidak membuktikan eksekusi terakhir sukses |
| Routing | n8n node menunjukkan URL HTTP `i3tkxq8woins9mnat3yxpice.43.129.33.7.sslip.io` ke API port 3000; Coolify juga menampilkan internal hostname pada network `coolify` dan alias `openclaw` | Autoclipper sebaiknya memakai internal hostname/network untuk panggilan n8n, dengan service auth; existing Instagram public HTTP bukan alasan menyalin exposure itu |
| Git build | Coolify GitHub app `autopost-ig`, repo `nndoo/social-media-automator`, branch `main`, build strategy Dockerfile, base directory `/openclaw`, Dockerfile location `/Dockerfile`; auto deploy `Deploy on push (webhooks)` | Reuse GitHub app → Coolify Dockerfile → webhook; Autoclipper perlu repo/branch/build context/image sendiri |
| Storage | Coolify menampilkan `No persistent storage`; image code berada di `/app/dist`; process juga menjalankan Chromium | Autoclipper membutuhkan volume existing `/data` dan receipts/media durable; pola stateless Instagram tidak cukup untuk video |
| Resource | Coolify CPU/memory limit Instagram bernilai 0 (unset); container cgroup `memory.max=max`, `cpu.max=max 100000`; snapshot Docker 103.1 MiB, 0% CPU | Ukuran Instagram tidak memprediksi beban render/QA; ukur Stage 5 langsung |
| Observability | Metrics Coolify disabled pada server dan app Instagram; status app tanpa healthcheck | Wajib uji resource peak serta readiness/reconciliation sebelum auto deploy video |

Nama package `openclaw` pada aplikasi Instagram adalah **aplikasi agent TypeScript
khusus** berdasarkan package/runtime yang diamati. Audit ini tidak membuktikan
aplikasi tersebut memakai executable OpenClaw 2026.9.9 yang dipakai pipeline
Autoclipper lokal. Adapter 9Router video serta validasi semantic tetap perlu
dibawa dari repository Mandala.

Keputusan: tiru **struktur satu aplikasi + modul agent + endpoint berbeda + node
n8n khusus**, bukan asumsi request sinkronnya aman untuk ASR atau rendering video.
Satu Media Worker Autoclipper versi baru dapat memuat HTTP server, queue consumer
PostgreSQL dan subprocess Stage 5 dalam container yang sama dengan concurrency satu
heavy job. Source download/decode berbagi slot berat itu. API segera mengembalikan
202 dan task status diambil melalui GET+Wait n8n. Jika uji puncak menunjukkan OOM,
API starvation atau host pressure, pisahkan executor di revisi arsitektur berikutnya
atau tambah kapasitas VPS; tidak membuat container kedua sekarang.

Detail role, task status dan alur revisi ada di [role-endpoint-map.md](role-endpoint-map.md).
