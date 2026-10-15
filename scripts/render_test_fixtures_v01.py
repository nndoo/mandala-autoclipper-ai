"""Closed synthetic fixtures for renderer tests; never accept arbitrary live plans."""
import copy
import hashlib
from pathlib import Path

import renderer_core_v01 as core

NAMES=('basic','dynamic','captions','audio','music','normalization','silent','fullhd','reuse','silent-music','creative-text')
RECIPE={'name':'stage55-color-tone-source-v01','duration_sec':6,'width':180,'height':320,'fps':30,
        'scenes':[{'color':'red','frequency':440},{'color':'green','frequency':660},{'color':'blue','frequency':880}],
        'synthetic_speech_truth':'None: labels describe synthetic scenes, not recognized human utterances'}


def shot(uid,order,start,end,speed=1,freeze=0,overlap=0):
    return {'shot_id':uid,'order':order,'source_start_sec':start,'source_end_sec':end,'timing_precision':'approximate',
            'evidence_refs':['synthetic.source'],'rationale':'Explicit synthetic test shot, not an editorial model decision',
            'timing':{'speed':speed,'freeze_sec':freeze,'transition_out':'crossfade' if overlap else 'cut','overlap_sec':overlap},
            'speech_safe':False,'review_required':True}


def op(uid,kind,shot_id,start,end,parameters):
    return {'operation_id':uid,'kind':kind,'shot_id':shot_id,'output_start_sec':start,'output_end_sec':end,
            'evidence_refs':['synthetic.source'],'rationale':'Explicit synthetic test operation',
            'capability_status':'requires_implementation','parameters':parameters}


def caption(text,kind='creative_copy'):
    return {'text':text,'kind':kind,'verification_status':'verified' if kind=='verified_quote' else 'unverified',
            'evidence_refs':['synthetic.source'],'publish_ready':False}


def definition(name):
    if name not in NAMES:raise core.Error('Unknown closed synthetic fixture identity')
    shots=[shot('s1',1,4,6),shot('s2',2,0,2),shot('s3',3,2,4)]
    operations=[];extra={}
    if name=='reuse':shots=[shot('s1',1,0,2),shot('s2',2,0,2),shot('s3',3,4,6)]
    elif name=='dynamic':
        shots=[shot('s1',1,0,2,1.25,.4,.3),shot('s2',2,2,4,.8,0,.2),shot('s3',3,4,6,1,.2)]
        operations=[op('zoom','zoom','s1',.2,1.2,{'scale':1.4,'center_x':.5,'center_y':.5}),
                    op('grade','color_grade','s2',1.8,3.8,{'intent':'Explicit synthetic brightness/contrast/saturation test'}),
                    op('crop','crop','s3',4.4,5.2,{'x':.1,'y':.1,'width':.8,'height':.8})]
        extra={'grade':{'color':{'brightness':.04,'contrast':1.1,'saturation':.8}}}
    elif name=='captions':
        shots=[shot('s1',1,4,6),shot('s2',2,0,2,1.25),shot('s3',3,2,4,.8,.4)]
        operations=[op('hook','overlay','s1',.2,1.4,{'caption':caption('TEST ONLY'),'position':'top'}),
                    op('sentence','subtitle','s3',4.85,5.475,{'caption':caption('SCENE TWO\nSYNTHETIC','verified_quote'),'position':'bottom'}),
                    op('cta','overlay','s3',5.9,6.5,{'caption':caption('END TEST'),'position':'center'}),
                    op('literal','overlay','s2',2.1,3.2,{'caption':caption('[%{n}]:\\{}'),'position':'top'})]
        extra={'sentence':{'caption_source_window':{'start_sec':3,'end_sec':3.5},'font_size_px':10},
               'hook':{'font_size_px':12},'cta':{'font_size_px':12},'literal':{'font_size_px':10}}
    elif name=='creative-text':
        shots=[shot('s1',1,0,6)]
        operations=[op('animated','overlay','s1',.2,1.8,{'caption':caption('LOOK'),'position':'bottom'}),
                    op('colored','overlay','s1',3.2,4.6,{'caption':caption('DETAIL'),'position':'bottom'})]
        extra={'animated':{'font_size_px':20,'text_layout':'social_portrait.v01',
            'text_style':{'font':'dejavu_sans_bold','color':'#FFE040','outline_color':'#000000','outline_width_px':1,'shadow':False},
            'text_animation':{'enter':'fade','exit':'fade','enter_duration_sec':.6,'exit_duration_sec':.6}},
            'colored':{'font_size_px':16,'text_layout':'social_portrait.v01',
            'text_style':{'font':'dejavu_sans','color':'#40E0FF','outline_color':'#000000','outline_width_px':1,'shadow':False}}}
    elif name in ('audio','music','normalization','silent-music'):
        shots=[shot('s1',1,0,6)]
        if name=='audio':
            operations=[op('gain','audio_gain','s1',0,2,{'gain_db':-6}),
                        op('denoise','denoise','s1',2,4,{'strength':.5}),
                        op('duck','audio_duck','s1',4,5,{'gain_db':-9}),
                        op('fade-in','custom','s1',0,.3,{'name':'renderer.audio_fade.v01','implementation_requirements':'Explicit synthetic fade parameters'}),
                        op('fade-out','custom','s1',5.7,6,{'name':'renderer.audio_fade.v01','implementation_requirements':'Explicit synthetic fade parameters'})]
            extra={'fade-in':{'fade':{'direction':'in','start_sec':0,'duration_sec':.3}},
                   'fade-out':{'fade':{'direction':'out','start_sec':5.7,'duration_sec':.3}}}
        elif name in ('music','silent-music'):
            operations=[op('bed','music_bed','s1',1,5,{'asset_reference':'tone','gain_db':-18}),
                        op('effect','sound_effect','s1',5,5.5,{'asset_reference':'tone','gain_db':-15})]
        else:
            operations=[op('normalize','custom','s1',0,6,{'name':'renderer.normalize.v01','implementation_requirements':'Explicit whole-output synthetic normalization'})]
            extra={'normalize':{'normalization':{'integrated_lufs':-23,'true_peak_db':-2,'loudness_range':7}}}
    elif name=='fullhd':shots=[shot('s1',1,0,1)]
    return {'fixture_id':'stage55.synthetic.'+name+'.v01','recipe':RECIPE,'name':name,'shots':shots,'operations':operations,'operation_parameters':extra}


