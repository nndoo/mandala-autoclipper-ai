"""Provenance-aware Director intake. No network, ASR, rendering or credentials."""

import copy
import contextlib
import signal
import json
from pathlib import Path

import analyze_adaptive_av_evidence_v01 as av

base, shared, gate = av.base, av.shared, av.gate
PACKET_VERSION = "0.3.0"
MAX_PACKET_BYTES = 49152
MAX_SELECTED_EVENTS = 12


def bounded_json(data, maximum=MAX_PACKET_BYTES):
    text = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(text.encode()) > maximum:
        raise base.AdapterError("Director input/output resource limit exceeded")
    return text


def selected_events(events):
    """Bound context by measured prominence; retain complete canonical timeline."""
    def prominence(event):
        priority = {"hard_cut_candidate": 3, "flash_candidate": 3, "fade_candidate": 2,
                    "brightness_change": 2, "stable_region": 1}.get(event["kind"], 0)
        values = [abs(n) for n in event["measurements"].values() if shared.finite(n)]
        return priority, max(values, default=0)
    indices = sorted(sorted(range(len(events)), key=lambda i: prominence(events[i]), reverse=True)[:MAX_SELECTED_EVENTS])
    return [(i, events[i]) for i in indices]


def validate_speech_bundle(bundle):
    manifest = av.read(av.checked_path(bundle/shared.MANIFEST, "Speech manifest"))
    if manifest.get("record_version") == "remote-asr-0.1.0":
        from generate_remote_speech_evidence_v01 import validate_bundle
    else:
        validate_bundle = shared.validate_bundle
    validate_bundle(bundle)  # Offline validator never invokes ASR or credentials.
    return manifest, av.read(av.checked_path(bundle/shared.REPORT, "Speech report"))


