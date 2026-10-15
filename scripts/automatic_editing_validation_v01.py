"""Independent automatic PRIVATE preview admission. Never grants human/production gates."""
import copy
import json
from pathlib import Path
import re
import jsonschema
import automatic_text_v01 as text
import renderer_revision_v02 as audio

core=audio.core
ROOT=core.base.ROOT/'data/revisions/stage59/automatic'
SCHEMA='src/schemas/automatic-editing-plan.v0.1.schema.json'
VERSION='automatic-editing-0.1.0'
POLICY_VERSION='automatic-preview-policy-0.2.0'
REVIEW_CODES={
    'poor_framing':'editorial','shot_repetition':'editorial','jump_cut':'editorial',
    'pacing':'editorial','weak_ending':'editorial','text_style':'editorial',
    'caption_density':'editorial','audio_balance':'editorial',
    'text_unreadable':'readability','text_clipped':'readability','text_invisible':'readability',
    'subtitle_uncertain':'technical_evidence','unsupported_claim':'technical_evidence',
    'decode_failure':'technical_evidence','audio_clipping':'technical_evidence',
    'audio_discontinuity':'technical_evidence'}


def finding(code,category,severity,diagnosis,location=''):
    return {'code':code,'category':category,'severity':severity,'diagnosis':diagnosis,'location':location}


def review_findings(response):
    """Model severity cannot soften evidence/readability blockers. Raw response stays intact."""
    findings=[]
    for issue in response['issues']:
        code=issue.get('code')
        if code is None:
            # Read-only compatibility for historical reports, never guess away ambiguous text/audio risks.
            code={'framing':'poor_framing','repetition':'shot_repetition','pacing':'pacing',
                'ending':'weak_ending','subtitle':'subtitle_uncertain','text':'text_unreadable',
                'audio':'audio_discontinuity'}.get(issue['category'],'unknown_review_issue')
            diagnosis=issue['diagnosis'].lower()
            if issue['category']=='text':
                if re.search(r'unsupported|unsubstantiated|condition claim|kondisi prima',diagnosis):code='unsupported_claim'
                elif not re.search(r'unreadable|illegible|clipp|invisible|cannot read|not visible',diagnosis) and re.search(r'font|typograph|colo[u]?r|styling|hierarchy',diagnosis):code='text_style'
            if issue['category']=='audio' and not re.search(r'clipp|discontin|dropout|distort|missing|desync',diagnosis) and re.search(r'balance|volume|too loud|too quiet|boomy',diagnosis):code='audio_balance'
        if code not in REVIEW_CODES:raise core.Error('Unknown Reviewer policy code')
        category=REVIEW_CODES[code]
        severity=issue.get('severity','major') if category=='editorial' else 'blocker'
        if severity not in ('minor','major','blocker'):raise core.Error('Invalid Reviewer severity')
        # Artistic judgments remain advisory even if the model calls them blocking.
        if category=='editorial' and severity=='blocker':severity='major'
        value=finding(code,category,severity,issue['diagnosis'])
        value.update(start_sec=issue['start_sec'],end_sec=issue['end_sec'],basis='model_unverified')
        findings.append(value)
    return {'policy_version':POLICY_VERSION,
        'blocking_findings':[f for f in findings if f['severity']=='blocker'],
        'advisory_findings':[f for f in findings if f['severity']!='blocker']}


def code_receipts():
    names=['scripts/automatic_text_v01.py','scripts/automatic_editing_validation_v01.py',
        'scripts/run_automatic_editing_v01.py',SCHEMA,'scripts/render_showcase_preview_v01.py',
        'scripts/generate_remote_speech_evidence_v01.py','scripts/generate_speech_evidence_v01.py']
    return audio.code_receipts()+[audio.qa.ref(core.base.ROOT/p) for p in names]


