#!/usr/bin/env python3
"""Bounded Stage 5.8 benchmark. Replay is offline; live actions need session authorization."""
import argparse
import copy
import fcntl
from functools import wraps
import json
from pathlib import Path
import time

import benchmark_evidence_v01 as evidence
import benchmark_preview_v01 as preview
import revision_quality_v01 as revision_quality
import director_diagnostics_v01 as diagnostics

core, qa, ri = evidence.core, evidence.qa, evidence.ri
director = core.director
TAXONOMY = ['analysis_failure','missing_speech_evidence','source_provenance_failure','model_response_invalid',
    'unsupported_editing_operation','plan_validation_failure','audio_continuity_failure','visual_rendering_defect',
    'qa_grounding_error','editorial_disagreement','human_review_pending','authorization_blocked',
    'resource_timeout','rights_clearance_pending']
SHOWCASE = '58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f'
MISSING = ['automotive_advertisement_with_verified_claims','product_demonstration','mixed_speech_music',
    'unstructured_showroom','previously_unseen_content']


def output(value): return core.new_directory(value, evidence.ROOT)


def criteria(characteristics):
    """Relevance only, never a genre-specific shot recipe or quality score."""
    def relevant(presence):
        return 'APPLICABLE' if presence=='present' else 'NOT_APPLICABLE' if presence=='absent' else 'UNCERTAIN'
    return {'speech_continuity':relevant(characteristics.get('speech_presence')),
        'music_phrasing':relevant(characteristics.get('music_presence')),
        'hook':'APPLICABLE','content_clarity':'APPLICABLE','visual_progression':'APPLICABLE',
        'pacing':'APPLICABLE','ending':'APPLICABLE','subtitles':'CONDITIONAL_ON_PLAN',
        'classification_basis':characteristics.get('classification_basis','UNAVAILABLE'),
        'uncertainty_policy':'Canonical absence is unverified context; no verified speech/beat boundaries inferred'}


def controls(destination):
    import renderer_revision_v02 as audio
    destination=core.new_directory(destination,core.TEST_ROOT)
    destination.mkdir(parents=True)
    audio.self_test('replace',destination/'replace');audio.self_test('mix',destination/'mix')
    receipt={'contract_version':evidence.VERSION,'mode':'synthetic_technical_control',
        'proofs':[qa.ref(destination/k/audio.MANIFEST) for k in ('replace','mix')],
        'evaluated':['hard_cuts','continuous_source_soundtrack','explicit_mixing','gain','fades','decode','PTS'],
        'real_editorial_genre_evaluation':'NOT_TESTED',
        'limitations':['Synthetic colors/tones contain no genuine dialogue or product claims'],**evidence.FLAGS}
    core.shared.write_json(destination/'control-receipt.v01.json',receipt)
    return destination/'control-receipt.v01.json'


def entry_from_prepared(dataset_id, prepared):
    ri.identifier(dataset_id)
    packet, _, _ = director.load_prepared(prepared)
    ref = {k: packet['source'][k] for k in ('path','sha256')}
    core.safe_path(ref['path'], under=core.base.ROOT/'data/test-videos');qa.same_reference(ref)
    info = core.media_info(core.safe_path(ref['path']))
    if any(info[k] != packet['source'][k] for k in ('duration_sec','width','height','fps')):
        raise core.Error('Dataset source metadata mismatch')
    profile = packet['canonical']['content_profile']; speech = packet['speech']
    historical = ref['sha256'] == SHOWCASE
    return evidence.check('entry', {'dataset_id':dataset_id,'source':ref,'metadata':info,'sample_kind':'real_content',
        'prepared':qa.ref(core.safe_path(Path(prepared)/director.REQUEST)),
        'characteristics':{'content_tags':profile['content_tags'],'speech_presence':profile['speech_presence'],
            'music_presence':profile['music_presence'],'language':None,'classification_basis':'canonical_model_unverified',
            'regional_speech':speech['requirements']['regions'],'mixed_or_uncertain_supported':True},
        'evidence_availability':{'canonical':'source_bound_model_unverified','audio_visual':'replay_verified_signal_candidates',
            'speech_eligibility':speech['eligibility'],'text_status':speech['text_verification_status'],
            'timing_status':speech['timing_verification_status'],'missing_evidence':packet['missing_evidence']},
        'rights_status':'UNKNOWN','permitted_operations':['historical_replay','technical_decode','human_review']+
            ([] if historical else ['authorized_director','source_bound_safe_preview','authorized_reviewer']),
        'analysis_readiness':'REPLAY_VERIFIED','rendering_eligibility':'NOT_ELIGIBLE' if historical else
            'SOURCE_WHOLE_ONLY_OR_BLOCKED' if speech['requirements']['overall_requirement']!='not_required' else 'CONDITIONAL',
        'human_reviews':['Audiovisual quality','Factual/context continuity','Rights/clearance'],
        'benchmark_eligibility':'HISTORICAL_ONLY' if historical else 'HISTORICAL_AND_LIVE_GATED'})


