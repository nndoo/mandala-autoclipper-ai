"""Independent, offline, source-bound technical QA. Never render or approve."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from scipy.fft import rfft
import renderer_core_v01 as core
import render_video_v01 as renderer
import render_test_fixtures_v01 as fixtures

VERSION='0.1.0'
QA_ROOT=core.base.ROOT/'data/qa/stage56'
REPORT='quality-report.v01.json'
TECH='technical-qa.v01.json'
PACKET='qa-packet.v01.json'
LIMITS={**core.DEFAULT_RESOURCES,'memory_mib':3072,'timeout_sec':180}
PARAMETERS={'audio_rate':48000,'audio_hop_sec':.02,'spectral_window_sec':.08,
            'quiet_rms':.0001,'visual_target_fps':4,'visual_width':64,'visual_height':64,
            'maximum_visual_samples':1000,'maximum_issues':256,'maximum_json_bytes':2097152}
DIMENSIONS=('technical_integrity','audio_continuity','visual_continuity','hook','story','pacing','captions','ending','factual_safety')
LIMITATIONS=[
    'Signal thresholds identify review candidates, not verified musical beats, phrase boundaries or editorial defects',
    'Fades/equal RMS/no clipping do not prove song, sung-vocal or speech continuity',
    'Visual measurements are downscaled/sampled, not pixel-perfect or editorial frame verification',
    'Source/manifest hashes and local replay prove consistency, not independent authentication',
    'Canonical semantics, speech classifications and factual claims remain model/unverified',
    'No OCR, word alignment, publication rights verification, engagement prediction or automatic revision',
    'CLI success is inspection completion only; all production/publishing eligibility remains false']


def read(path):
    path=core.safe_path(path)
    if path.stat().st_size>PARAMETERS['maximum_json_bytes']:raise core.Error('QA JSON limit')
    text=core.director.safe_text(path.read_text(),PARAMETERS['maximum_json_bytes'])
    try:data=json.loads(text,object_pairs_hook=core.base.unique_object,parse_float=core.base.finite_float,parse_constant=core.base.reject_constant)
    except (ValueError,RecursionError):raise core.Error('Malformed QA JSON') from None
    if not isinstance(data,dict):raise core.Error('QA object required')
    return data


def ref(path):return core.av.reference(core.safe_path(path))


def code_receipts():
    names=('scripts/video_quality_qa_v01.py','src/schemas/video-quality-report.v0.1.schema.json',
           'src/schemas/video-quality-human-feedback.v0.1.schema.json')
    return [ref(core.base.ROOT/p) for p in names]+core.code_receipts()


def same_reference(reference):
    if not isinstance(reference,dict) or set(reference)!={'path','sha256'} or ref(reference['path'])!=reference:
        raise core.Error('QA evidence fingerprint mismatch')


def verify_bundle(value):
    bundle=core.shared.directory(value)
    manifest_path=core.safe_path(bundle/renderer.MANIFEST)
    manifest=read(manifest_path);mode=manifest.get('authorization_mode')
    if mode not in ('TEST_ONLY','REAL_CONTENT_PREVIEW'):raise core.Error('Unsupported render receipt scope')
    schema='render-manifest.v0.1.schema.json' if mode=='TEST_ONLY' else 'render-preview-manifest.v0.1.schema.json'
    core.base.validate_object(manifest,core.base.load_schema(schema),'Render receipt')
    names={'plan':renderer.PLAN if mode=='TEST_ONLY' else 'preview-plan.v03.json','spec':renderer.SPEC,
           'timeline':renderer.TIMELINE,'manifest':renderer.MANIFEST}
    inputs={k:ref(bundle/n) for k,n in names.items()}
    plan=read(bundle/names['plan']);spec=read(bundle/names['spec']);timeline=read(bundle/names['timeline'])
    if (core.digest_object(plan)!=manifest['plan_sha256'] or core.digest_object(spec)!=manifest['execution_spec_sha256']
        or timeline!=core.compile_timeline(plan,spec) or manifest['timeline']!=timeline
        or manifest['source']!=plan['source'] or manifest['requested_operations']!=plan['variants'][0]['operations']
        or manifest['applied_operations']!=timeline['operations'] or manifest['verified_capabilities_used']!=timeline['required_capabilities']):
        raise core.Error('QA plan/spec/timeline/operation mismatch')
    source=core.safe_path(plan['source']['path']);output=core.safe_path(manifest['output']['path'],under=bundle)
    if output.parent!=bundle or output.name!=('render.mp4' if mode=='TEST_ONLY' else 'preview.mp4'):
        raise core.Error('QA output scope mismatch')
    if core.intake.gate.sha256_file(source)!=plan['source']['sha256'] or core.intake.gate.sha256_file(output)!=manifest['output']['sha256']:
        raise core.Error('QA source/output SHA mismatch')
    if output.stat().st_size!=manifest['output']['bytes']:raise core.Error('QA output byte size mismatch')
    inputs.update(source=ref(source),rendered_output=ref(output))
    if any(manifest['output'].get(k)!=v for k,v in core.media_info(output,LIMITS).items()):raise core.Error('QA output metadata mismatch')
    src_info=core.media_info(source,LIMITS)
    if any(src_info[k]!=plan['source'][k] for k in ('duration_sec','width','height','fps')):raise core.Error('QA source metadata mismatch')
    for receipt in manifest['code_receipts']:same_reference(receipt)
    if mode=='TEST_ONLY':
        identity=read(bundle/renderer.IDENTITY);inputs['fixture_identity']=ref(bundle/renderer.IDENTITY)
        assets={r['path']:core.safe_path(bundle/Path(r['path']).name) for r in spec['assets'].values()}
        fixtures.admit(identity,plan,spec,source,bundle,assets)
        if manifest['code_receipts']!=core.code_receipts():raise core.Error('QA stale fixture code receipt')
        canonical=None;speech={'status':'synthetic_non_speech','alignment_eligible':False}
        packet=None
    else:
        import render_showcase_preview_v01 as preview
        auth=read(bundle/preview.AUTH);packet=read(bundle/preview.PACKET);validation=read(bundle/preview.REPORT)
        core.base.validate_object(auth,core.base.load_schema('preview-authorization.v0.1.schema.json'),'Preview authorization')
        core.intake.validate_packet(packet)
        if (packet['source']!=plan['source'] or packet['source']['sha256']!=plan['source']['sha256']
            or manifest['evidence_packet_sha256']!=core.director.validator.packet_digest(packet)
            or plan['evidence_packet_sha256']!=manifest['evidence_packet_sha256']
            or manifest['authorization_sha256']!=core.digest_object(auth)
            or auth['source_sha256']!=plan['source']['sha256'] or auth['source_path']!=plan['source']['path']
            or auth['plan_sha256']!=manifest['plan_sha256'] or auth['execution_spec_sha256']!=manifest['execution_spec_sha256']
            or auth['evidence_packet_sha256']!=manifest['evidence_packet_sha256']
            or auth['output_directory']!=core.shared.relative(bundle)
            or manifest['code_receipts']!=preview.preview_code() or auth['code_receipts']!=manifest['code_receipts']
            or validation!=core.director.validator.validate_plan(plan,packet)
            or validation['blocking_findings'] or manifest['validation_status']!=validation['status']):
            raise core.Error('QA preview authorization/evidence/validation binding mismatch')
        if manifest['evidence_inputs']!=packet['inputs']:raise core.Error('QA render evidence ledger mismatch')
        for receipt in packet['inputs'].values():same_reference(receipt)
        same_reference(manifest['capabilities'])
        if auth['capabilities']!=manifest['capabilities']:raise core.Error('QA capability identity mismatch')
        capabilities=renderer.validate_registry(manifest['capabilities']['path'])
        if any(capabilities['operations'][name]['status']!='verified' for name in timeline['required_capabilities']):
            raise core.Error('QA required capability not verified')
        inputs.update({k:ref(bundle/n) for k,n in (('preview_permission_receipt',preview.AUTH),('director_packet',preview.PACKET),('plan_validation',preview.REPORT))})
        inputs.update({'evidence:'+k:r for k,r in packet['inputs'].items()})
        inputs['capabilities']=manifest['capabilities']
        canonical=packet['canonical'];speech=packet['speech']
    for record in spec['assets'].values():same_reference({'path':record['path'],'sha256':record['sha256']})
    return {'bundle':bundle,'manifest':manifest,'plan':plan,'spec':spec,'timeline':timeline,'source':source,
            'output':output,'source_info':src_info,'output_info':core.media_info(output,LIMITS),
            'inputs':inputs,'canonical':canonical,'speech':speech,'director_packet':packet}


def source_ranges(window,timeline):
    if window is None:return []
    result=[]
    for shot in timeline['shots']:
        a=max(window['start_sec'],shot['output_start_sec']);b=min(window['end_sec'],shot['output_end_sec'])
        if a>=b:continue
        start=shot['source_start_sec']+(a-shot['output_start_sec'])*shot['speed']
        end=shot['source_start_sec']+(b-shot['output_start_sec'])*shot['speed']
        # A planned freeze repeats the last retained source frame, not future time.
        result.append({'shot_id':shot['shot_id'],'source_start_sec':round(min(start,shot['source_end_sec']),6),
                       'source_end_sec':round(min(end,shot['source_end_sec']),6)})
    return result


def recommendation(target,change,operation=None,feasibility='requires_editorial_review'):
    return {'target':target,'change':change,'required_operation':operation,'feasibility':feasibility,'review_required':True}


def issue(category,event,description,window=None,*,origin='signal_measurement',severity='medium',evidence=None,
          confidence='low',cause='Uncertain; review actual media and context',fix=None):
    return {'issue_id':'pending','category':category,'severity':severity,'output_range':window,'source_ranges':[],
            'event_type':event,'evidence_refs':evidence or [],'detection_method':origin,'origin':origin,'confidence':confidence,
            'human_confirmation':'not_confirmed','description':description,'possible_cause':cause,'cause_confidence':'low',
            'recommendation':fix or recommendation('missing_evidence','Inspect actual media and context before revising'),
            'timing_precision':'signal_estimated' if origin=='signal_measurement' else 'approximate' if window else 'not_applicable',
            'review_required':True}


def runs(mask,times,step):
    result=[];start=None
    for i,yes in enumerate(list(mask)+[False]):
        if yes and start is None:start=i
        if not yes and start is not None:
            result.append({'start_sec':round(float(times[start]),6),'end_sec':round(float(times[i-1]+step),6)})
            start=None
    return result


def freeze_ranges(timeline):
    return [{'start_sec':s['freeze_output_start_sec'],'end_sec':s['output_end_sec']} for s in timeline['shots'] if s['freeze_sec']]


def contained(window,allowed):
    return any(a['start_sec']-.03<=window['start_sec'] and window['end_sec']<=a['end_sec']+.03 for a in allowed)


def frame_samples(path,duration,fps):
    raw,_=core.run(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time',
                    '-of','json',str(path)],LIMITS,max_bytes=2097152)
    data=json.loads(raw,object_pairs_hook=core.base.unique_object,parse_constant=core.base.reject_constant)
    times=np.asarray([float(f['best_effort_timestamp_time']) for f in data['frames']])
    if (not len(times) or len(times)>10800 or not np.isfinite(times).all() or times[0]<-.0001 or times[0]>1/fps
        or np.any(np.diff(times)<=0) or np.any(np.diff(times)>2/fps+.00001)
        or abs(len(times)-round(duration*fps))>2 or times[-1]>duration+.03):raise core.Error('QA invalid/missing output frame PTS')
    stride=max(1,math.ceil(fps/PARAMETERS['visual_target_fps']));selected=list(range(0,len(times),stride))
    if len(selected)>PARAMETERS['maximum_visual_samples']:raise core.Error('QA visual sampling limit')
    pixels,_=core.run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(path),'-map','0:v:0','-an',
            '-vf',f'select=not(mod(n\\,{stride})),scale=64:64:flags=area','-vsync','0','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],
            LIMITS,max_bytes=PARAMETERS['maximum_visual_samples']*12288)
    if len(pixels)!=len(selected)*12288:raise core.Error('QA visual sample/PTS count mismatch')
    samples=[];previous=None
    for i,index in enumerate(selected):
        frame=pixels[i*12288:(i+1)*12288];luma,hist,metrics=core.av.pixels_feature(frame,previous)
        dark=float((luma<26).mean());samples.append({'time_sec':round(float(times[index]),6),'frame_index':index,'dark_fraction':dark,**metrics})
        previous=(luma,hist,metrics['brightness'])
    return samples,{'decoded_frame_count':len(times),'sample_count':len(selected),'stride_frames':stride,
        'maximum_gap_sec':round(stride/fps,6),'sample_rgb_sha256':hashlib.sha256(pixels).hexdigest(),
        'precision':'sampled_decoded_frame_pts; no pixel-perfect/editorial boundary verification'}


def visual_analysis(samples,timeline,sampling):
    duration=timeline['expected_duration_sec'];step=sampling['maximum_gap_sec'];events=[];findings=[]
    times=[s['time_sec'] for s in samples]
    for w in runs([s['dark_fraction']>=.98 for s in samples],times,step):
        w['end_sec']=min(duration,w['end_sec'])
        events.append({'kind':'near_black_candidate','range':w,'confidence':'low','planned_freeze':contained(w,freeze_ranges(timeline))})
        if w['end_sec']-w['start_sec']>=.25:
            findings.append(issue('visual','near_black_review','Near-black sampled imagery; dark source lighting or intentional effects require context',w,evidence=['video.samples'],fix=recommendation('source_limitation','Compare dark imagery with source and editorial intent; do not automatically brighten cinematic scenes')))
    stable=[False]+[s['raw_difference']<.004 for s in samples[1:]]
    for w in runs(stable,times,step):
        w['end_sec']=min(duration,w['end_sec'])
        if w['end_sec']-w['start_sec']<.8:continue
        intended=contained(w,freeze_ranges(timeline));events.append({'kind':'planned_freeze' if intended else 'stable_visual_region','range':w,'confidence':'low'})
        if not intended:findings.append(issue('visual','static_or_duplicate_candidate','Sampled images are highly similar; this may be a static subject, not an encoder freeze',w,severity='info',evidence=['video.samples'],fix=recommendation('plan_change','Assess whether this stable view serves the hook/story; verify source motion before calling it a frozen-frame defect')))
    joins=[s['output_start_sec'] for s in timeline['shots'][1:]]
    for i,s in enumerate(samples[1:],1):
        if abs(s['brightness']-samples[i-1]['brightness'])>.15 or s['centered_difference']>.12:
            intended=any(abs(s['time_sec']-t)<=step+.04 for t in joins)
            w={'start_sec':samples[i-1]['time_sec'],'end_sec':min(duration,s['time_sec'])}
            events.append({'kind':'planned_transition_candidate' if intended else 'visual_change_candidate','range':w,
                           'confidence':'low','centered_difference':s['centered_difference'],'brightness_delta':s['brightness']-samples[i-1]['brightness']})
    # Reusing source intervals is measurable; similar-looking vehicles are semantic, not this detector.
    for i,s in enumerate(timeline['shots']):
        if any(max(s['source_start_sec'],p['source_start_sec'])<min(s['source_end_sec'],p['source_end_sec']) for p in timeline['shots'][:i]):
            w={'start_sec':s['output_start_sec'],'end_sec':s['output_end_sec']}
            findings.append(issue('visual','source_range_reuse','The plan reuses an earlier source interval; repetition may be intentional',w,origin='timeline_check',severity='low',evidence=['timeline'],fix=recommendation('plan_change','Review whether reuse helps meaning or adds unnecessary repetition')))
    return {'sampling':sampling,'samples':samples,'events':events[:128]},findings


def spectral(pcm,start,end,rate=48000):
    x=pcm[max(0,round(start*rate)):min(len(pcm),round(end*rate))]
    if len(x)<16:return np.zeros(24)
    n=min(len(x),8192);x=x[:n];power=np.abs(rfft(x*np.hanning(n)))**2
    edges=np.geomspace(1,len(power),25).astype(int);bands=np.array([power[a:b].sum() for a,b in zip(edges[:-1],edges[1:])])
    norm=np.linalg.norm(bands);return bands/norm if norm else bands


def audio_window(pcm,a,b):
    x=pcm[max(0,round(a*48000)):min(len(pcm),round(b*48000))]
    if not len(x):return {'rms':0.0,'peak':0.0}
    return {'rms':float(np.sqrt(np.mean(x*x))),'peak':float(np.max(np.abs(x)))}


def db(rms):return float(20*math.log10(max(rms,1e-9)))


def audio_analysis(pcm,timeline,*,source_pcm=None,audio_mode='preserve',operations=None):
    pcm=np.asarray(pcm,dtype=float);duration=timeline['expected_duration_sec'];hop=.02
    if not len(pcm) or not np.isfinite(pcm).all():raise core.Error('QA invalid audio PCM')
    count=min(math.ceil(duration/hop),math.ceil(len(pcm)/960));windows=[];events=[];findings=[];previous=None
    for i in range(count):
        a=i*hop;b=min(duration,(i+1)*hop);m=audio_window(pcm,a,b)
        spectrum=spectral(pcm,max(0,a-.04),min(duration,a+.04))
        difference=float(max(0,1-np.dot(spectrum,previous))) if previous is not None else 0.0
        flux=float(np.maximum(0,spectrum-previous).sum()) if previous is not None else 0.0
        x=pcm[max(0,i*960-1):min(len(pcm),(i+1)*960)];delta=float(np.max(np.abs(np.diff(x)))) if len(x)>1 else 0
        row={'time_sec':round(a,6),**m,'rms_dbfs':db(m['rms']),'spectral_distance':difference,'spectral_flux':flux,'max_sample_delta':delta}
        windows.append(row);previous=spectrum
        if difference>.45 or delta>.35:
            events.append({'kind':'acoustic_change_candidate','range':{'start_sec':round(max(0,a-.04),6),'end_sec':round(min(duration,a+.04),6)},
                           'spectral_distance':difference,'spectral_flux':flux,'max_sample_delta':delta,'confidence':'low'})
    allowed=freeze_ranges(timeline)
    for op in operations or []:
        if op.get('effective_kind')=='audio_fade' or (op.get('effective_kind') in ('audio_gain','audio_duck') and op['parameters'].get('gain_db',0)<=-18):
            allowed.append({'start_sec':op['output_start_sec'],'end_sec':op['output_end_sec']})
    quiet=runs([w['rms']<PARAMETERS['quiet_rms'] for w in windows],[w['time_sec'] for w in windows],hop)
    for w in quiet:
        w['end_sec']=min(duration,w['end_sec'])
        if w['end_sec']-w['start_sec']<.2:continue
        planned=contained(w,allowed) or audio_mode=='silent';source_quiet=None
        maps=source_ranges(w,timeline)
        if source_pcm is not None and maps:
            source_quiet=all(audio_window(source_pcm,m['source_start_sec'],m['source_end_sec'])['rms']<PARAMETERS['quiet_rms'] for m in maps if m['source_end_sec']>m['source_start_sec'])
        events.append({'kind':'planned_quiet' if planned else 'source_quiet_region' if source_quiet else 'unexplained_quiet_candidate','range':w,'confidence':'medium'})
        if not planned and not source_quiet:
            findings.append(issue('audio','unexpected_silence_candidate','Output near-silence is not explained by declared treatment or measured source quiet',w,evidence=['audio.metrics'],confidence='medium',fix=recommendation('renderer_adjustment','Inspect source/output audio mapping and gain/fade behavior before declaring a defect')))
    boundaries=[]
    for i,(outgoing,incoming) in enumerate(zip(timeline['shots'],timeline['shots'][1:])):
        t=incoming['output_start_sec'];a=max(0,t-.25);b=min(duration,t+.25)
        left=audio_window(pcm,a,max(a+.001,t-.05));right=audio_window(pcm,min(b-.001,t+.05),b)
        spec_l=spectral(pcm,a,t-.05);spec_r=spectral(pcm,t+.05,b)
        dip=audio_window(pcm,max(0,t-.05),min(duration,t+.05))
        jump=incoming['source_start_sec']-outgoing['source_end_sec']
        record={'boundary_id':f'audio.splice.{i}','output_time_sec':t,'output_range':{'start_sec':a,'end_sec':b},
            'source_out_point_sec':outgoing['source_end_sec'],'source_in_point_sec':incoming['source_start_sec'],
            'source_jump_sec':jump,'transition_type':outgoing['transition_out'],'overlap_sec':outgoing['overlap_sec'],
            'outgoing_level':left,'incoming_level':right,'level_difference_db':db(right['rms'])-db(left['rms']),
            'spectral_distance':float(max(0,1-np.dot(spec_l,spec_r))),'spectral_flux':float(np.maximum(0,spec_r-spec_l).sum()),
            'center_100ms':dip,'fade_present':any(o.get('effective_kind')=='audio_fade' and o['output_start_sec']<=t+.1 and o['output_end_sec']>=t-.1 for o in operations or []),
            'musical_phrase_continuity':'UNVERIFIED_REQUIRES_LISTENING','source_audio_comparison':None}
        if source_pcm is not None:
            record['source_audio_comparison']={'outgoing':audio_window(source_pcm,max(0,outgoing['source_end_sec']-.25),outgoing['source_end_sec']),
                'incoming':audio_window(source_pcm,incoming['source_start_sec'],incoming['source_start_sec']+.25)}
        boundaries.append(record)
        if abs(jump)>1/timeline['output_settings']['fps'] and audio_mode=='preserve':
            findings.append(issue('audio','discontinuous_source_audio_selection','Source-relative audio jumps at a visual join. Fades/level continuity cannot establish song or speech phrase coherence',record['output_range'],origin='timeline_check',evidence=[record['boundary_id'],'timeline'],confidence='high',cause='Outgoing and incoming visuals use noncontiguous source audio sections',fix=recommendation('plan_change','Review different in/out points or preserve a continuous source soundtrack bed; retain complete phrases where feasible','continuous_soundtrack_bed','requires_implementation')))
    peak=float(np.max(np.abs(pcm)))
    if peak>=.999:
        findings.append(issue('audio','potential_clipping','Decoded sample peak reaches clipping-risk threshold; this is not a true-peak/broadcast certification',{'start_sec':0,'end_sec':duration},severity='high',evidence=['audio.metrics'],confidence='medium',fix=recommendation('renderer_adjustment','Review gain/headroom and source distortion before changing audio','audio_gain','verified_current_capability')))
    if audio_window(pcm,max(0,duration-.4),max(.001,duration-.1))['rms']>.02:
        findings.append(issue('ending','active_audio_ending_review','Audio remains active near the final out-point; this does not independently prove phrase truncation',{'start_sec':max(0,duration-.4),'end_sec':duration},severity='low',evidence=['audio.metrics'],fix=recommendation('plan_change','Listen to ending and select a coherent phrase/out-point if needed')))
    stride=max(1,math.ceil(len(windows)/512))
    result={'status':'MEASURED','normalization':'FFmpeg mono 48000 Hz float32 PCM, verified zero presentation origin',
            'pcm_sha256':hashlib.sha256(np.asarray(pcm,dtype='<f4').tobytes()).hexdigest(),'sample_count':len(pcm),
            'rms':float(np.sqrt(np.mean(pcm*pcm))),'peak':peak,'window_sec':hop,'spectral_window_sec':.08,
            'full_window_count':len(windows),'reported_window_stride':stride,'windows':windows[::stride],
            'events':events[:64],'boundaries':boundaries,'musical_continuity_verified':False}
    return result,findings


def caption_analysis(plan,timeline):
    operations=[o for o in timeline['operations'] if o['effective_kind'] in ('overlay','subtitle')]
    checks=[];findings=[]
    for op in operations:
        try:
            core.checked_text(op['parameters']['caption']['text'],op['execution_parameters'].get('font_size_px',max(10,timeline['output_settings']['width']//12)),timeline['output_settings'])
            if not 0<=op['output_start_sec']<op['output_end_sec']<=timeline['expected_duration_sec']:raise core.Error('Caption timing')
            if 'caption_source_window' in op['execution_parameters']:
                shot=next(s for s in timeline['shots'] if s['shot_id']==op['shot_id'])
                if max(abs(x-y) for x,y in zip(core.source_window_to_output(shot,op['execution_parameters']['caption_source_window']),(op['output_start_sec'],op['output_end_sec'])))>1e-6:
                    raise core.Error('Caption source/output timing')
            checks.append({'operation_id':op['operation_id'],'layout_policy':'PASS','time_mapping':'PASS','raster_visibility':'UNVERIFIED_NO_OCR','word_accuracy':'UNVERIFIED'})
        except (core.Error,KeyError,TypeError,StopIteration):
            findings.append(issue('captions','caption_geometry_or_timing','Declared caption layout or source/output mapping fails policy',{'start_sec':max(0,op['output_start_sec']),'end_sec':min(timeline['expected_duration_sec'],op['output_end_sec'])},origin='deterministic_validation',severity='high',evidence=['timeline'],fix=recommendation('renderer_adjustment','Correct caption geometry/timing after independent text/word evidence review')))
    return {'status':'NOT_APPLICABLE' if not operations else 'NEEDS_REVIEW','scope':'Declared render-added captions; inherited on-screen text is not OCR-verified','checks':checks},findings


def human_findings(path,ctx):
    if not path:return None,[]
    data=read(path);core.base.validate_object(data,core.base.load_schema('video-quality-human-feedback.v0.1.schema.json'),'Human feedback')
    if data['source_sha256']!=ctx['plan']['source']['sha256'] or data['output_sha256']!=ctx['manifest']['output']['sha256']:
        raise core.Error('Human feedback media contamination')
    findings=[]
    for n,h in enumerate(data['observations']):
        w=h['output_range']
        if w is not None and not 0<=w['start_sec']<w['end_sec']<=ctx['timeline']['expected_duration_sec']:raise core.Error('Human timestamp invalid')
        f=issue(h['category'],'human_reported_quality_issue',h['description'],w,origin='human_feedback',severity=h['severity'],evidence=['human.feedback'],confidence='not_applicable',cause='Human experience reported in the user-supplied handoff; not independent acoustic/visual proof',fix=h['recommendation'])
        f['human_confirmation']=h['confirmation'];f['timing_precision']='approximate'
        findings.append(f)
    return data,findings


def dimension(status,origin,reason,refs=None,confidence='not_applicable'):
    return {'status':status,'provenance':origin,'confidence':confidence,'reason':reason,'evidence_refs':refs or []}


def assess(report):
    issues=report['issues'];critical=any(i['severity']=='critical' for i in issues)
    known_revision=any(i['origin']=='human_feedback' and i['severity'] in ('high','medium') for i in issues)
    high_signal=any(i['origin']!='human_feedback' and i['severity']=='high' for i in issues)
    model_revision=any(i['origin']=='model_unverified' and i['severity']=='high' for i in issues)
    report['technical_qa_status']='BLOCKED' if critical else 'NEEDS_REVIEW' if any(i['origin'] in ('signal_measurement','timeline_check','deterministic_validation') and i['severity']!='info' for i in issues) else 'PASS'
    report['human_review_status']='REVISE' if known_revision else 'NEEDS_REVIEW' if report['human']['performed'] else 'INCOMPLETE'
    report['overall_decision']='BLOCKED' if critical else 'REVISE' if known_revision or high_signal or model_revision or report['ai_editorial_status'] in ('REVISE','BLOCKED') else 'INCOMPLETE' if report['ai_editorial_status']=='INCOMPLETE' else 'NEEDS_REVIEW' if issues else 'PASS'
    for key in DIMENSIONS:
        categories={'technical_integrity':'integrity','audio_continuity':'audio','visual_continuity':'visual'}.get(key,key)
        group=[i for i in issues if i['category']==categories]
        if group:
            human=[i for i in group if i['origin']=='human_feedback'];status='BLOCKED' if any(i['severity']=='critical' for i in group) else 'REVISE' if human and any(i['severity'] in ('high','medium') for i in human) else 'NEEDS_REVIEW'
            origins={i['origin'] for i in group}
            origin='mixed' if len(origins)>1 else next(iter(origins))
            if origin=='timeline_check':origin='deterministic_validation'
            report['dimensions'][key]=dimension(status,origin,group[0]['description'],list(dict.fromkeys(r for i in group for r in i['evidence_refs'])))
    return report


def validate_report(report):
    core.base.validate_object(report,core.base.load_schema('video-quality-report.v0.1.schema.json'),'QA report')
    mode=report['ai'].get('mode')
    if mode not in ('not_run','offline_fixture','saved_response_replay','live_multimodal'):raise core.Error('QA unknown AI provenance mode')
    if report['ai_editorial_status']!='INCOMPLETE':
        for role,key,reference in (('edited_output','output_review',report['rendered_output']),('original_source','source_review',report['source'])):
            observed=report['ai'].get(key)
            if (mode!='live_multimodal' or not isinstance(observed,dict) or not reference
                or observed.get('media_role')!=role or observed.get('media_sha256')!=reference['sha256']
                or observed.get('media_observation',{}).get('video_examined') is not True):
                raise core.Error('QA completed AI review lacks bound media observations')
    duration=report['technical'].get('duration_sec',180);ledger=report['evidence_ledger'];ids=set()
    for f in report['issues']:
        if f['issue_id'] in ids:raise core.Error('QA duplicate issue ID')
        ids.add(f['issue_id']);w=f['output_range']
        if w and not 0<=w['start_sec']<w['end_sec']<=duration:raise core.Error('QA issue timestamp invalid')
        if any(r not in ledger for r in f['evidence_refs']):raise core.Error('QA ungrounded finding')
        if f['origin']!='human_feedback' and f['human_confirmation']!='not_confirmed':raise core.Error('QA fabricated human confirmation')
        for mapped in f['source_ranges']:
            if mapped['source_start_sec']>mapped['source_end_sec']:raise core.Error('QA inverted source range')
        timeline=report['technical'].get('timeline')
        if timeline and f['source_ranges']!=source_ranges(w,timeline):raise core.Error('QA incorrect source mapping')
    for d in report['dimensions'].values():
        if any(r not in ledger for r in d['evidence_refs']):raise core.Error('QA ungrounded dimension')
    if any(f['severity']=='critical' for f in report['issues']) and report['overall_decision']!='BLOCKED':raise core.Error('QA critical defect hidden')
    if any(f['origin']=='human_feedback' and f['severity'] in ('high','medium') for f in report['issues']) and report['overall_decision'] not in ('REVISE','BLOCKED'):
        raise core.Error('QA human defect hidden')
    if report['ai'].get('mode') in ('not_run','offline_fixture','saved_response_replay') and report['ai_editorial_status']!='INCOMPLETE':raise core.Error('QA offline response promoted to live review')
    if report['ai_editorial_status'] in ('REVISE','BLOCKED') and report['overall_decision'] not in ('REVISE','BLOCKED'):raise core.Error('QA model revision hidden')
    if any(f['origin']=='human_feedback' for f in report['issues']) and not report['human'].get('performed'):raise core.Error('QA human provenance missing')
    if report['integrity'].get('status')=='PASS' and (not report['source'] or not report['rendered_output']):raise core.Error('QA source/output binding missing')
    core.director.safe_text(json.dumps(report,allow_nan=False),PARAMETERS['maximum_json_bytes'])
    return report


def empty_report():
    return {'contract_version':VERSION,'source':None,'rendered_output':None,'inputs':{},'evidence_ledger':{},'integrity':{},'technical':{},
            'ai':{'mode':'not_run','video_observation':'UNAVAILABLE','audio_listening':'UNAVAILABLE','reason':'No authorized multimodal inference has occurred'},
            'human':{'performed':False,'provenance':None},'dimensions':{k:dimension('UNAVAILABLE','unavailable','Assessment unavailable') for k in DIMENSIONS},
            'issues':[],'technical_qa_status':'INCOMPLETE','ai_editorial_status':'INCOMPLETE','human_review_status':'INCOMPLETE','overall_decision':'INCOMPLETE',
            'production_eligible':False,'publishing_eligible':False,'render_approved':False,'publish_approved':False,
            'limitations':list(LIMITATIONS),'processing':{},'code_receipts':code_receipts()}


def evaluate(bundle,*,feedback=None):
    started=time.monotonic();report=empty_report();ctx=None
    try:
        ctx=verify_bundle(bundle)
        report.update(source=ctx['inputs']['source'],rendered_output=ctx['inputs']['rendered_output'],inputs=copy.deepcopy(ctx['inputs']))
        ledger={'media.source':ctx['inputs']['source'],'media.output':ctx['inputs']['rendered_output'],
                'timeline':ctx['inputs']['timeline'],'video.samples':{'method':'sampled_pixels'},'audio.metrics':{'method':'normalized_PCM'},
                'captions':{'method':'declared_caption_policy'},'canonical':{'basis':'model_unverified'},'speech.eligibility':{'basis':'existing_gate'}}
        report['evidence_ledger']=ledger
        report['integrity']={'status':'PASS','source_output_sha_bound':True,'manifest_plan_spec_timeline_checked':True,
                             'capability_receipts_checked':True,'source_metadata_checked':True,'production_approval_inherited':False}
        # Existing strict verifier covers full decode, stream format and actual PTS.
        try:verified=core.verify_output(ctx['output'],ctx['timeline'],ctx['output_info']['audio_present'],LIMITS)
        except core.Error as error:
            if str(error)!='Output audio clipping risk detected':raise
            verified={'status':'CLIPPING_GUARD_TRIGGERED','decode_and_metadata_checks_reached':True}
        samples,sampling=frame_samples(ctx['output'],ctx['timeline']['expected_duration_sec'],ctx['output_info']['fps'])
        video,findings=visual_analysis(samples,ctx['timeline'],sampling)
        audio={'status':'NOT_APPLICABLE','reason':'No rendered audio stream','boundaries':[]}
        if ctx['output_info']['audio_present']:
            source_pcm=np.asarray(core.audio_pcm(ctx['source'],LIMITS),dtype=float) if ctx['source_info']['audio_present'] else None
            audio,more=audio_analysis(core.audio_pcm(ctx['output'],LIMITS),ctx['timeline'],source_pcm=source_pcm,
                audio_mode=ctx['spec']['output']['audio_mode'],operations=ctx['timeline']['operations']);findings+=more
        for b in audio['boundaries']:ledger[b['boundary_id']]={'method':'audio_timeline_boundary','measurements':b}
        captions,more=caption_analysis(ctx['plan'],ctx['timeline']);findings+=more
        speech=ctx['speech']
        if ctx['canonical'] and speech['requirements']['overall_requirement']!='not_required' and not speech['eligibility']['speech_alignment']:
            findings.append(issue('audio','speech_boundary_unverified','Speech-related boundaries lack eligible alignment; energy peaks/pauses cannot prove sentence-safe cuts',origin='deterministic_validation',severity='low',evidence=['speech.eligibility'],fix=recommendation('missing_evidence','Obtain independent text/timing/context review before speech-sensitive revisions')))
        human,more=human_findings(feedback,ctx);findings+=more
        if human:
            report['inputs']['human_feedback']=ref(feedback);ledger['human.feedback']=ref(feedback)
            report['human']={'performed':True,'provenance':human['provenance'],'feedback_ref':ref(feedback),'claim_scope':'Reported human experience, independent from machine observations'}
        technical={'duration_sec':ctx['timeline']['expected_duration_sec'],'verification':verified,'video':video,'audio':audio,'captions':captions,
                   'timeline':ctx['timeline'],'speech':speech,'parameters':PARAMETERS,'geometry_policy_checked':True,
                   'pixel_perfect_crop_or_stretch_certification':'UNAVAILABLE','factual_claims_verified':False}
        report['technical']=technical
        report['dimensions']['technical_integrity']=dimension('PASS','deterministic_validation','Source/output receipts, stream metadata, full decode and PTS checks passed',['media.output','timeline'],'high')
        report['dimensions']['captions']=dimension(captions['status'],'deterministic_validation',captions['scope'],['captions'])
        report['dimensions']['audio_continuity']=dimension('NEEDS_REVIEW' if ctx['output_info']['audio_present'] else 'NOT_APPLICABLE','signal_measurement','Signal analysis cannot verify phrase/music continuity' if ctx['output_info']['audio_present'] else 'No audio stream',['audio.metrics'])
        priority={'critical':0,'high':1,'medium':2,'low':3,'info':4}
        findings=sorted(findings,key=lambda f:(0 if f['severity']=='critical' else 1 if f['origin']=='human_feedback' else 2,priority[f['severity']]))
        for i,f in enumerate(findings):f['issue_id']=f'qa-{i+1:04d}';f['source_ranges']=source_ranges(f['output_range'],ctx['timeline'])
        report['issues']=findings[:PARAMETERS['maximum_issues']]
        for name,receipt in report['inputs'].items():same_reference(receipt)
        if ctx['manifest']['code_receipts']!=read(ctx['bundle']/renderer.MANIFEST)['code_receipts']:raise core.Error('Render receipt changed during QA')
        assess(report)
    except (core.Error,OSError,ValueError,TypeError,KeyError,RecursionError):
        report['integrity']={'status':'BLOCKED','reason':'Source/output/receipt/temporal/decode validation failure; raw diagnostics suppressed'}
        report['evidence_ledger']['integrity.failure']={'method':'deterministic_validation'}
        report['issues']=[issue('integrity','integrity_or_decode_failure','Review blocked by media, receipt, timing or decoding failure',origin='deterministic_validation',severity='critical',evidence=['integrity.failure'],confidence='high',fix=recommendation('missing_evidence','Restore trustworthy source/output receipts or investigate corrupted media; do not infer editorial approval'))]
        report['issues'][0]['issue_id']='qa-blocked-0001';assess(report)
    report['processing']={'elapsed_sec':round(time.monotonic()-started,3),'resources':LIMITS,'network_requests':0,'new_render_performed':False}
    validate_report(report)
    return report,ctx


def packet_for(report,ctx):
    if report['integrity']['status']!='PASS' or ctx is None:raise core.Error('Cannot prepare model review of blocked evidence')
    audio=report['technical']['audio'];video=report['technical']['video']
    packet={'contract_version':VERSION,'source':report['source'],'rendered_output':report['rendered_output'],
            'source_info':ctx['source_info'],'output_info':ctx['output_info'],'inputs':report['inputs'],
            'editorial_intent':ctx['plan']['variants'][0]['editorial_concept'],'timeline':ctx['timeline'],
            'canonical_context':{'status':'model_unverified','content_profile':ctx['canonical']['content_profile'] if ctx['canonical'] else None},
            'technical_context':{'video_events':video['events'][:32],'video_sampling':video['sampling'],
                'audio_status':audio['status'],'audio_boundaries':audio['boundaries'],'audio_events':audio.get('events',[])[:24],
                'caption_status':report['technical']['captions']['status']},
            'evidence_ledger':{k:v for k,v in report['evidence_ledger'].items() if k!='human.feedback'},
            'comparison_policy':'Separate full-video calls, later timestamp correlation; no direct joint observation',
            'human_feedback_supplied_to_model':False,'production_eligible':False,'publishing_eligible':False}
    # Human feedback file remains an integrity receipt, not prompt information.
    packet['inputs']={k:v for k,v in packet['inputs'].items() if k!='human_feedback'}
    core.director.safe_text(json.dumps(packet,allow_nan=False),65536)
    return packet


def save(bundle,output,*,feedback=None):
    output=core.new_directory(output,QA_ROOT)
    report,ctx=evaluate(bundle,feedback=feedback)
    artifacts={REPORT:report,TECH:report['technical']}
    if report['integrity']['status']=='PASS':artifacts[PACKET]=packet_for(report,ctx)
    artifacts['qa-generation-provenance.v01.json']={'contract_version':VERSION,'mode':'offline_technical_qa',
        'source':report['source'],'rendered_output':report['rendered_output'],'inputs':report['inputs'],'code_receipts':code_receipts(),
        'artifacts':{name:{'path':core.shared.relative(output/name),
            'sha256':hashlib.sha256((json.dumps(value,ensure_ascii=True,indent=2,allow_nan=False)+'\n').encode()).hexdigest()} for name,value in artifacts.items()},
        'live_inference_performed':False,'production_eligible':False,'publishing_eligible':False}
    core.director.publish(output,artifacts)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True);parser.add_argument('--output',required=True);parser.add_argument('--feedback')
    args=parser.parse_args(argv)
    try:
        result=save(args.bundle,args.output,feedback=args.feedback)
        print(json.dumps({'overall_decision':result['overall_decision'],'technical_status':result['technical_qa_status'],
                          'ai_editorial_status':result['ai_editorial_status'],'production_eligible':False,'publishing_eligible':False}))
        return 2 if result['overall_decision']=='BLOCKED' else 0
    except (core.Error,OSError,ValueError,TypeError,KeyError):
        print('BLOCKED: QA admission/resource/output failure; raw diagnostics suppressed',file=sys.stderr);return 1


if __name__=='__main__':
    with core.intake.processing_deadline(600):raise SystemExit(main())
