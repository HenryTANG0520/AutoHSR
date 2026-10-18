import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_entry import entry_target,overclock_selected,advance_entry
from autohsr.currency_wars_flow import run_flow
from autohsr.models import AutomationError,InputInterrupted,Scene,Token
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import screen


def selected():
    data=json.loads((Path(__file__).parent/'fixtures/currency_wars_overclock_selected.json').read_text(encoding='utf-8'))
    return Scene([Token(**t) for t in data['tokens']],captured_at=time.monotonic())


class EntryTests(TestCase):
    def test_overclock_requires_header_warning_and_enter_button_not_sidebar_name(self):
        self.assertTrue(overclock_selected(selected()))
        self.assertFalse(overclock_selected(screen('mode_select')))
        self.assertEqual(entry_target(screen('mode_select'))[0],'select_overclock')
        self.assertEqual(entry_target(selected())[0],'enter_overclock')
        missing=selected()
        missing.tokens=[t for t in missing.tokens if not t.text.startswith('*无法')]
        self.assertFalse(overclock_selected(missing))

    def test_start_requires_a0_mode_and_exact_lowest_difficulty_effect(self):
        self.assertEqual(entry_target(screen('difficulty_select'))[0],'start_overclock_a0')
        for old,new in [('AO黑铁','A8财富造物主47'),('敌人难度+1','敌人难度+2'),('超频博弈','标准博弈')]:
            s=screen('difficulty_select')
            s.tokens=[Token(new,t.score,t.box) if t.text==old else t for t in s.tokens]
            with self.assertRaises(AutomationError):
                entry_target(s)

    def test_current_match_flow_stops_at_lobby_without_opening_another_match(self):
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[screen('lobby')])
            c.currency_advance_entry=Mock()
            run_flow(c)
            c.currency_advance_entry.assert_not_called()
            self.assertFalse(c.report.currency_wars['start_from_lobby_requested'])

    def test_calibrated_start_chain_journals_every_step_before_input(self):
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[selected(),screen('difficulty_select'),screen('boss_preview'),screen('plane_map')])
            c.runner.currency_start_from_lobby=True
            c.last_scene=screen('lobby')
            data=dict(actions=[],completion_verified=False)
            c.currency_advance_entry=Mock(side_effect=lambda *a:self.assertEqual(data['actions'][-1]['status'],'pending'))
            for _ in range(4):
                self.assertTrue(advance_entry(c,c.last_scene,data,lambda:None))
            self.assertTrue(data['started_from_lobby'])
            self.assertTrue(data['overclock_a0_started'])
            self.assertFalse(data['completion_verified'])
            self.assertEqual([a['status'] for a in data['actions']],['verified']*4)

    def test_unknown_or_interrupted_step_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('lobby')
            c=helpers.NodeWorkflowTests().context(directory,[first])
            c.last_scene=first
            c.runner.currency_start_from_lobby=True
            c.currency_advance_entry=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_entry.time',SimpleNamespace(monotonic=Mock(side_effect=[0,26]))):
                self.assertFalse(advance_entry(c,first,data,lambda:None))
            c.currency_advance_entry.assert_called_once()
            with self.assertRaises(AutomationError):
                advance_entry(c,first,data,lambda:None)
            c.currency_advance_entry.assert_called_once()
            data=dict(actions=[])
            c.currency_advance_entry=Mock(side_effect=InputInterrupted('pause'))
            with self.assertRaises(InputInterrupted):
                advance_entry(c,first,data,lambda:None)
            self.assertEqual(data['actions'][0]['status'],'pending')

    def test_product_input_requires_explicit_flag_flow_scope_and_fresh_scene(self):
        for flag,operation in [(False,'currency_wars_flow_test'),(True,'currency_wars')]:
            w=Mock()
            c=Context(Runner(Settings(),operation=operation,currency_start_from_lobby=flag),w,Mock())
            c.last_scene=screen('lobby')
            with self.assertRaises(AutomationError):
                c.currency_advance_entry(c.last_scene,'open_mode')
            w.click.assert_not_called()
        for flag in (1,'true',None):
            with self.assertRaises(ValueError):
                Runner(Settings(),currency_start_from_lobby=flag)
        w=Mock()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test',currency_start_from_lobby=True),w,Mock())
        c.last_scene=screen('lobby')
        c.last_scene.captured_at=time.monotonic()-9
        with self.assertRaises(AutomationError):
            c.currency_advance_entry(c.last_scene,'open_mode')
        w.click.assert_not_called()
