#!/usr/bin/env python3
"""Stage 5.5 renderer: closed TEST_ONLY fixtures and fail-closed production gate."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import renderer_core_v01 as core
import render_test_fixtures_v01 as fixtures

MANIFEST='render-manifest.v01.json'
PLAN='synthetic-plan.v03.json'
SPEC='execution-spec.v01.json'
TIMELINE='timeline.v01.json'
IDENTITY='synthetic-identity.v01.json'


@contextlib.contextmanager
def render_lock():
    core.TEST_ROOT.mkdir(parents=True,exist_ok=True)
    path=core.TEST_ROOT/'.render.lock'
    if path.is_symlink():raise core.Error('Unsafe renderer lock path')
    with path.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise core.Error('Another renderer is active; no unbounded concurrency') from None
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def publish(output,binary_files,json_files):
    output=core.new_directory(output,core.TEST_ROOT)
    output.parent.mkdir(parents=True,exist_ok=True);output.mkdir();created=[]
    try:
        for name,path in binary_files.items():
            dest=output/name
            if Path(name).name!=name:raise core.Error('Unsafe publication filename')
            core.safe_path(dest,output=True)
            with path.open('rb') as handle:os.fsync(handle.fileno())
            os.link(path,dest);created.append(dest)
        # Manifest last is the completed-bundle marker. Every file is exclusive
        # and atomically complete, including the MP4; partial bundles roll back.
        for name,data in json_files.items():
            dest=output/name;core.shared.write_json(dest,data);created.append(dest)
        return output
    except BaseException:
        for p in created:p.unlink(missing_ok=True)
        output.rmdir()
        raise


def self_test(name,output,*,output_overrides=None,resource_overrides=None):
    output=core.new_directory(output,core.TEST_ROOT);output.parent.mkdir(parents=True,exist_ok=True)
    with render_lock(),tempfile.TemporaryDirectory(dir=output.parent,prefix='.stage55-work-') as temporary:
        work=Path(temporary);started=time.monotonic()
        identity,plan,spec,source,assets=fixtures.create(work,name,output,output_overrides=output_overrides,resource_overrides=resource_overrides)
        graph=core.compile_timeline(plan,spec)
        environment=core.environment()
        missing=[cap for cap in graph['required_capabilities'] if not set(core.FILTERS[cap]).issubset(environment['available_filters'])]
        if {'overlay','subtitle'} & set(graph['required_capabilities']) and not environment['font']['available']:
            raise core.Error('Text operation requires the verified local font dependency')
        if missing or not environment['libx264_available'] or not environment['aac_available']:raise core.Error('Required local encoder/filter unavailable')
        video,audio,execution,filter_digest=core.encode(source,graph,spec,work,assets,'TEST_ONLY',admission=(identity,plan,output))
        verification=core.verify_output(video,graph,audio,spec['resources'])
        # Actual effect/source-order/audio behavior measurements accompany each
        # synthetic receipt, not merely filter listing or command compilation.
        observations=fixture_observations(name,source,video,graph,spec)
        execution.update(total_elapsed_sec=round(time.monotonic()-started,3),filter_graph_sha256=filter_digest)
        manifest={'contract_version':core.VERSION,'renderer_version':core.VERSION,'render_status':'TEST_ONLY_COMPLETED',
                  'authorization_mode':'TEST_ONLY','fixture_id':identity['fixture_id'],'source':plan['source'],
                  'plan_sha256':core.digest_object(plan),'execution_spec_sha256':core.digest_object(spec),'evidence_identifiers':['synthetic.source'],
                  'environment':environment,'code_receipts':core.code_receipts(),'verified_capabilities_used':graph['required_capabilities'],
                  'requested_operations':plan['variants'][0]['operations'],'applied_operations':graph['operations'],'unsupported_operations':[],
                  'timeline':graph,'output':{**verification['metadata'],'path':core.shared.relative(output/'render.mp4'),
                                            'sha256':core.intake.gate.sha256_file(video),'bytes':video.stat().st_size},
                  'execution':execution,'verification':{**verification,'fixture_measurements':observations},
                  'production_approval_granted':False,'publish_approved':False,'editorial_quality_review':'NOT_PERFORMED'}
        core.base.validate_object(manifest,core.base.load_schema('render-manifest.v0.1.schema.json'),'Render manifest')
        binaries={'render.mp4':video,'source.mp4':source}
        for logical,path in assets.items():binaries[Path(logical).name]=path
        publish(output,binaries,{PLAN:plan,SPEC:spec,IDENTITY:identity,TIMELINE:graph,MANIFEST:manifest})
        return manifest


def fixture_observations(name,source,video,timeline,spec):
    import math
    import numpy as np
    from scipy.fft import rfft,rfftfreq
    limits=spec['resources']
    measurements={'known_synthetic_source':'three colored scenes; synthetic 440/660/880 Hz tones, not human speech'}
    def frequency(pcm,time):
        part=np.asarray(pcm[int((time-.08)*48000):int((time+.08)*48000)],dtype=float)
        spectrum=np.abs(rfft(part*np.hanning(len(part))));return float(rfftfreq(len(part),1/48000)[int(np.argmax(spectrum))])
    def rms(pcm,a,b):
        values=pcm[int(a*48000):int(b*48000)];return math.sqrt(sum(x*x for x in values)/len(values))
    if name in ('basic','silent','reuse'):
        dominant=[]
        for t in (1,3,5):
            raw=core.frame_rgb(video,t,limits=limits);pixels=np.frombuffer(raw,dtype=np.uint8).reshape(320,180,3)
            dominant.append(int(np.argmax(pixels[180:220,80:110].mean(axis=(0,1)))))
        expected_colors=[0,0,2] if name=='reuse' else [2,0,1]
        if dominant!=expected_colors:raise core.Error('Synthetic reordered source-frame identity mismatch')
        measurements['frame_scene_order']=dominant
        if name in ('basic','reuse'):
            pcm=core.audio_pcm(video,limits);frequencies=[frequency(pcm,t) for t in (1,3,5)]
            if any(abs(a-b)>15 for a,b in zip(frequencies,[440,440,880] if name=='reuse' else [880,440,660])):raise core.Error('Synthetic audio/video reorder mismatch')
            measurements['aligned_tone_hz']=frequencies
    if name=='dynamic':
        pcm=core.audio_pcm(video,limits);source_pcm=core.audio_pcm(source,limits)
        f=frequency(pcm,.8)
        if abs(f-440)>15:raise core.Error('atempo pitch-preservation check failed')
        silence=rms(pcm,1.62,1.67)
        if silence>.01:raise core.Error('Freeze did not produce defined silence')
        frozen=np.frombuffer(core.frame_rgb(video,1.65,limits=limits),dtype=np.uint8).reshape(320,180,3)
        if frozen[180:220,80:110,0].mean()<180:raise core.Error('Freeze produced wrong/black frame')
        # White marker geometry changes under explicit punch zoom and crop.
        zoom=np.frombuffer(core.frame_rgb(video,.8,limits=limits),dtype=np.uint8).reshape(320,180,3)
        ordinary=np.frombuffer(core.frame_rgb(source,.8,limits=limits),dtype=np.uint8).reshape(320,180,3)
        if np.mean(np.abs(zoom.astype(float)-ordinary.astype(float)))<2:raise core.Error('Punch zoom did not change frame geometry')
        cropped=np.frombuffer(core.frame_rgb(video,4.7,limits=limits),dtype=np.uint8)
        original=np.frombuffer(core.frame_rgb(source,4.7,limits=limits),dtype=np.uint8)
        if np.mean(np.abs(cropped.astype(float)-original.astype(float)))<2:raise core.Error('Crop did not change frame geometry')
        green=np.frombuffer(core.frame_rgb(video,2.7,limits=limits),dtype=np.uint8)
        original_green=np.frombuffer(core.frame_rgb(source,2.7,limits=limits),dtype=np.uint8)
        if np.mean(np.abs(green.astype(float)-original_green.astype(float)))<2:raise core.Error('Explicit color parameters had no measured effect')
        measurements.update(speed_pitch_hz=f,freeze_rms=silence,zoom_crop_color_changed=True,freeze_frame_nonblack=True)
    if name=='creative-text':
        def sample(t):return np.frombuffer(core.frame_rgb(video,t,limits=limits),dtype=np.uint8).reshape(320,180,3)
        samples=[sample(t) for t in (.1,.3,.6,1.0,1.4,1.7,1.9)]
        green=[float(frame[200:252,:,1].sum()) for frame in samples]
        if not green[0]<green[1]<green[2]<green[3] or not green[3]>green[4]>green[5]>green[6]:
            raise core.Error('Animated text fade pixels do not follow the declared envelope')
        active=samples[3][200:252];yellow=(active[:,:,0]>170)&(active[:,:,1]>120)&(active[:,:,2]<110)
        cyan=sample(3.8)[200:252];cyan_pixels=(cyan[:,:,0]<140)&(cyan[:,:,1]>150)&(cyan[:,:,2]>180)
        if yellow.sum()<30 or cyan_pixels.sum()<30:raise core.Error('Selected text colors not physically visible')
        if any(float(np.mean(np.abs(frame[260:].astype(float)-samples[0][260:].astype(float))))>1 for frame in samples[1:]):
            raise core.Error('Animated text spills into reserved bottom area')
        measurements.update(text_animation_fade_green_sums=green,yellow_text_pixels=int(yellow.sum()),
            cyan_text_pixels=int(cyan_pixels.sum()),selected_fonts=['dejavu_sans_bold','dejavu_sans'],
            reserved_bottom_unchanged=True)
    if name=='captions':
        before=np.frombuffer(core.frame_rgb(video,.1,limits=limits),dtype=np.uint8).reshape(320,180,3)
        active=np.frombuffer(core.frame_rgb(video,.8,limits=limits),dtype=np.uint8).reshape(320,180,3)
        diff=float(np.mean(np.abs(active[20:65].astype(float)-before[20:65].astype(float))))
        if diff<1:raise core.Error('Hook overlay not visible in timed safe area')
        sub_off=np.frombuffer(core.frame_rgb(video,4.6,limits=limits),dtype=np.uint8).reshape(320,180,3)
        sub_on=np.frombuffer(core.frame_rgb(video,5.1,limits=limits),dtype=np.uint8).reshape(320,180,3)
        delta=float(np.mean(np.abs(sub_on[235:290].astype(float)-sub_off[235:290].astype(float))))
        if delta<1:raise core.Error('Mapped synthetic subtitle not visible')
        end=np.frombuffer(core.frame_rgb(video,6.2,limits=limits),dtype=np.uint8)
        original=np.frombuffer(core.frame_rgb(source,3.9,limits=limits),dtype=np.uint8)
        if np.mean(np.abs(end.astype(float)-original.astype(float)))<1:raise core.Error('CTA overlay not visible during freeze')
        measurements.update(hook_safe_area_difference=diff,subtitle_safe_area_difference=delta,caption_source_window=[3,3.5],caption_output_window=[4.85,5.475],cta_visible=True,literal_text_file_expansion_disabled=True)
    if name=='audio':
        pcm=core.audio_pcm(video,limits);original=core.audio_pcm(source,limits)
        gain=rms(pcm,.5,1.5)/rms(original,.5,1.5)
        duck=rms(pcm,4.2,4.8)/rms(original,4.2,4.8)
        if not .42<gain<.6 or not .28<duck<.44:raise core.Error('Gain/duck measured level mismatch')
        if not rms(pcm,.01,.04)<rms(pcm,.5,.8)*.3 or not rms(pcm,5.96,5.99)<rms(pcm,5.2,5.5)*.3:raise core.Error('Audio fade measurements failed')
        measurements.update(gain_ratio=gain,duck_ratio=duck,fade_in_out_measured=True,denoise_technical_render_only=True)
    if name in ('music','silent-music'):
        pcm=core.audio_pcm(video,limits);segment=np.asarray(pcm[2*48000:3*48000],dtype=float);s=np.abs(rfft(segment))
        if s[220]<5:raise core.Error('Explicit synthetic asset mix tone absent')
        measurements['asset_220_hz_magnitude']=float(s[220]);measurements['asset_rights_scope']='TEST_ONLY'
    if name=='normalization':
        pcm=core.audio_pcm(video,limits);r=rms(pcm,.5,5.5)
        if not .01<r<.15:raise core.Error('Normalization output signal outside expected range')
        measurements['normalized_rms']=r;measurements['method']='single-pass dynamic loudnorm, not a full broadcast compliance certificate'
    return measurements


def capability_registry(bundles):
    env=core.environment();proofs={cap:[] for cap in core.FILTERS}
    for value in sorted(bundles,key=lambda value:str(core.shared.directory(value))):
        bundle=core.shared.directory(value)
        core.safe_path(bundle/MANIFEST,under=core.TEST_ROOT)
        manifest=core.read_json(bundle/MANIFEST)
        core.base.validate_object(manifest,core.base.load_schema('render-manifest.v0.1.schema.json'),'Capability proof manifest')
        if manifest['authorization_mode']!='TEST_ONLY' or manifest['code_receipts']!=core.code_receipts() or manifest['environment']!=env:
            raise core.Error('Capability proof environment/code/scope mismatch')
        plan,spec,identity=[core.read_json(bundle/f) for f in (PLAN,SPEC,IDENTITY)]
        assets={r['path']:bundle/Path(r['path']).name for r in spec['assets'].values()}
        fixtures.admit(identity,plan,spec,bundle/'source.mp4',bundle,assets)
        graph=core.compile_timeline(plan,spec)
        if (manifest['source']!=plan['source'] or manifest['plan_sha256']!=core.digest_object(plan)
                or manifest['execution_spec_sha256']!=core.digest_object(spec) or manifest['requested_operations']!=plan['variants'][0]['operations']
                or manifest['applied_operations']!=graph['operations'] or manifest['verified_capabilities_used']!=graph['required_capabilities']
                or manifest['unsupported_operations']):
            raise core.Error('Capability manifest source/plan/spec/operation bindings mismatch')
        if manifest['timeline']!=graph or manifest['output']['sha256']!=core.intake.gate.sha256_file(bundle/'render.mp4'):
            raise core.Error('Capability proof graph/output mismatch')
        # Re-measure actual results rather than accepting a forged true status.
        verification=core.verify_output(bundle/'render.mp4',graph,manifest['output']['audio_present'],spec['resources'])
        if verification['metadata']!=manifest['verification']['metadata'] or any(manifest['output'].get(k)!=v for k,v in verification['metadata'].items()):
            raise core.Error('Capability manifest output metadata mismatch')
        name=identity['fixture_id'].split('.')[-2]
        measured=fixture_observations(name,bundle/'source.mp4',bundle/'render.mp4',graph,spec)
        if measured!=manifest['verification']['fixture_measurements']:raise core.Error('Capability effect measurement receipt mismatch')
        for cap in graph['required_capabilities']:proofs[cap].append(core.av.reference(bundle/MANIFEST))
    operations={}
    for cap,needed in core.FILTERS.items():
        available=set(needed).issubset(env['available_filters']) and (cap not in ('overlay','subtitle') or env['font']['available'])
        operations[cap]={'status':'verified' if proofs[cap] else 'available' if available else 'unavailable_missing_dependency',
                         'available':available,'proofs':proofs[cap],'limitations':['Verified controlled local fixtures only; no production approval, intelligibility or editorial quality certification']}
    for cap,reason in {'animated_zoom':'V0.3 has no animation trajectory parameters','word_highlighting':'No word-level eligible timing contract','custom_arbitrary':'No generic filter/script injection',
                      'semantic_color_intent':'Numeric execution parameters required; prose is not executable','subject_tracking':'No verified tracking evidence'}.items():
        operations[cap]={'status':'unsupported','available':False,'proofs':[],'limitations':[reason]}
    operations['ass_subtitle_engine']={'status':'not_tested','available':env['libass_filter_available'],'proofs':[],
                                       'limitations':['The verified caption engine uses drawtext; ASS/libass engine not exercised or exposed']}
    registry={'contract_version':core.VERSION,'renderer_version':core.VERSION,'scope':'LOCAL_TECHNICAL_SELF_TESTS_ONLY',
              'environment':env,'code_receipts':core.code_receipts(),'operations':operations,'production_approval_granted':False}
    core.base.validate_object(registry,core.base.load_schema('renderer-capabilities.v0.1.schema.json'),'Capability registry')
    return registry


def validate_registry(path):
    data=core.read_json(path)
    core.base.validate_object(data,core.base.load_schema('renderer-capabilities.v0.1.schema.json'),'Renderer capabilities')
    bundles=sorted({str(core.safe_path(ref['path']).parent) for op in data['operations'].values() for ref in op['proofs']})
    for op in data['operations'].values():
        for ref in op['proofs']:
            if core.av.reference(core.safe_path(ref['path']))!=ref:raise core.Error('Capability manifest fingerprint mismatch')
    if data!=capability_registry(bundles):raise core.Error('Capability status does not match replayed proofs')
    return data


def production_admission(plan_path,packet_path,validation_path,authorization_path=None,spec_path=None,capabilities_path=None):
    plan=core.read_json(plan_path);packet=core.read_json(packet_path);old_report=core.read_json(validation_path)
    reasons=[]
    core.base.validate_object(plan,core.base.load_schema('adaptive-editing-plan.v0.3.schema.json'),'Production editing plan')
    core.base.validate_object(old_report,core.base.load_schema('adaptive-plan-validation.v0.3.schema.json'),'Independent validation')
    if plan['render_approved'] is not True:reasons.append('plan_render_approved_false')
    if plan['render_readiness']!='READY_FOR_RENDER':reasons.append('plan_not_ready_for_render')
    if old_report['status'] in ('NEEDS_REVIEW','BLOCKED'):reasons.append('independent_status_'+old_report['status'])
    if old_report['render_gate_passed'] is not True or old_report['render_approved'] is not True:reasons.append('independent_render_gate_false')
    if plan['source']!=packet.get('source') or plan['evidence_packet_sha256']!=core.director.validator.packet_digest(packet):reasons.append('source_or_evidence_binding_mismatch')
    else:
        source=core.safe_path(plan['source']['path'])
        if core.intake.gate.sha256_file(source)!=plan['source']['sha256']:reasons.append('source_sha256_mismatch')
    if authorization_path:
        auth=core.read_json(authorization_path)
        if auth.get('authorization_mode')=='TEST_ONLY' or auth.get('production_approval_granted') is False:reasons.append('synthetic_authorization_cannot_authorize_production')
        elif (auth.get('authorization_mode')!='PRODUCTION' or auth.get('plan_sha256')!=core.digest_object(plan)
              or auth.get('render_approved') is not True):reasons.append('invalid_execution_authorization')
    else:reasons.append('execution_authorization_missing')
    # Current immutable V0.3 approvals and Stage 5.4 reports cannot satisfy this
    # admission. No self-test token, CLI force flag or capability receipt changes
    # that fact. A future approved contract must arrive via separate scope.
    if spec_path is None:reasons.append('execution_specification_missing')
    if capabilities_path is None:reasons.append('verified_renderer_receipt_missing')
    if plan['required_reviews'] or plan['missing_evidence']:reasons.append('required_reviews_or_missing_evidence_unresolved')
    requested=[op for v in plan['variants'] for op in v['operations']]
    unsupported=[]
    for operation in requested:
        try:core.effective_kind(operation)
        except core.Error:unsupported.append({'operation_id':operation['operation_id'],'requested_intent':operation['parameters']})
    if reasons:return {'contract_version':core.VERSION,'status':'REJECTED_BEFORE_RENDER','reasons':reasons,'editing_started':False,'mp4_created':False,
                       'plan':core.av.reference(core.safe_path(plan_path)),'source':plan['source'],'render_approved':False,'publish_approved':False,
                       'requested_operations':requested,'unsupported_operations':unsupported,
                       'checks_reached':['plan_schema','existing_validation_schema','plan_packet_binding','source_sha256','approval_hard_gates'],
                       'checks_not_reached':['evidence_replay','renderer_receipt_replay','speech_factual_asset_reviews','editing_execution']}
    # Defensive unreachable gate: do not treat an arbitrary future review JSON as
    # an authenticated approval protocol that has not been implemented yet.
    raise core.Error('Production review/authorization contract unavailable; no executable admission')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    test=commands.add_parser('self-test');test.add_argument('--fixture',choices=fixtures.NAMES,required=True);test.add_argument('--output',required=True)
    for field in ('width','height','fps','crf'):test.add_argument('--'+field,type=int)
    test.add_argument('--fit',choices=('pad','crop'));test.add_argument('--preset',choices=('ultrafast','superfast','veryfast','faster','fast','medium'))
    for field in ('threads','memory-mib'):test.add_argument('--'+field,type=int)
    test.add_argument('--timeout-sec',type=float)
    caps=commands.add_parser('capabilities');caps.add_argument('--bundles',nargs='+',required=True);caps.add_argument('--output',required=True)
    prod=commands.add_parser('production')
    for field in ('plan','packet','validation','output','report'):prod.add_argument('--'+field,required=True)
    for field in ('authorization','spec','capabilities'):prod.add_argument('--'+field)
    args=p.parse_args(argv)
    try:
        if args.command=='self-test':
            out={k:getattr(args,k) for k in ('width','height','fps','crf','fit','preset') if getattr(args,k) is not None}
            resources={k:getattr(args,k) for k in ('threads','memory_mib','timeout_sec') if getattr(args,k) is not None}
            result=self_test(args.fixture,args.output,output_overrides=out,resource_overrides=resources);print(json.dumps({'status':result['render_status'],'output':result['output']['path'],'duration_sec':result['output']['duration_sec']}));return 0
        if args.command=='capabilities':
            output=core.safe_path(args.output,output=True,under=core.TEST_ROOT)
            with render_lock():registry=capability_registry(args.bundles)
            core.shared.write_json(output,registry);print(json.dumps({'status':'CAPABILITIES_REPLAY_VERIFIED','verified':[k for k,v in registry['operations'].items() if v['status']=='verified']}));return 0
        core.new_directory(args.output,core.PRODUCTION_ROOT)
        output=core.safe_path(args.report,output=True,under=core.TEST_ROOT)
        refusal=production_admission(args.plan,args.packet,args.validation,args.authorization,args.spec,args.capabilities)
        core.shared.write_json(output,refusal);print(json.dumps({'status':refusal['status'],'reasons':refusal['reasons'],'editing_started':False}));return 20
    except (core.Error,OSError,KeyError,TypeError,ValueError,RecursionError):
        print('BLOCKED: renderer admission/validation/resource/output failure; untrusted diagnostics suppressed',file=__import__('sys').stderr);return 1

if __name__=='__main__':
    with core.intake.processing_deadline(600):raise SystemExit(main())
