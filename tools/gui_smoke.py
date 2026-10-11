"""Offline GUI smoke check. Uses a fake backend and never touches the game."""
from __future__ import annotations

import json
import sys
import threading
import time
import tkinter as tk
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autohsr import windows  # noqa: E402,F401 - DPI awareness before Tk
from autohsr.config import Settings  # noqa: E402
from autohsr.gui import AutoHSRWindow  # noqa: E402
from PIL import ImageGrab  # noqa: E402


def pump(root: tk.Tk, predicate=lambda: True, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for GUI event")


def enabled(widget: tk.Widget) -> bool:
    return str(widget.cget("state")) == "normal"


def destroy(root: tk.Tk) -> None:
    try:
        for callback in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(callback)
        root.destroy()
    except tk.TclError:
        pass  # The close handler may already have destroyed this fixture.


class FakeRunner:
    instances: list["FakeRunner"] = []

    def __init__(self, settings, emit):
        self.settings, self.emit = settings, emit
        self.paused = False
        self.stop_calls = 0
        self.release = threading.Event()
        self.instances.append(self)

    def run(self):
        self.emit({"type": "task", "task": "battle", "status": "running", "detail": "模拟副本挑战"})
        self.emit({"type": "progress", "stamina_spent": 10})
        self.emit({"type": "log", "message": "挑战成功，累计确认消耗20开拓力"})
        self.release.wait(8)
        report = {"status": "stopped" if self.stop_calls else "partial", "stamina_spent": 20,
                  "daily_verified": False, "run_dir": str(OUT / "mock-run"),
                  "results": [{"task": "battle", "status": "partial", "detail": "模拟报告：已确认20开拓力"}]}
        (OUT / "mock-run" / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        self.emit({"type": "finished", "report": report})
        return report

    def toggle_pause(self):
        self.paused = not self.paused
        self.emit({"type": "paused", "paused": self.paused})
        return self.paused

    def stop(self):
        self.stop_calls += 1
        self.release.set()


OUT = ROOT / "runs" / "gui-ui-smoke"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "mock-run").mkdir(exist_ok=True)
(OUT / "mock-run" / "report.json").write_text(json.dumps({"status": "partial", "mock": True}), encoding="utf-8")
config = OUT / "config.json"
Settings().save(config)
fake = types.ModuleType("autohsr.app")
fake.Runner = FakeRunner
fake.inspect_game = lambda _: {"title": "崩坏：星穹铁道（模拟检测）", "width": 1920, "height": 1080,
                              "administrator": True, "ocr_text": "模拟识别文字\n开拓力 240 / 300\n每日实训\n回忆之蕾",
                              "screenshot": str(OUT / "1100x760.png")}
fake.launch_game = lambda _: "模拟启动请求，未访问游戏。"


def screenshot(root: tk.Tk, name: str) -> None:
    root.update_idletasks()
    ImageGrab.grab(window=root.winfo_id()).save(OUT / name)


def layout_check(root: tk.Tk) -> None:
    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_ismapped():
                # Mapped controls must remain inside the main window's client area.
                x, y = child.winfo_rootx() - root.winfo_rootx(), child.winfo_rooty() - root.winfo_rooty()
                assert x >= 0 and y >= 0, (str(child), x, y)
                assert x + child.winfo_width() <= root.winfo_width() + 1, str(child)
                assert y + child.winfo_height() <= root.winfo_height() + 1, str(child)
                if child.winfo_class() in ("TLabel", "TButton", "TCheckbutton", "TEntry", "TSpinbox"):
                    assert child.winfo_height() >= child.winfo_reqheight(), (str(child), "clipped height", child.winfo_height(), child.winfo_reqheight())
                walk(child)
    walk(root)


with patch.dict(sys.modules, {"autohsr.app": fake}), patch("autohsr.gui.messagebox.showerror") as errors, \
        patch("autohsr.gui.messagebox.showwarning"), patch("autohsr.gui.messagebox.askyesnocancel", return_value=False), \
        patch("autohsr.gui.os.startfile") as opened:
    root = tk.Tk()
    ui = AutoHSRWindow(root, config)
    root.geometry("1100x760")
    pump(root)
    layout_check(root)
    screenshot(root, "1100x760.png")
    ui.settings_tabs.select(1)
    pump(root)
    game_tab = root.nametowidget(ui.settings_tabs.select())
    screenshot(root, "game-settings.png")
    layout_check(root)
    assert all(child.winfo_ismapped() for child in game_tab.winfo_children()), "Game help may not disappear"
    ui.settings_tabs.select(0)
    root.geometry("1180x820")
    pump(root)
    layout_check(root)
    screenshot(root, "1180x820.png")

    ui._preset(10, 1)
    assert ui.dirty and not ui.busy and ui.worker is None
    assert (ui.stamina_limit.get(), ui.rounds.get()) == ("10", "1")
    assert Settings.load(config).stamina_limit == 240, "Preset must not save or start"
    ui._save_settings()
    assert not ui.dirty and Settings.load(config).stamina_limit == 10
    ui._preset(240, 6)
    assert ui.dirty and not ui.running
    ui.tasks["battle"].set(False)
    assert all(not enabled(w) for w in ui.stamina_controls)
    ui.tasks["battle"].set(True)
    assert all(enabled(w) for w in ui.stamina_controls)
    ui.use_support.set(False)
    assert "好友支援已关闭" in ui.battle_hint.get()
    ui.use_support.set(True)
    ui.target_location.set("")
    ui._save_settings()
    assert Settings.load(config).target_location == ""
    ui.stamina_limit.set("11")
    assert ui._read_settings() is None and ui.dirty and errors.call_count == 1
    ui.stamina_limit.set("10")
    ui._preset(10, 1)
    ui._save_settings()

    ui._check()
    assert ui.busy and root.state() == "iconic"
    pump(root, lambda: not ui.busy)
    assert root.state() == "normal" and "1920" in ui.detect_size.get()
    assert "模拟识别文字" in ui.inspection_text.get("1.0", "end")
    assert "模拟识别文字" not in ui.log.get("1.0", "end"), "OCR must stay in detection details"
    screenshot(root, "detection.png")
    root.geometry("1100x760")
    pump(root)
    layout_check(root)
    screenshot(root, "detection-minimum.png")
    assert not ui.inspection_text.frame.winfo_ismapped(), "Minimum layout uses the detail dialog"
    root.geometry("1180x820")
    pump(root)
    assert ui.inspection_text.frame.winfo_ismapped(), "Growing the window must restore the preview"
    ui._show_inspection()
    pump(root)
    detail_windows = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(detail_windows) == 1
    screenshot(detail_windows[0], "detection-details.png")
    detail_windows[0].destroy()
    ui._open_path(ui.last_screenshot)
    assert opened.call_count == 1
    ui._launch()
    pump(root, lambda: not ui.busy)
    assert "启动请求已发送" in ui.status.get()

    ui._start()
    assert ui.running and root.state() == "iconic"
    pump(root, lambda: ui.runner is not None and ui.confirmed_stamina == 20)
    assert ui.current_task.get() == "拟造花萼挑战"
    assert all(not enabled(w) for w in ui.setting_controls)
    # Tk's local F9 binding should pause once and restore the assistant.
    ui._restore()
    root.focus_force()
    root.event_generate("<KeyPress-F9>")
    root.event_generate("<KeyRelease-F9>")
    pump(root, lambda: ui.paused)
    assert root.state() == "normal" and ui.pause_button.cget("text") == "继续"
    root.event_generate("<KeyRelease-F9>")
    pump(root)
    assert ui.paused, "A release from a global game hotkey must not toggle locally"
    screenshot(root, "paused.png")
    ui._pause()
    pump(root, lambda: not ui.paused)
    assert root.state() == "iconic"
    ui._pause()
    pump(root, lambda: ui.paused)
    runner = ui.runner
    ui._stop()
    ui._pause_state(True)  # A queued pause may not revive a stopping run.
    assert ui.stopping and not ui.paused and not enabled(ui.pause_button)
    ui._stop()
    pump(root, lambda: not ui.busy)
    assert runner.stop_calls == 1 and root.state() == "normal"
    assert ui.stamina.get() == "20" and "已停止" in ui.status.get()
    assert enabled(ui.report_button) and enabled(ui.directory_button)
    ui.report_button.invoke()
    ui.directory_button.invoke()
    assert opened.call_count == 3
    screenshot(root, "finished.png")
    for result_status in ("stopped", "failed"):
        ui._set_busy(True, True)
        ui._task({"task": "battle", "status": "running", "detail": "模拟中途退出"}, log=False)
        ui._finish({"status": result_status, "results": [], "stamina_spent": 20})
        assert ui.table.item("battle", "values")[1] == ("已停止" if result_status == "stopped" else "失败")
        assert all(ui.table.item(key, "values")[1] not in ("进行中", "等待") for key in ui.tasks)

    # Configuration-level denial must survive edit traces and busy transitions.
    ui.settings = Settings(allow_stamina_spend=False, battle=False)
    ui.tasks["battle"].set(True)
    ui._set_busy(True)
    ui._set_busy(False)
    assert not ui.tasks["battle"].get() and not enabled(ui.battle_checkbox)
    assert all(not enabled(w) for w in ui.stamina_controls)
    root.geometry("1100x760")
    pump(root)
    layout_check(root)
    screenshot(root, "restricted.png")
    destroy(root)

    # Closing an active worker stops it and waits for its exit without Tk calls in the worker.
    Settings().save(config)
    root = tk.Tk()
    ui = AutoHSRWindow(root, config)
    ui._start()
    pump(root, lambda: ui.runner is not None)
    runner = ui.runner
    ui._close()
    assert ui.closing and ui.stop_requested.is_set() and runner.stop_calls == 1
    ui.worker.join(timeout=3)
    assert not ui.worker.is_alive()
    destroy(root)

print("GUI smoke passed: presets/save/validation/detection/launch mocks/F9/pause/resume/stop/report/gate/close.")
print(f"Screenshots: {OUT}")
