"""Recorded OCR, synthetic observations and fake Windows; no live game access."""
from __future__ import annotations

import io
import json
import queue
import tempfile
import time
import unittest
from threading import Event, Thread as TestThread
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars import CurrencyWarsWorkflow, decide, observe
from autohsr.models import AutomationError, FocusLost, InputInterrupted, RunReport, Scene, Stopped, Token


def scene(text="货币战争", score=.99, box=(.1, .1, .3, .2)):
    return Scene([Token(text, score, box)], captured_at=time.monotonic())


class ObservationTests(unittest.TestCase):
    def world_entry(self):
        path = Path(__file__).parent / "fixtures" / "currency_wars_world_entry.json"
        return Scene([Token(**token) for token in json.loads(path.read_text(encoding="utf-8"))["tokens"]])

    def test_live_world_entry_is_distinct_from_opened_gameplay(self):
        result = observe(self.world_entry(), .65)
        self.assertEqual(result.page_kind, "world_entry")
        self.assertTrue(result.mode_text_visible)
        self.assertEqual(decide(result).reason, "entry_not_open")
        self.assertEqual(decide(result).action, "stop_without_input")
        self.assertFalse(any((result.page_verified, result.rules_verified, result.gameplay_enabled, result.completion_verified)))

    def test_world_entry_requires_all_trusted_anchors_in_their_hud_regions(self):
        original = self.world_entry().tokens
        for index, token in enumerate(original):
            for replacement in (None, Token(token.text, .5, token.box), Token(token.text, .99, (.3, .8, .4, .9))):
                with self.subTest(index=index, replacement=replacement):
                    tokens = original[:index] + ([] if replacement is None else [replacement]) + original[index + 1:]
                    self.assertEqual(observe(Scene(tokens), .65).page_kind, "unknown")

    def test_visible_name_is_never_page_rules_or_completion_proof(self):
        result = observe(scene(), .65)
        self.assertTrue(result.mode_text_visible)
        self.assertFalse(any((result.page_verified, result.rules_verified, result.gameplay_enabled, result.completion_verified)))

    def test_substrings_low_confidence_and_invalid_candidates_are_rejected(self):
        for candidate in (scene("货币战争攻略"), scene("战争"), Scene([]), scene(score=.64),
                          scene(score=float("nan")), scene(score=1.1), scene(box=(-.1, .1, .2, .2)),
                          scene(box=(.3, .1, .1, .2)), scene(box=(0, 0, float("inf"), 1))):
            with self.subTest(tokens=candidate.tokens):
                self.assertFalse(observe(candidate, .65).mode_text_visible)


