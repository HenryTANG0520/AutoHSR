"""Exercise detail placement, return focus and long content without game access."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import types
from unittest.mock import patch

from ux_smoke import ROOT, Settings, Window, module

OUT = ROOT/"runs/game-dialog-ui"


def content_widget(dialog):
    return next(w for frame in dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == "Text")


def close_button(dialog):
    return next(w for w in dialog.winfo_children() if isinstance(w,ttk.Button))


def center(widget):
    return widget.winfo_rootx()+widget.winfo_width()/2, widget.winfo_rooty()+widget.winfo_height()/2


def contained(widget):
    x,y = widget.winfo_rootx(),widget.winfo_rooty()
    right,bottom = x+widget.winfo_width(),y+widget.winfo_height()
    parent = widget.master
    while parent is not None:
        if not (x >= parent.winfo_rootx() and y >= parent.winfo_rooty()
                and right <= parent.winfo_rootx()+parent.winfo_width()+1
                and bottom <= parent.winfo_rooty()+parent.winfo_height()+1):
            return False
        # A transient Toplevel is owned by the root, not clipped by its client.
        if isinstance(parent,tk.Toplevel):
            break
        parent = parent.master
    return bool(widget.winfo_ismapped())


def in_work_area(dialog, area):
    side = dialog.winfo_rootx()-dialog.winfo_x()
    return (dialog.winfo_x() >= area[0] and dialog.winfo_y() >= area[1]
            and dialog.winfo_rootx()+dialog.winfo_width()+side <= area[2]
            and dialog.winfo_rooty()+dialog.winfo_height()+side <= area[3])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    def check(name, value):
        assert value, name
        checks.append(name)

    def reject(*args, **kwargs):
        raise AssertionError("Detail checks cannot start a game backend")

    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale * 96 / 72)
            root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
            ui = Window(root, config)
            try:
                root.update()
                root.focus_force()
                sizes = (root.geometry(), "1100x800")
                for size in sizes:
                    root.geometry(size)
                    root.update()
                    prefix = f"{scale}_{size}_"
                    ui._show_page("home")
                    ui.table.focus_set()
                    root.update()
                    detail = "10 开拓力待核对。\n" + "\n".join(f"核对记录 {n}" for n in range(80)) + "\n末尾记录保留。"
                    ui._show_summary(detail, title="日常副本挑战", return_focus=ui.table)
                    root.update()
                    check(prefix+"inside_book", ui.detail_view.master is ui.guide.content
                          and contained(ui.detail_text.frame) and not any(isinstance(w, tk.Toplevel) for w in root.winfo_children()))
                    check(prefix+"replaces_content_not_navigation", ui.active_page == "home"
                          and ui.detail_title.cget("text") == "日常副本挑战" and not ui.table.winfo_ismapped()
                          and not ui.footer_start_button.winfo_ismapped())
                    check(prefix+"readonly_and_scrollable", ui.detail_text.cget("state") == "disabled"
                          and ui.detail_text.get("1.0", "end-1c") == detail and ui.detail_text.yview()[1] < 1)
                    ui.detail_text.yview_moveto(1)
                    root.update()
                    check(prefix+"last_line_visible", ui.detail_text.yview()[1] == 1)
                    ui._show_summary("替换详情", return_focus=ui.detail_back)
                    root.update()
                    check(prefix+"reuses_existing_panel", ui.detail_text.get("1.0", "end-1c") == "替换详情")
                    ui.detail_text.event_generate("<Escape>")
                    root.update()
                    check(prefix+"escape_restores_original_focus", not ui.detail_view.winfo_ismapped()
                          and ui.table.winfo_ismapped() and root.focus_get() is ui.table)
                    ui._show_summary(detail, return_focus=ui.table)
                    root.update()
                    ui._show_page("logs")
                    root.update()
                    check(prefix+"changing_tab_dismisses_detail", ui.active_page == "logs" and not ui.detail_view.winfo_ismapped()
                          and not ui.footer_start_button.winfo_ismapped())
                    ui._show_inspection()
                    root.update()
                    check(prefix+"inspection_reuses_log_tab", ui.active_page == "logs"
                          and ui.output_tabs.select() == str(ui.inspection_text.frame.master)
                          and root.focus_get() is ui.inspection_text)
                    ui._show_page("home")
                    ui._set_busy(True, running=True)
                    ui._show_summary(detail, return_focus=ui.table)
                    root.update()
                    check(prefix+"retains_running_controls", ui.pause_button.winfo_ismapped()
                          and ui.stop_button.winfo_ismapped() and not ui.footer_start_button.winfo_ismapped())
                    ui.detail_back.invoke()
                    ui._set_busy(False)
                if scale == 1.:
                    ui._show_summary(detail, return_focus=ui.table)
                    root.update()
                    ui.detail_text.yview_moveto(1)
                    ui.detail_text.tag_add("sel", "3.0", "3.end")
                    root.state("zoomed")
                    root.update()
                    ui.responsive_layout.fit()
                    root.update()
                    check("resizing_preserves_open_detail_and_scroll",
                          ui.detail_view.winfo_ismapped() and ui.detail_text.yview()[1] == 1
                          and tuple(map(str, ui.detail_text.tag_ranges("sel"))) == ("3.0", ui.detail_text.index("3.end")))
                    ui.detail_back.invoke()
                    root.update()
                    check("resized_detail_restores_original_focus", root.focus_get() is ui.table)
                check(f"{scale}_config_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    if str(root.tk.call('after', 'info', token)[0]).endswith('_drain'):
                        root.after_cancel(token)
                root.destroy()
    check("no_callback_errors", not errors)
    result = dict(count=len(checks), checks=checks, game_started=False, config_unchanged=True)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
