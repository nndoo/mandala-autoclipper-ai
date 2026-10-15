#!/usr/bin/env python3
"""Prepare segment captions on output time; drafts never authorize video rendering."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import textwrap

import renderer_core_v01 as core
import speech_intelligence_v01 as speech
import adaptive_text_v01 as text_policy


def clock(sec):
    ms=round(Fraction(str(sec))*1000)
    hours,ms=divmod(ms,3600000); minutes,ms=divmod(ms,60000); seconds,ms=divmod(ms,1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}'


def captions(report, windows, *, width=1080, height=1920):
    if not report['eligibility']['reviewed_transcript'] or not report.get('human_review'):
        raise core.Error('Only explicitly reviewed transcript text can supply captions')
    if type(width) is not int or type(height) is not int or not 180<=width<=2160 or not 320<=height<=3840:
        raise core.Error('Unsupported caption canvas')
    if not windows or len(windows)>64 or any(not isinstance(w,list) or len(w)!=2 or not speech.range_ok(*w,report['source']['duration_sec']) for w in windows):
        raise core.Error('Invalid selected source windows')
    texts={r['segment_id']:r['reviewed_text'] for r in report['human_review']['text_reviews'] if r['accuracy_confirmed']}
    manual={r['segment_id']:r for r in report['human_review'].get('subtitle_source_reviews',[])
        if r['accuracy_confirmed'] and r['max_error_sec']<=speech.MAX_BOUNDARY_ERROR_SEC}
    cues=[]; elapsed=Fraction(0)
    for index,(a,b) in enumerate(windows):
        for segment in report['segments']:
            approved=manual.get(segment['segment_id'])
            start,end=(approved['source_start_sec'],approved['source_end_sec']) if approved else (segment['start_sec'],segment['end_sec'])
            if max(a,start)>=min(b,end): continue
            if not a<=start<end<=b:
                raise core.Error('Selection crosses a transcript segment; no caption timestamp invention')
            text=texts.get(segment['segment_id'])
            if not text: raise core.Error('Selected segment lacks accepted text')
            mapped_start=float(elapsed+Fraction(str(start))-Fraction(str(a)))
            mapped_end=float(elapsed+Fraction(str(end))-Fraction(str(a)))
            cues.append({'segment_id':segment['segment_id'],'selection_index':index,
                'source_start_sec':start,'source_end_sec':end,'output_start_sec':mapped_start,'output_end_sec':mapped_end,'text':text,
                'timing_basis':'human_source_review' if approved else 'asr_estimate'})
        elapsed+=Fraction(str(b))-Fraction(str(a))
    if not cues: raise core.Error('No selected reviewed speech; do not force dialogue subtitles')
    if any(a['output_end_sec']>b['output_start_sec'] for a,b in zip(cues,cues[1:])):
        raise core.Error('Overlapping segment captions require a separate reviewed layout')
    size=min(52,max(10,width//20))
    while size>=max(10,width//36):
        try:
            for cue in cues:
                cue['display_text']='\n'.join(textwrap.wrap(' '.join(cue['text'].split()),width=max(1,int(.74*width)//size),break_long_words=False,break_on_hyphens=False))
                core.checked_text(cue['display_text'],size,{'width':width,'height':height})
                text_policy.box(cue['display_text'],size,width,height,'bottom',text_policy.SOCIAL_PROFILE)
            break
        except (core.Error,ValueError): size-=1
    else: raise core.Error('Reviewed segment text cannot fit safe subtitle layout')
    return {'contract_version':'0.1.0','source':report['source'],'speech_evidence_sha256':speech.digest(report),
        'status':'DRAFT_NOT_EXECUTABLE','source_windows':windows,'cues':cues,'output_duration_sec':float(elapsed),
        'style':{'font':'DejaVu Sans','font_size_px':size,'font_color':'white','outline':'black','outline_width_px':2,
            'position':'bottom','bottom_margin_fraction':.22,'right_margin_fraction':.18,
            'text_layout':text_policy.SOCIAL_PROFILE,'maximum_lines':3,'word_animation':False},
        'timing_precision':'human_source_review' if all(c['timing_basis']=='human_source_review' for c in cues) else 'asr_estimate_or_mixed',
        'word_timestamps':'unavailable','segment_alignment':report['eligibility']['segment_alignment'],
        'semantic_cuts':report['eligibility']['semantic_cuts'],'render_admission':'NOT_GRANTED',**speech.FLAGS}


def srt(cues):
    return '\n\n'.join(f"{i}\n{clock(c['output_start_sec'])} --> {clock(c['output_end_sec'])}\n{c['display_text']}" for i,c in enumerate(cues,1))+'\n'


def prepare(report_path, output, *, windows):
    report=speech.load_report(report_path); draft=captions(report,windows)
    draft['speech_report']=speech.av.reference(core.safe_path(report_path))
    draft['code_receipts']=[speech.av.reference(Path(p).resolve()) for p in (__file__,text_policy.__file__,core.__file__)]
    from run_adaptive_director_v03 import publish
    return publish(output,{'segment-subtitles.draft.v01.json':draft,'segment-subtitles.draft.srt':srt(draft['cues'])})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('report','windows','output'):p.add_argument('--'+name,required=True)
    args=p.parse_args()
    try:
        selection=speech.read(args.windows)
        output=prepare(args.report,args.output,windows=selection['source_windows'])
        print(json.dumps({'status':'DRAFT_NOT_EXECUTABLE','bundle':speech.shared.relative(output),**speech.FLAGS}));return 0
    except (core.Error,OSError,ValueError,KeyError,TypeError):
        print('BLOCKED: transcript, selection, timing or subtitle layout');return 1


if __name__=='__main__':
    with speech.intake.processing_deadline():raise SystemExit(main())
