import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

import numpy as np

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_loot import loot_target,loot_feedback,collect_loot
from autohsr.currency_wars_deployment import bench_face
from autohsr.models import AutomationError,InputInterrupted
from autohsr.tests import test_currency_wars_node as node_helpers
from autohsr.tests.test_currency_wars_node import screen
from autohsr.tests.test_currency_wars_experience import xp

TARGET=(.70,.34,.01)


def reward(visible=True):
    s=xp()
    if visible:
        s.image[463:515,1765:1817]=190
    return s


class LootTests(TestCase):
    def test_native_crystal_bodies_exclude_overlapping_halos_and_pickup_rings(self):
        import cv2
        from pathlib import Path
        from autohsr.currency_wars_node import loot_centers
        root=Path(__file__).parent/'fixtures/currency_crystals'
        for name,count in (('four_blue',4),('gray_blue',4),('blue_after_gray',3),('gold_before_boss',1)):
            scene=reward(False)
            scene.image[330:690,1700:2180]=cv2.imread(str(root/(name+'.png')))
            found=loot_centers(scene)
            self.assertEqual(len(found),count,name)
            if name=='four_blue':
                expected=((2106,530),(1910,463),(1808,457),(1987,392))
                for x,y in expected:
                    self.assertTrue(any(np.hypot(a*2560-x,b*1440-y)<4 for a,b,_ in found))
                # The old Hough target lies between bodies; changing its glow
                # cannot prove that a real crystal was collected.
                self.assertEqual(loot_feedback(scene,scene,(1866/2560,424/1440,25/2560)),'unknown')
            if name=='gold_before_boss':
                from autohsr.currency_wars_node import start_target
                from autohsr.tests.test_currency_wars_node import prepared
                board=prepared()
                board.image[330:690,1700:2180]=scene.image[330:690,1700:2180]
                with self.assertRaisesRegex(AutomationError,'晶矿'):
                    start_target(board)

    def test_empty_bench_and_detected_crystal_required(self):
        s=reward()
        with patch('autohsr.currency_wars_loot.loot_centers',return_value=(TARGET,)):
            self.assertEqual(loot_target(s),TARGET)
            for slot in range(1,10):
                a,b,c,d=bench_face(slot)
                y1,y2=round(b*1440),round(d*1440)
                x1,x2=round(a*2560),round(c*2560)
                s.image[y1:y2,x1:x2]=np.random.default_rng(slot).integers(0,256,(y2-y1,x2-x1,3),dtype=np.uint8)
            with self.assertRaises(AutomationError):
                loot_target(s)
        with patch('autohsr.currency_wars_loot.loot_centers',return_value=()):
            with self.assertRaises(AutomationError):
                loot_target(reward())

    def test_disappearance_also_requires_changed_pixels_and_unchanged_context(self):
        before,after=reward(),reward(False)
        with patch('autohsr.currency_wars_loot.loot_centers',side_effect=lambda s:(TARGET,) if s is before else ()):
            self.assertEqual(loot_feedback(before,after,TARGET),'disappeared')
            self.assertEqual(loot_feedback(before,before,TARGET),'unchanged')
            self.assertEqual(loot_feedback(before,xp(gold=11),TARGET),'unknown')
        self.assertEqual(loot_feedback(before,screen('expert_selection'),TARGET),'choice_opened')
        self.assertEqual(loot_feedback(before,screen('bench_full'),TARGET),'unchanged')

    def test_two_disappearance_observations_follow_one_input(self):
        with tempfile.TemporaryDirectory() as directory:
            before=reward()
            c=node_helpers.NodeWorkflowTests().context(directory,[reward(False),reward(False)])
            c.last_scene=before
            c.currency_collect_loot=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_loot.loot_centers',side_effect=lambda s:(TARGET,) if s is before else ()):
                self.assertTrue(collect_loot(c,before,data,lambda:None))
            c.currency_collect_loot.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'verified')

    def test_overflow_is_pending_cleanup_and_never_a_verified_or_repeated_pickup(self):
        with tempfile.TemporaryDirectory() as directory:
            before=reward()
            c=node_helpers.NodeWorkflowTests().context(directory,[screen('bench_full')])
            c.last_scene=before
            c.currency_collect_loot=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_loot.loot_centers',return_value=(TARGET,)):
                self.assertFalse(collect_loot(c,before,data,lambda:None))
            c.currency_collect_loot.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'overflow_pending')
            self.assertEqual(data['action_status'],'overflow_pending')

    def test_ambiguous_feedback_or_pause_does_not_replay(self):
        for interrupted in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                before=reward()
                c=node_helpers.NodeWorkflowTests().context(directory,[before])
                c.last_scene=before
                c.currency_collect_loot=Mock(side_effect=InputInterrupted('paused') if interrupted else None)
                data=dict(actions=[])
                with patch('autohsr.currency_wars_loot.loot_centers',return_value=(TARGET,)):
                    if interrupted:
                        with self.assertRaises(InputInterrupted):
                            collect_loot(c,before,data,lambda:None)
                        self.assertEqual(data['actions'][0]['status'],'pending')
                    else:
                        with patch('autohsr.currency_wars_loot.time',SimpleNamespace(monotonic=Mock(side_effect=[0,11]))):
                            self.assertFalse(collect_loot(c,before,data,lambda:None))
                c.currency_collect_loot.assert_called_once()

    def test_context_rejects_readonly_operation_and_changed_target(self):
        window=Mock()
        for operation in ('daily','currency_wars','currency_wars_node_test'):
            c=Context(Runner(Settings(),operation=operation),window,Mock())
            c.last_scene=reward()
            with self.assertRaises(AutomationError):
                c.currency_collect_loot(c.last_scene,TARGET)
        window.click.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test'),window,Mock())
        c.last_scene=reward();c.sleep=Mock()
        with patch('autohsr.currency_wars_loot.loot_centers',return_value=(TARGET,)):
            with self.assertRaises(AutomationError):
                c.currency_collect_loot(c.last_scene,(.8,.4,.01))
            c.currency_collect_loot(c.last_scene,TARGET)
        window.click.assert_called_once()
