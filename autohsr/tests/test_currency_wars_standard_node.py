"""Standard node results are tied to a durable start; battle remains game-owned."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.currency_wars_identity import account_key
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_node import entry_feedback, observe_started_node
from autohsr.currency_wars_standard_flow import next_action
from autohsr.models import AutomationError, Scene, Token
from autohsr.tests.test_currency_wars_node import screen


def current(kind,node='1-1'):
    state=screen(kind,node)
    state.tokens.append(Token('UID:100000000',.99,(.01,.96,.1,.99)))
    return state


class StandardNodeTests(unittest.TestCase):
    def store(self,folder):
        store=StandardSession(Path(folder)/'session.json')
        store.begin(folder,dict(rank_verified=True))
        store.data.update(status='active',start_verified=True,account_key=account_key(current('battle')))
        action=store.pending('start_standard_node',0,'before.png','standard_node_entered')
        action.update(status='verified',target=['1-1',5,80,3])
        store.data['node_attempt']=dict(node='1-1',start_action_id=0,status='observing',node_verified=False,battle_observed=False)
        store.persist()
        return store

    def context(self,states):
        c=SimpleNamespace(settings=SimpleNamespace(ocr_confidence=.65,battle_timeout=120),
            runner=SimpleNamespace(input_epoch=0,inactive_duration=0),scene_epoch=0,
            checkpoint=Mock(),sleep=Mock(),log=Mock(),evidence=Mock(return_value='evidence.png'))
        sequence=iter(states)
        def snapshot():
            c.last_scene=next(sequence)
            c.last_scene.captured_at=time.monotonic()
            return c.last_scene
        c.snapshot=snapshot
        return c

    def test_entry_feedback_requires_matching_node_not_merely_battle_or_victory_text(self):
        for kind in ('battle','node_result'):
            self.assertTrue(entry_feedback(current(kind),'1-1'))
            self.assertFalse(entry_feedback(current(kind,'1-2'),'1-1'))
        self.assertFalse(entry_feedback(current('investment_selection'),'1-1'))

    def test_observed_and_too_short_battles_verify_only_node_not_whole_match(self):
        for battle in (True,False):
            with tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                c=self.context(([current('battle')] if battle else [])+[current('node_result')])
                with patch('autohsr.currency_wars_replay.save_sample'):
                    after,verified=observe_started_node(c,store,c.snapshot())
                self.assertTrue(verified)
                self.assertEqual(store.data['node_attempt']['battle_observed'],battle)
                self.assertTrue(store.data['node_attempt']['node_verified'])
                self.assertFalse(store.data['completion_verified'])
                self.assertEqual(len(store.data['actions']),1)

    def test_auto_on_requires_two_distinct_fresh_observations_without_adding_input(self):
        from autohsr.currency_wars_auto import AutoObservation
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            c=self.context([current('battle'),current('battle'),current('node_result')])
            snapshot=c.snapshot
            captured=[time.monotonic()-1]
            def fresh_snapshot():
                page=snapshot()
                captured[0]+=.01
                page.captured_at=captured[0]
                return page
            c.snapshot=fresh_snapshot
            c.evidence.side_effect=lambda scene,label:label+'.png'
            on=AutoObservation('on',.99,(('off_calibrated',False),))
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_auto.read_auto',return_value=on):
                _,verified=observe_started_node(c,store,c.snapshot())
            attempt=store.data['node_attempt']
            self.assertTrue(verified)
            self.assertTrue(attempt['auto_on_observed'])
            self.assertTrue(attempt['auto_observation']['verified_on'])
            self.assertEqual(len(attempt['auto_on_evidence']),2)
            self.assertLess(attempt['auto_on_evidence'][0]['captured_at'],attempt['auto_on_evidence'][1]['captured_at'])
            self.assertEqual(len(store.data['actions']),1)
            self.assertFalse(store.data['completion_verified'])

    def test_repeated_capture_timestamp_does_not_count_as_two_auto_observations(self):
        from autohsr.currency_wars_auto import AutoObservation
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            c=self.context([current('battle'),current('battle'),current('node_result')])
            snapshot=c.snapshot;captured=time.monotonic()-1
            def same_capture_time():
                page=snapshot();page.captured_at=captured
                return page
            c.snapshot=same_capture_time
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_auto.read_auto',return_value=AutoObservation('on',.99,())):
                _,verified=observe_started_node(c,store,c.snapshot())
            self.assertTrue(verified)
            self.assertFalse(store.data['node_attempt']['auto_on_observed'])
            self.assertEqual(len(store.data['actions']),1)

    def test_disabled_or_unknown_breaks_auto_confirmation_without_discarding_node_result(self):
        from autohsr.currency_wars_auto import AutoObservation
        for middle in ('disabled','unknown'):
            with self.subTest(middle=middle),tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                c=self.context([current('battle'),current('battle'),current('battle'),current('node_result')])
                states=[AutoObservation(state,.99,()) for state in ('on',middle,'on')]
                with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_auto.read_auto',side_effect=states):
                    _,verified=observe_started_node(c,store,c.snapshot())
                self.assertTrue(verified)
                self.assertFalse(store.data['node_attempt']['auto_on_observed'])
                self.assertFalse(store.data['node_attempt']['auto_observation']['verified_on'])
                self.assertEqual(len(store.data['actions']),1)

    def test_auto_reader_interruption_cannot_save_stale_on_proof(self):
        from autohsr.currency_wars_auto import AutoObservation
        from autohsr.models import InputInterrupted
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder);c=self.context([current('battle')])
            def interrupted(*args):
                c.runner.input_epoch+=1
                return AutoObservation('on',.99,())
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_auto.read_auto',side_effect=interrupted):
                with self.assertRaises(InputInterrupted):observe_started_node(c,store,c.snapshot())
            self.assertNotIn('auto_observation',store.data['node_attempt'])
            self.assertEqual(len(store.data['actions']),1)

    def test_wrong_result_different_battle_and_unknown_start_never_grant_success(self):
        for kind in ('battle','node_result'):
            with tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                c=self.context([current(kind,'1-2')])
                with patch('autohsr.currency_wars_replay.save_sample'):
                    _,verified=observe_started_node(c,store,c.snapshot())
                self.assertFalse(verified)
                self.assertFalse(store.data['node_attempt']['node_verified'])
                store.data['actions'][0]['status']='unknown'
                with self.assertRaises(AutomationError):
                    observe_started_node(c,store,c.last_scene)

    def test_identity_mismatch_and_unseen_transition_stop_without_restarting(self):
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            scene=current('battle')
            scene.tokens[-1]=Token('UID:200000000',.99,(.01,.96,.1,.99))
            c=self.context([scene])
            with self.assertRaises(AutomationError):
                observe_started_node(c,store,c.snapshot())
            c=self.context([Scene([current('battle').tokens[-1]],captured_at=time.monotonic())])
            clock=SimpleNamespace(monotonic=Mock(side_effect=[0,31]))
            with patch('autohsr.currency_wars_standard_node.time',clock),patch('autohsr.currency_wars_replay.save_sample'):
                _,verified=observe_started_node(c,store,c.snapshot())
            self.assertFalse(verified)
            self.assertEqual(store.data['action_status'],'node_unverified')
            self.assertEqual(len(store.data['actions']),1)

    def test_full_owned_board_can_start_once_and_own_pending_is_rederived(self):
        from autohsr.tests.test_currency_wars_standard_trading import full_board_fixture
        scene,source=full_board_fixture()
        session=dict(shop_observed_nodes=['1-1'],collection=source['collection'])
        with patch('autohsr.currency_wars_standard_deployment.standard_deployment',return_value=None):
            choice=next_action(scene,session=session)
            self.assertEqual(choice.intent,'start_standard_node')
            session.update(node_attempt=dict(node='1-1',status='start_pending',start_action_id=0),
                           actions=[dict(id=0,action='start_standard_node',status='pending',
                                         expected=choice.expected,target=list(choice.payload))])
            self.assertEqual(next_action(scene,session=session),choice)
            session['actions'][-1]['status']='verified'
            session['node_attempt']['status']='observing'
            with self.assertRaises(AutomationError):
                next_action(scene,session=session)


if __name__=='__main__':
    unittest.main()
