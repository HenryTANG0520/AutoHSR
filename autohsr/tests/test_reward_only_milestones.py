"""Daily and reward-only entry points through the native sender with simulated frames."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import ctypes
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2
import numpy as np

from autohsr.__main__ import main
from autohsr.app import Context
from autohsr.config import RESOURCE_ROOT, Settings
from autohsr.models import EmptyCapture, InputInterrupted, Scene
from autohsr.tests.test_core import token
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, _Window
from autohsr.tests.test_redemption_pages import phone_scene
from autohsr.vision import Vision
from autohsr.windows import INPUT
from autohsr.workflows import DailyWorkflow


CENTERS = {100: .333, 200: .459, 300: .586, 400: .713, 500: .840}


def stamp(image, template, x, y):
    path = RESOURCE_ROOT / 'assets' / 'templates' / (template + '.png')
    pixels = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    h, w = pixels.shape[:2]
    left, top = round(x * image.shape[1] - w / 2), round(y * image.shape[0] - h / 2)
    patch = image[top:top+h, left:left+w]
    if pixels.shape[2] == 4:
        alpha = pixels[:, :, 3:4] / 255
        patch[:] = pixels[:, :, :3] * alpha + patch * (1 - alpha)
    else:
        patch[:] = pixels


def training(activity, *, gifts=(), claimed=(), labels=(), account=ACCOUNT, tab='每日实训'):
    image = np.full((1080, 1920, 3), 70, dtype=np.uint8)
    stamp(image, 'daily_activity_badge', .178, .285)
    for points in gifts:
        stamp(image, 'daily_reward', CENTERS[points], .287)
    for points in claimed:
        stamp(image, 'daily_completed', CENTERS[points], .288)
    fields = [account, token('星际和平指南', .082, .05), token(tab, .082, .076),
              token(str(activity), .178, .329)]
    fields.extend(token(str(points), x, .33) for points, x in CENTERS.items())
    return Scene([*fields, *labels], image)


def item_overlay(*, account=ACCOUNT):
    image = np.full((1080, 1920, 3), 40, dtype=np.uint8)
    return Scene([account, token('获得物品', .50, .29), token('点击空白处关闭', .50, .79)], image)


class RewardOnlyMilestonesTests(unittest.TestCase):
    def invoke(self, *phases, short_reward=False, workflow=False, ordinary=False, mail=False):
        clicks = []
        releases = []
        phone = phone_scene()
        phone.tokens.append(ACCOUNT)
        phases = ((phone,), *phases)

        def frames():
            phase, index = None, 0
            while True:
                selected = min(len(clicks), len(phases) - 1)
                if selected != phase:
                    phase, index = selected, 0
                available = phases[phase]
                yield available[min(index, len(available) - 1)]
                index += 1

        def submit(length, raw, _size):
            events = ctypes.cast(raw, ctypes.POINTER(INPUT))
            flags = [events[i].mi.dwFlags for i in range(length)]
            if length == 1:
                self.assertEqual(flags, [4])
                releases.extend(flags)
                return length
            self.assertEqual(flags, [0xC001, 2, 4])
            clicks.append((events[0].mi.dx / 65535, events[0].mi.dy / 65535))
            return 2 if short_reward and len(clicks) == 2 else length

        window = _Window(frames())
        window.focus = Mock()
        native = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0),
                                 GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__),
                                 SendInput=Mock(side_effect=submit))
        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        template = Vision.__new__(Vision).template

        def vision(confidence):
            return SimpleNamespace(read=window.vision(confidence).read, template=template)

        with TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary).resolve()
            config = root / 'config.json'
            Settings(assignments=not ordinary, battle=not ordinary, allow_stamina_spend=not ordinary,
                     daily_synthesis=not ordinary, mail=mail or not ordinary,
                     battlepass=not ordinary, redemption_enabled=not ordinary,
                     overlay_logs=False).save(config)
            saved = config.read_bytes()
            ledger = root / 'runs' / 'battle-session.json'
            ledger.parent.mkdir()
            ledger.write_bytes(b'untouched reward-only test sentinel')
            for name, value in (('autohsr.app.ROOT', root), ('autohsr.task_workflow_run.ROOT', root),
                                ('autohsr.daily_synthesis.ROOT', root),
                                ('autohsr.windows.user32', native),
                                ('autohsr.windows.kernel32', kernel),
                                ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.RewardOnlyQA.' + uuid4().hex),
                                ('autohsr.workflow_lease.NATIVE_NAME', 'Local\\AutoHSR.RewardOnlyNativeQA.' + uuid4().hex)):
                stack.enter_context(patch(name, value))
            for name, options in (
                ('autohsr.app.C.get_last_error', dict(return_value=0)),
                ('autohsr.app.find_game', dict(return_value=window)),
                ('autohsr.app.Vision', dict(side_effect=vision)),
                ('autohsr.app.Runner._arm_hotkeys', {}), ('autohsr.app.Runner._hotkeys', {}),
                ('autohsr.task_workflow_run.TaskWorkflowRunner._hotkeys', {}),
                ('autohsr.app.launch_game', dict(side_effect=AssertionError('no game launch'))),
                ('autohsr.app.is_elevated', dict(return_value=False)),
                ('autohsr.daily_synthesis.complete_once', dict(side_effect=AssertionError('no synthesis'))),
                ('autohsr.daily_synthesis.resume_pending', dict(side_effect=AssertionError('no synthesis recovery'))),
            ):
                stack.enter_context(patch(name, **options))
            for name in ('assignments', 'battle', 'mail', 'battlepass', 'redemption'):
                stack.enter_context(patch.object(DailyWorkflow, name, side_effect=AssertionError('extra task')))
            stack.enter_context(patch.object(Context, 'sleep', lambda context, _duration: context.checkpoint()))
            args = ['--run'] if ordinary else ['--run', '--reward-only']
            if workflow:
                path = root / 'training.json'
                path.write_text(json.dumps(dict(version=1, name='Training rewards',
                                                steps=[dict(id='claim', type='task', task='daily_training_rewards')])),
                                encoding='utf8')
                args = ['--task-workflow', str(path)]
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                code = main([*args, '--config', str(config)])
            report = json.loads(output.getvalue())
            if workflow:
                step, = report['workflow']['steps']
                self.assertTrue(step['account_verified'], step)
                source = Path(step['source']['path'])
                with source.open(encoding='utf8') as stream:
                    child = json.load(stream)
                self.assertEqual(step['facts'], dict(status=child['status'], daily_verified=child['daily_verified']))
                for name in ('status', 'engagement', 'daily_verified', 'stamina_spent', 'stamina_pending',
                             'immersifiers_spent', 'immersifiers_pending'):
                    self.assertEqual(report[name], child[name])
                self.assertTrue(report['report_saved'])
                report = child
            self.assertEqual(report['operation'], 'daily' if ordinary else 'reward_only')
            self.assertEqual(config.read_bytes(), saved)
            self.assertEqual(ledger.read_bytes(), b'untouched reward-only test sentinel')
            self.assertFalse((root / 'runs' / 'daily-synthesis').exists())
            self.assertTrue(report['report_saved'])
            self.assertEqual([item['task'] for item in report['results']], ['daily', 'mail'] if mail else ['daily'])
            self.assertEqual([report[name] for name in ('stamina_spent', 'stamina_pending',
                                                       'immersifiers_spent', 'immersifiers_pending',
                                                       'battle_completed')], [0] * 5)
            with (Path(report['run_dir']) / 'report.json').open(encoding='utf8') as stream:
                self.assertEqual(json.load(stream), report)
        self.assertEqual(releases, [4] if short_reward else [])
        return code, report, clicks

    def test_workflow_native_partial_claim_and_already_complete_report(self):
        old = training(400, gifts=(400,), claimed=(100, 200, 300))
        settled = training(400, claimed=(100, 200, 300, 400))
        code, report, clicks = self.invoke((old,), (item_overlay(),), (settled,), workflow=True)
        self.assertEqual((code, report['status'], report['engagement']), (1, 'partial', 400))
        self.assertEqual(len(clicks), 3)
        self.assertAlmostEqual(clicks[1][0], CENTERS[400], places=2)
        full = training(500, claimed=tuple(CENTERS))
        code, report, clicks = self.invoke((full,), workflow=True)
        self.assertEqual((code, report['status'], report['engagement']), (0, 'success', 500))
        self.assertEqual(len(clicks), 1)

    def test_partial_activity_claims_the_visible_reached_gift_and_requires_return(self):
        old = training(400, gifts=(100, 200, 300, 400))
        settled = training(400, claimed=(100, 200, 300, 400))
        code, report, clicks = self.invoke((old,), (item_overlay(),), (settled,))
        self.assertEqual((code, report['status'], report['engagement'], report['daily_verified']),
                         (1, 'partial', 400, False))
        self.assertEqual(len(clicks), 3)
        self.assertAlmostEqual(clicks[1][0], CENTERS[400], places=2)
        self.assertAlmostEqual(clicks[2][0], .50, places=2)
        self.assertIn('400档已领', report['results'][0]['detail'])

    def test_ordinary_daily_claims_reached_gift_and_blocks_mail_if_feedback_is_unknown(self):
        old = training(400, gifts=(300, 400), claimed=(100, 200))
        settled = training(400, claimed=(100, 200, 300, 400))
        code, report, clicks = self.invoke((old,), (item_overlay(),), (settled,), ordinary=True)
        self.assertEqual((code, report['status'], report['engagement'], report['daily_verified']),
                         (1, 'partial', 400, False))
        self.assertEqual(len(clicks), 3)
        self.assertAlmostEqual(clicks[1][0], CENTERS[400], places=2)
        self.assertIn('300、400档已领', report['results'][0]['detail'])

        code, report, clicks = self.invoke((old,), (old,), ordinary=True, mail=True)
        self.assertEqual((code, report['status'], report['failure_task']), (1, 'partial', 'daily'))
        self.assertEqual(len(clicks), 2)
        self.assertIn('400档本次领取反馈待核对', report['results'][0]['detail'])
        self.assertEqual(report['results'][1]['status'], 'skipped')

    def test_five_claimed_milestones_still_complete_without_reward_input(self):
        full = training(500, claimed=tuple(CENTERS))
        code, report, clicks = self.invoke((full,))
        self.assertEqual((code, report['status'], report['engagement'], report['daily_verified']),
                         (0, 'success', 500, True))
        self.assertEqual(len(clicks), 1)

    def test_only_the_visible_reached_control_is_selected(self):
        old = training(300, gifts=(200,), claimed=(100,), labels=(token('领取奖励', CENTERS[400], .29),))
        settled = training(300, claimed=(100, 200))
        _, report, clicks = self.invoke((old,), (settled,))
        self.assertEqual(len(clicks), 2)
        self.assertAlmostEqual(clicks[1][0], CENTERS[200], places=2)
        self.assertIn('200档已领', report['results'][0]['detail'])
        self.assertFalse(report['daily_verified'])
        for frame in (training(0), training(300, gifts=(200, 400)),
                      training(300, gifts=(200,), labels=(token('300', .179, .33, .72),)),
                      training(300, gifts=(200,), account=token('UID', .06, .97))):
            with self.subTest(frame=frame.tokens):
                _, report, clicks = self.invoke((frame,))
                self.assertEqual(len(clicks), 1)
                self.assertFalse(report['daily_verified'])

    def test_next_visible_reward_waits_for_two_same_slot_return_frames(self):
        old = training(400, gifts=(300, 400), claimed=(100, 200))
        returned = training(400, gifts=(300,), claimed=(100, 200, 400))
        settled = training(400, claimed=(100, 200, 300, 400))
        _, report, clicks = self.invoke((old,), (EmptyCapture('fade'), item_overlay()), (returned,), (settled,))
        self.assertEqual(len(clicks), 4)
        for index, x in enumerate((CENTERS[400], .50, CENTERS[300]), 1):
            self.assertAlmostEqual(clicks[index][0], x, places=2)
        self.assertIn('300、400档已领', report['results'][0]['detail'])

    def test_stale_wrong_page_or_one_mark_never_repeats_the_click(self):
        old = training(400, gifts=(300, 400), claimed=(100, 200))
        stale = training(400, gifts=(300, 400), claimed=(100, 200), labels=(token('动画变化', .51, .58),))
        one_mark = training(400, gifts=(300,), claimed=(100, 200, 400))
        other_page = training(400, gifts=(300,), claimed=(100, 200, 400), tab='生存索引')
        for feedback in ((stale,), (one_mark, stale), (other_page,), (item_overlay(account=OTHER),),
                         (InputInterrupted('input epoch changed'), old)):
            with self.subTest(feedback_type=type(feedback[0]).__name__):
                _, report, clicks = self.invoke((old,), feedback)
                self.assertEqual(len(clicks), 2)
                self.assertIn('400档本次领取反馈待核对', report['results'][0]['detail'])
                self.assertFalse(report['daily_verified'])

    def test_open_overlay_does_not_confirm_a_reward_or_repeat_its_close(self):
        old = training(400, gifts=(400,))
        _, report, clicks = self.invoke((old,), (item_overlay(),))
        self.assertEqual(len(clicks), 3)
        self.assertAlmostEqual(clicks[-1][0], .50, places=2)
        self.assertIn('400档本次领取反馈待核对', report['results'][0]['detail'])
        self.assertFalse(report['daily_verified'])

    def test_duplicate_gifts_or_checkmarks_stop_every_milestone_input(self):
        for marker, states in (
                ('daily_reward', dict(gifts=(100, 400))),
                ('daily_completed', dict(gifts=(400,), claimed=(100,)))):
            for caption_read in (True, False):
                with self.subTest(marker=marker, caption_read=caption_read):
                    old = training(400, **states)
                    stamp(old.image, marker, .260, .287)
                    if caption_read:
                        old.tokens.append(token('100', .260, .33))
                    _, report, clicks = self.invoke((old,))
                    self.assertEqual(len(clicks), 1)  # Only the original guide navigation.
                    self.assertFalse(report['daily_verified'])

    def test_duplicate_return_checkmarks_keep_the_sent_milestone_pending(self):
        old = training(400, gifts=(300, 400))
        returned = training(400, gifts=(300,), claimed=(400,))
        stamp(returned.image, 'daily_completed', .672, .288)
        returned.tokens.append(token('400', .672, .33))
        _, report, clicks = self.invoke((old,), (returned,))
        self.assertEqual(len(clicks), 2)
        self.assertIn('400档本次领取反馈待核对', report['results'][0]['detail'])

    def test_short_native_claim_cannot_authorize_an_item_overlay_close(self):
        old = training(400, gifts=(400,))
        _, report, clicks = self.invoke((old,), (item_overlay(),), short_reward=True)
        self.assertEqual(len(clicks), 2)  # An incomplete claim and its left-button release.
        self.assertIn('400档本次领取反馈待核对', report['results'][0]['detail'])

    def test_ambiguous_item_overlay_cannot_authorize_a_close(self):
        old = training(400, gifts=(400,))
        for extra in (token('获得物品', .60, .32), token('点击空白处关闭', .59, .82)):
            with self.subTest(label=extra.text):
                overlay = item_overlay()
                overlay.tokens.append(extra)
                _, report, clicks = self.invoke((old,), (overlay,))
                self.assertEqual(len(clicks), 2)
                self.assertIn('400档本次领取反馈待核对', report['results'][0]['detail'])
