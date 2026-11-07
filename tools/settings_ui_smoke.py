"""Exercise settings choices, draft persistence and layout without a game backend."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import call, patch

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
                root.update()
                root.focus_force()
                ui.table.focus_set()
                ui._show_weekly_plan(return_focus=ui.table)
                root.update()
                check(f"{scale}_weekly_entry_focuses_visible_choice", root.focus_get() == ui.weekly_enabled_combo
                      and root.focus_get().winfo_viewable() and not ui.weekly_enabled.get())
                ui.weekly_enabled_combo.event_generate("<KeyPress-Down>")
                root.update()
                pop = str(root.tk.call("ttk::combobox::PopdownWindow", ui.weekly_enabled_combo))
                check(f"{scale}_entry_keyboard_opens_choice_without_changing_plan", root.tk.call("winfo", "ismapped", pop)
                      and not ui.dirty and not ui.weekly_enabled.get())
                root.tk.call("event", "generate", pop+".f.l", "<KeyPress-Escape>")
                root.update()
                ui.weekly_enabled_combo.event_generate("<KeyPress-Escape>")
                root.update()
                check(f"{scale}_entry_escape_returns_to_origin", ui.active_page == "home"
                      and root.focus_get() == ui.table)
                ui.guide.buttons["settings"].focus_set()
                ui.guide.buttons["settings"].invoke()
                root.update()
                check(f"{scale}_settings_entry_focuses_remembered_section", root.focus_get() == ui.weekly_enabled_combo)
                ui.settings_buttons["game"].invoke()
                root.update()
                check(f"{scale}_hidden_section_focus_moves_to_new_section", root.focus_get() == ui.game_path_entry)
                ui.game_path_entry.selection_range(0, "end")
                ui._show_page("settings")
                root.update()
                check(f"{scale}_visible_field_selection_is_preserved", root.focus_get() == ui.game_path_entry
                      and ui.game_path_entry.selection_present())
                ui._show_summary("保留本次费用", return_focus=ui.game_path_entry)
                root.update()
                check(f"{scale}_entry_focus_does_not_take_over_details", root.focus_get() is ui.detail_text)
                ui.detail_back.invoke()
                root.update()
                check(f"{scale}_details_return_to_the_original_field", root.focus_get() == ui.game_path_entry)
                ui._set_busy(True)
                ui._show_page("settings")
                root.update()
                check(f"{scale}_locked_current_field_returns_to_navigation", root.focus_get() == ui.settings_buttons["game"])
                ui.settings_buttons["weekly"].invoke()
                root.update()
                check(f"{scale}_locked_section_focuses_its_navigation", root.focus_get() == ui.settings_buttons["weekly"])
                ui._set_busy(False)
                ui._leave_settings()
                ui._show_weekly_plan()
                ui._leave_settings()
                root.update()
                check(f"{scale}_pending_entry_focus_cannot_follow_return", ui.active_page == "home"
                      and root.focus_get() == ui.table and not ui.dirty and config.read_bytes() == original)
                board = ui.table
                board.selected = "daily"
                board.activate()
                root.update()
                check(f"{scale}_daily_card_opens_task_choices", ui.active_page == "settings"
                      and ui.settings_tabs.select() == str(ui.settings_sections["daily"])
                      and not ui.dungeon_list.winfo_ismapped()
                      and not ui.start_button.winfo_ismapped() and ui.start_button.instate(("disabled",)))
                for task in ("assignments", "daily", "mail", "battlepass"):
                    control = ui.daily_task_controls[task]
                    original_value = ui.tasks[task].get()
                    choose(root, control, 1 if original_value else 0)
                    check(f"{scale}_{task}_choice_updates_plan", ui.tasks[task].get() != original_value
                          and ui.dirty
                          and board.item(task, "values")[1] == ("未加入" if original_value else "待执行"))
                    choose(root, control, 0 if original_value else 1)
                ui.settings_shell.back.invoke()
                root.update()
                returned_focus = str(root.tk.call("focus", "-lastfor", root)) == str(board)
                check(f"{scale}_return_restores_daily_card", ui.active_page == "home"
                      and returned_focus and board.selected == "daily" and not ui.dirty)
                check(f"{scale}_return_restores_plan_button", ui.start_button.winfo_ismapped()
                      and ui.start_button.cget("text") == "开始计划")
                with patch.object(ui, "_start") as start:
                    ui.start_button.invoke()
                    check(f"{scale}_return_dispatches_daily_plan", start.call_args_list == [call(run_plan=True)])
                ui.tasks["battle"].set(False)
                ui.table.selected = "battle"
                ui.table.activate()
                root.update()
                check(f"{scale}_disabled_battle_opens_dungeon_without_enabling", ui.active_page == "tasks"
                      and not ui.tasks["battle"].get() and root.focus_get() == ui.dungeon_list)
                ui._show_daily_tasks("battle")
                root.update()
                check(f"{scale}_battle_checkbox_and_settings_stay_in_sync", ui.daily_task_controls["battle"].get() == "关闭")
                choose(root, ui.daily_task_controls["battle"], 0)
                ui.settings.allow_stamina_spend = False
                ui._form_changed()
                root.update()
                check(f"{scale}_task_choices_cannot_grant_stamina", not ui.tasks["battle"].get()
                      and ui.daily_task_controls["battle"].instate(("disabled",)))
                ui.settings.allow_stamina_spend = True
                ui.tasks["battle"].set(True)
                ui._show_daily_tasks("daily")
                root.update()
                check(f"{scale}_synthesis_beside_daily_rewards", ui.synthesis_control.winfo_ismapped())
                ui._set_busy(True)
                root.update()
                check(f"{scale}_all_daily_choices_lock_during_work", all(control.instate(("disabled",))
                      for control in (*ui.daily_task_controls.values(), ui.synthesis_control)))
                ui._set_busy(False)
                root.update()
                check(f"{scale}_all_daily_choices_restore_readonly", all(control.instate(("readonly",))
                      for control in ui.daily_task_controls.values()))
                ui._show_page("home")
                ui._show_weekly_plan()
                root.update()
                check(f"{scale}_selected_secondary_category", ui.settings_buttons["weekly"].cget("style") == "Settings.Selected.Nav.TButton")
                check(f"{scale}_settings_shares_guide", ui.settings_shell.winfo_ismapped()
                      and ui.guide.winfo_ismapped() and ui.header.winfo_ismapped()
                      and ui.header.plan.winfo_ismapped() and ui.guide.selected_page == "settings")
                check(f"{scale}_initial_draft_unchanged", not ui.dirty and not ui.weekly_enabled.get())
                choose(root, ui.weekly_enabled_combo, 0)
                check(f"{scale}_enable_by_value_and_keyboard", ui.weekly_enabled.get() and ui.dirty and "未加入" not in ui.weekly_status.get())
                choose(root, ui.weekly_day_combo, 2)
                check(f"{scale}_day_selects_wednesday", ui.weekly_day.get() == "周三")
                ui.weekly_enabled.set(False)
                check(f"{scale}_external_boolean_updates_display", ui.weekly_enabled_combo.get() == "关闭")
                choose(root, ui.weekly_enabled_combo, 0)
                choose(root, ui.weekly_mode_combo, 1)
                check(f"{scale}_currency_shows_limit_and_hides_du_team", all(not control.winfo_ismapped() for control in ui.weekly_run_controls)
                      and ui.weekly_runs_combo.winfo_ismapped() and ui.weekly_runs_row.caption.cget('text')=='对局上限'
                      and '开发流程' in ui.weekly_boundary.get())
                check(f"{scale}_hidden_fields_not_keyboard_targets", str(root.tk.call("tk_focusNext", ui.weekly_time_entry)) not in
                      (str(ui.weekly_team_entry),))
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
                      and root.focus_get() == ui.table and ui.start_button.winfo_ismapped()
                      and ui.start_button.cget("text") == "开始计划")
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
                check(f"{scale}_weekly_returns_to_origin", ui.active_page == "differential_universe"
                      and ui.action_page == "differential_universe")
                ui._show_page("home")
                ui._show_weekly_plan()
                root.update()
                ui.settings_buttons["weekly"].focus_force()
                ui.settings_buttons["weekly"].event_generate("<KeyPress-Right>")
                root.update()
                check(f"{scale}_category_keyboard_moves_and_focuses", ui.settings_tabs.select() == str(ui.settings_sections["run"])
                      and root.focus_get() == ui.settings_buttons["run"])
                previous_photo = ui.header._photo
                root.withdraw()
                root.update()
                ui.stamina.set("120")
                ui.elapsed_seconds = 65
                ui._clock()
                root.update()
                check(f"{scale}_hidden_surface_does_not_repaint", ui.header._photo is previous_photo)
                root.deiconify()
                root.update()
                check(f"{scale}_restored_surface_has_current_cost_and_time", ui.header._photo is not previous_photo
                      and "已用开拓力  120" in drawn_text(ui.header) and "01:05" in drawn_text(ui.header))
                ui.stamina.set("—")
                ui.elapsed_seconds = 0
                ui._clock()
                ui.settings_buttons["run"].invoke()
                root.update()
                for section, control, variable, name in (("run", ui.overlay_control, ui.overlay_logs, "subtitle"),
                                                ("daily", ui.synthesis_control, ui.daily_synthesis, "synthesis")):
                    ui.settings_buttons[section].invoke()
                    root.update()
                    choose(root, control, 1)
                    check(f"{scale}_{name}_turns_off", not variable.get())
                    choose(root, control, 0)
                    check(f"{scale}_{name}_turns_on", variable.get())
                ui._set_busy(True)
                root.update()
                for section, control, variable in (("run", ui.overlay_control, ui.overlay_logs),
                        ("daily", ui.synthesis_control, ui.daily_synthesis), ("weekly", ui.weekly_enabled_combo, ui.weekly_enabled)):
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
                        primary = ui.start_button
                        if name == "tools":
                            label, _, enabled = ui.tools_shelf.primary_action()
                            action_ok = (primary.winfo_ismapped() and primary.cget("text") == label
                                         and primary.instate(("!disabled",)) == enabled)
                        else:
                            action_ok = not primary.winfo_ismapped() and primary.instate(("disabled",))
                        check(f"{scale}_{size}_{name}_reachable", ui.settings_tabs.select() == str(ui.settings_sections[name])
                              and action_ok and ui.guide.winfo_ismapped()
                              and ui.settings_shell.back.winfo_ismapped())
                        if scale == 1.5:
                            ImageGrab.grab(window=root.winfo_id()).save(OUT/(name+"-"+size+".png"))
                    ui.settings_shell.choose('power')
                    root.update()
                    canvas = ui.settings_shell.canvas
                    canvas.yview_moveto(0)
                    root.update()
                    initial = canvas.yview()
                    click(ui.power_mode_combo)
                    root.update()
                    pop = str(root.tk.call("ttk::combobox::PopdownWindow", ui.power_mode_combo))
                    check(f'{scale}_{size}_dropdown_keeps_form_position',
                          root.tk.call("winfo", "ismapped", pop) and canvas.yview() == initial)
                    root.tk.call("ttk::combobox::Unpost", ui.power_mode_combo)
                    root.update()
                    canvas.event_generate('<MouseWheel>', delta=-120)
                    root.update()
                    check(f'{scale}_{size}_long_form_scrolls_under_fixed_navigation',
                          canvas.yview()[0] > initial[0] and ui.settings_shell.back.winfo_ismapped())
                    ui.echo_config_button.focus_force()
                    root.update()
                    check(f'{scale}_{size}_focus_reveals_last_control',
                          ui.echo_config_button.winfo_rooty()+ui.echo_config_button.winfo_height()
                          <= canvas.winfo_rooty()+canvas.winfo_height())
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
