#!/usr/bin/env python3
"""Offline source-bound review packet; never creates human acceptance or an edit plan."""
import argparse
import copy
import html
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote

import numpy as np

import speech_intelligence_v01 as speech


def proposal(report, feedback=None, candidates=None):
    """Feedback changes only review suggestions, never the original assessment."""
    rows = copy.deepcopy(report['segments'])
    feedback = feedback or []
    if len(feedback) > 64 or len(candidates or []) > 64:
        raise speech.base.AdapterError('Review packet item limit')
    for row in rows:
        row['original_text_sha256'] = speech.digest(row['text'])
        row['proposed_text'] = row['text'].strip()
        row['review_status'] = 'PENDING_HUMAN_REVIEW'
    for item in feedback:
        if (set(item) != {'origin', 'source_sha256', 'segment_id', 'from', 'to', 'user_statement'}
                or item['origin'] != 'user_supplied_feedback' or item['source_sha256'] != report['source']['sha256']
                or any(not isinstance(item[k], str) or not item[k].strip() for k in ('from', 'to', 'user_statement'))):
            raise speech.base.AdapterError('Feedback source/origin/shape mismatch')
        row = next((r for r in rows if r['segment_id'] == item['segment_id']), None)
        pattern = r'(?<!\w)' + re.escape(item['from']) + r'(?!\w)'
        if row is None or len(re.findall(pattern, row['proposed_text'])) != 1:
            raise speech.base.AdapterError('Feedback must identify one exact original word')
        row['proposed_text'] = re.sub(pattern, lambda _: item['to'], row['proposed_text'])
    choices = copy.deepcopy(candidates or [])
    for choice in choices:
        if (set(choice) != {'candidate_id', 'label', 'basis', 'source_windows'}
                or any(not isinstance(choice[k], str) or not choice[k].strip() for k in ('candidate_id', 'label', 'basis'))
                or not isinstance(choice['source_windows'], list) or not choice['source_windows']
                or len(choice['source_windows']) > 64
                or any(not isinstance(w, list) or len(w) != 2 or not speech.range_ok(*w, report['source']['duration_sec']) for w in choice['source_windows'])):
            raise speech.base.AdapterError('Invalid review candidate')
        choice['review_status'] = 'PENDING_HUMAN_REVIEW'
    if len({c['candidate_id'] for c in choices}) != len(choices):
        raise speech.base.AdapterError('Duplicate review candidate')
    return {'contract_version': '0.1.0', 'origin': 'offline_review_preparation', 'source': report['source'],
        'evidence_sha256': speech.digest(report), 'segments': rows, 'feedback': feedback, 'candidates': choices,
        'boundaries_sec': sorted({edge for r in rows for edge in (r['start_sec'], r['end_sec'])}),
        'eligibility': report['eligibility'], 'word_timestamps': 'unavailable' if not report['words'] else 'asr_estimate',
        'human_review': None, 'limitations': ['Suggestions are not accepted text or verified boundaries',
            'Speaker and question-answer relationships require source listening',
            'Exported notes are not review_submission or human attestation'], **speech.FLAGS}


