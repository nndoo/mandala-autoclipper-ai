# Remote speech ASR — Whisper Large v3

Jalur utama Stage 5B memakai endpoint `/v1/audio/transcriptions` yang diuji pengguna, model request `groq/whisper-large-v3`. Konfigurasi non-secret ada di `config/speech-asr.remote.v01.json`. Setelah uji asli HTTP 200 dan permintaan pengguna mengganti runtime lama, default CLI menjadi `remote`. Tidak mengubah transport Gemini, OpenClaw terisolasi, sumber media, canonical, atau Director fixtures. Mode `--backend local` tetap eksplisit, tetapi memerlukan runtime/model lokal yang disetujui; dependency tidak dipasang otomatis.

API key khusus proyek disimpan di `.env.asr` (0600, diabaikan Git). Prioritas credential: environment `MANDALA_ASR_API_KEY`, file privat tersebut, kemudian provider OpenClaw yang endpoint-nya identik jika dikonfigurasi. Tidak ada key di config JSON, source, command arguments, job temporer, provenance atau laporan. Mengubah endpoint memerlukan credential yang memang sesuai; Authorization/audio tidak diteruskan melalui redirect. Tidak mengubah konfigurasi VPS atau OpenClaw.

```sh
python3 -B scripts/generate_speech_evidence_v01.py generate \
  --backend remote \
  --remote-config config/speech-asr.remote.v01.json \
  --video data/test-videos/mandala-original.mp4 \
  --metadata data/analyses/universal/mandala-original.media.json \
  --analysis data/analyses/universal/pak-fuad-universal-v02.canonical.json \
  --output-dir data/analyses/speech-v01/pak-fuad.remote.v01

python3 -B scripts/generate_speech_evidence_v01.py validate \
  --bundle data/analyses/speech-v01/pak-fuad.remote.v01
```

Direktori output wajib baru. Validator memilih kontrak lokal/remote berdasarkan versi manifest; validasi remote tetap offline tanpa credential atau network request. Remote hanya meng-upload WAV mono 16 kHz dari speech regions setelah sumber/canonical/PCM diverifikasi, dengan context 0.75 detik. Music-only, unknown, coverage gap dan konflik mempertahankan gate Stage 5A; no-speech tidak membuat request. Tidak ada retry, fallback model/format atau request Gemini otomatis.

Request default sesuai contoh pengguna: model di atas, `response_format=json`, temperature 0, language `id`, tanpa prompt tambahan. Untuk meminta timing provider, salin config ke file baru lalu pilih `verbose_json`; worker meminta word granularity. Dokumentasi underlying [Groq Speech to Text](https://console.groq.com/docs/speech-to-text) menjelaskan format verbose dan timestamp granularity; dukungan proxy ini tetap harus diuji, tidak diasumsikan dari dokumentasi Groq.

Respons JSON yang hanya mempunyai `text` dipertahankan di raw dan `draft-transcript.v01.json.recognized_regions`. `context_start_sec` / `context_end_sec` adalah batas audio yang di-upload, **bukan timestamp utterance**. Dalam kasus ini segments kosong, timing unavailable, review pending dengan start/end null; tidak mengarang word/sentence boundaries. Bila provider benar-benar memberi timestamps, offset source ditambahkan, raw timestamps tetap disimpan, dan validator lokal memeriksa rentang/order/confidence. Top-level words provider juga dipertahankan.

Nama artifact tetap raw/draft/timing/review/gate/generation-provenance/validation-eligibility V01, namun manifest version `remote-asr-0.1.0` membedakan kontrak. Raw respons, upload WAV/PCM hash, source/canonical/config hash, request fields, status HTTP, elapsed client dan generator hash dicatat. Remote model hash, runtime/compute dan internal decoding tetap unavailable/unobserved; model alias/request tidak membuktikan server weights. Generation provenance `recorded` berarti client mencatat request/response pada eksekusi tersebut, bukan autentikasi server independen. Kegagalan region berikutnya tetap menyimpan raw responses yang telah selesai, tanpa mengklaim whole-run completion.

Gate Stage 5A tidak diubah: text/timing belum verified, attachment transcript/alignment false dan Director attachments null. Text-only akan membuat gate structural timing gagal, bukan dipromosikan menjadi alignment. Template review remote belum diterima oleh perintah `accept-review` lokal; review manusia harus dilakukan dengan kontrak yang sesuai sebelum perubahan eligibility apa pun. CLI exit 0 hanya menyatakan assessment selesai; baca `generation_status` dan explicit eligibility.

Resource default: upload per region ≤25 MiB, raw response ≤8 MiB, HTTP worker wall time ≤90 detik, stdout ≤8 MiB +64 KiB, stderr DEVNULL; proses killed/reaped saat cap/timeout. Worker address space 512 MiB, CPU time 60 detik. FFprobe/PCM memakai batas Stage 5B yang ada (1 MiB/30 s dan 64 MiB/60 s). HTTPS diverifikasi; tidak memakai proxy environment, credential URL, redirects atau `verify=False`. Error body dan response yang memuat credential tidak disimpan. Temporary WAV/PCM/job dibersihkan; semua artifact output exclusive/atomic.

Tes baru menggunakan mock HTTP. Pengujian endpoint asli harus dicatat terpisah dan tidak membuktikan accuracy atau timing. Tidak ada dependency/model baru yang perlu dipasang. Stage 5C dan integrasi Creative Director tetap di luar scope.

Uji asli Pak Fuad: HTTP 200, elapsed request 2.593345 detik; satu request JSON tanpa retry. Sumber/PCM verified, generation recorded, text unverified, timing unavailable, review pending dan attachment ineligible. Hasil machine mengenali “Dua hari sekali ya?”; balasan machine “Wah sangat terjaga pak tentunya pak ya?” tetap perlu review, bukan dikoreksi otomatis ke candidate lama. Artifact ada di `data/analyses/speech-v01/pak-fuad.remote.v01/` dan lolos offline validator.

Atas instruksi pengguna, sesudah uji berhasil dihapus: `.venv-asr` (435.91 MiB allocated), `scripts/transcribe_audio.py` yang tidak direferensikan lagi dan meng-overwrite legacy output, serta tiga assessment `pak-fuad.v01` berstatus blocked model. Detail/hash target sebelum penghapusan ada di `data/analyses/speech-v01/remote-replacement-cleanup.v01.json`. `generate_speech_evidence_v01.py`, worker opsional dan tesnya tetap dipakai untuk shared validation atau pemeriksaan prerequisite; ini bukan runtime aktif jalur API. MP4/WAV/canonical/legacy evidence yang masih direferensikan, Stage 5A gate dan runtime OpenClaw terisolasi tetap dipertahankan.

Regresi final setelah cleanup: 240 tes Python lulus (termasuk 33 remote adapter tests), 7 plugin tests lulus; 0 failed/errors/skipped. Python `Ran 240 tests in 54.297s — OK`. Bundle real remote kembali lolos offline validator. Dari 127 original baseline files, 126 tetap identik dan satu script legacy dihapus sesuai instruksi pengguna; tidak ada perubahan/hilang yang tidak diharapkan. Scan source/artifacts tidak menemukan key; `.env.asr` mode 0600 dan diabaikan Git. Snapshot final ada di `data/analyses/speech-v01/remote-asr-validation-and-tests.v01.json`.
