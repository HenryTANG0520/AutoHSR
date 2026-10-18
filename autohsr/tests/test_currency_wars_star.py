import json,tempfile,time
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
import numpy as np

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_star import star_choice,star_selected,star_confirm_target,choose_star
from autohsr.models import Scene,Token,AutomationError,InputInterrupted
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import prepared


def star(selected=True):
    fixture=json.loads((Path(__file__).parent/'fixtures/currency_wars_star.json').read_text(encoding='utf-8'))
    s=Scene([Token(**t) for t in fixture['tokens']],image=np.zeros((1440,2560,3),dtype=np.uint8),captured_at=time.monotonic())
    if selected:
        s.image[round(.16*1440):round(.33*1440),round((.545-.059)*2560):round((.545-.056)*2560)]=240
    else:
        s.tokens=[t for t in s.tokens if t.text!='已选择']
    return s


class StarTests(TestCase):
    def test_observed_options_and_selected_card_both_required(self):
        self.assertIn('花火',star_choice(star()).text)
        self.assertTrue(star_selected(star()))
        self.assertFalse(star_selected(star(False)))
        with self.assertRaises(AutomationError):
            star_confirm_target(star(False))
        wrong=star()
        wrong.tokens=[Token('已选择',t.score,(.37,.15,.4,.18)) if t.text=='已选择' else t for t in wrong.tokens]
        self.assertFalse(star_selected(wrong))
        missing=star()
        missing.tokens=[t for t in missing.tokens if '知更鸟女士' not in t.text]
        with self.assertRaises(AutomationError):
            star_choice(missing)

    def test_existing_sparkle_selection_is_confirmed_once_without_toggling(self):
        with tempfile.TemporaryDirectory() as directory:
            first=star()
            after=prepared()
            after.tokens=[Token('3-5',t.score,t.box) if t.text=='1-1' else t for t in after.tokens if not t.within((.851,.829,.87,.868))]
            after.tokens.append(Token('124',.99,(.852,.84,.867,.86)))
            c=helpers.NodeWorkflowTests().context(directory,[after])
            c.last_scene=first
            data=dict(actions=[])
            c.currency_select_star=Mock(side_effect=lambda *a,**kw:self.assertEqual(data['actions'][-1]['status'],'pending'))
            self.assertTrue(choose_star(c,first,data,lambda:None))
            c.currency_select_star.assert_called_once_with(first,confirm=True)
            self.assertEqual(data['actions'][0]['status'],'verified')

    def test_readonly_scope_and_interrupted_confirmation_do_not_send_again(self):
        first=star()
        window=Mock()
        c=Context(Runner(Settings(),operation='currency_wars'),window,Mock())
        c.last_scene=first
        with self.assertRaises(AutomationError):
            c.currency_select_star(first,confirm=True)
        window.click.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=first
            c.currency_select_star=Mock(side_effect=InputInterrupted('pause'))
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                choose_star(c,first,data,lambda:None)
            c.currency_select_star.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'pending')
