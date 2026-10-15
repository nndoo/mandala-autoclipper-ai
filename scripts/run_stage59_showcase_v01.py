"""Source-bound Stage 5.9 Showcase V3 admission around the existing revision pipeline."""
import argparse
import copy
import json
from pathlib import Path
import tempfile

import render_video_v01 as renderer
import renderer_revision_v02 as audio
import revision_intelligence_v01 as ri
import revision_quality_v01 as quality
import run_adaptive_director_v03 as director
import run_revision_loop_v01 as loop

core=ri.core
qa=ri.qa
ROOT=core.base.ROOT/'data/revisions/stage59'
RENDER_ROOT=core.base.ROOT/'data/render-tests/stage59'
SOURCE='data/test-videos/cinematic-7693770515172887829.mp4'
SHA='58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f'
REGISTRY='data/render-tests/stage55/stage59-capabilities.v02.json'
AUDIO_CAPABILITY='data/render-tests/stage55/stage59-audio-capability.v02.json'
VERSION='stage59-showcase-v3.v0.1'
PROMPT='director-request.v01.txt'
REQUEST='request.v01.json'
BRIEF='revision-brief.v01.json'
PACKET='evidence-packet.v03.json'
PROPOSAL='revised-editing-plan.v01.json'
VALIDATION='revision-validation.v01.json'
GENERATION='revision-generation-provenance.v01.json'
PERMIT='preview-authorization.v01.json'
OUTPUT='preview-v3.mp4'


def code_receipts():
    return ri.code_receipts()+[qa.ref(Path(__file__)),qa.ref(core.base.ROOT/'scripts/stage59_recovery_v01.py'),qa.ref(Path(loop.validator.__file__)),qa.ref(core.base.ROOT/'src/schemas/adaptive-editing-plan.v0.3.schema.json'),qa.ref(core.base.ROOT/'scripts/render_showcase_preview_v01.py')]


def parent_context(path,source_packet=None):
    path=core.safe_path(path);report=qa.validate_report(qa.read(path))
    qa.same_reference(qa.ref(path))
    if report['integrity'].get('status')!='PASS' or report['source']!={'path':SOURCE,'sha256':SHA}:
        raise core.Error('Stage 5.9 requires source-bound Showcase QA')
    inputs=report['inputs']
    for name in ('plan','spec','timeline','manifest','director_packet','source','rendered_output'):
        qa.same_reference(inputs[name])
    for name in ('source','rendered_output'):
        if report[name]!=inputs[name]:raise core.Error('Parent QA media mismatch')
    plan=qa.read(inputs['plan']['path']);spec=qa.read(inputs['spec']['path'])
    timeline=qa.read(inputs['timeline']['path']);manifest=qa.read(inputs['manifest']['path'])
    historical_packet=qa.read(inputs['director_packet']['path'])
    if source_packet:
        packet=core.intake.validate_packet(qa.read(source_packet))
        from stage59_recovery_v01 import packet_view
        if packet_view(packet)!=packet_view(historical_packet):raise core.Error('Parent evidence observations changed')
    else:packet=core.intake.validate_packet(historical_packet)
    if plan['source']!=packet['source'] or manifest['source']!=plan['source'] or manifest['output']['sha256']!=inputs['rendered_output']['sha256']:
        raise core.Error('Parent plan, packet or manifest contamination')
    replay=audio.compile_timeline(plan,spec)
    # The historical V2 compiler predates the empty adaptive-text check field.
    if 'text_layout_checks' not in timeline and replay.get('text_layout_checks')==[] and not any(
            op['kind'] in ('overlay','subtitle') for op in plan['variants'][0]['operations']):
        replay.pop('text_layout_checks')
    if replay!=timeline or report['technical']['timeline']!=timeline:
        raise core.Error('Parent timeline replay mismatch')
    independent=loop.validator.validate_plan(plan,historical_packet)
    if independent['blocking_findings'] or not independent['structural_validity']:raise core.Error('Historical parent plan independently blocked')
    core.verify_output(core.safe_path(inputs['rendered_output']['path']),replay,True,spec.get('visual_spec',spec)['resources'])
    qa.same_reference({'path':manifest['output']['path'],'sha256':manifest['output']['sha256']})
    if manifest['output']['bytes']!=core.safe_path(manifest['output']['path']).stat().st_size:
        raise core.Error('Parent output size mismatch')
    return report,{'inputs':inputs,'plan':plan,'spec':spec,'timeline':timeline,'packet':packet,'manifest':manifest}


