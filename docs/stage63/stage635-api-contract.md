# Stage 6.3.5 — kontrak HTTP internal

**Status dokumen:** kontrak untuk implementasi lokal, bukan bukti endpoint
production aktif. Tahap A–E memiliki checkpoint PASS sesuai cakupan lokal;
[Tahap E](stage635-stage-e-checkpoint-2026-10-16.md) memakai replay TEST_ONLY. Cocokkan setiap
perilaku aktual dengan source dan integration test sebelum mengandalkannya.

Base URL internal: `http://mandala-ai-editing-worker:3003`. Tidak ada domain
publik. Semua `/v1/*` memerlukan `Authorization: Bearer <workflow-token>`;
semua POST job/role memakai `Idempotency-Key` stabil (1–128 karakter).
`Content-Type: application/json`, body maksimal 64 KiB. ID job/task UUID.
Versi kontrak: `stage6.3.5-v1`.

| Endpoint | Fungsi | Status utama |
| --- | --- | --- |
| `GET /health` | Liveness worker | 200 |
| `GET /health/ready` | DB, volume, proof Stage 5 | 200/503 |
| `POST /v1/jobs` | Admission ORIGINAL_READY, hash+probe source | 201/409/422 |
| `POST /v1/jobs/{id}/approve-inference` | Persetujuan manual operator; memerlukan token kedua | 200/401/409 |
| `POST /v1/jobs/{id}/roles/{role}` | Antre satu role sesuai `next_action` | 202/409/422 |
| `GET /v1/tasks/{id}` | Poll status dan hasil task | 200 |
| `GET /v1/jobs/{id}` | State, version, next_action, gate terpisah | 200 |
| `GET /v1/jobs/{id}/artifacts` | Manifest ID, path relatif, SHA-256, byte | 200 |

`/health` tetap liveness murah dan membawa `roles_ready=false` untuk
kompatibilitas respons lama. Gunakan status dan `roles_ready` dari
`/health/ready` sebagai gate operasional; 200 hanya setelah seluruh check
service lulus. Ini tetap bukan human review atau izin production.

Admission body:

```json
{"contract_version":"stage6.3.5-v1","source_key":"tiktok:1234567890123456789","expected_sha256":"<64 lowercase hex>"}
```

Task body disalin dari `GET /v1/jobs/{id}` saat `state=AWAITING_DISPATCH`.
`input_artifact_ids` harus identik dengan `next_action.input_artifact_ids`.
Untuk ASR retry, salin pula `regions` dari `next_action` bila ada.
Panggil `/health/ready` sampai 200 setelah setiap restart service sebelum
mengirim role task; bila belum siap, POST role mengembalikan 503.

```json
{"contract_version":"stage6.3.5-v1","expected_job_version":4,"phase":"measure","attempt":0,"input_artifact_ids":["<server-issued-uuid>"]}
```

Role path dan phase: `analyst/analyze`, `av-evidence/measure`,
`speech-asr/transcribe`, `director/propose`, `validator/validate`,
`renderer/encode`, `technical-qa/inspect`, `reviewer/source_speech` atau
`reviewer/edited_output`, `revision-controller/decide`. Reviewer memakai satu
node dengan phase kondisional. `attempt=0` untuk role awal/controller/ASR,
`attempt=1..3` untuk proposal, validator, renderer, QA, dan output Reviewer.

`POST` duplikat dengan key dan digest identik mengembalikan task yang sama
(`202`) walaupun version job sudah naik. Key sama dengan input berbeda, version
lama, role berbeda dari `next_action`, atau task lain yang aktif menerima `409`.
Kontrak salah menerima `422`. Poll `GET /v1/tasks/{id}` sampai
`SUCCEEDED`, `BLOCKED`, `FAILED`, atau `RECONCILIATION_REQUIRED`; HTTP 200
pada GET tidak menyatakan QA PASS. `next_action` pada GET task adalah salinan
state job terkini, bukan instruksi yang dibuat n8n.

## Satu canvas n8n Stage 6.3.6

`ORIGINAL_READY` → Admission → GET Job → Switch `next_action.role` → salah
satu dari sembilan HTTP Request node → GET Task → Wait (misalnya 10 detik) →
GET Task hingga terminal → GET Job → Switch ulang atau berhenti pada status
terminal. Controller adalah node kesembilan dan dijadwalkan backend setelah
setiap role. Cabang Reviewer memilih phase `source_speech` atau `edited_output`.
Workflow tidak menghitung budget, memilih MP4 terbaik, atau mengirim izin render.

Persetujuan inference berada di endpoint operator terpisah dengan
`X-Operator-Token` yang berbeda dari token workflow. Body persis
`{"decision":"approve_paid_inference","human_reviewed":true}`. Node n8n
tidak memegang token operator. Tidak ada endpoint publish atau production approval.
