"""Formal capture CLI with a fake native window and real local file publication."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from itertools import count
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from autohsr import reward_guide_capture
from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import FocusLost
from autohsr.tests.test_daily_reward_guide_pages import guide_scene
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, _Window
from autohsr.vision import Vision


def _frame(name, account=ACCOUNT):
    scene = guide_scene(name, width=1920)
    scene.tokens.append(account)
    return scene


def _pair():
    return [_frame('viewport-7014.png'), _frame('viewport-7026.png')]


class RewardGuideCaptureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.exe = self.root / 'StarRail.exe'
        self.exe.touch()
        self.installation = self.root / 'config.ini'
        self.installation.write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        self.config = self.root / 'settings.json'
        Settings(game_path=str(self.exe), auto_launch=True, overlay_logs=True, battle=True,
                 allow_stamina_spend=True, ocr_confidence=.93).save(self.config)
        self.target = self.root / 'calendar-capture.png'

    def args(self, *extra):
        return ['--reward-guide-capture', str(self.target), '--config', str(self.config), *extra]

    def cli(self, frames, *, code=0, foreground=True, busy=False, before_crop=None, final=None):
        window = _Window(frames)
        window.current_executable = Mock(return_value=self.exe)
        window.capture = Mock(wraps=window.capture)
        if not foreground:
            window.guard.side_effect = FocusLost('private-synthetic-focus')
        find = Mock(return_value=window)
        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        user32 = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0),
                                 SendInput=Mock(side_effect=AssertionError('no native input')))
        ticks = count(100., .001)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        original_save, original_publish = Runner._save_run_report, reward_guide_capture._publish
        state = {}

        def vision(floor):
            reader = window.vision(floor)
            reader.confidence = floor
            reader.template = Vision.__new__(Vision).template
            return reader

        def save(runner, directory, *args, **kwargs):
            state['runner'] = runner
            result = original_save(runner, directory, *args, **kwargs)
            if before_crop is not None:
                before_crop(runner, window, user32)
            return result

        def publish(target, sources, image, check):
            checks = count(1)

            def guarded():
                if next(checks) == 3 and final is not None:
                    state['final_checked'] = True
                    final(state['runner'], window, user32)
                check()

            self.assertTrue((Path(state['runner'].report.run_dir) / 'report.json').is_file())
            kernel.CloseHandle.assert_not_called()
            return original_publish(target, sources, image, guarded)

        config = self.config.read_bytes()
        output, logs = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            for name, replacement in (
                    ('autohsr.app.ROOT', self.root), ('autohsr.app.time', clock),
                    ('autohsr.challenge_pages.time', clock), ('autohsr.workflow_screen.time', clock),
                    ('autohsr.windows.kernel32', kernel), ('autohsr.windows.user32', user32),
                    ('autohsr.app.find_game', find), ('autohsr.app.Vision', Mock(side_effect=vision)),
                    ('autohsr.app.C.get_last_error', Mock(return_value=183 if busy else 0)),
                    ('autohsr.app.threading.Thread', Mock()), ('autohsr.app.Runner._arm_hotkeys', Mock()),
                    ('autohsr.workflow_lease.require_workflow_access', Mock()),
                    ('autohsr.app.is_elevated', Mock(return_value=False))):
                stack.enter_context(patch(name, replacement))
            for name in ('autohsr.app.Runner._prepare_daily_game', 'autohsr.app.launch',
                         'autohsr.notify_runtime.hooks', 'autohsr.overlay.OverlayService',
                         'autohsr.recovery.BattleBudget'):
                stack.enter_context(patch(name, side_effect=AssertionError(name)))
            stack.enter_context(patch.object(Context, 'evidence', side_effect=AssertionError('no raw screenshots')))
            stack.enter_context(patch.object(Context, 'sleep', lambda context, _: context.checkpoint()))
            stack.enter_context(patch.object(Runner, '_save_run_report', save))
            stack.enter_context(patch.object(reward_guide_capture, '_publish', side_effect=publish))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(logs))
            self.assertEqual(main(self.args()), code, output.getvalue() + logs.getvalue())

        result = json.loads(output.getvalue())
        if final is not None:
            self.assertIs(state.get('final_checked'), True)
        self.assertEqual(set(result), {'status', 'input_sent', 'visible_section', 'width', 'height'})
        self.assertIs(result['input_sent'], False)
        self.assertEqual(logs.getvalue(), '')
        for private in (str(self.root), self.target.name, ACCOUNT.text, OTHER.text, 'private-'):
            self.assertNotIn(private, output.getvalue())
        self.assertEqual(self.config.read_bytes(), config)
        self.assertFalse(list((self.root / 'runs').glob('*/*.png')))
        self.assertFalse(list(self.root.glob('.autohsr-reward-guide-*.tmp')))
        window.focus.assert_not_called()
        window.scroll.assert_not_called()
        user32.SendInput.assert_not_called()
        return result, window, find

    def test_two_verified_frames_export_only_the_second_native_content_box(self):
        first, second = _pair()
        second.image[1035:1075, 20:200] = (2, 3, 250)
        result, window, _ = self.cli([first, second])
        self.assertEqual(result, dict(status='ok', input_sent=False, visible_section='ongoing', width=1026, height=603))
        self.assertEqual(window.capture.call_count, 2)
        with Image.open(self.target) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.info, {})
            np.testing.assert_array_equal(np.asarray(image)[:, :, ::-1], second.image[342:945, 378:1404])

    def test_invalid_target_and_busy_or_background_never_capture(self):
        self.target.write_bytes(b'original')
        result, window, find = self.cli(_pair(), code=1)
        self.assertEqual(result['status'], 'invalid_target')
        self.assertEqual(self.target.read_bytes(), b'original')
        find.assert_not_called()
        window.capture.assert_not_called()
        self.target.unlink()
        for options in (dict(busy=True), dict(foreground=False)):
            result, window, _ = self.cli(_pair(), code=1, **options)
            self.assertEqual(result['status'], 'unverified')
            window.capture.assert_not_called()
            self.assertFalse(self.target.exists())

    def test_missing_box_account_change_fade_and_wrong_version_leave_no_png(self):
        for second in (_frame('highlights-2346.png'), _frame('viewport-7026.png', OTHER),
                       _frame('fade-2348.png')):
            result, _, _ = self.cli([_pair()[0], second], code=1)
            self.assertEqual(result['status'], 'unverified')
            self.assertFalse(self.target.exists())
        self.installation.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
        result, _, _ = self.cli(_pair(), code=1)
        self.assertEqual(result['status'], 'unverified')
        self.assertFalse(self.target.exists())

    def test_final_foreground_epoch_and_f10_rechecks_prevent_publication(self):
        def focus(_runner, window, _user32):
            window.guard.side_effect = FocusLost('private-synthetic-focus')

        def pause(runner, _window, _user32):
            runner.input_epoch += 1

        def stop(_runner, _window, user32):
            user32.GetAsyncKeyState.return_value = 1

        def change_box(runner, _window, _user32):
            runner.report.screen_test['reward_guide']['content_box'][0] = 0

        for mutation, status, code in ((focus, 'unverified', 1), (pause, 'unverified', 1), (stop, 'stopped', 130),
                                        (change_box, 'unverified', 1)):
            with self.subTest(mutation=mutation.__name__):
                result, _, _ = self.cli(_pair(), code=code, final=mutation)
                self.assertEqual(result['status'], status)
                self.assertFalse(self.target.exists())

    def test_f10_or_epoch_change_during_last_geometry_check_prevents_the_link(self):
        for stopping, status, code in ((True, 'stopped', 130), (False, 'unverified', 1)):
            with self.subTest(stopping=stopping):
                geometry_checks = []

                def at_final_check(runner, window, user32):
                    def after_geometry(expected=None):
                        if expected is not None:
                            self.assertEqual(expected, window.geometry)
                            geometry_checks.append(expected)
                            if len(geometry_checks) == 4:
                                if stopping:
                                    user32.GetAsyncKeyState.return_value = 1
                                else:
                                    runner.input_epoch += 1
                        return window.geometry

                    window.guard.side_effect = after_geometry

                with patch('autohsr.reward_guide_export.os.link', wraps=os.link) as link:
                    result, _, _ = self.cli(_pair(), code=code, final=at_final_check)
                self.assertEqual(len(geometry_checks), 4)
                self.assertEqual(result['status'], status)
                link.assert_not_called()
                self.assertFalse(self.target.exists())

    def test_version_change_after_report_and_failed_report_never_publish_png(self):
        def version_change(*_):
            self.installation.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')

        result, _, _ = self.cli(_pair(), code=1, before_crop=version_change)
        self.assertEqual(result['status'], 'unverified')
        self.assertFalse(self.target.exists())
        self.installation.write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        replace = Path.replace

        def fail_report(path, target):
            if path.name == 'report.tmp':
                raise OSError('private-synthetic-write')
            return replace(path, target)

        with patch.object(Path, 'replace', fail_report):
            result, _, _ = self.cli(_pair(), code=1)
        self.assertEqual(result['status'], 'report_unverified')
        self.assertFalse(self.target.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows installation read lock')
    def test_final_link_keeps_installation_locked_and_racing_target_preserved(self):
        link = os.link

        def race(staged, destination):
            self.assertEqual(destination, self.target)
            with self.assertRaises(OSError):
                self.installation.write_text('wrong version', encoding='utf8')
            destination.write_bytes(b'other process original')
            return link(staged, destination)

        with patch('autohsr.reward_guide_export.os.link', side_effect=race) as commit:
            result, _, _ = self.cli(_pair(), code=1)
        commit.assert_called_once()
        self.assertEqual(result['status'], 'invalid_target')
        self.assertEqual(self.target.read_bytes(), b'other process original')
        self.assertIn('4.6.0', self.installation.read_text(encoding='utf8'))

    def test_stop_after_the_exclusive_link_preserves_the_committed_crop(self):
        link = os.link
        state = {}

        def before_link(_runner, _window, user32):
            state['user32'] = user32

        def after_link(staged, destination):
            link(staged, destination)
            state['user32'].GetAsyncKeyState.return_value = 1

        with patch('autohsr.reward_guide_export.os.link', side_effect=after_link) as commit:
            result, _, _ = self.cli(_pair(), final=before_link)
        commit.assert_called_once()
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(self.target.is_file())

    def test_command_rejects_combined_actions_before_running(self):
        with patch.object(reward_guide_capture, 'capture_reward_guide') as capture:
            for extra in (['--screen-test'], ['--run'], ['--reward-guide-notify-profile', 'fixture'],
                          ['--reward-guide-output', str(self.target)], ['--config', str(self.config)]):
                with self.subTest(extra=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(self.args(*extra))
                self.assertEqual(error.exception.code, 2)
        capture.assert_not_called()
