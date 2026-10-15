"""Recovery must preserve historical inference and reject evidence drift."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import stage59_recovery_v01 as recovery
import run_stage59_showcase_v01 as stage


class RecoveryTests(unittest.TestCase):
    def test_only_receipt_locations_can_differ(self):
        historical={'source':{'sha256':'original'},'audio':{'gain':-6},'inputs':{'old':1},'request':{'old':1}}
        current=copy.deepcopy(historical)
        current.update(inputs={'new':2},request={'new':2})
        self.assertEqual(recovery.packet_view(historical),recovery.packet_view(current))
        current['audio']['gain']=0
        self.assertNotEqual(recovery.packet_view(historical),recovery.packet_view(current))
        current=copy.deepcopy(historical);current['source']['sha256']='other'
        self.assertNotEqual(recovery.packet_view(historical),recovery.packet_view(current))

    def test_recovery_refuses_new_paid_director_call(self):
        with patch.object(stage,'load_job',return_value=(None,{'mode':'recovered_historical_inference'},None,None,None)),patch.object(stage.director,'live_response') as call:
            with self.assertRaisesRegex(stage.core.Error,'Director call refused'):
                stage.infer('unused','authorized preview')
            call.assert_not_called()
