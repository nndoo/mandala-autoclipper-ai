"""Deterministic local FFmpeg compiler. No approval bypass or editorial choices."""
from array import array
import copy
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import tempfile
import time
import unicodedata

import run_adaptive_director_v03 as director

intake, base, shared, av = director.intake, director.base, director.shared, director.av
Error = base.AdapterError
VERSION = '0.1.0'
TEST_ROOT = base.ROOT/'data/render-tests/stage55'
PRODUCTION_ROOT = base.ROOT/'data/renders'
FONT = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
BOLD_FONT = FONT.with_name('DejaVuSans-Bold.ttf')
MAX_DURATION = 180
MAX_JSON = 131072
DEFAULT_OUTPUT = {'width':1080,'height':1920,'fps':30,'fit':'pad','video_codec':'libx264','audio_codec':'aac',
                  'pixel_format':'yuv420p','crf':23,'preset':'veryfast','audio_bitrate_kbps':128,'audio_sample_rate':48000,
                  'audio_mode':'preserve','freeze_audio':'silence','effect_scope':'output_composite','timing_tolerance_frames':2}
DEFAULT_RESOURCES = {'threads':2,'timeout_sec':90,'memory_mib':1536,'max_output_bytes':67108864,'disk_reserve_bytes':16777216}
CUSTOM_NAMES = {'renderer.audio_fade.v01':'audio_fade','renderer.normalize.v01':'normalization'}
FILTERS = {'trim':['trim','atrim'],'concat':['concat'],'reorder':['trim','concat'],'reuse':['trim','concat'],
           'speed':['setpts','atempo'],'freeze':['tpad','apad'],'crossfade':['xfade','acrossfade'],
           'crop':['crop','scale','overlay'],'zoom':['crop','scale','overlay'],'overlay':['drawtext'],
           'text_style':['drawtext'],'text_animation':['drawtext'],
           'subtitle':['drawtext'],'color_grade':['eq'],'audio_gain':['volume'],'audio_duck':['volume'],
           'denoise':['afftdn'],'audio_fade':['afade'],'normalization':['loudnorm'],
           'music_bed':['amix','adelay'],'sound_effect':['amix','adelay']}


def digest_object(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=False).encode()).hexdigest()


def safe_path(value,label='Renderer path',*,output=False,under=None):
    candidate=Path(value)
    if not candidate.is_absolute():candidate=base.ROOT/candidate
    if '..' in candidate.parts or any(part.startswith('.env') for part in candidate.parts):
        raise Error('Unsafe traversal or secret path')
    # Stronger than the reused root guard: renderer paths never follow symlinks.
    if any(parent.is_symlink() for parent in (candidate,*candidate.parents)):
        raise Error('Renderer symlink path rejected')
    path=av.checked_path(candidate,label,output=output)
    if under is not None and not path.is_relative_to(Path(under).resolve()):
        raise Error('Renderer path outside designated scope')
    return path


def new_directory(value,under):
    path=Path(value)
    if not path.is_absolute():path=base.ROOT/path
    if '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):
        raise Error('Unsafe output directory')
    resolved=path.resolve()
    if not resolved.is_relative_to(Path(under).resolve()) or resolved==Path(under).resolve():
        raise Error('Output must be below designated rendering root')
    return shared.directory(resolved,new=True)


def read_json(path):
    path=safe_path(path)
    if path.stat().st_size>MAX_JSON:raise Error('Renderer JSON byte limit exceeded')
    return director.strict_json(path.read_text())


def n(value):
    """Decimal arguments generated from finite values, never untrusted filter text."""
    if isinstance(value,bool) or not isinstance(value,(int,float,Fraction)) or not math.isfinite(value):
        raise Error('Nonfinite execution parameter')
    return format(float(value),'.9f').rstrip('0').rstrip('.') or '0'


def rational(value):
    return Fraction(str(value))


def prlimit_command(command,limits):
    executable=shutil.which('prlimit')
    if not executable:raise Error('prlimit unavailable; resource enforcement required')
    # Limit glibc arena reservations so media threads fit the virtual-memory cap.
    return [executable,'--as='+str(limits['memory_mib']*1048576),
            '--fsize='+str(limits['max_output_bytes']), '--cpu='+str(math.ceil(limits['timeout_sec'])+2),
            '--','env','MALLOC_ARENA_MAX=2',*command]