def generate_source(work,name,limits):
    arguments=[]
    for scene in RECIPE['scenes']:
        arguments+=['-f','lavfi','-i',f'color=c={scene["color"]}:s=180x320:r=30:d=2']
        if name not in ('silent','silent-music'):arguments+=['-f','lavfi','-i',f'sine=frequency={scene["frequency"]}:sample_rate=48000:duration=2']
    parts=[]
    for i in range(3):
        vi=i if name in ('silent','silent-music') else i*2
        parts.append(f'[{vi}:v]drawbox=x=15:y=20:w=60:h=50:color=white:t=fill[v{i}]')
    if name in ('silent','silent-music'):parts.append('[v0][v1][v2]concat=n=3:v=1:a=0[vout]')
    else:parts.append('[v0][1:a][v1][3:a][v2][5:a]concat=n=3:v=1:a=1[vout][aout]')
    source=work/'source.mp4'
    arguments+=['-filter_complex',';'.join(parts),'-map','[vout]']
    if name not in ('silent','silent-music'):arguments+=['-map','[aout]','-c:a','aac','-b:a','128k']
    else:arguments+=['-an']
    arguments+=['-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-preset','veryfast','-r','30','-threads',str(limits['threads']),'-map_metadata','-1',str(source)]
    core.ffmpeg(arguments,work,limits)
    return source


