"""Stage 5.7 admission adapter for the existing independent Stage 5.6 QA/Reviewer."""
import copy
import math
from pathlib import Path
import time

import numpy as np
import revision_intelligence_v01 as ri
import renderer_revision_v02 as audio

core=ri.core
qa=ri.qa
reviewer=ri.reviewer


def verify_bundle(value):
    """Verify new preview contract without weakening/relabeling legacy receipts."""
    candidate=core.shared.directory(value)
    if candidate.is_relative_to(core.base.ROOT/'data/render-tests/stage59'):
        from run_stage59_showcase_v01 import verify_bundle as verify_stage59
        return verify_stage59(candidate)
    bundle=core.shared.directory(value);core.safe_path(bundle/audio.MANIFEST,under=ri.RENDER_ROOT)
    manifest=ri.check('manifest',qa.read(bundle/audio.MANIFEST))
    if manifest.get('contract_version')!=audio.VERSION or manifest.get('mode')!='STAGE57_PRIVATE_PREVIEW':
        raise core.Error('Revision QA requires new private-preview manifest')
    if manifest['code_receipts']!=ri.code_receipts() or manifest['environment']!=core.environment():
        raise core.Error('Revision QA stale code/environment')
    ri.refs_match({str(i):r for i,r in enumerate(manifest['code_receipts'])})
    if any(manifest.get(k) is not False for k in ('production_eligible','publishing_eligible','render_approved','publish_approved')):
        raise core.Error('Revision manifest cannot authorize production')
    references={k:manifest[k] for k in ('proposal','validation','generation','permission','consumed_permission','renderer_capabilities','audio_capability')}
    ri.refs_match(references);proposal=ri.check('proposal',qa.read(manifest['proposal']['path']))
    validation=ri.check('validation',qa.read(manifest['validation']['path']))
    generation=qa.read(manifest['generation']['path']);permit=ri.check('permit',qa.read(manifest['permission']['path']))
    consumed=qa.read(manifest['consumed_permission']['path'])
    raw_path=core.safe_path(manifest['generation']['path']).parent/'untrusted-response.v01.txt'
    raw=core.director.safe_text(raw_path.read_text())
    if generation['mode']!='live_model_inference' or generation['code_receipts']!=ri.code_receipts() or generation['response_sha256']!=core.director.digest_text(raw) or core.director.parse_response(raw)!=proposal:
        raise core.Error('Revision QA proposal is not unchanged live response')
    plan=qa.read(bundle/audio.PLAN);spec=ri.check('execution',qa.read(bundle/audio.SPEC));timeline=qa.read(bundle/audio.TIMELINE)
    packet=core.intake.validate_packet(qa.read(bundle/core.director.PACKET))
    independent=core.director.validator.validate_plan(plan,packet)
    if independent['blocking_findings'] or not independent['structural_validity'] or validation['independent_plan_validation']!=independent or validation['blocking_reasons']:
        raise core.Error('Revision QA plan validation blocked')
    if (plan!=proposal['plan'] or spec!=audio.spec_for(plan,proposal['audio_timeline'],proposal['operation_parameters'])
        or manifest['source']!=plan['source'] or manifest['parent_plan']!=proposal['parent_plan'] or manifest['parent_render']!=proposal['parent_render']
        or manifest['plan_sha256']!=core.digest_object(plan) or manifest['execution_sha256']!=core.digest_object(spec)
        or validation['proposal_sha256']!=core.digest_object(proposal) or generation['proposal_sha256']!=core.digest_object(proposal)
        or timeline!=audio.compile_timeline(plan,spec) or manifest['timeline']!=timeline or manifest['evidence_inputs']!=packet['inputs']):
        raise core.Error('Revision QA plan/spec/timeline/provenance mismatch')
    if (permit['source']!={k:plan['source'][k] for k in ('path','sha256')} or permit['parent_render']!=manifest['parent_render']
        or permit['proposal']!=manifest['proposal'] or permit['validation']!=manifest['validation']
        or permit['plan_sha256']!=manifest['plan_sha256'] or permit['execution_sha256']!=manifest['execution_sha256']
        or permit['output_directory']!=core.shared.relative(bundle) or permit['acknowledged_reviews']!=validation['reviews']
        or permit['renderer_capabilities']!=manifest['renderer_capabilities'] or permit['audio_capability']!=manifest['audio_capability']
        or consumed['permission']!=manifest['permission'] or consumed['plan_sha256']!=manifest['plan_sha256']):
        raise core.Error('Revision QA private permission binding mismatch')
    from run_revision_loop_v01 import SHA
    if plan['source']['sha256']!=SHA or permit['source']['path']!='data/test-videos/cinematic-7693770515172887829.mp4':
        raise core.Error('Revision QA source outside Showcase permission')
    source=core.safe_path(plan['source']['path']);output=core.safe_path(manifest['output']['path'],under=bundle)
    if output!=bundle/'preview-v2.mp4':raise core.Error('Revision QA output substituted')
    qa.same_reference({k:plan['source'][k] for k in ('path','sha256')});qa.same_reference({k:manifest['output'][k] for k in ('path','sha256')})
    if manifest['output']['bytes']!=output.stat().st_size:raise core.Error('Revision QA output bytes changed')
    ri.refs_match(packet['inputs']);info=audio.validate_source_audio(source,plan,spec)
    verified=core.verify_output(output,timeline,True,spec['visual_spec']['resources'])
    if any(manifest['verification'].get(k)!=v for k,v in verified.items()) or any(manifest['output'].get(k)!=v for k,v in verified['metadata'].items()):
        raise core.Error('Revision QA decode/output metadata mismatch')
    from render_showcase_preview_v01 import black_scan
    if manifest['verification']['black_frame_scan']!=black_scan(output,timeline,spec['visual_spec']['resources']):raise core.Error('Revision QA dark-frame scan mismatch')
    if manifest['audio_mapping_verification']!=audio.measure_audio_mapping(source,output,timeline,spec):raise core.Error('Revision QA soundtrack mapping mismatch')
    registry=__import__('render_video_v01').validate_registry(manifest['renderer_capabilities']['path'])
    audio.validate_capability(manifest['audio_capability']['path'])
    if any(registry['operations'].get(cap,{}).get('status')!='verified' for cap in timeline['required_capabilities'] if cap!='continuous_source_audio'):
        raise core.Error('Revision QA renderer capability unavailable')
    inputs={k:qa.ref(bundle/n) for k,n in (('plan',audio.PLAN),('spec',audio.SPEC),('timeline',audio.TIMELINE),('manifest',audio.MANIFEST),('director_packet',core.director.PACKET))}
    inputs.update(source=qa.ref(source),rendered_output=qa.ref(output),**references)
    inputs.update({'evidence:'+k:r for k,r in packet['inputs'].items()})
    return {'bundle':bundle,'manifest':manifest,'plan':plan,'spec':spec,'timeline':timeline,'source':source,'output':output,
        'source_info':info,'output_info':verified['metadata'],'inputs':inputs,'canonical':packet['canonical'],
        'speech':packet['speech'],'director_packet':packet}


