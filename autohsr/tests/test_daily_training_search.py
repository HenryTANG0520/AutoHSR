"""Daily task fallback over native wheel input and calibrated card geometry."""

import ctypes
from dataclasses import replace
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import windows
from autohsr.app import Context as NativeContext
from autohsr.daily_support import observe as observe_support
from autohsr.daily_synthesis import task_target
from autohsr.daily_training_card_claim import claim_task_points
from autohsr.models import AutomationError, Scene
from autohsr.tests.test_daily_synthesis import card
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_workflow_navigation import ACCOUNT, OTHER, Context, identified
from autohsr.workflows import DailyWorkflow


def training_frames():
    full = identified(fixture('daily_survival_badge'))
    tokens = []
    for token in full.tokens:
        x, y = token.center
        text = token.text
        if text == '500' and .15 <= x <= .205 and .30 <= y <= .36:
            text = '400'
        elif text == '本日活跃度已满':
            text = '已领取' if x < .50 else '进行中'
        tokens.append(replace(token, text=text))
    initial = replace(full, tokens=tokens)
    image = initial.image.copy()
    shift = 172
    image[264:596, 184:1104-shift] = initial.image[264:596, 184+shift:1104]
    image[264:596, 906:1100] = initial.image[264:596, 184:378]

    def move(token, delta):
        x1, y1, x2, y2 = token.box
        return replace(token, box=(x1+delta, y1, x2+delta, y2))

    shifted = []
    for token in initial.tokens:
        x, y = token.center
        if not .37 <= y <= .82:
            shifted.append(token)
        elif .32 <= x <= .825:
            shifted.append(move(token, -shift/1280))
    shifted.extend(move(token, .20625) for token in card().tokens if .37 <= token.center[1] <= .82)
    return initial, Scene(shifted, image), full


