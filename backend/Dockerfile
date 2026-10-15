# Pinned linux/amd64 manifests match the current VPS architecture.
FROM --platform=linux/amd64 node:24.21.0-bookworm-slim@sha256:51b1100cc2a83d370c6a60952e3f2989c8a43159d0e38586e090f3b3326efefd AS node-runtime

FROM --platform=linux/amd64 python:3.14.2-slim-bookworm@sha256:34bb71a7de6dbecc839d8d6f8aaff8c4bf67ce01634764eaf929cb64d3ae315e AS base

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl ffmpeg fontconfig fonts-dejavu-core libstdc++6 util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: \
    --require-hashes -r /tmp/requirements.lock.txt

FROM base AS plugin-builder
ARG MANDALA_PROVIDER_ID
COPY openclaw/plugins/mandala-9router-video /app/openclaw/plugins/mandala-9router-video
WORKDIR /app/openclaw/plugins/mandala-9router-video
RUN test -n "$MANDALA_PROVIDER_ID" \
    && python tools/configure_plugin.py --provider-id "$MANDALA_PROVIDER_ID" \
    && npm ci \
    && npm run build \
    && npm test

FROM base AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/scripts \
    MALLOC_ARENA_MAX=2 \
    PATH=/root/.local/share/mandala-openclaw-runtime/tools/node-v24.21.0/bin:/root/.local/share/mandala-openclaw-runtime/bin:/usr/local/bin:/usr/bin:/bin

COPY backend/openclaw-runtime/package.json backend/openclaw-runtime/package-lock.json /root/.local/share/mandala-openclaw-runtime/
COPY backend/openclaw-runtime/openclaw /root/.local/share/mandala-openclaw-runtime/bin/openclaw
RUN mkdir -p /root/.local/share/mandala-openclaw-runtime/tools/node-v24.21.0/bin \
    && ln -s /usr/local/bin/node /root/.local/share/mandala-openclaw-runtime/tools/node-v24.21.0/bin/node \
    && chmod 755 /root/.local/share/mandala-openclaw-runtime/bin/openclaw \
    && npm ci --omit=dev --prefix /root/.local/share/mandala-openclaw-runtime

WORKDIR /app
COPY backend /app/backend
COPY scripts /app/scripts
COPY src/schemas /app/src/schemas
COPY config /app/config
COPY openclaw/prompts /app/openclaw/prompts
COPY openclaw/agents /app/openclaw/agents
COPY openclaw/plugins/mandala-9router-video /app/openclaw/plugins/mandala-9router-video
COPY --from=plugin-builder /app/openclaw/plugins/mandala-9router-video/src/provider-id.generated.ts /app/openclaw/plugins/mandala-9router-video/src/provider-id.generated.ts
COPY --from=plugin-builder /app/openclaw/plugins/mandala-9router-video/openclaw.plugin.json /app/openclaw/plugins/mandala-9router-video/openclaw.plugin.json
COPY --from=plugin-builder /app/openclaw/plugins/mandala-9router-video/dist /app/openclaw/plugins/mandala-9router-video/dist

RUN python -m backend.runtime_check \
    && test "$(node --version)" = v24.21.0 \
    && openclaw --version | grep -F 'OpenClaw 2026.9.9' \
    && ffmpeg -hide_banner -filters > /tmp/mandala-ffmpeg-filters.txt \
    && grep -q drawtext /tmp/mandala-ffmpeg-filters.txt \
    && grep -q subtitles /tmp/mandala-ffmpeg-filters.txt \
    && rm /tmp/mandala-ffmpeg-filters.txt \
    && test -f /app/openclaw/plugins/mandala-9router-video/dist/index.js

EXPOSE 3002
CMD ["python", "-m", "backend.media_worker.app"]
