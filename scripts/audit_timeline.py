import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
video = root / "data/test-videos/mandala-original.mp4"
analysis = root / "data/analyses/mandala-analysis.json"

probe = subprocess.run(
    [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(video)
    ],
    capture_output=True,
    text=True,
    check=True
)

duration = float(
    json.loads(probe.stdout)["format"]["duration"]
)
data = json.loads(analysis.read_text())
issues = []

def check_range(item, label):
    start = item.get("start_sec")
    end = item.get("end_sec")

    if start is None or end is None:
        issues.append(f"{label}: missing timestamp")
        return

    if not (
        isinstance(start, (int, float))
        and isinstance(end, (int, float))
    ):
        issues.append(f"{label}: invalid timestamp type")
        return

    if start < 0 or end <= start or end > duration + 0.1:
        issues.append(
            f"{label}: invalid range {start}-{end}"
        )

print("========== TIMELINE ALIGNMENT AUDIT ==========")
print(f"Actual video duration: {duration:.3f}s")

for name in ("timeline", "speech", "hooks"):
    items = data.get(name, [])
    print(f"\n=== {name.upper()} ({len(items)}) ===")

    for index, item in enumerate(items):
        label = f"{name}[{index}]"
        check_range(item, label)

        start = item.get("start_sec")
        end = item.get("end_sec")

        print(f"{index + 1}: {start}s - {end}s")

timeline = data.get("timeline", [])
if timeline:
    ordered = sorted(
        timeline,
        key=lambda item: item["start_sec"]
    )

    if ordered[0]["start_sec"] > 0.2:
        issues.append("Uncovered beginning")

    for previous, current in zip(ordered, ordered[1:]):
        difference = (
            current["start_sec"] - previous["end_sec"]
        )
        if difference > 0.5:
            issues.append(
                f"Timeline gap: {difference:.2f}s"
            )
        elif difference < -0.1:
            issues.append(
                f"Timeline overlap: {-difference:.2f}s"
            )

    print(
        "\nUncovered video tail:",
        round(max(0, duration - ordered[-1]["end_sec"]), 3),
        "seconds"
    )

print("\n=== VALIDATION ISSUES ===")

if issues:
    for issue in issues:
        print("WARNING:", issue)
else:
    print("No structural timestamp errors detected")

print("\nNOTE: Timestamp accuracy is not yet verified.")
print("========== AUDIT COMPLETE ==========")
