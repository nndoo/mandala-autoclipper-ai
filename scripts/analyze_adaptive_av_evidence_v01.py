#!/usr/bin/env python3
"""Offline Stage 5C measurements, candidates and source-bound V0.3 enrichment."""

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import signal
import statistics
import sys
import tempfile

import generate_speech_evidence_v01 as shared

base = shared.base
gate = shared.gate
VERSION = "0.1.0"
AUDIO = "music-rhythm.v01.json"
VISUAL = "visual-timing.v01.json"
CORRELATION = "audiovisual-correlation.v01.json"
REPORT = "validation.v01.json"
ENRICHED = "director-input.enriched.v03.json"
PARAMETERS = {
    "max_duration_sec": 180, "max_decoded_frames": 25000,
    "audio_window_samples": 320, "audio_sample_rate": 16000,
    "audio_fft_window": "hann", "onset_novelty_weights": [0.6, 0.4],
    "visual_target_fps": 8, "visual_width": 64, "visual_height": 64,
    "max_sampled_frames": 1500, "decode_timeout_sec": 60,
    "max_json_bytes": 8388608, "max_visual_bytes": 18432000,
    "max_pcm_bytes": 6400000, "pipeline_timeout_sec": 240,
    "worker_memory_mib": 1024, "worker_cpu_sec": 180,
    "correlation_tolerance_sec": 0.25,
}
LIMITATIONS = [
    "Unsigned local hashes and deterministic replay establish consistency, not independent authentication",
    "Canonical semantics and regional speech/music classifications remain unverified AI interpretations",
    "Signal peaks are not musical beats, speech boundaries, or speech-safe cuts",
    "Downscaled sampled-frame differences cannot verify editorial boundaries, camera movement types or reveals",
    "Temporal proximity does not prove intentional audiovisual synchronization or editing quality",
    "No text/timing review, renderer capability verification, render or publish approval is performed",
]
AUDIO_KINDS = {"onset_candidate", "energy_peak", "quiet_region", "abrupt_audio_change", "intensity_change"}
VISUAL_KINDS = {"hard_cut_candidate", "visual_change_candidate", "brightness_change", "flash_candidate",
                "fade_candidate", "high_motion_candidate", "motion_change", "stable_region"}


def checked_path(value, label, *, output=False):
    if ".." in Path(value).parts:
        raise base.AdapterError(label + ": path traversal rejected")
    return base.project_path(value, label, output=output)


def read(path):
    return shared.read_json(path)


def reference(path):
    return {"path": shared.relative(path), "sha256": gate.sha256_file(path)}


def code_receipts():
    return [reference(Path(__file__).resolve()), reference(Path(shared.__file__).resolve()),
            reference(Path(gate.__file__).resolve()), reference(Path(base.__file__).resolve()),
            reference(base.ROOT / "scripts/validate_universal_analysis_v02.py"),
            reference(base.ROOT / "src/schemas/adaptive-av-evidence.v0.1.schema.json"),
            reference(base.ROOT / "src/schemas/adaptive-av-validation.v0.1.schema.json"),
            reference(base.ROOT / "requirements-av.txt")]


def libraries():
    try:
        import numpy
        import scipy
        from scipy import fft, signal
    except ImportError:
        raise base.AdapterError("NumPy/SciPy unavailable; use the approved .venv-av runtime") from None
    return numpy, scipy, fft, signal


def event(identifier, kind, start, end, *, time=None, uncertainty=0.02, confidence="medium", metrics=None):
    return {"event_id": identifier, "kind": kind, "start_sec": start, "end_sec": end,
            "time_sec": start if time is None else time, "uncertainty_sec": uncertainty,
            "basis": "signal_estimate", "confidence": confidence, "verified_fact": False,
            "measurements": metrics or {}}


def region_context(canonical):
    requirement = gate.speech_requirements(canonical)
    profile = canonical["content_profile"]["music_presence"]
    segments = canonical["segments"]
    conflicts = []
    if profile == "absent" and any("music" in s["audio_layers"] for s in segments):
        conflicts.append("absent_music_profile_with_regional_music")
    if (profile == "present" and requirement["temporal_coverage"]["status"] == "complete"
            and all(s["audio_layers"] and "unknown" not in s["audio_layers"] for s in segments)
            and not any("music" in s["audio_layers"] for s in segments)):
        conflicts.append("present_music_profile_without_regional_music")
    blocked = bool(conflicts or requirement["classification_conflicts"] or
                   requirement["overall_requirement"] == "needs_review" or not canonical["analysis_meta"]["audio_examined"])
    regions = []
    for s, speech in zip(segments, requirement["regions"]):
        layers = s["audio_layers"]
        suitable = (not blocked and profile == "present" and "music" in layers and
                    "speech" not in layers and "unknown" not in layers and speech["requirement"] == "not_required")
        regions.append({"segment_id": s["segment_id"], "start_sec": s["start_sec"], "end_sec": s["end_sec"],
                        "audio_layers": layers, "speech_requirement": speech["requirement"],
                        "music_analysis_suitable": suitable, "classification_basis": "canonical_unverified"})
    # Overlapping contradictory regions are also unsuitable for beat attribution.
    for r in regions:
        if any(o is not r and max(o["start_sec"], r["start_sec"]) < min(o["end_sec"], r["end_sec"])
               and not o["music_analysis_suitable"] for o in regions):
            r["music_analysis_suitable"] = False
    return {"basis": "canonical_unverified", "music_presence": profile,
            "speech": requirement, "music_classification_conflicts": conflicts, "regions": regions}


