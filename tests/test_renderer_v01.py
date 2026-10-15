"""Offline rendering contracts, compiler, hard gates and resource boundaries."""
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
    guard=patch('socket.socket.connect',side_effect=AssertionError('Renderer tests cannot access network'));guard.start()
def tearDownModule():guard.stop()


def fixture(name='basic'):
    d=f.definition(name);shots=d['shots'];first=shots[0]
    hook={k:first[k] for k in ('shot_id','source_start_sec','source_end_sec','timing_precision','evidence_refs')};hook['rationale']='Synthetic opening'
    v={'variant_id':'A','title':'Synthetic','editorial_concept':'Synthetic','intended_message':'TEST ONLY','narrative_strategy':'Explicit',
       'hook':hook,'shots':shots,'estimated_output_duration_sec':round(sum((s['source_end_sec']-s['source_start_sec'])/s['timing']['speed']+s['timing']['freeze_sec']-s['timing']['overlap_sec'] for s in shots),2),
       'operations':d['operations'],'audio_strategy':{'intent':'Explicit','sync_basis':'none','evidence_refs':[]},
       'ending':{'intent':'Explicit','cta':None},'required_reviews':['TEST ONLY']}
    p={'contract_version':'0.3.0','plan_status':'DRAFT_UNVALIDATED','source':{'video_id':'synthetic','duration_sec':6,'width':180,'height':320,'fps':30,'path':'source.mp4','sha256':'a'*64},
       'evidence_packet_sha256':'b'*64,'editorial_concept':'TEST ONLY','intended_message':'TEST ONLY','proposed_variant_count':1,'variants':[v],
       'missing_evidence':[],'required_reviews':['TEST ONLY'],'factual_claims':[],'renderer_capabilities':{'verification_status':'unknown','supported_operations':[]},
       'render_readiness':'BLOCKED_FOR_RENDER','publish_ready':False,'render_approved':False,'publish_approved':False}
    spec={'contract_version':'0.1.0','plan_sha256':core.digest_object(p),'variant_id':'A','output':{**core.DEFAULT_OUTPUT,'width':180,'height':320},
          'resources':dict(core.DEFAULT_RESOURCES),'operation_parameters':d['operation_parameters'],'assets':{}}
    return p,spec