class DailyTrainingSearchTests(TestCase):
    def setUp(self):
        ticks = count(10_000)
        def monotonic():
            return next(ticks) / 1000.

        self.enterContext(patch('time.monotonic', monotonic))
        self.enterContext(patch('autohsr.daily_synthesis.monotonic', monotonic))
        self.enterContext(patch('autohsr.daily_support.monotonic', monotonic))
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.exe = self.root / 'StarRail.exe'
        self.exe.touch()
        self.ini = self.root / 'config.ini'
        self.ini.write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        self.initial, self.shifted, self.full = training_frames()
        self.packets = []
        self.accepted = 2
        self.click_accepted = 3

        def submit(count, raw, _size):
            events = ctypes.cast(raw, ctypes.POINTER(windows.INPUT))
            if count == 2:
                self.packets.append((events[0].mi.dwFlags, events[1].mi.dwFlags, events[1].mi.mouseData))
                return self.accepted
            if count == 1:
                self.assertEqual(events[0].mi.dwFlags, 4)
                self.packets.append((4,))
                return count
            self.assertEqual(count, 3)
            self.packets.append(tuple(events[index].mi.dwFlags for index in range(count)))
            return self.click_accepted

        native = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0),
            GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__),
            SendInput=Mock(side_effect=submit))
        self.enterContext(patch.object(windows, 'user32', native))

    def workflow(self, after):
        def frames():
            while True:
                yield after if self.packets else self.initial

        ctx = Context('daily_training', frames())
        ctx.report.operation = 'daily'
        ctx.window.current_executable = Mock(return_value=str(self.exe))
        ctx.window.scroll_down_once = windows.GameWindow.scroll_down_once.__get__(ctx.window)
        ctx._require_gameplay_input = Mock()
        ctx.training_task_points_input = NativeContext.training_task_points_input.__get__(ctx)
        ctx.log = Mock()
        ctx.evidence = Mock()
        return DailyWorkflow(ctx)

    def test_normal_daily_hands_the_new_card_to_original_synthesis_once(self):
        workflow = self.workflow(self.shifted)
        ctx = workflow.ctx
        workflow._open_guide = Mock(side_effect=lambda _tab: ctx.snapshot())

        def synthesize(current, scene):
            self.assertIs(current, workflow)
            self.assertIs(ctx.last_scene, scene)
            self.assertIsNotNone(task_target(scene))
            ctx.frames = iter([self.full] * 5)

        with patch('autohsr.daily_synthesis.complete_once', side_effect=synthesize) as craft:
            result = workflow.daily()
        self.assertEqual(result.status, 'ok')
        craft.assert_called_once()
        self.assertEqual(self.packets, [(0xC001, 0x0800, (-120) & 0xFFFFFFFF)])
        self.assertEqual(ctx.report.training_synthesis_search, dict(state='found', scrolls=['sent']))

    def test_no_movement_reads_again_without_resending(self):
        workflow = self.workflow(self.initial)
        scene, found = claim_task_points(workflow, workflow.ctx.snapshot(), 400, look_for_synthesis=True)
        self.assertIs(scene, workflow.ctx.last_scene)
        self.assertFalse(found)
        self.assertEqual(len(self.packets), 1)
        self.assertEqual(workflow.ctx.report.training_task_points[0]['search'], dict(state='no_movement', scrolls=['sent']))

    def test_account_change_or_short_send_cannot_offer_a_craft(self):
        other = replace(self.shifted, tokens=[OTHER if token == ACCOUNT else token for token in self.shifted.tokens])
        for after, accepted, expected in ((other, 2, 'sent'), (self.shifted, 1, 'unconfirmed')):
            with self.subTest(accepted=accepted):
                self.packets.clear()
                self.accepted = accepted
                workflow = self.workflow(after)
                with self.assertRaises(AutomationError):
                    claim_task_points(workflow, workflow.ctx.snapshot(), 400, look_for_synthesis=True)
                self.assertEqual(len(self.packets), 1)
                self.assertEqual(workflow.ctx.report.training_task_points[0]['search'],
                                 dict(state='unverified', scrolls=[expected]))

    def test_reward_only_search_skips_synthesis_and_uncalibrated_installation_never_scrolls(self):
        workflow = self.workflow(self.shifted)
        scene = workflow.ctx.snapshot()
        workflow.ctx.report.operation = 'reward_only'
        _, result = claim_task_points(workflow, scene, 400, look_for_synthesis=True)
        self.assertIsNone(result)
        self.assertEqual(len(self.packets), 1)
        self.assertEqual(workflow.ctx.report.training_synthesis_search, {})
        self.packets.clear()
        workflow.ctx.report.operation = 'daily'
        self.ini.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
        scene = workflow.ctx.snapshot()
        self.assertEqual(claim_task_points(workflow, scene, 400, look_for_synthesis=True), (scene, None))
        self.assertEqual(self.packets, [])
        self.assertEqual(workflow.ctx.report.training_synthesis_search, {})

    def test_visible_end_does_not_trigger_a_search_scroll(self):
        image = self.initial.image.copy()
        image[264:596, 1060:1104] = image[264:596, 1050:1051]
        self.initial = replace(self.initial, image=image)
        workflow = self.workflow(self.shifted)
        scene = workflow.ctx.snapshot()
        self.assertEqual(claim_task_points(workflow, scene, 400, look_for_synthesis=True), (scene, None))
        self.assertEqual(self.packets, [])

    def support_workflow(self, progress, control, *, already_shifted=False):
        def in_card(token, left, right):
            return token.within((left, .375, right, .81))

        source = [token for token in self.initial.tokens if in_card(token, .675, .825)]
        self.initial = replace(self.initial,
            tokens=[token for token in self.initial.tokens if not in_card(token, .675, .825)])
        tokens = [token for token in self.shifted.tokens if not in_card(token, .54, .864)]
        for token in source:
            x1, y1, x2, y2 = token.box
            text = (f'进度{progress}' if token.text.startswith('进度')
                    else control if token.text == '进行中' else token.text)
            tokens.append(replace(token, text=text, box=(x1+.039, y1, x2+.039, y2)))
        shifted = replace(self.shifted, tokens=tokens)
        if already_shifted:
            self.initial = shifted
        workflow = self.workflow(shifted)
        workflow.settings.use_support = workflow.settings.support_daily_only = True
        workflow._open_guide = Mock(side_effect=lambda _tab: workflow.ctx.snapshot())
        return workflow

    def test_hidden_support_uses_the_real_progress_to_decide_borrowing(self):
        original = self.initial
        for progress, control, expected in (('0/1', '进行中', 'needed'), ('1/1', '领取', 'completed')):
            with self.subTest(progress=progress):
                self.packets.clear()
                self.initial = original
                workflow = self.support_workflow(progress, control)
                decision = observe_support(workflow)
                self.assertEqual(decision.state, expected)
                decision.require(workflow.ctx, workflow.ctx.last_scene)
                record, = workflow.ctx.report.support_selections
                self.assertEqual(record['state'], expected)
                self.assertEqual(record['search'], dict(state='found', scrolls=['sent']))
                self.assertEqual(len(self.packets), 1)

    def test_support_already_visible_at_shifted_position_requires_no_scroll(self):
        workflow = self.support_workflow('0/1', '进行中', already_shifted=True)
        self.assertEqual(observe_support(workflow).state, 'needed')
        self.assertEqual(workflow.ctx.report.support_selections[0]['search'], dict(state='found', scrolls=[]))
        self.assertEqual(self.packets, [])

    def test_uncertain_support_card_does_not_reach_dungeon_or_payment(self):
        workflow = self.support_workflow('0/1', '前往')
        workflow.settings.allow_stamina_spend = True
        workflow._open_calyx = Mock(side_effect=AssertionError('unverified card must stop before dungeon'))
        with self.assertRaisesRegex(AutomationError, '支援需求未核实'):
            workflow.battle()
        workflow._open_calyx.assert_not_called()
        self.assertEqual(workflow.ctx.report.stamina_pending, 0)
        record, = workflow.ctx.report.support_selections
        self.assertEqual(record['state'], 'unknown')
        self.assertEqual(record['search'], dict(state='right_edge_clear', scrolls=['sent']))

    def claim_workflow(self, *, mode='daily', gold=True, confirmed=True, visible=False):
        tokens = [replace(token, text='进度1/1') if token.text == '进度0/1' and token.center[0] > .70 else
                  replace(token, text='领取') if token.text == '前往' else token
                  for token in self.shifted.tokens]
        image = self.shifted.image.copy()
        target, = (token for token in tokens if token.text == '领取')
        x1, y1, x2, y2 = (round(value*size) for value, size in zip(target.box, (1280, 720)*2))
        image[y1:y2, x1:x2] = (89, 200, 255) if gold else (100, 100, 100)
        offered = replace(self.shifted, tokens=tokens, image=image)
        after = []
        for token in tokens:
            text = token.text
            if text == '400' and .15 <= token.center[0] <= .205 and .30 <= token.center[1] <= .36:
                text = '500'
            elif text == '进行中' or text == '领取' and confirmed:
                text = '本日活跃度已满'
            after.append(replace(token, text=text))

        def frames():
            views = (offered, replace(offered, tokens=after))
            if not visible:
                views = (self.initial, *views)
            while True:
                yield views[min(len(views) - 1, len(self.packets))]

        workflow = self.workflow(offered)
        workflow.ctx.frames = frames()
        workflow.ctx.report.operation = mode
        workflow._open_guide = Mock(side_effect=lambda _tab: workflow.ctx.snapshot())
        return workflow

    def test_daily_and_reward_only_claim_the_hidden_card_then_verify_cap_and_same_card(self):
        for mode in ('daily', 'reward_only'):
            with self.subTest(mode=mode):
                self.packets.clear()
                workflow = self.claim_workflow(mode=mode)
                with patch('autohsr.daily_synthesis.complete_once') as craft:
                    self.assertEqual(workflow.daily().status, 'ok')
                craft.assert_not_called()
                record, = workflow.ctx.report.training_task_points
                self.assertEqual((record['task'], record['activity_before'], record['activity_after']),
                                 ('synthesis', 400, 500))
                self.assertEqual((record['input'], record['feedback']), ('sent', 'confirmed'))
                self.assertEqual(self.packets, [(0xC001, 0x0800, (-120) & 0xFFFFFFFF), (0xC001, 2, 4)])

    def test_visible_card_uses_the_same_receipt_without_scrolling(self):
        for mode in ('daily', 'reward_only'):
            with self.subTest(mode=mode):
                self.packets.clear()
                workflow = self.claim_workflow(mode=mode, visible=True)
                self.assertEqual(workflow.daily().status, 'ok')
                record, = workflow.ctx.report.training_task_points
                self.assertEqual(record['search'], dict(state='found', scrolls=[]))
                self.assertEqual((record['input'], record['feedback'], record['activity_after']),
                                 ('sent', 'confirmed', 500))
                self.assertEqual(self.packets, [(0xC001, 2, 4)])

    def test_visible_label_alone_never_uses_a_generic_click(self):
        for gray, version in ((True, '4.6.0'), (False, '4.7.0')):
            with self.subTest(gray=gray, version=version):
                self.ini.write_text(f'[General]\ngame_version={version}\n', encoding='utf8')
                workflow = self.claim_workflow(mode='reward_only', gold=not gray, visible=True)
                result = workflow.daily()
                self.assertEqual(result.status, 'partial')
                self.assertIn('领取状态待核对', result.detail)
                record, = workflow.ctx.report.training_task_points
                self.assertEqual((record['input'], record['feedback']), ('not_sent', 'unknown'))
                self.assertFalse(workflow.ctx.report.training_milestones)
                self.assertEqual(self.packets, [])

    def test_activity_gain_alone_cannot_confirm_or_retry_the_claim(self):
        workflow = self.claim_workflow(confirmed=False)
        with self.assertRaisesRegex(AutomationError, '反馈待核对'):
            workflow.daily()
        record, = workflow.ctx.report.training_task_points
        self.assertEqual((record['input'], record['feedback']), ('sent', 'unknown'))
        self.assertEqual(len(self.packets), 2)

    def test_gray_label_after_scroll_does_not_trigger_a_claim(self):
        workflow = self.claim_workflow(gold=False)
        _, confirmed = claim_task_points(workflow, workflow.ctx.snapshot(), 400)
        self.assertFalse(confirmed)
        record, = workflow.ctx.report.training_task_points
        self.assertEqual((record['input'], record['search']['state']), ('not_sent', 'right_edge_clear'))
        self.assertEqual(len(self.packets), 1)

    def test_partial_card_click_releases_and_stops_with_unconfirmed_receipt(self):
        workflow = self.claim_workflow()
        self.click_accepted = 2
        with self.assertRaises(AutomationError):
            workflow.daily()
        record, = workflow.ctx.report.training_task_points
        self.assertEqual((record['input'], record['feedback']), ('unconfirmed', 'unknown'))
        self.assertEqual(self.packets[1:], [(0xC001, 2, 4), (4,)])
