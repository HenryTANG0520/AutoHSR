"""Check joined scenery, native weekly access and idle redraws without a game."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import types
from unittest.mock import patch

from PIL import Image, ImageGrab, ImageOps
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from autohsr import theme
from autohsr.game_widgets import Surface, SceneButton

OUT = ROOT/"runs/guide-backdrop-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Scenery checks cannot start a game backend")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            prefix = str(scale)+"_"
            try:
                root.update()
                normal = root.geometry().split("+")[0]
                wider = f"{root.winfo_width()+round(60*scale)}x{root.winfo_height()}"
                for label, size in (("default", normal), ("minimum", "%dx%d" % root.minsize()), ("wider", wider), ("maximized", None)):
                    if size:
                        root.geometry(size)
                    else:
                        root.state("zoomed")
                    root.update()
                    ui.responsive_layout.fit()
                    root.update()
                    actual = ImageGrab.grab(window=root.winfo_id()).convert("RGB")
                    with Image.open(ROOT/"assets/ui/guide/backdrop.png") as source:
                        expected = ImageOps.fit(source.convert("RGB"), actual.size, Image.Resampling.LANCZOS)
                    # Visible points cross root/header/guide/plan/button boundaries.
                    points = [(1, root.winfo_height()//2)]
                    for widget in (ui.header, ui.guide, ui.header.plan, ui.plan_ribbon, ui.weekly_button):
                        points.append((widget.winfo_rootx()-root.winfo_rootx(), widget.winfo_rooty()-root.winfo_rooty()))
                    check(prefix+label+"_visible_scene_joins", all(max(abs(a-b) for a,b in zip(actual.getpixel(p), expected.getpixel(p))) <= 3 for p in points))
                    check_layout(root)
                    check(prefix+label+"_layout", True)
                    check(prefix+label+"_daily_primary_is_reachable", ui.start_button.winfo_ismapped() and ui.start_button.cget("text") == "开始计划")
                    if label == "maximized":
                        check(prefix+"_maximized_guide_keeps_readable_book_proportions", ui.guide.winfo_height() <= round(716*ui.ui_scale))
                        _, row_y, _, row_height = root.grid_bbox(0, 1)
                        check(prefix+"_maximized_guide_stays_near_center", abs(ui.guide.winfo_y()-row_y-(row_height-ui.guide.winfo_height())/2) <= row_height*.03+2)
                        if scale == 1.:
                            actual.save(OUT/"maximized.png")
                    if scale == 1.5 and label == "default":
                        actual.save(OUT/"home.png")
                root.state("normal")
                root.geometry(normal)
                root.update()
                ui.responsive_layout.fit()
                root.update()
                ui.weekly_button.state(("disabled",))
                ui.weekly_button.invoke()
                root.update()
                check(prefix+"_disabled_weekly_does_not_open", ui.active_page == "home")
                ui.weekly_button.state(("!disabled",))
                root.focus_force()
                ui.weekly_button.focus_set()
                root.update()
                ui.weekly_button.event_generate("<KeyPress-space>")
                ui.weekly_button.event_generate("<KeyRelease-space>")
                root.update()
                check(prefix+"_keyboard_weekly_opens_settings", ui.active_page == "settings" and ui.settings_shell.section == "weekly")
                check(prefix+"_settings_primary_remains_plan", ui.start_button.winfo_ismapped() and ui.start_button.cget("text") == "开始计划")
                ui.settings_shell.back.invoke()
                root.update()
                check(prefix+"_return_restores_guide_and_focus", ui.guide.winfo_ismapped() and root.focus_get() == ui.weekly_button)
                root.geometry(normal)
                root.update()
                ui.stamina.set("40")
                ui.elapsed_seconds = 12
                ui._clock()
                root.update()
                before = theme.scene_image.cache_info().misses
                ui.elapsed_seconds = 13
                ui._clock()
                root.update()
                check(prefix+"_live_metrics_reuse_scene", theme.scene_image.cache_info().misses == before)
                counts = []
                surface_render, button_render = Surface._render, SceneButton._render
                def surface(widget):
                    counts.append(type(widget).__name__)
                    return surface_render(widget)
                def button(widget):
                    counts.append(type(widget).__name__)
                    return button_render(widget)
                with patch.object(Surface, "_render", surface), patch.object(SceneButton, "_render", button):
                    deadline = time.monotonic()+.4
                    while time.monotonic() < deadline:
                        root.update()
                        time.sleep(.02)
                check(prefix+"_idle_has_no_paint_loop", not counts)
                check(prefix+"_navigation_keeps_config", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    result = dict(checks=checks, count=len(checks), game_started=False)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
