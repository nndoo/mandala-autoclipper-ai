#!/usr/bin/env python3
"""Bounded AI editing workflow: independent eligibility, private MP4, actual-media review.

Append-only bundles are the state machine. Interrupted/consumed attempts are never
reused. A job owns at most three Director reservations and two ASR calls per region.
"""
import argparse
import copy
import json
import re
from pathlib import Path
import tempfile
import time

import numpy as np
import automatic_editing_validation_v01 as validator
import automatic_text_v01 as text
import renderer_revision_v02 as audio
import render_video_v01 as renderer
import render_test_fixtures_v01 as fixtures
import render_showcase_preview_v01 as preview
import review_video_quality_v01 as reviewer
import generate_remote_speech_evidence_v01 as asr

core=audio.core
ROOT=validator.ROOT
MAX_DIRECTOR=3
MAX_ASR=2


def read(path):return core.read_json(path)


def write(path,data):
    core.shared.write_json(core.safe_path(path,output=True),data)


def save_text(path,value):
    path=core.safe_path(path,output=True)
    with path.open('x',encoding='utf8') as stream:stream.write(core.director.safe_text(value))


def reference(path):return audio.qa.ref(path)


def verify_inputs(request):
    for ref in request['inputs']:audio.qa.same_reference(ref)


def usage(raw):
    try:
        envelope=core.director.strict_json(raw)
        found=[]
        def visit(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k.lower() in ('usage','cost') and isinstance(v,(dict,int,float)):found.append({k:v})
                    elif isinstance(v,(dict,list)):visit(v)
            elif isinstance(value,list):
                for v in value:visit(v)
        visit(envelope)
        return {'provider_reported':found,'money_status':'REPORTED' if any('cost' in v for v in found) else 'NOT_REPORTED_NO_PRICE_INVENTED'}
    except core.Error:return {'provider_reported':[],'money_status':'NOT_REPORTED_NO_PRICE_INVENTED'}


def synthetic_cues():
    style={'font':'dejavu_sans_bold','size_px':20,'color':'#FFFFFF','active_color':'#40E0FF',
        'outline_px':1,'x':.45,'y':.5,'enter':'fade','exit':'fade','enter_sec':.3,'exit_sec':.3}
    cues=[]
    for i,(mode,start) in enumerate((('fade',.2),('pop',1.7),('slide',3.2))):
        cues.append({'id':mode,'role':'creative_text_overlay','text':'TEST','start_sec':start,'end_sec':start+1.3,
            'style':{**style,'enter':mode,'exit':'fade'}})
    cues.append({'id':'words','role':'automatic_speech_subtitle','text':'ONE TWO END','start_sec':4.7,'end_sec':5.8,
        'style':{**style,'size_px':16,'enter':'none','exit':'none','enter_sec':0,'exit_sec':0},
        'words':[{'text':w,'start_sec':a,'end_sec':b} for w,a,b in [('ONE',4.7,5.04),('TWO',5.08,5.42),('END',5.46,5.8)]]})
    return cues


def measure_proof(source,video,limits):
    records=[]
    def frame(path,t):return np.frombuffer(core.frame_rgb(path,t,limits=limits),dtype=np.uint8).reshape(320,180,3)
    for t in (.1,.233,.4,.8,1.433,1.533,1.733,1.9,2.2,3.233,3.4,3.7,4.75,5.2,5.6,5.9):
        a,b=frame(source,t),frame(video,t)
        delta=np.max(np.abs(a.astype(float)-b.astype(float)),axis=2)
        mask=delta>60;ys,xs=np.where(mask)
        # Source encoder noise near scene changes is excluded using central text region.
        mask[:100]=False;mask[220:]=False;mask[:,:10]=False;mask[:,165:]=False
        ys,xs=np.where(mask)
        rect=None if not len(xs) else [int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())]
        cyan=(b[:,:,0]<140)&(b[:,:,1]>150)&(b[:,:,2]>180)&mask
        records.append({'time_sec':t,'changed_pixels':int(mask.sum()),'box_px':rect,'cyan_pixels':int(cyan.sum())})
    values={r['time_sec']:r for r in records}
    if values[.8]['changed_pixels']<100 or values[.233]['changed_pixels']>=values[.8]['changed_pixels'] or values[1.433]['changed_pixels']>=values[.8]['changed_pixels']:
        raise core.Error('Synthetic fade not physically visible')
    if values[1.733]['box_px']==values[2.2]['box_px']:raise core.Error('Synthetic pop geometry did not change')
    if values[3.233]['box_px'] is None or values[3.7]['box_px'] is None or values[3.233]['box_px'][1]<=values[3.7]['box_px'][1]:
        raise core.Error('Synthetic short slide position did not change')
    if any(values[t]['cyan_pixels']<12 for t in (4.75,5.2,5.6)):raise core.Error('Synthetic active word color absent')
    if any(r['box_px'] and (r['box_px'][0]<14 or r['box_px'][2]>148 or r['box_px'][1]<25 or r['box_px'][3]>249) for r in records):
        raise core.Error('Synthetic active text outside portrait safe area')
    # Highlight must move from the first to last word, with phrase retained.
    cyan_boxes=[]
    for t in (4.75,5.2,5.6):
        f=frame(video,t);ys,xs=np.where((f[:,:,0]<140)&(f[:,:,1]>150)&(f[:,:,2]>180))
        cyan_boxes.append(float(xs.mean()))
    if not cyan_boxes[0]<cyan_boxes[1]<cyan_boxes[2]:raise core.Error('Active color does not follow real word intervals')
    return {'status':'PASS','samples':records,'active_word_centers_x':cyan_boxes,
        'capabilities':['relative_layout','text_fade','text_pop','text_slide','word_highlight'],
        'basis':'Actual synthetic MP4 pixels, full decode and closed recipe; not model self-report'}


