"""Versioned source-audio extension of the Stage 5.5 FFmpeg compiler.

Legacy compiler/receipts remain unchanged. Only new private-preview admission
and one continuous source-audio filter are added; visual operations use V0.1.
"""
import copy
import hashlib
import math
import os
from pathlib import Path
import resource
import tempfile
import time

import numpy as np
from scipy.signal import correlate, correlation_lags
import revision_intelligence_v01 as intelligence
import render_video_v01 as renderer
import render_test_fixtures_v01 as fixtures

core=intelligence.core
qa=intelligence.qa
VERSION='0.2.0'
MANIFEST='render-revision-manifest.v02.json'
PLAN='editing-plan.v03.json'
SPEC='execution-spec.v02.json'
TIMELINE='timeline.v02.json'
LIMITS={**core.DEFAULT_RESOURCES,'memory_mib':3072,'timeout_sec':180}
AUDIO_KINDS={'audio_gain','audio_duck','denoise','audio_fade','normalization','music_bed','sound_effect'}


def code_receipts():
    return core.code_receipts()+[qa.ref(core.base.ROOT/p) for p in (
        'scripts/renderer_revision_v02.py','scripts/revision_intelligence_v01.py',
        'src/schemas/revision-workflow.v0.1.schema.json')]


def original_audio(source):
    return {'mode':'original','source':{k:source[k] for k in ('path','sha256')},'source_range':None,
        'gain_db':0,'fade_in_sec':0,'fade_out_sec':0,'mix_original':False,'original_gain_db':0,
        'selection_basis':'model_candidate','evidence_refs':[],'phrase_verified':False,
        'publication_rights_verified':False,'review_required':True}


def spec_for(plan,audio,parameters=None,*,output=None,limits=None):
    visual={'contract_version':core.VERSION,'plan_sha256':core.digest_object(plan),
        'variant_id':plan['variants'][0]['variant_id'],'output':{**core.DEFAULT_OUTPUT,**(output or {})},
        'resources':{**LIMITS,**(limits or {})},'operation_parameters':parameters or {},'assets':{}}
    return intelligence.check('execution',{'contract_version':VERSION,'visual_spec':visual,'audio_timeline':audio})


def compile_timeline(plan,spec):
    intelligence.check('execution',spec)
    timeline=core.compile_timeline(plan,spec['visual_spec'])
    audio=spec['audio_timeline'];duration=timeline['expected_duration_sec']
    if audio['source']!={k:plan['source'][k] for k in ('path','sha256')}:
        raise core.Error('Independent soundtrack source identity mismatch')
    if spec['visual_spec']['assets']:raise core.Error('Revision audio extension accepts no external assets')
    if audio['mode']=='original':
        if audio['source_range'] is not None or audio['mix_original'] or any(audio[k]!=0 for k in ('gain_db','fade_in_sec','fade_out_sec','original_gain_db')):
            raise core.Error('Original audio mode has contradictory bed parameters')
        mapping={'mode':'per_shot_source','source':audio['source'],'segments':[
            {'source_start_sec':s['source_start_sec'],'source_end_sec':s['source_end_sec'],
             'output_start_sec':s['output_start_sec'],'output_end_sec':s['output_end_sec'],'speed':s['speed']}
            for s in timeline['shots']]}
    else:
        window=audio['source_range']
        if not window or not 0<=window['start_sec']<window['end_sec']<=plan['source']['duration_sec']:
            raise core.Error('Continuous source audio range invalid')
        if abs(window['end_sec']-window['start_sec']-duration)>1e-6:
            raise core.Error('Continuous source audio duration must equal output; no loop/pad substitution')
        if audio['fade_in_sec']+audio['fade_out_sec']>=duration:raise core.Error('Audio fades consume the passage')
        if timeline['output_settings']['audio_mode']!='preserve':raise core.Error('Silent output contradicts source audio bed')
        if not audio['mix_original'] and any(op['effective_kind'] in AUDIO_KINDS for op in timeline['operations']):
            raise core.Error('Replacement soundtrack cannot silently discard per-shot audio operations')
        if not audio['mix_original'] and audio['original_gain_db']!=0:raise core.Error('Orphan original mix gain')
        mapping={'mode':'continuous_source','source':audio['source'],'source_start_sec':window['start_sec'],
            'source_end_sec':window['end_sec'],'output_start_sec':0,'output_end_sec':duration,'speed':1,
            'gain_db':audio['gain_db'],'fade_in_sec':audio['fade_in_sec'],'fade_out_sec':audio['fade_out_sec'],
            'mix_original':audio['mix_original'],'original_gain_db':audio['original_gain_db'],
            'phrase_verified':False,'publication_rights_verified':False}
        timeline['required_capabilities']=sorted(set(timeline['required_capabilities'])|{'continuous_source_audio'})
    timeline['audio_timeline']=mapping
    return timeline


