import base64
import getpass
import json
import sys
import urllib.request
import urllib.error

from pathlib import Path
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parents[1]
VIDEO = PROJECT / "data/test-videos/mandala-original.mp4"
CONFIG = Path.home() / ".openclaw/openclaw.json"
MODEL = "openclaw"

def fail(message):
    print("ERROR:", message)
    sys.exit(1)

if not VIDEO.is_file():
    fail("Original MP4 tidak ditemukan")

if VIDEO.stat().st_size > 20_000_000:
    fail("Video melebihi batas POC 20 MB")

config = json.loads(CONFIG.read_text())
providers = config.get("models", {}).get("providers", {})

matches = [
    (name, data)
    for name, data in providers.items()
    if any(
        m.get("id") == MODEL
        for m in data.get("models", [])
    )
]

if len(matches) != 1:
    fail("Tidak dapat menentukan provider combo openclaw")

provider_name, provider = matches[0]
base_url = provider.get("baseUrl", "").rstrip("/")

if not base_url:
    fail("baseUrl 9Router tidak ditemukan")

parsed = urlsplit(base_url)

if parsed.scheme not in ("http", "https"):
    fail("URL provider tidak valid")

if parsed.scheme == "http" and parsed.hostname not in (
    "localhost", "127.0.0.1", "::1"
):
    fail("HTTP non-local ditolak demi keamanan API key")

endpoint = base_url + "/chat/completions"

print("=== VIDEO POC ===")
print("Provider:", provider_name)
print("Endpoint host:", parsed.hostname)
print("Model combo:", MODEL)
print("File:", VIDEO.name)
print("Video size:", round(VIDEO.stat().st_size / 1048576, 2), "MB")

key = getpass.getpass("Masukkan API key 9Router (hidden): ").strip()

if not key:
    fail("API key kosong")

video_base64 = base64.b64encode(VIDEO.read_bytes()).decode("ascii")

prompt = """
Analisis video MP4 yang dilampirkan, bukan gambar tunggal.

Jawab dalam bahasa Indonesia.

1. Apa yang terlihat pada 0-5 detik pertama?
2. Apa yang terjadi di sekitar pertengahan video?
3. Apa yang terjadi menjelang akhir video?
4. Jelaskan gerakan kamera atau perubahan adegan.
5. Jelaskan isi pembicaraan yang benar-benar terdengar.
6. Sebutkan satu kandidat hook terbaik dan timestamp-nya.

Jika video atau audio tidak dapat diakses, katakan secara eksplisit.
Jangan mengarang transkrip, adegan, timestamp, atau spesifikasi mobil.
"""

payload = {
    "model": MODEL,
    "stream": False,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "video_url",
                    "video_url": {
                        "url": "data:video/mp4;base64," + video_base64
                    }
                }
            ]
        }
    ]
}

data = json.dumps(payload).encode("utf-8")

request = urllib.request.Request(
    endpoint,
    data=data,
    method="POST",
    headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
)

print("Request size:", round(len(data) / 1048576, 2), "MB")
print("Sending video to 9Router...")
print("Timeout: 240 seconds")

try:
    with urllib.request.urlopen(request, timeout=240) as response:
        body = response.read()
        status = response.status
        content_type = response.headers.get("Content-Type", "")

except urllib.error.HTTPError as error:
    raw = error.read(8192).decode("utf-8", errors="replace")
    try:
        parsed_error = json.loads(raw)
        details = parsed_error.get("error", {})
        message = (
            details.get("message", "")
            if isinstance(details, dict)
            else str(details)
        )
    except ValueError:
        message = "Non-JSON HTTP error response"

    print("HTTP STATUS:", error.code)
    print("ERROR:", str(message).replace(key, "[REDACTED]")[:1000])
    sys.exit(1)

except Exception as error:
    print("TRANSPORT ERROR:", type(error).__name__)
    sys.exit(1)

print("HTTP STATUS:", status)
print("CONTENT TYPE:", content_type)

if "text/event-stream" in content_type:
    parts = []
    for line in body.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data: "):
            continue
        value = line[6:]
        if value == "[DONE]":
            continue
        try:
            event = json.loads(value)
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                text = delta.get("content", "")
                if isinstance(text, str):
                    parts.append(text)
        except ValueError:
            pass
    answer = "".join(parts)
    result = {}
else:
    try:
        result = json.loads(body)
    except ValueError:
        fail("Respons bukan JSON valid")

    choices = result.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    answer = message.get("content", "")

    if isinstance(answer, list):
        answer = "\n".join(
            item.get("text", "")
            for item in answer
            if isinstance(item, dict)
        )

    print("Response model:", result.get("model", "unknown"))
    print("Usage:", result.get("usage", "not provided"))

print()
print("========== MODEL RESPONSE ==========")
print(str(answer).replace(key, "[REDACTED]")[:12000])
print("========== END RESPONSE ==========")

if not answer:
    fail("Tidak ada konten jawaban dari model")
