"""Official free-reward CLI and workflow through fake Win32 and local fixtures."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import ctypes
from dataclasses import replace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.daily_attachments import ATTACHMENT_FLOWS
from autohsr.free_rewards import battlepass_progress, battlepass_tab, mail_entry
from autohsr.tests.test_free_rewards import with_battlepass_category_badge
from autohsr.models import AutomationError, InputInterrupted, Scene
from autohsr.task_workflow import FREE_ATTACHMENT_TASK, WorkflowError, compile_recipe, task_spec
from autohsr.tests.test_assignment_only import ACCOUNT, OTHER
from autohsr.tests.test_core import token
from autohsr.tests.test_daily_startup import supply
from autohsr.tests.test_du_team import fixture
from autohsr.workflows import DailyWorkflow


GEOMETRY = windows.Geometry(0, 0, 1920, 1080)


class AttachmentTests(unittest.TestCase):
    def invoke(self, task, start, *, event=None, workflow=False, combined=False):
        workflow = workflow or combined
        folder = TemporaryDirectory(prefix='autohsr-attachment-')
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config = root / 'settings.json'
        Settings(mail=True, battlepass=True, weekly_enabled=True, overlay_logs=False,
                 redemption_enabled=True, redemption_source='manual', redemption_codes=['FAKEMARKER'],
                 notification_enabled=not workflow, notification_profiles=['synthetic']).save(config)
        original = config.read_bytes()
        if workflow:
            document = root / 'task.json'
            steps = ([dict(id=target, type='task', task=FREE_ATTACHMENT_TASK, params=dict(target=target))
                      for target in ('mail', 'battlepass')] if combined else
                     [dict(id='single', type='task', task='daily', params=dict(tasks=[task]))])
            document.write_text(json.dumps(dict(version=1, name='自定义单附件', steps=steps),
                                           ensure_ascii=False), encoding='utf8')
            args = ['--task-workflow', str(document)]
        else:
            args = ['--daily-attachment-only', task]

        window = windows.GameWindow.__new__(windows.GameWindow)
        window.hwnd, window.path, window.focus = 58741, None, Mock()
        native = Mock()
        native.IsWindow.return_value = 1
        native.IsIconic.return_value = 0
        native.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__
        native.MapVirtualKeyW.side_effect = lambda key, _: key
        current = None
        mode = start
        active = None
        sent = []
        claim_guards = 0
        last_stage = None
        mail_return_captures = 0
        missing_window = Mock(side_effect=AutomationError('游戏窗口未打开。'))

        class TestContext(Context):
            def __init__(self, runner, observed_window, vision):
                super().__init__(runner, observed_window, vision)
                window.owner, window.context = runner, self

            def sleep(self, _seconds):
                self.checkpoint()

            def wait(self, predicate, timeout=30, description='界面'):
                for _ in range(5):
                    scene = self.snapshot()
                    if predicate(scene):
                        return scene
                raise AutomationError('测试画面尚未到达：' + description)

            def evidence(self, scene, name):
                if event == 'settlement_write_failure' and name == 'mail_attachments_settled':
                    raise OSError('测试领取证据未能写入')
                return super().evidence(scene, name)

        def capture():
            nonlocal current, mail_return_captures
            if mode in ('reward', 'old-reward'):
                scene = Scene([token('获得物品', .50, .11), token('点击空白处关闭', .50, .87)])
            elif mode == 'supply':
                scene = supply()
            elif mode == 'old-battle':
                scene = Scene([token('挑战成功', .52, .14), token('退出关卡', .45, .89)])
            elif mode == 'phone-battlepass':
                scene = Scene([token('开拓等级 70', .68, .10), token('无名勋礼', .76, .43),
                               token('委托', .82, .60), token('星际和平指南', .88, .43)])
            elif mode == 'period-claimable':
                scene = fixture('bp_period_settled')
                target = fixture('bp_tasks_claimable').find('一键领取', exact=True)
                level = battlepass_progress(scene)[0]
                scene.tokens = [replace(t, text=str(level - 1)) if t.text == str(level)
                                and t.within((.08, .18, .17, .28)) else t for t in scene.tokens]
                scene.tokens.append(target)
                x, y = target.center
                height, width = scene.image.shape[:2]
                scene.image[round((y - .025) * height):round((y + .025) * height),
                            round((x - .05) * width):round((x + .05) * width)] = (30, 175, 245)
            else:
                scene = fixture(mode)
            if mode == 'bp_tasks_settled' and event == 'cross_category_badge':
                scene = with_battlepass_category_badge(scene, '本期任务')
            if mode == 'bp_tasks_claimable' and event in ('weekly_alias', 'weekly_alias_unverified'):
                target = scene.find('一键领取', exact=True)
                scene.tokens = [replace(t, text='-键领取') if t == target else t for t in scene.tokens]
            if mode == 'bp_rewards_settled' and event == 'late_purchase':
                scene.tokens.append(token('选择奖励', .50, .45))
            if mode == 'mail_claimable' and event == 'duplicate':
                scene.tokens.append(token('全部领取', .30, .91))
            if mode == 'mail_claimable' and event == 'neutral_bulk_button':
                # Neutralize the bulk button fill while keeping the source arrow.
                scene.image[955:1010, 360:570] = (120, 120, 120)
            if mode == 'mail_claimed' and last_stage == 'mail':
                mail_return_captures += 1
                if event == 'selected_attachment_remains':
                    claimable = fixture('mail_claimable')
                    scene.tokens.remove(scene.find('删除', (.8, .83, .98, .97), exact=True))
                    scene.tokens.append(claimable.find('领取', (.8, .83, .98, .97), exact=True))
                    scene.image[910:1040, 1510:1850] = claimable.image[910:1040, 1510:1850]
                if event == 'return_temporarily_disabled' and mail_return_captures > 2:
                    # The close click and the first mailbox wait consume the first two reads.
                    scene = fixture('mail_claimable')
            tokens = [value for value in scene.tokens if not value.text.lower().startswith('uid')]
            if mode not in ('reward', 'old-reward', 'supply'):
                changed = event == 'combined_account_change' and window.owner.daily_attachment_only == 'battlepass'
                tokens.append(token(OTHER if changed else ACCOUNT, .08, .97, .99))
            image = scene.image if scene.image is not None else np.full((1080, 1920, 3), 35, np.uint8)
            current = replace(scene, tokens=tokens, image=image, geometry=GEOMETRY)
            return image, GEOMETRY

        def click(x, y, expected, **options):
            nonlocal active
            scene = window.context.last_scene
            candidates = list(scene.tokens)
            candidates.extend(candidate for candidate in (mail_entry(scene), battlepass_tab(scene, 'tasks'),
                              battlepass_tab(scene, 'rewards')) if candidate is not None)
            active = next(candidate.text for candidate in candidates
                          if abs(candidate.center[0] - x) < 1e-6 and abs(candidate.center[1] - y) < 1e-6)
            try:
                windows.GameWindow.click(window, x, y, expected, **options)
                if active == '全部领取' and event == 'interrupted':
                    window.owner.input_epoch += 1
                    raise InputInterrupted('测试领取后输入代次变化')
            finally:
                active = None

        def foreground():
            nonlocal claim_guards
            if active == '全部领取':
                claim_guards += 1
                if claim_guards == 3:
                    if event == 'late_epoch':
                        window.owner.input_epoch += 1
                    elif event == 'late_uid':
                        window.context.last_scene.field_reads['uid_counterevidence'] = (token(OTHER, .08, .97, .74),)
                    elif event == 'late_focus':
                        return window.hwnd + 1
            return window.hwnd

        def send(count, events, _size):
            nonlocal mode, last_stage
            if combined and active is None and count == 1:
                key = ctypes.cast(events, ctypes.POINTER(windows.INPUT))[0]
                self.assertEqual((key.type, key.ki.wScan), (1, 0x1B))
                if key.ki.dwFlags == 0x08:
                    self.assertEqual(mode, 'mail_claimed')
                    sent.append('esc')
                    mode = 'phone-battlepass'
                else:
                    self.assertEqual(key.ki.dwFlags, 0x0A)
                return count
            sent.append(active)
            if active == 'phone_mail_body':
                mode = 'mail_claimable'
            elif active == '无名勋礼':
                mode = 'bp_tasks_claimable'
            elif active == '全部领取':
                last_stage = 'mail'
                if event != 'interrupted':
                    mode = 'reward'
            elif active == '点击空白处关闭':
                if event != 'close_stuck':
                    mode = 'mail_claimed' if last_stage == 'mail' else 'bp_rewards_settled'
            elif active in ('一键领取', '-键领取') and mode == 'bp_tasks_claimable':
                mode = 'bp_tasks_settled'
            elif active == '本期任务':
                mode = 'period-claimable' if event in ('period_claim', 'cross_category_badge') else 'bp_period_settled'
            elif active == '一键领取' and mode == 'period-claimable':
                mode = 'bp_period_settled'
            elif active == 'bp_rewards_tab':
                mode = 'bp_rewards_settled' if start == 'bp_tasks_settled' or event == 'late_purchase' else 'bp_rewards_claimable'
            elif active == '一键领取' and mode == 'bp_rewards_claimable':
                last_stage, mode = 'battlepass', 'reward'
            else:
                raise AssertionError('unscoped fixture input')
            return count

        window.capture, window.click = capture, click
        native.GetForegroundWindow.side_effect = foreground
        native.GetAsyncKeyState.side_effect = lambda code: (
            0x8000 if code == 0x79 and event == 'late_stop' and active == '全部领取' and claim_guards >= 3 else 0)
        native.SendInput.side_effect = send
        vision = SimpleNamespace(
            read=lambda *_: replace(current, tokens=list(current.tokens)), template=lambda *_: None,
            _read_field=lambda _crop, _pattern: token('一键领取', .5, .5) if event == 'weekly_alias' else None,
        )
        mutex = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        launch = Mock(side_effect=AssertionError('launch out of scope'))
        out, err = io.StringIO(), io.StringIO()
        with ExitStack() as stack, redirect_stdout(out), redirect_stderr(err):
            for name, value in (
                ('autohsr.app.ROOT', root), ('autohsr.task_workflow_run.ROOT', root),
                ('autohsr.app.Context', TestContext), ('autohsr.app.threading.Thread', Mock()),
                ('autohsr.app.C.get_last_error', Mock(return_value=0)), ('autohsr.app.is_elevated', Mock(return_value=False)),
                ('autohsr.app.find_game', missing_window if start == 'missing-window' else Mock(return_value=window)),
                ('autohsr.app.launch_game', launch), ('autohsr.app.Vision', Mock(return_value=vision)),
                ('autohsr.windows.user32', native), ('autohsr.windows.kernel32', mutex),
                ('autohsr.windows.geometry', Mock(return_value=GEOMETRY)), ('autohsr.windows.time.sleep', Mock()),
            ):
                stack.enter_context(patch(name, value))
            unselected = ('assignments', 'battle', 'daily', 'redemption')
            if not combined:
                unselected += ('mail' if task == 'battlepass' else 'battlepass',)
            for other in unselected:
                stack.enter_context(patch.object(DailyWorkflow, other, side_effect=AssertionError('extra daily task')))
            if not workflow:
                stack.enter_context(patch('autohsr.notify_runtime.hooks', side_effect=AssertionError('unrequested notification')))
            code = main([*args, '--config', str(config)])
        self.assertEqual(config.read_bytes(), original)
        launch.assert_not_called()
        self.assertFalse((root / 'runs' / 'battle-session.json').exists())
        self.assertNotIn(ACCOUNT, out.getvalue() + err.getvalue())
        parent = json.loads(out.getvalue())
        step = parent['workflow']['steps'][0]
        if not combined:
            self.assertEqual(len(parent['workflow']['steps']), 1)
        child = json.loads(Path(step['source']['path']).read_text(encoding='utf8'))
        self.assertEqual(child['stamina_spent'], 0)
        self.assertEqual(child['stamina_pending'], 0)
        self.assertFalse(child['daily_verified'])
        self.assertEqual(child['operation'], 'daily')
        self.assertEqual(parent['workflow']['name'], '自定义单附件' if workflow else ATTACHMENT_FLOWS[task])
        return SimpleNamespace(code=code, parent=parent, child=child, step=step, sent=sent)

    def test_combines_independent_mail_and_battlepass_without_a_daily_budget(self):
        combined = self.invoke('mail', 'mail_claimable', combined=True)
        self.assertEqual((combined.code, combined.parent['status']), (0, 'success'), combined.parent['error'])
        workflow = combined.parent['workflow']
        self.assertEqual((workflow['reservations']['daily_calls'], workflow['reservations']['free_attachment_calls']),
                         (0, 2))
        self.assertEqual([step['attachment'] for step in workflow['steps']], [
            dict(target='mail', outcome='claimed', verified_claims=['mail_attachments']),
            dict(target='battlepass', outcome='claimed', verified_claims=['battlepass_weekly_tasks', 'battlepass_free_levels']),
        ])
        self.assertEqual(combined.sent[:4], ['全部领取', '点击空白处关闭', 'esc', '无名勋礼'])
        self.assertEqual(combined.sent.count('全部领取'), 1)

    def test_combination_stops_after_unknown_claim_or_changed_account(self):
        for event, count in (('close_stuck', 1), ('combined_account_change', 2)):
            with self.subTest(event=event):
                combined = self.invoke('mail', 'mail_claimable', event=event, combined=True)
                self.assertEqual(combined.code, 1)
                self.assertEqual(combined.sent, ['全部领取', '点击空白处关闭'])
                steps = combined.parent['workflow']['steps']
                self.assertEqual(len(steps), count)
                if count == 2:
                    self.assertEqual(steps[0]['attachment']['outcome'], 'claimed')
                    self.assertNotIn('attachment', steps[1])

    def test_reservation_rejects_duplicate_or_overlapping_reward_owners(self):
        def compile_steps(*steps):
            return compile_recipe(dict(version=1, name='领奖', steps=list(steps)))

        mail = dict(id='mail', type='task', task=FREE_ATTACHMENT_TASK, params=dict(target='mail'))
        battlepass = dict(id='bp', type='task', task=FREE_ATTACHMENT_TASK, params=dict(target='battlepass'))
        assignments = dict(id='daily', type='task', task='daily', params=dict(tasks=['assignments']))
        self.assertEqual(compile_steps(assignments, mail, battlepass).profile['free_attachment_calls'], 2)
        for overlapping in (dict(mail, id='other'), dict(assignments, params=dict(tasks=['mail'])),
                            dict(assignments, params={}), dict(assignments, task='plan', params={})):
            with self.subTest(overlapping=overlapping), self.assertRaises(WorkflowError):
                compile_steps(mail, overlapping)

    def test_mail_navigates_claims_closes_and_distinguishes_empty(self):
        claimed = self.invoke('mail', 'phone_mail_icon')
        self.assertEqual((claimed.code, claimed.sent), (0, ['phone_mail_body', '全部领取', '点击空白处关闭']))
        self.assertTrue(claimed.step['account_verified'])
        self.assertEqual(claimed.child['results'][0]['attachment_outcome'], 'claimed')
        self.assertEqual(claimed.child['results'][0]['verified_claims'], ['mail_attachments'])
        empty = self.invoke('mail', 'mail_claimed', workflow=True)
        self.assertEqual((empty.code, empty.sent), (0, []))
        self.assertEqual(empty.child['results'][0]['attachment_outcome'], 'empty')
        self.assertEqual(empty.child['results'][0]['verified_claims'], [])

    def test_neutral_bulk_button_does_not_prove_a_mailbox_is_empty(self):
        result = self.invoke('mail', 'mail_claimable', event='neutral_bulk_button')
        self.assertEqual((result.code, result.sent), (1, []))
        self.assertEqual(result.child['results'][0]['attachment_outcome'], 'unknown')

    def test_ambiguous_or_unstable_mail_return_never_repeats_inputs(self):
        for event in ('selected_attachment_remains', 'return_temporarily_disabled', 'close_stuck'):
            with self.subTest(event=event):
                result = self.invoke('mail', 'mail_claimable', event=event)
                self.assertEqual((result.code, result.sent), (1, ['全部领取', '点击空白处关闭']))
                self.assertEqual(result.child['results'][0]['attachment_outcome'], 'unknown')
                self.assertEqual(result.child['results'][0]['verified_claims'], [])

    def test_battlepass_confirms_weekly_experience_and_free_levels_separately(self):
        claimed = self.invoke('battlepass', 'phone-battlepass')
        self.assertEqual((claimed.code, claimed.sent), (0, [
            '无名勋礼', '一键领取', '本期任务', 'bp_rewards_tab', '一键领取', '点击空白处关闭',
        ]))
        self.assertEqual(claimed.child['results'][0]['verified_claims'], ['battlepass_weekly_tasks', 'battlepass_free_levels'])
        self.assertEqual(claimed.child['results'][0]['attachment_outcome'], 'claimed')
        empty = self.invoke('battlepass', 'bp_tasks_settled')
        self.assertEqual((empty.code, empty.sent), (0, ['本期任务', 'bp_rewards_tab']))
        self.assertEqual(empty.child['results'][0]['attachment_outcome'], 'empty')

    def test_unknown_later_battlepass_result_preserves_verified_experience(self):
        result = self.invoke('battlepass', 'bp_tasks_claimable', event='late_purchase')
        self.assertEqual((result.code, result.sent), (1, ['一键领取', '本期任务', 'bp_rewards_tab']))
        self.assertEqual(result.child['results'][0]['attachment_outcome'], 'unknown')
        self.assertEqual(result.child['results'][0]['verified_claims'], ['battlepass_weekly_tasks'])

    def test_battlepass_native_claim_requires_local_verification_for_weekly_alias(self):
        observed = self.invoke('battlepass', 'bp_tasks_claimable', event='weekly_alias')
        self.assertEqual(observed.code, 0)
        self.assertEqual(observed.sent, [
            '-键领取', '本期任务', 'bp_rewards_tab', '一键领取', '点击空白处关闭',
        ])
        self.assertEqual(observed.child['results'][0]['verified_claims'], [
            'battlepass_weekly_tasks', 'battlepass_free_levels',
        ])
        unknown = self.invoke('battlepass', 'bp_tasks_claimable', event='weekly_alias_unverified')
        self.assertEqual((unknown.code, unknown.sent), (1, []))
        self.assertEqual(unknown.child['failure_task'], 'battlepass')
        self.assertEqual(unknown.child['results'][0]['verified_claims'], [])

    def test_battlepass_period_experience_has_its_own_receipt(self):
        result = self.invoke('battlepass', 'bp_tasks_claimable', event='period_claim', workflow=True)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.child['results'][0]['verified_claims'], [
            'battlepass_weekly_tasks', 'battlepass_period_tasks', 'battlepass_free_levels',
        ])

    def test_other_category_badge_preserves_weekly_receipt_and_allows_period_claim(self):
        result = self.invoke('battlepass', 'bp_tasks_claimable', event='cross_category_badge', workflow=True)
        self.assertEqual((result.code, result.sent), (0, [
            '一键领取', '本期任务', '一键领取', 'bp_rewards_tab', '一键领取', '点击空白处关闭',
        ]))
        self.assertEqual(result.child['results'][0]['verified_claims'], [
            'battlepass_weekly_tasks', 'battlepass_period_tasks', 'battlepass_free_levels',
        ])

    def test_unwritten_settlement_evidence_does_not_publish_a_verified_claim(self):
        result = self.invoke('mail', 'mail_claimable', event='settlement_write_failure')
        self.assertEqual((result.code, result.sent), (1, ['全部领取', '点击空白处关闭']))
        self.assertEqual(result.child['results'][0]['attachment_outcome'], 'unknown')
        self.assertEqual(result.child['results'][0]['verified_claims'], [])

    def test_unrelated_startup_screens_and_missing_window_are_never_operated(self):
        for start in ('supply', 'old-reward', 'old-battle', 'missing-window'):
            with self.subTest(start=start):
                result = self.invoke('mail', start)
                self.assertEqual((result.code, result.sent), (1, []))

    def test_native_late_stop_epoch_conflict_and_unconfirmed_feedback_do_not_resend(self):
        for event in ('late_stop', 'late_epoch', 'late_uid', 'late_focus', 'duplicate', 'interrupted'):
            with self.subTest(event=event):
                result = self.invoke('mail', 'mail_claimable', event=event)
                self.assertEqual(result.code, 1)
                self.assertEqual(result.sent, ['全部领取'] if event == 'interrupted' else [])
                self.assertEqual(result.child['results'][0]['attachment_outcome'], 'unknown')
                if event == 'late_stop':
                    self.assertEqual(result.parent['status'], 'stopped')

    def test_native_and_task_spec_do_not_expand_scoped_settings(self):
        settings = Settings(assignments=True, battle=True, mail=True, battlepass=True)
        scoped = Runner(settings, daily_attachment_only='mail')
        self.assertTrue(settings.battle and settings.assignments and settings.battlepass)
        self.assertTrue(scoped.settings.mail)
        self.assertFalse(scoped.settings.battle or scoped.settings.assignments or scoped.settings.battlepass)
        for options in (dict(operation='reward_only'), dict(new_battle_run=True), dict(use_power_plan=True),
                        dict(new_power_plan=True), dict(assignments_only=True)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                Runner(settings, daily_attachment_only='mail', **options)
        _, plain = task_spec(Settings(mail=True, assignments=False, battle=False, daily=False), dict(task='daily'), Path('.'))
        self.assertNotIn('daily_attachment_only', plain)
        _, mixed = task_spec(settings, dict(task='daily', params={'tasks': ['mail', 'battlepass']}), Path('.'))
        self.assertNotIn('daily_attachment_only', mixed)

    def test_conflicting_cli_options_reject_before_loading_settings(self):
        options = [(value,) for value in ('--run', '--reward-only', '--power-plan', '--with-redemption', '--notify')]
        options.append(('--daily-attachment-only=battlepass',))
        for extra in options:
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), patch.object(Settings, 'load') as load:
                with self.assertRaises(SystemExit) as error:
                    main(['--daily-attachment-only', 'mail', *extra])
                self.assertEqual(error.exception.code, 2)
                load.assert_not_called()