def validate_source_audio(source,plan,spec):
    source=core.safe_path(source)
    if core.intake.gate.sha256_file(source)!=plan['source']['sha256']:raise core.Error('Revision source SHA mismatch')
    info=core.media_info(source,spec['visual_spec']['resources'])
    if any(info[k]!=plan['source'][k] for k in ('duration_sec','width','height','fps')):raise core.Error('Revision source metadata mismatch')
    if spec['audio_timeline']['mode']=='continuous_source':
        if not info['audio_present']:raise core.Error('Continuous soundtrack requires original audio stream')
        if spec['audio_timeline']['source_range']['end_sec']>info['audio_duration_sec']+.0001:
            raise core.Error('Original audio stream is shorter than requested source range')
        if not spec['audio_timeline']['mix_original']:
            window=spec['audio_timeline']['source_range'];pcm=np.asarray(core.audio_pcm(source,spec['visual_spec']['resources']))
            segment=pcm[round(window['start_sec']*48000):round(window['end_sec']*48000)]
            if not len(segment) or float(np.max(np.abs(segment)))*10**(spec['audio_timeline']['gain_db']/20)>=.95:
                raise core.Error('Continuous soundtrack lacks safe decoded-sample headroom')
    return info


def filter_graph(timeline,source_has_audio,work,spec):
    audio=spec['audio_timeline'];legacy=copy.deepcopy(timeline);visual_spec=copy.deepcopy(spec['visual_spec'])
    if audio['mode']=='original':return core.filter_graph(legacy,source_has_audio,work,visual_spec)
    if not source_has_audio:raise core.Error('Missing continuous source audio stream')
    if not audio['mix_original']:
        legacy['output_settings']['audio_mode']='silent';visual_spec['output']['audio_mode']='silent'
    graph,_,assets,text=core.filter_graph(legacy,source_has_audio,work,visual_spec)
    if assets:raise core.Error('External assets cannot enter continuous-source preview')
    if audio['mix_original']:graph=graph.replace('[aout]','[shot_audio]')
    n=core.n;window=audio['source_range'];duration=timeline['expected_duration_sec']
    filters=[f'atrim=start={n(window["start_sec"])}:end={n(window["end_sec"])}','asetpts=PTS-STARTPTS',
        'aformat=sample_rates=48000:channel_layouts=stereo',f'volume={n(audio["gain_db"])}dB']
    if audio['fade_in_sec']:filters.append(f'afade=t=in:st=0:d={n(audio["fade_in_sec"])}')
    if audio['fade_out_sec']:filters.append(f'afade=t=out:st={n(duration-audio["fade_out_sec"])}:d={n(audio["fade_out_sec"])}')
    filters += [f'atrim=duration={n(duration)}','asetpts=PTS-STARTPTS','aresample=48000']
    label='continuous_bed' if audio['mix_original'] else 'aout'
    graph+=';\n[0:a]'+','.join(filters)+'['+label+']'
    if audio['mix_original']:
        graph+=f';\n[shot_audio]volume={n(audio["original_gain_db"])}dB[original_mix];[original_mix][continuous_bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,atrim=duration={n(duration)}[aout]'
    return graph,True,assets,text


