"""Keep excluded dungeon preferences across explicit save and reopening."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from autohsr.dungeon_ui import select_mission, set_count, show_advanced

OUT = ROOT / "runs/plan-preferences-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    def draft(ui):
        return (ui.tasks["battle"].get(), ui.dungeon_category.get(), ui.target_name.get(),
                ui.target_location.get(), ui.challenge_count.get(), ui.stamina_limit.get(),
                ui.use_support.get())

    def close(ui):
        ui.closing = True
        for token in ui.root.tk.splitlist(ui.root.tk.call("after", "info")):
            if str(ui.root.tk.call("after", "info", token)[0]).endswith("_drain"):
                ui.root.after_cancel(token)
        ui.root.destroy()

    def open_window(config, scale):
        root = tk.Tk()
        root.tk.call("tk", "scaling", scale * 96 / 72)
        root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
        return Window(root, config)

    fake = types.ModuleType("autohsr.app")

    def reject(*args, **kwargs):
        raise AssertionError("Saving preferences must not start a game backend")

    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        for scale in (1., 1.25, 1.5, 2.):
            config = Path(folder) / (str(scale) + ".json")
            Settings().save(config)
            original = config.read_bytes()
            ui = open_window(config, scale)
            try:
                ui._show_page("tasks")
                mission = next(m for m in ui.dungeon_catalogue if m.category == "cavern")
                select_mission(ui, mission)
                ui.challenge_count.set("3")
                ui.stamina_limit.set("120")
                ui.use_support.set(False)
                ui.battle_checkbox.invoke()
                ui.root.update()
                expected = (False, "侵蚀隧洞", mission.name, mission.location, "3", "120", False)
                check(f"{scale}_excluded_preferences_remain_editable", draft(ui) == expected
                      and all(str(w.cget("state")) != "disabled" for w in ui.stamina_controls))
                for operation in ("plan", "reward_only", "check", "launch"):
                    snapshot = ui._read_settings(operation=operation)
                    check(f"{scale}_{operation}_does_not_save_or_replace_draft", snapshot is not None
                          and (operation not in ("plan", "reward_only") or not snapshot.battle)
                          and draft(ui) == expected and config.read_bytes() == original)
                ui.save_button.invoke()
                ui.root.update()
                saved = Settings.load(config)
                check(f"{scale}_explicit_save_keeps_excluded_target_and_budget", not saved.battle
                      and (saved.dungeon_category, saved.target_name, saved.target_location,
                           saved.challenge_count, saved.stamina_limit, saved.use_support)
                      == ("cavern", mission.name, mission.location, 3, 120, False)
                      and draft(ui) == expected and not ui.dirty)
            finally:
                close(ui)

            ui = open_window(config, scale)
            try:
                ui._show_page("tasks")
                ui.root.update()
                saved_bytes = config.read_bytes()
                check(f"{scale}_reopening_keeps_choices_without_enabling_task", draft(ui) == expected
                      and ui.battle_cost.get() == "本次不刷本" and ui.challenge_scale.get() == 3
                      and not ui.dirty)
                ui._set_busy(True)
                set_count(ui, 1)
                ui._preset(40, 1)
                ui.save_button.invoke()
                check(f"{scale}_running_plan_blocks_editing_and_save", draft(ui) == expected
                      and config.read_bytes() == saved_bytes
                      and all(str(w.cget("state")) == "disabled" for w in ui.stamina_controls))
                ui._set_busy(False)
                for value, message in (("abc", "整数"), ("0", "挑战次数"), ("4", "超过")):
                    ui.challenge_count.set(value)
                    ui._show_page("home")
                    ui.save_button.invoke()
                    ui.root.update()
                    check(f"{scale}_invalid_excluded_count_{value}_is_correctable", ui.input_error_field == "challenge_count"
                          and message in ui.input_error.get() and ui.root.focus_get() == ui.challenge_entry
                          and not ui.challenge_entry.instate(("disabled",))
                          and not ui.tasks["battle"].get() and config.read_bytes() == saved_bytes)
                    if scale == 1.25 and value == "abc":
                        ImageGrab.grab(window=ui.root.winfo_id()).save(OUT / "excluded-count-error.png")
                    ui.challenge_entry.delete(0, "end")
                    ui.challenge_entry.insert(0, "3")
                ui.stamina_limit.set("123")
                ui._show_page("home")
                ui.save_button.invoke()
                ui.root.update()
                check(f"{scale}_invalid_excluded_budget_opens_editable_field", ui.input_error_field == "stamina_limit"
                      and ui.dungeon_advanced_visible and ui.root.focus_get() == ui.stamina_limit_entry
                      and not ui.stamina_limit_entry.instate(("disabled",))
                      and config.read_bytes() == saved_bytes and not ui.tasks["battle"].get())
                ui.stamina_limit_entry.delete(0, "end")
                ui.stamina_limit_entry.insert(0, "120")
                ui._preset(40, 1)
                ui.root.update()
                check(f"{scale}_preset_edits_preferences_without_joining_or_saving", not ui.tasks["battle"].get()
                      and ui.challenge_count.get() == "1" and ui.stamina_limit.get() == "40"
                      and ui.battle_cost.get() == "本次不刷本" and config.read_bytes() == saved_bytes)
                ui.save_button.invoke()
                check(f"{scale}_corrected_preferences_save_without_enabling_task", not ui.input_error.get()
                      and not ui.dirty and not Settings.load(config).battle
                      and Settings.load(config).challenge_count == 1)
                show_advanced(ui, False)
                ui.battle_checkbox.invoke()
                ui.root.update()
                snapshot = ui._read_settings(operation="plan")
                check(f"{scale}_rejoining_uses_saved_target_and_current_budget", snapshot is not None and snapshot.battle
                      and snapshot.target_name == mission.name and snapshot.target_location == mission.location
                      and snapshot.challenge_count == 1 and snapshot.stamina_limit == 40
                      and not Settings.load(config).battle)
                ui.settings.allow_stamina_spend = False
                ui._form_changed()
                before = draft(ui)
                set_count(ui, 2)
                ui._preset(240, 6)
                select_mission(ui, mission)
                ui.battle_checkbox.invoke()
                check(f"{scale}_no_authorization_keeps_controls_and_join_locked", draft(ui) == before
                      and not ui.tasks["battle"].get()
                      and all(str(w.cget("state")) == "disabled" for w in ui.stamina_controls))
            finally:
                close(ui)
    result = dict(game_started=False, count=len(checks), checks=checks, dpi=[100, 125, 150, 200])
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(dict(game_started=False, count=len(checks))))


if __name__ == "__main__":
    main()
