"""Independent guards for AI-selected creative treatment; synthetic plans only."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
import adaptive_text_v01 as text
import renderer_core_v01 as core
import run_revision_loop_v01 as loop
import test_renderer_v01 as fixtures
from test_revision_loop_v01 import sample

STYLE={'font':'dejavu_sans_bold','color':'#FFE040','outline_color':'#000000','outline_width_px':2,'shadow':True}
FADE={'enter':'fade','exit':'fade','enter_duration_sec':.2,'exit_duration_sec':.2}


class CreativeTextTests(unittest.TestCase):
    def spec(self):
        plan,spec=fixtures.fixture('captions')
        spec['operation_parameters']['hook'].update(text_style=copy.deepcopy(STYLE),text_animation=copy.deepcopy(FADE))
        return plan,spec

    def test_schema_blocks_filter_and_font_path_injection(self):
        for field,value in [('color','white:enable=1'),('font','/tmp/font.ttf')]:
            plan,spec=self.spec();spec['operation_parameters']['hook']['text_style'][field]=value
            with self.assertRaises(core.Error):core.compile_timeline(plan,spec)

    def test_invalid_fade_and_no_hold_refused(self):
        for enter,exit,duration in [('none','fade',.2),('fade','fade',.05)]:
            with self.assertRaises(ValueError):text.validate_treatment({'text_animation':{'enter':enter,'exit':exit,'enter_duration_sec':.2,'exit_duration_sec':.2}},duration)

    def test_treatment_requires_separate_verified_capabilities(self):
        plan,spec=self.spec();timeline=core.compile_timeline(plan,spec)
        self.assertIn('text_animation',timeline['required_capabilities']);self.assertIn('text_style',timeline['required_capabilities'])
        self.assertIn(':alpha=',text.ffmpeg_treatment(spec['operation_parameters']['hook'],.2,1.4))

    def test_creative_directive_requires_populated_overlay(self):
        packet,parent,brief,proposal,spec,registry=sample()
        brief['inputs']['creative_directive']={'path':'data/synthetic-directive.json','sha256':'a'*64}
        proposal['brief_sha256']=core.digest_object(brief)
        keys=['hook','shot_selection','pacing','transitions','effects','creative_text','branding','ending_cta']
        proposal['creative_decisions']={k:'Synthetic decision' for k in keys}
        proposal['creative_decisions']['text_evaluation']={'needed':True,'reason':'Synthetic promotion','evidence_refs':['canonical.segments.0']}
        with patch.object(loop.qa,'same_reference'),patch.object(loop.qa,'read',return_value={'require_visible_overlay':True}),patch.object(loop.audio,'validate_source_audio'):
            result=loop.validate_proposal(proposal,brief,packet,parent,spec,registry)
        self.assertIn('creative_overlay_required',result['blocking_reasons'])

    def test_unverified_product_quality_copy_blocked(self):
        packet,parent,_,_,_,_=sample()
        import adaptive_director_v03_fixtures as plan_fixture
        op=plan_fixture.operation();op['parameters']['caption']['text']='Pilihan Unit Terbaik'
        parent['variants'][0]['operations']=[op]
        result=loop.validator.validate_plan(parent,packet)
        self.assertTrue(result['blocking_findings'])

    def test_reframing_only_conflicts_with_concurrent_preceding_text(self):
        import adaptive_director_v03_fixtures as plan_fixture
        for start,conflict in ((3,False),(1,True)):
            packet,parent,brief,proposal,spec,registry=sample()
            brief['inputs']['creative_directive']={'path':'data/synthetic-directive.json','sha256':'a'*64}
            proposal['brief_sha256']=core.digest_object(brief)
            overlay=plan_fixture.operation();overlay['output_start_sec']=.2;overlay['output_end_sec']=2
            zoom=plan_fixture.operation('zoom');zoom.update(operation_id='zoom-test',output_start_sec=start,output_end_sec=start+2,parameters={'scale':1.2,'center_x':.5,'center_y':.5})
            proposal['plan']['variants'][0]['operations']=[overlay,zoom]
            proposal['operation_parameters']={overlay['operation_id']:{'font_size_px':36,'text_style':STYLE,'text_animation':FADE}}
            keys=['hook','shot_selection','pacing','transitions','effects','creative_text','branding','ending_cta']
            proposal['creative_decisions']={k:'Synthetic decision' for k in keys}
            proposal['creative_decisions']['text_evaluation']={'needed':True,'reason':'Synthetic promotion','evidence_refs':['canonical.segments.0']}
            with patch.object(loop.qa,'same_reference'),patch.object(loop.qa,'read',return_value={'require_visible_overlay':True}),patch.object(loop.audio,'validate_source_audio'):
                result=loop.validate_proposal(proposal,brief,packet,parent,spec,registry)
            self.assertEqual('visual_reframe_after_text' in result['blocking_reasons'],conflict)

    def test_legacy_static_treatment_unchanged(self):
        self.assertEqual(text.ffmpeg_treatment({},0,2),'fontcolor=white:borderw=2:bordercolor=black:shadowx=1:shadowy=1')
