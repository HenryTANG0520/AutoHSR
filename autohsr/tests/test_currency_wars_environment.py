import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

import numpy as np

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_environment import CENTERS,environment_choice,environment_confirm,choose_environment
from autohsr.models import AutomationError,Scene,Token
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import prepared


def environment(chosen=None):
    data=json.loads((Path(__file__).parent/'fixtures/currency_wars_insurance.json').read_text(encoding='utf-8'))
    s=Scene([Token(**t) for t in data['tokens']],image=np.zeros((1440,2560,3),dtype=np.uint8),captured_at=time.monotonic())
    if chosen is not None:
        cx=CENTERS[chosen]
        s.image[round(.20*1440):round(.79*1440),round((cx-.123)*2560):round((cx-.121)*2560)]=255
        s.image[round(.895*1440):round(.925*1440),round(.50*2560):round(.62*2560)]=255
    return s


class EnvironmentTests(TestCase):
    def test_full_effect_and_correct_unique_selected_card_are_required(self):
        self.assertEqual(environment_choice(environment())[0].text,'人身意外险')
        environment_confirm(environment(0))
        for s in (environment(),environment(1),environment(2)):
            with self.assertRaises(AutomationError):
                environment_confirm(s)
        s=environment()
        s.tokens=[Token(t.text.replace('额外补给','额外战斗'),t.score,t.box) for t in s.tokens]
        with self.assertRaises(AutomationError):
            environment_choice(s)

    def test_different_selection_is_corrected_then_confirmed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            first=environment(1)
            c=helpers.NodeWorkflowTests().context(directory,[environment(0),prepared()])
            c.last_scene=first
            data=dict(actions=[])
            c.currency_select_environment=Mock(side_effect=lambda *a,**k:self.assertEqual(data['actions'][-1]['status'],'pending'))
            self.assertTrue(choose_environment(c,first,data,lambda:None))
            self.assertEqual([a['action'] for a in data['actions']],['select_environment','confirm_environment'])
            self.assertEqual([a['status'] for a in data['actions']],['verified']*2)

    def test_already_selected_card_is_not_toggled_and_unknown_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            first=environment(0)
            c=helpers.NodeWorkflowTests().context(directory,[first])
            c.last_scene=first
            c.currency_select_environment=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_environment.time',SimpleNamespace(monotonic=Mock(side_effect=[0,21]))):
                self.assertFalse(choose_environment(c,first,data,lambda:None))
            c.currency_select_environment.assert_called_once_with(first,confirm=True)
            self.assertEqual(data['actions'][0]['status'],'unknown')
        c=Context(Runner(Settings(),operation='currency_wars'),Mock(),Mock())
        c.last_scene=first
        with self.assertRaises(AutomationError):
            c.currency_select_environment(first,confirm=True)
        c.window.click.assert_not_called()
