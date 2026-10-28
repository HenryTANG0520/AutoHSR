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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    reference = parser.parse_args().reference
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
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
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
                board.event_generate("<Button-1>", x=round((x1+x2)/2*ui.ui_scale), y=round(90*ui.ui_scale))
                root.update()
                check(f"{scale}_partial_card_opens_its_settings", ui.active_page == "tasks"
                      and root.focus_get() == ui.task_controls[partial])
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
                check(f"{scale}_weekly_returns_plan_and_header", ui.header.plan.winfo_ismapped()
                      and ui.start_button.cget("text") == "开始计划")
                ui.target_name.set("长副本名称"*10)
                root.update()
                check(f"{scale}_cost_precedes_truncatable_target", ui.daily_caption.get().index("240 开拓力")
                      < ui.daily_caption.get().index("长副本名称"))
                check(f"{scale}_config_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    if str(root.tk.call("after", "info", token)[0]).endswith("_drain"):
                        root.after_cancel(token)
                root.destroy()
    result = dict(reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  reference_paper_rectangles=source_rectangles, reference_ratio=ratio,
                  cases=cases, checks=checks, count=len(checks), game_started=False)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