PAGE = '''<!doctype html><html lang="id"><meta charset="utf-8"><title>Speech source review</title>
<style>body{font:16px system-ui;max-width:1100px;margin:24px auto;padding:16px;background:#f4f5f7;color:#17202a}video{width:270px;max-height:480px;background:black}section{background:white;padding:16px;margin:12px 0;border-radius:8px}textarea{width:96%;min-height:65px}button{margin:4px;padding:8px;cursor:pointer}small{display:block;color:#555}canvas{width:100%;height:130px;background:#eef2f5}input{padding:8px}pre{white-space:pre-wrap}</style>
<h1>Review sumber: teks, boundary, dan konteks</h1><p>Belum ada persetujuan. Koreksi kata tidak menyetujui seluruh transkrip. Dengarkan sumber, periksa speaker, awal/akhir kalimat, serta hubungan pertanyaan–jawaban. Timestamps ASR tetap estimasi.</p>
<video id="video" controls preload="metadata" src="@@VIDEO@@"></video>
<p><button id="normal">Kecepatan 1×</button><button id="slow">Kecepatan 0,5×</button> <span id="clock"></span></p>
<canvas id="wave" width="1000" height="130"></canvas><p id="scope"></p>
<p>Waveform berasal dari PCM sumber; tombol boundary menampilkan konteks ±1 detik. Klik waveform untuk seek. Satu bin 20 ms bukan timestamp kata atau bukti batas kalimat.</p>
<label>Nama reviewer <input id="identity" placeholder="Isi sendiri"></label><h2>Seluruh segmen sumber</h2><div id="rows"></div>
<h2>Pilihan untuk diperiksa (bukan plan final)</h2><div id="choices"></div>
<h2>Catatan konteks / speaker / koreksi boundary</h2><textarea id="context" placeholder="Catat nomor segmen yang saling bergantung, speaker, boundary yang salah beserta waktu koreksi, dan potongan yang aman/tidak aman."></textarea>
<p>Review timing untuk engine existing membutuhkan estimasi error boundary ≤0,05 detik. Jangan menyatakan ini jika belum dapat diperiksa. Teks belum accepted sampai pengguna memberikan review eksplisit dan receipt divalidasi.</p>
<button id="export">Unduh catatan review (belum diterima)</button><p>File ini hanya notes; tidak memberi render approval atau membuat human attestation. Berikan catatan kepada Codex untuk validasi checkpoint.</p>
<script id="packet" type="application/json">@@PACKET@@</script><script>
const p=JSON.parse(document.getElementById('packet').textContent),v=document.getElementById('video');let stop=null,range=[0,p.source.duration_sec];
const fmt=x=>Number(x).toFixed(3),rows=document.getElementById('rows'),choices=document.getElementById('choices');
function draw(){const c=document.getElementById('wave'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);ctx.strokeStyle='#245d81';ctx.beginPath();p.waveform.bins.forEach((b,i)=>{const t=i*p.waveform.bin_sec;if(t<range[0]||t>range[1])return;const x=(t-range[0])/(range[1]-range[0])*c.width;ctx.moveTo(x,65-b[1]*60);ctx.lineTo(x,65-b[0]*60)});ctx.stroke();document.getElementById('scope').textContent=`Waveform ${fmt(range[0])}–${fmt(range[1])} s`;}
function play(a,b){range=[Math.max(0,a),Math.min(p.source.duration_sec,b)];v.currentTime=range[0];stop=range[1];draw();v.play().catch(()=>{});}
function button(parent,label,a,b){const el=document.createElement('button');el.textContent=label;el.onclick=()=>play(a,b);parent.append(el);}
p.segments.forEach((r,i)=>{const section=document.createElement('section'),head=document.createElement('h3');head.textContent=`S${String(i+1).padStart(2,'0')} · ${fmt(r.start_sec)}–${fmt(r.end_sec)} s`;section.append(head);const raw=document.createElement('small');raw.textContent=`ASR asli: ${r.text} | Speaker: ${r.reported_speaker??'belum terverifikasi'}`;section.append(raw);button(section,'Putar dengan konteks',r.start_sec-.5,r.end_sec+.5);button(section,'Boundary awal ±1 s',r.start_sec-1,r.start_sec+1);button(section,'Boundary akhir ±1 s',r.end_sec-1,r.end_sec+1);const text=document.createElement('textarea');text.value=r.proposed_text;text.id='text-'+i;section.append(text);const notes=document.createElement('textarea');notes.id='note-'+i;notes.placeholder='Benar / koreksi teks, speaker, kalimat lengkap, boundary dan estimasi error. Kosong = belum direview.';section.append(notes);rows.append(section);});
p.candidates.forEach((c,i)=>{const s=document.createElement('section'),h=document.createElement('h3');h.textContent=c.label;s.append(h);const info=document.createElement('p');info.textContent=c.basis;s.append(info);c.source_windows.forEach(w=>button(s,`${fmt(w[0])}–${fmt(w[1])} s`,w[0],w[1]));const n=document.createElement('textarea');n.id='choice-'+i;n.placeholder='Aman/tidak aman? Makna dan urutan Q&A tetap benar? Catat syarat dan koreksi.';s.append(n);choices.append(s);});
v.ontimeupdate=()=>{document.getElementById('clock').textContent=`Source ${fmt(v.currentTime)} s`;if(stop!==null&&v.currentTime>=stop){v.pause();stop=null;}};document.getElementById('normal').onclick=()=>v.playbackRate=1;document.getElementById('slow').onclick=()=>v.playbackRate=.5;
document.getElementById('wave').onclick=e=>{const b=e.currentTarget.getBoundingClientRect();v.currentTime=range[0]+(e.clientX-b.left)/b.width*(range[1]-range[0]);};
document.getElementById('export').onclick=()=>{const notes={origin:'human_review_notes_unaccepted',source_sha256:p.source.sha256,evidence_sha256:p.evidence_sha256,reviewer_identity:document.getElementById('identity').value,text_notes:p.segments.map((s,i)=>({segment_id:s.segment_id,original_text_sha256:s.original_text_sha256,proposed_text:document.getElementById('text-'+i).value,notes:document.getElementById('note-'+i).value})),selection_notes:p.candidates.map((c,i)=>({candidate_id:c.candidate_id,source_windows:c.source_windows,notes:document.getElementById('choice-'+i).value})),context_notes:document.getElementById('context').value,accepted:false,render_approved:false,publish_approved:false};const url=URL.createObjectURL(new Blob([JSON.stringify(notes,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='speech-review-notes.unaccepted.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};draw();
</script></html>'''


