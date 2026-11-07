"""Window-only capture and short navigation gestures for a bound Win32 client."""

from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import math
import threading
import time

from .du_points_followup import require_followup_week
from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped
from .screenshot_tool import MAX_PIXELS
from .windows import GameWindow, geometry, kernel32, process_path, user32


_capture_gate = threading.Lock()
_CAPTURE_TIMEOUT = 1.


def _bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


class _BitmapHeader(C.Structure):
    _fields_ = [('size', W.DWORD), ('width', W.LONG), ('height', W.LONG),
                ('planes', W.WORD), ('bits', W.WORD), ('compression', W.DWORD),
                ('image_size', W.DWORD), ('x_resolution', W.LONG), ('y_resolution', W.LONG),
                ('colors', W.DWORD), ('important', W.DWORD)]


def _print_client(hwnd, width, height):
    import numpy as np

    gdi = C.WinDLL('gdi32', use_last_error=True)
    memory_dc = _bind(gdi, 'CreateCompatibleDC', W.HDC, W.HDC)
    dib = _bind(gdi, 'CreateDIBSection', W.HANDLE, W.HDC, C.POINTER(_BitmapHeader), W.UINT,
                C.POINTER(C.c_void_p), W.HANDLE, W.DWORD)
    select = _bind(gdi, 'SelectObject', W.HANDLE, W.HDC, W.HANDLE)
    delete = _bind(gdi, 'DeleteObject', W.BOOL, W.HANDLE)
    delete_dc = _bind(gdi, 'DeleteDC', W.BOOL, W.HDC)
    print_window = _bind(user32, 'PrintWindow', W.BOOL, W.HWND, W.HDC, W.UINT)
    dc = memory_dc(None)
    if not dc:
        raise EmptyCapture('无法分配后台窗口截图。')
    bitmap = previous = None
    try:
        data = C.c_void_p()
        header = _BitmapHeader(size=C.sizeof(_BitmapHeader), width=width, height=-height, planes=1, bits=32)
        bitmap = dib(dc, C.byref(header), 0, C.byref(data), None, 0)
        if not bitmap or not data.value:
            raise EmptyCapture('无法分配后台窗口像素。')
        previous = select(dc, bitmap)
        if previous in (None, W.HANDLE(-1).value):
            previous = None
            raise EmptyCapture('无法选中后台窗口位图。')
        C.memset(data, 0, width * height * 4)
        if not print_window(hwnd, dc, 3):  # Client area plus full content rendering.
            raise EmptyCapture('后台客户区取帧失败。')
        rgba = (C.c_ubyte * (width * height * 4)).from_address(data.value)
        bgr = np.ctypeslib.as_array(rgba).reshape(height, width, 4)[:, :, :3].copy()
        if bgr[::8, ::8].std(axis=(0, 1)).max() < 2:
            raise EmptyCapture('后台客户区画面为空或单色。')
        return bgr
    finally:
        if previous:
            select(dc, previous)
        if bitmap:
            delete(bitmap)
        delete_dc(dc)


def _bounded_capture(hwnd, size, checkpoint):
    get_desktop = _bind(user32, 'GetThreadDesktop', W.HANDLE, W.DWORD)
    set_desktop = _bind(user32, 'SetThreadDesktop', W.BOOL, W.HANDLE)
    desktop = get_desktop(kernel32.GetCurrentThreadId())
    if not desktop or not _capture_gate.acquire(blocking=False):
        raise EmptyCapture('上次后台截图尚未返回，或当前桌面不可用。')
    done = threading.Event()
    result = []

    def work():
        try:
            if not set_desktop(desktop):
                raise EmptyCapture('后台取帧线程无法绑定当前桌面。')
            result.append(_print_client(hwnd, *size))
        except Exception as error:
            result.append(error)
        finally:
            _capture_gate.release()
            done.set()

    try:
        threading.Thread(target=work, name='AutoHSR-background-capture', daemon=True).start()
    except Exception:
        _capture_gate.release()
        raise
    deadline = time.monotonic() + _CAPTURE_TIMEOUT
    while not done.wait(.025):
        checkpoint()
        if time.monotonic() >= deadline:
            raise EmptyCapture('后台窗口截图超时。')
    if isinstance(result[0], Exception):
        raise result[0]
    return result[0]


def _window_thread(hwnd):
    pid = W.DWORD()
    thread = user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return thread, pid.value


def _cursor():
    point = W.POINT()
    read = _bind(user32, 'GetCursorPos', W.BOOL, C.POINTER(W.POINT))
    if not read(C.byref(point)):
        raise InputInterrupted('当前桌面光标不可用。')
    return point.x, point.y