def convert(proposal,packet):
    """Copy explicit AI choices to the existing visual compiler; no editorial repair."""
    source=packet['source'];shots=[];operations=[];cursor=core.rational(0);parameters={}
    for order,s in enumerate(proposal['shots'],1):
        shots.append({'shot_id':s['id'],'order':order,'source_start_sec':s['start_sec'],'source_end_sec':s['end_sec'],
            'timing_precision':'approximate','evidence_refs':s['evidence_refs'],'rationale':s['rationale'],
            'timing':{'speed':s['speed'],'freeze_sec':0,'transition_out':s['transition_out'],'overlap_sec':s['overlap_sec']},
            'speech_safe':False,'review_required':True})
        length=(core.rational(s['end_sec'])-core.rational(s['start_sec']))/core.rational(s['speed'])
        if s['scale']!=1:
            operations.append({'operation_id':'frame-'+s['id'],'kind':'zoom','shot_id':s['id'],
                'output_start_sec':float(cursor),'output_end_sec':float(cursor+length),
                'evidence_refs':s['evidence_refs'],'rationale':s['rationale'],'capability_status':'requires_implementation',
                'parameters':{'scale':s['scale'],'center_x':s['center_x'],'center_y':s['center_y']}})
        if s.get('grade'):
            uid='grade-'+s['id'];parameters[uid]={'color':s['grade']}
            operations.append({'operation_id':uid,'kind':'color_grade','shot_id':s['id'],
                'output_start_sec':float(cursor),'output_end_sec':float(cursor+length),
                'evidence_refs':s['evidence_refs'],'rationale':s['rationale'],'capability_status':'requires_implementation',
                'parameters':{'intent':proposal['decisions']['effects']}})
        cursor+=length-core.rational(s['overlap_sec'])
    first=shots[0];hook={k:first[k] for k in ('shot_id','source_start_sec','source_end_sec','timing_precision','evidence_refs','rationale')}
    d=proposal['decisions']
    variant={'variant_id':'A','title':'Automatic private preview','editorial_concept':proposal['concept'],
        'intended_message':proposal['concept'],'narrative_strategy':d['shot_selection'],'hook':hook,'shots':shots,
        'estimated_output_duration_sec':round(float(cursor),2),'operations':operations,
        'audio_strategy':{'intent':d['audio'],'sync_basis':'none','evidence_refs':first['evidence_refs']},
        'ending':{'intent':d['ending'],'cta':None},'required_reviews':['Human review remains pending']}
    plan={'contract_version':'0.3.0','plan_status':'DRAFT_UNVALIDATED','source':source,
        'evidence_packet_sha256':core.director.validator.packet_digest(packet),'editorial_concept':proposal['concept'],
        'intended_message':proposal['concept'],'proposed_variant_count':1,'variants':[variant],'missing_evidence':[],
        'required_reviews':['Automatic private eligibility is separate from human verification'],
        'factual_claims':[],'renderer_capabilities':{'verification_status':'unknown','supported_operations':[]},
        'render_readiness':'BLOCKED_FOR_RENDER','publish_ready':False,'render_approved':False,'publish_approved':False}
    plan['missing_evidence']=packet['missing_evidence']
    chosen=proposal['audio'];bed=audio.original_audio(source)
    if chosen['mode']=='continuous_source':
        bed.update(mode='continuous_source',source_range={'start_sec':chosen['start_sec'],'end_sec':float(core.rational(chosen['start_sec'])+cursor)},
            gain_db=chosen['gain_db'],fade_in_sec=chosen['fade_in_sec'],fade_out_sec=chosen['fade_out_sec'])
    elif any(chosen[k]!=0 for k in ('start_sec','gain_db','fade_in_sec','fade_out_sec')):
        # Original audio adjustments use the shared explicit audio operation, not discarded fields.
        if chosen['start_sec']!=0 or chosen['fade_in_sec'] or chosen['fade_out_sec']:
            raise core.Error('Original dialogue audio accepts gain only; source timing follows shots')
        for i,s in enumerate(shots):
            a=sum((v['source_end_sec']-v['source_start_sec'])/v['timing']['speed']-v['timing']['overlap_sec'] for v in shots[:i])
            b=a+(s['source_end_sec']-s['source_start_sec'])/s['timing']['speed']
            operations.append({'operation_id':'gain-'+s['shot_id'],'kind':'audio_gain','shot_id':s['shot_id'],
                'output_start_sec':round(a,9),'output_end_sec':round(b,9),'evidence_refs':s['evidence_refs'],
                'rationale':d['audio'],'capability_status':'requires_implementation','parameters':{'gain_db':chosen['gain_db']}})
    return plan,audio.spec_for(plan,bed,parameters)


def envelope(cue,width=1080,height=1920):
    s=cue['style'];lines=cue['text'].split('\n');tw=max(map(len,lines))*s['size_px'];th=1.5*s['size_px']*len(lines)
    pad=s['outline_px']+2;motion=.015*height if 'slide' in (s['enter'],s['exit']) else 0
    x,y=s['x']*width,s['y']*height
    return [x-tw/2-pad,y-th/2-pad-motion,x+tw/2+pad,y+th/2+pad+motion]


