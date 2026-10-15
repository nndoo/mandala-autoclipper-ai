#!/usr/bin/env python3
"""Speech evidence V0.1. Inspection success never means attachment eligibility."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import unicodedata

import check_speech_evidence_provenance as gate

base = gate.base
VERSION = "0.1.0"
MANIFEST = "generation-provenance.v01.json"
REPORT = "validation-eligibility.v01.json"
RAW = "raw-asr.v01.json"
DRAFT = "draft-transcript.v01.json"
TIMING = "speech-timing.v01.json"
REVIEW = "transcript-review.v01.json"
GATE = "stage5a-provenance.v01.json"
LEAVES = {RAW, DRAFT, TIMING, REVIEW, GATE}
LIMITATIONS = [
    "Canonical speech classifications are unverified AI findings, not independent acoustic facts",
    "PCM equivalence covers only the selected stream normalized to mono 16 kHz signed 16-bit little-endian",
    "Execution receipts record local generation; unsigned local hashes are not independent authentication",
    "Faster-Whisper word timestamps are ASR estimates, not forced alignment or frame-accurate boundaries",
    "Text, utterance boundaries and timing require separate review; Stage 5A attachment remains disabled",
]


def now():
    return datetime.now(timezone.utc).isoformat()


def relative(path):
    return path.relative_to(base.ROOT).as_posix()


def read_json(path):
    if path.stat().st_size > gate.MAX_JSON_BYTES:
        raise base.AdapterError("JSON resource limit exceeded")
    return base.load_object(path, "Speech evidence")


def write_json(path, data):
    base.write_exclusive(path, json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False) + "\n")


def directory(value, *, new=False):
    path = Path(value)
    if not path.is_absolute():
        path = base.ROOT / path
    if ".." in path.parts or path.is_symlink():
        raise base.AdapterError("Unsafe output/bundle path")
    resolved = path.resolve()
    if not resolved.is_relative_to(base.ROOT) or resolved == base.ROOT:
        raise base.AdapterError("Output/bundle must be inside project")
    if new and (resolved.exists() or path.is_symlink()):
        raise base.AdapterError("Output already exists; refusing to overwrite")
    if not new and not resolved.is_dir():
        raise base.AdapterError("Bundle directory missing")
    return resolved


def verified_inputs(video, metadata, analysis):
    paths = {key: base.project_path(value, key) for key, value in
             (("video", video), ("metadata", metadata), ("analysis", analysis))}
    source, digest = base.verify_source(paths["video"], read_json(paths["metadata"]),
                                      base.load_schema("adaptive-director-input.v0.3.schema.json")["properties"]["source"])
    canonical = read_json(paths["analysis"])
    schema = base.load_schema("universal-video-analysis.v0.2.schema.json")
    errors, warnings = base.validate_analysis(canonical, schema)
    if errors:
        base.validate_object(canonical, schema, "Canonical analysis")
        raise base.AdapterError("Canonical semantic/timing validation blocked")
    if canonical["source"] != source:
        raise base.AdapterError("Canonical analysis source metadata mismatch")
    return paths, source, digest, canonical, warnings


def limits_config(threads=4, memory=4096, timeout=300, pcm_bytes=gate.MAX_PCM_BYTES, result_bytes=gate.MAX_JSON_BYTES):
    if type(threads) is not int or not 1 <= threads <= 8 or type(memory) is not int or not 512 <= memory <= 8192:
        raise base.AdapterError("Invalid resource limits")
    if not finite(timeout) or not 1 <= timeout <= 1800:
        raise base.AdapterError("Invalid ASR timeout")
    if any(type(n) is not int or not 1024 <= n <= ceiling for n, ceiling in
           ((pcm_bytes, gate.MAX_PCM_BYTES), (result_bytes, gate.MAX_JSON_BYTES))):
        raise base.AdapterError("Invalid byte limits")
    return {"cpu_threads": threads, "memory_mib": memory, "asr_timeout_sec": timeout,
            "max_pcm_bytes": pcm_bytes, "max_result_bytes": result_bytes,
            "decode_timeout_sec": gate.DECODE_TIMEOUT_SEC, "stderr_policy": "discarded_DEVNULL"}


def finite(value):
    try:
        return type(value) in (float, int) and math.isfinite(value)
    except OverflowError:
        return False


def select_regions(requirement, duration, context=0.75):
    if not finite(context) or not 0 <= context <= 3:
        raise base.AdapterError("Context must be between 0 and 3 seconds")
    if requirement["classification_conflicts"] or requirement["overall_requirement"] != "required":
        return []
    candidates = sorted((r for r in requirement["regions"] if r["requirement"] == "required"), key=lambda r: r["start_sec"])
    merged = []
    for candidate in candidates:
        start = max(0, candidate["start_sec"] - context)
        end = min(duration, candidate["end_sec"] + context)
        if merged and start <= merged[-1]["end_sec"]:
            merged[-1]["end_sec"] = max(end, merged[-1]["end_sec"])
            merged[-1]["candidates"].append(candidate)
        else:
            merged.append({"region_id": f"region-{len(merged) + 1:04d}", "start_sec": start, "end_sec": end,
                           "candidates": [candidate]})
    return merged


def capture_pcm(video, stream, path, limits):
    digest = hashlib.sha256()
    with path.open("xb") as output:
        def consume(chunk):
            output.write(chunk)
            digest.update(chunk)
        count = base.bounded_run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-max_alloc", "67108864",
            "-threads", "1", "-protocol_whitelist", "file", "-i", str(video), "-map", f"0:{stream['index']}",
            "-vn", "-filter_threads", "1", "-threads", "1", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
        ], consume, max_bytes=limits["max_pcm_bytes"], timeout=limits["decode_timeout_sec"])
    if count == 0 or count % 2:
        raise base.AdapterError("Decoded PCM empty or incomplete")
    return {"sha256": digest.hexdigest(), "byte_count": count, "sample_count": count // 2, "duration_sec": count / 32000}


def worker_call(job, python, temporary):
    executable = Path(python).expanduser().absolute()
    if not executable.is_file():
        return {"status": "blocked", "reason": "runtime_dependencies_unavailable"}
    worker = Path(__file__).with_name("speech_asr_worker.py")
    job_path = temporary / (job["action"] + "-job.json")
    job_path.write_text(json.dumps(job, allow_nan=False), encoding="utf-8")
    chunks = []
    try:
        base.bounded_run([str(executable), "-B", str(worker), "--job", str(job_path)], chunks.append,
                         max_bytes=job["limits"]["max_result_bytes"], timeout=job["limits"]["asr_timeout_sec"])
        result = json.loads(b"".join(chunks), object_pairs_hook=base.unique_object, parse_constant=base.reject_constant)
        if not isinstance(result, dict) or result.get("status") not in ("blocked", "complete"):
            raise ValueError()
        if result["status"] == "complete" and result.get("action") != job["action"]:
            raise ValueError()
        return result
    except base.AdapterError as error:
        return {"status": "blocked", "reason": "worker_bounded_execution_failed", "detail": str(error)}
    except (ValueError, UnicodeError, RecursionError):
        return {"status": "blocked", "reason": "malformed_worker_result"}


def prepare_regions(regions, pcm_path, temporary, pcm):
    result = []
    with pcm_path.open("rb") as source:
        for region in regions:
            start = max(0, math.floor(region["start_sec"] * 16000))
            end = min(pcm["sample_count"], math.ceil(region["end_sec"] * 16000))
            if end <= start:
                raise base.AdapterError("Speech region has no decoded samples")
            source.seek(start * 2)
            data = source.read((end - start) * 2)
            path = temporary / (region["region_id"] + ".pcm")
            path.write_bytes(data)
            result.append({**region, "offset_sec": start / 16000, "processing_end_sec": end / 16000,
                           "sample_start": start, "sample_end": end,
                           "pcm_sha256": hashlib.sha256(data).hexdigest(), "pcm_path": str(path)})
    return result


def project_transcript(raw, regions, source, source_digest, pcm):
    check_receipt(raw)
    mapping = {r["region_id"]: r for r in regions}
    if raw.get("status") != "complete" or raw.get("action") != "transcribe" or not isinstance(raw.get("regions"), list):
        raise base.AdapterError("Malformed ASR execution receipt")
    if (any(not isinstance(r, dict) for r in raw["regions"]) or len(raw["regions"]) != len(mapping) or
            {r.get("region_id") for r in raw["regions"]} != set(mapping)):
        raise base.AdapterError("ASR region identity mismatch")
    segments = []
    for region_result in raw["regions"]:
        region = mapping[region_result["region_id"]]
        if (region_result.get("pcm_sha256") != region["pcm_sha256"] or
                region_result.get("sample_count") != region["sample_end"] - region["sample_start"]):
            raise base.AdapterError("ASR region PCM mismatch")
        if not isinstance(region_result.get("segments"), list) or not isinstance(region_result.get("info"), dict):
            raise base.AdapterError("Malformed ASR region receipt")
        for index, item in enumerate(region_result["segments"]):
            if not isinstance(item, dict):
                raise base.AdapterError("Malformed ASR segment")
            def source_time(value):
                return value + region["offset_sec"] if finite(value) else value
            words = item.get("words")
            if words is None:
                words = []
            if not isinstance(words, list) or any(not isinstance(w, dict) for w in words):
                raise base.AdapterError("Malformed ASR words")
            segments.append({"segment_id": f"{region['region_id']}-segment-{index + 1:04d}",
                             "region_id": region["region_id"], "raw_segment_id": item.get("id"),
                             "start_sec": source_time(item.get("start")), "end_sec": source_time(item.get("end")),
                             "text": item.get("text"), "language": region_result["info"].get("language"),
                             "avg_logprob": item.get("avg_logprob"), "no_speech_prob": item.get("no_speech_prob"),
                             "compression_ratio": item.get("compression_ratio"),
                             "words": [{"start_sec": source_time(w.get("start")), "end_sec": source_time(w.get("end")),
                                        "word": w.get("word"), "probability": w.get("probability")} for w in words]})
    return {"record_version": VERSION, "source_id": source["video_id"], "source_video": source["file_name"],
            "engine": "faster-whisper", "model": raw["model"]["identifier"], "compute": "cpu-int8",
            "timing_status": "estimated_not_verified", "text_verification_status": "unverified",
            "provenance": {"source_sha256": source_digest, "audio_pcm_sha256": pcm["sha256"]}, "segments": segments}


def check_receipt(receipt):
    """Validate recorded identities, without claiming a trusted signature or accuracy."""
    try:
        model = receipt["model"]
        if not isinstance(model["identifier"], str) or not model["identifier"] or not Path(model["resolved_path"]).is_absolute():
            raise ValueError()
        files = model["files"]
        names = {f["name"] for f in files}
        if len(names) != len(files) or not {"model.bin", "config.json", "tokenizer.json"} <= names or not names & {"vocabulary.json", "vocabulary.txt"}:
            raise ValueError()
        if any(Path(f["name"]).name != f["name"] or not re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) or
               type(f["byte_count"]) is not int or f["byte_count"] <= 0 for f in files):
            raise ValueError()
        runtime = receipt["runtime"]
        if any(not isinstance(runtime[k], str) or not runtime[k] for k in ("faster-whisper", "ctranslate2", "numpy", "python")):
            raise ValueError()
        if receipt.get("action") == "transcribe" and (not finite(receipt.get("elapsed_sec")) or receipt["elapsed_sec"] < 0):
            raise ValueError()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise base.AdapterError("Missing or malformed ASR generation provenance") from None


def assess(draft, regions, duration, language):
    flags = []
    def flag(code, segment=None):
        flags.append({"code": code, "segment_id": segment})
    mapping = {r["region_id"]: r for r in regions}
    previous = 0
    seen = set()
    languages = set()
    invalid_timing = False
    def valid_range(item, lower, upper):
        return all(finite(item.get(k)) for k in ("start_sec", "end_sec")) and lower <= item["start_sec"] < item["end_sec"] <= upper
    for segment in draft["segments"]:
        sid = segment["segment_id"]
        region = mapping[segment["region_id"]]
        text = segment["text"]
        if not isinstance(text, str) or not text.strip():
            flag("missing_or_empty_text", sid)
        else:
            normalized = " ".join(text.casefold().split())
            if normalized in seen or re.search(r"(\b\w+\b)(?:\s+\1){3,}", normalized):
                flag("repeated_or_suspicious_text", sid)
            seen.add(normalized)
            if any(c == "\ufffd" or unicodedata.category(c) == "Cs" or unicodedata.category(c) == "Cc" and c not in "\n\t\r" for c in text):
                flag("invalid_or_suspicious_encoding", sid)
        lang = segment.get("language")
        if lang:
            languages.add(lang)
            if language and lang != language:
                flag("unexpected_language", sid)
        if not valid_range(segment, 0, duration) or not valid_range(segment, region["offset_sec"], region["processing_end_sec"]):
            flag("invalid_segment_timestamps", sid)
            invalid_timing = True
            continue
        if segment["start_sec"] < previous:
            flag("segment_order_or_overlap", sid)
            invalid_timing = True
        if segment["start_sec"] - previous > 2 and previous >= region["offset_sec"]:
            flag("large_speech_gap", sid)
        previous = segment["end_sec"]
        if not any(max(segment["start_sec"], c["start_sec"]) < min(segment["end_sec"], c["end_sec"]) for c in region["candidates"]):
            flag("speech_outside_candidate_possible_music_hallucination", sid)
        if segment["start_sec"] - region["offset_sec"] < 0.15 or region["processing_end_sec"] - segment["end_sec"] < 0.15:
            flag("possibly_incomplete_utterance", sid)
        for metric, threshold, direction in (("avg_logprob", -1, -1), ("no_speech_prob", 0.6, 1), ("compression_ratio", 2.4, 1)):
            value = segment.get(metric)
            if value is None:
                flag("confidence_metric_unavailable:" + metric, sid)
            elif not finite(value) or direction * value > direction * threshold:
                flag("suspicious_confidence:" + metric, sid)
        if not segment["words"]:
            flag("word_timing_unavailable", sid)
        word_end = segment["start_sec"]
        for word in segment["words"]:
            if not valid_range(word, segment["start_sec"], segment["end_sec"]) or word["start_sec"] < word_end:
                flag("invalid_word_timestamps_or_order", sid)
                invalid_timing = True
            if finite(word.get("end_sec")):
                word_end = word["end_sec"]
            probability = word.get("probability")
            if not finite(probability) or not 0 <= probability <= 1 or probability < 0.5:
                flag("word_probability_low_or_unavailable", sid)
            if not isinstance(word.get("word"), str) or not word["word"].strip():
                flag("missing_word_text", sid)
    if len(languages) > 1:
        flag("language_change")
    for region in regions:
        if not any(s["region_id"] == region["region_id"] for s in draft["segments"]):
            flag("missing_transcript_region:" + region["region_id"])
    flag("utterance_boundaries_unverified")
    return {"structure_status": "failed" if invalid_timing else "checked",
            "review_status": "pending", "text_verification_status": "unverified", "timing_verification_status": "unverified",
            "thresholds": {"large_gap_sec": 2, "edge_margin_sec": 0.15, "word_probability_min": 0.5,
                           "avg_logprob_min": -1, "no_speech_prob_max": 0.6, "compression_ratio_max": 2.4}, "flags": flags}


def timing_artifact(draft):
    return {"record_version": VERSION, "source_id": draft["source_id"], "method": "faster_whisper_word_timestamps",
            "precision": "ASR_estimate", "timing_verification_status": "unverified", "frame_accurate": False,
            "segments": [{k: s[k] for k in ("segment_id", "region_id", "start_sec", "end_sec", "words")} for s in draft["segments"]]}


def review_template(draft, digest):
    return {"record_version": VERSION, "source_id": draft["source_id"], "transcript_sha256": digest,
            "review_status": "pending", "windows": [
                {"segment_id": s["segment_id"], "start_sec": s["start_sec"], "end_sec": s["end_sec"],
                 "original_recognized_text": s["text"], "confidence": {k: s[k] for k in ("avg_logprob", "no_speech_prob", "compression_ratio")},
                 "review_status": "pending", "corrected_transcription": None, "reviewer_identity": None,
                 "review_method": None, "verified_at": None} for s in draft["segments"]]}


def generate(video, metadata, analysis, output_dir, *, model="small", asr_python=".venv-asr/bin/python", language="id",
             beam_size=5, context=0.75, limits=None, stream_index=None, expected_pcm_sha256=None):
    limits = limits or limits_config()
    limits = limits_config(limits["cpu_threads"], limits["memory_mib"], limits["asr_timeout_sec"], limits["max_pcm_bytes"], limits["max_result_bytes"])
    if type(beam_size) is not int or not 1 <= beam_size <= 10:
        raise base.AdapterError("Invalid beam size")
    if language is not None and (not isinstance(language, str) or not re.fullmatch(r"[a-z]{2,3}", language)):
        raise base.AdapterError("Invalid language setting")
    output = directory(output_dir, new=True)
    paths, source, digest, canonical, warnings = verified_inputs(video, metadata, analysis)
    input_hashes = {key: gate.sha256_file(path) for key, path in paths.items()}
    requirement = gate.speech_requirements(canonical)
    regions = select_regions(requirement, source["duration_sec"], context)
    streams = gate.audio_streams(paths["video"])
    stream = next((s for s in streams if s["index"] == stream_index), None) if stream_index is not None else next(iter(streams), None)
    if stream_index is not None and stream is None:
        raise base.AdapterError("Requested audio stream unavailable")
    started = now()
    options = {"language": language, "beam_size": beam_size, "temperature": 0.0, "word_timestamps": True,
               "vad_filter": False, "condition_on_previous_text": False}
    status = "needs_review" if requirement["classification_conflicts"] else requirement["overall_requirement"]
    worker_result = None
    pcm = None
    public_regions = []
    artifacts = {}
    quality = None
    runtime_path = Path(asr_python).expanduser().absolute()
    # Do all expensive/unsafe execution before publishing any output bundle.
    with tempfile.TemporaryDirectory(prefix="mandala-speech-generation-") as temporary_name:
        temporary = Path(temporary_name)
        if stream:
            pcm = capture_pcm(paths["video"], stream, temporary / "source.pcm", limits)
            if pcm != gate.pcm_fingerprint(paths["video"], stream["index"]):
                raise base.AdapterError("Audio fingerprint mismatch")
            if expected_pcm_sha256 is not None and expected_pcm_sha256 != pcm["sha256"]:
                raise base.AdapterError("Expected audio fingerprint mismatch")
        if status == "required":
            if not pcm:
                status = "source_audio_stream_unavailable"
            else:
                jobs = prepare_regions(regions, temporary / "source.pcm", temporary, pcm)
                public_regions = [{k: v for k, v in r.items() if k != "pcm_path"} for r in jobs]
                job = {"action": "preflight", "model": model, "limits": limits, "decoding_options": options}
                preflight = worker_call(job, runtime_path, temporary)
                if preflight["status"] != "complete":
                    worker_result = preflight
                    status = preflight.get("reason", "asr_execution_failed")
                else:
                    check_receipt(preflight)
                    worker_result = worker_call({**job, "action": "transcribe", "regions": jobs}, runtime_path, temporary)
                    if worker_result["status"] != "complete":
                        status = worker_result.get("reason", "asr_execution_failed")
                    else:
                        if worker_result.get("model") != preflight.get("model") or worker_result.get("runtime") != preflight.get("runtime"):
                            raise base.AdapterError("Model/runtime changed between preflight and execution")
                        status = "complete"
                        artifacts[RAW] = worker_result
                        draft = project_transcript(worker_result, public_regions, {**source, "file_name": paths["video"].name}, digest, pcm)
                        artifacts[DRAFT] = draft
                        artifacts[TIMING] = timing_artifact(draft)
                        quality = assess(draft, public_regions, source["duration_sec"], language)
        # Bind bytes again after execution; never publish a stale-source receipt.
        if any(gate.sha256_file(path) != input_hashes[key] for key, path in paths.items()):
            raise base.AdapterError("Inputs changed during execution")
    output.parent.mkdir(parents=True, exist_ok=True)
    output = directory(output, new=True)
    output.mkdir(mode=0o700)
    created = []
    try:
        def publish(name, data):
            write_json(output / name, data)
            created.append(output / name)
        for name, artifact in artifacts.items():
            publish(name, artifact)
        if DRAFT in artifacts:
            publish(REVIEW, review_template(artifacts[DRAFT], gate.sha256_file(output / DRAFT)))
        inspection = gate.inspect_provenance(paths["video"], paths["metadata"], paths["analysis"], output / GATE,
                                            transcript=output / DRAFT if DRAFT in artifacts else None,
                                            review=output / REVIEW if DRAFT in artifacts else None,
                                            stream_index=stream["index"] if stream else None)
        created.append(output / GATE)
        if inspection["audio"]["source_pcm"] != pcm or inspection["source"]["sha256"] != digest:
            raise base.AdapterError("Source/audio changed during gate inspection")
        if any(gate.sha256_file(path) != input_hashes[key] for key, path in paths.items()):
            raise base.AdapterError("Inputs changed during publication")
        manifest = {"record_version": VERSION, "generation_status": status, "started_at": started, "finished_at": now(),
                    "inputs": {key: {"path": relative(path), "sha256": input_hashes[key]} for key, path in paths.items()},
                    "source": source, "source_integrity_status": "verified", "audio_integrity_status": "verified" if pcm else "unavailable",
                    "speech_requirements": requirement, "processing_regions": public_regions, "region_context_sec": context,
                    "audio": {"stream": stream, "pcm_parameters": gate.PCM_PARAMETERS, "source_pcm": pcm},
                    "requested_model": model, "model": worker_result.get("model") if worker_result else None,
                    "runtime": worker_result.get("runtime") if worker_result else None,
                    "execution_failure": worker_result if worker_result and worker_result["status"] == "blocked" else None,
                    "generation_provenance_status": "recorded" if status == "complete" else "unavailable",
                    "decoding_options": options, "limits": limits, "media_tools": inspection["inspection_tools"],
                    "generator": {"version": VERSION, "scripts": {p.name: gate.sha256_file(p) for p in
                                  (Path(__file__), Path(__file__).with_name("speech_asr_worker.py"))},
                                  "asr_python": str(runtime_path), "asr_python_sha256": gate.sha256_file(runtime_path) if runtime_path.is_file() else None},
                    "artifacts": {path.name: {"path": path.name, "sha256": gate.sha256_file(path)} for path in created},
                    "hash_boundary": "Manifest hashes leaf artifacts only; validation report hashes manifest; no self/cyclic hashing",
                    "limitations": LIMITATIONS, "canonical_warnings": warnings}
        publish(MANIFEST, manifest)
        report = make_report(manifest, gate.sha256_file(output / MANIFEST), inspection, quality)
        publish(REPORT, report)
        return report
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        # Remove only our own empty reservation, never recursively delete a raced-in file.
        try:
            output.rmdir()
        except OSError:
            pass
        raise


def make_report(manifest, manifest_hash, inspection, quality):
    generated = manifest["generation_status"] == "complete"
    return {"record_version": VERSION, "manifest_sha256": manifest_hash, "generation_status": manifest["generation_status"],
            "source_integrity_status": manifest["source_integrity_status"], "audio_integrity_status": manifest["audio_integrity_status"],
            "generation_provenance_status": manifest["generation_provenance_status"],
            "text_verification_status": "unverified" if generated else "unavailable",
            "timing_verification_status": "unverified" if generated else "unavailable", "human_review_status": "pending" if generated else "not_performed",
            "quality_assessment": quality, "evidence_eligibility": inspection["evidence_eligibility"],
            "director_attachments": {"transcript": None, "speech_alignment": None}, "limitations": LIMITATIONS}


def validate_bundle(bundle):
    bundle = directory(bundle)
    manifest = read_json(base.project_path(bundle / MANIFEST, "Manifest"))
    report = read_json(base.project_path(bundle / REPORT, "Report"))
    try:
        required_fields = {"record_version", "generation_status", "started_at", "finished_at", "inputs", "source",
                           "source_integrity_status", "audio_integrity_status", "speech_requirements", "processing_regions",
                           "region_context_sec", "audio", "requested_model", "model", "runtime", "execution_failure",
                           "generation_provenance_status", "decoding_options", "limits", "media_tools", "generator",
                           "artifacts", "hash_boundary", "limitations", "canonical_warnings"}
        if not required_fields <= set(manifest):
            raise base.AdapterError("Missing generation provenance fields")
        limits = manifest["limits"]
        normalized_limits = limits_config(limits["cpu_threads"], limits["memory_mib"], limits["asr_timeout_sec"],
                                         limits["max_pcm_bytes"], limits["max_result_bytes"])
        if limits != normalized_limits:
            raise base.AdapterError("Malformed resource limit provenance")
        if manifest["record_version"] != VERSION or report["manifest_sha256"] != gate.sha256_file(bundle / MANIFEST):
            raise base.AdapterError("Manifest integrity mismatch")
        generated = manifest["generation_status"] == "complete"
        statuses = {"complete", "not_required", "needs_review", "BLOCKED_MODEL_NOT_AVAILABLE", "source_audio_stream_unavailable",
                    "runtime_dependencies_unavailable", "asr_execution_failed", "worker_bounded_execution_failed", "malformed_worker_result",
                    "resource_limit", "unsafe_model_symlink", "model_changed_during_execution", "region_pcm_integrity_mismatch", "pcm_resource_limit"}
        if manifest["generation_status"] not in statuses:
            raise base.AdapterError("Unknown generation status")
        started = datetime.fromisoformat(manifest["started_at"])
        finished = datetime.fromisoformat(manifest["finished_at"])
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise base.AdapterError("Invalid generation timestamps")
        if (manifest["generator"]["version"] != VERSION or
                any(not re.fullmatch(r"[0-9a-f]{64}", manifest["generator"]["scripts"][name]) for name in
                    ("generate_speech_evidence_v01.py", "speech_asr_worker.py")) or
                not all(isinstance(manifest["media_tools"][name], str) and manifest["media_tools"][name] for name in ("ffmpeg", "ffprobe"))):
            raise base.AdapterError("Malformed tool provenance")
        required = LEAVES if generated else {GATE}
        if set(manifest["artifacts"]) != required:
            raise base.AdapterError("Missing or unexpected provenance artifacts")
        leaves = {}
        for name, record in manifest["artifacts"].items():
            if record["path"] != name or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
                raise base.AdapterError("Malformed artifact provenance")
            if (bundle / name).is_symlink():
                raise base.AdapterError("Artifact symlink rejected")
            path = base.project_path(bundle / name, "Artifact")
            if gate.sha256_file(path) != record["sha256"]:
                raise base.AdapterError("Artifact integrity mismatch")
            leaves[name] = read_json(path)
        paths, source, digest, canonical, _ = verified_inputs(**{k: manifest["inputs"][k]["path"] for k in ("video", "metadata", "analysis")})
        if any(gate.sha256_file(path) != manifest["inputs"][key]["sha256"] for key, path in paths.items()) or source != manifest["source"]:
            raise base.AdapterError("Input provenance mismatch")
        if gate.speech_requirements(canonical) != manifest["speech_requirements"]:
            raise base.AdapterError("Speech requirement mismatch")
        requirement = manifest["speech_requirements"]
        decision = "needs_review" if requirement["classification_conflicts"] else requirement["overall_requirement"]
        if ((decision != "required" and manifest["generation_status"] != decision) or
                (decision == "required" and manifest["generation_status"] in ("needs_review", "not_required"))):
            raise base.AdapterError("Generation decision conflicts with speech requirement")
        stream = manifest["audio"]["stream"]
        streams = gate.audio_streams(paths["video"])
        if stream is not None and stream not in streams or stream is None and streams:
            raise base.AdapterError("Audio stream provenance mismatch")
        pcm = gate.pcm_fingerprint(paths["video"], stream["index"]) if stream else None
        if manifest["audio"]["pcm_parameters"] != gate.PCM_PARAMETERS or pcm != manifest["audio"]["source_pcm"]:
            raise base.AdapterError("Audio provenance mismatch")
        if manifest["source_integrity_status"] != "verified" or manifest["audio_integrity_status"] != ("verified" if pcm else "unavailable"):
            raise base.AdapterError("False source/audio integrity status")
        inspection = leaves[GATE]
        if inspection["source"]["sha256"] != digest or inspection["audio"]["source_pcm"] != pcm:
            raise base.AdapterError("Gate source binding mismatch")
        if inspection["evidence_eligibility"]["transcript"] is not False or inspection["evidence_eligibility"]["speech_alignment"] is not False:
            raise base.AdapterError("Unsafe attachment eligibility")
        if inspection["evidence_eligibility"]["status"] not in ("ineligible", "needs_review", "not_required"):
            raise base.AdapterError("Unknown Stage 5A eligibility status")
        quality = None
        if generated:
            if manifest["generation_provenance_status"] != "recorded" or not manifest["model"]["files"] or not manifest["runtime"]:
                raise base.AdapterError("Missing generation provenance")
            if leaves[RAW]["model"] != manifest["model"] or leaves[RAW]["runtime"] != manifest["runtime"]:
                raise base.AdapterError("ASR provenance mismatch")
            # Recompute regional slices from actual source PCM; declared offsets/hashes alone are insufficient.
            with tempfile.TemporaryDirectory(prefix="mandala-speech-validation-") as temp_name:
                temporary = Path(temp_name)
                decoded = capture_pcm(paths["video"], stream, temporary / "source.pcm", limits)
                if decoded != pcm:
                    raise base.AdapterError("Validation PCM mismatch")
                candidates = select_regions(manifest["speech_requirements"], source["duration_sec"], manifest["region_context_sec"])
                actual_regions = prepare_regions(candidates, temporary / "source.pcm", temporary, pcm)
                actual_regions = [{k: v for k, v in r.items() if k != "pcm_path"} for r in actual_regions]
            if actual_regions != manifest["processing_regions"]:
                raise base.AdapterError("Region PCM/offset provenance mismatch")
            draft = project_transcript(leaves[RAW], manifest["processing_regions"], {**source, "file_name": paths["video"].name}, digest, pcm)
            if draft != leaves[DRAFT] or timing_artifact(draft) != leaves[TIMING]:
                raise base.AdapterError("Transcript/timing projection mismatch")
            if leaves[REVIEW] != review_template(draft, manifest["artifacts"][DRAFT]["sha256"]):
                raise base.AdapterError("Original review template modified; submit separate review")
            quality = assess(draft, manifest["processing_regions"], source["duration_sec"], manifest["decoding_options"]["language"])
        elif manifest["generation_provenance_status"] != "unavailable":
            raise base.AdapterError("False generation provenance")
        expected = make_report(manifest, gate.sha256_file(bundle / MANIFEST), inspection, quality)
        if report != expected:
            raise base.AdapterError("Validation report mismatch or false verification")
    except (KeyError, TypeError, AttributeError, ValueError, IndexError) as error:
        if isinstance(error, base.AdapterError):
            raise
        raise base.AdapterError("Missing or malformed generation provenance") from None
    return {"integrity_status": "checked", "generation_status": manifest["generation_status"],
            "evidence_eligibility": report["evidence_eligibility"], "independent_verification": False}


def accept_review(bundle, submission, output, approved_by):
    validate_bundle(bundle)
    bundle = directory(bundle)
    draft = read_json(base.project_path(bundle / DRAFT, "Draft transcript"))
    data = read_json(base.project_path(submission, "Review submission"))
    output = base.project_path(output, "Review output", output=True)
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise base.AdapterError("Explicit reviewer approval identity required")
    segments = {s["segment_id"]: s for s in draft["segments"]}
    if data.get("source_id") != draft["source_id"] or data.get("transcript_sha256") != gate.sha256_file(bundle / DRAFT):
        raise base.AdapterError("Review source/transcript binding mismatch")
    windows = data.get("windows")
    if not isinstance(windows, list) or not windows:
        raise base.AdapterError("Blank review remains pending")
    seen = set()
    for window in windows:
        if not isinstance(window, dict) or window.get("segment_id") not in segments or window["segment_id"] in seen:
            raise base.AdapterError("Invalid review segment identity")
        seen.add(window["segment_id"])
        original = segments[window["segment_id"]]
        if any(window.get(key) != original[key] for key in ("start_sec", "end_sec")) or window.get("original_recognized_text") != original["text"]:
            raise base.AdapterError("Review changed original text/timing binding")
        correction = window.get("corrected_transcription")
        if (window.get("review_status") != "reviewed" or window.get("reviewer_identity") != approved_by or
                not isinstance(window.get("review_method"), str) or not window["review_method"].strip() or
                not isinstance(correction, str) or not correction.strip() or
                any(c == "\ufffd" or unicodedata.category(c) in ("Cs", "Cc") for c in correction)):
            raise base.AdapterError("Invalid or unapproved human review claim")
        try:
            stamp = datetime.fromisoformat(window["verified_at"])
            if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise base.AdapterError("Invalid review timestamp") from None
    artifact = {"record_version": VERSION, "source_id": draft["source_id"], "transcript_sha256": data["transcript_sha256"],
                "submission_sha256": gate.sha256_file(base.project_path(submission, "Review submission")),
                "accepted_at": now(), "approved_by": approved_by, "attestation_status": "human_supplied_not_independently_verified",
                "coverage": "complete" if seen == set(segments) else "partial", "windows": windows,
                "text_verification_status": "unverified", "timing_verification_status": "unverified",
                "evidence_eligibility": {"transcript": False, "speech_alignment": False}}
    write_json(output, artifact)
    return artifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate", allow_abbrev=False)
    for name in ("video", "metadata", "analysis", "output-dir"):
        generate_parser.add_argument("--" + name, required=True)
    generate_parser.add_argument("--model", default="small")
    generate_parser.add_argument("--backend", choices=("local", "remote"), default="remote",
                                 help="Remote explicitly uploads speech audio to the configured endpoint")
    generate_parser.add_argument("--remote-config", default="config/speech-asr.remote.v01.json")
    generate_parser.add_argument("--asr-python", default=".venv-asr/bin/python")
    generate_parser.add_argument("--language", default="id", help="Language code or auto")
    generate_parser.add_argument("--beam-size", type=int, default=5)
    generate_parser.add_argument("--context", type=float, default=0.75)
    generate_parser.add_argument("--threads", type=int, default=4)
    generate_parser.add_argument("--memory-mib", type=int, default=4096)
    generate_parser.add_argument("--timeout", type=float, default=300)
    generate_parser.add_argument("--max-pcm-bytes", type=int, default=gate.MAX_PCM_BYTES)
    generate_parser.add_argument("--max-result-bytes", type=int, default=gate.MAX_JSON_BYTES)
    generate_parser.add_argument("--stream-index", type=int)
    generate_parser.add_argument("--expected-pcm-sha256")
    validate_parser = sub.add_parser("validate", allow_abbrev=False)
    validate_parser.add_argument("--bundle", required=True)
    review_parser = sub.add_parser("accept-review", allow_abbrev=False)
    for name in ("bundle", "submission", "output", "approved-by"):
        review_parser.add_argument("--" + name, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "generate":
            backend = args.pop("backend")
            remote_config = args.pop("remote_config")
            args["limits"] = limits_config(args.pop("threads"), args.pop("memory_mib"), args.pop("timeout"),
                                            args.pop("max_pcm_bytes"), args.pop("max_result_bytes"))
            if args["language"] == "auto":
                args["language"] = None
            if backend == "remote":
                import generate_remote_speech_evidence_v01 as remote
                result = remote.generate(**{k: args[k] for k in ("video", "metadata", "analysis", "output_dir", "context", "stream_index", "expected_pcm_sha256")},
                                         config=remote_config)
            else:
                result = generate(**args)
        elif command == "validate":
            bundle = directory(args["bundle"])
            manifest = read_json(base.project_path(bundle / MANIFEST, "Manifest"))
            if manifest.get("record_version") == "remote-asr-0.1.0":
                import generate_remote_speech_evidence_v01 as remote
                result = remote.validate_bundle(bundle)
            else:
                result = validate_bundle(**args)
        else:
            result = accept_review(**args)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0  # Completion of inspection, not evidence eligibility or ASR success.
    except (base.AdapterError, OSError, RecursionError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
