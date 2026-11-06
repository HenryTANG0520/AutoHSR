"""Exercise the explicit command with the real Runner and a fake Win32 window."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import app
from autohsr.__main__ import main
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

    def invoke(self):
        config = self.fixture.root / 'settings.json'
        with redirect_stdout(io.StringIO()) as stdout:
            code = main(['--daily-event-claim', '4', '--config', str(config), '--game-path', str(self.fixture.exe)])
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
