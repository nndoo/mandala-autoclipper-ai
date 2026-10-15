# AI role modules

This package belongs to the NEW `mandala-ai-editing-worker` service. Nine roles: Analyst,
AV Evidence, Speech/ASR, Director, Validator, Renderer, Technical QA, Reviewer and Revision
Controller will have separate modules and nine HTTP nodes in the same main n8n
workflow; they run in one editing container.
No role/job endpoint is active yet; `backend/editing_worker.py` provides the
runtime-only health entrypoint. The permanent source Media Worker remains on its
existing VPS service, with its preserved local source in `backend/media_worker/app.py`.
