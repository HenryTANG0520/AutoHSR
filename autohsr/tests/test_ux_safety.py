from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, Scene, TaskResult, Token
from autohsr.workflows import DailyWorkflow


class BudgetRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_historical_partial_spend_blocks_implicit_new_budget(self):
        from autohsr.recovery import BattleBudget, recovery_state
        for spent in (70, 210):
            report = self.root / str(spent) / 'report.json'
            report.parent.mkdir()
            report.write_text(json.dumps({'status': 'failed', 'stamina_spent': spent,
                'daily_verified': False, 'results': [{'task': 'battle', 'status': 'partial'},
                {'task': 'run', 'status': 'failed', 'detail': '手机菜单中未识别到邮件入口。'}]}), encoding='utf-8')
        self.assertTrue(recovery_state(self.root)['blocked'])
        self.assertIsNone(recovery_state(self.root)['pending'])
        with self.assertRaisesRegex(AutomationError, '新一轮|恢复'):
            BattleBudget(self.root, Settings(), RunReport()).begin()

    def test_reservation_survives_restart_and_never_counts_unknown_as_zero(self):
        from autohsr.recovery import BattleBudget, recovery_state
        report = RunReport()
        budget = BattleBudget(self.root, Settings(stamina_limit=20), report)
        budget.begin()
        budget.reserve(10)
        state = recovery_state(self.root)
        self.assertEqual(state['pending'], 10)
        self.assertTrue(state['blocked'])
        with self.assertRaises(AutomationError):
            BattleBudget(self.root, Settings(), RunReport()).begin()
        self.assertEqual(report.stamina_spent, 0)
        self.assertEqual(report.stamina_pending, 10)

    def test_confirmed_cost_is_accounted_once_and_cap_cannot_be_exceeded(self):
        from autohsr.recovery import BattleBudget
        report = RunReport()
        budget = BattleBudget(self.root, Settings(stamina_limit=20), report)
        budget.begin()
        budget.reserve(10)
        budget.confirm(10)
        self.assertEqual((report.stamina_spent, report.stamina_pending), (10, 0))
        with self.assertRaises(AutomationError):
            budget.confirm(10)
        with self.assertRaises(AutomationError):
            budget.reserve(20)

    def test_corrupt_journal_fails_closed_and_reward_only_settings_do_not_clear_it(self):
        from autohsr.recovery import BattleBudget, recovery_state, reward_only_settings
        path = self.root / 'battle-session.json'
        path.write_text('{broken', encoding='utf-8')
        self.assertTrue(recovery_state(self.root)['blocked'])
        with self.assertRaises(AutomationError):
            BattleBudget(self.root, Settings(), RunReport()).begin(new_run=True)
        settings = reward_only_settings(Settings())
        self.assertFalse(settings.battle)
        self.assertTrue(settings.daily)
        self.assertFalse(settings.mail)
        self.assertEqual(path.read_text(), '{broken')

    def test_failed_atomic_write_never_allows_challenge(self):
        from autohsr.recovery import BattleBudget
        report = RunReport()
        budget = BattleBudget(self.root, Settings(), report)
        budget.begin()
        budget._write = Mock(side_effect=OSError('disk unavailable'))
        with self.assertRaises(OSError):
            budget.reserve(10)


class FlowRecoveryTests(unittest.TestCase):
    def test_journal_failure_prevents_the_start_challenge_click(self):
        from autohsr.tests.test_core import FakeContext, calyx_scene, support_team
        success = Scene([Token('挑战成功', .99, (.4, .28, .6, .32)),
                         Token('退出关卡', .99, (.75, .85, .85, .95))])
        context = FakeContext([calyx_scene(cost=10, rounds=1), support_team(), success, Scene([])],
                              Settings(stamina_limit=10, rounds=1, use_support=False))
        context.battle_budget = SimpleNamespace(reserve=Mock(side_effect=OSError('disk full')), confirm=Mock())
        with self.assertRaises(OSError):
            DailyWorkflow(context).battle()
        self.assertNotIn('开始挑战', context.clicks)
        context.battle_budget.confirm.assert_not_called()

    def test_unresolved_challenge_is_not_replayed_after_input_interruption(self):
        from autohsr.app import Runner
        from autohsr.models import InputInterrupted
        runner = Runner(Settings())
        runner.report.stamina_pending = 10
        action = Mock(side_effect=InputInterrupted('pause'))
        with self.assertRaisesRegex(AutomationError, '不重复'):
            runner._resume_step(action, 'battle')
        self.assertEqual(action.call_count, 1)

    def test_interrupted_free_step_can_freshly_verify_without_resetting_budget(self):
        from autohsr.app import Runner
        from autohsr.models import InputInterrupted
        runner = Runner(Settings())
        runner.report.stamina_spent = 70
        action = Mock(side_effect=[InputInterrupted('pause'), TaskResult('daily', 'ok', 'verified')])
        self.assertEqual(runner._resume_step(action, 'daily').status, 'ok')
        self.assertEqual(runner.report.stamina_spent, 70)

    def test_optional_error_happens_after_core_proof_and_does_not_erase_it(self):
        from autohsr.app import Runner
        runner = Runner(Settings(assignments=False, battle=False, daily=True, mail=True, battlepass=True))
        called = []
        def daily():
            called.append('daily')
            runner.report.daily_verified = True
            return TaskResult('daily', 'ok', '500 + five claims verified')
        def mail():
            called.append('mail')
            raise AutomationError('手机菜单中未识别到邮件入口。')
        workflow = SimpleNamespace(daily=daily, mail=mail, battlepass=Mock())
        context = SimpleNamespace(last_scene=None)
        runner._run_tasks(context, workflow)
        self.assertEqual(called, ['daily', 'mail'])
        self.assertTrue(runner.report.daily_verified)
        self.assertEqual(runner.report.status, 'partial')
        self.assertEqual(runner.report.failure_task, 'mail')
        workflow.battlepass.assert_not_called()

    def test_same_name_multiple_maps_without_location_is_rejected(self):
        def token(text, x, y):
            return Token(text, .99, (x, y, x + .06, y + .02))
        scene = Scene([token('回忆之蕾', .4, .3), token('城郊雪原', .4, .33), token('传送', .8, .3),
                       token('回忆之蕾', .4, .5), token('绘世学院', .4, .53), token('传送', .8, .5)])
        workflow = DailyWorkflow(SimpleNamespace(settings=Settings(target_location='')))
        with self.assertRaisesRegex(AutomationError, '多个|歧义|地点'):
            workflow._guide_target_row(scene)
        workflow.settings.target_location = '绘世学院'
        self.assertEqual(workflow._guide_target_row(scene)[1].text, '绘世学院')


if __name__ == '__main__':
    unittest.main()
