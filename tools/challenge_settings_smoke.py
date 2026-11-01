"""Exercise in-place challenge settings, focus, Escape and preserved plan drafts."""
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

OUT = ROOT / "runs/challenge-settings-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    def fill(control, value):
        control.delete(0, "end")
        control.insert(0, value)

    def draft(ui):
        return (ui.tasks["battle"].get(), ui.dungeon_category.get(), ui.target_name.get(),
                ui.target_location.get(), ui.challenge_count.get(), ui.stamina_limit.get(), ui.use_support.get())

    fake = types.ModuleType("autohsr.app")
    def reject(*args, **kwargs):
        raise AssertionError("Editing challenge settings must not access the game")
    fake.Runner = fake.launch_game = fake.inspect_game = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings(battle=False).save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, tb: (_ for _ in ()).throw(value.with_traceback(tb))
            ui = Window(root, config)
            try:
                ui._show_page("tasks")
                root.focus_force()
                root.update()
                normal = root.geometry()
                before = draft(ui)
                ui.dungeon_advanced_button.invoke()
                root.update()
                check(f"{scale}_settings_open_beside_list_and_select_budget", ui.dungeon_browser.winfo_ismapped()
                      and ui.dungeon_advanced_fields.winfo_ismapped() and root.focus_get() is ui.stamina_limit_entry
                      and ui.stamina_limit_entry.selection_present() and draft(ui) == before)
                check(f"{scale}_excluded_task_uses_existing_status_without_extra_warning", not ui.battle_hint.get()
                      and not ui.dungeon_hint_label.winfo_ismapped() and ui.battle_cost.get() == "本次不刷本")
                fill(ui.stamina_limit_entry, "120")
                ui.dungeon_support_control.invoke()
                ui.category_buttons["侵蚀隧洞"].invoke()
                root.update()
                check(f"{scale}_browsing_preserves_open_settings_and_draft_options", ui.dungeon_advanced_visible
                      and ui.dungeon_browser.winfo_ismapped() and ui.stamina_limit.get() == "120" and not ui.use_support.get()
                      and ui.target_name.get() == before[2] and not ui.tasks["battle"].get())
                board = ui.dungeon_list
                index, box = next((i, b) for i, b in board.hitboxes.items() if b[3]-b[1] >= board.ROW_HEIGHT-1)
                mission = board.rows[index]
                board.event_generate("<Button-1>", x=round((box[2]-50)*ui.ui_scale), y=round((box[1]+box[3])/2*ui.ui_scale))
                fill(ui.challenge_entry, "3")
                root.update()
                snapshot = ui._read_settings(operation="plan")
                check(f"{scale}_selection_and_options_form_one_plan_without_saving", snapshot is not None and snapshot.battle
                      and snapshot.target_name == mission.name and snapshot.target_location == mission.location
                      and snapshot.challenge_count == 3 and snapshot.stamina_limit == 120 and not snapshot.use_support
                      and ui.dungeon_advanced_visible and config.read_bytes() == original)
                check(f"{scale}_required_support_and_cost_feedback_remains_visible", ui.dungeon_hint_label.winfo_ismapped()
                      and "支援已关闭" in ui.battle_hint.get() and "120" in ui.battle_cost.get())
                expected = draft(ui)
                ui.dungeon_search.set(mission.name)
                ui.dungeon_search_entry.focus_force()
                root.update()
                ui.dungeon_search_entry.event_generate("<Escape>")
                root.update()
                check(f"{scale}_first_escape_only_clears_search", not ui.dungeon_search.get() and ui.dungeon_advanced_visible
                      and root.focus_get() is ui.dungeon_search_entry and draft(ui) == expected)
                ui.dungeon_search_entry.event_generate("<Escape>")
                root.update()
                check(f"{scale}_next_escape_collapses_settings_and_returns_focus", not ui.dungeon_advanced_visible
                      and ui.dungeon_browser.winfo_ismapped() and root.focus_get() is ui.dungeon_advanced_button
                      and draft(ui) == expected)
                ui.dungeon_manual_button.invoke()
                root.update()
                check(f"{scale}_manual_entry_keeps_catalogue_read_explicit", ui.dungeon_manual_visible
                      and ui.dungeon_catalogue_button.winfo_ismapped() and root.focus_get() is ui.dungeon_name_combo)
                commands = []
                with patch.object(ui, "_start", side_effect=lambda **kwargs: commands.append(kwargs)):
                    ui.dungeon_catalogue_button.invoke()
                check(f"{scale}_catalogue_button_dispatches_only_catalogue", commands == [dict(catalogue=True)])
                combo = ui.dungeon_category_combo
                combo.focus_force()
                root.update()
                combo.event_generate("<Down>")
                root.update()
                popdown = str(root.tk.call("ttk::combobox::PopdownWindow", str(combo)))
                check(f"{scale}_category_dropdown_open", bool(root.tk.call("winfo", "ismapped", popdown)))
                root.tk.call("event", "generate", popdown+".f.l", "<Escape>")
                root.update()
                check(f"{scale}_dropdown_owns_first_escape", ui.dungeon_manual_visible
                      and not bool(root.tk.call("winfo", "ismapped", popdown)) and draft(ui) == expected)
                combo.event_generate("<Escape>")
                root.update()
                check(f"{scale}_manual_escape_returns_to_visible_entry", not ui.dungeon_manual_visible
                      and ui.dungeon_browser.winfo_ismapped() and root.focus_get() is ui.dungeon_manual_button)
                ui.stamina_limit.set("123")
                check(f"{scale}_invalid_budget_is_rejected", ui._read_settings(operation="plan") is None)
                root.update()
                check(f"{scale}_budget_error_keeps_target_context", ui.dungeon_advanced_visible
                      and ui.dungeon_browser.winfo_ismapped() and root.focus_get() is ui.stamina_limit_entry
                      and ui.input_error_field == "stamina_limit" and config.read_bytes() == original)
                fill(ui.stamina_limit_entry, "120")
                root.update()
                for size in ("minimum", "maximized", "restored", "maximized_again", "restored_again"):
                    if size.startswith("maximized"):
                        root.state("zoomed")
                    else:
                        root.state("normal")
                        root.geometry("%dx%d" % root.minsize() if size == "minimum" else normal)
                    root.update()
                    ui.responsive_layout.fit()
                    root.update()
                    check_layout(root)
                    check(f"{scale}_{size}_settings_list_and_plan_stay_visible", ui.dungeon_browser.winfo_ismapped()
                          and ui.dungeon_advanced_fields.winfo_ismapped() and ui.start_button.winfo_ismapped()
                          and any(b[3]-b[1] >= ui.dungeon_list.ROW_HEIGHT-1 for b in ui.dungeon_list.hitboxes.values())
                          and draft(ui) == expected and not ui.input_error.get())
                if scale == 1.25:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"inline-settings.png")
                ui.stamina_limit_entry.focus_force()
                ui._set_busy(True)
                root.update()
                ui.stamina_limit_entry.event_generate("<Escape>")
                root.update()
                check(f"{scale}_running_escape_moves_focus_to_enabled_navigation", ui.busy and not ui.dungeon_advanced_visible
                      and root.focus_get() is ui.nav_buttons["tasks"] and draft(ui) == expected
                      and ui.stamina_limit_entry.instate(("disabled",)))
                ui._set_busy(False)
                check(f"{scale}_configuration_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    if str(root.tk.call("after", "info", token)[0]).endswith("_drain"):
                        root.after_cancel(token)
                root.destroy()
    result = dict(count=len(checks), checks=checks, game_started=False, dpi=[100,125,150,200])
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