def encode(source,plan,spec,work,*,mode,context):
    """New admission wrapper, same V0.1 visual compiler/FFmpeg/resource verifier."""
    work=core.safe_path(Path(work)/'render.mp4',output=True).parent
    if any(c in str(work) for c in ":,;[]'\\\n\r") or not work.name.startswith('.revision-work-'):
        raise core.Error('Revision encoding requires a private filter-safe work directory')
    timeline=compile_timeline(plan,spec);limits=spec['visual_spec']['resources']
    info=validate_source_audio(source,plan,spec)
    if mode=='TEST_ONLY':
        if not work.is_relative_to(core.TEST_ROOT):raise core.Error('Synthetic revision work outside test root')
        fixtures.admit(context['identity'],plan,spec['visual_spec'],source,context['output'],{})
        expected=fixture_audio(plan['source'],context['fixture'])
        if spec['audio_timeline']!=expected:raise core.Error('Only the closed synthetic audio recipe may execute')
    elif mode=='STAGE57_PRIVATE_PREVIEW':
        if not work.is_relative_to(intelligence.RENDER_ROOT):raise core.Error('Real revision work outside preview root')
        from run_revision_loop_v01 import render_admission
        render_admission(context,plan,spec,source)
    elif mode=='STAGE59_PRIVATE_PREVIEW':
        from run_stage59_showcase_v01 import RENDER_ROOT,render_admission
        if not work.is_relative_to(RENDER_ROOT):raise core.Error('Stage 5.9 work outside preview root')
        render_admission(context,plan,spec,source)
    elif mode=='AUTOMATIC_PRIVATE_PREVIEW':
        from automatic_editing_validation_v01 import admit,ROOT
        if not work.is_relative_to(ROOT):raise core.Error('Automatic preview work outside Stage 5.9 root')
        timeline=admit(context,plan,spec,source,timeline)
    else:raise core.Error('Revision encoding has no production or arbitrary-force mode')
    core.disk_preflight(work,limits)
    graph,audio,_,_=filter_graph(timeline,info['audio_present'],work,spec)
    script=work/'filters.ffgraph';script.write_text(graph)
    o=timeline['output_settings'];output=work/'render.mp4'
    # Only encoder command emission is adapted for the new admission. Source
    # ranges, effects, mapping, subprocess controls and decode checks are shared.
    arguments=['-protocol_whitelist','file,pipe','-i',str(source),'-filter_complex_script',str(script),'-map','[vout]']
    if audio:arguments+=['-map','[aout]','-c:a','aac','-b:a',str(o['audio_bitrate_kbps'])+'k','-ar','48000','-ac','2']
    else:arguments+=['-an']
    arguments+=['-c:v','libx264','-preset',o['preset'],'-crf',str(o['crf']),'-pix_fmt','yuv420p','-r',str(o['fps']),
        '-threads',str(limits['threads']),'-movflags','+faststart','-map_metadata','-1',
        '-metadata','title='+('TEST_ONLY synthetic source-audio fixture' if mode=='TEST_ONLY' else 'PREVIEW_ONLY NOT_APPROVED_FOR_PUBLICATION'),
        '-metadata','comment=Private preview; human review and publication rights pending',str(output)]
    before=resource.getrusage(resource.RUSAGE_CHILDREN);_,elapsed=core.ffmpeg(arguments,work,limits);after=resource.getrusage(resource.RUSAGE_CHILDREN)
    if output.stat().st_size>limits['max_output_bytes']:raise core.Error('Revision output exceeds file limit')
    verified=core.verify_output(output,timeline,audio,limits)
    mapping=measure_audio_mapping(source,output,timeline,spec) if audio else {'status':'NOT_APPLICABLE'}
    execution={'elapsed_sec':round(elapsed,3),'child_user_cpu_sec':round(after.ru_utime-before.ru_utime,3),
        'child_system_cpu_sec':round(after.ru_stime-before.ru_stime,3),'child_max_rss_kib':after.ru_maxrss,
        'max_rss_scope':'Cumulative child maximum for this Python invocation','limits':limits,
        'filter_graph_sha256':hashlib.sha256(graph.encode()).hexdigest()}
    return output,timeline,verified,mapping,execution


