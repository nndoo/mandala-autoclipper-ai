#!/usr/bin/env python3

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RAW = ROOT / (
    "data/analyses/universal/"
    "cinematic-universal-v02-20261011-195206-3209.json"
)

META = ROOT / (
    "data/analyses/universal/"
    "cinematic-7693770515172887829.media.json"
)

VIDEO = ROOT / (
    "data/test-videos/"
    "cinematic-7693770515172887829.mp4"
)

OUT = ROOT / (
    "data/analyses/universal/"
    "cinematic-universal-v02.normalized.json"
)

def find_analysis(value, depth=0):
    if depth > 12:
        return None

    if isinstance(value, dict):
        if value.get("schema_version") == "0.2.0":
            return value

        for nested in value.values():
            found = find_analysis(nested, depth + 1)
            if found is not None:
                return found

    elif isinstance(value, list):
        for nested in value:
            found = find_analysis(nested, depth + 1)
            if found is not None:
                return found

    elif isinstance(value, str):
        text = value.strip()

        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1]).strip()

        try:
            return find_analysis(json.loads(text), depth + 1)
        except (ValueError, TypeError):
            return None

    return None


def main():
    if OUT.exists():
        raise SystemExit("STOP: Output sudah ada. Tidak ditimpa.")

    for path in (RAW, META, VIDEO):
        if not path.is_file():
            raise SystemExit(f"STOP: Missing file: {path}")

    response = json.loads(RAW.read_text(encoding="utf-8"))
    metadata = json.loads(META.read_text(encoding="utf-8"))

    analysis = find_analysis(response)

    if analysis is None:
        raise SystemExit("STOP: Universal Analysis V0.2 not found.")

    analysis = copy.deepcopy(analysis)

    print("=== VERIFY SOURCE HASH ===")

    with VIDEO.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()

    expected = metadata["verification"]["sha256"]

    if digest != expected:
        raise SystemExit("STOP: Source SHA-256 mismatch.")

    if metadata["verification"]["file_name"] != VIDEO.name:
        raise SystemExit("STOP: Source filename mismatch.")

    print("SHA-256: MATCH")

    print("\n=== NORMALIZE SEGMENTS ===")

    segments = analysis.get("segments")

    if isinstance(segments, dict):
        expected_keys = {str(i) for i in range(len(segments))}

        if set(segments) != expected_keys:
            raise SystemExit(
                "STOP: Segment keys are not contiguous zero-based indexes."
            )

        analysis["segments"] = [
            segments[str(i)] for i in range(len(segments))
        ]

        print("Converted indexed object to array")

    elif isinstance(segments, list):
        print("Already an array")

    else:
        raise SystemExit("STOP: Unsupported segments format.")

    print("Segments:", len(analysis["segments"]))

    print("\n=== NORMALIZE SOURCE METADATA ===")

    previous_source = analysis.get("source")

    analysis["source"] = copy.deepcopy(metadata["source"])

    print("AI source:", previous_source)
    print("Verified source:", analysis["source"])

    # Save as an unverified draft, never as an approved analysis.
    analysis["analysis_status"] = "DRAFT_UNVERIFIED"

    with OUT.open("x", encoding="utf-8") as file:
        json.dump(
            analysis,
            file,
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")

    print("\nNormalized output:", OUT)

    print("\n=== RUN UNIVERSAL VALIDATOR ===")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate_universal_analysis_v02.py"),
            "--input",
            str(OUT)
        ],
        cwd=ROOT,
        capture_output=True,
        text=True
    )

    print(result.stdout)

    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise SystemExit(
            "VALIDATION BLOCKED: Review errors before proceeding."
        )

    print("=== NORMALIZATION COMPLETE ===")
    print("NOTE: Audiovisual facts still require review.")


if __name__ == "__main__":
    main()