class WorkflowSafetyTests(unittest.TestCase):
    def test_drag_diagnostic_cannot_click_keys_or_use_other_coordinates(self):
        window = Mock()
        context = Context(Runner(Settings(), operation="currency_wars_drag_test"), window, Mock())
        for action in (lambda: context.click(scene(), (.5, .5)), lambda: context.key("esc"),
                       lambda: context.move(scene(), (.5, .5)), lambda: context.scroll(-120),
                       lambda: context.drag(scene(), (.5, .5), (.6, .6))):
            with self.assertRaises(AutomationError):
                action()
        for method in (window.click, window.key, window.move, window.scroll, window.drag):
            method.assert_not_called()

    def test_context_rejects_every_gameplay_input_in_readonly_operation(self):
        window = Mock()
        context = Context(Runner(Settings(), operation="currency_wars"), window, Mock())
        for action in (lambda: context.click(scene(), (.5, .5)), lambda: context.key("esc"),
                       lambda: context.move(scene(), (.5, .5)), lambda: context.scroll(-120),
                       lambda: context.drag(scene(), (.5, .5), (.6, .6))):
            with self.assertRaisesRegex(AutomationError, "只读"):
                action()
        for method in (window.click, window.key, window.move, window.scroll, window.drag):
            method.assert_not_called()

    def context(self, observation):
        sample = patch("autohsr.currency_wars_replay.save_sample", return_value=Path("offline.sample.json"))
        sample.start()
        self.addCleanup(sample.stop)
        context = SimpleNamespace(
            settings=Settings(), report=RunReport(), runner=SimpleNamespace(inactive_duration=0, input_epoch=0, emit=Mock()),
            snapshot=Mock(return_value=observation), checkpoint=Mock(), evidence=Mock(return_value=Path("evidence.png")),
            scene_epoch=0, last_scene=observation, log=Mock(), click=Mock(), key=Mock(),
        )
        return context

    def test_unknown_or_paid_screen_saves_evidence_and_never_sends_input(self):
        for observation in (Scene([], captured_at=time.monotonic()), scene("充值"), scene("购买"), scene("挑战成功")):
            context = self.context(observation)
            result = CurrencyWarsWorkflow(context).inspect()
            self.assertEqual(result.status, "partial")
            self.assertFalse(context.report.currency_wars["completion_verified"])
            context.click.assert_not_called()
            context.key.assert_not_called()

    def test_stale_scene_is_rejected_without_recording_success(self):
        observation = scene()
        observation.captured_at -= 10
        context = self.context(observation)
        with self.assertRaisesRegex(AutomationError, "过期"):
            CurrencyWarsWorkflow(context).inspect()
        context.evidence.assert_not_called()

    def test_pause_invalidates_old_observation_for_fresh_retry(self):
        context = self.context(scene())
        context.runner.input_epoch = 1
        with self.assertRaises(InputInterrupted):
            CurrencyWarsWorkflow(context).inspect()
        self.assertFalse(context.report.currency_wars)
        context.evidence.assert_not_called()

    def test_deadline_rejects_slow_observation_when_it_returns(self):
        context = self.context(scene())
        with patch("autohsr.currency_wars.time.monotonic", side_effect=[0, 31]), self.assertRaisesRegex(AutomationError, "30 秒"):
            CurrencyWarsWorkflow(context).inspect()
        context.evidence.assert_not_called()

    def test_pause_duration_is_excluded_from_deadline(self):
        observation = scene()
        observation.captured_at = 40
        context = self.context(observation)
        def snapshot():
            context.runner.inactive_duration = 40
            return observation
        context.snapshot.side_effect = snapshot
        with patch("autohsr.currency_wars.time.monotonic", side_effect=[0, 40, 40, 40, 40]):
            self.assertEqual(CurrencyWarsWorkflow(context).inspect().status, "partial")

    def test_stop_after_evidence_save_never_publishes_completed_observation(self):
        context = self.context(scene())
        context.checkpoint.side_effect = [None, None, Stopped("stop")]
        with self.assertRaises(Stopped):
            CurrencyWarsWorkflow(context).inspect()
        self.assertFalse(context.report.currency_wars)
        context.runner.emit.assert_not_called()

    def test_pause_during_evidence_save_invalidates_observation(self):
        context = self.context(scene())
        def save(*_):
            context.runner.input_epoch += 1
            return Path("old.png")
        context.evidence.side_effect = save
        with self.assertRaises(InputInterrupted):
            CurrencyWarsWorkflow(context).inspect()
        self.assertFalse(context.report.currency_wars)
        context.runner.emit.assert_not_called()

    def test_slow_evidence_save_cannot_publish_expired_scene(self):
        observation = scene()
        context = self.context(observation)
        def save(*_):
            observation.captured_at -= 10
            return Path("expired.png")
        context.evidence.side_effect = save
        with self.assertRaisesRegex(AutomationError, "过期"):
            CurrencyWarsWorkflow(context).inspect()
        self.assertFalse(context.report.currency_wars)