def audio_analysis_context(ctx):
    timeline=copy.deepcopy(ctx['timeline']);sound=ctx['spec']['audio_timeline'];operations=timeline['operations']
    if sound['mode']=='continuous_source' and not sound['mix_original']:
        duration=timeline['expected_duration_sec'];window=sound['source_range']
        # Stage 5.6 measurements must inspect the actual AUDIO timeline, not
        # misclassify visual source jumps as soundtrack splices in the new mode.
        timeline['shots']=[{'shot_id':'continuous-source-audio','source_start_sec':window['start_sec'],
            'source_end_sec':window['end_sec'],'output_start_sec':0,'output_end_sec':duration,'speed':1,
            'freeze_sec':0,'freeze_output_start_sec':duration,'overlap_sec':0,'transition_out':'cut'}]
        operations=[]
        for direction,start,length in (('in',0,sound['fade_in_sec']),('out',duration-sound['fade_out_sec'],sound['fade_out_sec'])):
            if length:operations.append({'effective_kind':'audio_fade','parameters':{},'output_start_sec':start,'output_end_sec':start+length})
    return timeline,operations


def evaluate(bundle,*,feedback=None):
    started=time.monotonic();report=qa.empty_report();ctx=None
    try:
        ctx=verify_bundle(bundle);report.update(source=ctx['inputs']['source'],rendered_output=ctx['inputs']['rendered_output'],inputs=copy.deepcopy(ctx['inputs']))
        ledger={'media.source':ctx['inputs']['source'],'media.output':ctx['inputs']['rendered_output'],
            'timeline':ctx['inputs']['timeline'],'video.samples':{'method':'Stage56_sampled_pixels'},
            'audio.metrics':{'method':'Stage56_normalized_PCM'},'audio.mapping':{'method':'source_bound_audio_timeline','mapping':ctx['timeline']['audio_timeline']},
            'captions':{'method':'Stage56_declared_caption_policy'},'canonical':{'basis':'model_unverified'},'speech.eligibility':{'basis':'existing_gate'}}
        report['evidence_ledger']=ledger;report['integrity']={'status':'PASS','source_output_sha_bound':True,
            'manifest_plan_spec_timeline_checked':True,'capability_receipts_checked':True,'source_metadata_checked':True,'production_approval_inherited':False}
        samples,sampling=qa.frame_samples(ctx['output'],ctx['timeline']['expected_duration_sec'],ctx['output_info']['fps'])
        video,findings=qa.visual_analysis(samples,ctx['timeline'],sampling)
        audio_timeline,operations=audio_analysis_context(ctx)
        measured,more=qa.audio_analysis(core.audio_pcm(ctx['output'],qa.LIMITS),audio_timeline,
            source_pcm=np.asarray(core.audio_pcm(ctx['source'],qa.LIMITS),dtype=float),audio_mode='preserve',operations=operations)
        findings+=more;measured['source_audio_mapping']=ctx['timeline']['audio_timeline']
        for boundary in measured['boundaries']:ledger[boundary['boundary_id']]={'method':'audio_timeline_boundary','measurements':boundary}
        captions,more=qa.caption_analysis(ctx['plan'],ctx['timeline']);findings+=more
        human,more=qa.human_findings(feedback,ctx);findings+=more
        if human:
            report['inputs']['human_feedback']=qa.ref(feedback);ledger['human.feedback']=qa.ref(feedback)
            complete=human['provenance'].get('all_required_reviews_completed') is True and human['provenance'].get('completed_required_reviews')==ri.check('validation',qa.read(ctx['manifest']['validation']['path']))['reviews']
            report['human']={'performed':True,'provenance':human['provenance'],'feedback_ref':qa.ref(feedback),
                'required_reviews_complete':complete,'claim_scope':'Fresh source/output-bound human review; old V1 feedback not transferred'}
        report['technical']={'duration_sec':ctx['timeline']['expected_duration_sec'],'verification':ctx['manifest']['verification'],
            'video':video,'audio':measured,'captions':captions,'timeline':ctx['timeline'],'speech':ctx['speech'],
            'parameters':qa.PARAMETERS,'geometry_policy_checked':True,'pixel_perfect_crop_or_stretch_certification':'UNAVAILABLE','factual_claims_verified':False}
        report['dimensions']['technical_integrity']=qa.dimension('PASS','deterministic_validation','New MP4 source, decode, PTS, plan, authorization and capabilities verified',['media.output','timeline'],'high')
        report['dimensions']['captions']=qa.dimension(captions['status'],'deterministic_validation',captions['scope'],['captions'])
        report['dimensions']['audio_continuity']=qa.dimension('NEEDS_REVIEW','signal_measurement','Source mapping checked; musical phrase quality still requires listening',['audio.metrics','audio.mapping'])
        for i,finding in enumerate(findings):
            finding['issue_id']=f'v2-qa-{i+1:04d}';finding['source_ranges']=qa.source_ranges(finding['output_range'],ctx['timeline'])
        report['issues']=findings;ri.refs_match(report['inputs']);qa.assess(report)
    except (core.Error,OSError,ValueError,TypeError,KeyError,RecursionError):
        report['integrity']={'status':'BLOCKED','reason':'Revision receipt, media, authorization, decode or mapping verification failed'}
        report['evidence_ledger']['integrity.failure']={'method':'independent_validation'}
        finding=qa.issue('integrity','revision_integrity_failure','New output QA failed; do not claim improvement',origin='deterministic_validation',severity='critical',evidence=['integrity.failure'])
        finding['issue_id']='v2-blocked-0001';report['issues']=[finding];qa.assess(report)
    report['processing']={'elapsed_sec':round(time.monotonic()-started,3),'resources':qa.LIMITS,'network_requests':0,'new_render_performed':False}
    report['code_receipts']=ri.code_receipts();report['limitations']+=['V1 human-confirmed defects are historical, not fresh confirmation on V2']
    return qa.validate_report(report),ctx


