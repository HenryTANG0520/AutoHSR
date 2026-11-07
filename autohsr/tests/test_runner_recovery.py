"""Run the real coordinator against fake windows/OCR/workflows; no game input."""
import json
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, Scene, TaskResult, Token
from autohsr.tests.test_du_team import fixture
from autohsr.workflows import DailyWorkflow


class RunnerRecoveryTests(unittest.TestCase):
    def fixture(self, root, workflow):
        stack = ExitStack()
        self.addCleanup(stack.close)
        context = SimpleNamespace(last_scene=Scene([]), snapshot=Mock(return_value=Scene([])), evidence=Mock(),
                                  daily_startup=lambda *_: nullcontext())
        window = Mock()
        stack.enter_context(patch('autohsr.app.ROOT', root))
        stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
        stack.enter_context(patch('autohsr.app.threading.Thread'))
        stack.enter_context(patch('autohsr.app.is_elevated', return_value=False))
        stack.enter_context(patch('autohsr.app.is_admin', return_value=False))
        stack.enter_context(patch('autohsr.app.Vision'))
        stack.enter_context(patch('autohsr.app.Context', return_value=context))
        find = stack.enter_context(patch('autohsr.app.find_game', return_value=window))

        def initialize(instance, _context):
            vars(instance).update(vars(workflow))

        # Runner can import navigation here. Keep the class binding stable.
        stack.enter_context(patch.object(DailyWorkflow, '__init__', initialize))
        stack.enter_context(patch('autohsr.windows.kernel32', SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock(return_value=True))))
        return context, find

    def test_pending_challenge_survives_run_and_blocks_second_coordinator_before_game_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workflow = SimpleNamespace(ensure_main=Mock())
            context, find = self.fixture(root, workflow)
            def battle():
                context.battle_budget.reserve(10)
                raise AutomationError('模拟开始挑战后识别中断')
            workflow.battle = battle
            settings = Settings(assignments=False, battle=True, daily=False, mail=False, battlepass=False, stamina_limit=10)
            first = Runner(settings).run()
            self.assertEqual(first.status, 'partial')
            self.assertEqual((first.stamina_spent, first.stamina_pending), (0, 10))
            path = root/'runs/battle-session.json'
            before = path.read_bytes()
            stored = json.loads(before)
            self.assertEqual(stored['pending'], 10)
            for explicit in (False, True):
                with self.subTest(explicit=explicit):
                    second = Runner(settings, new_battle_run=explicit).run()
                    self.assertEqual(second.status, 'failed')
                    self.assertIn('新一轮', second.error)
                    self.assertEqual(find.call_count, 1)
                    self.assertEqual(path.read_bytes(), before)

    def test_optional_failure_preserves_core_verification_in_saved_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workflow = SimpleNamespace(ensure_main=Mock(), mail=Mock(side_effect=AutomationError('邮件入口未识别')))
            self.fixture(root, workflow)
            runner = Runner(Settings(assignments=False, battle=False, daily=True, mail=True, battlepass=True))
            def daily():
                runner.report.daily_verified = True
                runner.report.engagement = 500
                return TaskResult('daily', 'ok', '500 plus five claims verified')
            workflow.daily = daily
            workflow.battlepass = Mock()
            report = runner.run()
            self.assertTrue(report.daily_verified)
            self.assertEqual(report.status, 'partial')
            self.assertEqual(report.failure_task, 'mail')
            self.assertEqual(report.stamina_spent, 0)
            workflow.battlepass.assert_not_called()
            saved = json.loads((Path(report.run_dir)/'report.json').read_text(encoding='utf-8'))
            self.assertTrue(saved['daily_verified'])
            self.assertEqual(saved['engagement'], 500)
            self.assertFalse((root/'runs/battle-session.json').exists())

    def test_normal_daily_stops_before_battlepass_on_unverified_mail(self):
        for phase in ('button_unknown', 'return_unverified', 'empty_verified', 'training_400'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                workflow = SimpleNamespace(ensure_main=Mock())
                context, _ = self.fixture(root, workflow)
                settings = Settings(assignments=False, battle=True, daily=True, mail=True, battlepass=True,
                                    stamina_limit=10, daily_synthesis=False, redemption_enabled=False)
                runner = Runner(settings)
                mail = fixture('mail_claimed' if phase in ('empty_verified', 'training_400') else 'mail_claimable')
                if phase == 'button_unknown':
                    mail.image[:] = 0
                popup = Scene([Token('获得物品', .99, (.46, .09, .54, .13)),
                               Token('点击空白处关闭', .99, (.39, .82, .61, .88))])
                returned = fixture('mail_claimable')
                context.checkpoint = Mock()
                context.sleep = Mock()
                context.log = Mock()
                context.click = Mock()
                context.snapshot.return_value = mail
                frames = iter([mail, popup, popup, returned])

                def wait(predicate, **_options):
                    frame = next(frames)
                    self.assertTrue(predicate(frame))
                    return frame

                context.wait = wait
                dismiss = Mock()
                flow = SimpleNamespace(
                    ctx=context, settings=settings, daily_attachment_only=None,
                    _snapshot=context.snapshot, _wait=context.wait, _dismiss_reward=dismiss,
                    _click=context.click, _result=lambda task, status, detail, scene: TaskResult(task, status, detail),
                )

                def battle():
                    context.battle_budget.reserve(10)
                    context.battle_budget.confirm(10, completed=1)
                    return TaskResult('battle', 'ok', '已结算')

                def daily():
                    if phase == 'training_400':
                        runner.report.engagement = 400
                        return TaskResult('daily', 'partial', '实训活跃值为400/500，尚未确认每日任务完成。')
                    runner.report.daily_verified = True
                    runner.report.engagement = 500
                    return TaskResult('daily', 'ok', '五档已核实')

                def battlepass():
                    context.click(mail, '模拟勋礼入口输入')
                    return TaskResult('battlepass', 'ok', '模拟勋礼完成')

                workflow.battle, workflow.daily = battle, daily
                workflow.mail = lambda: DailyWorkflow.mail(flow)
                workflow.battlepass = Mock(side_effect=battlepass)
                report = runner.run()
                saved = json.loads((Path(report.run_dir)/'report.json').read_text(encoding='utf-8'))
                self.assertEqual((saved['stamina_spent'], saved['stamina_pending'], saved['battle_completed']), (10, 0, 1))
                self.assertEqual(saved['daily_verified'], phase != 'training_400')
                self.assertEqual(saved['engagement'], 400 if phase == 'training_400' else 500)
                ledger = json.loads((root/'runs/battle-session.json').read_text(encoding='utf-8'))
                self.assertEqual((ledger['spent'], ledger['pending'], ledger['completed']), (10, 0, 1))
                if phase in ('empty_verified', 'training_400'):
                    workflow.battlepass.assert_called_once()
                    self.assertEqual((saved['status'], saved['failure_task']),
                                     ('success' if phase == 'empty_verified' else 'partial', ''))
                    continue
                workflow.battlepass.assert_not_called()
                self.assertEqual((saved['status'], saved['failure_task']), ('partial', 'mail'))
                self.assertEqual([(r['task'], r['status']) for r in saved['results']],
                                 [('battle', 'ok'), ('daily', 'ok'), ('mail', 'partial'), ('battlepass', 'skipped')])
                self.assertEqual((context.click.call_count, dismiss.call_count),
                                 (1, 1) if phase == 'return_unverified' else (0, 0))

    def test_normal_daily_stops_before_budget_use_on_unverified_assignment_overlay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workflow = SimpleNamespace(ensure_main=Mock())
            context, _ = self.fixture(root, workflow)
            assignment = Scene([Token('委托', .99, (.04, .03, .08, .05))])
            overlay = Scene([Token('获得物品', .99, (.46, .09, .54, .13))])
            flow = SimpleNamespace(
                assignments_only=False, _snapshot=Mock(side_effect=[assignment, overlay]),
                _dismiss_reward=lambda scene: scene, _persistent_assignments=Mock(return_value=True),
                _result=lambda task, status, detail, scene: TaskResult(task, status, detail),
            )
            workflow.assignments = lambda: DailyWorkflow.assignments(flow)
            workflow.battle = Mock(return_value=TaskResult('battle', 'ok', '模拟挑战结束'))
            settings = Settings(assignments=True, battle=True, daily=False, mail=False, battlepass=False,
                                daily_synthesis=False, redemption_enabled=False, stamina_limit=10)
            report = Runner(settings).run()
            workflow.battle.assert_not_called()
            self.assertEqual((report.status, report.failure_task, report.stamina_spent, report.stamina_pending),
                             ('partial', 'assignments', 0, 0))
            self.assertEqual([(r.task, r.status) for r in report.results],
                             [('assignments', 'partial'), ('battle', 'skipped')])
