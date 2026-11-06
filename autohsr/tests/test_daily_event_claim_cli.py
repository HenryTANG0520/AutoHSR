"""Exercise the explicit command with the real Runner and a fake Win32 window."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import app
from autohsr.__main__ import main
from autohsr.daily_event_claim_flow import replace_file
from autohsr.models import Token
from autohsr.tests import test_daily_event_claim as cases


class DailyEventClaimCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = cases.DailyEventClaimTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for module in ('autohsr.daily_event_claim', 'autohsr.challenge_pages'):
            self.enterContext(patch(module + '.time', time))
        self.window = self.fixture.window
        self.window.capture = Mock(side_effect=self.capture)
        self.enterContext(patch.object(app, 'ROOT', self.fixture.root))
        self.enterContext(patch.object(app, 'find_game', return_value=self.window))
        self.enterContext(patch.object(app, 'is_elevated', return_value=False))
        self.enterContext(patch.object(app, 'Vision', return_value=SimpleNamespace(
            confidence=.65, read=lambda image, _: self.scene, _read_field=self.field)))
        self.frames = iter(())

    def capture(self):
        self.scene, amount = next(self.frames)
        self.scene.tokens.append(cases.ACCOUNT)
        self.scene.geometry = self.fixture.geometry
        self.amount = amount
        return self.scene.image, self.fixture.geometry

    def field(self, _image, pattern):
        if self.amount is not None and pattern == cases.claim._NUMBER_PATTERN:
            return Token(str(self.amount), .97, (0, 0, 1, 1))
        return None

    def invoke(self, *flags):
        config = self.fixture.root / 'settings.json'
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            code = main(['--daily-event-claim', '4', '--config', str(config), '--game-path', str(self.fixture.exe), *flags])
        self.close_notice = stderr.getvalue()
        data = json.loads(stdout.getvalue())
        self.assertEqual(json.loads((Path(data['run_dir']) / 'report.json').read_text(encoding='utf8')), data)
        self.assertNotIn(cases.ACCOUNT.text, stdout.getvalue())
        self.assertNotIn(str(self.fixture.exe), stdout.getvalue())
        self.assertFalse(config.exists())
        return code, data

    def test_official_entry_observes_one_popup_and_rejects_a_repeat(self):
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(2)]
                           + [(cases.popup(), 1) for _ in range(2)])
        code, report = self.invoke()
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status']), (1, 'partial'), report['error'])
        self.assertEqual((claim['state'], claim['submission'], claim['popup'], claim['quantity']),
                         ('pending', 'sent', 'observed', 1))
        self.assertEqual(self.window.capture.call_count, 4)
        receipts = list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.json'))
        self.assertEqual({json.loads(path.read_text(encoding='utf8'))['state'] for path in receipts},
                         {'pending', 'reserved', 'submitted'})
        originals = {path: path.read_bytes() for path in receipts}
        self.frames = iter((cases.day_cards({1, 2, 3}), None) for _ in range(2))
        code, report = self.invoke()
        self.assertEqual((code, report['status']), (1, 'failed'))
        self.assertEqual({path: path.read_bytes() for path in receipts}, originals)
        self.fixture.native.SendInput.assert_called_once()

    def queue_manual_return(self, claimed, *, next_frames=()):
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(2)]
                           + [(cases.popup(), 1) for _ in range(3)]
                           + list(next_frames) + [(cases.day_cards(claimed), None) for _ in range(2)])

    def test_opt_in_observes_manual_return_with_one_claim_batch(self):
        self.queue_manual_return({1, 2, 3, 4})
        code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status']), (0, 'success'), report['error'])
        self.assertEqual((claim['state'], claim['stage'], claim['submission'], claim['popup'], claim['quantity']),
                         ('verified', 'done', 'sent', 'observed', 1))
        self.assertIn('请手动关闭当前弹窗', self.close_notice)
        self.assertEqual(self.window.capture.call_count, 7)
        self.fixture.native.SendInput.assert_called_once()
        verified, = (self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')
        self.assertTrue(json.loads(verified.read_text(encoding='utf8'))['same_card_claimed'])

    def test_another_day_changing_with_the_selected_day_does_not_settle(self):
        self.queue_manual_return({1, 2, 3, 4, 5})
        code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status']), (1, 'partial'))
        self.assertEqual((claim['state'], claim['stage'], claim['submission']), ('pending', 'return_unverified', 'sent'))
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_one_return_frame_showing_another_claimed_day_is_counterevidence(self):
        def without_fifth_day(scene):
            x, y = cases.claim._CENTERS[4]
            label = scene.find('领取', (x - .025, y - .020, x + .025, y + .020), exact=True)
            self.assertIsNotNone(label)
            scene.tokens.remove(label)
            return scene

        before = [without_fifth_day(cases.day_cards({1, 2, 3})) for _ in range(2)]
        self.frames = iter([(scene, None) for scene in before] + [(cases.popup(), 1) for _ in range(2)]
                           + [(cases.day_cards({1, 2, 3, 4, 5}), None),
                              (without_fifth_day(cases.day_cards({1, 2, 3, 4})), None)])
        code, report = self.invoke('--observe-daily-event-return')
        state = report['daily_event_claim']
        self.assertEqual((code, report['status'], state['state'], state['submission']),
                         (1, 'partial', 'pending', 'sent'))
        self.assertEqual(self.window.capture.call_count, 6)
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_conflicting_account_between_popup_and_return_leaves_the_original_pending(self):
        conflict = cases.popup()
        conflict.tokens.append(cases.OTHER)
        self.queue_manual_return({1, 2, 3, 4}, next_frames=[(conflict, 1)])
        code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status'], claim['state'], claim['stage']),
                         (1, 'partial', 'pending', 'return_unverified'))
        self.assertEqual(self.window.capture.call_count, 6)
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_f10_at_manual_close_handoff_keeps_sent_without_return_or_new_click(self):
        self.queue_manual_return({1, 2, 3, 4})
        emit = app.Runner.emit

        def stop_on_handoff(runner, event):
            emit(runner, event)
            if event.get('type') == 'daily_event_manual_close':
                self.fixture.native.GetAsyncKeyState.return_value = 1

        with patch.object(app.Runner, 'emit', new=stop_on_handoff):
            code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status'], claim['state'], claim['stage'], claim['submission']),
                         (130, 'stopped', 'pending', 'return_unverified', 'sent'))
        self.assertEqual(self.window.capture.call_count, 4)
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_report_does_not_claim_success_after_the_return_receipt_is_replaced(self):
        self.queue_manual_return({1, 2, 3, 4})
        replacement = b'{"external":true}'

        def replace_before_report(source, target, **kwargs):
            if 'attempt_scope' in kwargs:
                verified, = (self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')
                verified.write_bytes(replacement)
            return replace_file(source, target, **kwargs)

        with patch('autohsr.daily_event_claim_flow.replace_file', side_effect=replace_before_report):
            code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status'], claim['state'], claim['stage']),
                         (1, 'partial', 'pending', 'return_unverified'))
        verified, = (self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')
        self.assertEqual(verified.read_bytes(), replacement)
        self.fixture.native.SendInput.assert_called_once()

    def _replace_with_same_bytes(self, path):
        raw, identity = path.read_bytes(), path.stat().st_ino
        external = path.with_name('outside.tmp')
        external.write_bytes(raw)
        external.replace(path)
        self.assertNotEqual(path.stat().st_ino, identity)
        return raw

    def _check_same_byte_replacement_before_report(self, suffix):
        self.queue_manual_return({1, 2, 3, 4})
        ledger = self.fixture.root / 'runs' / 'daily-event-claim'
        replaced = {}

        def replace_before_report(source, target, **kwargs):
            if 'attempt_scope' in kwargs:
                receipt, = ledger.glob(suffix)
                replaced[receipt] = self._replace_with_same_bytes(receipt)
            return replace_file(source, target, **kwargs)

        with patch('autohsr.daily_event_claim_flow.replace_file', side_effect=replace_before_report):
            code, report = self.invoke('--observe-daily-event-return')
        state = report['daily_event_claim']
        self.assertEqual((code, report['status'], state['state'], state['submission']),
                         (1, 'partial', 'pending', 'sent'))
        self.assertEqual(len(replaced), 1)
        self.assertEqual({path: path.read_bytes() for path in replaced}, replaced)
        self.fixture.native.SendInput.assert_called_once()

    def test_original_verified_receipt_must_keep_its_file_identity_until_report(self):
        self._check_same_byte_replacement_before_report('*.verified.json')

    def test_original_submitted_receipt_must_keep_its_file_identity_until_report(self):
        self._check_same_byte_replacement_before_report('*.submitted.json')

    def test_same_byte_replacement_at_verified_rename_is_not_the_created_receipt(self):
        self.queue_manual_return({1, 2, 3, 4})
        native_rename = os.rename
        replaced = {}

        def swap_after_rename(source, destination):
            native_rename(source, destination)
            path = Path(destination)
            if path.name.endswith('.verified.json'):
                replaced[path] = self._replace_with_same_bytes(path)

        with patch('autohsr.warp_service.os.rename', side_effect=swap_after_rename):
            code, report = self.invoke('--observe-daily-event-return')
        state = report['daily_event_claim']
        self.assertEqual((code, report['status'], state['state'], state['submission']),
                         (1, 'partial', 'pending', 'sent'))
        self.assertEqual(len(replaced), 1)
        self.assertEqual({path: path.read_bytes() for path in replaced}, replaced)
        self.fixture.native.SendInput.assert_called_once()

    def test_return_option_cannot_start_an_unrelated_operation(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            with patch('autohsr.daily_event_claim_cli.Settings.load') as load:
                main(['--run', '--observe-daily-event-return'])
            load.assert_not_called()
        self.assertEqual(stopped.exception.code, 2)
        self.fixture.native.SendInput.assert_not_called()

    def test_other_foreground_window_never_captures_or_sends(self):
        self.fixture.native.GetForegroundWindow.return_value = 55
        code, report = self.invoke()
        self.assertEqual((code, report['status'], report['daily_event_claim']['submission']),
                         (1, 'failed', 'not_sent'))
        self.window.capture.assert_not_called()
        self.fixture.native.SendInput.assert_not_called()

    def test_unrelated_and_duplicate_flags_fail_before_settings(self):
        for extras in (['--new-battle-run'], ['--daily-event-claim=5'], ['--config=a', '--config=b']):
            with self.subTest(extras=extras), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                with patch('autohsr.daily_event_claim_cli.Settings.load') as load:
                    main(['--daily-event-claim=4', *extras])
                load.assert_not_called()
            self.assertEqual(stopped.exception.code, 2)
