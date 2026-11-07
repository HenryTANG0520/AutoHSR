from __future__ import annotations

import json
import os
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
        with self.assertRaisesRegex(AutomationError, '仍待核对'):
            BattleBudget(self.root, Settings(), RunReport()).begin(new_run=True)

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

    def test_explicit_budget_preserves_pending_cash_and_immersifier_journals(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        for cash, tokens in ((40, 0), (0, 1), (40, 1)):
            with self.subTest(cash=cash, tokens=tokens):
                root = self.root / f'{cash}-{tokens}'
                settings = Settings(stamina_limit=40, dungeon_category='planar')
                report = RunReport(status='stopped')
                original = BattleBudget(root, settings, report)
                original.begin()
                original.reserve(cash, immersifiers=tokens)
                original.finish()
                before = original.path.read_bytes()
                reason = new_budget_block_reason(recovery_state(root))
                for protect_pending in (False, True):
                    candidate = BattleBudget(root, settings, RunReport())
                    with self.assertRaises(AutomationError) as rejected:
                        candidate.begin(new_run=True, protect_pending=protect_pending)
                    self.assertEqual(str(rejected.exception), reason)
                    self.assertFalse(candidate.active)
                    self.assertEqual(original.path.read_bytes(), before)

    def test_confirmed_partial_battle_allows_explicit_new_budget(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        settings = Settings(stamina_limit=40, dungeon_category='planar')
        runs = self.root / 'runs'
        directory = runs / 'paid-attempt'
        directory.mkdir(parents=True)
        report = RunReport(operation='daily', status='partial', budget_scope='run',
                           source=str(self.root), run_dir=str(directory), report_saved=True,
                           stamina_limit=40, battle_requested=2,
                           results=[TaskResult('battle', 'partial', '第二轮未执行')])
        original = BattleBudget(runs, settings, report)
        original.begin()
        original.reserve(40, immersifiers=1)
        original.confirm(40, immersifiers=1, completed=1)
        original.finish()
        timestamp = json.loads(original.path.read_text(encoding='utf-8'))['updated_at']
        report.started_at = report.finished_at = timestamp
        (directory / 'report.json').write_text(json.dumps(report.to_dict()), encoding='utf-8')
        state = recovery_state(runs)
        self.assertTrue(state['blocked'])
        self.assertIsNone(new_budget_block_reason(state))
        candidate = BattleBudget(runs, settings, RunReport())
        with self.assertRaisesRegex(AutomationError, '明确确认新增预算'):
            candidate.begin()
        candidate.begin(new_run=True)
        self.assertTrue(candidate.active)
        self.assertEqual((candidate.report.stamina_spent, candidate.report.immersifiers_spent), (0, 0))

    def historical_report(self, root, name, stamp, **data):
        path = root/name/'report.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.utime(path, (stamp, stamp))
        return path

    def test_legacy_first_payment_is_not_hidden_by_later_nonspending_reports(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        for cash, tokens in ((40, 0), (0, 1)):
            with self.subTest(cash=cash, tokens=tokens):
                root = self.root / f'{cash}-{tokens}'
                original = self.historical_report(root, 'paid-attempt', 10,
                    operation='daily', status='stopped', stamina_spent=0, stamina_pending=cash,
                    immersifiers_spent=0, immersifiers_pending=tokens)
                self.historical_report(root, 'no-battle', 20, operation='daily', status='success',
                    stamina_spent=0, stamina_pending=0, immersifiers_spent=0, immersifiers_pending=0)
                for index, operation in enumerate(('reward_only', 'currency_wars', 'plan'), 30):
                    self.historical_report(root, operation, index, operation=operation, status='success',
                        stamina_spent=40, stamina_pending=0, immersifiers_spent=1, immersifiers_pending=0)
                before = original.read_bytes()
                state = recovery_state(root)
                self.assertEqual(state['source'], str(original))
                self.assertEqual((state['pending'], state['immersifiers_pending']), (cash, tokens))
                self.assertIsNotNone(new_budget_block_reason(state))
                with self.assertRaisesRegex(AutomationError, '仍待核对'):
                    BattleBudget(root, Settings(), RunReport()).begin(new_run=True)
                self.assertFalse((root/'battle-session.json').exists())
                self.assertEqual(original.read_bytes(), before)

    def test_later_settled_daily_does_not_settle_an_earlier_unresolved_payment(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        older_reports = (
            RunReport(operation='daily', status='stopped', stamina_limit=40, stamina_pending=40).to_dict(),
            dict(status='failed', stamina_spent=70, results=[dict(task='battle', status='partial')]),
        )
        for index, older in enumerate(older_reports):
            with self.subTest(pending=older.get('stamina_pending')):
                root = self.root/str(index)
                original = self.historical_report(root, 'interrupted', 10, **older)
                newer = self.historical_report(root, 'different-run', 20,
                    **RunReport(operation='daily', status='success', stamina_limit=40, stamina_spent=40,
                                run_dir=str(root/'different-run'), report_saved=True).to_dict())
                before = original.read_bytes(), newer.read_bytes()
                state = recovery_state(root)
                self.assertEqual(state['source'], str(original))
                self.assertEqual(state['pending'], older.get('stamina_pending'))
                self.assertIsNotNone(new_budget_block_reason(state))
                with self.assertRaisesRegex(AutomationError, '仍待核对'):
                    BattleBudget(root, Settings(), RunReport()).begin(new_run=True)
                self.assertFalse((root/'battle-session.json').exists())
                self.assertEqual((original.read_bytes(), newer.read_bytes()), before)

    def test_history_prefers_latest_cleared_report_and_still_rejects_unreadable_history(self):
        from autohsr.recovery import new_budget_block_reason, recovery_state
        original = self.historical_report(self.root, 'pre-journal', 10, status='success', stamina_spent=40)
        newer = self.historical_report(self.root, 'daily', 20,
            **RunReport(operation='daily', status='partial', stamina_limit=40, stamina_spent=10).to_dict())
        state = recovery_state(self.root)
        self.assertEqual(state['source'], str(newer))
        self.assertTrue(state['blocked'])  # The confirmed partial run still needs explicit consent for a new budget.
        self.assertIsNone(new_budget_block_reason(state))

        original.write_text('{invalid', encoding='utf-8')
        os.utime(original, (10, 10))
        state = recovery_state(self.root)
        self.assertEqual(state['source'], str(original))
        self.assertTrue(state['corrupt'])
        self.assertIsNotNone(new_budget_block_reason(state))
        self.assertEqual(original.read_text('utf-8'), '{invalid')

    def test_canonical_root_journal_takes_precedence_over_unresolved_historical_report(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        settings = Settings(stamina_limit=40)
        budget = BattleBudget(self.root, settings, RunReport(status='success'))
        budget.begin()
        budget.reserve(40)
        budget.confirm(40)
        budget.finish()
        original = self.historical_report(self.root, 'interrupted', 10,
            **RunReport(operation='daily', status='stopped', stamina_limit=40, stamina_pending=40).to_dict())
        before = original.read_bytes()
        state = recovery_state(self.root)
        self.assertEqual(state['source'], str(budget.path))
        self.assertIsNone(new_budget_block_reason(state))

        budget.path.write_text('{invalid', encoding='utf-8')
        state = recovery_state(self.root)
        self.assertEqual(state['source'], str(budget.path))
        self.assertTrue(state['corrupt'])
        self.assertEqual(original.read_bytes(), before)

    def test_parent_report_keeps_explicit_pending_if_child_ledger_is_unavailable(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        for operation in ('plan', 'task_workflow'):
            for cash, tokens in ((40, 0), (0, 1), (0, None)):
                with self.subTest(operation=operation, cash=cash, tokens=tokens):
                    root = self.root/f'{operation}-{cash}-{tokens}'
                    original = self.historical_report(root, 'parent', 10,
                        **RunReport(operation=operation, status='partial', stamina_pending=cash,
                                    immersifiers_pending=tokens).to_dict())
                    before = original.read_bytes()
                    state = recovery_state(root)
                    self.assertEqual(state['source'], str(original))
                    self.assertEqual((state['pending'], state['immersifiers_pending']), (cash, tokens))
                    self.assertIsNotNone(new_budget_block_reason(state))
                    with self.assertRaisesRegex(AutomationError, '仍待核对'):
                        BattleBudget(root, Settings(), RunReport()).begin(new_run=True)
                    self.assertFalse((root/'battle-session.json').exists())
                    self.assertEqual(original.read_bytes(), before)

    def test_missing_or_null_current_pending_counts_remain_unverified(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        cases = (dict(stamina_spent=40), dict(stamina_spent=40, stamina_pending=None),
                 dict(stamina_spent=0, stamina_pending=0, immersifiers_spent=1),
                 dict(stamina_spent=0, stamina_pending=0, immersifiers_pending=0),
                 dict(stamina_spent=0, stamina_pending=0, immersifiers_pending=1),
                 dict(stamina_spent=0, stamina_pending=0, immersifiers_spent=0, immersifiers_pending=None))
        for index, fields in enumerate(cases):
            with self.subTest(fields=fields):
                root = self.root/str(index)
                self.historical_report(root, 'current-format', 10, operation='daily', status='success', **fields)
                state = recovery_state(root)
                self.assertTrue(state['blocked'])
                if fields.get('immersifiers_pending') == 1:
                    self.assertEqual(state['immersifiers_pending'], 1)
                self.assertIsNotNone(new_budget_block_reason(state))
                with self.assertRaisesRegex(AutomationError, '仍待核对'):
                    BattleBudget(root, Settings(), RunReport()).begin(new_run=True)
                self.assertFalse((root/'battle-session.json').exists())

    def test_allocated_daily_budget_without_pending_counter_remains_unverified(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        for limit in (40, 0):
            with self.subTest(limit=limit):
                root = self.root/str(limit)
                data = RunReport(operation='daily', status='stopped', stamina_limit=limit).to_dict()
                del data['stamina_pending']
                original = self.historical_report(root, 'run', 10, **data)
                before = original.read_bytes()
                state = recovery_state(root)
                if limit:
                    self.assertTrue(state['blocked'])
                    self.assertIsNone(state['pending'])
                    self.assertEqual(state['source'], str(original))
                    with self.assertRaisesRegex(AutomationError, '仍待核对'):
                        BattleBudget(root, Settings(), RunReport()).begin(new_run=True)
                    self.assertFalse((root/'battle-session.json').exists())
                else:
                    self.assertFalse(state['blocked'])
                    self.assertIsNone(new_budget_block_reason(state))
                self.assertEqual(original.read_bytes(), before)

    def test_batch_can_check_its_direct_daily_report_after_journal_loss(self):
        from autohsr.recovery import new_budget_block_reason, recovery_state
        original = self.historical_report(self.root, 'batch-01', 10,
            **RunReport(operation='daily', status='stopped', stamina_limit=40,
                        immersifiers_pending=1).to_dict())
        before = original.read_bytes()
        self.assertFalse(recovery_state(original.parent)['blocked'])
        state = recovery_state(original.parent, direct_report=True)
        self.assertEqual(state['source'], str(original))
        self.assertEqual(state['immersifiers_pending'], 1)
        self.assertIsNotNone(new_budget_block_reason(state))
        self.assertEqual(original.read_bytes(), before)

    def test_direct_batch_rejects_report_from_another_operation(self):
        from autohsr.recovery import new_budget_block_reason, recovery_state
        original = self.historical_report(self.root, 'batch-01', 10,
            **RunReport(operation='plan', status='success', stamina_limit=40).to_dict())
        before = original.read_bytes()
        state = recovery_state(original.parent, direct_report=True)
        self.assertEqual(state['source'], str(original))
        self.assertTrue(state['corrupt'])
        self.assertIsNotNone(new_budget_block_reason(state))
        self.assertEqual(original.read_bytes(), before)

    def test_direct_batch_report_cannot_override_present_or_corrupt_journal(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        folder = self.root/'batch-01'
        budget = BattleBudget(folder, Settings(stamina_limit=40), RunReport(status='stopped'))
        budget.begin()
        budget.reserve(40)
        budget.finish()
        (folder/'report.json').write_text(json.dumps(RunReport(operation='daily', status='success',
            stamina_limit=40, stamina_spent=40).to_dict()), encoding='utf-8')
        state = recovery_state(folder, direct_report=True)
        self.assertEqual(state['source'], str(budget.path))
        self.assertEqual(state['pending'], 40)
        budget.path.write_text('{invalid', encoding='utf-8')
        state = recovery_state(folder, direct_report=True)
        self.assertEqual(state['source'], str(budget.path))
        self.assertTrue(state['corrupt'])
        self.assertIsNotNone(new_budget_block_reason(state))
        self.assertEqual(budget.path.read_text('utf-8'), '{invalid')

    def test_successful_pre_journal_report_remains_a_usable_history(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        original = self.historical_report(self.root, 'pre-journal', 10, status='success', stamina_spent=40,
            results=[dict(task='battle', status='ok')])
        before = original.read_bytes()
        state = recovery_state(self.root)
        self.assertFalse(state['blocked'])
        self.assertIsNone(new_budget_block_reason(state))
        budget = BattleBudget(self.root, Settings(), RunReport())
        budget.begin()
        self.assertTrue(budget.active)
        self.assertEqual(original.read_bytes(), before)

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

    def test_canonical_journal_with_one_missing_immersifier_field_is_preserved(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        for missing in ('immersifiers_spent', 'immersifiers_pending'):
            with self.subTest(missing=missing):
                root = self.root/missing
                settings = Settings(stamina_limit=40, dungeon_category='planar')
                original = BattleBudget(root, settings, RunReport(status='success'))
                original.begin()
                original.reserve(40)
                original.confirm(40)
                original.finish()
                data = json.loads(original.path.read_bytes())
                del data[missing]
                before = json.dumps(data).encode('utf-8')
                original.path.write_bytes(before)
                state = recovery_state(root)
                self.assertTrue(state['corrupt'])
                self.assertIsNotNone(new_budget_block_reason(state))
                with self.assertRaises(AutomationError):
                    BattleBudget(root, settings, RunReport()).begin(new_run=True)
                self.assertEqual(original.path.read_bytes(), before)

    def test_pre_immersifier_journal_without_either_field_remains_usable(self):
        from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state
        settings = Settings(stamina_limit=40)
        original = BattleBudget(self.root, settings, RunReport(status='success'))
        original.begin()
        original.reserve(40)
        original.confirm(40)
        original.finish()
        data = json.loads(original.path.read_bytes())
        for field in ('immersifiers_spent', 'immersifiers_pending'):
            del data[field]
        original.path.write_text(json.dumps(data), encoding='utf-8')
        state = recovery_state(self.root)
        self.assertFalse(state['blocked'])
        self.assertIsNone(new_budget_block_reason(state))
        candidate = BattleBudget(self.root, settings, RunReport())
        candidate.begin()
        self.assertTrue(candidate.active)

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