@contextmanager
def _borrow_cursor(point):
    """Keep physical cursor movement brief and never restore over user movement."""
    move = _bind(user32, 'SetCursorPos', W.BOOL, C.c_int, C.c_int)

    def require_still(expected):
        if _cursor() != expected or any(user32.GetAsyncKeyState(button) & 0x8000 for button in (1, 2, 4)):
            raise InputInterrupted('检测到鼠标操作，已中断本次后台点击。')

    original = _cursor()
    time.sleep(.03)
    require_still(original)
    if not move(*point):
        raise InputInterrupted('当前桌面无法定位后台点击光标。')
    try:
        require_still(point)
        yield lambda: require_still(point)
    finally:
        if _cursor() == point and not move(*original):
            raise AutomationError('后台点击后光标归还未核实。')


class BackgroundGameWindow:
    """Only the operations required by guarded daily page navigation."""

    def __init__(self, window, *, checkpoint):
        self.hwnd = window.hwnd
        self._checkpoint = checkpoint
        self._thread = _window_thread(self.hwnd)
        self._post = _bind(user32, 'PostMessageW', W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self._key = GameWindow.current_window_key(self)
        if not self._key:
            raise AutomationError('后台游戏窗口来源未核实。')

    def guard(self, expected=None):
        if (not all(self._thread) or _window_thread(self.hwnd) != self._thread
                or not user32.IsWindowVisible(self.hwnd) or user32.IsIconic(self.hwnd)):
            raise AutomationError('后台游戏窗口已关闭、隐藏或最小化。')
        current = geometry(self.hwnd)
        if (current.width < 960 or current.height < 540 or current.width * current.height > MAX_PIXELS
                or abs(current.width / current.height - 16 / 9) > .04):
            raise AutomationError('后台游戏窗口须使用可核实的 16:9 客户区。')
        if expected is not None and current != expected:
            raise AutomationError('后台游戏窗口位置或大小已变化。')
        return current

    def current_window_key(self):
        key = GameWindow.current_window_key(self)
        if key != self._key:
            raise AutomationError('后台游戏进程来源已变化。')
        return key

    def current_executable(self):
        self.current_window_key()
        path = process_path(self.hwnd)
        if not path:
            raise AutomationError('后台游戏安装来源未核实。')
        return path

    def capture(self):
        current = self.guard()
        self.current_window_key()
        frame = _bounded_capture(self.hwnd, (current.width, current.height), self._checkpoint)
        self._checkpoint()
        self.current_window_key()
        self.guard(current)
        return frame, current

    emergency_pressed = staticmethod(GameWindow.emergency_pressed)

    def _before(self, expected, before_send, before_submit):
        if expected is None:
            raise AutomationError('后台窗口操作缺少本次识别客户区。')
        self._checkpoint()
        self.guard(expected)
        self.current_window_key()
        if self.emergency_pressed():
            raise Stopped('F10 已停止后台页面导航。')
        if before_send is not None:
            before_send()
        require_followup_week()
        if before_submit is None:
            raise AutomationError('后台窗口操作缺少本次导航意图。')
        before_submit()
        self.guard(expected)

    def _message(self, message, parameter, detail):
        if _window_thread(self.hwnd) != self._thread or not self._post(self.hwnd, message, parameter, detail):
            raise AutomationError('后台窗口消息未完整发送，需核对当前游戏页面。')

    def click(self, x, y, expected, *, before_send=None, before_submit=None):
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < 1
               for value in (x, y)):
            raise AutomationError('后台点击位置超出游戏客户区。')
        self._before(expected, before_send, before_submit)
        px, py = round(x * (expected.width - 1)), round(y * (expected.height - 1))
        point = px | (py << 16)
        with _borrow_cursor((expected.left + px, expected.top + py)) as still:
            self.guard(expected)
            still()
            self._message(0x0200, 0, point)
            self.guard(expected)
            still()
            try:
                self._message(0x0201, 1, point)
                time.sleep(.08)
                still()
            finally:
                self._message(0x0202, 0, point)

    def key(self, name, *, expected=None, before_submit=None, require_release=False):
        if name != 'esc':
            raise AutomationError('后台页面导航仅开放 Esc。')
        self._before(expected, None, before_submit)
        vk = 0x1b
        flags = 1 | (user32.MapVirtualKeyW(vk, 0) << 16)
        try:
            self._message(0x0100, vk, flags)
            time.sleep(.08)
        finally:
            self._message(0x0101, vk, flags | 0xc0000000)
