"""Native navigation with simulated Win32 packets and scrubbed page fixtures."""

import ctypes
from itertools import chain, count, repeat
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr import windows
from autohsr.config import RESOURCE_ROOT, Settings
from autohsr.currency_wars_identity import UID_COUNTEREVIDENCE
from autohsr.models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, RunReport, Scene, Stopped, Token
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, phone
from autohsr.tests.test_du_team import fixture
from autohsr.vision import Vision
from autohsr.workflow_navigation import OPERATION, WorkflowNavigation


_GEOMETRY = windows.Geometry(0, 0, 1920, 1080)
_CLICK = ((0, 0xC001), (0, 0x0002), (0, 0x0004))
_DOWN = ((1, 0x08),)
_UP = ((1, 0x0A),)


def identified(scene, *tokens):
    return Scene([*scene.tokens, ACCOUNT, *tokens], scene.image, field_reads=scene.field_reads.copy())


def badge(text, x, y, width=.032, score=.99):
    return Token(text, score, (x-width, y-.009, x+width, y+.009))


def battlepass():
    return Scene([ACCOUNT, badge('无名勋礼', .078, .05), badge('任务', .24, .05),
                  badge('本周经验上限', .71, .257), badge('剩余时间', .25, .211),
                  badge('本周任务', .127, .40), badge('本期任务', .127, .64)], phone().image)


def world():
    # Synthetic normal HUD to isolate the actual packaged world anchor.
    image = np.full((_GEOMETRY.height, _GEOMETRY.width, 3), 100, dtype=np.uint8)
    image[400:780, 330:1260] = 144
    icon = cv2.imread(str(RESOURCE_ROOT / 'assets' / 'templates' / 'world_character.png'))
    height, width = icon.shape[:2]
    image[20:20+height, 1820:1820+width] = icon
    return Scene([ACCOUNT], image)


class Window:
    click = windows.GameWindow.click
    key = windows.GameWindow.key
    send = windows.GameWindow.send
    emergency_pressed = staticmethod(windows.GameWindow.emergency_pressed)

    def __init__(self):
        self.guard = Mock(return_value=_GEOMETRY)
        self.current_window_key = Mock(return_value='synthetic-game-window')
        self.focus = Mock(side_effect=AssertionError('navigation must not focus a window'))


class Context:
    def __init__(self, target, frames):
        self.window = Window()
        self.runner = SimpleNamespace(_foreground_only=True, stop_requested=False, input_epoch=0)
        self.settings = Settings(ocr_confidence=.85)
        self.report = RunReport(operation=OPERATION)
        self.vision = Vision.__new__(Vision)
        self.frames = iter(frames)
        self.last_scene = None
        self.scene_epoch = self.capture_sequence = self.capture_occlusion_count = 0
        self._scroll_anchor = None
        self.workflow_navigation = WorkflowNavigation(self, target)

    def snapshot(self):
        self.capture_sequence += 1
        frame = next(self.frames, EmptyCapture('synthetic empty frame'))
        self.last_scene = None
        if isinstance(frame, Exception):
            raise frame
        stamp = time.monotonic()
        pixels = cv2.resize(frame.image, (_GEOMETRY.width, _GEOMETRY.height))
        self.last_scene = Scene(list(frame.tokens), pixels, _GEOMETRY, stamp, frame.field_reads.copy())
        return self.last_scene

    def template(self, scene, name, roi, threshold=.88):
        return self.vision.template(scene, RESOURCE_ROOT / 'assets' / 'templates' / (name + '.png'), roi, threshold)

    def checkpoint(self):
        if self.runner.stop_requested:
            raise Stopped('synthetic stop')

    def sleep(self, _seconds):
        self.checkpoint()

    def workflow_navigation_input(self, scene, action):
        return self.workflow_navigation.dispatch(scene, action)


class WorkflowNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The survival page has no supplied OCR. Read its actual scrubbed pixels.
        path = Path(__file__).parent / 'fixtures' / 'du_runtime' / 'guide_universe_tab_clear.png'
        image = cv2.imdecode(np.fromfile(path, np.uint8), 1)
        cls.survival = identified(Vision(.65).read(image))

    def setUp(self):
        self.sent = []
        self.native = SimpleNamespace(
            GetAsyncKeyState=Mock(return_value=0), MapVirtualKeyW=Mock(return_value=1),
            GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__),
            SendInput=Mock(side_effect=self.send),
        )
        native = patch.object(windows, 'user32', self.native)
        native.start()
        self.addCleanup(native.stop)
        ticks = count(100_000)
        clock = patch.object(time, 'monotonic', side_effect=lambda: next(ticks) / 1000.)
        clock.start()
        self.addCleanup(clock.stop)
        self.daily = identified(fixture('daily_survival_badge'))
        self.mail = identified(fixture('mail_claimable'))
        self.assignments = identified(fixture('assignments_after_claim'))

    def send(self, count, events, _size):
        data = ctypes.cast(events, ctypes.POINTER(windows.INPUT))
        self.sent.append(tuple((event.type, event.mi.dwFlags if event.type == 0 else event.ki.dwFlags)
                               for event in (data[index] for index in range(count))))
        return count

    def test_each_already_open_page_needs_two_frames_and_zero_input(self):
        for target, scene in (('phone', phone()), ('guide', identified(fixture('guide_du_capped'))),
                              ('daily_training', self.daily), ('survival_index', self.survival),
                              ('assignments', self.assignments), ('mail', self.mail), ('battlepass', battlepass())):
            with self.subTest(target=target):
                c = Context(target, [scene, scene])
                result = c.workflow_navigation.run()
                self.assertEqual((result.task, result.status), (OPERATION, 'ok'))
                self.assertEqual(c.report.workflow_navigation, dict(target=target, page_verified=True, actions=[]))
                c.workflow_navigation.guard_publication()
        self.assertEqual(self.sent, [])

    def test_phone_mail_real_envelope_then_real_page(self):
        source = phone()
        c = Context('mail', [source, source, source, self.mail, self.mail])
        self.assertEqual(c.workflow_navigation.run().status, 'ok')
        self.assertEqual(self.sent, [_CLICK])
        self.assertEqual(c.report.workflow_navigation['actions'], [dict(
            action='open_mail', source_page='phone', expected_pages=['mail'], input_status='sent',
            destination_status='verified', destination_page='mail')])
        c.window.focus.assert_not_called()

    def test_known_page_returns_via_world_then_guide_and_survival_once(self):
        frames = chain.from_iterable([page, page] for page in (self.mail, world(), phone(), self.daily, self.survival))
        c = Context('survival_index', frames)
        self.assertEqual(c.workflow_navigation.run().status, 'ok')
        self.assertEqual(self.sent, [_DOWN, _UP, _DOWN, _UP, _CLICK, _CLICK])
        rows = c.report.workflow_navigation['actions']
        self.assertEqual([row['action'] for row in rows],
                         ['return_to_hub', 'open_phone', 'open_guide', 'open_survival_index'])
        self.assertTrue(all(row['destination_status'] == 'verified' for row in rows))

    def test_survival_to_daily_uses_same_slot_4_6_template(self):
        c = Context('daily_training', [self.survival, self.survival, self.daily, self.daily])
        self.assertEqual(c.workflow_navigation.run().status, 'ok')
        self.assertEqual(self.sent, [_CLICK])
        self.assertEqual(c.report.workflow_navigation['actions'][0]['action'], 'open_daily_training')

    def test_phone_battlepass_and_assignments_only_use_caption_once(self):
        for target, result in (('battlepass', battlepass()), ('assignments', self.assignments)):
            with self.subTest(target=target):
                source = phone()
                c = Context(target, [source, source, result, result])
                self.assertEqual(c.workflow_navigation.run().status, 'ok')
                self.assertEqual(c.report.workflow_navigation['actions'][0]['action'], 'open_' + target)
        self.assertEqual(self.sent, [_CLICK, _CLICK])

    def test_wrong_modal_battle_and_duplicate_control_never_send(self):
        duplicate = phone(badge('指南', .32, .45, score=.72))
        for frame in (phone(badge('确认', .5, .55, score=.70)), phone(badge('战斗失败', .5, .42)),
                      phone(badge('列车补给', .5, .13)), duplicate):
            with self.subTest(tokens=len(frame.tokens)):
                c = Context('guide', repeat(frame, 6))
                with self.assertRaises(AutomationError):
                    c.workflow_navigation.run()
                self.assertEqual(c.report.workflow_navigation['actions'], [])
        self.assertEqual(self.sent, [])

    def test_low_confidence_conflicting_account_cannot_start(self):
        first = phone()
        second = phone()
        second.field_reads[UID_COUNTEREVIDENCE] = (Token(OTHER.text, .72, OTHER.box),)
        c = Context('mail', [first, second])
        with self.assertRaises(AutomationError):
            c.workflow_navigation.run()
        self.assertEqual(self.sent, [])

    def test_unchanged_or_interrupted_feedback_never_replays(self):
        source = phone()
        for feedback in (repeat(source, 6), [self.mail, EmptyCapture('blank'), self.mail], [battlepass()]):
            with self.subTest():
                c = Context('mail', chain((source, source), feedback))
                before = len(self.sent)
                with self.assertRaises(AutomationError):
                    c.workflow_navigation.run()
                self.assertEqual(self.sent[before:], [_CLICK])
                report = c.report.workflow_navigation
                self.assertFalse(report['page_verified'])
                self.assertEqual(report['actions'][0]['destination_status'], 'unknown')

    def test_late_f10_and_input_epoch_in_final_native_guard_send_nothing(self):
        for kind, error in (('f10', Stopped), ('epoch', InputInterrupted)):
            with self.subTest(kind=kind):
                c = Context('mail', repeat(phone(), 2))
                navigation = c.workflow_navigation
                planned = navigation._planned
                calls = 0
                pending = False

                def capture_plan(pair):
                    nonlocal calls, pending
                    value = planned(pair)
                    calls += 1
                    pending = calls == 2
                    return value

                def key():
                    if pending and kind == 'f10':
                        self.native.GetAsyncKeyState.return_value = 1
                    elif pending:
                        c.runner.input_epoch += 1
                    return 'synthetic-game-window'

                with patch.object(navigation, '_planned', side_effect=capture_plan):
                    c.window.current_window_key.side_effect = key
                    with self.assertRaises(error):
                        navigation.run()
                self.native.GetAsyncKeyState.return_value = 0
                self.assertEqual(c.report.workflow_navigation['actions'], [])
        self.assertEqual(self.sent, [])

    def test_failed_native_packet_leaves_unconfirmed_intent_and_zero_replay(self):
        c = Context('mail', repeat(phone(), 2))

        def partial(count, events, size):
            self.send(count, events, size)
            return count - 1 if count == 3 else count

        self.native.SendInput.side_effect = partial
        with self.assertRaises(AutomationError):
            c.workflow_navigation.run()
        self.assertEqual(c.report.workflow_navigation['actions'][0]['input_status'], 'unconfirmed')
        with self.assertRaises(AutomationError):
            c.workflow_navigation.dispatch(c.last_scene, 'open_mail')
        self.assertEqual(self.sent, [_CLICK, ((0, 4),)])

    def test_replaced_first_frame_after_target_check_cannot_authorize_native_input(self):
        c = Context('mail', repeat(phone(), 2))
        navigation = c.workflow_navigation
        planned = navigation._planned
        calls = 0

        def capture_plan(pair):
            nonlocal calls
            value = planned(pair)
            calls += 1
            if calls == 2:
                def replace():
                    pair[0].scene.image = pair[0].image.copy()
                    return 'synthetic-game-window'

                c.window.current_window_key.side_effect = replace
            return value

        with patch.object(navigation, '_planned', side_effect=capture_plan):
            with self.assertRaisesRegex(AutomationError, '封存双帧'):
                navigation.run()
        self.assertEqual(c.report.workflow_navigation['actions'], [])
        self.assertEqual(self.sent, [])

    def test_publication_focus_loss_does_not_replay_prior_action(self):
        c = Context('mail', [phone(), phone(), self.mail, self.mail])
        c.workflow_navigation.run()
        c.window.guard.side_effect = FocusLost('synthetic late foreground loss')
        with self.assertRaises(FocusLost):
            c.workflow_navigation.guard_publication()
        self.assertEqual(self.sent, [_CLICK])
        self.assertEqual(c.report.workflow_navigation['actions'][0]['input_status'], 'sent')


if __name__ == '__main__':
    unittest.main()
