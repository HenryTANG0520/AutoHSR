"""Missing installations produce correctable errors without game access."""
from contextlib import ExitStack
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Runner
from autohsr.config import Settings, SettingsError
from autohsr.models import AutomationError
from autohsr.plan_runner import PlanRunner
from autohsr.weekly_plan import CHINA
from autohsr.windows import launch


class StartupFeedbackTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root/"missing"/"StarRail.exe"

    def offline(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("autohsr.app.ROOT", self.root))
        stack.enter_context(patch("autohsr.app.C.get_last_error", return_value=0))
        stack.enter_context(patch("autohsr.app.threading.Thread"))
        stack.enter_context(patch.object(Runner, "_arm_hotkeys"))
        stack.enter_context(patch("autohsr.windows.kernel32", SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())))
        self.find = stack.enter_context(patch("autohsr.app.find_game", side_effect=AutomationError("absent")))
        self.launch_process = stack.enter_context(patch("autohsr.windows.subprocess.Popen"))
        self.vision = stack.enter_context(patch("autohsr.app.Vision"))
        self.workflow = stack.enter_context(patch("autohsr.workflows.DailyWorkflow"))

    def assert_report(self, report):
        self.assertEqual(report.input_error_field, "game_path")
        self.assertIn("StarRail.exe", report.error)
        self.assertTrue(report.report_saved)
        self.assertEqual(report.stamina_spent, 0)
        self.assertEqual(report.stamina_pending, 0)
        saved = json.loads((Path(report.run_dir)/"report.json").read_text("utf-8"))
        self.assertEqual(saved, report.to_dict())
        self.launch_process.assert_not_called()
        self.vision.assert_not_called()
        self.workflow.assert_not_called()

    def test_missing_file_and_directory_are_typed_without_launching(self):
        directory = self.root/"StarRail.exe"
        directory.mkdir()
        for path in (self.path, directory):
            with self.subTest(path=path), patch("autohsr.windows.find_game") as find, \
                    patch("autohsr.windows.subprocess.Popen") as process:
                with self.assertRaises(SettingsError) as caught:
                    launch(str(path))
                self.assertEqual(caught.exception.field, "game_path")
                find.assert_not_called()
                process.assert_not_called()

    def test_settings_remain_saveable_without_installation_check(self):
        settings = Settings(game_path=str(self.path))
        settings.save(self.root/"config.json")
        self.assertEqual(Settings.load(self.root/"config.json").game_path, str(self.path))

    def test_existing_window_still_skips_file_check_and_launch(self):
        runner = Runner(Settings(game_path=str(self.path), battle=False))
        window = Mock()
        with patch("autohsr.app.find_game", return_value=window), patch("autohsr.app.launch_game") as start:
            runner._prepare_daily_game()
        start.assert_not_called()
        self.assertIs(runner._window, window)

    def test_daily_failure_keeps_typed_error_in_saved_report(self):
        self.offline()
        report = Runner(Settings(game_path=str(self.path), battle=False)).run()
        self.assertEqual(report.status, "failed")
        self.assert_report(report)

    def test_combined_plan_preserves_error_and_skips_weekly(self):
        self.offline()
        report = PlanRunner(Settings(game_path=str(self.path), battle=False, weekly_enabled=True),
            root=self.root/"runs", now=datetime(2026, 10, 28, 12, tzinfo=CHINA)).run()
        self.assertEqual(report.weekly_plan["status"], "not_started")
        self.assertEqual([child["operation"] for child in report.weekly_plan["children"]], ["daily"])
        self.assert_report(report)

    def test_weekly_only_plan_preserves_startup_error(self):
        self.offline()
        report = PlanRunner(Settings(game_path=str(self.path), assignments=False, battle=False,
            daily=False, weekly_enabled=True), root=self.root/"runs",
            now=datetime(2026, 10, 28, 12, tzinfo=CHINA)).run()
        self.assertEqual([child["operation"] for child in report.weekly_plan["children"]], ["differential_universe"])
        self.assert_report(report)

    def test_permission_error_is_not_mislabeled_as_missing_path(self):
        error = OSError("access denied")
        error.winerror = 5
        with patch("autohsr.windows.Path.is_file", return_value=True), \
                patch("autohsr.windows.find_game", side_effect=AutomationError("absent")), \
                patch("autohsr.windows.subprocess.Popen", side_effect=error):
            with self.assertRaises(AutomationError) as caught:
                launch(str(self.path))
        self.assertNotIsInstance(caught.exception, SettingsError)


if __name__ == "__main__":
    unittest.main()
