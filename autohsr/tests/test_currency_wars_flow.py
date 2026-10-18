import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_flow import active_plane, continue_target, run_flow
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted, Scene, Token
from autohsr.tests import test_currency_wars_node as node_helpers
from autohsr.tests.test_currency_wars_node import prepared, screen


class FlowTests(TestCase):
    def test_transient_unknown_is_observed_without_replaying_input(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.context(directory,[Scene([],captured_at=time.monotonic()),screen('environment')])
            run_flow(c)
            c.currency_continue_node.assert_not_called()
            c.currency_start_node.assert_not_called()
            self.assertEqual(c.report.currency_wars['page_kind'],'environment')

    def plane(self, active=(2,)):
        import numpy as np
        s=screen('plane_map')
        s.image=np.zeros((1440,2560,3),dtype=np.uint8)
        for plane in active:
            cx=(.23,.50,.77)[plane-1]
            s.image[round(.39*1440):round(.47*1440),round((cx-.025)*2560):round((cx+.025)*2560)]=(20,190,240)
        return s

    def test_plane_highlight_must_be_unique_and_map_is_advanced_once(self):
        self.assertEqual(active_plane(self.plane()),2)
        for active in ((),(1,2),(2,3)):
            with self.assertRaises(AutomationError):
                active_plane(self.plane(active))
        with tempfile.TemporaryDirectory() as directory:
            c=self.context(directory,[self.plane(),screen('environment'),screen('environment')])
            c.currency_advance_plane=Mock()
            run_flow(c)
            c.currency_advance_plane.assert_called_once()
            c.currency_continue_node.assert_not_called()
            self.assertEqual(c.report.currency_wars['actions'][0]['status'],'verified')

    def test_unready_preparation_requests_decision_without_starting(self):
        with tempfile.TemporaryDirectory() as directory:
            s=prepared()
            s.image[:]=0
            c=self.context(directory,[s])
            self.assertEqual(run_flow(c).status,'partial')
            c.currency_start_node.assert_not_called()
            self.assertEqual(c.report.currency_wars['action_status'],'needs_decision')

    def context(self, directory, scenes):
        c = node_helpers.NodeWorkflowTests().context(directory,scenes)
        def dispatch(scene):
            pending=json.loads((Path(directory)/'currency-flow.json').read_text(encoding='utf-8'))
            self.assertEqual(pending['actions'][-1]['status'],'pending')
            continue_target(scene)
        c.currency_continue_node=Mock(side_effect=dispatch)
        return c

    def test_battle_result_and_transition_are_journaled_without_whole_game_success(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.context(directory,[prepared(),screen('battle'),screen('node_result'),
                screen('node_result'),EmptyCapture('black'),screen('environment'),screen('environment')])
            self.assertEqual(run_flow(c).status,'partial')
            c.currency_start_node.assert_called_once()
            c.currency_continue_node.assert_called_once()
            data=json.loads((Path(directory)/'currency-flow.json').read_text(encoding='utf-8'))
            self.assertTrue(data['actions'][0]['node_verified'])
            self.assertEqual(data['actions'][1]['status'],'verified')
            self.assertEqual(data['page_kind'],'environment')
            self.assertFalse(data['completion_verified'])
            self.assertTrue((Path(directory)/'currency-node-0.json').exists())

    def test_same_result_or_same_node_never_confirms_transition_or_replays(self):
        for after in (screen('node_result'),prepared(),Scene([],captured_at=time.monotonic())):
            with tempfile.TemporaryDirectory() as directory:
                c=self.context(directory,[screen('node_result'),after])
                with patch('autohsr.currency_wars_flow.time',SimpleNamespace(monotonic=Mock(side_effect=[0,0,31]))):
                    run_flow(c)
                c.currency_continue_node.assert_called_once()
                self.assertEqual(c.report.currency_wars['actions'][0]['status'],'unknown')
                self.assertFalse(c.report.currency_wars['completion_verified'])

    def test_unsupported_selection_sends_no_input(self):
        for page in ('bench_full','star_selection'):
            with tempfile.TemporaryDirectory() as directory:
                c=self.context(directory,[screen(page)])
                run_flow(c)
                c.currency_continue_node.assert_not_called()
                c.currency_start_node.assert_not_called()
                self.assertEqual(c.report.currency_wars['action_status'],'needs_decision')

    def test_pause_after_pending_dispatch_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.context(directory,[screen('node_result')])
            c.currency_continue_node.side_effect=InputInterrupted('paused')
            with self.assertRaises(InputInterrupted):
                run_flow(c)
            c.currency_continue_node.assert_called_once()
            data=json.loads((Path(directory)/'currency-flow.json').read_text(encoding='utf-8'))
            self.assertEqual(data['actions'][0]['status'],'pending')

    def test_continue_requires_valid_hp_unique_button_and_scoped_fresh_scene(self):
        result=screen('node_result')
        for tokens in ([t for t in result.tokens if not t.text.startswith('小队生命值')],
                       result.tokens+[Token('继续挑战',.99,(.4,.8,.6,.84))]):
            with self.assertRaises(AutomationError):
                continue_target(Scene(tokens))
        window=Mock()
        for operation in ('daily','currency_wars','currency_wars_node_test'):
            c=Context(Runner(Settings(),operation=operation),window,Mock())
            c.last_scene=result
            with self.assertRaises(AutomationError):
                c.currency_continue_node(result)
        window.click.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test'),window,Mock())
        c.last_scene=result
        c.sleep=Mock()
        c.currency_continue_node(result)
        self.assertIsNone(c.last_scene)
        window.click.assert_called_once()
