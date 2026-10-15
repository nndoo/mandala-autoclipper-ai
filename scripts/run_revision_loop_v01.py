#!/usr/bin/env python3
"""Bounded Stage 5.7 CLI checkpoints; no service, production, or automatic retry."""
import argparse
import contextlib
import copy
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import time

import revision_intelligence_v01 as ri
import renderer_revision_v02 as audio

core=ri.core
qa=ri.qa
director=core.director
validator=director.validator
reviewer=ri.reviewer
BRIEF='revision-brief.v01.json'
PACKET=director.PACKET
REQUEST='revision-request.v01.json'
PROMPT='revision-director-request.v01.txt'
PROPOSAL='revised-editing-plan.v01.json'
VALIDATION='revision-validation.v01.json'
GENERATION='revision-generation-provenance.v01.json'
PERMISSION='preview-authorization.v01.json'
STATE_GLOB='checkpoint.*.json'
SHA='58fa3abcb7ebacfc162057fa946fc144961eebc0211d43e08ba6021b872e171f'


def state_files(job):return sorted(job.glob(STATE_GLOB))


def load_state(job):
    job=core.safe_path(Path(job)/REQUEST,under=ri.ROOT).parent
    files=state_files(job)
    if not files:raise core.Error('Revision history missing')
    prior=None;previous=None;request=qa.read(job/REQUEST)
    for sequence,path in enumerate(files,1):
        current=ri.check('state',qa.read(path))
        if path.name!=f'checkpoint.{sequence:03d}.json' or current['sequence']!=sequence or current['previous']!=prior:
            raise core.Error('Revision checkpoint chain changed')
        if len(current['submitted_plan_digests'])!=current['attempt_count'] or len(set(current['submitted_plan_digests']))!=current['attempt_count']:
            raise core.Error('Revision attempt accounting changed')
        if previous:
            if any(current['remaining_budget'][k]>previous['remaining_budget'][k] for k in current['remaining_budget']):raise core.Error('Revision budget increased without new workflow authorization')
            if current['submitted_plan_digests'][:previous['attempt_count']]!=previous['submitted_plan_digests']:raise core.Error('Revision attempt history changed')
        elif any(current['remaining_budget'][k]!=request['initial_'+k] for k in ('director_calls','reviewer_calls','renders')):
            raise core.Error('Initial revision budget differs from request')
        prior=qa.ref(path)
        previous=current
    ri.refs_match(current['artifacts'])
    return job,current


def checkpoint(job,state,*,status,reason,artifacts=None,attempts=None,digests=None,budget=None):
    sequence=state['sequence']+1 if state else 1
    item={'contract_version':ri.VERSION,'revision_id':state['revision_id'] if state else qa.read(job/BRIEF)['revision_id'],
        'sequence':sequence,'state':status,'reason':reason,'attempt_count':attempts if attempts is not None else state['attempt_count'] if state else 0,
        'submitted_plan_digests':digests if digests is not None else state['submitted_plan_digests'] if state else [],
        'remaining_budget':budget if budget is not None else state['remaining_budget'] if state else {'director_calls':1,'reviewer_calls':1,'renders':1,'processing_sec':1200},
        'artifacts':{**(state['artifacts'] if state else {}),**(artifacts or {})},
        'previous':qa.ref(job/f'checkpoint.{sequence-1:03d}.json') if state else None,'created_at':core.shared.now(),
        'human_review_pending':status!='ACCEPTED_FOR_PREVIEW','production_eligible':False,'publishing_eligible':False,
        'render_approved':False,'publish_approved':False}
    ri.check('state',item);core.shared.write_json(job/f'checkpoint.{sequence:03d}.json',item)
    return item


def load_job(job):
    job,state=load_state(job);request=qa.read(job/REQUEST);brief=ri.validate_brief(qa.read(job/BRIEF))
    if request['code_receipts']!=ri.code_receipts() or request['brief_sha256']!=core.digest_object(brief):
        raise core.Error('Revision request/code changed; new bundle required')
    packet=core.intake.validate_packet(qa.read(job/PACKET))
    if request['packet_sha256']!=validator.packet_digest(packet) or packet['source']!=brief['source']:
        raise core.Error('Revision packet identity mismatch')
    ri.refs_match(request['inputs'])
    if (job/PROMPT).read_text()!=make_prompt(brief,packet,qa.read(brief['parent_plan']['path']),
            qa.read(brief['renderer_capabilities']['path']),qa.read(brief['audio_capability']['path'])):
        raise core.Error('Revision prompt differs from bound inputs')
    return job,state,request,brief,packet


def model_schema():
    """Factor identical operation fields; preserve every parameter constraint."""
    schema=copy.deepcopy(ri.contracts()['$defs']['proposal'])
    operations=schema['properties']['plan']['properties']['variants']['items']['properties']['operations']
    branches=operations['items']['oneOf'];first=branches[0]
    common={k:v for k,v in first['properties'].items() if k not in ('kind','parameters')}
    if not all({k:v for k,v in branch['properties'].items() if k not in ('kind','parameters')}==common
        and branch['required']==first['required'] and branch.get('additionalProperties') is False for branch in branches):
        raise core.Error('Operation contract changed; model-schema factoring must be reviewed')
    operations['items']={'type':'object','additionalProperties':False,'required':first['required'],
        'properties':{**common,'kind':{},'parameters':{}},'allOf':[{'oneOf':[
            {'properties':{k:branch['properties'][k] for k in ('kind','parameters')},'required':['kind','parameters']}
            for branch in branches]}]}
    return schema


