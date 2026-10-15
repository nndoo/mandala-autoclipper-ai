"""One explicitly authorized local Showcase preview, using the existing encoder.

This is a fixed manual inspection recipe, not an autonomous editing policy.
There is no production, publishing, arbitrary plan or arbitrary source mode.
"""
import argparse
import copy
from pathlib import Path
import tempfile

import renderer_core_v01 as core
import render_video_v01 as renderer
import validate_adaptive_director_plan_v03 as validator

TASK = 'stage55-one-local-showcase-preview-v01'
SHA = '58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f'
SOURCE = core.base.ROOT/'data/test-videos/cinematic-7693770515172887829.mp4'
LIVE = core.base.ROOT/'data/analyses/director/adaptive-v03/showcase.live.v01'
ORIGINAL_HASHES = {
    'editing-plan.v03.json':'afe679fb40c21ac3cd6ccbc5be5d75948c56209fc112cc986089dd08c273e86f',
    'plan-validation.v03.json':'494ee2ab1d6d46748f57dfd3392ebc3cd8024dc0ee9de2c6c78002757e2394df'}
AUDIT = core.TEST_ROOT/'real-preview-audit.v01'
PLAN = 'preview-plan.v03.json'
AUTH = 'preview-authorization.v01.json'
REPORT = 'validation-report.v01.json'
SPEC = 'execution-spec.v01.json'
PACKET = 'evidence-packet.v03.json'
ALLOWED = {'trim', 'concat', 'audio_gain', 'audio_fade'}
FAILURE = 'render-failure.v01.json'
TIME_FAILURE = 'render-failure.v02.json'


def preview_code():
    return core.code_receipts()+[core.av.reference(core.base.ROOT/p) for p in (
        'scripts/render_showcase_preview_v01.py',
        'src/schemas/preview-authorization.v0.1.schema.json',
        'src/schemas/render-preview-manifest.v0.1.schema.json')]


def destination(value):
    path=core.new_directory(value,core.TEST_ROOT)
    if path.parent!=core.TEST_ROOT or not __import__('re').fullmatch(r'real-content-showcase\.v[0-9]{2,}',path.name):
        raise core.Error('Preview requires its dedicated versioned destination')
    return path


def manual_plan(packet):
    # These three source ranges are editorial reference material only. Rebuilding
    # a distinct manual plan leaves the failed inference and its report intact.
    plan=copy.deepcopy(core.read_json(LIVE/'editing-plan.v03.json'))
    plan['editorial_concept']='Manual local preview: three showroom perspectives'
    plan['intended_message']='Private evaluation of original showroom visuals'
    variant=plan['variants'][0]
    variant.update(title='PREVIEW ONLY — manual Showcase selection',
                   editorial_concept=plan['editorial_concept'],intended_message=plan['intended_message'],
                   narrative_strategy='Frontal vehicle opening, wide showroom, then existing close-to-wide sequence')
    rationales=[
        'Manual selection: skip darkest opening, retain frontal vehicle view; sampled stability is a candidate only',
        'Manual selection: retain wide showroom framing; model vehicle identifications remain unverified',
        'Manual selection: retain close view and existing return transition; out-point is not a verified black-screen boundary']
    for shot,rationale in zip(variant['shots'],rationales):
        shot['rationale']=rationale
    variant['hook']['rationale']=rationales[0]
    variant['audio_strategy']={'intent':'Source music with explicit -8 dB headroom and short splice fades; musical continuity pending listening review',
                              'sync_basis':'none','evidence_refs':['source.metadata']}
    variant['ending']={'intent':'End on source showroom visuals; manual out-point, no verified silence or blackout claim','cta':None}
    reviews=['Listen to sung-vocal splices; short fades do not prove musical continuity',
             'Inspect hook, pacing, exposure and original transitions',
             'Source music publication rights are unknown; private local inspection only']
    variant['required_reviews']=reviews
    plan['required_reviews']=reviews
    plan['evidence_packet_sha256']=validator.packet_digest(packet)
    plan['missing_evidence']=list(packet['missing_evidence'])
    variant['operations']=[]
    clock=0
    for i,shot in enumerate(variant['shots']):
        end=round(clock+shot['source_end_sec']-shot['source_start_sec'],6)
        def operation(uid,kind,a,b,parameters):
            return {'operation_id':uid,'kind':kind,'shot_id':shot['shot_id'],
                    'output_start_sec':a,'output_end_sec':b,'evidence_refs':['source.metadata'],
                    'rationale':'Explicit manual audio headroom/splice treatment, not beat or speech evidence',
                    'capability_status':'requires_implementation','parameters':parameters}
        variant['operations'].append(operation(f'gain-{i}','audio_gain',clock,end,{'gain_db':-8}))
        for direction,a,b in (('in',clock,round(clock+.1,6)),('out',round(end-.1,6),end)):
            variant['operations'].append(operation(f'fade-{i}-{direction}','custom',a,b,
                {'name':'renderer.audio_fade.v01','implementation_requirements':'Explicit 0.1 second linear source-audio fade in bound execution spec'}))
        clock=end
    return plan