def prepare(parent_qa,job,target,prior_call=None,prior_validation=None,*,source_packet=None,registry_path=None,audio_capability_path=None,creative_directive=None):
    job=core.new_directory(job,ROOT);target=core.new_directory(target,RENDER_ROOT)
    report,ctx=parent_context(parent_qa,source_packet)
    registry_path=registry_path or REGISTRY;audio_capability_path=audio_capability_path or AUDIO_CAPABILITY
    registry=renderer.validate_registry(registry_path)
    capability=audio.validate_capability(audio_capability_path)
    adapted=copy.deepcopy(report)
    adapted['inputs']['capabilities']=qa.ref(registry_path)
    extra={'renderer_capabilities':qa.ref(registry_path),'capabilities':qa.ref(registry_path),
           'response:original_source':report['ai']['response_refs']['original_source']}
    metrics=ri.ROOT/'audit.v01/source-audio-metrics.v01.json'
    if metrics.is_file():extra['source_audio_metrics']=qa.ref(metrics)
    if creative_directive:extra['creative_directive']=qa.ref(creative_directive)
    brief=ri.make_brief(job.name,adapted,ctx,qa.ref(parent_qa),qa.ref(audio_capability_path),extra)
    prompt=loop.make_prompt(brief,ctx['packet'],ctx['plan'],registry,capability)
    prompt=director.safe_text(prompt+'\nSTAGE59_OBJECTIVE=Produce a genuinely different, source-grounded visual edit from the parent. Select a strong hook, progression and ending; vary source ranges/order/pacing or restrained verified visual treatment. Keep original music continuous and natural when source evidence allows. Do not invent beats, subtitles, product facts or renderer capabilities.\n',director.MAX_PROMPT_BYTES)
    prior_ref=None
    if prior_call:
        prior_ref=qa.ref(core.safe_path(prior_call,under=ROOT))
        prompt=director.safe_text(prompt+'\nPRIOR_CALL_CORRECTION=The referenced earlier live response ended inside a JSON string and was rejected before plan validation. Return one complete, compact JSON object only. Use one variant and concise rationales; omit whitespace and redundant prose. Keep every required contract field. Do not continue the truncated response.\n',director.MAX_PROMPT_BYTES)
    prior_validation_ref=None
    if prior_validation:
        prior_validation_ref=qa.ref(core.safe_path(prior_validation,under=ROOT))
        diagnostic=qa.read(prior_validation)
        if diagnostic.get('status')!='BLOCKED_HEADROOM' or diagnostic['source']!={'path':SOURCE,'sha256':SHA}:
            raise core.Error('Stage 5.9 correction requires source-bound headroom diagnosis')
        prompt=director.safe_text(prompt+'\nPRIOR_PLAN_CORRECTION=The prior saved AI proposal was rejected before rendering: its continuous source audio passage has measured decoded peak '+str(diagnostic['decoded_peak_linear'])+' at gain 0 dB, exceeding safe output headroom. Propose a genuinely new complete plan with sufficient attenuation and margin for AAC overshoot. Preserve a natural continuous soundtrack, source-bound visual changes, and all original review limitations. Do not copy or postprocess the rejected response.\n',director.MAX_PROMPT_BYTES)
    request={'contract_version':VERSION,'mode':'prepared_no_inference','source':brief['source'],
             'parent_qa':qa.ref(parent_qa),'parent_render':brief['parent_render'],
             'brief_sha256':core.digest_object(brief),'packet_sha256':loop.validator.packet_digest(ctx['packet']),
             'prompt_sha256':director.digest_text(prompt),'target_output':core.shared.relative(target),
             'renderer_capabilities':qa.ref(registry_path),'audio_capability':qa.ref(audio_capability_path),
             'code_receipts':code_receipts(),'prior_failed_call':prior_ref,'prior_blocked_validation':prior_validation_ref,'paid_calls':0,'renders':0,
             'production_eligible':False,'publishing_eligible':False}
    if source_packet:request['source_packet_replay']=qa.ref(source_packet)
    if creative_directive:request['output_filename']='preview-v4.mp4'
    director.publish(job,{BRIEF:brief,PACKET:ctx['packet'],PROMPT:prompt,REQUEST:request})
    return job