def energy_windows(pcm_path, start_sec, duration):
    np, _, fft, _ = libraries()
    windows = []
    index = 0
    previous_spectrum = None
    with pcm_path.open("rb") as file:
        while chunk := file.read(PARAMETERS["audio_window_samples"] * 2):
            if len(chunk) % 2:
                raise base.AdapterError("Incomplete PCM sample")
            samples = np.frombuffer(chunk, dtype="<i2").astype(np.float64)/32768
            start = start_sec + index / 16000
            if start >= duration:
                break
            samples = samples[:max(0, math.floor((duration-start)*16000+1e-6))]
            if not len(samples):
                break
            end = start_sec + (index+len(samples))/16000
            rms = float(np.sqrt(np.mean(samples*samples)))
            spectrum = np.abs(fft.rfft(samples*np.hanning(len(samples))))/len(samples)
            flux = (float(np.maximum(spectrum-previous_spectrum, 0).sum()/(spectrum.sum()+previous_spectrum.sum()+1e-12))
                    if previous_spectrum is not None and len(spectrum) == len(previous_spectrum) else 0.0)
            total = float(spectrum.sum())
            centroid = float(np.dot(spectrum, fft.rfftfreq(len(samples), 1/16000))/total) if total else 0.0
            windows.append({"start_sec": start, "end_sec": end, "rms": rms,
                            "dbfs": max(-120.0, 20 * math.log10(rms)) if rms else -120.0,
                            "spectral_flux": flux, "spectral_centroid_hz": centroid})
            previous_spectrum = spectrum
            index += len(samples)
    return windows


def audio_events(windows):
    if not windows:
        return [], []
    np, _, _, signal = libraries()
    rms = [w["rms"] for w in windows]
    peak = max(rms)
    energy_novelty = [max(0.0, n - statistics.mean(rms[max(0, i-5):i])) / peak if i and peak else 0.0
                      for i, n in enumerate(rms)]
    novelty = [0.6*n+0.4*w["spectral_flux"] for n, w in zip(energy_novelty, windows)]
    median = statistics.median(novelty)
    threshold = max(0.06, median + 3 * statistics.median(abs(n - median) for n in novelty))
    events = []
    last = {"onset_candidate": -1, "energy_peak": -1, "abrupt_audio_change": -1, "intensity_change": -1}
    def add(kind, index, metrics):
        w = windows[index]
        if w["start_sec"] - last[kind] < (0.10 if kind in ("onset_candidate", "energy_peak") else 0.25):
            return
        events.append(event("audio-%04d" % (len(events)+1), kind, w["start_sec"], w["end_sec"], metrics=metrics))
        last[kind] = w["start_sec"]
    onset_indices = set(signal.find_peaks(np.asarray(novelty), height=threshold, distance=5)[0])
    energy_indices = set(signal.find_peaks(np.asarray(rms), height=max(0.003, 0.45*peak), distance=5)[0])
    for i in range(1, len(windows)-1):
        if peak > 0.003 and i in onset_indices:
            add("onset_candidate", i, {"combined_novelty": novelty[i], "energy_novelty": energy_novelty[i],
                                       "spectral_flux": windows[i]["spectral_flux"], "threshold": threshold})
        if peak > 0.003 and i in energy_indices:
            add("energy_peak", i, {"rms": rms[i]})
        delta = windows[i]["dbfs"] - windows[i-1]["dbfs"]
        if abs(delta) >= 8 and max(rms[i], rms[i-1]) > max(0.003, peak * 0.1):
            add("abrupt_audio_change", i, {"db_change": delta})
        if i >= 25 and abs(windows[i]["dbfs"] - windows[i-25]["dbfs"]) >= 10 and rms[i] > max(0.003, peak * 0.1):
            add("intensity_change", i, {"db_change_0_5_sec": windows[i]["dbfs"] - windows[i-25]["dbfs"]})
    quiet = None
    limit = max(10 ** (-45/20), peak * 0.04)
    for i in range(len(windows)+1):
        is_quiet = i < len(windows) and rms[i] < limit
        if is_quiet and quiet is None:
            quiet = i
        if not is_quiet and quiet is not None:
            start, end = windows[quiet]["start_sec"], windows[i-1]["end_sec"]
            if end - start >= 0.20:
                events.append(event("audio-%04d" % (len(events)+1), "quiet_region", start, end,
                                    metrics={"rms_threshold": limit}))
            quiet = None
    return events, novelty


