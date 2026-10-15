#!/usr/bin/env python3
"""Source-bound Director diagnostics; existing transport, no retry or render."""
import argparse
import fcntl
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
import uuid

import run_adaptive_director_v03 as d

ROOT = d.base.ROOT/'data/benchmarks/stage58/pak-fuad-director-remediation.v01'
PROVIDER = 'custom-ipt02mbjindt5ldise8woehy-43-129-33-7-sslip-io'
CATEGORIES = ('REQUEST_PREPARATION_FAILURE', 'PROVIDER_CONFIGURATION_FAILURE',
    'INVOCATION_FAILURE', 'TRANSPORT_FAILURE', 'UPSTREAM_MODEL_FAILURE', 'TIMEOUT',
    'EMPTY_RESPONSE', 'RESPONSE_EXTRACTION_FAILURE', 'RESPONSE_SCHEMA_FAILURE',
    'EVIDENCE_GROUNDING_FAILURE', 'SPEECH_ELIGIBILITY_BLOCKED',
    'PLANNING_VALIDATION_BLOCKED', 'UNKNOWN_FAILURE')
FLAGS = {'render_approved': False, 'publish_approved': False,
         'production_eligible': False, 'publishing_eligible': False}


class Failure(d.base.AdapterError):
    def __init__(self, diagnostic):
        super().__init__(diagnostic['error_category'])
        self.diagnostic = diagnostic


def sanitize(text):
    # Diagnostic excerpts are untrusted; omit credential-bearing lines entirely.
    lines = []
    for line in text.splitlines():
        if re.search(r'authorization|api.?key|password|secret|token\s*[:=]|INPUT_PACKET|--prompt', line, re.I):
            lines.append('[PRIVATE_LINE_OMITTED]'); continue
        line = re.sub(r'https?://\S+', '[URL_REDACTED]', line)
        line = re.sub(r'(?i)\b(?:sk|gsk)-[\w-]+|Bearer\s+\S+|AIza[\w-]+', '[REDACTED]', line)
        lines.append(line)
    return '\n'.join(lines)[:4096]


def classify(stderr, reason, code, raw):
    if reason == 'timeout': return 'TIMEOUT'
    if reason: return 'INVOCATION_FAILURE'
    if code:
        if re.search(r'Unknown (?:agent|model)|not configured|API key|auth profile|credential', stderr, re.I):
            return 'PROVIDER_CONFIGURATION_FAILURE'
        if re.search(r'ENOTFOUND|ECONNREFUSED|ETIMEDOUT|fetch failed|socket|connection', stderr, re.I):
            return 'TRANSPORT_FAILURE'
        if re.search(r'HTTP\s+[45]\d\d|No text output|rate.limit|quota|upstream', stderr, re.I):
            return 'UPSTREAM_MODEL_FAILURE'
        return 'INVOCATION_FAILURE'
    return 'EMPTY_RESPONSE' if not raw.strip() else None


