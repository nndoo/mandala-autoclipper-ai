"""Real offline FFmpeg integration: actual MP4s, effects, receipts and refusals."""
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
import renderer_core_v01 as core
import render_video_v01 as renderer
import render_test_fixtures_v01 as f


def setUpModule():
    global guard
    guard=patch('socket.socket.connect',side_effect=AssertionError('FFmpeg integration forbids network'));guard.start()
def tearDownModule():guard.stop()


class FFmpegIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.TEST_ROOT.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=core.TEST_ROOT,prefix='ffmpeg-integration-')
        cls.addClassCleanup(cls.temp.cleanup);cls.root=Path(cls.temp.name);cls.bundles={};cls.manifests={}
        for name in f.NAMES:
            bundle=cls.root/name;cls.manifests[name]=renderer.self_test(name,bundle);cls.bundles[name]=bundle
        cls.registry=renderer.capability_registry(list(cls.bundles.values()))
    def test_actual_ten_mp4_outputs(self):
        for name,bundle in self.bundles.items():
            with self.subTest(name=name):self.assertGreater((bundle/'render.mp4').stat().st_size,1000)
    def test_h264_aac_pixel_format(self):
        for name,m in self.manifests.items():
            with self.subTest(name=name):self.assertEqual(m['output']['video_codec'],'h264');self.assertEqual(m['output']['pixel_format'],'yuv420p');self.assertEqual(m['output']['audio_codec'],None if name=='silent' else 'aac')
    def test_expected_real_durations(self):
        expected={'basic':6,'dynamic':6.2,'captions':6.5,'audio':6,'music':6,'normalization':6,'silent':6,'fullhd':1,'reuse':6,'silent-music':6}
        for name,duration in expected.items():
            with self.subTest(name=name):self.assertAlmostEqual(self.manifests[name]['output']['duration_sec'],duration,places=2)
    def test_real_basic_audio_video_synchronization(self):m=self.manifests['basic']['verification']['fixture_measurements'];self.assertEqual(m['frame_scene_order'],[2,0,1]);self.assertTrue(all(abs(a-b)<15 for a,b in zip(m['aligned_tone_hz'],[880,440,660])))
    def test_speed_preserves_pitch(self):self.assertLess(abs(self.manifests['dynamic']['verification']['fixture_measurements']['speed_pitch_hz']-440),15)
    def test_freeze_has_defined_silence_and_nonblack_frame(self):m=self.manifests['dynamic']['verification']['fixture_measurements'];self.assertLess(m['freeze_rms'],.01);self.assertTrue(m['freeze_frame_nonblack'])
    def test_crop_zoom_color_change_actual_pixels(self):self.assertTrue(self.manifests['dynamic']['verification']['fixture_measurements']['zoom_crop_color_changed'])
    def test_crossfade_compiled_and_executed(self):m=self.manifests['dynamic'];self.assertIn('crossfade',m['verified_capabilities_used']);self.assertEqual([s['overlap_sec'] for s in m['timeline']['shots']],[.3,.2,0]);self.assertTrue(m['verification']['decoded_to_completion'])
    def test_caption_source_to_output_shift_is_measured(self):m=self.manifests['captions']['verification']['fixture_measurements'];self.assertEqual(m['caption_source_window'],[3,3.5]);self.assertEqual(m['caption_output_window'],[4.85,5.475]);self.assertGreater(m['subtitle_safe_area_difference'],1)
    def test_timed_hook_cta_are_visible(self):m=self.manifests['captions']['verification']['fixture_measurements'];self.assertGreater(m['hook_safe_area_difference'],1);self.assertTrue(m['cta_visible'])
    def test_literal_expansion_and_filter_text_not_executed(self):self.assertTrue(self.manifests['captions']['verification']['fixture_measurements']['literal_text_file_expansion_disabled'])
    def test_gain_duck_and_fades_measured(self):m=self.manifests['audio']['verification']['fixture_measurements'];self.assertTrue(.42<m['gain_ratio']<.6);self.assertTrue(.28<m['duck_ratio']<.44);self.assertTrue(m['fade_in_out_measured'])
    def test_local_asset_tone_actually_mixed(self):m=self.manifests['music']['verification']['fixture_measurements'];self.assertGreater(m['asset_220_hz_magnitude'],5);self.assertEqual(m['asset_rights_scope'],'TEST_ONLY')
    def test_normalization_actual_signal(self):r=self.manifests['normalization']['verification']['fixture_measurements']['normalized_rms'];self.assertTrue(.01<r<.15)
    def test_silent_visual_only_no_extra_music(self):self.assertFalse(self.manifests['silent']['output']['audio_present']);self.assertEqual(self.manifests['silent']['verification']['audio_frame_count'],0)
    def test_fullhd_actual_portrait_output(self):m=self.manifests['fullhd'];self.assertEqual((m['output']['width'],m['output']['height']),(1080,1920))
    def test_full_decode_and_timestamps_all_outputs(self):
        for name,m in self.manifests.items():
            with self.subTest(name=name):self.assertTrue(m['verification']['decoded_to_completion']);self.assertTrue(m['verification']['presentation_timestamps_continuous'])
    def test_output_hashes_match_real_files(self):
        for name,bundle in self.bundles.items():
            with self.subTest(name=name):self.assertEqual(core.intake.gate.sha256_file(bundle/'render.mp4'),self.manifests[name]['output']['sha256'])
    def test_test_only_container_title(self):
        for name,bundle in self.bundles.items():
            with self.subTest(name=name):self.assertTrue(core.probe(bundle/'render.mp4')['format']['tags']['title'].startswith('TEST_ONLY'))
    def test_manifests_validate_and_never_approve_production(self):
        for name,m in self.manifests.items():
            with self.subTest(name=name):core.base.validate_object(m,core.base.load_schema('render-manifest.v0.1.schema.json'),'manifest');self.assertFalse(m['production_approval_granted']);self.assertFalse(m['publish_approved']);self.assertEqual(m['editorial_quality_review'],'NOT_PERFORMED')
    def test_capabilities_verified_by_real_proofs(self):
        for cap in ['trim','reorder','concat','speed','freeze','crossfade','crop','zoom','color_grade','overlay','subtitle','audio_gain','audio_duck','denoise','audio_fade','normalization','music_bed','sound_effect']:
            with self.subTest(cap=cap):self.assertEqual(self.registry['operations'][cap]['status'],'verified');self.assertTrue(self.registry['operations'][cap]['proofs'])
    def test_unsupported_features_explicit(self):
        for cap in ['animated_zoom','word_highlighting','custom_arbitrary','subject_tracking','semantic_color_intent']:
            with self.subTest(cap=cap):self.assertEqual(self.registry['operations'][cap]['status'],'unsupported')
    def test_reuse_verified_by_real_repetition(self):self.assertEqual(self.registry['operations']['reuse']['status'],'verified');self.assertEqual(self.manifests['reuse']['verification']['fixture_measurements']['frame_scene_order'],[0,0,2])
    def test_explicit_asset_mix_on_silent_source(self):self.assertFalse(core.media_info(self.bundles['silent-music']/'source.mp4')['audio_present']);self.assertTrue(self.manifests['silent-music']['output']['audio_present']);self.assertGreater(self.manifests['silent-music']['verification']['fixture_measurements']['asset_220_hz_magnitude'],5)
    def test_ass_availability_not_promoted(self):self.assertEqual(self.registry['operations']['ass_subtitle_engine']['status'],'not_tested')
    def test_capability_receipt_validation(self):
        data=renderer.capability_registry([self.bundles['basic']]);path=self.root/'capabilities.json';core.shared.write_json(path,data);self.assertEqual(renderer.validate_registry(path),data)
    def test_multiple_proof_order_replays_canonically(self):
        bundles=[self.bundles['dynamic'],self.bundles['basic']]
        data=renderer.capability_registry(bundles)
        self.assertEqual(data,renderer.capability_registry(list(reversed(bundles))))
        path=self.root/'multiple-capabilities.json';core.shared.write_json(path,data)
        self.assertEqual(renderer.validate_registry(path),data)

    def test_capability_receipt_forged_status_refused(self):
        data=renderer.capability_registry([self.bundles['basic']]);data['operations']['zoom']['status']='verified';path=self.root/'forged.json';core.shared.write_json(path,data);self.assertRaises(core.Error,renderer.validate_registry,path)
    def test_capability_proof_hash_tamper_refused(self):
        data=copy.deepcopy(self.registry);data['operations']['trim']['proofs'][0]['sha256']='a'*64;path=self.root/'forged-hash.json';core.shared.write_json(path,data);self.assertRaises(core.Error,renderer.validate_registry,path)
    def test_manifest_plan_digest_tamper_refused(self):
        original=core.read_json;forged=copy.deepcopy(self.manifests['basic']);forged['plan_sha256']='c'*64
        with patch.object(core,'read_json',side_effect=lambda path:forged if Path(path).name==renderer.MANIFEST else original(path)):
            self.assertRaises(core.Error,renderer.capability_registry,[self.bundles['basic']])
    def test_manifest_output_metadata_tamper_refused(self):
        original=core.read_json;forged=copy.deepcopy(self.manifests['basic']);forged['output']['duration_sec']=7
        with patch.object(core,'read_json',side_effect=lambda path:forged if Path(path).name==renderer.MANIFEST else original(path)):
            self.assertRaises(core.Error,renderer.capability_registry,[self.bundles['basic']])
    def test_existing_output_refused_before_ffmpeg(self):
        with patch.object(f,'generate_source',side_effect=AssertionError('must not start FFmpeg')):self.assertRaises(core.Error,renderer.self_test,'basic',self.bundles['basic'])
    def test_unknown_test_identity_refused(self):self.assertRaises(core.Error,renderer.self_test,'live-plan',self.root/'unknown')
    def test_synthetic_plan_fingerprint_tamper_refused(self):
        b=self.bundles['basic'];identity=core.read_json(b/renderer.IDENTITY);plan=core.read_json(b/renderer.PLAN);spec=core.read_json(b/renderer.SPEC);identity['plan_sha256']='a'*64
        self.assertRaises(core.Error,f.admit,identity,plan,spec,b/'source.mp4',b,{})
    def test_source_fingerprint_tamper_refused(self):
        b=self.bundles['basic'];identity=core.read_json(b/renderer.IDENTITY);plan=core.read_json(b/renderer.PLAN);spec=core.read_json(b/renderer.SPEC);identity['source_sha256']='a'*64
        self.assertRaises(core.Error,f.admit,identity,plan,spec,b/'source.mp4',b,{})
    def test_caption_eligibility_tamper_refused(self):
        b=self.bundles['captions'];identity=core.read_json(b/renderer.IDENTITY);plan=core.read_json(b/renderer.PLAN);spec=core.read_json(b/renderer.SPEC);plan['variants'][0]['operations'][1]['parameters']['caption']['verification_status']='unverified'
        self.assertRaises(core.Error,f.admit,identity,plan,spec,b/'source.mp4',b,{})
    def test_test_receipt_cannot_be_promoted(self):
        b=self.bundles['basic'];identity=core.read_json(b/renderer.IDENTITY);plan=core.read_json(b/renderer.PLAN);spec=core.read_json(b/renderer.SPEC);identity['authorization_mode']='PRODUCTION';identity['production_approval_granted']=True
        self.assertRaises(core.Error,f.admit,identity,plan,spec,b/'source.mp4',b,{})
    def test_missing_audio_operation_refused(self):
        b=self.bundles['audio'];timeline=copy.deepcopy(self.manifests['audio']['timeline']);spec=core.read_json(b/renderer.SPEC)
        self.assertRaises(core.Error,core.filter_graph,timeline,False,self.root,spec)
    def test_missing_asset_file_refused(self):b=self.bundles['music'];spec=core.read_json(b/renderer.SPEC);self.assertRaises(core.Error,core.validate_asset,spec['assets']['tone'],self.root/'missing.wav','TEST_ONLY')
    def test_invalid_asset_identity_refused(self):b=self.bundles['music'];record=core.read_json(b/renderer.SPEC)['assets']['tone'];record['sha256']='a'*64;self.assertRaises(core.Error,core.validate_asset,record,b/'asset.wav','TEST_ONLY')
    def test_invalid_asset_rights_refused(self):b=self.bundles['music'];record=core.read_json(b/renderer.SPEC)['assets']['tone'];record['rights']['scope']='PRODUCTION';self.assertRaises(core.Error,core.validate_asset,record,b/'asset.wav','TEST_ONLY')
    def test_invalid_output_resolution_refused(self):b=self.bundles['basic'];g=copy.deepcopy(self.manifests['basic']['timeline']);g['output_settings']['width']=200;self.assertRaises(core.Error,core.verify_output,b/'render.mp4',g,True)
    def test_missing_output_audio_detected(self):b=self.bundles['silent'];g=self.manifests['silent']['timeline'];self.assertRaises(core.Error,core.verify_output,b/'render.mp4',g,True)
    def test_wrong_output_duration_detected(self):b=self.bundles['basic'];g=copy.deepcopy(self.manifests['basic']['timeline']);g['expected_duration_sec']=8;self.assertRaises(core.Error,core.verify_output,b/'render.mp4',g,True)
    def test_corrupt_output_refused(self):p=self.root/'corrupt.mp4';p.write_bytes(b'not an MP4');self.assertRaises(core.Error,core.verify_output,p,self.manifests['basic']['timeline'],True)
    def test_nonzero_source_clock_refused(self):
        p=self.root/'shifted.mp4';core.ffmpeg(['-itsoffset','1','-i',str(self.bundles['basic']/'source.mp4'),'-c','copy',str(p)],self.root,core.DEFAULT_RESOURCES);self.assertRaises(core.Error,core.media_info,p)
    def test_pak_fuad_production_gate_refuses_before_encoding(self):self.production_refusal('pak-fuad','NEEDS_REVIEW')
    def test_showcase_production_gate_refuses_before_encoding(self):self.production_refusal('showcase','BLOCKED')
    def production_refusal(self,name,status):
        b=PROJECT/'data/analyses/director/adaptive-v03'/(name+'.live.v01');before=(b/'editing-plan.v03.json').read_bytes()
        out=core.PRODUCTION_ROOT/(name+'.test-refused');report=self.root/(name+'.rejection.json')
        with patch.object(core,'encode',side_effect=AssertionError('production editing must not start')),patch.object(f,'generate_source',side_effect=AssertionError('no test source route')),contextlib.redirect_stdout(io.StringIO()):
            code=renderer.main(['production','--plan',str(b/'editing-plan.v03.json'),'--packet',str(b/'evidence-packet.v03.json'),'--validation',str(b/'plan-validation.v03.json'),'--output',str(out),'--report',str(report),'--authorization',str(self.bundles['basic']/renderer.IDENTITY)])
        self.assertEqual(code,20);self.assertFalse(out.exists());self.assertEqual((b/'editing-plan.v03.json').read_bytes(),before)
        r=core.read_json(report);self.assertFalse(r['editing_started']);self.assertFalse(r['mp4_created']);self.assertIn('independent_status_'+status,r['reasons']);self.assertIn('synthetic_authorization_cannot_authorize_production',r['reasons'])
    def test_temporary_files_cleaned_after_success(self):self.assertFalse(list(self.root.glob('.stage55-work-*')))
    def test_failure_before_encode_cleans_temporary_files(self):
        out=self.root/'failed'
        with patch.object(core,'encode',side_effect=core.Error('synthetic execution failure')):self.assertRaises(core.Error,renderer.self_test,'basic',out)
        self.assertFalse(out.exists());self.assertFalse(list(self.root.glob('.stage55-work-*')))
    def test_same_engine_cross_strategy_profiles(self):self.assertEqual(self.manifests['captions']['renderer_version'],self.manifests['dynamic']['renderer_version']);self.assertNotEqual(self.manifests['captions']['timeline']['operations'],self.manifests['dynamic']['timeline']['operations'])

    def test_configurable_output_and_resource_settings_real_render(self):
        m=renderer.self_test('basic',self.root/'configured',output_overrides={'width':360,'height':640,'fps':24,'crf':24,'preset':'ultrafast'},resource_overrides={'threads':1})
        self.assertEqual((m['output']['width'],m['output']['height'],m['output']['fps']),(360,640,24))
        self.assertEqual(m['timeline']['resources']['threads'],1)
        self.assertEqual(m['timeline']['output_settings']['crf'],24)
        self.assertEqual(m['render_status'],'TEST_ONLY_COMPLETED')

    def test_decoder_helpers_honor_configured_thread_limits(self):
        calls=[];original=core.base.bounded_run
        def capture(command,*a,**kw):calls.append(command);return original(command,*a,**kw)
        with patch.object(core.base,'bounded_run',side_effect=capture):
            core.frame_rgb(self.bundles['basic']/'render.mp4',1,limits={**core.DEFAULT_RESOURCES,'threads':1})
        cmd=calls[0]
        self.assertEqual(cmd[cmd.index('-threads')+1],'1')
        self.assertEqual(cmd[cmd.index('-filter_threads')+1],'1')