def discovery_metadata(path):
    try:return core.media_info(core.safe_path(path))
    except core.Error:
        try:
            data=core.probe(core.safe_path(path))
            return {'status':'BLOCKED_MEDIA_POLICY','reason':'Cannot qualify under existing duration/FPS/stream policy',
                'ffprobe_video':[ {k:s.get(k) for k in ('codec_name','width','height','r_frame_rate','duration')}
                    for s in data.get('streams',[]) if s.get('codec_type')=='video']}
        except core.Error:return {'status':'UNAVAILABLE','reason':'Bounded probe failed; source is not eligible'}


def dataset(entries, destination):
    destination = output(destination)
    if len({e['dataset_id'] for e in entries})!=len(entries) or len({e['source']['sha256'] for e in entries})!=len(entries):
        raise core.Error('Duplicate dataset ID or real source')
    discovered = [qa.ref(core.safe_path(p, under=core.base.ROOT/'data/test-videos'))
        for p in sorted((core.base.ROOT/'data/test-videos').glob('*.mp4'))]
    for ref in discovered:
        if any(e['source']==ref for e in entries):continue
        # Unknown local bytes are discovery records, never invented editorial samples.
        entries.append(evidence.check('entry', {'dataset_id':'unclassified-'+ref['sha256'][:12],'source':ref,
            'metadata':discovery_metadata(ref['path']),'sample_kind':'unknown_local','prepared':None,
            'characteristics':{'classification_basis':'UNAVAILABLE','speech_presence':'uncertain','music_presence':'uncertain'},
            'evidence_availability':{},'rights_status':'UNKNOWN','permitted_operations':['technical_decode'],
            'analysis_readiness':'UNAVAILABLE','rendering_eligibility':'NOT_ELIGIBLE','human_reviews':['Source/content identification'],
            'benchmark_eligibility':'NOT_READY'}))
    registry = evidence.check('registry', {'contract_version':evidence.VERSION,'entries':entries,'discovered_media':discovered,
        'missing_real_categories':MISSING,'inputs':[e['prepared'] for e in entries if e['prepared']], **evidence.FLAGS})
    director.publish(destination, {'dataset-registry.v01.json':registry,
        'source-identity-receipts.v01.json':{'contract_version':evidence.VERSION,'sources':[
            {'source':e['source'],'metadata':e['metadata'],'verification':'SHA256_ONLY_MEDIA_POLICY_BLOCKED' if e['metadata'].get('status') else 'SHA256_AND_FFPROBE','semantic_classification':'UNVERIFIED'} for e in entries],**evidence.FLAGS},
        'failure-taxonomy.v01.json':{
        'contract_version':evidence.VERSION,'categories':TAXONOMY,'limitation':'Component attribution requires evidence; creative scores are not bug diagnoses'}})
    return destination/'dataset-registry.v01.json'


def load_registry(reference):
    qa.same_reference(reference);value=evidence.check('registry',qa.read(reference['path']))
    if len({e['dataset_id'] for e in value['entries']})!=len(value['entries']):raise core.Error('Duplicate registry ID')
    for entry in value['entries']:
        qa.same_reference(entry['source']);core.safe_path(entry['source']['path'],under=core.base.ROOT/'data/test-videos')
        info=discovery_metadata(entry['source']['path']) if entry['sample_kind']=='unknown_local' else core.media_info(core.safe_path(entry['source']['path']))
        if info!=entry['metadata']:raise core.Error('Dataset source metadata changed')
    ri.refs_match({str(i):r for i,r in enumerate(value['inputs'])})
    return value