def build_plan_spec(name,source,final,assets,*,output_overrides=None,resource_overrides=None):
    d=definition(name);info=core.media_info(source,{**core.DEFAULT_RESOURCES,**(resource_overrides or {})});sha=core.intake.gate.sha256_file(source)
    if (info['width'],info['height'],info['fps'],info['duration_sec'],info['audio_present'])!=(180,320,30,6,name not in ('silent','silent-music')):
        raise core.Error('Source is not the required synthetic recipe topology')
    source_record={'video_id':'local-sha256-'+sha[:32],'duration_sec':6,'width':180,'height':320,'fps':30,
                   'path':core.shared.relative(final/'source.mp4'),'sha256':sha}
    shots=d['shots'];total=round(sum((s['source_end_sec']-s['source_start_sec'])/s['timing']['speed']+s['timing']['freeze_sec']-s['timing']['overlap_sec'] for s in shots),2)
    hook={k:shots[0][k] for k in ('shot_id','source_start_sec','source_end_sec','timing_precision','evidence_refs')}
    hook['rationale']='Explicit controlled synthetic opening'
    variant={'variant_id':'A','title':'TEST ONLY '+name,'editorial_concept':'Controlled renderer acceptance fixture',
             'intended_message':'TEST ONLY, not a production video','narrative_strategy':'Explicit fixture shot order',
             'hook':hook,'shots':shots,'estimated_output_duration_sec':total,'operations':d['operations'],
             'audio_strategy':{'intent':'Explicit synthetic tone audio tests','sync_basis':'none','evidence_refs':['synthetic.source']},
             'ending':{'intent':'Synthetic test ending','cta':None},'required_reviews':['TEST ONLY, never approved for production']}
    plan={'contract_version':'0.3.0','plan_status':'DRAFT_UNVALIDATED','source':source_record,
          'evidence_packet_sha256':core.digest_object(d),'editorial_concept':'Synthetic renderer fixture',
          'intended_message':'TEST ONLY','proposed_variant_count':1,'variants':[variant],'missing_evidence':[],
          'required_reviews':['TEST ONLY, never approved for production'],'factual_claims':[],
          'renderer_capabilities':{'verification_status':'unknown','supported_operations':[]},
          'render_readiness':'BLOCKED_FOR_RENDER','publish_ready':False,'render_approved':False,'publish_approved':False}
    output={**core.DEFAULT_OUTPUT,'width':180,'height':320,'preset':'veryfast'}
    if name=='fullhd':output.update(width=1080,height=1920)
    output.update(output_overrides or {})
    spec={'contract_version':'0.1.0','plan_sha256':core.digest_object(plan),'variant_id':'A','output':output,
          'resources':{**core.DEFAULT_RESOURCES,**(resource_overrides or {})},'operation_parameters':d['operation_parameters'],'assets':assets}
    return plan,spec


def create(work,name,final,*,output_overrides=None,resource_overrides=None):
    d=definition(name);limits={**core.DEFAULT_RESOURCES,**(resource_overrides or {})}
    core.base.validate_object(limits,core.base.load_schema('render-execution.v0.1.schema.json')['properties']['resources'],'Self-test resources')
    source=generate_source(work,name,limits);asset_paths={};assets={}
    if name in ('music','silent-music'):
        asset=work/'asset.wav'
        core.ffmpeg(['-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=6','-c:a','pcm_s16le',str(asset)],work,limits)
        record={'path':core.shared.relative(final/'asset.wav'),'sha256':core.intake.gate.sha256_file(asset),'duration_sec':6,
                'rights':{'scope':'TEST_ONLY','authorized':True,'basis':'Generated sine-wave test fixture; not a music reuse license'}}
        assets['tone']=record;asset_paths[record['path']]=asset
    plan,spec=build_plan_spec(name,source,final,assets,output_overrides=output_overrides,resource_overrides=resource_overrides)
    identity={'contract_version':'0.1.0','fixture_id':d['fixture_id'],'authorization_mode':'TEST_ONLY',
              'definition_sha256':core.digest_object(d),'source_sha256':core.intake.gate.sha256_file(source),
              'plan_sha256':core.digest_object(plan),'execution_spec_sha256':core.digest_object(spec),
              'production_approval_granted':False}
    admit(identity,plan,spec,source,final,asset_paths)
    return identity,plan,spec,source,asset_paths


def admit(identity,plan,spec,source,final,asset_paths):
    name=identity['fixture_id'].removeprefix('stage55.synthetic.').removesuffix('.v01')
    d=definition(name)
    if identity['authorization_mode']!='TEST_ONLY' or identity['production_approval_granted'] is not False:
        raise core.Error('Synthetic identity cannot authorize production')
    expected_plan,expected_spec=build_plan_spec(name,source,final,spec['assets'],output_overrides=spec['output'],resource_overrides=spec['resources'])
    if plan!=expected_plan or spec!=expected_spec or identity['definition_sha256']!=core.digest_object(d):
        raise core.Error('Synthetic fixture plan/spec/recipe identity mismatch')
    if identity['source_sha256']!=core.intake.gate.sha256_file(source) or identity['plan_sha256']!=core.digest_object(plan) or identity['execution_spec_sha256']!=core.digest_object(spec):
        raise core.Error('Synthetic fixture fingerprint mismatch')
    if set(spec['assets'])!=({'tone'} if name in ('music','silent-music') else set()):raise core.Error('Synthetic asset identity mismatch')
    for record in spec['assets'].values():core.validate_asset(record,asset_paths[record['path']],'TEST_ONLY')
    core.base.validate_object(plan,core.base.load_schema('adaptive-editing-plan.v0.3.schema.json'),'Synthetic editing plan')
    return True
