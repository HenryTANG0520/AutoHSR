import tempfile
from unittest import TestCase
from unittest.mock import Mock

from autohsr.currency_wars_intro import boss_target,advance_boss
from autohsr.models import AutomationError,EmptyCapture,InputInterrupted
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import screen,prepared


class BossIntroTests(TestCase):
    def test_only_calibrated_intro_provides_continue_target(self):
        scene=screen('boss_intro')
        self.assertEqual(boss_target(scene).text,'点击空白处继续')
        with self.assertRaises(AutomationError):
            boss_target(screen('plane_map'))
        scene.tokens=[t for t in scene.tokens if t.text!='强敌来袭']
        with self.assertRaises(AutomationError):
            boss_target(scene)

    def test_one_action_then_observation_only_until_board(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('boss_intro')
            c=helpers.NodeWorkflowTests().context(directory,[EmptyCapture('black'),prepared()])
            c.last_scene=first
            data=dict(actions=[])
            c.currency_advance_boss=Mock(side_effect=lambda _:self.assertEqual(data['actions'][-1]['status'],'pending'))
            self.assertTrue(advance_boss(c,first,data,lambda:None))
            c.currency_advance_boss.assert_called_once()
            self.assertEqual(data['actions'][-1]['status'],'verified')

    def test_pause_does_not_repeat_or_confirm(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('boss_intro')
            c=helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=first
            c.currency_advance_boss=Mock(side_effect=InputInterrupted('paused'))
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                advance_boss(c,first,data,lambda:None)
            c.currency_advance_boss.assert_called_once()
            self.assertEqual(data['actions'][-1]['status'],'pending')
