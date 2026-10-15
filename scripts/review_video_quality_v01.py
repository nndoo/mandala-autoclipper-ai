#!/usr/bin/env python3
"""Stage 5.6 independent media Reviewer. Prepare offline; live requires approval."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
import video_quality_qa_v01 as qa

c=qa.core
PROMPT=c.base.ROOT/'openclaw/prompts/video-quality-reviewer-v01.md'
RECEIPT='qa-generation-provenance.v01.json'
PREPARED='review-requests-provenance.v01.json'
ROLES=('edited_output','original_source')
MAX_MEDIA=20*1024*1024
PROVIDER='custom-ipt02mbjindt5ldise8woehy-43-129-33-7-sslip-io'
MODEL='openclaw'


class InferenceFailure(c.Error):
    """Bounded diagnostics contain classifications, never raw stderr/secrets."""
    def __init__(self,diagnostic,stdout=''):
        super().__init__('Reviewer invocation failed: '+diagnostic['reason'])
        self.diagnostic=diagnostic;self.stdout=stdout


def stderr_reason(text):
    http=re.search(r'HTTP\s+(\d{3})\b',text)
    if http:return {'reason':'upstream_http_error','http_status':int(http[1])}
    for pattern,reason in ((r'heap out of memory|allocation failed','node_heap_exhausted'),
        (r'ENOTFOUND|ECONNREFUSED|ETIMEDOUT|fetch failed','network_failure'),
        (r'QA (?:request|media|prompt|symlink|credential)|Unsafe QA','plugin_request_binding_failure'),
        (r'No description returned|No video|no-model','video_provider_selection_failure'),
        (r'Unknown agent|not configured|agent.*not found','agent_configuration_failure'),
        (r'Unsupported.*mode','plugin_mode_failure')):
        if re.search(pattern,text,re.I):return {'reason':reason}
    return {'reason':'cli_exit_nonzero_unclassified'}


def capture_inference(command,*,env,timeout=180,max_bytes=131072,max_stderr=16384):
    """Reviewer-only diagnostic capture; leave working Director runner untouched."""
    started=time.monotonic();buffers={'stdout':bytearray(),'stderr':bytearray()}
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env=env,cwd=c.base.ROOT)
    reason=None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ,'stdout');selector.register(process.stderr,selectors.EVENT_READ,'stderr')
            while selector.get_map():
                remaining=timeout-(time.monotonic()-started)
                if remaining<=0:reason='invocation_timeout';break
                ready=selector.select(remaining)
                if not ready:reason='invocation_timeout';break
                for key,_ in ready:
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:selector.unregister(key.fileobj);continue
                    target=buffers[key.data];limit=max_bytes if key.data=='stdout' else max_stderr
                    if len(target)+len(chunk)>limit:reason=key.data+'_limit_exceeded';break
                    target.extend(chunk)
                if reason:break
            if reason is None:
                try:process.wait(timeout=max(.001,timeout-(time.monotonic()-started)))
                except subprocess.TimeoutExpired:reason='invocation_timeout'
    finally:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait();process.stdout.close();process.stderr.close()
    diagnostic={'phase':'invocation','process_exit_code':process.returncode,'stdout_bytes':len(buffers['stdout']),
        'stderr_bytes':len(buffers['stderr']),'elapsed_sec':round(time.monotonic()-started,3),
        **({'reason':reason} if reason else stderr_reason(buffers['stderr'].decode('utf8','replace')))}
    try:raw=c.director.safe_text(buffers['stdout'].decode('utf8'),max_bytes)
    except (c.Error,UnicodeError):raw='';diagnostic['reason']='stdout_encoding_or_credential_policy'
    if reason or process.returncode or not raw:raise InferenceFailure(diagnostic,raw)
    return raw


def digest(data):return c.digest_object(data)
def name(role):return role.replace('_','-')+'.request.v01.json'


def code_receipts():
    names=('scripts/review_video_quality_v01.py','src/schemas/video-quality-ai-request.v0.1.schema.json',
        'src/schemas/video-quality-ai-response.v0.1.schema.json','openclaw/prompts/video-quality-reviewer-v01.md',
        'openclaw/agents/mandala-video-reviewer/AGENTS.md','openclaw/plugins/mandala-9router-video/src/qa-prompt.ts',
        'openclaw/plugins/mandala-9router-video/src/transport.ts','openclaw/plugins/mandala-9router-video/dist/qa-prompt.js',
        'openclaw/plugins/mandala-9router-video/dist/transport.js')
    return qa.code_receipts()+[qa.ref(c.base.ROOT/p) for p in names]


def load_qa(bundle):
    root=c.shared.directory(bundle);receipt=qa.read(root/RECEIPT)
    if receipt.get('mode')!='offline_technical_qa' or receipt.get('code_receipts')!=qa.code_receipts() or receipt.get('live_inference_performed') is not False:
        raise c.Error('Stale or invalid technical QA provenance')
    if set(receipt.get('artifacts',{}))!={qa.REPORT,qa.TECH,qa.PACKET}:raise c.Error('Incomplete technical QA bundle')
    for filename,r in receipt['artifacts'].items():
        if r!=qa.ref(root/filename):raise c.Error('QA bundle changed')
    report=qa.validate_report(qa.read(root/qa.REPORT));packet=qa.read(root/qa.PACKET)
    if report['integrity'].get('status')!='PASS' or receipt['inputs']!=report['inputs'] or receipt['source']!=report['source'] or receipt['rendered_output']!=report['rendered_output']:
        raise c.Error('QA media/receipt mismatch')
    for r in report['inputs'].values():qa.same_reference(r)
    ctx=qa.verify_bundle(c.safe_path(report['inputs']['manifest']['path']).parent)
    if packet!=qa.packet_for(report,ctx) or qa.read(root/qa.TECH)!=report['technical']:
        raise c.Error('QA packet/technical mismatch')
    return report,packet,ctx


def make_request(packet,role):
    if role not in ROLES:raise c.Error('Reviewer media role invalid')
    reference=packet['rendered_output'] if role=='edited_output' else packet['source']
    info=packet['output_info'] if role=='edited_output' else packet['source_info']
    path=c.safe_path(reference['path']);qa.same_reference(reference)
    if not 1024<=path.stat().st_size<=MAX_MEDIA:raise c.Error('Reviewer MP4 exceeds existing transport limit')
    media={'role':role,**reference,'bytes':path.stat().st_size,'duration_sec':info['duration_sec'],
           'video_offered':True,'audio_offered':info['audio_present']}
    schema=c.base.load_schema('video-quality-ai-response.v0.1.schema.json')
    # Mirror existing semantic validation in the model-facing contract. The
    # shared report schema also admits technical/human origins, which a model
    # must never borrow. Evidence IDs are exact ledger keys, not JSON paths.
    allowed=[key for key in packet['evidence_ledger'] if role=='edited_output' or (key!='media.output' and not key.startswith('audio.splice.'))]
    for key,dimension in schema['properties']['dimensions']['properties'].items():
        dimension['properties']['provenance']['enum']=['model_unverified','unavailable']
        dimension['properties']['evidence_refs']['items']['enum']=allowed
        if key=='factual_safety':dimension['properties']['status']['enum'].remove('PASS')
    finding=schema['properties']['issues']['items']['properties']
    finding['evidence_refs']['items']['enum']=allowed
    finding['recommendation']['properties']['feasibility']['enum'].remove('verified_current_capability')
    prompt=(PROMPT.read_text()+'\nMEDIA_ROLE='+role+'\nMEDIA='+json.dumps(media,separators=(',',':'))+
        '\nPACKET_SHA256='+digest(packet)+'\nQA_PACKET='+json.dumps(packet,separators=(',',':'),ensure_ascii=False)+
        '\nALLOWED_EVIDENCE_IDS='+json.dumps(allowed)+
        '\nOUTPUT_SCHEMA='+json.dumps(schema,separators=(',',':')))
    c.director.safe_text(prompt,65536)
    request={'contract_version':qa.VERSION,'kind':'stage56_multimodal_qa_request','packet_sha256':digest(packet),
        'media':media,'prompt':prompt,'prompt_sha256':c.director.digest_text(prompt),'code_receipts':code_receipts(),
        'live_inference_performed':False,'production_eligible':False,'publishing_eligible':False}
    c.base.validate_object(request,c.base.load_schema('video-quality-ai-request.v0.1.schema.json'),'Reviewer request')
    c.director.safe_text(json.dumps(request),131072)
    return request


def prepare(bundle,output):
    output=c.new_directory(output,qa.QA_ROOT)
    report,packet,ctx=load_qa(bundle)
    requests={name(role):make_request(packet,role) for role in ROLES}
    receipt={'contract_version':qa.VERSION,'mode':'prepared_no_inference','qa_bundle':c.shared.relative(c.shared.directory(bundle)),
        'qa_generation':qa.ref(c.shared.directory(bundle)/RECEIPT),'packet_sha256':digest(packet),'code_receipts':code_receipts(),
        'provider':PROVIDER,'model_alias':MODEL,'runtime_version':'2026.9.9','configured_agent':'mandala-video-analyst',
        'logical_role':'mandala-video-reviewer; isolated prompt, existing auth routing only',
        'maximum_calls':2,'automatic_retries':0,'audio_delivery':'Full MP4 audio offered; model decoding/listening not independently certified',
        'live_inference_performed':False,'production_eligible':False,'publishing_eligible':False}
    c.director.publish(output,{**requests,PREPARED:receipt})
    return receipt


def load_prepared(bundle):
    root=c.shared.directory(bundle);receipt=qa.read(root/PREPARED)
    if (receipt.get('mode')!='prepared_no_inference' or receipt.get('code_receipts')!=code_receipts()
        or receipt.get('maximum_calls')!=2 or receipt.get('automatic_retries')!=0
        or receipt.get('provider')!=PROVIDER or receipt.get('model_alias')!=MODEL):raise c.Error('Reviewer prepared receipt mismatch')
    qa.same_reference(receipt['qa_generation'])
    report,packet,ctx=load_qa(receipt['qa_bundle'])
    requests={role:qa.read(root/name(role)) for role in ROLES}
    if receipt['packet_sha256']!=digest(packet) or any(requests[r]!=make_request(packet,r) for r in ROLES):raise c.Error('Reviewer request changed')
    return report,packet,ctx,requests


def validate_response(data,request,packet):
    c.base.validate_object(data,c.base.load_schema('video-quality-ai-response.v0.1.schema.json'),'Untrusted Reviewer response')
    c.director.safe_text(json.dumps(data,allow_nan=False))
    media=request['media'];obs=data['media_observation'];ledger=packet['evidence_ledger']
    if (data['packet_sha256']!=request['packet_sha256'] or data['media_sha256']!=media['sha256'] or data['media_role']!=media['role']):raise c.Error('Reviewer response media/packet contamination')
    if obs['audio_examined'] and (not media['audio_offered'] or obs['audio_access']!='model_self_reported_available'):
        raise c.Error('Reviewer unsupported listening claim')
    if not obs['audio_examined'] and data['dimensions']['audio_continuity']['status'] not in ('UNAVAILABLE','NOT_APPLICABLE'):
        raise c.Error('Reviewer audio judgment without listening')
    if obs['audio_access']=='model_self_reported_available' and not obs['audio_examined']:raise c.Error('Contradictory audio observation')
    for key,d in data['dimensions'].items():
        if d['provenance'] not in ('model_unverified','unavailable'):raise c.Error('Reviewer promoted model judgment')
        if any(r not in ledger for r in d['evidence_refs']):raise c.Error('Reviewer ungrounded dimension')
        if media['role']=='original_source' and 'media.output' in d['evidence_refs']:raise c.Error('Source-only dimension references unseen output')
        if not obs['video_examined'] and key not in ('audio_continuity',) and d['status'] not in ('UNAVAILABLE','NOT_APPLICABLE'):
            raise c.Error('Reviewer visual judgment without video')
        if key=='factual_safety' and d['status']=='PASS':raise c.Error('Reviewer cannot verify factual/rights safety')
    ids=set();media_ref='media.output' if media['role']=='edited_output' else 'media.source'
    for f in data['issues']:
        if f['issue_id'] in ids:raise c.Error('Duplicate model issue ID')
        ids.add(f['issue_id']);w=f['media_range']
        if not 0<=w['start_sec']<w['end_sec']<=media['duration_sec']:raise c.Error('Reviewer invalid media timestamp')
        if not f['evidence_refs'] or any(r not in ledger for r in f['evidence_refs']):raise c.Error('Reviewer ungrounded finding')
        if f['basis']=='model_media_observation':
            if media_ref not in f['evidence_refs']:raise c.Error('Reviewer missing actual attached media reference')
            if f['category']=='audio' and not obs['audio_examined']:raise c.Error('Reviewer unheard audio observation')
            if f['category']!='audio' and not obs['video_examined']:raise c.Error('Reviewer unseen visual observation')
        for reference in f['evidence_refs']:
            if reference.startswith('audio.splice.'):
                boundary=ledger[reference].get('measurements',{}).get('output_time_sec')
                if media['role']!='edited_output' or boundary is None or not w['start_sec']-.3<=boundary<=w['end_sec']+.3:
                    raise c.Error('Reviewer splice timestamp mismatch')
        if media['role']=='original_source' and 'media.output' in f['evidence_refs']:raise c.Error('Source-only Reviewer cannot observe output')
        if f['recommendation']['feasibility']=='verified_current_capability':raise c.Error('Model cannot certify renderer capability')
    return data


def mock_response(request):
    return {'contract_version':qa.VERSION,'packet_sha256':request['packet_sha256'],'media_sha256':request['media']['sha256'],
        'media_role':request['media']['role'],'media_observation':{'video_examined':False,'audio_examined':False,
            'audio_access':'not_available','comparison_access':'single_attached_video'},
        'dimensions':{k:qa.dimension('UNAVAILABLE','unavailable','Offline fixture: no model observed media') for k in qa.DIMENSIONS},
        'issues':[],'limitations':['OFFLINE MOCK; no live editorial/audio observation'],
        'production_eligible':False,'publishing_eligible':False}


def invoke(request,path,*,approved=False):
    if not approved:raise c.Error('Separate explicit approval required for paid Reviewer calls')
    runtime=c.director.RUNTIME;executable=runtime/'bin/openclaw';nodebin=runtime/'tools/node-v24.21.0/bin'
    if not executable.is_file() or not (nodebin/'node').is_file():raise c.Error('Isolated OpenClaw runtime unavailable')
    if qa.ref(request['media']['path'])!={k:request['media'][k] for k in ('path','sha256')}:raise c.Error('Media changed before inference')
    if qa.read(path)!=request:raise c.Error('Request changed before inference')
    env=os.environ.copy();env.update(PATH=str(nodebin)+':'+str(runtime/'bin')+':'+env.get('PATH',''),
        NODE_OPTIONS='--max-old-space-size=256',MANDALA_VIDEO_ANALYSIS_MODE='quality_qa_v01',
        MANDALA_VIDEO_QA_PROJECT_ROOT=str(c.base.ROOT),
        MANDALA_VIDEO_QA_REQUEST_FILE=str(c.safe_path(path)),MANDALA_VIDEO_QA_REQUEST_SHA256=qa.ref(path)['sha256'])
    return capture_inference([str(executable),'infer','video','describe','--agent','mandala-video-analyst',
        '--model',PROVIDER+'/'+MODEL,'--file',str(c.safe_path(request['media']['path'])),'--json'],timeout=180,max_bytes=131072,env=env)


def merge(report,responses,*,mode,response_refs=None):
    report=copy.deepcopy(report);live=mode=='live_multimodal'
    output=responses.get('edited_output');source=responses.get('original_source')
    report['ai']={'mode':mode,'response_refs':response_refs or {},'output_review':output,'source_review':source,
        'comparison_method':'Separate single-video observations correlated by verified timeline; not joint observation',
        'video_observation':'MODEL_SELF_REPORTED_UNVERIFIED' if live and output and output['media_observation']['video_examined'] else 'UNAVAILABLE',
        'audio_listening':'MODEL_SELF_REPORTED_UNVERIFIED' if live and output and output['media_observation']['audio_examined'] else 'UNAVAILABLE',
        'live_inference_performed':live and bool(responses),'source_review_is_output_verdict':False}
    complete=live and output is not None and source is not None and output['media_observation']['video_examined'] and source['media_observation']['video_examined']
    report['ai_editorial_status']='REVISE' if complete and (any(f['severity']=='high' for f in output['issues']) or any(d['status']=='REVISE' for d in output['dimensions'].values())) else 'NEEDS_REVIEW' if complete else 'INCOMPLETE'
    if complete:
        report['evidence_ledger']['ai.output']=(response_refs or {}).get('edited_output',{'method':'validated_model_output'})
        for f in output['issues']:
            fix=copy.deepcopy(f['recommendation']);fix['feasibility']='requires_editorial_review' if fix['feasibility']=='not_applicable' else fix['feasibility']
            x=qa.issue(f['category'],f['event_type'],f['description'],f['media_range'],origin='model_unverified',
                severity=f['severity'],evidence=f['evidence_refs']+['ai.output'],confidence=f['confidence'],cause=f['possible_cause'],fix=fix)
            x['detection_method']=f['basis'];x['source_ranges']=qa.source_ranges(x['output_range'],report['technical']['timeline'])
            x['issue_id']='model-'+f['issue_id'];report['issues'].append(x)
        for key,d in output['dimensions'].items():
            if key not in ('technical_integrity','factual_safety') and report['dimensions'][key]['status']=='UNAVAILABLE':
                report['dimensions'][key]=copy.deepcopy(d)
    # Never drop human/critical findings to fit the bounded issue contract.
    report['issues']=report['issues'][:256]
    qa.assess(report);qa.validate_report(report)
    return report


def review(bundle,output,*,mode='offline_fixture',saved=None,approved=False,roles=None):
    if mode=='live_multimodal' and not approved:raise c.Error('Paid inference approval required')
    if mode not in ('offline_fixture','saved_response_replay','live_multimodal'):raise c.Error('Reviewer mode invalid')
    roles=ROLES if roles is None else tuple(roles)
    if not roles or len(set(roles))!=len(roles) or any(role not in ROLES for role in roles):raise c.Error('Reviewer invocation roles invalid')
    output=c.new_directory(output,qa.QA_ROOT)
    report,packet,ctx,requests=load_prepared(bundle)
    root=c.shared.directory(bundle);output.parent.mkdir(parents=True,exist_ok=True)
    # Reserve before billable work; a failed call is persisted, never retried automatically.
    output.mkdir();artifacts={};responses={};attempts=[]
    try:
        for role in roles:
            attempt={'role':role,'request_ref':qa.ref(root/name(role)),'media':requests[role]['media'],
                'provider':PROVIDER,'model_alias':MODEL,'paid_call_attempted':mode=='live_multimodal','automatic_retries':0}
            phase='invocation'
            try:
                if mode=='live_multimodal':
                    raw=invoke(requests[role],root/name(role),approved=approved)
                    # Bound/credential-check before preserving untrusted bytes. Never
                    # promote this diagnostic artifact to validated evidence.
                    c.director.safe_text(raw)
                    artifacts[role+'.untrusted-response.v01.txt']=raw
                    attempt['response_received']=True
                    phase='response_parse';data=c.director.parse_response(raw)
                    envelope=c.director.strict_json(raw)
                    if isinstance(envelope.get('model'),str):attempt['reported_model']=envelope['model'][:200]
                elif mode=='saved_response_replay':data=qa.read(saved[role])
                else:data=mock_response(requests[role])
                phase='response_validation'
                responses[role]=validate_response(data,requests[role],packet)
                artifacts[role+'.response.v01.json']=data;attempt['status']='VALIDATED_MODEL_UNVERIFIED' if mode=='live_multimodal' else 'OFFLINE_VALIDATED'
            except (c.Error,OSError,ValueError,TypeError,KeyError) as error:
                attempt['status']='FAILED_NO_RETRY';attempt['failure_phase']=phase
                if isinstance(error,InferenceFailure):
                    attempt['diagnostic']=error.diagnostic
                    if error.stdout:artifacts[role+'.untrusted-response.v01.txt']=error.stdout
                else:attempt['diagnostic']={'phase':phase,'reason':'structured_response_invalid' if phase!='invocation' else 'request_preflight_or_runtime_failure'}
                attempts.append(attempt);break
            attempts.append(attempt)
        response_refs={role:{'path':c.shared.relative(output/(role+'.response.v01.json')),
            'sha256':hashlib.sha256((json.dumps(data,ensure_ascii=True,indent=2,allow_nan=False)+'\n').encode()).hexdigest()} for role,data in responses.items()}
        result=merge(report,responses,mode=mode,response_refs=response_refs)
        for r in report['inputs'].values():qa.same_reference(r)
        artifacts[qa.REPORT]=result
        artifacts['review-generation-provenance.v01.json']={'contract_version':qa.VERSION,'mode':mode,'prepared_receipt':qa.ref(root/PREPARED),
            'packet_sha256':digest(packet),'code_receipts':code_receipts(),'attempts':attempts,'live_inference_performed':any(a['paid_call_attempted'] for a in attempts),
            'responses':response_refs,'production_eligible':False,'publishing_eligible':False}
        for n,data in artifacts.items():
            if isinstance(data,str):c.base.write_exclusive(output/n,data)
            else:c.shared.write_json(output/n,data)
        return result
    except BaseException:
        # Retain reservation after any live attempt to prevent silent repeat billing.
        if mode!='live_multimodal':
            for p in output.iterdir():p.unlink()
            output.rmdir()
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--qa-bundle',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('review');p.add_argument('--prepared',required=True);p.add_argument('--output',required=True)
    p.add_argument('--mode',choices=('offline_fixture','saved_response_replay','live_multimodal'),default='offline_fixture')
    p.add_argument('--saved-output');p.add_argument('--saved-source');p.add_argument('--live-approved',action='store_true')
    p.add_argument('--role',choices=ROLES,help='One independent call; does not retry a failed other role')
    args=parser.parse_args(argv)
    try:
        if args.action=='prepare':prepare(args.qa_bundle,args.output);print('PREPARED_NO_INFERENCE');return 0
        result=review(args.prepared,args.output,mode=args.mode,saved={'edited_output':args.saved_output,'original_source':args.saved_source},approved=args.live_approved,roles=(args.role,) if args.role else None)
        print(json.dumps({k:result[k] for k in ('overall_decision','ai_editorial_status','production_eligible','publishing_eligible')}));return 2 if result['overall_decision']=='BLOCKED' else 0
    except (c.Error,OSError,ValueError,TypeError,KeyError):print('BLOCKED: Reviewer request/response policy failure; diagnostics suppressed',file=sys.stderr);return 1


if __name__=='__main__':
    with c.intake.processing_deadline(600):raise SystemExit(main())