def checkpoint(job, old, state, reason, **updates):
    seq=1 if old is None else old['sequence']+1
    value={**(old or {}),**updates,'contract_version':evidence.VERSION,'sequence':seq,'state':state,'reason':reason,
        'previous':qa.ref(job/f'checkpoint.{seq-1:03d}.json') if old else None,'created_at':core.shared.now(),**evidence.FLAGS}
    evidence.check('state',value);core.shared.write_json(job/f'checkpoint.{seq:03d}.json',value)
    return value


def load(job):
    job=core.safe_path(Path(job)/'benchmark-config.v01.json',under=evidence.ROOT).parent
    config=qa.read(job/'benchmark-config.v01.json')
    if config['code_receipts']!=evidence.receipts():raise core.Error('Benchmark code changed; prepare new run')
    prior=None;state=None
    for i,path in enumerate(sorted(job.glob('checkpoint.*.json')),1):
        current=evidence.check('state',qa.read(path))
        if current['sequence']!=i or current['previous']!=prior:raise core.Error('Checkpoint chain changed')
        if state and (any(current['remaining_budget'][k]>state['remaining_budget'][k] for k in state['remaining_budget']) or current['attempts']<state['attempts']):
            raise core.Error('Budget/attempt history replenished')
        if state is None and current['remaining_budget']!=config['initial_budget']:
            raise core.Error('Initial benchmark budget changed')
        state=current;prior=qa.ref(path)
    if state is None:raise core.Error('Missing benchmark checkpoint')
    ri.refs_match(state['artifacts']);registry=load_registry(state['registry'])
    entry=next((e for e in registry['entries'] if e['dataset_id']==state['entry_id']),None)
    if entry is None:raise core.Error('Unknown benchmark source')
    if config['source']!=entry['source'] or config['mode']!=state['mode']:
        raise core.Error('Benchmark configuration/source scope changed')
    return job,state,config,entry


def bounded_step(function):
    @wraps(function)
    def execute(job_value):
        _,state,_,_=load(job_value)
        if state['remaining_budget']['processing_sec']<=0:raise core.Error('Processing time budget exhausted')
        with core.intake.processing_deadline(min(900,state['remaining_budget']['processing_sec'])):
            return function(job_value)
    return execute


def prepare(registry, dataset_id, destination, *, mode='historical_replay', authorization=''):
    destination=output(destination);regref=qa.ref(registry);value=load_registry(regref)
    entry=next((e for e in value['entries'] if e['dataset_id']==dataset_id),None)
    if not entry:raise core.Error('Unknown benchmark dataset ID')
    if mode=='live_e2e' and (not authorization.strip() or entry['benchmark_eligibility']!='HISTORICAL_AND_LIVE_GATED' or entry['source']['sha256']==SHOWCASE):
        raise core.Error('Live sample unauthorized, unready or exhausted Showcase lineage')
    config={'contract_version':evidence.VERSION,'source':entry['source'],'mode':mode,'permission_text':authorization,
        'initial_budget':{'director_calls':1 if mode=='live_e2e' else 0,'reviewer_calls':2 if mode=='live_e2e' else 0,
            'renders':1 if mode=='live_e2e' else 0,'processing_sec':1800},'maximum_attempts':1,
        'automatic_retries':0,'code_receipts':evidence.receipts(),'cost':'UNKNOWN',
        'source_upload_policy':'Director text only; Reviewer source and output complete MP4 if safely rendered; no new ASR/Analyst calls',
        'destination':core.shared.relative(evidence.RENDER_ROOT/destination.name),**evidence.FLAGS}
    director.publish(destination,{'benchmark-config.v01.json':config})
    checkpoint(destination,None,'PREPARED','Source registered; no model/render executed',run_id=destination.name,
        registry=regref,entry_id=dataset_id,mode=mode,remaining_budget=config['initial_budget'],attempts=0,
        action_reserved=None,artifacts={'config':qa.ref(destination/'benchmark-config.v01.json')})
    if entry['prepared']:
        packet,_,_=director.load_prepared(core.safe_path(entry['prepared']['path']).parent)
        core.shared.write_json(destination/'analysis-eligibility.v01.json',{'contract_version':evidence.VERSION,
            'source':entry['source'],'canonical_status':'SOURCE_BOUND_MODEL_UNVERIFIED','fresh_analysis_required':False,
            'speech':packet['speech'],'missing_evidence':packet['missing_evidence'],**evidence.FLAGS})
    core.shared.write_json(destination/'authorization-requirements.v01.json',{'contract_version':evidence.VERSION,
        'source':entry['source'],'authorization_received':bool(authorization.strip()),'session_authorization':authorization,
        'provider':ri.reviewer.PROVIDER,'model_alias':ri.reviewer.MODEL,'backend_identity':'UNVERIFIED',
        'director_calls':config['initial_budget']['director_calls'],'reviewer_calls':config['initial_budget']['reviewer_calls'],
        'analysis_calls':0,'asr_calls':0,'preview_renders':config['initial_budget']['renders'],
        'modalities':{'director':'source-bound evidence text','reviewer':'MP4 video/audio offered; hearing remains self-report'},
        'expected_resources':{'media_memory_mib':3072,'threads':2,'command_wall_sec':900},
        'cost':'UNKNOWN','destination':config['destination'],'limitations':entry['human_reviews'],**evidence.FLAGS})
    return destination


