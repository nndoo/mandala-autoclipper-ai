"""Stage 3 ORIGINAL_READY MP4 to Stage 5 source metadata, without media copying."""

import math
import re
import sys
from pathlib import Path

from backend.media_worker.config import ROOT, USERNAME

# Stage 5 scripts predate a Python package and import one another by bare name.
# Keep their source untouched while reusing the tested probe/schema/receipt gate.
SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import build_adaptive_director_input_v03 as stage5  # noqa: E402


MAX_POC_BYTES = 20 * 1024 * 1024
MAX_POC_DURATION_SEC = 180
MIN_VIDEO_BYTES = 1024


class IntakeError(ValueError):
    """The Stage 3 original cannot be admitted to the Stage 5 POC."""


def _positive_number(value, label):
    if isinstance(value, bool):
        raise IntakeError(f'Invalid {label}')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise IntakeError(f'Invalid {label}') from None
    if not math.isfinite(number) or number <= 0:
        raise IntakeError(f'Invalid {label}')
    return number


def _dimension(value, label):
    if type(value) is not int or value <= 0:
        raise IntakeError(f'Invalid {label}')
    return value


def prepare_intake(record, *, storage_root=ROOT, expected_username=USERNAME,
                   verified_mirror_path=None, stage5_video_path=None):
    """Verify an ORIGINAL_READY DB row and return source-bound Stage 5 inputs.

    This is a pure admission/read operation. It does not write a sidecar, copy
    media, reserve a job, or call an external service. The caller must persist
    the returned metadata with an exclusive, source-bound job writer later.
    `verified_mirror_path` is for an explicitly trusted, pre-existing local
    copy during offline compatibility checks. It never overrides the Stage 3
    logical path check, and its bytes must pass the same size/hash/probe gates.
    """
    if not isinstance(record, dict):
        raise IntakeError('Expected Stage 3 source record')
    video_id = record.get('video_id')
    if not isinstance(video_id, str) or not re.fullmatch(r'\d{15,25}', video_id):
        raise IntakeError('Invalid Stage 3 video_id')
    if (record.get('platform') != 'tiktok' or
            record.get('username') != expected_username or
            record.get('source_key') != f'tiktok:{video_id}' or
            record.get('status') != 'ORIGINAL_READY'):
        raise IntakeError('Stage 3 source identity or state mismatch')

    digest = record.get('original_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise IntakeError('Invalid Stage 3 SHA-256')
    size = record.get('original_size_bytes')
    if type(size) is not int or not MIN_VIDEO_BYTES <= size <= MAX_POC_BYTES:
        raise IntakeError('Stage 3 original exceeds POC size limit or is too small')

    duration = _positive_number(record.get('original_duration_seconds'), 'Stage 3 duration')
    if duration > MAX_POC_DURATION_SEC:
        raise IntakeError('Stage 3 original exceeds POC duration limit')
    width = _dimension(record.get('original_width'), 'Stage 3 width')
    height = _dimension(record.get('original_height'), 'Stage 3 height')

    logical_root = Path(storage_root)
    if not logical_root.is_absolute() or '..' in logical_root.parts:
        raise IntakeError('Invalid persistent source root')
    expected_path = logical_root / 'originals' / f'{video_id}.mp4'
    if str(expected_path) != record.get('original_local_path'):
        raise IntakeError('Original path does not match Stage 3 metadata')
    if verified_mirror_path is None:
        try:
            root = logical_root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise IntakeError('Persistent source root is unavailable') from None
        if not root.is_dir() or root != logical_root:
            raise IntakeError('Persistent source root is unsafe')
        original = expected_path
    else:
        original = Path(verified_mirror_path)
        if not original.is_absolute():
            raise IntakeError('Verified mirror path must be absolute')
    if original.is_symlink() or not original.is_file():
        raise IntakeError('Original MP4 missing or unsafe')
    resolved = original.resolve(strict=True)
    if verified_mirror_path is None and not resolved.is_relative_to(root):
        raise IntakeError('Original path escapes persistent source root')
    before = original.stat()
    if before.st_size != size:
        raise IntakeError('Original size differs from Stage 3 metadata')

    try:
        probed = stage5.probe_video(original)
        if probed['duration_sec'] > MAX_POC_DURATION_SEC:
            raise IntakeError('Probed source exceeds POC duration limit')
        if (probed['duration_sec'] != stage5.rounded_metadata(duration) or
                probed['width'] != width or probed['height'] != height):
            raise IntakeError('Stage 3 duration or resolution differs from FFprobe')
        if 'fps' in record and probed['fps'] != stage5.rounded_metadata(
            _positive_number(record['fps'], 'Stage 3 FPS')
        ):
            raise IntakeError('Stage 3 FPS differs from FFprobe')
        source = {'video_id': 'local-sha256-' + digest[:32], **probed}
        metadata = {
            'source': source.copy(),
            'verification': {
                'method': 'ffprobe_and_sha256',
                'file_name': original.name,
                'sha256': digest,
            },
        }
        source_schema = stage5.load_schema('adaptive-director-input.v0.3.schema.json')['properties']['source']
        verified_source, verified_digest = stage5.verify_source(original, metadata, source_schema)
    except stage5.AdapterError as exc:
        raise IntakeError(str(exc)) from None

    after = original.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise IntakeError('Original changed during intake')
    if verified_digest != digest or verified_source != source:
        raise IntakeError('Stage 5 source verification mismatch')
    project_video = None
    if stage5_video_path is not None:
        try:
            project_video = stage5.project_path(stage5_video_path, 'Stage 5 source MP4')
        except stage5.AdapterError as exc:
            raise IntakeError(str(exc)) from None
        alias = project_video.stat()
        if (alias.st_dev, alias.st_ino, alias.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise IntakeError('Stage 5 path is not the same original file')
    return {
        'source_key': record['source_key'],
        'upstream_video_id': video_id,
        'original_path': str(original),
        'stage3_original_path': str(expected_path),
        'stage5_video_path': str(project_video) if project_video is not None else None,
        'original_size_bytes': size,
        'source': source,
        'metadata': metadata,
    }


def validate_canonical_analysis(intake_result, analysis):
    """Gate later Analyst output against the Stage 5 schema and intake source.

    Intake creates no AI findings. A separately generated canonical analysis
    must pass this check before Stage 5 evidence consumers can use it.
    """
    if not isinstance(intake_result, dict) or not isinstance(analysis, dict):
        raise IntakeError('Expected intake and canonical analysis objects')
    schema = stage5.load_schema('universal-video-analysis.v0.2.schema.json')
    errors, warnings = stage5.validate_analysis(analysis, schema)
    if errors:
        raise IntakeError('Stage 5 canonical analysis validation blocked')
    if analysis['source'] != intake_result.get('source'):
        raise IntakeError('Canonical analysis source metadata mismatch')
    return warnings
