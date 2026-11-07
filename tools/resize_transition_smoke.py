"""Offline checks at the moment a resized UI replaces its previous controls."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import types
import traceback
from unittest.mock import patch
import sys

from ux_smoke import ROOT, Settings, Window, module
from autohsr.desktop_scale import _widgets
from autohsr.game_widgets import Surface
from PIL import ImageGrab


def main():
    checks, timings = [], []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Transition checks cannot start a game backend")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    out = ROOT/"runs/resize-transition-ui"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for dpi in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", dpi*96/72)
            errors = []
            def callback_error(kind, value, tb):
                errors.append(repr(value))
                traceback.print_exception(kind, value, tb)
            root.report_callback_exception = callback_error
            ui = Window(root, config)
            try:
                root.update()
                root.focus_force()
                normal = root.geometry()
                def text_sizes():
                    # Measure the font used by Tk, without making a fresh Font
                    # object that would hide stale font-cache scaling.
                    fonts = (ui.style.lookup("Accent.TButton", "font"),
                             ui.weekly_time_entry.cget("font"), ui.log.cget("font"))
                    return [int(root.tk.call("font", "measure", font, "开始计划"))/ui.ui_scale for font in fonts]
                normal_text = text_sizes()
                def font_width(widget):
                    font = widget.cget("font") if "font" in widget.keys() else None
                    font = font or ui.style.lookup(str(widget.cget("style")) or widget.winfo_class(), "font")
                    return int(root.tk.call("font", "measure", font, "开始计划"))
                for view, name, maximized in ((view, name, zoom) for view in ("home", "settings")
                        for name, zoom in (("maximize", True), ("restore", False))):
                    if name == "maximize":
                        ui._show_daily_tasks("mail") if view == "settings" else ui._show_page("home")
                        root.update()
                    prefix = f"{dpi}_{view}_{name}_"
                    in_settings = view == "settings"
                    old_shell, old_start = ui.shell, ui.start_button
                    old_action = ui.settings_shell.back if in_settings else old_start
                    old_paints = []
                    presenters = {}
                    for _, widget in _widgets(old_shell):
                        if isinstance(widget, Surface):
                            present = widget._present
                            presenters[widget] = present
                            def track_present(image, widget=widget, present=present, paints=old_paints):
                                paints.append(type(widget).__name__)
                                return present(image)
                            widget._present = track_present
                    old_metrics = old_action.winfo_reqwidth(), old_action.winfo_reqheight(), font_width(old_action)
                    captions = [w for _, w in _widgets(old_shell) if w.winfo_class() == "TLabel"
                                and w.winfo_ismapped()]
                    caption_fonts = [(w, font_width(w)) for w in captions]
                    photos = tuple(str(photo) for photo in root._hsr_images)
                    retire = ui.responsive_layout._retire_view
                    replaced = []
                    def inspect_swap(parked_view):
                        check(prefix+"old_action_stays_mapped", old_shell.winfo_ismapped() and old_action.winfo_ismapped())
                        check(prefix+"old_action_is_complete", old_action.winfo_width() >= old_action.winfo_reqwidth()
                              and old_action.winfo_height() >= old_action.winfo_reqheight())
                        check(prefix+"displayed_native_metrics_stay_unchanged", old_metrics ==
                              (old_action.winfo_reqwidth(), old_action.winfo_reqheight(), font_width(old_action))
                              and all(font_width(widget) == width for widget, width in caption_fonts))
                        check(prefix+"old_theme_pixels_survive", all(root.tk.call("image", "type", photo) == "photo" for photo in photos))
                        check(prefix+"old_shell_remains_on_top", root.winfo_children()[-1] is old_shell)
                        content_ready = (ui.settings_shell.canvas.winfo_ismapped()
                                         and all(c.winfo_ismapped() for c in ui.daily_task_controls.values())
                                         if in_settings else ui.table._photo is not None)
                        new_action = ui.settings_shell.back if in_settings else ui.start_button
                        check(prefix+"replacement_is_ready", ui.shell is not old_shell and new_action.winfo_ismapped()
                              and ui.guide._photo is not None and content_ready)
                        if in_settings:
                            check(prefix+"both_settings_layouts_hide_run_action",
                                  all(not button.winfo_ismapped() and button.instate(("disabled",))
                                      for button in (old_start, ui.start_button)))
                        if dpi == 1.5:
                            ImageGrab.grab(window=root.winfo_id()).save(out/(view+"-"+name+"-before-swap.png"))
                        replaced.append(True)
                        retire(parked_view)
                    ui.responsive_layout._retire_view = inspect_swap
                    started = time.perf_counter()
                    root.state("zoomed" if maximized else "normal")
                    if not maximized:
                        root.geometry(normal)
                    deadline = time.monotonic()+8
                    while not replaced and time.monotonic() < deadline:
                        root.update()
                    root.update()
                    ui.responsive_layout._retire_view = retire
                    for widget, present in presenters.items():
                        widget._present = present
                    timings.append(dict(dpi=dpi, action=name, elapsed_ms=round((time.perf_counter()-started)*1000, 2)))
                    check(prefix+"automatic_resize_completed", bool(replaced) and not errors)
                    check(prefix+"previous_artwork_is_not_repainted", not old_paints)
                    check(prefix+"one_previous_layout_is_parked", old_shell.winfo_exists() and not old_shell.winfo_ismapped()
                          and len(root.winfo_children()) == 2
                          and [w for w in root.winfo_children() if w.winfo_ismapped()] == [ui.shell])
                    check(prefix+"native_button_entry_and_log_text_scale", all(abs(a-b) < 2 for a, b in zip(normal_text, text_sizes())))
                    if in_settings:
                        check(prefix+"settings_edit_focus_survives_swap",
                              root.focus_get() is ui.daily_task_controls["mail"])
                ui.settings_shell.back.invoke()
                root.update()
                check(f"{dpi}_settings_return_restores_home_action_and_focus", ui.active_page == "home"
                      and root.focus_get() is ui.table and ui.start_button.winfo_ismapped()
                      and ui.start_button.instate(("!disabled",)) and ui.start_button.cget("text") == "开始计划")
                check(f"{dpi}_no_config_write", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    result = dict(count=len(checks), checks=checks, timings=timings, game_started=False)
    (out/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
