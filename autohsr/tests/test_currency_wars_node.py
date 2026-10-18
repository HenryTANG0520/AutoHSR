import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_node import run_node, start_target
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted, RunReport, Scene, Token
from autohsr.tests.test_currency_wars_deployment import frame


def prepared():
    s = frame()
    s.tokens = [t for t in s.tokens if not t.within((.43,.18,.55,.26))]
    s.tokens = [t for t in s.tokens if not t.within((.28,.07,.72,.105))]
    s.tokens += [Token('3/3', .99, (.46,.20,.54,.25))]
    s.tokens += [Token('战斗', .99, (.53,.075,.56,.10))]
    return s


def screen(kind, node='1-1'):
    data = json.loads((Path(__file__).parent/'fixtures/currency_wars_pages.json').read_text(encoding='utf-8'))
    tokens = [Token(**t) for t in data['pages'][kind]['tokens']]
    if kind == 'node_result':
        # The result OCR may combine its node with the adjacent battle label.
        tokens = [t for t in tokens if not t.within((.4,.24,.47,.30))]
        tokens += [Token(node+'战斗', .99, (.412,.25,.48,.28))]
    if kind=='battle':
        # Runtime adds a direct node-only OCR token when the progress percent
        # is joined to the node. Workflow unit inputs provide that exact field.
        tokens=[t for t in tokens if not t.within((.30,0,.44,.05))]
        tokens += [Token(node,.99,(.35,.01,.39,.04))]
    return Scene(tokens, captured_at=time.monotonic())


class NodeWorkflowTests(TestCase):
    def test_battle_from_another_node_cannot_verify_the_requested_result(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.context(directory,[prepared(),screen('battle','1-2'),screen('node_result')])
            run_node(c)
            self.assertFalse(c.report.currency_wars['node_verified'])
            self.assertIn('战斗节点',c.report.currency_wars['reason'])
    def context(self, directory, scenes):
        c = SimpleNamespace(settings=Settings(),report=RunReport(run_dir=directory),
            runner=SimpleNamespace(inactive_duration=0,input_epoch=0,emit=Mock()), scene_epoch=0,last_scene=None,
            checkpoint=Mock(),currency_start_node=Mock(),sleep=Mock(),log=Mock())
        sequence = iter(scenes)
        def snapshot():
            value = next(sequence)
            if isinstance(value,Exception):
                c.last_scene = None
                raise value
            c.last_scene = value
            return c.last_scene
        c.snapshot = snapshot
        c.evidence = Mock(side_effect=lambda _,name: Path(directory)/(name+'.png'))
        return c

    def test_preparation_full_capacity_and_frontline_required(self):
        start_target(prepared())
        empty = prepared()
        empty.image[:] = (140,20,10)
        with self.assertRaises(AutomationError):
            start_target(empty)
        with self.assertRaises(AutomationError):
            start_target(frame())
        reward = prepared()
        reward.tokens = [Token('补给',t.score,t.box) if t.text=='战斗' else t for t in reward.tokens]
        with self.assertRaises(AutomationError):
            start_target(reward)

    def test_battle_and_matching_node_result_are_required_not_overall_completion(self):
        for battle_seen, result_id, expected in ((True,'1-1',True),(True,'1-2',False),(False,'1-1',True),(False,'1-2',False)):
            with tempfile.TemporaryDirectory() as directory:
                scenes = [prepared()] + ([screen('battle')] if battle_seen else []) + [screen('node_result',result_id)]
                c = self.context(directory,scenes)
                self.assertEqual(run_node(c).status,'partial')
                c.currency_start_node.assert_called_once()
                data = json.loads((Path(directory)/'currency-node.json').read_text(encoding='utf-8'))
                self.assertEqual(data['node_verified'],expected)
                self.assertTrue(data['start_dispatched'])
                self.assertEqual(data['battle_observed'],battle_seen)
                self.assertFalse(data['completion_verified'])

    def test_known_unexpected_page_or_long_unknown_never_restarts(self):
        for after in (screen('star_selection'), Scene([],captured_at=time.monotonic())):
            with tempfile.TemporaryDirectory() as directory:
                c = self.context(directory,[prepared(),after])
                with patch('autohsr.currency_wars_node.time',SimpleNamespace(monotonic=Mock(side_effect=[0,31]))):
                    run_node(c)
                c.currency_start_node.assert_called_once()
                self.assertFalse(c.report.currency_wars['node_verified'])

    def test_pause_during_start_keeps_pending_and_never_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.context(directory,[prepared()])
            c.currency_start_node.side_effect = InputInterrupted('paused')
            with self.assertRaises(InputInterrupted):
                run_node(c)
            c.currency_start_node.assert_called_once()
            self.assertEqual(json.loads((Path(directory)/'currency-node.json').read_text(encoding='utf-8'))['action_status'],'pending')

    def test_blank_transition_retries_observation_only(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.context(directory,[prepared(),EmptyCapture('black'),screen('battle'),screen('node_result')])
            run_node(c)
            c.currency_start_node.assert_called_once()
            self.assertTrue(c.report.currency_wars['node_verified'])

    def test_already_running_battle_is_observed_without_input(self):
        with tempfile.TemporaryDirectory() as directory:
            battle = screen('battle')
            battle.tokens += [Token('1-1',.99,(.36,0,.39,.045))]
            c = self.context(directory,[battle,screen('node_result')])
            run_node(c)
            c.currency_start_node.assert_not_called()
            self.assertTrue(c.report.currency_wars['node_verified'])
            self.assertEqual(c.report.currency_wars['action'],'observe_existing_battle')

    def test_context_start_is_operation_scoped_and_invalidates_dispatched_scene(self):
        window = Mock()
        for operation in ('daily','currency_wars','currency_wars_deploy_test'):
            ctx = Context(Runner(Settings(),operation=operation),window,Mock())
            with self.assertRaises(AutomationError):
                ctx.currency_start_node(prepared())
        window.click.assert_not_called()
        ctx = Context(Runner(Settings(),operation='currency_wars_node_test'),window,Mock())
        ctx.last_scene = prepared()
        ctx.sleep = Mock()
        ctx.currency_start_node(ctx.last_scene)
        self.assertIsNone(ctx.last_scene)
        window.click.assert_called_once()
