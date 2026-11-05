"""Behavioral contracts for result continuation, settlement and interrupted IO."""
import tempfile
import re
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars import observe
from autohsr.currency_wars_node import result_node
from autohsr.currency_wars_standard_budget import StandardBudget
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import StandardAction, next_action, run_standard, transition_ready
from autohsr.currency_wars_standard_node import observe_started_node, read_survived_loss
from autohsr.currency_wars_standard_progress import BOSS_INTRO_ACTION, BOSS_INTRO_RETURN, progress_verified
from autohsr.models import AutomationError, InputInterrupted, Stopped, Token
from autohsr.windows import GameWindow, Geometry
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


def loss_page(node='1-1', life=60):
    """Synthetic layout using the result field locations and pinned loss text."""
    scene = current('node_result', node)
    scene.tokens = [Token('挑战结束' if t.text == '挑战成功' else f'小队生命值{life}'
                          if t.text.startswith('小队生命值') else t.text, t.score, t.box)
                    for t in scene.tokens]
    scene.image = np.full((108, 192, 3), 64, np.uint8)
    scene.geometry = Geometry(0, 0, 1920, 1080)
    return scene


def boss_arrival(node='2-7', *, shop=False, gold=17):
    from autohsr.tests.test_currency_wars_standard_trading import hud
    if shop:
        scene = screen('shop')
        scene.tokens = [t for t in scene.tokens if not t.within((.1, .04, .29, .13))
                        or not re.fullmatch(r'[1-3]-[0-9]+', t.text)]
        scene.tokens.append(Token(node, .99, (.23, .055, .26, .085)))
    else:
        scene = board(node)
        scene.tokens = [t for t in scene.tokens if not t.within((.28, .07, .73, .105))
                        or t.text not in ('战斗', '奖励', '首领')]
        scene.tokens.append(Token('首领', .99, (.53, .075, .56, .10)))
    hud(scene, gold=gold, level=8)
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

    def loss_context(self, folder, window, frames):
        seed = self.store(folder, observed=False)
        seed.data['actions'][0]['after'] = 'entered.png'
        seed.persist()
        run_dir = Path(folder) / 'resume'
        run_dir.mkdir()
        runner = Runner(Settings(), operation='currency_wars_standard', currency_resume=True)
        runner.report.run_dir = str(run_dir)
        context = Context(runner, window, Mock())
        states = iter(frames)
        origin = time.monotonic() - 1
        capture = 0

        def snapshot():
            nonlocal capture
            capture += 1
            scene = next(states, None)
            if scene is None:
                raise Stopped('synthetic frames exhausted')
            if observe(scene, .65).page_kind == 'preparation':
                identity = next(t for t in scene.tokens if t.text.startswith('UID'))
                scene = board('1-2')
                scene.tokens.append(identity)
            scene.captured_at = origin + capture * .01
            context.last_scene = scene
            return scene

        def checkpoint():
            store = getattr(context, 'currency_standard_session', None)
            if store is not None and store.data.get('node_history'):
                raise Stopped('synthetic arrival verified')

        context.snapshot, context.checkpoint, context.sleep = snapshot, checkpoint, Mock()
        return context, seed

    def test_standard_survives_node_loss_without_recording_a_win(self):
        with tempfile.TemporaryDirectory() as folder:
            window = Mock()
            window.emergency_pressed.return_value = False
            window.click.side_effect = lambda *_args, before_send: before_send()
            self.assertEqual(observe(loss_page(), .65).page_kind, 'node_loss')
            frames = (loss_page(), loss_page(), current('preparation', '1-2'), current('preparation', '1-2'))
            context, seed = self.loss_context(folder, window, frames)
            with self.assertRaises(Stopped):
                run_standard(context)
            data = StandardSession(seed.path).data
            window.click.assert_called_once()
            attempt, = data['node_history']
            self.assertIs(attempt['node_verified'], False)
            self.assertIs(attempt['node_loss_verified'], True)
            self.assertEqual(attempt['remaining_hp'], 60)
            self.assertEqual(data['actions'][-1]['feedback'], dict(page_kind='preparation', node='1-2'))
            self.assertFalse(data.get('match_victory_observed', False))
            self.assertFalse(data['completion_verified'])
            self.assertEqual(StandardBudget(seed.data).window(data)['phase_node'], '1-2')

    def test_loss_fields_and_pair_reject_zero_conflicts_and_a_single_frame(self):
        split = loss_page()
        split.tokens = [t for t in split.tokens if not t.text.startswith('小队生命值')]
        split.tokens.extend((Token('小队生命值', .99, (.35,.452,.421,.479)),
                             Token('60/100', .98, (.425,.453,.464,.479))))
        self.assertEqual(read_survived_loss(split)[:2], ('1-1', 60))
        self.assertIsNone(read_survived_loss(loss_page(life=0)))
        split.tokens.append(Token('0', .97, (.425,.453,.444,.479)))
        self.assertIsNone(read_survived_loss(split))
        conflicting = loss_page()
        conflicting.tokens.append(Token('前往结算', .98, (.47,.812,.528,.842)))
        self.assertIsNone(read_survived_loss(conflicting))
        for frames in ((loss_page(),), (loss_page(), loss_page(life=59))):
            with tempfile.TemporaryDirectory() as folder:
                window = Mock()
                context, seed = self.loss_context(folder, window, frames)
                with self.assertRaises(Stopped):
                    run_standard(context)
                window.click.assert_not_called()
                attempt = StandardSession(seed.path).data['node_attempt']
                self.assertFalse(attempt.get('node_loss_verified', False))

    def test_loss_native_send_blocks_replaced_original_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            window = object.__new__(GameWindow)
            window.guard = Mock(return_value=Geometry(0, 0, 1920, 1080))
            context, seed = self.loss_context(folder, window, (loss_page(), loss_page()))
            replacement = b'changed synthetic loss PNG'

            def key_state(_key):
                session = StandardSession(seed.path).data
                before = Path(session['node_attempt']['loss_frames'][0]['evidence'])
                before.write_bytes(replacement)
                return 0

            native = Mock()
            native.GetSystemMetrics.side_effect = {76:0, 77:0, 78:1920, 79:1080}.__getitem__
            native.GetAsyncKeyState.side_effect = key_state
            with patch('autohsr.windows.user32', native), self.assertRaises(AutomationError):
                run_standard(context)
            native.SendInput.assert_not_called()
            saved = StandardSession(seed.path).data
            self.assertEqual(saved['actions'][-1]['status'], 'pending')
            self.assertEqual(Path(saved['node_attempt']['loss_frames'][0]['evidence']).read_bytes(), replacement)
            self.assertNotIn('node_history', saved)

    def boss_flow(self, folder, states, *, start_node='2-6', stop_at=None, replace_source=False):
        store = self.store(folder, start_node, observed=False)
        store.data['actions'][0]['after'] = 'entered.png'
        store.persist()
        c = standard_helpers.StandardFlowTests().context(folder, states, resume=True)
        c.window = Mock()
        c.currency_standard_input = Mock()
        c.intermediate = []
        now = 100.
        stamp_before = None
        take_snapshot = c.snapshot
        budget = StandardBudget(store.data)

        def snapshot():
            nonlocal now, stamp_before
            now += .05
            scene = take_snapshot()
            scene.captured_at = now
            if scene is states[1]:
                stamp_before = now
            elif scene is states[2]:
                scene.captured_at = stamp_before
            return scene

        def sleep(seconds):
            nonlocal now
            session = getattr(c, 'currency_standard_session', None)
            waiting_for_wrong_arrival = (stop_at is None and session
                                         and session.data['actions'][-1]['action'] == BOSS_INTRO_ACTION)
            now += 31. if seconds == .5 and waiting_for_wrong_arrival else seconds

        def checkpoint():
            session = getattr(c, 'currency_standard_session', None)
            if session and session.data['actions']:
                if session.data['node_attempt']['status'] == 'intro_pending':
                    c.intermediate.append(budget.window(session.data))
                last = session.data['actions'][-1]
                if last.get('action') == stop_at and last['status'] == 'verified':
                    raise Stopped('fixture reached the boss arrival')

        def dispatch(scene, choice):
            if replace_source and choice.intent == BOSS_INTRO_ACTION:
                durable = StandardSession(c.currency_standard_session.path)
                durable.data['actions'][1]['feedback']['enemy'] = '等级99另一名敌人'
                durable.persist()
                c.replaced_bytes = durable.path.read_bytes()
            return Context.currency_standard_input(c, scene, choice)

        c.snapshot, c.sleep, c.checkpoint = snapshot, sleep, checkpoint
        c.currency_standard_input.side_effect = dispatch
        clock = SimpleNamespace(monotonic=lambda: now)
        return c, clock, budget

    def test_standard_boss_intro_continues_through_board_or_arrival_shop(self):
        for start, node, shop in (('1-8', '1-9', False), ('2-6', '2-7', False),
                                  ('2-6', '2-7', True), ('3-6', '3-7', False)):
            with self.subTest(node=node, shop=shop), tempfile.TemporaryDirectory() as folder:
                frames = [current('node_result', start)] + [screen('boss_intro') for _ in range(4)]
                frames += [boss_arrival(node, shop=shop), boss_arrival(node, shop=shop)]
                if shop:
                    frames.append(boss_arrival(node))
                last_intent = 'close_standard_arrival_shop' if shop else BOSS_INTRO_ACTION
                c, clock, budget = self.boss_flow(folder, frames, start_node=start, stop_at=last_intent)
                with (patch('autohsr.currency_wars_replay.save_sample'),
                      patch('autohsr.currency_wars.time', clock),
                      patch('autohsr.currency_wars_standard_node.time', clock),
                      patch('autohsr.currency_wars_standard_flow.time', clock), self.assertRaises(Stopped)):
                    run_standard(c)
                data = StandardSession(c.currency_standard_session.path).data
                introduction, arrival = data['actions'][1:3]
                self.assertEqual(introduction['feedback']['expected_node'], node)
                self.assertNotIn('node', introduction['feedback'])
                self.assertEqual(arrival['target'], [start, 0, 1, node])
                self.assertEqual(arrival['feedback']['page_kind'], 'shop' if shop else 'preparation')
                self.assertEqual(arrival['feedback']['node'], node)
                for action in (introduction, arrival):
                    first, last = action['progress_frames']
                    self.assertLess(first['captured_at'], last['captured_at'])
                self.assertGreater(introduction['progress_frames'][0]['captured_at'], frames[2].captured_at)
                self.assertEqual(c.window.click.call_count, 3 if shop else 2)
                self.assertTrue(c.intermediate)
                self.assertTrue(all(w['phase_node'] is None for w in c.intermediate))
                self.assertEqual(budget.window(data)['phase_node'], node)
                self.assertEqual(budget.window(data)['phase_start'], arrival['id']+1)
                history, = data['node_history']
                self.assertEqual((history['continue_action_id'], history['arrival_action_id']), (1, 2))
                self.assertFalse(data['completion_verified'])

    def test_boss_preparation_requires_unambiguous_type_and_current_hud(self):
        choice = StandardAction(BOSS_INTRO_ACTION, BOSS_INTRO_RETURN, None, payload=('2-6', 0, 1, '2-7'))
        self.assertTrue(transition_ready(choice, boss_arrival()))
        conflicting_type = boss_arrival()
        conflicting_type.tokens.append(Token('战斗', .99, (.60, .075, .63, .10)))
        self.assertFalse(transition_ready(choice, conflicting_type))
        invalid_hp = boss_arrival()
        invalid_hp.tokens = [Token('101', t.score, t.box) if t.within((.735, .05, .78, .095)) else t
                             for t in invalid_hp.tokens]
        self.assertFalse(transition_ready(choice, invalid_hp))

    def test_resume_at_old_result_preserves_the_verified_intro(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = [current('node_result', '2-6')] + [screen('boss_intro') for _ in range(4)]
            c, clock, _ = self.boss_flow(folder, frames, stop_at='continue_standard_node')
            with (patch('autohsr.currency_wars_replay.save_sample'),
                  patch('autohsr.currency_wars.time', clock),
                  patch('autohsr.currency_wars_standard_node.time', clock),
                  patch('autohsr.currency_wars_standard_flow.time', clock), self.assertRaises(Stopped)):
                run_standard(c)
            original = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(original['node_attempt']['status'], 'intro_pending')
            self.assertEqual(c.window.click.call_count, 1)

            resumed = standard_helpers.StandardFlowTests().context(folder, [current('node_result', '2-6')])
            resumed.runner.currency_resume = True
            with patch('autohsr.currency_wars_replay.save_sample'):
                self.assertEqual(run_standard(resumed).status, 'partial')
            resumed.currency_standard_input.assert_not_called()
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['node_attempt'], original['node_attempt'])
            self.assertEqual(saved['actions'], original['actions'])
            self.assertEqual(next_action(screen('boss_intro'), session=saved).intent, BOSS_INTRO_ACTION)

    def test_intro_without_standard_source_or_wrong_return_cannot_advance(self):
        with self.assertRaises(AutomationError):
            next_action(screen('boss_intro'), session={})
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder, '2-4')  # The real historical A0 transition is not standard.
            choice = next_action(current('node_result', '2-4'), session=store.data)
            self.assertFalse(transition_ready(choice, screen('boss_intro')))
        for tampered in (False, True):
            with self.subTest(tampered=tampered), tempfile.TemporaryDirectory() as folder:
                frames = [current('node_result', '2-6')] + [screen('boss_intro') for _ in range(4)]
                frames += [boss_arrival('2-5'), boss_arrival('2-5')]
                c, clock, budget = self.boss_flow(folder, frames, replace_source=tampered)
                with (patch('autohsr.currency_wars_replay.save_sample'),
                      patch('autohsr.currency_wars.time', clock),
                      patch('autohsr.currency_wars_standard_node.time', clock),
                      patch('autohsr.currency_wars_standard_flow.time', clock)):
                    if tampered:
                        with self.assertRaisesRegex(AutomationError, '落盘'):
                            run_standard(c)
                        self.assertEqual(c.currency_standard_session.path.read_bytes(), c.replaced_bytes)
                    else:
                        self.assertEqual(run_standard(c).status, 'partial')
                    data = StandardSession(c.currency_standard_session.path).data
                    self.assertEqual(data['actions'][-1]['action'], BOSS_INTRO_ACTION)
                    self.assertEqual(data['actions'][-1]['status'], 'pending' if tampered else 'unknown')
                    self.assertEqual(data['node_attempt']['status'], 'intro_pending')
                    self.assertIsNone(budget.window(data)['phase_node'])
                    self.assertEqual(c.window.click.call_count, 1 if tampered else 2)
                    with self.assertRaises(AutomationError):
                        run_standard(c)

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

    def test_continue_and_settlement_reject_changed_durable_result_or_start_evidence(self):
        for kind, changed in (('node_result', 'result'), ('final_victory', 'start')):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                terminal = kind == 'final_victory'
                store = self.store(folder, '3-5' if terminal else '1-1')
                if terminal:
                    store.data['node_attempt']['result_kind'] = kind
                    store.data.update(match_victory_observed=True, victory_start_action_id=0)
                scene = current(kind)
                choice = next_action(scene, session=store.data)
                self.persist_choice(store, choice)
                durable = StandardSession(store.path)
                if changed == 'result':
                    durable.data['node_attempt']['result'] = 'different-result.png'
                else:
                    durable.data['actions'][0]['before'] = 'different-start.png'
                durable.persist()
                saved = store.path.read_bytes()
                c = Context(Runner(Settings(), operation='currency_wars_standard'), Mock(), Mock())
                c.last_scene, c.currency_standard_session = scene, store
                c.checkpoint, c.sleep = Mock(), Mock()
                with self.assertRaisesRegex(AutomationError, '落盘'):
                    c.currency_standard_input(scene, choice)
                c.window.click.assert_not_called()
                self.assertEqual(store.path.read_bytes(), saved)

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
        entry = dict(action='advance_standard_next_plane', status='verified',
                     expected='standard_plane_entered', target=['1-7', 4, '2-1'])
        session = dict(expected_board='2-1', actions=[entry])
        choice = next_action(environment((1,), True), session=session)
        self.assertEqual(choice.payload, ('2-1',))
        self.assertTrue(transition_ready(choice, board('2-1')))
        self.assertFalse(transition_ready(choice, board('1-1')))
        for old_entry in (dict(entry, status='unknown'), dict(entry, target=['2-7', 4, '3-1'])):
            with self.assertRaises(AutomationError):
                next_action(environment((1,), True), session=dict(session, actions=[old_entry]))

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
