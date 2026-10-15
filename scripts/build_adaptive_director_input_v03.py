#!/usr/bin/env python3
"""Package source-bound evidence offline; relative CLI paths start at project root."""

import argparse
import hashlib
import json
import math
import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from validate_universal_analysis_v02 import validate_analysis

ROOT = Path(__file__).resolve().parents[1]
MAX_METADATA_BYTES = 1024 * 1024
PROBE_TIMEOUT_SEC = 30


class AdapterError(ValueError):
    """A blocking validation or provenance failure."""


def bounded_run(command, consume, *, max_bytes, timeout):
    """Stream bounded stdout; discard diagnostics rather than buffer untrusted stderr."""
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise AdapterError(f"{command[0]} is unavailable") from None
    deadline = time.monotonic() + timeout
    total = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                raise AdapterError("Media subprocess timeout exceeded")
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise AdapterError("Media subprocess output resource limit exceeded")
            consume(chunk)
        try:
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise AdapterError("Media subprocess timeout exceeded") from None
        if code != 0:
            raise AdapterError("Media subprocess failed; raw diagnostics suppressed")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
    return total


def small_output(command, *, max_bytes=MAX_METADATA_BYTES, timeout=PROBE_TIMEOUT_SEC):
    output = bytearray()
    bounded_run(command, output.extend, max_bytes=max_bytes, timeout=timeout)
    try:
        return output.decode("utf-8")
    except UnicodeDecodeError:
        raise AdapterError("Media subprocess returned invalid UTF-8 output") from None


def project_path(value, label, *, output=False):
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise AdapterError(f"{label}: path escapes project root (including symlinks)")
    if output:
        if candidate.exists() or candidate.is_symlink():
            raise AdapterError("Output already exists; refusing to overwrite")
    elif not resolved.is_file():
        raise AdapterError(f"{label}: required file is missing or not a regular file")
    return resolved


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite JSON number")
    return number


def reject_constant(_value):
    raise ValueError("Nonfinite JSON constant")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def load_object(path, label):
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=finite_float,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (ValueError, UnicodeError):
        raise AdapterError(f"{label}: invalid JSON, duplicate keys, or nonfinite numbers") from None
    if not isinstance(data, dict):
        raise AdapterError(f"{label}: expected a JSON object")
    return data


def validate_object(data, schema, label):
    issue = next(Draft202012Validator(schema).iter_errors(data), None)
    if issue is not None:
        location = ".".join(map(str, issue.path)) or "root"
        # Schema error messages can echo arbitrary input values; log only location/rule.
        raise AdapterError(f"{label}: schema violation at {location} ({issue.validator})")


