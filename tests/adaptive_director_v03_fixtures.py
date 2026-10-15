"""Synthetic/model-response fixtures only; never production editorial decisions."""
import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import adaptive_director_evidence_v03 as intake
import validate_adaptive_director_plan_v03 as validator
from validate_universal_analysis_v02 import sample_analysis


def packet(speech='absent',music='absent',tags=None):
    canonical=sample_analysis()
    canonical['source'].update(duration_sec=12,width=64,height=64,fps=30)
    canonical['content_profile'].update(speech_presence=speech,music_presence=music,content_tags=tags or ['unfamiliar-content'])
    canonical['segments'][0].update(start_sec=0,end_sec=12,audio_layers=['speech','music'] if speech=='present' and music=='present' else ['speech'] if speech!='absent' else ['music'] if music=='present' else ['silence'])
    canonical['events']=[];canonical['claims']=[];canonical['editing_opportunities']=[]
    source={**canonical['source'],'path':'source.mp4','sha256':'a'*64}
    requirement=intake.gate.speech_requirements(canonical)
    missing=['verified_renderer_capabilities','reliable_music_beat_grid']
    if speech!='absent':missing+=['eligible_transcript','verified_speech_alignment','speech_safe_cut_boundaries']
    e=intake.av.event('audio-1','onset_candidate',2,2.02,metrics={'novelty':.8})
    e['ref']='audio.events.0'
    return {'contract_version':'0.3.0','source':source,'canonical':canonical,
            'editorial_policy':{'max_variants':2,'allow_fewer_variants':True},
            'speech':{'requirements':requirement,'eligibility':{'status':'ineligible','transcript':False,'speech_alignment':False}},
            'audio':{'rhythm':{'status':'unavailable'},'selected_events':[e]},'visual':{'selected_events':[]},'correlation':[],
            'evidence_ledger':{'canonical.segments.0':{'start_sec':0,'end_sec':12,'basis':'model_unverified','timing_precision':'approximate'},
                               'source.metadata':{'start_sec':0,'end_sec':12,'basis':'source_metadata_verified','timing_precision':'not_applicable'},
                               'audio.events.0':{'start_sec':2,'end_sec':2.02,'basis':'signal_candidate','timing_precision':'signal_estimated'}},
            'missing_evidence':missing,'inputs':{},'renderer_capabilities':{'verification_status':'unknown','supported_operations':[]}}


def shot(start=0,end=12,uid='s1',order=1,refs=None):
    return {'shot_id':uid,'order':order,'source_start_sec':start,'source_end_sec':end,'timing_precision':'approximate',
            'evidence_refs':refs or ['canonical.segments.0'],'rationale':'Candidate contextual source moment, pending review',
            'timing':{'speed':1,'freeze_sec':0,'transition_out':'cut','overlap_sec':0},'speech_safe':False,'review_required':True}


def plan(p=None):
    p=p or packet()
    s=shot()
    hook={k:s[k] for k in ('shot_id','source_start_sec','source_end_sec','timing_precision','evidence_refs')}
    hook['rationale']='Contextual visual opening from canonical interpretation; needs audiovisual review'
    v={'variant_id':'A','title':'Contextual proposal','editorial_concept':'Let the material explain its action',
       'intended_message':'Show the action without adding business claims','narrative_strategy':'Preserve context',
       'hook':hook,'shots':[s],'estimated_output_duration_sec':12,'operations':[],
       'audio_strategy':{'intent':'Preserve source audio','sync_basis':'none','evidence_refs':[]},
       'ending':{'intent':'Natural source ending','cta':None},'required_reviews':['Listen and inspect boundaries']}
    return {'contract_version':'0.3.0','plan_status':'DRAFT_UNVALIDATED','source':copy.deepcopy(p['source']),
            'evidence_packet_sha256':validator.packet_digest(p),'editorial_concept':v['editorial_concept'],
            'intended_message':v['intended_message'],'proposed_variant_count':1,'variants':[v],
            'missing_evidence':copy.deepcopy(p['missing_evidence']),'required_reviews':['Audiovisual meaning and timing review'],
            'factual_claims':[],'renderer_capabilities':{'verification_status':'unknown','supported_operations':[]},
            'render_readiness':'BLOCKED_FOR_RENDER','publish_ready':False,'render_approved':False,'publish_approved':False}


def set_shots(v,shots):
    v['shots']=shots
    v['hook']={**{k:shots[0][k] for k in ('shot_id','source_start_sec','source_end_sec','timing_precision','evidence_refs')},'rationale':'Source-bound candidate hook'}
    v['estimated_output_duration_sec']=round(sum((s['source_end_sec']-s['source_start_sec'])/s['timing']['speed']+s['timing']['freeze_sec']-s['timing']['overlap_sec'] for s in shots),2)


def operation(kind='overlay',caption=None):
    return {'operation_id':'o1','kind':kind,'shot_id':'s1','output_start_sec':0,'output_end_sec':3,
            'evidence_refs':['canonical.segments.0'],'rationale':'Optional restrained caption subject to review',
            'capability_status':'requires_implementation','parameters':{'position':'bottom','caption':caption or {
            'text':'Lihat detailnya','kind':'creative_copy','verification_status':'unverified','evidence_refs':['canonical.segments.0'],'publish_ready':False}}}
