"""Graceful Windows close bound to the process observed during a game run."""

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path

from .models import AutomationError


def _bind(library, name, result, *args):
    function = getattr(library, name)
    function.argtypes, function.restype = list(args), result
    return function


class CloseTarget:
    def __init__(self, window):
        user = C.WinDLL('user32', use_last_error=True)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        self._pid = _bind(user, 'GetWindowThreadProcessId', W.DWORD, W.HWND, C.POINTER(W.DWORD))
        self._post = _bind(user, 'PostMessageW', W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self._hotkey = _bind(user, 'GetAsyncKeyState', C.c_short, C.c_int)
        self._wait = _bind(kernel, 'WaitForSingleObject', W.DWORD, W.HANDLE, W.DWORD)
        self._release = _bind(kernel, 'CloseHandle', W.BOOL, W.HANDLE)
        open_process = _bind(kernel, 'OpenProcess', W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
        query = _bind(kernel, 'QueryFullProcessImageNameW', W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR,
                      C.POINTER(W.DWORD))
        self.hwnd = window.hwnd
        expected = os.path.normcase(str(Path(window.current_executable()).resolve(strict=True)))
        self.pid = self._window_pid()
        if not self.pid or Path(expected).name != 'starrail.exe':
            raise AutomationError('游戏窗口身份未核实。')
        self.handle = open_process(0x101000, False, self.pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not self.handle:
            raise AutomationError('无法绑定本次游戏进程。')
        try:
            name = C.create_unicode_buffer(32768)
            length = W.DWORD(len(name))
            if (not query(self.handle, 0, name, C.byref(length))
                    or os.path.normcase(str(Path(name.value).resolve(strict=True))) != expected
                    or not self.matches(window)):
                raise AutomationError('游戏窗口与运行进程不一致。')
        except BaseException:
            self.release()
            raise

    def _window_pid(self):
        pid = W.DWORD()
        return pid.value if self._pid(self.hwnd, C.byref(pid)) else 0

    def matches(self, window):
        return window.hwnd == self.hwnd and self._window_pid() == self.pid and self._wait(self.handle, 0) == 258

    def release(self):
        if self.handle:
            self._release(self.handle)
            self.handle = None

    def request(self, stopped):
        if self._wait(self.handle, 0) == 0:
            return 'skipped', '本次绑定的游戏进程已退出。'
        if self._window_pid() != self.pid or self._wait(self.handle, 0) != 258:
            return 'skipped', '本次绑定的游戏窗口已变化。'
        if stopped() or self._hotkey(0x79) & 0x8000:
            return 'skipped', '已收到停止请求。'
        if not self._post(self.hwnd, 0x0010, 0, 0):  # WM_CLOSE
            return 'failed', 'Windows 拒绝了退出请求。'
        for _ in range(60):
            result = self._wait(self.handle, 100)
            if result == 0:
                return 'ok', '本次游戏进程已退出。'
            if result != 258 or stopped() or self._hotkey(0x79) & 0x8000:
                break
        return 'partial', '已发送退出请求，游戏进程退出待核对。'
