# AI role modules

This package belongs to the NEW `mandala-ai-editing-worker` service. Nine roles: Analyst,
AV Evidence, Speech/ASR, Director, Validator, Renderer, Technical QA, Reviewer and Revision
Controller will have separate modules and nine HTTP nodes in the same main n8n
workflow; they run in one editing container.
Stage 6.3.5 has internal job/role HTTP routes and a PostgreSQL dispatcher.
Real role executors are not connected; the TEST_ONLY mock is injected by local
integration tests, and service readiness remains false without an executor.
The permanent source Media Worker remains in `backend/media_worker/app.py`.