def execution_spec(plan):
    extra={}
    for op in plan['variants'][0]['operations']:
        if op['kind']=='custom':
            extra[op['operation_id']]={'fade':{'direction':op['operation_id'].split('-')[-1],
                'start_sec':op['output_start_sec'],'duration_sec':.1}}
    return {'contract_version':core.VERSION,'plan_sha256':core.digest_object(plan),'variant_id':'A',
            'output':dict(core.DEFAULT_OUTPUT),'resources':{**core.DEFAULT_RESOURCES,'memory_mib':3072,'timeout_sec':180},
            'operation_parameters':extra,'assets':{}}


def authorization(plan,spec,packet,capabilities,output):
    return {'contract_version':'0.1.0','task_id':TASK,'authorization_mode':'REAL_CONTENT_PREVIEW',
            'source_sha256':SHA,'source_path':core.shared.relative(SOURCE),
            'plan_sha256':core.digest_object(plan),'execution_spec_sha256':core.digest_object(spec),
            'evidence_packet_sha256':validator.packet_digest(packet),
            'capabilities':core.av.reference(core.safe_path(capabilities,under=AUDIT)),
            'code_receipts':preview_code(),'original_blocked_plan':core.av.reference(LIVE/'editing-plan.v03.json'),
            'original_blocked_report':core.av.reference(LIVE/'plan-validation.v03.json'),
            'output_directory':core.shared.relative(output),'maximum_final_candidates':1,
            'prior_failure':core.av.reference(AUDIT/(TIME_FAILURE if (AUDIT/TIME_FAILURE).is_file() else FAILURE)) if (AUDIT/FAILURE).is_file() else None,
            'local_preview_authorized':True,'production_approval_granted':False,'publish_approved':False,
            'labels':['PREVIEW_ONLY','NOT_APPROVED_FOR_PUBLICATION']}


def validate_context(context,plan,spec,source,output,assets):
    output=destination(output)
    if core.safe_path(source)!=SOURCE or core.intake.gate.sha256_file(SOURCE)!=SHA:
        raise core.Error('Preview source is outside the single-source allowlist')
    if assets or spec.get('assets'):raise core.Error('Preview permits no external assets')
    if any(core.intake.gate.sha256_file(core.safe_path(LIVE/name))!=sha for name,sha in ORIGINAL_HASHES.items()):
        raise core.Error('Original blocked plan/report fingerprint changed')
    packet=context['packet'];core.intake.validate_packet(packet)
    if packet['source']['sha256']!=SHA or packet['source']['path']!=core.shared.relative(SOURCE):
        raise core.Error('Preview evidence source mismatch')
    original=core.read_json(LIVE/'editing-plan.v03.json')
    old_report=core.read_json(LIVE/'plan-validation.v03.json')
    if old_report['status']!='BLOCKED' or not any(f['code']=='onset_sync_without_onset' for f in old_report['blocking_findings']):
        raise core.Error('Original blocked evidence changed')
    if core.digest_object(plan)==core.digest_object(original) or plan!=manual_plan(packet):
        raise core.Error('Only the separate manual preview recipe may execute')
    if spec!=execution_spec(plan):raise core.Error('Preview execution spec differs from approved manual recipe')
    report=validator.validate_plan(plan,packet)
    if not report['structural_validity'] or report['blocking_findings'] or report['status']=='BLOCKED' or report!=context['validation']:
        raise core.Error('Preview structural/temporal validation blocked or mismatched')
    cap_path=core.safe_path(context['capabilities'],under=AUDIT)
    expected=authorization(plan,spec,packet,cap_path,output)
    core.base.validate_object(context['authorization'],core.base.load_schema('preview-authorization.v0.1.schema.json'),'Preview authorization')
    if context['authorization']!=expected:raise core.Error('Preview authorization bindings mismatch')
    if expected['prior_failure'] is not None:check_recovery(plan,output)
    graph=core.compile_timeline(plan,spec)
    if set(graph['required_capabilities'])-ALLOWED:raise core.Error('Operation outside preview scope')
    registry=renderer.validate_registry(cap_path)
    if any(registry['operations'][c]['status']!='verified' for c in graph['required_capabilities']):
        raise core.Error('Preview capability has no current replay-verified proof')
    return graph,report


