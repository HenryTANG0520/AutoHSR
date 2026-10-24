import unittest
from unittest.mock import Mock,patch
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_events import action, reward_bundle_size
from autohsr.models import AutomationError, RunReport, Scene, Token


class RewardQueueTests(unittest.TestCase):
    @staticmethod
    def fixture(name):
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture(name)

    def flow(self):
        return DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)

    def test_changed_native_item_quantity_is_a_new_layer(self):
        before=self.fixture('reward_items_fifty');after=self.fixture('reward_items_twenty')
        flow=self.flow();flow._click=Mock(return_value=(after,'tutorial_overlay'))
        self.assertEqual(flow._close_tutorial(before),(after,'tutorial_overlay'))
        flow._click.assert_called_once()

    def test_native_five_reward_choice_supplies_bounded_close_allowance(self):
        page=self.fixture('event_five_reward_confirm')
        target,intent=action(page)
        self.assertEqual(intent,'event_star_confirm')
        self.assertEqual(reward_bundle_size(page,target,intent),5)
        self.assertEqual(reward_bundle_size(page,target,'event_star_select'),0)
        star=Token('差分宇宙事件选项',.99,(.70,.3,.72,.32))
        with patch('autohsr.du_events.action',return_value=(target,intent)), \
             patch('autohsr.du_events.preferred_option',return_value=star), \
             patch('autohsr.du_events.option_stars',return_value=[star]):
            for body,expected in (('获得0-10次随机奖励驶出冥滩',10),
                    ('获得1次随机奖励',1),('获得20次随机奖励',20),
                    ('获得21次随机奖励',0),('获得10-5次随机奖励',0),('奖励次数未知',0)):
                with self.subTest(body=body),patch('autohsr.du_events.description',return_value=body):
                    self.assertEqual(reward_bundle_size(page,target,intent),expected)

    def test_five_identical_receipts_can_close_but_unresponsive_bundle_is_bounded(self):
        receipt=self.fixture('reward_items_twenty');done=Scene([])
        flow=self.flow();flow._reward_overlay_budget=15
        flow._click=Mock(side_effect=[(receipt,'tutorial_overlay')]*4+[(done,'field_reward')])
        flow._snapshot=Mock(return_value=(receipt,'tutorial_overlay'))
        self.assertEqual(flow._close_tutorial(receipt),(done,'field_reward'))
        self.assertEqual(flow._click.call_count,5)
        flow=self.flow();flow._reward_overlay_budget=15
        flow._click=Mock(return_value=(receipt,'tutorial_overlay'))
        flow._snapshot=Mock(return_value=(receipt,'tutorial_overlay'))
        with self.assertRaisesRegex(AutomationError,'15次实时关闭提示'):
            flow._close_tutorial(receipt)
        self.assertEqual(flow._click.call_count,15)
        self.assertEqual(flow._reward_overlay_budget,0)

    def test_unknown_unchanged_receipt_still_stops_after_three_inputs(self):
        receipt=self.fixture('reward_items_twenty');flow=self.flow()
        flow._click=Mock(return_value=(receipt,'tutorial_overlay'))
        flow._snapshot=Mock(return_value=(receipt,'tutorial_overlay'))
        with self.assertRaisesRegex(AutomationError,'三次实时关闭提示'):
            flow._close_tutorial(receipt)
        self.assertEqual(flow._click.call_count,3)
