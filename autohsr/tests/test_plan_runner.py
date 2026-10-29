from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.plan_runner import PlanRunner
from autohsr.weekly_plan import CHINA, WeeklyReceipt
from autohsr.tests.test_weekly_plan import du_report


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls, self.events = [], []
        self.daily = dict(operation="daily", status="success", daily_verified=True, report_saved=True,
                          stamina_spent=120, stamina_pending=0, stamina_limit=240,
                          results=[dict(task="daily", status="ok", detail="实训已核实")])
        self.settings = Settings(weekly_enabled=True)
        self.now = datetime(2026, 10, 28, 12, tzinfo=CHINA)
        self.before_return = lambda child: None

    def factory(self, settings, emit, **options):
        owner = self
        class Child:
            paused = False
            stopped = False
            def toggle_pause(self):
                self.paused = not self.paused
                emit(dict(type="paused", paused=self.paused))
                return self.paused
            def stop(self):
                self.stopped = True
            def run(self):
                owner.calls.append((replace(settings), options))
                if options["operation"] == "daily":
                    report = dict(owner.daily)
                elif options['operation'] == 'currency_wars_points':
                    report = dict(operation='currency_wars_points', status='partial', report_saved=True,
                                  error='模拟积分未核实', results=[])
                else:
                    guard = options["weekly_plan"]
                    guard.receipt = WeeklyReceipt(owner.root, "a"*24, guard.slot)
                    guard.already_complete = not guard.receipt.begin(guard.settings)
                    report = du_report(owner.root, options["du_runs"])
                emit(dict(type="finished", report=report))
                owner.before_return(self)
                return report
        return Child()

    def runner(self, **kwargs):
        return PlanRunner(self.settings, self.events.append, root=self.root, now=self.now,
                          runner_factory=self.factory, **kwargs)

    def test_one_start_runs_daily_then_due_weekly_and_preserves_proof(self):
        runner = self.runner()
        report = runner.run()
        self.assertEqual([v[1]["operation"] for v in self.calls], ["daily", "differential_universe"])
        self.assertEqual(report.status, "success")
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_spent, 120)
        self.assertEqual(report.weekly_plan["status"], "complete")
        self.assertFalse(report.weekly_plan["score_rewards_verified"])
        self.assertEqual(len([e for e in self.events if e["type"] == "finished"]), 1)
        self.assertTrue(report.report_saved)
        self.assertEqual(json.loads((Path(report.run_dir)/"report.json").read_text("utf-8")), report.to_dict())
        du = self.calls[1][0]
        self.assertEqual(du.differential_universe_runs, 1)
        self.assertEqual(du.differential_universe_mode, "periodic")
        self.assertFalse(du.differential_universe_daily or du.differential_universe_rewards or du.differential_universe_save)

    def test_settings_are_frozen_at_start(self):
        runner = self.runner()
        self.settings.weekly_mode = "currency_wars"
        self.settings.stamina_limit = 10
        self.settings.assignments = self.settings.battle = self.settings.daily = False
        report = runner.run()
        self.assertEqual(report.weekly_plan["mode"], "differential_universe")
        self.assertEqual(report.weekly_plan["daily_tasks"], ["assignments", "battle", "daily"])
        self.assertEqual(self.calls[0][0].stamina_limit, 240)

    def test_future_weekly_only_freezes_empty_daily_scope_without_a_child(self):
        self.settings = replace(self.settings, assignments=False, battle=False, daily=False,
                                mail=False, battlepass=False, weekly_day=7)
        report = self.runner().run()
        self.assertEqual(self.calls, [])
        self.assertEqual(report.weekly_plan["daily_tasks"], [])
        self.assertEqual(report.weekly_plan["status"], "not_due")
        self.assertTrue(report.report_saved)
        self.assertEqual(report.status, "success")

    def test_due_weekly_only_does_not_claim_a_daily_result(self):
        self.settings = replace(self.settings, assignments=False, battle=False, daily=False,
                                mail=False, battlepass=False, weekly_mode="currency_wars")
        report = self.runner().run()
        self.assertEqual([item[1]['operation'] for item in self.calls], ['currency_wars_points'])
        self.assertEqual(report.weekly_plan["daily_tasks"], [])
        self.assertNotIn("日常结果", report.weekly_plan["message"])
        self.assertEqual(report.status, "partial")

    def test_daily_proof_is_published_before_weekly_can_finish(self):
        observed = []
        original = self.factory
        def factory(settings, emit, **options):
            if options["operation"] == "differential_universe":
                observed.extend(e for e in self.events if e["type"] == "plan_daily_result")
                emit(dict(type="progress", stamina_spent=0))
            return original(settings, emit, **options)
        runner = self.runner()
        runner.factory = factory
        report = runner.run()
        self.assertEqual(len(observed), 1)
        self.assertTrue(observed[0]["report"]["daily_verified"])
        self.assertEqual(observed[0]["report"]["stamina_spent"], 120)
        self.assertEqual([e["phase"] for e in self.events if e["type"] == "plan_phase"], ["daily", "weekly"])
        self.assertEqual([e["phase"] for e in self.events if e["type"] == "progress"], ["weekly"])
        self.assertEqual(report.stamina_spent, 120)

    def test_disabled_and_not_due_do_not_create_du_runner(self):
        for values, status in ((dict(weekly_enabled=False), "disabled"), (dict(weekly_day=7), "not_due")):
            with self.subTest(status=status):
                self.settings = replace(Settings(), **values)
                if status == "not_due":
                    self.settings.weekly_enabled = True
                self.calls.clear()
                report = self.runner().run()
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(report.weekly_plan["status"], status)
                self.assertEqual(report.status, "success")

    def test_currency_requires_saved_original_daily_before_starting_weekly(self):
        self.settings.weekly_mode = "currency_wars"
        report = self.runner().run()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(report.status, "partial")
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.weekly_plan["status"], "needs_review")

    def test_daily_failure_or_unsaved_report_does_not_start_weekly(self):
        for values in (dict(status="partial"), dict(status="stopped"), dict(report_saved=False)):
            with self.subTest(values=values):
                original = dict(self.daily)
                self.daily.update(values)
                self.calls.clear()
                report = self.runner().run()
                self.assertEqual(len(self.calls), 1)
                self.assertTrue(report.daily_verified)
                self.assertEqual(report.weekly_plan["status"], "not_started")
                self.daily = original

    def test_stop_at_handoff_does_not_start_next_runner(self):
        runner = self.runner()
        self.before_return = lambda child: runner.stop()
        report = runner.run()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(report.status, "stopped")
        self.assertTrue(report.daily_verified)

    def test_stop_before_start_has_no_child(self):
        runner = self.runner()
        runner.stop()
        report = runner.run()
        self.assertEqual(report.status, "stopped")
        self.assertEqual(self.calls, [])

    def test_pause_survives_handoff_and_stop_releases_it(self):
        runner = self.runner()
        paused = threading.Event()
        def finish(child):
            runner.toggle_pause()
            paused.set()
        self.before_return = finish
        worker = threading.Thread(target=runner.run)
        worker.start()
        self.assertTrue(paused.wait(2))
        self.assertTrue(worker.is_alive())
        self.assertEqual(len(self.calls), 1)
        runner.stop()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(self.calls), 1)

    def test_combined_report_failure_retains_child_result(self):
        self.settings.weekly_enabled = False
        with patch("autohsr.plan_runner.replace_file", side_effect=OSError("locked")):
            report = self.runner().run()
        self.assertFalse(report.report_saved)
        self.assertEqual(report.status, "partial")
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_spent, 120)


if __name__ == "__main__":
    unittest.main()