def completed_candidate_exists():
    return any(core.TEST_ROOT.glob('real-content-showcase.v*/render-manifest.v01.json'))


def check_recovery(plan,output):
    # One narrowly evidenced resource recovery for the same, never-delivered
    # candidate. Failed bytes/receipts are preserved; no validation is overridden.
    if not (AUDIT/FAILURE).is_file():raise core.Error('No evidenced failed attempt for recovery')
    failed=core.read_json(AUDIT/FAILURE)
    paths={'prior_authorization':AUDIT/'prepared.v04'/AUTH,'consumed_attempt':AUDIT/'preview-attempt.v01.json',
           'decoder_diagnostic':AUDIT/'read-only-filter-diagnostic.v01.json',
           'successful_frame_diagnostic':AUDIT/'read-only-filter-diagnostic.v02.json'}
    if any(failed.get(k)!=core.av.reference(core.safe_path(path,under=AUDIT)) for k,path in paths.items()):
        raise core.Error('Failed attempt evidence fingerprint mismatch')
    prior=core.read_json(paths['prior_authorization']);attempt=core.read_json(paths['consumed_attempt'])
    bad=core.read_json(paths['decoder_diagnostic']);good=core.read_json(paths['successful_frame_diagnostic'])
    if (failed.get('task_id')!=TASK or failed.get('source_sha256')!=SHA or failed.get('status')!='FAILED_NO_FINAL_CANDIDATE'
        or failed.get('final_candidate_created') is not False or failed.get('temporary_work_cleaned') is not True
        or failed.get('exit_code')!=1 or failed.get('output_directory')!=core.shared.relative(output)
        or prior.get('source_sha256')!=SHA or prior.get('plan_sha256')!=core.digest_object(plan)
        or prior.get('output_directory')!=core.shared.relative(output)
        or attempt.get('authorization_sha256')!=core.digest_object(prior)
        or 'Cannot allocate memory' not in bad.get('bounded_diagnostics','')
        or bad.get('resources',{}).get('memory_mib')!=1536
        or good.get('status')!='FRAME_REPLAY_VERIFIED' or good.get('actual_frames')!=312
        or good.get('resources',{}).get('memory_mib')!=3072 or good.get('diagnostic_errors')!=[]
        or good.get('encoding_performed') is not False or good.get('mp4_created') is not False):
        raise core.Error('Recovery is not the evidenced same-candidate memory adjustment')
    if completed_candidate_exists():raise core.Error('The single final candidate already exists')
    if (AUDIT/'preview-attempt.v02.json').exists():
        if not (AUDIT/TIME_FAILURE).is_file():raise core.Error('No evidence for the final bounded time recovery')
        stopped=core.read_json(AUDIT/TIME_FAILURE)
        paths={'prior_authorization':AUDIT/'prepared.v05'/AUTH,'prior_execution_spec':AUDIT/'prepared.v05'/SPEC,
               'consumed_attempt':AUDIT/'preview-attempt.v02.json','previous_failure':AUDIT/FAILURE,
               'execution_log':AUDIT/'render.final.v03.txt'}
        if any(stopped.get(k)!=core.av.reference(core.safe_path(path,under=AUDIT)) for k,path in paths.items()):
            raise core.Error('Time recovery evidence fingerprint mismatch')
        prior=core.read_json(paths['prior_authorization']);old_spec=core.read_json(paths['prior_execution_spec'])
        attempt=core.read_json(paths['consumed_attempt'])
        if (stopped.get('task_id')!=TASK or stopped.get('source_sha256')!=SHA or stopped.get('status')!='FAILED_NO_FINAL_CANDIDATE'
            or stopped.get('final_candidate_created') is not False or stopped.get('temporary_work_cleaned') is not True
            or stopped.get('exit_code')!=1 or stopped.get('output_directory')!=core.shared.relative(output)
            or not 90<=stopped.get('elapsed_after_reservation_sec',0)<=100
            or prior.get('plan_sha256')!=core.digest_object(plan) or prior.get('source_sha256')!=SHA
            or prior.get('output_directory')!=core.shared.relative(output)
            or prior.get('execution_spec_sha256')!=core.digest_object(old_spec)
            or old_spec['resources']['memory_mib']!=3072 or old_spec['resources']['timeout_sec']!=90
            or attempt.get('authorization_sha256')!=core.digest_object(prior)):
            raise core.Error('Time recovery differs from the same failed candidate')