def reserve(job,state,config,action,charges):
    if state['mode']!='live_e2e' or not config['permission_text'].strip():raise core.Error('Live invocation unauthorized')
    if state['action_reserved']:raise core.Error('Interrupted action reserved; no automatic retry')
    budget=copy.deepcopy(state['remaining_budget'])
    if budget['processing_sec']<=0:raise core.Error('Processing time budget exhausted')
    for key,count in charges.items():
        if budget[key]<count:raise core.Error('Model/render budget exhausted')
        budget[key]-=count
    return checkpoint(job,state,'ACTION_RESERVED',action,remaining_budget=budget,action_reserved=action)


def finish(job,state,started,status,reason,artifacts=None,attempts=None):
    budget=copy.deepcopy(state['remaining_budget']);elapsed=time.monotonic()-started
    budget['processing_sec']=max(0,budget['processing_sec']-elapsed)
    if not budget['processing_sec']:status='RESOURCE_TIMEOUT';reason='Processing time exhausted; no PASS'
    return checkpoint(job,state,status,reason,remaining_budget=budget,action_reserved=None,
        attempts=state['attempts'] if attempts is None else attempts,
        artifacts={**state['artifacts'],**(artifacts or {})})


@bounded_step
def plan(job_value):
    job,state,config,entry=load(job_value)
    if state['state']!='PREPARED':return state
    if entry['source']['sha256']==SHOWCASE:raise core.Error('No additional Showcase Director attempt')
    prepared=core.safe_path(entry['prepared']['path']).parent
    packet,prompt,_=director.load_prepared(prepared);director.safe_text(prompt,director.MAX_PROMPT_BYTES)
    state=reserve(job,state,config,'director',{'director_calls':1});started=time.monotonic()
    try:
        bundle,result=diagnostics.run(prepared,job/'director.live.v01',live_approved=True)
        artifacts={'generation':qa.ref(bundle/director.RECEIPT),'independent_validation':qa.ref(bundle/director.REPORT)}
        if (bundle/'invocation-diagnostic.v01.json').exists():
            artifacts['director_diagnostic']=qa.ref(bundle/'invocation-diagnostic.v01.json')
        if not result['structural_validity']:
            return finish(job,state,started,'MODEL_RESPONSE_INVALID','Director schema invalid',artifacts,1)
        plan_value=qa.read(bundle/director.PLAN);artifacts['plan']=qa.ref(bundle/director.PLAN)
        capabilities=core.base.ROOT/'data/render-tests/stage55/real-preview-audit.v01/capabilities.v05.json'
        registry=__import__('render_video_v01').validate_registry(capabilities)
        spec={'contract_version':core.VERSION,'plan_sha256':core.digest_object(plan_value),
            'variant_id':plan_value['variants'][0]['variant_id'],'output':core.DEFAULT_OUTPUT,
            'resources':{**core.DEFAULT_RESOURCES,'memory_mib':3072,'timeout_sec':180},'operation_parameters':{},'assets':{}}
        validation,_=preview.validate_plan(plan_value,packet,registry,spec)
        core.shared.write_json(job/'execution-spec.v01.json',spec);core.shared.write_json(job/'preview-validation.v01.json',validation)
        artifacts.update(spec=qa.ref(job/'execution-spec.v01.json'),validation=qa.ref(job/'preview-validation.v01.json'),capabilities=qa.ref(capabilities))
        return finish(job,state,started,'VALIDATED_FOR_PRIVATE_PERMISSION' if validation['private_preview_eligible'] else 'PLAN_BLOCKED',
            'Independent validator and speech/context safety; no approval promotion',artifacts,1)
    except diagnostics.Failure as exc:
        return finish(job,state,started,'PLANNING_FAILURE',exc.diagnostic['error_category'],
            {'director_diagnostic':qa.ref(job/'director.live.v01/invocation-diagnostic.v01.json')})
    except (core.Error,OSError,ValueError,TypeError,KeyError):
        return finish(job,state,started,'PLANNING_FAILURE','Bounded Director/validation failed; no automatic retry')


