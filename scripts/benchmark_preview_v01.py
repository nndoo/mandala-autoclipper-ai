"""Narrow Stage 5.8 private admission; uses the existing FFmpeg compiler and QA."""
import copy
from pathlib import Path
import resource
import tempfile

import numpy as np
import benchmark_evidence_v01 as evidence
import render_video_v01 as renderer
import render_showcase_preview_v01 as showcase

core, qa = evidence.core, evidence.qa


def speech_safety(plan, packet, speech_report=None):
    import speech_intelligence_v01 as speech
    if speech_report is None and packet.get('speech_intelligence'):
        ref = packet['speech_intelligence']['report']; path = core.safe_path(ref['path'])
        if qa.ref(path) != ref or packet['inputs'].get('speech_intelligence') != ref:
            raise core.Error('Speech intelligence attachment changed')
        speech_report = speech.load_report(path)
    if speech_report is not None:
        # Render-facing consumers replay every artifact; caller-supplied true fields are insufficient.
        request = speech_report.get('request', {})
        if speech.assess(**request) != speech_report: raise core.Error('Speech assessment replay mismatch')
    result = speech.evaluate_plan(plan, packet, speech_report)
    reasons = ['missing_speech_evidence:'+f['code'] for f in result['findings'] if f['blocking']]
    # Preserve established diagnostic codes when no new contract is provided.
    if reasons and speech_report is None:
        if any(len(v['shots']) > 1 for v in plan['variants']): reasons.append('missing_speech_evidence:disconnected_speech_selection')
        else: reasons.append('missing_speech_evidence:unreviewed_trim_or_timing_change')
    return list(dict.fromkeys(reasons))


def validate_plan(plan, packet, registry, spec, speech_report=None):
    independent = core.director.validator.validate_plan(plan, packet)
    reasons = list(independent['blocking_findings'])
    if not independent['structural_validity']: reasons.append({'code':'invalid_plan_schema'})
    reasons += [{'code': r} for r in speech_safety(plan, packet, speech_report)] if independent['structural_validity'] else []
    timeline = None
    if not reasons:
        try:
            timeline = core.compile_timeline(plan, spec)
            if spec['assets']: raise core.Error('Benchmark real preview does not admit external assets')
            for name in timeline['required_capabilities']:
                if registry['operations'].get(name, {}).get('status') != 'verified':
                    reasons.append({'code':'unsupported_editing_operation', 'operation': name})
        except (core.Error, KeyError, TypeError, ValueError): reasons.append({'code':'execution_spec_invalid'})
    return {'contract_version':evidence.VERSION, 'independent_plan_validation':independent,
        'blocking_reasons':reasons, 'private_preview_eligible':not reasons,
        'speech_context_review':'SOURCE_WHOLE_UNALTERED_ONLY' if packet['speech']['requirements']['overall_requirement']!='not_required' else 'NOT_REQUIRED_BY_UNVERIFIED_CANONICAL',
        'plan_sha256':core.digest_object(plan), 'spec_sha256':core.digest_object(spec), **evidence.FLAGS}, timeline


def admit(permit, entry, plan, spec, validation, generation, destination):
    evidence.check('permit', permit)
    if (entry['source']['sha256']==__import__('run_benchmark_v01').SHOWCASE or
        entry.get('benchmark_eligibility')!='HISTORICAL_AND_LIVE_GATED'):
        raise core.Error('Historical/exhausted/unregistered source cannot enter a new benchmark render')
    for field in ('source', 'registry', 'plan', 'validation', 'generation', 'spec', 'capabilities'):
        qa.same_reference(permit[field])
    if not permit['permission_text'].strip(): raise core.Error('Private preview authorization missing')
    if permit['source'] != entry['source'] or core.shared.relative(destination) != permit['destination']:
        raise core.Error('Preview permission source/destination mismatch')
    if generation.get('mode') != 'live_model_inference' or generation.get('code_receipts') != core.director.code_receipts():
        raise core.Error('Only unchanged live Director plans can enter real benchmark rendering')
    registry = renderer.validate_registry(permit['capabilities']['path'])
    packet = core.intake.validate_packet(qa.read(core.safe_path(permit['generation']['path']).parent/core.director.PACKET))
    if packet['source'] != plan['source'] or {k:plan['source'][k] for k in ('path','sha256')} != entry['source']:
        raise core.Error('Preview cross-source contamination')
    if (generation.get('plan_sha256') != core.director.digest_text(core.intake.bounded_json(plan,core.director.MAX_RESPONSE_BYTES))
        or generation.get('evidence_packet_sha256') != core.director.validator.packet_digest(packet)):
        raise core.Error('Director generation plan/packet binding changed')
    actual, timeline = validate_plan(plan, packet, registry, spec)
    if actual != validation or not actual['private_preview_eligible']:
        raise core.Error('Independent plan safety does not authorize private preview')
    original = qa.read(permit['plan']['path'])
    if original != plan or core.digest_object(plan) != validation['plan_sha256']:
        raise core.Error('Blocked/saved plan cannot be relabeled for rendering')
    info = core.media_info(core.safe_path(entry['source']['path']), spec['resources'])
    if any(info[k] != plan['source'][k] for k in ('duration_sec','width','height','fps')):
        raise core.Error('Benchmark source metadata changed')
    return packet, timeline, info


