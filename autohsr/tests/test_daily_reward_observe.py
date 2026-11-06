"""Formal achievements observation CLI with a synthetic foreground and Win32 sender."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
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
from uuid import uuid4

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.daily_reward_observe import OPERATION, phone_achievement_target
from autohsr.models import AutomationError, EmptyCapture, FocusLost, RunReport, Scene, Token
from autohsr.policy import guard_click
from autohsr.tests.test_du_team import fixture
from autohsr.windows import GameWindow, Geometry


ACCOUNT = Token('UID:135792468', .99, (.018, .957, .106, .985))
OTHER = Token('UID:246813579', .99, (.018, .957, .106, .985))


def phone(*extra, account=ACCOUNT):
    scene = fixture('phone_mail_icon')
    scene.tokens.extend((account, *extra))
    return scene


def destination(*extra, account=ACCOUNT):
    return Scene([account, Token('成就', .99, (.027, .032, .052, .058)), *extra], phone().image)


class _Window:
    hwnd = 1
    geometry = Geometry(0, 0, 1920, 1080)
    click = GameWindow.click
    send = GameWindow.send
    emergency_pressed = staticmethod(GameWindow.emergency_pressed)

    def __init__(self, frames):
        self.frames = iter(frames)
        self.frame = None
        self.guard = Mock(return_value=self.geometry)
        self.current_window_key = Mock(return_value='synthetic-window')
        self.focus = Mock(side_effect=AssertionError('must not focus a window'))
        for name in ('move', 'key', 'scroll', 'drag'):
            setattr(self, name, Mock(side_effect=AssertionError('no generic input')))

    def capture(self):
        self.frame = next(self.frames, EmptyCapture('blank test frame'))
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame.image.copy(), self.geometry

    def vision(self, confidence):
        def read(image, geometry):
            return Scene([token for token in self.frame.tokens if token.score >= confidence], image, geometry)

        return SimpleNamespace(read=read)


class DailyRewardObserveTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.config = self.root / 'config.json'
        Settings(overlay_logs=True, auto_launch=True, ocr_confidence=.93).save(self.config)
        self.original = self.config.read_bytes()

    def run_cli(self, frames, *, entry_hook=None, before_native=None, short=False, foreground=True):
        self.window = window = _Window(frames)
        if not foreground:
            window.guard.side_effect = FocusLost('synthetic window is not foreground')
        self.context = None
        self.events = []
        key_checks = []
        original_entry = Context.daily_reward_entry_input

        def entry(context, scene):
            self.context = context
            if entry_hook is not None:
                entry_hook(context, scene)
            return original_entry(context, scene)

        def key_state(_):
            key_checks.append(True)
            return before_native(len(key_checks)) if before_native else 0

        def submit(length, items, _size):
            self.events.append(tuple((item.mi.dwFlags, item.mi.dx, item.mi.dy) for item in items))
            return length - 1 if short else length

        user32 = SimpleNamespace(GetAsyncKeyState=Mock(side_effect=key_state),
                                 GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__),
                                 SendInput=Mock(side_effect=submit))
        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        ticks = count(100., .01)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        output, logs = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            for target, value in (('autohsr.app.ROOT', self.root), ('autohsr.app.time', clock),
                                  ('autohsr.daily_reward_observe.time', clock), ('autohsr.windows.user32', user32),
                                  ('autohsr.windows.kernel32', kernel),
                                  ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.DailyRewardQA.' + uuid4().hex)):
                stack.enter_context(patch(target, value))
            for target, kwargs in (
                    ('autohsr.app.C.get_last_error', dict(return_value=0)),
                    ('autohsr.app.threading.Thread', {}),
                    ('autohsr.app.is_elevated', dict(return_value=False)),
                    ('autohsr.app.find_game', dict(return_value=window)),
                    ('autohsr.app.Vision', dict(side_effect=window.vision)),
                    ('autohsr.notify_runtime.hooks', dict(side_effect=AssertionError('no notifications'))),
                    ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay'))),
                    ('autohsr.app.Runner._arm_hotkeys', {}),
                    ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no startup')))):
                stack.enter_context(patch(target, **kwargs))
            stack.enter_context(patch.object(Context, 'sleep', lambda ctx, _seconds: ctx.checkpoint()))
            stack.enter_context(patch.object(Context, 'daily_reward_entry_input', entry))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(logs))
            self.assertEqual(main(['--daily-reward-observe', 'achievements', '--config', str(self.config)]), 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report['operation'], OPERATION)
        self.assertEqual((report['stamina_spent'], report['stamina_pending'], report['battle_completed']), (0, 0, 0))
        self.assertFalse(report['daily_reward_observe']['page_verified'])
        self.assertEqual(json.loads((Path(report['run_dir']) / 'report.json').read_text('utf8')), report)
        self.assertEqual(self.config.read_bytes(), self.original)
        window.focus.assert_not_called()
        for name in ('move', 'key', 'scroll', 'drag'):
            getattr(window, name).assert_not_called()
        for value in (ACCOUNT.text[4:], OTHER.text[4:]):
            self.assertNotIn(value, output.getvalue() + logs.getvalue())
        return report

    def test_real_phone_fixture_submits_one_native_batch_and_saves_unverified_arrival(self):
        report = self.run_cli([phone(), phone(), phone(), destination(), destination()])
        self.assertEqual(report['status'], 'partial', report['error'])
        result = report['daily_reward_observe']
        self.assertEqual((result['entry_input'], result['destination_status']), ('sent', 'achievement_title_only'))
        self.assertEqual(len(self.events), 1)
        self.assertEqual([item[0] for item in self.events[0]], [0xC001, 0x0002, 0x0004])
        x, y = result['entry_point']
        self.assertAlmostEqual(x, .9018, places=4)
        self.assertAlmostEqual(y, .4981, places=4)
        self.assertEqual(result['submission_capture_sequence'], 3)
        frames = [*result['before_frames'], *result['after_frames']]
        self.assertEqual([row['capture_sequence'] for row in frames], [1, 2, 4, 5])
        directory = Path(report['run_dir'])
        for row in frames:
            self.assertEqual(sha256((directory / row['screenshot']).read_bytes()).hexdigest(), row['sha256'])
        intent = (directory / result['intent']).read_text('utf8')
        self.assertEqual(json.loads(intent)['sources'], result['before_frames'])
        self.assertNotIn(ACCOUNT.text[4:], intent)

    def test_wrong_page_modal_duplicate_weak_account_or_gap_cannot_send(self):
        duplicate = Token('成就', .72, (.31, .32, .34, .35))
        modal = Token('确认', .73, (.43, .42, .48, .45))
        split = (Token('确', .88, (.43, .42, .45, .45)), Token('认', .89, (.456, .42, .477, .45)))
        weak_other = Token(OTHER.text, .68, OTHER.box)
        for frames in ([destination(), destination()], [phone(duplicate), phone(duplicate)],
                       [phone(modal), phone(modal)], [phone(*split), phone(*split)], [phone(weak_other), phone(weak_other)],
                       [phone(), EmptyCapture('gap'), phone()], [phone(), phone(account=OTHER)]):
            with self.subTest(frames=len(frames)):
                report = self.run_cli(frames)
                result = report['daily_reward_observe']
                self.assertEqual(result['entry_input'], 'not_sent')
                self.assertEqual(self.events, [])
                self.assertNotIn('intent', result)

    def test_third_capture_cannot_reuse_the_saved_intent_after_view_or_account_change(self):
        for changed in (destination(), phone(account=OTHER), phone(Token('切换账号', .99, (.43, .42, .52, .46)))):
            with self.subTest(changed=len(changed.tokens)):
                report = self.run_cli([phone(), phone(), changed])
                result = report['daily_reward_observe']
                self.assertEqual(result['entry_input'], 'not_sent')
                self.assertIn('intent', result)
                self.assertEqual(self.events, [])

    def test_background_window_and_last_native_stop_do_not_send(self):
        background = self.run_cli([phone(), phone(), phone()], foreground=False)
        self.assertEqual(background['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertEqual(self.events, [])
        stopped = self.run_cli([phone(), phone(), phone()], before_native=lambda count: count == 2)
        self.assertEqual(stopped['status'], 'stopped')
        self.assertEqual(stopped['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertEqual(self.events, [])

    def test_input_epoch_change_at_native_stop_check_cannot_submit(self):
        def pause(count):
            if count == 2:
                self.context.runner.toggle_pause()
            return 0

        report = self.run_cli([phone(), phone(), phone()], before_native=pause)
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertIn('输入代次已改变', report['error'])
        self.assertEqual(self.events, [])

    def test_evidence_swap_before_native_lock_stops_submission(self):
        def replace(context, _scene):
            reader = context.daily_reward_reader
            file = reader.directory / reader.record['before_frames'][0]['screenshot']
            file.write_bytes(file.read_bytes() + b'different bytes')

        report = self.run_cli([phone(), phone(), phone()], entry_hook=replace)
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertIn('截图在发送前已变化', report['error'])
        self.assertEqual(self.events, [])

    @unittest.skipUnless(os.name == 'nt', 'requires Windows file sharing')
    def test_real_ntfs_sources_are_locked_at_native_submit(self):
        blocked = []

        def try_replace(count):
            if count == 2:
                reader = self.context.daily_reward_reader
                for name in (reader.intent.name, *(row['screenshot'] for row in reader.record['before_frames'])):
                    replacement = reader.directory / 'replacement.tmp'
                    replacement.write_bytes(b'changed')
                    with self.assertRaises(PermissionError):
                        os.replace(replacement, reader.directory / name)
                    blocked.append(name)
            return 0

        report = self.run_cli([phone(), phone(), phone(), destination(), destination()], before_native=try_replace)
        self.assertEqual(len(blocked), 3)
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'sent')
        self.assertEqual(len(self.events), 1)

    def test_existing_run_ledger_preflights_can_block_navigation(self):
        for target in ('autohsr.du_reward_store.preflight', 'autohsr.du_archive_store.preflight',
                       'autohsr.currency_wars_weekly_reward_store.RewardStore.preflight',
                       'autohsr.currency_wars_weekly.native_gate'):
            with (self.subTest(target=target), patch(target, side_effect=AutomationError('synthetic ledger block'))):
                report = self.run_cli([phone(), phone(), phone()])
                self.assertEqual(report['daily_reward_observe']['entry_input'], 'not_sent')
                self.assertEqual(report['error'], 'synthetic ledger block')
                self.assertIsNone(self.window.frame)
                self.assertEqual(self.events, [])

    def test_short_send_or_account_change_after_click_never_retry(self):
        short = self.run_cli([phone(), phone(), phone()], short=True)
        self.assertEqual(short['daily_reward_observe']['entry_input'], 'unconfirmed')
        self.assertEqual(len(self.events), 1)
        changed = self.run_cli([phone(), phone(), phone(), destination(account=OTHER)])
        self.assertEqual(changed['status'], 'partial')
        self.assertEqual(changed['daily_reward_observe']['entry_input'], 'sent')
        self.assertEqual(changed['daily_reward_observe']['after_frames'], [])
        self.assertEqual(len(self.events), 1)
        unchanged = self.run_cli([phone() for _ in range(9)])
        self.assertEqual(unchanged['daily_reward_observe']['destination_status'], 'phone_still_visible')
        self.assertEqual(len(self.events), 1)

    def test_generic_input_and_incompatible_cli_options_stay_out_of_scope(self):
        scene = phone()
        target = phone_achievement_target(scene, .85)
        self.assertIsNotNone(target)
        with self.assertRaises(AutomationError):
            guard_click(scene, target)
        window = _Window(())
        context = Context(Runner(Settings(), operation=OPERATION), window, None)
        for action, args in ((context.click, (scene, target)), (context.key, ('esc',)),
                             (context.scroll, (1,)), (context.move, (scene, target.center)),
                             (context.drag, (scene, (.2, .3), (.4, .5))),
                             (context.daily_reward_entry_input, (scene,))):
            with self.assertRaises(AutomationError):
                action(*args)
        with self.assertRaises(ValueError):
            Runner(Settings(), operation=OPERATION, new_battle_run=True)
        self.assertNotIn('daily_reward_observe', RunReport().to_dict())
        for option in ('--run', '--reward-only', '--new-battle-run', '--with-redemption'):
            with (self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error,
                  patch.object(Settings, 'load', side_effect=AssertionError('invalid CLI must not load config'))):
                main(['--daily-reward-observe', 'achievements', option])
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
