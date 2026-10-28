"""Behavioral contracts for result continuation, settlement and interrupted IO."""
import tempfile
import re
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_node import result_node
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard, transition_ready
from autohsr.currency_wars_standard_node import observe_started_node
from autohsr.currency_wars_standard_progress import progress_verified
from autohsr.models import AutomationError, InputInterrupted, Token
from autohsr.tests import test_currency_wars_flow as flow_helpers
from autohsr.tests import test_currency_wars_standard_flow as standard_helpers
from autohsr.tests import test_currency_wars_standard_node as node_helpers
from autohsr.tests.test_currency_wars_node import prepared, screen
from autohsr.tests.test_currency_wars_standard_node import current


def board(node):
    scene = prepared()
    scene.tokens = [t for t in scene.tokens if not (t.within((.1,.04,.29,.13)) and re.fullmatch(r'[1-3]-[0-9]+',t.text))]
    scene.tokens.append(Token(node, .99, (.23,.055,.26,.085)))
    return scene


class StandardProgressTests(unittest.TestCase):
    def store(self, folder, node='1-1', *, observed=True):
        store = standard_helpers.StandardFlowTests().store(folder)
        store.data.update(status='active', start_verified=True)
        action = store.pending('start_standard_node', 0, 'before.png', 'standard_node_entered')
        action.update(status='verified', target=[node, 5, 80, 3])
        store.data['node_attempt'] = dict(node=node, start_action_id=0, status='verified' if observed else 'observing',
                                        node_verified=observed, result='result.png' if observed else '', result_kind='node_result')
        store.persist()
        return store

    def persist_choice(self, store, choice):
        action = store.pending(choice.intent, 0, 'before.png', choice.expected)
        action['target'] = list(choice.payload)
        store.persist()
        return action

    def test_result_continues_once_from_verified_start_and_rederives_exact_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            scene = current('node_result')
            choice = next_action(scene, session=store.data)
            self.assertEqual(choice.intent, 'continue_standard_node')
            action = self.persist_choice(store, choice)
            self.assertEqual(next_action(scene, session=store.data), choice)
            c = Context(Runner(Settings(), operation='currency_wars_standard'), Mock(), Mock())
            c.last_scene, c.currency_standard_session = scene, store
            c.checkpoint, c.sleep = Mock(), Mock()
            c.currency_standard_input(scene, choice)
            c.window.click.assert_called_once()
            self.assertIsNone(c.last_scene)
            self.assertFalse(store.data['completion_verified'])
            action['status'] = 'verified'
            progress_verified(store.data, choice, board('1-2'))
            with self.assertRaises(AutomationError):
                next_action(scene, session=store.data)
            self.assertEqual(store.data['node_history'][0]['node'], '1-1')

    def test_missing_provenance_wrong_node_or_unknown_previous_action_blocks_continue(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            original = deepcopy(store.data)
            for mutation in ('node', 'result', 'start', 'unknown', 'status'):
                data = deepcopy(original)
                if mutation == 'node':
                    data['node_attempt']['node'] = '1-2'
                elif mutation == 'result':
                    data['node_attempt']['node_verified'] = False
                elif mutation == 'start':
                    data['node_attempt']['start_action_id'] = 99
                elif mutation == 'unknown':
                    data['actions'][-1]['status'] = 'unknown'
                else:
                    data['status'] = 'start_pending'
                with self.subTest(mutation=mutation), self.assertRaises(AutomationError):
                    next_action(current('node_result'), session=data)

    def test_successor_must_be_exact_or_the_next_uniquely_highlighted_plane(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder, '1-6')
            choice = next_action(current('node_result', '1-6'), session=store.data)
            self.assertTrue(transition_ready(choice, board('1-7')))
            self.assertTrue(transition_ready(choice, flow_helpers.FlowTests().plane((2,))))
            for scene in (board('1-6'), board('1-8'), board('2-1'), flow_helpers.FlowTests().plane((3,)),
                          flow_helpers.FlowTests().plane((1,2)), screen('environment')):
                self.assertFalse(transition_ready(choice, scene))
            action = self.persist_choice(store, choice)
            action['status'] = 'verified'
            progress_verified(store.data, choice, flow_helpers.FlowTests().plane((2,)))
            onward = next_action(flow_helpers.FlowTests().plane((2,)), session=store.data)
            self.assertEqual(onward.intent, 'advance_standard_next_plane')
            self.assertEqual(onward.payload[2], '2-1')
            self.persist_choice(store, onward)
            self.assertEqual(next_action(flow_helpers.FlowTests().plane((2,)), session=store.data), onward)
            with self.assertRaises(AutomationError):
                next_action(flow_helpers.FlowTests().plane((3,)), session=store.data)

    def test_transient_unreadable_battle_is_observed_again_without_input(self):
        with tempfile.TemporaryDirectory() as folder:
            store = node_helpers.StandardNodeTests().store(folder)
            unknown = current('battle')
            unknown.field_reads['currency_battle_node.normal'] = (None, None)
            c = node_helpers.StandardNodeTests().context([unknown, current('battle'), current('node_result')])
            with patch('autohsr.currency_wars_replay.save_sample'):
                _, verified = observe_started_node(c, store, c.snapshot())
            self.assertTrue(verified)
            self.assertEqual(len(store.data['actions']), 1)

    def test_automatic_arrival_shop_closes_only_after_the_observed_next_node(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            choice = next_action(current('node_result'), session=store.data)
            action = self.persist_choice(store, choice)
            action['status'] = 'verified'
            shop = screen('shop')
            shop.tokens = [Token('1-2',t.score,t.box) if t.text == '1-1' else t for t in shop.tokens]
            shop.tokens += [Token('7', .99, (.852,.833,.869,.867)), Token('Lv.3', .99, (.14,.82,.18,.86))]
            self.assertTrue(transition_ready(choice, shop))
            progress_verified(store.data, choice, shop)
            close = next_action(shop, session=store.data)
            self.assertEqual(close.intent, 'close_standard_arrival_shop')
            self.persist_choice(store, close)
            self.assertEqual(next_action(shop, session=store.data), close)
            after = board('1-2')
            after.tokens.append(Token('7', .99, (.852,.833,.869,.867)))
            self.assertTrue(transition_ready(close, after))
            after.tokens[-1] = Token('6', .99, (.852,.833,.869,.867))
            self.assertFalse(transition_ready(close, after))
            store.data['actions'][-2]['feedback']['node'] = '1-3'
            with self.assertRaises(AutomationError):
                next_action(shop, session=store.data)

    def test_next_plane_environment_feedback_does_not_accept_the_old_board(self):
        from autohsr.tests.test_currency_wars_standard_environment import environment
        choice = next_action(environment((1,), True), session=dict(expected_board='2-1'))
        self.assertEqual(choice.payload, ('2-1',))
        self.assertTrue(transition_ready(choice, board('2-1')))
        self.assertFalse(transition_ready(choice, board('1-1')))

    def test_terminal_pages_without_complete_source_chain_cannot_settle(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder, '3-5')
            for kind in ('final_victory', 'match_rating', 'match_summary', 'match_statistics'):
                with self.subTest(kind=kind), self.assertRaises(AutomationError):
                    next_action(screen(kind), session=store.data)
            store.data.update(match_victory_observed=True, victory_start_action_id=0)
            store.data['node_attempt']['result_kind'] = 'final_victory'
            for kind in ('match_rating', 'match_summary', 'match_statistics'):
                with self.subTest(kind=kind), self.assertRaises(AutomationError):
                    next_action(screen(kind), session=store.data)
            self.assertFalse(store.data['completion_verified'])

    def test_final_result_and_four_feedback_pages_complete_development_match_only(self):
        with tempfile.TemporaryDirectory() as folder:
            self.store(folder, '3-5', observed=False)
            states = [screen(kind) for kind in ('final_victory','match_rating','match_rating','match_summary','match_statistics','lobby')]
            self.assertEqual(result_node(states[0]), '3-5')
            c = standard_helpers.StandardFlowTests().context(folder, states, resume=True)
            snapshot = c.snapshot
            count = 0
            def transition_hides_identity():
                nonlocal count
                scene = snapshot()
                count += 1
                if count == 2:
                    scene.tokens = [t for t in scene.tokens if not t.text.startswith('UID')]
                return scene
            c.snapshot = transition_hides_identity
            with patch('autohsr.currency_wars_replay.save_sample'):
                result = run_standard(c)
            self.assertEqual(result.status, 'success')
            self.assertEqual(c.currency_standard_input.call_count, 4)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['status'], 'settled')
            self.assertTrue(saved['completion_verified'])
            self.assertTrue(saved['development_only'])
            self.assertEqual([a['status'] for a in saved['actions']], ['verified']*5)
            self.assertNotIn('independent_successes', saved)

    def test_unknown_continue_is_not_repeated_or_resumed(self):
        with tempfile.TemporaryDirectory() as folder:
            self.store(folder)
            c = standard_helpers.StandardFlowTests().context(folder, [current('node_result'), current('node_result')], resume=True)
            with patch('autohsr.currency_wars_replay.save_sample'), \
                    patch('autohsr.currency_wars_standard_flow.time', SimpleNamespace(monotonic=Mock(side_effect=[0,61]))):
                result = run_standard(c)
            self.assertEqual(result.status, 'partial')
            c.currency_standard_input.assert_called_once()
            self.assertEqual(c.report.currency_wars['actions'][-1]['status'], 'unknown')
            c.currency_standard_input.reset_mock()
            with self.assertRaises(AutomationError):
                run_standard(c)
            c.currency_standard_input.assert_not_called()

    def test_pause_and_identity_change_keep_durable_intent_unverified(self):
        for case in ('pause','account'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                self.store(folder)
                c = standard_helpers.StandardFlowTests().context(folder, [current('node_result'), board('1-2')], resume=True)
                if case == 'pause':
                    c.currency_standard_input.side_effect = InputInterrupted('pause')
                else:
                    original = c.snapshot
                    count = 0
                    def changed():
                        nonlocal count
                        state = original()
                        count += 1
                        if count == 2:
                            state.tokens[-1] = Token('UID:200000000', .99, (.01,.96,.10,.99))
                        return state
                    c.snapshot = changed
                with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaises(AutomationError):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['actions'][-1]['status'], 'pending')
                self.assertFalse(saved['completion_verified'])
                c.currency_standard_input.assert_called_once()


if __name__ == '__main__':
    unittest.main()