def load_job(job):
    job=core.shared.directory(job);core.safe_path(job/REQUEST,under=ROOT)
    request=qa.read(job/REQUEST);brief=ri.validate_brief(qa.read(job/BRIEF))
    packet=qa.read(job/PACKET)
    if 'source_packet_replay' in request:
        qa.same_reference(request['source_packet_replay'])
        if packet!=core.intake.validate_packet(qa.read(request['source_packet_replay']['path'])):raise core.Error('Prepared replay packet changed')
    if request.get('mode')=='recovered_historical_inference':
        from stage59_recovery_v01 import validate
        validate(job,request,packet)
    else:packet=core.intake.validate_packet(packet)
    prompt=director.safe_text((job/PROMPT).read_text(),director.MAX_PROMPT_BYTES)
    if (request['contract_version']!=VERSION or request['code_receipts']!=code_receipts()
            or request['brief_sha256']!=core.digest_object(brief)
            or request['packet_sha256']!=loop.validator.packet_digest(packet)
            or request['prompt_sha256']!=director.digest_text(prompt)
            or request['source']!=brief['source'] or request['parent_render']!=brief['parent_render']):
        raise core.Error('Stage 5.9 prepared request changed')
    return job,request,brief,packet,prompt


def attempts(job):
    return sorted(job.glob('attempt.[0-9][0-9]'))


def visual_signature(plan):
    variant=plan['variants'][0]
    return ([(s['source_start_sec'],s['source_end_sec'],s['timing']) for s in variant['shots']],
            [(o['kind'],o['output_start_sec'],o['output_end_sec'],o['parameters']) for o in variant['operations']
             if o['kind'] in ('overlay','subtitle','zoom','crop','color_grade')])


