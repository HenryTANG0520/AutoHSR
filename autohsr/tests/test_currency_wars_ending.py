import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_ending import ENDING_STEPS,ending_target,advance_ending
from autohsr.currency_wars_node import run_node
from autohsr.models import AutomationError,InputInterrupted,Token
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import screen,prepared


class EndingTests(TestCase):
    def test_four_observed_steps_have_distinct_targets_and_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('final_victory')
            c=helpers.NodeWorkflowTests().context(directory,[screen(k) for k in ('match_rating','match_summary','match_statistics','lobby')])
            c.last_scene=first
            data=dict(actions=[],completion_verified=False,gameplay_enabled=False)
            c.currency_advance_ending=Mock(side_effect=lambda *a:self.assertEqual(data['actions'][-1]['status'],'pending'))
            for kind in ENDING_STEPS:
                self.assertEqual(ending_target(c.last_scene)[0],kind)
                self.assertTrue(advance_ending(c,c.last_scene,data,lambda:None))
            self.assertEqual(c.currency_advance_ending.call_count,4)
            self.assertTrue(data['settlement_verified'])
            self.assertTrue(data['match_victory_observed'])
            self.assertFalse(data['completion_verified'])
            self.assertEqual([a['status'] for a in data['actions']],['verified']*4)

    def test_starting_at_statistics_only_proves_return_not_match_victory_or_full_run(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('match_statistics')
            c=helpers.NodeWorkflowTests().context(directory,[screen('lobby')])
            c.last_scene=first
            c.currency_advance_ending=Mock()
            data=dict(actions=[],completion_verified=False)
            self.assertTrue(advance_ending(c,first,data,lambda:None))
            self.assertNotIn('match_victory_observed',data)
            self.assertFalse(data['completion_verified'])

    def test_unknown_transition_never_repeats_the_terminal_click(self):
        with tempfile.TemporaryDirectory() as directory:
            first=screen('final_victory')
            c=helpers.NodeWorkflowTests().context(directory,[prepared()])
            c.last_scene=first
            c.currency_advance_ending=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_ending.time',SimpleNamespace(monotonic=Mock(side_effect=[0,21]))):
                self.assertFalse(advance_ending(c,first,data,lambda:None))
            c.currency_advance_ending.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'unknown')

    def test_readonly_scope_and_interruption_preserve_pending_intent(self):
        first=screen('match_statistics')
        window=Mock()
        c=Context(Runner(Settings(),operation='currency_wars'),window,Mock())
        c.last_scene=first
        with self.assertRaises(AutomationError):
            c.currency_advance_ending(first,'match_statistics')
        window.click.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=first
            c.currency_advance_ending=Mock(side_effect=InputInterrupted('pause'))
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                advance_ending(c,first,data,lambda:None)
            self.assertEqual(data['actions'][0]['status'],'pending')

    def test_final_boss_victory_requires_matching_battle_node_and_remains_partial(self):
        first=prepared()
        first.tokens=[Token('3-5',t.score,t.box) if t.text=='1-1' else t for t in first.tokens]
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[first,screen('battle','3-5'),screen('final_victory')])
            run_node(c)
            self.assertTrue(c.report.currency_wars['node_verified'])
            self.assertTrue(c.report.currency_wars['final_victory'])
            self.assertFalse(c.report.currency_wars['completion_verified'])
