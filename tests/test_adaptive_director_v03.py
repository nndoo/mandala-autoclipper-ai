"""Director intake and untrusted model response tests, entirely offline."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'scripts'))
import adaptive_director_evidence_v03 as e
import run_adaptive_director_v03 as run
import adaptive_director_v03_fixtures as f
import test_adaptive_director_input_v03 as old


def setUpModule():
    global guard
    guard=patch('socket.socket.connect',side_effect=AssertionError('No remote requests in offline tests'))
    guard.start()
def tearDownModule():guard.stop()


class IntakeTests(unittest.TestCase):
    def setUp(self):
        old.AdapterTests.setUp(self)
        for name in ('adaptive-editing-plan.v0.3.schema.json',):
            shutil.copyfile(PROJECT/'src/schemas'/name,self.root/'src/schemas'/name)
        e.base.build_director_input(self.video,self.metadata_path,self.analysis_path,self.output)
        self.bundle=self.root/'av';self.bundle.mkdir()
        self.binding={**self.source,'path':'source.mp4','sha256':self.metadata['verification']['sha256']}
        self.report={'source':self.binding,'eligibility':{'music_rhythm':False,'visual_timing':True}}
        audio={'data':{'audio_status':'present','rhythm':{'status':'uncertain'}},'events':[]}
        visual={'data':{'sampling':{'timestamp_basis':'decoded_pts','frame_stride':4}},'events':[]}
        for name,data in ((e.av.AUDIO,audio),(e.av.VISUAL,visual),(e.av.CORRELATION,{'events':[]}),(e.av.REPORT,self.report)):
            (self.bundle/name).write_text(json.dumps(data))
        mock=patch.object(e.av,'validate_bundle',side_effect=lambda _:copy.deepcopy(self.report))
        self.replay=mock.start();self.addCleanup(mock.stop)
    def save_inputs(self):old.AdapterTests.save_inputs(self)
    def build(self,**kw):
        args=dict(video=self.video,metadata=self.metadata_path,analysis=self.analysis_path,director_input=self.output,av_bundle=self.bundle)
        args.update(kw);return e.build_packet(**args)
    def test_valid_source(self):self.assertEqual(self.build()['source'],self.binding);self.replay.assert_called_once()
    def test_packet_replay(self):p=self.build();self.assertEqual(e.validate_packet(p),p)
    def test_packet_tampering(self):p=self.build();p['missing_evidence']=[];self.assertRaises(e.base.AdapterError,e.validate_packet,p)
    def test_invalid_packet_header(self):self.assertRaises(e.base.AdapterError,e.validate_packet,{'contract_version':'0'})
    def test_missing_source(self):self.video.unlink();self.assertRaises(e.base.AdapterError,self.build)
    def test_missing_canonical(self):self.analysis_path.unlink();self.assertRaises(e.base.AdapterError,self.build)
    def test_source_sha_mismatch(self):self.video.write_bytes(b'tampered');self.assertRaises(e.base.AdapterError,self.build)
    def test_metadata_mismatch(self):self.metadata['source']['fps']=24;self.save_inputs();self.assertRaises(e.base.AdapterError,self.build)
    def test_invalid_canonical(self):self.analysis['segments']=[];self.save_inputs();self.assertRaises(e.base.AdapterError,self.build)
    def test_director_source_mismatch(self):d=json.loads(self.output.read_text());d['source']['video_id']='other';self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_canonical_reference_mismatch(self):d=json.loads(self.output.read_text());d['evidence']['universal_analysis']['path']='metadata.json';self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_canonical_precision_forged(self):d=json.loads(self.output.read_text());d['evidence']['universal_analysis']['timing_precision']='frame_verified';self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_tampered_av_rejected_by_replay(self):self.replay.side_effect=e.base.AdapterError('AV replay mismatch');self.assertRaises(e.base.AdapterError,self.build)
    def test_cross_source_av(self):self.report['source']={**self.binding,'sha256':'b'*64};self.assertRaises(e.base.AdapterError,self.build)
    def test_visual_attachment_matches_artifact(self):d=json.loads(self.output.read_text());d['evidence']['visual_timing']={'path':'av/'+e.av.VISUAL,'timing_precision':'signal_estimated'};self.output.write_text(json.dumps(d));self.assertEqual(self.build()['source'],self.binding)
    def test_ineligible_music_attachment(self):d=json.loads(self.output.read_text());d['evidence']['music_rhythm']={'path':'av/'+e.av.AUDIO,'timing_precision':'signal_estimated'};self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_invalid_artifact_path(self):d=json.loads(self.output.read_text());d['evidence']['visual_timing']={'path':'missing.json','timing_precision':'signal_estimated'};self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_traversal(self):self.assertRaises(e.base.AdapterError,self.build,video='av/../source.mp4')
    def test_symlink_escape(self):link=self.root/'escape';link.symlink_to(PROJECT/'README.md');self.assertRaises(e.base.AdapterError,self.build,analysis=link)
    def test_renderer_unknown(self):self.assertEqual(self.build()['renderer_capabilities']['verification_status'],'unknown')
    def test_false_renderer_capability(self):d=json.loads(self.output.read_text());d['renderer_capabilities']['verification_status']='verified';self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_transcript_attachment_without_eligibility(self):d=json.loads(self.output.read_text());d['evidence']['transcript']={'path':'canonical.json','timing_precision':'approximate'};self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_alignment_attachment_without_eligibility(self):d=json.loads(self.output.read_text());d['evidence']['speech_alignment']={'path':'canonical.json','timing_precision':'asr_estimate'};self.output.write_text(json.dumps(d));self.assertRaises(e.base.AdapterError,self.build)
    def test_input_bounded(self):self.analysis['content_profile']['summary']='x'*60000;self.save_inputs();self.assertRaises(e.base.AdapterError,self.build)
    def test_missing_speech_explicitly_unavailable(self):self.assertEqual(self.build()['speech']['eligibility']['status'],'unavailable')
    def speech_fixture(self,eligible=False):
        bundle=self.root/'speech';bundle.mkdir()
        req=e.gate.speech_requirements(self.analysis)
        manifest={'source':self.source,'speech_requirements':req}
        report={'source_integrity_status':'verified','evidence_eligibility':{'status':'ineligible','transcript':eligible,'speech_alignment':False},'text_verification_status':'unverified','timing_verification_status':'unavailable'}
        stage={'source':{'sha256':self.binding['sha256'],'metadata':self.source},'canonical_analysis':{'path':'canonical.json','sha256':e.gate.sha256_file(self.analysis_path),'source_metadata_match':True,'findings_status':'unverified'},'speech_requirements':req}
        for name,value in ((e.shared.MANIFEST,manifest),(e.shared.REPORT,report),(e.shared.GATE,stage),(e.shared.DRAFT,{'text':'DO NOT SUPPLY AS ELIGIBLE TEXT'})):(bundle/name).write_text(json.dumps(value))
        mock=patch.object(e,'validate_speech_bundle',return_value=(manifest,report));mock.start();self.addCleanup(mock.stop)
        return bundle,stage
    def test_invalid_transcript_eligibility_promotion(self):b,_=self.speech_fixture(True);self.assertRaises(e.base.AdapterError,self.build,speech_bundle=b)
    def test_draft_text_is_quarantined(self):b,_=self.speech_fixture();p=self.build(speech_bundle=b);self.assertIsNone(p['speech']['eligible_transcript']);self.assertNotIn('DO NOT SUPPLY',json.dumps(p))
    def test_cross_source_speech(self):b,s=self.speech_fixture();s['source']['sha256']='c'*64;(b/e.shared.GATE).write_text(json.dumps(s));self.assertRaises(e.base.AdapterError,self.build,speech_bundle=b)
    def test_stage5a_canonical_receipt_mismatch(self):b,s=self.speech_fixture();s['canonical_analysis']['sha256']='c'*64;(b/e.shared.GATE).write_text(json.dumps(s));self.assertRaises(e.base.AdapterError,self.build,speech_bundle=b)
    def test_stage5a_classification_conflict(self):b,s=self.speech_fixture();s['speech_requirements']['overall_requirement']='required';(b/e.shared.GATE).write_text(json.dumps(s));self.assertRaises(e.base.AdapterError,self.build,speech_bundle=b)


class DirectorOutputTests(unittest.TestCase):
    def setUp(self):self.plan=f.plan()
    def test_json_plan(self):self.assertEqual(run.parse_response(json.dumps(self.plan)),self.plan)
    def test_openclaw_local_envelope(self):self.assertEqual(run.parse_response(json.dumps({'ok':True,'outputs':[{'text':json.dumps(self.plan)}]})),self.plan)
    def test_saved_legacy_envelope(self):self.assertEqual(run.parse_response(json.dumps({'payloads':[{'text':json.dumps(self.plan)}]})),self.plan)
    def test_fenced_json(self):self.assertEqual(run.parse_response(json.dumps({'text':'```json\n'+json.dumps(self.plan)+'\n```'})),self.plan)
    def test_malformed(self):self.assertRaises(e.base.AdapterError,run.parse_response,'{bad}')
    def test_duplicate_keys(self):self.assertRaises(e.base.AdapterError,run.parse_response,'{"text":"x","text":"y"}')
    def test_nonfinite_json(self):self.assertRaises(e.base.AdapterError,run.parse_response,'{"text":NaN}')
    def test_array_response(self):self.assertRaises(e.base.AdapterError,run.parse_response,'[]')
    def test_ambiguous_multiple_payloads(self):self.assertRaises(e.base.AdapterError,run.parse_response,json.dumps({'outputs':[{'text':'{}'},{'text':'{}'}]}))
    def test_wrong_envelope(self):self.assertRaises(e.base.AdapterError,run.parse_response,json.dumps({'choices':[{'text':'{}'}]}))
    def test_overlarge_response(self):self.assertRaises(e.base.AdapterError,run.parse_response,'x'*(run.MAX_RESPONSE_BYTES+1))
    def test_credential_not_persistable(self):self.assertRaises(e.base.AdapterError,run.safe_text,'sk-SYNTHETIC_ONLY_TEST_12345')
    def test_bearer_not_persistable(self):self.assertRaises(e.base.AdapterError,run.safe_text,'Bearer SYNTHETIC_TEST_TOKEN')
    def test_live_call_requires_approval(self):self.assertRaises(e.base.AdapterError,run.live_response,'test prompt')
    def test_production_logic_not_video_specific(self):
        text=Path(run.__file__).read_text()+Path(e.__file__).read_text()
        for name in ('pak-fuad','mandala-original.mp4','cinematic-769377'):
            self.assertNotIn(name,text)
    def test_prompt_policy_present(self):
        text=run.make_prompt(f.packet('present','present'))
        for term in ('ADAPTIVE_DIRECTOR_V03','INPUT_PACKET','OUTPUT_SCHEMA','ineligible','speech_safe false','Do not use a fixed genre template'):
            self.assertIn(term,text)
        for term in ('progression and an ending','repeated source ranges','different label or effect count','fixed duration'):
            self.assertIn(term,text)
