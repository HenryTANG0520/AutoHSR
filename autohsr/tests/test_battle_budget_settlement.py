"""Payment and completion stay pending when a successful battle cannot be recorded."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport
from autohsr.power_plan_run import PowerWorkflow
from autohsr.power_plan_store import validate
from autohsr.recovery import BattleBudget, replace_file
from autohsr.tests import test_power_plan as fixtures


class BattleBudgetSettlementTests(unittest.TestCase):
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