def measure_audio_mapping(source,output,timeline,spec):
    audio=spec['audio_timeline']
    if audio['mode']=='original':return {'status':'PER_SHOT_SOURCE_MAPPING','musical_phrase_verified':False}
    if audio['mix_original']:return {'status':'CONTINUOUS_BED_MIXED_WITH_SHOT_AUDIO','waveform_equivalence':'NOT_ASSERTED_FOR_MIX','musical_phrase_verified':False}
    limits=spec['visual_spec']['resources'];source_pcm=np.asarray(core.audio_pcm(source,limits),dtype=float)
    pcm=np.asarray(core.audio_pcm(output,limits),dtype=float);duration=timeline['expected_duration_sec'];rate=48000
    centers=[max(.4,audio['fade_in_sec']+.3),duration/2,min(duration-.4,duration-audio['fade_out_sec']-.3)]
    centers += [s['output_start_sec'] for s in timeline['shots'][1:]]
    records=[]
    for center in sorted(set(centers)):
        if center-.12<audio['fade_in_sec'] or center+.12>duration-audio['fade_out_sec']:continue
        start=round((center-.1)*rate);end=round((center+.1)*rate)
        reference_start=round((audio['source_range']['start_sec']+center-.1)*rate)
        expected=source_pcm[reference_start:reference_start+end-start]*10**(audio['gain_db']/20)
        actual=pcm[start:end]
        if len(actual)!=len(expected) or len(actual)<960:raise core.Error('Audio mapping sample range missing')
        if np.linalg.norm(expected)<1e-6:
            if np.sqrt(np.mean(actual*actual))>.001:raise core.Error('Expected source silence mapping failed')
            records.append({'output_time_sec':center,'status':'SOURCE_QUIET','correlation':None});continue
        values=correlate(actual,expected,mode='full',method='fft');lags=correlation_lags(len(actual),len(expected),mode='full')
        usable=np.abs(lags)<=1024;index=int(np.argmax(values[usable]));lag=int(lags[usable][index])
        normalized=float(values[usable][index]/max(1e-12,np.linalg.norm(actual)*np.linalg.norm(expected)))
        ratio=float(np.linalg.norm(actual)/max(1e-12,np.linalg.norm(expected)))
        if normalized<.9 or not .75<ratio<1.25:raise core.Error('Decoded audio does not match declared continuous source mapping')
        records.append({'output_time_sec':center,'source_time_sec':audio['source_range']['start_sec']+center,
            'correlation':normalized,'best_lag_samples':lag,'rms_ratio':ratio,'status':'LOSSY_SIGNAL_MAPPING_CONSISTENT'})
    if not records:raise core.Error('Audio mapping verification has insufficient usable samples')
    return {'status':'CONTINUOUS_SOURCE_MAPPING','rate':rate,'window_sec':.2,'maximum_lag_samples':1024,
        'records':records,'musical_phrase_verified':False,
        'limitations':['Lossy AAC sample correlation, not PCM identity or musical phrasing proof','Endpoint fades excluded from correlation windows']}


def fixture_audio(source,name):
    if name not in ('replace','mix'):raise core.Error('Unknown closed soundtrack fixture')
    result=original_audio(source)
    result.update(mode='continuous_source',source_range={'start_sec':0,'end_sec':6},gain_db=-8,
        fade_in_sec=.25,fade_out_sec=.3,mix_original=name=='mix',original_gain_db=-18 if name=='mix' else 0,
        selection_basis='synthetic_fixture',evidence_refs=['synthetic.source'])
    return result