def admit(context,plan,spec,source,output,assets):
    validate_context(context,plan,spec,source,output,assets)
    if completed_candidate_exists():raise core.Error('No second completed preview is authorized')
    marker='preview-attempt.v01.json'
    if (AUDIT/marker).exists():
        check_recovery(plan,output)
        marker='preview-attempt.v02.json'
        if (AUDIT/marker).exists():
            if not (AUDIT/TIME_FAILURE).is_file():raise core.Error('No evidenced final recovery')
            marker='preview-attempt.v03.json'  # Exclusive: no fourth attempt or second final candidate.
    core.shared.write_json(AUDIT/marker,{
        'task_id':TASK,'authorization_sha256':core.digest_object(context['authorization']),
        'started_at':core.shared.now(),'maximum_final_candidates':1,
        'prior_failure':context['authorization']['prior_failure'],
        'production_approval_granted':False,'publish_approved':False})


def prepare(output,capabilities,prepared):
    output=destination(output);prepared=core.new_directory(prepared,AUDIT)
    packet=core.read_json(LIVE/PACKET);core.intake.validate_packet(packet)
    plan=manual_plan(packet);spec=execution_spec(plan)
    context={'packet':packet,'validation':validator.validate_plan(plan,packet),
             'capabilities':str(core.safe_path(capabilities,under=AUDIT)),
             'authorization':authorization(plan,spec,packet,capabilities,output)}
    validate_context(context,plan,spec,SOURCE,output,{})
    prepared.mkdir()
    for name,obj in ((PLAN,plan),(SPEC,spec),(PACKET,packet),(REPORT,context['validation']),(AUTH,context['authorization'])):
        core.shared.write_json(prepared/name,obj)
    return context['validation']


def black_scan(video,graph,limits,*,decoded_frame_count=None):
    import numpy as np
    width,height=54,96
    raw,_=core.run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(video),
                    '-vf',f'scale={width}:{height}','-vsync','0','-pix_fmt','gray','-f','rawvideo','pipe:1'],limits,max_bytes=3000000)
    frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,height*width)
    nominal=round(graph['expected_duration_sec']*graph['output_settings']['fps'])
    expected=nominal if decoded_frame_count is None else decoded_frame_count
    tolerance=graph['output_settings'].get('timing_tolerance_frames',2)
    if not isinstance(expected,int) or expected<=0 or abs(expected-nominal)>tolerance or len(frames)!=expected:
        raise core.Error('Dark-frame scan sample count mismatch')
    fractions=(frames<26).mean(axis=1)
    candidates=[round(i/graph['output_settings']['fps'],6) for i,v in enumerate(fractions) if v>=.98]
    if candidates:raise core.Error('Near-black output frame requires review; no second candidate rendered')
    return {'method':'Every decoded CFR frame downscaled to 54x96 luma; >=98% pixels below 26/255',
            'decoded_frames':len(frames),'near_black_timestamps_sec':candidates,
            'maximum_dark_pixel_fraction':float(fractions.max()),
            'limitation':'Threshold scan is not semantic verification or a full-resolution defect detector'}


