#!/usr/bin/env python3
"""Accept explicit text-only user review; missing timing/context remain unavailable."""
import argparse
import copy
import json
from pathlib import Path

import speech_intelligence_v01 as speech


def submission(notes, original, current, reviewer):
    if not isinstance(reviewer,str) or not reviewer.strip():
        raise speech.base.AdapterError('Explicit reviewer identifier required')
    before=copy.deepcopy(original); after=copy.deepcopy(current)
    before.pop('code_receipts',None); after.pop('code_receipts',None)
    if before != after or original['request']['human_review']:
        raise speech.base.AdapterError('Review source/evidence changed')
    if (notes.get('origin') != 'human_review_notes_unaccepted'
            or notes.get('source_sha256') != original['source']['sha256']
            or notes.get('evidence_sha256') != speech.digest(original)):
        raise speech.base.AdapterError('User notes/source/evidence mismatch')
    if notes.get('reviewer_identity') and notes['reviewer_identity'] != reviewer:
        raise speech.base.AdapterError('Reviewer identity mismatch')
    rows=notes.get('text_notes')
    if not isinstance(rows,list) or len(rows)!=len(current['segments']):
        raise speech.base.AdapterError('Full per-segment text review required')
    ids={s['segment_id']:s for s in current['segments']}; reviewed=[]; seen=set()
    for row in rows:
        if not isinstance(row,dict): raise speech.base.AdapterError('Malformed text note')
        sid=row.get('segment_id'); source=ids.get(sid)
        if (not source or sid in seen or row.get('original_text_sha256')!=speech.digest(source['text'])
                or not isinstance(row.get('proposed_text'),str) or not row['proposed_text'].strip()
                or not isinstance(row.get('notes'),str) or not row['notes'].strip()):
            raise speech.base.AdapterError('Text review missing, duplicated or unbound')
        seen.add(sid)
        reviewed.append({'segment_id':sid,'original_text_sha256':row['original_text_sha256'],
            'reviewed_text':row['proposed_text'].strip(),'accuracy_confirmed':True})
    # The caller must have explicit endorsement of THESE texts, not just a file upload.
    # Free-form "safe" notes are retained separately; never converted to five semantic assertions.
    return speech.check('review_submission',{'contract_version':'0.1.0','origin':'human_source_review',
        'reviewer_identity':reviewer,'source_sha256':current['source']['sha256'],
        'evidence_sha256':speech.digest(current),'review_method':'user_supplied_review_notes',
        'text_reviews':reviewed,'boundary_reviews':[],'word_reviews':[],
        'selection_reviews':[],'context_links':[],'subtitle_reviews':[]})


def accept(notes_path, original_report, output, *, reviewer, endorsement):
    if not isinstance(endorsement,str) or not endorsement.strip():
        raise speech.base.AdapterError('Explicit user text endorsement required')
    from run_adaptive_director_v03 import safe_text
    safe_text(endorsement,speech.MAX_BYTES)
    output=speech.shared.directory(output,new=True)
    notes=speech.read(notes_path); original=speech.check('report',speech.read(original_report))
    current=speech.assess(**original['request'])
    human=submission(notes,original,current,reviewer)
    from run_adaptive_director_v03 import publish
    publish(output,{'original-user-notes.v01.json':notes,'assessment.before-review.v01.json':current,
        'text-review.submission.v01.json':human,'user-endorsement.v01.json':{
            'basis':'direct_user_message','text':endorsement,'reviewer_identifier':reviewer,
            'scope':'per_segment_text_only','timing_accuracy_not_supplied':True,
            'original_notes':speech.av.reference(speech.av.checked_path(notes_path,'Imported user notes')),
            'original_assessment':speech.av.reference(speech.av.checked_path(original_report,'Original review assessment')),
            'new_producer':speech.av.reference(Path(__file__).resolve()),**speech.FLAGS}})
    speech.review_data(human,current,reviewer)
    receipt={'contract_version':'0.1.0','origin':'explicit_human_acceptance','accepted_by':reviewer,
        'accepted_at':speech.shared.now(),'report':speech.av.reference(output/'assessment.before-review.v01.json'),
        'submission':speech.av.reference(output/'text-review.submission.v01.json'),'code_receipts':speech.refs(),**speech.FLAGS}
    speech.shared.write_json(output/'text-review.receipt.v01.json',speech.check('review_receipt',receipt))
    report=speech.assess(**{**current['request'],'human_review':speech.shared.relative(output/'text-review.receipt.v01.json')})
    speech.shared.write_json(output/'assessment.text-reviewed.v01.json',report)
    assert speech.load_report(output/'assessment.text-reviewed.v01.json')==report
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('notes','original-report','output','reviewer','user-text-endorsement'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    try:
        report=accept(args.notes,args.original_report,args.output,reviewer=args.reviewer,endorsement=args.user_text_endorsement)
        print(json.dumps({'eligibility':report['eligibility'],**speech.FLAGS})); return 0
    except (speech.base.AdapterError,OSError,ValueError,TypeError,KeyError,RecursionError):
        print('BLOCKED: explicit text review, source, output or evidence integrity'); return 1


if __name__=='__main__':
    with speech.intake.processing_deadline(): raise SystemExit(main())
