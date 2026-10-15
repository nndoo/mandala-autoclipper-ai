#!/usr/bin/env python3
"""Bounded, offline Faster-Whisper worker; no project or jsonschema dependency."""

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import resource
import socket
import sys
import time


class WorkerBlocked(ValueError):
    pass


def fingerprint(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def offline_limits(job):
    limits = job["limits"]
    memory = limits["memory_mib"]
    threads = limits["cpu_threads"]
    timeout = limits["asr_timeout_sec"]
    if type(memory) is not int or not 512 <= memory <= 8192 or type(threads) is not int or not 1 <= threads <= 8:
        raise WorkerBlocked("invalid_resource_limits")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 1800:
        raise WorkerBlocked("invalid_resource_limits")
    resource.setrlimit(resource.RLIMIT_AS, (memory * 1048576, memory * 1048576))
    cpu_seconds = math.ceil(timeout * threads)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      OMP_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS=str(threads))
    def deny_network(*args, **kwargs):
        raise WorkerBlocked("network_forbidden")
    socket.socket.connect = deny_network
    socket.create_connection = deny_network


def local_model(identifier):
    from faster_whisper.utils import download_model
    from huggingface_hub.constants import HF_HUB_CACHE
    candidate = Path(identifier).expanduser()
    cache = Path(HF_HUB_CACHE).resolve()
    if candidate.is_dir():
        model = candidate.resolve()
    else:
        if candidate.is_absolute() or identifier.startswith(".") or not cache.is_dir():
            raise WorkerBlocked("BLOCKED_MODEL_NOT_AVAILABLE")
        try:
            model = Path(download_model(identifier, local_files_only=True)).resolve()
        except Exception:
            raise WorkerBlocked("BLOCKED_MODEL_NOT_AVAILABLE") from None
    names = ["model.bin", "config.json", "tokenizer.json"]
    vocabulary = next((name for name in ("vocabulary.json", "vocabulary.txt") if (model / name).is_file()), None)
    if vocabulary is None:
        raise WorkerBlocked("BLOCKED_MODEL_NOT_AVAILABLE")
    names.append(vocabulary)
    if (model / "preprocessor_config.json").exists():
        names.append("preprocessor_config.json")
    files = []
    for name in names:
        path = model / name
        resolved = path.resolve()
        # Hugging Face snapshots legitimately link to blobs inside the same cache.
        if not resolved.is_relative_to(model) and not (model.is_relative_to(cache) and resolved.is_relative_to(cache)):
            raise WorkerBlocked("unsafe_model_symlink")
        if not resolved.is_file() or resolved.stat().st_size == 0:
            raise WorkerBlocked("BLOCKED_MODEL_NOT_AVAILABLE")
        files.append({"name": name, "sha256": fingerprint(resolved), "byte_count": resolved.stat().st_size})
    return {"identifier": identifier, "resolved_path": str(model), "files": files}


def execute(job):
    offline_limits(job)
    try:
        from faster_whisper import WhisperModel
        import numpy as np
    except ImportError:
        raise WorkerBlocked("runtime_dependencies_unavailable") from None
    runtime = {name: importlib.metadata.version(name) for name in ("faster-whisper", "ctranslate2", "numpy")}
    runtime["python"] = sys.version.split()[0]
    try:
        model_record = local_model(job["model"])
    except WorkerBlocked as error:
        return {"status": "blocked", "reason": str(error), "runtime": runtime}
    if job["action"] == "preflight":
        return {"status": "complete", "action": "preflight", "model": model_record, "runtime": runtime}
    if job["action"] != "transcribe":
        raise WorkerBlocked("invalid_worker_action")
    started = time.monotonic()
    model = WhisperModel(model_record["resolved_path"], device="cpu", compute_type="int8",
                         cpu_threads=job["limits"]["cpu_threads"], num_workers=1, local_files_only=True)
    regions = []
    for region in job["regions"]:
        path = Path(region["pcm_path"])
        if path.stat().st_size > job["limits"]["max_pcm_bytes"]:
            raise WorkerBlocked("pcm_resource_limit")
        pcm = path.read_bytes()
        if not pcm or len(pcm) % 2 or hashlib.sha256(pcm).hexdigest() != region["pcm_sha256"]:
            raise WorkerBlocked("region_pcm_integrity_mismatch")
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        segments, info = model.transcribe(audio, **job["decoding_options"])
        regions.append({
            "region_id": region["region_id"], "pcm_sha256": region["pcm_sha256"],
            "sample_count": len(pcm) // 2,
            "info": {"language": info.language, "language_probability": info.language_probability,
                     "duration": info.duration, "duration_after_vad": info.duration_after_vad,
                     "all_language_probs": info.all_language_probs,
                     "resolved_decoding_options": asdict(info.transcription_options)},
            "segments": [asdict(segment) for segment in segments],
        })
    if local_model(model_record["resolved_path"])["files"] != model_record["files"]:
        raise WorkerBlocked("model_changed_during_execution")
    return {"status": "complete", "action": "transcribe", "model": model_record, "runtime": runtime,
            "elapsed_sec": time.monotonic() - started, "regions": regions}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.job.stat().st_size > 8 * 1048576:
            raise WorkerBlocked("job_resource_limit")
        job = json.loads(args.job.read_text())
        result = execute(job)
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False)
    except WorkerBlocked as error:
        encoded = json.dumps({"status": "blocked", "reason": str(error)})
    except MemoryError:
        encoded = json.dumps({"status": "blocked", "reason": "resource_limit"})
    except Exception:
        encoded = json.dumps({"status": "blocked", "reason": "asr_execution_failed"})
    print(encoded)
    return 0  # Parent evaluates this structured status, never exit code alone.


if __name__ == "__main__":
    sys.exit(main())
