# Working on Mandala Auto

Mandala's current implementation is a Python video pipeline plus an OpenClaw TypeScript adapter. Start with source and documentation for the component being changed. README services describe intended architecture; verify a service connection before treating it as operational.

## Environments and checks

- Use `.venv-av/bin/python` for media analysis, rendering, QA, and Python tests. It supplies NumPy, SciPy, and jsonschema; the system Python does not supply the numerical packages.
- The tested video inference runtime is `~/.local/share/mandala-openclaw-runtime/bin/openclaw`, with its bundled Node under `~/.local/share/mandala-openclaw-runtime/tools/`. Verify the runtime selected by existing runners rather than assuming `openclaw` or `node` on PATH is equivalent.
- Python tests use unittest. Run the affected suite, for example `.venv-av/bin/python -m unittest discover -s tests -p 'test_video_quality_v01.py'`. Use `-p 'test_*.py'` for full regression when justified. Files named `poc_*` are live experiments, not ordinary offline tests.
- Run `ruff check scripts tests` for conservative checks configured in `ruff.toml`. Fix findings within the requested scope; do not bulk-format legacy code.
- For adapter changes, work in `openclaw/plugins/mandala-9router-video`, use the existing TypeScript compiler and `npm test`. A read-only type check is `node_modules/.bin/tsc --noEmit`; rebuild generated dist files when implementation changes.

## Evidence and media workflow

- JSON Schemas are in `src/schemas`; model instructions are in `openclaw/prompts`. OpenClaw agent workspaces have their own AGENTS.md files, distinct from these Codex contributor instructions.
- Receipts bind source, media, configuration, and sometimes code hashes. Check affected receipt producers/validators before changing a contract. Historical artifacts remain evidence of their original code, not proof of the current implementation.
- Use new output bundles through existing exclusive writers. Keep original media and historical canonical evidence intact; do not overwrite a prior bundle to make validation pass.
- Structural validation, generated transcript timing, model-reported observations, technical decode success, human editorial review, and production/publishing authorization are separate outcomes. Report the actual status of each. Model self-report is not independent verification.
- The default speech backend is remote. Optional local Whisper workers are not evidence that a model/runtime is installed. Read `docs/remote-speech-asr-v01.md` before speech/timestamp changes.
- The adapter's video-in-image_url payload is a tested 9Router compatibility path. Verify transport and semantic validation if upgrading router/runtime; do not assume every OpenAI-compatible endpoint accepts that payload.

## Tools and references

- Use `mandala-video-workflow` for pipeline, evidence, rendering, and QA tasks; it routes to relevant project documentation.
- For n8n workflow work, load `using-n8n-skills-official` and relevant capability guidance. Skills do not establish authenticated access to an instance.
- For Cloudinary integration/delivery URLs, use `cloudinary-docs` or `cloudinary-transformations`. Context7 can retrieve indexed library APIs by version; use source SDK/docs when coverage is missing.
- Use installed security skills for requested security review or relevant secure implementation work. Use REA for shipped applications/binaries or requested runtime evidence; inspect repository source directly for ordinary development.
- Connection credentials belong in existing environment/private configuration mechanisms. Reports and test logs must not print tokens, secret file contents, or credential-bearing URLs.
