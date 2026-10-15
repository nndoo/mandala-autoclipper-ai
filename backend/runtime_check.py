"""Offline image inventory; never print credential values or contact a provider."""

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path('/app')
RUNTIME = Path.home() / '.local/share/mandala-openclaw-runtime'
PACKAGES = {
    'numpy': '2.5.4',
    'scipy': '1.18.1',
    'jsonschema': '4.25.1',
    'psycopg': '3.3.6',
    'yt-dlp': '2026.8.19',
    'curl-cffi': '0.16.3',
}
FILES = (
    'scripts/build_adaptive_director_input_v03.py',
    'src/schemas/adaptive-director-input.v0.3.schema.json',
    'openclaw/prompts/universal-video-analysis-v02.md',
    'openclaw/prompts/adaptive-creative-director-v03.md',
    'openclaw/plugins/mandala-9router-video/dist/index.js',
    'openclaw/plugins/mandala-9router-video/openclaw.plugin.json',
)


def inspect(*, check_storage=False, require_service_env=False):
    errors = []
    if sys.version_info[:3] != (3, 14, 2):
        errors.append('Python version mismatch')
    versions = {}
    for name, expected in PACKAGES.items():
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
        if versions[name] != expected:
            errors.append(f'{name} version mismatch or missing')
    for name in ('node', 'ffmpeg', 'ffprobe', 'prlimit'):
        if shutil.which(name) is None:
            errors.append(f'{name} unavailable')
    for relative in FILES:
        if not (ROOT / relative).is_file():
            errors.append(f'{relative} missing')
    for font in ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf'):
        if not (Path('/usr/share/fonts/truetype/dejavu') / font).is_file():
            errors.append(f'{font} missing')
    if not (RUNTIME / 'bin/openclaw').is_file():
        errors.append('OpenClaw wrapper missing')
    if not (RUNTIME / 'tools/node-v24.21.0/bin/node').is_file():
        errors.append('Isolated Node path missing')
    if not (RUNTIME / 'node_modules/openclaw/openclaw.mjs').is_file():
        errors.append('OpenClaw package missing')

    provider_id = os.getenv('AUTOCLIPPER_OPENCLAW_PROVIDER_ID')
    manifest = ROOT / 'openclaw/plugins/mandala-9router-video/openclaw.plugin.json'
    if provider_id and manifest.is_file():
        try:
            configured = json.loads(manifest.read_text())['contracts']['mediaUnderstandingProviders']
            if configured != [provider_id]:
                errors.append('9Router provider ID differs from image manifest')
        except (ValueError, KeyError, TypeError):
            errors.append('9Router manifest invalid')
    if require_service_env:
        for name in ('PGHOST', 'PGUSER', 'PGPASSWORD'):
            if not os.getenv(name):
                errors.append(f'{name} missing')
        for name, default in (('PGPORT', '5432'), ('AUTOCLIPPER_WORKER_PORT', '3002')):
            try:
                if not 1 <= int(os.getenv(name, default)) <= 65535:
                    raise ValueError
            except ValueError:
                errors.append(f'{name} invalid')
    if check_storage:
        root = Path(os.getenv('AUTOCLIPPER_SOURCE_ROOT', '/data/source'))
        if not root.is_relative_to('/data'):
            errors.append('Source storage path outside /data')
        else:
            try:
                with tempfile.TemporaryFile(dir=root.parent):
                    pass
            except OSError:
                errors.append('Persistent storage is not writable')

    return {'status': 'PASS' if not errors else 'BLOCKED',
            'python': sys.version.split()[0], 'packages': versions, 'errors': errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-storage', action='store_true')
    parser.add_argument('--require-service-env', action='store_true')
    args = parser.parse_args()
    result = inspect(check_storage=args.check_storage,
                     require_service_env=args.require_service_env)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