def load_schema(name):
    schema = load_object(project_path(Path("src/schemas") / name, "Schema"), "Schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise AdapterError("Schema: invalid JSON Schema") from None
    return schema


def rounded_metadata(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("Invalid positive metadata number")
    # Match media-metadata.ts: Math.round(value * 1000) / 1000, not bankers' rounding.
    return math.floor(number * 1000 + 0.5) / 1000


def probe_video(video):
    try:
        output = small_output(
            [
                "ffprobe", "-v", "error", "-protocol_whitelist", "file",
                "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate",
                "-of", "json", str(video),
            ],
            max_bytes=MAX_METADATA_BYTES, timeout=PROBE_TIMEOUT_SEC,
        )
    except AdapterError as error:
        raise AdapterError("FFprobe metadata inspection blocked: " + str(error)) from None
    try:
        data = json.loads(output)
        stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
        rate = stream["avg_frame_rate"].split("/")
        fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 else float(stream["avg_frame_rate"])
        width, height = stream["width"], stream["height"]
        if any(type(n) is not int or n <= 0 for n in (width, height)):
            raise ValueError("Invalid resolution")
        return {
            "duration_sec": rounded_metadata(data["format"]["duration"]),
            "width": width,
            "height": height,
            "fps": rounded_metadata(fps),
        }
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration, ZeroDivisionError, OverflowError):
        raise AdapterError("FFprobe returned invalid video metadata") from None


def verify_source(video, metadata, source_schema):
    validate_object(metadata.get("source"), source_schema, "Metadata source")
    verification = metadata.get("verification")
    if not isinstance(verification, dict) or verification.get("method") != "ffprobe_and_sha256":
        raise AdapterError("Metadata verification method must be ffprobe_and_sha256")
    with video.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if verification.get("sha256") != digest:
        raise AdapterError("Source SHA-256 mismatch")
    if verification.get("file_name") != video.name:
        raise AdapterError("Source filename mismatch")
    video_id = "local-sha256-" + digest[:32]
    if metadata["source"]["video_id"] != video_id:
        raise AdapterError("Metadata source ID does not correspond to content hash")
    verified = {"video_id": video_id, **probe_video(video)}
    validate_object(verified, source_schema, "Probed source")
    if metadata["source"] != verified:
        raise AdapterError("Metadata source differs from FFprobe duration, resolution, or FPS")
    return metadata["source"], digest


def write_exclusive(output, text):
    """Publish a complete file with an atomic no-clobber hard link on local Linux."""
    output.parent.mkdir(parents=True, exist_ok=True)
    project_path(output, "Output", output=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=".adaptive-input-", suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        # Unlike rename/replace, link fails if another process created the output.
        os.link(temporary, output)
    except FileExistsError:
        raise AdapterError("Output already exists; refusing to overwrite") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_director_input(video, metadata, analysis, output):
    video = project_path(video, "Source MP4")
    metadata_path = project_path(metadata, "Metadata sidecar")
    analysis_path = project_path(analysis, "Canonical analysis")
    output = project_path(output, "Output", output=True)
    universal_schema = load_schema("universal-video-analysis.v0.2.schema.json")
    adaptive_schema = load_schema("adaptive-director-input.v0.3.schema.json")
    metadata = load_object(metadata_path, "Metadata sidecar")
    analysis = load_object(analysis_path, "Canonical analysis")

    errors, warnings = validate_analysis(analysis, universal_schema)
    if errors:
        validate_object(analysis, universal_schema, "Universal analysis")
        # Semantic errors are controlled validator messages, except duplicate ID values.
        safe_errors = ["Duplicate segment IDs" if e.startswith("Duplicate segment IDs:") else e for e in errors]
        raise AdapterError("Universal analysis blocked: " + "; ".join(safe_errors))

    source, digest = verify_source(video, metadata, adaptive_schema["properties"]["source"])
    if analysis["source"] != source:
        raise AdapterError("Canonical analysis source metadata mismatch")

    if analysis["analysis_meta"]["timing_precision"] != "approximate":
        warnings.append("No independent timing evidence attached; universal artifact precision remains approximate")
    payload = {
        "contract_version": "0.3.0",
        "source": source,
        "evidence": {
            "universal_analysis": {
                "path": analysis_path.relative_to(ROOT).as_posix(),
                "timing_precision": "approximate",
            },
            "transcript": None,
            "speech_alignment": None,
            "music_rhythm": None,
            "visual_timing": None,
        },
        "editorial_policy": {
            "goal": "Develop content-adaptive editing proposals from available evidence",
            "max_variants": 2,
            "allow_fewer_variants": True,
            "preserve_complete_utterances": True,
            "allow_unverified_claims": False,
            "render_approved": False,
            "publish_approved": False,
        },
        "renderer_capabilities": {
            "verification_status": "unknown",
            "supported_operations": [],
        },
    }
    validate_object(payload, adaptive_schema, "Adaptive Director Input V0.3")
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    write_exclusive(output, text)
    return {
        "status": "NEEDS_REVIEW",
        "contract_version": "0.3.0",
        "output": output.relative_to(ROOT).as_posix(),
        "source": source,
        "source_sha256": digest,
        "inputs": {
            "video": video.relative_to(ROOT).as_posix(),
            "metadata": metadata_path.relative_to(ROOT).as_posix(),
            "analysis": analysis_path.relative_to(ROOT).as_posix(),
        },
        "warnings": warnings,
        "render_approved": False,
        "publish_approved": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--video", required=True, type=Path, help="Source MP4")
    parser.add_argument("--metadata", required=True, type=Path, help="FFprobe/SHA-256 metadata sidecar")
    parser.add_argument("--analysis", required=True, type=Path, help="Canonical Universal V0.2 JSON")
    parser.add_argument("--output", required=True, type=Path, help="New Director Input V0.3 JSON (never overwritten)")
    args = parser.parse_args(argv)
    try:
        report = build_director_input(args.video, args.metadata, args.analysis, args.output)
    except AdapterError as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}), file=sys.stderr)
        return 1
    except OSError as error:
        print(json.dumps({"status": "BLOCKED", "error": f"Filesystem failure: {error.strerror}"}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