def proof(output):
    output=core.new_directory(output,ROOT);output.parent.mkdir(parents=True,exist_ok=True)
    fixture_root=core.TEST_ROOT/(output.name+'-automatic')
    for name in ('dynamic','fullhd','reuse','audio'):
        renderer.self_test(name,fixture_root/name)
    registry=renderer.capability_registry([fixture_root/n for n in ('dynamic','fullhd','reuse','audio')])
    registry_path=fixture_root/'registry.json';write(registry_path,registry)
    with renderer.render_lock(),tempfile.TemporaryDirectory(dir=output.parent,prefix='.revision-work-') as temporary:
        work=Path(temporary);limits=audio.LIMITS
        # Closed source/plan recipe is owned here, not accepted from callers or AI.
        source=fixtures.generate_source(work,'basic',limits)
        plan,visual=fixtures.build_plan_spec('basic',source,core.TEST_ROOT/'automatic-proof',{},resource_overrides=limits)
        variant=plan['variants'][0];variant['shots']=[fixtures.shot('s1',1,0,6)];variant['operations']=[]
        variant['hook']={k:variant['shots'][0][k] for k in ('shot_id','source_start_sec','source_end_sec','timing_precision','evidence_refs','rationale')}
        visual['plan_sha256']=core.digest_object(plan)
        graph=core.compile_timeline(plan,visual)
        graph['automatic_text_cues']=synthetic_cues()
        filters,has_audio,_,_=core.filter_graph(graph,True,work,visual)
        f=work/'filters.ffgraph';f.write_text(filters)
        video=work/'render.mp4'
        core.ffmpeg(['-i',str(source),'-filter_complex_script',str(f),'-map','[vout]','-map','[aout]',
            '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','2',
            '-c:a','aac','-ar','48000','-ac','2','-map_metadata','-1',str(video)],work,limits)
        verified=core.verify_output(video,graph,has_audio,limits)
        observations=measure_proof(source,video,limits)
        safe=synthetic_cues()[0]
        clipped={**safe,'text':'W'*15,'style':{**safe['style'],'x':.08,'size_px':96}}
        clipping={'safe_pixels_outside_frame':glyph_clipping(safe,.8,work,limits,'proof-safe'),
            'clipped_pixels_outside_frame':glyph_clipping(clipped,.8,work,limits,'proof-clipped')}
        if clipping['safe_pixels_outside_frame'] or not clipping['clipped_pixels_outside_frame']:
            raise core.Error('Synthetic glyph clipping discrimination failed')
        # Continuous source bed uses the existing extension and correlation verifier.
        bed=audio.original_audio(plan['source']);bed.update(mode='continuous_source',source_range={'start_sec':0,'end_sec':6},gain_db=-6,fade_out_sec=.3)
        spec=audio.spec_for(plan,bed,output={'width':180,'height':320})
        bed_graph=audio.compile_timeline(plan,spec);bed_graph['automatic_text_cues']=synthetic_cues()
        filters,_,_,_=audio.filter_graph(bed_graph,True,work,spec);f2=work/'bed.ffgraph';f2.write_text(filters)
        bed_video=work/'continuous.mp4'
        core.ffmpeg(['-i',str(source),'-filter_complex_script',str(f2),'-map','[vout]','-map','[aout]',
            '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','2','-c:a','aac',
            '-ar','48000','-ac','2','-map_metadata','-1',str(bed_video)],work,limits)
        bed_verified=core.verify_output(bed_video,bed_graph,True,limits)
        mapping=audio.measure_audio_mapping(source,bed_video,bed_graph,spec)
        output.mkdir()
        for name,path in [('source.mp4',source),('render.mp4',video),('continuous.mp4',bed_video)]:
            import os
            os.link(path,output/name)
        result={'kind':'closed_synthetic_automatic_capability','code_receipts':validator.code_receipts(),
            'environment':core.environment(),'recipe':fixtures.RECIPE,'cues':synthetic_cues(),'status':'PASS',
            'verification':verified,'measurements':observations,'continuous_audio_verification':bed_verified,
            'clipping_verification':clipping,
            'plan':plan,'visual_spec':visual,'continuous_spec':spec,
            'continuous_audio_mapping':mapping,'artifacts':[reference(output/n) for n in ('source.mp4','render.mp4','continuous.mp4')],
            'visual_registry':reference(registry_path),
            'verified_capabilities':[k for k,v in registry['operations'].items() if v['status']=='verified']+['continuous_source_audio'],
            'human_verified':False,'production_eligible':False}
        write(output/'proof.json',result)
    return result


def check_proof(ref):
    audio.qa.same_reference(ref);p=read(ref['path'])
    if p.get('kind')!='closed_synthetic_automatic_capability' or p['status']!='PASS' or p['code_receipts']!=validator.code_receipts() or p['environment']!=core.environment() or p['recipe']!=fixtures.RECIPE or p['cues']!=synthetic_cues():
        raise core.Error('Synthetic capability code/environment/recipe mismatch; fresh proof required')
    for r in p['artifacts']:audio.qa.same_reference(r)
    audio.qa.same_reference(p['visual_registry'])
    registry=renderer.validate_registry(p['visual_registry']['path'])
    expected=[k for k,v in registry['operations'].items() if v['status']=='verified']+['continuous_source_audio']
    if p['verified_capabilities']!=expected:raise core.Error('Synthetic verified capabilities mismatch')
    source,video,bed_video=[core.safe_path(r['path']) for r in p['artifacts']]
    visual_graph=core.compile_timeline(p['plan'],p['visual_spec']);visual_graph['automatic_text_cues']=synthetic_cues()
    bed_graph=audio.compile_timeline(p['plan'],p['continuous_spec']);bed_graph['automatic_text_cues']=synthetic_cues()
    for path,graph,record in ((video,visual_graph,p['verification']),(bed_video,bed_graph,p['continuous_audio_verification'])):
        if core.verify_output(path,graph,True,audio.LIMITS)!=record:raise core.Error('Synthetic decode verification replay mismatch')
    if audio.measure_audio_mapping(source,bed_video,bed_graph,p['continuous_spec'])!=p['continuous_audio_mapping']:
        raise core.Error('Synthetic audio correlation replay mismatch')
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='.glyph-proof-') as temp:
        safe=synthetic_cues()[0];clipped={**safe,'text':'W'*15,'style':{**safe['style'],'x':.08,'size_px':96}}
        replay={'safe_pixels_outside_frame':glyph_clipping(safe,.8,Path(temp),audio.LIMITS,'safe'),
            'clipped_pixels_outside_frame':glyph_clipping(clipped,.8,Path(temp),audio.LIMITS,'clipped')}
        if replay!=p['clipping_verification']:raise core.Error('Synthetic glyph clipping replay mismatch')
    replay=measure_proof(core.safe_path(p['artifacts'][0]['path']),core.safe_path(p['artifacts'][1]['path']),audio.LIMITS)
    if replay!=p['measurements']:raise core.Error('Synthetic capability pixel replay mismatch')
    return p


def timed_units(payload,start,end,region_id):
    """Provider times only. Never infer timestamps from upload bounds or text length."""
    words=payload.get('words') or [w for s in payload.get('segments',[]) for w in s.get('words',[])]
    timing='word' if words else 'phrase';items=words or payload.get('segments',[])
    if not items:raise core.Error('ASR returned transcript without real timestamps')
    units=[];previous=start
    for i,u in enumerate(items):
        a,b=u.get('start'),u.get('end');value=u.get('word') if words else u.get('text')
        if isinstance(a,bool) or isinstance(b,bool) or not asr.local.finite(a) or not asr.local.finite(b):raise core.Error('Missing/nonfinite ASR timestamp')
        a,b=a+start,b+start
        if not start<=a<b<=end+.01 or a<previous-.01:raise core.Error('ASR times are out of bounds/order')
        if not isinstance(value,str) or not value.strip():raise core.Error('Empty ASR timing text')
        value=value.strip();text.literal(value)
        if not words and len(value.split())>15:raise core.Error('Provider phrase too long for three readable lines; cannot fabricate word timing')
        if u.get('no_speech_prob',0)>.6 or u.get('avg_logprob',0)<-1:raise core.Error('ASR low-confidence timed segment')
        units.append({'id':f'{region_id}-{i:03d}','text':value,'start_sec':a,'end_sec':b,'timing_basis':'provider_estimated','human_verified':False})
        previous=b
    def tokens(value):return re.findall(r'\w+',value.casefold())
    transcript=payload.get('text')
    if isinstance(transcript,str) and tokens(transcript)!=tokens(' '.join(u['text'] for u in units)):
        raise core.Error('Timed ASR units do not cover the returned transcript text')
    return timing,units


