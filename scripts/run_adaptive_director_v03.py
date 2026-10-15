#!/usr/bin/env python3
"""Stage 5.4 planning entry point. Offline by default; stops before rendering."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

import adaptive_director_evidence_v03 as intake
import validate_adaptive_director_plan_v03 as validator

base, shared, av = intake.base, intake.shared, intake.av
PACKET='evidence-packet.v03.json'
PROMPT='director-request.v03.txt'
REQUEST='request-provenance.v03.json'
PLAN='editing-plan.v03.json'
REPORT='plan-validation.v03.json'
RECEIPT='generation-provenance.v03.json'
PROMPT_FILE=base.ROOT/'openclaw/prompts/adaptive-creative-director-v03.md'
MAX_PROMPT_BYTES=65536
MAX_RESPONSE_BYTES=131072
LIVE_TIMEOUT_SEC=180
RUNTIME=Path.home()/'.local/share/mandala-openclaw-runtime'
SECRET_PATTERN = __import__('re').compile(r'(?:\b(?:sk|gsk)-[A-Za-z0-9_-]{8,}|\bAIza[\w-]{16,}|Bearer\s+[\w.-]+|"(?:api_key|apiKey|authorization)"\s*:)',__import__('re').I)


def digest_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def safe_text(text,maximum=MAX_RESPONSE_BYTES):
    if not isinstance(text,str) or len(text.encode())>maximum or SECRET_PATTERN.search(text):
        raise base.AdapterError('Untrusted output resource/credential policy violation')
    return text


def strict_json(text):
    try:
        result=json.loads(safe_text(text),parse_float=base.finite_float,parse_constant=base.reject_constant,
                          object_pairs_hook=base.unique_object)
    except (ValueError,TypeError,UnicodeError,RecursionError):
        raise base.AdapterError('Malformed untrusted JSON response') from None
    if not isinstance(result,dict): raise base.AdapterError('Model output must be an object')
    return result


def parse_response(text):
    data=strict_json(text)
    if 'contract_version' in data or ('schema_version' in data and 'variants' in data): return data
    # Known OpenClaw one-shot and legacy agent result envelopes; no arbitrary search.
    content=data.get('text',data.get('output_text'))
    payloads=data.get('outputs',data.get('payloads'))
    if content is None and isinstance(payloads,list):
        texts=[p.get('text') for p in payloads if isinstance(p,dict) and isinstance(p.get('text'),str)]
        if len(texts)==1: content=texts[0]
    if not isinstance(content,str): raise base.AdapterError('Unsupported model response envelope')
    content=safe_text(content).strip()
    if content.startswith('```json\n') and content.endswith('\n```'):
        content=content[8:-4]
    return strict_json(content)


def code_receipts():
    return [av.reference(Path(p).resolve()) for p in (__file__,intake.__file__,validator.__file__,
              base.ROOT/'src/schemas'/validator.SCHEMA,base.ROOT/'src/schemas/adaptive-plan-validation.v0.3.schema.json',PROMPT_FILE,
              base.ROOT/'openclaw/agents/mandala-video-director/AGENTS.md',
              base.ROOT/'scripts/speech_intelligence_v01.py',base.ROOT/'scripts/speech_planning_v01.py',
              base.ROOT/'src/schemas/speech-intelligence.v0.1.schema.json',
              base.ROOT/'scripts/adaptive_text_v01.py')]


def make_prompt(packet):
    schema=base.load_schema(validator.SCHEMA)
    prompt=(PROMPT_FILE.read_text()+'\nEVIDENCE_PACKET_SHA256='+validator.packet_digest(packet)+
            '\nINPUT_PACKET='+intake.bounded_json(packet)+
            '\nOUTPUT_SCHEMA='+json.dumps(schema,separators=(',',':'),ensure_ascii=False,allow_nan=False))
    return safe_text(prompt,MAX_PROMPT_BYTES)


def recheck_inputs(packet):
    for ref in packet['inputs'].values():
        path=av.checked_path(ref['path'],'Input receipt')
        if av.reference(path)!=ref: raise base.AdapterError('Input changed during planning')


def publish(directory,artifacts):
    """Exclusive files; remove only this invocation's outputs if publication fails."""
    directory=shared.directory(directory,new=True)
    directory.parent.mkdir(parents=True,exist_ok=True)
    directory.mkdir()  # Exclusive ownership, never reuse an existing output directory.
    created=[]
    try:
        for name,value in artifacts.items():
            path=directory/name
            if isinstance(value,str): base.write_exclusive(path,value)
            else: shared.write_json(path,value)
            created.append(path)
        return directory
    except BaseException:
        for path in created: path.unlink(missing_ok=True)
        directory.rmdir()
        raise


