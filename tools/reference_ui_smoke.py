"""Compare rendered card geometry with a supplied, account-free guide crop."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import tkinter as tk
from unittest.mock import patch

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
                    check(f"{scale}_{size}_reference_card_proportion", len(rectangles) >= 3 and
                          all(abs(w/h-ratio) < .015 for _, _, w, h in rectangles))
                    if scene_reference and size == "default":
                        factor = screenshot.width/scene_reference.width
                        tolerance = 4*ui.ui_scale
                        check(f"{scale}_reference_panel_position", all(abs(a-b*factor) <= tolerance
                              for a,b in zip(panel_origin_and_width(screenshot), scene_panel)))
                        check(f"{scale}_reference_card_positions_and_sizes", len(rectangles) == len(scene_cards) and
                              all(abs(a-b*factor) <= tolerance for actual,expected in zip(sorted(rectangles),scene_cards)
                                  for a,b in zip(actual,expected)))
                    check_layout(root)
                    cases.append(dict(scale=scale, size=size, paper_rectangles=rectangles))
                    if scale == 1.5 and size == "default":
                        screenshot.save(OUT/"home.png")
                board = ui.table
                keys = list(board.names)
                partial = keys[board.offset+board.visible_count]
                x1, y1, x2, y2 = board.hitboxes[partial]
                first = board.hitboxes[keys[0]]
                check(f"{scale}_next_card_is_visible", 0 < x2-x1 < .75*(first[2]-first[0]))
                root.focus_force()
                root.update()
                before = ui.tasks[partial].get()
                board.event_generate("<Button-1>", x=round((x1+x2)/2*ui.ui_scale), y=round(90*ui.ui_scale))
                root.update()
                x1, y1, x2, y2 = board.hitboxes[partial]
                check(f"{scale}_partial_card_reveals_its_action_before_editing", ui.active_page == "home"
                      and ui.tasks[partial].get() == before and x2-x1 >= board.card_width-1)
                board.event_generate("<Button-1>", x=round((x1+x2)/2*ui.ui_scale), y=round((y2-30)*ui.ui_scale))
                root.update()
                check(f"{scale}_revealed_card_performs_its_named_action", ui.tasks[partial].get() and
                      (ui.active_page == "settings" if before else ui.active_page == "home"))
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
                check(f"{scale}_weekly_returns_plan_in_settings_surface", ui.settings_shell.plan.winfo_ismapped()
                      and not ui.guide.winfo_ismapped()
                      and ui.start_button.cget("text") == "开始计划")
                ui.target_name.set("长副本名称"*10)
                root.update()
                check(f"{scale}_cost_precedes_truncatable_target", ui.daily_caption.get().index("240 开拓力")
                      < ui.daily_caption.get().index("长副本名称"))
                check(f"{scale}_config_unchanged", config.read_bytes() == original)
                for key, caption in (("logs", "记录"), ("settings", "设置")):
                    button = ui.guide.buttons[key]
                    ui._show_page("home")
                    root.update()
                    check(f"{scale}_{key}_name_visible_without_hover", button.winfo_ismapped() and
                          button.cget("text") == caption
                          and str(button.cget("compound")) == ("left" if key == "settings" else "center"))
                    button.event_generate("<Enter>")
                    root.update()
                    check(f"{scale}_{key}_has_no_duplicate_name_popup", not any(isinstance(child, tk.Toplevel)
                          for child in button.winfo_children()))
                    root.focus_force()
                    button.focus_set()
                    button.event_generate("<KeyPress-space>")
                    button.event_generate("<KeyRelease-space>")
                    root.update()
                    check(f"{scale}_{key}_named_button_opens_expected_page", ui.active_page == key and
                          ui.start_button.cget("text") == "开始计划")
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
