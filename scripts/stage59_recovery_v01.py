"""Read-only historical inference recovery with fresh source evidence and admission."""

import json

import run_stage59_showcase_v01 as stage

core=stage.core
qa=stage.qa
HISTORICAL=stage.ROOT/'showcase-v3.v04'
LINEAGE='recovery-lineage.v01.json'


def read_generation(path):
    path=core.safe_path(path)
    if path.stat().st_size>qa.PARAMETERS['maximum_json_bytes']:
        raise core.Error('Generation receipt too large')
    data=json.loads(path.read_text(),object_pairs_hook=core.base.unique_object,
                    parse_float=core.base.finite_float,parse_constant=core.base.reject_constant)
    authorization=data.get('authorization')
    if not isinstance(authorization,dict) or set(authorization)!={'path','sha256'}:
        raise core.Error('Generation authorization must be a file reference')
    qa.same_reference(authorization)
    stage.director.safe_text(json.dumps({k:v for k,v in data.items() if k!='authorization'}))
    return data


def packet_view(packet):
    return {k:v for k,v in packet.items() if k not in ('inputs','request')}


def prepare(job,target,registry,audio_capability,*,historical_job=None,failure=None):
    historical=core.shared.directory(historical_job) if historical_job else HISTORICAL
    core.safe_path(historical/stage.REQUEST,under=stage.ROOT)
    job=core.new_directory(job,stage.ROOT)
    target=core.new_directory(target,stage.RENDER_ROOT)
    old=qa.read(historical/stage.REQUEST)
    brief=stage.ri.validate_brief(qa.read(historical/stage.BRIEF))
    packet=qa.read(historical/stage.PACKET)
    raw=(historical/'attempt.01/untrusted-response.v01.txt').read_text()
    proposal=stage.ri.check('proposal',qa.read(historical/'attempt.01'/stage.PROPOSAL))
    generation=read_generation(historical/'attempt.01'/stage.GENERATION)
    if (old['brief_sha256']!=core.digest_object(brief)
            or old['packet_sha256']!=stage.loop.validator.packet_digest(packet)
            or stage.director.parse_response(raw)!=proposal
            or generation['response_sha256']!=stage.director.digest_text(raw)
            or generation['proposal_sha256']!=core.digest_object(proposal)
            or generation['request']!=qa.ref(historical/stage.REQUEST)
            or generation['authorization']!=qa.ref(historical/'call.01.reserved.json')
            or not generation['live_inference_performed']
            or raw!=(historical/'call.01.raw.txt').read_text()
            or generation['prompt_sha256']!=stage.director.digest_text((historical/'attempt.01'/stage.PROMPT).read_text())):
        raise core.Error('Historical inference binding mismatch')
    if core.safe_path(old['target_output'],output=True).exists():raise core.Error('Historical preview output already exists')
    failure_ref=None
    if any(historical.glob('attempt.*/preview-*.json')):
        if historical!=stage.ROOT/'showcase-v4.v05' or not failure:raise core.Error('Historical preview already reserved')
        failure_ref=qa.ref(failure);diagnostic=qa.read(failure)
        if (diagnostic['status']!='FAILED_AFTER_ENCODE_NO_PUBLISHED_OUTPUT'
                or diagnostic['error']!='Dark-frame scan sample count mismatch'
                or diagnostic['request']!=qa.ref(historical/stage.REQUEST)
                or diagnostic['proposal']!=qa.ref(historical/'attempt.01'/stage.PROPOSAL)
                or diagnostic['execution']!=qa.ref(historical/'attempt.01'/stage.audio.SPEC)
                or diagnostic['permission']!=qa.ref(historical/'attempt.01'/stage.PERMIT)
                or diagnostic['consumed_permission']!=qa.ref(historical/'attempt.01/preview-consumed.v01.json')
                or diagnostic['output_directory']!=old['target_output']
                or diagnostic['source']!=qa.ref(stage.SOURCE)):
            raise core.Error('Bounded same-plan render recovery evidence mismatch')
        core.shared.write_json(stage.ROOT/'showcase-v4-same-plan-recovery.reserved.v01.json',{
            'failure':failure_ref,'historical_request':qa.ref(historical/stage.REQUEST),
            'recovery_job':core.shared.relative(job),'target':core.shared.relative(target),'maximum_additional_renders':1,
            'permission_origin':'explicit_user_session','permission_scope':'Complete authorized private Showcase V4 after evidenced scanner failure; same AI plan/spec; no ledger reset',
            'production_eligible':False,'publishing_eligible':False})
    stage.ri.refs_match(packet['inputs'])
    registry_data=stage.renderer.validate_registry(registry)
    stage.audio.validate_capability(audio_capability)
    # Generate fresh physical evidence, then compare all planning observations.
    av=core.av
    historical_report=qa.read(packet['inputs'][av.REPORT]['path'])
    job.mkdir(parents=True)
    av.generate(packet['request']['video'],packet['request']['metadata'],packet['request']['analysis'],
        job/'source-evidence.v01',director_input=historical_report['original_director_input']['path'])
    request={**packet['request'],'av_bundle':core.shared.relative(job/'source-evidence.v01'),
             'director_input':core.shared.relative(job/'source-evidence.v01'/av.ENRICHED)}
    current=core.intake.build_packet(**request)
    if packet_view(current)!=packet_view(packet):
        raise core.Error('Fresh source observations differ from historical planning context')
    parent=qa.read(brief['parent_plan']['path']);parent_spec=qa.read(brief['inputs']['spec']['path'])
    if 'visual_spec' in parent_spec:parent_spec=parent_spec['visual_spec']
    validation=stage.loop.validate_proposal(proposal,brief,packet,parent,parent_spec,registry_data)
    if validation['blocking_reasons'] or stage.visual_signature(parent)==stage.visual_signature(proposal['plan']):
        raise core.Error('Recovered plan independently blocked')
    spec=stage.audio.spec_for(proposal['plan'],proposal['audio_timeline'],proposal['operation_parameters'])
    if spec!=qa.read(historical/'attempt.01'/stage.audio.SPEC):
        raise core.Error('Recovered execution differs from historical AI execution')
    lineage={'contract_version':'stage59-recovery.v0.1','source':qa.ref(stage.SOURCE),
        'historical_directory':core.shared.relative(historical),'prior_render_failure':failure_ref,
        'historical':{core.shared.relative(p):qa.ref(p) for p in sorted(historical.rglob('*')) if p.is_file()},
        'current_packet':None,
        'code_receipts':stage.code_receipts(),'environment':core.environment(),
        'director_calls':0,'maximum_renders':1,'maximum_reviewer_calls':1,
        'production_eligible':False,'publishing_eligible':False}
    core.shared.write_json(job/'current-evidence-packet.v03.json',current)
    lineage['current_packet']=qa.ref(job/'current-evidence-packet.v03.json')
    core.shared.write_json(job/LINEAGE,lineage)
    recovered={**old,'mode':'recovered_historical_inference','code_receipts':stage.code_receipts(),
        'target_output':core.shared.relative(target),'renderer_capabilities':qa.ref(registry),
        'audio_capability':qa.ref(audio_capability),'recovery_lineage':qa.ref(job/LINEAGE)}
    for name in (stage.BRIEF,stage.PACKET,stage.PROMPT):
        core.base.write_exclusive(job/name,(historical/name).read_text())
    core.shared.write_json(job/stage.REQUEST,recovered)
    stage.director.publish(job/'attempt.01',{stage.PROPOSAL:proposal,stage.VALIDATION:validation,
        stage.GENERATION:generation,stage.audio.SPEC:spec,'untrusted-response.v01.txt':raw,
        stage.PROMPT:(historical/'attempt.01'/stage.PROMPT).read_text()})
    return job


