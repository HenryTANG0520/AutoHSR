from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.models import AutomationError
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
        self.current = self.now
        self.before_return = lambda child: None
        self.persist_daily = True
        owner = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.current.astimezone(tz) if tz else owner.current.replace(tzinfo=None)

        clock = patch('autohsr.weekly_plan.datetime', Clock)
        clock.start()
        self.addCleanup(clock.stop)
        # A fake native points child must reach the same frozen week as its
        # parent plan, even when these tests run months after the fixture date.
        for module in ('currency_wars_weekly', 'currency_wars_weekly_run', 'currency_wars_points',
                       'currency_wars_points_run', 'currency_wars_points_goal', 'currency_wars_weekly_reward_store'):
            clock = patch('autohsr.' + module + '.local_now', side_effect=lambda: self.now)
            clock.start()
            self.addCleanup(clock.stop)

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
                self.operation = options['operation']
                owner.calls.append((replace(settings), options))
                if options["operation"] == "daily":
                    report = dict(owner.daily)
                    if owner.persist_daily:
                        directory = Path(tempfile.mkdtemp(dir=owner.root))
                        report['run_dir'] = str(directory)
                        (directory / 'report.json').write_text(json.dumps(report), encoding='utf-8')
                elif options['operation'] == 'currency_wars_points':
                    report = dict(operation='currency_wars_points', status='partial', report_saved=True,
                                  error='模拟积分未核实', results=[])
                else:
                    guard = options["weekly_plan"]
                    guard.receipt = WeeklyReceipt(owner.root, "a"*24, guard.slot)
                    guard.already_complete = not guard.receipt.begin(guard.settings, fixed_run_dir=owner.root / 'child')
                    if guard.already_complete:
                        report = dict(operation="differential_universe", status="success", report_saved=True)
                    else:
                        report = du_report(owner.root, options["du_runs"], receipt=guard.receipt)
                emit(dict(type="finished", report=report))
                owner.before_return(self)
                return report
        return Child()

    def runner(self, **kwargs):
        return PlanRunner(self.settings, self.events.append, root=self.root, now=self.now,
                          runner_factory=self.factory, **kwargs)

    def test_one_start_runs_daily_then_due_weekly_and_preserves_proof(self):
        supply = dict(claim='sent', reward_display='not_observed', close='not_sent', return_status='without_display')
        self.daily['train_supply'] = supply
        runner = self.runner()
        report = runner.run()
        self.assertEqual([v[1]["operation"] for v in self.calls], ["daily", "differential_universe"])
        self.assertEqual(report.status, "success")
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_spent, 120)
        self.assertEqual(report.to_dict()['train_supply'], supply)
        self.assertEqual(report.weekly_plan["status"], "complete")
        self.assertFalse(report.weekly_plan["score_rewards_verified"])
        self.assertEqual(len([e for e in self.events if e["type"] == "finished"]), 1)
        self.assertTrue(report.report_saved)
        self.assertEqual(json.loads((Path(report.run_dir)/"report.json").read_text("utf-8")), report.to_dict())
        du = self.calls[1][0]
        self.assertEqual(du.differential_universe_runs, 1)
        self.assertEqual(du.differential_universe_mode, "periodic")
        self.assertFalse(du.differential_universe_daily or du.differential_universe_rewards or du.differential_universe_save)

    def test_explicit_workflow_scope_dispatches_only_selected_daily_then_due_weekly(self):
        from autohsr.task_workflow import task_spec

        original = replace(self.settings, redemption_enabled=True)
        settings, options = task_spec(original, dict(task="plan", params={"tasks": ["mail"]}), self.root)
        self.settings = settings
        self.daily.update(daily_verified=False, stamina_spent=0, stamina_limit=0,
                          results=[dict(task="mail", status="ok", detail="邮件已核实")])
        report = self.runner(**options).run()
        self.assertEqual(report.status, "success")
        self.assertEqual(report.weekly_plan["daily_tasks"], ["mail"])
        self.assertEqual([args["operation"] for _, args in self.calls], ["daily", "differential_universe"])
        self.assertTrue(self.calls[0][0].mail)
        self.assertFalse(self.calls[0][0].battle or self.calls[0][0].redemption_enabled)
        self.assertTrue(original.battle and original.redemption_enabled)

    def test_settings_are_frozen_at_start(self):
        runner = self.runner()
        self.settings.weekly_mode = "currency_wars"
        self.settings.stamina_limit = 10
        self.settings.assignments = self.settings.battle = self.settings.daily = False
        report = runner.run()
        self.assertEqual(report.weekly_plan["mode"], "differential_universe")
        self.assertEqual(report.weekly_plan["daily_tasks"], ["assignments", "battle", "daily"])
        self.assertEqual(self.calls[0][0].stamina_limit, 240)

    def test_same_plan_cannot_restart_during_or_after_its_original_execution(self):
        runner = self.runner()
        entered, release = threading.Event(), threading.Event()
        reports = []

        def hold_daily(child):
            if child.operation == 'daily':
                entered.set()
                if not release.wait(5):
                    raise AssertionError('test did not release the daily child')

        self.before_return = hold_daily
        worker = threading.Thread(target=lambda: reports.append(runner.run()))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            directories = set(self.root.iterdir())
            with self.assertRaisesRegex(AutomationError, '只能执行一次'):
                runner.run()
            self.assertEqual(set(self.root.iterdir()), directories)
            self.assertEqual(len(self.calls), 1)
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        report, = reports
        self.assertEqual(report.status, 'success')
        path = Path(report.run_dir) / 'report.json'
        original = path.read_bytes()
        directories = set(self.root.iterdir())
        with self.assertRaisesRegex(AutomationError, '只能执行一次'):
            runner.run()
        self.assertEqual(set(self.root.iterdir()), directories)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual([options['operation'] for _, options in self.calls], ['daily', 'differential_universe'])

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
        self.persist_daily = False
        report = self.runner().run()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(report.status, "partial")
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.weekly_plan["status"], "needs_review")

    def test_daily_source_is_checked_again_after_weekly_phase_event(self):
        runner = self.runner()
        path = None

        def emit(event):
            nonlocal path
            if event['type'] == 'plan_daily_result':
                path = Path(event['report']['run_dir']) / 'report.json'
            elif event['type'] == 'plan_phase' and event['phase'] == 'weekly':
                path.write_text('{"status":"partial","report_saved":false}', encoding='utf-8')

        runner.emit = emit
        report = runner.run()
        self.assertEqual([options['operation'] for _, options in self.calls], ['daily'])
        self.assertEqual((report.status, report.weekly_plan['daily_handoff']), ('partial', 'needs_review'))
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_spent, 120)
        self.assertFalse(list(self.root.glob('weekly-plan/*/*.json')))

    def test_due_differential_requires_daily_report_inside_plan_runs_root(self):
        self.persist_daily = False
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / 'report.json'
            self.daily['run_dir'] = outside
            path.write_text(json.dumps(self.daily), encoding='utf-8')
            report = self.runner().run()
            self.assertEqual([options['operation'] for _, options in self.calls], ['daily'])
            self.assertEqual(report.weekly_plan['daily_handoff'], 'needs_review')
            self.assertEqual(json.loads(path.read_bytes()), self.daily)

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

    def test_optional_battlepass_partial_retains_verified_daily_and_blocks_weekly(self):
        self.settings.battlepass = True
        self.daily.update(status='partial', failure_task='battlepass')
        self.daily['results'].append(dict(task='battlepass', status='partial', detail='勋礼分类未核实'))
        report = self.runner().run()
        self.assertEqual([options['operation'] for _, options in self.calls], ['daily'])
        self.assertEqual((report.status, report.daily_verified, report.stamina_spent), ('partial', True, 120))
        self.assertEqual(report.weekly_plan['daily_status'], 'partial')
        self.assertTrue(report.weekly_plan['daily_report_saved'])
        self.assertEqual(report.weekly_plan['daily_handoff'], 'needs_review')
        self.assertEqual(report.weekly_plan['status'], 'not_started')
        self.assertFalse(list(self.root.glob('weekly-plan/*/*.json')))

    def test_daily_success_does_not_bypass_independent_daily_or_payment_checks(self):
        for update in (dict(daily_verified=False), dict(stamina_pending=40), dict(immersifiers_pending=1)):
            with self.subTest(update=update):
                original = dict(self.daily)
                self.daily.update(update)
                self.calls.clear()
                report = self.runner().run()
                self.daily = original
                self.assertEqual([options['operation'] for _, options in self.calls], ['daily'])
                self.assertEqual((report.status, report.weekly_plan['daily_handoff']), ('partial', 'needs_review'))
                self.assertEqual(report.weekly_plan['status'], 'not_started')

    def test_daily_can_finish_after_week_reset_without_starting_a_weekly_child(self):
        runner = self.runner()
        self.before_return = lambda child: setattr(self, 'current', datetime(2026, 11, 2, 4, tzinfo=CHINA))
        report = runner.run()
        self.assertEqual([options['operation'] for _, options in self.calls], ['daily'])
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.weekly_plan['week'], '2026-10-26')
        self.assertEqual(report.weekly_plan['status'], 'needs_review')
        self.assertIn('跨游戏周', report.error)
        self.assertFalse(list(self.root.glob('weekly-plan/*/*.json')))

    def test_pause_across_reset_rechecks_week_before_constructing_weekly_child(self):
        runner = self.runner()
        daily_published = threading.Event()
        weekly_construction = []
        original = self.factory

        def emit(event):
            if event['type'] == 'plan_daily_result':
                runner.toggle_pause()
                daily_published.set()

        def factory(settings, send, **options):
            if options['operation'] == 'differential_universe':
                weekly_construction.append(True)
            return original(settings, send, **options)

        runner.emit, runner.factory = emit, factory
        worker = threading.Thread(target=runner.run)
        worker.start()
        try:
            self.assertTrue(daily_published.wait(2))
            self.assertTrue(worker.is_alive())
            self.current = datetime(2026, 11, 2, 4, tzinfo=CHINA)
            self.assertFalse(runner.toggle_pause())
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                runner.stop()
                worker.join(2)
        self.assertEqual(weekly_construction, [])
        self.assertTrue(runner.report.daily_verified)
        self.assertEqual(runner.report.weekly_plan['daily_handoff'], 'complete')
        self.assertEqual(runner.report.weekly_plan['status'], 'needs_review')

    def test_same_week_reuses_only_the_original_weekly_receipt(self):
        first = self.runner().run()
        original, = self.root.glob('weekly-plan/*/*.json')
        source = original.read_bytes()
        self.calls.clear()
        self.settings.weekly_runs = 3
        second = self.runner().run()
        self.assertEqual([options['operation'] for _, options in self.calls], ['daily', 'differential_universe'])
        self.assertEqual(second.weekly_plan['status'], 'already_complete')
        self.assertEqual(second.weekly_plan['daily_handoff'], 'complete')
        self.assertEqual(second.weekly_plan['requested_runs'], 1)
        self.assertEqual(second.weekly_plan['new_completed_runs'], 0)
        self.assertEqual(second.weekly_plan['original_run_dir'], first.weekly_plan['children'][-1]['run_dir'])
        self.assertEqual(original.read_bytes(), source)

    def test_reused_weekly_evidence_is_preserved_but_not_accepted_after_reset(self):
        self.runner().run()
        receipt, = self.root.glob('weekly-plan/*/*.json')
        source = receipt.read_bytes()

        def cross_after_read(child):
            if child.operation == 'differential_universe':
                self.current = datetime(2026, 11, 2, 4, tzinfo=CHINA)

        self.before_return = cross_after_read
        report = self.runner().run()
        self.assertEqual(report.status, 'partial')
        self.assertEqual(report.weekly_plan['status'], 'needs_review')
        self.assertFalse(report.weekly_plan.get('reused_result', False))
        self.assertEqual(report.weekly_plan['completed_runs'], 1)
        self.assertEqual(report.weekly_plan['new_completed_runs'], 0)
        self.assertEqual(receipt.read_bytes(), source)

    def test_stop_during_fixed_weekly_receipt_retry_preserves_started_receipt_and_child_win(self):
        runner = self.runner()
        replace_path = Path.replace
        writes = []

        def stop_at_weekly_receipt(source, destination):
            if Path(destination).parent.parent.name == 'weekly-plan':
                writes.append(destination)
                if len(writes) == 1:
                    runner.stop()
                    raise PermissionError('synthetic sharing violation')
            return replace_path(source, destination)

        with patch.object(Path, 'replace', stop_at_weekly_receipt):
            report = runner.run()
        self.assertEqual(len(writes), 1)
        self.assertEqual(report.status, 'stopped')
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.weekly_plan['completed_runs'], 1)
        self.assertEqual(report.weekly_plan['status'], 'needs_review')
        receipt, = self.root.glob('weekly-plan/*/*.json')
        self.assertEqual(json.loads(receipt.read_bytes())['state'], 'started')

    def test_stop_at_partial_daily_handoff_survives_parent_report_failure(self):
        runner = self.runner()
        self.daily.update(status='partial', report_saved=False, report_write_error='synthetic child lock')
        self.before_return = lambda child: runner.stop()
        with patch('autohsr.plan_runner.replace_file', side_effect=OSError('synthetic parent lock')):
            report = runner.run()
        self.assertEqual([options['operation'] for _, options in self.calls], ['daily'])
        self.assertEqual(report.status, 'stopped')
        self.assertTrue(report.daily_verified)
        self.assertFalse(report.report_saved)
        self.assertEqual(report.weekly_plan['daily_handoff'], 'stopped')
        self.assertEqual(report.weekly_plan['daily_report_write_error'], 'synthetic child lock')

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
