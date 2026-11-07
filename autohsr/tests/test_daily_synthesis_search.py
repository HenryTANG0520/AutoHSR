"""Daily synthesis fallback over native wheel input and calibrated card geometry."""

import ctypes
from dataclasses import replace
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import windows
from autohsr.daily_synthesis import task_target
from autohsr.daily_synthesis_search import find_hidden_card
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


class DailySynthesisSearchTests(TestCase):
    def setUp(self):
        ticks = count(10_000)
        def monotonic():
            return next(ticks) / 1000.

        self.enterContext(patch('time.monotonic', monotonic))
        self.enterContext(patch('autohsr.daily_synthesis.monotonic', monotonic))
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.exe = self.root / 'StarRail.exe'
        self.exe.touch()
        self.ini = self.root / 'config.ini'
        self.ini.write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        self.initial, self.shifted, self.full = training_frames()
        self.packets = []
        self.accepted = 2

        def submit(count, raw, _size):
            events = ctypes.cast(raw, ctypes.POINTER(windows.INPUT))
            self.assertEqual(count, 2)
            self.packets.append((events[0].mi.dwFlags, events[1].mi.dwFlags, events[1].mi.mouseData))
            return self.accepted

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
        scene, found = find_hidden_card(workflow, workflow.ctx.snapshot(), 400)
        self.assertIs(scene, workflow.ctx.last_scene)
        self.assertFalse(found)
        self.assertEqual(len(self.packets), 1)
        self.assertEqual(workflow.ctx.report.training_synthesis_search, dict(state='no_movement', scrolls=['sent']))

    def test_account_change_or_short_send_cannot_offer_a_craft(self):
        other = replace(self.shifted, tokens=[OTHER if token == ACCOUNT else token for token in self.shifted.tokens])
        for after, accepted, expected in ((other, 2, 'sent'), (self.shifted, 1, 'unconfirmed')):
            with self.subTest(accepted=accepted):
                self.packets.clear()
                self.accepted = accepted
                workflow = self.workflow(after)
                with self.assertRaises(AutomationError):
                    find_hidden_card(workflow, workflow.ctx.snapshot(), 400)
                self.assertEqual(len(self.packets), 1)
                self.assertEqual(workflow.ctx.report.training_synthesis_search,
                                 dict(state='unverified', scrolls=[expected]))

    def test_reward_only_and_uncalibrated_installation_never_scroll(self):
        workflow = self.workflow(self.shifted)
        scene = workflow.ctx.snapshot()
        workflow.ctx.report.operation = 'reward_only'
        self.assertEqual(find_hidden_card(workflow, scene, 400), (scene, False))
        workflow.ctx.report.operation = 'daily'
        self.ini.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
        self.assertEqual(find_hidden_card(workflow, scene, 400), (scene, False))
        self.assertEqual(self.packets, [])
        self.assertEqual(workflow.ctx.report.training_synthesis_search, {})

    def test_visible_end_does_not_trigger_a_search_scroll(self):
        image = self.initial.image.copy()
        image[264:596, 1060:1104] = image[264:596, 1050:1051]
        self.initial = replace(self.initial, image=image)
        workflow = self.workflow(self.shifted)
        scene = workflow.ctx.snapshot()
        self.assertEqual(find_hidden_card(workflow, scene, 400), (scene, False))
        self.assertEqual(self.packets, [])
