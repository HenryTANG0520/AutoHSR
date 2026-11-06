"""The existing JSON assignment selection through native Runner and fake Win32."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.models import AutomationError, InputInterrupted, Scene
from autohsr.tests.test_core import assignments_scene, token
from autohsr.tests.test_daily_startup import phone, supply
from autohsr.tests.test_du_team import fixture
from autohsr.workflows import DailyWorkflow


GEOMETRY = windows.Geometry(0, 0, 960, 540)
ACCOUNT = 'UID:100000000'
OTHER = 'UID:100000001'


class AssignmentOnlyTests(unittest.TestCase):
    def invoke(self, start='phone', *, event=None, workflow=True, active_scene=None, overrides=None):
        folder = TemporaryDirectory(prefix='autohsr-assignment-only-')
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config = root / 'settings.json'
        Settings(assignments=True, battle=workflow, daily=workflow, mail=workflow, battlepass=workflow,
                 daily_synthesis=False, overlay_logs=False).save(config)
        original = config.read_bytes()
        document = root / 'only-assignments.json'
        document.write_text(json.dumps(dict(version=1, name='委托',
            steps=[dict(id='assignments', type='task', task='daily', params=dict(tasks=['assignments']))])),
            encoding='utf8')
        mode = start
        current = None
        active = None
        sent = []
        submitted = False
        interrupted = False
        claim_guards = 0
        extra_uid = None
        actual_account = ACCOUNT
        clean = fixture('assignments_after_claim')
        active_scene = active_scene if active_scene is not None else assignments_scene(claim='enabled')
        active_scene = replace(active_scene, tokens=[
            replace(field, text='已进行：28/30小时') if field.text.startswith('已进行') else field
            for field in active_scene.tokens
        ])
        window = windows.GameWindow.__new__(windows.GameWindow)
        window.hwnd, window.path, window.focus = 50974, None, Mock()
        native = Mock()
        native.IsWindow.return_value = 1
        native.IsIconic.return_value = 0
        native.GetForegroundWindow.return_value = window.hwnd
        native.GetAsyncKeyState.return_value = 0
        native.GetSystemMetrics.side_effect = {76:0, 77:0, 78:1920, 79:1080}.__getitem__
        native.MapVirtualKeyW.return_value = 1

        class SyntheticContext(Context):
            def __init__(self, runner, observed_window, vision):
                super().__init__(runner, observed_window, vision)
                window.owner, window.context = runner, self

            def sleep(self, seconds):
                self.checkpoint()

            def wait(self, predicate, timeout=30, description='界面'):
                for _ in range(5):
                    scene = self.snapshot()
                    if predicate(scene):
                        return scene
                raise AutomationError('测试画面尚未到达：' + description)

        def capture():
            nonlocal current
            pages = {
                'phone': phone,
                'supply': supply,
                'supply-revealed': lambda: supply(revealed=True),
                'login-reward': lambda: Scene([token('获得物品', .50, .11),
                                               token('点击空白处关闭', .50, .87)]),
                'active': lambda: active_scene,
                'disabled': lambda: clean,
                'reward': lambda: Scene([token('获得物品', .50, .11),
                                          token('点击空白处关闭', .50, .87)]),
                'legacy': lambda: Scene([token('委托', .08, .06), token('一键领取', .82, .87),
                                          token('再次派遣', .50, .86)]),
            }
            scene = (overrides or {}).get(mode, pages[mode])()
            tokens = [field for field in scene.tokens if not field.text.startswith('UID:')]
            if mode not in ('supply', 'supply-revealed', 'reward', 'login-reward'):
                tokens.append(token(actual_account, .08, .97, .99))
            if extra_uid is not None:
                tokens.append(extra_uid)
            image = scene.image
            if image is None:
                image = np.full((540, 960, 3), 35, np.uint8)
            elif image.shape[:2] != (540, 960):
                image = cv2.resize(image, (960, 540))
            current = replace(scene, tokens=tokens, image=image, geometry=GEOMETRY)
            return image, GEOMETRY

        def click(x, y, expected, **options):
            nonlocal active, interrupted
            active = next(field.text for field in current.tokens
                          if abs(field.center[0]-x)<1e-6 and abs(field.center[1]-y)<1e-6)
            try:
                windows.GameWindow.click(window, x, y, expected, **options)
                if active == '领取奖励' and event == 'interrupt_after_claim' and not interrupted:
                    interrupted = True
                    window.owner.input_epoch += 1
                    raise InputInterrupted('fixture lost input after native submission')
            finally:
                active = None

        def key(name, **options):
            nonlocal active
            active = name
            try:
                return windows.GameWindow.key(window, name, **options)
            finally:
                active = None

        def foreground():
            nonlocal claim_guards
            if active == '领取奖励':
                claim_guards += 1
                if claim_guards == 3:
                    if event == 'epoch_before_native':
                        window.owner.input_epoch += 1
                    if event == 'other_uid_before_native':
                        window.context.last_scene.field_reads['uid_counterevidence'] = (token(OTHER, .08, .97, .74),)
                    if event == 'focus_before_native':
                        return window.hwnd + 1
            return window.hwnd

        def send(count, _events, _size):
            nonlocal mode, submitted, actual_account
            sent.append(active)
            if active == '点击领取今日补给':
                mode = 'supply-revealed' if mode == 'supply' else 'phone'
            elif active == '委托':
                mode = start if start in ('disabled', 'legacy') else 'active'
            elif active == '一键领取':
                mode = 'disabled'
            elif active == '领取奖励':
                if submitted or event != 'interrupt_after_claim':
                    mode = 'reward'
                if event == 'other_uid_after_claim':
                    mode, actual_account = 'active', OTHER
                submitted = True
            elif active == '点击空白处关闭':
                mode = 'phone' if mode == 'login-reward' else 'disabled'
            elif active == 'esc':
                mode = 'phone'
            else:
                raise AssertionError(f'non-assignment fixture input {active!r}')
            return count

        window.capture, window.click, window.key = capture, click, key
        native.GetForegroundWindow.side_effect = foreground
        native.GetAsyncKeyState.side_effect = lambda code: (
            0x8000 if code == 0x79 and event == 'stop_before_native' and active == '领取奖励' and claim_guards >= 3 else 0)
        native.SendInput.side_effect = send
        vision = SimpleNamespace(read=lambda *_: replace(current, tokens=list(current.tokens)), template=lambda *_: None)
        native_mutex = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        out, err = io.StringIO(), io.StringIO()
        with (ExitStack() as stack, redirect_stdout(out), redirect_stderr(err)):
            for name, value in (
                ('autohsr.app.ROOT', root), ('autohsr.task_workflow_run.ROOT', root),
                ('autohsr.app.Context', SyntheticContext), ('autohsr.app.threading.Thread', Mock()),
                ('autohsr.app.C.get_last_error', Mock(return_value=0)), ('autohsr.app.is_elevated', Mock(return_value=False)),
                ('autohsr.app.find_game', Mock(return_value=window)), ('autohsr.app.launch_game', Mock(side_effect=AssertionError)),
                ('autohsr.app.Vision', Mock(return_value=vision)), ('autohsr.windows.user32', native),
                ('autohsr.windows.kernel32', native_mutex), ('autohsr.windows.geometry', Mock(return_value=GEOMETRY)),
                ('autohsr.windows.time.sleep', Mock()),
            ):
                stack.enter_context(patch(name, value))
            for name in ('battle', 'daily', 'mail', 'battlepass'):
                stack.enter_context(patch.object(DailyWorkflow, name, side_effect=AssertionError('extra daily task')))
            args = ['--task-workflow', str(document)] if workflow else ['--run']
            code = main(args + ['--config', str(config)])
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse((root / 'runs' / 'battle-session.json').exists())
        report = json.loads(out.getvalue())
        return SimpleNamespace(code=code, report=report, sent=sent, root=root)

    def test_single_assignment_tree_blocks_unrelated_startup_rewards(self):
        for mode in ('supply', 'login-reward'):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertEqual(result.sent, [])
                self.assertNotEqual(result.code, 0)

    def test_single_assignment_tree_does_not_restart_after_a_native_claim(self):
        result = self.invoke(event='interrupt_after_claim')
        self.assertEqual(result.sent, ['委托', '领取奖励'])
        self.assertEqual(result.report['status'], 'partial')

    def test_final_native_guard_blocks_stale_epoch_conflicting_account_and_focus_loss(self):
        for event in ('epoch_before_native', 'other_uid_before_native', 'focus_before_native'):
            with self.subTest(event=event):
                result = self.invoke(event=event)
                self.assertEqual(result.sent, ['委托'])
                self.assertEqual(result.report['status'], 'partial')

    def test_f10_at_final_native_guard_blocks_claim(self):
        result = self.invoke(event='stop_before_native')
        self.assertEqual(result.sent, ['委托'])
        self.assertEqual(result.report['status'], 'stopped')

    def test_account_change_after_claim_blocks_further_inputs(self):
        result = self.invoke(event='other_uid_after_claim')
        self.assertEqual(result.sent, ['委托', '领取奖励'])
        self.assertEqual(result.report['status'], 'partial')

    def test_same_four_slots_and_unavailable_button_without_timer_reset_stay_pending(self):
        clean = fixture('assignments_after_claim')
        stale = replace(clean, tokens=[
            replace(field, text='已进行：28/30小时') if field.text.startswith('已进行') else field
            for field in clean.tokens
        ])
        for first_return in (stale, clean):
            with self.subTest(first_return_is_stale=first_return is stale):
                first = iter((first_return,))
                result = self.invoke(overrides={'disabled': lambda: next(first, stale)})
                self.assertEqual(result.sent, ['委托', '领取奖励', '点击空白处关闭'])
                self.assertEqual(result.report['status'], 'partial')
                entry, = result.report['workflow']['steps']
                original = json.loads(Path(entry['source']['path']).read_text('utf8'))
                self.assertEqual([(row['task'], row['status']) for row in original['results']],
                                 [('assignments', 'partial')])
                self.assertEqual((original['stamina_spent'], original['immersifiers_spent']), (0, 0))

    def test_gold_button_requires_an_unambiguous_positive_accrual(self):
        active = assignments_scene(claim='enabled')
        for timer in ('已进行0/30h', '已进行：28/30小', '已进行：31/30小时'):
            with self.subTest(timer=timer):
                invalid = replace(active, tokens=[
                    replace(field, text=timer) if field.text.startswith('已进行') else field
                    for field in active.tokens
                ])
                result = self.invoke(overrides={'active': lambda: invalid})
                self.assertEqual(result.sent, ['委托'])
                self.assertEqual(result.report['status'], 'partial')

    def test_opened_current_settled_page_and_legacy_page_need_no_input(self):
        settled = self.invoke('disabled')
        self.assertEqual(settled.sent, [])
        self.assertEqual(settled.code, 0, settled.report)
        legacy = self.invoke('legacy')
        self.assertEqual(legacy.sent, [])
        self.assertEqual(legacy.report['status'], 'partial')

    def test_dark_or_duplicate_claim_is_not_submitted(self):
        dark = assignments_scene(claim='enabled')
        dark.image[:] = 0
        duplicate = assignments_scene(claim='enabled')
        duplicate.tokens.append(token('领取奖励', .84, .85))
        for scene in (dark, duplicate):
            with self.subTest(scene=scene.text):
                result = self.invoke(active_scene=scene)
                self.assertEqual(result.sent, ['委托'])
                self.assertEqual(result.report['status'], 'partial')

    def test_single_assignment_tree_preserves_existing_daily_startup_for_unscoped_run(self):
        result = self.invoke('supply', workflow=False)
        self.assertEqual(result.code, 0, result.report)
        self.assertEqual(result.sent[:2], ['点击领取今日补给', '点击领取今日补给'])

    def test_single_assignment_tree_claims_and_closes_its_own_display(self):
        result = self.invoke()
        self.assertEqual(result.code, 0, result.report)
        self.assertEqual(result.sent, ['委托', '领取奖励', '点击空白处关闭'])
        entry, = result.report['workflow']['steps']
        self.assertTrue(entry['account_verified'])
        original = json.loads(Path(entry['source']['path']).read_text('utf8'))
        self.assertEqual([row['task'] for row in original['results']], ['assignments'])
        self.assertEqual((original['stamina_spent'], original['immersifiers_spent']), (0, 0))
