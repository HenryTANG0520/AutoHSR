"""Offline guide layout, keyboard access and evidence-state checks at three DPIs."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autohsr import windows  # Establish DPI awareness before Tk; no game access.
from autohsr.config import Settings
from autohsr.gui import AutoHSRWindow
from autohsr import theme
from PIL import ImageGrab

OUT = Path(__file__).resolve().parents[1] / "runs" / "ui-layout"


def check_layout(widget):
    for child in widget.winfo_children():
        if not child.winfo_ismapped():
            continue
        x, y, w, h = child.winfo_x(), child.winfo_y(), child.winfo_width(), child.winfo_height()
        bounds = (str(child), child.winfo_class(), (x, y, w, h), (widget.winfo_width(), widget.winfo_height()))
        assert x >= -2 and y >= -2, ("negative position", bounds)
        assert x+w <= widget.winfo_width()+2, ("outside parent width", bounds)
        assert y+h <= widget.winfo_height()+2, ("outside parent height", bounds)
        if child.winfo_class() in ("TLabel", "TButton", "TCheckbutton", "TEntry", "TCombobox", "TSpinbox"):
            assert w >= child.winfo_reqwidth(), ("text clipped horizontally", bounds, child.winfo_reqwidth())
            assert h >= child.winfo_reqheight(), ("text clipped vertically", bounds, child.winfo_reqheight())
        check_layout(child)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases, interactions = [], []
    with tempfile.TemporaryDirectory() as folder:
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            def callback_error(kind, value, traceback):
                raise value.with_traceback(traceback)
            root.report_callback_exception = callback_error
            ui = AutoHSRWindow(root, config)
            try:
                assert theme.FONT == "SDK_SC_Web", "The bundled reference font was not registered"
                root.update()
                default_geometry = root.geometry()
                for size in ("default", "minimum"):
                    if size == "minimum":
                        root.geometry("%dx%d" % root.minsize())
                    for page in ui.pages:
                        ui._show_page(page)
                        root.update()
                        selections = [None]
                        notebook = None
                        if page == "settings":
                            notebook = ui.settings_tabs
                            selections = list(ui.settings_sections.values())
                        elif page == "currency_wars":
                            notebook = ui.currency_tabs
                            selections = list(ui.currency_sections.values())
                        for index, selection in enumerate(selections):
                            if notebook:
                                notebook.select(selection)
                            root.update()
                            try:
                                check_layout(root)
                            except AssertionError as exc:
                                raise AssertionError((scale, size, page, index, exc.args)) from exc
                            cases.append(dict(dpi=round(scale*100), size=size, page=page, section=index))
                        if size == "default" and scale == 1.5:
                            if notebook:
                                notebook.select(0)
                            root.update()
                            ImageGrab.grab(window=root.winfo_id()).save(OUT/(page+".png"))
                for size in ("default", "minimum"):
                    root.geometry(default_geometry if size == "default" else "%dx%d" % root.minsize())
                    ui._show_page("home")
                    ui.active_operation = "plan"
                    ui.runner = object()  # No backend or input method is available.
                    ui._set_busy(True, True)
                    ui._plan_daily_result(dict(status="success", daily_verified=True, stamina_spent=240,
                        battle_completed=6, battle_requested=6, results=[dict(task="battle", status="ok", detail="模拟结果")]))
                    ui._universe_progress(dict(requested_runs=2, completed_runs=1))
                    for paused in (False, True):
                        ui._pause_state(paused)
                        ui._restore()
                        root.update()
                        check_layout(root)
                        cases.append(dict(dpi=round(scale*100), size=size, page="home", state="paused" if paused else "running"))
                        if scale == 1.5 and size == "default":
                            ImageGrab.grab(window=root.winfo_id()).save(OUT/("paused.png" if paused else "running.png"))
                    ui.runner = None
                    ui._set_busy(False)
                ui._has_run = False
                ui._daily_result_signature = None
                ui.active_operation = "daily"
                ui.training_result.set("unknown")
                ui._refresh_controls()
                ui._show_page("home")
                root.update()
                assert not ui.training_meter.verified
                ui.table.selected = "battle"
                ui.table.activate()
                assert ui.active_page == "tasks"
                ui.category_buttons["历战余响"].invoke()
                ui.dungeon_list.choose(0)
                assert int(ui.challenge_count.get()) <= 3
                assert "3" in ui.battle_cost.get()
                ui.busy = True
                ui._refresh_controls()
                ui.category_buttons["拟造花萼（金）"].invoke()
                assert ui.dungeon_category.get() == "历战余响"
                ui.busy = False
                ui._refresh_controls()
                ui._show_page("currency_wars")
                ui._show_page("home")
                ui.guide.buttons["universe"].invoke()
                assert ui.active_page == "currency_wars"
                ui._show_page("home")
                interactions.append("task_setup_category_limits_locks_and_universe_return")
                ui._has_run = True
                ui._finish(dict(status="partial", daily_verified=True, results=[dict(task="mail", status="partial", detail="入口未识别")]))
                root.update()
                assert ui.training_meter.verified and ui.table.item("mail", "values")[1] == "部分完成"
                interactions.append("verified_daily_survives_optional_failure")
                ui._finish(dict(operation="currency_wars", status="partial", results=[]))
                assert ui.training_meter.verified
                interactions.append("unrelated_operation_does_not_clear_daily_proof")
                ui._show_page("differential_universe")
                expected = ui.start_button.cget("text")
                for page in ("logs", "settings"):
                    ui._show_page(page)
                    assert ui.start_button.cget("text") == expected
                    assert str(ui.reward_button.cget("state")) == "disabled"
                interactions.append("records_and_settings_preserve_operation")
                ui._show_page("home")
                board = ui.table
                for key in ui.tasks:
                    board.item(key, values=(key, "部分完成", "完整的详细结果："+key), has_result=True)
                board.move(9)
                root.update()
                assert board.selection() == ("battlepass",) and "battlepass" in board.hitboxes
                summary = ui.summary.get()
                board.activate()
                assert ui.summary.get() == summary
                root.update()
                assert ui.summary_dialog.winfo_exists()
                from tkinter.scrolledtext import ScrolledText
                def text_widgets(widget):
                    for child in widget.winfo_children():
                        if isinstance(child, ScrolledText):
                            yield child
                        yield from text_widgets(child)
                assert any("完整的详细结果：battlepass" in text.get("1.0", "end") for text in text_widgets(ui.summary_dialog))
                ui.summary_dialog.destroy()
                board.move(-9)
                root.update()
                assert board.selection() == ("assignments",) and "assignments" in board.hitboxes
                interactions.append("all_five_cards_and_full_details_reachable")
                # Long reports remain in scrollable outputs, leaving controls reachable.
                ui.du_observation.set("长结果\n"*200)
                ui.currency_observation.set("长结果\n"*200)
                ui.summary.set("明确的错误原因与费用说明\n"*200)
                for page in ("differential_universe", "currency_wars"):
                    ui._show_page(page)
                    root.update()
                    check_layout(root)
                assert config.read_bytes() == original
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    result = dict(game_started=False, config_unchanged=True, reference_font_loaded=True, layout_cases=len(cases), dpi=[100, 150, 200], interactions=interactions)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
