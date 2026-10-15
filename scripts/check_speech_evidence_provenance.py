#!/usr/bin/env python3
"""Inspect speech evidence offline. Provenance inspection does not verify words or cuts."""

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import build_adaptive_director_input_v03 as base
from validate_universal_analysis_v02 import speech_consistency

PCM_PARAMETERS = {"codec": "pcm_s16le", "sample_rate": 16000, "channels": 1, "endianness": "little"}
MAX_PCM_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
DECODE_TIMEOUT_SEC = 60
bounded_run = base.bounded_run
small_output = base.small_output


def sha256_file(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def audio_streams(video):
    text = small_output([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file", "-select_streams", "a",
        "-show_entries", "stream=index,codec_name,sample_rate,channels,channel_layout", "-of", "json", str(video),
    ])
    try:
        streams = json.loads(text)["streams"]
        if not isinstance(streams, list):
            raise ValueError()
        for stream in streams:
            if type(stream["index"]) is not int or stream["index"] < 0:
                raise ValueError()
            if type(stream["channels"]) is not int or stream["channels"] <= 0:
                raise ValueError()
            if int(stream["sample_rate"]) <= 0 or not isinstance(stream["codec_name"], str) or not stream["codec_name"]:
                raise ValueError()
        return streams
    except (ValueError, KeyError, TypeError):
        raise base.AdapterError("FFprobe returned invalid audio stream metadata") from None


def pcm_fingerprint(path, stream_index=None):
    digest = hashlib.sha256()
    mapping = f"0:{stream_index}" if stream_index is not None else "0:a:0"
    count = bounded_run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-max_alloc", "67108864", "-threads", "1", "-protocol_whitelist", "file", "-i", str(path),
        "-map", mapping, "-vn", "-filter_threads", "1", "-threads", "1",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
    ], digest.update, max_bytes=MAX_PCM_BYTES, timeout=DECODE_TIMEOUT_SEC)
    if count == 0 or count % 2:
        raise base.AdapterError("Decoded PCM is empty or has incomplete samples")
    return {"sha256": digest.hexdigest(), "byte_count": count, "sample_count": count // 2, "duration_sec": count / 32000}


def speech_requirements(analysis):
    profile = analysis["content_profile"]["speech_presence"]
    regions = []
    for segment in analysis["segments"]:
        layers = segment["audio_layers"]
        requirement = "required" if "speech" in layers else "needs_review" if not layers or "unknown" in layers else "not_required"
        regions.append({"segment_id": segment["segment_id"], "start_sec": segment["start_sec"], "end_sec": segment["end_sec"], "requirement": requirement})
    consistency = speech_consistency(analysis)
    required = any(r["requirement"] == "required" for r in regions)
    uncertain = (
        profile == "uncertain"
        or consistency["temporal_coverage"]["status"] == "incomplete"
        or not analysis["analysis_meta"]["audio_examined"]
        or any(r["requirement"] == "needs_review" for r in regions)
        or "present_profile_without_regional_speech" in consistency["classification_conflicts"]
    )
    return {
        "reported_speech_presence": profile,
        "basis": "canonical_analysis_unverified",
        "overall_requirement": "needs_review" if uncertain else "required" if required else "not_required",
        "regions": regions,
        **consistency,
    }


def artifact_record(path):
    return {
        "path": path.relative_to(base.ROOT).as_posix() if path else None,
        "sha256": sha256_file(path) if path else None,
        "file_identity_status": "verified" if path else "unavailable",
        "structure_status": "unverified" if path else "unavailable",
        "source_association_status": "unverified" if path else "unavailable",
        "generation_provenance_status": "unverified" if path else "unavailable",
        "reported_generation": None,
        "reported_timing_status": None,
        "text_verification_status": "unverified" if path else "unavailable",
        "timing_verification_status": "unverified" if path else "unavailable",
        "eligible_for_attachment": False,
        "blocking_reasons": [],
        "limitations": [],
    }


def load_evidence(path, record):
    if path.stat().st_size > MAX_JSON_BYTES:
        raise base.AdapterError("Evidence JSON resource limit exceeded")
    try:
        return base.load_object(path, "Speech evidence")
    except (base.AdapterError, RecursionError):
        record["structure_status"] = "failed"
        record["blocking_reasons"].append("invalid_evidence_json")
        return None


def valid_ranges(items, duration, *, text_required=False):
    if not isinstance(items, list) or not items:
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        start, end = item.get("start_sec"), item.get("end_sec")
        try:
            if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in (start, end)):
                return False
        except OverflowError:
            return False
        if not 0 <= start < end <= duration:
            return False
        if text_required and (not isinstance(item.get("text"), str) or not item["text"].strip()):
            return False
        if "words" in item and isinstance(item["words"], list) and any(isinstance(w, dict) and "words" in w for w in item["words"]):
            return False
        if "words" in item and not valid_ranges(item["words"], duration):
            if item["words"] != []:
                return False
        if "words" in item and any(not isinstance(w.get("word"), str) for w in item["words"]):
            return False
    return True


