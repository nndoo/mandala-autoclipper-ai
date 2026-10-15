FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
    "yt-dlp[default,curl-cffi]==2026.8.19" \
    "curl-cffi>=0.11,<0.17" \
    "psycopg[binary]>=3.2,<4"
