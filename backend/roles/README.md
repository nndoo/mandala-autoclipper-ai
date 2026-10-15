# Stage 6.3.5 editing role adapters

Modul di direktori ini dijalankan oleh `Stage5RoleExecutor` melalui
`backend/editing_dispatch.py` pada editing worker `:3003`. HTTP API,
`next_action`, lease, dan idempotency berada di backend; n8n kelak hanya
mengirim role yang ditetapkan backend. Media Worker `:3002` berada di
`backend/media_worker/` dan tidak memakai modul ini.

| Role HTTP | Modul | Status checkpoint Tahap D |
| --- | --- | --- |
| `analyst` | `analyst.py` | Replay sintetis PostgreSQL PASS |
| `av-evidence` | `av_evidence.py` | Analisis source-bound sintetis PASS |
| `speech-asr` | `speech_asr.py` | No-speech dan dua putaran ASR sintetis PASS |
| `director` | `director.py` | Proposal valid/rusak dan batas tiga proposal PASS |
| `validator` | `validator.py` | Validasi dan penolakan proposal PASS |
| `renderer` | `renderer.py` | Proof Stage 5, permit sekali pakai dan MP4 sintetis PASS |
| `technical-qa` | `technical_qa.py` | MP4 aktual PASS; cabang BLOCKED diuji dengan injeksi TEST_ONLY |
| `reviewer` | `reviewer.py` | Kedua phase PASS menggunakan respons replay TEST_ONLY |
| `revision-controller` | `revision_controller.py` | Terminal dan kandidat terbaik `WITH_NOTES` PASS |

`common.py` memegang context/gate bersama. `provider.py` memisahkan
`LiveProvider` dari `TestOnlyReplayProvider`; replay hanya dapat disuntik
secara eksplisit pada test. Service live memerlukan opt-in
`MANDALA_EDITING_LIVE_ROLES_ENABLED=1` dan seluruh readiness gate. Opt-in
bukan bukti provider terhubung atau izin paid inference. Lihat
[kontrak HTTP](../../docs/stage63/stage635-api-contract.md) dan
[checkpoint Tahap D](../../docs/stage63/stage635-stage-d-completion-2026-10-16.md)
untuk batas verifikasi. Periksa source dan test lagi sebelum menyebut status
terkini; checkpoint tidak boleh dipakai sebagai proof production.
