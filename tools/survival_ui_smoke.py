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
from autohsr.dungeon_ui import show_advanced, show_manual
from autohsr.dungeons import CATEGORIES, load_catalogue
from autohsr.survival_widgets import artwork

OUT = ROOT/"runs/survival-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    catalogue = load_catalogue(ROOT/"assets/dungeons.json")
    entries = json.loads((ROOT/"assets/ui/survival/sources.json").read_text("utf-8"))["assets"]
    check("all_104_catalogue_rows_have_exact_artwork_keys", len(entries) == len(catalogue) == 104 and
          {(m.category, m.name, m.location) for m in catalogue} == set(artwork()))
    check("artwork_hashes_match", all(hashlib.sha256((ROOT/"assets/ui/survival"/e["file"]).read_bytes()).hexdigest() == e["sha256"] for e in entries))
    fake = types.ModuleType("autohsr.app")
    def reject(*args, **kwargs):
        raise AssertionError("A catalogue interaction must not start a game backend")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                ui._show_task_setup("battle")
                root.focus_force()
                root.update()
                board = ui.dungeon_list
                current = next(i for i, m in enumerate(board.rows) if board.matches(m))
                check(f"{scale}_current_target_is_fully_visible", current*board.ROW_HEIGHT >= board.offset-1 and
                      (current+1)*board.ROW_HEIGHT <= board.offset+board.winfo_height()/ui.ui_scale+1)
                default = root.geometry()
                signature = ui._form_signature()
                for category in CATEGORIES:
                    ui.category_buttons[category.label].invoke()
                    root.update()
                    check(f"{scale}_{category.key}_browse_only", ui._form_signature() == signature and
                          all(m.category == category.key for m in board.rows))
                ui.category_buttons["拟造花萼（金）"].invoke()
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
    result = dict(game_started=False, checks=checks, count=len(checks), artwork_rows=len(entries), dpi=[100,150,200])
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
