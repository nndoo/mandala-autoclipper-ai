"""Source-bound Stage 5.7 intake. Findings are data, never execution permission."""
import copy
from functools import lru_cache
from pathlib import Path
import re

import review_video_quality_v01 as reviewer

qa=reviewer.qa
core=qa.core
ROOT=core.base.ROOT/'data/revisions/stage57'
RENDER_ROOT=core.base.ROOT/'data/render-tests/stage57'
QA_ROOT=core.base.ROOT/'data/qa/stage57'
SCHEMA='revision-workflow.v0.1.schema.json'
VERSION='0.1.0'


@lru_cache(maxsize=2)
def _contracts(schema_sha256):
    # Cache only repository contracts after structural schema validation. A
    # changed byte fingerprint invalidates the cache, never an evidence object.
    return core.base.load_schema(SCHEMA)


def contracts():
    path=core.safe_path(core.base.ROOT/'src/schemas'/SCHEMA)
    return _contracts(core.intake.gate.sha256_file(path))


def check(kind,data):
    schema=contracts()
    core.base.validate_object(data,{'$defs':schema['$defs'],'$ref':'#/$defs/'+kind},'Revision '+kind)
    core.director.safe_text(__import__('json').dumps(data,allow_nan=False),2097152)
    return data


def identifier(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,99}',value):raise core.Error('Unsafe revision identity')
    return value


def refs_match(references):
    for reference in references.values():qa.same_reference(reference)


def code_receipts():
    return reviewer.code_receipts()+[qa.ref(core.base.ROOT/p) for p in (
        'scripts/revision_intelligence_v01.py','scripts/renderer_revision_v02.py',
        'scripts/run_revision_loop_v01.py','scripts/revision_quality_v01.py',
        'src/schemas/revision-workflow.v0.1.schema.json','openclaw/prompts/adaptive-director-revision-v01.md')]


def load_parent(report_path):
    """Replay the real Stage 5.6 receipt, including human and model provenance."""
    path=core.safe_path(report_path);report=qa.validate_report(qa.read(path))
    if report['integrity'].get('status')!='PASS':raise core.Error('Parent QA integrity blocked')
    generation=qa.read(path.parent/'review-generation-provenance.v01.json')
    if generation.get('mode')!='live_multimodal' or generation.get('code_receipts')!=reviewer.code_receipts():
        raise core.Error('Parent Reviewer generation provenance unavailable or stale')
    qa.same_reference(generation['prepared_receipt'])
    prepared=core.safe_path(generation['prepared_receipt']['path']).parent
    base,packet,ctx,requests=reviewer.load_prepared(prepared)
    responses={}
    for role in reviewer.ROLES:
        reference=generation['responses'].get(role)
        if not reference:raise core.Error('Parent media review missing')
        qa.same_reference(reference)
        responses[role]=reviewer.validate_response(qa.read(reference['path']),requests[role],packet)
    if generation['packet_sha256']!=reviewer.digest(packet):raise core.Error('Parent QA packet mismatch')
    replay=reviewer.merge(base,responses,mode='live_multimodal',response_refs=generation['responses'])
    if replay!=report:raise core.Error('Parent QA differs from generation replay')
    refs_match(report['inputs'])
    return report,ctx,{'generation':qa.ref(path.parent/'review-generation-provenance.v01.json'),
        'prepared':generation['prepared_receipt'],**{'response:'+role:r for role,r in generation['responses'].items()}}


def classified(issue):
    origin=issue['origin']
    if origin=='human_feedback':
        # Earlier editorial notes were recorded in a human handoff envelope;
        # that envelope does not make them a fresh independently confirmed review.
        if issue['category']=='audio' and issue['human_confirmation']=='confirmed_user_handoff':return 'confirmed_user'
        return 'prior_editorial_unverified'
    return origin


def priority(issue):
    category={'integrity':0,'audio':10,'factual_safety':20,'captions':30,'visual':40,
              'hook':50,'story':50,'pacing':50,'ending':50}.get(issue['category'],60)
    severity={'critical':0,'high':1,'medium':2,'low':3,'info':4}[issue['severity']]
    provenance={'confirmed_user':0,'deterministic_validation':1,'timeline_check':2,
                'signal_measurement':3,'model_unverified':4,'prior_editorial_unverified':5}[classified(issue)]
    return (0 if severity==0 else category+severity),provenance,issue['issue_id']


