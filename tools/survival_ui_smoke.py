"""Exercise actual list gestures, draft isolation and collapsed-field recovery."""
import hashlib
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
from autohsr.dungeon_ui import select_mission, show_advanced, show_manual
from autohsr.dungeons import CATEGORIES, Dungeon, load_catalogue
from autohsr.survival_widgets import artwork, group_metadata, display_group

OUT = ROOT/"runs/survival-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def thumb_fraction(slider):
        y = slider.winfo_height()//2
        positions = [x for x in range(slider.winfo_width()) if slider.identify(x, y).endswith("slider")]
        assert positions, "The challenge slider thumb must be visible"
        return (min(positions)+max(positions))/2/slider.winfo_width()
    catalogue = load_catalogue(ROOT/"assets/dungeons.json")
    entries = json.loads((ROOT/"assets/ui/survival/sources.json").read_text("utf-8"))["assets"]
    check("all_104_catalogue_rows_have_exact_artwork_keys", len(entries) == len(catalogue) == 104 and
          {(m.category, m.name, m.location) for m in catalogue} == set(artwork()))
    check("artwork_hashes_match", all(hashlib.sha256((ROOT/"assets/ui/survival"/e["file"]).read_bytes()).hexdigest() == e["sha256"] for e in entries))
    groups, members = group_metadata()
    check("21_observed_headings_cover_64_grouped_missions", len(groups) == 21 and len(members) == 64 and
          set(members) == {(m.category, m.name, m.location) for m in catalogue if m.category in ("calyx_golden", "calyx_crimson", "stagnant_shadow")})
    check("heading_icons_match_source_manifest", all(hashlib.sha256((ROOT/"assets/ui/survival"/g["file"]).read_bytes()).hexdigest() == g["sha256"] for g in groups.values()))
    fake = types.ModuleType("autohsr.app")
    def reject(*args, **kwargs):
        raise AssertionError("A catalogue interaction must not start a game backend")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings(battle=False).save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                ui._show_page("tasks")
                root.update()
                check(f"{scale}_initial_excluded_count_matches_editable_slider", ui.challenge_count.get() == "24"
                      and ui.challenge_scale.get() == 24 and not ui.challenge_scale.instate(("disabled",)))
                check(f"{scale}_initial_excluded_thumb_matches_maximum", thumb_fraction(ui.challenge_scale) > .9)
                ui.battle_checkbox.invoke()
                root.update()
                check(f"{scale}_first_join_preserves_count_and_thumb", ui.tasks["battle"].get()
                      and ui.challenge_count.get() == "24" and ui.challenge_scale.get() == 24
                      and thumb_fraction(ui.challenge_scale) > .9)
                ui._show_page("home")
                ui._show_task_setup("battle")
                root.focus_force()
                root.update()
                check(f"{scale}_return_preserves_count_and_thumb", ui.challenge_scale.get() == 24
                      and thumb_fraction(ui.challenge_scale) > .9)
                board = ui.dungeon_list
                initial = ui._form_signature()
                original_mission = next(m for m in board.rows if board.matches(m))
                original_count = ui.challenge_count.get()
                ui.battle_checkbox.invoke()
                root.update()
                inactive = ui._form_signature()
                check(f"{scale}_unjoined_dungeon_can_be_browsed", not ui.tasks["battle"].get() and not board.locked
                      and all(str(w.cget("state")) != "disabled" for w in ui.dungeon_browse_controls)
                      and not ui.challenge_entry.instate(("disabled",)))
                check(f"{scale}_unjoined_dungeon_has_no_active_cost", ui.battle_cost.get() == "本次不刷本"
                      and ui.dungeon_target_caption.get().startswith("未加入")
                      and all(board.action_label(m) == "加入计划" for m in board.rows))
                for category in CATEGORIES:
                    ui.category_buttons[category.label].invoke()
                    root.update()
                    check(f"{scale}_{category.key}_unjoined_browse_keeps_draft", ui._form_signature() == inactive
                          and all(m.category == category.key for m in board.rows))
                ui.category_buttons["拟造花萼（金）"].invoke()
                ui.dungeon_search.set("回忆")
                root.update()
                board.focus_force()
                board.event_generate("<Home>")
                board.event_generate("<Down>")
                root.update()
                check(f"{scale}_unjoined_search_and_keys_do_not_join", len(board.rows) == 5
                      and ui._form_signature() == inactive)
                board.yview("moveto", str(50/board.total_height))
                root.update()
                partial = next(i for i, box in board.hitboxes.items() if 10 < box[3]-box[1] < board.ROW_HEIGHT-2)
                mission = board.rows[partial]
                box = board.hitboxes[partial]
                board.event_generate("<Button-1>", x=round((box[2]-55)*ui.ui_scale), y=round((box[1]+box[3])/2*ui.ui_scale))
                root.update()
                check(f"{scale}_unjoined_partial_row_reveals_before_join", ui._form_signature() == inactive
                      and board.row_bounds(partial)[0] >= board.offset-1
                      and board.row_bounds(partial)[1] <= board.offset+board.winfo_height()/ui.ui_scale+1)
                if scale == 1.25:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"unjoined-browser.png")
                box = board.hitboxes[partial]
                board.event_generate("<Button-1>", x=round((box[2]-55)*ui.ui_scale), y=round((box[1]+box[3])/2*ui.ui_scale))
                root.update()
                check(f"{scale}_one_click_joins_exact_target", ui.tasks["battle"].get()
                      and board.matches(mission) and board.action_label(mission) == "已选"
                      and not ui.challenge_entry.instate(("disabled",)) and not ui.busy
                      and config.read_bytes() == original)
                ui.battle_checkbox.invoke()
                root.update()
                snapshot = ui._read_settings(operation="plan")
                check(f"{scale}_removal_excludes_battle_from_run_snapshot", snapshot is not None and not snapshot.battle
                      and ui.target_location.get() == mission.location and ui.battle_cost.get() == "本次不刷本")
                ui.category_buttons["历战余响"].invoke()
                root.update()
                board.focus_force()
                board.event_generate("<Home>")
                root.update()
                mission = board.rows[board.cursor]
                board.event_generate("<Return>")
                root.update()
                snapshot = ui._read_settings(operation="plan")
                check(f"{scale}_keyboard_join_applies_exact_category_and_limit", snapshot is not None and snapshot.battle
                      and board.matches(mission) and ui.challenge_count.get() == "3"
                      and "90" in ui.battle_cost.get() and "90" in ui.daily_caption.get())
                ui.battle_checkbox.invoke()
                ui.battle_checkbox.invoke()
                root.update()
                check(f"{scale}_checkbox_rejoin_preserves_target", board.matches(mission)
                      and ui.tasks["battle"].get() and ui.challenge_count.get() == "3")
                ui.battle_checkbox.invoke()
                root.update()
                inactive = ui._form_signature()
                ui._set_busy(True)
                board.event_generate("<Return>")
                select_mission(ui, original_mission)
                ui.category_buttons["拟造花萼（金）"].invoke()
                root.update()
                check(f"{scale}_busy_unjoined_dungeon_stays_excluded", ui._form_signature() == inactive
                      and board.locked and board.action_label(mission) == "未加入")
                ui._set_busy(False)
                ui.settings.allow_stamina_spend = False
                ui._form_changed()
                root.update()
                before = ui._form_signature()
                board.event_generate("<Return>")
                select_mission(ui, original_mission)
                ui.battle_checkbox.invoke()
                root.update()
                check(f"{scale}_unauthorized_browser_cannot_join", ui._form_signature() == before and board.locked
                      and board.action_label(mission) == "未授权"
                      and all(str(w.cget("state")) == "disabled" for w in ui.dungeon_browse_controls)
                      and ui.battle_checkbox.instate(("disabled",)))
                ui.settings.allow_stamina_spend = True
                ui._form_changed()
                select_mission(ui, original_mission)
                ui.challenge_count.set(original_count)
                ui.dungeon_list.reveal_selection()
                root.update()
                check(f"{scale}_join_checks_leave_original_plan_intact", ui._form_signature() == initial
                      and config.read_bytes() == original)
                current = next(i for i, m in enumerate(board.rows) if board.matches(m))
                top, bottom = board.row_bounds(current)
                check(f"{scale}_current_target_is_fully_visible", top >= board.offset-1 and
                      bottom <= board.offset+board.winfo_height()/ui.ui_scale+1)
                check(f"{scale}_only_dungeon_toggle_remains_in_browser", set(ui.task_controls) == {"battle"} and ui.battle_checkbox.winfo_ismapped())
                default = root.geometry()
                signature = ui._form_signature()
                for category in CATEGORIES:
                    ui.category_buttons[category.label].invoke()
                    root.update()
                    check(f"{scale}_{category.key}_browse_only", ui._form_signature() == signature and
                          all(m.category == category.key for m in board.rows))
                ui.category_buttons["拟造花萼（金）"].invoke()
                ui.dungeon_search.set("匹诺康尼")
                root.update()
                check(f"{scale}_planet_search_finds_three_distinct_missions", len(board.rows) == 3 and
                      len({m.name for m in board.rows}) == 3 and all(display_group(m)["label"] == "匹诺康尼" for m in board.rows)
                      and ui._form_signature() == signature)
                board.yview("moveto", "0")
                root.update()
                header = next(iter(board.header_hitboxes.values()))
                board.event_generate("<Button-1>", x=round(90*ui.ui_scale), y=round((header[1]+header[3])/2*ui.ui_scale))
                root.update()
                check(f"{scale}_heading_is_not_a_mission_action", ui._form_signature() == signature)
                ui.dungeon_search.set("")
                root.update()
                board.yview("moveto", str(50/board.total_height))
                root.update()
                partial = next((i for i, box in board.hitboxes.items() if 10 < box[3]-box[1] < board.ROW_HEIGHT-2), None)
                check(f"{scale}_partial_row_fixture", partial is not None)
                box = board.hitboxes[partial]
                board.event_generate("<Button-1>", x=round(140*ui.ui_scale), y=round((box[1]+box[3])/2*ui.ui_scale))
                root.update()
                check(f"{scale}_partial_row_first_click_reveals_without_selecting", ui._form_signature() == signature and
                      board.row_bounds(partial)[0] >= board.offset-1 and board.row_bounds(partial)[1] <= board.offset+board.winfo_height()/ui.ui_scale+1)
                extra = Dungeon("calyx_golden", "回忆之蕾", "本地新增地点")
                ui.dungeon_catalogue.append(extra)
                ui.dungeon_search.set(extra.location)
                root.update()
                check(f"{scale}_unverified_group_does_not_inherit_from_same_name", board.rows == [extra]
                      and board.headers[0][1]["label"] == "其他副本" and ui._form_signature() == signature)
                ui.dungeon_catalogue.remove(extra)
                ui.dungeon_search.set("回忆")
                root.update()
                check(f"{scale}_duplicate_names_keep_locations", len(board.rows) == 5 and len({m.location for m in board.rows}) == 5
                      and ui._form_signature() == signature)
                board.focus_force()
                board.event_generate("<Home>")
                root.update()
                before = ui._form_signature()
                board.event_generate("<Down>")
                root.update()
                check(f"{scale}_keyboard_navigation_is_not_selection", ui._form_signature() == before)
                chosen = board.rows[board.cursor]
                board.event_generate("<Return>")
                root.update()
                check(f"{scale}_enter_selects_exact_location", ui.target_name.get() == chosen.name and
                      ui.target_location.get() == chosen.location and config.read_bytes() == original and not ui.busy)
                ui.dungeon_search.set("不存在的地点")
                root.update()
                check(f"{scale}_empty_search_keeps_target", not board.rows and ui.target_location.get() == chosen.location)
                ui.dungeon_search_entry.focus_force()
                ui.dungeon_search_entry.event_generate("<Escape>")
                root.update()
                before = ui._form_signature()
                board.event_generate("<MouseWheel>", delta=-120)
                root.update()
                check(f"{scale}_scroll_does_not_change_plan", ui._form_signature() == before)
                ui.category_buttons["历战余响"].invoke()
                root.update()
                index = next(i for i, box in board.hitboxes.items() if box[3]-box[1] >= board.ROW_HEIGHT-1)
                mission = board.rows[index]
                x1,y1,x2,y2 = board.hitboxes[index]
                board.event_generate("<Button-1>", x=round((x2-50)*ui.ui_scale), y=round((y1+y2)/2*ui.ui_scale))
                root.update()
                check(f"{scale}_one_click_selects_and_applies_category_limit", ui.dungeon_category.get() == "历战余响"
                      and ui.target_name.get() == mission.name and int(ui.challenge_count.get()) <= 3 and "3" in ui.battle_cost.get())
                ui.category_buttons["饰品提取"].invoke()
                board.choose(0)
                root.update()
                check(f"{scale}_ungrouped_categories_keep_plain_rows", not board.headers and board.total_height == len(board.rows)*board.ROW_HEIGHT)
                check(f"{scale}_planar_cost_retains_existing_immersifiers", "已有沉浸器优先" in ui.battle_cost.get()
                      and "最多" in ui.battle_cost.get() and "余量使用开拓力" in ui.battle_hint.get())
                before = ui._form_signature()
                ui._set_busy(True)
                board.event_generate("<End>")
                board.event_generate("<Return>")
                board.event_generate("<Button-1>", x=round((x2-50)*ui.ui_scale), y=round((y1+y2)/2*ui.ui_scale))
                ui.category_buttons["拟造花萼（金）"].invoke()
                root.update()
                check(f"{scale}_busy_gestures_cannot_change_target", ui._form_signature() == before)
                ui._set_busy(False)
                show_advanced(ui)
                ui.category_buttons["历战余响"].invoke()
                root.update()
                check(f"{scale}_category_returns_from_editor_to_list", not ui.dungeon_advanced_visible and ui.dungeon_browser.winfo_ismapped())
                ui.target_name.set("新增副本")
                ui.target_location.set("新增地点")
                show_manual(ui)
                root.update()
                check(f"{scale}_custom_target_is_preserved", ui.dungeon_name_combo.get() == "新增副本"
                      and ui.dungeon_location_combo.get() == "新增地点" and not any(board.matches(m) for m in board.rows))
                show_manual(ui, False)
                ui.target_location.set("")
                ui._show_page("home")
                check(f"{scale}_missing_location_rejected", ui._read_settings(operation="plan") is None)
                root.update()
                check(f"{scale}_error_reveals_manual_field", ui.dungeon_manual_visible and root.focus_get() == ui.dungeon_location_combo
                      and ui.start_button.cget("text") == "开始计划")
                ui.target_location.set("新增地点")
                ui.stamina_limit.set("abc")
                ui._show_page("home")
                check(f"{scale}_bad_budget_rejected", ui._read_settings(operation="plan") is None)
                root.update()
                check(f"{scale}_error_reveals_budget", ui.dungeon_advanced_visible and root.focus_get() == ui.stamina_limit_entry)
                ui.stamina_limit.set("240")
                for size in ("default", "minimum"):
                    root.geometry(default if size == "default" else "%dx%d" % root.minsize())
                    for manual, advanced in ((False, False), (False, True), (True, False)):
                        show_manual(ui, manual)
                        show_advanced(ui, advanced)
                        root.update()
                        check_layout(root)
                        check(f"{scale}_{size}_{manual}_{advanced}_layout", ui.start_button.winfo_ismapped())
                show_advanced(ui, False)
                show_manual(ui, False)
                ui.category_buttons["凝滞虚影"].invoke()
                ui.dungeon_search.set("")
                root.geometry(default)
                root.update()
                board.yview("moveto", "0")
                board.choose(0)
                root.update()
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"survival-index.png")
                check(f"{scale}_config_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    if str(root.tk.call("after", "info", token)[0]).endswith("_drain"):
                        root.after_cancel(token)
                root.destroy()
    result = dict(game_started=False, checks=checks, count=len(checks), artwork_rows=len(entries), heading_icons=len(groups), dpi=[100,125,150,200])
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
