"""Check overlay behavior against our own test window, never the game."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import json
import sys
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autohsr import windows  # DPI awareness before Tk
from autohsr.overlay import GameLogOverlay, NativePresentation, OverlayService
import mss
import numpy as np
from PIL import Image

OUTPUT = Path(__file__).resolve().parents[1] / "runs" / "overlay-smoke"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    host = tk.Tk()
    host.title("AutoHSR 覆盖日志测试 · 模拟游戏窗口")
    host.geometry("1280x720+80+80")
    host.attributes("-topmost", True)
    canvas = tk.Canvas(host, background="#263b4c", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(60, 80, text="AutoHSR 覆盖日志验证", anchor="nw", fill="white", font=("Microsoft YaHei UI", 25))
    canvas.create_text(60, 145, text="模拟游戏画面 · 此窗口不连接游戏", anchor="nw", fill="#b1d0e0", font=("Microsoft YaHei UI", 13))
    owner = tk.Tk()
    owner.title("AutoHSR 日志测试控制窗口")
    owner.geometry("400x200+1450+100")
    owner.update()
    owner.iconify()
    host.update()
    handle = windows.user32.GetAncestor(host.winfo_id(), 2)
    presentation = NativePresentation()
    warnings = []
    overlay = GameLogOverlay(owner, lambda: handle, lambda *args: warnings.append(args), presentation=presentation)

    def pump(duration=.4):
        until = time.monotonic() + duration
        while time.monotonic() < until:
            host.update()
            owner.update()
            time.sleep(.01)

    def capture():
        bounds = presentation.game_bounds(handle)
        assert bounds is not None, f"Own test window is not foreground (expected {handle}, actual {windows.user32.GetForegroundWindow()})."
        left, top, width, height = bounds
        with mss.mss() as camera:
            return np.array(camera.grab({"left": left, "top": top, "width": width, "height": height}))

    def activate_host():
        # Exercise our foreground helper against this process's own viewport.
        host.lift()
        host.focus_force()
        windows.GameWindow(handle).focus()

    try:
        activate_host()
        pump()
        assert not warnings and overlay.handle, warnings
        baseline = capture()
        overlay.begin("正在进入游戏")
        overlay.append("已启动所选区服，正在检查登录页面。")
        overlay.append("已确认主界面，可以开始每日。")
        pump()
        assert overlay.visible, "Overlay must remain visible while the helper is minimized."
        assert windows.user32.GetForegroundWindow() == handle, "Overlay stole focus."
        flags = presentation.get_style(overlay.handle, -20)
        assert flags & 0x80800a0 == 0x80800a0, hex(flags)
        affinity = W.DWORD()
        presentation.user32.GetWindowDisplayAffinity.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        assert presentation.user32.GetWindowDisplayAffinity(overlay.handle, C.byref(affinity)) and affinity.value == 0x11
        captured = capture()
        Image.fromarray(baseline[:, :, [2, 1, 0]]).save(OUTPUT / "baseline.png")
        Image.fromarray(captured[:, :, [2, 1, 0]]).save(OUTPUT / "capture-excluded.png")
        # Win11 rounded corners expose the animated desktop beneath the host.
        # Exclude only this 8px outer border; the complete overlay remains inside.
        assert np.array_equal(baseline[8:-8, 8:-8], captured[8:-8, 8:-8]), "Overlay must not appear in mss OCR captures."
        presentation.user32.WindowFromPoint.argtypes = [W.POINT]
        presentation.user32.WindowFromPoint.restype = W.HWND
        bounds = overlay._bounds
        assert presentation.user32.WindowFromPoint(W.POINT(bounds[0]+15, bounds[1]+15)) != overlay.handle, "Overlay blocks input."
        overlay.set_enabled(False)
        assert not overlay.visible
        overlay.set_enabled(True)
        pump()
        assert overlay.visible
        owner.deiconify()
        owner.lift()
        owner.focus_force()
        pump()
        assert not overlay.visible, "Overlay must hide when game loses focus."
        owner.iconify()
        activate_host()
        pump()
        assert overlay.visible, "Overlay must resume when game regains focus."
        overlay.finish("已进入游戏")
        overlay.linger_until = 0
        pump()
        assert not overlay.visible
        overlay.close()

        # The preview deliberately allows capture only of our own fake window.
        preview = GameLogOverlay(owner, lambda: handle, lambda *args: warnings.append(args),
                                 presentation=NativePresentation(protect_capture=False))
        preview.begin("正在执行：每日实训")
        for line, level in (("已进入游戏主界面。", "info"), ("正在识别每日任务状态。", "info"),
                            ("已领取持续委托奖励，正在挑战浴火钢心。", "info"), ("F9 暂停 / 继续，F10 停止。", "warning")):
            preview.append(line, level)
        pump()
        assert preview.visible
        pixels = capture()
        assert not np.array_equal(baseline, pixels), "Visual preview must contain text."
        Image.fromarray(pixels[:, :, [2, 1, 0]]).save(OUTPUT / "overlay-preview.png")
        preview.close()
        # Production CLI/GUI use a separate passive native process.
        service = OverlayService()
        try:
            activate_host()
            service.start(int(handle))
            service.publish(dict(type='log', message='日志队列字幕事件测试'))
            notices = []
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and not notices:
                pump(.1)
                notices.extend(service.drain_notices())
            assert notices and all(level != 'warning' for _, level in notices), notices
            pump(1.0)  # Include the child's first paint and later positioning ticks.
            notices.extend(service.drain_notices())
            foreground = windows.user32.GetForegroundWindow()
            title = C.create_unicode_buffer(512)
            presentation.user32.GetWindowTextW(foreground, title, 512)
            assert foreground == handle, f'Overlay service stole focus: {foreground}, {title.value!r}; expected {handle}.'
            assert np.array_equal(baseline[8:-8, 8:-8], capture()[8:-8, 8:-8]), 'Overlay service appeared in capture.'
        finally:
            service.close()
        (OUTPUT / "proof.json").write_text(json.dumps({"status": "passed", "capture_affinity": affinity.value,
            "foreground_preserved": True, "capture_pixels_unchanged": True, "mouse_passthrough": True,
            "native_service_verified": True}), encoding="utf-8")
        print("Overlay smoke passed: minimized helper, foreground retained, click-through, capture exclusion, toggle, hide/resume, finish.")
        print(f"Preview: {OUTPUT / 'overlay-preview.png'}")
    finally:
        for root in (owner, host):
            for timer in root.tk.splitlist(root.tk.call("after", "info")):
                root.after_cancel(timer)
            root.destroy()


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    try:
        main()
    except Exception as error:
        (OUTPUT / "proof.json").write_text(json.dumps({"status": "failed", "error": str(error)}), encoding="utf-8")
        raise
