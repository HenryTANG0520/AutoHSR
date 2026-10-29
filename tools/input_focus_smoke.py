"""Check that correction input reaches its visible field after rapid changes."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import call, patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from autohsr.config import SettingsError
from autohsr.desktop_dialogs import DetailClose

OUT = ROOT/"runs/input-focus-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, callback_errors = [], []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Input focus checks must not access the game")
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
                normal = root.geometry()
                root.focus_force()
                ui._show_page("tasks")
                root.update()
                ui.stamina_limit.set("abc")
                ui._read_settings(operation="plan")
                ui.stamina_limit.set("240")
                ui.dungeon_search_entry.focus_set()
                root.update()
                check(prefix+"correcting_before_idle_preserves_the_next_input", root.focus_get() is ui.dungeon_search_entry
                      and not ui.input_error.get() and ui.input_focus.pending is None)

                zoomed = False
                for cycle in range(2):
                    for field, value, attribute in (("stamina_limit", "abc", "stamina_limit_entry"),
                            ("battle_timeout", "50", "battle_timeout_entry"),
                            ("ocr_confidence", "2", "ocr_confidence_entry"),
                            ("weekly_time", "24:00", "weekly_time_entry")):
                        ui.weekly_enabled.set(True)
                        variable = getattr(ui, field)
                        before = variable.get()
                        ui._show_page("home")
                        root.update()
                        old_tabs = ui.settings_tabs
                        variable.set(value)
                        check(prefix+f"{cycle}_{field}_is_rejected", ui._read_settings(operation="plan") is None)
                        zoomed = not zoomed
                        root.state("zoomed" if zoomed else "normal")
                        if not zoomed:
                            root.geometry(normal)
                        # Exercise geometry mapping before normal queued events,
                        # which previously lost the target during replacement.
                        root.update_idletasks()
                        ui.responsive_layout.fit()
                        root.update()
                        target = getattr(ui, attribute)
                        if not (target.winfo_ismapped() and root.focus_get() is target and target.selection_present()):
                            print(json.dumps(dict(stage="resized_error", scale=scale, cycle=cycle, field=field,
                                focus=str(root.focus_get()), target=str(target), mapped=bool(target.winfo_ismapped()),
                                selected=bool(target.selection_present()), pending=ui.input_focus.pending,
                                page=ui.active_page, action_page=ui.action_page, action=ui.start_button.cget("text"),
                                callbacks=callback_errors),ensure_ascii=False),flush=True)
                        check(prefix+f"{cycle}_{field}_is_focused_after_resize", target.winfo_ismapped()
                              and root.focus_get() is target and target.selection_present()
                              and target.index("sel.first") == 0 and target.index("sel.last") == len(value)
                              and ui.action_page == "home" and ui.start_button.cget("text") == "开始计划")
                        old_tabs.event_generate("<<NotebookTabChanged>>")
                        root.update()
                        check(prefix+f"{cycle}_{field}_retired_notebook_cannot_change_current_section", not callback_errors
                              and root.focus_get() is target and (field == "stamina_limit" or
                                  ui.settings_tabs.select() == str(ui.settings_sections["weekly" if field == "weekly_time" else "recognition"])))
                        if scale == 1.25 and cycle == 0 and field == "battle_timeout":
                            ImageGrab.grab(window=root.winfo_id()).save(OUT/"resized-error.png")
                        root.focus_get().event_generate("<KeyPress>", keysym="1")
                        root.update()
                        check(prefix+f"{cycle}_{field}_typing_replaces_the_error_without_a_click", variable.get() == "1"
                              and not ui.input_error.get() and ui.input_focus.pending is None)
                        variable.set(before)

                ui._show_page("home")
                root.update()
                ui.battle_timeout.set("50")
                ui._read_settings(operation="plan")
                root.update_idletasks()
                ui._show_page("home")
                check(prefix+"leaving_cancels_a_request_waiting_for_mapping", ui.input_focus.pending is None)
                ui.start_button.focus_set()
                root.update()
                check(prefix+"leaving_the_error_page_drops_the_request", root.focus_get() is ui.start_button
                      and ui.active_page == "home" and ui.input_focus.pending is None)
                ui.battle_timeout.set("900")

                ui._input_failed(SettingsError("stamina_limit", "开拓力上限请填写整数。"))
                ui._input_failed(SettingsError("battle_timeout", "战斗超时应为60～3600。"))
                root.update()
                check(prefix+"newest_error_owns_the_focus", root.focus_get() is ui.battle_timeout_entry
                      and ui.input_focus.pending is None and ui.input_error_field == "battle_timeout")
                ui.ocr_confidence_entry.focus_force()
                ui.ocr_confidence_entry.selection_range(0, 1)
                ui.ocr_confidence_entry.icursor(1)
                root.update()
                root.state("zoomed")
                root.update_idletasks()
                ui.responsive_layout.fit()
                root.update()
                check(prefix+"handled_error_does_not_override_a_later_field_choice", root.focus_get() is ui.ocr_confidence_entry
                      and ui.ocr_confidence_entry.index("insert") == 1 and ui.ocr_confidence_entry.index("sel.last") == 1)

                ui._input_failed(SettingsError("battle_timeout", "战斗超时应为60～3600。"))
                ui._show_summary("保留当前输入后继续修改。", title="提示")
                root.update()
                dialog = ui.summary_dialog
                check(prefix+"detail_keeps_keyboard_ownership", root.focus_get().winfo_toplevel() is dialog)
                next(w for w in dialog.winfo_children() if isinstance(w, DetailClose)).invoke()
                root.update()
                ui._input_failed(SettingsError("battle_timeout", "战斗超时应为60～3600。"))
                ui._set_busy(True)
                check(prefix+"run_lock_cancels_focus_before_events_are_drained", ui.input_focus.pending is None)
                root.update()
                check(prefix+"running_state_drops_pending_field_focus", ui.input_focus.pending is None
                      and ui.battle_timeout_entry.instate(("disabled",)))
                ui._set_busy(False)
                ui._clear_input_error()
                ui._show_page("home")
                root.state("normal")
                root.geometry(normal)
                root.update_idletasks()
                ui.responsive_layout.fit()
                root.update()
                ui.weekly_mode.set("货币战争")
                ui.du_team.set("")
                ui.save_button.invoke()
                root.update()
                for zoomed in (True, False):
                    root.state("zoomed" if zoomed else "normal")
                    if not zoomed:
                        root.geometry(normal)
                    root.update_idletasks()
                    ui.responsive_layout.fit()
                    root.update()
                    check(prefix+f"plan_action_survives_team_error_resize_{zoomed}", ui.active_page == "differential_universe"
                          and ui.action_page == "home" and ui.start_button.cget("text") == "开始计划"
                          and root.focus_get() is ui.du_team_entry)
                ui.du_team.set("哈哈哈哈")
                with patch.object(ui, "_start") as start:
                    ui.start_button.invoke()
                    check(prefix+"corrected_primary_dispatches_original_plan", start.call_args_list == [call(run_plan=True)])
                ui._show_page("differential_universe")
                root.state("zoomed")
                root.update_idletasks()
                ui.responsive_layout.fit()
                root.update()
                check(prefix+"explicit_independent_action_is_also_preserved", ui.action_page == "differential_universe"
                      and "开始演算" in ui.start_button.cget("text"))
                with patch.object(ui, "_start") as start:
                    ui.start_button.invoke()
                    check(prefix+"independent_primary_dispatches_independent_mode", start.call_args_list == [call(differential_universe=True)])
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
