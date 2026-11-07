"""Compare rendered card geometry with a supplied, account-free guide crop."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import tkinter as tk
from unittest.mock import call, patch

import cv2
import numpy as np
from PIL import Image, ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout

OUT = ROOT/"runs/reference-ui"


def paper_rectangles(image):
    pixels = np.asarray(image.convert("RGB"))
    mask = ((pixels[:, :, 0] > 245) & (pixels[:, :, 1] > 244) & (pixels[:, :, 2] > 237)).astype("uint8")
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    return [list(map(int, s[:4])) for s in stats[1:]
            if s[4] > 20000 and s[2] > 150 and s[3] > 220 and .6 < s[2]/s[3] < 1.]


def panel_origin_and_width(image):
    """Find the first broad neutral paper row, excluding tabs and hanging art."""
    pixels = np.asarray(image.convert("RGB")).astype("int16")
    mask = ((pixels.min(2) >= 210) & (pixels.max(2) <= 235) &
            (pixels.max(2)-pixels.min(2) < 5))
    rows = np.flatnonzero(mask.sum(1) > image.width*.7)
    assert rows.size, "No broad paper panel found"
    y = int(rows[0])
    columns = np.flatnonzero(mask[y])
    return [int(columns[0]), y, int(columns[-1]-columns[0]+1)]


def paper_color_errors(image, reference):
    """Compare visible chart ink with the source, independent of asset masks.

    The sampled regions stay clear of the regrouped cards, timer and ornaments.
    Permit the same four reference-pixel layout tolerance as the geometry check.
    These samples prove local color/placement only, not whole-screen parity.
    """
    pixels = np.asarray(image.convert("RGB").resize(
        (reference.width, round(image.height*reference.width/image.width)), Image.Resampling.LANCZOS)).astype(int)
    source = np.asarray(reference.convert("RGB")).astype(int)
    regions = ((260,897,565,960), (1350,951,1620,962))
    errors = []
    for x1,y1,x2,y2 in regions:
        expected = source[y1:y2,x1:x2]
        ink = (expected[:,:,0]-expected[:,:,2] >= 5) & (expected.min(2)>170)
        assert ink.sum() > 50, ("Reference lacks chart ink", (x1,y1,x2,y2))
        error = min(float(np.abs(pixels[y1+dy:y2+dy,x1+dx:x2+dx][ink]-expected[ink]).mean())
                    for dx in range(-4,5) for dy in range(-4,5))
        errors.append(error)
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--scene-reference", type=Path, help="Account-free full-width guide crop; retain original screen coordinates")
    args = parser.parse_args()
    reference = args.reference
    scene_reference = Image.open(args.scene_reference) if args.scene_reference else None
    scene_cards = sorted(paper_rectangles(scene_reference)) if scene_reference else None
    scene_panel = panel_origin_and_width(scene_reference) if scene_reference else None
    source_rectangles = paper_rectangles(Image.open(reference))
    assert len(source_rectangles) == 4, source_rectangles
    ratio = statistics.median(w/h for _, _, w, h in source_rectangles)
    OUT.mkdir(parents=True, exist_ok=True)
    cases, checks = [], []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            callback_errors = []
            root.report_callback_exception = lambda kind, value, traceback: callback_errors.append(str(value))
            ui = Window(root, config)
            try:
                root.update()
                default = root.geometry()
                for size in ("default", "minimum"):
                    root.geometry(default if size == "default" else "%dx%d" % root.minsize())
                    root.update()
                    screenshot = ImageGrab.grab(window=root.winfo_id())
                    rectangles = paper_rectangles(screenshot)
                    check(f"{scale}_{size}_reference_card_proportion", len(rectangles) == ui.table.visible_count and
                          all(abs(w/h-ratio) < .015 for _, _, w, h in rectangles))
                    if scene_reference and size == "default":
                        factor = screenshot.width/scene_reference.width
                        tolerance = 4*ui.ui_scale
                        check(f"{scale}_reference_panel_position", all(abs(a-b*factor) <= tolerance
                              for a,b in zip(panel_origin_and_width(screenshot), scene_panel)))
                        colors = paper_color_errors(screenshot, scene_reference)
                        for region, error in enumerate(colors):
                            check(f"{scale}_reference_paper_color_{region}", error < 4.5)
                    check_layout(root)
                    cases.append(dict(scale=scale, size=size, paper_rectangles=rectangles,
                                      paper_color_errors=colors if scene_reference and size == "default" else None))
                    if scale == 1.5 and size == "default":
                        screenshot.save(OUT/"home.png")
                check(f"{scale}_home_uses_primary_cards", ui.table.card_keys == ("battle", "daily", "weekly"))
                ui._show_page("home")
                check(f"{scale}_summary_hidden_when_empty", not ui.summary_label.winfo_ismapped())
                ui.result_alert.set("示例：待核对消耗")
                root.update()
                check(f"{scale}_necessary_error_reappears", ui.summary_label.winfo_ismapped())
                check_layout(root)
                ui.result_alert.set("")
                ui._show_page("differential_universe")
                root.update()
                check(f"{scale}_independent_mode_hides_daily_header", not ui.header.plan.winfo_ismapped())
                ui._show_weekly_plan()
                root.update()
                check(f"{scale}_weekly_shows_plan_in_shared_guide", ui.header.plan.winfo_ismapped()
                      and ui.guide.winfo_ismapped() and ui.guide.selected_page=='settings'
                      and not ui.start_button.winfo_ismapped() and ui.start_button.instate(("disabled",)))
                ui.target_name.set("长副本名称"*10)
                root.update()
                check(f"{scale}_cost_precedes_truncatable_target", ui.daily_caption.get().index("240 开拓力")
                      < ui.daily_caption.get().index("长副本名称"))
                check(f"{scale}_config_unchanged", config.read_bytes() == original)
                ui.settings_shell.back.invoke()
                root.update()
                check(f"{scale}_weekly_back_restores_independent_action",
                      ui.active_page == ui.action_page == "differential_universe"
                      and ui.start_button.winfo_ismapped()
                      and ui.start_button.cget("text") == f"开始演算 · {ui.differential_universe_runs.get()} 局")
                with patch.object(ui, "_start") as start:
                    ui.start_button.invoke()
                    check(f"{scale}_restored_action_dispatches_independent_mode",
                          start.call_args_list == [call(differential_universe=True)])
                for key, caption in (("logs", "记录"), ("settings", "设置")):
                    button = ui.guide.buttons[key]
                    ui._show_page("home")
                    root.update()
                    check(f"{scale}_{key}_uses_named_icon_tab", button.winfo_ismapped()
                          and button.cget("text") == caption and str(button.cget("compound")) == "none")
                    root.focus_force()
                    button.focus_set()
                    button.event_generate("<KeyPress-space>")
                    button.event_generate("<KeyRelease-space>")
                    root.update()
                    check(f"{scale}_{key}_named_button_opens_expected_page", ui.active_page == key and
                          not ui.start_button.winfo_ismapped() and ui.start_button.instate(("disabled",)))
                for key, page in (("home", "home"), ("tasks", "tasks"), ("universe", "differential_universe")):
                    ui._show_page(page)
                    root.focus_force()
                    root.focus_set()
                    button = ui.guide.buttons[key]
                    button.event_generate("<Leave>")
                    root.update()
                    def blue_pixels():
                        shot = ImageGrab.grab(window=root.winfo_id())
                        x, y = button.winfo_rootx()-root.winfo_rootx(), button.winfo_rooty()-root.winfo_rooty()
                        pixels = np.asarray(shot.crop((x, y, x+button.winfo_width(), y+button.winfo_height())).convert("RGB")).astype(int)
                        return int(((pixels[:, :, 2]-pixels[:, :, 0]) > 20).sum())
                    idle = blue_pixels()
                    button.event_generate("<Enter>")
                    root.update()
                    check(f"{scale}_{key}_hover_visible", blue_pixels() > idle+20)
                    button.event_generate("<Leave>")
                    root.update()
                    check(f"{scale}_{key}_hover_clears", blue_pixels() == idle)
                    button.focus_set()
                    root.update()
                    check(f"{scale}_{key}_keyboard_focus_visible", blue_pixels() > idle+20)
                    button.event_generate("<KeyPress-space>")
                    button.event_generate("<KeyRelease-space>")
                    root.update()
                    check(f"{scale}_{key}_keyboard_navigation", ui.active_page == page)
                check(f"{scale}_no_drawing_callback_errors", not callback_errors)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    if str(root.tk.call("after", "info", token)[0]).endswith("_drain"):
                        root.after_cancel(token)
                root.destroy()
    result = dict(reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  scene_reference_sha256=hashlib.sha256(args.scene_reference.read_bytes()).hexdigest() if scene_reference else None,
                  scene_reference_cards=scene_cards, scene_reference_panel=scene_panel,
                  reference_paper_rectangles=source_rectangles, reference_ratio=ratio,
                  cases=cases, checks=checks, count=len(checks), game_started=False)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
