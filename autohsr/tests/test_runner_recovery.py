"""Run the real coordinator against fake windows/OCR/workflows; no game input."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, Scene, TaskResult


class RunnerRecoveryTests(unittest.TestCase):
    def fixture(self, root, workflow):
        stack = ExitStack()
        self.addCleanup(stack.close)
        context = SimpleNamespace(last_scene=Scene([]), snapshot=Mock(return_value=Scene([])), evidence=Mock())
        window = Mock()
        stack.enter_context(patch('autohsr.app.ROOT', root))
        stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
        stack.enter_context(patch('autohsr.app.threading.Thread'))
        stack.enter_context(patch('autohsr.app.is_elevated', return_value=False))
        stack.enter_context(patch('autohsr.app.is_admin', return_value=False))
        stack.enter_context(patch('autohsr.app.Vision'))
        stack.enter_context(patch('autohsr.app.Context', return_value=context))
        find = stack.enter_context(patch('autohsr.app.find_game', return_value=window))
        stack.enter_context(patch('autohsr.workflows.DailyWorkflow', return_value=workflow))
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
            stored = json.loads((root/'runs/battle-session.json').read_text(encoding='utf-8'))
            self.assertEqual(stored['pending'], 10)
            second = Runner(settings).run()
            self.assertEqual(second.status, 'failed')
            self.assertIn('新一轮', second.error)
            self.assertEqual(find.call_count, 1)
            self.assertEqual(json.loads((root/'runs/battle-session.json').read_text(encoding='utf-8'))['pending'], 10)

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
