"""Exercise initial custody through the real flow and Context, using fake IO."""
from copy import deepcopy
from itertools import count
import json
import mmap
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import windows
from autohsr.app import Context
from autohsr.currency_wars_initial import _pixels, begin, capture_current
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError, InputInterrupted, Stopped
from autohsr.storage import file_revision
from autohsr.tests import test_currency_wars_initial as initial
from autohsr.tests.test_currency_wars_standard_environment import change_text, environment
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

    def stage_environment(self, c, store, scene, *, selected=None):
        choice = next_action(scene)
        action = store.pending(choice.intent, 0, c.evidence(scene, 'before-environment'), choice.expected)
        name, kind, effect, parameters, score, reason, policy = choice.details
        action['decision'] = dict(name=name, kind=kind, effect=effect, parameters=dict(parameters),
                                  score=score, reason=reason, policy=policy)
        if selected is not None:
            action.update(status='verified', after=str(c.evidence(selected, 'after-environment-select')))
        elif choice.intent.startswith('confirm_standard_environment_'):
            begin(store.data, action['id'], run_dir=c.report.run_dir, epoch=0)
        store.persist()
        return choice

    def test_changed_effect_after_selection_stays_unknown_and_is_not_replayed(self):
        for variant in ('changed_effect', 'reused_capture'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                c, _, store = self.context(folder)
                selected = environment((1,), True)
                duplicate_at = (1,) if variant == 'reused_capture' else ()
                if variant == 'changed_effect':
                    change_text(selected, '随机2星2费', '随机3星2费')
                self.states(c, [environment(), selected, selected], duplicate_at=duplicate_at)
                clock = SimpleNamespace(monotonic=Mock(side_effect=count(0, 61)))
                with patch('autohsr.currency_wars_replay.save_sample'), \
                     patch('autohsr.currency_wars_standard_flow.time', clock):
                    run_standard(c)
                saved = StandardSession(store.path).data
                action = saved['actions'][-1]
                self.assertEqual((len(saved['actions']), action['action'], action['status']),
                                 (4, 'select_standard_environment_1', 'unknown'))
                self.assertEqual(action['decision']['parameters']['star'], 2)
                c.window.click.assert_called_once()
                with self.assertRaises(AutomationError):
                    run_standard(c)
                c.window.click.assert_called_once()

    def test_resume_rechecks_last_verified_environment_selection(self):
        for variant in ('changed_effect', 'missing_decision', 'matching_effect'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                c, board, store = self.context(folder)
                self.stage_environment(c, store, environment(), selected=environment((1,), True))
                last = store.data['actions'][-1]
                if variant == 'missing_decision':
                    last.pop('decision')
                    store.persist()
                current = environment((1,), True)
                if variant == 'changed_effect':
                    change_text(current, '随机2星2费', '随机3星2费')
                if variant == 'matching_effect':
                    change_text(current, '战力飙升', '战力 飙升')
                    change_text(current, '随机属性加成。', '随机属性加成')
                    change_text(current, '得6金币', '得80金币')
                    self.states(c, [current, initial.clone(board), initial.clone(board)])
                    self.stop_after(c, 'confirm_standard_environment_1')
                    with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaises(Stopped):
                        run_standard(c)
                    saved = StandardSession(store.path).data
                    self.assertEqual(saved['actions'][-1]['action'], 'confirm_standard_environment_1')
                    self.assertEqual(saved['actions'][-1]['decision']['parameters']['star'], 2)
                    self.assertTrue(saved['initial_environment']['selection_accepted'])
                    c.window.click.assert_called_once()
                else:
                    self.states(c, [current, current])
                    with patch('autohsr.currency_wars_replay.save_sample'):
                        try:
                            result = run_standard(c)
                        except Stopped:
                            result = None
                    saved = StandardSession(store.path).data
                    self.assertIsNotNone(result)
                    self.assertEqual(result.status, 'partial')
                    self.assertEqual(saved['actions'][-1], last)
                    self.assertEqual(saved['action_status'], 'needs_observation')
                    c.window.click.assert_not_called()

    def test_next_plane_environment_keeps_initial_origin_and_waits_for_its_own_board(self):
        with tempfile.TemporaryDirectory() as folder:
            c, _, store = self.context(folder)
            board, history = initial.fixture(c.report.run_dir)
            initial.arrive(c.report.run_dir, board, history)
            store.data.update(history, expected_board='2-1')
            original = deepcopy(history['initial_environment'])
            start_id = len(store.data['actions'])
            for name, expected, target in (
                ('start_standard_node', 'standard_node_entered', ['1-7', 17, 100, 3]),
                ('continue_standard_node', 'standard_node_advanced', ['1-7', start_id]),
                ('advance_standard_next_plane', 'standard_plane_entered', ['1-7', start_id, '2-1']),
            ):
                entry = store.pending(name, 0, c.evidence(board, 'before-'+name), expected)
                entry.update(status='verified', target=target, after=str(c.evidence(board, 'after-'+name)))
                if name == 'continue_standard_node':
                    entry['feedback'] = dict(page_kind='plane_map', node='2-1')
            store.persist()
            selected = environment((1,), True)
            following_board = initial.clone(board)
            change_text(following_board, '1-1', '2-1')
            self.states(c, [environment(), selected, initial.clone(selected), board,
                            following_board, initial.clone(following_board)])
            snapshot = c.snapshot
            capture_times = count()
            start = board.captured_at - 1

            def successive_frames():
                frame = snapshot()
                frame.captured_at = start + next(capture_times) / 100
                return frame

            c.snapshot = successive_frames
            self.stop_after(c, 'confirm_standard_environment_1')
            c.window.emergency_pressed.return_value = False
            c.window.click.side_effect = lambda *_args, before_send: before_send()
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaisesRegex(Stopped, 'verified synthetic boundary'):
                run_standard(c)

            saved = StandardSession(store.path).data
            select, confirm = saved['actions'][-2:]
            self.assertEqual((select['action'], confirm['action']),
                             ('select_standard_environment_1', 'confirm_standard_environment_1'))
            for action in (select, confirm):
                self.assertEqual((action['status'], action['target']), ('verified', ['2-1']))
            self.assertEqual(saved['initial_environment'], original)
            self.assertNotIn('expected_board', saved)
            self.assertEqual(c.window.click.call_count, 2)
            self.assertEqual(next(capture_times), 6)
            with self.assertRaises(AutomationError):
                next_action(selected, session=saved)

    def test_context_rejects_current_proposal_with_different_durable_effect(self):
        for variant in ('changed_pending_effect', 'changed_prior_effect', 'equivalent_format'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                c, _, store = self.context(folder)
                c.currency_standard_session = store
                scene = environment((1,), True)
                if variant == 'changed_prior_effect':
                    self.stage_environment(c, store, environment(), selected=scene)
                    change_text(scene, '随机2星2费', '随机3星2费')
                self.states(c, [scene])
                scene = c.snapshot()
                planned = self.stage_environment(c, store, scene)
                original = store.path.read_bytes()
                if variant == 'changed_pending_effect':
                    change_text(scene, '随机2星2费', '随机3星2费')
                elif variant == 'equivalent_format':
                    change_text(scene, '随机属性加成。', '随机属性加成')
                current = next_action(scene)
                self.assertEqual(current.intent, planned.intent)
                if variant == 'equivalent_format':
                    self.assertNotEqual(current.details, planned.details)
                    Context.currency_standard_input(c, scene, current)
                    c.window.click.assert_called_once()
                else:
                    with self.assertRaises(AutomationError):
                        Context.currency_standard_input(c, scene, current)
                    c.window.click.assert_not_called()
                self.assertEqual(store.path.read_bytes(), original)

    def test_native_environment_send_rechecks_source_after_window_and_evidence_reads(self):
        late_writes = ('late_pending', 'window_pending', 'window_same_size_pending', 'window_png', 'window_replaced_png')
        existing_mappings = ('mapped_pending_before_hold', 'mapped_image_before_hold') if os.name == 'nt' else ()
        cases = ('valid', 'valid_read_only', 'epoch', 'stop', 'pending', 'image', 'late_pending', 'late_age', 'late_effect', 'late_focus',
                 'window_pending', 'window_same_size_pending', 'window_png', 'window_replaced_png',
                 'window_effect', 'window_fields', 'window_pixels', 'window_image_replaced', 'window_unfreeze',
                 'window_epoch', 'window_f10', 'final_hash_focus', 'final_revision_focus', *existing_mappings)
        for confirm in (False, True):
            for case in cases:
                with self.subTest(confirm=confirm, case=case), tempfile.TemporaryDirectory() as folder:
                    c, _, store = self.context(folder)
                    c.currency_standard_session = store
                    geometry = windows.Geometry(0, 0, 1920, 1080)
                    page = environment((1,), True) if confirm else environment()
                    page.geometry = geometry
                    self.states(c, [page])
                    scene = c.snapshot()
                    captured_image = scene.image
                    if case == 'valid_read_only':
                        captured_image.setflags(write=False)
                    original_writeable = captured_image.flags.writeable
                    original_pixel = int(captured_image[0, 0, 0])
                    choice = self.stage_environment(c, store, scene)
                    expected_record = store.path.read_bytes()
                    before = Path(store.data['actions'][-1]['before'])
                    expected_image = before.read_bytes()
                    now = scene.captured_at
                    reached_send = False
                    reached_last_guard = False
                    denied_write = False
                    denied_pixel_write = False
                    mapping = None
                    pixel_checks = revision_checks = 0

                    def attempt_write(operation):
                        nonlocal denied_write
                        try:
                            operation()
                        except PermissionError:
                            denied_write = True
                            return False
                        return True

                    def change_pending():
                        nonlocal expected_record
                        record = json.loads(expected_record)
                        record['actions'][-1]['decision']['parameters']['star'] = 3
                        changed = json.dumps(record).encode('utf-8')
                        if attempt_write(lambda: store.path.write_bytes(changed)):
                            expected_record = changed

                    def native_boundary(_):
                        nonlocal reached_send, mapping
                        if reached_send:
                            return 0x8000 if case == 'window_f10' and reached_last_guard else 0
                        reached_send = True
                        if case in existing_mappings:
                            path = store.path if case == 'mapped_pending_before_hold' else before
                            with path.open('r+b') as writer:
                                mapping = mmap.mmap(writer.fileno(), 0, access=mmap.ACCESS_WRITE)
                        elif case == 'epoch':
                            c.runner.input_epoch += 1
                        elif case == 'stop':
                            c.runner.stop_requested = True
                        elif case == 'pending':
                            change_pending()
                        elif case == 'image':
                            scene.image[0, 0, 0] = 1
                        return 0

                    def read_evidence(*args):
                        nonlocal now
                        result = original_evidence(*args)
                        if reached_send and case == 'late_pending':
                            change_pending()
                        elif reached_send and case == 'late_age':
                            now += 9
                        return result

                    def read_pending(*args):
                        result = original_pending(*args)
                        if reached_send and case == 'late_effect':
                            change_text(scene, '随机2星2费', '随机3星2费')
                        elif reached_send and case == 'late_focus':
                            user32.GetForegroundWindow.return_value = 72
                        return result

                    def pixel_hash(image):
                        nonlocal pixel_checks
                        if reached_send and image is captured_image:
                            pixel_checks += 1
                            if case == 'final_hash_focus' and pixel_checks == 2:
                                user32.GetForegroundWindow.return_value = 72
                        return _pixels(image)

                    def revision(path):
                        nonlocal revision_checks
                        if reached_send:
                            revision_checks += 1
                            if case == 'final_revision_focus' and revision_checks == 3:
                                user32.GetForegroundWindow.return_value = 72
                        return file_revision(path)

                    def foreground():
                        nonlocal reached_last_guard, expected_record, expected_image, denied_pixel_write
                        if reached_send and not reached_last_guard:
                            reached_last_guard = True
                            if case == 'window_pending':
                                change_pending()
                            elif case == 'window_same_size_pending':
                                metadata = store.path.stat()
                                changed = expected_record.replace(b'"star": 2', b'"star": 3', 1)
                                self.assertEqual(json.loads(changed)['actions'][-1]['decision']['parameters']['star'], 3)
                                if attempt_write(lambda: store.path.write_bytes(changed)):
                                    expected_record = changed
                                    os.utime(store.path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                            elif case == 'window_png':
                                changed = expected_image + b'changed'
                                if attempt_write(lambda: before.write_bytes(changed)):
                                    expected_image = changed
                            elif case == 'window_replaced_png':
                                metadata = before.stat()
                                replacement = before.with_name('replacement.png')
                                replacement.write_bytes(expected_image)
                                os.utime(replacement, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                                attempt_write(lambda: replacement.replace(before))
                            elif case == 'window_effect':
                                change_text(scene, '随机2星2费', '随机3星2费')
                            elif case == 'window_fields':
                                scene.field_reads['synthetic.final.conflict'] = (None,)
                            elif case == 'window_pixels':
                                try:
                                    scene.image[0, 0, 0] = original_pixel + 1
                                except ValueError:
                                    denied_pixel_write = True
                            elif case == 'window_image_replaced':
                                scene.image = captured_image.copy()
                            elif case == 'window_unfreeze':
                                captured_image.setflags(write=True)
                            elif case == 'window_epoch':
                                c.runner.input_epoch += 1
                        return user32.GetForegroundWindow.return_value

                    def submit(count, *_):
                        self.assertEqual(user32.GetForegroundWindow.return_value, 71,
                                         'SendInput reached after foreground changed during source verification')
                        self.assertIs(scene.image, captured_image)
                        self.assertFalse(captured_image.flags.writeable)
                        self.assertEqual(captured_image[0, 0, 0], original_pixel)
                        if os.name == 'nt':
                            for path in (store.path, before):
                                with self.assertRaises(PermissionError), path.open('r+b'):
                                    pass
                        self.assertEqual(store.path.read_bytes(), expected_record)
                        self.assertEqual(before.read_bytes(), expected_image)
                        return count

                    game = windows.GameWindow.__new__(windows.GameWindow)
                    game.hwnd, game.path = 71, ''
                    c.window = game
                    c._focus_interrupted = Mock(side_effect=InputInterrupted('synthetic focus change'))
                    user32 = Mock()
                    user32.IsWindow.return_value = 1
                    user32.IsIconic.return_value = 0
                    user32.GetForegroundWindow.return_value = 71
                    user32.GetForegroundWindow.side_effect = foreground
                    user32.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__
                    user32.GetAsyncKeyState.side_effect = native_boundary
                    user32.SendInput.side_effect = submit
                    original_evidence, original_pending = initial.evidence_ref, store.require_pending
                    clock = SimpleNamespace(monotonic=lambda: now)
                    with patch.object(windows, 'user32', user32), patch.object(windows, 'geometry', return_value=geometry), \
                         patch('autohsr.currency_wars.time', clock), \
                         patch('autohsr.currency_wars_initial.evidence_ref', side_effect=read_evidence), \
                         patch('autohsr.currency_wars_initial._pixels', side_effect=pixel_hash), \
                         patch('autohsr.storage.file_revision', side_effect=revision), \
                         patch.object(store, 'require_pending', side_effect=read_pending):
                        try:
                            if case in ('valid', 'valid_read_only', 'window_pixels') or os.name == 'nt' and case in late_writes:
                                Context.currency_standard_input(c, scene, choice)
                                user32.SendInput.assert_called_once()
                                self.assertEqual(user32.SendInput.call_args.args[0], 3)
                                self.assertEqual(denied_write, case in late_writes)
                                self.assertEqual(denied_pixel_write, case == 'window_pixels')
                            elif case in existing_mappings:
                                with self.assertRaisesRegex(AutomationError, '无法保持只读'):
                                    Context.currency_standard_input(c, scene, choice)
                                user32.SendInput.assert_not_called()
                            elif case == 'window_f10':
                                with self.assertRaisesRegex(Stopped, 'F10'):
                                    Context.currency_standard_input(c, scene, choice)
                                user32.SendInput.assert_not_called()
                            else:
                                with self.assertRaises(AutomationError):
                                    Context.currency_standard_input(c, scene, choice)
                                user32.SendInput.assert_not_called()
                        finally:
                            if mapping is not None:
                                mapping.close()
                    self.assertTrue(reached_send)
                    if case.startswith('window_'):
                        self.assertTrue(reached_last_guard)
                    if case in ('final_hash_focus', 'final_revision_focus'):
                        self.assertEqual(user32.GetForegroundWindow.return_value, 72)
                        c._focus_interrupted.assert_called_once()
                    self.assertIsNone(c.last_scene)
                    self.assertEqual(captured_image.flags.writeable, original_writeable)
                    self.assertEqual(store.path.read_bytes(), expected_record)
                    self.assertEqual(before.read_bytes(), expected_image)
                    for path in (store.path, before):
                        with path.open('r+b'):
                            pass  # Both handles have been released on success or rejection.

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
