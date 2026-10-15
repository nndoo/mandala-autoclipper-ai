#!/usr/bin/env python3
"""Mandala Autoclipper POC: Gemini context + Whisper timed speech -> review clips.

No source mutation, no gateway/network access, no publishing.
Speech-safe means avoiding cuts inside *estimated Whisper segments*, not verified
word-accurate or speaker-aware cutting. Every clip requires listening review.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = "0.1.0-poc"
# These are intentional POC review targets for mandala-original.mp4 only.
# The 1-based segments refer to the ASR output already reviewed in the project.
TARGETS = [
    ("01-opening", 1, 3, "Pembuka: pertanyaan dan jawaban awal"),
    ("02-main-hook", 5, 10, "Hook: pertanyaan, jawaban dua hari sekali, dan penjelasan"),
    ("03-closing", 13, 15, "Penutup: pertanyaan customer, pesan perawatan, dan terima kasih"),
]
SHORT_GAP = 0.24  # seconds; flag tight transitions for mandatory manual review
MAX_HANDLE = 0.25 # seconds of room tone outside each selected speech region


def probe_video(video: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,width,height,avg_frame_rate",
         "-of", "json", str(video)],
        text=True, capture_output=True, check=True,
    )
    payload = json.loads(proc.stdout)
    duration = float(payload["format"]["duration"])
    streams = payload.get("streams", [])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Durasi video tidak valid")
    if not any(s.get("codec_type") == "video" for s in streams):
        raise ValueError("Sumber tidak memiliki stream video")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise ValueError("Sumber tidak memiliki stream audio")
    return {"duration_sec": duration, "streams": streams}


def load_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Bukan JSON object: {path}")
    return obj


def valid_timestamp(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_segments(segments: list, duration: float) -> None:
    if not isinstance(segments, list) or len(segments) < 15:
        raise ValueError("POC membutuhkan minimal 15 segmen Faster-Whisper")
    previous_start = -1.0
    for i, s in enumerate(segments, 1):
        a, b = s.get("start_sec"), s.get("end_sec")
        if not (valid_timestamp(a) and valid_timestamp(b)):
            raise ValueError(f"ASR segment {i}: timestamp bukan angka")
        if not (0 <= a < b <= duration + 0.1):
            raise ValueError(f"ASR segment {i}: rentang di luar video")
        if a < previous_start:
            raise ValueError(f"ASR segment {i}: tidak berurutan")
        previous_start = a


def boundary_before(segments: list, first_idx: int, duration: float) -> tuple[float, float | None]:
    first = segments[first_idx]
    if first_idx == 0:
        return 0.0, None
    previous = segments[first_idx-1]
    gap = float(first["start_sec"]) - float(previous["end_sec"])
    if gap <= 0:
        # If model estimated overlapping dialogue, use exact speech start and flag it.
        return max(0.0, float(first["start_sec"])), gap
    return max(0.0, float(first["start_sec"]) - min(MAX_HANDLE, gap/2)), gap


def boundary_after(segments: list, last_idx: int, duration: float) -> tuple[float, float | None]:
    last = segments[last_idx]
    if last_idx == len(segments)-1:
        gap = duration - float(last["end_sec"])
        return min(duration, float(last["end_sec"]) + min(MAX_HANDLE, max(0.0,gap))), None
    following = segments[last_idx+1]
    gap = float(following["start_sec"]) - float(last["end_sec"])
    if gap <= 0:
        return min(duration, float(last["end_sec"])), gap
    return min(duration, float(last["end_sec"]) + min(MAX_HANDLE, gap/2)), gap


def overlapping(items, start, end):
    if not isinstance(items, list):
        return []
    return [item for item in items
            if valid_timestamp(item.get("start_sec")) and valid_timestamp(item.get("end_sec"))
            and item["start_sec"] < end and item["end_sec"] > start]


def plan_clip(name, first, last, reason, segments, gemini, duration):
    si, ei = first - 1, last - 1
    start, gap_before = boundary_before(segments, si, duration)
    end, gap_after = boundary_after(segments, ei, duration)
    flags = []
    if gap_before is not None and gap_before < SHORT_GAP:
        flags.append("tight_or_overlapping_start_gap_needs_listening")
    if gap_after is not None and gap_after < SHORT_GAP:
        flags.append("tight_or_overlapping_end_gap_needs_listening")
    if start >= end or end > duration + 0.001:
        raise ValueError(f"Invalid clip boundaries: {name}: {start}-{end}")
    selected = segments[si:ei+1]
    for item in selected:
        if item["start_sec"] < start - .005 or item["end_sec"] > end + .005:
            flags.append("target_speech_segment_crosses_cut")
            break
    # Check *all* ASR intervals: never mark this completely safe until listening review.
    for item in segments:
        a, b = item["start_sec"], item["end_sec"]
        if (a + .005 < start < b - .005) or (a + .005 < end < b - .005):
            flags.append("asr_speech_interval_crosses_cut")
            break
    matches = overlapping(gemini.get("speech", []), start, end)
    return {
        "id": name, "editorial_intent": reason,
        "start_sec": round(start, 3), "end_sec": round(end, 3),
        "duration_sec": round(end-start, 3),
        "source_asr_segment_numbers": list(range(first, last+1)),
        "asr_text_unverified": " ".join(s.get("text", "").strip() for s in selected),
        "gemini_dialogue_hints_unverified": [
            {"speaker": s.get("speaker"), "text": s.get("text"),
             "start_sec": s.get("start_sec"), "end_sec": s.get("end_sec")}
            for s in matches
        ],
        "gemini_scene_hints_unverified": overlapping(gemini.get("timeline", []), start, end),
        "gemini_hook_hints_unverified": overlapping(gemini.get("hooks", []), start, end),
        "gap_before_sec": None if gap_before is None else round(gap_before, 3),
        "gap_after_sec": None if gap_after is None else round(gap_after, 3),
        "qa_flags": list(dict.fromkeys(flags)),
        "review_status": "pending_manual_audio_video_review",
    }


def render_clip(source: Path, target: Path, clip: dict):
    duration = clip["duration_sec"]
    # Re-encode (do not stream-copy): sample/frame accurate output timing.
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-ss", f"{clip['start_sec']:.3f}",
        "-t", f"{duration:.3f}", "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(target),
    ]
    subprocess.run(cmd, check=True)
    if not target.exists() or target.stat().st_size < 1024:
        raise RuntimeError(f"Render kosong: {target}")
    return probe_video(target)["duration_sec"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--gemini", required=True, type=Path)
    parser.add_argument("--whisper", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--render", action="store_true", help="Render QA clips (optional)")
    args = parser.parse_args()
    for command in ("ffprobe", "ffmpeg"):
        if not shutil.which(command):
            raise SystemExit(f"Required: {command}")
    for path in (args.video, args.gemini, args.whisper):
        if not path.is_file():
            raise SystemExit(f"Missing input: {path}")
    source = probe_video(args.video)
    duration = source["duration_sec"]
    gemini = load_json(args.gemini)
    whisper = load_json(args.whisper)
    segments = whisper.get("segments")
    check_segments(segments, duration)
    planned = [plan_clip(name, first, last, intent, segments, gemini, duration)
               for name, first, last, intent in TARGETS]
    report = {
        "schema_version": SCHEMA_VERSION,
        "source_video": str(args.video.resolve()),
        "source_duration_sec": round(duration, 3),
        "analysis_sources": {
            "semantic": str(args.gemini.resolve()),
            "speech_timing": str(args.whisper.resolve()),
        },
        "speech_timing_status": "estimated_not_frame_verified",
        "speech_text_status": "unverified_model_generated",
        "scope": "3 preselected Mandala POC clips; not a general autonomous editor",
        "cuts_are_safe_for_publishing": False,
        "asr_speech_timeline_unverified": [
            {"start_sec": s["start_sec"], "end_sec": s["end_sec"],
             "text": s.get("text", ""),
             "gemini_speaker_hints_unverified": list(dict.fromkeys(
                 str(g.get("speaker", "unknown"))
                 for g in overlapping(gemini.get("speech", []), s["start_sec"], s["end_sec"])
             ))}
            for s in segments
        ],
        "clips": planned,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outfile = args.output_dir / "aligned-timeline.json"
    outfile.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    notes = ["MANDALA AUTO - REVIEW REQUIRED (3 POC clips)",
             "AI word and speaker labels are unverified; listen to every start and end.",
             "DO NOT PUBLISH on these timestamps without checking the actual audio.", ""]
    for clip in planned:
        flags = ", ".join(clip["qa_flags"]) if clip["qa_flags"] else "none (still review)"
        notes += [f"{clip['id']}: {clip['start_sec']:.3f}-{clip['end_sec']:.3f}s",
                  f"ASR (unverified): {clip['asr_text_unverified']}", f"QA flags: {flags}",
                  "Manual check: No word clipped? Speaker switch okay? Hook meaningful?", ""]
    (args.output_dir / "review-notes.txt").write_text("\n".join(notes), encoding="utf-8")
    print(f"Aligned timeline: {outfile}")
    for clip in planned:
        print(f"{clip['id']}: {clip['start_sec']:.3f}-{clip['end_sec']:.3f}s"
              f" | flags={clip['qa_flags']}")
    if args.render:
        print("Rendering review clips (no source overwrite)...", flush=True)
        for clip in planned:
            target = args.output_dir / f"{clip['id']}-aligned.mp4"
            actual_duration = render_clip(args.video, target, clip)
            if abs(actual_duration-clip["duration_sec"]) > 0.30:
                raise RuntimeError(f"Unexpected duration {actual_duration:.3f}s for {target}")
            print(f"{target.name}: {actual_duration:.3f}s, {target.stat().st_size:,} bytes", flush=True)
    print("DONE: manual audio/video review is still required.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as e:
        sys.exit(f"ERROR: {e}")