def inspect_declared_binding(data, record, source_digest, source_pcm):
    provenance = data.get("provenance", {})
    if not isinstance(provenance, dict):
        record["source_association_status"] = "failed"
        record["blocking_reasons"].append("malformed_declared_provenance")
        return
    binding = {}
    for key, expected in (("source_sha256", source_digest), ("audio_pcm_sha256", source_pcm["sha256"] if source_pcm else None)):
        declared = provenance.get(key, data.get(key))
        binding[key] = declared if isinstance(declared, str) and re.fullmatch(r"[0-9a-f]{64}", declared) else None
        if declared is not None and (binding[key] is None or expected is not None and declared != expected):
            record["source_association_status"] = "failed"
            record["blocking_reasons"].append(f"declared_{key}_invalid_or_mismatched")
    record["declared_binding"] = binding
    record["blocking_reasons"].append("generation_not_independently_observed")
    record["limitations"].append("Matching declared hashes or audio cannot prove historical transcript generation")


def inspect_transcript(path, duration, source_digest, source_pcm, source_name):
    record = artifact_record(path)
    if path is None:
        return record
    data = load_evidence(path, record)
    if data is None:
        return record
    generation = {}
    malformed = False
    for key in ("engine", "model", "language", "compute", "elapsed_sec"):
        if key not in data:
            continue
        value = data[key]
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 if key == "elapsed_sec" else isinstance(value, str) and bool(value.strip())
        if valid:
            generation[key] = value
        else:
            malformed = True
    record["reported_generation"] = generation or None
    if not record["reported_generation"]:
        record["generation_provenance_status"] = "unavailable"
    if malformed:
        record["generation_provenance_status"] = "failed"
        record["blocking_reasons"].append("malformed_generation_information")
    record["reported_timing_status"] = data.get("timing_status") if isinstance(data.get("timing_status"), str) else None
    record["source_filename_matches"] = data.get("source_video") == source_name
    segments = data.get("segments")
    if not valid_ranges(segments, duration, text_required=True):
        record["structure_status"] = "failed"
        record["blocking_reasons"].append("malformed_transcript_segments_or_timestamps")
    else:
        record["structure_status"] = "verified"
        record["segment_count"] = len(segments)
    inspect_declared_binding(data, record, source_digest, source_pcm)
    record["limitations"].append("ASR words and timestamps are not independently verified")
    return record