def live_review(root,report,ctx,brief,*,under=None):
    """One real V2 call. Original-source observation is bound cached context."""
    output=core.new_directory(Path(root)/'live.v01',under or ri.ROOT);packet=qa.packet_for(report,ctx)
    request=reviewer.make_request(packet,'edited_output');output.mkdir()
    request_path=output/reviewer.name('edited_output');core.shared.write_json(request_path,request)
    generation={'contract_version':ri.VERSION,'mode':'live_multimodal','new_media_role':'edited_output',
        'new_media':report['rendered_output'],'request':qa.ref(request_path),'maximum_calls':1,'automatic_retries':0,
        'source_context_reused':True,'source_review_origin':brief['inputs']['response:original_source'],
        'code_receipts':ri.code_receipts(),'production_eligible':False,'publishing_eligible':False}
    try:
        raw=reviewer.invoke(request,request_path,approved=True)
        core.base.write_exclusive(output/'edited_output.untrusted-response.v01.txt',core.director.safe_text(raw))
        response=reviewer.validate_response(core.director.parse_response(raw),request,packet)
        core.shared.write_json(output/'edited_output.response.v01.json',response)
        # Revalidate the saved source response with ITS OWN old packet/request.
        # Never rewrite its packet hash to present it as a new inference.
        source_ref=brief['inputs']['response:original_source'];qa.same_reference(source_ref)
        if ctx['bundle'].is_relative_to(core.base.ROOT/'data/render-tests/stage59'):
            from stage59_recovery_v01 import cached_source
            source=cached_source(brief)
        else:
            old_prepared=core.safe_path(brief['inputs']['prepared']['path']).parent
            _,old_packet,_,requests=reviewer.load_prepared(old_prepared)
            source=reviewer.validate_response(qa.read(source_ref['path']),requests['original_source'],old_packet)
        if source['media_sha256']!=report['source']['sha256']:raise core.Error('Cached source review contamination')
        refs={'edited_output':qa.ref(output/'edited_output.response.v01.json'),'original_source':source_ref}
        merged=reviewer.merge(report,{'edited_output':response,'original_source':source},mode='live_multimodal',response_refs=refs)
        merged['ai']['source_context_reused']=True;merged['ai']['source_context_packet_sha256']=source['packet_sha256']
        merged['ai']['comparison_method']='One fresh V2 observation plus unchanged source-context observation from Stage 5.6; separate calls, not joint observation'
        qa.validate_report(merged);core.shared.write_json(output/qa.REPORT,merged)
        generation.update(status='VALIDATED_MODEL_UNVERIFIED',reported_model=core.director.strict_json(raw).get('model'),responses=refs)
        core.shared.write_json(output/'review-generation-provenance.v01.json',generation)
        return merged,output/qa.REPORT
    except (core.Error,OSError,ValueError,TypeError,KeyError) as error:
        generation.update(status='FAILED_NO_RETRY',diagnostic=error.diagnostic if isinstance(error,reviewer.InferenceFailure) else {'reason':'structured_response_or_context_invalid'})
        core.shared.write_json(output/'review-generation-provenance.v01.json',generation)
        raise