def prepare(request,output):
    shared.directory(output,new=True)
    packet=intake.build_packet(**request)
    prompt=make_prompt(packet)
    receipts=code_receipts()
    recheck_inputs(packet)
    request_receipt={'contract_version':'0.3.0','mode':'prepared_no_inference','created_at':shared.now(),
                     'agent':'mandala-video-director','provider_policy':'existing_agent_local_model_auth',
                     'evidence_packet_sha256':validator.packet_digest(packet),'prompt_sha256':digest_text(prompt),
                     'prompt_bytes':len(prompt.encode()),'code_receipts':receipts,
                     'live_inference_performed':False,'render_approved':False,'publish_approved':False}
    return publish(output,{PACKET:packet,PROMPT:prompt,REQUEST:request_receipt})


def bounded_model_output(command,*,timeout=LIVE_TIMEOUT_SEC,max_bytes=MAX_RESPONSE_BYTES,env=None):
    """Unlike media helper, terminate the entire OpenClaw/Node process group."""
    output=bytearray()
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                             start_new_session=True,stdin=subprocess.DEVNULL,env=env)
    deadline=time.monotonic()+timeout
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([process.stdout],[],[],remaining)[0]:
                raise base.AdapterError('Director inference timeout exceeded')
            chunk=os.read(process.stdout.fileno(),65536)
            if not chunk: break
            output.extend(chunk)
            if len(output)>max_bytes: raise base.AdapterError('Director response byte limit exceeded')
        try: code=process.wait(timeout=max(.001,deadline-time.monotonic()))
        except subprocess.TimeoutExpired: raise base.AdapterError('Director inference timeout exceeded') from None
        if code: raise base.AdapterError('Director inference failed; raw diagnostics suppressed')
        try: return safe_text(output.decode())
        except UnicodeError: raise base.AdapterError('Invalid Director output encoding') from None
    finally:
        # Also kill surviving descendants after their parent exits/ closes stdout.
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait()
        process.stdout.close()


def live_response(prompt,approved=False,*,image_paths=None):
    if not approved: raise base.AdapterError('Live inference requires explicit approval of this intended call')
    executable=RUNTIME/'bin/openclaw'
    nodebin=RUNTIME/'tools/node-v24.21.0/bin'
    if not executable.is_file() or not os.access(executable,os.X_OK) or not (nodebin/'node').is_file():
        raise base.AdapterError('Existing isolated OpenClaw runtime unavailable')
    env=os.environ.copy()
    env['PATH']=str(nodebin)+':'+str(RUNTIME/'bin')+':'+env.get('PATH','')
    env['NODE_OPTIONS']='--max-old-space-size=256'
    # One wrapper call, no automatic repair/retry and no tools/session writes.
    images=[]
    for value in image_paths or []:
        path=av.checked_path(value,'Director storyboard image')
        if path.suffix.lower() not in ('.png','.jpg','.jpeg') or path.stat().st_size>8*1048576:
            raise base.AdapterError('Director storyboard image exceeds allowed format/size')
        images+=['--file',str(path)]
    command=[str(executable),'infer','model','run','--agent','mandala-video-director',
        '--local','--json','--prompt',safe_text(prompt,MAX_PROMPT_BYTES),*images]
    if images:
        from review_video_quality_v01 import capture_inference
        return capture_inference(command,env=env)
    return bounded_model_output(command,env=env)


