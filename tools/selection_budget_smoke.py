"""Changing a dungeon should produce a usable plan within the existing ceiling."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from autohsr.dungeon_ui import select_mission, select_category, set_count, use_budget, show_advanced
from autohsr.dungeons import BY_KEY

OUT = ROOT/"runs/selection-budget-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Choosing a dungeon must not access the game")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = fake.launch_game = fake.inspect_game = reject

    def click_first(ui):
        board = ui.dungeon_list
        index, box = next((i,b) for i,b in board.hitboxes.items() if b[3]-b[1] >= board.ROW_HEIGHT-1)
        mission = board.rows[index]
        board.event_generate("<Button-1>", x=round((box[2]-50)*ui.ui_scale), y=round((box[1]+box[3])/2*ui.ui_scale))
        ui.root.update()
        return mission

    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings(stamina_limit=120, challenge_count=12).save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            prefix = f"{scale}_"
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, tb: (_ for _ in ()).throw(value.with_traceback(tb))
            ui = Window(root, config)
            try:
                ui._show_page("tasks")
                root.focus_force()
                root.update()
                for category, budget, count in (
                    ("calyx_golden",120,12), ("calyx_crimson",120,12), ("stagnant_shadow",120,4),
                    ("cavern",120,3), ("echo_of_war",120,3), ("planar",120,3),
                    ("stagnant_shadow",50,1), ("cavern",50,1), ("echo_of_war",50,1), ("planar",50,1),
                ):
                    ui.stamina_limit.set(str(budget))
                    ui.challenge_count.set("24")
                    before = ui._form_signature()
                    ui.category_buttons[BY_KEY[category].label].invoke()
                    root.update()
                    check(prefix+f"{category}_{budget}_browse_does_not_change_draft", ui._form_signature() == before)
                    mission = click_first(ui)
                    snapshot = ui._read_settings(operation="plan")
                    check(prefix+f"{category}_{budget}_one_click_makes_valid_plan", snapshot is not None
                          and snapshot.dungeon_category == category and snapshot.target_name == mission.name
                          and snapshot.target_location == mission.location and snapshot.challenge_count == count
                          and snapshot.stamina_limit == budget and ui.stamina_limit.get() == str(budget)
                          and int(float(ui.challenge_entry.cget("to"))) == count
                          and int(float(ui.challenge_scale.cget("to"))) == count and config.read_bytes() == original)
                ui.stamina_limit.set("120")
                ui.challenge_count.set("2")
                ui.category_buttons["侵蚀隧洞"].invoke()
                root.update()
                cavern = click_first(ui)
                check(prefix+"affordable_user_count_is_preserved", ui.challenge_count.get() == "2"
                      and "预计 80" in ui.battle_cost.get() and ui.stamina_limit.get() == "120")
                ui.challenge_scale.set(100)
                root.update()
                check(prefix+"slider_cannot_exceed_current_budget", ui.challenge_count.get() == "3"
                      and ui.challenge_scale.get() == 3 and ui.stamina_limit.get() == "120")
                plus = next(w for w in ui.challenge_entry.master.winfo_children()
                            if w.winfo_class() == "TButton" and w.cget("text") == "+")
                plus.invoke()
                ui.challenge_entry.focus_force()
                root.update()
                ui.challenge_entry.event_generate("<Up>")
                root.update()
                check(prefix+"plus_and_spinbox_arrows_stop_at_budget", ui.challenge_count.get() == "3"
                      and ui._read_settings(operation="plan").challenge_count == 3)
                ui.challenge_count.set("4")
                root.update()
                check(prefix+"manual_over_budget_draft_is_not_silently_rewritten", ui.challenge_count.get() == "4"
                      and ui._read_settings(operation="plan") is None and ui.input_error_field == "challenge_count"
                      and config.read_bytes() == original)
                select_mission(ui, cavern)
                root.update()
                check(prefix+"reselecting_repairs_count_and_clears_resolved_error", ui.challenge_count.get() == "3"
                      and not ui.input_error.get() and ui._read_settings(operation="plan") is not None)
                if scale == 1.25:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"affordable-selection.png")
                ui.stamina_limit.set("80")
                ui.challenge_count.set("8")
                ui.dungeon_category.set("侵蚀隧洞")
                select_category(ui)
                root.update()
                snapshot = ui._read_settings(operation="plan")
                check(prefix+"manual_category_choice_obeys_the_same_budget", snapshot is not None
                      and snapshot.challenge_count == 2 and snapshot.stamina_limit == 80
                      and ui.challenge_scale.get() == 2 and int(float(ui.challenge_entry.cget("to"))) == 2)

                ui.stamina_limit.set("10")
                gold = next(m for m in ui.dungeon_catalogue if m.category == "calyx_golden")
                select_mission(ui, gold)
                ui.tasks["battle"].set(False)
                ui.category_buttons["侵蚀隧洞"].invoke()
                show_advanced(ui, False)
                root.update()
                before = ui._form_signature()
                check(prefix+"unaffordable_choice_names_the_needed_action", ui.dungeon_list.action_label(cavern) == "调整上限")
                click_first(ui)
                check(prefix+"unaffordable_choice_keeps_original_plan_and_selects_budget", ui._form_signature() == before
                      and not ui.tasks["battle"].get() and ui.dungeon_browse_category.get() == "侵蚀隧洞"
                      and ui.input_error_field == "stamina_limit" and "40" in ui.input_error.get()
                      and "10" in ui.input_error.get() and ui.dungeon_advanced_visible
                      and root.focus_get() is ui.stamina_limit_entry and ui.stamina_limit_entry.selection_present())
                if scale == 1.25:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"budget-correction.png")
                ui.stamina_limit.set("40")
                root.update()
                check(prefix+"correction_restores_join_action", ui.dungeon_list.action_label(cavern) == "加入计划")
                board = ui.dungeon_list
                board.focus_force()
                board.cursor = 0
                root.update()
                board.event_generate("<Return>")
                root.update()
                snapshot = ui._read_settings(operation="plan")
                check(prefix+"keyboard_join_uses_corrected_budget", snapshot is not None and snapshot.battle
                      and snapshot.dungeon_category == "cavern" and snapshot.challenge_count == 1
                      and snapshot.stamina_limit == 40 and not ui.input_error.get())

                for value, fragment in (("", "整数"), ("abc", "整数"), ("25", "10～240"), ("250", "10～240"), ("0", "10～240")):
                    ui.stamina_limit.set(value)
                    root.update()
                    before = ui._form_signature()
                    click_first(ui)
                    selected = bool(ui.stamina_limit_entry.selection_present()) if value else ui.stamina_limit_entry.index("insert") == 0
                    if not (ui._form_signature() == before and root.focus_get() is ui.stamina_limit_entry
                            and selected and fragment in ui.summary_label.message()):
                        print(json.dumps(dict(stage="invalid_budget", value=value, same_draft=ui._form_signature()==before,
                            focus=str(root.focus_get()), expected=str(ui.stamina_limit_entry), selected=bool(ui.stamina_limit_entry.selection_present()),
                            message=ui.summary_label.message(), error=ui.input_error.get(), label=ui.dungeon_list.action_label(cavern)),ensure_ascii=False),flush=True)
                    check(prefix+f"invalid_budget_{value}_preserves_plan_and_focuses_reason", ui._form_signature() == before
                          and root.focus_get() is ui.stamina_limit_entry and selected
                          and fragment in ui.summary_label.message() and config.read_bytes() == original)
                ui.stamina_limit.set("abc")
                root.update()
                ui._clear_input_error()
                use_budget(ui)
                root.update()
                check(prefix+"fill_budget_also_reveals_its_input_error", ui.input_error_field == "stamina_limit"
                      and root.focus_get() is ui.stamina_limit_entry and "整数" in ui.summary_label.message())
                ui._clear_input_error()
                ui._set_busy(True)
                before = ui._form_signature()
                set_count(ui, 2)
                use_budget(ui)
                select_mission(ui, gold)
                check(prefix+"running_actions_cannot_edit_or_redirect", ui._form_signature() == before and not ui.input_error.get())
                ui._set_busy(False)
                ui.settings.allow_stamina_spend = False
                ui._form_changed()
                before = ui._form_signature()
                set_count(ui, 2)
                use_budget(ui)
                select_mission(ui, gold)
                check(prefix+"unapproved_actions_remain_locked", ui._form_signature() == before and not ui.input_error.get()
                      and ui.dungeon_list.action_label(cavern) == "未授权" and not ui.tasks["battle"].get())
                check(prefix+"configuration_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    if "_drain" in str(root.tk.call("after", "info", token)):
                        root.after_cancel(token)
                root.destroy()
    result = dict(count=len(checks), checks=checks, game_started=False, dpi=[100,125,150,200])
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
