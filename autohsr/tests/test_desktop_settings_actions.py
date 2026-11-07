"""Settings action routing with a withdrawn Tk window and fake run controls."""
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from autohsr.config import Settings
from autohsr.gui import AutoHSRWindow


PLAY_SCOPES = (
    ("home", "开始计划", {"run_plan": True}),
    ("differential_universe", "开始演算", {"differential_universe": True}),
    ("currency_wars", "只读识别当前画面", {"currency_wars": True}),
)


class DesktopSettingsActionTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch("autohsr.gui.ROOT", folder))
        self.config = folder / "config.json"
        Settings(battle=False).save(self.config)
        self.original = self.config.read_bytes()
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk 不可用：{error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.errors = []
        self.root.report_callback_exception = lambda _kind, value, _tb: self.errors.append(value)
        self.ui = AutoHSRWindow(self.root, self.config)
        self.enterContext(patch.object(self.ui, "_restore"))
        self.enterContext(patch.object(self.root, "iconify"))
        for name in ("autohsr.app.Runner", "autohsr.plan_runner.PlanRunner"):
            factory = self.enterContext(patch(name, side_effect=AssertionError("Unexpected game dispatch")))
            self.addCleanup(factory.assert_not_called)
        self.addCleanup(self.check_window)
        self.root.update()

    def check_window(self):
        self.assertEqual(self.root.state(), "withdrawn")
        self.assertEqual(self.errors, [])

    def assert_no_play_action(self):
        self.assertIs(self.ui.start_button, self.ui.footer_start_button)
        self.assertFalse(self.ui.start_button.winfo_manager())
        self.assertTrue(self.ui.start_button.instate(("disabled",)))

    def test_ordinary_settings_keep_save_and_return_to_each_original_action(self):
        ui = self.ui
        ui.overlay_logs.set(not ui.overlay_logs.get())
        for page, label, options in PLAY_SCOPES:
            with self.subTest(page=page), patch.object(ui, "_start") as start:
                ui._show_page(page)
                ui._show_page("settings")
                ui.settings_shell.choose("recognition")
                self.root.update()
                self.assert_no_play_action()
                self.assertTrue(ui.save_button.winfo_manager())
                self.assertTrue(ui.save_button.instate(("!disabled",)))
                ui.start_button.invoke()
                start.assert_not_called()
                ui.settings_shell.back.invoke()
                self.root.update()
                self.assertEqual((ui.active_page, ui.action_page), (page, page))
                self.assertIn(label, ui.start_button.cget("text"))
                ui.start_button.invoke()
                start.assert_called_once_with(**options)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_tools_action_is_available_only_on_its_own_page(self):
        ui = self.ui
        ui._show_page("currency_wars")
        ui._show_page("settings")
        ui.settings_shell.choose("recognition")
        ui._show_tools(ui.guide.tools_button)
        ui.tools_shelf.select("workflow")
        self.root.update()
        self.assertEqual(ui.start_button.cget("text"), "新建草稿")
        self.assertTrue(ui.start_button.winfo_manager())
        self.assertTrue(ui.start_button.instate(("!disabled",)))
        ui.start_button.invoke()
        self.assertIsNotNone(ui.workflow_panel.draft)
        self.assertEqual(ui.start_button.cget("text"), "另存为")
        ui.settings_shell.back.invoke()
        self.root.update()
        self.assertEqual(ui.settings_tabs.select(), str(ui.settings_sections["recognition"]))
        self.assert_no_play_action()
        ui.settings_shell.back.invoke()
        self.assertEqual(ui.active_page, "currency_wars")

    def test_settings_keep_pause_and_stop_for_the_active_runner(self):
        ui = self.ui
        runner = Mock()
        runner.toggle_pause.return_value = True
        ui.runner = ui._native_run.runner = runner
        ui._show_page("differential_universe")
        ui._set_busy(True, True)
        ui._show_page("settings")
        self.root.update()
        self.assert_no_play_action()
        for button in (ui.pause_button, ui.stop_button):
            self.assertTrue(button.winfo_manager())
            self.assertTrue(button.instate(("!disabled",)))
        ui.pause_button.invoke()
        runner.toggle_pause.assert_called_once_with()
        self.assertEqual(ui.pause_button.cget("text"), "继续 F9")
        ui.stop_button.invoke()
        runner.stop.assert_called_once_with()
        self.assertTrue(ui.stop_button.instate(("disabled",)))
        self.assert_no_play_action()

    def test_launch_validation_keeps_the_error_field_and_original_return_scope(self):
        ui = self.ui
        original_path = ui.game_path.get()
        for page, label, options in PLAY_SCOPES:
            with self.subTest(page=page), patch.object(ui.input_focus, "request", wraps=ui.input_focus.request) as focus:
                ui._show_page(page)
                ui.game_path.set("invalid.exe")
                ui.start_button.invoke()
                self.root.update()
                self.assertIsNone(ui.worker)
                self.assertEqual((ui.active_page, ui.settings_return_page, ui.settings_return_action),
                                 ("settings", page, page))
                self.assertEqual(ui.settings_tabs.select(), str(ui.settings_sections["game"]))
                self.assertIn("StarRail.exe", ui.input_error.get())
                focus.assert_called_once_with("game_path", "settings", "game", "game_path_entry")
                self.assert_no_play_action()
                ui.game_path.set(original_path)
                self.assertEqual(ui.input_error.get(), "")
                self.assertIsNone(ui.worker)
                with patch.object(ui, "_start") as start:
                    ui.settings_shell.back.invoke()
                    self.root.update()
                    self.assertEqual((ui.active_page, ui.action_page), (page, page))
                    self.assertIn(label, ui.start_button.cget("text"))
                    start.assert_not_called()
                    ui.start_button.invoke()
                    start.assert_called_once_with(**options)
        self.assertEqual(self.config.read_bytes(), self.original)
