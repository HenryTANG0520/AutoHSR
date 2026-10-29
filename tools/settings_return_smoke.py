"""Settings return keeps the operation that brought the player to that page."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import call, patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from autohsr.desktop_modes import show_mode_view

OUT = ROOT/"runs/settings-return-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, callback_errors = [], []
    def check(name, condition):
        if not condition:
            from autohsr.theme import focus_widget
            diagnostic = dict(check=name,focus=str(focus_widget(root)),native_focus=str(root.tk.call('focus')),
                              page=ui.active_page,action=ui.action_page,return_page=ui.settings_return_page,
                              return_focus=str(ui.settings_return_focus),busy=ui.busy,
                              dungeon_state=str(ui.dungeon_list.cget('state')),geometry=root.geometry(),state=root.state())
            (OUT/(name+'-failure.json')).write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),'utf-8')
            ImageGrab.grab(window=root.winfo_id()).save(OUT/(name+'-failure.png'))
        assert condition, (name, callback_errors)
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Settings navigation must not access the game")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = fake.launch_game = fake.inspect_game = reject

    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            prefix = f"{scale}_"
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, tb: callback_errors.append(repr(value))
            ui = Window(root, config)
            try:
                root.update()
                root.focus_force()
                normal = root.geometry()
                ui.du_team.set("")
                ui._show_page("home")
                ui.save_button.invoke()
                root.update()
                check(prefix+"team_error_starts_from_plan", ui.active_page == "differential_universe"
                      and ui.action_page == "home" and root.focus_get() is ui.du_team_entry)
                draft = ui._form_signature()
                ui._show_page("settings")
                root.update()
                ui.settings_shell.choose("recognition")
                root.update()
                ui.settings_shell.back.event_generate("<Escape>")
                root.update()
                check(prefix+"escape_returns_to_original_plan_error", ui.active_page == "differential_universe"
                      and ui.action_page == "home" and ui.start_button.cget("text") == "开始计划"
                      and root.focus_get() is ui.du_team_entry and ui._form_signature() == draft)
                ui.du_team.set("哈哈哈哈")
                with patch.object(ui, "_start") as start:
                    ui.start_button.invoke()
                    check(prefix+"corrected_button_still_dispatches_plan", start.call_args_list == [call(run_plan=True)])

                ui.du_team_entry.selection_range(0, 2)
                ui.du_team_entry.icursor(2)
                ui.du_team_entry.focus_set()
                root.update()
                for zoomed in (True, False):
                    ui._show_page("settings")
                    root.update()
                    root.state("zoomed" if zoomed else "normal")
                    if not zoomed:
                        root.geometry(normal)
                    root.update_idletasks()
                    ui.responsive_layout.fit()
                    root.update()
                    check(prefix+f"{zoomed}_layout_keeps_return_operation", ui.settings_return_page == "differential_universe"
                          and ui.settings_return_action == "home")
                    ui.settings_shell.back.invoke()
                    root.update()
                    check(prefix+f"{zoomed}_return_keeps_operation_and_edit_selection", ui.action_page == "home"
                          and ui.start_button.cget("text") == "开始计划" and root.focus_get() is ui.du_team_entry
                          and ui.du_team_entry.index("insert") == 2 and ui.du_team_entry.index("sel.first") == 0
                          and ui.du_team_entry.index("sel.last") == 2)
                if scale == 1.25:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"returned-plan-editor.png")

                ui._show_page("differential_universe")
                show_mode_view(ui, "differential_universe", "editor")
                root.update()
                ui.du_team_entry.focus_set()
                root.update()
                ui._show_page("settings")
                root.update()
                ui.settings_shell.back.invoke()
                root.update()
                check(prefix+"independent_editor_remains_independent", ui.action_page == "differential_universe"
                      and "开始演算" in ui.start_button.cget("text") and root.focus_get() is ui.du_team_entry)
                with patch.object(ui, "_start") as start:
                    ui.start_button.invoke()
                    check(prefix+"independent_dispatch_is_preserved", start.call_args_list == [call(differential_universe=True)])

                ui._show_page("currency_wars")
                root.update()
                hero = ui.mode_decks["currency_wars"]["hero"]
                hero.primary.focus_set()
                root.update()
                ui._show_page("settings")
                root.update()
                with patch.object(ui, "_currency_wars") as identify:
                    ui.settings_shell.back.invoke()
                    root.update()
                    check(prefix+"currency_return_keeps_poster_and_readonly_action", ui.active_page == "currency_wars"
                          and ui.action_page == "currency_wars" and ui.mode_decks["currency_wars"]["shown"] == "hero"
                          and ui.start_button.cget("text") == "只读识别当前画面")
                    ui.start_button.invoke()
                    check(prefix+"currency_dispatch_remains_readonly", identify.call_args_list == [call()])

                ui._show_page("logs")
                root.update()
                ui.log.focus_set()
                root.update()
                ui._show_page("settings")
                root.update()
                ui.settings_shell.back.invoke()
                root.update()
                check(prefix+"logs_return_keeps_previous_operation_and_log_focus", ui.active_page == "logs"
                      and ui.action_page == "currency_wars" and root.focus_get() is ui.log
                      and ui.start_button.cget("text") == "只读识别当前画面")

                for section in ("daily", "weekly"):
                    ui._show_page("currency_wars")
                    ui._show_page("settings")
                    root.update()
                    ui.settings_shell.choose(section)
                    root.update()
                    check(prefix+section+"_shortcut_changes_return_to_daily_plan", ui.settings_return_page == "home"
                          and ui.settings_return_action == "home" and ui.action_page == "home")
                    ui.settings_shell.back.invoke()
                    root.update()
                    check(prefix+section+"_shortcut_returns_home_with_plan_action", ui.active_page == "home"
                          and ui.action_page == "home" and ui.start_button.cget("text") == "开始计划")

                ui._show_page("differential_universe")
                show_mode_view(ui, "differential_universe", "editor")
                root.update()
                ui.du_team_entry.focus_set()
                root.update()
                ui._show_page("settings")
                root.update()
                ui._set_busy(True)
                with patch.object(ui, "_stop") as stop:
                    ui.settings_shell.back.invoke()
                    root.update()
                    check(prefix+"running_return_uses_enabled_navigation", ui.busy and ui.du_team_entry.instate(("disabled",))
                          and root.focus_get() is ui.nav_buttons["differential_universe"]
                          and not root.focus_get().instate(("disabled",)) and not stop.called)
                ui._set_busy(False)
                ui._show_page("tasks")
                root.update()
                ui.dungeon_list.focus_set()
                root.update()
                ui._show_page("settings")
                root.update()
                ui._set_busy(True)
                ui.settings_shell.back.invoke()
                root.update()
                check(prefix+"running_return_skips_the_disabled_dungeon_list", ui.busy
                      and str(ui.dungeon_list.cget("state")) == "disabled"
                      and root.focus_get() is ui.nav_buttons["tasks"])
                ui._set_busy(False)
                ui._show_page("home")
                root.update()
                ui.table.focus_set()
                root.update()
                ui._show_page("settings")
                root.update()
                ui._set_busy(True)
                ui.settings_shell.back.invoke()
                root.update()
                check(prefix+"running_return_keeps_readable_task_cards_focusable", ui.busy and root.focus_get() is ui.table)
                ui._set_busy(False)
                check(prefix+"no_config_write_or_callback_error", config.read_bytes() == original and not callback_errors)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    if "_drain" in str(root.tk.call("after", "info", token)):
                        root.after_cancel(token)
                root.destroy()
    result = dict(count=len(checks), checks=checks, callback_errors=callback_errors, game_started=False)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