def load_prepared(bundle):
    bundle=shared.directory(bundle)
    packet=intake.validate_packet(av.read(av.checked_path(bundle/PACKET,'Prepared packet')))
    request=av.read(av.checked_path(bundle/REQUEST,'Prepared request'))
    prompt=safe_text(av.checked_path(bundle/PROMPT,'Prepared prompt').read_text(),MAX_PROMPT_BYTES)
    if (request.get('evidence_packet_sha256')!=validator.packet_digest(packet) or request.get('prompt_sha256')!=digest_text(prompt)
            or request.get('code_receipts')!=code_receipts() or prompt!=make_prompt(packet)):
        raise base.AdapterError('Prepared request changed; prepare a new version before inference')
    return packet,prompt,request


def run(prepared,output,*,response_file=None,live_approved=False,replay_kind='offline_fixture'):
    shared.directory(output,new=True)
    if bool(response_file)==bool(live_approved): raise base.AdapterError('Choose exactly one offline response or approved live call')
    packet,prompt,request=load_prepared(prepared)
    started=time.monotonic()
    if response_file:
        path=av.checked_path(response_file,'Saved response')
        if path.stat().st_size>MAX_RESPONSE_BYTES: raise base.AdapterError('Saved response byte limit exceeded')
        raw=safe_text(path.read_text())
        response_ref=av.reference(path)
        mode=replay_kind
    else:
        raw=live_response(prompt,approved=live_approved)
        response_ref=None
        mode='live_model_inference'
    plan=parse_response(raw)
    envelope=strict_json(raw)
    observed_model={k:envelope.get(k) for k in ('provider','model','transport','capability')} if mode=='live_model_inference' else None
    result=validator.validate_plan(plan,packet)
    # Persist blocked but schema-valid proposals for independent audit. Malformed
    # objects/secret-bearing output are never published as editing plans.
    recheck_inputs(packet)
    receipt={'contract_version':'0.3.0','mode':mode,'created_at':shared.now(),'agent':'mandala-video-director',
             'provider_policy':'existing_agent_local_model_auth','model_identity':'provider_reported_not_independently_verified','observed_model':observed_model,
             'evidence_packet_sha256':validator.packet_digest(packet),'prompt_sha256':digest_text(prompt),
             'response_sha256':digest_text(raw),'plan_sha256':digest_text(intake.bounded_json(plan,MAX_RESPONSE_BYTES)),
             'saved_response':response_ref,'code_receipts':request['code_receipts'],
             'elapsed_sec':round(time.monotonic()-started,3),'wrapper_invocations':0 if response_file else 1,
             'live_inference_performed':not bool(response_file),'render_approved':False,'publish_approved':False}
    result.update(source=packet['source'],evidence_packet_sha256=validator.packet_digest(packet))
    artifacts={PACKET:packet,RECEIPT:receipt,REPORT:result}
    artifacts[PLAN if result['structural_validity'] else 'rejected-output.v03.json']=plan
    bundle=publish(output,artifacts)
    return bundle,result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prep=commands.add_parser('prepare')
    for field in ('video','metadata','analysis','director-input','av-bundle','speech-bundle','output'):
        prep.add_argument('--'+field,required=True)
    prep.add_argument('--speech-intelligence')
    execute=commands.add_parser('run')
    execute.add_argument('--prepared',required=True);execute.add_argument('--output',required=True)
    group=execute.add_mutually_exclusive_group(required=True)
    group.add_argument('--response-file');group.add_argument('--live-approved',action='store_true')
    execute.add_argument('--replay-kind',choices=('offline_fixture','saved_response_replay'),default='offline_fixture')
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            request={k:getattr(args,k) for k in ('video','metadata','analysis','director_input','av_bundle','speech_bundle','speech_intelligence')}
            bundle=prepare(request,args.output)
            print(json.dumps({'status':'PREPARED_NO_INFERENCE','bundle':shared.relative(bundle),'live_inference_performed':False}))
            return 0
        bundle,result=run(args.prepared,args.output,response_file=args.response_file,live_approved=args.live_approved,replay_kind=args.replay_kind)
        print(json.dumps({'status':result['status'],'render_readiness':result['render_readiness'],'bundle':shared.relative(bundle)}))
        return validator.exit_code(result)
    except (base.AdapterError,OSError,ValueError,TypeError,KeyError,RecursionError):
        print('BLOCKED: planning, provenance, resource or publication failure; raw data suppressed',file=sys.stderr)
        return 1

if __name__=='__main__':
    with intake.processing_deadline():
        raise SystemExit(main())
