"""Typed libass text compiler. Only bounded numeric tags and literal text enter ASS."""
from pathlib import Path
import re
import unicodedata
import renderer_core_v01 as core

FONTS={'dejavu_sans':'DejaVu Sans','dejavu_sans_bold':'DejaVu Sans'}


def literal(text):
    # ASS metacharacters cannot be escaped reliably across libass versions.
    if not text or re.search(r'[{}\\\x00-\x08\x0b-\x1f]',text) or any(unicodedata.category(c).startswith('C') and c!='\n' for c in text):
        raise core.Error('Unsafe ASS caption text')
    return text.replace('\n',r'\N')


def color(value):
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}',value):raise core.Error('Invalid text color')
    return '&H'+value[5:7]+value[3:5]+value[1:3]+'&'


def clock(seconds):
    # Quantization is explicit and independently bounded to one centisecond.
    ticks=round(seconds*100)
    return f'{ticks//360000}:{ticks//6000%60:02d}:{ticks//100%60:02d}.{ticks%100:02d}'


def tags(style,start,end,width,height,*,offset=None,span=None):
    x,y=round(style['x']*width),round(style['y']*height)
    duration=round((end-start)*1000);enter=round(style['enter_sec']*1000);exit=round(style['exit_sec']*1000)
    value=rf'\an5\fn{FONTS[style["font"]]}\b{int(style["font"]=="dejavu_sans_bold")}\fs{style["size_px"]}\bord{style["outline_px"]}\shad0\1c{color(style["color"])}\3c&H000000&'
    if offset is not None:
        def ramp(t,direction):
            mode=style[direction];seconds=style[direction+'_sec']
            if mode=='none':return 1
            return min(1,max(0,(t if direction=='enter' else end-start-t)/seconds))
        def position(t):
            return y+(1-ramp(t,'enter'))*height*.015*(style['enter']=='slide')-(1-ramp(t,'exit'))*height*.015*(style['exit']=='slide')
        ya,yb=round(position(offset)),round(position(offset+span));ms=round(span*1000)
        value+=rf'\move({x},{ya},{x},{yb},0,{ms})' if ya!=yb else rf'\pos({x},{ya})'
        def factor(t,mode):return min(ramp(t,k) if style[k]==mode else 1 for k in ('enter','exit'))
        alpha_a=round(255*(1-factor(offset,'fade')));alpha_b=round(255*(1-factor(offset+span,'fade')))
        value+=rf'\alpha&H{alpha_a:02X}&\t(0,{ms},\alpha&H{alpha_b:02X}&)'
        scale_a=85+15*factor(offset,'pop');scale_b=85+15*factor(offset+span,'pop')
        value+=rf'\fscx{scale_a:.3f}\fscy{scale_a:.3f}\t(0,{ms},\fscx{scale_b:.3f}\fscy{scale_b:.3f})'
        return value
    if style['enter']=='slide':value+=rf'\move({x},{y+round(height*.015)},{x},{y},0,{enter})'
    elif style['exit']=='slide':value+=rf'\move({x},{y},{x},{y-round(height*.015)},{duration-exit},{duration})'
    else:value+=rf'\pos({x},{y})'
    value+=rf'\fad({enter if style["enter"]=="fade" else 0},{exit if style["exit"]=="fade" else 0})'
    if style['enter']=='pop':value+=rf'\fscx85\fscy85\t(0,{enter},\fscx100\fscy100)'
    if style['exit']=='pop':value+=rf'\t({duration-exit},{duration},\fscx85\fscy85)'
    return value


def document(cues,output):
    width,height=output['width'],output['height']
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines=[]
    for cue in cues:
        a,b,s=cue['start_sec'],cue['end_sec'],cue['style']
        words=cue.get('words',[])
        boundaries=sorted({a,b,*[max(a,min(b,w[k])) for w in words for k in ('start_sec','end_sec')]})
        if words:boundaries=sorted(set(boundaries+[a+s['enter_sec'],b-s['exit_sec']]))
        for left,right in zip(boundaries,boundaries[1:]):
            if right-left<.005:continue
            active=[i for i,w in enumerate(words) if w['start_sec']<right and w['end_sec']>left]
            if words:
                text=' '.join(('{'+rf'\1c{color(s["active_color"] if i in active else s["color"])}'+'}'+literal(w['text'])) for i,w in enumerate(words))
            else:text=literal(cue['text'])
            treatment=tags(s,a,b,width,height,offset=left-a,span=right-left) if words else tags(s,a,b,width,height)
            lines.append(f'Dialogue: 0,{clock(left)},{clock(right)},Default,,0,0,0,,{{{treatment}}}{text}')
    return header+'\n'.join(lines)+'\n'


def filter_for(timeline,work):
    path=Path(work)/'automatic-text.ass'
    path.write_text(document(timeline['automatic_text_cues'],timeline['output_settings']),encoding='utf8')
    return f'subtitles=filename={path}:fontsdir={core.FONT.parent}',path