def run(command,limits=DEFAULT_RESOURCES,*,max_bytes=1048576):
    """Reuse bounded stdout/DEVNULL stderr and kill/reap; prlimit execs same PID."""
    command=list(command)
    if Path(command[0]).name=='ffmpeg':
        command[1:1]=['-threads',str(limits['threads']),'-filter_threads','1','-filter_complex_threads','1','-max_alloc','67108864']
    elif Path(command[0]).name=='ffprobe':
        command[1:1]=['-threads',str(limits['threads'])]
    output=bytearray();started=time.monotonic()
    base.bounded_run(prlimit_command(command,limits),output.extend,max_bytes=max_bytes,timeout=limits['timeout_sec'])
    return bytes(output),time.monotonic()-started


def ffmpeg(arguments,work,limits):
    # Work paths never enter filter strings: enter a private working directory and
    # use generated ASCII filenames, avoiding shell and FFmpeg path escaping.
    command=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n','-xerror',
             '-max_alloc','67108864','-threads',str(limits['threads']),'-filter_threads','1','-filter_complex_threads','1',*arguments]
    # base.bounded_run lacks cwd; fixed paths in a graph use an absolute work path
    # validated to contain only filter-safe characters below the project root.
    if any(c in str(work) for c in ":,;[]'\\\n\r"):
        raise Error('Working directory is not filter-safe')
    return run(command,limits)


def probe(path,limits=DEFAULT_RESOURCES):
    output,_=run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_streams','-show_format','-of','json',str(safe_path(path))],limits)
    try:return json.loads(output,parse_constant=base.reject_constant,parse_float=base.finite_float,object_pairs_hook=base.unique_object)
    except (ValueError,UnicodeError):raise Error('Invalid FFprobe metadata') from None


def media_info(path,limits=DEFAULT_RESOURCES):
    data=probe(path,limits)
    videos=[s for s in data['streams'] if s['codec_type']=='video']
    audios=[s for s in data['streams'] if s['codec_type']=='audio']
    if len(videos)!=1 or len(audios)>1:raise Error('Unsupported stream topology')
    v=videos[0]
    if v.get('tags',{}).get('rotate') or any(s.get('rotation',0) for s in v.get('side_data_list',[])):
        raise Error('Rotation metadata needs an explicit verified mapping')
    if v['width']*v['height']>8294400 or max(v['width'],v['height'])>4096 or v.get('sample_aspect_ratio','1:1') not in ('1:1','N/A'):
        raise Error('Source dimensions/sample aspect ratio outside verified policy')
    duration=float(data['format']['duration']);fps=float(Fraction(v['avg_frame_rate']))
    if not 0<duration<=MAX_DURATION or not 10<=fps<=60:raise Error('Source duration/FPS outside resource policy')
    if abs(float(data['format'].get('start_time',0)))>.0001 or abs(float(v.get('start_time',0)))>.0001:
        raise Error('Nonzero source presentation origin is not implemented')
    if audios and abs(float(audios[0].get('start_time',0)))>.0001:
        raise Error('Offset audio presentation clock needs an explicit mapping')
    return {'duration_sec':round(duration,3),'width':v['width'],'height':v['height'],'fps':fps,
            'video_codec':v['codec_name'],'pixel_format':v.get('pix_fmt'),'audio_present':bool(audios),
            'audio_codec':audios[0]['codec_name'] if audios else None,'audio_sample_rate':int(audios[0]['sample_rate']) if audios else None,
            'audio_channels':audios[0]['channels'] if audios else None,'audio_duration_sec':float(audios[0].get('duration',duration)) if audios else None}


def environment():
    paths={name:shutil.which(name) for name in ('ffmpeg','ffprobe','prlimit')}
    if not all(paths.values()):raise Error('Required local processing tool unavailable')
    versions={}
    for name in ('ffmpeg','ffprobe'):
        text=base.small_output([paths[name],'-version'],max_bytes=65536,timeout=10)
        versions[name]={'path':paths[name],'version':text.splitlines()[0],'sha256':intake.gate.sha256_file(Path(paths[name]))}
    listed=base.small_output([paths['ffmpeg'],'-hide_banner','-filters'],max_bytes=262144,timeout=10)
    encoders=base.small_output([paths['ffmpeg'],'-hide_banner','-encoders'],max_bytes=262144,timeout=10)
    filters={line.split()[1] for line in listed.splitlines() if len(line.split())>2 and len(line.split()[0])==3}
    return {'tools':versions,'font':{'path':str(FONT),'available':FONT.is_file(),'sha256':intake.gate.sha256_file(FONT) if FONT.is_file() else None},
            'bold_font':{'path':str(BOLD_FONT),'available':BOLD_FONT.is_file(),'sha256':intake.gate.sha256_file(BOLD_FONT) if BOLD_FONT.is_file() else None},
            'available_filters':sorted(filters),'libx264_available':'libx264 ' in encoders,'aac_available':' aac ' in encoders,
            'libass_filter_available':'ass' in filters and 'subtitles' in filters,
            'availability_is_not_verification':True}