def make_brief(revision_id,report,ctx,qa_reference,audio_capability,extra_refs=None):
    identifier(revision_id);qa.validate_report(report)
    if report['source']!=ctx['inputs']['source'] or report['rendered_output']!=ctx['inputs']['rendered_output']:
        raise core.Error('Parent QA source/output contamination')
    if any(report['inputs'].get(name)!=ctx['inputs'].get(name) for name in ('plan','spec','timeline','manifest')):
        raise core.Error('Parent QA plan/render input mismatch')
    if report['technical']['timeline']!=ctx['timeline']:raise core.Error('Parent timeline mismatch')
    issues=[];ids=set();ledger=report['evidence_ledger']
    for issue in sorted(report['issues'],key=priority):
        if issue['issue_id'] in ids or any(ref not in ledger for ref in issue['evidence_refs']):
            raise core.Error('Duplicate or ungrounded revision issue')
        ids.add(issue['issue_id']);recommendation=issue['recommendation'];target=recommendation['target']
        action={'plan_change':'replan','renderer_adjustment':'renderer_investigation',
                'missing_evidence':'additional_evidence','rights_factual_review':'human_review',
                'source_limitation':'human_review'}.get(target,'human_review')
        required=recommendation.get('required_operation')
        if required=='continuous_soundtrack_bed':required='continuous_source_audio'
        issues.append({'issue_id':issue['issue_id'],'category':issue['category'],'severity':issue['severity'],
            'original_origin':issue['origin'],'provenance':classified(issue),'confidence':issue['confidence'],
            'human_confirmation':issue['human_confirmation'],'output_range':copy.deepcopy(issue['output_range']),
            'source_ranges':copy.deepcopy(issue['source_ranges']),'evidence_refs':list(issue['evidence_refs']),
            'description':issue['description'],'recommendation':copy.deepcopy(recommendation),'action':action,
            'priority':priority(issue)[0],'capability_requirements':[required] if required else []})
    conflicts=[]
    model=report['ai'].get('output_review') or {}
    for dimension,assessment in model.get('dimensions',{}).items():
        category={'technical_integrity':'integrity','audio_continuity':'audio','visual_continuity':'visual'}.get(dimension,dimension)
        dissent=[i['issue_id'] for i in issues if i['category']==category and i['provenance'] in ('confirmed_user','prior_editorial_unverified')]
        if dissent and assessment['status']=='PASS':
            conflicts.append({'dimension':dimension,'historical_issue_ids':dissent,'model_status':'PASS',
                              'resolution':'UNRESOLVED_PRESERVE_BOTH'})
    inputs={**report['inputs'],**(extra_refs or {}),'parent_qa':qa_reference,'audio_capability':audio_capability}
    refs_match(inputs)
    reviews=['Human audiovisual review of any V2; V1 confirmation does not transfer to V2',
        'Listen to source passage and beginning/ending; continuous mapping is not verified musical phrasing',
        'Investigate possible source-baked ghosting before proposing a renderer repair',
        'Preserve disagreements and inspect hook, repetition, progression and ending',
        'Publication/music rights remain unknown; private preview only']
    brief={'contract_version':VERSION,'revision_id':revision_id,'source':copy.deepcopy(ctx['plan']['source']),
        'parent_render':ctx['inputs']['rendered_output'],'parent_plan':ctx['inputs']['plan'],'qa_report':qa_reference,
        'inputs':inputs,'issues':issues,'conflicts':conflicts,'renderer_capabilities':report['inputs']['capabilities'],
        'audio_capability':audio_capability,'required_reviews':reviews,
        'constraints':{'maximum_attempts':2,'production_eligible':False,'publishing_eligible':False,
            'allow_external_assets':False,'human_audio_review_required':True,'no_verified_beat_claims':True},
        'expected_improvement_targets':list(dict.fromkeys(i['category'] for i in issues)),
        'limitations':list(report['limitations'])[:32]+['Revision recommendations are proposals, not audiovisual facts'],
        'render_approved':False,'publish_approved':False}
    return check('brief',brief)


def validate_brief(brief):
    check('brief',brief);refs_match(brief['inputs'])
    for name in ('parent_render','parent_plan','qa_report','renderer_capabilities','audio_capability'):qa.same_reference(brief[name])
    qa.same_reference({'path':brief['source']['path'],'sha256':brief['source']['sha256']})
    report=qa.validate_report(qa.read(brief['qa_report']['path']))
    if report['source']!={k:brief['source'][k] for k in ('path','sha256')} or report['rendered_output']!=brief['parent_render']:
        raise core.Error('Revision brief media mismatch')
    original={i['issue_id']:i for i in report['issues']}
    if len(brief['issues'])!=len(original) or len({i['issue_id'] for i in brief['issues']})!=len(original):raise core.Error('Revision issues missing or repeated')
    for item in brief['issues']:
        issue=original.get(item['issue_id'])
        if not issue or item['provenance']!=classified(issue) or item['original_origin']!=issue['origin'] or item['human_confirmation']!=issue['human_confirmation']:
            raise core.Error('Revision provenance promotion')
        for key in ('category','severity','confidence','output_range','source_ranges','evidence_refs','description','recommendation'):
            if item[key]!=issue[key]:raise core.Error('Revision finding changed')
    return brief