def build_packet(video, metadata, analysis, director_input, av_bundle, *, speech_bundle=None, speech_intelligence=None):
    requested = {"video": video, "metadata": metadata, "analysis": analysis, "director_input": director_input}
    requested = {k: av.checked_path(v, k) for k, v in requested.items()}
    paths, source, digest, canonical, warnings = shared.verified_inputs(requested["video"], requested["metadata"], requested["analysis"])
    if not canonical["segments"]:
        raise base.AdapterError("Canonical regional timeline unavailable for planning")
    director = av.read(requested["director_input"])
    schema = base.load_schema("adaptive-director-input.v0.3.schema.json")
    base.validate_object(director, schema, "Director Input V0.3")
    if director["source"] != source:
        raise base.AdapterError("Director source mismatch")
    canonical_ref = director["evidence"]["universal_analysis"]
    if av.checked_path(canonical_ref["path"], "Canonical reference") != paths["analysis"] or canonical_ref["timing_precision"] != "approximate":
        raise base.AdapterError("Director canonical reference or precision mismatch")
    if director["renderer_capabilities"] != {"verification_status": "unknown", "supported_operations": []}:
        raise base.AdapterError("No verified renderer capability receipt exists in Stage 5.4")
    bundle = shared.directory(av_bundle)
    av_report = av.validate_bundle(bundle)
    binding = {**source, "path": shared.relative(paths["video"]), "sha256": digest}
    if av_report["source"] != binding:
        raise base.AdapterError("AV bundle source mismatch")
    artifacts = {n: av.read(bundle/n) for n in (av.AUDIO, av.VISUAL, av.CORRELATION)}
    for slot, name in (("music_rhythm", av.AUDIO), ("visual_timing", av.VISUAL)):
        ref = director["evidence"].get(slot)
        if ref:
            if av.checked_path(ref["path"], "AV reference") != bundle/name or ref["timing_precision"] != "signal_estimated":
                raise base.AdapterError("Director AV artifact reference/precision mismatch")
            if not av_report["eligibility"][slot]:
                raise base.AdapterError("Director attaches ineligible AV evidence")
    inputs = {k: av.reference(p) for k, p in requested.items()}
    inputs.update({name: av.reference(bundle/name) for name in (av.AUDIO, av.VISUAL, av.CORRELATION, av.REPORT)})
    requirement = gate.speech_requirements(canonical)
    eligibility = {"status": "unavailable", "transcript": False, "speech_alignment": False}
    text_status, timing_status = "unavailable", "unavailable"
    if speech_bundle:
        speech_bundle = shared.directory(speech_bundle)
        manifest, speech_report = validate_speech_bundle(speech_bundle)
        if manifest["source"] != source or speech_report.get("source_integrity_status") != "verified":
            raise base.AdapterError("Speech evidence source mismatch")
        stage5a = av.read(av.checked_path(speech_bundle/shared.GATE, "Stage 5A gate"))
        if stage5a["source"]["sha256"] != digest or stage5a["source"]["metadata"] != source:
            raise base.AdapterError("Stage 5A source mismatch")
        if stage5a["canonical_analysis"] != {"path": shared.relative(paths["analysis"]), "sha256": gate.sha256_file(paths["analysis"]),
                                            "source_metadata_match": True, "findings_status": "unverified"}:
            raise base.AdapterError("Stage 5A canonical provenance mismatch")
        if manifest["speech_requirements"] != requirement or stage5a["speech_requirements"] != requirement:
            raise base.AdapterError("Speech regional requirements mismatch")
        eligibility = speech_report["evidence_eligibility"]
        # Current gate cannot certify these attachments. Never trust a forged true field.
        if eligibility.get("transcript") is not False or eligibility.get("speech_alignment") is not False:
            raise base.AdapterError("Unsupported transcript/alignment eligibility promotion")
        text_status = speech_report.get("text_verification_status", "unavailable")
        timing_status = speech_report.get("timing_verification_status", "unavailable")
        for name in (shared.MANIFEST, shared.REPORT, shared.GATE):
            inputs["speech:"+name] = av.reference(speech_bundle/name)
        if (speech_bundle/shared.DRAFT).is_file():
            inputs["speech:draft"] = av.reference(av.checked_path(speech_bundle/shared.DRAFT, "Quarantined speech draft"))
    for slot in ("transcript", "speech_alignment"):
        ref = director["evidence"].get(slot)
        if ref:
            av.checked_path(ref["path"], "Speech attachment")
            raise base.AdapterError("Director contains speech attachment without current eligibility")
    ledger = {}
    def add(uid, artifact, pointer, start, end, precision, basis, data):
        ledger[uid] = {"artifact": artifact, "pointer": pointer, "start_sec": start, "end_sec": end,
                       "timing_precision": precision, "basis": basis}
    add("source.metadata", "metadata", "/source", 0, source["duration_sec"], "not_applicable", "source_metadata_verified", source)
    for collection in ("segments", "events", "claims", "editing_opportunities"):
        for i, item in enumerate(canonical[collection]):
            add(f"canonical.{collection}.{i}", "analysis", f"/{collection}/{i}", item.get("start_sec"), item.get("end_sec"),
                "approximate", "model_unverified", item)
    audio_summaries, visual_summaries, correlation_summaries = [], [], []
    for name, prefix, summaries in ((av.AUDIO, "audio", audio_summaries), (av.VISUAL, "visual", visual_summaries),
                                     (av.CORRELATION, "correlation", correlation_summaries)):
        for i, item in selected_events(artifacts[name]["events"]):
            uid = f"{prefix}.events.{i}"
            add(uid, name, f"/events/{i}", item["start_sec"], item["end_sec"], "signal_estimated", "signal_candidate", item)
            summaries.append({"ref": uid, **item})
    missing = []
    if requirement["overall_requirement"] != "not_required":
        missing.extend(["eligible_transcript", "verified_speech_alignment", "speech_safe_cut_boundaries"])
    if artifacts[av.AUDIO]["data"]["rhythm"]["status"] != "estimated":
        missing.append("reliable_music_beat_grid")
    missing.append("verified_renderer_capabilities")
    request = {k: shared.relative(p) for k, p in requested.items()}
    request.update(av_bundle=shared.relative(bundle), speech_bundle=shared.relative(speech_bundle) if speech_bundle else None)
    packet = {"contract_version": PACKET_VERSION, "source": binding, "request": request, "inputs": inputs,
              "editorial_policy": copy.deepcopy(director["editorial_policy"]), "renderer_capabilities": director["renderer_capabilities"],
              "canonical": canonical, "speech": {"requirements": requirement, "eligibility": eligibility,
              "text_verification_status": text_status, "timing_verification_status": timing_status,
              "eligible_transcript": None, "eligible_alignment": None,
              "quarantine_policy": "Ineligible ASR draft text is not supplied as eligible editorial evidence; inspect original draft for human review"},
              "audio": {"audio_status": artifacts[av.AUDIO]["data"]["audio_status"],
              "rhythm": artifacts[av.AUDIO]["data"]["rhythm"], "selected_events": audio_summaries,
              "total_event_count": len(artifacts[av.AUDIO]["events"])},
              "visual": {"sampling": artifacts[av.VISUAL]["data"]["sampling"], "selected_events": visual_summaries,
              "total_event_count": len(artifacts[av.VISUAL]["events"])}, "correlation": correlation_summaries,
              "evidence_ledger": ledger, "missing_evidence": missing, "warnings": warnings,
              "limitations": av.LIMITATIONS, "render_approved": False, "publish_approved": False}
    if speech_intelligence:
        import speech_intelligence_v01 as intelligence
        from speech_planning_v01 import enrich_packet
        report = intelligence.load_report(speech_intelligence)
        if report['source'] != binding or report['classification'] != requirement:
            raise base.AdapterError('Generalized speech evidence source/requirements mismatch')
        if any(report['inputs'][key] != inputs[key] for key in ('video', 'metadata', 'analysis')):
            raise base.AdapterError('Generalized speech canonical/input provenance mismatch')
        packet = enrich_packet(packet, report, speech_intelligence)
        packet['request']['speech_intelligence'] = shared.relative(av.checked_path(speech_intelligence, 'Speech intelligence'))
    bounded_json(packet)
    return packet


def validate_packet(packet):
    if not isinstance(packet, dict) or packet.get("contract_version") != PACKET_VERSION or not isinstance(packet.get("request"), dict):
        raise base.AdapterError("Invalid Director evidence packet")
    expected = build_packet(**packet["request"])
    if packet != expected:
        raise base.AdapterError("Director evidence packet differs from source-bound replay")
    return packet


@contextlib.contextmanager
def processing_deadline(seconds=480):
    """Linux CLI wall-clock limit; existing subprocess finally blocks still reap."""
    previous = signal.getsignal(signal.SIGALRM)
    def expired(_signum, _frame):
        raise base.AdapterError("Planning wall-clock budget exceeded")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
