import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_supply import supply_choice,supply_options,supply_confirm,choose_supply
from autohsr.models import AutomationError,EmptyCapture,InputInterrupted,Token,Scene
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import screen,prepared


def supply(selected=False):
    import numpy as np
    scene=screen('supply_selection')
    scene.image=np.zeros((1440,2560,3),dtype=np.uint8)
    if selected:
        scene.tokens=[Token(t.text.replace('已选择0/1','已选择1/1'),t.score,t.box) for t in scene.tokens]
        scene.image[round(.59*1440):round(.69*1440),round(.055*2560):round(.205*2560)]=240
    return scene


class SupplyTests(TestCase):
    def test_advanced_supply_supports_observed_archer_and_known_energy_sail(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/currency_wars_supply_plane3.json').read_text(encoding='utf-8'))
        scene=Scene([Token(**t) for t in fixture['tokens']])
        self.assertEqual(supply_choice(scene)[:3],(5,'符玄','蓄能帆'))
        self.assertEqual(supply_options(scene)[3][1],'archer')
        for old,new in (('Archer','Unknown'),('蓄能帆','未知装备')):
            changed=Scene([Token(t.text.replace(old,new),t.score,t.box) for t in scene.tokens])
            with self.assertRaises(AutomationError):
                supply_choice(changed)

    def test_full_pairing_required_and_defensive_default_is_visible_pair(self):
        scene=supply()
        self.assertEqual(supply_choice(scene)[:3],(1,'符玄','量产型装甲'))
        scene.tokens=[t for t in scene.tokens if t.text!='量产型装甲']
        with self.assertRaises(AutomationError):
            supply_choice(scene)
        with self.assertRaises(AutomationError):
            supply_choice(prepared())

    def test_existing_choice_or_changed_pairing_cannot_be_toggled_or_confirmed(self):
        scene=supply()
        expected=tuple(o[:3] for o in supply_options(scene))
        with self.assertRaises(AutomationError):
            supply_confirm(scene,expected)
        supply_confirm(supply(True),expected)
        wrong=supply(True)
        wrong.image[:]=0
        wrong.image[round(.59*1440):round(.69*1440),round(.24*2560):round(.39*2560)]=240
        with self.assertRaises(AutomationError):
            supply_confirm(wrong,expected)
        with self.assertRaises(AutomationError):
            supply_choice(supply(True))
        changed=supply(True)
        changed.tokens=[Token(t.text.replace('符玄','三月七'),t.score,t.box) for t in changed.tokens]
        with self.assertRaises(AutomationError):
            supply_confirm(changed,expected)

    def test_select_and_confirm_have_separate_pending_records_and_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            first=supply()
            c=helpers.NodeWorkflowTests().context(directory,[EmptyCapture('black'),supply(True),prepared()])
            c.last_scene=first
            data=dict(actions=[])
            def persist():
                (Path(directory)/'flow.json').write_text(json.dumps(data),encoding='utf-8')
            def dispatch(scene,expected,choice,confirm=False):
                saved=json.loads((Path(directory)/'flow.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['actions'][-1]['status'],'pending')
                self.assertEqual(choice,(1,'符玄','量产型装甲'))
            c.currency_select_supply=Mock(side_effect=dispatch)
            self.assertTrue(choose_supply(c,first,data,persist))
            self.assertEqual(c.currency_select_supply.call_count,2)
            self.assertEqual([a['status'] for a in data['actions']],['verified','verified'])

    def test_unknown_selection_and_interruption_do_not_confirm_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            first=supply()
            c=helpers.NodeWorkflowTests().context(directory,[supply()])
            c.last_scene=first
            c.currency_select_supply=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_supply.time',SimpleNamespace(monotonic=Mock(side_effect=[0,21]))):
                self.assertFalse(choose_supply(c,first,data,lambda:None))
            c.currency_select_supply.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'unknown')
            c.last_scene=first
            c.currency_select_supply=Mock(side_effect=InputInterrupted('paused'))
            with self.assertRaises(InputInterrupted):
                choose_supply(c,first,dict(actions=[]),lambda:None)
            c.currency_select_supply.assert_called_once()

    def test_scoped_context_checks_fresh_pair_before_dispatch(self):
        scene=supply()
        expected=tuple(o[:3] for o in supply_options(scene))
        choice=supply_choice(scene)[:3]
        window=Mock()
        for operation in ('daily','currency_wars','currency_wars_node_test'):
            c=Context(Runner(Settings(),operation=operation),window,Mock())
            c.last_scene=scene
            with self.assertRaises(AutomationError):
                c.currency_select_supply(scene,expected,choice)
        window.click.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test'),window,Mock())
        c.last_scene=scene
        c.sleep=Mock()
        c.currency_select_supply(scene,expected,choice)
        self.assertIsNone(c.last_scene)
        window.click.assert_called_once()
