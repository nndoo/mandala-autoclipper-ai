# Mandala Auto OpenClaw 9Router Video Plugin (POC)

For OpenClaw 2026.9.9 and observed 9Router 0.5.95 compatibility behavior.

### Setup (Linux, from the project root)

```bash
.venv-av/bin/python openclaw/plugins/mandala-9router-video/tools/configure_plugin.py
cd openclaw/plugins/mandala-9router-video
npm ci
npm run build
npm test
~/.local/share/mandala-openclaw-runtime/bin/openclaw plugins install --link "$PWD"
~/.local/share/mandala-openclaw-runtime/bin/openclaw infer video providers --agent mandala-video-analyst --json
```

Provider shares existing `models.providers.<custom-provider-id>` auth and URL. There is no second API key.

For a clean source build without private OpenClaw configuration, generate the
binding with `tools/configure_plugin.py --provider-id <non-secret-provider-id>`
before `npm run build`. Docker supplies that ID through `MANDALA_PROVIDER_ID`.
The generated manifest, binding and `dist/` are rebuilt rather than committed.

### Regression

The POC sends a `video/mp4` Base64 data URI in an OpenAI chat `image_url` block. That is a **9Router v0.5.95 compatibility path**, not a standard video transport. Retest on every router upgrade.

The video is read into RAM, never written to logs. Max input 20 MiB. Plugin never edits video and never publishes anything.

`tools/configure_plugin.py` generates `src/provider-id.generated.ts` and `openclaw.plugin.json` for the current local provider. Re-run it on deployment hosts with a different provider ID.
