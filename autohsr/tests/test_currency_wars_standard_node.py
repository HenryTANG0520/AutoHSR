"""Standard node results are tied to a durable start; battle remains game-owned."""
import json
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
from autohsr.models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, Scene, Stopped, Token
from autohsr.tests.test_currency_wars_node import screen


def current(kind,node='1-1'):
    state=screen(kind,node)
    state.tokens.append(Token('UID:100000000',.99,(.01,.96,.1,.99)))
    return state


def defeat_result():
    page = current('final_victory')
    page.tokens = [Token('挑战结束' if t.text == '挑战成功' else '1-1首领'
                         if t.text == '3-5首领' else t.text, t.score, t.box) for t in page.tokens]
    return page


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
        captured=[time.monotonic()-1]
        def snapshot():
            c.last_scene=next(sequence)
            if isinstance(c.last_scene,Exception):
                error=c.last_scene;c.last_scene=None
                raise error
            # Fake OCR captures must still be distinct on Windows clocks whose
            # resolution can exceed this in-memory test's entire iteration.
            captured[0]+=.001
            c.last_scene.captured_at=captured[0]
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

    def test_known_result_with_unreadable_node_recovers_on_the_same_attempt(self):
        from autohsr.currency_wars import observe
        from autohsr.currency_wars_node import result_node

        recorded = json.loads((Path(__file__).parent/'fixtures/currency_wars_pages.json').read_text('utf8'))
        for variant in ('missing', 'historical_ocr'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                store = self.store(folder)
                hidden, result = current('node_result'), current('node_result')
                if variant == 'missing':
                    hidden.tokens = [t for t in hidden.tokens if not t.within((.4, .24, .53, .30))]
                else:
                    hidden.tokens = [Token(**t) for t in recorded['pages']['node_result']['tokens']] + hidden.tokens[-1:]
                self.assertEqual(observe(hidden, .65).page_kind, 'node_result')
                self.assertIsNone(result_node(hidden))
                c = self.context([current('battle'), hidden, result])
                with patch('autohsr.currency_wars_replay.save_sample'):
                    after, verified = observe_started_node(c, store, c.snapshot())
                self.assertTrue(verified)
                self.assertIs(after, result)
                self.assertTrue(store.data['node_attempt']['node_verified'])
                self.assertFalse(any(call.args[0] is hidden for call in c.evidence.call_args_list))
                self.assertEqual(len(store.data['actions']), 1)

    def test_conflicting_readable_result_nodes_stop_instead_of_picking_the_expected_one(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            conflicting = current('node_result')
            conflicting.tokens.append(Token('1-2战斗', .99, (.455, .253, .501, .281)))
            c = self.context([conflicting])
            with patch('autohsr.currency_wars_replay.save_sample'):
                after, verified = observe_started_node(c, store, c.snapshot())
            self.assertIs(after, conflicting)
            self.assertFalse(verified)
            self.assertFalse(store.data['node_attempt']['node_verified'])
            self.assertIn('节点号有冲突', store.data['reason'])

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
            result=current('node_result')
            c=self.context([current('battle'),current('battle'),result])
            snapshot=c.snapshot;captured=time.monotonic()-1
            def same_capture_time():
                page=snapshot();page.captured_at=captured+(.01 if page is result else 0)
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

    def test_temporarily_missing_low_confidence_or_conflicting_identity_is_only_an_unknown_frame(self):
        for variant in ('missing','low_confidence','conflicting'):
            for kind in ('battle','node_result'):
                with self.subTest(variant=variant,kind=kind),tempfile.TemporaryDirectory() as folder:
                    store=self.store(folder)
                    hidden=current(kind)
                    if variant=='missing':hidden.tokens=hidden.tokens[:-1]
                    elif variant=='low_confidence':
                        last=hidden.tokens[-1];hidden.tokens[-1]=Token(last.text,.80,last.box)
                    else:hidden.tokens.append(Token('UID:200000000',.99,(.11,.96,.2,.99)))
                    battle,result=current('battle'),current('node_result')
                    c=self.context([hidden,battle,result])
                    with patch('autohsr.currency_wars_replay.save_sample'):
                        after,verified=observe_started_node(c,store,c.snapshot())
                    self.assertTrue(verified)
                    self.assertIs(after,result)
                    self.assertTrue(store.data['node_attempt']['battle_observed'])
                    self.assertTrue(store.data['node_attempt']['node_verified'])
                    self.assertFalse(store.data['completion_verified'])
                    self.assertFalse(any(call.args[0] is hidden for call in c.evidence.call_args_list))
                    self.assertEqual(len(store.data['actions']),1)

    def test_identity_gap_cannot_bridge_two_auto_on_observations(self):
        from autohsr.currency_wars_auto import AutoObservation
        for gap in ('identity','capture'):
            with self.subTest(gap=gap),tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                hidden=current('battle');hidden.tokens=hidden.tokens[:-1]
                missing=hidden if gap=='identity' else EmptyCapture('transition')
                c=self.context([current('battle'),missing,current('battle'),current('node_result')])
                with patch('autohsr.currency_wars_replay.save_sample'),patch(
                        'autohsr.currency_wars_auto.read_auto',return_value=AutoObservation('on',.99,())) as read_auto:
                    _,verified=observe_started_node(c,store,c.snapshot())
                self.assertTrue(verified)
                self.assertEqual(read_auto.call_count,2)
                self.assertFalse(store.data['node_attempt']['auto_on_observed'])
                self.assertFalse(store.data['node_attempt']['auto_observation']['verified_on'])
                self.assertEqual(len(store.data['node_attempt']['auto_observation']['on_frames']),1)

    def test_identity_gap_discards_current_on_but_preserves_verified_on_history(self):
        import json
        from autohsr.currency_wars_auto import AutoObservation
        for gap in ('identity','capture'):
            with self.subTest(gap=gap),tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                hidden=current('node_result');hidden.tokens=hidden.tokens[:-1]
                missing=hidden if gap=='identity' else EmptyCapture('transition')
                c=self.context([current('battle'),current('battle'),missing,current('node_result')])
                with patch('autohsr.currency_wars_replay.save_sample'),patch(
                        'autohsr.currency_wars_auto.read_auto',return_value=AutoObservation('on',.99,())):
                    _,verified=observe_started_node(c,store,c.snapshot())
                self.assertTrue(verified)
                attempt=store.data['node_attempt']
                self.assertTrue(attempt['auto_on_observed'])
                self.assertEqual(len(attempt['auto_on_evidence']),2)
                self.assertNotIn('auto_observation',attempt)
                saved=json.loads(store.path.read_text(encoding='utf-8'))['node_attempt']
                self.assertTrue(saved['auto_on_observed'])
                self.assertNotIn('auto_observation',saved)

    def test_identity_or_capture_gap_requires_two_new_defeat_frames(self):
        for gap in ('identity','capture'):
            with self.subTest(gap=gap),tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                first,second,third=defeat_result(),defeat_result(),defeat_result()
                hidden=defeat_result();hidden.tokens=hidden.tokens[:-1]
                missing=hidden if gap=='identity' else EmptyCapture('transition')
                c=self.context([first,missing,second,third])
                c.evidence.side_effect=lambda scene,label:label+str(id(scene))+'.png'
                with patch('autohsr.currency_wars_replay.save_sample'):
                    after,verified=observe_started_node(c,store,c.snapshot())
                self.assertTrue(verified)
                self.assertIs(after,third)
                self.assertFalse(store.data['node_attempt']['node_verified'])
                self.assertEqual(store.data['node_attempt']['status'],'defeated')
                self.assertEqual(store.data['node_attempt']['defeat_frames'],[
                    'currency_standard_defeat_frame_1'+str(id(second))+'.png',
                    'currency_standard_defeat_frame_2'+str(id(third))+'.png'])
                self.assertFalse(store.data['completion_verified'])
                self.assertEqual(len(store.data['actions']),1)

    def test_repeated_capture_or_epoch_change_breaks_terminal_defeat_confirmation(self):
        for gap, count in (('duplicate', 4), ('epoch', 3)):
            with self.subTest(gap=gap), tempfile.TemporaryDirectory() as folder:
                store = self.store(folder)
                frames = [defeat_result() for _ in range(count)]
                c = self.context(frames)
                snapshot = c.snapshot

                def observe_frame():
                    frame = snapshot()
                    if frame is frames[1]:
                        if gap == 'duplicate':
                            frame.captured_at = frames[0].captured_at
                        else:
                            c.runner.input_epoch = c.scene_epoch = 1
                    return frame

                c.snapshot = observe_frame
                c.evidence.side_effect = lambda scene, label: label + str(id(scene)) + '.png'
                with patch('autohsr.currency_wars_replay.save_sample'):
                    after, verified = observe_started_node(c, store, c.snapshot())
                self.assertTrue(verified)
                self.assertIs(after, frames[-1])
                self.assertEqual(store.data['node_attempt']['defeat_frames'], [
                    'currency_standard_defeat_frame_1' + str(id(frames[-2])) + '.png',
                    'currency_standard_defeat_frame_2' + str(id(frames[-1])) + '.png',
                ])

    def test_loading_screen_cannot_bridge_auto_on_observations(self):
        from autohsr.currency_wars_auto import AutoObservation

        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            loading = Scene([current('battle').tokens[-1]])
            c = self.context([current('battle'), loading, current('battle'), current('node_result')])
            with (patch('autohsr.currency_wars_replay.save_sample'),
                  patch('autohsr.currency_wars_auto.read_auto', return_value=AutoObservation('on', .99, ())) as read_auto):
                _, verified = observe_started_node(c, store, c.snapshot())
            self.assertTrue(verified)
            self.assertEqual(read_auto.call_count, 2)
            self.assertFalse(store.data['node_attempt']['auto_on_observed'])

    def test_missing_identity_uses_one_existing_deadline_across_frames_and_never_verifies_result(self):
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            hidden_battle,hidden_result=current('battle'),current('node_result')
            for page in (hidden_battle,hidden_result):page.tokens=page.tokens[:-1]
            c=self.context([hidden_battle,hidden_result,current('node_result')])
            first=c.snapshot()
            clock=SimpleNamespace(monotonic=Mock(side_effect=[0,12,12,21,21,31]))
            with patch('autohsr.currency_wars_standard_node.time',clock),patch('autohsr.currency_wars_replay.save_sample'):
                after,verified=observe_started_node(c,store,first)
            self.assertFalse(verified)
            self.assertIs(after,hidden_result)
            self.assertFalse(store.data['node_attempt']['node_verified'])
            self.assertFalse(store.data['node_attempt']['battle_observed'])
            self.assertEqual(store.data['node_attempt']['status'],'unknown')
            self.assertEqual(store.data['action_status'],'node_unverified')
            self.assertIn('账号标识',store.data['reason'])
            self.assertNotIn('result',store.data['node_attempt'])
            self.assertNotIn('auto_observation',store.data['node_attempt'])
            self.assertEqual(len(store.data['actions']),1)

    def test_capture_crossing_the_unreadable_deadline_cannot_deliver_a_late_result(self):
        for missing in ('identity', 'result_node'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                hidden=current('battle' if missing == 'identity' else 'node_result')
                if missing == 'identity':
                    hidden.tokens=hidden.tokens[:-1]
                else:
                    hidden.tokens=[t for t in hidden.tokens if not t.within((.4, .24, .53, .30))]
                result=current('node_result');c=self.context([hidden,result]);first=c.snapshot()
                clock=SimpleNamespace(monotonic=Mock(side_effect=[0,1,1,32]))
                with patch('autohsr.currency_wars_standard_node.time',clock),patch('autohsr.currency_wars_replay.save_sample'):
                    after,verified=observe_started_node(c,store,first)
                self.assertFalse(verified)
                self.assertIs(after,result)
                self.assertEqual(store.data['node_attempt']['status'],'unknown')
                self.assertFalse(store.data['node_attempt']['node_verified'])
                self.assertNotIn('result',store.data['node_attempt'])
                self.assertIn('账号标识' if missing == 'identity' else '节点号', store.data['reason'])
                self.assertEqual(len(store.data['actions']),1)

    def test_identity_recovery_still_rejects_a_different_account_or_node(self):
        for variant in ('account','node'):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as folder:
                store=self.store(folder)
                hidden=current('battle');hidden.tokens=hidden.tokens[:-1]
                wrong=current('battle','1-2') if variant=='node' else current('node_result')
                if variant=='account':wrong.tokens[-1]=Token('UID:200000000',.99,(.01,.96,.1,.99))
                c=self.context([hidden,wrong])
                with patch('autohsr.currency_wars_replay.save_sample'):
                    if variant=='account':
                        with self.assertRaises(AutomationError):observe_started_node(c,store,c.snapshot())
                    else:
                        _,verified=observe_started_node(c,store,c.snapshot())
                        self.assertFalse(verified)
                self.assertFalse(store.data['node_attempt']['node_verified'])
                self.assertEqual(len(store.data['actions']),1)

    def test_empty_capture_and_missing_identity_can_recover_without_restarting(self):
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            hidden=current('node_result');hidden.tokens=hidden.tokens[:-1]
            c=self.context([current('battle'),EmptyCapture('transition'),hidden,current('node_result')])
            with patch('autohsr.currency_wars_replay.save_sample'):
                _,verified=observe_started_node(c,store,c.snapshot())
            self.assertTrue(verified)
            self.assertTrue(store.data['node_attempt']['node_verified'])
            self.assertEqual(len(store.data['actions']),1)

    def test_control_exceptions_from_identity_or_auto_are_never_converted_to_unknown(self):
        for source in ('identity','auto'):
            for control in (Stopped('stop'),InputInterrupted('epoch'),FocusLost('focus')):
                with self.subTest(source=source,control=type(control).__name__),tempfile.TemporaryDirectory() as folder:
                    store=self.store(folder);c=self.context([current('battle')])
                    name=('autohsr.currency_wars_standard_node.account_key' if source=='identity'
                          else 'autohsr.currency_wars_auto.read_auto')
                    with patch('autohsr.currency_wars_replay.save_sample'),patch(name,side_effect=control):
                        with self.assertRaises(type(control)) as raised:
                            observe_started_node(c,store,c.snapshot())
                    self.assertIs(raised.exception,control)
                    self.assertFalse(store.data['node_attempt']['node_verified'])
                    self.assertNotIn('auto_observation',store.data['node_attempt'])
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
