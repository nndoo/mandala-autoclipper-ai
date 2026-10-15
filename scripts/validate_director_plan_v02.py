#!/usr/bin/env python3

import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INPUT = ROOT / "data/analyses/director/director-run-02.response.json"
OUTPUT = ROOT / "data/analyses/director/director-run-02.validation.json"
WHISPER = ROOT / "data/analyses/mandala-whisper.json"
VIDEO = ROOT / "data/test-videos/mandala-original.mp4"

if OUTPUT.exists():
    raise SystemExit("STOP: Validation report sudah ada.")

def number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )

response = json.loads(INPUT.read_text(encoding="utf-8"))
content = response["payloads"][0]["text"].strip()

if content.startswith("```"):
    lines = content.splitlines()
    if lines[-1].strip() == "```":
        content = "\n".join(lines[1:-1]).strip()

plan = json.loads(content)

whisper = json.loads(WHISPER.read_text(encoding="utf-8"))

probe = subprocess.run(
    [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(VIDEO)
    ],
    capture_output=True,
    text=True,
    check=True,
    timeout=30
)

duration = float(json.loads(probe.stdout)["format"]["duration"])

errors = []
warnings = []
variant_results = []

words = []

for segment in whisper.get("segments", []):
    for word in segment.get("words", []):
        a = word.get("start_sec")
        b = word.get("end_sec")

        if number(a) and number(b) and 0 <= a < b:
            words.append({
                "start": a,
                "end": b,
                "text": word.get("word", "").strip()
            })

if plan.get("plan_status") != "DRAFT_UNVALIDATED":
    errors.append("Unexpected plan_status")

reported_duration = plan.get("source_duration_sec")

if not number(reported_duration) or abs(reported_duration - duration) > 0.1:
    errors.append("Source duration mismatch")

variants = plan.get("variants")

if not isinstance(variants, list) or len(variants) != 2:
    errors.append("Expected exactly two variants")
    variants = []

seen_ids = set()