def validate(job,request,packet):
    qa.same_reference(request['recovery_lineage'])
    lineage=qa.read(request['recovery_lineage']['path'])
    historical=core.shared.directory(lineage.get('historical_directory',HISTORICAL))
    core.safe_path(historical/stage.REQUEST,under=stage.ROOT)
    if lineage.get('prior_render_failure'):
        qa.same_reference(lineage['prior_render_failure'])
        reservation=qa.read(stage.ROOT/'showcase-v4-same-plan-recovery.reserved.v01.json')
        if reservation['failure']!=lineage['prior_render_failure'] or reservation['recovery_job']!=core.shared.relative(job):
            raise core.Error('Recovery reservation mismatch')
    if lineage['code_receipts']!=stage.code_receipts() or lineage['environment']!=core.environment():
        raise core.Error('Recovery current code/environment changed')
    stage.ri.refs_match(lineage['historical'])
    qa.same_reference(lineage['source']);qa.same_reference(lineage['current_packet'])
    current=core.intake.validate_packet(qa.read(lineage['current_packet']['path']))
    if packet!=qa.read(historical/stage.PACKET) or packet_view(current)!=packet_view(packet):
        raise core.Error('Recovery evidence context changed')
    for name in (stage.PROPOSAL,stage.GENERATION,'untrusted-response.v01.txt',stage.PROMPT,stage.audio.SPEC):
        if (job/'attempt.01'/name).read_bytes()!=(historical/'attempt.01'/name).read_bytes():
            raise core.Error('Recovered historical inference bytes changed')
    if len(stage.attempts(job))!=1:raise core.Error('Recovery cannot add Director attempts')
    stage.audio.validate_capability(request['audio_capability']['path'])


def cached_source(brief):
    """Validate cached model context against its own immutable request and packet."""
    reviewer=stage.quality.reviewer
    source_ref=brief['inputs']['response:original_source'];qa.same_reference(source_ref)
    root=core.safe_path(source_ref['path']).parent
    generation=qa.read(root/'review-generation-provenance.v01.json')
    qa.same_reference(generation['prepared_receipt'])
    prepared=core.safe_path(generation['prepared_receipt']['path']).parent
    receipt=qa.read(generation['prepared_receipt']['path'])
    packet_path=core.shared.directory(receipt['qa_bundle'])/qa.PACKET
    packet=qa.read(packet_path)
    if reviewer.digest(packet)!=receipt['packet_sha256'] or generation['packet_sha256']!=receipt['packet_sha256']:
        raise core.Error('Cached source packet binding mismatch')
    request=qa.read(prepared/reviewer.name('original_source'))
    expected=reviewer.make_request(packet,'original_source')
    expected['code_receipts']=receipt['code_receipts']
    if request!=expected:
        raise core.Error('Cached source request changed')
    if generation['responses']['original_source']!=source_ref:
        raise core.Error('Cached source response provenance mismatch')
    return reviewer.validate_response(qa.read(source_ref['path']),request,packet)