def infer(job,permission_text):
    job,request,brief,packet,prompt=load_job(job)
    if request.get('mode')=='recovered_historical_inference':raise core.Error('Recovery reuses inference; Director call refused')
    if not permission_text:raise core.Error('Live Director permission missing')
    previous=attempts(job)
    if previous:
        prior=previous[-1];validation=qa.read(prior/VALIDATION) if (prior/VALIDATION).is_file() else None
        if validation and not validation['blocking_reasons']:
            raise core.Error('Valid prior plan cannot be retried without a new review finding')
        correction={'previous_attempt':qa.ref(prior/GENERATION) if (prior/GENERATION).is_file() else None,
                    'blocking_reasons':validation['blocking_reasons'] if validation else ['invalid_model_response']}
        prompt=director.safe_text(prompt+'\nSTAGE59_CORRECTION='+json.dumps(correction,separators=(',',':')))
    number=len(previous)+1;marker=job/f'call.{number:02d}.reserved.json'
    core.shared.write_json(marker,{'contract_version':VERSION,'kind':'director','permission_origin':'explicit_user_session',
        'permission_text':director.safe_text(permission_text,2000),'request':qa.ref(job/REQUEST),
        'prompt_sha256':director.digest_text(prompt),'automatic_retry':False,'cost':'UNKNOWN'})
    iteration=job/f'attempt.{number:02d}'
    try:raw=director.live_response(prompt,approved=True)
    except (core.Error,OSError,ValueError,TypeError):
        core.shared.write_json(job/f'call.{number:02d}.failed.json',{'contract_version':VERSION,'status':'FAILED_NO_RETRY','reserved':qa.ref(marker)})
        raise
    core.base.write_exclusive(job/f'call.{number:02d}.raw.txt',raw)
    proposal=director.parse_response(raw)
    parent=qa.read(brief['parent_plan']['path']);parent_spec=qa.read(brief['inputs']['spec']['path'])
    if 'visual_spec' in parent_spec:parent_spec=parent_spec['visual_spec']
    registry=renderer.validate_registry(request['renderer_capabilities']['path'])
    validation=loop.validate_proposal(proposal,brief,packet,parent,parent_spec,registry)
    if not validation['blocking_reasons'] and visual_signature(parent)==visual_signature(proposal['plan']):
        validation['blocking_reasons'].append('stage59_requires_real_visual_plan_change')
        validation['preview_status']='BLOCKED'
        ri.check('validation',validation)
    spec=audio.spec_for(proposal['plan'],proposal['audio_timeline'],proposal['operation_parameters']) if not validation['blocking_reasons'] else None
    generation={'contract_version':VERSION,'mode':'live_model_inference','live_inference_performed':True,
        'request':qa.ref(job/REQUEST),'authorization':qa.ref(marker),'prompt_sha256':director.digest_text(prompt),
        'response_sha256':director.digest_text(raw),'proposal_sha256':core.digest_object(proposal),
        'code_receipts':code_receipts(),'cost':'UNKNOWN','automatic_retry':False,
        'production_eligible':False,'publishing_eligible':False}
    payload={'director-request.v01.txt':prompt,'untrusted-response.v01.txt':raw,
             PROPOSAL:proposal,VALIDATION:validation,GENERATION:generation}
    if spec is not None:payload[audio.SPEC]=spec
    director.publish(iteration,payload)
    return iteration,validation


def selected(job):
    job,request,brief,packet,_=load_job(job)
    for iteration in reversed(attempts(job)):
        if not (iteration/VALIDATION).is_file():continue
        validation=ri.check('validation',qa.read(iteration/VALIDATION))
        if validation['blocking_reasons']:continue
        proposal=ri.check('proposal',qa.read(iteration/PROPOSAL))
        spec=ri.check('execution',qa.read(iteration/audio.SPEC))
        from stage59_recovery_v01 import read_generation
        generation=read_generation(iteration/GENERATION)
        raw=director.safe_text((iteration/'untrusted-response.v01.txt').read_text())
        if ((request.get('mode')!='recovered_historical_inference' and generation['code_receipts']!=code_receipts()) or generation['response_sha256']!=director.digest_text(raw)
                or director.parse_response(raw)!=proposal or generation['proposal_sha256']!=core.digest_object(proposal)
                or generation['live_inference_performed'] is not True):
            raise core.Error('Stage 5.9 generated proposal changed')
        parent=qa.read(brief['parent_plan']['path']);parent_spec=qa.read(brief['inputs']['spec']['path'])
        if 'visual_spec' in parent_spec:parent_spec=parent_spec['visual_spec']
        registry=renderer.validate_registry(request['renderer_capabilities']['path'])
        if validation!=loop.validate_proposal(proposal,brief,packet,parent,parent_spec,registry):
            raise core.Error('Stage 5.9 independent validation changed')
        if visual_signature(parent)==visual_signature(proposal['plan']):raise core.Error('Audio-only V3 proposal blocked')
        if spec!=audio.spec_for(proposal['plan'],proposal['audio_timeline'],proposal['operation_parameters']):
            raise core.Error('Stage 5.9 execution spec changed')
        return job,request,brief,packet,iteration,proposal,spec,validation,generation
    raise core.Error('No independently valid live V3 plan')


def output_name(request):
    name=request.get('output_filename',OUTPUT)
    if name not in (OUTPUT,'preview-v4.mp4'):raise core.Error('Unsupported Stage 5.9 output name')
    return name


