import tempfile
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

from autohsr.currency_wars_rewards import reward_choice,reward_action,open_reward_target
from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.models import AutomationError,InputInterrupted,Token,Scene
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import screen,prepared


class RewardTests(TestCase):
    def test_observed_advanced_box_only_selects_calibrated_team_armor(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/currency_wars_advanced_box.json').read_text(encoding='utf-8'))
        scene=Scene([Token(**t) for t in fixture['tokens']])
        self.assertEqual(reward_choice(scene)[0],'advanced_equipment_selection')
        self.assertEqual(reward_choice(scene)[1].text,'很硬的甲')
        scene.tokens=[t for t in scene.tokens if t.text!='很硬的甲']
        with self.assertRaises(AutomationError):
            reward_choice(scene)

    def test_context_dispatches_one_held_click_with_nonblocking_pause_guard(self):
        for pause in (False,True):
            scene=prepared()
            scene.tokens += [Token('开启',.99,(.34,.82,.37,.86))]
            runner=Runner(Settings(),operation='currency_wars_flow_test')
            window=Mock()
            c=Context(runner,window,Mock())
            c.last_scene=scene
            c.sleep=Mock()
            def held(*args,checkpoint):
                if pause:
                    runner._pause.set()
                checkpoint()
            window.click_held.side_effect=held
            if pause:
                with self.assertRaises(InputInterrupted):
                    c.currency_open_reward(scene,3)
            else:
                c.currency_open_reward(scene,3)
            window.click_held.assert_called_once()
            window.click.assert_not_called()
            self.assertIsNone(c.last_scene)

    def test_pause_during_item_hover_cancels_the_click(self):
        scene=prepared()
        scene.tokens += [Token('开启',.99,(.34,.82,.37,.86))]
        runner=Runner(Settings(),operation='currency_wars_flow_test')
        window=Mock()
        c=Context(runner,window,Mock())
        c.last_scene=scene
        c.sleep=Mock(side_effect=lambda _:setattr(runner,'input_epoch',runner.input_epoch+1))
        with self.assertRaises(InputInterrupted):
            c.currency_open_reward(scene,3)
        window.click.assert_not_called()
        window.click_held.assert_not_called()
        self.assertIsNone(c.last_scene)

    def test_observed_equipment_and_cash_amount_are_required(self):
        kind,target=reward_choice(screen('equipment_selection'))
        self.assertEqual((kind,target.text),('equipment_selection','量产型装甲'))
        first=screen('expert_selection')
        self.assertEqual(reward_choice(first)[1].text,'现金为王')
        first.tokens=[t for t in first.tokens if t.text!='4']
        with self.assertRaises(AutomationError):
            reward_choice(first)

    def test_bench_reward_requires_explicit_open_label_in_slot(self):
        scene=prepared()
        with self.assertRaises(AutomationError):
            open_reward_target(scene)
        scene.tokens += [Token('开启',.99,(.34,.82,.37,.86))]
        self.assertEqual(open_reward_target(scene)[0],3)

    def test_cash_is_verified_by_four_gold_gain_and_same_node(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('expert_selection')
            after=prepared()
            after.tokens=[Token('1-6',t.score,t.box) if t.text=='1-1' else t for t in after.tokens
                          if not t.within((.851,.829,.87,.868))]
            after.tokens += [Token('52',.99,(.852,.84,.867,.86))]
            c=helpers.NodeWorkflowTests().context(directory,[after])
            c.last_scene=first
            data=dict(actions=[])
            c.currency_choose_reward=Mock(side_effect=lambda *args:self.assertEqual(data['actions'][-1]['status'],'pending'))
            self.assertTrue(reward_action(c,first,data,lambda:None))
            c.currency_choose_reward.assert_called_once()
            self.assertEqual(data['actions'][-1]['status'],'verified')

    def test_interrupted_selection_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('expert_selection')
            c=helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=first
            c.currency_choose_reward=Mock(side_effect=InputInterrupted('paused'))
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                reward_action(c,first,data,lambda:None)
            c.currency_choose_reward.assert_called_once()
            self.assertEqual(data['actions'][-1]['status'],'pending')