def model_review(media,output,context,*,speech=False):
    info=core.media_info(media,audio.LIMITS);media_ref=reference(media)
    response_schema={'type':'object','additionalProperties':False,'required':['media_sha256','video_examined','audio_examined','revision_required','issues','assessment','human_verified','production_eligible'],
        'properties':{'media_sha256':{'const':media_ref['sha256']},'video_examined':{'const':True},'audio_examined':{'const':True},
            'revision_required':{'type':'boolean'},'issues':{'type':'array','maxItems':24,'items':{'type':'object','additionalProperties':False,
                'required':['code','category','severity','start_sec','end_sec','diagnosis'], 'properties':{
                    'code':{'enum':list(validator.REVIEW_CODES)},'severity':{'enum':['minor','major','blocker']},
                    'category':{'enum':['technical_evidence','readability','editorial']},
                    'start_sec':{'type':'number','minimum':0},'end_sec':{'type':'number','maximum':info['duration_sec']},'diagnosis':{'type':'string','minLength':5,'maxLength':1000}}}},
            'assessment':{'type':'string','minLength':10,'maxLength':2500},'human_verified':{'const':False},'production_eligible':{'const':False}}}
    prompt=('Review the ACTUAL attached MP4 independently. You are a model, never human verification. '
        'Examine audio and video. Request revision for unreadable text, poor subject framing, distracting repeated shots/jump cuts, '
        'suspect subtitles, any audio problem or weak ending. Also reject unsupported price, stock, condition, guarantee or product claims: '
        'a clean-looking vehicle is not evidence of mechanical condition. Large empty ceiling dominating vehicle framing is poor subject prominence. '
        'Give concrete timestamps and diagnosis, not generic advice. '
        'Return only compact JSON matching OUTPUT_SCHEMA. Use issue codes to distinguish editorial preferences '
        '(poor_framing, shot_repetition, jump_cut, pacing, weak_ending, text_style, caption_density, audio_balance) '
        'from actual unreadable/clipped/invisible text, subtitle uncertainty, unsupported claims or technical failures. '
        'Editorial issues have category editorial and severity minor/major; evidence or actual readability defects have severity blocker. '
        'Estimated safe-area overlap or fast reading alone is advisory, not proof of unreadability. '
        'revision_required means you recommend a correction; issues do not automatically reject a technically sound private preview. '
        +('This is SOURCE speech admission: compare every timed ASR unit against what you hear. Any uncertain/missing/mistranscribed speech or synchronization mismatch must be an issue. ' if speech else '')
        +'CONTEXT='+json.dumps(context,separators=(',',':'),ensure_ascii=False)+'\nOUTPUT_SCHEMA='+json.dumps(response_schema,separators=(',',':')))
    request={'contract_version':'0.1.0','kind':'stage56_multimodal_qa_request','packet_sha256':core.digest_object(context),
        'media':{'role':'original_source' if speech else 'edited_output',**media_ref,'bytes':media.stat().st_size,
            'duration_sec':info['duration_sec'],'video_offered':True,'audio_offered':info['audio_present']},
        'prompt':prompt,'prompt_sha256':core.director.digest_text(prompt),'code_receipts':reviewer.code_receipts(),
        'live_inference_performed':False,'production_eligible':False,'publishing_eligible':False}
    core.base.validate_object(request,core.base.load_schema('video-quality-ai-request.v0.1.schema.json'),'Bound Reviewer request')
    output.mkdir();write(output/'request.json',request)
    write(output/'reservation.json',{'type':'source_speech_reviewer' if speech else 'output_reviewer','maximum_calls':1,'human_verified':False})
    raw=''
    try:
        raw=reviewer.invoke(request,output/'request.json',approved=True)
        save_text(output/'raw-response.json',raw)
        response=core.director.parse_response(raw)
        import jsonschema
        jsonschema.Draft202012Validator(response_schema).validate(response)
        for issue in response['issues']:
            if issue['category']!=validator.REVIEW_CODES[issue['code']]:raise core.Error('Reviewer category/code contradiction')
        if any(not 0<=i['start_sec']<i['end_sec']<=info['duration_sec'] for i in response['issues']):raise core.Error('Reviewer invalid issue timing')
        write(output/'response.json',response)
        write(output/'policy-assessment.json',validator.review_findings(response))
        return response
    except reviewer.InferenceFailure as error:
        raw=error.stdout
        if raw and not (output/'raw-response.json').exists():save_text(output/'raw-response.json',raw)
        write(output/'failure.json',error.diagnostic)
        raise
    finally:
        write(output/'usage.json',{'api_calls':1,**usage(raw),'raw_response_saved':bool(raw),'human_verified':False})


