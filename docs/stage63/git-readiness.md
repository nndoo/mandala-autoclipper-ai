# Stage 6.3.4 — GitHub Source Preparation

Tanggal: 15 Oktober 2026. **Status source: READY_FOR_INITIAL_PRIVATE_COMMIT.**
Audit dimulai dengan **221** file untracked, bukan 220 karena laporan Coolify
sebelumnya sudah bertambah. Setelah 10 snapshot historis dikeluarkan melalui
ignore dan tiga dokumen inventaris audit ditambahkan, daftar final berisi
**214 file**. Tidak ada file yang dihapus atau dipindahkan, original media maupun
receipt historis tidak diedit. Tidak ada staging pada index Git utama, commit,
push, deploy, atau akses/perubahan VPS pada tahap ini.

## Daftar file yang siap masuk Git

Daftar lengkap satu path per baris ada di [`git-safe-files.txt`](git-safe-files.txt).
Daftar itu mencakup dirinya sendiri dan laporan ini. Ukuran total calon commit
sekitar **4,2 MB**, seluruhnya teks UTF-8, tanpa binary media atau symlink.

| Kelompok | File | Isi yang dipertahankan |
| --- | ---: | --- |
| Root | 8 | Ignore rules, Python version, contributor instructions, README, requirements dan lint config |
| `backend/` | 17 | Empat endpoint Worker, Intake Adapter, runtime checker, Dockerfile/Compose, blank env example, dua package runtime OpenClaw, wrapper, requirements, placeholder role package dan snapshot VPS |
| `config/` | 1 | Konfigurasi remote ASR non-secret; credential dirujuk melalui nama environment |
| `docs/` | 67 | Panduan, Stage 5/6 reports, evidence logs, cleanup manifests, baseline dan daftar audit ini |
| `openclaw/` | 28 | Agent instructions aktif, empat prompts, adapter TypeScript, plugin tests, generator, package/lock dan build config |
| `scripts/` | 40 | Pipeline Stage 5, validator, renderer, Reviewer, revision, proof/capability helpers dan utilitas |
| `src/schemas/` | 19 | Kontrak schema yang ditemukan pada checkout saat audit |
| `tests/` | 34 | Regression tests, fixture helper, serta tiga source live POC |

File terbesar adalah `docs/stage61/cleanup-manifest.json` (1.101.279 byte),
disusul baseline preservasi (445.315 byte) dan lock OpenClaw (235.466 byte).
Tidak ada calon file di atas 5 MiB; Git LFS tidak dibutuhkan untuk snapshot source
ini. Manifest/baseline dan log `.txt` tetap disertakan karena bernilai sebagai
evidence. `backend/vps_snapshot/worker.py` tetap masuk Git sebagai source asli
Stage 6.3.1; ia dikeluarkan dari Docker context.

## Hasil pemeriksaan credential

Semua calon file diperiksa untuk header private key, pola token provider/GitHub,
JWT, URL dengan userinfo/password, query credential, literal assignment secret,
binary/NUL, symlink dan ukuran file. Satu nilai secret privat yang tersedia dari
konfigurasi lokal dibandingkan langsung dengan calon file tanpa mencetak nilainya;
**tidak ada kecocokan**. Tidak ada credential nyata yang teridentifikasi dalam
calon commit. Ini pemeriksaan offline terhadap snapshot saat ini; tidak ada
verifikasi token melalui layanan eksternal.

Temuan yang diklasifikasikan aman:

- String menyerupai token pada tests Director/renderer/planning/diagnostics adalah
  input sintetis untuk menguji penolakan credential dan redaksi. Fixture plugin
  memakai key test dan `fetchFn` mock. Fixture tersebut tetap disimpan; hasil scan
  tidak berisi nilai tokennya.
- `PGPASSWORD` pada Compose adalah interpolasi environment, bukan password
  literal. `backend/.env.example` menyediakan field credential kosong.
- Header Bearer di source dibentuk dari variabel runtime; source POC meminta key
  tersembunyi melalui `getpass`. POC tidak dijalankan pada audit ini.
- ID channel TikTok, provider ID, alamat VPS, URL workflow dan path lokal di
  dokumentasi adalah metadata operasional, bukan credential. Metadata itu tetap
  dipertahankan untuk source identity/provenance. Status siap ini ditujukan untuk
  **repository private**, bukan penilaian publikasi seluruh laporan ke publik.

Nilai private `~/.openclaw/openclaw.json`, `~/.openclaw/.env`, `.env.asr`, DB
password dan ASR/provider keys tidak ditambahkan ke repository. Perubahan baru
setelah audit tetap perlu diperiksa sebelum commit berikutnya.

## Perubahan ignore dan preservasi

`.gitignore` kini mencakup semua `.venv*`, snapshot `.before-*`, backup `.bak`,
private runtime directories, key/certificate, credential JSON/YAML dengan nama
umum, database lokal, serta output/temp/media tambahan. Blank `.env.example`,
source POC, tests aktif dan dokumentasi evidence tetap eligible untuk Git.

Sepuluh snapshot `.before-*` tetap berada di path asal. Masing-masing telah
dicocokkan SHA-256-nya dengan salinan di `archive/stage61/historical/`:

- Analyst `AGENTS.md.before-registration`;
- Director `AGENTS.md.before-registration` dan `AGENTS.md.before-timing-*`;
- empat `src/transport.ts.before-*` adapter;
- dua `tests/universal-mode.test.mjs.before-*` adapter;
- satu `prompts/universal-video-analysis-v02.md.before-*`.

Tidak ada penghapusan evidence. `data/`, `archive/`, media, render/test outputs,
environment, node_modules dan dist tetap lokal/backup terpisah. Clone Git tidak
mengembalikan originals atau evidence di lokasi ignored. File bernama
`scripts/render_test_fixtures_v01.py` sengaja tetap masuk image karena dipakai
proof/capability Stage 5, bukan sekadar artefak pengujian.

