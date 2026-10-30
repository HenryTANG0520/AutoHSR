"""Exercise initial custody through the real flow and Context, using fake IO."""
from copy import deepcopy
from itertools import count
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context
from autohsr.currency_wars_initial import capture_current
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError, InputInterrupted, Stopped
from autohsr.tests import test_currency_wars_initial as initial
from autohsr.tests.test_currency_wars_standard_environment import environment
from autohsr.tests import test_currency_wars_standard_flow as flow_helpers


class InitialFlowTests(unittest.TestCase):
    def context(self, folder, *, empty=False):
        c = flow_helpers.StandardFlowTests().context(folder, [], resume=True)
        board, session = initial.fixture(c.report.run_dir, empty=empty)
        session['actions'].pop()  # The formal flow must create its own confirm.
        session['shop_observed_nodes'] = []
        store = StandardSession(Path(folder) / 'currency-standard-session.json')
        store.begin(c.report.run_dir, dict(rank_verified=True))
        store.data.update(session)
        store.persist()
        c.window = Mock()
        c.currency_standard_input = Mock(side_effect=lambda scene, choice: Context.currency_standard_input(c, scene, choice))
        indexes = count()
        c.evidence = lambda scene, label: initial.write_scene(c.report.run_dir, str(next(indexes)) + '-' + label + '.png', scene)
        return c, board, store

    def states(self, c, scenes, *, duplicate_at=()):
        source = iter(scenes)
        snapshots, stamp = count(), [None]
        original = c.snapshot
        def take():
            try:
                scene = next(source)
            except StopIteration:
                raise Stopped('synthetic scene sequence ended')
            # The helper supplies the same fake account and normal freshness.
            c.last_scene = scene
            current = original()
            index = next(snapshots)
            if index in duplicate_at:
                current.captured_at = stamp[0]
            stamp[0] = current.captured_at
            return current
        c.snapshot = take

    def stop_after(self, c, intent):
        def boundary():
            store = getattr(c, 'currency_standard_session', None)
            if store and store.data['actions'][-1]['action'] == intent and store.data['actions'][-1]['status'] == 'verified':
                raise Stopped('verified synthetic boundary')
        c.checkpoint = boundary

    def test_confirm_and_automatic_shop_close_have_independent_two_frame_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            c, board, _ = self.context(folder)
            self.states(c, [environment((1,), True), initial.clone(board), initial.shop_scene(board),
                            initial.clone(board), initial.clone(board)])
            self.stop_after(c, 'close_standard_initial_shop')
            with patch('autohsr.currency_wars_replay.save_sample'), \
                 patch('autohsr.currency_wars_standard_trading.purchase_action', side_effect=AssertionError('must collect first')), \
                 patch('autohsr.currency_wars_standard_refresh.refresh_action', side_effect=AssertionError('must collect first')), \
                 self.assertRaises(Stopped):
                run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual([a['action'] for a in saved['actions'][3:]],
                             ['confirm_standard_environment_1', 'close_standard_initial_shop'])
            self.assertTrue(saved['initial_environment']['selection_accepted'])
            self.assertEqual([f['page'] for f in saved['initial_environment']['arrival_frames']], ['preparation', 'shop'])
            receipt = saved['initial_shop_return']['receipt']
            self.assertTrue(receipt['free_view_only'])
            self.assertFalse(receipt['trade_authorized'])
            self.assertFalse(receipt['delivery_attributed'])
            self.assertEqual(len(receipt['frames']), 2)
            self.assertNotIn('pre_shop_snapshot', saved)
            self.assertEqual(saved['shop_observed_nodes'], [])
            self.assertEqual(ledger_status(saved['actions']), 'clear')
            self.assertEqual(c.window.click.call_count, 2)

    def test_repeated_capture_does_not_count_as_second_confirm_or_return_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            c, board, _ = self.context(folder)
            self.states(c, [environment((1,), True), initial.clone(board), initial.clone(board), initial.shop_scene(board),
                            initial.clone(board), initial.clone(board), initial.clone(board)], duplicate_at=(2, 5))
            self.stop_after(c, 'close_standard_initial_shop')
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaises(Stopped):
                run_standard(c)
            data = c.currency_standard_session.data
            arrivals = data['initial_environment']['arrival_frames']
            returns = data['initial_shop_return']['receipt']['frames']
            self.assertEqual((len(arrivals), len(returns)), (2, 2))
            self.assertLess(arrivals[0]['captured_at'], arrivals[1]['captured_at'])
            self.assertLess(returns[0]['captured_at'], returns[1]['captured_at'])
            self.assertEqual(c.window.click.call_count, 2)

    def test_direct_preparation_current_zero_roster_is_after_choice_and_before_loot(self):
        with tempfile.TemporaryDirectory() as folder:
            c, board, _ = self.context(folder, empty=True)
            self.states(c, [environment((1,), True), initial.clone(board), initial.clone(board)])
            def boundary(message, *args):
                if message.startswith('初始环境：'):
                    raise Stopped('current state saved before any reward')
            c.log = Mock(side_effect=boundary)
            with patch('autohsr.currency_wars_replay.save_sample'), \
                 patch('autohsr.currency_wars_loot.loot_target', side_effect=AssertionError('current state must be first')), \
                 self.assertRaises(Stopped):
                run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            record = saved['initial_environment']
            self.assertEqual(record['post_choice_observation']['baseline_scope'], 'post_choice')
            self.assertEqual(record['post_choice_observation']['snapshot']['roster'], [])
            self.assertFalse(record['post_choice_observation']['delivery_verified'])
            self.assertEqual(record['declared_obligations'][0]['status'], 'unattributed')
            self.assertEqual(c.window.click.call_count, 1)

    def test_native_current_capture_requires_confirmed_inspection_before_any_reward(self):
        with tempfile.TemporaryDirectory() as folder:
            c, board, store = self.context(folder)
            # Establish only the accepted choice and original role cache. A
            # matching two-star role alone cannot publish a current observation.
            data = store.data
            _, source = initial.fixture(c.report.run_dir)
            data['actions'] = source['actions']
            initial.arrive(c.report.run_dir, board, data)
            with patch('autohsr.currency_wars_standard_rewards.open_bench_action', side_effect=AssertionError('read roles first')):
                with self.assertRaises(AutomationError):
                    next_action(initial.clone(board), session=data)
            initial.collect_role(c.report.run_dir, board, data)
            store.persist()
            self.states(c, [initial.clone(board)])
            c.log = Mock(side_effect=lambda message, *args: (_ for _ in ()).throw(Stopped('observed'))
                         if message.startswith('初始环境：') else None)
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaises(Stopped):
                run_standard(c)
            observation = c.currency_standard_session.data['initial_environment']['post_choice_observation']
            self.assertEqual(len(observation['snapshot']['roster']), 1)
            self.assertEqual(len(observation['action_proofs']), 2)
            self.assertFalse(observation['delivery_verified'])
            c.window.click.assert_not_called()

    def accepted_context(self, folder):
        c, board, store = self.context(folder)
        _, source = initial.fixture(c.report.run_dir)
        store.data['actions'] = source['actions']
        initial.arrive(c.report.run_dir, board, store.data, mixed=True)
        store.persist()
        c.currency_standard_session = store
        self.states(c, [initial.shop_scene(board)])
        scene = c.snapshot()
        choice = next_action(scene, session=store.data)
        action = store.pending(choice.intent, 0, c.evidence(scene, 'before-shop-close'), choice.expected)
        action['target'] = deepcopy(list(choice.payload))
        from autohsr.currency_wars_initial_shop import bind_intent
        bind_intent(store.data, choice, scene)
        store.persist()
        return c, board, store, scene, choice

    def test_context_requires_durable_initial_binding_and_live_account_epoch(self):
        for change in ('unwritten', 'deleted', 'account', 'epoch'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c, _, store, scene, choice = self.accepted_context(folder)
                if change == 'unwritten':
                    store.data['initial_shop_return']['policy'] = 'not-durable'
                elif change == 'deleted':
                    store.data.pop('initial_environment')
                elif change == 'epoch':
                    c.runner.input_epoch += 1
                else:
                    from autohsr.tests.test_currency_wars_standard_collection import uid
                    uid(scene, '200000000')
                with self.assertRaises((AutomationError, InputInterrupted)):
                    Context.currency_standard_input(c, scene, choice)
                c.window.click.assert_not_called()

    def test_post_choice_json_roundtrip_allows_normal_guarded_shop_input(self):
        with tempfile.TemporaryDirectory() as folder:
            c, board, store = self.context(folder)
            _, source = initial.fixture(c.report.run_dir)
            store.data['actions'] = source['actions']
            initial.arrive(c.report.run_dir, board, store.data)
            initial.collect_role(c.report.run_dir, board, store.data)
            current = initial.clone(board)
            capture_current(store.data, current, evidence=c.evidence(current, 'post-choice'), run_dir=c.report.run_dir, epoch=0)
            store.persist()
            c.currency_standard_session = store
            self.states(c, [initial.clone(board)])
            scene = c.snapshot()
            choice = next_action(scene, session=store.data)
            self.assertEqual(choice.intent, 'open_standard_shop')
            action = store.pending(choice.intent, 0, c.evidence(scene, 'before-normal-shop'), choice.expected)
            action['target'] = list(choice.payload)
            store.persist()
            Context.currency_standard_input(c, scene, choice)
            c.window.click.assert_called_once_with(*choice.target.center, scene.geometry)
            self.assertNotIn('initial_shop_return', store.data)

    def test_failed_initial_binding_write_never_sends_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            c, _, _ = self.context(folder)
            self.states(c, [environment((1,), True)])
            original = StandardSession.persist
            def save(store):
                if 'initial_environment' in store.data:
                    raise OSError('simulated locked journal')
                return original(store)
            with patch('autohsr.currency_wars_replay.save_sample'), \
                 patch.object(StandardSession, 'persist', save), self.assertRaises(OSError):
                run_standard(c)
            c.window.click.assert_not_called()
            saved = StandardSession(Path(folder) / 'currency-standard-session.json').data
            self.assertEqual(saved['actions'][-1]['status'], 'pending')
            self.assertNotIn('initial_environment', saved)

    def test_invalid_return_receipt_retains_unknown_instead_of_verified_action(self):
        with tempfile.TemporaryDirectory() as folder:
            c, board, _ = self.context(folder)
            self.states(c, [environment((1,), True), initial.clone(board), initial.shop_scene(board),
                            initial.clone(board), initial.clone(board)])
            with patch('autohsr.currency_wars_replay.save_sample'), \
                 patch('autohsr.currency_wars_initial_shop.closed', side_effect=AutomationError('return proof conflict')), \
                 self.assertRaises(AutomationError):
                run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'], 'unknown')
            self.assertEqual(saved['initial_shop_return']['status'], 'pending')
            self.assertEqual(c.window.click.call_count, 2)
            with self.assertRaises(AutomationError):
                run_standard(c)
            self.assertEqual(c.window.click.call_count, 2)
