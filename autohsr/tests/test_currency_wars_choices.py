import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

import numpy as np

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_choices import investment_choice,investment_confirm,choose_investment
from autohsr.currency_wars_node import start_target
from autohsr.models import AutomationError,EmptyCapture,InputInterrupted,Scene,Token
from autohsr.tests import test_currency_wars_node as node_helpers
from autohsr.tests.test_currency_wars_node import prepared,screen


def investment(selected=False):
    s=screen('investment_selection')
    s.image=np.zeros((1440,2560,3),dtype=np.uint8)
    if selected:
        s.image[round(.892*1440):round(.925*1440),round(.43*2560):round(.57*2560)]=240
        title=investment_choice(s)[1]
        cx=min((.24,.50,.76),key=lambda value:abs(value-title.center[0]))
        s.image[round(.198*1440):round(.722*1440),round((cx-.106)*2560):round((cx-.103)*2560)]=240
    return s


class InvestmentTests(TestCase):
    def test_plane_three_observed_defensive_effect_requires_complete_numbers_and_reward(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/currency_wars_investment_plane3.json').read_text(encoding='utf-8'))
        s=Scene([Token(**t) for t in fixture['tokens']])
        self.assertEqual(investment_choice(s)[0],'保守派')
        original=s.tokens
        for old,new in (('8%','80%'),('12%','21%'),('进阶武装箱','简易武装箱'),('保守派','未知策略')):
            s.tokens=[Token(t.text.replace(old,new),t.score,t.box) for t in original]
            with self.subTest(changed=old),self.assertRaises(AutomationError):
                investment_choice(s)

    def test_observed_effect_and_name_both_required_with_known_fallback(self):
        self.assertEqual(investment_choice(investment())[0],'爆仓')
        s=investment()
        s.tokens=[Token(t.text.replace('16%','15%'),t.score,t.box) for t in s.tokens]
        self.assertEqual(investment_choice(s)[0],'延迟收益')
        s.tokens=[Token(t.text.replace('40%','80%'),t.score,t.box) for t in s.tokens]
        with self.assertRaises(AutomationError):
            investment_choice(s)
        with self.assertRaises(AutomationError):
            investment_choice(screen('preparation'))

    def test_confirm_requires_enabled_button_and_expected_choice(self):
        with self.assertRaises(AutomationError):
            investment_confirm(investment(),'爆仓')
        investment_confirm(investment(True),'爆仓')
        wrong=investment(True)
        wrong.image[round(.198*1440):round(.722*1440)]=0
        wrong.image[round(.198*1440):round(.722*1440),round((.76-.106)*2560):round((.76-.103)*2560)]=240
        with self.assertRaises(AutomationError):
            investment_confirm(wrong,'爆仓')
        with self.assertRaises(AutomationError):
            investment_confirm(investment(True),'延迟收益')

    def test_each_input_has_pending_intent_and_feedback_before_next_input(self):
        with tempfile.TemporaryDirectory() as directory:
            first=investment()
            c=node_helpers.NodeWorkflowTests().context(directory,[EmptyCapture('black'),investment(True),prepared()])
            c.last_scene=first
            data=dict(actions=[])
            def persist():
                (Path(directory)/'flow.json').write_text(json.dumps(data),encoding='utf-8')
            def dispatch(scene,name,confirm=False):
                saved=json.loads((Path(directory)/'flow.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['actions'][-1]['status'],'pending')
                self.assertEqual(name,'爆仓')
            c.currency_select_investment=Mock(side_effect=dispatch)
            self.assertTrue(choose_investment(c,first,data,persist))
            self.assertEqual(c.currency_select_investment.call_count,2)
            self.assertEqual([a['status'] for a in data['actions']],['verified','verified'])

    def test_ambiguous_selection_does_not_confirm_or_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            first=investment()
            c=node_helpers.NodeWorkflowTests().context(directory,[investment()])
            c.last_scene=first
            c.currency_select_investment=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_choices.time',SimpleNamespace(monotonic=Mock(side_effect=[0,21]))):
                self.assertFalse(choose_investment(c,first,data,lambda:None))
            c.currency_select_investment.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'unknown')

    def test_hint_and_loot_prevent_starting_under_an_unready_screen(self):
        s=prepared()
        s.tokens += [Token('请选择投资策略',.99,(.44,.44,.56,.5))]
        with self.assertRaises(AutomationError):
            start_target(s)
        with patch('autohsr.currency_wars_node.loot_centers',return_value=((.77,.38,.02),)):
            with self.assertRaises(AutomationError):
                start_target(prepared())

    def test_context_choice_is_scoped_and_pending_interruption_never_confirms(self):
        window=Mock()
        s=investment()
        for operation in ('daily','currency_wars','currency_wars_node_test'):
            c=Context(Runner(Settings(),operation=operation),window,Mock())
            c.last_scene=s
            with self.assertRaises(AutomationError):
                c.currency_select_investment(s,'爆仓')
        window.click.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test'),window,Mock())
        c.last_scene=s
        c.sleep=Mock()
        c.currency_select_investment(s,'爆仓')
        self.assertIsNone(c.last_scene)
        window.click.assert_called_once()
        with tempfile.TemporaryDirectory() as directory:
            c=node_helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=s
            c.currency_select_investment=Mock(side_effect=InputInterrupted('paused'))
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                choose_investment(c,s,data,lambda:None)
            self.assertEqual(data['actions'][0]['status'],'pending')
