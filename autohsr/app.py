from __future__ import annotations

import ctypes as C
import json
import logging
from pathlib import Path
import threading
import time
from datetime import datetime

from .config import ROOT, RESOURCE_ROOT, Settings
from .models import AutomationError, FocusLost, RunReport, Scene, Stopped, TaskResult, Token
from .vision import Vision, save_scene
from .windows import find_game, is_admin, launch


def launch_game(settings: Settings) -> str:
    settings.validate()
    return launch(settings.game_path)


def inspect_game(settings: Settings) -> dict:
    settings.validate()
    window = find_game(settings.game_path)
    window.focus()
    vision = Vision(settings.ocr_confidence)
    image, geometry = window.capture()
    scene = vision.read(image, geometry)
    output = ROOT / "runs" / ("check_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    screenshot = save_scene(scene, output, "screen")
    result = dict(window=window.hwnd, title=window.title, width=geometry.width, height=geometry.height,
                  administrator=is_admin(), ocr_text=scene.text, screenshot=str(screenshot))
    (output / "check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


class Context:
    def __init__(self, runner: Runner, window, vision):
        self.runner, self.window, self.vision = runner, window, vision
        self.settings, self.report = runner.settings, runner.report
        self.last_scene: Scene | None = None
        self.scene_epoch = 0
        self._scroll_anchor = None

    def log(self, message: str, level="info"):
        self.runner.log(message, level)

    def checkpoint(self):
        self.runner.checkpoint()

    def sleep(self, seconds: float):
        remaining = seconds
        while remaining > 0:
            self.checkpoint()
            interval = min(0.1, remaining)
            start = time.monotonic()
            time.sleep(interval)
            remaining -= time.monotonic() - start
        self.checkpoint()

    def snapshot(self) -> Scene:
        self.checkpoint()
        capture_epoch = self.runner.input_epoch
        captured_at = time.monotonic()
        image, geometry = self.window.capture()
        scene = self.vision.read(image, geometry)
        scene.captured_at = captured_at
        self.checkpoint()
        if capture_epoch != self.runner.input_epoch:
            raise AutomationError("识别过程中发生暂停或恢复，旧截图已丢弃，请重新开始。")
        self.window.guard(geometry)
        self.last_scene = scene
        self.scene_epoch = capture_epoch
        return scene

    def click(self, scene: Scene, target: Token | tuple[float, float]):
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch or time.monotonic() - scene.captured_at > 8:
            raise AutomationError("识别画面已经过期，请重新识别后操作。")
        from .policy import guard_click, replenishment_dialog
        guard_click(scene, target)
        coordinates = target.center if isinstance(target, Token) else target
        resource_dialog = replenishment_dialog(scene)
        if resource_dialog and (not isinstance(target, Token) or target.text.strip() != "取消"):
            self.evidence(scene, "resource_dialog")
            raise AutomationError("开拓力补充/兑换界面只允许取消，已禁止该操作。")
        label = target.text if isinstance(target, Token) else f"{coordinates[0]:.3f},{coordinates[1]:.3f}"
        self.log(f"点击：{label}")
        self.window.click(*coordinates, scene.geometry)
        self.last_scene = None
        self.sleep(self.settings.action_delay)

    def key(self, name: str):
        self.checkpoint()
        if name not in ("esc", "f4"):
            raise AutomationError("日常流程仅允许返回键和指南快捷键；其他快捷键被禁止。")
        self.window.key(name)
        self.last_scene = None
        self.sleep(self.settings.action_delay)

    def wait(self, predicate, timeout=30, description="界面") -> Scene:
        elapsed = 0.0
        while elapsed < timeout:
            # Paused time is excluded from transition deadlines.
            self.checkpoint()
            start = time.monotonic()
            scene = self.snapshot()
            if predicate(scene):
                return scene
            elapsed += time.monotonic() - start
            self.sleep(0.7)
            elapsed += 0.7
        if self.last_scene:
            self.evidence(self.last_scene, "timeout")
        raise AutomationError(f"等待{description}超时（{timeout} 秒）。请查看本次运行截图。")

    def evidence(self, scene: Scene, name: str):
        stamp = datetime.now().strftime("%H%M%S_%f")
        return save_scene(scene, Path(self.report.run_dir), f"{stamp}_{name}")

    def scroll(self, amount: int):
        self.checkpoint()
        if not self._scroll_anchor or self.scene_epoch != self.runner.input_epoch or self.last_scene is None:
            raise AutomationError("滚动前需要重新识别并定位列表区域。")
        point, geometry, epoch = self._scroll_anchor
        if epoch != self.runner.input_epoch or time.monotonic()-self.last_scene.captured_at > 8:
            raise AutomationError("滚动前定位已经过期。")
        self.window.move(*point, geometry)
        self.window.scroll(amount)
        self.last_scene = None
        self.sleep(self.settings.action_delay)

    def move(self, scene: Scene, point: tuple[float, float]):
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch or time.monotonic()-scene.captured_at > 8:
            raise AutomationError("移动前识别画面已经过期。")
        self.window.move(*point, scene.geometry)
        self._scroll_anchor = (point, scene.geometry, self.scene_epoch)

    def template(self, scene: Scene, name: str, roi=(0, 0, 1, 1), threshold=0.88):
        path = RESOURCE_ROOT / "assets" / "templates" / f"{name}.png"
        if not path.exists():
            return None
        return self.vision.template(scene, path, roi, threshold)


class Runner:
    def __init__(self, settings: Settings, emit=None):
        self.settings = settings
        self.emit = emit or (lambda event: None)
        self.report = RunReport()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._resume_focus = False
        self._window = None
        self._monitor_end = threading.Event()
        self._logger = None
        self.input_epoch = 0

    def log(self, message: str, level="info"):
        if self._logger:
            getattr(self._logger, level if level in ("info", "warning", "error") else "info")(message)
        self.emit(dict(type="log", message=message, level=level))

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def toggle_pause(self) -> bool:
        self.input_epoch += 1
        if self._pause.is_set():
            self._resume_focus = True
            self._pause.clear()
            self.log("继续任务；正在重新检查游戏窗口。")
            self.emit(dict(type="paused", paused=False))
            return False
        self._pause.set()
        self.log("任务已暂停，按 F9 或点击继续恢复。")
        self.emit(dict(type="paused", paused=True))
        return True

    def checkpoint(self):
        if self._stop.is_set():
            raise Stopped("任务已停止。")
        while self._pause.is_set():
            if self._stop.wait(0.1):
                raise Stopped("任务已停止。")
        if self._stop.is_set():
            raise Stopped("任务已停止。")
        if self._resume_focus and self._window:
            self._resume_focus = False
            self._window.focus()

    def _hotkeys(self):
        from .windows import user32
        previous = False
        while not self._monitor_end.wait(0.05):
            if self._window.emergency_pressed():
                self.stop()
            current = bool(user32.GetAsyncKeyState(0x78) & 0x8000)
            if current and not previous and user32.GetForegroundWindow() == self._window.hwnd:
                self.toggle_pause()
            previous = current

    def run(self) -> RunReport:
        from .workflows import DailyWorkflow
        from .windows import kernel32
        directory = ROOT / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        directory.mkdir(parents=True)
        self.report.run_dir = str(directory)
        self._logger = logging.getLogger(f"autohsr.{directory.name}")
        self._logger.setLevel(logging.INFO)
        handler = logging.FileHandler(directory / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self._logger.addHandler(handler)
        kernel32.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
        kernel32.CreateMutexW.restype = C.c_void_p
        mutex = kernel32.CreateMutexW(None, False, "Local\\AutoHSR.DailyRunner")
        already_running = C.get_last_error() == 183
        context = None
        try:
            if not mutex or already_running:
                raise AutomationError("另一个 AutoHSR 任务正在运行，请先停止后重试。")
            self.settings.validate()
            self.checkpoint()
            if self.settings.auto_launch:
                self.log(launch_game(self.settings))
                self.log("等待游戏窗口；首次登录/更新请手动完成。")
                for _ in range(120):
                    self.checkpoint()
                    try:
                        self._window = find_game(self.settings.game_path)
                        break
                    except AutomationError:
                        if self._stop.wait(1):
                            raise Stopped("任务已停止。")
            self._window = self._window or find_game(self.settings.game_path)
            self._window.focus()
            threading.Thread(target=self._hotkeys, name="AutoHSR-hotkeys", daemon=True).start()
            self.log("正在加载中文 OCR 模型。F9 暂停/继续，F10 紧急停止。")
            vision = Vision(self.settings.ocr_confidence)
            context = Context(self, self._window, vision)
            workflow = DailyWorkflow(context)
            initial = context.snapshot()
            context.evidence(initial, "start")
            workflow.ensure_main()
            for name, enabled in (("assignments", self.settings.assignments), ("battle", self.settings.battle),
                                  ("mail", self.settings.mail), ("battlepass", self.settings.battlepass), ("daily", self.settings.daily)):
                if not enabled:
                    continue
                self.checkpoint()
                self.emit(dict(type="task", task=name, status="running", detail="正在执行"))
                result = getattr(workflow, name)()
                self.report.results.append(result)
                self.emit(dict(type="task", **result.__dict__))
                self.log(f"{result.task}：{result.detail}")
            if not self.report.results:
                raise AutomationError("至少选择一个任务。")
            success = all(r.status == "ok" for r in self.report.results)
            self.report.status = "success" if success else "partial"
            if self.settings.daily and not self.report.daily_verified:
                self.report.status = "partial"
            self.log("任务已结束；请查看各项结果和实训活跃度验证。")
        except Stopped as error:
            self.report.status = "stopped"
            self.log(str(error), "warning")
        except Exception as error:
            self.report.status = "failed"
            self.log(str(error), "error")
            if context and context.last_scene:
                context.evidence(context.last_scene, "failure")
            self.report.results.append(TaskResult("run", "failed", str(error)))
        finally:
            self._monitor_end.set()
            if mutex:
                kernel32.CloseHandle(mutex)
            (directory / "report.json").write_text(json.dumps(self.report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            self._logger.removeHandler(handler)
            handler.close()
            self.emit(dict(type="finished", report=self.report.to_dict()))
        return self.report