def render_admission(context,plan,spec,source):
    job,request,brief,packet,iteration,proposal,expected,validation,generation=selected(context['job'])
    permit=ri.check('permit',qa.read(iteration/PERMIT))
    target=core.new_directory(request['target_output'],RENDER_ROOT)
    if (plan!=proposal['plan'] or spec!=expected or core.safe_path(source)!=core.safe_path(SOURCE)
            or core.intake.gate.sha256_file(source)!=SHA or permit['mode']!='STAGE59_PRIVATE_PREVIEW'
            or permit['source']!={'path':SOURCE,'sha256':SHA} or permit['parent_render']!=brief['parent_render']
            or permit['proposal']!=qa.ref(iteration/PROPOSAL) or permit['validation']!=qa.ref(iteration/VALIDATION)
            or permit['plan_sha256']!=core.digest_object(plan) or permit['execution_sha256']!=core.digest_object(spec)
            or permit['output_directory']!=core.shared.relative(target) or permit['acknowledged_reviews']!=validation['reviews']
            or permit['renderer_capabilities']!=request['renderer_capabilities'] or permit['audio_capability']!=request['audio_capability']):
        raise core.Error('Stage 5.9 preview identity or permission mismatch')
    core.shared.write_json(iteration/'preview-consumed.v01.json',{'contract_version':VERSION,
        'permission':qa.ref(iteration/PERMIT),'plan_sha256':core.digest_object(plan),
        'started_at':core.shared.now(),'maximum_renders':1,'production_eligible':False,'publishing_eligible':False})


def render(job,permission_text):
    job,request,brief,packet,iteration,proposal,spec,validation,generation=selected(job)
    if not permission_text:raise core.Error('Local preview permission missing')
    target=core.new_directory(request['target_output'],RENDER_ROOT)
    if (iteration/PERMIT).exists() or (iteration/'preview-consumed.v01.json').exists() or target.exists():
        raise core.Error('Stage 5.9 preview already reserved or created')
    permit={'contract_version':ri.VERSION,'mode':'STAGE59_PRIVATE_PREVIEW','revision_id':brief['revision_id'],
        'source':{'path':SOURCE,'sha256':SHA},'parent_render':brief['parent_render'],
        'proposal':qa.ref(iteration/PROPOSAL),'plan_sha256':core.digest_object(proposal['plan']),
        'execution_sha256':core.digest_object(spec),'validation':qa.ref(iteration/VALIDATION),
        'renderer_capabilities':request['renderer_capabilities'],'audio_capability':request['audio_capability'],
        'output_directory':core.shared.relative(target),'maximum_renders':1,'permission_origin':'explicit_user_session',
        'permission_text':director.safe_text(permission_text,2000),'acknowledged_reviews':validation['reviews'],
        'local_preview_authorized':True,'production_eligible':False,'publishing_eligible':False,
        'render_approved':False,'publish_approved':False}
    ri.check('permit',permit);core.shared.write_json(iteration/PERMIT,permit)
    target.parent.mkdir(parents=True,exist_ok=True)
    with renderer.render_lock(),tempfile.TemporaryDirectory(dir=target.parent,prefix='.revision-work-') as temporary:
        video,timeline,verified,mapping,execution=audio.encode(core.safe_path(SOURCE),proposal['plan'],spec,Path(temporary),
            mode='STAGE59_PRIVATE_PREVIEW',context={'job':job})
        from render_showcase_preview_v01 import black_scan
        verified['black_frame_scan']=black_scan(video,timeline,spec['visual_spec']['resources'],decoded_frame_count=verified['frame_count'])
        manifest={'contract_version':audio.VERSION,'mode':'STAGE59_PRIVATE_PREVIEW','revision_id':brief['revision_id'],
            'source':brief['source'],'parent_render':brief['parent_render'],'parent_plan':brief['parent_plan'],
            'proposal':qa.ref(iteration/PROPOSAL),'validation':qa.ref(iteration/VALIDATION),
            'generation':qa.ref(iteration/GENERATION),'permission':qa.ref(iteration/PERMIT),
            'consumed_permission':qa.ref(iteration/'preview-consumed.v01.json'),
            'plan_sha256':core.digest_object(proposal['plan']),'execution_sha256':core.digest_object(spec),
            'evidence_inputs':packet['inputs'],'renderer_capabilities':request['renderer_capabilities'],
            'audio_capability':request['audio_capability'],'code_receipts':code_receipts(),
            'environment':core.environment(),'timeline':timeline,'verification':verified,
            'audio_mapping_verification':mapping,'execution':execution,
            'output':{**verified['metadata'],'path':core.shared.relative(target/output_name(request)),
                'sha256':core.intake.gate.sha256_file(video),'bytes':video.stat().st_size},
            'production_eligible':False,'publishing_eligible':False,'render_approved':False,'publish_approved':False,
            'human_review':'PENDING','labels':['PREVIEW_ONLY','NOT_APPROVED_FOR_PUBLICATION']}
        ri.check('manifest',manifest)
        audio.publish(target,{output_name(request):video},{audio.PLAN:proposal['plan'],audio.SPEC:spec,
            PACKET:packet,audio.TIMELINE:timeline,audio.MANIFEST:manifest},RENDER_ROOT)
    return target