def prepare(report_path, output, *, feedback=None, candidates=None):
    output = speech.shared.directory(output, new=True)
    report = speech.load_report(report_path)
    packet = proposal(report, feedback, candidates)
    source = speech.av.checked_path(report['source']['path'], 'Review source')
    streams = speech.gate.audio_streams(source)
    if not streams:
        raise speech.base.AdapterError('No source audio for listening review')
    with tempfile.TemporaryDirectory(prefix='mandala-review-waveform-') as name:
        path = Path(name)/'source.pcm'
        pcm = speech.shared.capture_pcm(source, streams[0], path, speech.shared.limits_config())
        if pcm != report['pcm']:
            raise speech.base.AdapterError('Review waveform PCM differs from generation')
        samples = np.frombuffer(path.read_bytes(), dtype='<i2')
        size = 320
        packet['waveform'] = {'bin_sec': .02, 'method': 'min_max_mono_16khz_s16le', 'pcm': pcm,
            'bins': [[round(float(samples[i:i+size].min())/32768,5), round(float(samples[i:i+size].max())/32768,5)]
                for i in range(0,len(samples),size)]}
    packet['report'] = speech.av.reference(speech.av.checked_path(report_path, 'Review evidence'))
    packet['producer'] = speech.av.reference(Path(__file__).resolve())
    if speech.gate.sha256_file(source) != report['source']['sha256']:
        raise speech.base.AdapterError('Source changed during review preparation')
    encoded = json.dumps(packet, ensure_ascii=True, allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    video_url = quote(os.path.relpath(source, output), safe='/')
    page = PAGE.replace('@@VIDEO@@',html.escape(video_url, quote=True)).replace('@@PACKET@@',encoded)
    lines = ['# Review speech sumber — PENDING HUMAN REVIEW', '', 'Koreksi pengguna hanya feedback; semua teks/boundary/konteks tetap menunggu review.', '',
        f"Source SHA-256: `{report['source']['sha256']}`", '', '| Segmen | Source waktu (s) | Teks usulan review |', '|---|---|---|']
    for i,row in enumerate(packet['segments'],1):
        text = row['proposed_text'].replace('|','\\|').replace('\n',' ')
        lines.append(f"| S{i:02d} | {row['start_sec']:.6f}–{row['end_sec']:.6f} | {text} |")
    import run_adaptive_director_v03 as director
    return director.publish(output, {'review-packet.v01.json':packet, 'review.html':page, 'transcript-review.md':'\n'.join(lines)+'\n'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True); parser.add_argument('--output-dir', required=True)
    parser.add_argument('--feedback'); parser.add_argument('--candidates')
    args = parser.parse_args()
    try:
        def items(path):
            if not path: return None
            value = speech.read(path)
            if set(value) != {'items'} or not isinstance(value['items'],list):
                raise speech.base.AdapterError('Expected items object')
            return value['items']
        result = prepare(args.report,args.output_dir,feedback=items(args.feedback),candidates=items(args.candidates))
        print(json.dumps({'status':'PENDING_HUMAN_REVIEW','bundle':speech.shared.relative(result),**speech.FLAGS}))
        return 0
    except (speech.base.AdapterError, OSError, ValueError, TypeError, KeyError):
        print('BLOCKED: review source, input, PCM or exclusive output integrity failure')
        return 1


if __name__ == '__main__':
    with speech.intake.processing_deadline(): raise SystemExit(main())
