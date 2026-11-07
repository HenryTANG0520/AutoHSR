from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, Scene, Token
from autohsr.weekly_plan import CHINA, WeeklyGuard, WeeklyReceipt, plan_caption, weekly_slot


def when(value):
    return datetime.fromisoformat(value).replace(tzinfo=CHINA)


def du_report(root, requested=1, *, receipt=None):
    folder = Path(root)/"child"
    folder.mkdir(exist_ok=True)
    rows = []
    for i in range(requested):
        row = dict(status="completed", counted=True, difficulty_verified=True, run_id=str(uuid4()), origin="fresh")
        for field in ("started_evidence", "victory_evidence", "return_evidence"):
            path = folder/f"{i}-{field}.png"
            path.write_bytes(f"synthetic offline evidence {i} {field}".encode())
            row[field] = str(path)
        rows.append(row)
    report = dict(operation="differential_universe", status="success", report_saved=True,
                  run_dir=str(folder), differential_universe=dict(mode="周期演算", requested_runs=requested,
                  completed_runs=requested, run_results=rows))
    if receipt is not None:
        report["weekly_plan"] = dict(fixed_du_scope=receipt.fixed_scope(receipt.data))
    (folder/"report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return report


class CalendarTests(unittest.TestCase):
    def test_refresh_boundary(self):
        before = weekly_slot(Settings(), when("2026-10-26T03:59:59"))
        at = weekly_slot(Settings(), when("2026-10-26T04:00:00"))
        self.assertEqual(before.week, "2026-10-19")
        self.assertEqual(at.week, "2026-10-26")
        self.assertTrue(at.due)

    def test_custom_time_catches_up_within_game_week(self):
        settings = Settings(weekly_day=3, weekly_time="20:30")
        self.assertFalse(weekly_slot(settings, when("2026-10-28T20:29:59")).due)
        self.assertTrue(weekly_slot(settings, when("2026-10-28T20:30:00")).due)
        self.assertTrue(weekly_slot(settings, when("2026-10-30T18:00:00")).due)
        self.assertFalse(weekly_slot(settings, when("2026-11-02T04:00:00")).due)

    def test_early_monday_belongs_to_ending_week(self):
        settings = Settings(weekly_time="02:00")
        slot = weekly_slot(settings, when("2026-10-26T02:00:00"))
        self.assertEqual(slot.week, "2026-10-19")
        self.assertTrue(slot.due)
        slot = weekly_slot(settings, when("2026-10-26T04:00:00"))
        self.assertEqual(slot.due_at, when("2026-11-02T02:00:00"))
        self.assertFalse(slot.due)

    def test_timezone_and_year_boundary(self):
        a = weekly_slot(Settings(), when("2027-01-01T12:00:00"))
        b = weekly_slot(Settings(), when("2027-01-01T12:00:00").astimezone(timezone.utc))
        self.assertEqual(a, b)
        self.assertEqual(a.week, "2026-12-28")
        with self.assertRaises(ValueError):
            weekly_slot(Settings(), datetime(2026, 10, 28))

    def test_invalid_schedule_rejected_even_on_save(self):
        for values in (dict(weekly_time="4:00"), dict(weekly_time="24:00"), dict(weekly_time="12:60"),
                       dict(weekly_day=True), dict(weekly_day=0), dict(weekly_day=8),
                       dict(weekly_enabled=1), dict(weekly_runs=True), dict(weekly_runs=0),
                       dict(weekly_runs=11), dict(weekly_mode=[]), dict(weekly_mode="unknown")):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(Settings(), **values).validate("save")

    def test_legacy_config_and_explicit_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"config.json"
            path.write_text('{"target_name":"回忆之蕾"}', encoding="utf-8")
            original = path.read_bytes()
            settings = Settings.load(path)
            self.assertFalse(settings.weekly_enabled)
            settings.weekly_enabled = True
            self.assertEqual(path.read_bytes(), original)
            settings.save(path)
            self.assertEqual(Settings.load(path), settings)

    def test_preview_does_not_claim_account_completion(self):
        caption = plan_caption(Settings(weekly_enabled=True), when("2026-10-28T12:00:00"))
        self.assertIn("运行时核对", caption)
        self.assertNotIn("已完成", caption)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = Settings(weekly_enabled=True)
        self.slot = weekly_slot(self.settings, when("2026-10-28T12:00:00"))
        self.receipt = WeeklyReceipt(self.root, "a"*24, self.slot)

    def test_verified_completion_deduplicates_and_accounts_are_separate(self):
        self.assertTrue(self.receipt.begin(self.settings, fixed_run_dir=self.root / "child"))
        self.receipt.complete(du_report(self.root, receipt=self.receipt))
        self.assertFalse(WeeklyReceipt(self.root, "a"*24, self.slot).begin(self.settings))


        self.assertTrue(WeeklyReceipt(self.root, "b"*24, self.slot).begin(self.settings, fixed_run_dir=self.root / "other-child"))

    def test_schedule_edit_cannot_start_again_in_same_week(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        self.receipt.complete(du_report(self.root, receipt=self.receipt))
        edited = replace(self.settings, weekly_day=2, weekly_runs=3)
        self.assertFalse(WeeklyReceipt(self.root, "a"*24, weekly_slot(edited, when("2026-10-28T12:00:00"))).begin(edited))

    def test_unknown_intent_blocks_current_and_future_week(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        before = self.receipt.path.read_bytes()
        for now in ("2026-10-28T13:00:00", "2026-11-02T04:00:00"):
            with self.assertRaisesRegex(AutomationError, "待核对"):
                WeeklyReceipt(self.root, "a"*24, weekly_slot(self.settings, when(now))).begin(self.settings)
        self.assertEqual(before, self.receipt.path.read_bytes())

    def test_next_week_has_new_receipt_after_verified_completion(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        self.receipt.complete(du_report(self.root, receipt=self.receipt))
        before = self.receipt.path.read_bytes()
        next_week = WeeklyReceipt(self.root, "a"*24, weekly_slot(self.settings, when("2026-11-02T04:00:00")))
        self.assertTrue(next_week.begin(self.settings, fixed_run_dir=self.root / "next-child"))
        self.assertEqual(self.receipt.path.read_bytes(), before)

    def test_fixed_receipt_cannot_be_relabelled_to_another_account_or_week(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        self.receipt.complete(du_report(self.root, receipt=self.receipt))
        before = self.receipt.path.read_bytes()
        other = WeeklyReceipt(self.root, "b"*24, self.slot)
        later = WeeklyReceipt(self.root, "a"*24, weekly_slot(self.settings, when("2026-11-02T04:00:00")))
        for target in (other, later):
            with self.subTest(account=target.account, week=target.slot.week):
                target.folder.mkdir(parents=True, exist_ok=True)
                relabelled = dict(json.loads(before), account_key=target.account, week=target.slot.week,
                                  due_at=target.slot.due_at.isoformat())
                target.path.write_text(json.dumps(relabelled), encoding="utf-8")
                unchanged = target.path.read_bytes()
                with self.assertRaisesRegex(AutomationError, "待核对"):
                    target.begin(self.settings, fixed_run_dir=self.root / "new-child")
                self.assertEqual(target.path.read_bytes(), unchanged)
        self.assertEqual(self.receipt.path.read_bytes(), before)

    def test_unbound_fixed_history_blocks_new_week_without_rewriting_history(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        self.receipt.complete(du_report(self.root, receipt=self.receipt))
        for state in ("complete", "started"):
            with self.subTest(state=state):
                legacy = dict(self.receipt.data, version=1, state=state)
                for name in ("account_key", "run_dir", "intent_id", "objective"):
                    legacy.pop(name)
                self.receipt.path.write_text(json.dumps(legacy), encoding="utf-8")
                unchanged = self.receipt.path.read_bytes()
                later = WeeklyReceipt(self.root, "a"*24, weekly_slot(self.settings, when("2026-11-02T04:00:00")))
                with self.assertRaisesRegex(AutomationError, "待核对"):
                    later.begin(self.settings, fixed_run_dir=self.root / "new-child")
                self.assertEqual(self.receipt.path.read_bytes(), unchanged)
                self.assertFalse(later.path.exists())

    def test_fixed_completion_rejects_repeated_runs_paths_or_evidence(self):
        settings = replace(self.settings, weekly_runs=2)
        self.receipt.begin(settings, fixed_run_dir=self.root / "child")
        before = self.receipt.path.read_bytes()
        for overlap in ("run_id", "path", "content"):
            with self.subTest(overlap=overlap):
                report = du_report(self.root, 2, receipt=self.receipt)
                first, second = report["differential_universe"]["run_results"]
                if overlap == "run_id":
                    second["run_id"] = first["run_id"]
                elif overlap == "path":
                    second["victory_evidence"] = first["victory_evidence"]
                else:
                    for key in ("started_evidence", "victory_evidence", "return_evidence"):
                        Path(second[key]).write_bytes(Path(first[key]).read_bytes())
                (Path(report["run_dir"]) / "report.json").write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaises(AutomationError):
                    self.receipt.complete(report)
                self.assertEqual(self.receipt.path.read_bytes(), before)
        self.assertEqual(self.receipt.complete(du_report(self.root, 2, receipt=self.receipt)), "complete")

    def test_victory_counter_alone_cannot_complete(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        report = du_report(self.root, receipt=self.receipt)
        report["differential_universe"]["run_results"][0].pop("victory_evidence")
        with self.assertRaises(AutomationError):
            self.receipt.complete(report)
        self.assertEqual(json.loads(self.receipt.path.read_text("utf-8"))["state"], "started")

    def test_failed_or_unsaved_reports_cannot_complete(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        for field, value in (("status", "partial"), ("status", "stopped"), ("report_saved", False)):
            report = du_report(self.root, receipt=self.receipt)
            report[field] = value
            with self.assertRaises(AutomationError):
                self.receipt.complete(report)

    def test_missing_or_changed_original_evidence_blocks_replay(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        report = du_report(self.root, receipt=self.receipt)
        self.receipt.complete(report)
        Path(report["differential_universe"]["run_results"][0]["victory_evidence"]).write_bytes(b"changed")
        with self.assertRaises(AutomationError):
            WeeklyReceipt(self.root, "a"*24, self.slot).begin(self.settings)

    def test_fixed_receipt_retry_rejects_changed_victory_evidence(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        intent = self.receipt.path.read_bytes()
        report = du_report(self.root, receipt=self.receipt)
        victory = Path(report['differential_universe']['run_results'][0]['victory_evidence'])
        replace_path = Path.replace
        writes = []

        def locked_then_changed(source, destination):
            if Path(destination) == self.receipt.path:
                writes.append(destination)
                if len(writes) == 1:
                    raise PermissionError('synthetic sharing violation')
            return replace_path(source, destination)

        with patch.object(Path, 'replace', locked_then_changed), \
                patch('autohsr.storage.time.sleep', side_effect=lambda _: victory.write_bytes(b'changed')):
            with self.assertRaisesRegex(AutomationError, '原始演算证据'):
                self.receipt.complete(report)
        self.assertEqual(len(writes), 1)
        self.assertEqual(self.receipt.path.read_bytes(), intent)

    def test_corrupt_record_is_preserved_and_blocks(self):
        self.receipt.folder.mkdir(parents=True)
        self.receipt.path.write_text("[]", encoding="utf-8")
        with self.assertRaises(AutomationError):
            self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        self.assertEqual(self.receipt.path.read_text("utf-8"), "[]")

    def test_failed_receipt_save_does_not_erase_intent(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        original = self.receipt.path.read_bytes()
        with patch("autohsr.weekly_plan.replace_file", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                self.receipt.complete(du_report(self.root, receipt=self.receipt))
        self.assertEqual(self.receipt.path.read_bytes(), original)

    def test_json_coordinate_conversion_does_not_discard_verified_report(self):
        self.receipt.begin(self.settings, fixed_run_dir=self.root / "child")
        report = du_report(self.root, receipt=self.receipt)
        report["differential_universe"]["actions"] = [dict(box=(.1, .2, .3, .4))]
        (Path(report["run_dir"])/"report.json").write_text(json.dumps(report), encoding="utf-8")
        self.receipt.complete(report)
        self.assertFalse(WeeklyReceipt(self.root, "a"*24, self.slot).begin(self.settings))


class GuardTests(unittest.TestCase):
    def test_real_runner_checks_receipt_before_starting_workflow(self):
        from autohsr.app import Runner
        from autohsr.models import TaskResult
        from autohsr.tests.test_runner_recovery import RunnerRecoveryTests
        for outcome in (False, True, AutomationError("待核对")):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                context, _ = RunnerRecoveryTests.fixture(self, root, Mock())
                settings = Settings(overlay_logs=False)
                guard = WeeklyGuard(root/"runs", settings, weekly_slot(settings))
                options = dict(side_effect=outcome) if isinstance(outcome, Exception) else dict(return_value=outcome)
                with patch.object(guard, "prepare", **options) as prepare, \
                        patch.object(Runner, "_prepare_daily_game") as startup, \
                        patch("autohsr.differential_universe.DifferentialUniverseWorkflow") as workflow:
                    workflow.return_value.run.return_value = TaskResult("differential_universe", "ok", "模拟返回")
                    report = Runner(settings, operation="differential_universe", weekly_plan=guard).run()
                startup.assert_called_once()
                prepare.assert_called_once_with(context)
                self.assertEqual(workflow.call_count, 1 if outcome is True else 0)
                self.assertEqual(report.status, "failed" if isinstance(outcome, Exception) else "success")

    def test_account_is_rechecked_after_navigation_before_any_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(weekly_enabled=True)
            guard = WeeklyGuard(Path(tmp), settings, weekly_slot(settings))
            calls = []
            context = Mock()
            context.settings = settings
            context.report = RunReport(run_dir=str(Path(tmp) / 'child'))
            scene = Scene([Token('UID:100000000', .99, (.01, .96, .12, .99))])
            context.snapshot.side_effect = lambda: calls.append("snapshot") or scene
            with patch("autohsr.workflows.DailyWorkflow") as workflow, \
                    patch("autohsr.du_daily.account_key", side_effect=lambda _: calls.append("account") or "a"*24):
                workflow.return_value.ensure_main.side_effect = lambda: calls.append("navigate")
                self.assertTrue(guard.prepare(context))
            self.assertEqual(calls, ["navigate", "snapshot", "account"])
            self.assertTrue(guard.receipt.path.exists())
            self.assertEqual(context.report.weekly_plan["fixed_du_scope"], guard.receipt.fixed_scope(guard.receipt.data))

    def test_unknown_account_cannot_create_weekly_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(weekly_enabled=True)
            guard = WeeklyGuard(Path(tmp), settings, weekly_slot(settings))
            context = Mock(settings=settings)
            context.snapshot.return_value = Scene([])
            with patch("autohsr.workflows.DailyWorkflow"):
                with self.assertRaisesRegex(AutomationError, "未核实当前账号"):
                    guard.prepare(context)
            self.assertFalse(list(Path(tmp).rglob("*.json")))

    def test_fixed_receipt_rejects_conflicting_account_regions(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(weekly_enabled=True)
            guard = WeeklyGuard(Path(tmp), settings, weekly_slot(settings))
            context = Mock(settings=settings)
            context.report = RunReport(run_dir=str(Path(tmp) / 'child'))
            context.snapshot.return_value = Scene([
                Token('UID:100000000', .99, (.01, .942, .12, .99)),
                Token('UID:200000000', .99, (.24, .96, .34, .99)),
            ])
            with patch("autohsr.workflows.DailyWorkflow"):
                with self.assertRaisesRegex(AutomationError, "未核实当前账号"):
                    guard.prepare(context)
            self.assertFalse(list(Path(tmp).rglob("*.json")))


if __name__ == "__main__":
    unittest.main()
