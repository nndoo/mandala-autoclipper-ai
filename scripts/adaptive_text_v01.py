"""Text roles and layout checks shared by independent validation and FFmpeg compilation."""

VERSION='0.1.0'
ROLES={'subtitle':'speech_subtitle','overlay':'creative_text_overlay'}
SOCIAL_PROFILE='social_portrait.v01'


def text_operations(variant):
    return [o for o in variant['operations'] if o['kind'] in ROLES]


def plan_findings(variant, packet):
    findings=[]; ops=text_operations(variant)
    for op in ops:
        caption=op['parameters']['caption']; text=caption['text']; location=variant['variant_id']+'/'+op['operation_id']
        if op['kind']=='subtitle' and text is not None:
            if caption['kind']=='creative_copy':
                findings.append({'code':'creative_copy_is_not_speech_subtitle','location':location})
            if packet['speech']['requirements']['overall_requirement']=='not_required':
                findings.append({'code':'subtitle_without_classified_speech','location':location})
        if op['kind']=='overlay' and caption['kind'] in ('asr_draft','verified_quote'):
            findings.append({'code':'speech_quote_must_use_subtitle_role','location':location})
    for i,a in enumerate(ops):
        for b in ops[i+1:]:
            if (a['parameters']['caption']['text'] is not None and b['parameters']['caption']['text'] is not None
                    and a['parameters']['position']==b['parameters']['position']
                    and max(a['output_start_sec'],b['output_start_sec'])<min(a['output_end_sec'],b['output_end_sec'])):
                findings.append({'code':'text_collision_same_position','location':variant['variant_id']+'/'+a['operation_id']+'/'+b['operation_id']})
    return findings


def box(text, size, width, height, position, profile=None):
    """Conservative glyph envelopes, not optical glyph/subject tracking."""
    lines=text.split('\n'); tw=max(map(len,lines))*size; th=1.5*size*len(lines)
    if profile is None:
        left,right,top,bottom=.06*width,.94*width,.08*height,.88*height
        x=(width-tw)/2
        y={'top':.08*height,'center':(height-th)/2,'bottom':.88*height-th}[position]
    elif profile==SOCIAL_PROFILE:
        left,right,top,bottom=.08*width,.82*width,.08*height,.78*height
        x=(left+right-tw)/2
        y={'top':top+4,'center':(top+bottom-th)/2,'bottom':bottom-4-th}[position]
    else: raise ValueError('Unknown text safe-area profile')
    # Four pixels cover outline/shadow in the collision envelope.
    rect=[x-4,y-4,x+tw+4,y+th+4]
    if x<left-1e-6 or x+tw>right+1e-6 or y<top-1e-6 or y+th>bottom+1e-6:
        raise ValueError('Text exceeds conservative safe area')
    if profile==SOCIAL_PROFILE and (rect[0]<left or rect[1]<top or rect[2]>right or rect[3]>bottom):
        raise ValueError('Text outline/shadow exceeds conservative safe area')
    return rect


def validate_layout(operations, output):
    records=[]
    for op in operations:
        if op['effective_kind'] not in ROLES: continue
        p=op['parameters']; extra=op['execution_parameters']; width,height=output['width'],output['height']
        size=extra.get('font_size_px',max(10,width//12))
        rect=box(p['caption']['text'],size,width,height,p['position'],extra.get('text_layout'))
        records.append({'operation_id':op['operation_id'],'text_role':ROLES[op['effective_kind']],
            'output_start_sec':op['output_start_sec'],'output_end_sec':op['output_end_sec'],'conservative_box_px':rect})
    for i,a in enumerate(records):
        for b in records[i+1:]:
            ar,br=a['conservative_box_px'],b['conservative_box_px']
            if (max(a['output_start_sec'],b['output_start_sec'])<min(a['output_end_sec'],b['output_end_sec'])
                    and max(ar[0],br[0])<min(ar[2],br[2]) and max(ar[1],br[1])<min(ar[3],br[3])):
                raise ValueError('Text collision on output timeline')
    return records


def ffmpeg_position(position, width, height, profile=None):
    if profile==SOCIAL_PROFILE:
        return f'{width}*0.08+({width}*0.74-text_w)/2',{
            'top':f'{height}*0.08+4','center':f'{height}*0.43-text_h/2','bottom':f'{height}*0.78-text_h-4'}[position]
    if profile is not None: raise ValueError('Unknown text safe-area profile')
    return '(w-text_w)/2',{'top':f'{height}*0.08','center':'(h-text_h)/2','bottom':f'h-text_h-{height}*0.12'}[position]


def validate_treatment(extra, duration):
    """Finite bounded fades; no arbitrary expressions or filesystem font paths."""
    animation=extra.get('text_animation')
    if not animation:return
    import math
    total=0
    for direction in ('enter','exit'):
        seconds=animation[direction+'_duration_sec']
        if not math.isfinite(seconds) or (animation[direction]=='none' and seconds!=0) or (animation[direction]=='fade' and not .05<=seconds<=1):
            raise ValueError('Text animation duration contradicts its mode')
        total+=seconds
    if total>duration-.2:raise ValueError('Text fades leave no readable hold interval')


def ffmpeg_treatment(extra, start, end):
    style=extra.get('text_style')
    if style:
        color='0x'+style['color'][1:];outline='0x'+style['outline_color'][1:]
        shadow=1 if style['shadow'] else 0
        result=f'fontcolor={color}:borderw={style["outline_width_px"]}:bordercolor={outline}:shadowx={shadow}:shadowy={shadow}'
    else:result='fontcolor=white:borderw=2:bordercolor=black:shadowx=1:shadowy=1'
    animation=extra.get('text_animation')
    if animation:
        factors=[]
        if animation['enter']=='fade':factors.append(f'min(1,max(0,(t-{start:.9f})/{animation["enter_duration_sec"]:.9f}))')
        if animation['exit']=='fade':factors.append(f'min(1,max(0,({end:.9f}-t)/{animation["exit_duration_sec"]:.9f}))')
        if factors:result+=":alpha='"+'*'.join(factors)+"'"
    return result