def compare(parent,new,parent_ref,new_ref,parent_plan,new_plan,spec):
    qa.validate_report(parent);qa.validate_report(new)
    if parent['source']!=new['source'] or parent['rendered_output']==new['rendered_output']:raise core.Error('Comparison source/output mismatch')
    changes=core.director.validator.differentiation(parent_plan['variants'][0],new_plan['variants'][0])
    continuous=spec['audio_timeline']['mode']=='continuous_source' and not spec['audio_timeline']['mix_original']
    if continuous:changes.append('independent_continuous_source_soundtrack')
    old_audio=parent['technical'].get('audio',{})
    old_jumps=any(abs(boundary.get('source_jump_sec',0))>1/30 for boundary in old_audio.get('boundaries',[]))
    critical=any(i['severity']=='critical' for i in new['issues']) or new['integrity'].get('status')!='PASS'
    high=any(i['severity']=='high' for i in new['issues']) or new['overall_decision'] in ('REVISE','BLOCKED')
    human_complete=new['human'].get('performed') is True and new['human'].get('required_reviews_complete') is True
    if any(i['origin']=='human_feedback' for i in new['issues']) and not new['human'].get('performed'):raise core.Error('Comparison human review provenance missing')
    decision='BLOCKED' if critical else 'REVISE' if high else 'ACCEPTED_FOR_PREVIEW' if new['overall_decision']=='PASS' and new['ai_editorial_status']!='INCOMPLETE' and human_complete else 'NEEDS_REVIEW'
    conflicts=[]
    for dimension in qa.DIMENSIONS:
        old=parent['dimensions'][dimension];current=new['dimensions'][dimension]
        if old['status']!=current['status']:
            conflicts.append({'dimension':dimension,'v1':old,'v2':current,'interpretation':'Different outputs and provenance; no automatic reconciliation or human confirmation'})
    result={'contract_version':ri.VERSION,'parent_output':parent['rendered_output'],'revised_output':new['rendered_output'],
        'parent_qa':parent_ref,'revised_qa':new_ref,'technical_result':'BLOCKED' if critical else 'PASS',
        'decision':decision,'audio_timeline_result':'CONTINUOUS_SOURCE_MAPPING' if continuous else 'PER_SHOT_SOURCE_MAPPING',
        'musical_phrase_quality':'UNVERIFIED_REQUIRES_LISTENING','human_review_pending':not human_complete,
        'historical_human_findings':[i for i in parent['issues'] if i['origin']=='human_feedback'],
        'new_issues':new['issues'],'editorial_disagreements':conflicts,'changes':changes,
        'improvement_claim':'REGRESSION_DETECTED' if critical else 'TECHNICAL_MAPPING_IMPROVED_ONLY' if continuous and old_jumps and not high else 'NOT_ESTABLISHED',
        'production_eligible':False,'publishing_eligible':False,'render_approved':False,'publish_approved':False}
    result['measured_changes']=measured_changes(parent,new)
    return ri.check('comparison',result)