def verify_bundle(bundle):
    bundle=core.shared.directory(bundle);core.safe_path(bundle/audio.MANIFEST,under=RENDER_ROOT)
    manifest=ri.check('manifest',qa.read(bundle/audio.MANIFEST))
    if manifest['mode']!='STAGE59_PRIVATE_PREVIEW' or manifest['code_receipts']!=code_receipts() or manifest['environment']!=core.environment():
        raise core.Error('Stage 5.9 manifest code/scope changed')
    iteration=core.safe_path(manifest['proposal']['path']).parent
    job,request,brief,packet,selected_iteration,proposal,spec,validation,generation=selected(iteration.parent)
    if iteration!=selected_iteration or manifest['source']!=brief['source'] or manifest['parent_render']!=brief['parent_render']:
        raise core.Error('Stage 5.9 lineage mismatch')
    plan=qa.read(bundle/audio.PLAN);timeline=qa.read(bundle/audio.TIMELINE)
    if (plan!=proposal['plan'] or qa.read(bundle/audio.SPEC)!=spec or qa.read(bundle/PACKET)!=packet
            or timeline!=audio.compile_timeline(plan,spec) or manifest['timeline']!=timeline
            or manifest['plan_sha256']!=core.digest_object(plan) or manifest['execution_sha256']!=core.digest_object(spec)
            or manifest['evidence_inputs']!=packet['inputs']):
        raise core.Error('Stage 5.9 plan/spec/timeline mismatch')
    output=core.safe_path(bundle/output_name(request),under=RENDER_ROOT)
    if (manifest['output']['path']!=core.shared.relative(output)
            or manifest['output']['sha256']!=core.intake.gate.sha256_file(output)
            or manifest['output']['bytes']!=output.stat().st_size):
        raise core.Error('Stage 5.9 output mismatch')
    permit=ri.check('permit',qa.read(iteration/PERMIT))
    consumed=qa.read(iteration/'preview-consumed.v01.json')
    if (manifest['permission']!=qa.ref(iteration/PERMIT) or manifest['consumed_permission']!=qa.ref(iteration/'preview-consumed.v01.json')
            or consumed['permission']!=manifest['permission'] or permit['proposal']!=manifest['proposal']
            or permit['output_directory']!=core.shared.relative(bundle)):
        raise core.Error('Stage 5.9 permit consumption mismatch')
    verified=core.verify_output(output,timeline,True,spec['visual_spec']['resources'])
    if manifest['verification']['metadata']!=verified['metadata'] or manifest['output']['duration_sec']!=verified['metadata']['duration_sec']:
        raise core.Error('Stage 5.9 decode mismatch')
    if manifest['audio_mapping_verification']!=audio.measure_audio_mapping(core.safe_path(SOURCE),output,timeline,spec):
        raise core.Error('Stage 5.9 audio mapping mismatch')
    inputs={k:qa.ref(bundle/n) for k,n in (('plan',audio.PLAN),('spec',audio.SPEC),('timeline',audio.TIMELINE),
        ('manifest',audio.MANIFEST),('director_packet',PACKET))}
    inputs.update(source=qa.ref(SOURCE),rendered_output=qa.ref(output),
        proposal=manifest['proposal'],validation=manifest['validation'],generation=manifest['generation'],
        permission=manifest['permission'],consumed_permission=manifest['consumed_permission'],
        renderer_capabilities=manifest['renderer_capabilities'],audio_capability=manifest['audio_capability'])
    inputs.update({'evidence:'+k:r for k,r in packet['inputs'].items()})
    return {'bundle':bundle,'manifest':manifest,'plan':plan,'spec':spec,'timeline':timeline,
        'source':core.safe_path(SOURCE),'output':output,'source_info':audio.validate_source_audio(SOURCE,plan,spec),
        'output_info':verified['metadata'],'inputs':inputs,'canonical':packet['canonical'],
        'speech':packet['speech'],'director_packet':packet}


