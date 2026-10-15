#!/usr/bin/env python3

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESPONSE = ROOT / "data/analyses/director/director-run-01.response.json"
WHISPER = ROOT / "data/analyses/mandala-whisper.json"
VIDEO = ROOT / "data/test-videos/mandala-original.mp4"
REPORT = ROOT / "data/analyses/director/director-run-01.validation.json"

if REPORT.exists():
    raise SystemExit("STOP: Validation report sudah ada. Tidak ditimpa.")

response = json.loads(RESPONSE.read_text(encoding="utf-8"))
text = response["payloads"][0]["text"].strip()

if text.startswith("```"):
    lines = text.splitlines()
    if lines[-1].strip() == "```":
        text = "\n".join(lines[1:-1]).strip()

plan = json.loads(text)
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
results = []

def error(message):
    errors.append(message)

def warning(message):
    warnings.append(message)

words = []

for segment in whisper.get("segments", []):
    for word in segment.get("words", []):
        start = word.get("start_sec")
        end = word.get("end_sec")

        if (
            isinstance(start, (int, float))
            and isinstance(end, (int, float))
            and 0 <= start < end
        ):
            words.append({
                "start": start,
                "end": end,
                "word": word.get("word", "").strip()
            })

if plan.get("plan_status") != "DRAFT_UNVALIDATED":
    error("Plan status harus DRAFT_UNVALIDATED")

reported_duration = plan.get("source_duration_sec")

if (
    not isinstance(reported_duration, (int, float))
    or abs(reported_duration - duration) > 0.1
):
    error("Durasi sumber tidak cocok dengan FFprobe")

variants = plan.get("variants")

if not isinstance(variants, list) or len(variants) != 2:
    error("Creative plan wajib mempunyai dua variants")
    variants = []

ids = [v.get("variant_id") for v in variants if isinstance(v, dict)]

if sorted(ids) != ["A", "B"]:
    error("Variant IDs harus A dan B")

for variant in variants:
    if not isinstance(variant, dict):
        error("Variant bukan object")
        continue

    variant_id = variant.get("variant_id", "UNKNOWN")
    shots = variant.get("shots")
    total_duration = 0.0

    if not isinstance(shots, list) or not shots:
        error(f"{variant_id}: Shots kosong atau tidak valid")
        continue

    shot_results = []

    for index, shot in enumerate(shots, start=1):
        label = f"{variant_id}/shot-{index}"

        if not isinstance(shot, dict):
            error(f"{label}: Shot bukan object")
            continue

        start = shot.get("source_start_sec")
        end = shot.get("source_end_sec")

        if (
            not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not (0 <= start < end <= duration)
        ):
            error(f"{label}: Timestamp tidak valid")
            continue

        total_duration += end - start

        boundary_flags = []

        for boundary_name, timestamp in [
            ("start", start),
            ("end", end)
        ]:
            if timestamp == 0 or abs(timestamp - duration) < 0.01:
                continue

            nearby = [
                w for w in words
                if w["start"] - 0.15 <= timestamp <= w["end"] + 0.15
            ]

            if nearby:
                sample = [w["word"] for w in nearby[:4]]
                boundary_flags.append({
                    "boundary": boundary_name,
                    "timestamp": timestamp,
                    "nearby_asr_words_unverified": sample
                })

                warning(
                    f"{label}: {boundary_name} {timestamp:.2f}s "
                    "dekat kata ASR; perlu review audio"
                )

        if shot.get("review_required"):
            warning(f"{label}: AI meminta manual review")

        shot_results.append({
            "shot_id": shot.get("shot_id"),
            "start_sec": start,
            "end_sec": end,
            "duration_sec": round(end - start, 3),
            "boundary_flags": boundary_flags
        })

    target = variant.get("target_duration_sec")

    if not isinstance(target, (int, float)) or isinstance(target, bool):
        error(f"{variant_id}: Target duration tidak valid")
    elif abs(target - total_duration) > 0.15:
        error(
            f"{variant_id}: Target {target:.2f}s tidak cocok "
            f"dengan raw shot duration {total_duration:.2f}s. "
            "Butuh rencana timing eksplisit."
        )

    results.append({
        "variant_id": variant_id,
        "raw_duration_sec": round(total_duration, 3),
        "target_duration_sec": target,
        "shots": shot_results
    })

warning(
    "Whisper timestamps dan transkrip belum diverifikasi; "
    "subtitle serta speech-safe cuts memerlukan QA."
)

report = {
    "validator_version": "0.1.0-poc",
    "status": "BLOCKED" if errors else "NEEDS_REVIEW",
    "source_duration_sec": duration,
    "render_approved": False,
    "publish_approved": False,
    "errors": errors,
    "warnings": warnings,
    "variants": results
}

REPORT.write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8"
)

print("=== DYNAMIC TIMELINE VALIDATOR ===")
print("Status:", report["status"])
print("Verified source duration:", round(duration, 3))
print("Blocking issues:", len(errors))
print("Review warnings:", len(warnings))

for item in results:
    print(
        f"Variant {item['variant_id']}: "
        f"{len(item['shots'])} shots, "
        f"{item['raw_duration_sec']}s raw"
    )

print("\n=== BLOCKING ISSUES ===")
for issue in errors:
    print("-", issue)

print("\nReport:", REPORT)
print("Render approved:", report["render_approved"])