class CompilerTests(unittest.TestCase):
    def setUp(self):self.plan,self.spec=fixture();self.v=self.plan['variants'][0];self.shot=self.v['shots'][0]
    def compile(self):self.spec['plan_sha256']=core.digest_object(self.plan);return core.compile_timeline(self.plan,self.spec)
    def blocked(self):
        with self.assertRaises((core.Error,ValueError,TypeError)):self.compile()
    def test_deterministic_graph(self):self.assertEqual(self.compile(),self.compile())
    def test_reorder_source_mapping(self):g=self.compile();self.assertEqual([(s['source_start_sec'],s['output_start_sec']) for s in g['shots']],[(4,0),(0,2),(2,4)])
    def test_basic_expected_duration(self):self.assertEqual(self.compile()['expected_duration_fraction'],'6')
    def test_explicit_variant_selection(self):self.spec['variant_id']='B';self.blocked()
    def test_variant_count_mismatch(self):self.plan['proposed_variant_count']=2;self.blocked()
    def test_spec_fingerprint_mismatch(self):self.spec['plan_sha256']='c'*64;self.assertRaises(core.Error,core.compile_timeline,self.plan,self.spec)
    def test_hook_source_mismatch(self):self.v['hook']['source_start_sec']=.2;self.blocked()
    def test_negative_time(self):self.shot['source_start_sec']=-1;self.blocked()
    def test_source_time_outside_duration(self):self.shot['source_end_sec']=7;self.blocked()
    def test_zero_shot_duration(self):self.shot['source_start_sec']=self.shot['source_end_sec'];self.v['hook']['source_start_sec']=self.shot['source_start_sec'];self.blocked()
    def test_invalid_speed_below_contract(self):self.shot['timing']['speed']=.7;self.blocked()
    def test_invalid_speed_above_contract(self):self.shot['timing']['speed']=1.3;self.blocked()
    def test_invalid_freeze_duration(self):self.shot['timing']['freeze_sec']=3;self.blocked()
    def test_speed_freeze_crossfade_math(self):self.plan,self.spec=fixture('dynamic');g=self.compile();self.assertEqual(g['expected_duration_fraction'],'31/5');self.assertEqual([s['output_start_sec'] for s in g['shots']],[0,1.7,4])
    def test_freeze_audio_policy(self):self.plan,self.spec=fixture('dynamic');self.assertTrue(all(s['freeze_audio']=='silence' for s in self.compile()['shots']))
    def test_cut_overlap_refused(self):self.shot['timing']['overlap_sec']=.2;self.blocked()
    def test_crossfade_needs_positive_overlap(self):self.shot['timing']['transition_out']='crossfade';self.blocked()
    def test_subframe_freeze_refused(self):self.shot['timing']['freeze_sec']=.001;self.blocked()
    def test_subframe_crossfade_refused(self):self.shot['timing'].update(transition_out='crossfade',overlap_sec=.001);self.blocked()
    def test_source_interval_too_short_for_a_frame(self):self.shot['source_end_sec']=4.005;self.v['hook']['source_end_sec']=4.005;self.v['estimated_output_duration_sec']=4.0;self.blocked()
    def test_final_transition_refused(self):self.v['shots'][-1]['timing'].update(transition_out='crossfade',overlap_sec=.2);self.blocked()
    def test_infeasible_crossfade(self):self.v['shots'][1]['source_end_sec']=.1;self.shot['timing'].update(transition_out='crossfade',overlap_sec=.2);self.blocked()
    def test_order_mismatch(self):self.shot['order']=2;self.blocked()
    def test_duplicate_shot_id(self):self.v['shots'][1]['shot_id']=self.shot['shot_id'];self.blocked()
    def test_incorrect_expected_duration(self):self.v['estimated_output_duration_sec']=5;self.blocked()
    def test_reuse_explicitly_recorded(self):self.v['shots'][1].update(source_start_sec=4,source_end_sec=6);self.assertIn('reuse',self.compile()['required_capabilities'])
    def test_operation_outside_output(self):self.v['operations']=[f.op('x','audio_gain','s1',1,7,{'gain_db':-6})];self.blocked()
    def test_operation_unknown_shot(self):self.v['operations']=[f.op('x','audio_gain','missing',1,2,{'gain_db':-6})];self.blocked()
    def test_duplicate_operation(self):o=f.op('x','audio_gain','s1',0,1,{'gain_db':-6});self.v['operations']=[o,copy.deepcopy(o)];self.blocked()
    def test_unknown_operation(self):self.v['operations']=[f.op('x','danger','s1',0,1,{})];self.blocked()
    def test_unsupported_custom_operation(self):self.v['operations']=[f.op('x','custom','s1',0,1,{'name':'shell','implementation_requirements':'unsafe'})];self.blocked()
    def test_color_prose_not_executable(self):self.v['operations']=[f.op('x','color_grade','s1',0,1,{'intent':'cinematic'})];self.blocked()
    def test_numeric_color_parameters(self):self.plan,self.spec=fixture('dynamic');self.assertIn('color_grade',self.compile()['required_capabilities'])
    def test_orphan_parameters(self):self.spec['operation_parameters']={'missing':{'font_size_px':12}};self.blocked()
    def test_irrelevant_parameters_refused(self):self.v['operations']=[f.op('x','audio_gain','s1',0,1,{'gain_db':-6})];self.spec['operation_parameters']={'x':{'font_size_px':12}};self.blocked()
    def test_false_renderer_support(self):self.v['operations']=[f.op('x','audio_gain','s1',0,1,{'gain_db':-6})];self.v['operations'][0]['capability_status']='supported';self.blocked()
    def test_invalid_crop_bounds(self):self.v['operations']=[f.op('x','crop','s1',0,1,{'x':.7,'y':0,'width':.5,'height':1})];self.blocked()
    def test_crop_below_pixel_resolution(self):self.v['operations']=[f.op('x','crop','s1',0,1,{'x':0,'y':0,'width':.001,'height':1})];self.blocked()
    def test_invalid_zoom_bounds(self):self.v['operations']=[f.op('x','zoom','s1',0,1,{'scale':1.5,'center_x':0,'center_y':.5})];self.blocked()
    def test_placeholder_caption_blocks(self):self.v['operations']=[f.op('x','overlay','s1',0,1,{'caption':f.caption(None),'position':'top'})];self.blocked()
    def test_subtitle_without_source_timing(self):self.v['operations']=[f.op('x','subtitle','s1',0,1,{'caption':f.caption('TEXT'),'position':'bottom'})];self.blocked()
    def test_caption_speed_reorder_mapping(self):self.plan,self.spec=fixture('captions');g=self.compile();self.assertEqual(core.source_window_to_output(g['shots'][2],{'start_sec':3,'end_sec':3.5}),(4.85,5.475))
    def test_caption_wrong_timing_mapping(self):self.plan,self.spec=fixture('captions');self.plan['variants'][0]['operations'][1]['output_start_sec']=4.8;self.blocked()
    def test_unverified_subtitle_blocks(self):self.plan,self.spec=fixture('captions');self.plan['variants'][0]['operations'][1]['parameters']['caption']['verification_status']='unverified';self.blocked()
    def test_caption_source_range_outside_shot(self):self.plan,self.spec=fixture('captions');self.spec['operation_parameters']['sentence']['caption_source_window']['end_sec']=5;self.blocked()
    def test_audio_fade_missing_parameters(self):self.v['operations']=[f.op('x','custom','s1',0,1,{'name':'renderer.audio_fade.v01','implementation_requirements':'fade'})];self.blocked()
    def test_normalization_missing_parameters(self):self.v['operations']=[f.op('x','custom','s1',0,1,{'name':'renderer.normalize.v01','implementation_requirements':'norm'})];self.blocked()
    def test_missing_asset_record(self):self.v['operations']=[f.op('x','music_bed','s1',0,1,{'asset_reference':'missing','gain_db':-6})];self.blocked()
    def test_unused_asset_record(self):self.spec['assets']={'x':{'path':'missing','sha256':'a'*64,'duration_sec':1,'rights':{'scope':'TEST_ONLY','authorized':True,'basis':'test'}}};self.blocked()
    def test_aspect_ratio_fit_explicit(self):self.spec['output']['fit']='stretch';self.blocked()
    def test_odd_dimensions(self):self.spec['output']['width']=181;self.blocked()
    def test_excessive_output_area(self):self.spec['output'].update(width=1920,height=1920);self.blocked()
    def test_thread_bounds(self):self.spec['resources']['threads']=20;self.blocked()
    def test_memory_bounds(self):self.spec['resources']['memory_mib']=8192;self.blocked()
    def test_wall_time_bounds(self):self.spec['resources']['timeout_sec']=1000;self.blocked()
    def test_invalid_freeze_audio_policy(self):self.spec['output']['freeze_audio']='repeat_speech';self.blocked()
    def test_finite_filter_numbers(self):self.assertRaises(core.Error,core.n,float('nan'));self.assertRaises(core.Error,core.n,True)
    def test_nan_timestamps(self):self.shot['source_start_sec']=float('nan');self.blocked()
    def test_inf_timestamps(self):self.shot['source_end_sec']=float('inf');self.blocked()
    def test_compiler_does_not_change_original_plan(self):p=copy.deepcopy(self.plan);self.compile();self.assertEqual(p,self.plan)
    def test_speech_safe_never_certified(self):self.assertFalse(self.compile()['speech_safe_certified'])
    def test_caption_safe_area_size(self):self.assertRaises(core.Error,core.checked_text,'x'*300,24,self.spec['output'])
    def test_caption_control_character(self):self.assertRaises(core.Error,core.checked_text,'x\x00y',12,self.spec['output'])
    def test_caption_secret_rejected(self):self.assertRaises(core.Error,core.checked_text,'sk-SYNTHETIC_TEST_12345',8,self.spec['output'])
    def test_caption_literal_filter_characters_allowed(self):self.assertEqual(core.checked_text("a';[x]",10,self.spec['output']),"a';[x]")