def render(prepared):
    prepared=core.safe_path(Path(prepared)/AUTH,under=AUDIT).parent
    plan,spec,packet,report,auth=[core.read_json(prepared/n) for n in (PLAN,SPEC,PACKET,REPORT,AUTH)]
    output=destination(auth['output_directory'])
    context={'packet':packet,'validation':report,'authorization':auth,'capabilities':auth['capabilities']['path']}
    with renderer.render_lock(),tempfile.TemporaryDirectory(dir=AUDIT,prefix='.preview-work-') as temporary:
        work=Path(temporary)
        graph,_=validate_context(context,plan,spec,SOURCE,output,{})
        video,audio,execution,filter_digest=core.encode(SOURCE,graph,spec,work,{},'REAL_CONTENT_PREVIEW',admission=(context,plan,output))
        verified=core.verify_output(video,graph,audio,spec['resources'])
        verified['black_frame_scan']=black_scan(video,graph,spec['resources'],decoded_frame_count=verified['frame_count'])
        core.ffmpeg(['-i',str(video),'-vf',f'fps=12/{core.n(graph["expected_duration_sec"])},scale=180:320,tile=6x2',
                     '-frames:v','1',str(work/'preview-contact.png')],work,spec['resources'])
        # Recheck file identities after decoding/encoding, without consuming again.
        validate_context(context,plan,spec,SOURCE,output,{})
        execution['filter_graph_sha256']=filter_digest
        manifest={'contract_version':'0.1.0','authorization_mode':'REAL_CONTENT_PREVIEW',
            'render_status':'PREVIEW_ONLY_COMPLETED','labels':auth['labels'],
            'authorization_sha256':core.digest_object(auth),'source':plan['source'],
            'plan_sha256':core.digest_object(plan),'execution_spec_sha256':core.digest_object(spec),
            'evidence_packet_sha256':validator.packet_digest(packet),'evidence_inputs':packet['inputs'],
            'capabilities':auth['capabilities'],'code_receipts':preview_code(),'environment':core.environment(),
            'verified_capabilities_used':graph['required_capabilities'],'timeline':graph,
            'requested_operations':plan['variants'][0]['operations'],'applied_operations':graph['operations'],
            'output':{**verified['metadata'],'path':core.shared.relative(output/'preview.mp4'),
                      'sha256':core.intake.gate.sha256_file(video),'bytes':video.stat().st_size},
            'execution':execution,'verification':verified,'validation_status':report['status'],
            'production_approval_granted':False,'publish_approved':False,'editorial_quality_review':'PENDING_MANUAL_REVIEW'}
        core.base.validate_object(manifest,core.base.load_schema('render-preview-manifest.v0.1.schema.json'),'Preview manifest')
        notes=work/'preview-review-notes.md'
        notes.write_text(review_notes(manifest),encoding='utf-8')
        renderer.publish(output,{'preview.mp4':video,'preview-contact.png':work/'preview-contact.png','preview-review-notes.md':notes},
            {PLAN:plan,SPEC:spec,PACKET:packet,REPORT:report,AUTH:auth,'timeline.v01.json':graph,renderer.MANIFEST:manifest})
        return manifest


def review_notes(manifest):
    return f'''# Private Showcase preview — manual review pending

PREVIEW_ONLY; NOT_APPROVED_FOR_PUBLICATION. Production and publish approval false.
One local candidate only. No new AI inference or Stage 5.6 review.

Manual plan preserves candidate ranges 0.6–4.1, 14.5–17.5, 21.2–25.1 seconds (10.4 s).
Source frames show frontal vehicle, wide showroom, close view and existing return transition.
Canonical vehicle identifications and conversational-speech absence remain model/unverified.
The canonical black-screen claim from 25.1 s is inconsistent with sampled source imagery;
25.1 s is an editorial out-point only. Stage 5C cut/stability evidence remains signal-estimated.

Departures from the blocked model proposal: distinct manual title/concept/rationales;
no onset/beat synchronization; no prose-only color correction. Explicit source gain -8 dB
because decoded source peak was 1.639118; no repair of pre-existing distortion is claimed.
Each selected audio segment gets 100 ms linear fade-in/out. This reduces splice discontinuity,
but produces brief dips and may interrupt sung phrases. Original effects inside retained
source windows stay present. No new flash/neon/transition/caption/music asset is added.

Technical checks passed: full decode, H264/AAC, 1080x1920/30 FPS, continuous PTS,
{manifest['verification']['frame_count']} frames, near-black threshold scan empty.
Output peak {manifest['verification']['audio_signal']['peak_linear']:.6f}, RMS
{manifest['verification']['audio_signal']['rms_linear']:.6f}. These are not artistic certification.

Listen especially at output 3.5 and 6.5 seconds: vocal/phrase cuts, volume dips and continuity.
Watch framing, exposure, hook and pacing, and the source's existing transition near 7.4 seconds.
Publication/music rights unknown. Human audiovisual review remains required.
'''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare')
    for name in ('output','capabilities','prepared'):p.add_argument('--'+name,required=True)
    p=sub.add_parser('render');p.add_argument('--prepared',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':result=prepare(args.output,args.capabilities,args.prepared);print(result['status'])
        else:
            result=render(args.prepared);print(result['render_status'],result['output']['path'])
        return 0
    except (core.Error,OSError,KeyError,ValueError,TypeError) as error:
        category='SUBPROCESS_TIMEOUT' if str(error)=='Media subprocess timeout exceeded' else 'VALIDATION_OR_SUBPROCESS_FAILURE'
        print('BLOCKED: '+category+'; scoped preview failure; raw diagnostics suppressed',file=__import__('sys').stderr)
        return 1


if __name__=='__main__':
    with core.intake.processing_deadline(600):raise SystemExit(main())
