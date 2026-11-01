"""Preserve an explicitly selected daily subtask across plan boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from autohsr.models import AutomationError
from autohsr.plan_runner import PlanRunner
from autohsr.tests import test_plan_runner as fixtures


class PlanDailyScopeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PlanTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.receipt = dict(server='cn', submitted=1, redeemed=1,
            results=[dict(code='ExampleOnly', status='redeemed', reused=False)])
        self.f.daily['redemption'] = deepcopy(self.receipt)
        self.f.daily['results'].append(dict(task='redemption', status='ok', detail='synthetic code result'))
        self.f.settings.redemption_enabled = True

    def only_redemption(self, **options):
        self.f.settings = replace(self.f.settings, assignments=False, battle=False, daily=False,
            mail=False, battlepass=False, **options)
        self.f.daily.update(daily_verified=False, stamina_spent=0,
            results=[dict(task='redemption', status='ok', detail='synthetic code result')])

    def test_redemption_only_without_weekly_is_a_real_selected_daily_task(self):
        self.only_redemption(weekly_enabled=False)
        report = self.f.runner().run()
        self.assertEqual([call[1]['operation'] for call in self.f.calls], ['daily'])
        self.assertEqual(report.weekly_plan['daily_tasks'], ['redemption'])
        self.assertEqual(report.status, 'success')
        self.assertEqual(report.redemption, self.receipt)
        self.assertFalse(report.daily_verified)
        self.assertEqual(report.stamina_spent, 0)

    def test_redemption_only_executes_before_due_weekly(self):
        self.only_redemption()
        report = self.f.runner().run()
        self.assertEqual([call[1]['operation'] for call in self.f.calls], ['daily', 'differential_universe'])
        self.assertEqual(report.redemption, self.receipt)
        self.assertEqual(report.status, 'success')

    def test_daily_scope_order_and_saved_parent_keep_the_original_receipt(self):
        self.f.settings = replace(self.f.settings, mail=True, battlepass=True)
        report = self.f.runner().run()
        self.assertEqual(report.weekly_plan['daily_tasks'],
            ['assignments', 'battle', 'daily', 'redemption', 'mail', 'battlepass'])
        stored = json.loads((Path(report.run_dir) / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['redemption'], self.receipt)
        self.f.daily['redemption']['results'][0]['status'] = 'unknown'
        self.assertEqual(report.redemption, self.receipt)

    def test_partial_or_stopped_daily_keeps_known_codes_and_prevents_weekly(self):
        for status in ('partial', 'stopped'):
            with self.subTest(status=status):
                self.f.calls.clear()
                self.f.daily['status'] = status
                report = self.f.runner().run()
                self.assertEqual([c[1]['operation'] for c in self.f.calls], ['daily'])
                self.assertEqual(report.redemption, self.receipt)
                self.assertEqual(report.weekly_plan['status'], 'not_started')

    def test_later_weekly_exception_cannot_erase_confirmed_daily_codes(self):
        original = self.f.factory
        def factory(settings, emit, **options):
            if options['operation'] != 'daily':
                raise AutomationError('synthetic weekly failure')
            return original(settings, emit, **options)
        runner = self.f.runner()
        runner.factory = factory
        report = runner.run()
        self.assertEqual(report.status, 'partial')
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.redemption, self.receipt)

    def test_resume_weekly_disables_new_daily_redemption_but_reuses_original_receipt(self):
        self.f.settings.weekly_mode = 'currency_wars'
        runner = self.f.runner(resume_weekly_currency=True)
        self.assertFalse(runner.settings.redemption_enabled)
        self.assertTrue(self.f.settings.redemption_enabled)
        runner.report.weekly_plan = dict(children=[])
        runner._copy_daily(self.f.daily, reused=True)
        self.assertEqual(runner.report.redemption, self.receipt)
        self.assertTrue(runner.report.weekly_plan['daily_reused'])


if __name__ == '__main__':
    unittest.main()
