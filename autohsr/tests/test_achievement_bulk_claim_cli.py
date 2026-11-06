"""Formal bulk achievement claim CLI with synthetic capture and native send receipts."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import ctypes
from hashlib import sha256
import io
from itertools import count
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.__main__ import main
from autohsr.achievement_bulk_claim import AchievementBulkClaim
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import FocusLost, Scene, Token
from autohsr.tests.test_achievement_pages import gold_controls, label, overview, receipt_rows
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, _Window
from autohsr.windows import Geometry, INPUT


OPERATION = 'achievement_bulk_claim'
CLAIM = label('一键领取奖励', .825, .898)
CONFIRM = label('确认', .502, .926)


def overview_scene(*, claim=False, marked=False):
    tokens = [ACCOUNT, *overview(), label('911', .373, .910)]
    if claim:
        tokens.append(CLAIM)
    pixels = gold_controls(CLAIM) if claim else gold_controls()
    if marked:
        if claim:
            pixels[187:209, 500:520] = (12, 28, 225)
            pixels[190:203, 507:510] = 245
        else:
            pixels[187:209, 500:520] = (95, 65, 30)
    return Scene(tokens, pixels)


def receipt_scene():
    rows = [label('东山再起', .176, .258), label('超大杯', .166, .408)]
    return Scene([ACCOUNT, label('成就奖励', .50, .114), label('与你同行的回忆', .127, .193),
                  *rows, label('总计获得', .466, .836), label('×20', .55, .838), CONFIRM],
                 receipt_rows(*rows))


def overlay_scene(background):
    return Scene([*background.tokens, label('获得物品', .50, .160), label('20', .50, .548),
                  label('星琼', .50, .578), label('点击空白处关闭', .50, .735)],
                 background.image)


def wallet_scene(value):
    pixels = gold_controls()
    pixels[29:44, 1092:1111] = 235
    pixels[45:58, 1088:1114] = (230, 166, 75)
    return Scene([ACCOUNT, label('跃迁', .066, .048), label('沧海萃珠', .080, .075),
                  label('角色活动跃迁', .22, .175), label('131', .816, .060),
                  label(str(value), .889, .060)], pixels)


class AchievementBulkClaimCliTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.config = self.root / 'config.json'
        Settings(overlay_logs=True, auto_launch=True, ocr_confidence=.93).save(self.config)
        self.original_config = self.config.read_bytes()

    def run_cli(self, *, after_claim=None, short_at=None, lose_foreground=False, stop_confirm=False,
                wallet=False, marked=False, change_receipt=False, publish=None, wait_for_foreground=False,
                keep_overlay=False, stop_at_final_guard=False):
        self.events = []
        self.actions = []
        clicks = 0
        emergency = False
        ready = overview_scene(claim=True, marked=marked)
        receipt = receipt_scene() if after_claim is None else after_claim
        returned = overview_scene(marked=marked)
        overlay = overlay_scene(returned)

        def frames():
            if wallet:
                yield wallet_scene(4508)
                yield wallet_scene(4508)
            while clicks == 0:
                yield ready
            while clicks == 1:
                yield receipt
            yield overlay
            yield overlay
            while keep_overlay:
                yield overlay
            yield returned
            yield returned
            while True:
                yield wallet_scene(4528) if wallet else returned

        self.window = window = _Window(frames())
        window.geometry = Geometry(0, 0, 1280, 720)
        window.guard.return_value = window.geometry
        executable = self.root / 'StarRail.exe'
        executable.touch()
        executable.with_name('config.ini').write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        window.current_executable = Mock(return_value=executable)
        original_save = Runner._save_run_report

        def save_report(runner, directory, *args, **kwargs):
            if publish is not None:
                publish(window, executable)
            return original_save(runner, directory, *args, **kwargs)
        if lose_foreground:
            window.guard.side_effect = FocusLost('synthetic window is not foreground')

        def submit(length, items, _size):
            nonlocal clicks
            events = ctypes.cast(items, ctypes.POINTER(INPUT))
            self.events.append(tuple((events[i].mi.dwFlags, events[i].mi.dx, events[i].mi.dy)
                                     for i in range(length)))
            if length == 3:
                clicks += 1
                if clicks == short_at:
                    return length - 1
            return length

        user32 = SimpleNamespace(GetAsyncKeyState=Mock(side_effect=lambda key: int(emergency and key == 0x79)),
                                 GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1280, 79: 720}.__getitem__),
                                 SendInput=Mock(side_effect=submit))
        kernel32 = SimpleNamespace(CreateMutexW=Mock(return_value=1), OpenMutexW=Mock(return_value=None),
                                   CloseHandle=Mock())
        clock = SimpleNamespace(monotonic=count(100., .04).__next__)
        output, logs = io.StringIO(), io.StringIO()
        original_input = Context.achievement_bulk_input
        original_guard = AchievementBulkClaim._guard

        def achievement_input(context, scene, action):
            self.actions.append(action)
            if action == 'confirm' and change_receipt:
                run = Path(context.report.run_dir)
                source = next(run.glob('*_achievement_receipt.png'))
                source.write_bytes(b'replaced')
            return original_input(context, scene, action)

        def guard_claim(claim, *, installation=False):
            if installation or self.actions != ['claim'] or emergency:
                return original_guard(claim, installation=installation)

            def lose_at_return(expected=None):
                nonlocal emergency
                if expected is not None:
                    self.assertEqual(expected, window.geometry)
                    emergency = True
                return window.geometry

            with patch.object(window, 'guard', side_effect=lose_at_return):
                return original_guard(claim, installation=installation)

        if stop_confirm:
            original_send = window.send

            def send(events, geometry, *, before_send=None, before_submit=None):
                def stop_at_submit():
                    nonlocal emergency
                    emergency = self.actions[-1:] == ['confirm']
                    if before_submit is not None:
                        before_submit()

                return original_send(events, geometry, before_send=before_send, before_submit=stop_at_submit)

            window.send = send

        with ExitStack() as stack:
            for target, value in (('autohsr.app.ROOT', self.root), ('autohsr.app.time', clock),
                                  ('autohsr.achievement_bulk_claim.time', clock),
                                  ('autohsr.windows.user32', user32), ('autohsr.windows.kernel32', kernel32)):
                stack.enter_context(patch(target, value))
            for target, kwargs in (
                    ('autohsr.workflow_lease._kernel', dict(return_value=kernel32)),
                    ('autohsr.app.C.get_last_error', dict(return_value=0)),
                    ('autohsr.app.threading.Thread', {}),
                    ('autohsr.app.is_elevated', dict(return_value=False)),
                    ('autohsr.app.Vision', dict(side_effect=window.vision)),
                    ('autohsr.notify_runtime.hooks', dict(side_effect=AssertionError('no notifications'))),
                    ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay'))),
                    ('autohsr.app.Runner._arm_hotkeys', {}),
                    ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no startup')))):
                stack.enter_context(patch(target, **kwargs))
            self.find_game = stack.enter_context(patch('autohsr.app.find_game', return_value=window))
            stack.enter_context(patch.object(Context, 'sleep', lambda ctx, _seconds: ctx.checkpoint()))
            stack.enter_context(patch.object(Context, 'achievement_bulk_input', achievement_input))
            if stop_at_final_guard:
                stack.enter_context(patch.object(AchievementBulkClaim, '_guard', guard_claim))
            stack.enter_context(patch.object(Runner, '_save_run_report', save_report))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(logs))
            if wait_for_foreground:
                def handoff(current, checkpoint):
                    self.assertIs(current, window)
                    self.assertFalse(self.events)
                    checkpoint()
                    return current.geometry

                self.handoff = stack.enter_context(patch('autohsr.screenshot_tool._foreground_geometry',
                                                         side_effect=handoff))
                run = Runner(Settings.load(self.config), operation=OPERATION, observation_wait_for_foreground=True)
                report = run.run()
                print(json.dumps(report.to_dict()))
                exit_code = 0 if report.status == 'success' else 1
            else:
                exit_code = main(['--achievement-bulk-claim', '--config', str(self.config)])

        self.assertTrue(output.getvalue(), logs.getvalue())
        report = json.loads(output.getvalue())
        self.assertEqual(report['operation'], OPERATION)
        self.assertEqual((report['stamina_spent'], report['stamina_pending'], report['battle_completed']), (0, 0, 0))
        self.assertEqual(json.loads((Path(report['run_dir']) / 'report.json').read_text('utf8')), report)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertNotIn(ACCOUNT.text[4:], output.getvalue() + logs.getvalue())
        for name in ('focus', 'move', 'key', 'scroll', 'drag'):
            getattr(window, name).assert_not_called()
        return exit_code, report

    def test_claim_confirms_once_and_returns_with_unknown_jade_attribution(self):
        exit_code, report = self.run_cli()
        result = report[OPERATION]
        self.assertEqual((exit_code, report['status']), (0, 'success'), report['error'])
        self.assertEqual(self.actions, ['claim', 'confirm'])
        self.assertEqual(len(self.events), 2)
        for batch, target in zip(self.events, (CLAIM, CONFIRM)):
            self.assertEqual(tuple(flags for flags, _, _ in batch), (0xC001, 0x0002, 0x0004))
            _, x, y = batch[0]
            self.assertAlmostEqual(x / 65535, target.center[0], delta=.002)
            self.assertAlmostEqual(y / 65535, target.center[1], delta=.002)
        self.assertEqual((result['bulk_input'], result['confirm_input']), ('sent', 'sent'))
        self.assertEqual((result['receipt_total'], result['overlay_quantity']), (20, 20))
        self.assertTrue(result['overview_return_verified'])
        self.assertIsNone(result['jade_attributed'])

    def test_foreground_loss_or_f10_prevents_unsubmitted_click(self):
        exit_code, report = self.run_cli(lose_foreground=True)
        self.assertEqual(exit_code, 1)
        self.assertEqual(report[OPERATION]['bulk_input'], 'not_sent')
        self.assertEqual(self.actions, [])
        self.assertEqual(self.events, [])

        exit_code, report = self.run_cli(stop_confirm=True)
        self.assertEqual((exit_code, report['status']), (130, 'stopped'))
        self.assertEqual(self.actions, ['claim', 'confirm'])
        self.assertEqual(len(self.events), 1)
        self.assertEqual(report[OPERATION]['bulk_input'], 'sent')
        self.assertEqual(report[OPERATION]['confirm_input'], 'not_sent')
        self.assertEqual(report[OPERATION]['receipt_total'], 20)
        self.assertIsNone(report[OPERATION]['overlay_quantity'])

    def test_short_send_does_not_retry_or_confirm_and_blocks_the_next_run(self):
        exit_code, report = self.run_cli(after_claim=overview_scene(claim=True), short_at=1)
        result = report[OPERATION]
        self.assertEqual(exit_code, 1)
        self.assertEqual(self.actions, ['claim'])
        flags = [tuple(flag for flag, _, _ in batch) for batch in self.events]
        self.assertEqual(flags, [(0xC001, 0x0002, 0x0004), (0x0004,)])
        self.assertEqual((result['bulk_input'], result['confirm_input']), ('unknown', 'not_sent'))
        self.assertIsNone(result['receipt_total'])
        original_run = Path(report['run_dir'])
        original_sources = {path: path.read_bytes() for path in original_run.glob('achievement-bulk-*.json')}
        self.assertTrue(original_sources)

        exit_code, repeated = self.run_cli()
        self.assertEqual((exit_code, repeated['status']), (1, 'failed'))
        self.assertNotEqual(repeated['run_dir'], report['run_dir'])
        self.assertIn('已有未决成就领奖意图', repeated['error'])
        self.assertEqual(repeated[OPERATION]['bulk_input'], 'not_sent')
        self.find_game.assert_not_called()
        self.assertIsNone(self.window.frame)
        self.assertEqual(self.actions, [])
        self.assertEqual(self.events, [])
        self.assertEqual({path: path.read_bytes() for path in original_sources}, original_sources)

    def test_generic_overlay_is_not_a_receipt_even_with_confirm_text_behind_it(self):
        exit_code, report = self.run_cli(after_claim=overlay_scene(receipt_scene()))
        result = report[OPERATION]
        self.assertEqual(exit_code, 1)
        self.assertEqual(self.actions, ['claim'])
        self.assertEqual(len(self.events), 1)
        self.assertEqual((result['bulk_input'], result['confirm_input']), ('sent', 'not_sent'))
        self.assertIsNone(result['receipt_total'])
        self.assertIsNone(result['overlay_quantity'])
        self.assertFalse(result['overview_return_verified'])

    def test_attributed_overlay_timeout_preserves_feedback_and_blocks_a_new_attempt(self):
        exit_code, report = self.run_cli(keep_overlay=True)
        result = report[OPERATION]
        self.assertEqual((exit_code, report['status']), (1, 'partial'))
        self.assertEqual(self.actions, ['claim', 'confirm'])
        self.assertEqual(len(self.events), 2)
        self.assertEqual((result['bulk_input'], result['confirm_input']), ('sent', 'sent'))
        self.assertEqual((result['receipt_total'], result['overlay_quantity']), (20, 20))
        self.assertIn('overlay', result['samples'])
        self.assertNotIn('return', result['samples'])
        self.assertFalse(result['overview_return_verified'])
        self.assertFalse(result['overview_controls_cleared'])
        self.assertIsNone(result['jade_attributed'])
        original = Path(report['run_dir'])
        self.assertFalse((original / 'achievement-bulk-terminal.json').exists())
        saved = (original / 'report.json').read_bytes()

        exit_code, blocked = self.run_cli()
        self.assertEqual((exit_code, blocked['status']), (1, 'failed'))
        self.assertIn('已有未决成就领奖意图', blocked['error'])
        self.find_game.assert_not_called()
        self.assertEqual(self.events, [])
        self.assertEqual((original / 'report.json').read_bytes(), saved)

    def test_stop_during_last_geometry_check_prevents_the_first_click(self):
        code, report = self.run_cli(stop_at_final_guard=True)
        self.assertEqual((code, report['status'], self.events), (130, 'stopped', []), report['error'])
        self.assertEqual(report[OPERATION]['bulk_input'], 'not_sent')
        self.assertTrue(report[OPERATION]['stopped'])
        original = Path(report['run_dir'])
        self.assertEqual(json.loads((original / 'achievement-bulk-send.json').read_bytes())['outcome'], 'not_sent')

        code, repeated = self.run_cli(lose_foreground=True)
        self.assertEqual(code, 1)
        self.find_game.assert_called_once()
        self.assertEqual(self.events, [])
        self.assertFalse((self.root / 'runs' / 'achievement-bulk-pending.json').exists())
        self.assertNotIn('已有未决成就领奖意图', repeated['error'])

    def test_stop_after_attributed_overlay_preserves_observed_reward_and_the_pending_gate(self):
        save = AchievementBulkClaim._save

        def stop_after_overlay(claim, name, frames):
            rows = save(claim, name, frames)
            if name == 'overlay':
                claim.reader.window.emergency_pressed = lambda: True
            return rows

        with patch.object(AchievementBulkClaim, '_save', stop_after_overlay):
            exit_code, report = self.run_cli()
        result = report[OPERATION]
        self.assertEqual((exit_code, report['status']), (130, 'stopped'))
        self.assertTrue(result['stopped'])
        self.assertEqual(len(self.events), 2)
        self.assertEqual((result['bulk_input'], result['confirm_input']), ('sent', 'sent'))
        self.assertEqual((result['receipt_total'], result['overlay_quantity']), (20, 20))
        self.assertFalse(result['overview_return_verified'])
        self.assertTrue((self.root / 'runs' / 'achievement-bulk-pending.json').exists())
        self.assertFalse((Path(report['run_dir']) / 'achievement-bulk-terminal.json').exists())

    def test_same_wallet_page_records_delta_without_claiming_exclusive_attribution(self):
        exit_code, report = self.run_cli(wallet=True, marked=True)
        result = report[OPERATION]
        self.assertEqual((exit_code, report['status']), (0, 'success'), report['error'])
        self.assertEqual((result['jade_balance_before'], result['jade_balance_after'], result['jade_balance_delta']),
                         (4508, 4528, 20))
        self.assertIsNone(result['jade_attributed'])
        self.assertTrue(result['overview_controls_cleared'])
        original = Path(report['run_dir'])
        self.assertTrue((original / 'achievement-bulk-terminal.json').exists())

        exit_code, repeated = self.run_cli(lose_foreground=True)
        self.assertEqual(exit_code, 1)
        self.assertTrue(self.find_game.called)
        self.assertNotIn('已有未决成就领奖意图', repeated['error'])
        self.assertFalse((self.root / 'runs' / 'achievement-bulk-pending.json').exists())
        self.assertTrue((original / 'achievement-bulk-intent.json').exists())

    def test_mutated_receipt_prevents_confirmation(self):
        exit_code, report = self.run_cli(change_receipt=True)
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(report[OPERATION]['confirm_input'], 'not_sent')
        self.assertEqual(report[OPERATION]['receipt_total'], 20)

    def test_terminal_report_with_changed_source_still_blocks_a_fresh_run(self):
        exit_code, report = self.run_cli(marked=True)
        self.assertEqual((exit_code, report['status']), (0, 'success'), report['error'])
        proof = report[OPERATION]['samples']['return'][0]['file']
        (Path(report['run_dir']) / proof).write_bytes(b'changed')

        exit_code, repeated = self.run_cli()
        self.assertEqual((exit_code, repeated['status']), (1, 'failed'))
        self.assertIn('已有未决成就领奖意图', repeated['error'])
        self.find_game.assert_not_called()
        self.assertFalse(self.events)

    def test_confirmation_send_changed_before_publication_stays_pending(self):
        changed = {}

        def replace_send(_window, _executable):
            path = next((self.root / 'runs').glob('*/achievement-bulk-confirm-send.json'))
            sent = json.loads(path.read_bytes())
            sent['sent_at'] += .01
            raw = json.dumps(sent, sort_keys=True).encode()
            path.write_bytes(raw)
            changed[path] = raw

        exit_code, report = self.run_cli(marked=True, publish=replace_send)
        self.assertEqual((exit_code, report['status']), (1, 'partial'), report['error'])
        self.assertEqual(len(self.events), 2)
        self.assertEqual(report[OPERATION]['confirm_input'], 'sent')
        self.assertEqual(report[OPERATION]['overlay_quantity'], 20)
        self.assertIsNone(report[OPERATION]['jade_attributed'])
        original = Path(report['run_dir'])
        self.assertFalse((original / 'achievement-bulk-terminal.json').exists())
        self.assertEqual({path: path.read_bytes() for path in changed}, changed)

        exit_code, blocked = self.run_cli()
        self.assertEqual((exit_code, blocked['status']), (1, 'failed'))
        self.find_game.assert_not_called()
        self.assertEqual(self.events, [])

    def test_terminal_digest_cannot_vouch_for_a_mismatched_send(self):
        exit_code, report = self.run_cli(marked=True)
        self.assertEqual((exit_code, report['status']), (0, 'success'), report['error'])
        original = Path(report['run_dir'])
        intent = original / 'achievement-bulk-confirm-intent.json'
        send = original / 'achievement-bulk-confirm-send.json'
        terminal = original / 'achievement-bulk-terminal.json'
        original_intent, original_send = intent.read_bytes(), send.read_bytes()
        original_terminal = terminal.read_bytes()
        unbound = json.dumps(dict(json.loads(original_intent), previous_send='0' * 64)).encode()

        for name, intent_raw, send_raw in (
            ('invalid JSON', original_intent, b'changed'),
            ('unknown send', original_intent, json.dumps(dict(json.loads(original_send), outcome='unknown')).encode()),
            ('wrong intent', original_intent, json.dumps(dict(json.loads(original_send), intent='0' * 64)).encode()),
            ('wrong predecessor', unbound,
             json.dumps(dict(json.loads(original_send), intent=sha256(unbound).hexdigest())).encode()),
        ):
            with self.subTest(name=name):
                intent.write_bytes(intent_raw)
                send.write_bytes(send_raw)
                record = json.loads(original_terminal)
                record['journal'].update({intent.name: sha256(intent_raw).hexdigest(),
                                          send.name: sha256(send_raw).hexdigest()})
                terminal.write_bytes(json.dumps(record).encode())
                marker = self.root / 'runs' / 'achievement-bulk-pending.json'
                before = {path: path.read_bytes() for path in (intent, send, terminal, original / 'report.json', marker)}

                exit_code, blocked = self.run_cli()
                self.assertEqual((exit_code, blocked['status']), (1, 'failed'))
                self.assertIn('已有未决成就领奖意图', blocked['error'])
                self.find_game.assert_not_called()
                self.assertEqual(self.events, [])
                self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_zero_send_terminal_cannot_discard_existing_sent_records(self):
        exit_code, report = self.run_cli(marked=True)
        self.assertEqual((exit_code, report['status']), (0, 'success'), report['error'])
        original = Path(report['run_dir'])
        saved = original / 'report.json'
        terminal = original / 'achievement-bulk-terminal.json'
        report[OPERATION].update(bulk_input='not_sent', confirm_input='not_sent', receipt_total=None,
                                 overlay_quantity=None, overview_return_verified=False, overview_controls_cleared=False)
        raw = json.dumps(report).encode()
        saved.write_bytes(raw)
        record = dict(json.loads(terminal.read_bytes()), report=sha256(raw).hexdigest(), journal={})
        terminal.write_bytes(json.dumps(record).encode())

        exit_code, blocked = self.run_cli()
        self.assertEqual((exit_code, blocked['status']), (1, 'failed'))
        self.assertIn('已有未决成就领奖意图', blocked['error'])
        self.find_game.assert_not_called()
        self.assertEqual(self.events, [])
        self.assertEqual(saved.read_bytes(), raw)
        self.assertTrue((self.root / 'runs' / 'achievement-bulk-pending.json').exists())

    def test_zero_send_terminal_with_intent_but_no_receipt_stays_pending(self):
        exit_code, report = self.run_cli(stop_at_final_guard=True)
        self.assertEqual((exit_code, report['status']), (130, 'stopped'))
        original = Path(report['run_dir'])
        terminal = original / 'achievement-bulk-terminal.json'
        terminal_bytes = terminal.read_bytes()
        (original / 'achievement-bulk-send.json').unlink()

        exit_code, blocked = self.run_cli()
        self.assertEqual((exit_code, blocked['status']), (1, 'failed'))
        self.assertIn('已有未决成就领奖意图', blocked['error'])
        self.find_game.assert_not_called()
        self.assertEqual(self.events, [])
        self.assertEqual(terminal.read_bytes(), terminal_bytes)

    def test_complete_weak_uid_is_a_conflict_even_below_the_settings_floor(self):
        receipt = receipt_scene()
        receipt.tokens.append(Token(OTHER.text, .71, OTHER.box))
        exit_code, report = self.run_cli(after_claim=receipt)
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(report[OPERATION]['confirm_input'], 'not_sent')
        self.assertIsNone(report[OPERATION]['receipt_total'])

    def test_desktop_opt_in_waits_for_foreground_before_capturing(self):
        code, report = self.run_cli(wait_for_foreground=True)
        self.handoff.assert_called_once()
        self.assertEqual((code, report['status'], len(self.events)), (0, 'success', 2))

    def test_same_version_installation_changes_revoke_current_account_proof(self):
        def change(_window, executable):
            executable.with_name('config.ini').write_text(
                '[General]\ngame_version=4.6.0\n; revised source\n', encoding='utf8')

        code, report = self.run_cli(marked=True, publish=change)
        record = report[OPERATION]
        self.assertEqual((code, report['status'], record['account_verified']), (1, 'partial', False))
        self.assertEqual((record['bulk_input'], record['confirm_input']), ('sent', 'sent'))
        self.assertTrue((self.root / 'runs' / 'achievement-bulk-pending.json').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows installation read lock')
    def test_installation_read_lock_is_held_during_final_report_publication(self):
        original = Path.replace
        verified = []

        def replace_report(path, destination):
            if path.name == 'report.tmp':
                with self.assertRaises(PermissionError), (self.root / 'config.ini').open('ab'):
                    pass
                verified.append(True)
            return original(path, destination)

        with patch.object(Path, 'replace', new=replace_report):
            code, report = self.run_cli()
        self.assertEqual((code, report['status'], verified), (0, 'success', [True]))