def inspect_alignment(path, duration, source_digest, source_pcm):
    record = artifact_record(path)
    if path is None:
        return record
    data = load_evidence(path, record)
    if data is None:
        return record
    record["generation_provenance_status"] = "unavailable"
    record["reported_timing_status"] = data.get("speech_timing_status") if isinstance(data.get("speech_timing_status"), str) else None
    if not valid_ranges(data.get("clips"), duration):
        record["structure_status"] = "failed"
        record["blocking_reasons"].append("malformed_alignment_clips_or_timestamps")
    else:
        record["structure_status"] = "verified"
    if "source_duration_sec" in data and (type(data["source_duration_sec"]) not in (int, float) or data["source_duration_sec"] != duration):
        record["source_association_status"] = "failed"
        record["blocking_reasons"].append("alignment_source_duration_mismatch")
    references = {"source_video": data.get("source_video")}
    sources = data.get("analysis_sources")
    if isinstance(sources, dict):
        references.update({"analysis_sources." + k: v for k, v in sources.items()})
    else:
        record["blocking_reasons"].append("alignment_analysis_sources_missing_or_malformed")
    stale = []
    for field, value in references.items():
        try:
            if not isinstance(value, str):
                raise base.AdapterError("Missing legacy reference")
            base.project_path(value, "Legacy reference")
        except (base.AdapterError, OSError):
            stale.append(field)
    record["stale_or_unsafe_reference_fields"] = stale
    if stale:
        record["blocking_reasons"].append("stale_or_unsafe_alignment_references")
    inspect_declared_binding(data, record, source_digest, source_pcm)
    record["limitations"].append("Legacy references are inspected without repair; alignment accuracy remains unverified")
    return record


def inspect_review(path):
    result = {"path": path.relative_to(base.ROOT).as_posix() if path else None, "sha256": sha256_file(path) if path else None, "status": "unverified" if path else "unavailable", "corrected_text_present": None, "all_windows_reviewed": None}
    if path:
        try:
            if path.stat().st_size > MAX_JSON_BYTES:
                raise base.AdapterError("Review resource limit exceeded")
            data = base.load_object(path, "Transcript review")
            windows = data.get("windows")
            if not isinstance(windows, list) or not windows or any(not isinstance(w, dict) for w in windows):
                raise base.AdapterError("Invalid review windows")
            result["corrected_text_present"] = any(isinstance(w.get("verified_transcript"), str) and bool(w["verified_transcript"].strip()) for w in windows)
            result["all_windows_reviewed"] = all(w.get("review_status") in ("reviewed", "verified") for w in windows)
        except (base.AdapterError, RecursionError):
            result["status"] = "failed"
    return result