def check_style(cue,advisories=None):
    s=cue['style'];text.literal(cue['text'])
    if len(cue['text'].split('\n'))>3:raise core.Error('At most three text lines')
    for mode,key in ((s['enter'],'enter_sec'),(s['exit'],'exit_sec')):
        if (mode=='none' and s[key]!=0) or (mode!='none' and not .05<=s[key]<=1):raise core.Error('Animation mode/duration mismatch')
    if s['enter_sec']+s['exit_sec']>cue['end_sec']-cue['start_sec']-.2:raise core.Error('Insufficient readable text hold')
    if s['enter']==s['exit']=='slide':raise core.Error('One bounded slide per cue; choose another exit')
    rect=envelope(cue)
    notes=[]
    if rect[0]<86.4 or rect[1]<153.6 or rect[2]>885.6 or rect[3]>1497.6:
        notes.append(finding('estimated_safe_area','readability','major',
            'Conservative text/motion envelope exceeds portrait safe area; inspect actual rendered glyphs',cue['id']))
    if len(cue['text'].replace('\n',''))/(cue['end_sec']-cue['start_sec'])>22:
        notes.append(finding('estimated_reading_rate','readability','minor',
            'Text exceeds preferred 22 characters/second; actual-MP4 readability review required',cue['id']))
    if advisories is not None:advisories.extend(notes)
    return rect


def cues_for(proposal,timeline,speech,advisories=None):
    shots={s['shot_id']:s for s in timeline['shots']};cues=[]
    for o in proposal['overlays']:
        s=shots[o['shot_id']]
        if not s['output_start_sec']<=o['start_sec']<o['end_sec']<=s['output_end_sec']:
            raise core.Error('Caption must lie within its shot on OUTPUT timeline')
        cues.append({'id':o['id'],'role':'creative_text_overlay','start_sec':o['start_sec'],'end_sec':o['end_sec'],
            'text':o['text'],'style':o['style'],'evidence_refs':o['evidence_refs'],'human_verified':False})
    used=set();units={u['id']:u for u in speech.get('units',[])}
    for group in proposal['subtitle_groups']:
        shot=shots[group['shot_id']];selected=[units[i] for i in group['unit_ids']]
        if used.intersection(group['unit_ids']):raise core.Error('Duplicate subtitle timing unit')
        used.update(group['unit_ids'])
        if any(u['start_sec']<shot['source_start_sec'] or u['end_sec']>shot['source_end_sec'] for u in selected):
            raise core.Error('Subtitle timing outside selected speech shot')
        if any(a['end_sec']>b['start_sec']+.01 for a,b in zip(selected,selected[1:])):raise core.Error('Subtitle units out of order')
        def mapped(t):return round(shot['output_start_sec']+(t-shot['source_start_sec'])/shot['speed'],6)
        words=[{'text':u['text'],'start_sec':mapped(u['start_sec']),'end_sec':mapped(u['end_sec'])} for u in selected]
        phrase=' '.join(u['text'] for u in selected)
        if speech['timing']=='word' and not 2<=len(selected)<=5:raise core.Error('Word subtitle groups need 2–5 actual words')
        if speech['timing']=='word' and group.get('line_breaks_after'):raise core.Error('Word groups already short; no phrase-fallback line splitting')
        if speech['timing']=='phrase':
            if len(selected)!=1:raise core.Error('Phrase fallback must use one actual provider segment')
            tokens=phrase.split();breaks=group.get('line_breaks_after',[]);cuts=[0,*breaks,len(tokens)]
            if breaks!=sorted(breaks) or any(not 0<=a<b<=len(tokens) or b-a>5 for a,b in zip(cuts,cuts[1:])):
                raise core.Error('Phrase fallback requires readable lines of at most five words using exact source text')
            phrase='\n'.join(' '.join(tokens[a:b]) for a,b in zip(cuts,cuts[1:]))
        cues.append({'id':group['id'],'role':'automatic_speech_subtitle','start_sec':words[0]['start_sec'],
            'end_sec':words[-1]['end_sec'],'text':phrase,'style':group['style'],
            'words':words if speech['timing']=='word' else [],'timing_basis':'provider_estimated',
            'human_verified':False,'evidence_refs':group['unit_ids']})
    if speech['required']:
        selected_units={u['id'] for u in units.values() if any(s['source_start_sec']<=u['start_sec'] and u['end_sec']<=s['source_end_sec'] for s in shots.values())}
        if not selected_units or used!=selected_units:raise core.Error('Selected dialogue must be fully covered by source-bound subtitle units')
    for i,cue in enumerate(cues):
        rect=check_style(cue,advisories)
        for other in cues[:i]:
            r=envelope(other)
            if max(cue['start_sec'],other['start_sec'])<min(cue['end_sec'],other['end_sec']) and max(rect[0],r[0])<min(rect[2],r[2]) and max(rect[1],r[1])<min(rect[3],r[3]):
                if advisories is not None:advisories.append(finding('estimated_text_overlap','readability','major',
                    'Conservative concurrent text envelopes overlap; inspect actual glyphs/readability',cue['id']+'/'+other['id']))
    return cues


