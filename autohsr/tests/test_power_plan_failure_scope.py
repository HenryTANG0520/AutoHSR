"""Native battle failures stop the remaining plan, using synthetic game IO."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.models import RunReport, Token
from autohsr.power_plan_run import PowerWorkflow
from autohsr.power_plan_store import read, validate
from autohsr.recovery import BattleBudget
from autohsr.tests import test_power_plan as fixtures
from autohsr.weekly_plan import CHINA


class UnavailableTeam(fixtures.World):
    """A real battle page carries an unavailable-team warning before payment."""

    def __init__(self, target, *, after_payments=0, stamina=80):
        super().__init__(stamina=stamina)
        self.unavailable_target = target
        self.after_payments = after_payments

    def scene(self, settings):
        scene = super().scene(settings)
        if (self.mode == 'team' and settings.target_name == self.unavailable_target
                and len(self.payments) >= self.after_payments):
            scene.tokens.append(Token('阵亡', .99, (.4, .3, .6, .4)))
        return scene


class PowerFailureScopeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        clock = patch('autohsr.echo_weekly.local_now',
                      return_value=datetime(2026, 11, 1, 12, tzinfo=CHINA))
        clock.start()
        self.addCleanup(clock.stop)

    def context(self, settings, world):
        report = RunReport(run_dir=str(self.root / 'current'))
        budget = BattleBudget(self.root, settings, report)
        budget.begin(protect_pending=True)
        return fixtures.FakeContext(world, settings, report, budget)

    def run_plan(self, context):
        return PowerWorkflow(context, workflow_factory=fixtures.Screens).run()

    def assert_saved(self, context, *, spent, done, status):
        ledger = read(context.battle_budget.path)
        validate(self.root, ledger)
        self.assertEqual((ledger['spent'], ledger['pending']), (spent, 0))
        self.assertEqual(ledger['power_plan']['done'], done)
        self.assertEqual(ledger['power_plan']['run_status'], status)
        self.assertIsNone(ledger['power_plan']['intent'])

    def test_unavailable_planned_team_does_not_start_later_rows_or_default_fill(self):
        settings = Settings(power_plan=[
            fixtures.row('stagnant_shadow', 1, '苦寒晶壳', '残响回廊'),
            fixtures.row('cavern', 1, '侵蚀隧洞', '残响回廊')],
            power_plan_fill=True, stamina_limit=80, use_support=False)
        context = self.context(settings, UnavailableTeam('苦寒晶壳'))
        result = self.run_plan(context)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(context.world.payments, [])
        self.assertNotIn('侵蚀隧洞', context.world.opened)
        self.assertEqual(context.world.opened[-1], '苦寒晶壳')
        self.assertEqual([(r['row'], r['status']) for r in context.report.power_plan['results']],
                         [(0, 'partial')])
        self.assert_saved(context, spent=0, done=[0, 0], status='partial')

    def test_later_team_failure_preserves_the_earlier_success_without_fill(self):
        settings = Settings(power_plan=[fixtures.row(count=1),
            fixtures.row('stagnant_shadow', 1, '苦寒晶壳', '残响回廊')],
            power_plan_fill=True, stamina_limit=80, use_support=False)
        context = self.context(settings, UnavailableTeam('苦寒晶壳'))
        result = self.run_plan(context)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(context.world.payments, [('回忆之蕾', 1, 10, 0)])
        self.assertEqual(context.report.battle_completed, 1)
        self.assertEqual([(r['row'], r['status']) for r in context.report.power_plan['results']],
                         [(0, 'ok'), (1, 'partial')])
        self.assert_saved(context, spent=10, done=[1, 0], status='partial')

    def test_partial_native_batch_keeps_confirmed_six_and_stops_default_fill(self):
        settings = Settings(power_plan=[fixtures.row(count=8)], power_plan_fill=True,
            dungeon_category='cavern', target_name='侵蚀隧洞', target_location='残响回廊',
            stamina_limit=140, use_support=False)
        world = UnavailableTeam('回忆之蕾', after_payments=1, stamina=140)
        context = self.context(settings, world)
        result = self.run_plan(context)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(world.payments, [('回忆之蕾', 6, 60, 0)])
        self.assertEqual(context.report.battle_completed, 6)
        self.assertEqual(context.report.power_plan['results'][0]['completed'], 6)
        self.assertNotIn('侵蚀隧洞', world.opened)
        self.assert_saved(context, spent=60, done=[6], status='partial')

    def test_failed_weekly_prelude_does_not_reopen_or_start_any_later_stage(self):
        settings = Settings(power_plan=[fixtures.row(count=1)], power_plan_fill=True,
            echo_of_war_enabled=True, stamina_limit=80, use_support=False)
        world = UnavailableTeam(settings.echo_of_war_target)
        context = self.context(settings, world)
        result = self.run_plan(context)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(world.payments, [])
        self.assertEqual([(r['row'], r['status']) for r in context.report.power_plan['results']],
                         [(-2, 'partial')])
        echo = context.report.power_plan['weekly_echo']
        self.assertEqual((echo['state'], echo['completed']), ('partial', 0))
        self.assertEqual(len(echo['observations']), 1)
        self.assertEqual(world.opened.count(settings.echo_of_war_target), 2)
        self.assert_saved(context, spent=0, done=[0], status='partial')

    def test_known_zero_weekly_allowance_still_allows_default_fill(self):
        settings = Settings(power_plan=[fixtures.row('echo_of_war', 3, '毁灭的开端', '支援舱段')],
            power_plan_fill=True, stamina_limit=80, use_support=False)
        world = fixtures.World(stamina=80)
        world.weekly_left = 0
        context = self.context(settings, world)
        self.assertEqual(self.run_plan(context).status, 'ok')
        self.assertEqual(sum(p[2] for p in world.payments), 80)
        self.assertTrue(all(p[0] == '回忆之蕾' for p in world.payments))
        self.assertEqual(context.report.power_plan['results'][0]['reason'], 'weekly_exhausted')
        self.assert_saved(context, spent=80, done=[0], status='complete')

    def test_known_insufficient_resources_can_fill_the_cheaper_default(self):
        settings = Settings(power_plan=[fixtures.row('stagnant_shadow', 1, '苦寒晶壳', '残响回廊')],
            power_plan_fill=True, stamina_limit=20, use_support=False)
        context = self.context(settings, fixtures.World(stamina=20))
        self.assertEqual(self.run_plan(context).status, 'ok')
        self.assertEqual(context.world.payments, [('回忆之蕾', 2, 20, 0)])
        self.assert_saved(context, spent=20, done=[0], status='complete')

    def test_successful_limited_weekly_prelude_keeps_running_planned_rows(self):
        settings = Settings(power_plan=[fixtures.row(count=2)], power_plan_fill=False,
            echo_of_war_enabled=True, stamina_limit=80, use_support=False)
        context = self.context(settings, fixtures.World(stamina=80))
        self.assertEqual(self.run_plan(context).status, 'ok')
        self.assertEqual(context.world.payments,
                         [('毁灭的开端', 2, 60, 0), ('回忆之蕾', 2, 20, 0)])
        self.assertEqual(context.report.power_plan['weekly_echo']['state'], 'limited')
        self.assert_saved(context, spent=80, done=[2], status='complete')


if __name__ == '__main__':
    unittest.main()