class CoordinatorTests(unittest.TestCase):
    def fixture(self, root, *, save_error=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        window = Mock()
        window.capture.return_value = (np.zeros((90, 160, 3), dtype=np.uint8), Mock())
        vision = Mock()
        vision.read.side_effect = lambda image, geometry: Scene(scene().tokens, image, geometry)
        stack.enter_context(patch("autohsr.app.ROOT", root))
        stack.enter_context(patch("autohsr.app.C.get_last_error", return_value=0))
        stack.enter_context(patch("autohsr.app.threading.Thread"))
        stack.enter_context(patch("autohsr.app.is_elevated", return_value=True))
        stack.enter_context(patch("autohsr.app.is_admin", return_value=False))
        stack.enter_context(patch("autohsr.app.Vision", return_value=vision))
        stack.enter_context(patch("autohsr.app.IsolatedVision", return_value=vision))
        find = stack.enter_context(patch("autohsr.app.find_game", return_value=window))
        daily = stack.enter_context(patch("autohsr.workflows.DailyWorkflow"))
        launch = stack.enter_context(patch("autohsr.app.launch_game"))
        budget = stack.enter_context(patch("autohsr.recovery.BattleBudget"))
        stack.enter_context(patch("autohsr.windows.kernel32", SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())))
        if save_error:
            stack.enter_context(patch("autohsr.app.save_scene", side_effect=OSError("disk unavailable")))
        return window, vision, find, daily, launch, budget

    def test_readonly_run_keeps_daily_budget_and_saves_real_offline_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = root / "runs/battle-session.json"
            ledger.parent.mkdir()
            ledger.write_text('{"pending":10}', encoding="utf-8")
            window, _, _, daily, launch, budget = self.fixture(root)
            settings = Settings(auto_launch=True, target_location="")
            report = Runner(settings, operation="currency_wars").run()
            saved = json.loads((Path(report.run_dir) / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report.status, "partial")
            self.assertEqual(saved["operation"], "currency_wars")
            self.assertEqual([r["task"] for r in saved["results"]], ["currency_wars"])
            self.assertFalse(saved["currency_wars"]["completion_verified"])
            evidence = Path(saved["currency_wars"]["screenshot"])
            self.assertTrue(evidence.is_file())
            self.assertEqual(evidence.with_suffix(".txt").read_text(encoding="utf-8"), "货币战争")
            self.assertTrue(Path(saved["currency_wars"]["sample"]).is_file())
            self.assertEqual(ledger.read_text(encoding="utf-8"), '{"pending":10}')
            self.assertEqual((report.stamina_spent, report.stamina_pending, report.daily_verified), (0, 0, False))
            for method in (window.click, window.key, window.move, window.scroll, daily, launch, budget):
                method.assert_not_called()

    def test_stop_before_game_access_is_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, _, find, _, _, budget = self.fixture(root)
            runner = Runner(Settings(), operation="currency_wars")
            runner.stop()
            report = runner.run()
            self.assertEqual(report.status, "stopped")
            self.assertTrue((Path(report.run_dir) / "report.json").is_file())
            find.assert_not_called()
            budget.assert_not_called()

    def test_evidence_failure_still_writes_failed_report(self):
        with tempfile.TemporaryDirectory() as folder:
            self.fixture(Path(folder), save_error=True)
            report = Runner(Settings(), operation="currency_wars").run()
            self.assertEqual(report.status, "failed")
            self.assertIn("disk unavailable", report.error)
            self.assertFalse(report.currency_wars)
            self.assertTrue((Path(report.run_dir) / "report.json").is_file())

    def test_ocr_failure_never_enables_gameplay(self):
        with tempfile.TemporaryDirectory() as folder:
            window, vision, *_ = self.fixture(Path(folder))
            vision.read.side_effect = AutomationError("OCR unavailable")
            report = Runner(Settings(), operation="currency_wars").run()
            self.assertEqual(report.status, "failed")
            self.assertFalse(report.currency_wars)
            window.click.assert_not_called()

    def test_unknown_operation_stops_before_game_access(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, find, _, _, budget = self.fixture(Path(folder))
            report = Runner(Settings(), operation="not_a_mode").run()
            self.assertEqual(report.status, "failed")
            self.assertIn("未知运行类型", report.error)
            find.assert_not_called()
            budget.assert_not_called()

    def test_report_save_failure_still_finishes_and_closes_logger(self):
        with tempfile.TemporaryDirectory() as folder:
            self.fixture(Path(folder))
            original = Path.write_text
            def fail_report(path, *args, **kwargs):
                if path.name in ("report.json", "report.tmp"):
                    raise OSError("report disk full")
                return original(path, *args, **kwargs)
            events = []
            runner = Runner(Settings(), events.append, operation="currency_wars")
            with patch.object(Path, "write_text", fail_report):
                report = runner.run()
            self.assertEqual(report.status, "failed")
            self.assertIn("report disk full", report.error)
            self.assertFalse(report.report_saved)
            self.assertFalse(runner._logger.handlers)
            self.assertEqual(events[-1]["type"], "finished")

    def test_report_replace_failure_never_exposes_partial_report_json(self):
        with tempfile.TemporaryDirectory() as folder:
            self.fixture(Path(folder))
            original = Path.replace
            def fail_replace(path, target):
                if path.name == "report.tmp":
                    raise OSError("replace denied")
                return original(path, target)
            runner = Runner(Settings(), operation="currency_wars")
            with patch.object(Path, "replace", fail_replace):
                report = runner.run()
            self.assertFalse(report.report_saved)
            self.assertFalse((Path(report.run_dir) / "report.json").exists())
            self.assertFalse(runner._logger.handlers)

    def test_monitor_start_failure_still_closes_resources_without_joining_unstarted_thread(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, find, *_ = self.fixture(Path(folder))
            monitor = Mock()
            monitor.start.side_effect = RuntimeError("thread start failed")
            with patch("autohsr.app.threading.Thread", return_value=monitor):
                runner = Runner(Settings(), operation="currency_wars")
                report = runner.run()
            self.assertEqual(report.status, "failed")
            self.assertTrue(report.report_saved)
            monitor.join.assert_not_called()
            find.assert_not_called()
            self.assertFalse(runner._logger.handlers)

    def test_stop_during_ocr_joins_worker_after_ocr_returns(self):
        with tempfile.TemporaryDirectory() as folder:
            window, vision, *_ = self.fixture(Path(folder))
            entered, release = Event(), Event()
            def read(image, geometry):
                entered.set()
                if not release.wait(2):
                    raise AssertionError("test OCR release timed out")
                return Scene(scene().tokens, image, geometry)
            vision.read.side_effect = read
            runner = Runner(Settings(), operation="currency_wars")
            reports = []
            worker = TestThread(target=lambda: reports.append(runner.run()))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                runner.stop()
                release.set()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(reports[0].status, "stopped")
                self.assertFalse(reports[0].currency_wars)
                self.assertTrue(reports[0].report_saved)
                window.click.assert_not_called()
            finally:
                runner.stop()
                release.set()
                worker.join(2)

    def test_stop_while_paused_ends_worker_without_resuming_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            window, *_ = self.fixture(Path(folder))
            entered = Event()
            runner = Runner(Settings(), operation="currency_wars")
            runner._pause.set()
            original = runner._control_checkpoint
            def checkpoint():
                entered.set()
                original()
            runner._control_checkpoint = checkpoint
            reports = []
            worker = TestThread(target=lambda: reports.append(runner.run()))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                runner.stop()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(reports[0].status, "stopped")
                window.capture.assert_not_called()
            finally:
                runner.stop()
                worker.join(2)

    def test_focus_loss_during_capture_discards_first_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            window, vision, *_ = self.fixture(Path(folder))
            image, geometry = window.capture.return_value
            window.capture.side_effect = [FocusLost("capture interrupted"), (image, geometry)]
            report = Runner(Settings(), operation="currency_wars").run()
            self.assertEqual(report.status, "partial")
            self.assertEqual(window.capture.call_count, 2)
            self.assertEqual(vision.read.call_count, 1)
            window.click.assert_not_called()

    def test_hotkey_monitor_has_exited_before_finished_event(self):
        with tempfile.TemporaryDirectory() as folder:
            self.fixture(Path(folder))
            started, exited = Event(), Event()
            events = []
            runner = Runner(Settings(), operation="currency_wars")
            def monitor():
                started.set()
                runner._monitor_end.wait(2)
                exited.set()
            def emit(event):
                if event["type"] == "finished":
                    self.assertTrue(exited.is_set())
                events.append(event)
            runner._hotkeys, runner.emit = monitor, emit
            with patch("autohsr.app.threading.Thread", TestThread):
                report = runner.run()
            self.assertTrue(started.is_set() and exited.is_set())
            self.assertEqual(report.status, "partial")
            self.assertEqual(events[-1]["type"], "finished")

    def test_runner_stop_terminates_real_isolated_ocr_even_while_paused(self):
        import multiprocessing
        from autohsr.ocr_isolation import IsolatedVision
        from autohsr.tests.test_ocr_isolation import worker_hangs
        for paused in (False, True):
            with self.subTest(paused=paused), tempfile.TemporaryDirectory() as folder:
                window, *_ = self.fixture(Path(folder))
                runner = Runner(Settings(), operation="currency_wars")
                reports = []
                with patch("autohsr.app.IsolatedVision", IsolatedVision), patch("autohsr.ocr_isolation._ocr_job", worker_hangs):
                    worker = TestThread(target=lambda: reports.append(runner.run()))
                    worker.start()
                    try:
                        until = time.monotonic() + 2
                        while not multiprocessing.active_children() and time.monotonic() < until:
                            time.sleep(.02)
                        self.assertTrue(multiprocessing.active_children())
                        if paused:
                            runner.toggle_pause()
                            time.sleep(.1)
                        runner.stop()
                        worker.join(3)
                        self.assertFalse(worker.is_alive())
                        self.assertEqual(reports[0].status, "stopped")
                        self.assertFalse(reports[0].currency_wars)
                        self.assertEqual(multiprocessing.active_children(), [])
                        window.click.assert_not_called()
                    finally:
                        runner.stop()
                        worker.join(3)


class ContextFailureTests(unittest.TestCase):
    def test_failed_recapture_discards_previous_scene(self):
        runner = Runner(Settings(), operation="currency_wars")
        window, vision = Mock(), Mock()
        window.capture.return_value = (object(), object())
        vision.read.side_effect = [scene(), AutomationError("OCR failed")]
        context = Context(runner, window, vision)
        context.snapshot()
        with self.assertRaises(AutomationError):
            context.snapshot()
        self.assertIsNone(context.last_scene)


class GuiLifecycleTests(unittest.TestCase):
    def test_terminal_event_is_not_applied_while_worker_is_still_alive(self):
        from autohsr.gui import AutoHSRWindow
        events = queue.Queue()
        events.put(dict(type="finished", report=dict(status="partial", operation="currency_wars")))
        worker = Mock()
        worker.is_alive.return_value = True
        ui = SimpleNamespace(events=events, worker=worker, _finish=Mock(), _clock=Mock(), _drain=Mock(), closing=False, root=Mock())
        AutoHSRWindow._drain(ui)
        ui._finish.assert_not_called()
        self.assertFalse(events.empty())
        worker.is_alive.return_value = False
        AutoHSRWindow._drain(ui)
        ui._finish.assert_called_once()
        self.assertTrue(events.empty())


class CliTests(unittest.TestCase):
    def test_currency_check_uses_own_operation_and_does_not_save_config(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            Settings(auto_launch=True).save(config)
            original = config.read_bytes()
            runner = Mock()
            runner.run.return_value = RunReport(status="partial", operation="currency_wars")
            with patch("autohsr.app.Runner", return_value=runner) as factory, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--config", str(config), "--currency-wars-check"]), 1)
            self.assertEqual(factory.call_args.kwargs["operation"], "currency_wars")
            self.assertEqual(config.read_bytes(), original)

    def test_daily_flags_cannot_be_combined_with_currency_check(self):
        from autohsr.__main__ import main
        for flag in ("--reward-only", "--new-battle-run"):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--currency-wars-check", flag]), 2)
