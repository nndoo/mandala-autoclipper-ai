"""Dark scan must inspect every verified frame without implicit frame resampling."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import render_showcase_preview_v01 as preview


class DarkFrameCounts(unittest.TestCase):
    def graph(self):return {'expected_duration_sec':1,'output_settings':{'fps':30,'timing_tolerance_frames':2}}
    def test_verified_two_frame_tolerance_is_scanned_in_full(self):
        with patch.object(preview.core,'run',return_value=(bytes([100])*54*96*32,0)) as run:
            result=preview.black_scan('synthetic',self.graph(),{},decoded_frame_count=32)
        self.assertEqual(result['decoded_frames'],32);self.assertIn('-vsync',run.call_args.args[0])
    def test_black_extra_frame_is_not_dropped(self):
        raw=bytes([100])*54*96*30+bytes(54*96)
        with patch.object(preview.core,'run',return_value=(raw,0)):
            with self.assertRaisesRegex(preview.core.Error,'Near-black'):
                preview.black_scan('synthetic',self.graph(),{},decoded_frame_count=31)
    def test_wrong_decode_count_or_excess_tolerance_is_refused(self):
        for count,proof in ((31,32),(33,33)):
            with patch.object(preview.core,'run',return_value=(bytes([100])*54*96*count,0)):
                with self.assertRaisesRegex(preview.core.Error,'sample count mismatch'):
                    preview.black_scan('synthetic',self.graph(),{},decoded_frame_count=proof)