class SafetyTests(unittest.TestCase):
    def setUp(self):
        core.TEST_ROOT.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=core.TEST_ROOT,prefix='unit-test-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_no_overwrite_json(self):p=self.root/'a.json';core.shared.write_json(p,{'first':True});self.assertRaises(core.Error,core.shared.write_json,p,{'second':True})
    def test_json_limit(self):p=self.root/'a.json';p.write_text('x'*(core.MAX_JSON+1));self.assertRaises(core.Error,core.read_json,p)
    def test_duplicate_keys(self):p=self.root/'a.json';p.write_text('{"x":1,"x":2}');self.assertRaises(core.Error,core.read_json,p)
    def test_nonfinite_json(self):p=self.root/'a.json';p.write_text('{"x":NaN}');self.assertRaises(core.Error,core.read_json,p)
    def test_traversal(self):self.assertRaises(core.Error,core.safe_path,self.root/'../outside')
    def test_secret_path_never_read(self):p=self.root/'.env.asr';p.write_text('SYNTHETIC_TEST_VALUE');self.assertRaises(core.Error,core.read_json,p)
    def test_symlink_escape(self):p=self.root/'link';p.symlink_to('/etc/hosts');self.assertRaises(core.Error,core.safe_path,p)
    def test_symlink_inside_project_rejected(self):a=self.root/'a';a.write_text('x');p=self.root/'link';p.symlink_to(a);self.assertRaises(core.Error,core.safe_path,p)
    def test_test_output_cannot_escape_designated_root(self):self.assertRaises(core.Error,core.new_directory,PROJECT/'data/renders/unsafe',core.TEST_ROOT)
    def test_existing_test_directory_rejected(self):self.assertRaises(core.Error,core.new_directory,self.root,core.TEST_ROOT)
    def test_unknown_fixture_rejected(self):self.assertRaises(core.Error,f.definition,'pak-fuad')
    def test_no_force_option(self):
        with contextlib.redirect_stderr(io.StringIO()):self.assertRaises(SystemExit,renderer.main,['self-test','--fixture','basic','--output',str(self.root/'out'),'--force'])
    def test_no_arbitrary_self_test_plan_option(self):
        with contextlib.redirect_stderr(io.StringIO()):self.assertRaises(SystemExit,renderer.main,['self-test','--fixture','basic','--output',str(self.root/'out'),'--plan','real.json'])
    def test_production_low_level_rendering_refused(self):self.assertRaises(core.Error,core.encode,None,None,None,None,{},'PRODUCTION')
    def test_missing_test_admission_refused(self):self.assertRaises(core.Error,core.encode,None,None,None,None,{},'TEST_ONLY')
    def test_disk_preflight(self):
        with patch.object(core.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(100,99,1)):self.assertRaises(core.Error,core.disk_preflight,self.root,core.DEFAULT_RESOURCES)
    def test_prlimit_has_memory_file_cpu_limits(self):command=core.prlimit_command(['ffmpeg'],core.DEFAULT_RESOURCES);self.assertTrue(any(v.startswith('--as=') for v in command));self.assertTrue(any(v.startswith('--fsize=') for v in command));self.assertTrue(any(v.startswith('--cpu=') for v in command))
    def test_allocator_limit_keeps_process_resource_caps(self):
        script='import json,os,resource;print(json.dumps([os.environ.get("MALLOC_ARENA_MAX"),resource.getrlimit(resource.RLIMIT_AS)[0],resource.getrlimit(resource.RLIMIT_FSIZE)[0],resource.getrlimit(resource.RLIMIT_CPU)[0]]))'
        output,_=core.run([sys.executable,'-c',script])
        self.assertEqual(json.loads(output),['2',core.DEFAULT_RESOURCES['memory_mib']*1048576,
                                            core.DEFAULT_RESOURCES['max_output_bytes'],core.DEFAULT_RESOURCES['timeout_sec']+2])
    def test_timeout_reaped(self):
        processes=[];original=core.base.subprocess.Popen
        def tracked(*a,**kw):p=original(*a,**kw);processes.append(p);return p
        with patch.object(core.base.subprocess,'Popen',side_effect=tracked):self.assertRaises(core.Error,core.run,[sys.executable,'-c','import time;time.sleep(10)'],{**core.DEFAULT_RESOURCES,'timeout_sec':.1})
        self.assertIsNotNone(processes[0].poll());self.assertTrue(processes[0].stdout.closed)
    def test_stdout_overflow(self):self.assertRaises(core.Error,core.run,[sys.executable,'-c','print("x"*10000)'],core.DEFAULT_RESOURCES,max_bytes=128)
    def test_real_memory_boundary(self):self.assertRaises(core.Error,core.run,[sys.executable,'-c','x=bytearray(800*1048576);print("unsafe")'],{**core.DEFAULT_RESOURCES,'memory_mib':512})
    def test_failed_subprocess_diagnostics_not_leaked(self):self.assertRaises(core.Error,core.run,[sys.executable,'-c','import sys;sys.stderr.write("TEST_SECRET");raise SystemExit(2)'])
    def test_atomic_binary_publication(self):
        source=self.root/'complete.mp4';source.write_bytes(b'COMPLETE_TEST_FILE');output=self.root/'out';renderer.publish(output,{'render.mp4':source},{'manifest.json':{'complete':True}});self.assertEqual((output/'render.mp4').read_bytes(),source.read_bytes());self.assertTrue((output/'manifest.json').is_file())
    def test_publication_failure_cleanup(self):
        source=self.root/'complete.mp4';source.write_bytes(b'test');output=self.root/'out'
        with patch.object(core.shared,'write_json',side_effect=OSError('synthetic failure')):self.assertRaises(OSError,renderer.publish,output,{'render.mp4':source},{'manifest.json':{}})
        self.assertFalse(output.exists());self.assertFalse(list(self.root.glob('*.tmp')))
    def test_publication_does_not_replace_existing(self):source=self.root/'v';source.write_bytes(b'new');out=self.root/'out';out.mkdir();(out/'keep').write_text('old');self.assertRaises(core.Error,renderer.publish,out,{'render.mp4':source},{});self.assertEqual((out/'keep').read_text(),'old')
    def test_lock_prevents_concurrent_operations(self):
        with renderer.render_lock():
            with self.assertRaises(core.Error):
                with renderer.render_lock():pass
    def test_bad_cli_reports_no_raw_input(self):
        capture=io.StringIO()
        with contextlib.redirect_stderr(capture):code=renderer.main(['production','--plan','missing','--packet','missing','--validation','missing','--output','data/renders/test','--report',str(self.root/'report.json')])
        self.assertEqual(code,1);self.assertNotIn('TEST_SECRET',capture.getvalue())
    def test_manifest_never_grants_production_or_publish(self):
        s=core.base.load_schema('render-manifest.v0.1.schema.json');self.assertEqual(s['properties']['production_approval_granted'],{'const':False});self.assertEqual(s['properties']['publish_approved'],{'const':False})
    def test_filters_cannot_use_untrusted_asset_path(self):
        plan,spec=fixture();timeline=core.compile_timeline(plan,spec)
        with self.assertRaises(core.Error):core.ffmpeg([],self.root/"bad:path",core.DEFAULT_RESOURCES)
