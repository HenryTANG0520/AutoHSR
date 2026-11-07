"""Daily battle settlement, persistent budget and optional-task recovery."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, TaskResult
from autohsr.power_plan_run import PowerWorkflow
from autohsr.power_plan_store import validate
from autohsr.recovery import BattleBudget, new_budget_block_reason, recovery_state, replace_file
from autohsr.tests import test_power_plan as fixtures


class BattleBudgetSettlementTests(unittest.TestCase):
    def settled_daily(self, root):
        runs = root / 'runs'
        directory = runs / 'settled'
        directory.mkdir(parents=True)
        start = datetime.fromisoformat('2026-11-07T11:35:42+08:00')
        finish = datetime.fromisoformat('2026-11-07T11:45:35+08:00')
        report = RunReport(operation='daily', status='partial', budget_scope='run', daily_verified=True,
                           report_saved=True, run_dir=str(directory), source=str(root), started_at=start.isoformat(),
                           finished_at=finish.isoformat(), stamina_limit=240, stamina_spent=240,
                           battle_completed=24)
        report.results = [TaskResult(task, 'ok', '') for task in ('assignments', 'battle', 'daily', 'mail')]
        report.results.append(TaskResult('battlepass', 'partial', '分类未核实'))
        budget = BattleBudget(runs, Settings(stamina_limit=240), report)
        with patch('autohsr.recovery.datetime', wraps=datetime) as clock:
            clock.now.return_value = finish
            budget._write('partial')
        source = directory / 'report.json'
        source.write_text(json.dumps(report.to_dict(), ensure_ascii=False), encoding='utf-8')
        return budget, source

    def test_only_battlepass_partial_keeps_same_day_closed_and_allows_next_game_day(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            budget, source = self.settled_daily(root)
            original = budget.path.read_bytes(), source.read_bytes()
            for current in ('2026-11-07T10:00:00+08:00', '2026-11-08T03:59:59+08:00'):
                with self.subTest(current=current), patch('autohsr.recovery.datetime', wraps=datetime) as clock:
                    clock.now.return_value = datetime.fromisoformat(current)
                    with self.assertRaisesRegex(AutomationError, '下一游戏日'):
                        budget.preflight(new_run=True)
            reset = datetime.fromisoformat('2026-11-08T04:00:00+08:00')
            with patch('autohsr.recovery.datetime', wraps=datetime) as clock:
                clock.now.return_value = reset
                state = budget.preflight()
            self.assertEqual((state['status'], state['spent'], state['completed']), ('partial', 240, 24))
            self.assertFalse(state['blocked'])
            self.assertEqual(original, (budget.path.read_bytes(), source.read_bytes()))

    def test_optional_recovery_does_not_accept_missing_or_changed_receipts_and_payments(self):
        reset = datetime.fromisoformat('2026-11-08T04:00:00+08:00')
        for fault in ('missing', 'cost', 'paid_rounds', 'pending', 'token_pending', 'day', 'timestamp',
                      'wrong_run', 'wrong_source', 'unsaved', 'duplicate', 'all_ok', 'no_battlepass', 'daily_mismatch'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                budget, source = self.settled_daily(Path(folder).resolve())
                report = json.loads(source.read_text(encoding='utf-8'))
                ledger = json.loads(budget.path.read_text(encoding='utf-8'))
                if fault == 'missing':
                    source.unlink()
                elif fault == 'cost':
                    report['stamina_spent'] = 230
                elif fault == 'paid_rounds':
                    report['battle_completed'] = 23
                elif fault == 'pending':
                    ledger.update(spent=230, pending=10)
                elif fault == 'token_pending':
                    ledger['immersifiers_pending'] = 1
                elif fault == 'day':
                    report['game_day'] = '2026-11-06'
                elif fault == 'timestamp':
                    report['started_at'] = '2026-11-06T11:35:42+08:00'
                elif fault == 'wrong_run':
                    report['run_dir'] = str(source.parent.parent)
                elif fault == 'wrong_source':
                    report['source'] = str(source.parent)
                elif fault == 'unsaved':
                    report['report_saved'] = False
                elif fault == 'duplicate':
                    report['results'].append(report['results'][0])
                elif fault == 'all_ok':
                    report['results'][-1]['status'] = 'ok'
                elif fault == 'no_battlepass':
                    report['results'].pop()
                elif fault == 'daily_mismatch':
                    report['daily_verified'] = False
                if source.exists():
                    source.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
                budget.path.write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
                state = recovery_state(budget.runs, now=reset)
                self.assertTrue(state['blocked'])
                self.assertIsNotNone(new_budget_block_reason(state))
                self.assertNotIn('settled_daily_battle_day', state)

    def test_other_bound_partial_results_keep_their_original_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            budget, source = self.settled_daily(Path(folder).resolve())
            report = json.loads(source.read_text(encoding='utf-8'))
            report['results'][2]['status'] = 'partial'
            report['daily_verified'] = False
            source.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            state = recovery_state(budget.runs, now=datetime.fromisoformat('2026-11-08T04:00:00+08:00'))
            self.assertTrue(state['blocked'])
            self.assertNotIn('settled_daily_battle_day', state)
            self.assertIsNone(new_budget_block_reason(state))

    def test_settlement_write_failure_preserves_the_previous_batch_and_pending_payment(self):
        for planned in (False, True):
            with self.subTest(planned=planned), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                settings = Settings(dungeon_category='calyx_golden', challenge_count=7, stamina_limit=80,
                                    use_support=False, power_plan_fill=False, power_plan=[fixtures.row(count=7)])
                report = RunReport(run_dir=str(root/'attempt'))
                budget = BattleBudget(root, settings, report)
                budget.begin()
                world = fixtures.World(stamina=80)
                context = fixtures.FakeContext(world, settings, report, budget)

                def fail_second_confirmation(source, destination):
                    data = json.loads(source.read_text(encoding='utf-8'))
                    if (data['spent'], data['pending']) == (70, 0):
                        raise OSError('fixture settlement replacement failed')
                    return replace_file(source, destination)

                with patch('autohsr.recovery.replace_file', fail_second_confirmation):
                    with self.assertRaisesRegex(OSError, 'fixture settlement replacement failed'):
                        if planned:
                            PowerWorkflow(context, workflow_factory=fixtures.Screens).run()
                        else:
                            fixtures.Screens(context).battle()
                pending = json.loads(budget.path.read_text(encoding='utf-8'))
                report.status = 'failed'
                budget.finish()
                stored = json.loads(budget.path.read_text(encoding='utf-8'))
                self.assertEqual(world.paid, [('回忆之蕾', 6, 60), ('回忆之蕾', 1, 10)])
                for ledger in (pending, stored):
                    self.assertEqual((ledger['completed'], ledger['spent'], ledger['pending']), (6, 60, 10))
                self.assertEqual(stored['status'], 'failed')
                self.assertEqual((report.battle_completed, report.stamina_spent, report.stamina_pending), (6, 60, 10))
                if planned:
                    validate(root, stored)
                    self.assertEqual(stored['power_plan'], report.power_plan)
                    self.assertEqual(report.power_plan['done'], [6])
                    self.assertEqual(report.power_plan['intent']['count'], 1)
                with self.assertRaises(AutomationError):
                    BattleBudget(root, settings, RunReport(run_dir=str(root/'next'))).begin(new_run=True)

    def test_mixed_planar_payment_stays_pending_if_the_receipt_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = RunReport(run_dir=str(root/'attempt'))
            budget = BattleBudget(root, Settings(dungeon_category='planar'), report)
            budget.begin()
            budget.reserve(40, immersifiers=2)
            before = budget.path.read_bytes()
            with patch('autohsr.recovery.replace_file', side_effect=OSError('fixture ledger replacement failed')):
                with self.assertRaisesRegex(OSError, 'fixture ledger replacement failed'):
                    budget.confirm(40, immersifiers=2)
            self.assertEqual(budget.path.read_bytes(), before)
            self.assertEqual((report.stamina_spent, report.stamina_pending), (0, 40))
            self.assertEqual((report.immersifiers_spent, report.immersifiers_pending), (0, 2))
