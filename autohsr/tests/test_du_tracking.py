import json,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2

from autohsr.models import Scene,Token
from autohsr.du_tracking import track_gate,recent_gate


class DuGateTrackingTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).parent/'fixtures/du_runtime'
        self.reference=cv2.imread(str(root/'gate_tracking_reference.png'))
        self.occluded=cv2.imread(str(root/'gate_tracking_occluded.png'))
        self.wrong=cv2.imread(str(root/'gate_tracking_wrong_view.png'))
        box=json.loads((root/'gate_tracking_reference.json').read_text('utf8'))['box']
        self.target=Token('Target',.745,tuple(box))

    def test_native_gate_tracks_through_avatar_occlusion_but_not_a_different_view(self):
        result=track_gate(self.reference,self.occluded,self.target)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.center[0],.475,delta=.02)
        self.assertAlmostEqual(result.center[1],.423,delta=.02)
        self.assertIsNone(track_gate(self.reference,self.wrong,self.target))
        self.assertIsNone(track_gate(self.reference,self.occluded*0,self.target))

    def test_recent_gate_requires_same_room_geometry_and_bounded_age(self):
        header=Token('(1/13) 第一位面-战斗',.99,(.02,.01,.25,.04))
        original=Scene([header],self.reference,geometry='same')
        current=Scene([header],self.occluded,geometry='same')
        context=SimpleNamespace(_du_gate_reference=(original,self.target,100))
        with patch('autohsr.du_tracking.time.monotonic',return_value=105):
            self.assertIsNotNone(recent_gate(context,current))
            current.geometry='different';self.assertIsNone(recent_gate(context,current))
            current.geometry='same'
            current.tokens=[Token('(2/13) 第一位面-战斗',.99,header.box)]
            self.assertIsNone(recent_gate(context,current))
            current.tokens=[];self.assertIsNone(recent_gate(context,current))
        with patch('autohsr.du_tracking.time.monotonic',return_value=113):
            self.assertIsNone(recent_gate(context,Scene([header],self.occluded,geometry='same')))
