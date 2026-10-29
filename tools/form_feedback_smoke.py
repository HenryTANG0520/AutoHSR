"""Exercise native control bindings and concise DU results without a game backend."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import sys
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from autohsr.desktop_modes import show_mode_view

OUT = ROOT/"runs/form-feedback-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def click(widget, x, y):
        widget.event_generate("<ButtonPress-1>", x=x, y=y)
        widget.event_generate("<ButtonRelease-1>", x=x, y=y)
    def part(widget, suffix):
        for y in range(widget.winfo_height()):
            for x in range(0, widget.winfo_width(), 2):
                if widget.identify(x, y).endswith(suffix):
                    return x, y
        raise AssertionError((widget, suffix))

    fake = types.ModuleType("autohsr.app")
    def reject_runner(*args, **kwargs):
        raise AssertionError("No game backend")
    fake.Runner = reject_runner
    with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"autohsr.app": fake}), patch.object(module, "ROOT", Path(folder)):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                ui._show_page("tasks")
                ui.tasks["battle"].set(False)
                root.update()
                checkbox = ui.battle_checkbox
                click(checkbox, *part(checkbox, "indicator"))
                root.update()
                check(f"{scale}_indicator_changes_value", ui.tasks["battle"].get())
                click(checkbox, checkbox.winfo_width()-5, checkbox.winfo_height()//2)
                root.update()
                check(f"{scale}_label_changes_same_value", not ui.tasks["battle"].get())
                checkbox.focus_force()
                checkbox.event_generate("<KeyPress-space>")
                checkbox.event_generate("<KeyRelease-space>")
                root.update()
                check(f"{scale}_keyboard_toggle", ui.tasks["battle"].get())
                ui.challenge_count.set("2")
                spin = ui.challenge_entry
                click(spin, *part(spin, "uparrow"))
                check(f"{scale}_spin_up", ui.challenge_count.get() == "3")
                click(spin, *part(spin, "downarrow"))
                check(f"{scale}_spin_down", ui.challenge_count.get() == "2")
                slider = ui.challenge_scale
                root.update()
                x, y = part(slider, "slider")
                slider.event_generate("<ButtonPress-1>", x=x, y=y)
                slider.event_generate("<B1-Motion>", x=slider.winfo_width()//2, y=y)
                slider.event_generate("<ButtonRelease-1>", x=slider.winfo_width()//2, y=y)
                check(f"{scale}_slider_drag", 10 <= int(ui.challenge_count.get()) <= 14)
                ui._set_busy(True)
                before = ui.tasks["mail"].get(), ui.challenge_count.get()
                click(checkbox, *part(checkbox, "indicator"))
                click(spin, *part(spin, "uparrow"))
                check(f"{scale}_disabled_does_not_edit", before == (ui.tasks["mail"].get(), ui.challenge_count.get()))
                ui._set_busy(False)
                ui._show_weekly_plan()
                ui.weekly_enabled.set(True)
                root.update()
                combo = ui.weekly_day_combo
                click(combo, *part(combo, "downarrow"))
                root.update()
                pop = str(root.tk.call("ttk::combobox::PopdownWindow", combo))
                check(f"{scale}_dropdown_opens", root.tk.call("winfo", "ismapped", pop))
                # Tk creates this listbox through Tcl, so it is not a Python Widget.
                listing = pop+".f.l"
                root.tk.call("event", "generate", listing, "<KeyPress-Down>")
                root.tk.call("event", "generate", listing, "<KeyPress-Return>")
                root.update()
                check(f"{scale}_dropdown_keyboard_select", ui.weekly_day.get() == "周二")
                ui.weekly_time_entry.focus_force()
                ui.weekly_time_entry.selection_range(0, "end")
                check(f"{scale}_entry_text_selection", ui.weekly_time_entry.selection_present())
                check_layout(root)
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"weekly-settings.png")
                ui._show_page("differential_universe")
                show_mode_view(ui, "differential_universe", "result")
                ui._finish(dict(operation="differential_universe", status="failed", report_saved=True,
                    error="拟合奖励页未返回", safe_next="核对当前奖励页面后再接续。",
                    differential_universe=dict(requested_runs=3, completed_runs=3, mode="周期演算",
                        page_history=[dict(ocr_text="raw-report-evidence")],
                        reward_collection=dict(status="failed", failure_reason="拟合奖励页未返回", claims=[]))))
                root.update()
                check(f"{scale}_result_preserves_completion_and_failure", "3/3" in ui.du_status.get()
                      and "领奖未完成" in ui.du_status.get() and "拟合奖励页未返回" in ui.du_result_text.get("1.0", "end"))
                check(f"{scale}_result_has_no_raw_payload", "page_history" not in ui.du_result_text.get("1.0", "end"))
                check_layout(root)
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"du-result.png")
                    ui._show_page("tasks")
                    root.update()
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"task-controls.png")
                ui._finish(dict(operation="daily", status="success", report_saved=True, results=[]))
                ui.du_record_button.invoke()
                root.update()
                detail = next(w for frame in ui.summary_dialog.winfo_children() for w in frame.winfo_children()
                              if w.winfo_class() == "Text")
                check(f"{scale}_detail_keeps_own_run", "raw-report-evidence" in detail.get("1.0", "end"))
                ui.summary_dialog.destroy()
                check(f"{scale}_config_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    script = str(root.tk.call("after", "info", token)[0])
                    if script.endswith("_drain"):
                        root.after_cancel(token)
                root.destroy()
    result = dict(game_started=False, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