def speech_evidence(packet,job):
    source=core.safe_path(packet['source']['path']);sha=packet['source']['sha256']
    required=packet['speech']['requirements']['overall_requirement']!='not_required'
    if not required:return {'required':False,'status':'NOT_REQUIRED','source_sha256':sha,'units':[],'timing':'none','human_verified':False}
    _,config=asr.load_config(asr.DEFAULT_CONFIG);config={**config,'response_format':'verbose_json'}
    regions=[r for r in packet['speech']['requirements']['regions'] if r['requirement']!='not_required']
    if not regions:raise core.Error('Speech classification has no source regions')
    selected={};diagnoses={};attempt_counts={};review_count=0
    for iteration in range(MAX_ASR):
        for index,r in enumerate(regions):
            rid=f'region-{index:02d}'
            if rid in selected:continue
            n=attempt_counts.get(rid,0)+1;attempt_counts[rid]=n
            dest=job/f'asr-{rid}-{n:02d}';dest.mkdir()
            write(dest/'reservation.json',{'region_id':rid,'attempt':n,'maximum_attempts':MAX_ASR,'source_sha256':sha,
                'start_sec':r['start_sec'],'end_sec':r['end_sec'],'correction_diagnosis':diagnoses.get(rid),'api_calls':1})
            with tempfile.TemporaryDirectory(dir=job,prefix='.asr-work-') as temp:
                temp=Path(temp);wav=temp/'audio.wav'
                core.ffmpeg(['-i',str(source),'-ss',core.n(r['start_sec']),'-t',core.n(r['end_sec']-r['start_sec']),
                    '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)],temp,audio.LIMITS)
                result=asr.remote_call(config,wav,temp)
                write(dest/'raw-response.json',result)
                write(dest/'upload.json',{'sha256':core.intake.gate.sha256_file(wav),'bytes':wav.stat().st_size,'source_sha256':sha,
                    'start_sec':r['start_sec'],'end_sec':r['end_sec'],'config_sha256':core.digest_object(config)})
            try:
                if result['status']!='complete':raise core.Error(result.get('reason','ASR unavailable'))
                timing,units=timed_units(result['payload'],r['start_sec'],r['end_sec'],rid)
                selected[rid]=(timing,units,reference(dest/'raw-response.json'))
                write(dest/'timing-validation.json',{'status':'PASS','timing':timing,'units':units,'human_verified':False})
            except core.Error as error:
                diagnoses[rid]=str(error);write(dest/'timing-validation.json',{'status':'BLOCKED','diagnosis':str(error),'human_verified':False})
        if len(selected)!=len(regions):continue
        kinds={v[0] for v in selected.values()}
        if len(kinds)!=1:raise core.Error('Mixed phrase/word region timing needs consistent fallback; no invented words')
        evidence={'required':True,'status':'AUTO_PREVIEW_ELIGIBLE','source_sha256':sha,'timing':next(iter(kinds)),
            'units':[u for k,v in sorted(selected.items()) for u in v[1]],'raw_responses':[v[2] for k,v in sorted(selected.items())],
            'upload_receipts':[reference(core.safe_path(v[2]['path']).parent/'upload.json') for k,v in sorted(selected.items())],
            'attempt_counts':attempt_counts,'human_verified':False,'production_eligible':False,
            'limitations':['ASR timing is provider-estimated; model speech assessment is not human verification']}
        review_count+=1
        assessment=model_review(source,job/f'speech-review-{review_count:02d}',evidence,speech=True)
        if not validator.review_findings(assessment)['blocking_findings']:
            evidence['model_assessment']=reference(job/f'speech-review-{review_count:02d}'/'response.json');return evidence
        affected=set()
        for issue in assessment['issues']:
            if issue.get('code')!='subtitle_uncertain' and issue['category']!='subtitle':continue
            for index,r in enumerate(regions):
                if max(r['start_sec'],issue['start_sec'])<min(r['end_sec'],issue['end_sec']):affected.add(f'region-{index:02d}')
        if not affected:raise core.Error('Source reviewer found non-ASR blocker: '+json.dumps(assessment['issues']))
        for rid in affected:
            selected.pop(rid,None);diagnoses[rid]=assessment['issues']
    raise core.Error('ASR region budget exhausted: '+json.dumps(diagnoses,ensure_ascii=False))


def verify_speech(packet,evidence):
    if evidence['source_sha256']!=packet['source']['sha256'] or evidence['human_verified'] is not False:raise core.Error('Speech identity boundary violation')
    if not evidence['required']:
        if packet['speech']['requirements']['overall_requirement']!='not_required' or evidence['units']:raise core.Error('Required speech cannot be silently omitted')
        return
    if evidence['status']!='AUTO_PREVIEW_ELIGIBLE' or any(n>MAX_ASR for n in evidence['attempt_counts'].values()):raise core.Error('Speech timing/budget is not eligible')
    replay=[];kinds=set()
    for raw_ref,upload_ref in zip(evidence['raw_responses'],evidence['upload_receipts'],strict=True):
        audio.qa.same_reference(raw_ref);audio.qa.same_reference(upload_ref)
        payload=read(raw_ref['path']);upload=read(upload_ref['path'])
        region=core.safe_path(raw_ref['path']).parent.name.split('-')
        rid='region-'+region[2]
        if payload['status']!='complete' or upload['source_sha256']!=evidence['source_sha256']:raise core.Error('ASR raw/source mismatch')
        timing,units=timed_units(payload['payload'],upload['start_sec'],upload['end_sec'],rid)
        kinds.add(timing);replay.extend(units)
    if kinds!={evidence['timing']} or replay!=evidence['units']:raise core.Error('ASR timing does not replay from immutable raw provider response')
    ref=evidence['model_assessment'];audio.qa.same_reference(ref);assessment=read(ref['path'])
    if assessment['media_sha256']!=packet['source']['sha256'] or validator.review_findings(assessment)['blocking_findings'] or assessment['human_verified'] or not assessment['audio_examined']:
        raise core.Error('Source speech model assessment is uncertain or contaminated')


def revalidate_speech_cache(oldjob,output):
    """New validation lineage over old raw ASR bytes; zero new ASR calls/ledger resets."""
    oldjob=core.safe_path(Path(oldjob)/'packet.json',under=ROOT).parent
    output=core.new_directory(output,ROOT);output.mkdir()
    packet=core.intake.validate_packet(read(oldjob/'packet.json'));selected=[];uploads=[];units=[];kinds=set();counts={}
    for index,region in enumerate(packet['speech']['requirements']['regions']):
        if region['requirement']=='not_required':continue
        rid=f'region-{index:02d}';attempts=sorted(oldjob.glob(f'asr-{rid}-*/reservation.json'));counts[rid]=len(attempts)
        if not 1<=len(attempts)<=MAX_ASR:raise core.Error('Cached speech region budget invalid')
        dest=attempts[-1].parent;raw=read(dest/'raw-response.json');upload=read(dest/'upload.json')
        if raw['status']!='complete' or upload['source_sha256']!=packet['source']['sha256']:raise core.Error('Cached ASR source/response mismatch')
        timing,group=timed_units(raw['payload'],upload['start_sec'],upload['end_sec'],rid)
        kinds.add(timing);units.extend(group);selected.append(reference(dest/'raw-response.json'));uploads.append(reference(dest/'upload.json'))
    if len(kinds)!=1:raise core.Error('Cached region timings inconsistent')
    evidence={'required':True,'status':'AUTO_PREVIEW_ELIGIBLE','source_sha256':packet['source']['sha256'],
        'timing':next(iter(kinds)),'units':units,'raw_responses':selected,'upload_receipts':uploads,
        'attempt_counts':counts,'human_verified':False,'production_eligible':False,
        'limitations':['Provider-estimated phrase timing; no fabricated word timestamps; model review is not human verification']}
    write(output/'timing-revalidation.json',{'evidence':evidence,'old_job':str(oldjob),'code_receipts':validator.code_receipts(),
        'new_asr_calls':0,'reason':'Readable multi-line phrase fallback uses complete actual provider intervals'})
    result=model_review(core.safe_path(packet['source']['path']),output/'review',evidence,speech=True)
    evidence['model_assessment']=reference(output/'review/response.json')
    if validator.review_findings(result)['blocking_findings']:evidence['status']='BLOCKED_MODEL_SPEECH_ASSESSMENT'
    else:verify_speech(packet,evidence)
    write(output/'speech.json',evidence)
    write(output/'result.json',{'status':evidence['status'],'new_asr_calls':0,'source_reviewer_calls':1,'human_verified':False,
        'diagnosis':result['issues'],'notification':'Speech cache revalidated; historical attempt budgets preserved'})
    evidence['diagnosis']=result['issues']
    return evidence


def storyboard(source,job,duration):
    # Sampling density is source-duration dependent; no fixed editorial shot recipe.
    count=min(16,max(6,int(duration/2)+1));times=[round((i+.5)*duration/count,3) for i in range(count)]
    paths=[];board=job/'storyboard';board.mkdir()
    for i,t in enumerate(times):
        path=board/f'frame-{i:02d}.jpg'
        core.ffmpeg(['-ss',core.n(t),'-i',str(source),'-frames:v','1','-vf',
            f"scale=360:640,drawtext=fontfile={core.BOLD_FONT}:text='SOURCE {t:.3f} s':fontsize=18:fontcolor=white:box=1:boxcolor=black:x=8:y=8",
            '-q:v','3',str(path)],board,audio.LIMITS)
        paths.append({'time_sec':t,**reference(path)})
    return paths


def prepare(packet_path,proof_path,job,comparison=None):
    job=core.new_directory(job,ROOT);job.parent.mkdir(parents=True,exist_ok=True)
    packet=core.intake.validate_packet(read(packet_path));source=core.safe_path(packet['source']['path'])
    check_proof(reference(proof_path))
    job.mkdir();write(job/'packet.json',packet)
    try:
        board=storyboard(source,job,packet['source']['duration_sec'])
        speech=speech_evidence(packet,job);write(job/'speech.json',speech)
        inputs=[reference(packet_path),reference(job/'packet.json'),reference(job/'speech.json'),reference(source),*[{'path':p['path'],'sha256':p['sha256']} for p in board]]
        if comparison:inputs.append(reference(comparison))
        request={'kind':'automatic_stage59_private_job','source_sha256':packet['source']['sha256'],
            'inputs':inputs,'storyboard':board,'proof':reference(proof_path),'comparison':reference(comparison) if comparison else None,
            'code_receipts':validator.code_receipts(),'environment':core.environment(),'maximum_director_proposals':MAX_DIRECTOR,
            'maximum_asr_attempts_per_region':MAX_ASR,'human_verified':False,'production_eligible':False,'publishing_eligible':False}
        write(job/'request.json',request);return request
    except Exception as error:
        write(job/'stopped.json',{'status':'BLOCKED','diagnosis':str(error)[:2000],'notification':'Workflow stopped; source/timing admission failed','human_verified':False})
        raise
    finally:
        reservations=sorted(job.glob('asr-*/reservation.json'))
        write(job/'preparation-api-ledger.json',{'asr_calls_reserved':len(reservations),
            'reservations':[reference(p) for p in reservations],'money_status':'NOT_REPORTED_NO_PRICE_INVENTED'})


def prompt_for(job,request,diagnosis,previous):
    packet=read(job/'packet.json');speech=read(job/'speech.json')
    view={k:packet[k] for k in ('source','canonical','audio','visual','correlation','evidence_ledger')}
    schema=read(core.base.ROOT/validator.SCHEMA)
    return ('You are the Creative Director. Decide the ENTIRE integrated edit, not a fixed template: compelling hook, '
        'distinct nonrepetitive shot selection, subject-first framing, pacing, motivated transitions/effects, '
        'coherent typography/color, branding and satisfying ending. Attached images are timestamped SOURCE storyboard frames. '
        'Inspect them visually for vehicle position and clean negative space. Source metadata/evidence may be model-unverified. '
        'Do not invent product claims, inventory availability, features/prices, mechanical condition or identities. '
        'Never say kondisi prima, bebas banjir/tabrak, garansi or ready-stock based on appearance. Mandala Auto project branding is permitted. '
        'Choose any duration/shot count within source and bounded capabilities. Source range seconds and output text seconds are different! '
        'Shots overlap when transition_out=crossfade: next output_start subtracts previous overlap. Last shot must cut with overlap=0. '
        'Reframe scale 1–2; crop center must satisfy 1/(2*scale)<=center<=1-1/(2*scale). Scale=1 means centers=.5. '
        'Optional numeric shot grade chooses brightness [-.2,.2], contrast [.5,1.5], saturation [0,2]; use it purposefully. '
        'Place relevant Indonesian creative captions on MORE THAN HALF of cinematic shots, with breathing gaps. '
        'Use multiple concise captions with visual hierarchy, attractive deliberate sizes/colors/placement; do not blanket the subject. '
        'Text <=3 lines; portrait safe area left .08 right .82 top .08 bottom .78. x/y is TEXT CENTER. '
        'CONSERVATIVE half width=max_line_characters*size_px/2, half height=1.5*size_px*line_count/2; outline adds 5 px, '
        'slide envelope adds .015*1920 px vertically. Reading rate <=22 characters/sec; animations leave >=.2 sec hold. '
        'Font choices are verified DejaVu Sans regular/bold. All style fields are explicit. none duration=0, others .05–1 sec. '
        'A pop scales 85 to100 percent; slide is a short 1.5 percent vertical move. At most one slide per cue. '
        'For dialogue use ALL available timed units inside selected shots, groups of 2–5 words; unit_ids carry real source timing. '
        'If phrase-only timing, choose one provider segment per group, never invent word times. For >5 words choose line_breaks_after '
        '(word indices) to wrap the full segment into <=3 lines of 2–5 words; all lines share the actual phrase interval. '
        'Subtitles follow speech language. '
        'Dialogue audio mode original, speed=1 and no crossfades; choose boundaries outside speech units. '
        'For music-only, continuous_source keeps an uninterrupted source passage of exactly the output length; choose gain with headroom and tasteful fades. '
        'All flags human_verified and production_eligible false. Return ONLY compact complete JSON, no markdown. '
        '\nSOURCE_EVIDENCE='+json.dumps(view,separators=(',',':'),ensure_ascii=False)+
        '\nSPEECH='+json.dumps(speech,separators=(',',':'),ensure_ascii=False)+
        '\nSTORYBOARD='+json.dumps(request['storyboard'],separators=(',',':'))+
        '\nCONCRETE_CORRECTION_DIAGNOSIS='+json.dumps(diagnosis,separators=(',',':'),ensure_ascii=False)+
        '\nPREVIOUS_PROPOSAL='+json.dumps(previous,separators=(',',':'),ensure_ascii=False)+
        '\nOUTPUT_SCHEMA='+json.dumps(schema,separators=(',',':')))


def glyph_clipping(cue,t,work,limits,index):
    """Observe libass glyphs on a padded synthetic canvas, not a character-count estimate."""
    w,h,pad=1080,1920,64
    ass=text.document([cue],{'width':w,'height':h})
    ass=ass.replace(f'PlayResX: {w}',f'PlayResX: {w+2*pad}').replace(f'PlayResY: {h}',f'PlayResY: {h+2*pad}')
    def shift(match):
        values=match.group(2).split(',');coordinates=2 if match.group(1)=='pos' else 4
        for i in range(coordinates):values[i]=str(int(values[i])+pad)
        return '\\'+match.group(1)+'('+','.join(values)+')'
    ass=re.sub(r'\\(pos|move)\(([^)]+)\)',shift,ass)
    path=work/f'glyph-check-{index}.ass';path.write_text(ass)
    width,height=w+2*pad,h+2*pad
    raw,_=core.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',f'color=black:s={width}x{height}:r=30:d=0.04',
        '-vf',f'setpts=PTS+{core.n(t)}/TB,subtitles=filename={path}:fontsdir={core.FONT.parent}',
        '-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],limits,max_bytes=width*height*3)
    pixels=np.frombuffer(raw,dtype=np.uint8).reshape(height,width,3)
    mask=np.max(pixels,axis=2)>32
    mask[pad:pad+h,pad:pad+w]=False
    return int(mask.sum())


def visibility(video,timeline,spec,work):
    """Matched same-edit/no-text controls isolate rendered glyphs from source motion."""
    limits=spec['visual_spec']['resources'];control_graph=copy.deepcopy(timeline);control_graph.pop('automatic_text_cues',None)
    source=core.safe_path(spec['audio_timeline']['source']['path'])
    filters,_,_,_=audio.filter_graph(control_graph,True,work,spec)
    # Only video control is encoded; no audio stream is mixed into the comparison.
    script=work/'control.ffgraph';script.write_text(filters)
    control=work/'control.mp4'
    core.ffmpeg(['-i',str(source),'-filter_complex_script',str(script),'-map','[vout]','-map','[aout]',
        '-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-threads','2',str(control)],work,limits)
    records=[];w,h=270,480
    samples=[]
    for cue in timeline['automatic_text_cues']:
        a,b=cue['start_sec'],cue['end_sec'];s=cue['style']
        times={round(a+s['enter_sec']+.05,6),round((a+b)/2,6),round(b-s['exit_sec']-.05,6)}
        times.update(round((w['start_sec']+w['end_sec'])/2,6) for w in cue.get('words',[]))
        samples.extend((cue,t) for t in sorted(times) if a<t<b)
    for index,(cue,t) in enumerate(samples):
        a=np.frombuffer(core.frame_rgb(video,t,w,h,limits),dtype=np.uint8).reshape(h,w,3)
        b=np.frombuffer(core.frame_rgb(control,t,w,h,limits),dtype=np.uint8).reshape(h,w,3)
        rect=validator.envelope(cue);x1,y1,x2,y2=[round(v/4) for v in rect]
        x1,x2=max(0,x1),min(w,x2);y1,y2=max(0,y1),min(h,y2)
        diff=np.mean(np.abs(a.astype(float)-b.astype(float)),axis=2)
        inside=diff[y1:y2,x1:x2];outside=diff.copy();outside[y1:y2,x1:x2]=0
        count=int((inside>25).sum())
        if count<12:raise core.Error('Actual MP4 text not visibly different from matched no-text control: '+cue['id'])
        clipped=glyph_clipping(cue,t,work,limits,index)
        if clipped:raise core.Error('Observed libass glyph pixels extend beyond actual frame: '+cue['id'])
        records.append({'cue_id':cue['id'],'sample_sec':t,'changed_glyph_pixels_270x480':count,
            'inside_mean_difference':float(inside.mean()),'outside_median_difference':float(np.median(outside)),
            'envelope_px':rect,'glyph_pixels_beyond_frame':clipped,'status':'VISIBLE_BY_MATCHED_CONTROL','ocr_verified':False})
        path=work/f'caption-{cue["id"]}-{index:03d}.png'
        core.ffmpeg(['-ss',core.n(t),'-i',str(video),'-frames:v','1',str(path)],work,limits)
    return {'status':'PASS','records':records,'limitation':'Pixel visibility is not OCR, semantic correctness or human editorial review'}


def render_attempt(job,attempt,proposal,plan,spec,timeline,request):
    permit={'scope':'STAGE59_PRIVATE_PREVIEW','human_verified':False,'production_eligible':False,
        'source_sha256':plan['source']['sha256'],'proposal_sha256':core.digest_object(proposal),
        'execution_sha256':core.digest_object(spec),'request_sha256':core.digest_object(request)}
    with renderer.render_lock(),tempfile.TemporaryDirectory(dir=job,prefix='.revision-work-') as temp:
        work=Path(temp);write(attempt/'permit.json',permit)
        video,graph,verified,mapping,execution=audio.encode(core.safe_path(plan['source']['path']),plan,spec,work,
            mode='AUTOMATIC_PRIVATE_PREVIEW',context={'job':str(job),'attempt':str(attempt)})
        write(attempt/'encode-verification.json',verified)
        destination=attempt/'render'
        output_ref={'path':str(destination/'preview.mp4'),'sha256':core.intake.gate.sha256_file(video),'bytes':video.stat().st_size}
        audio.publish(destination,{'preview.mp4':video},{'plan.json':plan,'spec.json':spec,'timeline.json':graph,
            'encode-result.json':{'output':output_ref,'verification':verified,'execution':execution,'human_verified':False}},ROOT)
        technical={'decode':verified,'audio_mapping':mapping,'execution':execution}
        technical['black_frames']=preview.black_scan(video,graph,spec['visual_spec']['resources'],decoded_frame_count=verified['frame_count'])
        technical['audio_headroom']=stereo_headroom(video,graph,spec['visual_spec']['resources'])
        technical['text_visibility']=visibility(video,graph,spec,work)
        # Existing exclusive publisher; final manifest is completed-bundle marker.
        manifest={'status':'PRIVATE_PREVIEW_COMPLETED','source':plan['source'],'output':output_ref,'technical':technical,
            'code_receipts':validator.code_receipts(),'environment':core.environment(),'human_verified':False,
            'production_eligible':False,'publishing_eligible':False,'permit':reference(attempt/'permit.json')}
        import os
        for path in work.glob('caption-*.png'):os.link(path,destination/path.name)
        write(destination/'manifest.json',manifest)
        return manifest,graph


def stereo_headroom(video,graph,limits):
    raw,_=core.run(['ffmpeg','-v','error','-nostdin','-i',str(video),'-vn','-ac','2','-ar','48000',
        '-f','f32le','pipe:1'],limits,max_bytes=round(graph['expected_duration_sec']*48000*8)+48000)
    pcm=np.frombuffer(raw,dtype='<f4');peak=float(np.max(np.abs(pcm))) if len(pcm) else 0
    if not len(pcm) or peak>=.95:raise core.Error('Rendered audio lacks decoded sample headroom')
    return {'decoded_stereo_peak':peak,'clipped_samples':int((np.abs(pcm)>=.999).sum()),
        'status':'PASS','limitation':'Decoded sample peak, not oversampled true-peak measurement'}


def comparison(old,new,output):
    limits=audio.LIMITS;oldinfo=core.media_info(old,limits);newinfo=core.media_info(new,limits)
    records=[]
    for fraction in (.1,.3,.5,.7,.9):
        a=np.frombuffer(core.frame_rgb(old,fraction*oldinfo['duration_sec'],180,320,limits),dtype=np.uint8).astype(float)
        b=np.frombuffer(core.frame_rgb(new,fraction*newinfo['duration_sec'],180,320,limits),dtype=np.uint8).astype(float)
        records.append({'normalized_time':fraction,'rgb_mean_absolute_difference':float(np.mean(np.abs(a-b)))})
    result={'old':reference(old),'new':reference(new),'old_info':oldinfo,'new_info':newinfo,'actual_mp4_frame_differences':records,
        'visual_change_measured':all(r['rgb_mean_absolute_difference']>2 for r in records),
        'human_review':'NOT_PERFORMED','limitation':'Time-normalized pixel comparison detects change, not artistic superiority'}
    write(output,result);return result


def select_candidate(candidates):
    eligible=[c for c in candidates if not c['blocking_findings']]
    return min(eligible,key=lambda c:(sum(f['category']=='editorial' and f['severity']=='major' for f in c['advisory_findings']),
        len(c['advisory_findings']),-c['attempt'])) if eligible else None


def candidate_for(attempt,report,manifest,response):
    assessment=validator.review_findings(response)
    return {'policy_version':validator.POLICY_VERSION,'attempt':int(attempt.name.split('-')[-1]),
        'blocking_findings':report['blocking_findings']+assessment['blocking_findings'],
        'advisory_findings':report['advisory_findings']+assessment['advisory_findings'],
        'output':manifest['output'],'manifest':reference(attempt/'render/manifest.json'),
        'proposal':reference(attempt/'proposal.json'),'validation':reference(attempt/'validation.json'),
        'reviewer':reference(attempt/'review/response.json'),'human_verified':False,
        'production_eligible':False,'publishing_eligible':False}


def saved_review(attempt,output):
    request=read(attempt/'review/request.json');response=read(attempt/'review/response.json')
    raw=core.director.parse_response(core.safe_path(attempt/'review/raw-response.json').read_text())
    if (raw!=response or response['media_sha256']!=output['sha256'] or request['media']['sha256']!=output['sha256']
            or request['media']['bytes']!=output['bytes'] or request['prompt_sha256']!=core.director.digest_text(request['prompt'])
            or not response['video_examined'] or not response['audio_examined']
            or response['human_verified'] or response['production_eligible']):
        raise core.Error('Reviewer raw/media/permission boundary mismatch')
    return response


def verify_output_reference(output,job):
    # Render manifests store absolute paths; generic QA receipts use project-relative paths.
    # Compare the resolved guarded file and bytes, not the two spelling conventions.
    video=core.safe_path(output['path'],under=job)
    if reference(video)['sha256']!=output['sha256'] or video.stat().st_size!=output['bytes']:
        raise core.Error('Candidate MP4 fingerprint/byte count mismatch')
    return video


def verify_candidate(candidate,job):
    """A saved candidate is evidence to replay, never an approval shortcut."""
    for key in ('manifest','proposal','validation','reviewer'):audio.qa.same_reference(candidate[key])
    verify_output_reference(candidate['output'],job)
    attempt=core.safe_path(candidate['proposal']['path'],under=job).parent
    report,plan,spec,graph=validator.validate(read(candidate['proposal']['path']),read(job/'packet.json'),read(job/'speech.json'))
    manifest=read(candidate['manifest']['path']);response=saved_review(attempt,candidate['output'])
    if candidate!=candidate_for(attempt,report,manifest,response) or report!=read(candidate['validation']['path']):
        raise core.Error('Candidate policy/validation replay mismatch')
    if report['blocking_findings'] or validator.review_findings(response)['blocking_findings']:
        raise core.Error('Candidate still has evidence/readability blockers')
    if manifest['code_receipts']!=validator.code_receipts() or manifest['environment']!=core.environment():
        raise core.Error('Candidate code/environment lineage mismatch')
    if plan!=read(attempt/'render/plan.json') or spec!=read(attempt/'render/spec.json') or graph!=read(attempt/'render/timeline.json'):
        raise core.Error('Candidate render graph mismatch')
    video=core.safe_path(candidate['output']['path'])
    if core.verify_output(video,graph,True,spec['visual_spec']['resources'])!=manifest['technical']['decode']:
        raise core.Error('Candidate full decode replay mismatch')
    stereo_headroom(video,graph,spec['visual_spec']['resources'])
    return graph


def complete_candidate(job,candidate,total,request):
    check_proof(request['proof'])
    graph=verify_candidate(candidate,job)
    if request.get('comparison'):
        comparison(core.safe_path(request['comparison']['path']),core.safe_path(candidate['output']['path']),job/'comparison.json')
    notes=candidate['advisory_findings']
    completed={'status':'AUTO_PREVIEW_COMPLETED_WITH_NOTES' if notes else 'AUTO_PREVIEW_COMPLETED',
        'policy_version':validator.POLICY_VERSION,'output':candidate['output'],'duration_sec':graph['expected_duration_sec'],
        'resolution':[graph['output_settings']['width'],graph['output_settings']['height']],
        'selected_attempt':candidate['attempt'],'director_proposals_reserved':total,'reviewer':candidate['reviewer'],
        'blocking_findings':[],'advisory_findings':notes,'technical_qa':'PASS','human_verified':False,
        'human_review':'NOT_PERFORMED','production_eligible':False,'publishing_eligible':False}
    write(job/'completed.json',completed);return completed


def replay_render_decisions(proposal,packet,plan,spec):
    expected_plan,expected_spec=validator.convert(proposal,packet)
    if expected_plan!=plan or spec['visual_spec']['plan_sha256']!=core.digest_object(plan):
        raise core.Error('Historical visual decisions or original plan fingerprint mismatch')
    # Old writers encoded zero as 0; rational-clock writers encode the same time as 0.0.
    # Each digest must bind its OWN original bytes/object; compare remaining executable choices.
    if expected_spec['visual_spec']['plan_sha256']!=core.digest_object(expected_plan):
        raise core.Error('Current converted plan fingerprint mismatch')
    left=copy.deepcopy(expected_spec);right=copy.deepcopy(spec)
    left['visual_spec'].pop('plan_sha256');right['visual_spec'].pop('plan_sha256')
    if left!=right:raise core.Error('Historical execution choices mismatch')


def reevaluate(job,proof_path,output):
    """Read-only historical MP4 evaluation into a NEW report; no inference, source render or permit."""
    job=core.safe_path(Path(job)/'request.json',under=ROOT).parent
    output=core.new_directory(output,ROOT);output.mkdir()
    request=read(job/'request.json');verify_inputs(request)
    check_proof(reference(proof_path))
    packet=core.intake.validate_packet(read(job/'packet.json'));speech=read(job/'speech.json');verify_speech(packet,speech)
    evaluations=[]
    for attempt in sorted(job.glob('proposal-*')):
        if not (attempt/'render/manifest.json').exists():continue
        manifest=read(attempt/'render/manifest.json');video=verify_output_reference(manifest['output'],job)
        proposal=read(attempt/'proposal.json')
        if core.director.parse_response(core.safe_path(attempt/'raw-response.json').read_text())!=proposal:
            raise core.Error('Historical Director raw/proposal mismatch')
        report,_,_,_=validator.validate(proposal,packet,speech)
        plan=read(attempt/'render/plan.json');spec=read(attempt/'render/spec.json');graph=read(attempt/'render/timeline.json')
        replay_render_decisions(proposal,packet,plan,spec)
        visual=audio.compile_timeline(plan,spec);visual['automatic_text_cues']=validator.cues_for(proposal,visual,speech,[])
        if graph!=visual:raise core.Error('Historical graph replay mismatch')
        limits=spec['visual_spec']['resources'];verified=core.verify_output(video,graph,True,limits)
        black=preview.black_scan(video,graph,limits,decoded_frame_count=verified['frame_count'])
        mapping=audio.measure_audio_mapping(core.safe_path(plan['source']['path']),video,graph,spec)
        review_policy={'blocking_findings':[validator.finding('review_unavailable','technical_evidence','blocker','No saved actual-MP4 Reviewer response')],'advisory_findings':[]}
        inputs=[reference(attempt/n) for n in ('proposal.json','raw-response.json','render/manifest.json','render/plan.json','render/spec.json','render/timeline.json')]
        if (attempt/'review/response.json').exists():
            response=saved_review(attempt,manifest['output'])
            review_policy=validator.review_findings(response)
            inputs.extend(reference(attempt/'review'/n) for n in ('request.json','response.json','raw-response.json'))
        blockers=report['blocking_findings']+review_policy['blocking_findings']
        notes=report['advisory_findings']+review_policy['advisory_findings']
        result={'attempt':int(attempt.name.split('-')[-1]),'output':manifest['output'],'blocking_findings':blockers,
            'advisory_findings':notes,'status':'BLOCKED' if blockers else 'AUTO_PREVIEW_COMPLETED_WITH_NOTES' if notes else 'AUTO_PREVIEW_COMPLETED',
            'technical_replay':{'decode':verified,'black_scan':black,'audio_mapping':mapping,'audio_headroom':stereo_headroom(video,graph,limits)},
            'historical_text_visibility':manifest['technical']['text_visibility'],
            'text_visibility_basis':'Historical measured pixels retained; no current no-text control render performed',
            'inputs':inputs,'historical_code_receipts':manifest['code_receipts'],'human_verified':False,
            'production_eligible':False,'publishing_eligible':False}
        write(output/f'proposal-{result["attempt"]:02d}.json',result);evaluations.append(result)
    best=select_candidate(evaluations)
    result={'status':best['status'] if best else 'BLOCKED','policy_version':validator.POLICY_VERSION,
        'blocking_findings':[] if best else [f for e in evaluations for f in e['blocking_findings']],
        'advisory_findings':best['advisory_findings'] if best else [f for e in evaluations for f in e['advisory_findings']],
        'diagnosis':[] if best else [f for e in evaluations for f in e['blocking_findings']],
        'selected_attempt':best['attempt'] if best else None,'evaluations':evaluations,'code_receipts':validator.code_receipts(),
        'environment':core.environment(),'proof':reference(proof_path),'historical_request':reference(job/'request.json'),
        'api_calls':0,'director_inference_calls':0,'real_content_renders':0,'permits_created':0,
        'human_verified':False,'production_eligible':False,'publishing_eligible':False}
    write(output/'reevaluation.json',result);return result


def run(job):
    job=core.safe_path(Path(job)/'request.json',under=ROOT).parent;request=read(job/'request.json')
    verify_inputs(request)
    if request['code_receipts']!=validator.code_receipts() or request['environment']!=core.environment():raise core.Error('Job lineage changed; do not replenish its budget')
    if (job/'completed.json').exists():return read(job/'completed.json')
    if (job/'stopped.json').exists():raise core.Error('This job is stopped; saved diagnosis is final')
    reservations=sorted(job.glob('proposal-*/reservation.json'))
    # A crash cannot silently replay a paid call. Reserved slots count even without a response.
    diagnosis=[{'code':'interrupted_reserved_attempt','attempt':str(p.parent)} for p in reservations if not (p.parent/'outcome.json').exists()]
    previous=None
    if reservations:
        last=reservations[-1].parent
        if (last/'proposal.json').exists():previous=read(last/'proposal.json')
        if (last/'outcome.json').exists():diagnosis=read(last/'outcome.json').get('diagnosis',[])
    packet=read(job/'packet.json');speech=read(job/'speech.json')
    candidates=[]
    for path in sorted(job.glob('proposal-*/candidate.json')):
        candidate=read(path)
        if candidate['blocking_findings']:continue
        try:verify_candidate(candidate,job);candidates.append(candidate)
        except core.Error as error:diagnosis.append(validator.finding('candidate_replay_failed','technical_evidence','blocker',str(error)))
    try:
        for number in range(len(reservations)+1,MAX_DIRECTOR+1):
            attempt=job/f'proposal-{number:02d}';attempt.mkdir()
            prompt=core.director.safe_text(prompt_for(job,request,diagnosis,previous),65536)
            save_text(attempt/'prompt.txt',prompt)
            write(attempt/'reservation.json',{'attempt':number,'maximum_proposals':MAX_DIRECTOR,'api_calls':1,
                'prompt_sha256':core.director.digest_text(prompt),'request_sha256':core.digest_object(request),
                'attached_images':request['storyboard'],'correction_diagnosis':diagnosis,'human_verified':False})
            raw=''
            try:
                raw=core.director.live_response(prompt,approved=True,image_paths=[p['path'] for p in request['storyboard']])
                save_text(attempt/'raw-response.json',raw)
                proposal=core.director.parse_response(raw);write(attempt/'proposal.json',proposal);previous=proposal
                report,plan,spec,timeline=validator.validate(proposal,packet,speech);write(attempt/'validation.json',report)
                if report['blocking_findings']:diagnosis=report['blocking_findings'];continue
                write(attempt/'visual-plan.json',plan);write(attempt/'execution.json',spec)
                manifest,graph=render_attempt(job,attempt,proposal,plan,spec,timeline,request)
                result=model_review(core.safe_path(manifest['output']['path']),attempt/'review',
                    {'source':packet['source'],'proposal':proposal,'technical':manifest['technical'],'speech':speech,
                        'timing':graph['shots'],'text':graph['automatic_text_cues']})
                candidate=candidate_for(attempt,report,manifest,result);write(attempt/'candidate.json',candidate)
                diagnosis=candidate['blocking_findings']+candidate['advisory_findings']
                if not candidate['blocking_findings']:
                    candidates.append(candidate)
                    if not candidate['advisory_findings']:return complete_candidate(job,candidate,number,request)
            except Exception as error:
                if isinstance(error,reviewer.InferenceFailure):
                    raw=error.stdout
                    if raw and not (attempt/'raw-response.json').exists():save_text(attempt/'raw-response.json',raw)
                    write(attempt/'inference-failure.json',error.diagnostic)
                diagnosis=[validator.finding('attempt_failed','technical_evidence','blocker',str(error)[:1800])]
            finally:
                write(attempt/'usage.json',{'api_calls':1,**usage(raw),'raw_response_saved':bool(raw),'human_verified':False})
                write(attempt/'outcome.json',{'diagnosis':diagnosis,'human_verified':False})
        best=select_candidate(candidates)
        if best:return complete_candidate(job,best,MAX_DIRECTOR,request)
        stopped={'status':'BLOCKED','diagnosis':diagnosis,'notification':'Automatic edit stopped after maximum three Director proposals; no eligible candidate',
            'director_proposals_reserved':MAX_DIRECTOR,'human_verified':False,'production_eligible':False}
        write(job/'stopped.json',stopped);return stopped
    finally:
        calls=[{'path':str(p),**read(p)} for p in job.glob('**/reservation.json')]
        ledger={'reservations':calls,'api_calls_reserved':sum(c.get('api_calls',1) for c in calls),
            'cost_reporting':'Provider-reported usage retained per invocation; no invented monetary totals'}
        path=job/f'api-ledger-{len(calls):02d}.json'
        if not path.exists():write(path,ledger)
        elif read(path)!=ledger:write(job/f'api-ledger-{len(calls):02d}-{core.digest_object(ledger)[:12]}.json',ledger)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('proof');p.add_argument('--output',required=True)
    p=sub.add_parser('prepare');p.add_argument('--packet',required=True);p.add_argument('--proof',required=True);p.add_argument('--job',required=True);p.add_argument('--compare')
    p=sub.add_parser('run');p.add_argument('--job',required=True)
    p=sub.add_parser('revalidate-speech');p.add_argument('--old-job',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('reevaluate');p.add_argument('--job',required=True);p.add_argument('--proof',required=True);p.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.action=='proof':result=proof(args.output)
    elif args.action=='prepare':result=prepare(args.packet,args.proof,args.job,args.compare)
    elif args.action=='revalidate-speech':result=revalidate_speech_cache(args.old_job,args.output)
    elif args.action=='reevaluate':result=reevaluate(args.job,args.proof,args.output)
    else:result=run(args.job)
    print(json.dumps({'status':result.get('status','PREPARED'),'output':result.get('output'),'diagnosis':result.get('diagnosis')},ensure_ascii=False))
    if str(result.get('status','')).startswith('BLOCKED'):raise SystemExit(20)


if __name__=='__main__':main()
