"""Check home hierarchy and card navigation without accessing a game."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from ux_smoke import ROOT, Settings, Window, module, pump
from home_feedback_smoke import drawn_text
from autohsr.desktop_daily import MAIL, BATTLEPASS

OUT = ROOT / "runs/task-board-navigation"


def click(board, box):
    x1, y1, x2, y2 = box
    x, y = round((x1+x2)/2*board.scale), round((y1+y2)/2*board.scale)
    board.event_generate("<Button-1>", x=x, y=y)
    board.event_generate("<ButtonRelease-1>", x=x, y=y)


def main():
    checks = 0
    selection_checks = []
    for scale in (1., 1.25, 1.5, 2.):
        def check_selection(name, condition):
            assert condition, (scale, name)
            selection_checks.append(f"{scale:g}_{name}")

        with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)):
            local = Path(folder)
            config = local / "fresh.json"
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale * 96 / 72)
            root.report_callback_exception = lambda _, error, trace: (_ for _ in ()).throw(error.with_traceback(trace))
            with patch("autohsr.app.Runner", side_effect=AssertionError("game backend is forbidden")):
                ui = Window(root, config)
                try:
                    root.geometry("%dx%d" % root.minsize())
                    root.update()
                    board = ui.table
                    assert board.card_keys == ("battle", "daily", "weekly")
                    assert "mail" in board.records and "battlepass" in board.records
                    assert all(not ui.daily_entry_buttons[key].winfo_ismapped() for key in (MAIL, BATTLEPASS))
                    assert not ui.reward_button.winfo_ismapped()
                    assert ui.start_button.cget("text") == "开始计划"
                    assert board.action_label("battle") == "选择副本"
                    assert "副本待配置" in ui.daily_caption.get()
                    assert ui._read_settings(save=True).target_location == ""
                    assert Settings.load(config).target_location == ""
                    saved = config.read_bytes()
                    plan = ui._form_signature()
                    root.focus_force()
                    ui.start_button.focus_set()
                    ui.start_button.invoke()
                    root.update()
                    assert ui.active_page == "tasks" and not ui.busy and ui.dungeon_home_return == "start"
                    assert ui.start_button.cget("text") == "返回每日"
                    assert root.focus_get() is ui.dungeon_list

                    def pending_selection():
                        return ("请从列表选择副本" in ui.dungeon_target_caption.get()
                                and ui.battle_cost.get() == "选定副本后显示预计费用"
                                and not ui.battle_checkbox.winfo_ismapped()
                                and not any(ui.dungeon_list.matches(row) for row in ui.dungeon_list.rows))

                    def open_dungeon_card():
                        board.selected = "battle"
                        board.focus_set()
                        root.update()
                        board.event_generate("<Return>")
                        root.update()

                    check_selection("start_opens_unselected_dungeon", pending_selection())
                    ui.dungeon_list.event_generate("<Escape>")
                    root.update()
                    assert ui.active_page == "home" and root.focus_get() is ui.start_button
                    assert ui._form_signature() == plan and config.read_bytes() == saved

                    open_dungeon_card()
                    check_selection("card_opens_unselected_dungeon", ui.dungeon_home_return == "card"
                                    and root.focus_get() is ui.dungeon_list and pending_selection())
                    ui.start_button.invoke()
                    root.update()
                    check_selection("card_cancel_restores_focus_and_draft", ui.active_page == "home"
                                    and root.focus_get() is board and ui._form_signature() == plan
                                    and config.read_bytes() == saved)

                    ui.start_button.invoke()
                    root.update()
                    dungeons = ui.dungeon_list
                    first, second = [row for row in dungeons.rows if row.name == ui.target_name.get()][:2]
                    dungeons.choose(dungeons.rows.index(second))
                    root.update()
                    assert ui.active_page == "home" and not ui.busy and not ui._battle_setup_needed()
                    assert ui.target_location.get() and ui.dirty and config.read_bytes() == saved
                    assert ui.start_button.cget("text") == "开始计划"
                    assert root.focus_get() is ui.start_button
                    check_selection("start_choice_uses_exact_same_name_row", ui.target_name.get() == second.name
                                    and ui.target_location.get() == second.location and first.location != second.location)
                    checks += 16

                    open_dungeon_card()
                    check_selection("valid_choice_and_estimate_visible_on_reopen", ui.dungeon_home_return == "card"
                                    and ui.dungeon_target_caption.get() == f"已选 · {second.name} · {second.location}"
                                    and ui.battle_checkbox.winfo_ismapped() and ui.battle_checkbox.instate(("selected",))
                                    and dungeons.matches(second) and not dungeons.matches(first)
                                    and "24 次" in ui.battle_cost.get() and "预计 240 开拓力" in ui.battle_cost.get())
                    ui.challenge_count.set("2")
                    dungeons.choose(dungeons.rows.index(first))
                    root.update()
                    check_selection("card_choice_updates_location_and_restores_focus", ui.active_page == "home"
                                    and root.focus_get() is board and not ui.busy
                                    and ui.dungeon_target_caption.get() == f"已选 · {first.name} · {first.location}"
                                    and "2 次" in ui.battle_cost.get() and "预计 20 开拓力" in ui.battle_cost.get()
                                    and config.read_bytes() == saved)

                    board.selected = "daily"
                    board.activate()
                    root.update()
                    assert ui.active_page == "settings"
                    assert ui.daily_entry_buttons[MAIL].winfo_ismapped()
                    ui.daily_entry_buttons[MAIL].invoke()
                    assert ui.daily_section == MAIL and not ui.busy
                    ui.daily_back_button.invoke()
                    assert ui.active_page == "settings" and ui.daily_section is None
                    ui._leave_settings()
                    root.update()
                    assert ui.active_page == "home"
                    board.move(10)
                    pump(root, lambda: board._slide_job is None)
                    board.activate()
                    root.update()
                    assert ui.active_page == "settings"
                    assert ui.settings_tabs.select() == str(ui.settings_sections["weekly"])
                    ui._leave_settings()
                    root.update()
                    assert ui.active_page == "home" and board.selection() == ("weekly",)
                    ui._set_busy(True, True)
                    board.activate()
                    root.update()
                    assert ui.active_page == "home" and ui.stop_button.winfo_ismapped()
                    ui._set_busy(False)
                    with patch.object(ui, "_weekly_currency_recovery", {"resume": False}):
                        board.redraw()
                        assert "待核对" in drawn_text(board)
                    board.redraw()
                    checks += 10

                    plan = ui._form_signature()
                    for keys in ((), ("battle",), ("battle", "daily"), ("battle", "daily", "weekly"),
                                 ("battle", "daily", "weekly", "mail"),
                                 ("battle", "daily", "weekly", "mail", "battlepass")):
                        count = len(keys)
                        board.card_keys = keys
                        board.offset = 0
                        board.selection_remove()
                        board._cancel_slide()
                        root.update()
                        if not count:
                            board.activate()
                        board.move(50)
                        pump(root, lambda: board._slide_job is None)
                        assert board.offset == max(0, count-board.visible_count)
                        assert board.selection() == ((keys[-1],) if keys else ())
                        assert (keys[-1] in board.hitboxes) if keys else not board.hitboxes
                        board.move(-50)
                        pump(root, lambda: board._slide_job is None)
                        assert board.offset == 0
                        checks += 4
                    assert "next" in board.hitboxes
                    click(board, board.hitboxes["next"])
                    assert board._slide_job is not None
                    root.update_idletasks()
                    click(board, board.hitboxes["previous"])
                    pump(root, lambda: board._slide_job is None)
                    assert board.offset == 0 and ui.active_page == "home"
                    click(board, board.hitboxes["next"])
                    pump(root, lambda: board._slide_job is None)
                    assert board.offset == 1
                    board.event_generate("<MouseWheel>", delta=120)
                    pump(root, lambda: board._slide_job is None)
                    assert board.offset == 0
                    board.event_generate("<Button-1>", x=round(150*scale), y=round(50*scale))
                    board.event_generate("<ButtonRelease-1>", x=round(80*scale), y=round(50*scale))
                    assert board._slide_job is not None and board.offset == 1
                    root.focus_force()
                    board.focus_set()
                    board.event_generate("<Escape>")
                    assert board._slide_job is None and board._position == board.offset
                    board.scroll(1)
                    assert board._slide_job is not None
                    ui._show_page("logs")
                    root.update()
                    assert board._slide_job is None and board._position == board.offset
                    assert plan == ui._form_signature() and config.read_bytes() == saved
                    checks += 9
                finally:
                    root.destroy()

    result = dict(checks=checks + len(selection_checks), selection_checks=selection_checks,
                  scales=[100, 125, 150, 200], game_started=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
