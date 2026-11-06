"""Use the calibrated layout through Runner, Context and fake native input."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_identity import installed_client
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_double_supply import ARRIVAL, FEEDBACK, INPUT, INTENTS
from autohsr.currency_wars_standard_encounter import record_start
from autohsr.currency_wars_standard_flow import StandardAction, run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_rewards import active_action, enter
from autohsr.currency_wars_standard_supply_refresh import (
    candidate_descriptors, digest, icon_template, table, valid_receipt,
)
from autohsr.models import AutomationError, EmptyCapture, Stopped
from autohsr.windows import GameWindow
from autohsr.tests import test_currency_wars_standard_encounter as encounter
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_supply_bundles as bundles
from autohsr.tests import test_currency_wars_supply_observation as layout
from autohsr.tests import test_currency_wars_supply_refresh as refresh


REFRESH, SELECT, CONFIRM = 'refresh_standard_supply', 'select_standard_supply', 'confirm_standard_supply'
PAIR = ('shoe', 'armor')


def modal(*, selected=None, quota=0, name=None, single=False):
    scene = layout.supply(selected=selected, single=single)
    if name is not None:
        scene.tokens = [replace(token, text=name) if token.text == '轮滑鞋' else token for token in scene.tokens]
    scene.tokens.append(encounter.UID)
    rewards.node(scene, '1-2')
    # Gold is hidden in the public modal and stays independently unobserved.
    trading.hud(scene, level=3, xp=(0, 6), deployment=(3, 3))
    refresh.quota(scene, quota)
    if quota:
        scene.image = cv2.resize(scene.image, (2560, 1440), interpolation=cv2.INTER_NEAREST)
        ref = icon_template()
        scene.image[1276:1276 + ref.shape[0], 1718:1718 + ref.shape[1]] = ref
    return scene


class StandardDoubleSupplyTests(unittest.TestCase):
    def play(self, *, stock=PAIR, worn=(), fault=None, with_refresh=False, custom_frames=None):
        sandbox = TemporaryDirectory(prefix='cw-double-')
        self.addCleanup(sandbox.cleanup)
        root = Path(sandbox.name)
        run = root / 'r'
        run.mkdir()
        executable = root / 'StarRail.exe'
        executable.touch()
        version = root / 'config.ini'
        version.write_text('[General]\ngame_version=4.6.0\n', encoding='utf-8')
        window = object.__new__(GameWindow)
        window.hwnd, window.path = 43021, str(executable)
        runner = Runner(Settings(ocr_confidence=.78), operation='currency_wars_standard', currency_resume=True)
        runner.report.run_dir = str(run)
        runner.wait_for_focus = Mock()
        context = Context(runner, window, Mock())
        now = 100.
        calls, injected = [], []
        board, _, session = rewards.supply_fixture(strategy='aglaea')
        store = StandardSession(root / 'currency-standard-session.json')
        store.begin(run, dict(rank_verified=True, rank=8, wealth=40))
        store.data.update(session, account_verified_run=str(run),
                          client=dict(installed_client(executable), verified_run=str(run), input_epoch=0))
        store.data['collection']['run_dir'] = str(run)
        original, arrival = store.data['actions']
        original['reward_basis']['run_dir'] = str(run)
        board = replace(board, captured_at=96., geometry=encounter.GEOMETRY)
        page = modal(quota=1, name='以太钻头') if with_refresh else modal()
        page = replace(page, captured_at=98., geometry=encounter.GEOMETRY)
        original['before'] = str(context.evidence(board, 'original_start'))
        record_start(store.data, original, board, 'before', str(run), 0, .78)
        arrival['after'] = str(context.evidence(page, 'original_arrival'))
        enter(store.data, StandardAction('continue_standard_node', 'standard_node_advanced', None, payload=('1-1', 0)),
              page, .78)
        self.assertIn(ARRIVAL, arrival)
        if fault == 'old_arrival':
            arrival.pop(ARRIVAL)
        store.persist()
        if fault == 'original_png':
            Path(arrival['after']).write_bytes(b'replaced synthetic PNG')
        after = bundles.board(board, stock)
        extra = dict(name='白厄', zone='bench', slot=6, star=1, tier=4,
                     traits=('测试',), equipment=(), eligible_zones=('front', 'back'))
        units = {slot: item['unit'] for slot, item in session['collection']['units'].items()}
        units['bench:6'] = extra
        frames = [modal(single=True) if fault == 'switched_layout' else page]
        if with_refresh:
            frames.extend((modal(), modal()))
        frames.extend(custom_frames if custom_frames is not None else (modal(selected=4), modal(selected=4), after, after))
        for cell in sorted((c for c in roster_cells(after) if c.state == 'occupied'),
                           key=lambda c: (c.zone != 'bench', c.zone, c.slot)):
            unit = units[f'{cell.zone}:{cell.slot}']
            gear = worn if unit['name'] == '白厄' else unit['equipment']
            panel = rewards.node(equipment.panel(unit, gear), '1-3')
            panel.tokens.append(encounter.UID)
            frames.extend((panel, after))
        frames = iter(frames)

        def active():
            return context.currency_standard_session.data

        def snapshot():
            nonlocal now
            now += .02
            frame = next(frames, None)
            if frame is None or isinstance(frame, EmptyCapture):
                context.last_scene = None
                raise EmptyCapture('synthetic blank')
            context.last_scene = replace(frame, tokens=list(frame.tokens), image=frame.image.copy(),
                                         geometry=encounter.GEOMETRY, captured_at=now)
            context.scene_epoch = runner.input_epoch
            return context.last_scene

        def checkpoint():
            if hasattr(context, 'currency_standard_session') and active()['reward']['status'] == 'verified':
                raise Stopped('synthetic delivery complete')
            if fault == 'selection_png' and not injected and hasattr(context, 'currency_standard_session'):
                selected = active()['actions'][-1]
                if selected['action'] == SELECT and selected['status'] == 'verified':
                    Path(selected[FEEDBACK][0]['evidence']['path']).write_bytes(b'tampered selected frame')
                    injected.append(fault)
            if fault in ('delivery_png', 'delivery_client') and not injected and hasattr(context, 'currency_standard_session'):
                pending = active()['actions'][-1]
                if pending['action'] == CONFIRM and pending['status'] == 'verified':
                    if fault == 'delivery_png':
                        Path(pending[FEEDBACK][0]['evidence']['path']).write_bytes(b'tampered return frame')
                    else:
                        active()['client']['sha256'] = 'f' * 64
                    injected.append(fault)

        def sleep(seconds):
            nonlocal now
            now += seconds if context.last_scene is not None else 61.

        context.checkpoint, context.snapshot, context.sleep = checkpoint, snapshot, sleep
        native = Mock()
        native.IsWindow.return_value, native.IsIconic.return_value = 1, 0
        native.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__
        native.GetForegroundWindow.return_value = window.hwnd

        def emergency(_key):
            if fault == 'receipt_f10' and injected:
                return 0x8001
            if fault == 'native_epoch' and active()['actions'][-1]['action'] == SELECT and not injected:
                if native.GetAsyncKeyState.call_count == 2:
                    runner.input_epoch += 1
                    injected.append(fault)
            return 0

        def send(count, _events, _size):
            pending = StandardSession(store.path).data['actions'][-1]
            self.assertEqual((pending['status'], count), ('pending', 3))
            calls.append(pending['action'])
            if fault == 'native_holds' and pending['action'] == CONFIRM:
                for name in [original['before'], arrival['after'], pending['before'], str(version), str(store.path)]:
                    path = Path(name)
                    raw = path.read_bytes()
                    with self.assertRaises(PermissionError):
                        path.write_bytes(b'write while native sending')
                    self.assertEqual(path.read_bytes(), raw)
                self.assertFalse(context.last_scene.image.flags.writeable)
                injected.append(fault)
            return count

        read_pending = StandardSession.require_pending

        def pending_after_late_event(instance, intent, epoch):
            nonlocal now
            saved = read_pending(instance, intent, epoch)
            if (fault in ('receipt_epoch', 'receipt_focus', 'receipt_f10', 'receipt_stale')
                    and intent == SELECT and instance.data['actions'][-1]['status'] == 'verified' and not injected):
                injected.append(fault)
                if fault == 'receipt_epoch':
                    runner.input_epoch += 1
                elif fault == 'receipt_focus':
                    native.GetForegroundWindow.return_value = window.hwnd + 1
                elif fault == 'receipt_stale':
                    now += 9
            return saved

        native.GetAsyncKeyState.side_effect = emergency
        native.SendInput.side_effect = send
        clock = SimpleNamespace(monotonic=lambda: now)
        error = None
        with (patch('autohsr.windows.user32', native), patch('autohsr.windows.geometry', return_value=encounter.GEOMETRY),
              patch('autohsr.windows.process_path', return_value=str(executable)),
              patch('autohsr.currency_wars.time', clock), patch('autohsr.currency_wars_standard_flow.time', clock),
              patch.object(StandardSession, 'require_pending', pending_after_late_event),
              patch('autohsr.currency_wars_replay.save_sample')):
            try:
                run_standard(context)
            except AutomationError as caught:
                error = caught
        data = StandardSession(store.path).data
        return SimpleNamespace(actions=data['actions'], reward=data['reward'], error=error,
                               calls=[action for action in calls if action in INTENTS], injected=injected)

    def test_native_refresh_selection_confirmation_then_both_in_stock(self):
        result = self.play(with_refresh=True, fault='native_holds')
        self.assertEqual(result.calls, [REFRESH, SELECT, CONFIRM], str(result.error))
        self.assertEqual(result.injected, ['native_holds'])
        self.assertIsInstance(result.error, Stopped)
        refresh_action, selected, confirmed = [action for action in result.actions if action['action'] in INTENTS]
        self.assertTrue(valid_receipt(refresh_action, result.actions))
        self.assertEqual((selected['target'][3], selected['target'][5]), (3, list(PAIR)))
        self.assertEqual(confirmed['reward_effect']['inventory_after'], {'shoe': 1, 'armor': 1})
        self.assertEqual(confirmed['reward_effect']['equipment_after'], [])
        self.assertEqual(ledger_status(result.actions), 'clear')
        for action in (refresh_action, selected, confirmed):
            self.assertEqual(len(action[FEEDBACK]), 2)
            self.assertIn(INPUT, action)

    def test_auto_worn_is_verified_only_with_exact_pair(self):
        for worn in (PAIR, PAIR[:1]):
            with self.subTest(worn=worn):
                result = self.play(stock=(), worn=worn)
                self.assertEqual(result.calls, [SELECT, CONFIRM], str(result.error))
                claim = next(action for action in result.actions if action['action'] == CONFIRM)
                self.assertIs(claim['reward_verified'], len(worn) == 2)
                self.assertEqual(ledger_status(result.actions), 'clear' if len(worn) == 2 else 'pending')

    def test_selection_never_confirms_a_changed_column_or_a_split_pair(self):
        wrong, partial = modal(selected=3), modal(selected=4, name='滑鞋')
        for frames in ([wrong, wrong], [modal(selected=4), EmptyCapture('flip'), partial]):
            with self.subTest(frames=len(frames)):
                result = self.play(custom_frames=frames)
                self.assertEqual(result.calls, [SELECT], str(result.error))
                self.assertEqual(result.actions[-1]['status'], 'unknown')
                self.assertNotIn(FEEDBACK, result.actions[-1])

    def test_original_arrival_last_epoch_or_selection_image_cannot_be_reused(self):
        for fault, calls in (('old_arrival', []), ('original_png', []), ('native_epoch', []), ('selection_png', [SELECT])):
            with self.subTest(fault=fault):
                result = self.play(fault=fault)
                self.assertEqual(result.calls, calls, str(result.error))
                self.assertIsInstance(result.error, AutomationError)
                self.assertNotIn(CONFIRM, result.calls)

    def test_late_feedback_publication_preserves_already_sent_pending_action(self):
        for fault in ('receipt_epoch', 'receipt_focus', 'receipt_f10', 'receipt_stale'):
            with self.subTest(fault=fault):
                result = self.play(fault=fault)
                self.assertEqual(result.calls, [SELECT], str(result.error))
                self.assertEqual(result.injected, [fault])
                self.assertIsInstance(result.error, AutomationError)
                self.assertEqual(result.actions[-1]['status'], 'pending')
                self.assertNotIn(FEEDBACK, result.actions[-1])

    def test_original_confirmed_return_must_survive_until_delivery_publication(self):
        for fault in ('delivery_png', 'delivery_client'):
            with self.subTest(fault=fault):
                result = self.play(fault=fault)
                self.assertEqual(result.calls, [SELECT, CONFIRM], str(result.error))
                self.assertEqual(result.injected, [fault])
                self.assertEqual(result.reward['status'], 'unit_verifying')
                self.assertEqual(ledger_status(result.actions), 'pending')

    def test_complete_names_bind_layout_but_unknown_pair_never_becomes_one(self):
        _, _, session = rewards.supply_fixture(strategy='aglaea')
        known = table(modal())
        self.assertEqual(known[3]['item'], list(PAIR))
        self.assertIsNone(table(modal(name='滑鞋'))[3]['item'])
        self.assertNotEqual(active_action(modal(name='滑鞋'), session).payload[3], 3)
        old = [{key: value for key, value in row.items() if key != 'layout'} for row in known]
        self.assertNotEqual(digest(candidate_descriptors(known)), digest(candidate_descriptors(old)))

    def test_raised_name_row_or_original_double_arrival_blocks_single_layout_fallback(self):
        partial = modal(single=True)
        for index, token in enumerate(partial.tokens):
            if token.text in layout.ROLES:
                x1, _, x2, _ = token.box
                y1, y2 = (.468, .488) if token.text == layout.ROLES[0] else (.499, .509)
                partial.tokens[index] = replace(token, box=(x1, y1, x2, y2))
        with self.assertRaisesRegex(AutomationError, '未退回单件布局'):
            table(partial)
        result = self.play(fault='switched_layout')
        self.assertEqual(result.calls, [])
        self.assertEqual(len(result.actions), 2)