def fixture_measurements(source,video,timeline,spec):
    from scipy.fft import rfft,rfftfreq
    limits=spec['visual_spec']['resources'];pcm=np.asarray(core.audio_pcm(video,limits),dtype=float)
    original=np.asarray(core.audio_pcm(source,limits),dtype=float)
    frequencies=[]
    for center in (1,3,5):
        segment=pcm[round((center-.08)*48000):round((center+.08)*48000)]
        frequencies.append(float(rfftfreq(len(segment),1/48000)[int(np.argmax(np.abs(rfft(segment*np.hanning(len(segment))))))]))
    if any(abs(a-b)>15 for a,b in zip(frequencies,[440,660,880])):raise core.Error('Synthetic bed is not independent of reordered visuals')
    def rms(values,a,b):return float(np.sqrt(np.mean(values[round(a*48000):round(b*48000)]**2)))
    ratio=rms(pcm,.6,1.4)/rms(original,.6,1.4)
    if not .35<ratio<.55:raise core.Error('Synthetic continuous gain mismatch')
    if not spec['audio_timeline']['mix_original']:
        if rms(pcm,.01,.03)>=rms(pcm,.6,.8)*.3 or rms(pcm,5.98,5.995)>=rms(pcm,5,5.2)*.3:
            raise core.Error('Synthetic endpoint fades not measured')
    colors=[]
    for center in (1,3,5):
        pixels=np.frombuffer(core.frame_rgb(video,center,limits=limits),dtype=np.uint8).reshape(320,180,3)
        colors.append(int(np.argmax(pixels[180:220,80:110].mean(axis=(0,1)))))
    if colors!=[2,0,1]:raise core.Error('Legacy visual ordering changed in soundtrack extension')
    peak=float(np.max(np.abs(pcm)))
    if peak>=.999:raise core.Error('Synthetic source bed clipped')
    return {'audio_tones_hz':frequencies,'visual_scene_order':colors,'gain_ratio':ratio,'peak_linear':peak,
        'endpoint_fades_measured':not spec['audio_timeline']['mix_original'],
        'mix_original':spec['audio_timeline']['mix_original'],'musical_phrase_verified':False}


def publish(output,binaries,artifacts,under):
    output=core.new_directory(output,under);output.parent.mkdir(parents=True,exist_ok=True);output.mkdir();created=[]
    try:
        for name,path in binaries.items():
            if Path(name).name!=name:raise core.Error('Unsafe revision output filename')
            dest=core.safe_path(output/name,output=True,under=under)
            with Path(path).open('rb') as handle:os.fsync(handle.fileno())
            os.link(path,dest);created.append(dest)
        for name,data in artifacts.items():
            if Path(name).name!=name:raise core.Error('Unsafe revision artifact filename')
            dest=core.safe_path(output/name,output=True,under=under);core.shared.write_json(dest,data);created.append(dest)
    except BaseException:
        for path in created:path.unlink(missing_ok=True)
        output.rmdir();raise
    return output


