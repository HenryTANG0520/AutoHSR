"""Check home hierarchy and card navigation without accessing a game."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from ux_smoke import ROOT, Settings, Window, module, pump
from autohsr.desktop_daily import MAIL, BATTLEPASS

OUT = ROOT / "runs/task-board-navigation"


def click(board, box):
    x1, y1, x2, y2 = box
    x, y = round((x1+x2)/2*board.scale), round((y1+y2)/2*board.scale)
    board.event_generate("<Button-1>", x=x, y=y)
    board.event_generate("<ButtonRelease-1>", x=x, y=y)


def main():
    checks = 0
    for scale in (1., 1.25, 1.5, 2.):
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
                    ui.start_button.invoke()
                    root.update()
                    assert ui.active_page == "tasks" and not ui.busy and ui.dungeon_home_return
                    assert ui.start_button.cget("text") == "返回每日"
                    # Selecting the first displayed mission confirms target and location.
                    ui.dungeon_list.choose(0)
                    root.update()
                    assert ui.active_page == "home" and not ui.busy and not ui._battle_setup_needed()
                    assert ui.target_location.get() and ui.dirty and config.read_bytes() == saved
                    assert ui.start_button.cget("text") == "开始计划"
                    checks += 12

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
                    checks += 9

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
                    checks += 8
                finally:
                    root.destroy()

    result = dict(checks=checks, scales=[100, 125, 150, 200], game_started=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