def validate(proposal,packet,speech):
    findings=[];advisories=[];legacy=None;plan=spec=timeline=None
    try:
        schema=json.loads((core.base.ROOT/SCHEMA).read_text())
        jsonschema.Draft202012Validator(schema).validate(proposal)
        core.director.safe_text(json.dumps(proposal,ensure_ascii=False))
        if proposal['source_sha256']!=packet['source']['sha256']:raise core.Error('Director source contamination')
        ids=[s['id'] for s in proposal['shots']]
        textids=[o['id'] for o in proposal['overlays']+proposal['subtitle_groups']]
        if len(set(ids))!=len(ids) or len(set(textids))!=len(textids) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',i) for i in ids+textids):raise core.Error('Duplicate/unsafe shot or text identity')
        for s in proposal['shots']:
            if not 0<=s['start_sec']<s['end_sec']<=packet['source']['duration_sec']:raise core.Error('Shot exceeds source')
            if s['transition_out']=='cut' and s['overlap_sec']!=0:raise core.Error('Cut cannot have overlap')
            if s['transition_out']=='crossfade' and s['overlap_sec']<=0:raise core.Error('Crossfade requires positive overlap')
            for k in ('center_x','center_y'):
                if not 1/(2*s['scale'])<=s[k]<=1-1/(2*s['scale']):raise core.Error('Reframe extends outside source')
        if proposal['shots'][-1]['overlap_sec']:raise core.Error('Final shot cannot overlap absent shot')
        ledger=packet['evidence_ledger']
        if any(e not in ledger for o in proposal['shots']+proposal['overlays'] for e in o['evidence_refs']):raise core.Error('Unknown source evidence ID')
        for o in proposal['overlays']:
            # A showroom picture cannot establish commercial or mechanical facts.
            if re.search(r'\b(kondisi\s+prima|bebas\s+(banjir|tabrak)|garansi|termurah|terbaik|kilometer\s+rendah|siap\s+pakai|tersedia|stok\s+ready|diskon|cicilan|\d+\s*(juta|rupiah))\b',o['text'],re.I):
                raise core.Error('Unsupported commercial/vehicle-condition claim in creative caption: '+o['text'])
        if speech['source_sha256']!=packet['source']['sha256'] or speech['human_verified'] is not False:raise core.Error('Speech source/human boundary violation')
        if speech['required']:
            if speech['status']!='AUTO_PREVIEW_ELIGIBLE' or proposal['audio']['mode']!='original':raise core.Error('Dialogue needs independently admitted ASR and original shot audio')
            if any(s['speed']!=1 or s['overlap_sec'] for s in proposal['shots']):raise core.Error('Automatic dialogue currently needs real-time straight-cut speech-safe ranges')
            for s in proposal['shots']:
                for u in speech['units']:
                    if max(s['start_sec'],u['start_sec'])<min(s['end_sec'],u['end_sec']) and not s['start_sec']<=u['start_sec']<u['end_sec']<=s['end_sec']:
                        raise core.Error('Dialogue edit cuts inside a timed speech unit')
        elif proposal['subtitle_groups']:raise core.Error('Subtitles without speech')
        plan,spec=convert(proposal,packet);timeline=audio.compile_timeline(plan,spec)
        legacy=core.director.validator.validate_plan(plan,packet)
        # Human speech gate stays intact. The new preview contract owns automatic ASR eligibility.
        automatic_speech_scope={'speech_intelligence:speech_selection_without_independent_boundary_and_context_support',
            'speech_intelligence:noncontiguous_or_reordered_dialogue','speech_intelligence:speech_audio_treatment_not_independently_supported'}
        structural=[f for f in legacy['blocking_findings'] if not (speech['required'] and f['code'] in automatic_speech_scope)]
        if not legacy['structural_validity'] or structural:raise core.Error('Existing independent visual validator blocked: '+str(structural))
        cues=cues_for(proposal,timeline,speech,advisories)
        if not speech['required']:
            covered={o['shot_id'] for o in proposal['overlays']}
            if len(covered)<=len(ids)/2:advisories.append(finding('caption_density','editorial','minor',
                'Creative captions cover no more than half the shots; prefer more presence when relevant'))
            covered_time=0;last_end=0
            for cue in sorted(cues,key=lambda c:c['start_sec']):
                covered_time+=max(0,cue['end_sec']-max(last_end,cue['start_sec']))
                last_end=max(last_end,cue['end_sec'])
            if covered_time>=timeline['expected_duration_sec']-.3:advisories.append(finding('text_free_pause','editorial','minor',
                'No substantial text-free viewing pause; prefer breathing space'))
        timeline['automatic_text_cues']=cues
    except (core.Error,jsonschema.ValidationError,KeyError,ValueError,TypeError) as error:
        diagnosis=str(error)[:1800]
        code='unsupported_claim' if 'Unsupported commercial/vehicle-condition claim' in diagnosis else 'invalid_plan_or_evidence'
        findings=[finding(code,'technical_evidence','blocker',diagnosis)]
    return {'contract_version':VERSION,'status':'BLOCKED' if findings else 'AUTO_PREVIEW_ELIGIBLE',
        'policy_version':POLICY_VERSION,'blocking_findings':findings,'advisory_findings':advisories,
        'findings':findings,'legacy_validation':legacy,'human_verified':False,'production_eligible':False,
        'publishing_eligible':False,'plan_sha256':core.digest_object(proposal)},plan,spec,timeline