def capture(command, *, env=None, timeout=180, max_bytes=131072, max_stderr=16384):
    started = time.monotonic(); start = d.shared.now()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}; reason = None; process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, env=env, cwd=d.base.ROOT)
        with selectors.DefaultSelector() as selector:
            for name in buffers: selector.register(getattr(process, name), selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = timeout-(time.monotonic()-started)
                if remaining <= 0: reason = 'timeout'; break
                ready = selector.select(remaining)
                if not ready: reason = 'timeout'; break
                for key, _ in ready:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk: selector.unregister(key.fileobj); continue
                    target = buffers[key.data]; cap = max_bytes if key.data == 'stdout' else max_stderr
                    overflow = len(target)+len(chunk) > cap
                    target.extend(chunk[:max(0, cap-len(target))])
                    if overflow:
                        reason = key.data+'_limit'; break
                if reason: break
            if reason is None:
                try: process.wait(timeout=max(.001, timeout-(time.monotonic()-started)))
                except subprocess.TimeoutExpired: reason = 'timeout'
    except OSError:
        reason = 'spawn_failure'
    finally:
        if process is not None:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(); process.stdout.close(); process.stderr.close()
    code = process.returncode if process else None
    stdout = bytes(buffers['stdout']); stderr = bytes(buffers['stderr'])
    raw = stdout.decode('utf8', 'replace'); err = stderr.decode('utf8', 'replace')
    category = classify(err, reason, code, raw)
    try: raw = d.safe_text(stdout.decode('utf8'), max_bytes)
    except (d.base.AdapterError, UnicodeError):
        raw = ''; category = 'INVOCATION_FAILURE'; reason = 'encoding_or_credential_policy'
    return raw, {'process_started': process is not None, 'process_pid': process.pid if process else None,
        'process_exit_code': code, 'process_signal': -code if code is not None and code < 0 else None,
        'started_at': start, 'ended_at': d.shared.now(), 'duration_sec': round(time.monotonic()-started, 6),
        'stdout_bytes': len(stdout), 'stderr_bytes': len(stderr),
        'stdout_sha256': hashlib.sha256(stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(stderr).hexdigest(),
        'stderr_excerpt': sanitize(err), 'stdout_excerpt': sanitize(raw[:4096]),
        'resource_reason': reason, 'error_category': category,
        'captured_hash_scope': 'bounded_prefix' if reason in ('stdout_limit', 'stderr_limit') else 'captured_stream',
        'response_presence': bool(stdout), 'raw_response_preservable': bool(raw),
        'upstream_request_verification_status': 'UNKNOWN', 'actual_upstream_http_count': 'UNKNOWN',
        'actual_billable_cost': 'UNKNOWN'}


def command(prompt):
    executable = d.RUNTIME/'bin/openclaw'; nodebin = d.RUNTIME/'tools/node-v24.21.0/bin'
    if not os.access(executable, os.X_OK) or not os.access(nodebin/'node', os.X_OK):
        raise d.base.AdapterError('Existing isolated runtime unavailable')
    env = os.environ.copy(); env['PATH'] = str(nodebin)+':'+str(d.RUNTIME/'bin')+':'+env.get('PATH', '')
    env['NODE_OPTIONS'] = '--max-old-space-size=256'
    return [str(executable), 'infer', 'model', 'run', '--agent', 'mandala-video-director',
            '--local', '--json', '--prompt', d.safe_text(prompt, d.MAX_PROMPT_BYTES)], env


def run(prepared, output, *, live_approved=False):
    if not live_approved: raise d.base.AdapterError('Explicit live scope required')
    output = d.shared.directory(output, new=True)
    diagnostic = {'contract_version': '0.1.0', 'invocation_id': str(uuid.uuid4()),
        'source_sha256': None, 'prepared_packet_sha256': None, 'provider_alias': PROVIDER,
        'model_alias': 'openclaw', 'failure_phase': 'request_preparation',
        'parsing_status': 'NOT_RUN', 'validation_status': 'NOT_RUN',
        'generation_receipt_status': 'NOT_CREATED', 'upstream_request_verification_status': 'UNKNOWN',
        'actual_upstream_http_count': 'UNKNOWN', 'actual_billable_cost': 'UNKNOWN',
        'automatic_retries': 0, 'command_structure': None, 'process_started': False,
        'process_exit_code': None, 'process_signal': None, 'started_at': d.shared.now(),
        'ended_at': None, 'duration_sec': 0, 'response_presence': False, **FLAGS}
    artifacts = {}; category = None; result = None
    try:
        packet, prompt, request = d.load_prepared(prepared)
        diagnostic.update(source_sha256=packet['source']['sha256'],
            prepared_packet_sha256=d.validator.packet_digest(packet), prompt_sha256=d.digest_text(prompt),
            prompt_bytes=len(prompt.encode()), prepared_request=d.av.reference(d.shared.directory(prepared)/d.REQUEST))
        cmd, env = command(prompt)
        diagnostic['command_structure'] = cmd[:-1]+['[PROMPT_SHA256='+d.digest_text(prompt)+']']
        diagnostic['failure_phase'] = 'invocation'
        raw, observed = capture(cmd, env=env)
        diagnostic.update(observed); category = observed['error_category']
        if raw: artifacts['raw-response.v01.txt'] = raw
        if category: raise Failure(diagnostic)
        diagnostic['failure_phase'] = 'response_extraction'
        envelope = d.strict_json(raw); plan = d.parse_response(raw)
        diagnostic['parsing_status'] = 'PASS'
        diagnostic['observed_model'] = {key: envelope.get(key) for key in ('provider', 'model', 'transport', 'capability')}
        if (envelope.get('provider') != PROVIDER or envelope.get('model') != 'openclaw'
                or envelope.get('transport') != 'local' or envelope.get('capability') != 'model.run'):
            category = 'PROVIDER_CONFIGURATION_FAILURE'
            raise Failure(diagnostic)
        diagnostic['failure_phase'] = 'schema_and_evidence_validation'
        result = d.validator.validate_plan(plan, packet)
        diagnostic['validation_status'] = result['status']
        if not result['structural_validity']: category = 'RESPONSE_SCHEMA_FAILURE'
        elif result['blocking_findings']:
            codes = [x['code'] for x in result['blocking_findings']]
            category = ('EVIDENCE_GROUNDING_FAILURE' if any('evidence' in x or 'source_identity' in x for x in codes)
                        else 'PLANNING_VALIDATION_BLOCKED')
        if result['structural_validity']:
            from benchmark_preview_v01 import speech_safety
            diagnostic['speech_safety_blockers'] = speech_safety(plan, packet)
            if diagnostic['speech_safety_blockers'] and category is None:
                category = 'SPEECH_ELIGIBILITY_BLOCKED'
        d.recheck_inputs(packet)
        result.update(source=packet['source'], evidence_packet_sha256=d.validator.packet_digest(packet))
        receipt = {'contract_version': '0.3.0', 'mode': 'live_model_inference', 'created_at': d.shared.now(),
            'agent': 'mandala-video-director', 'provider_policy': 'existing_agent_local_model_auth',
            'model_identity': 'provider_reported_not_independently_verified', 'observed_model': diagnostic['observed_model'],
            'evidence_packet_sha256': d.validator.packet_digest(packet), 'prompt_sha256': d.digest_text(prompt),
            'response_sha256': d.digest_text(raw), 'plan_sha256': d.digest_text(d.intake.bounded_json(plan, d.MAX_RESPONSE_BYTES)),
            'saved_response': {'path': str((output/'raw-response.v01.txt').relative_to(d.base.ROOT)), 'sha256': d.digest_text(raw)},
            'code_receipts': request['code_receipts'], 'diagnostic_code_receipt': d.av.reference(Path(__file__).resolve()),
            'elapsed_sec': diagnostic['duration_sec'], 'wrapper_invocations': 1,
            'live_inference_performed': True, 'render_approved': False, 'publish_approved': False}
        artifacts.update({d.PACKET: packet, d.RECEIPT: receipt, d.REPORT: result,
            d.PLAN if result['structural_validity'] else 'rejected-output.v03.json': plan})
        diagnostic['generation_receipt_status'] = 'CREATED'
    except Failure:
        pass
    except (d.base.AdapterError, OSError, ValueError, TypeError, KeyError, RecursionError):
        category = {'request_preparation': 'REQUEST_PREPARATION_FAILURE',
            'invocation': 'INVOCATION_FAILURE', 'response_extraction': 'RESPONSE_EXTRACTION_FAILURE',
            'schema_and_evidence_validation': 'EVIDENCE_GROUNDING_FAILURE'}.get(diagnostic['failure_phase'], 'UNKNOWN_FAILURE')
    diagnostic.update(error_category=category, ended_at=d.shared.now(),
        suggested_next_action='Inspect exact blocking evidence; no automatic retry' if category else 'Independent planning readiness check; no rendering')
    artifacts['invocation-diagnostic.v01.json'] = diagnostic
    d.publish(output, artifacts)
    if diagnostic['generation_receipt_status'] != 'CREATED': raise Failure(diagnostic)
    return output, result


def live_attempt(prepared, *, fix_record=None):
    """Separate capped ledger; reservations survive crashes and are never refilled."""
    d.shared.directory(ROOT, new=not ROOT.exists())
    ROOT.mkdir(parents=True, exist_ok=True)
    lockpath = d.av.checked_path(ROOT/'.diagnostic.lock', 'Diagnostic lock', output=not (ROOT/'.diagnostic.lock').exists())
    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        permit = d.av.read(d.av.checked_path(ROOT/'live-scope.v01.json', 'Remediation scope'))
        if (permit.get('maximum_director_invocations') != 2 or permit.get('automatic_retries') != 0
                or permit.get('user_approved') is not True or permit.get('provider_alias') != PROVIDER
                or permit.get('model_alias') != 'openclaw'):
            raise d.base.AdapterError('Invalid remediation cap')
        packet, prompt, _ = d.load_prepared(prepared); command(prompt)
        if packet['source']['sha256'] != permit['source_sha256'] or permit.get('render_approved') is not False:
            raise d.base.AdapterError('Source/scope mismatch')
        ref = permit['provider_inspection']
        inventory_path = d.av.checked_path(ref['path'], 'Provider inspection')
        inventory = d.av.read(inventory_path)
        if (d.av.reference(inventory_path) != ref or inventory['diagnostic']['process_exit_code'] != 0
                or inventory['inventory']['provider'] != PROVIDER or inventory['inventory']['id'] != 'openclaw'
                or inventory.get('inference_performed') is not False):
            raise d.base.AdapterError('Provider resolution not verified')
        reservations = sorted(ROOT.glob('reservation.*.json'))
        if len(reservations) >= 2: raise d.base.AdapterError('Diagnostic budget exhausted')
        fix = None
        if reservations:
            previous = d.av.read(ROOT/'call.01/invocation-diagnostic.v01.json')
            reservation = d.av.read(reservations[0])
            if (previous['generation_receipt_status'] == 'CREATED' or not fix_record
                    or previous.get('error_category') in (None, 'UNKNOWN_FAILURE')):
                raise d.base.AdapterError('Second call requires actionable failure and a concrete fix')
            fixpath = d.av.checked_path(fix_record, 'Concrete fix'); fix = d.av.read(fixpath)
            if (fix.get('previous_diagnostic') != d.av.reference(ROOT/'call.01/invocation-diagnostic.v01.json')
                    or fix.get('current_code') != d.av.reference(Path(__file__).resolve())
                    or fix.get('previous_code') != reservation.get('diagnostic_code')
                    or fix.get('previous_code') == fix.get('current_code') or not fix.get('rationale')):
                raise d.base.AdapterError('Unproven second-call fix')
        number = len(reservations)+1
        d.shared.write_json(ROOT/f'reservation.{number:02}.json', {'contract_version': '0.1.0',
            'created_at': d.shared.now(), 'scope': d.av.reference(ROOT/'live-scope.v01.json'),
            'source_sha256': packet['source']['sha256'], 'prepared_packet_sha256': d.validator.packet_digest(packet),
            'ordinal': number, 'maximum': 2, 'automatic_retries': 0,
            'diagnostic_code': d.av.reference(Path(__file__).resolve()), 'fix': fix, **FLAGS})
        return run(prepared, ROOT/f'call.{number:02}', live_approved=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', required=True); parser.add_argument('--fix-record')
    args = parser.parse_args(argv)
    try:
        bundle, result = live_attempt(args.prepared, fix_record=args.fix_record)
        print(json.dumps({'bundle': str(bundle.relative_to(d.base.ROOT)), 'status': result['status'], **FLAGS}))
        if d.av.read(bundle/'invocation-diagnostic.v01.json').get('speech_safety_blockers'): return 20
        return d.validator.exit_code(result)
    except (d.base.AdapterError, OSError, ValueError, TypeError, KeyError):
        print('BLOCKED: consult immutable sanitized Director diagnostics', file=sys.stderr); return 1


if __name__ == '__main__':
    with d.intake.processing_deadline(): raise SystemExit(main())
