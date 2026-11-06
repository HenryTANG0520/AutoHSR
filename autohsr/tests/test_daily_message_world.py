from dataclasses import replace
from hashlib import sha256
from itertools import count
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr.app import Context, Runner
from autohsr.daily_message_observe import message_panel
from autohsr.daily_message_world import _BUBBLE, _WORLD_ANCHOR, _WORLD_ROI, world_message_target
from autohsr.models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, RunReport, Scene, Token
from autohsr.tests.test_daily_message_observe import ACCOUNT, BRIGHT_FIXTURES, OTHER, STATE_FIXTURES, phone
from autohsr.vision import Vision
from autohsr.windows import Geometry
from autohsr.workflow_navigation import OPERATION, TARGETS, WorkflowNavigation


FIXTURES = STATE_FIXTURES.with_name('daily_message_world')
CLIENT_SIZE = (1704, 960)


def image(path):
    return cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)


def client_frame(frame, *tokens):
    return Scene(list(tokens), cv2.resize(frame, CLIENT_SIZE, interpolation=cv2.INTER_NEAREST),
                 captured_at=time.monotonic())


def world_cases():
    return json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf8'))['cases']


def world_pair():
    return [client_frame(image(FIXTURES / case['file']), ACCOUNT) for case in world_cases()
            if case['part'] == 178 and case['phase'] == 'world'][:2]


def bright_sequence(index=0):
    source = json.loads((BRIGHT_FIXTURES / 'manifest.json').read_text(encoding='utf8'))['sources'][index]
    return [client_frame(image(BRIGHT_FIXTURES / case['file']), ACCOUNT) for case in source['cases']]


class ReplayContext:
    """Window and click recorder for the test only. Frames come from fixtures."""

    workflow_navigation_input = Context.workflow_navigation_input

    def __init__(self, scenes, executable):
        self.scenes = iter(scenes)
        self.geometry = Geometry(0, 0, *CLIENT_SIZE)
        self.window = SimpleNamespace(guard=Mock(return_value=self.geometry),
                                      current_window_key=Mock(return_value='test-window'),
                                      emergency_pressed=Mock(return_value=False),
                                      current_executable=Mock(return_value=executable),
                                      click=Mock(side_effect=self.submit),
                                      key=Mock(side_effect=AssertionError('no keyboard route')))
        self.report = RunReport(operation=OPERATION)
        self.runner = SimpleNamespace(input_epoch=0, stop_requested=False, _foreground_only=True, report=self.report)
        self.settings = SimpleNamespace(ocr_confidence=.85)
        self.checkpoint, self.sleep = Mock(), Mock()
        self.template = Mock(return_value=None)
        self.submissions = []
        self.before_click, self.after_click = Mock(), Mock()
        self.last_scene = self._scroll_anchor = None
        self.capture_sequence = self.scene_epoch = self.capture_occlusion_count = 0
        self.workflow_navigation = WorkflowNavigation(self, 'messages')

    def submit(self, x, y, geometry, *, before_submit):
        self.before_click()
        before_submit()
        self.submissions.append((x, y, geometry))
        self.after_click()

    def snapshot(self):
        scene = next(self.scenes, None)
        if scene is None:
            raise EmptyCapture('end of offline replay')
        self.capture_sequence += 1
        self.last_scene = replace(scene, geometry=self.geometry, captured_at=time.monotonic())
        return self.last_scene