@bounded_step
def render(job_value):
    job,state,config,entry=load(job_value)
    if state['state']!='VALIDATED_FOR_PRIVATE_PERMISSION':return state
    destination=evidence.RENDER_ROOT/job.name
    permit=evidence.check('permit',{'contract_version':evidence.VERSION,'mode':'STAGE58_PRIVATE_PREVIEW','source':entry['source'],
        'registry':state['registry'],**{k:state['artifacts'][k] for k in ('plan','validation','generation','spec','capabilities')},
        'destination':core.shared.relative(destination),'permission_text':config['permission_text'],'created_at':core.shared.now(),**evidence.FLAGS})
    permit_path=job/'preview-authorization.v01.json';core.shared.write_json(permit_path,permit)
    state=reserve(job,state,config,'render',{'renders':1});started=time.monotonic()
    try:
        preview.render(qa.ref(permit_path),entry,destination)
        return finish(job,state,started,'RENDERED','One source-bound private render; no production approval',
            {'render_manifest':qa.ref(destination/'benchmark-render-manifest.v01.json'),'output':qa.ref(destination/'preview.mp4'),'permit':qa.ref(permit_path)})
    except (core.Error,OSError,ValueError,TypeError,KeyError):return finish(job,state,started,'RENDER_FAILURE','Bounded render failed; no retry')


@bounded_step
def review(job_value):
    job,state,config,entry=load(job_value)
    if state['state']!='RENDERED':return state
    started=time.monotonic()
    try:
        report,ctx=preview.technical(state['artifacts']['render_manifest'])
        core.shared.write_json(job/'technical-qa.v01.json',report)
        packet=qa.packet_for(report,ctx);core.shared.write_json(job/'qa-packet.v01.json',packet)
        requests={role:ri.reviewer.make_request(packet,role) for role in ri.reviewer.ROLES}
        for role,request in requests.items():core.shared.write_json(job/ri.reviewer.name(role),request)
    except (core.Error,OSError,ValueError,TypeError,KeyError):return finish(job,state,started,'QA_FAILURE','Technical QA blocked; no model inference')
    state=reserve(job,state,config,'reviewer',{'reviewer_calls':2})
    try:
        responses={};refs={}
        for role,request in requests.items():
            raw=ri.reviewer.invoke(request,job/ri.reviewer.name(role),approved=True)
            core.base.write_exclusive(job/(role+'.untrusted-response.v01.txt'),director.safe_text(raw))
            responses[role]=ri.reviewer.validate_response(director.parse_response(raw),request,packet)
            path=job/(role+'.response.v01.json');core.shared.write_json(path,responses[role]);refs[role]=qa.ref(path)
        final=ri.reviewer.merge(report,responses,mode='live_multimodal',response_refs=refs)
        core.shared.write_json(job/'quality-report.v01.json',final)
        manifest=qa.read(state['artifacts']['render_manifest']['path'])
        fixed=evidence.quality_v02(qa.ref(job/'quality-report.v01.json'),final,manifest['timeline'],qa.read(manifest['spec']['path']))
        core.shared.write_json(job/'quality-report.v02.json',fixed)
        core.shared.write_json(job/'human-scorecard.v01.json',evidence.scorecard(state['artifacts']['output']))
        return finish(job,state,started,'HUMAN_REVIEW_PENDING','Fresh model judgment remains unverified',
            {'quality':qa.ref(job/'quality-report.v01.json'),'mapped_quality':qa.ref(job/'quality-report.v02.json'),'technical':qa.ref(job/'technical-qa.v01.json')})
    except (core.Error,OSError,ValueError,TypeError,KeyError):return finish(job,state,started,'QA_FAILURE','Reviewer failed/invalid; no retry')