for variant in variants:
    if not isinstance(variant, dict):
        errors.append("Variant must be an object")
        continue

    vid = variant.get("variant_id")
    normalized = {
        "A": "A",
        "B": "B",
        "variant_a": "A",
        "variant_b": "B"
    }.get(vid)

    if normalized is None or normalized in seen_ids:
        errors.append(f"Invalid or duplicate variant ID: {vid}")
    else:
        seen_ids.add(normalized)

    if vid not in ("A", "B"):
        warnings.append(f"{vid}: Variant ID differs from original A/B contract")

    shots = variant.get("shots")

    if not isinstance(shots, list) or not shots:
        errors.append(f"{vid}: Missing shots")
        continue

    calculated = 0.0
    shot_results = []
    last_end = None

    for index, shot in enumerate(shots, 1):
        label = f"{vid}/shot-{index}"

        if not isinstance(shot, dict):
            errors.append(f"{label}: Invalid shot object")
            continue

        start = shot.get("source_start_sec")
        end = shot.get("source_end_sec")
        timing = shot.get("timing")

        if not number(start) or not number(end) or not 0 <= start < end <= duration:
            errors.append(f"{label}: Invalid source range")
            continue

        if not isinstance(timing, dict):
            errors.append(f"{label}: Missing timing object")
            continue

        speed = timing.get("playback_speed")
        freeze = timing.get("freeze_tail_sec")
        transition = timing.get("transition_to_next")

        if not number(speed) or not 0.8 <= speed <= 1.25:
            errors.append(f"{label}: Invalid playback speed")
            continue

        if not number(freeze) or not 0 <= freeze <= 2:
            errors.append(f"{label}: Invalid freeze duration")
            continue

        if not isinstance(transition, dict):
            errors.append(f"{label}: Missing transition")
            continue

        kind = transition.get("type")
        overlap = transition.get("overlap_sec")

        if kind not in ("cut", "crossfade"):
            errors.append(f"{label}: Unsupported transition")
            continue

        if not number(overlap) or not 0 <= overlap <= 0.5:
            errors.append(f"{label}: Invalid overlap")
            continue

        if kind == "cut" and overlap != 0:
            errors.append(f"{label}: Cut cannot have overlap")

        if index == len(shots) and (kind != "cut" or overlap != 0):
            errors.append(f"{label}: Invalid final transition")

        shot_duration = (end - start) / speed + freeze

        if overlap >= shot_duration:
            errors.append(f"{label}: Overlap exceeds shot duration")

        calculated += shot_duration - overlap

        boundary_flags = []

        for boundary, t in (("start", start), ("end", end)):
            if t == 0 or abs(t - duration) < 0.01:
                continue

            nearby = [
                w["text"] for w in words
                if w["start"] - 0.15 <= t <= w["end"] + 0.15
            ]

            if nearby:
                boundary_flags.append({
                    "boundary": boundary,
                    "time": t,
                    "nearby_asr_words_unverified": nearby[:5]
                })
                warnings.append(f"{label}: {boundary} near ASR speech; review audio")

        if last_end is not None and start < last_end:
            warnings.append(f"{label}: Source order jumps backward or overlaps")

        last_end = end

        if freeze > 0:
            warnings.append(f"{label}: Freeze frame requires visual review")

        if speed != 1:
            warnings.append(f"{label}: Speed adjustment requires audio review")

        if overlap > 0:
            warnings.append(f"{label}: Crossfade requires renderer verification")

        if shot.get("review_required"):
            warnings.append(f"{label}: AI flagged manual review")

        descriptions = " ".join(
            str(shot.get(k, ""))
            for k in (
                "narrative_purpose",
                "overlay_text",
                "visual_treatment"
            )
        )

        if re.search(r"\b(hundreds|ratusan)\b", descriptions, re.I):
            warnings.append(
                f"{label}: Inventory quantity claim requires factual verification"
            )

        shot_results.append({
            "shot_id": shot.get("shot_id"),
            "source_start_sec": start,
            "source_end_sec": end,
            "calculated_duration_sec": round(shot_duration, 3),
            "boundary_flags": boundary_flags
        })

    target = variant.get("target_duration_sec")

    if not number(target):
        errors.append(f"{vid}: Invalid target duration")
    elif abs(calculated - target) > 0.02:
        errors.append(
            f"{vid}: Duration mismatch "
            f"calculated={calculated:.3f}, target={target:.3f}"
        )

    variant_results.append({
        "variant_id": vid,
        "calculated_duration_sec": round(calculated, 3),
        "target_duration_sec": target,
        "shots": shot_results
    })

if seen_ids != {"A", "B"}:
    errors.append("Both variants A and B are required")

warnings.append(
    "ASR and speech boundaries remain unverified; "
    "numerical validity does not guarantee edit safety."
)

report = {
    "validator_version": "0.2.0-poc",
    "status": "BLOCKED" if errors else "NEEDS_REVIEW",
    "source_duration_sec": duration,
    "render_approved": False,
    "publish_approved": False,
    "errors": errors,
    "warnings": list(dict.fromkeys(warnings)),
    "variants": variant_results
}

OUTPUT.write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8"
)

print("=== DYNAMIC TIMELINE VALIDATOR V0.2 ===")
print("Status:", report["status"])
print("Source duration:", duration)
print("Blocking issues:", len(report["errors"]))
print("Review warnings:", len(report["warnings"]))

for variant in variant_results:
    print(
        f"Variant {variant['variant_id']}: "
        f"{len(variant['shots'])} shots, "
        f"{variant['calculated_duration_sec']}s calculated"
    )

print("\n=== ERRORS ===")
for issue in report["errors"]:
    print("-", issue)

print("\n=== WARNINGS ===")
for issue in report["warnings"]:
    print("-", issue)

print("\nReport:", OUTPUT)
print("Render approved:", report["render_approved"])