class WorldMessageTargetTests(unittest.TestCase):
    def test_real_world_and_first_fade(self):
        for case in world_cases():
            with self.subTest(file=case['file']):
                path = FIXTURES / case['file']
                self.assertEqual(sha256(path.read_bytes()).hexdigest(), case['sha256'])
                scene = client_frame(image(path))
                target = world_message_target(scene)
                self.assertEqual(target is not None, case['expected'])
                if target is not None:
                    self.assertAlmostEqual(target.center[0], 107.5 / 852, delta=.006)
                    self.assertAlmostEqual(target.center[1], 106 / 480, delta=.008)
                world_anchor = Vision.__new__(Vision).template(scene, _WORLD_ANCHOR, _WORLD_ROI, .65)
                self.assertEqual(world_anchor is not None, case['world_anchor'])

    def test_bright_double_column_and_phone_do_not_offer_world_target(self):
        for index in range(2):
            for panel in bright_sequence(index)[-2:]:
                self.assertTrue(message_panel(panel))
                self.assertIsNone(world_message_target(panel))
        self.assertIsNone(world_message_target(phone()))

    def test_other_real_red_icon_is_rejected_in_both_positions(self):
        source = next(case for case in world_cases() if case['expected'])
        case = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf8'))['other_red_icon']
        path = FIXTURES / case['file']
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), case['sha256'])
        icon = image(path)
        for x, y in (case['canonical_xyxy'][:2], case['relocated_xy']):
            with self.subTest(origin=(x, y)):
                frame = image(FIXTURES / source['file'])
                frame[76:123, 86:144] = 30
                height, width = icon.shape[:2]
                frame[y:y + height, x:x + width] = icon
                self.assertIsNone(world_message_target(client_frame(frame)))

    def test_missing_world_anchor_and_modal_text_veto_a_visible_bubble(self):
        scene = world_pair()[0]
        self.assertIsNotNone(world_message_target(scene))
        for token in (Token('恭喜获得物品', .96, (.44, .11, .52, .16)),
                      Token('点击任意位置关闭', .96, (.44, .78, .52, .83))):
            self.assertIsNone(world_message_target(replace(scene, tokens=[token])))
        self.assertIsNone(world_message_target(replace(scene, captured_at=0)))
        scene.image[:86, round(.93 * CLIENT_SIZE[0]):] = 30
        self.assertIsNone(world_message_target(scene))

    def test_rejects_two_aligned_badges_even_when_both_glyphs_are_valid(self):
        source = next(case for case in world_cases() if case['expected'])
        frame = image(FIXTURES / source['file'])
        frame[76:123, 86:144] = 30
        ref = cv2.imdecode(np.frombuffer(_BUBBLE.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
        glyph = ref[:, :, 3] > 0
        for index, (x, y) in enumerate(((86, 95), (112, 99))):
            cv2.circle(frame, (x + 21, y + 1), 5, (58, 73, 242), thickness=-1)
            frame[y:y + 22, x:x + 25][glyph] = ref[:, :, :3][glyph]
            self.assertEqual(world_message_target(client_frame(frame)) is not None, index == 0)


class WorldMessageReplayTests(unittest.TestCase):
    def setUp(self):
        tick = count(100., .01)
        clock = patch('time.monotonic', side_effect=lambda: next(tick))
        clock.start()
        self.addCleanup(clock.stop)
        self.root = Path(self.enterContext(TemporaryDirectory()))

    def context(self, scenes, version='4.6.0'):
        executable = self.root / 'StarRail.exe'
        executable.touch()
        executable.with_name('config.ini').write_text(f'[General]\ngame_version={version}\n', encoding='utf8')
        context = ReplayContext(scenes, executable)
        self.addCleanup(context.window.key.assert_not_called)
        return context

    def assert_single_unverified_action(self, context):
        self.assertEqual(len(context.submissions), 1)
        self.assertFalse(context.workflow_navigation.record['page_verified'])
        self.assertEqual(context.workflow_navigation.record['actions'], [dict(
            action='open_messages', source_page='world', expected_pages=['messages'], input_status='sent',
            destination_status='unknown',
        )])

    def test_one_fake_click_then_two_panels(self):
        p178 = [client_frame(image(STATE_FIXTURES / name), ACCOUNT) for name in
                ('before_panel.png', 'list_badge.png', 'selected_fade.png')]
        for name, after in (('same_episode', p178), ('bright_panel_variant', bright_sequence()[-3:])):
            with self.subTest(replay=name):
                pair = world_pair()
                context = self.context([*pair, *after])
                self.assertEqual(context.workflow_navigation.run().status, 'ok')
                self.assertEqual(context.submissions, [(*world_message_target(pair[-1]).center, context.geometry)])
                self.assertEqual(context.capture_sequence, 5)
                self.assertTrue(context.workflow_navigation.record['page_verified'])
                self.assertEqual(context.workflow_navigation.record['actions'][0]['destination_page'], 'messages')

    def test_already_on_notifications_verifies_without_submitting(self):
        context = self.context(bright_sequence()[-2:])
        self.assertEqual(context.workflow_navigation.run().status, 'ok')
        self.assertEqual(context.workflow_navigation.record['actions'], [])
        self.assertEqual(context.submissions, [])

    def test_other_page_target_does_not_press_escape_through_the_notification_panel(self):
        context = self.context(bright_sequence()[-2:])
        navigation = context.workflow_navigation = WorkflowNavigation(context, 'phone')
        navigation._page = Mock(return_value='world')
        with self.assertRaisesRegex(AutomationError, '唯一入口'):
            navigation.run()
        self.assertEqual(navigation.record['actions'], [])
        self.assertEqual(context.submissions, [])

    def test_other_versions_do_not_capture(self):
        context = self.context(world_pair(), version='4.7.0')
        self.assertIn('messages', TARGETS)
        with self.assertRaisesRegex(AutomationError, '尚未校准'):
            context.workflow_navigation.run()
        self.assertEqual(context.capture_sequence, 0)
        self.assertEqual(context.submissions, [])

    def test_missing_source_consensus_and_reused_buffer_prevent_click(self):
        first, second = world_pair()
        transition = bright_sequence()[2]
        for rejected in (transition, replace(second, image=first.image), replace(second, tokens=[OTHER])):
            context = self.context((first, rejected))
            with self.assertRaises(AutomationError):
                context.workflow_navigation.run()
            self.assertEqual(context.submissions, [])

    def test_two_visible_but_displaced_targets_prevent_click(self):
        first, second = world_pair()
        patch = second.image[152:246, 166:298]
        patch[:, 6:] = patch[:, :-6].copy()
        patch[:, :6] = 30
        first_target = world_message_target(first)
        second_target = world_message_target(second)
        self.assertIsNotNone(first_target)
        self.assertIsNotNone(second_target)
        self.assertGreater(second_target.center[0] - first_target.center[0], 2 / 852)
        context = self.context((first, second))
        with self.assertRaisesRegex(AutomationError, '位置'):
            context.workflow_navigation.run()
        self.assertEqual(context.submissions, [])

    def test_account_change_after_click_preserves_one_submission_and_no_arrival(self):
        first, second = bright_sequence()[-2:]
        context = self.context([*world_pair(), first, replace(second, tokens=[OTHER])])
        with self.assertRaisesRegex(AutomationError, '账号'):
            context.workflow_navigation.run()
        self.assert_single_unverified_action(context)

    def test_nonconsecutive_panels_do_not_confirm_arrival_or_repeat_click(self):
        transition, first, second = bright_sequence()[-3:]
        context = self.context([*world_pair(), first, transition, second, transition, first, transition])
        with self.assertRaisesRegex(AutomationError, '连续独立'):
            context.workflow_navigation.run()
        self.assert_single_unverified_action(context)

    def test_interrupted_native_receipt_is_unconfirmed_and_cannot_be_replayed(self):
        context = self.context([*world_pair(), *bright_sequence()[-2:]])
        navigation = context.workflow_navigation
        context.after_click.side_effect = AutomationError('simulated incomplete native batch')
        with self.assertRaisesRegex(AutomationError, 'incomplete'):
            navigation.run()
        self.assertFalse(navigation.record['page_verified'])
        self.assertEqual(navigation.record['actions'][0]['input_status'], 'unconfirmed')
        self.assertEqual(navigation.record['actions'][0]['destination_status'], 'unknown')
        with self.assertRaises(AutomationError):
            navigation.run()
        self.assertEqual(len(context.submissions), 1)

    def test_wrong_page_cannot_start_and_stops_after_one_submission(self):
        phone_scene = phone(ACCOUNT)
        phone_frame = client_frame(phone_scene.image, *phone_scene.tokens)
        mail = replace(bright_sequence()[2], tokens=[ACCOUNT, Token('邮箱', .99, (.03, .027, .072, .054)),
                                                     Token('暂无邮件', .99, (.28, .45, .34, .49))])
        for page in (phone_frame, mail):
            with self.subTest(page=page.tokens[1].text):
                before = self.context((page, replace(page, image=page.image.copy())))
                with self.assertRaisesRegex(AutomationError, '唯一入口'):
                    before.workflow_navigation.run()
                self.assertEqual(before.submissions, [])

                after = self.context([*world_pair(), page, *bright_sequence()[-2:]])
                with self.assertRaisesRegex(AutomationError, '预期之外'):
                    after.workflow_navigation.run()
                self.assert_single_unverified_action(after)
                self.assertEqual(after.capture_sequence, 3)

    def test_focus_or_generation_change_after_click_has_no_retry(self):
        for event, error in (('focus', FocusLost), ('generation', InputInterrupted)):
            with self.subTest(event=event):
                context = self.context([*world_pair(), *bright_sequence()[-2:]])
                def interrupt(*_):
                    if event == 'focus':
                        context.window.guard.side_effect = FocusLost('offline focus loss')
                    else:
                        context.runner.input_epoch += 1

                context.after_click.side_effect = interrupt
                with self.assertRaises(error):
                    context.workflow_navigation.run()
                self.assert_single_unverified_action(context)

    def test_late_focus_loss_before_fake_submission_prevents_click(self):
        context = self.context(world_pair())
        context.before_click.side_effect = lambda: self.focus_on_second_installation_read(context)
        with self.assertRaises(FocusLost):
            context.workflow_navigation.run()
        self.assertEqual(context.submissions, [])
        self.assertEqual(context.workflow_navigation.record['actions'], [])

    def focus_on_second_installation_read(self, context):
        reads = count(1)
        executable = context.window.current_executable.return_value

        def read_executable():
            if next(reads) == 2:
                context.window.guard.side_effect = FocusLost('offline focus loss')
            return executable

        context.window.current_executable.side_effect = read_executable

    def test_late_focus_loss_revokes_published_arrival_but_keeps_submission(self):
        context = self.context([*world_pair(), *bright_sequence()[-2:]])
        navigation = context.workflow_navigation
        report = context.report
        report.results.append(navigation.run())
        report.status = 'success'
        self.assertTrue(navigation.record['page_verified'])
        self.focus_on_second_installation_read(context)
        Runner._save_run_report(context.runner, self.root, workflow_navigation=navigation)
        saved = json.loads((self.root / 'report.json').read_text(encoding='utf8'))
        self.assertEqual(saved['status'], 'partial')
        self.assertFalse(saved['workflow_navigation']['page_verified'])
        self.assertEqual(saved['workflow_navigation']['actions'][0]['input_status'], 'sent')
        self.assertEqual(len(context.submissions), 1)