def rhythm_estimates(windows, events, novelty, context):
    np, _, _, signal = libraries()
    intervals = []
    for region in sorted(context["regions"], key=lambda r: r["start_sec"]):
        if region["music_analysis_suitable"]:
            if intervals and region["start_sec"] <= intervals[-1][1]:
                intervals[-1][1] = max(intervals[-1][1], region["end_sec"])
            else:
                intervals.append([region["start_sec"], region["end_sec"]])
    estimates = []
    for start, end in intervals:
        indices = [i for i, w in enumerate(windows) if start <= w["start_sec"] < end]
        onsets = [e for e in events if e["kind"] == "onset_candidate" and start <= e["time_sec"] < end]
        item = {"start_sec": start, "end_sec": end, "status": "uncertain", "tempo_bpm": None,
                "period_sec": None, "autocorrelation": None, "onset_consistency": None,
                "candidate_beats": [], "confidence": "low", "musical_fact_verified": False,
                "attribution_basis": "canonical_unverified", "reason": "insufficient_repeating_signal",
                "harmonic_ambiguity_bpm": []}
        # A periodic envelope is evidence of repetition, not independent proof of music.
        if len(indices) >= 300 and len(onsets) >= 8:
            values = np.asarray([novelty[i] for i in indices], dtype=np.float64)
            autocorrelation = signal.correlate(values, values, mode="full", method="fft")[len(values)-1:]
            correlations = []
            for lag in range(13, 51):  # 0.26--1 sec; approximately 60--231 BPM
                a, b = values[:-lag], values[lag:]
                denominator = float(np.sqrt(np.dot(a, a)*np.dot(b, b)))
                score = max(0.0, min(1.0, float(autocorrelation[lag])/denominator)) if denominator else 0
                correlations.append((score, lag))
            best = max(score for score, lag in correlations)
            lag = min(lag for score, lag in correlations if score >= best - 0.025)
            period = lag * 0.02
            anchor = onsets[0]["time_sec"]
            aligned = [e for e in onsets if abs((e["time_sec"]-anchor)/period - round((e["time_sec"]-anchor)/period)) <= 0.12]
            consistency = len(aligned)/len(onsets)
            # Verify recurrence in both halves, and at least six distinct cycles.
            cycles = {round((e["time_sec"]-anchor)/period) for e in aligned}
            midpoint = (start+end)/2
            halves = all(sum(a <= e["time_sec"] < b for e in aligned) >= 3 for a, b in ((start, midpoint), (midpoint, end)))
            item.update(autocorrelation=best, onset_consistency=consistency)
            if best >= 0.60 and consistency >= 0.75 and len(cycles) >= 6 and halves:
                item.update(status="estimated", tempo_bpm=60/period, period_sec=period, confidence="medium",
                            reason="repeating_energy_onsets_with_unverified_music_context",
                            candidate_beats=[{"time_sec": e["time_sec"], "uncertainty_sec": 0.02,
                                              "onset_event_id": e["event_id"]} for e in aligned],
                            harmonic_ambiguity_bpm=[60/(alternative*0.02) for score, alternative in correlations
                                                    if alternative != lag and alternative in (lag*2, lag/2) and score >= 0.60])
        estimates.append(item)
    status = ("estimated" if any(r["status"] == "estimated" for r in estimates) else
              "uncertain" if estimates or context["music_presence"] in ("present", "uncertain") or
              context["music_classification_conflicts"] or context["speech"]["overall_requirement"] == "needs_review" else "unavailable")
    return {"status": status, "reason": "regional_signal_and_unverified_canonical_context" if estimates else
            "no_suitable_known_music_only_regions", "estimates": estimates,
            "grid_interpolation_performed": False, "musical_facts_verified": False}


def json_probe(command):
    try:
        return json.loads(base.small_output(command, max_bytes=PARAMETERS["max_json_bytes"], timeout=60),
                          object_pairs_hook=base.unique_object, parse_constant=base.reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise base.AdapterError("Invalid timing probe JSON") from None


def media_clock(video):
    info = json_probe(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_entries",
                       "format=start_time", "-of", "json", str(video)])
    try:
        start = float(info["format"].get("start_time", 0))
        if not math.isfinite(start):
            raise ValueError()
        return start
    except (KeyError, ValueError, TypeError):
        raise base.AdapterError("Invalid media presentation origin") from None


def frame_times(video, selector, origin, duration, *, sample_rate=None):
    entries = "frame=best_effort_timestamp_time,nb_samples" if sample_rate else "frame=best_effort_timestamp_time"
    data = json_probe(["ffprobe", "-v", "error", "-threads", "1", "-protocol_whitelist", "file",
                       "-select_streams", selector, "-show_frames", "-show_entries", entries,
                       "-of", "json", str(video)])
    try:
        frames = data["frames"]
        if not isinstance(frames, list) or not 0 < len(frames) <= PARAMETERS["max_decoded_frames"]:
            raise ValueError()
        times = [float(f["best_effort_timestamp_time"])-origin for f in frames]
        if any(not math.isfinite(t) or t < 0 or t > duration + (0.10 if sample_rate else 0) for t in times):
            raise ValueError()
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError()
        if sample_rate:
            counts = [f["nb_samples"] for f in frames]
            if any(type(n) is not int or not 0 < n <= 65536 for n in counts):
                raise ValueError()
            if any(abs(times[i+1] - times[i] - counts[i]/sample_rate) > 3/sample_rate + 0.000002 for i in range(len(times)-1)):
                raise base.AdapterError("Discontinuous audio PTS: normalized PCM cannot safely represent timeline")
            return {"start_sec": times[0], "end_sec": times[-1]+counts[-1]/sample_rate,
                    "decoded_duration_sec": sum(counts)/sample_rate, "frame_count": len(frames)}
        return times
    except base.AdapterError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError):
        raise base.AdapterError("Invalid or unsupported decoded-frame presentation timestamps") from None


