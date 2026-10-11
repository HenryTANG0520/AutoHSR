"""Developer calibration helper: one bounded visual action per invocation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autohsr.config import Settings, ROOT
from autohsr.vision import Vision, save_scene
from autohsr.windows import find_game, is_admin, user32, process_path
from autohsr.policy import guard_click, replenishment_dialog

parser = argparse.ArgumentParser()
parser.add_argument("--label")
parser.add_argument("--key", choices=("esc", "f4"))
parser.add_argument("--expected")
parser.add_argument("--roi", default="0,0,1,1")
parser.add_argument("--x", type=float)
parser.add_argument("--y", type=float)
parser.add_argument("--delay", type=float, default=2)
args = parser.parse_args()
out = ROOT / "runs" / "live_probe"
out.mkdir(parents=True, exist_ok=True)
try:
    (out / "startup.json").write_text(json.dumps(dict(admin=is_admin(), foreground=user32.GetForegroundWindow(), foreground_process=process_path(user32.GetForegroundWindow())),ensure_ascii=False),encoding="utf-8")
    settings = Settings.load()
    time.sleep(1.2)  # Let the UAC foreground transition finish before focusing.
    window = find_game(settings.game_path)
    try:
        window.focus()
    except Exception:
        (out / "focus.json").write_text(json.dumps(dict(admin=is_admin(), expected=window.hwnd, foreground=user32.GetForegroundWindow(), foreground_process=process_path(user32.GetForegroundWindow())),ensure_ascii=False),encoding="utf-8")
        raise
    vision = Vision(settings.ocr_confidence)
    image, geometry = window.capture()
    scene = vision.read(image, geometry)
    save_scene(scene, out, "before")
    if args.expected and not scene.has(args.expected):
        raise RuntimeError(f"画面未识别到必要锚点：{args.expected}")
    if args.label:
        roi = tuple(float(v) for v in args.roi.split(","))
        token = scene.find(args.label, roi, exact=True)
        if not token:
            raise RuntimeError(f"画面未识别到按钮：{args.label}")
        guard_click(scene, token)
        if replenishment_dialog(scene) and token.text.strip() != "取消":
            raise RuntimeError("开拓力补充/兑换界面只允许取消。")
        window.click(*token.center, geometry)
    elif args.key:
        window.key(args.key)
    elif args.x is not None:
        if not args.expected or args.y is None:
            raise RuntimeError("坐标校准必须提供页面文字锚点和完整坐标。")
        guard_click(scene, (args.x, args.y))
        if replenishment_dialog(scene):
            raise RuntimeError("开拓力补充/兑换界面禁止坐标操作。")
        window.click(args.x, args.y, geometry)
    if args.label or args.key or args.x is not None:
        time.sleep(args.delay)
        image, geometry = window.capture()
        scene = vision.read(image, geometry)
    screenshot = save_scene(scene, out, "screen")
    save_scene(scene, out / "history", time.strftime("%H%M%S"))
    result = dict(administrator=is_admin(), screenshot=str(screenshot), ocr_text=scene.text,
                  tokens=[dict(text=t.text, score=t.score, box=t.box) for t in scene.tokens])
except Exception as error:
    result = dict(error=str(error))
(out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