def inspect_provenance(video, metadata, analysis, output, *, audio=None, transcript=None, alignment=None, review=None, stream_index=None):
    paths = {"video": video, "metadata": metadata, "analysis": analysis, "audio": audio, "transcript": transcript, "alignment": alignment, "review": review}
    paths = {key: base.project_path(value, key) if value is not None else None for key, value in paths.items()}
    output = base.project_path(output, "Output", output=True)
    adaptive_schema = base.load_schema("adaptive-director-input.v0.3.schema.json")
    source, digest = base.verify_source(paths["video"], base.load_object(paths["metadata"], "Metadata"), adaptive_schema["properties"]["source"])
    canonical = base.load_object(paths["analysis"], "Canonical analysis")
    universal_schema = base.load_schema("universal-video-analysis.v0.2.schema.json")
    errors, warnings = base.validate_analysis(canonical, universal_schema)
    if errors:
        base.validate_object(canonical, universal_schema, "Canonical analysis")
        raise base.AdapterError("Canonical semantic/timing validation blocked")
    if canonical["source"] != source:
        raise base.AdapterError("Canonical analysis source metadata mismatch")
    streams = audio_streams(paths["video"])
    stream = next((s for s in streams if s["index"] == stream_index), None) if stream_index is not None else next(iter(streams), None)
    if stream_index is not None and stream is None:
        raise base.AdapterError("Requested audio stream index is unavailable")
    source_pcm = pcm_fingerprint(paths["video"], stream["index"]) if stream else None
    wav_pcm = pcm_fingerprint(paths["audio"]) if paths["audio"] and stream else None
    comparison = "unavailable" if wav_pcm is None else "verified" if wav_pcm == source_pcm else "failed"
    transcript_result = inspect_transcript(paths["transcript"], source["duration_sec"], digest, source_pcm, paths["video"].name)
    alignment_result = inspect_alignment(paths["alignment"], source["duration_sec"], digest, source_pcm)
    requirement = speech_requirements(canonical)
    reasons = ["speech_classification_conflict:" + conflict for conflict in requirement["classification_conflicts"]]
    if requirement["temporal_coverage"]["status"] == "incomplete":
        reasons.append("speech_temporal_coverage_incomplete")
    speech_needed = requirement["overall_requirement"] == "required" or any(r["requirement"] == "required" for r in requirement["regions"])
    if comparison == "failed":
        reasons.append("extracted_audio_pcm_mismatch")
    if stream is None and (speech_needed or paths["transcript"] or paths["alignment"]):
        reasons.append("source_audio_stream_unavailable")
    if speech_needed and paths["transcript"] is None:
        reasons.append("required_transcript_unavailable")
    for kind, evidence in (("transcript", transcript_result), ("alignment", alignment_result)):
        reasons.extend(kind + ":" + reason for reason in evidence["blocking_reasons"])
    eligibility = "needs_review" if requirement["overall_requirement"] == "needs_review" else "ineligible" if reasons else "not_required"
    report = {
        "record_version": "0.1.0",
        "inspection_status": "complete",
        "source": {"path": paths["video"].relative_to(base.ROOT).as_posix(), "video_id": source["video_id"], "sha256": digest, "metadata": source, "association_status": "verified"},
        "metadata_sidecar": {"path": paths["metadata"].relative_to(base.ROOT).as_posix(), "sha256": sha256_file(paths["metadata"])},
        "canonical_analysis": {"path": paths["analysis"].relative_to(base.ROOT).as_posix(), "sha256": sha256_file(paths["analysis"]), "source_metadata_match": True, "findings_status": "unverified"},
        "audio": {
            "source_association_status": "verified" if source_pcm else "unavailable",
            "available_stream_indices": [s["index"] for s in streams],
            "stream": stream, "pcm_parameters": PCM_PARAMETERS, "source_pcm": source_pcm,
            "existing_audio": {"path": paths["audio"].relative_to(base.ROOT).as_posix() if paths["audio"] else None, "file_sha256": sha256_file(paths["audio"]) if paths["audio"] else None, "pcm": wav_pcm},
            "comparison_status": comparison,
            "verification_scope": "Equality of normalized decoded PCM only; does not prove transcript generation or accuracy",
        },
        "speech_requirements": requirement,
        "transcript": transcript_result, "alignment": alignment_result, "transcript_review": inspect_review(paths["review"]),
        "evidence_eligibility": {"status": eligibility, "transcript": False, "speech_alignment": False, "blocking_reasons": reasons},
        "inspection_tools": {"ffmpeg": small_output(["ffmpeg", "-version"]).splitlines()[0], "ffprobe": small_output(["ffprobe", "-version"]).splitlines()[0]},
        "warnings": warnings,
        "limitations": ["Speech requirements come from unverified canonical analysis", "Only the selected audio stream is fingerprinted", "No independently observed transcript/alignment generation receipt is verified in this stage", "File fingerprints identify bytes, not textual accuracy or word/frame-accurate timing"],
    }
    base.write_exclusive(output, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("video", "metadata", "analysis", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("audio", "transcript", "alignment", "review"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--audio-stream-index", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        report = inspect_provenance(args.video, args.metadata, args.analysis, args.output, audio=args.audio, transcript=args.transcript, alignment=args.alignment, review=args.review, stream_index=args.audio_stream_index)
    except (base.AdapterError, OSError) as error:
        message = str(error) if isinstance(error, base.AdapterError) else "Filesystem failure: " + str(error.strerror)
        print(json.dumps({"inspection_status": "failed", "status": "BLOCKED", "blocking_reasons": [message]}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
