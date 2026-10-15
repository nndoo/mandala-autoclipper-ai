#!/usr/bin/env python3

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "src/schemas/"
    "universal-video-analysis.v0.2.schema.json"
)

def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def speech_consistency(data):
    """Check model classifications and interval coverage, without acoustic verification."""
    duration = data["source"]["duration_sec"]
    covered_until = 0
    gaps = []
    intervals = sorted((s["start_sec"], s["end_sec"]) for s in data["segments"])
    for start, end in intervals:
        if not 0 <= start < end <= duration:
            continue
        if start > covered_until:
            gaps.append({"start_sec": covered_until, "end_sec": start})
        covered_until = max(covered_until, end)
    if covered_until < duration:
        gaps.append({"start_sec": covered_until, "end_sec": duration})
    segments = data["segments"]
    speech = any("speech" in s["audio_layers"] for s in segments)
    unknown = any(not s["audio_layers"] or "unknown" in s["audio_layers"] for s in segments)
    profile = data["content_profile"]["speech_presence"]
    conflicts = []
    if profile == "absent" and speech:
        conflicts.append("absent_profile_with_regional_speech")
    if profile == "present" and not gaps and not speech and not unknown and data["analysis_meta"]["audio_examined"]:
        conflicts.append("present_profile_without_regional_speech")
    return {
        "classification_conflicts": conflicts,
        "temporal_coverage": {"status": "incomplete" if gaps else "complete", "uncovered_regions": gaps},
    }


def validate_analysis(data, schema):
    errors = []
    warnings = []

    validator = Draft202012Validator(schema)

    for issue in validator.iter_errors(data):
        location = ".".join(str(x) for x in issue.path)
        errors.append(
            f"{location or 'root'}: {issue.message}"
        )

    if errors:
        return errors, warnings

    duration = data["source"]["duration_sec"]

    def check_window(item, label, allow_instant=False):
        start = item.get("start_sec")
        end = item.get("end_sec")

        if not is_number(start) or not is_number(end):
            errors.append(f"{label}: Missing numeric timestamp")
            return

        if start > duration or end > duration:
            errors.append(
                f"{label}: Timestamp exceeds source duration"
            )

        if end < start:
            errors.append(f"{label}: End precedes start")

        if end == start and not allow_instant:
            errors.append(f"{label}: Zero-duration interval")

    for collection in (
        "segments",
        "events",
        "editing_opportunities"
    ):
        for index, item in enumerate(data[collection]):
            check_window(
                item,
                f"{collection}[{index}]",
                allow_instant=(collection == "events")
            )

    for index, issue in enumerate(data["quality_issues"]):
        start = issue.get("start_sec")
        end = issue.get("end_sec")

        if start is None and end is None:
            continue

        if start is None or end is None:
            warnings.append(
                f"quality_issues[{index}]: "
                "Partial timing requires review"
            )
            continue

        check_window(
            issue,
            f"quality_issues[{index}]"
        )

    segment_ids = [
        segment["segment_id"]
        for segment in data["segments"]
    ]

    duplicates = [
        sid for sid, count in Counter(segment_ids).items()
        if count > 1
    ]

    if duplicates:
        errors.append(
            f"Duplicate segment IDs: {duplicates}"
        )

    profile = data["content_profile"]
    layers = {
        layer
        for segment in data["segments"]
        for layer in segment["audio_layers"]
    }

    consistency = speech_consistency(data)
    if "absent_profile_with_regional_speech" in consistency["classification_conflicts"]:
        warnings.append(
            "Speech marked absent but speech audio layer exists"
        )
    if "present_profile_without_regional_speech" in consistency["classification_conflicts"]:
        warnings.append("Speech marked present but complete known audio regions contain no speech")
    if consistency["temporal_coverage"]["status"] == "incomplete":
        warnings.append("Speech review required: incomplete segment temporal coverage")

    if (
        profile["music_presence"] == "absent"
        and "music" in layers
    ):
        warnings.append(
            "Music marked absent but music audio layer exists"
        )

    meta = data["analysis_meta"]

    if (
        not meta["audio_examined"]
        and (
            profile["speech_presence"] == "present"
            or profile["music_presence"] == "present"
        )
    ):
        warnings.append(
            "Audio presence reported without audio examination"
        )

    if not meta["video_examined"]:
        warnings.append(
            "Video has not been directly examined"
        )

    if not data["segments"]:
        warnings.append(
            "No analyzed segments available"
        )

    warnings.append(
        "Schema validation does not verify audiovisual facts "
        "or frame-accurate timing"
    )

    return errors, warnings


def sample_analysis():
    return {
        "schema_version": "0.2.0",
        "analysis_status": "DRAFT_UNVERIFIED",
        "source": {
            "video_id": "synthetic-cinematic-test",
            "duration_sec": 26.53
        },
        "analysis_meta": {
            "video_examined": True,
            "audio_examined": True,
            "asr_used": False,
            "timing_precision": "approximate",
            "limitations": [
                "Synthetic test fixture, not actual media analysis"
            ]
        },
        "content_profile": {
            "summary": "Synthetic vehicle showcase test",
            "content_tags": ["showcase"],
            "speech_presence": "absent",
            "music_presence": "present",
            "editorial_goal_suggestions": [
                "Visual storytelling"
            ]
        },
        "segments": [
            {
                "segment_id": "scene-01",
                "start_sec": 0,
                "end_sec": 10,
                "visual_description": "Vehicle showcase",
                "audio_description": "Music",
                "audio_layers": ["music"],
                "confidence": "medium"
            }
        ],
        "events": [],
        "editing_opportunities": [
            {
                "opportunity_type": "visual_hook",
                "start_sec": 2,
                "end_sec": 6,
                "reason": "Synthetic test opportunity",
                "score": 8,
                "confidence": "medium",
                "timing_basis": "model_estimate"
            }
        ],
        "claims": [],
        "quality_issues": []
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument(
        "--self-test",
        action="store_true"
    )
    args = parser.parse_args()

    schema = json.loads(
        SCHEMA_PATH.read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(schema)

    if args.self_test:
        sample = sample_analysis()

        errors, warnings = validate_analysis(
            sample, schema
        )

        print("=== VALID SYNTHETIC SAMPLE ===")
        print("Errors:", len(errors))
        print("Warnings:", len(warnings))

        if errors:
            print(*errors, sep="\n")
            raise SystemExit(1)

        invalid = json.loads(json.dumps(sample))
        invalid["editing_opportunities"][0]["end_sec"] = 30

        errors, _ = validate_analysis(
            invalid, schema
        )

        print("\n=== INVALID TIMESTAMP TEST ===")
        print("Detected errors:", len(errors))

        for issue in errors:
            print("-", issue)

        if not errors:
            raise SystemExit(
                "FAIL: Invalid timestamp was accepted"
            )

        print("\nSELF-TEST: PASS")
        return

    if args.input is None:
        parser.error("Provide --input or --self-test")

    data = json.loads(
        args.input.read_text(encoding="utf-8")
    )

    errors, warnings = validate_analysis(
        data, schema
    )

    print("=== UNIVERSAL ANALYSIS VALIDATOR V0.2 ===")
    print("Status:", "BLOCKED" if errors else "NEEDS_REVIEW")
    print("Errors:", len(errors))
    print("Warnings:", len(warnings))

    for issue in errors:
        print("ERROR:", issue)

    for issue in warnings:
        print("WARNING:", issue)

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