def self_test(name,output):
    output=core.new_directory(output,core.TEST_ROOT);output.parent.mkdir(parents=True,exist_ok=True)
    with renderer.render_lock(),tempfile.TemporaryDirectory(dir=output.parent,prefix='.revision-work-') as temporary:
        work=Path(temporary);identity,plan,visual,source,_=fixtures.create(work,'basic',output)
        spec={'contract_version':VERSION,'visual_spec':visual,'audio_timeline':fixture_audio(plan['source'],name)}
        video,timeline,verification,mapping,execution=encode(source,plan,spec,work,mode='TEST_ONLY',
            context={'identity':identity,'output':output,'fixture':name})
        measured=fixture_measurements(source,video,timeline,spec)
        manifest={'contract_version':VERSION,'mode':'TEST_ONLY','fixture':name,'source':plan['source'],
            'plan_sha256':core.digest_object(plan),'execution_sha256':core.digest_object(spec),'timeline':timeline,
            'code_receipts':code_receipts(),'environment':core.environment(),'verification':verification,
            'audio_mapping_verification':mapping,'fixture_measurements':measured,'execution':execution,
            'output':{**verification['metadata'],'path':core.shared.relative(output/'render.mp4'),
                'sha256':core.intake.gate.sha256_file(video),'bytes':video.stat().st_size},
            'production_eligible':False,'publishing_eligible':False,'render_approved':False,'publish_approved':False}
        publish(output,{'source.mp4':source,'render.mp4':video},
            {PLAN:plan,SPEC:spec,TIMELINE:timeline,'synthetic-identity.v01.json':identity,MANIFEST:manifest},core.TEST_ROOT)
        return manifest


def validate_proof(reference):
    qa.same_reference(reference);bundle=core.safe_path(reference['path'],under=core.TEST_ROOT).parent
    manifest=qa.read(reference['path']);plan=qa.read(bundle/PLAN);spec=qa.read(bundle/SPEC)
    identity=qa.read(bundle/'synthetic-identity.v01.json');source=core.safe_path(bundle/'source.mp4')
    if manifest.get('mode')!='TEST_ONLY' or manifest['code_receipts']!=code_receipts() or manifest['environment']!=core.environment():
        raise core.Error('Audio capability code/environment/scope mismatch')
    fixtures.admit(identity,plan,spec['visual_spec'],source,bundle,{})
    if spec['audio_timeline']!=fixture_audio(plan['source'],manifest['fixture']):raise core.Error('Audio capability recipe mismatch')
    timeline=compile_timeline(plan,spec);validate_source_audio(source,plan,spec)
    if manifest['timeline']!=timeline or qa.read(bundle/TIMELINE)!=timeline or manifest['plan_sha256']!=core.digest_object(plan) or manifest['execution_sha256']!=core.digest_object(spec):
        raise core.Error('Audio capability graph/plan/spec mismatch')
    output=core.safe_path(bundle/'render.mp4');qa.same_reference({k:manifest['output'][k] for k in ('path','sha256')})
    if manifest['output']['path']!=core.shared.relative(output) or manifest['output']['bytes']!=output.stat().st_size:raise core.Error('Audio proof media substitution')
    verification=core.verify_output(output,timeline,True,spec['visual_spec']['resources'])
    if verification!=manifest['verification'] or manifest['audio_mapping_verification']!=measure_audio_mapping(source,output,timeline,spec) or manifest['fixture_measurements']!=fixture_measurements(source,output,timeline,spec):
        raise core.Error('Audio proof measured result mismatch')
    if any(manifest.get(k) is not False for k in ('production_eligible','publishing_eligible','render_approved','publish_approved')):
        raise core.Error('Audio proof cannot authorize production')
    return manifest


def capability(proofs):
    manifests=[validate_proof(r) for r in proofs]
    if {m['fixture'] for m in manifests}!={'replace','mix'}:raise core.Error('Both replacement and safe original mix need synthetic proof')
    result={'contract_version':VERSION,'capability':'continuous_source_audio','scope':'LOCAL_SYNTHETIC_SELF_TESTS_ONLY',
        'status':'verified','proofs':proofs,'environment':core.environment(),'code_receipts':code_receipts(),
        'limitations':['Source range must exactly cover output duration; no looping or external music',
            'Private preview only; musical phrasing and publication rights not certified',
            'Replacement refuses conflicting shot-audio effects; mixes require clipping verification'],
        'production_eligible':False,'publishing_eligible':False}
    return intelligence.check('audio_capability',result)


def validate_capability(path):
    receipt=intelligence.check('audio_capability',qa.read(path))
    if receipt!=capability(receipt['proofs']):raise core.Error('Audio capability differs from actual fixture replay')
    return receipt
