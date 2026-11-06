"""Native navigation with simulated Win32 packets and scrubbed page fixtures."""

import ctypes
from itertools import chain, count, repeat
from pathlib import Path
from tempfile import TemporaryDirectory
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
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, phone, visa_collection
from autohsr.tests.test_daily_visa_pages import small_visa
from autohsr.tests.test_du_team import fixture
from autohsr.vision import Vision
from autohsr.workflow_battlepass_tabs import small_battlepass_tab
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


def world_hud(name='normal_hud', *tokens):
    source = Path(__file__).parent / 'fixtures' / 'workflow_world' / (name + '.png')
    return Scene([ACCOUNT, *tokens], cv2.imdecode(np.fromfile(source, np.uint8), 1))


class Window:
    click = windows.GameWindow.click
    key = windows.GameWindow.key
    send = windows.GameWindow.send
    emergency_pressed = staticmethod(windows.GameWindow.emergency_pressed)

    def __init__(self):
        self.guard = Mock(return_value=_GEOMETRY)
        self.require_foreground = Mock()
        self.current_window_key = Mock(return_value='synthetic-game-window')
        self.focus = Mock(side_effect=AssertionError('navigation must not focus a window'))


class Context:
    def __init__(self, target, frames, *, geometry=_GEOMETRY):
        self.window = Window()
        self.geometry = geometry
        self.window.guard.return_value = geometry
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
        pixels = cv2.resize(frame.image, (self.geometry.width, self.geometry.height))
        self.last_scene = Scene(list(frame.tokens), pixels, self.geometry, stamp, frame.field_reads.copy())
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

    def _installed_context(self, frames, *, target='visa_characters', geometry=_GEOMETRY):
        install = TemporaryDirectory()
        self.addCleanup(install.cleanup)
        root = Path(install.name).resolve()
        executable = root / 'StarRail.exe'
        executable.touch()
        (root / 'config.ini').write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        context = Context(target, frames, geometry=geometry)
        context.window.current_executable = Mock(return_value=str(executable))
        return context

    def test_visa_switch_retries_only_the_small_heading_in_each_current_frame(self):
        collection = identified(small_visa('collection'))
        role = identified(small_visa('characters'))
        context = self._installed_context([collection, collection, role, role], geometry=windows.Geometry(0, 0, 960, 540))
        context.vision._read_field = Mock(return_value=Token('漫游签证', .88, (0, 0, 1, 1)))
        result = context.workflow_navigation.run()
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.sent, [_CLICK])
        self.assertEqual(context.vision._read_field.call_count, 4)
        self.assertTrue(context.workflow_navigation.record['page_verified'])

    def test_visa_switch_has_no_click_from_obscured_tab_or_inconsistent_source(self):
        source = visa_collection()
        covered = visa_collection()
        tab = next(token for token in covered.tokens if token.text == '角色展示')
        left, top, right, bottom = (round(value * size) for value, size in zip(tab.box, (1920, 1080) * 2))
        covered.image[top:bottom, left:right] = 50
        for tag, frames in (('masked tab', [source, covered]), ('phone', [phone()] * 2),
                            ('other account', [source, visa_collection(account=OTHER)]),
                            ('nonadjacent', [source, EmptyCapture('fade'), source]),
                            ('wrong tab', [visa_collection('battle-record')] * 2)):
            with self.subTest(tag=tag):
                context = self._installed_context(frames)
                with self.assertRaises(AutomationError):
                    context.workflow_navigation.run()
                self.assertEqual(self.sent, [])
                self.assertEqual(context.workflow_navigation.record['actions'], [])
                self.assertFalse(context.workflow_navigation.record['page_verified'])

    def test_visa_switch_does_not_repeat_when_destination_has_no_same_account_pair(self):
        source = visa_collection()
        role = visa_collection('characters')
        cases = (('still on collection', [source] * 6),
                 ('gap on role page', [role, EmptyCapture('fade'), role]),
                 ('other account', [visa_collection('characters', account=OTHER)] * 2))
        for tag, after in cases:
            with self.subTest(tag=tag):
                self.sent.clear()
                context = self._installed_context([source, source, *after])
                with self.assertRaises(AutomationError):
                    context.workflow_navigation.run()
                self.assertEqual(self.sent, [_CLICK])
                [action] = context.workflow_navigation.record['actions']
                self.assertEqual((action['input_status'], action['destination_status']), ('sent', 'unknown'))
                self.assertFalse(context.workflow_navigation.record['page_verified'])

    def test_visa_switch_stops_at_native_boundary_or_records_short_send_without_retry(self):
        context = self._installed_context([visa_collection()] * 2)
        native_click = context.window.click

        def stop_before_click(*args, **kwargs):
            self.native.GetAsyncKeyState.return_value = 0x8001
            return native_click(*args, **kwargs)

        context.window.click = stop_before_click
        with self.assertRaises(Stopped):
            context.workflow_navigation.run()
        self.assertEqual(self.sent, [])
        self.assertEqual(context.workflow_navigation.record['actions'], [])

        self.native.GetAsyncKeyState.return_value = 0

        def short(count, events, size):
            self.send(count, events, size)
            return 2 if count == 3 else count

        self.native.SendInput.side_effect = short
        context = self._installed_context([visa_collection()] * 2 + [visa_collection('characters')] * 2)
        with self.assertRaises(AutomationError):
            context.workflow_navigation.run()
        self.assertEqual(self.sent, [_CLICK, ((0, 0x0004),)])
        [action] = context.workflow_navigation.record['actions']
        self.assertEqual((action['input_status'], action['destination_status']), ('unconfirmed', 'unknown'))
        self.assertFalse(context.workflow_navigation.record['page_verified'])

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

    def test_battlepass_subpages_reject_ambiguous_heading_covered_tab_modal_and_unrelated_page(self):
        tasks = identified(fixture('bp_tasks_claimable'))
        rewards = identified(fixture('bp_rewards_claimable'))
        covered = Scene(tasks.tokens, tasks.image.copy())
        height, width = covered.image.shape[:2]
        covered.image[:round(.09 * height), round(.42 * width):round(.48 * width)] = 40
        for label, frames in (
                ('conflicting heading', [Scene([*tasks.tokens, badge('奖励', .29, .05, score=.72)], tasks.image)] * 2),
                ('missing tab', [tasks, covered]),
                ('different initial tabs', [tasks, rewards]),
                ('reward popup', [Scene([*tasks.tokens, badge('获得物品', .5, .25)], tasks.image)] * 2),
                ('unrelated page', [self.mail] * 2),
        ):
            with self.subTest(label=label):
                context = self._installed_context(frames, target='battlepass_rewards')
                with self.assertRaises(AutomationError):
                    context.workflow_navigation.run()
                self.assertEqual(context.report.workflow_navigation['actions'], [])
                self.assertFalse(context.report.workflow_navigation['page_verified'])
        self.assertEqual(self.sent, [])

    def test_battlepass_subpage_switch_does_not_replay_or_verify_wrong_return(self):
        tasks = identified(fixture('bp_tasks_settled'))
        rewards = identified(fixture('bp_rewards_claimable'))
        conflict = Scene([OTHER, *[token for token in rewards.tokens if token != ACCOUNT]], rewards.image)
        for label, after in (('same tab', [tasks] * 6), ('different account', [conflict] * 2),
                             ('one fresh frame', [rewards, EmptyCapture('fade')])):
            with self.subTest(label=label):
                self.sent.clear()
                context = self._installed_context([tasks, tasks, *after], target='battlepass_rewards')
                with self.assertRaises(AutomationError):
                    context.workflow_navigation.run()
                self.assertEqual(self.sent, [_CLICK])
                [action] = context.report.workflow_navigation['actions']
                self.assertEqual((action['input_status'], action['destination_status']), ('sent', 'unknown'))
                self.assertFalse(context.report.workflow_navigation['page_verified'])

    def test_small_battlepass_matches_both_inactive_glyphs_with_the_original_threshold(self):
        nav = Context('battlepass_tasks', ()).workflow_navigation
        for name, selected, target, expected_x in (
                ('bp_tasks_claimable', 'tasks', 'rewards', .45), ('bp_period_settled', 'tasks', 'rewards', .45),
                ('bp_rewards_claimable', 'rewards', 'tasks', .50), ('bp_rewards_settled', 'rewards', 'tasks', .50)):
            frame = fixture(name)
            for width, height in ((960, 540), (1280, 720)):
                for method in (cv2.INTER_AREA, cv2.INTER_LINEAR):
                    with self.subTest(name=name, width=width, method=method):
                        image = cv2.resize(frame.image, (width, height), interpolation=method)
                        self.assertEqual(nav._page(Scene(frame.tokens, image)), 'battlepass_' + selected)
                        token = small_battlepass_tab(image, target)
                        self.assertIsNotNone(token)
                        self.assertGreaterEqual(token.score, .94)
                        self.assertAlmostEqual(token.center[0], expected_x, delta=.002)
                        self.assertIsNone(small_battlepass_tab(image, selected))

    def test_small_battlepass_requires_the_actual_inactive_glyph_and_selected_line(self):
        original = identified(fixture('bp_rewards_claimable'))
        for width, height in ((960, 540), (1280, 720)):
            source = cv2.resize(original.image, (width, height), interpolation=cv2.INTER_AREA)
            covered, wrong_icon, wrong_line, double_line = (source.copy() for _ in range(4))
            top, bottom = round(.03 * height), round(.084 * height)
            left, right = round(.48 * width), round(.52 * width)
            covered[top:bottom, left:right] = 40
            # The neighboring slot has a glyph on the same bar but serves a different function.
            offset = round(.05 * width)
            wrong_icon[top:bottom, left:right] = source[top:bottom, left + offset:right + offset]
            top, bottom = round(.093 * height), round(.104 * height)
            active_left, active_right = round(.43 * width), round(.47 * width)
            wrong_line[top:bottom, active_left:active_right] = 40
            double_line[top:bottom, left:right] = source[top:bottom, active_left:active_right]
            for name, image in (('covered', covered), ('wrong glyph', wrong_icon), ('missing underline', wrong_line),
                                ('double underline', double_line)):
                with self.subTest(width=width, name=name):
                    scene = Scene(original.tokens, image)
                    context = self._installed_context([scene] * 2, target='battlepass_tasks',
                                                      geometry=windows.Geometry(0, 0, width, height))
                    with self.assertRaises(AutomationError):
                        context.workflow_navigation.run()
                    self.assertEqual(context.report.workflow_navigation['actions'], [])
        self.assertEqual(self.sent, [])

    def test_small_battlepass_cannot_confirm_arrival_while_the_old_tab_stays_selected(self):
        source = identified(fixture('bp_rewards_claimable'))
        destination = identified(fixture('bp_tasks_claimable'))
        stale = Scene(destination.tokens, source.image)
        context = self._installed_context([source, source, *([stale] * 6)], target='battlepass_tasks',
                                          geometry=windows.Geometry(0, 0, 960, 540))
        with self.assertRaises(AutomationError):
            context.workflow_navigation.run()
        self.assertEqual(self.sent, [_CLICK])
        [action] = context.report.workflow_navigation['actions']
        self.assertEqual((action['input_status'], action['destination_status']), ('sent', 'unknown'))
        self.assertFalse(context.report.workflow_navigation['page_verified'])

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

    def test_world_target_returns_from_verified_daily_panels_and_never_reopens_phone(self):
        menu = identified(fixture('phone_mail_icon'))
        for name, source in (('daily_training', self.daily), ('survival_index', self.survival),
                             ('assignments', self.assignments), ('mail', self.mail),
                             ('battlepass', identified(fixture('bp_rewards_claimable')))):
            with self.subTest(name=name):
                self.sent.clear()
                frames = (source, source, menu, menu, world_hud(), world_hud())
                context = self._installed_context(frames, target='world')
                self.assertEqual(context.workflow_navigation.run().status, 'ok')
                self.assertEqual(self.sent, [_DOWN, _UP, _DOWN, _UP])
                rows = context.report.workflow_navigation['actions']
                self.assertEqual([(row['action'], row['source_page'], row['destination_page']) for row in rows],
                                 [('return_to_hub', name, 'phone'), ('return_to_hub', 'phone', 'world')])

    def test_world_target_vetoes_overlay_and_rejects_du_hud_without_ocr(self):
        examples = [world(), world_hud('du_hud')]
        for label in ('跳过剧情', '扫码登录', '确认付款', '获得物品', '战斗失败'):
            examples.append(world_hud('normal_hud', badge(label, .5, .45)))
            examples.append(phone(badge(label, .5, .45)))
        examples.append(world_hud('normal_hud', badge('奖励指南', .11, .05)))
        examples.append(world_hud('normal_hud', badge('（13/13）第三位面-首领', .11, .028)))
        for index, frame in enumerate(examples):
            with self.subTest(index=index):
                context = self._installed_context([frame] * 2, target='world')
                with self.assertRaises(AutomationError):
                    context.workflow_navigation.run()
                self.assertFalse(context.report.workflow_navigation['page_verified'])
                self.assertEqual(context.report.workflow_navigation['actions'], [])
        self.assertEqual(self.sent, [])

    def test_world_target_preserves_first_escape_without_replaying_unknown_feedback(self):
        menu = identified(fixture('phone_mail_icon'))
        for after in (menu, world_hud('du_hud'), world_hud('normal_hud', badge('跳过剧情', .5, .48))):
            with self.subTest(after=after.text):
                self.sent.clear()
                context = self._installed_context([menu, menu, *([after] * 6)], target='world')
                with self.assertRaises(AutomationError):
                    context.workflow_navigation.run()
                self.assertEqual(self.sent, [_DOWN, _UP])
                [row] = context.report.workflow_navigation['actions']
                self.assertEqual((row['input_status'], row['destination_status']), ('sent', 'unknown'))

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
