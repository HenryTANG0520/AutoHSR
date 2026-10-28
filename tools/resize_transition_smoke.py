"""Offline checks at the moment a resized UI replaces its previous controls."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import types
from unittest.mock import patch
import sys

from ux_smoke import ROOT, Settings, Window, module


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
            root.report_callback_exception = lambda kind, value, tb: errors.append(repr(value))
            ui = Window(root, config)
            try:
                root.update()
                normal = root.geometry()
                def text_sizes():
                    # Measure the font used by Tk, without making a fresh Font
                    # object that would hide stale font-cache scaling.
                    fonts = (ui.style.lookup("Accent.TButton", "font"),
                             ui.weekly_time_entry.cget("font"), ui.log.cget("font"))
                    return [int(root.tk.call("font", "measure", font, "开始计划"))/ui.ui_scale for font in fonts]
                normal_text = text_sizes()
                for name, maximized in (("maximize", True), ("restore", False)):
                    prefix = f"{dpi}_{name}_"
                    old_shell, old_primary = ui.shell, ui.start_button
                    photos = tuple(str(photo) for photo in root._hsr_images)
                    destroy = old_shell.destroy
                    replaced = []
                    def inspect_swap():
                        check(prefix+"old_action_stays_mapped", old_shell.winfo_ismapped() and old_primary.winfo_ismapped())
                        check(prefix+"old_action_is_complete", old_primary.winfo_width() >= old_primary.winfo_reqwidth()
                              and old_primary.winfo_height() >= old_primary.winfo_reqheight())
                        check(prefix+"old_theme_pixels_survive", all(root.tk.call("image", "type", photo) == "photo" for photo in photos))
                        check(prefix+"old_shell_remains_on_top", root.winfo_children()[-1] is old_shell)
                        check(prefix+"replacement_is_ready", ui.shell is not old_shell and ui.start_button.winfo_ismapped()
                              and ui.guide._photo is not None and ui.table._photo is not None)
                        replaced.append(True)
                        destroy()
                    old_shell.destroy = inspect_swap
                    started = time.perf_counter()
                    root.state("zoomed" if maximized else "normal")
                    if not maximized:
                        root.geometry(normal)
                    deadline = time.monotonic()+8
                    while not replaced and time.monotonic() < deadline:
                        root.update()
                    root.update()
                    timings.append(dict(dpi=dpi, action=name, elapsed_ms=round((time.perf_counter()-started)*1000, 2)))
                    check(prefix+"automatic_resize_completed", bool(replaced) and not errors)
                    check(prefix+"previous_controls_released", not old_shell.winfo_exists()
                          and root.winfo_children() == [ui.shell])
                    check(prefix+"native_button_entry_and_log_text_scale", all(abs(a-b) < 2 for a, b in zip(normal_text, text_sizes())))
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