def render(permit_ref, entry, destination):
    permit = evidence.check('permit', qa.read(permit_ref['path']));qa.same_reference(permit_ref)
    destination = core.new_directory(destination, evidence.RENDER_ROOT)
    plan = qa.read(permit['plan']['path']);spec = qa.read(permit['spec']['path'])
    validation = qa.read(permit['validation']['path']);generation = qa.read(permit['generation']['path'])
    packet, timeline, info = admit(permit, entry, plan, spec, validation, generation, destination)
    parent = core.safe_path(permit_ref['path']).parent
    consumed = parent/'preview-consumed.v01.json'
    core.shared.write_json(consumed, {'permission':permit_ref,'source':entry['source'], 'created_at':core.shared.now(), **evidence.FLAGS})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with renderer.render_lock(), tempfile.TemporaryDirectory(prefix='.benchmark-work-', dir=destination.parent) as tmp:
        work = Path(tmp);core.disk_preflight(work, spec['resources'])
        graph, audio, assets, _ = core.filter_graph(timeline, info['audio_present'], work, spec)
        if assets: raise core.Error('Unapproved asset reached benchmark encoder')
        script = work/'filters.ffgraph';script.write_text(graph)
        settings = timeline['output_settings'];output = work/'preview.mp4'
        # Encoder emission only; all operation/timeline/filter policies are shared.
        args = ['-protocol_whitelist','file,pipe','-i',str(core.safe_path(entry['source']['path'])),
            '-filter_complex_script',str(script),'-map','[vout]']
        if audio: args += ['-map','[aout]','-c:a','aac','-b:a',str(settings['audio_bitrate_kbps'])+'k','-ar','48000','-ac','2']
        else: args += ['-an']
        args += ['-c:v','libx264','-preset',settings['preset'],'-crf',str(settings['crf']),'-pix_fmt','yuv420p',
            '-r',str(settings['fps']),'-threads',str(spec['resources']['threads']),'-movflags','+faststart','-map_metadata','-1',
            '-metadata','title=PREVIEW_ONLY NOT_APPROVED_FOR_PUBLICATION',str(output)]
        _, elapsed = core.ffmpeg(args, work, spec['resources'])
        verification = core.verify_output(output, timeline, audio, spec['resources'])
        verification['black_frame_scan'] = showcase.black_scan(output, timeline, spec['resources'])
        final_ref = {'path':core.shared.relative(destination/'preview.mp4'),'sha256':core.intake.gate.sha256_file(output)}
        manifest = evidence.check('manifest', {'contract_version':evidence.VERSION,'mode':'STAGE58_PRIVATE_PREVIEW',
            'source':entry['source'],'output':final_ref, **{k:permit[k] for k in ('plan','validation','generation','spec','capabilities')},
            'packet':qa.ref(core.safe_path(permit['generation']['path']).parent/core.director.PACKET),
            'permit':permit_ref,'consumed_permit':qa.ref(consumed),'timeline':timeline,'verification':verification,
            'execution':{'elapsed_sec':elapsed,'limits':spec['resources'],'max_child_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss},
            'code_receipts':evidence.receipts(), **evidence.FLAGS})
        __import__('renderer_revision_v02').publish(destination, {'preview.mp4':output},
            {'benchmark-render-manifest.v01.json':manifest}, evidence.RENDER_ROOT)
    return manifest


def technical(manifest_ref):
    manifest = evidence.check('manifest', qa.read(manifest_ref['path']));qa.same_reference(manifest_ref)
    if manifest['code_receipts'] != evidence.receipts(): raise core.Error('Benchmark render code changed')
    for k in ('source','output','plan','validation','generation','spec','packet','permit','consumed_permit','capabilities'):qa.same_reference(manifest[k])
    registry = qa.read(manifest['permit']['path'])['registry'];reg = evidence.check('registry',qa.read(registry['path']))
    entry = next(e for e in reg['entries'] if e['source']==manifest['source'])
    spec = qa.read(manifest['spec']['path']);plan = qa.read(manifest['plan']['path'])
    packet, timeline, info = admit(qa.read(manifest['permit']['path']), entry, plan, spec,
        qa.read(manifest['validation']['path']),qa.read(manifest['generation']['path']),core.safe_path(manifest['output']['path']).parent)
    if timeline != manifest['timeline']: raise core.Error('Rendered timeline changed')
    output = core.safe_path(manifest['output']['path']);verified = core.verify_output(output, timeline, info['audio_present'], spec['resources'])
    if any(manifest['verification'].get(k)!=v for k,v in verified.items()):raise core.Error('Technical media replay mismatch')
    report = qa.empty_report();report.update(source=manifest['source'],rendered_output=manifest['output'],inputs={
        'source':manifest['source'],'rendered_output':manifest['output'],'manifest':manifest_ref,
        'plan':manifest['plan'],'spec':manifest['spec'],'timeline':manifest_ref,'director_packet':manifest['packet']})
    report['integrity']={'status':'PASS','source_output_sha_bound':True,'manifest_plan_spec_timeline_checked':True,
        'capability_receipts_checked':True,'source_metadata_checked':True,'production_approval_inherited':False}
    report['evidence_ledger']={k:v for k,v in report['inputs'].items()}
    report['evidence_ledger'].update({'media.source':manifest['source'],'media.output':manifest['output'],
        'video.samples':{'method':'sampled_pixels'},'audio.metrics':{'method':'normalized_PCM'},
        'captions':{'method':'declared_plan'},'canonical':{'basis':'model_unverified'},'speech.eligibility':{'basis':'existing_gate'}})
    samples, sampling = qa.frame_samples(output,timeline['expected_duration_sec'],verified['metadata']['fps'])
    video, findings = qa.visual_analysis(samples,timeline,sampling)
    if info['audio_present']:
        measured, more = qa.audio_analysis(core.audio_pcm(output,qa.LIMITS),timeline,
            source_pcm=np.asarray(core.audio_pcm(core.safe_path(entry['source']['path']),qa.LIMITS)),
            operations=timeline['operations'],audio_mode=spec['output']['audio_mode']);findings+=more
    else: measured={'status':'UNAVAILABLE','boundaries':[],'events':[]}
    captions, more = qa.caption_analysis(plan,timeline);findings+=more
    for i,f in enumerate(findings):f.update(issue_id=f'benchmark-{i:04d}',source_ranges=qa.source_ranges(f['output_range'],timeline))
    report['issues']=findings
    report['technical']={'duration_sec':timeline['expected_duration_sec'],'verification':verified,'video':video,'audio':measured,
        'captions':captions,'timeline':timeline,'speech':packet['speech'],'parameters':qa.PARAMETERS,
        'factual_claims_verified':False,'geometry_policy_checked':True}
    report['dimensions']['technical_integrity']=qa.dimension('PASS','deterministic_validation','Actual bytes fully decoded and source-bound',['media.output','timeline'],'high')
    report['dimensions']['captions']=qa.dimension(captions['status'],'deterministic_validation',captions['scope'],['captions'])
    report['code_receipts']=evidence.receipts();qa.assess(report);qa.validate_report(report)
    ctx={'source_info':info,'output_info':verified['metadata'],'plan':plan,'timeline':timeline,'canonical':packet['canonical']}
    return report,ctx
