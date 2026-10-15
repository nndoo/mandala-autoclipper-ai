"""Adaptive text choice across content profiles; synthetic evidence only."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
import adaptive_text_v01 as text
import adaptive_director_v03_fixtures as f
import renderer_core_v01 as core
import render_test_fixtures_v01 as rf
import test_renderer_v01 as renderer_fixture
import numpy as np


class AdaptiveTextTests(unittest.TestCase):
    def packet_plan(self,speech='absent',music='absent'):
        p=f.packet(speech=speech,music=music);return p,f.plan(p)

    def overlay(self,uid='hook',position='top',start=0,end=2):
        o=f.operation();o['operation_id']=uid;o['parameters']['position']=position
        o['parameters']['caption']['text']='Explore the detail'
        o['output_start_sec']=start;o['output_end_sec']=end
        return o

    def subtitle(self,placeholder=False):
        o=f.operation('subtitle');o['operation_id']='dialogue';o['parameters']['position']='bottom'
        o['parameters']['caption'].update(text=None if placeholder else 'Synthetic spoken text',kind='placeholder' if placeholder else 'asr_draft')
        return o

    def test_no_text_valid_for_dialogue_music_mixed_and_silent(self):
        for speech,music in [('present','absent'),('absent','present'),('present','present'),('absent','absent')]:
            p,plan=self.packet_plan(speech,music)
            self.assertEqual(text.plan_findings(plan['variants'][0],p),[])
            self.assertFalse(f.validator.validate_plan(plan,p)['blocking_findings'])

    def test_music_showcase_overlay_without_subtitle(self):
        p,plan=self.packet_plan(music='present');plan['variants'][0]['operations']=[self.overlay()]
        self.assertEqual(text.plan_findings(plan['variants'][0],p),[])
        self.assertNotEqual(f.validator.validate_plan(plan,p)['status'],'BLOCKED')

    def test_dialogue_can_propose_both_types_independently(self):
        p,plan=self.packet_plan('present');plan['variants'][0]['operations']=[self.overlay(),self.subtitle(True)]
        self.assertEqual(text.plan_findings(plan['variants'][0],p),[])
        self.assertNotEqual(f.validator.validate_plan(plan,p)['status'],'BLOCKED')

    def test_mixed_content_does_not_force_subtitles(self):
        p,plan=self.packet_plan('present','present');plan['variants'][0]['operations']=[self.overlay()]
        self.assertNotEqual(f.validator.validate_plan(plan,p)['status'],'BLOCKED')

    def test_silent_source_spoken_subtitle_rejected(self):
        p,plan=self.packet_plan();plan['variants'][0]['operations']=[self.subtitle()]
        self.assertIn('subtitle_without_classified_speech',[x['code'] for x in text.plan_findings(plan['variants'][0],p)])

    def test_creative_copy_cannot_be_subtitle(self):
        p,plan=self.packet_plan('present');o=self.subtitle();o['parameters']['caption']['kind']='creative_copy'
        plan['variants'][0]['operations']=[o]
        self.assertIn('creative_copy_is_not_speech_subtitle',[x['code'] for x in text.plan_findings(plan['variants'][0],p)])

    def test_asr_quote_cannot_hide_as_creative_overlay(self):
        p,plan=self.packet_plan('present');o=self.overlay();o['parameters']['caption']['kind']='asr_draft'
        plan['variants'][0]['operations']=[o]
        self.assertIn('speech_quote_must_use_subtitle_role',[x['code'] for x in text.plan_findings(plan['variants'][0],p)])

    def test_unsupported_product_claim_still_blocked(self):
        p,plan=self.packet_plan(music='present');o=self.overlay();o['parameters']['caption']['text']='Garansi 5 tahun'
        plan['variants'][0]['operations']=[o]
        self.assertIn('unsupported_copy_claim_or_quote',[x['code'] for x in f.validator.validate_plan(plan,p)['blocking_findings']])

    def test_canonical_confidence_cannot_verify_product_information(self):
        p,plan=self.packet_plan();o=self.overlay();o['parameters']['caption'].update(text='Vehicle information',kind='canonical_unverified')
        plan['variants'][0]['operations']=[o]
        self.assertEqual(f.validator.validate_plan(plan,p)['status'],'BLOCKED')

    def test_same_position_temporal_collision_detected(self):
        p,plan=self.packet_plan();plan['variants'][0]['operations']=[self.overlay('a'),self.overlay('b',start=1,end=3)]
        self.assertIn('text_collision_same_position',[x['code'] for x in text.plan_findings(plan['variants'][0],p)])

    def test_touching_time_windows_do_not_collide(self):
        p,plan=self.packet_plan();plan['variants'][0]['operations']=[self.overlay('a',end=2),self.overlay('b',start=2,end=3)]
        self.assertEqual(text.plan_findings(plan['variants'][0],p),[])

    def test_spatially_separated_concurrent_text(self):
        ops=[]
        for kind,pos in [('overlay','top'),('subtitle','bottom')]:
            ops.append({'effective_kind':kind,'operation_id':kind,'output_start_sec':0,'output_end_sec':2,
                'parameters':{'caption':{'text':'Synthetic'},'position':pos},
                'execution_parameters':{'font_size_px':40,'text_layout':text.SOCIAL_PROFILE}})
        records=text.validate_layout(ops,{'width':1080,'height':1920})
        self.assertEqual({r['text_role'] for r in records},{'speech_subtitle','creative_text_overlay'})

    def test_actual_box_collision_detected(self):
        o={'effective_kind':'overlay','operation_id':'a','output_start_sec':0,'output_end_sec':2,
            'parameters':{'caption':{'text':'Synthetic'},'position':'top'},'execution_parameters':{'font_size_px':40}}
        b=copy.deepcopy(o);b['operation_id']='b'
        with self.assertRaises(ValueError):text.validate_layout([o,b],{'width':1080,'height':1920})

    def test_social_profile_reserves_bottom_and_right(self):
        b=text.box('Synthetic',40,1080,1920,'bottom',text.SOCIAL_PROFILE)
        self.assertLessEqual(b[2],1080*.82+4);self.assertLessEqual(b[3],1920*.78+4)
        self.assertGreaterEqual(b[0],1080*.08-4)

    def test_social_profile_oversized_text_rejected(self):
        with self.assertRaises(ValueError):text.box('x'*40,40,1080,1920,'top',text.SOCIAL_PROFILE)

    def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):text.box('Synthetic',12,180,320,'top','invented')

    def test_ffmpeg_social_profile_has_explicit_coordinates(self):
        x,y=text.ffmpeg_position('bottom',1080,1920,text.SOCIAL_PROFILE)
        self.assertIn('0.74',x);self.assertEqual(y,'1920*0.78-text_h-4')

    def test_legacy_coordinates_remain_stable(self):
        self.assertEqual(text.ffmpeg_position('bottom',180,320),('(w-text_w)/2','h-text_h-320*0.12'))

    def test_renderer_rejects_text_collision(self):
        plan,spec=renderer_fixture.fixture('captions');op=copy.deepcopy(plan['variants'][0]['operations'][0])
        op['operation_id']='duplicate';plan['variants'][0]['operations'].append(op)
        spec['plan_sha256']=core.digest_object(plan)
        with self.assertRaisesRegex(core.Error,'collision'):core.compile_timeline(plan,spec)

    def test_renderer_compiles_social_profile_with_separate_roles(self):
        plan,spec=renderer_fixture.fixture('captions')
        spec['operation_parameters']['hook']['text_layout']=text.SOCIAL_PROFILE
        spec['operation_parameters']['sentence']['text_layout']=text.SOCIAL_PROFILE
        timeline=core.compile_timeline(plan,spec)
        self.assertEqual({r['text_role'] for r in timeline['text_layout_checks']},{'speech_subtitle','creative_text_overlay'})
        with tempfile.TemporaryDirectory(dir=ROOT/'data',prefix='text-graph-') as tmp:
            graph,_,_,_=core.filter_graph(timeline,True,Path(tmp),spec)
            self.assertIn('180*0.74-text_w',graph);self.assertIn('320*0.78-text_h',graph)
            self.assertIn('expansion=none',graph)

    def test_shared_validator_rejects_collision(self):
        p,plan=self.packet_plan();plan['variants'][0]['operations']=[self.overlay('a'),self.overlay('b')]
        self.assertIn('adaptive_text:text_collision_same_position',
            [x['code'] for x in f.validator.validate_plan(plan,p)['blocking_findings']])

    def test_ffmpeg_social_profile_burnin_timing_and_reserved_ui_space(self):
        plan,spec=renderer_fixture.fixture('captions')
        for name in ('hook','sentence'):spec['operation_parameters'][name]['text_layout']=text.SOCIAL_PROFILE
        timeline=core.compile_timeline(plan,spec)
        with tempfile.TemporaryDirectory(dir=ROOT/'data',prefix='text-pixels-') as tmp:
            graph,_,_,_=core.filter_graph(timeline,False,Path(tmp),spec)
            def frame(time):
                raw,_=core.run(['ffmpeg','-v','error','-nostdin','-threads','1','-filter_threads','1',
                    '-filter_complex_threads','1','-f','lavfi','-i','color=c=red:s=180x320:r=30:d=6',
                    '-filter_complex',graph,'-map','[vout]','-ss',str(time),'-frames:v','1','-pix_fmt','rgb24',
                    '-f','rawvideo','pipe:1'],spec['resources'],max_bytes=180*320*3)
                return np.frombuffer(raw,dtype=np.uint8).reshape(320,180,3).astype(float)
            before=frame(.1);hook=frame(.8);subtitle=frame(5.1)
            self.assertGreater(np.mean(np.abs(hook[25:65]-before[25:65])),1)
            self.assertGreater(np.mean(np.abs(subtitle[220:250]-before[220:250])),1)
            self.assertLess(np.max(np.abs(hook[:,150:]-before[:,150:])),1)
            self.assertLess(np.max(np.abs(subtitle[251:]-before[251:])),1)


if __name__=='__main__':unittest.main()