def replay_showcase(destination,human_path=None):
    destination=output(destination);started=time.monotonic()
    parent_ref=qa.ref(core.base.ROOT/'data/qa/stage56/showcase.remediation.live.v02/quality-report.v01.json')
    parent,_,_=ri.load_parent(parent_ref['path'])
    ctx=revision_quality.verify_bundle(core.base.ROOT/'data/render-tests/stage57/showcase-revision.v01')
    live=ri.ROOT/'showcase-revision.v03/qa.01/live.v01'
    current_ref=qa.ref(live/qa.REPORT);current=qa.validate_report(qa.read(current_ref['path']))
    technical=qa.validate_report(qa.read(live.parent/qa.REPORT));packet=qa.packet_for(technical,ctx)
    request=ri.reviewer.make_request(packet,'edited_output')
    if request!=qa.read(live/ri.reviewer.name('edited_output')):raise core.Error('Historical Reviewer request mismatch')
    response=ri.reviewer.validate_response(qa.read(live/'edited_output.response.v01.json'),request,packet)
    # Original-source context is validated against its own historical packet.
    brief=ri.validate_brief(qa.read(ri.ROOT/'showcase-revision.v03/revision-brief.v01.json'))
    _,oldpacket,_,oldrequests=ri.reviewer.load_prepared(core.safe_path(brief['inputs']['prepared']['path']).parent)
    source_ref=brief['inputs']['response:original_source'];qa.same_reference(source_ref)
    source_response=ri.reviewer.validate_response(qa.read(source_ref['path']),oldrequests['original_source'],oldpacket)
    generation=qa.read(live/'review-generation-provenance.v01.json')
    reconstructed=ri.reviewer.merge(technical,{'edited_output':response,'original_source':source_response},
        mode='live_multimodal',response_refs=generation['responses'])
    reconstructed['ai'].update(source_context_reused=True,source_context_packet_sha256=source_response['packet_sha256'],
        comparison_method='One fresh V2 observation plus unchanged source-context observation from Stage 5.6; separate calls, not joint observation')
    if reconstructed!=current:raise core.Error('Historical V2 report differs from generation replay')
    old_timeline=parent['technical']['timeline'];new_timeline=ctx['timeline']
    old_spec=qa.read(parent['inputs']['spec']['path']);new_spec=ctx['spec']
    fixed=evidence.quality_v02(current_ref,current,new_timeline,new_spec)
    evidence.validate_quality(fixed,current,new_timeline,new_spec)
    human=qa.read(human_path) if human_path else None
    comparison=evidence.compare_media(evidence.frame_records(parent['rendered_output']['path']),evidence.frame_records(current['rendered_output']['path']),
        parent,current,old_timeline,new_timeline,human,ctx['manifest']['audio_mapping_verification'])
    if not comparison['identical_visual_frames_and_timing']:raise core.Error('Expected V1/V2 baseline visual identity failed')
    artifacts={'showcase-quality.v02.json':fixed,'showcase-comparison.v01.json':comparison,
        'human-scorecard.v01.json':evidence.scorecard(current['rendered_output'],parent['rendered_output']),
        'historical-replay-receipt.v01.json':{'contract_version':evidence.VERSION,'source':parent['source'],
            'parent_report':parent_ref,'current_report':current_ref,'mode':'historical_replay','new_inference':False,'new_render':False,
            'actual_media_revalidated':True,'human_review_input':qa.ref(human_path) if human_path else None,
            'elapsed_sec':time.monotonic()-started,'code_receipts':evidence.receipts(),**evidence.FLAGS}}
    if human:artifacts['human-submitted-scorecard.v01.json']=human
    director.publish(destination,artifacts)
    return destination