def pixels_feature(frame, previous):
    np, _, _, _ = libraries()
    rgb = np.frombuffer(frame, dtype=np.uint8).reshape(-1, 3)
    pixels = rgb.astype(np.float64) @ np.asarray([77,150,29], dtype=np.float64)/256
    brightness = float(pixels.mean())/255
    histogram = np.concatenate([np.bincount(rgb[:,i]//64, minlength=4)/len(pixels) for i in range(3)])
    if previous is None:
        return pixels, histogram, {"brightness": brightness, "centered_difference": 0.0,
                                   "raw_difference": 0.0, "histogram_difference": 0.0}
    old_pixels, old_histogram, old_brightness = previous
    delta = (brightness - old_brightness)*255
    return pixels, histogram, {"brightness": brightness,
                              "centered_difference": float(np.abs(pixels-old_pixels-delta).mean())/255,
                              "raw_difference": float(np.abs(pixels-old_pixels).mean())/255,
                              "histogram_difference": float(np.abs(histogram-old_histogram).sum())/6}


def visual_features(video, times, duration):
    stride = max(1, math.ceil(len(times)/(duration*PARAMETERS["visual_target_fps"])))
    selected = list(range(0, len(times), stride))
    if len(selected) > PARAMETERS["max_sampled_frames"]:
        raise base.AdapterError("Visual sampling resource limit")
    frame_size = PARAMETERS["visual_width"]*PARAMETERS["visual_height"]*3
    buffer = bytearray()
    previous = None
    features = []
    digest = hashlib.sha256()
    def consume(chunk):
        nonlocal previous
        digest.update(chunk)
        buffer.extend(chunk)
        while len(buffer) >= frame_size:
            if len(features) >= len(selected):
                raise base.AdapterError("Decoded visual sample count mismatch")
            frame = bytes(buffer[:frame_size])
            del buffer[:frame_size]
            pixels, histogram, metrics = pixels_feature(frame, previous)
            index = selected[len(features)]
            features.append({"frame_index": index, "pts_sec": times[index], **metrics})
            previous = (pixels, histogram, metrics["brightness"])
    base.bounded_run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-max_alloc", "67108864",
        "-threads", "1", "-protocol_whitelist", "file", "-i", str(video), "-map", "0:v:0", "-an",
        "-vf", f"select=not(mod(n\\,{stride})),scale=64:64:flags=area", "-vsync", "0",
        "-filter_threads", "1", "-threads", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ], consume, max_bytes=PARAMETERS["max_visual_bytes"], timeout=60)
    if buffer or len(features) != len(selected):
        raise base.AdapterError("Decoded visual samples/PTS mismatch")
    return features, {"stride_frames": stride, "decoded_frame_count": len(times),
                      "sample_count": len(features), "sample_rgb_sha256": digest.hexdigest(),
                      "observed_max_gap_sec": max((b["pts_sec"]-a["pts_sec"] for a, b in zip(features, features[1:])), default=0),
                      "presentation_origin_sec": None}


def visual_events(features, duration):
    events = []
    last_motion = -1
    def add(kind, a, b, metrics=None, confidence="medium", time=None):
        start, end = features[a]["pts_sec"], features[b]["pts_sec"]
        events.append(event("visual-%04d" % (len(events)+1), kind, start, end, time=end if time is None else time,
                            uncertainty=end-start if b == a+1 else max(0.0, end-start),
                            confidence=confidence, metrics=metrics))
    for i in range(1, len(features)):
        f, old = features[i], features[i-1]
        delta = f["brightness"] - old["brightness"]
        flash = (i+1 < len(features) and delta > 0.18 and
                 f["brightness"]-features[i+1]["brightness"] > 0.18)
        returning_flash = (i >= 2 and old["brightness"]-features[i-2]["brightness"] > 0.18 and -delta > 0.18)
        if flash:
            add("flash_candidate", i-1, i+1, {"brightness_excursion": delta}, "low", time=f["pts_sec"])
        elif not returning_flash:
            if abs(delta) > 0.12:
                add("brightness_change", i-1, i, {"brightness_delta": delta})
            if f["centered_difference"] >= 0.12 and f["histogram_difference"] >= 0.20:
                add("hard_cut_candidate", i-1, i, {"centered_difference": f["centered_difference"],
                                                   "histogram_difference": f["histogram_difference"]}, "low")
            elif f["centered_difference"] >= 0.12:
                add("visual_change_candidate", i-1, i, {"centered_difference": f["centered_difference"]}, "low")
            if f["centered_difference"] >= 0.045 and f["pts_sec"]-last_motion >= 0.5:
                add("high_motion_candidate", i-1, i, {"centered_difference": f["centered_difference"]}, "low")
                last_motion = f["pts_sec"]
            if abs(f["centered_difference"]-old["centered_difference"]) >= 0.08:
                add("motion_change", i-1, i, {"difference_delta": f["centered_difference"]-old["centered_difference"]}, "low")
    # Runs of stable structure and monotonic brightness; no camera-type inference.
    stable = None
    fade = None
    direction = 0
    for i in range(1, len(features)+1):
        good = i < len(features) and features[i]["centered_difference"] < 0.018
        if good and stable is None:
            stable = i-1
        if not good and stable is not None:
            if features[i-1]["pts_sec"]-features[stable]["pts_sec"] >= 0.5:
                add("stable_region", stable, i-1)
            stable = None
        delta = features[i]["brightness"]-features[i-1]["brightness"] if i < len(features) else 0
        sign = 1 if delta > 0.006 else -1 if delta < -0.006 else 0
        monotonic = sign and i < len(features) and features[i]["centered_difference"] < 0.07
        if fade is not None and (not monotonic or sign != direction):
            if i-1-fade >= 3 and abs(features[i-1]["brightness"]-features[fade]["brightness"]) >= 0.15:
                add("fade_candidate", fade, i-1, {"brightness_delta": features[i-1]["brightness"]-features[fade]["brightness"]}, "low")
            fade = None
        if monotonic and fade is None:
            fade, direction = i-1, sign
    return events


def semantic_associations(events, canonical):
    associations = []
    for e in events:
        refs = [{"collection": "segments", "index": i} for i, s in enumerate(canonical["segments"])
                if max(s["start_sec"], e["start_sec"]) <= min(s["end_sec"], e["end_sec"])]
        refs += [{"collection": "events", "index": i} for i, s in enumerate(canonical["events"])
                 if s["modality"] in ("visual", "audiovisual") and
                 max(s["start_sec"], e["start_sec"]) <= min(s["end_sec"], e["end_sec"])]
        if refs:
            associations.append({"event_id": e["event_id"], "canonical_references": refs,
                                 "basis": "approximate_model_context", "independently_verified": False})
    return associations


def correlate(audio_events_, visual_events_, duration, audio_status):
    matches = []
    if audio_status == "unavailable":
        return matches
    candidates = [e for e in audio_events_ if e["kind"] in ("onset_candidate", "abrupt_audio_change", "intensity_change")]
    for v in visual_events_:
        if v["kind"] in ("stable_region", "fade_candidate") or not candidates:
            continue
        a = min(candidates, key=lambda e: abs(e["time_sec"]-v["time_sec"]))
        offset = v["time_sec"]-a["time_sec"]
        tolerance = PARAMETERS["correlation_tolerance_sec"]
        uncertainty = a["uncertainty_sec"]+v["uncertainty_sec"]
        if abs(offset) <= tolerance:
            match = event("av-%04d" % (len(matches)+1), "temporal_proximity_candidate",
                          min(a["start_sec"], v["start_sec"]), max(a["end_sec"], v["end_sec"]),
                          time=v["time_sec"], uncertainty=uncertainty, confidence="low",
                          metrics={"offset_sec": offset, "tolerance_sec": tolerance})
            match.update(audio_event_id=a["event_id"], visual_event_id=v["event_id"],
                         intentional_sync_verified=False, relation_status="uncertain")
            matches.append(match)
    return matches


def make_artifact(kind, source, provenance, tools, timing, events, payload):
    return {"contract_version": VERSION, "artifact_kind": kind, "source": source,
            "method": {"name": "mandala-adaptive-av", "version": VERSION, "parameters": PARAMETERS,
                       "tools": tools}, "provenance": provenance, "timestamp_precision": timing,
            "events": events, "data": payload, "validation_status": "structurally_checked",
            "limitations": LIMITATIONS}


def analyze(video, metadata, analysis):
    for value, label in ((video, "Source MP4"), (metadata, "Metadata"), (analysis, "Canonical")):
        checked_path(value, label)
    paths, source, digest, canonical, warnings = shared.verified_inputs(video, metadata, analysis)
    if source["duration_sec"] > PARAMETERS["max_duration_sec"] or source["fps"] > 120:
        raise base.AdapterError("Source exceeds duration/FPS resource envelope")
    binding = {**source, "path": shared.relative(paths["video"]), "sha256": digest}
    provenance = {"metadata": reference(paths["metadata"]), "canonical": reference(paths["analysis"]),
                  "code": code_receipts(), "canonical_findings_status": "unverified",
                  "canonical_limitations": canonical["analysis_meta"]["limitations"]}
    tools = {"ffmpeg": base.small_output(["ffmpeg", "-version"]).splitlines()[0],
             "ffprobe": base.small_output(["ffprobe", "-version"]).splitlines()[0],
             "numpy": libraries()[0].__version__, "scipy": libraries()[1].__version__,
             "python": sys.version.split()[0]}
    context = region_context(canonical)
    origin = media_clock(paths["video"])
    streams = gate.audio_streams(paths["video"])
    stream = next(iter(streams), None)
    windows, ae, novelty, pcm, clock = [], [], [], None, None
    if stream:
        clock = frame_times(paths["video"], str(stream["index"]), origin, source["duration_sec"], sample_rate=int(stream["sample_rate"]))
        with tempfile.TemporaryDirectory(prefix="mandala-av-pcm-") as temporary:
            path = Path(temporary)/"audio.pcm"
            pcm = shared.capture_pcm(paths["video"], stream, path,
                                     {"max_pcm_bytes": PARAMETERS["max_pcm_bytes"], "decode_timeout_sec": 60})
            if abs(pcm["duration_sec"] - clock["decoded_duration_sec"]) > 0.05:
                raise base.AdapterError("PCM duration differs from decoded audio PTS coverage")
            windows = energy_windows(path, clock["start_sec"], source["duration_sec"])
        ae, novelty = audio_events(windows)
    audio_status = "available" if stream else "unavailable"
    rhythm = rhythm_estimates(windows, ae, novelty, context)
    if not stream:
        rhythm.update(status="unavailable", reason="source_audio_stream_unavailable", estimates=[])
    audio = make_artifact("music_rhythm", binding, provenance, tools,
                          {"label": "signal_estimated", "basis": "decoded_audio_PTS_plus_sample_count",
                           "resolution_sec": 0.02, "frame_verified": False}, ae,
                          {"audio_status": audio_status, "stream": stream, "pcm": pcm, "pcm_parameters": gate.PCM_PARAMETERS,
                           "audio_clock": clock, "presentation_origin_sec": origin, "context": context,
                           "energy_windows": windows, "rhythm": rhythm})
    times = frame_times(paths["video"], "v:0", origin, source["duration_sec"])
    features, sampling = visual_features(paths["video"], times, source["duration_sec"])
    sampling["presentation_origin_sec"] = origin
    ve = visual_events(features, source["duration_sec"])
    visual = make_artifact("visual_timing", binding, provenance, tools,
                           {"label": "signal_estimated", "basis": "decoded_frame_PTS_sampled_candidates",
                            "resolution_sec": sampling["observed_max_gap_sec"], "frame_verified": False}, ve,
                           {"sampling": sampling, "frame_measurements": features,
                            "semantic_associations": semantic_associations(ve, canonical)})
    ce = correlate(ae, ve, source["duration_sec"], audio_status)
    correlation = make_artifact("audiovisual_correlation", binding, provenance, tools,
                                {"label": "signal_estimated", "basis": "temporal_proximity_of_estimated_events",
                                 "resolution_sec": 0.02+sampling["observed_max_gap_sec"], "frame_verified": False}, ce,
                                {"audio_status": audio_status, "intentional_sync_verified": False,
                                 "audio_evidence_file": AUDIO, "visual_evidence_file": VISUAL,
                                 "semantic_associations": semantic_associations([e for e in ve if e["kind"] == "stable_region"], canonical)})
    artifacts = {AUDIO: audio, VISUAL: visual, CORRELATION: correlation}
    validate_artifacts(artifacts)
    # Detect mutations between initial verification and publication.
    for key, receipt in (("video", {"sha256": digest}), ("metadata", provenance["metadata"]), ("analysis", provenance["canonical"])):
        if gate.sha256_file(paths[key]) != receipt["sha256"]:
            raise base.AdapterError("Input changed during analysis")
    return artifacts, warnings


def validate_artifacts(artifacts):
    pending = [artifacts]
    count = 0
    while pending:
        value = pending.pop()
        count += 1
        if count > 250000:
            raise base.AdapterError("Evidence object resource limit")
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif type(value) in (int, float) and not shared.finite(value):
            raise base.AdapterError("Nonfinite evidence number")
    schema = base.load_schema("adaptive-av-evidence.v0.1.schema.json")
    source = artifacts[AUDIO]["source"]
    duration = source["duration_sec"]
    for name, data in artifacts.items():
        base.validate_object(data, schema, "AV evidence")
        if data["source"] != source or data["method"]["parameters"] != PARAMETERS:
            raise base.AdapterError("Cross-source evidence or analysis parameter mismatch")
        if data["provenance"] != artifacts[AUDIO]["provenance"]:
            raise base.AdapterError("Cross-artifact provenance mismatch")
        seen = set()
        for e in data["events"]:
            if not 0 <= e["start_sec"] <= e["time_sec"] <= e["end_sec"] <= duration or e["event_id"] in seen:
                raise base.AdapterError("Invalid evidence event timestamp or duplicate ID")
            seen.add(e["event_id"])
    audio, visual, correlation = (artifacts[n] for n in (AUDIO, VISUAL, CORRELATION))
    for e in audio["events"]:
        if e["kind"] not in AUDIO_KINDS:
            raise base.AdapterError("Invalid audio event kind")
    for e in visual["events"]:
        if e["kind"] not in VISUAL_KINDS:
            raise base.AdapterError("Invalid visual event kind")
    previous = -1
    for w in audio["data"]["energy_windows"]:
        if not previous <= w["start_sec"] < w["end_sec"] <= duration:
            raise base.AdapterError("Invalid audio window timestamps")
        previous = w["end_sec"] - 1e-9
    previous = -1
    for f in visual["data"]["frame_measurements"]:
        if not previous < f["pts_sec"] <= duration:
            raise base.AdapterError("Invalid sampled-frame timestamp")
        previous = f["pts_sec"]
    if audio_events(audio["data"]["energy_windows"])[0] != audio["events"]:
        raise base.AdapterError("Audio event derivation mismatch")
    ae, novelty = audio_events(audio["data"]["energy_windows"])
    expected_rhythm = rhythm_estimates(audio["data"]["energy_windows"], ae, novelty, audio["data"]["context"])
    if audio["data"]["audio_status"] == "unavailable":
        expected_rhythm.update(status="unavailable", reason="source_audio_stream_unavailable", estimates=[])
    if expected_rhythm != audio["data"]["rhythm"]:
        raise base.AdapterError("Rhythm estimate derivation mismatch")
    if visual_events(visual["data"]["frame_measurements"], duration) != visual["events"]:
        raise base.AdapterError("Visual event derivation mismatch")
    if correlate(audio["events"], visual["events"], duration, audio["data"]["audio_status"]) != correlation["events"]:
        raise base.AdapterError("Audiovisual correlation derivation mismatch")


def attach(original_path, artifacts, artifact_paths):
    original_path = checked_path(original_path, "Director Input")
    original = read(original_path)
    schema = base.load_schema("adaptive-director-input.v0.3.schema.json")
    base.validate_object(original, schema, "Original Director Input")
    source = {k: artifacts[AUDIO]["source"][k] for k in schema["properties"]["source"]["properties"]}
    if original["source"] != source:
        raise base.AdapterError("Director Input source mismatch")
    canonical_path = checked_path(original["evidence"]["universal_analysis"]["path"], "Director canonical reference")
    if reference(canonical_path) != artifacts[AUDIO]["provenance"]["canonical"]:
        raise base.AdapterError("Director canonical reference mismatch")
    if original["evidence"]["universal_analysis"]["timing_precision"] != "approximate":
        raise base.AdapterError("Unverified canonical timing must remain approximate")
    if original["renderer_capabilities"] != {"verification_status": "unknown", "supported_operations": []}:
        raise base.AdapterError("Stage 5C requires unknown renderer capabilities")
    for slot in ("transcript", "speech_alignment", "music_rhythm", "visual_timing"):
        ref = original["evidence"].get(slot)
        if ref is not None:
            checked_path(ref["path"], "Existing evidence reference")
    validate_artifacts(artifacts)
    enriched = copy.deepcopy(original)
    # Preserve preexisting optional slots; replacement requires a separate reviewed contract.
    for slot, name, eligible in (("music_rhythm", AUDIO, artifacts[AUDIO]["data"]["rhythm"]["status"] == "estimated"),
                                 ("visual_timing", VISUAL, True)):
        if original["evidence"].get(slot) is not None:
            raise base.AdapterError("Existing AV evidence slot cannot be overwritten")
        if eligible:
            checked_path(artifact_paths[name], "New evidence reference", output=not Path(artifact_paths[name]).exists())
            enriched["evidence"][slot] = {"path": shared.relative(Path(artifact_paths[name])), "timing_precision": "signal_estimated"}
    base.validate_object(enriched, schema, "Enriched Director Input")
    return enriched


def validation_report(artifacts, paths, warnings, *, director=None, original=None):
    return {"contract_version": VERSION, "validation_status": "passed", "source": artifacts[AUDIO]["source"],
            "checks": {"source_sha256": True, "ffprobe_metadata": True, "canonical_schema_and_timing": True,
                       "artifact_schema_and_derivation": True, "source_timeline": True},
            "artifacts": {name: reference(paths[name]) for name in artifacts},
            "eligibility": {"music_rhythm": artifacts[AUDIO]["data"]["rhythm"]["status"] == "estimated",
                            "visual_timing": True, "audiovisual_correlation": True,
                            "scope": "source_bound_structurally_checked_uncertain_evidence",
                            "independent_fact_verification": False},
            "director_input": reference(director) if director else None,
            "original_director_input": reference(original) if original else None,
            "warnings": warnings, "limitations": LIMITATIONS,
            "render_approved": False, "publish_approved": False}


def generate(video, metadata, analysis, output_dir, *, director_input=None):
    output = shared.directory(output_dir, new=True)
    artifacts, warnings = analyze(video, metadata, analysis)
    paths = {name: output/name for name in artifacts}
    enriched = attach(director_input, artifacts, paths) if director_input else None
    output.parent.mkdir(parents=True, exist_ok=True)
    shared.directory(output, new=True)
    output.mkdir()  # exclusive directory ownership; no prior files are overwritten
    created = []
    try:
        for name, data in artifacts.items():
            shared.write_json(paths[name], data)
            created.append(paths[name])
        if enriched:
            shared.write_json(output/ENRICHED, enriched)
            created.append(output/ENRICHED)
        report = validation_report(artifacts, paths, warnings, director=output/ENRICHED if enriched else None,
                                   original=checked_path(director_input, "Director Input") if enriched else None)
        base.validate_object(report, base.load_schema("adaptive-av-validation.v0.1.schema.json"), "AV validation report")
        shared.write_json(output/REPORT, report)
        created.append(output/REPORT)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        if not any(output.iterdir()):
            output.rmdir()
        raise
    return report


def validate_bundle(bundle):
    bundle = shared.directory(bundle)
    paths = {name: checked_path(bundle/name, "AV artifact") for name in (AUDIO, VISUAL, CORRELATION)}
    artifacts = {name: read(path) for name, path in paths.items()}
    validate_artifacts(artifacts)
    source = artifacts[AUDIO]["source"]
    provenance = artifacts[AUDIO]["provenance"]
    for receipt in [provenance["metadata"], provenance["canonical"], *provenance["code"]]:
        if reference(checked_path(receipt["path"], "Provenance reference")) != receipt:
            raise base.AdapterError("Provenance file hash mismatch")
    # Replay technical observations from the verified original, not just declared hashes.
    expected, warnings = analyze(source["path"], provenance["metadata"]["path"], provenance["canonical"]["path"])
    if expected != artifacts:
        raise base.AdapterError("Evidence differs from deterministic source replay")
    report = read(checked_path(bundle/REPORT, "Validation report"))
    base.validate_object(report, base.load_schema("adaptive-av-validation.v0.1.schema.json"), "AV validation report")
    director = original = None
    if report["director_input"]:
        director = checked_path(report["director_input"]["path"], "Enriched Director Input")
        original = checked_path(report["original_director_input"]["path"], "Original Director Input")
        if director != bundle/ENRICHED or read(director) != attach(original, artifacts, paths):
            raise base.AdapterError("Enriched Director Input preservation mismatch")
    if report != validation_report(artifacts, paths, warnings, director=director, original=original):
        raise base.AdapterError("Validation report binding mismatch")
    return report


def enrich(bundle, director_input, output):
    validate_bundle(bundle)
    bundle = shared.directory(bundle)
    artifacts = {n: read(bundle/n) for n in (AUDIO, VISUAL, CORRELATION)}
    output = checked_path(output, "Enriched output", output=True)
    payload = attach(director_input, artifacts, {n: bundle/n for n in artifacts})
    shared.write_json(output, payload)
    return {"status": "passed", "output": shared.relative(output), "render_approved": False, "publish_approved": False}


def worker_main(argv):
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    def stop(_signal, _frame):
        raise base.AdapterError("Pipeline processing timeout or termination")
    signal.signal(signal.SIGTERM, stop)
    resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("generate", allow_abbrev=False)
    for name in ("video", "metadata", "analysis", "output-dir"):
        run.add_argument("--"+name, type=Path, required=True)
    run.add_argument("--director-input", type=Path)
    validate = commands.add_parser("validate", allow_abbrev=False)
    validate.add_argument("--bundle", type=Path, required=True)
    en = commands.add_parser("enrich", allow_abbrev=False)
    for name in ("bundle", "director-input", "output"):
        en.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            result = generate(args.video, args.metadata, args.analysis, args.output_dir, director_input=args.director_input)
        elif args.command == "validate":
            result = validate_bundle(args.bundle)
        else:
            result = enrich(args.bundle, args.director_input, args.output)
        print(json.dumps(result, allow_nan=False))
        return 0
    except (base.AdapterError, OSError, ValueError, KeyError, TypeError, MemoryError, RecursionError) as error:
        message = str(error) if isinstance(error, base.AdapterError) else "Resource, filesystem or malformed evidence failure"
        print(json.dumps({"status": "BLOCKED", "error": message}))
        return 1


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--bounded-worker":
        return worker_main(args[1:])
    chunks = bytearray()
    try:
        watchdog = shutil.which("timeout")
        if watchdog is None:
            raise base.AdapterError("GNU timeout unavailable; bounded process-group execution required")
        # GNU timeout signals the worker's entire process group. The worker's TERM
        # handler unwinds existing bounded_run finally blocks and reaps FFmpeg.
        runtime = base.ROOT/".venv-av/bin/python"
        executable = str(runtime) if runtime.is_file() else sys.executable
        base.bounded_run([watchdog, "--signal=TERM", "--kill-after=2s",
                          str(PARAMETERS["pipeline_timeout_sec"])+"s", executable, "-B",
                          str(Path(__file__).resolve()), "--bounded-worker", *args],
                         chunks.extend, max_bytes=PARAMETERS["max_json_bytes"], timeout=PARAMETERS["pipeline_timeout_sec"]+5)
    except base.AdapterError as error:
        print(chunks.decode("utf-8") if chunks else json.dumps({"status": "BLOCKED", "error": str(error)}), file=sys.stderr)
        return 1
    print(chunks.decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
