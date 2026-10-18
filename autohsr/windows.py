"""Win32 client-area capture and guarded SendInput; no game internals."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time

from .models import AutomationError, FocusLost

user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
shell32 = C.WinDLL("shell32", use_last_error=True)
try:
    user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
except (AttributeError, OSError):
    user32.SetProcessDPIAware()

ENUMPROC = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user32.EnumWindows.argtypes = [ENUMPROC, W.LPARAM]
user32.GetForegroundWindow.restype = W.HWND
user32.IsWindow.argtypes = [W.HWND]
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsIconic.argtypes = [W.HWND]
user32.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user32.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
user32.GetWindowTextLengthW.argtypes = [W.HWND]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.BringWindowToTop.argtypes = [W.HWND]
user32.AttachThreadInput.argtypes = [W.DWORD, W.DWORD, W.BOOL]
kernel32.GetCurrentThreadId.restype = W.DWORD
user32.ShowWindow.argtypes = [W.HWND, C.c_int]
user32.GetAsyncKeyState.argtypes = [C.c_int]
user32.GetAsyncKeyState.restype = C.c_short
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]


@dataclass(frozen=True)
class Geometry:
    left: int
    top: int
    width: int
    height: int


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", INPUTUNION)]


user32.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
user32.SendInput.restype = W.UINT


def is_admin() -> bool:
    return bool(shell32.IsUserAnAdmin())


def is_elevated(hwnd: int) -> bool | None:
    """Read token elevation to explain Windows UIPI before attempting input."""
    advapi = C.WinDLL("advapi32", use_last_error=True)
    advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    pid, token, elevated, length = W.DWORD(), W.HANDLE(), W.DWORD(), W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    process = kernel32.OpenProcess(0x1000, False, pid.value)
    if not process:
        return None
    try:
        if not advapi.OpenProcessToken(process, 8, C.byref(token)):
            return None
        if not advapi.GetTokenInformation(token, 20, C.byref(elevated), C.sizeof(elevated), C.byref(length)):
            return None
        return bool(elevated.value)
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


def process_path(hwnd: int) -> str:
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        length = W.DWORD(32768)
        buffer = C.create_unicode_buffer(length.value)
        return buffer.value if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(length)) else ""
    finally:
        kernel32.CloseHandle(handle)


def geometry(hwnd: int) -> Geometry:
    rect, point = W.RECT(), W.POINT(0, 0)
    if not user32.GetClientRect(hwnd, C.byref(rect)) or not user32.ClientToScreen(hwnd, C.byref(point)):
        raise AutomationError("无法读取游戏窗口，请重新启动检测。")
    return Geometry(point.x, point.y, rect.right - rect.left, rect.bottom - rect.top)


def find_game(expected_path: str | None = None) -> GameWindow:
    matches = []
    expected = str(Path(expected_path).resolve()).casefold() if expected_path else None

    @ENUMPROC
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            path = process_path(hwnd)
            if Path(path).name.casefold() == "starrail.exe" and (expected is None or str(Path(path).resolve()).casefold() == expected):
                g = geometry(hwnd)
                if g.width >= 640 and g.height >= 360:
                    matches.append((g.width * g.height, hwnd))
        return True

    user32.EnumWindows(visit, 0)
    if not matches:
        raise AutomationError("未找到指定 StarRail.exe 的游戏窗口。请启动游戏、登录并进入可自由操作的场景。")
    return GameWindow(max(matches)[1])


def launch(path: str) -> str:
    executable = Path(path)
    if not executable.is_file() or executable.name.casefold() != "starrail.exe":
        raise AutomationError("游戏路径无效，请选择实际的 StarRail.exe。")
    try:
        existing = find_game(path)
        existing.focus()
        return "游戏已运行，已切换到游戏窗口。"
    except FocusLost:
        raise
    except AutomationError:
        pass
    try:
        subprocess.Popen([str(executable)], cwd=str(executable.parent))
    except OSError as error:
        if error.winerror == 740:
            raise AutomationError("游戏需要管理员权限，请以管理员身份启动 AutoHSR 后重试。") from error
        raise AutomationError(f"启动游戏失败：{error}") from error
    return "启动请求已发送。窗口出现后，请完成登录并检测窗口，再开始每日任务。"


class GameWindow:
    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.path = process_path(hwnd)

    @property
    def title(self) -> str:
        buffer = C.create_unicode_buffer(user32.GetWindowTextLengthW(self.hwnd) + 1)
        user32.GetWindowTextW(self.hwnd, buffer, len(buffer))
        return buffer.value

    def focus(self) -> None:
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, 9)
        for _ in range(4):
            user32.SetForegroundWindow(self.hwnd)
            foreground = user32.GetForegroundWindow()
            if foreground == self.hwnd:
                time.sleep(0.4)
                if user32.GetForegroundWindow() == self.hwnd:
                    break
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
            target_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
            current_thread = kernel32.GetCurrentThreadId()
            attached = user32.AttachThreadInput(current_thread, foreground_thread, True)
            attached_target = user32.AttachThreadInput(current_thread, target_thread, True)
            try:
                user32.BringWindowToTop(self.hwnd)
                user32.SetForegroundWindow(self.hwnd)
            finally:
                if attached_target:
                    user32.AttachThreadInput(current_thread, target_thread, False)
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            time.sleep(0.5)
        self.guard()

    def guard(self, expected: Geometry | None = None) -> Geometry:
        if not user32.IsWindow(self.hwnd):
            raise AutomationError("游戏窗口已关闭，当前运行已停止。")
        if user32.IsIconic(self.hwnd):
            raise FocusLost("游戏窗口已最小化，等待恢复前台。")
        if user32.GetForegroundWindow() != self.hwnd:
            raise FocusLost("游戏窗口失去焦点，等待恢复前台。")
        g = geometry(self.hwnd)
        if expected and g != expected:
            raise AutomationError("游戏窗口位置或大小已变化，请重新开始以刷新识别坐标。")
        if g.width < 960 or g.height < 540 or abs(g.width / g.height - 16 / 9) > 0.04:
            raise AutomationError(f"当前客户区为 {g.width}×{g.height}，请使用至少 960×540 的 16:9 窗口，推荐 1920×1080。")
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        if g.left < left or g.top < top or g.left + g.width > left + user32.GetSystemMetrics(78) or g.top + g.height > top + user32.GetSystemMetrics(79):
            raise AutomationError("游戏客户区有部分位于屏幕外，请移动窗口后重试。")
        return g

    def capture(self):
        import mss
        import numpy as np
        g = self.guard()
        with mss.mss() as capture:
            raw = capture.grab({"left": g.left, "top": g.top, "width": g.width, "height": g.height})
            bgr = np.asarray(raw)[:, :, :3].copy()
        self.guard(g)
        if bgr.std() < 2:
            from .models import EmptyCapture
            raise EmptyCapture("截图为空或黑屏；请等待加载完成，关闭 HDR/滤镜并使用窗口模式。")
        return bgr, g

    @staticmethod
    def emergency_pressed() -> bool:
        return bool(user32.GetAsyncKeyState(0x79) & 0x8000)  # F10

    def send(self, events: list[INPUT], expected: Geometry | None = None) -> None:
        self.guard(expected)
        if self.emergency_pressed():
            from .models import Stopped
            raise Stopped("F10 紧急停止。")
        items = (INPUT * len(events))(*events)
        if user32.SendInput(len(items), items, C.sizeof(INPUT)) != len(items):
            raise AutomationError("模拟输入被 Windows 拒绝；请以管理员身份启动 AutoHSR。")

    def click(self, x: float, y: float, expected: Geometry) -> None:
        g = self.guard(expected)
        if not (0 <= x < 1 and 0 <= y < 1):
            raise AutomationError("点击坐标超出游戏客户区。")
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        px, py = g.left + round(x * (g.width - 1)), g.top + round(y * (g.height - 1))
        move = INPUT(type=0, mi=MOUSEINPUT(round((px-vx)*65535/(vw-1)), round((py-vy)*65535/(vh-1)), 0, 0xC001, 0, 0))
        down = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0002, 0, 0))
        up = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0004, 0, 0))
        self.send([move, down, up], expected)

    def click_held(self,x: float,y: float,expected: Geometry,*,checkpoint=lambda:None) -> None:
        """One frame-visible click; release even after a pause or focus loss."""
        import math
        if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<1 for v in (x,y)):
            raise AutomationError('点击坐标超出游戏客户区。')
        checkpoint()
        self.move(x,y,expected)
        down=INPUT(type=0,mi=MOUSEINPUT(0,0,0,0x0002,0,0))
        up=INPUT(type=0,mi=MOUSEINPUT(0,0,0,0x0004,0,0))
        try:
            self.send([down],expected)
            for _ in range(6):
                checkpoint()
                time.sleep(.02)
        finally:
            if user32.SendInput(1,C.byref(up),C.sizeof(INPUT))!=1:
                raise AutomationError('左键释放失败，请手动松开鼠标并检查输入权限。')

    def move(self, x: float, y: float, expected: Geometry) -> None:
        g = self.guard(expected)
        if not (0 <= x < 1 and 0 <= y < 1):
            raise AutomationError("移动坐标超出游戏客户区。")
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        px, py = g.left + round(x*(g.width-1)), g.top + round(y*(g.height-1))
        self.send([INPUT(type=0, mi=MOUSEINPUT(round((px-vx)*65535/(vw-1)), round((py-vy)*65535/(vh-1)), 0, 0xC001, 0, 0))], expected)

    def key(self, name: str) -> None:
        vk = {"esc": 0x1B, "f1": 0x70, "f2": 0x71, "f4": 0x73, "v": 0x56, "space": 0x20}.get(name.casefold())
        if vk is None:
            raise ValueError(f"Unsupported key: {name}")
        scan = user32.MapVirtualKeyW(vk, 0)
        self.send([INPUT(type=1, ki=KEYBDINPUT(0, scan, 0x8, 0, 0))])
        try:
            time.sleep(0.08)  # Unity polls keys once per frame.
        finally:
            release = INPUT(type=1, ki=KEYBDINPUT(0, scan, 0xA, 0, 0))
            user32.SendInput(1, C.byref(release), C.sizeof(INPUT))

    def drag(self, start: tuple[float, float], end: tuple[float, float], expected: Geometry,
             *, checkpoint=lambda: None, waypoints=()) -> None:
        """Hold left throughout a paced movement; always release on interruption.

        The game polls input per frame, so batching down/move/up together can
        appear as a click. This primitive is not a verified Currency Wars flow.
        """
        import math
        if not isinstance(waypoints,(tuple,list)) or len(waypoints)>4:
            raise AutomationError('拖动路径无效。')
        for point in (start, *waypoints, end):
            if (len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v < 1 for v in point)):
                raise AutomationError("拖动坐标超出游戏客户区。")
        checkpoint()
        self.move(*start, expected)
        down = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0002, 0, 0))
        up = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0004, 0, 0))
        try:
            self.send([down], expected)
            # Hold through multiple Unity frames before crossing drag threshold.
            for _ in range(6):
                checkpoint()
                time.sleep(.02)
            previous=start
            for destination in (*waypoints,end):
                for step in range(1, 31):
                    checkpoint()
                    fraction = step / 30
                    self.move(previous[0] + (destination[0] - previous[0]) * fraction,
                              previous[1] + (destination[1] - previous[1]) * fraction, expected)
                    time.sleep(.02)
                previous=destination
            for _ in range(4):
                checkpoint()
                time.sleep(.02)
        finally:
            # Releasing our held button is required even after focus/F10 loss.
            # Do not call guarded send(): that could refuse the cleanup itself.
            if user32.SendInput(1, C.byref(up), C.sizeof(INPUT)) != 1:
                raise AutomationError("左键释放失败，请手动松开鼠标并检查输入权限。")

    def scroll(self, amount: int) -> None:
        # Cursor is first placed inside the game by the caller's guarded click.
        self.send([INPUT(type=0, mi=MOUSEINPUT(0, 0, amount & 0xFFFFFFFF, 0x0800, 0, 0))])