def summarize(registry_path, outputs, destination, control_receipts=None):
    destination=output(destination);registry=load_registry(qa.ref(registry_path));evaluations=[]
    control_refs=[]
    for path in control_receipts or []:
        receipt=qa.read(path)
        if receipt['mode']!='synthetic_technical_control' or receipt['real_editorial_genre_evaluation']!='NOT_TESTED':
            raise core.Error('Synthetic controls cannot claim real editorial acceptance')
        for ref in receipt['proofs']:__import__('renderer_revision_v02').validate_proof(ref)
        control_refs.append(qa.ref(path))
    for entry in registry['entries']:
        failures=[];layers={k:{'status':'UNAVAILABLE'} for k in ('technical','content_preservation','editorial','autonomy_grounding','human')}
        if entry['source']['sha256']==SHOWCASE:
            replay=next((Path(p) for p in outputs if (Path(p)/'showcase-comparison.v01.json').is_file()),None)
            if replay:
                comparison=evidence.check('comparison',qa.read(replay/'showcase-comparison.v01.json'))
                layers.update(technical={'status':'PASS','basis':'historical_actual_media_revalidated'},
                    editorial={'status':'NEEDS_REVIEW','basis':'historical_assessments_read_each_provenance','absolute_dimensions':comparison['absolute_quality_dimensions']},
                    autonomy_grounding={'status':'REPLAY_VERIFIED','visual_improvement':'NOT_ESTABLISHED_IDENTICAL','audio_mapping':'CONTINUOUS_SOURCE_MAPPING',
                        'initial_visual_plan_origin':'MANUAL_STAGE55_POC','initial_live_director_plan':'BLOCKED_NOT_RENDERED',
                        'stage57_revision_origin':'LIVE_DIRECTOR_AUDIO_ONLY','full_autonomous_initial_visual_selection':'NOT_DEMONSTRATED'},
                    content_preservation={'status':'NEEDS_REVIEW','speech':'not_required_canonical_unverified','musical_phrase_quality':'UNVERIFIED'},
                    human={'status':'PENDING' if comparison['human_review_pending'] else 'COMPLETED',
                        'scorecard':comparison['human_review']})
            mode='historical_replay'
        elif entry['analysis_readiness']=='REPLAY_VERIFIED':
            found=next((Path(p) for p in outputs if (Path(p)/'benchmark-config.v01.json').is_file() and qa.read(Path(p)/'benchmark-config.v01.json')['source']==entry['source']),None)
            mode='live_e2e' if found else 'historical_replay'
            layers['content_preservation']={'status':'UNAVAILABLE','speech':entry['evidence_availability']['speech_eligibility'],'semantic_continuity':'UNVERIFIED'}
            if found:
                _,state,_,_=load(found)
                layers['autonomy_grounding']={'status':state['state'],'attempts':state['attempts'],'artifacts':state['artifacts']}
                if state['state']=='PLAN_BLOCKED':
                    failures.append({'category':'missing_speech_evidence','component':'speech_gate_and_plan_safety',
                        'evidence':[state['artifacts']['validation']],'description':'Unsafe speech edits refused; not an approved output'})
                if state['state']=='HUMAN_REVIEW_PENDING':
                    actual=qa.validate_report(qa.read(state['artifacts']['quality']['path']))
                    layers['technical']={'status':actual['technical_qa_status']};layers['editorial']={'status':actual['ai_editorial_status'],'basis':'new_live_model_unverified'}
            layers['human']={'status':'PENDING','ratings':None}
        else:mode='historical_replay';layers['technical']={'status':'NOT_TESTED','reason':'Unclassified local canary is not a real editorial genre sample'}
        layers['editorial']['criteria_relevance']=criteria(entry['characteristics'])
        if layers['human']['status']=='PENDING':failures.append({'category':'human_review_pending','component':'human_evaluation','evidence':[],'description':'No exact-output human ratings received'})
        failures.append({'category':'rights_clearance_pending','component':'rights_review','evidence':[],'description':'Private benchmark only; publication rights unknown'})
        evaluations.append(evidence.check('evaluation',{'contract_version':evidence.VERSION,'dataset_id':entry['dataset_id'],'source':entry['source'],
            'mode':mode,'layers':layers,'failures':failures,'engineering_complete':True,'multi_genre_validated':False,'quality_decision':'NEEDS_REVIEW',**evidence.FLAGS}))
    summary={'contract_version':evidence.VERSION,'registry':qa.ref(registry_path),'evaluations':evaluations,
        'missing_real_categories':registry['missing_real_categories'],'aggregate_score':None,'aggregate_reason':'Unavailable/human-pending dimensions are not positive scores',
        'multi_genre_validated':False,'stage59_started':False,'synthetic_controls':control_refs,'code_receipts':evidence.receipts(),**evidence.FLAGS}
    director.publish(destination,{'cross-genre-summary.v01.json':summary,'benchmark-manifest.v01.json':{
        'contract_version':evidence.VERSION,'registry':qa.ref(registry_path),'run_inputs':[qa.ref(Path(p)/('showcase-comparison.v01.json' if (Path(p)/'showcase-comparison.v01.json').exists() else 'benchmark-config.v01.json')) for p in outputs],
        'synthetic_controls':control_refs,'mode':'offline_summary_of_explicit_runs','code_receipts':evidence.receipts(),**evidence.FLAGS}})
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('register');p.add_argument('--prepared',action='append',required=True);p.add_argument('--dataset-id',action='append',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('prepare');p.add_argument('--registry',required=True);p.add_argument('--dataset-id',required=True);p.add_argument('--output',required=True);p.add_argument('--mode',choices=['historical_replay','live_e2e'],default='historical_replay');p.add_argument('--authorization',default='')
    for action in ('plan','render','qa','advance','status'):p=sub.add_parser(action);p.add_argument('--job',required=True)
    p=sub.add_parser('replay-showcase');p.add_argument('--output',required=True);p.add_argument('--human-scorecard')
    p=sub.add_parser('controls');p.add_argument('--output',required=True)
    p=sub.add_parser('summarize');p.add_argument('--registry',required=True);p.add_argument('--run',action='append',required=True);p.add_argument('--output',required=True);p.add_argument('--control-receipt',action='append')
    args=parser.parse_args(argv);evidence.ROOT.mkdir(parents=True,exist_ok=True)
    lock=evidence.ROOT/'.benchmark.lock';core.safe_path(lock,output=not lock.exists(),under=evidence.ROOT)
    with lock.open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:
            if args.action=='register':
                if len(args.prepared)!=len(args.dataset_id):raise core.Error('Dataset ID/prepared length mismatch')
                result=dataset([entry_from_prepared(uid,p) for uid,p in zip(args.dataset_id,args.prepared)],args.output)
            elif args.action=='prepare':result=prepare(args.registry,args.dataset_id,args.output,mode=args.mode,authorization=args.authorization)
            elif args.action=='replay-showcase':result=replay_showcase(args.output,args.human_scorecard)
            elif args.action=='controls':result=controls(args.output)
            elif args.action=='summarize':result=summarize(args.registry,args.run,args.output,args.control_receipt)
            elif args.action=='status':result=load(args.job)[1]
            elif args.action=='plan':result=plan(args.job)
            elif args.action=='render':result=render(args.job)
            elif args.action=='qa':result=review(args.job)
            else:
                result=plan(args.job)
                if result['state']=='VALIDATED_FOR_PRIVATE_PERMISSION':result=render(args.job)
                if result['state']=='RENDERED':result=review(args.job)
            print(json.dumps({'status':result['state'] if isinstance(result,dict) and 'state' in result else 'COMPLETE','result':str(result) if isinstance(result,Path) else None}))
            if isinstance(result,dict) and args.action!='status':
                if result.get('state') in ('PLAN_BLOCKED','HUMAN_REVIEW_PENDING'):return 20
                if result.get('state') in ('PLANNING_FAILURE','RENDER_FAILURE','QA_FAILURE','RESOURCE_TIMEOUT','MODEL_RESPONSE_INVALID'):return 1
            return 0
        except (core.Error,OSError,ValueError,TypeError,KeyError):
            print('BLOCKED: benchmark provenance, safety, resource or output guard',file=__import__('sys').stderr);return 1


if __name__=='__main__':
    with core.intake.processing_deadline(900):raise SystemExit(main())
