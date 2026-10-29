"""Runtime configuration failures return to their field; all backends are fake."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import Mock, patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module, pump
from ui_layout_smoke import check_layout
from autohsr.config import SettingsError

OUT = ROOT/"runs/startup-feedback-ui"
MESSAGE = "未找到 StarRail.exe，请重新选择游戏路径。"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    fake = types.ModuleType("autohsr.app")
    fake.launch_game = Mock(side_effect=SettingsError("game_path", MESSAGE))
    fake.inspect_game = Mock(side_effect=AssertionError("No game inspection"))
    fake.Runner = Mock(side_effect=AssertionError("No real runner"))
    with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"autohsr.app": fake}), \
            patch.object(module, "ROOT", Path(folder)), patch.object(module.messagebox, "showerror") as modal:
        config = Path(folder)/"config.json"
        Settings(game_path=str(Path(folder)/"missing"/"StarRail.exe"), battle=False).save(config)
        original = config.read_bytes()
        root = tk.Tk()
        root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
        ui = Window(root, config)
        try:
            root.update()
            ui._launch()
            pump(root, lambda: not ui.busy)
            root.update()
            check("launch_focuses_path", ui.active_page == "settings" and root.focus_get() == ui.game_path_entry)
            check("launch_reason_and_selection", ui.summary_label.message() == MESSAGE and ui.game_path_entry.selection_present())
            check("no_extra_modal_or_save", not modal.called and config.read_bytes() == original)
            check_layout(root)
            ImageGrab.grab(window=root.winfo_id()).save(OUT/"launch-path-error.png")
            ui.game_path.set(ui.game_path.get()+" ")
            check("editing_clears_field_error", not ui.input_error.get() and "失败" in ui.status.get())

            for daily_verified in (False, True):
                ui._show_page("home")
                report = dict(operation="plan", status="partial", report_saved=True,
                    error=MESSAGE, input_error_field="game_path", daily_verified=daily_verified,
                    stamina_spent=120 if daily_verified else 0, stamina_limit=240, stamina_pending=0,
                    weekly_plan=dict(status="needs_review" if daily_verified else "not_started",
                        message="周常未开始。"), results=[])
                frozen = copy.deepcopy(report)
                with patch("autohsr.plan_runner.PlanRunner") as factory:
                    factory.return_value.run.return_value = report
                    ui._start(run_plan=True)
                    pump(root, lambda: not ui.busy)
                root.update()
                prefix = "after_daily" if daily_verified else "before_daily"
                check(prefix+"_focuses_path", ui.active_page == "settings" and root.focus_get() == ui.game_path_entry
                      and ui.settings_tabs.select() == str(ui.settings_sections["game"]))
                check(prefix+"_keeps_start_plan", ui.action_page == "home" and ui.start_button.cget("text") == "开始计划")
                check(prefix+"_keeps_report", json.loads(ui.report_text.get("1.0", "end-1c")) == frozen and report == frozen)
                check(prefix+"_keeps_daily_and_cost", ui.training_meter.verified == daily_verified
                      and ui.confirmed_stamina == (120 if daily_verified else 0))
                check(prefix+"_only_one_start", factory.call_count == 1 and fake.launch_game.call_count == 1)
                check(prefix+"_no_config_write", config.read_bytes() == original)
                ui.game_path.set(ui.game_path.get()+" ")
                check(prefix+"_edit_keeps_result", not ui.input_error.get() and ui.summary.get()
                      and json.loads(ui.report_text.get("1.0", "end-1c")) == frozen)
                ui._leave_settings()
                root.update()
                check(prefix+"_return_home", ui.active_page == "home")

            ui._show_page("home")
            ui._finish(dict(operation="plan", status="partial", error=MESSAGE, input_error_field="game_path",
                            report_saved=False, stamina_pending=10, immersifiers_pending=2))
            root.update()
            check("other_failures_and_costs_remain_visible", all(text in ui.input_error.get()
                  for text in ("报告未保存", "10 开拓力待核对", "2 沉浸器待核对", "StarRail.exe")))
            ui._clear_input_error()

            for field in (None, "unknown", [], "game_path"):
                ui._show_page("home")
                report = dict(operation="daily", status="failed", error=MESSAGE if field != "game_path" else "",
                              input_error_field=field, results=[])
                ui._finish(report)
                root.update()
                check("no_guessing_"+repr(field), ui.active_page == "home" and not ui.input_error.get())

            ui.emit(dict(type="run_error", message=MESSAGE, input_error_field="game_path"))
            pump(root, lambda: ui.active_page == "settings")
            check("constructor_error_also_focuses_path", root.focus_get() == ui.game_path_entry)
            check("no_real_backend_or_save", not fake.inspect_game.called and not fake.Runner.called
                  and config.read_bytes() == original and not modal.called)
        finally:
            ui.closing = True
            root.destroy()
    result = dict(count=len(checks), checks=checks, game_started=False, config_unchanged=True)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