def code_receipts():
    return [av.reference(base.ROOT/p) for p in ('scripts/renderer_core_v01.py','scripts/render_video_v01.py',
                'scripts/adaptive_text_v01.py',
                'scripts/render_test_fixtures_v01.py','src/schemas/render-execution.v0.1.schema.json',
                'src/schemas/renderer-capabilities.v0.1.schema.json','src/schemas/render-manifest.v0.1.schema.json')]


def settings(spec):
    base.validate_object(spec,base.load_schema('render-execution.v0.1.schema.json'),'Rendering execution specification')
    o=spec['output']
    if o['width']%2 or o['height']%2 or o['width']*o['height']>2073600:
        raise Error('Even dimensions and maximum 1080x1920 pixel area required')
    return o,spec['resources']


def effective_kind(operation):
    kind=operation['kind']
    if kind=='custom':
        kind=CUSTOM_NAMES.get(operation['parameters']['name'])
        if kind is None:raise Error('Unsupported custom operation; no substitution')
    return kind


def source_window_to_output(shot,window):
    start,end=rational(window['start_sec']),rational(window['end_sec'])
    a,b=rational(shot['source_start_sec']),rational(shot['source_end_sec'])
    if not a<=start<end<=b:raise Error('Caption source window outside selected shot')
    offset=rational(shot['output_start_sec']);speed=rational(shot['speed'])
    return float(offset+(start-a)/speed),float(offset+(end-a)/speed)