`.dockerignore` berubah menjadi **default deny + allowlist** untuk source
backend, scripts, schemas, non-secret config, agent/prompts dan plugin. Aturan
terakhir menolak secrets, cache, media, backup, snapshot VPS, dist serta binding
provider/manifest lokal. Plugin tests tetap masuk builder karena Dockerfile
menjalankan `npm test`. Direktori project `tests/` dan `docs/` tidak dikirim ke
Docker context.

## Verifikasi root build context Coolify

[`coolify-build-context.txt`](coolify-build-context.txt) mencatat **107 file**,
**1.620.592 byte** sebelum kompresi/tar. Seluruh file context termasuk dalam calon
file Git; tidak ada ketergantungan tersembunyi pada file ignored lokal. Daftar
difilter secara statis menggunakan `@balena/dockerignore@1.0.2` dalam tooling
sementara di `/tmp`, bukan dependency repository atau bukti build Docker Engine.
Semua 20 probe path terlarang ditolak. Seluruh sumber `COPY` Dockerfile tersedia.

| Input context | File |
| --- | ---: |
| Root build inputs | 4 |
| `backend/` tanpa snapshot VPS dan `.env.example` | 15 |
| `scripts/` | 40 |
| `src/schemas/` | 19 |
| `config/` | 1 |
| `openclaw/agents/` aktif | 10 |
| `openclaw/prompts/` aktif | 4 |
| Plugin source/build/test inputs | 14 |

Pengaturan Coolify: Dockerfile **`backend/Dockerfile`**, build context/base
directory **root repository (`/`)**, build argument non-secret
`MANDALA_PROVIDER_ID` yang cocok dengan private OpenClaw config target. Binding
`src/provider-id.generated.ts`, `openclaw.plugin.json` dan `dist/` memang tidak
masuk Git; generator dan build step membuatnya kembali. Root README dan plugin
README diperjelas agar clean clone menjalankan generator sebelum TypeScript build.
Wrapper OpenClaw kini executable (0755); Docker tetap melakukan chmod eksplisit.

Lockfile Python backend memuat **23 paket** dengan versi dan SHA-256. Package/npm
lock cocok untuk OpenClaw (**560 package entries**) dan plugin (**3 entries**);
semua `resolved` package URL yang ada memakai registry npm resmi dengan integrity.
Optional local Whisper tetap membutuhkan runtime/model tambahan; jalur speech
default adalah remote seperti dokumentasi Stage 5. Paket OS apt belum dipin ke
snapshot bertanggal, sehingga image belum dijamin bit-identical antar waktu.

## Masalah clean-source yang ditemukan dan diperbaiki

Pada salinan bersih calon Git, `npm ci` dan TypeScript build berhasil, tetapi
16 test QA gagal karena fixture memanggil `mkdtemp` pada parent
`data/qa/stage56` yang hanya kebetulan ada pada checkout pengembangan. Fixture
sekarang membuat parent-nya secara recursive sebelum membuat direktori eksklusif;
temporary request tetap dibersihkan oleh test. Tidak ada perubahan transport,
validation, provenance, permit, budget, atau revision logic.

Dockerfile juga menaruh plugin builder di `/plugin`, sehingga root yang dihitung
test menjadi `/`. Builder sekarang memakai layout repository
`/app/openclaw/plugins/mandala-9router-video`, dan sumber `COPY --from` diperbarui.
Dengan layout itu root test adalah `/app` dan penolakan path di luar project tetap
berlaku. Perbaikan dilakukan lokal; image belum dibangun pada tahap ini.

## Hasil verifikasi

| Pemeriksaan | Hasil |
| --- | --- |
| Git ignore probes | 17 path private/generated ditolak, 8 path source/evidence dipertahankan |
| Static Docker context, COPY sources, dan seluruh context tersedia dari Git | PASS |
| Konsistensi package/npm lock dan pin/hash Python backend | PASS |
| Clean export hanya dari daftar eligible Git, tanpa media/node_modules/dist/binding lokal | Berhasil |
| Generator provider non-secret → `npm ci` → `npm run build` → `npm test` → `tsc --noEmit`, clean export | **23/23 test PASS** setelah perbaikan fixture |
| Import enam entry/module Stage 5 + Intake pada clean export | PASS, tanpa inference/render |
| Universal Analysis `--self-test` pada clean export | PASS; sample valid memiliki 0 error/2 warning, sample timestamp invalid ditolak |
| Intake Adapter offline, clean export | **10 test PASS** |
| Media Worker parity offline, clean export | **7 test PASS**, eksternal/DB menggunakan mock |
| `ruff check scripts tests backend` | PASS |
| `docker compose -f backend/compose.yaml config -q` | PASS |

Pengujian clean export memakai `.venv-av` host dan bundled Node 24.21.0, bukan
container. Full regression yang membutuhkan media historis tidak dijalankan
ulang karena media sengaja tidak masuk Git. Tidak ada inference, download model,
editorial render, publish, GitHub transfer, atau perubahan VPS.

## Keputusan berikutnya

Source pada daftar aman sudah siap dipilih untuk commit pertama ke repository
private. Index utama masih kosong, jumlah commit tetap nol dan remote belum
disetel. Pemilik repository tetap perlu memilih/membuat repo GitHub, melakukan
commit/push sendiri, lalu memberi GitHub App Coolify akses repo tersebut sesuai
[laporan Coolify](stage634-coolify-runtime-test.md). Setelah source tersedia,
build dan smoke test canary dengan volume terpisah masih wajib dijalankan; Git
readiness tidak menetapkan image runtime, editorial, atau production sebagai PASS.