def review(job,permission_text):
    if not permission_text:raise core.Error('Live Reviewer permission missing')
    job,request,brief,packet,iteration,proposal,spec,validation,generation=selected(job)
    target=core.shared.directory(request['target_output']);ctx=verify_bundle(target)
    root=core.new_directory(job/'qa.v01',ROOT)
    report,checked=quality.evaluate(target)
    if report['integrity']['status']!='PASS' or checked is None:raise core.Error('Stage 5.9 technical QA blocked')
    director.publish(root,{qa.REPORT:report,qa.TECH:report['technical'],qa.PACKET:qa.packet_for(report,ctx)})
    core.shared.write_json(job/'reviewer-call.reserved.json',{'contract_version':VERSION,
        'permission_origin':'explicit_user_session','permission_text':director.safe_text(permission_text,2000),
        'output':qa.ref(target/output_name(request)),'automatic_retry':False,'cost':'UNKNOWN'})
    reviewed,path=quality.live_review(root,report,ctx,brief,under=ROOT)
    comparison=quality.compare(qa.read(brief['qa_report']['path']),reviewed,brief['qa_report'],qa.ref(path),
        qa.read(brief['parent_plan']['path']),proposal['plan'],spec)
    core.shared.write_json(job/'comparison.v01.json',comparison)
    return path,job/'comparison.v01.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--parent-qa',required=True);p.add_argument('--job',required=True);p.add_argument('--target',required=True);p.add_argument('--prior-call');p.add_argument('--prior-validation');p.add_argument('--source-packet');p.add_argument('--registry');p.add_argument('--audio-capability');p.add_argument('--creative-directive')
    for name in ('infer','render','review'):
        p=commands.add_parser(name);p.add_argument('--job',required=True);p.add_argument('--permission-text',required=True)
    args=parser.parse_args()
    try:
        with core.intake.processing_deadline(600):
            if args.command=='prepare':result=prepare(args.parent_qa,args.job,args.target,args.prior_call,args.prior_validation,source_packet=args.source_packet,registry_path=args.registry,audio_capability_path=args.audio_capability,creative_directive=args.creative_directive)
            elif args.command=='infer':result=infer(args.job,args.permission_text)
            elif args.command=='render':result=render(args.job,args.permission_text)
            else:result=review(args.job,args.permission_text)
        print(json.dumps({'status':'COMPLETED','command':args.command,'result':str(result)},default=str))
    except (core.Error,OSError,ValueError,TypeError,KeyError,RecursionError) as error:
        print(json.dumps({'status':'BLOCKED','command':args.command,'reason':str(error)[:300]}))
        raise SystemExit(1) from None


if __name__=='__main__':main()