def compile_timeline(plan,spec):
    base.validate_object(plan,base.load_schema('adaptive-editing-plan.v0.3.schema.json'),'Editing plan V0.3')
    output,limits=settings(spec)
    if digest_object(plan)!=spec['plan_sha256']:raise Error('Execution spec plan identity mismatch')
    if plan['proposed_variant_count']!=len(plan['variants']) or len({v['variant_id'] for v in plan['variants']})!=len(plan['variants']):
        raise Error('Variant count or identity mismatch')
    matches=[v for v in plan['variants'] if v['variant_id']==spec['variant_id']]
    if len(matches)!=1:raise Error('Variant selection is ambiguous or missing')
    v=matches[0]
    first=v['shots'][0]
    if any(v['hook'][key]!=first[key] for key in ('shot_id','source_start_sec','source_end_sec','timing_precision')):
        raise Error('Hook/source shot mismatch')
    duration=rational(plan['source']['duration_sec']);clock=Fraction(0);shots=[];ids=set();required={'trim'}
    if len(v['shots'])>1:required.add('concat')
    for i,s in enumerate(v['shots']):
        a,b=rational(s['source_start_sec']),rational(s['source_end_sec']);t=s['timing'];speed=rational(t['speed']);freeze=rational(t['freeze_sec']);overlap=rational(t['overlap_sec'])
        if not 0<=a<b<=duration or s['order']!=i+1 or s['shot_id'] in ids:raise Error('Invalid source range/order/duplicate shot')
        if b-a<Fraction(1)/rational(plan['source']['fps']) or (b-a)/speed<Fraction(1,output['fps']):
            raise Error('Shot shorter than the supported source/output frame sampling interval')
        if (0<freeze<Fraction(1,output['fps'])) or (0<overlap<Fraction(1,output['fps'])):
            raise Error('Freeze/crossfade below output-frame timing resolution')
        ids.add(s['shot_id']);play=(b-a)/speed;length=play+freeze
        if (t['transition_out']=='cut' and overlap) or (t['transition_out']=='crossfade' and overlap<=0):raise Error('Transition/overlap inconsistency')
        if i==len(v['shots'])-1 and (t['transition_out']!='cut' or overlap):raise Error('Final transition must be cut/zero')
        item={'shot_id':s['shot_id'],'source_start_sec':float(a),'source_end_sec':float(b),'speed':float(speed),
              'playback_duration_sec':float(play),'freeze_sec':float(freeze),'freeze_audio':'silence','freeze_source_frame_rule':'last retained CFR presentation frame from source range [start,end)',
              'output_start_sec':float(clock),'output_end_sec':float(clock+length),'freeze_output_start_sec':float(clock+play),
              'transition_out':t['transition_out'],'overlap_sec':float(overlap),'timing_precision':s['timing_precision']}
        shots.append(item);clock+=length-overlap
        if speed!=1:required.add('speed')
        if freeze:required.add('freeze')
        if overlap:required.add('crossfade')
        if i and a<rational(v['shots'][i-1]['source_end_sec']):required.add('reorder')
        if any(max(a,rational(p['source_start_sec']))<min(b,rational(p['source_end_sec'])) for p in v['shots'][:i]):required.add('reuse')
    for i,s in enumerate(shots):
        incoming=rational(shots[i-1]['overlap_sec']) if i else 0;outgoing=rational(s['overlap_sec']);length=rational(s['playback_duration_sec'])+rational(s['freeze_sec'])
        if incoming+outgoing>=length or (i+1<len(shots) and outgoing>=rational(shots[i+1]['playback_duration_sec'])+rational(shots[i+1]['freeze_sec'])):
            raise Error('Impossible crossfade combination')
    if clock<=0 or clock>MAX_DURATION or abs(round(float(clock),2)-v['estimated_output_duration_sec'])>1e-6:raise Error('Output duration mismatch/resource limit')
    operations=[];opids=set();params=spec['operation_parameters']
    if set(params)-{o['operation_id'] for o in v['operations']}:raise Error('Orphan execution operation parameters')
    for op in v['operations']:
        oid=op['operation_id'];s=next((s for s in shots if s['shot_id']==op['shot_id']),None)
        a,b=op['output_start_sec'],op['output_end_sec']
        if oid in opids or not s or not 0<=a<b<=float(clock)+1e-8 or not s['output_start_sec']<=a<b<=s['output_end_sec']+1e-8:
            raise Error('Invalid operation output window/identity')
        opids.add(oid);kind=effective_kind(op);p=op['parameters'];extra=params.get(oid,{})
        allowed={'color_grade':{'color'},'overlay':{'font_size_px','caption_source_window','text_layout','text_style','text_animation'},'subtitle':{'font_size_px','caption_source_window','text_layout','text_style','text_animation'},'audio_fade':{'fade'},'normalization':{'normalization'}}.get(kind,set())
        if set(extra)-allowed:raise Error('Irrelevant or unsupported execution parameters')
        if op['capability_status']=='supported':raise Error('Plan cannot self-certify renderer support')
        if kind=='crop' and (p['x']+p['width']>1 or p['y']+p['height']>1):raise Error('Crop outside source image')
        if kind=='crop' and (p['width']*output['width']<2 or p['height']*output['height']<2):raise Error('Crop below decoded pixel resolution')
        if kind=='zoom':
            margin=.5/p['scale']
            if not margin<=p['center_x']<=1-margin or not margin<=p['center_y']<=1-margin:raise Error('Zoom viewport outside source image')
        if kind=='color_grade' and 'color' not in extra:raise Error('Color intent lacks executable numeric parameters')
        if kind=='audio_fade':
            fade=extra.get('fade');
            if not fade or fade['start_sec']<a or fade['start_sec']+fade['duration_sec']>b:raise Error('Explicit fade window required')
        if kind=='normalization' and 'normalization' not in extra:raise Error('Explicit normalization parameters required')
        if kind in ('overlay','subtitle'):
            caption=p['caption']
            if caption['text'] is None or caption['kind']=='placeholder':raise Error('Caption text/timing eligibility missing')
            if kind=='subtitle' and (caption['kind']!='verified_quote' or caption['verification_status']!='verified'):
                raise Error('Subtitle requires fixture-verified text and timing, not ASR or model claims')
            import adaptive_text_v01 as text_policy
            try:text_policy.validate_treatment(extra,b-a)
            except ValueError as error:raise Error(str(error)) from None
            if 'text_style' in extra:
                required.add('text_style')
                if extra['text_style']['font']=='dejavu_sans_bold' and not BOLD_FONT.is_file():raise Error('Verified bold font missing')
            if 'text_animation' in extra:required.add('text_animation')
            checked_text(caption['text'],extra.get('font_size_px',max(10,output['width']//12)),output)
            if 'caption_source_window' in extra:
                mapped=source_window_to_output(s,extra['caption_source_window'])
                if max(abs(mapped[0]-a),abs(mapped[1]-b))>1e-6:raise Error('Caption source/output mapping mismatch')
            elif kind=='subtitle':raise Error('Subtitle source timing evidence required')
        required.add(kind);operations.append({**copy.deepcopy(op),'effective_kind':kind,'execution_parameters':copy.deepcopy(extra)})
    asset_names={op['parameters']['asset_reference'] for op in v['operations'] if op['kind'] in ('music_bed','sound_effect')}
    if asset_names!=set(spec['assets']):raise Error('Missing or orphan approved asset record')
    for op in v['operations']:
        if op['kind'] in ('music_bed','sound_effect') and spec['assets'][op['parameters']['asset_reference']]['duration_sec']<op['output_end_sec']-op['output_start_sec']:
            raise Error('Audio asset shorter than requested operation')
    import adaptive_text_v01 as text_policy
    try: text_layout=text_policy.validate_layout(operations,output)
    except ValueError as error: raise Error(str(error)) from None
    return {'contract_version':VERSION,'variant_id':v['variant_id'],'shots':shots,'operations':operations,
            'text_layout_checks':text_layout,
            'expected_duration_sec':float(clock),'expected_duration_fraction':str(clock),'required_capabilities':sorted(required),
            'frame_quantization_sec':1/output['fps'],'output_settings':output,'resources':limits,
            'source_time_policy':'decoded source PTS with verified zero presentation origin; no cut boundary correction',
            'effect_scope':'explicit output composite; overlapping shots may both appear under the requested effect',
            'speech_safe_certified':False}


def checked_text(text,font_size,output):
    director.safe_text(text,1200)
    if len(text)>300 or any(unicodedata.category(c).startswith('C') and c!='\n' for c in text):raise Error('Unsafe caption control characters')
    lines=text.split('\n')
    if len(lines)>3 or any(len(line)*font_size>.88*output['width'] for line in lines) or font_size*1.5*len(lines)>.3*output['height']:
        raise Error('Caption exceeds conservative safe-area layout')
    return text


def fit_filter(output):
    w,h=output['width'],output['height']
    if output['fit']=='pad':return f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black'
    return f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}'


def filter_graph(timeline,source_has_audio,work,spec):
    o=timeline['output_settings'];w,h,fps=o['width'],o['height'],o['fps'];duration=n(timeline['expected_duration_sec'])
    audio=(source_has_audio and o['audio_mode']=='preserve') or bool(spec['assets'])
    if o['audio_mode']=='silent' and spec['assets']:raise Error('Silent output contradicts audio mixing request')
    graph=[];source_audio='0:a'
    if audio and not source_has_audio:
        if not spec['assets']:raise Error('Missing source audio for requested processing')
        labels=''.join(f'[silence{i}]' for i in range(len(timeline['shots'])))
        source_duration=max(s['source_end_sec'] for s in timeline['shots'])
        graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={n(source_duration)},asplit={len(timeline["shots"])}{labels}')
    for i,s in enumerate(timeline['shots']):
        a,b,speed,freeze=s['source_start_sec'],s['source_end_sec'],s['speed'],s['freeze_sec'];length=s['output_end_sec']-s['output_start_sec']
        graph.append(f'[0:v]trim=start={n(a)}:end={n(b)},setpts=(PTS-STARTPTS)/{n(speed)},fps={fps},{fit_filter(o)},setsar=1,format=yuv420p,settb=1/{fps},tpad=stop_mode=clone:stop_duration={n(freeze)},trim=duration={n(length)},setpts=PTS-STARTPTS[v{i}]')
        if audio:
            graph.append(f'[{source_audio if source_has_audio else "silence"+str(i)}]atrim=start={n(a)}:end={n(b)},asetpts=PTS-STARTPTS,atempo={n(speed)},aformat=sample_rates=48000:channel_layouts=stereo,apad=pad_dur={n(freeze)},atrim=duration={n(length)},asetpts=PTS-STARTPTS[a{i}]')
    video_label,audio_label='v0','a0'
    for i in range(1,len(timeline['shots'])):
        prev=timeline['shots'][i-1];d=prev['overlap_sec']
        if d:
            graph.append(f'[{video_label}][v{i}]xfade=transition=fade:duration={n(d)}:offset={n(timeline["shots"][i]["output_start_sec"])}[vc{i}]')
            if audio:graph.append(f'[{audio_label}][a{i}]acrossfade=d={n(d)}:c1=tri:c2=tri[ac{i}]')
        else:
            graph.append(f'[{video_label}][v{i}]concat=n=2:v=1:a=0,settb=1/{fps}[vc{i}]')
            if audio:graph.append(f'[{audio_label}][a{i}]concat=n=2:v=0:a=1[ac{i}]')
        video_label,audio_label=f'vc{i}',f'ac{i}'
    asset_inputs=[];text_files=[]
    for i,op in enumerate(timeline['operations']):
        kind=op['effective_kind'];p=op['parameters'];extra=op['execution_parameters'];a,b=op['output_start_sec'],op['output_end_sec'];enable=f'gte(t,{n(a)})*lt(t,{n(b)})'
        if kind in ('overlay','subtitle'):
            size=extra.get('font_size_px',max(10,w//12));text=checked_text(p['caption']['text'],size,o)
            filename=work/f'caption-{i}.txt';filename.write_text(text,encoding='utf-8');text_files.append(filename)
            import adaptive_text_v01 as text_policy
            x,y=text_policy.ffmpeg_position(p['position'],w,h,extra.get('text_layout'))
            font=BOLD_FONT if extra.get('text_style',{}).get('font')=='dejavu_sans_bold' else FONT
            treatment=text_policy.ffmpeg_treatment(extra,a,b)
            graph.append(f'[{video_label}]drawtext=fontfile={font}:textfile={filename}:expansion=none:fontsize={size}:{treatment}:x={x}:y={y}:enable=\'{enable}\'[ve{i}]');video_label=f've{i}'
        elif kind in ('zoom','crop'):
            if kind=='zoom':cw,ch=1/p['scale'],1/p['scale'];x,y=p['center_x']-cw/2,p['center_y']-ch/2
            else:cw,ch,x,y=p['width'],p['height'],p['x'],p['y']
            graph.append(f'[{video_label}]split=2[orig{i}][branch{i}];[branch{i}]crop=w=iw*{n(cw)}:h=ih*{n(ch)}:x=iw*{n(x)}:y=ih*{n(y)}:exact=1,{fit_filter(o)},setsar=1[effect{i}];[orig{i}][effect{i}]overlay=x=0:y=0:enable=\'{enable}\'[ve{i}]');video_label=f've{i}'
        elif kind=='color_grade':
            c=extra['color'];graph.append(f'[{video_label}]eq=brightness={n(c["brightness"])}:contrast={n(c["contrast"])}:saturation={n(c["saturation"])}:enable=\'{enable}\'[ve{i}]');video_label=f've{i}'
        elif kind in ('audio_gain','audio_duck','denoise','audio_fade','normalization'):
            if not audio:raise Error('Requested audio operation has no audio stream')
            if kind in ('audio_gain','audio_duck'):f=f'volume={n(p["gain_db"])}dB:enable=\'{enable}\''
            elif kind=='denoise':f='anull' if p['strength']==0 else f'afftdn=nr={n(p["strength"]*30)}:nf=-50:enable=\'{enable}\''
            elif kind=='audio_fade':
                fade=extra['fade'];f=f'afade=t={fade["direction"]}:st={n(fade["start_sec"])}:d={n(fade["duration_sec"])}:enable=\'{enable}\''
            else:
                if a!=0 or abs(b-timeline['expected_duration_sec'])>1e-6:raise Error('Normalization currently requires whole output timeline')
                params=extra['normalization'];f=f'loudnorm=I={n(params["integrated_lufs"])}:TP={n(params["true_peak_db"])}:LRA={n(params["loudness_range"])}:linear=false'
            graph.append(f'[{audio_label}]{f}[ae{i}]');audio_label=f'ae{i}'
        elif kind in ('music_bed','sound_effect'):
            if not audio:raise Error('Audio asset mixing needs audio stream')
            record=spec['assets'].get(p['asset_reference'])
            if record is None:raise Error('Missing approved audio asset receipt')
            asset_inputs.append(record);input_index=len(asset_inputs)
            graph.append(f'[{input_index}:a]atrim=start=0:end={n(b-a)},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,volume={n(p["gain_db"])}dB,adelay={n(a*1000)}:all=1,apad,atrim=duration={duration}[asset{i}];[{audio_label}][asset{i}]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[ae{i}]');audio_label=f'ae{i}'
        else:raise Error('Unsupported operation reached compiler')
    if timeline.get('automatic_text_cues'):
        from automatic_text_v01 import filter_for
        text_filter,filename=filter_for(timeline,work)
        graph.append(f'[{video_label}]{text_filter}[automatic_text]')
        text_files.append(filename);video_label='automatic_text'
    graph.append(f'[{video_label}]fps={fps},trim=duration={duration},setpts=PTS-STARTPTS,format=yuv420p[vout]')
    if audio:graph.append(f'[{audio_label}]apad,atrim=duration={duration},asetpts=PTS-STARTPTS,aresample=48000[aout]')
    return ';\n'.join(graph),audio,asset_inputs,text_files


def validate_asset(record,actual_path,mode):
    path=safe_path(actual_path)
    if record['rights']['scope']!=mode or record['rights']['authorized'] is not True:raise Error('Audio asset rights/authorization mismatch')
    if intake.gate.sha256_file(path)!=record['sha256']:raise Error('Audio asset fingerprint mismatch')
    raw=probe(path);audios=[s for s in raw['streams'] if s['codec_type']=='audio']
    if len(audios)!=1 or abs(float(raw['format']['duration'])-record['duration_sec'])>.05:raise Error('Audio asset duration/stream mismatch')
    return path


def disk_preflight(parent,limits):
    if shutil.disk_usage(parent).free<limits['disk_reserve_bytes']+limits['max_output_bytes']:
        raise Error('Insufficient disk space for bounded render')


def encode(source,timeline,spec,work,asset_paths,mode,*,admission=None):
    if mode=='REAL_CONTENT_PREVIEW' and admission:
        # A single task-scoped permit; it cannot admit production or arbitrary media.
        import render_showcase_preview_v01 as preview
        work=safe_path(Path(work)/'render.mp4',output=True,under=preview.AUDIT).parent
        if not work.is_dir() or not work.name.startswith('.preview-work-'):
            raise Error('Preview encoding requires its private project work directory')
        context,plan,final=admission
        preview.admit(context,plan,spec,source,final,asset_paths)
    elif mode=='TEST_ONLY' and admission:
        import render_test_fixtures_v01 as fixtures
        identity,plan,final=admission
        final=new_directory(final,TEST_ROOT)
        fixtures.admit(identity,plan,spec,source,final,asset_paths)
    else:
        raise Error('Low-level rendering requires closed synthetic admission; production is fail-closed')
    if compile_timeline(plan,spec)!=timeline:raise Error('Execution graph differs from admitted plan')
    o,limits=settings(spec);disk_preflight(work,limits);info=media_info(source,limits)
    graph,audio,assets,_=filter_graph(timeline,info['audio_present'],work,spec)
    script=work/'filters.ffgraph';script.write_text(graph)
    arguments=['-protocol_whitelist','file,pipe','-i',str(source)]
    for record in assets:
        path=asset_paths.get(record['path'])
        if path is None:raise Error('Audio asset path not admitted')
        arguments+=['-protocol_whitelist','file,pipe','-i',str(validate_asset(record,path,mode))]
    output=work/'render.mp4'
    arguments+=['-filter_complex_script',str(script),'-map','[vout]']
    if audio:arguments+=['-map','[aout]','-c:a','aac','-b:a',str(o['audio_bitrate_kbps'])+'k','-ar','48000','-ac','2']
    else:arguments+=['-an']
    arguments+=['-c:v','libx264','-preset',o['preset'],'-crf',str(o['crf']),'-pix_fmt','yuv420p','-r',str(o['fps']),
                '-threads',str(limits['threads']),'-movflags','+faststart','-map_metadata','-1',
                '-metadata','title='+('PREVIEW_ONLY NOT_APPROVED_FOR_PUBLICATION' if mode=='REAL_CONTENT_PREVIEW' else 'TEST_ONLY synthetic renderer fixture'),
                '-metadata','comment=Not authorized for production or publishing; no AI editorial quality review',str(output)]
    before=resource.getrusage(resource.RUSAGE_CHILDREN);_,elapsed=ffmpeg(arguments,work,limits);after=resource.getrusage(resource.RUSAGE_CHILDREN)
    if output.stat().st_size>limits['max_output_bytes']:raise Error('Encoded file exceeds disk limit')
    return output,audio,{'elapsed_sec':round(elapsed,3),'child_user_cpu_sec':round(after.ru_utime-before.ru_utime,3),
                         'child_system_cpu_sec':round(after.ru_stime-before.ru_stime,3),'process_children_max_rss_kib':after.ru_maxrss,
                         'max_rss_scope':'cumulative maximum over child processes in this Python invocation',
                         'output_bytes':output.stat().st_size,'threads':limits['threads'],'limits':limits},hashlib.sha256(graph.encode()).hexdigest()


def frame_rgb(path,time_sec,width=180,height=320,limits=DEFAULT_RESOURCES):
    raw,_=run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(safe_path(path)),
               '-ss',n(time_sec),'-frames:v','1','-vf',f'scale={width}:{height}','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],limits,max_bytes=width*height*3)
    if len(raw)!=width*height*3:raise Error('Incomplete decoded frame')
    return raw


def audio_pcm(path,limits=DEFAULT_RESOURCES):
    raw,_=run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(safe_path(path)),
               '-map','0:a:0','-ac','1','-ar','48000','-f','f32le','pipe:1'],limits,max_bytes=35000000)
    if len(raw)%4:raise Error('Invalid decoded PCM')
    values=array('f');values.frombytes(raw)
    if not values or any(not math.isfinite(x) for x in values):raise Error('Invalid/missing audio samples')
    return values


def verify_output(path,timeline,expected_audio,limits=DEFAULT_RESOURCES):
    o=timeline['output_settings'];info=media_info(path,limits);tolerance=o['timing_tolerance_frames']/o['fps']+1024/48000
    if (info['width'],info['height'],info['video_codec'],info['pixel_format'])!=(o['width'],o['height'],'h264','yuv420p'):
        raise Error('Output video metadata mismatch')
    if info['fps']!=o['fps'] or abs(info['duration_sec']-timeline['expected_duration_sec'])>tolerance:
        raise Error('Output FPS/duration mismatch')
    if info['audio_present']!=expected_audio or (expected_audio and info['audio_codec']!='aac'):raise Error('Unexpected missing/extra audio or codec')
    if expected_audio and (info['audio_sample_rate']!=48000 or info['audio_channels']!=2 or abs(info['audio_duration_sec']-timeline['expected_duration_sec'])>tolerance):
        raise Error('Audio format/duration mismatch')
    raw,_=run(['ffprobe','-v','error','-show_frames','-show_entries','frame=media_type,best_effort_timestamp_time',
               '-of','json',str(safe_path(path))],limits,max_bytes=4194304)
    frames=json.loads(raw);times={'video':[],'audio':[]}
    for frame in frames['frames']:
        kind=frame.get('media_type')
        if kind in times:
            t=float(frame['best_effort_timestamp_time'])
            if not math.isfinite(t):raise Error('Nonfinite output PTS')
            times[kind].append(t)
    for kind,values in times.items():
        if not values:
            if kind=='video' or expected_audio:raise Error('Missing output timestamp series')
            continue
        gap=2/o['fps'] if kind=='video' else 2*1024/48000
        if values[0]<-.0001 or values[0]>gap or any(b<=a or b-a>gap+.00001 for a,b in zip(values,values[1:])):
            raise Error('Discontinuous output presentation timestamps')
    run(['ffmpeg','-v','error','-xerror','-nostdin','-protocol_whitelist','file,pipe','-i',str(path),'-f','null','-'],limits,max_bytes=65536)
    result={'ffprobe_checked':True,'decoded_to_completion':True,'presentation_timestamps_continuous':True,
            'duration_tolerance_sec':tolerance,'frame_count':len(times['video']),'audio_frame_count':len(times['audio']),'metadata':info}
    if expected_audio:
        pcm=audio_pcm(path,limits);peak=max(abs(x) for x in pcm);rms=math.sqrt(sum(x*x for x in pcm)/len(pcm))
        if peak>=.999:raise Error('Output audio clipping risk detected')
        result['audio_signal']={'peak_linear':peak,'rms_linear':rms,'sample_count':len(pcm),'scope':'technical signal check, not speech intelligibility or musical quality proof'}
    return result