def admit(context,plan,spec,source,timeline):
    """Replay input/code/environment/proof/plan and consume a new permit exactly once."""
    from run_automatic_editing_v01 import read,write,check_proof,verify_inputs
    job=core.safe_path(Path(context['job'])/'request.json',under=ROOT).parent
    request=read(job/'request.json');verify_inputs(request)
    if request['code_receipts']!=code_receipts() or request['environment']!=core.environment():raise core.Error('Automatic code/environment lineage changed')
    proof=check_proof(request['proof'])
    attempt=core.safe_path(Path(context['attempt'])/'reservation.json',under=job).parent
    proposal=read(attempt/'proposal.json');packet=read(job/'packet.json');speech=read(job/'speech.json')
    reservation=read(attempt/'reservation.json')
    raw=core.safe_path(attempt/'raw-response.json').read_text()
    prompt=core.safe_path(attempt/'prompt.txt').read_text()
    if (core.director.parse_response(raw)!=proposal or reservation['prompt_sha256']!=core.director.digest_text(prompt)
            or reservation['request_sha256']!=core.digest_object(request) or reservation['attached_images']!=request['storyboard']
            or not 1<=reservation['attempt']<=3 or len(list(job.glob('proposal-*/reservation.json')))>3):
        raise core.Error('Director raw/request/reservation provenance mismatch')
    from run_automatic_editing_v01 import verify_speech
    core.intake.validate_packet(packet)
    verify_speech(packet,speech)
    report,replayed,spec_replay,graph=validate(proposal,packet,speech)
    if report['status']!='AUTO_PREVIEW_ELIGIBLE' or report!=read(attempt/'validation.json') or plan!=replayed or spec!=spec_replay:
        raise core.Error('Independent automatic plan replay mismatch')
    if set(graph['required_capabilities'])-set(proof['verified_capabilities']):
        raise core.Error('Plan uses capability without current physical proof')
    if source!=core.safe_path(packet['source']['path']) or core.intake.gate.sha256_file(source)!=packet['source']['sha256']:
        raise core.Error('Automatic media contamination')
    permit=read(attempt/'permit.json')
    expected={'scope':'STAGE59_PRIVATE_PREVIEW','human_verified':False,'production_eligible':False,
        'source_sha256':packet['source']['sha256'],'proposal_sha256':core.digest_object(proposal),
        'execution_sha256':core.digest_object(spec),'request_sha256':core.digest_object(request)}
    if permit!=expected:raise core.Error('Automatic permit mismatch')
    # Exclusive write is the consumption operation; historical markers are never reset.
    write(attempt/'permit-consumed.json',{'permit_sha256':core.digest_object(permit),'scope':'PRIVATE_PREVIEW_ONLY'})
    return graph