def measured_changes(parent,new):
    """Compare physical QA measurements; none of these certify an editorial gain."""
    old=parent.get('technical',{});current=new.get('technical',{})
    old_audio=old.get('audio',{});new_audio=current.get('audio',{})
    old_video=old.get('video',{}).get('sampling',{});new_video=current.get('video',{}).get('sampling',{})
    required_audio=('rms','peak','pcm_sha256','boundaries')
    if not all(k in old_audio and k in new_audio for k in required_audio) or not all(
            'sample_rgb_sha256' in sample for sample in (old_video,new_video)):
        return {'status':'UNAVAILABLE','reason':'Both source-bound QA reports need decoded PCM and sampled video measurements'}
    old_rms,new_rms=old_audio['rms'],new_audio['rms']
    if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>=0 for x in
               (old_rms,new_rms,old_audio['peak'],new_audio['peak'])):
        raise core.Error('Invalid QA audio measurement')
    for boundaries in (old_audio['boundaries'],new_audio['boundaries']):
        if any(not isinstance(b.get('source_jump_sec'),(int,float)) or not math.isfinite(b['source_jump_sec']) for b in boundaries):
            return {'status':'UNAVAILABLE','reason':'QA audio boundary source jumps are missing or invalid'}
    jumps=lambda boundaries:sum(abs(b['source_jump_sec'])>1/30 for b in boundaries)
    return {'status':'COMPARED',
        'parent_duration_sec':old['duration_sec'],'revised_duration_sec':current['duration_sec'],
        'parent_audio_rms':old_rms,'revised_audio_rms':new_rms,
        'audio_rms_change_db':round(20*math.log10(max(new_rms,1e-9)/max(old_rms,1e-9)),3),
        'parent_audio_peak':old_audio['peak'],'revised_audio_peak':new_audio['peak'],
        'parent_audio_source_jumps':jumps(old_audio['boundaries']),
        'revised_audio_source_jumps':jumps(new_audio['boundaries']),
        'decoded_audio_changed':old_audio['pcm_sha256']!=new_audio['pcm_sha256'],
        'sampled_video_changed':old_video['sample_rgb_sha256']!=new_video['sample_rgb_sha256'],
        'interpretation':'Measured media difference only; visual sampling is sparse, duration may differ, and semantic/audio quality needs human review'}
