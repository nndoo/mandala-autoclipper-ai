#!/usr/bin/env python3
"""Explicit remote ASR option; reuses Stage 5B source checks and Stage 5A gate."""

import argparse
import io
import json
import os
from pathlib import Path
import re
import resource
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
import wave

import generate_speech_evidence_v01 as local

base = local.base
gate = local.gate
DEFAULT_CONFIG = "config/speech-asr.remote.v01.json"
VERSION = "remote-asr-0.1.0"
LIMITATIONS = local.LIMITATIONS + [
    "Remote server/model weights, compute, versions and internal decoding are not independently observable",
    "Request regions identify uploaded context only; they never substitute for missing ASR timestamps",
]


def load_config(value):
    path = base.project_path(value, "Remote ASR config")
    config = local.read_json(path)
    try:
        url = urlsplit(config["endpoint"])
        if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or
                url.path != "/v1/audio/transcriptions"):
            raise ValueError()
        if not isinstance(config["model"], str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,128}", config["model"]):
            raise ValueError()
        if config["response_format"] not in ("json", "verbose_json") or config["temperature"] != 0:
            raise ValueError()
        if config["language"] is not None and not re.fullmatch(r"[a-z]{2}", config["language"]):
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", config["api_key_env"]):
            raise ValueError()
        if not isinstance(config["openclaw_provider"], (str, type(None))):
            raise ValueError()
        if not local.finite(config["timeout_sec"]) or not 1 <= config["timeout_sec"] <= 300:
            raise ValueError()
        for name, maximum in (("max_upload_bytes", 25 * 1048576), ("max_response_bytes", gate.MAX_JSON_BYTES)):
            if type(config[name]) is not int or not 1024 <= config[name] <= maximum:
                raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise base.AdapterError("Invalid remote ASR configuration") from None
    # Keep unknown configuration fields out of receipts (in particular accidental secrets).
    names = ("endpoint", "model", "response_format", "language", "temperature", "api_key_env", "openclaw_provider",
             "timeout_sec", "max_upload_bytes", "max_response_bytes")
    return path, {key: config[key] for key in names}


def credentials(config):
    key = os.environ.get(config["api_key_env"])
    origin = "environment:" + config["api_key_env"]
    private = base.ROOT / ".env.asr"
    if not key and private.exists():
        if private.is_symlink() or private.stat().st_size > 8192 or private.stat().st_mode & 0o077:
            raise base.AdapterError("Private ASR credential file must be regular, private and bounded")
        values = dict(line.split("=", 1) for line in private.read_text().splitlines() if "=" in line and not line.startswith("#"))
        key = values.get(config["api_key_env"])
        origin = "project_private_env"
    if not key and config["openclaw_provider"]:
        path = Path.home() / ".openclaw/openclaw.json"
        try:
            if path.stat().st_size > gate.MAX_JSON_BYTES:
                raise ValueError()
            provider = base.load_object(path, "OpenClaw config")["models"]["providers"][config["openclaw_provider"]]
            if provider["baseUrl"].rstrip("/") + "/audio/transcriptions" != config["endpoint"]:
                raise base.AdapterError("Credential provider endpoint mismatch")
            key = provider.get("apiKey")
            if isinstance(key, str) and re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", key):
                key = os.environ.get(key[2:-1])
            origin = "openclaw_provider:" + config["openclaw_provider"]
        except (OSError, ValueError, KeyError, TypeError):
            raise base.AdapterError("Remote ASR credential unavailable or provider mismatched") from None
    if not isinstance(key, str) or not key or any(c.isspace() for c in key):
        raise base.AdapterError("Remote ASR credential unavailable")
    return key, origin


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward Authorization or audio to a redirected target.