def make_prompt(brief,packet,parent,capabilities,audio_capability):
    # Keep complete evidence in referenced artifacts; avoid sending duplicate
    # input receipts and large proof/environment arrays in the model context.
    model_brief={k:brief[k] for k in ('revision_id','conflicts','required_reviews','expected_improvement_targets')}
    model_brief['issues']=[{'issue_id':issue['issue_id'],'category':issue['category'],'severity':issue['severity'],
        'provenance':issue['provenance'],'confidence':issue['confidence'],
        'output_range':issue['output_range'],'source_ranges':[[r['shot_id'],r['source_start_sec'],r['source_end_sec']] for r in issue['source_ranges']],
        'description':issue['description'],'recommended_change':issue['recommendation']['change'],
        'capability_requirements':issue['capability_requirements']} for issue in brief['issues']]
    model_packet={k:v for k,v in packet.items() if k not in ('inputs','request')}
    model_packet['evidence_ledger']={key:{k:entry[k] for k in ('start_sec','end_sec','timing_precision','basis')}
        for key,entry in packet['evidence_ledger'].items()}
    model_packet['correlation']=packet['correlation'][:4]
    model_packet['audio']=copy.deepcopy(packet['audio']);model_packet['audio']['selected_events']=packet['audio']['selected_events'][:4]
    model_packet['visual']=copy.deepcopy(packet['visual']);model_packet['visual']['selected_events']=packet['visual']['selected_events'][:6]
    model_packet['prompt_view_limitations']=['Artifact/pointer columns are omitted from ledger; exact IDs/times/basis retained',
        'First four selected correlations/audio events and six visual events shown; complete evidence remains in hash-bound packet',
        'Issue source_ranges triples mean [shot_id, source_start_sec, source_end_sec]',
        'Full brief limitations remain in the hash-bound brief; shared uncertainty/safety constraints are explicit in this prompt']
    model_parent=copy.deepcopy(parent)
    model_parent.pop('required_reviews',None)
    for variant in model_parent['variants']:
        variant.pop('required_reviews',None)
        for operation in variant['operations']:
            operation.pop('rationale',None);operation.pop('evidence_refs',None)
    bindings={k:brief[k] for k in ('revision_id','parent_plan','parent_render','qa_report')}
    bindings['brief_sha256']=core.digest_object(brief)
    summary={k:v['status'] for k,v in capabilities['operations'].items()}
    prompt=(core.base.ROOT/'openclaw/prompts/adaptive-director-revision-v01.md').read_text()
    for key in ('source_audio_metrics','ghosting_investigation'):
        if key in brief['inputs']:
            qa.same_reference(brief['inputs'][key]);evidence=qa.read(brief['inputs'][key]['path'])
            if evidence['source']!={k:packet['source'][k] for k in ('path','sha256')}:raise core.Error('Revision investigation source mismatch')
            if key=='ghosting_investigation':
                evidence={'reference':brief['inputs'][key],'sample_count':len(evidence['samples']),
                    'maximum_mean_absolute_pixel_delta_8bit':max(row['mean_absolute_pixel_delta_8bit'] for row in evidence['samples']),
                    'minimum_pixel_correlation':min(row['pixel_correlation'] for row in evidence['samples']),
                    'conclusion':'Mapped source/output samples are consistent; no added visual blend is declared; physical ghosting remains unverified',
                    'provenance':evidence['provenance'],'physical_ghosting_verified':False}
            prompt+='\n'+key.upper()+'='+json.dumps(evidence,separators=(',',':'))
    directive=None
    if 'creative_directive' in brief['inputs']:
        qa.same_reference(brief['inputs']['creative_directive'])
        directive=qa.read(brief['inputs']['creative_directive']['path'])
        if directive['source']!={k:packet['source'][k] for k in ('path','sha256')} or directive['parent_render']!=brief['parent_render']:
            raise core.Error('Creative directive source/parent contamination')
    prompt+='\nEVIDENCE_PACKET_SHA256='+validator.packet_digest(packet)
    for name,value in (('REVISION_BINDINGS',bindings),('INPUT_PACKET',model_packet),('PARENT_PLAN',model_parent),
        ('REVISION_BRIEF',model_brief),('CAPABILITY_SUMMARY',summary),
        ('AUDIO_CAPABILITY',{'status':audio_capability['status'],'capability':audio_capability['capability'],'limitations':audio_capability['limitations']}),
        ('OUTPUT_SCHEMA',model_schema())):
        prompt+='\n'+name+'='+json.dumps(value,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    if directive is not None:prompt+='\nCREATIVE_DIRECTIVE='+json.dumps(directive,separators=(',',':'),ensure_ascii=False)
    return director.safe_text(prompt,director.MAX_PROMPT_BYTES)


def prepare(report,audio_capability,output,target,revision_id):
    started=time.monotonic()
    output=core.new_directory(output,ri.ROOT);target=core.new_directory(target,ri.RENDER_ROOT)
    parent,ctx,extra=ri.load_parent(report)
    # Optional source-bound investigations are measured beforehand, never
    # fabricated or silently refreshed by the planner.
    for name in ('source-audio-metrics','ghosting-investigation'):
        path=ri.ROOT/'audit.v01'/(name+'.v01.json')
        if path.is_file():extra[name.replace('-','_')]=qa.ref(path)
    capability=audio.validate_capability(audio_capability)
    brief=ri.make_brief(revision_id,parent,ctx,qa.ref(report),qa.ref(audio_capability),extra)
    packet=ctx['director_packet']
    if packet is None:raise core.Error('Revision needs real canonical/source evidence')
    prompt=make_prompt(brief,packet,ctx['plan'],qa.read(brief['renderer_capabilities']['path']),capability)
    request={'contract_version':ri.VERSION,'mode':'prepared_no_inference','source':brief['source'],
        'brief_sha256':core.digest_object(brief),'packet_sha256':validator.packet_digest(packet),
        'prompt_sha256':director.digest_text(prompt),'inputs':brief['inputs'],'code_receipts':ri.code_receipts(),
        'target_output':core.shared.relative(target),'maximum_attempts':2,'initial_director_calls':1,
        'initial_reviewer_calls':1,'initial_renders':1,'cost':'UNKNOWN','live_inference_performed':False,
        'production_eligible':False,'publishing_eligible':False}
    director.publish(output,{BRIEF:brief,PACKET:packet,PROMPT:prompt,REQUEST:request})
    return checkpoint(output,None,status='WAITING_FOR_APPROVAL',reason='Offline request ready; paid inference and new private render require session authorization',
        artifacts={'brief':qa.ref(output/BRIEF),'request':qa.ref(output/REQUEST),'packet':qa.ref(output/PACKET),'prompt':qa.ref(output/PROMPT)},
        budget={'director_calls':1,'reviewer_calls':1,'renders':1,'processing_sec':max(0,1200-(time.monotonic()-started))})


def meaningful_changes(parent,proposal,parent_spec):
    changes=validator.differentiation(parent['variants'][0],proposal['plan']['variants'][0])
    if proposal['operation_parameters']!=parent_spec['operation_parameters']:changes.append('numeric_operation_parameters')
    if proposal['audio_timeline']['mode']=='continuous_source':changes.append('independent_continuous_source_soundtrack')
    return list(dict.fromkeys(changes))


def validate_proposal(proposal,brief,packet,parent,parent_spec,registry):
    blockers=[];plan=proposal.get('plan',{}) if isinstance(proposal,dict) else {}
    independent=validator.validate_plan(plan,packet)
    result={'contract_version':ri.VERSION,'proposal_sha256':core.digest_object(proposal),'parent_plan':brief['parent_plan'],
        'independent_plan_validation':independent,'preview_status':'BLOCKED','blocking_reasons':blockers,
        'required_capabilities':[],'actual_changes':[],'audio_mapping':None,'reviews':list(brief['required_reviews']),
        'production_eligible':False,'publishing_eligible':False,'render_approved':False,'publish_approved':False}
    if not independent['structural_validity'] or independent['blocking_findings']:blockers.append('independent_plan_validation_blocked')
    try:ri.check('proposal',proposal)
    except core.Error:blockers.append('revision_proposal_schema_invalid');return ri.check('validation',result)
    bindings={k:brief[k] for k in ('revision_id','parent_plan','parent_render','qa_report')}
    if any(proposal[k]!=v for k,v in bindings.items()) or proposal['brief_sha256']!=core.digest_object(brief):blockers.append('revision_lineage_mismatch')
    if len(plan['variants'])!=1:blockers.append('revision_requires_one_explicit_selected_variant')
    ids={i['issue_id'] for i in brief['issues']}
    if any(not change['issue_ids'] or set(change['issue_ids'])-ids for change in proposal['change_log']):blockers.append('change_log_ungrounded')
    if not proposal['change_log']:blockers.append('change_log_missing')
    if 'creative_directive' in brief['inputs']:
        qa.same_reference(brief['inputs']['creative_directive'])
        directive=qa.read(brief['inputs']['creative_directive']['path'])
        decisions=proposal.get('creative_decisions')
        if not decisions:blockers.append('creative_decisions_missing')
        else:
            evaluation=decisions['text_evaluation']
            if set(evaluation['evidence_refs'])-set(packet['evidence_ledger']):blockers.append('creative_text_evaluation_ungrounded')
            overlays=[o for o in plan['variants'][0]['operations'] if o['kind']=='overlay' and o['parameters']['caption']['text']]
            if (evaluation['needed'] or directive.get('require_visible_overlay')) and not overlays:blockers.append('creative_overlay_required')
            for op in overlays:
                extra=proposal['operation_parameters'].get(op['operation_id'],{})
                if not {'text_style','text_animation','font_size_px'}.issubset(extra):blockers.append('creative_text_treatment_not_decided')
            if directive.get('require_subject_reframe') and not any(o['kind'] in ('crop','zoom') for o in plan['variants'][0]['operations']):
                blockers.append('requested_subject_reframe_missing')
            active_text=[]
            for op in plan['variants'][0]['operations']:
                if op['kind'] in ('overlay','subtitle'):active_text.append(op)
                elif op['kind'] in ('crop','zoom') and any(
                        max(op['output_start_sec'],prior['output_start_sec'])<min(op['output_end_sec'],prior['output_end_sec'])
                        for prior in active_text):blockers.append('visual_reframe_after_text')
    sound=proposal['audio_timeline'];refs=sound['evidence_refs']
    if set(refs)-set(packet['evidence_ledger']):blockers.append('soundtrack_evidence_unknown')
    if sound['selection_basis']!='model_candidate':blockers.append('model_cannot_claim_fixture_or_human_passage_review')
    if sound['mode']=='continuous_source':
        if packet['speech']['requirements']['overall_requirement']!='not_required':blockers.append('speech_audio_replacement_requires_separate_context_review')
        if not refs:blockers.append('soundtrack_passage_evidence_missing')
    if not blockers:
        try:
            spec=audio.spec_for(plan,sound,proposal['operation_parameters'])
            timeline=audio.compile_timeline(plan,spec)
            audio.validate_source_audio(core.safe_path(plan['source']['path']),plan,spec)
            result['required_capabilities']=timeline['required_capabilities'];result['audio_mapping']=timeline['audio_timeline']
            for cap in timeline['required_capabilities']:
                if cap=='continuous_source_audio':continue  # Separate replay-verified extension receipt.
                if registry['operations'].get(cap,{}).get('status')!='verified':blockers.append('capability_unverified:'+cap)
            result['actual_changes']=meaningful_changes(parent,proposal,parent_spec)
            if not result['actual_changes']:blockers.append('no_meaningful_revision')
        except (core.Error,KeyError,ValueError,TypeError):blockers.append('execution_or_audio_mapping_invalid')
    result['reviews']+=proposal['required_reviews']+proposal['unresolved_risks']
    if not blockers:result['preview_status']='NEEDS_SOURCE_BOUND_PREVIEW_PERMISSION'
    return ri.check('validation',result)


def allowed_next(state,action):
    if state['remaining_budget']['processing_sec']<=0:return 'RESOURCE_BUDGET_EXHAUSTED'
    if action=='plan':
        if state['attempt_count']>=2:return 'MAXIMUM_ATTEMPTS_EXHAUSTED'
        if state['state'] not in ('WAITING_FOR_APPROVAL','PLAN_REJECTED','REVISE') and not (state['state']=='PERMISSION_BLOCKED' and 'proposal' not in state['artifacts']):return 'NO_ACTIONABLE_PLANNING_TRANSITION'
        if state['state']=='REVISE' and 'comparison' not in state['artifacts']:return 'NO_ACTIONABLE_CORRECTION'
    elif action=='render':
        if state['state']!='READY_FOR_PREVIEW' and not (state['state']=='PERMISSION_BLOCKED' and 'proposal' in state['artifacts'] and 'render_manifest' not in state['artifacts']):return 'PLAN_NOT_READY_FOR_PRIVATE_PREVIEW'
    elif action=='qa':
        if state['state']!='RENDERED' and not (state['state']=='PERMISSION_BLOCKED' and 'technical_qa' in state['artifacts']):return 'NO_NEW_RENDER_TO_REVIEW'
    return None


def consume(state,key):
    budget=copy.deepcopy(state['remaining_budget'])
    if budget[key]<=0:raise core.Error('Revision budget exhausted: '+key)
    budget[key]-=1
    return budget


def lineage_records(brief):
    directory=ri.ROOT/'lineages'/brief['parent_render']['sha256']
    guard=directory/'attempt.01.json'
    core.safe_path(guard,output=not guard.exists(),under=ri.ROOT)
    records=[]
    for index,path in enumerate(sorted(directory.glob('attempt.*.json')),1):
        data=qa.read(path)
        if path.name!=f'attempt.{index:02d}.json' or data['parent_render']!=brief['parent_render'] or data['source_sha256']!=brief['source']['sha256']:
            raise core.Error('Baseline revision lineage changed')
        records.append((path,data))
    if len(records)>2:raise core.Error('Baseline revision attempt limit exceeded')
    return directory,records


def reserve_attempt(job,brief,digest):
    directory,records=lineage_records(brief)
    if len(records)>=2:raise core.Error('Maximum two distinct proposals per baseline')
    if any(data['plan_sha256']==digest for _,data in records):raise core.Error('Same rejected plan cannot be retried')
    directory.mkdir(parents=True,exist_ok=True);path=directory/f'attempt.{len(records)+1:02d}.json'
    core.shared.write_json(path,{'contract_version':ri.VERSION,'parent_render':brief['parent_render'],
        'source_sha256':brief['source']['sha256'],'plan_sha256':digest,'job':core.shared.relative(job),
        'maximum_attempts':2,'production_eligible':False,'publishing_eligible':False})
    return qa.ref(path)


def correction_prompt(job,state):
    prompt=(job/PROMPT).read_text()
    if state['attempt_count']:
        key='comparison' if state['state']=='REVISE' else 'validation'
        reference=state['artifacts'].get(key)
        if not reference:raise core.Error('Second revision lacks actionable correction evidence')
        qa.same_reference(reference);correction=qa.read(reference['path'])
        if key=='validation' and not correction['blocking_reasons']:raise core.Error('Second attempt lacks rejected-plan correction')
        if key=='comparison' and not correction['new_issues']:raise core.Error('Second attempt lacks new actionable issues')
        prompt+='\nPRIOR_ATTEMPT_CORRECTION='+json.dumps({'reference':reference,'content':correction},separators=(',',':'))
    return director.safe_text(prompt,director.MAX_PROMPT_BYTES)


def inference_permit(job,state,kind,permission_text):
    if not permission_text:raise core.Error('Paid inference lacks explicit session authorization')
    name=f'{kind}-inference-authorization.{state["sequence"]+1:03d}.json'
    permit={'contract_version':ri.VERSION,'kind':kind,'permission_origin':'explicit_user_session',
        'permission_text':director.safe_text(permission_text,2000),'revision_request':qa.ref(job/REQUEST),
        'source':qa.read(job/BRIEF)['source'],'maximum_calls':1,'automatic_retries':0,
        'production_eligible':False,'publishing_eligible':False}
    core.shared.write_json(job/name,permit)
    return qa.ref(job/name)


def submit(job,*,response_file=None,permission_text=None):
    started=time.monotonic()
    job,state,request,brief,packet=load_job(job)
    reason=allowed_next(state,'plan')
    if reason:return checkpoint(job,state,status='BLOCKED',reason=reason)
    if len(lineage_records(brief)[1])>=2:return checkpoint(job,state,status='BLOCKED',reason='BASELINE_MAXIMUM_ATTEMPTS_EXHAUSTED')
    live=response_file is None;effective_prompt=correction_prompt(job,state)
    if live and not permission_text:return checkpoint(job,state,status='PERMISSION_BLOCKED',reason='Director inference authorization missing')
    if live:
        if state['remaining_budget']['director_calls']<=0:return checkpoint(job,state,status='BLOCKED',reason='DIRECTOR_BUDGET_EXHAUSTED')
        authorization=inference_permit(job,state,'director',permission_text)
        state=checkpoint(job,state,status='PREPARED',reason='Single Director invocation reserved; no retry',
            artifacts={'director_permission':authorization},budget=consume(state,'director_calls'))
    iteration=job/f'attempt.{state["attempt_count"]+1:02d}'
    core.shared.directory(iteration,new=True)
    try:
        raw=director.live_response(effective_prompt,approved=True) if live else director.safe_text(core.safe_path(response_file).read_text())
        proposal=director.parse_response(raw)
        if not isinstance(proposal.get('plan'),dict):raise core.Error('Revised plan payload missing')
        digest=core.digest_object({k:proposal.get(k) for k in ('plan','audio_timeline','operation_parameters')})
        if digest in state['submitted_plan_digests']:
            return checkpoint(job,state,status='BLOCKED',reason='REPEATED_PLAN_NO_RETRY')
        marker=reserve_attempt(job,brief,digest)
        state=checkpoint(job,state,status='PLAN_GENERATED',reason='Distinct proposal submitted for independent validation',
            attempts=state['attempt_count']+1,digests=state['submitted_plan_digests']+[digest],artifacts={'baseline_attempt':marker})
        parent=qa.read(brief['parent_plan']['path']);parent_spec=qa.read(brief['inputs']['spec']['path'])
        registry=qa.read(brief['renderer_capabilities']['path'])
        audio.validate_capability(brief['audio_capability']['path'])
        validation=validate_proposal(proposal,brief,packet,parent,parent_spec,registry)
        envelope=director.strict_json(raw)
        generation={'contract_version':ri.VERSION,'mode':'live_model_inference' if live else 'offline_fixture',
            'revision_request':qa.ref(job/REQUEST),'parent_plan':brief['parent_plan'],'parent_render':brief['parent_render'],
            'source':brief['source'],'response_sha256':director.digest_text(raw),'proposal_sha256':core.digest_object(proposal),
            'prompt_sha256':director.digest_text(effective_prompt),
            'code_receipts':ri.code_receipts(),'observed_model':{k:envelope.get(k) for k in ('provider','model','transport')} if live else None,
            'wrapper_invocations':1 if live else 0,'automatic_retries':0,'live_inference_performed':live,
            'production_eligible':False,'publishing_eligible':False}
        artifacts={'untrusted-response.v01.txt':raw,'director-request.v01.txt':effective_prompt,PROPOSAL:proposal,VALIDATION:validation,GENERATION:generation,PACKET:packet}
        if validation['independent_plan_validation']['structural_validity']:
            artifacts[audio.PLAN]=proposal['plan']
        if not validation['blocking_reasons']:
            artifacts[audio.SPEC]=audio.spec_for(proposal['plan'],proposal['audio_timeline'],proposal['operation_parameters'])
        ri.refs_match(brief['inputs']);director.publish(iteration,artifacts)
        budget=copy.deepcopy(state['remaining_budget']);budget['processing_sec']=max(0,budget['processing_sec']-(time.monotonic()-started))
        return checkpoint(job,state,status='PLAN_REJECTED' if validation['blocking_reasons'] else 'READY_FOR_PREVIEW',
            reason='Independent validation blocked: '+','.join(validation['blocking_reasons']) if validation['blocking_reasons'] else 'No structural blockers; private preview permission still required; production gates false',
            artifacts={'proposal':qa.ref(iteration/PROPOSAL),'validation':qa.ref(iteration/VALIDATION),'generation':qa.ref(iteration/GENERATION)},budget=budget)
    except (core.Error,OSError,ValueError,TypeError,KeyError,RecursionError):
        budget=copy.deepcopy(state['remaining_budget']);budget['processing_sec']=max(0,budget['processing_sec']-(time.monotonic()-started))
        return checkpoint(job,state,status='INFERENCE_UNAVAILABLE' if live and state['state']=='PREPARED' else 'PLANNING_FAILED',
            reason='Planning/provenance/response failure; no fabricated plan or automatic retry',budget=budget)


def validate_iteration(job,state,brief,packet):
    proposal_path=core.safe_path(state['artifacts']['proposal']['path']);bundle=proposal_path.parent
    proposal=ri.check('proposal',qa.read(proposal_path));validation=ri.check('validation',qa.read(bundle/VALIDATION))
    generation=qa.read(bundle/GENERATION);spec=ri.check('execution',qa.read(bundle/audio.SPEC))
    if generation['code_receipts']!=ri.code_receipts() or generation['proposal_sha256']!=core.digest_object(proposal):raise core.Error('Proposal generation code/identity mismatch')
    raw=director.safe_text((bundle/'untrusted-response.v01.txt').read_text())
    if director.digest_text(raw)!=generation['response_sha256'] or director.parse_response(raw)!=proposal:raise core.Error('Proposal is not unchanged generated response')
    if director.digest_text((bundle/'director-request.v01.txt').read_text())!=generation['prompt_sha256']:raise core.Error('Director revision prompt receipt mismatch')
    if spec!=audio.spec_for(proposal['plan'],proposal['audio_timeline'],proposal['operation_parameters']):raise core.Error('Revision execution spec changed')
    audio.validate_capability(brief['audio_capability']['path'])
    registry=qa.read(brief['renderer_capabilities']['path'])
    replay=validate_proposal(proposal,brief,packet,qa.read(brief['parent_plan']['path']),qa.read(brief['inputs']['spec']['path']),registry)
    if validation!=replay or validation['blocking_reasons']:raise core.Error('Revised plan remains blocked or validation changed')
    return bundle,proposal,spec,validation,generation


def authorize_preview(job,permission_text):
    job,state,request,brief,packet=load_job(job)
    if allowed_next(state,'render') or not permission_text:raise core.Error('New private preview authorization unavailable')
    bundle,proposal,spec,validation,generation=validate_iteration(job,state,brief,packet)
    if generation['mode']!='live_model_inference' or generation['live_inference_performed'] is not True:
        raise core.Error('Offline or replayed model proposal cannot authorize a real-content revision')
    if brief['source']['sha256']!=SHA or brief['source']['path']!='data/test-videos/cinematic-7693770515172887829.mp4':
        raise core.Error('Only the explicitly scoped original Showcase may receive real preview permission')
    target=core.new_directory(request['target_output'],ri.RENDER_ROOT)
    permit={'contract_version':ri.VERSION,'mode':'STAGE57_PRIVATE_PREVIEW','revision_id':brief['revision_id'],
        'source':{k:brief['source'][k] for k in ('path','sha256')},'parent_render':brief['parent_render'],
        'proposal':qa.ref(bundle/PROPOSAL),'plan_sha256':core.digest_object(proposal['plan']),
        'execution_sha256':core.digest_object(spec),'validation':qa.ref(bundle/VALIDATION),
        'renderer_capabilities':brief['renderer_capabilities'],'audio_capability':brief['audio_capability'],
        'output_directory':core.shared.relative(target),'maximum_renders':1,'permission_origin':'explicit_user_session',
        'permission_text':director.safe_text(permission_text,2000),'acknowledged_reviews':validation['reviews'],
        'local_preview_authorized':True,'production_eligible':False,'publishing_eligible':False,'render_approved':False,'publish_approved':False}
    ri.check('permit',permit);core.shared.write_json(bundle/PERMISSION,permit)
    return checkpoint(job,state,status='READY_FOR_PREVIEW',reason='New source/plan/output-bound private preview permission recorded',
        artifacts={'preview_permission':qa.ref(bundle/PERMISSION)})


def validate_permission(context,plan,spec,source):
    job,state,request,brief,packet=load_job(context['job'])
    if 'preview_permission' not in state['artifacts']:raise core.Error('Private preview permission missing')
    qa.same_reference(state['artifacts']['preview_permission']);permit=ri.check('permit',qa.read(state['artifacts']['preview_permission']['path']))
    bundle,proposal,expected,validation,generation=validate_iteration(job,state,brief,packet)
    if generation['mode']!='live_model_inference' or plan!=proposal['plan'] or spec!=expected:raise core.Error('Preview must use exact new live proposal')
    if (permit['source']!={k:plan['source'][k] for k in ('path','sha256')} or permit['source']['sha256']!=SHA
        or core.safe_path(source)!=core.safe_path(permit['source']['path']) or permit['parent_render']!=brief['parent_render']
        or permit['proposal']!=qa.ref(bundle/PROPOSAL) or permit['plan_sha256']!=core.digest_object(plan)
        or permit['execution_sha256']!=core.digest_object(spec) or permit['validation']!=qa.ref(bundle/VALIDATION)
        or permit['renderer_capabilities']!=brief['renderer_capabilities'] or permit['audio_capability']!=brief['audio_capability']
        or permit['output_directory']!=request['target_output'] or permit['acknowledged_reviews']!=validation['reviews']):
        raise core.Error('Private preview permission identity mismatch')
    core.new_directory(permit['output_directory'],ri.RENDER_ROOT)
    return job,state,permit,bundle,packet


def render_admission(context,plan,spec,source):
    job,state,permit,bundle,packet=validate_permission(context,plan,spec,source)
    marker=bundle/'preview-consumed.v01.json'
    core.shared.write_json(marker,{'contract_version':ri.VERSION,'permission':qa.ref(bundle/PERMISSION),
        'plan_sha256':core.digest_object(plan),'started_at':core.shared.now(),'maximum_renders':1,
        'production_eligible':False,'publishing_eligible':False})


def render_preview(job):
    started=time.monotonic()
    job,state,request,brief,packet=load_job(job)
    reason=allowed_next(state,'render')
    if reason:return checkpoint(job,state,status='BLOCKED',reason=reason)
    if 'preview_permission' not in state['artifacts']:
        return checkpoint(job,state,status='PERMISSION_BLOCKED',reason='New source-bound real-content render permission missing')
    if state['remaining_budget']['renders']<=0:return checkpoint(job,state,status='BLOCKED',reason='RENDER_BUDGET_EXHAUSTED')
    bundle,proposal,spec,validation,generation=validate_iteration(job,state,brief,packet)
    validate_permission({'job':job},proposal['plan'],spec,core.safe_path(brief['source']['path']))
    state=checkpoint(job,state,status='READY_FOR_PREVIEW',reason='Render budget reserved before encoding',budget=consume(state,'renders'))
    try:
        target=core.new_directory(request['target_output'],ri.RENDER_ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        with __import__('render_video_v01').render_lock(),tempfile.TemporaryDirectory(dir=target.parent,prefix='.revision-work-') as temporary:
            work=Path(temporary);source=core.safe_path(brief['source']['path'])
            video,timeline,verified,mapping,execution=audio.encode(source,proposal['plan'],spec,work,
                mode='STAGE57_PRIVATE_PREVIEW',context={'job':job})
            from render_showcase_preview_v01 import black_scan
            verified['black_frame_scan']=black_scan(video,timeline,spec['visual_spec']['resources'])
            ri.refs_match(brief['inputs'])
            manifest={'contract_version':audio.VERSION,'mode':'STAGE57_PRIVATE_PREVIEW','revision_id':brief['revision_id'],
                'source':brief['source'],'parent_render':brief['parent_render'],'parent_plan':brief['parent_plan'],
                'proposal':qa.ref(bundle/PROPOSAL),'validation':qa.ref(bundle/VALIDATION),'generation':qa.ref(bundle/GENERATION),
                'permission':qa.ref(bundle/PERMISSION),'consumed_permission':qa.ref(bundle/'preview-consumed.v01.json'),
                'plan_sha256':core.digest_object(proposal['plan']),'execution_sha256':core.digest_object(spec),
                'evidence_inputs':packet['inputs'],'renderer_capabilities':brief['renderer_capabilities'],
                'audio_capability':brief['audio_capability'],'code_receipts':ri.code_receipts(),'environment':core.environment(),
                'timeline':timeline,'verification':verified,'audio_mapping_verification':mapping,'execution':execution,
                'output':{**verified['metadata'],'path':core.shared.relative(target/'preview-v2.mp4'),
                    'sha256':core.intake.gate.sha256_file(video),'bytes':video.stat().st_size},
                'production_eligible':False,'publishing_eligible':False,'render_approved':False,'publish_approved':False,
                'human_review':'PENDING','labels':['PREVIEW_ONLY','NOT_APPROVED_FOR_PUBLICATION']}
            ri.check('manifest',manifest)
            audio.publish(target,{'preview-v2.mp4':video},{audio.PLAN:proposal['plan'],audio.SPEC:spec,
                PACKET:packet,audio.TIMELINE:timeline,audio.MANIFEST:manifest},ri.RENDER_ROOT)
        budget=copy.deepcopy(state['remaining_budget']);budget['processing_sec']=max(0,budget['processing_sec']-(time.monotonic()-started))
        return checkpoint(job,state,status='RENDERED',reason='New private MP4 decoded/verified; human review pending',
            artifacts={'render_manifest':qa.ref(target/audio.MANIFEST),'rendered_output':qa.ref(target/'preview-v2.mp4')},budget=budget)
    except (core.Error,OSError,ValueError,TypeError,KeyError):
        budget=copy.deepcopy(state['remaining_budget']);budget['processing_sec']=max(0,budget['processing_sec']-(time.monotonic()-started))
        return checkpoint(job,state,status='RENDER_FAILED',reason='Encoding/verification failed; reservation retained; no retry',budget=budget)


def qa_preview(job,permission_text=None,feedback=None):
    started=time.monotonic()
    job,state,request,brief,packet=load_job(job)
    reason=allowed_next(state,'qa')
    if reason:return checkpoint(job,state,status='BLOCKED',reason=reason)
    from revision_quality_v01 import evaluate,verify_bundle,live_review,compare
    root=job/f'qa.{state["attempt_count"]:02d}'
    try:
        if 'technical_qa' in state['artifacts']:
            report=qa.validate_report(qa.read(state['artifacts']['technical_qa']['path']))
            ctx=verify_bundle(core.safe_path(state['artifacts']['render_manifest']['path']).parent)
            if report['rendered_output']!=ctx['inputs']['rendered_output'] or qa.read(root/qa.PACKET)!=qa.packet_for(report,ctx):raise core.Error('Pending QA context changed')
        else:
            report,ctx=evaluate(core.safe_path(state['artifacts']['render_manifest']['path']).parent,feedback=feedback)
            artifacts={qa.REPORT:report,qa.TECH:report['technical']}
            if ctx and report['integrity']['status']=='PASS':artifacts[qa.PACKET]=qa.packet_for(report,ctx)
            director.publish(root,artifacts)
            state=checkpoint(job,state,status='RENDERED',reason='Independent technical QA persisted; fresh AI and human review may remain pending',
                artifacts={'technical_qa':qa.ref(root/qa.REPORT)})
        if report['integrity']['status']!='PASS':return checkpoint(job,state,status='QA_FAILED',reason='Technical QA blocked')
        report_path=root/qa.REPORT
        if permission_text:
            if state['remaining_budget']['reviewer_calls']<=0:return checkpoint(job,state,status='BLOCKED',reason='REVIEWER_BUDGET_EXHAUSTED')
            authorization=inference_permit(job,state,'reviewer',permission_text)
            state=checkpoint(job,state,status='RENDERED',reason='Single V2 Reviewer call reserved; no automatic retry',
                artifacts={'reviewer_permission':authorization},budget=consume(state,'reviewer_calls'))
            report,report_path=live_review(root,report,ctx,brief)
        else:
            return checkpoint(job,state,status='PERMISSION_BLOCKED',reason='Technical QA complete; fresh V2 Reviewer authorization pending')
        comparison=compare(qa.read(brief['qa_report']['path']),report,brief['qa_report'],qa.ref(report_path),qa.read(brief['parent_plan']['path']),ctx['plan'],ctx['spec'])
        comparison_path=job/f'comparison.{state["attempt_count"]:02d}.json';core.shared.write_json(comparison_path,comparison)
        status=comparison['decision']
        budget=copy.deepcopy(state['remaining_budget']);budget['processing_sec']=max(0,budget['processing_sec']-(time.monotonic()-started))
        return checkpoint(job,state,status=status,reason='Independent V1/V2 comparison; musical quality and human review are explicit',
            artifacts={'new_qa':qa.ref(report_path),'comparison':qa.ref(comparison_path)},budget=budget)
    except (core.Error,OSError,ValueError,TypeError,KeyError):
        budget=copy.deepcopy(state['remaining_budget']);budget['processing_sec']=max(0,budget['processing_sec']-(time.monotonic()-started))
        return checkpoint(job,state,status='QA_FAILED',reason='Technical/model QA failure; no fabricated review or retry',budget=budget)


def advance(job,*,director_permission=None,preview_permission=None,reviewer_permission=None):
    """Run authorized transitions, stopping on failure, review or missing budget."""
    for _ in range(2):
        _,state=load_state(job)
        if state['state'] in ('WAITING_FOR_APPROVAL','PLAN_REJECTED','REVISE'):
            if state['state']=='REVISE' and any(state['remaining_budget'][k]<=0 for k in ('director_calls','renders','reviewer_calls')):
                return state
            if not director_permission:return state
            state=submit(job,permission_text=director_permission)
            if state['state']=='PLAN_REJECTED' and state['remaining_budget']['director_calls']>0:continue
        if state['state']=='READY_FOR_PREVIEW':
            if 'preview_permission' not in state['artifacts']:
                if not preview_permission:return state
                state=authorize_preview(job,preview_permission)
            state=render_preview(job)
        if state['state']=='RENDERED':state=qa_preview(job,reviewer_permission)
        return state
    return load_state(job)[1]


@contextlib.contextmanager
def revision_lock():
    ri.ROOT.mkdir(parents=True,exist_ok=True);candidate=ri.ROOT/'.loop.lock'
    path=core.safe_path(candidate,output=not candidate.exists())
    with path.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise core.Error('Another bounded revision command is active') from None
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='action',required=True)
    p=commands.add_parser('prepare')
    for name in ('qa-report','audio-capability','output','target','revision-id'):p.add_argument('--'+name,required=True)
    p=commands.add_parser('plan');p.add_argument('--job',required=True);p.add_argument('--response-file');p.add_argument('--permission-text')
    p=commands.add_parser('authorize-preview');p.add_argument('--job',required=True);p.add_argument('--permission-text',required=True)
    p=commands.add_parser('render');p.add_argument('--job',required=True)
    p=commands.add_parser('qa');p.add_argument('--job',required=True);p.add_argument('--permission-text');p.add_argument('--feedback')
    p=commands.add_parser('status');p.add_argument('--job',required=True)
    p=commands.add_parser('advance');p.add_argument('--job',required=True)
    for role in ('director','preview','reviewer'):p.add_argument('--'+role+'-permission')
    args=parser.parse_args(argv)
    try:
        seconds=600 if args.action=='prepare' else min(600,max(.01,load_state(args.job)[1]['remaining_budget']['processing_sec']))
        with revision_lock(),core.intake.processing_deadline(seconds):
            if args.action=='prepare':state=prepare(args.qa_report,args.audio_capability,args.output,args.target,args.revision_id)
            elif args.action=='plan':state=submit(args.job,response_file=args.response_file,permission_text=args.permission_text)
            elif args.action=='authorize-preview':state=authorize_preview(args.job,args.permission_text)
            elif args.action=='render':state=render_preview(args.job)
            elif args.action=='qa':state=qa_preview(args.job,args.permission_text,args.feedback)
            elif args.action=='advance':state=advance(args.job,director_permission=args.director_permission,
                preview_permission=args.preview_permission,reviewer_permission=args.reviewer_permission)
            else:_,state=load_state(args.job)
        print(json.dumps({k:state[k] for k in ('state','reason','attempt_count','remaining_budget','human_review_pending','production_eligible','publishing_eligible')}))
        return 0 if state['state'] in ('PREPARED','READY_FOR_PREVIEW','RENDERED','QA_COMPLETED','ACCEPTED_FOR_PREVIEW') else 20
    except (core.Error,OSError,ValueError,TypeError,KeyError,RecursionError):
        print('BLOCKED: revision integrity, resource or authorization policy failure; raw diagnostics suppressed',file=sys.stderr);return 1


if __name__=='__main__':
    with core.intake.processing_deadline(600):raise SystemExit(main())
