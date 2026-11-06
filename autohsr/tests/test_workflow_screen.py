"""Native Context observations driven by in-memory frames and a fake window."""
from itertools import count
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from autohsr.app import Context
from autohsr.currency_wars_identity import UID_COUNTEREVIDENCE
from autohsr.models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, Scene, Stopped, Token
from autohsr.windows import Geometry
from autohsr.workflow_identity import WorkflowIdentity, account_scope
from autohsr.workflow_screen import WorkflowScreenError, observe_game


ACCOUNT = Token('UID:135792468', .99, (.018, .952, .106, .982))
OTHER = Token('UID:246813579', .99, ACCOUNT.box)


class _Window:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.geometry = Geometry(0, 0, 96, 72)
        self.identity = 'fake foreground identity'
        self.foreground = True
        self.capture_calls = 0
        self.emergency_pressed = Mock(return_value=False)
        for name in ('focus', 'send', 'click', 'key', 'move', 'drag', 'scroll'):
            setattr(self, name, Mock(side_effect=AssertionError('observation cannot send input')))

    def guard(self, expected=None):
        if not self.foreground:
            raise FocusLost('synthetic loss of foreground')
        if expected is not None and expected != self.geometry:
            raise AutomationError('synthetic window resize')
        return self.geometry

    def current_window_key(self):
        return self.identity

    def capture(self):
        self.capture_calls += 1
        self.frame = next(self.frames, EmptyCapture('synthetic capture ended'))
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame.image, self.geometry

    def read(self, image, geometry):
        return Scene(list(self.frame.tokens), image, geometry, field_reads=dict(self.frame.field_reads))


class WorkflowScreenTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        ticks = count(100., .01)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        for module in ('autohsr.app', 'autohsr.workflow_screen', 'autohsr.workflow_identity'):
            timer = patch(module + '.time', clock)
            timer.start()
            self.addCleanup(timer.stop)
        self.directory = Path(folder.name)
        self.template = self.directory / 'synthetic-template.png'
        self.needle = np.full((20, 24, 3), 215, dtype=np.uint8)
        self.needle[3:16, 4:7] = (12, 54, 120)
        self.needle[12:16, 4:21] = (40, 130, 58)
        self.needle[5:10, 11:20] = (20, 40, 180)
        Image.fromarray(self.needle).save(self.template)

    def frame(self, *, found=True, account=ACCOUNT, extra=()):
        bgr = np.full((72, 96, 3), 215, dtype=np.uint8)
        bgr[:, :8] = 60
        if found:
            bgr[14:34, 10:34] = self.needle[:, :, ::-1]
        return Scene([*([account] if account is not None else []), *extra], bgr)

    def context(self, frames, *, mode='image'):
        runner = SimpleNamespace(settings=SimpleNamespace(ocr_confidence=.9), _foreground_only=True,
                                 _challenge_read_only=True, stop_requested=False, input_epoch=2,
                                 report=SimpleNamespace(operation='workflow_game_' + mode, run_dir=str(self.directory)),
                                 checkpoint=Mock(), log=Mock(), wait_for_focus=Mock(side_effect=AssertionError('no focus wait')))
        window = _Window(frames)
        context = Context(runner, window, window)
        context.sleep = lambda _seconds: context.checkpoint()
        context.evidence = Mock()
        self.addCleanup(self.assert_no_input, window, runner)
        return context, window

    def assert_no_input(self, window, runner):
        runner.wait_for_focus.assert_not_called()
        for name in ('focus', 'send', 'click', 'key', 'move', 'drag', 'scroll'):
            getattr(window, name).assert_not_called()

    def test_image_observation_reports_only_the_two_agreed_booleans(self):
        for roi, expected in (([0, 0, .5, .5], True), ([.5, 0, 1, 1], False)):
            with self.subTest(roi=roi):
                context, window = self.context([self.frame(), self.frame()])
                self.assertEqual(observe_game(context, {'template': self.template, 'region': roi}),
                                 {'image_found': expected})
                self.assertEqual(window.capture_calls, 2)
                context.evidence.assert_not_called()

    def test_actual_context_scope_can_verify_current_account_before_adjacent_pair(self):
        identity = WorkflowIdentity(self.directory, required=True)
        with account_scope(identity):
            context, window = self.context([self.frame(), self.frame(), self.frame()])
            self.assertEqual(observe_game(context, {'template': self.template}), {'image_found': True})
        self.assertEqual(window.capture_calls, 3)
        self.assertTrue(identity.public()['verified'])

    def test_text_is_read_from_current_bgr_crop_with_one_reused_reader(self):
        context, _ = self.context([self.frame(), self.frame()], mode='text')
        reader = Mock()
        reader.read.return_value = Scene([Token('委托 已完成', .99, (.2, .2, .7, .6)),
                                          Token('委托', .999, (.8, .3, 1.2, .6))])
        query = {'text': '委托', 'contains': True, 'region': [0, 0, .5, .5], 'threshold': .85}
        with patch('autohsr.workflow_vision.Vision', return_value=reader) as initialize:
            self.assertEqual(observe_game(context, query), {'text_found': True})
        initialize.assert_called_once_with(.85)
        self.assertEqual(reader.read.call_count, 2)
        for call in reader.read.call_args_list:
            self.assertEqual(call.args[0].shape, (36, 48, 3))
            self.assertTrue(np.array_equal(call.args[0][14:34, 10:34], self.needle[:, :, ::-1]))

    def test_missing_conflicting_or_changed_uid_cannot_report_false_or_true(self):
        weak = Token(OTHER.text, .72, OTHER.box)
        field_conflict = self.frame()
        field_conflict.field_reads[UID_COUNTEREVIDENCE] = (weak,)
        cases = (self.frame(account=None), self.frame(account=OTHER), self.frame(extra=(weak,)), field_conflict)
        for index, second in enumerate(cases):
            with self.subTest(index=index):
                context, _ = self.context([self.frame(), second])
                with self.assertRaises(AutomationError):
                    observe_game(context, {'template': self.template})

    def test_result_disagreement_blank_login_payment_or_helper_occlusion_is_unknown(self):
        login = Token('账号登录', .99, (.35, .45, .65, .55))
        payment = Token('确认支付', .99, (.35, .45, .65, .55))
        helper = tuple(Token(text, .99, (.1, .1, .3, .2)) for text in ('AutoHSR', '运行日志', '每日任务'))
        blank = Scene([ACCOUNT], np.full((72, 96, 3), (40, 70, 100), dtype=np.uint8))
        for tag, after in (('different', [self.frame(found=False)]), ('blank', [blank]),
                           ('login', [self.frame(extra=(login,))]), ('payment', [self.frame(extra=(payment,))]),
                           ('helper', [self.frame(extra=helper), self.frame()])):
            with self.subTest(tag=tag):
                context, _ = self.context([self.frame(), *after])
                with self.assertRaises(WorkflowScreenError):
                    observe_game(context, {'template': self.template})

    def test_nonadjacent_stale_reused_or_mutated_frames_are_unknown(self):
        for tag in ('skipped_sequence', 'old_timestamp', 'reused_pixels', 'mutated_pixels'):
            with self.subTest(tag=tag):
                first, second = self.frame(), self.frame()
                if tag == 'reused_pixels':
                    second.image = first.image
                context, _ = self.context([first, second])
                capture = context.snapshot

                def altered_capture():
                    scene = capture()
                    if context.capture_sequence == 2:
                        if tag == 'skipped_sequence':
                            context.capture_sequence += 1
                        elif tag == 'old_timestamp':
                            scene.captured_at -= 1
                        elif tag == 'mutated_pixels':
                            first.image[0, 0] = 180
                    return scene

                context.snapshot = altered_capture
                with self.assertRaises(WorkflowScreenError):
                    observe_game(context, {'template': self.template})

    def test_focus_window_epoch_and_stop_changes_do_not_publish(self):
        for tag, expected in (('focus', FocusLost), ('window', WorkflowScreenError),
                              ('epoch', InputInterrupted), ('F10', Stopped)):
            with self.subTest(tag=tag):
                context, window = self.context([self.frame(), self.frame()])

                def wait(_seconds):
                    if tag == 'focus':
                        window.foreground = False
                    elif tag == 'window':
                        window.identity = 'different window'
                    elif tag == 'epoch':
                        context.runner.input_epoch += 1
                    else:
                        window.emergency_pressed.return_value = True

                context.sleep = wait
                with self.assertRaises(expected):
                    observe_game(context, {'template': self.template})
                self.assertEqual(window.capture_calls, 1)

    def test_only_the_exclusive_read_only_operation_can_capture(self):
        for foreground, mode, query in ((False, 'image', {'template': self.template}),
                                        (True, 'text', {'template': self.template}),
                                        (True, 'image', {'template': self.template, 'image': self.template})):
            with self.subTest(foreground=foreground, mode=mode):
                context, window = self.context([self.frame()], mode=mode)
                context.runner._foreground_only = foreground
                with self.assertRaises(WorkflowScreenError):
                    observe_game(context, query)
                self.assertEqual(window.capture_calls, 0)

    def test_template_is_locked_from_before_first_capture_until_both_are_verified(self):
        if os.name != 'nt':
            self.skipTest('requires Windows file sharing')
        context, window = self.context([self.frame(), self.frame()])
        replacement = self.directory / 'replacement.png'
        Image.new('RGB', (20, 20), 'blue').save(replacement)
        capture = window.capture

        def checked_capture():
            with self.assertRaises(PermissionError):
                os.replace(replacement, self.template)
            return capture()

        window.capture = checked_capture
        self.assertEqual(observe_game(context, {'template': self.template}), {'image_found': True})
        self.assertEqual(window.capture_calls, 2)
        os.replace(replacement, self.template)