def request_transcription(config, upload):
    key, origin = credentials(config)
    if upload.stat().st_size > config["max_upload_bytes"]:
        raise base.AdapterError("Remote upload resource limit exceeded")
    boundary = "mandala-" + uuid.uuid4().hex
    parts = []
    fields = {"model": config["model"], "response_format": config["response_format"], "temperature": "0"}
    if config["language"]:
        fields["language"] = config["language"]
    if config["response_format"] == "verbose_json":
        # Keep default request matching the user's tested json request; richer timing is explicit.
        fields["timestamp_granularities[]"] = "word"
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode(),
                  upload.read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
    request = urllib.request.Request(config["endpoint"], data=b"".join(parts), method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "multipart/form-data; boundary=" + boundary,
        "Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    started = time.monotonic()
    try:
        with opener.open(request, timeout=config["timeout_sec"]) as response:
            encoded = response.read(config["max_response_bytes"] + 1)
            if len(encoded) > config["max_response_bytes"]:
                return {"status": "blocked", "reason": "remote_response_resource_limit"}
            if key.encode() in encoded:
                return {"status": "blocked", "reason": "remote_response_sensitive_content"}
            payload = json.loads(encoded, object_pairs_hook=base.unique_object, parse_constant=base.reject_constant)
            if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
                raise ValueError()
            return {"status": "complete", "http_status": response.status, "elapsed_sec": time.monotonic() - started,
                    "credential_source": origin, "payload": payload}
    except urllib.error.HTTPError as error:
        # Never log body, request headers, credentials or arbitrary upstream diagnostics.
        error.close()
        return {"status": "blocked", "reason": "remote_http_error", "http_status": error.code}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": "blocked", "reason": "remote_transport_error"}
    except (ValueError, UnicodeError, RecursionError):
        return {"status": "blocked", "reason": "malformed_remote_response"}


def remote_call(config, upload, temporary):
    job_path = temporary / "remote-job.json"
    # Secret is resolved in the subprocess, never sent through argv or a job file.
    job_path.write_text(json.dumps({"config": config, "upload": str(upload)}), encoding="utf-8")
    chunks = []
    try:
        base.bounded_run([sys.executable, "-B", str(Path(__file__)), "--http-job", str(job_path)], chunks.append,
                         max_bytes=config["max_response_bytes"] + 65536, timeout=config["timeout_sec"])
        result = json.loads(b"".join(chunks), object_pairs_hook=base.unique_object, parse_constant=base.reject_constant)
        if not isinstance(result, dict) or result.get("status") not in ("complete", "blocked"):
            raise ValueError()
        return result
    except base.AdapterError:
        return {"status": "blocked", "reason": "remote_worker_bounded_execution_failed"}
    except (ValueError, UnicodeError, RecursionError):
        return {"status": "blocked", "reason": "malformed_remote_response"}


def write_wav(pcm_path, output):
    with wave.open(str(output), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(pcm_path.read_bytes())


def project_response(raw, regions, source, digest, pcm, config):
    mapping = {r["region_id"]: r for r in regions}
    responses = raw.get("regions")
    if (not isinstance(responses, list) or len(responses) != len(mapping) or
            any(not isinstance(r, dict) for r in responses) or {r.get("region_id") for r in responses} != set(mapping)):
        raise base.AdapterError("Remote response region mismatch")
    recognized = []
    segments = []
    provider_words = []
    for response in responses:
        region = mapping[response["region_id"]]
        if response["upload_pcm_sha256"] != region["pcm_sha256"] or response["status"] != "complete":
            raise base.AdapterError("Remote upload PCM binding mismatch")
        payload = response["payload"]
        if not isinstance(payload.get("text"), str):
            raise base.AdapterError("Malformed remote transcript text")
        recognized.append({"region_id": region["region_id"], "context_start_sec": region["offset_sec"],
                           "context_end_sec": region["processing_end_sec"], "text": payload["text"],
                           "reported_model": payload.get("model"),
                           "timing_status": "provider_reported" if payload.get("segments") else "unavailable"})
        def timestamp(value):
            return value + region["offset_sec"] if local.finite(value) else value
        def word(w):
            if not isinstance(w, dict):
                raise base.AdapterError("Malformed remote word")
            return {"start_sec": timestamp(w.get("start")), "end_sec": timestamp(w.get("end")),
                    "word": w.get("word"), "probability": w.get("probability")}
        returned_words = payload.get("words") or []
        returned_segments = payload.get("segments") or []
        if not isinstance(returned_words, list) or not isinstance(returned_segments, list):
            raise base.AdapterError("Malformed remote timing arrays")
        words = [word(w) for w in returned_words]
        provider_words.extend({**w, "region_id": region["region_id"]} for w in words)
        for index, segment in enumerate(returned_segments):
            if not isinstance(segment, dict):
                raise base.AdapterError("Malformed remote segment")
            start, end = timestamp(segment.get("start")), timestamp(segment.get("end"))
            segment_words = segment.get("words")
            if segment_words is not None:
                if not isinstance(segment_words, list):
                    raise base.AdapterError("Malformed remote segment words")
                segment_words = [word(w) for w in segment_words]
            else:
                segment_words = [w for w in words if all(local.finite(v) for v in (start, end, w["start_sec"], w["end_sec"]))
                                 and start <= w["start_sec"] < w["end_sec"] <= end]
            segments.append({"segment_id": f"{region['region_id']}-segment-{index+1:04d}", "region_id": region["region_id"],
                             "raw_segment_id": segment.get("id"), "start_sec": start, "end_sec": end,
                             "text": segment.get("text"), "language": payload.get("language"), "words": segment_words,
                             **{key: segment.get(key) for key in ("avg_logprob", "no_speech_prob", "compression_ratio")}})
    return {"record_version": VERSION, "source_id": source["video_id"], "source_video": source["file_name"],
            "engine": "remote-openai-compatible", "model": config["model"], "compute": "remote_unobserved",
            "timing_status": "estimated_not_verified" if segments else "unavailable", "text_verification_status": "unverified",
            "provenance": {"source_sha256": digest, "audio_pcm_sha256": pcm["sha256"]},
            "recognized_regions": recognized, "provider_words": provider_words, "segments": segments}


def assessments(draft, regions, duration):
    quality = local.assess(draft, regions, duration, None)
    flags = quality["flags"]
    seen = set()
    for region in draft["recognized_regions"]:
        if not region["text"].strip():
            flags.append({"code": "empty_remote_transcript", "segment_id": region["region_id"]})
        elif not any(s["region_id"] == region["region_id"] for s in draft["segments"]):
            flags.append({"code": "text_available_without_provider_timestamps", "segment_id": region["region_id"]})
        normalized = " ".join(region["text"].casefold().split())
        if normalized in seen or re.search(r"(\b\w+\b)(?:\s+\1){3,}", normalized):
            flags.append({"code": "repeated_or_suspicious_text", "segment_id": region["region_id"]})
        seen.add(normalized)
        if any(c == "\ufffd" or local.unicodedata.category(c) == "Cs" or local.unicodedata.category(c) == "Cc" and c not in "\n\t\r" for c in region["text"]):
            flags.append({"code": "invalid_or_suspicious_encoding", "segment_id": region["region_id"]})
        if region["reported_model"] is not None and region["reported_model"] not in (draft["model"], draft["model"].removeprefix("groq/")):
            flags.append({"code": "reported_model_mismatch", "segment_id": region["region_id"]})
    timing = local.timing_artifact(draft)
    timing.update(record_version=VERSION, method="remote_provider_reported_timestamps", words=draft["provider_words"],
                  precision="ASR_estimate" if draft["segments"] or draft["provider_words"] else "unavailable",
                  timing_verification_status="unverified" if draft["segments"] or draft["provider_words"] else "unavailable")
    quality["timing_verification_status"] = timing["timing_verification_status"]
    for word in draft["provider_words"]:
        region = next(r for r in regions if r["region_id"] == word["region_id"])
        if (not all(local.finite(word[k]) for k in ("start_sec", "end_sec")) or
                not region["offset_sec"] <= word["start_sec"] < word["end_sec"] <= min(duration, region["processing_end_sec"])):
            flags.append({"code": "invalid_provider_word_timestamps", "segment_id": word["region_id"]})
            quality["structure_status"] = "failed"
    return quality, timing


def review_template(draft, digest):
    review = local.review_template(draft, digest)
    review["record_version"] = VERSION
    for region in draft["recognized_regions"]:
        if not any(s["region_id"] == region["region_id"] for s in draft["segments"]):
            review["windows"].append({"region_id": region["region_id"], "start_sec": None, "end_sec": None,
                                      "context_start_sec": region["context_start_sec"], "context_end_sec": region["context_end_sec"],
                                      "original_recognized_text": region["text"], "review_status": "pending",
                                      "corrected_transcription": None, "reviewer_identity": None,
                                      "review_method": None, "verified_at": None})
    return review


def make_report(manifest, manifest_hash, inspection, quality, timing):
    completed = manifest["generation_status"] == "complete"
    return {"record_version": VERSION, "backend": "remote", "manifest_sha256": manifest_hash,
            "generation_status": manifest["generation_status"], "generation_provenance_status": "recorded" if completed else "unavailable",
            "source_integrity_status": "verified", "audio_integrity_status": "verified" if manifest["audio"]["source_pcm"] else "unavailable",
            "text_verification_status": "unverified" if completed else "unavailable",
            "timing_verification_status": timing["timing_verification_status"] if timing else "unavailable",
            "human_review_status": "pending" if completed else "not_performed", "quality_assessment": quality,
            "evidence_eligibility": inspection["evidence_eligibility"],
            "director_attachments": {"transcript": None, "speech_alignment": None}, "limitations": LIMITATIONS}


def generate(video, metadata, analysis, output_dir, *, config=DEFAULT_CONFIG, context=0.75, stream_index=None,
             expected_pcm_sha256=None):
    output = local.directory(output_dir, new=True)
    config_path, settings = load_config(config)
    paths, source, digest, canonical, warnings = local.verified_inputs(video, metadata, analysis)
    paths["remote_config"] = config_path
    hashes = {key: gate.sha256_file(path) for key, path in paths.items()}
    requirement = gate.speech_requirements(canonical)
    regions = local.select_regions(requirement, source["duration_sec"], context)
    status = "needs_review" if requirement["classification_conflicts"] else requirement["overall_requirement"]
    streams = gate.audio_streams(paths["video"])
    stream = next((s for s in streams if s["index"] == stream_index), None) if stream_index is not None else next(iter(streams), None)
    if stream_index is not None and stream is None:
        raise base.AdapterError("Requested audio stream unavailable")
    started = local.now()
    pcm, public_regions, artifacts, quality, timing, failure = None, [], {}, None, None, None
    with tempfile.TemporaryDirectory(prefix="mandala-remote-speech-") as name:
        temporary = Path(name)
        if stream:
            pcm = local.capture_pcm(paths["video"], stream, temporary / "source.pcm", local.limits_config())
            if pcm != gate.pcm_fingerprint(paths["video"], stream["index"]) or expected_pcm_sha256 is not None and pcm["sha256"] != expected_pcm_sha256:
                raise base.AdapterError("Audio fingerprint mismatch")
        if status == "required":
            if not pcm:
                status = "source_audio_stream_unavailable"
            else:
                jobs = local.prepare_regions(regions, temporary / "source.pcm", temporary, pcm)
                public_regions = [{k: v for k, v in r.items() if k != "pcm_path"} for r in jobs]
                raw = {"record_version": VERSION, "backend": "remote", "regions": []}
                for region in jobs:
                    upload = temporary / (region["region_id"] + ".wav")
                    write_wav(Path(region["pcm_path"]), upload)
                    if upload.stat().st_size > settings["max_upload_bytes"]:
                        raise base.AdapterError("Remote upload resource limit exceeded")
                    response = remote_call(settings, upload, temporary)
                    raw["regions"].append({**response, "region_id": region["region_id"], "upload_pcm_sha256": region["pcm_sha256"],
                                           "upload_file_sha256": gate.sha256_file(upload), "upload_byte_count": upload.stat().st_size})
                    if response["status"] != "complete":
                        status, failure = "remote_asr_failed", response
                        break  # No automatic retry, format fallback or provider/model substitution.
                else:
                    status = "complete"
                    draft = project_response(raw, public_regions, {**source, "file_name": paths["video"].name}, digest, pcm, settings)
                    quality, timing = assessments(draft, public_regions, source["duration_sec"])
                    artifacts = {local.RAW: raw, local.DRAFT: draft, local.TIMING: timing}
                artifacts[local.RAW] = raw  # Preserve completed earlier responses if a later region fails.
        if any(gate.sha256_file(path) != hashes[key] for key, path in paths.items()):
            raise base.AdapterError("Inputs changed during remote execution")
    output.parent.mkdir(parents=True, exist_ok=True)
    output = local.directory(output, new=True)
    output.mkdir(mode=0o700)
    created = []
    try:
        def publish(name, data):
            local.write_json(output / name, data)
            created.append(output / name)
        for name, data in artifacts.items():
            publish(name, data)
        if local.DRAFT in artifacts:
            publish(local.REVIEW, review_template(artifacts[local.DRAFT], gate.sha256_file(output / local.DRAFT)))
        inspection = gate.inspect_provenance(paths["video"], paths["metadata"], paths["analysis"], output / local.GATE,
                                            transcript=output / local.DRAFT if local.DRAFT in artifacts else None,
                                            review=output / local.REVIEW if local.DRAFT in artifacts else None,
                                            stream_index=stream["index"] if stream else None)
        created.append(output / local.GATE)
        if inspection["audio"]["source_pcm"] != pcm or any(gate.sha256_file(path) != hashes[key] for key, path in paths.items()):
            raise base.AdapterError("Inputs/source PCM changed during publication")
        manifest = {"record_version": VERSION, "backend": "remote", "generation_status": status,
                    "generation_provenance_status": "recorded" if status == "complete" else "unavailable",
                    "started_at": started, "finished_at": local.now(), "source": source,
                    "inputs": {key: {"path": local.relative(path), "sha256": hashes[key]} for key, path in paths.items()},
                    "speech_requirements": requirement, "processing_regions": public_regions, "region_context_sec": context,
                    "audio": {"stream": stream, "source_pcm": pcm, "pcm_parameters": gate.PCM_PARAMETERS},
                    "remote_request": settings, "remote_model_artifact_sha256": None, "remote_runtime_versions": None,
                    "execution_failure": failure, "media_tools": inspection["inspection_tools"],
                    "generator": {"version": VERSION, "script_sha256": gate.sha256_file(Path(__file__)),
                                  "local_helpers_sha256": gate.sha256_file(Path(local.__file__))},
                    "artifacts": {p.name: {"path": p.name, "sha256": gate.sha256_file(p)} for p in created},
                    "hash_boundary": "Manifest hashes leaves; report hashes manifest; no credentials or cyclic hashes",
                    "canonical_warnings": warnings, "limitations": LIMITATIONS}
        publish(local.MANIFEST, manifest)
        report = make_report(manifest, gate.sha256_file(output / local.MANIFEST), inspection, quality, timing)
        publish(local.REPORT, report)
        return report
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            output.rmdir()
        except OSError:
            pass
        raise


def validate_bundle(bundle):
    """Offline verification; no remote requests or credential reads."""
    bundle = local.directory(bundle)
    manifest = local.read_json(base.project_path(bundle / local.MANIFEST, "Manifest"))
    report = local.read_json(base.project_path(bundle / local.REPORT, "Report"))
    try:
        required = {"record_version", "backend", "generation_status", "generation_provenance_status", "started_at", "finished_at",
                    "source", "inputs", "speech_requirements", "processing_regions", "region_context_sec", "audio", "remote_request",
                    "remote_model_artifact_sha256", "remote_runtime_versions", "execution_failure", "media_tools", "generator", "artifacts"}
        if not required <= set(manifest):
            raise base.AdapterError("Missing remote generation provenance")
        if any(not re.fullmatch(r"[0-9a-f]{64}", manifest["generator"][key]) for key in ("script_sha256", "local_helpers_sha256")):
            raise base.AdapterError("Malformed remote generator provenance")
        started = local.datetime.fromisoformat(manifest["started_at"])
        finished = local.datetime.fromisoformat(manifest["finished_at"])
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise base.AdapterError("Invalid remote generation timestamps")
        if manifest["record_version"] != VERSION or manifest["backend"] != "remote" or report["manifest_sha256"] != gate.sha256_file(bundle / local.MANIFEST):
            raise base.AdapterError("Remote manifest integrity mismatch")
        completed = manifest["generation_status"] == "complete"
        required_artifacts = local.LEAVES if completed else {local.GATE, local.RAW} if manifest["generation_status"] == "remote_asr_failed" else {local.GATE}
        if set(manifest["artifacts"]) != required_artifacts:
            raise base.AdapterError("Remote artifact provenance incomplete")
        leaves = {}
        for name, record in manifest["artifacts"].items():
            if record["path"] != name or (bundle / name).is_symlink():
                raise base.AdapterError("Unsafe remote artifact path")
            path = base.project_path(bundle / name, "Artifact")
            if gate.sha256_file(path) != record["sha256"]:
                raise base.AdapterError("Remote artifact integrity mismatch")
            leaves[name] = local.read_json(path)
        paths, source, digest, canonical, _ = local.verified_inputs(**{key: manifest["inputs"][key]["path"] for key in ("video", "metadata", "analysis")})
        config_path, config = load_config(manifest["inputs"]["remote_config"]["path"])
        paths["remote_config"] = config_path
        if any(gate.sha256_file(path) != manifest["inputs"][key]["sha256"] for key, path in paths.items()) or source != manifest["source"] or config != manifest["remote_request"]:
            raise base.AdapterError("Remote input/config provenance mismatch")
        requirement = gate.speech_requirements(canonical)
        decision = "needs_review" if requirement["classification_conflicts"] else requirement["overall_requirement"]
        if requirement != manifest["speech_requirements"] or manifest["generation_status"] not in ("complete", "remote_asr_failed", "source_audio_stream_unavailable", "not_required", "needs_review"):
            raise base.AdapterError("Remote speech decision mismatch")
        if decision != "required" and manifest["generation_status"] != decision or decision == "required" and manifest["generation_status"] in ("not_required", "needs_review"):
            raise base.AdapterError("Remote speech requirement bypass")
        stream = manifest["audio"]["stream"]
        streams = gate.audio_streams(paths["video"])
        if stream is not None and stream not in streams or stream is None and streams:
            raise base.AdapterError("Remote audio stream mismatch")
        pcm = gate.pcm_fingerprint(paths["video"], stream["index"]) if stream else None
        if pcm != manifest["audio"]["source_pcm"] or manifest["audio"]["pcm_parameters"] != gate.PCM_PARAMETERS:
            raise base.AdapterError("Remote audio provenance mismatch")
        inspection = leaves[local.GATE]
        if inspection["source"]["sha256"] != digest or inspection["audio"]["source_pcm"] != pcm:
            raise base.AdapterError("Remote gate source mismatch")
        if inspection["evidence_eligibility"]["transcript"] is not False or inspection["evidence_eligibility"]["speech_alignment"] is not False:
            raise base.AdapterError("Unsafe remote attachment eligibility")
        quality, timing = None, None
        if completed:
            if manifest["generation_provenance_status"] != "recorded" or manifest["remote_model_artifact_sha256"] is not None or manifest["remote_runtime_versions"] is not None:
                raise base.AdapterError("False remote model provenance")
        if local.RAW in leaves:
            with tempfile.TemporaryDirectory(prefix="mandala-remote-validation-") as name:
                temporary = Path(name)
                if local.capture_pcm(paths["video"], stream, temporary / "source.pcm", local.limits_config()) != pcm:
                    raise base.AdapterError("Remote validation PCM mismatch")
                selected = local.select_regions(requirement, source["duration_sec"], manifest["region_context_sec"])
                jobs = local.prepare_regions(selected, temporary / "source.pcm", temporary, pcm)
                public = [{k: v for k, v in r.items() if k != "pcm_path"} for r in jobs]
                if public != manifest["processing_regions"]:
                    raise base.AdapterError("Remote region provenance mismatch")
                response_list = leaves[local.RAW]["regions"]
                responses = {r["region_id"]: r for r in response_list}
                if not responses or len(responses) != len(response_list) or not set(responses) <= {r["region_id"] for r in jobs}:
                    raise base.AdapterError("Remote response region identity mismatch")
                for region in jobs:
                    if region["region_id"] not in responses:
                        continue
                    upload = temporary / "verify.wav"
                    write_wav(Path(region["pcm_path"]), upload)
                    response = responses[region["region_id"]]
                    if (response["upload_file_sha256"] != gate.sha256_file(upload) or response["upload_pcm_sha256"] != region["pcm_sha256"] or
                            response["upload_byte_count"] != upload.stat().st_size):
                        raise base.AdapterError("Remote upload hash mismatch")
        if completed:
            draft = project_response(leaves[local.RAW], public, {**source, "file_name": paths["video"].name}, digest, pcm, config)
            quality, timing = assessments(draft, public, source["duration_sec"])
            if draft != leaves[local.DRAFT] or timing != leaves[local.TIMING] or review_template(draft, manifest["artifacts"][local.DRAFT]["sha256"]) != leaves[local.REVIEW]:
                raise base.AdapterError("Remote transcript/timing/review projection mismatch")
        elif manifest["generation_provenance_status"] != "unavailable":
            raise base.AdapterError("False remote generation provenance")
        if report != make_report(manifest, gate.sha256_file(bundle / local.MANIFEST), inspection, quality, timing):
            raise base.AdapterError("Remote report mismatch or false verification")
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        if isinstance(error, base.AdapterError):
            raise
        raise base.AdapterError("Malformed remote provenance") from None
    return {"integrity_status": "checked", "backend": "remote", "generation_status": manifest["generation_status"],
            "evidence_eligibility": report["evidence_eligibility"], "independent_verification": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--http-job", help=argparse.SUPPRESS)
    parser.add_argument("--validate-bundle")
    for name in ("video", "metadata", "analysis", "output-dir"):
        parser.add_argument("--" + name)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--context", type=float, default=0.75)
    parser.add_argument("--stream-index", type=int)
    parser.add_argument("--expected-pcm-sha256")
    args = vars(parser.parse_args(argv))
    job_path = args.pop("http_job")
    bundle = args.pop("validate_bundle")
    try:
        if job_path:
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1048576, 512 * 1048576))
            resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
            job = local.read_json(Path(job_path))
            result = request_transcription(job["config"], Path(job["upload"]))
        elif bundle:
            result = validate_bundle(bundle)
        else:
            if any(not args[name] for name in ("video", "metadata", "analysis", "output_dir")):
                parser.error("--video, --metadata, --analysis and --output-dir are required")
            result = generate(**args)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except MemoryError:
        print(json.dumps({"status": "blocked", "reason": "remote_resource_limit"}))
        return 1
    except (base.AdapterError, OSError, RecursionError):
        # Do not echo arbitrary exceptions from HTTP/config/credential boundaries.
        print(json.dumps({"status": "blocked", "reason": "remote_execution_blocked"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
