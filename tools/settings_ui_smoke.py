"""Exercise settings choices, draft persistence and layout without a game backend."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from home_feedback_smoke import drawn_text

OUT = ROOT/"runs/settings-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)

    def click(widget):
        x, y = widget.winfo_width()//2, widget.winfo_height()//2
        widget.event_generate("<ButtonPress-1>", x=x, y=y)
        widget.event_generate("<ButtonRelease-1>", x=x, y=y)

    def choose(root, widget, index):
        current = widget.current()
        click(widget)
        root.update()
        pop = str(root.tk.call("ttk::combobox::PopdownWindow", widget))
        assert root.tk.call("winfo", "ismapped", pop), "Clicking the value must open its choices"
        listing = pop+".f.l"
        for _ in range(abs(index-current)):
            root.tk.call("event", "generate", listing, "<KeyPress-Down>" if index > current else "<KeyPress-Up>")
        root.tk.call("event", "generate", listing, "<KeyPress-Return>")
        root.update()

    fake = types.ModuleType("autohsr.app")
    def reject_runner(*args, **kwargs):
        raise AssertionError("Settings must not start a game backend")
    fake.Runner = reject_runner
    with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"autohsr.app": fake}), patch.object(module, "ROOT", Path(folder)):
        config = Path(folder)/"config.json"
        for scale in (1., 1.5, 2.):
            Settings().save(config)
            original = config.read_bytes()
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                ui._show_weekly_plan()
                root.update()
                check(f"{scale}_settings_owns_surface", ui.settings_shell.winfo_ismapped()
                      and not ui.guide.winfo_ismapped() and not ui.header.winfo_ismapped()
                      and ui.settings_shell.plan.winfo_ismapped())
                check(f"{scale}_initial_draft_unchanged", not ui.dirty and not ui.weekly_enabled.get())
                choose(root, ui.weekly_enabled_combo, 0)
                check(f"{scale}_enable_by_value_and_keyboard", ui.weekly_enabled.get() and ui.dirty and "未加入" not in ui.weekly_status.get())
                choose(root, ui.weekly_day_combo, 2)
                check(f"{scale}_day_selects_wednesday", ui.weekly_day.get() == "周三")
                ui.weekly_enabled.set(False)
                check(f"{scale}_external_boolean_updates_display", ui.weekly_enabled_combo.get() == "关闭")
                choose(root, ui.weekly_enabled_combo, 0)
                choose(root, ui.weekly_mode_combo, 1)
                check(f"{scale}_currency_hides_complete_du_rows", all(not control.winfo_ismapped() for control in ui.weekly_run_controls)
                      and "尚未接入" in ui.weekly_boundary.get())
                check(f"{scale}_hidden_fields_not_keyboard_targets", str(root.tk.call("tk_focusNext", ui.weekly_time_entry)) not in
                      (str(ui.weekly_runs_combo), str(ui.weekly_team_entry)))
                choose(root, ui.weekly_mode_combo, 0)
                check(f"{scale}_du_rows_restore", all(control.winfo_ismapped() for control in ui.weekly_run_controls))
                click(ui.weekly_day_combo)
                root.update()
                pop = str(root.tk.call("ttk::combobox::PopdownWindow", ui.weekly_day_combo))
                root.tk.call("event", "generate", pop+".f.l", "<KeyPress-Escape>")
                root.update()
                check(f"{scale}_escape_only_closes_dropdown", ui.active_page == "settings"
                      and not root.tk.call("winfo", "ismapped", pop) and ui.weekly_day.get() == "周三")
                ui.weekly_time_entry.focus_force()
                ui.weekly_time_entry.event_generate("<KeyPress-Escape>")
                root.update()
                check(f"{scale}_escape_returns_to_daily", ui.active_page == "home"
                      and root.focus_get() == ui.weekly_button and ui.start_button.cget("text") == "开始计划")
                for origin in ("home", "tasks", "differential_universe", "currency_wars", "logs"):
                    ui._show_page(origin)
                    root.update()
                    before_action = ui.action_page
                    ui._show_page("settings")
                    root.update()
                    ui.settings_shell.back.invoke()
                    root.update()
                    check(f"{scale}_return_restores_{origin}", ui.active_page == origin and ui.action_page == before_action
                          and ui.guide.winfo_ismapped() and not ui.settings_shell.winfo_ismapped())
                ui._show_page("differential_universe")
                ui._show_weekly_plan()
                root.focus_force()
                root.event_generate("<KeyPress-Escape>")
                root.update()
                check(f"{scale}_weekly_returns_home_from_independent_mode", ui.active_page == "home"
                      and ui.action_page == "home")
                ui._show_weekly_plan()
                root.update()
                ui.settings_buttons["weekly"].focus_force()
                ui.settings_buttons["weekly"].event_generate("<KeyPress-Right>")
                root.update()
                check(f"{scale}_category_keyboard_moves_and_focuses", ui.settings_tabs.select() == str(ui.settings_sections["run"])
                      and root.focus_get() == ui.settings_buttons["run"])
                previous_photo = ui.settings_shell._photo
                root.withdraw()
                root.update()
                ui.stamina.set("120")
                ui.elapsed_seconds = 65
                ui._clock()
                root.update()
                check(f"{scale}_hidden_surface_does_not_repaint", ui.settings_shell._photo is previous_photo)
                root.deiconify()
                root.update()
                check(f"{scale}_restored_surface_has_current_cost_and_time", ui.settings_shell._photo is not previous_photo
                      and "已用开拓力  120" in drawn_text(ui.settings_shell) and "01:05" in drawn_text(ui.settings_shell))
                ui.stamina.set("—")
                ui.elapsed_seconds = 0
                ui._clock()
                ui.settings_buttons["run"].invoke()
                root.update()
                for control, variable, name in ((ui.overlay_control, ui.overlay_logs, "subtitle"),
                                                (ui.synthesis_control, ui.daily_synthesis, "synthesis")):
                    choose(root, control, 1)
                    check(f"{scale}_{name}_turns_off", not variable.get())
                    choose(root, control, 0)
                    check(f"{scale}_{name}_turns_on", variable.get())
                ui._set_busy(True)
                root.update()
                for section, control, variable in (("run", ui.overlay_control, ui.overlay_logs),
                        ("run", ui.synthesis_control, ui.daily_synthesis), ("weekly", ui.weekly_enabled_combo, ui.weekly_enabled)):
                    ui.settings_tabs.select(ui.settings_sections[section])
                    root.update()
                    before = variable.get()
                    click(control)
                    control.event_generate("<KeyPress-Down>")
                    control.event_generate("<KeyPress-Return>")
                    root.update()
                    pop = str(root.tk.call("ttk::combobox::PopdownWindow", control))
                    check(f"{scale}_{control}_locked", variable.get() == before and not root.tk.call("winfo", "ismapped", pop))
                ui.settings_shell.back.invoke()
                root.update()
                check(f"{scale}_return_keeps_running_lock", ui.busy and ui.active_page == "home"
                      and str(ui.start_button.cget("state")) == "disabled")
                ui._show_weekly_plan()
                root.update()
                ui._set_busy(False)
                choose(root, ui.weekly_enabled_combo, 1)
                check(f"{scale}_unlock_restores_native_selection", not ui.weekly_enabled.get())
                ui.weekly_enabled.set(True)
                ui.readiness.set("已找到游戏窗口；当前权限不匹配，请核对管理员启动状态。")
                ui.admin_launch_status.set("授权状态：未启用。首次需要 Windows 授权，移动目录后需要重新启用。")
                default_geometry = root.geometry()
                for size in ("default", "minimum"):
                    root.geometry(default_geometry if size == "default" else "%dx%d" % root.minsize())
                    for name, button in ui.settings_buttons.items():
                        button.invoke()
                        root.update()
                        check_layout(root)
                        check(f"{scale}_{size}_{name}_reachable", ui.settings_tabs.select() == str(ui.settings_sections[name])
                              and ui.start_button.cget("text") == "开始计划" and not ui.guide.winfo_ismapped()
                              and ui.settings_shell.back.winfo_ismapped())
                        if scale == 1.5:
                            ImageGrab.grab(window=root.winfo_id()).save(OUT/(name+"-"+size+".png"))
                check(f"{scale}_draft_and_navigation_do_not_save", original == config.read_bytes())
                ui.save_button.invoke()
                saved = Settings.load(config)
                check(f"{scale}_explicit_save_persists_switches", saved.weekly_enabled and saved.weekly_day == 3
                      and saved.daily_synthesis and saved.overlay_logs and not ui.dirty)
            finally:
                ui.closing = True
                root.update_idletasks()
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    script = str(root.tk.call("after", "info", token)[0])
                    if script.endswith("_drain"):
                        root.after_cancel(token)
                root.destroy()
    result = dict(game_started=False, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
