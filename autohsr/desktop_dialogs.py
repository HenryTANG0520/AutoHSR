"""Place read-only details near their owner, inside its monitor's work area."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


def _work_area(owner):
    if sys.platform == "win32":
        class MonitorInfo(ctypes.Structure):
            _fields_ = (("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD))
        user32 = ctypes.windll.user32
        nearest = user32.MonitorFromWindow
        nearest.argtypes, nearest.restype = (wintypes.HWND, wintypes.DWORD), wintypes.HANDLE
        info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        read = user32.GetMonitorInfoW
        read.argtypes, read.restype = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo)), wintypes.BOOL
        if read(nearest(owner.winfo_id(), 2), ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    # A missing monitor API must not send a secondary-window dialog to (0, 0).
    x, y = owner.winfo_rootx(), owner.winfo_rooty()
    return x, y, x+owner.winfo_width(), y+owner.winfo_height()


def place_dialog(dialog, owner, size, minimum, *, padding=12):
    """Measure the native frame while hidden, then position the visible content."""
    dialog.geometry(f"{size[0]}x{size[1]}")
    dialog.update_idletasks()
    side = max(0, dialog.winfo_rootx()-dialog.winfo_x())
    top = max(0, dialog.winfo_rooty()-dialog.winfo_y())
    left, upper, right, bottom = _work_area(owner)
    width = max(1, min(size[0], right-left-2*padding-2*side))
    height = max(1, min(size[1], bottom-upper-2*padding-top-side))
    dialog.minsize(min(minimum[0], width), min(minimum[1], height))
    x = owner.winfo_rootx()+(owner.winfo_width()-width)//2-side
    y = owner.winfo_rooty()+(owner.winfo_height()-height)//2-top
    x = max(left+padding, min(x, right-padding-width-2*side))
    y = max(upper+padding, min(y, bottom-padding-height-top-side))
    # "+-x" is Tk's absolute negative coordinate, unlike "-x" from the right.
    dialog.geometry(f"{width}x{height}+{x}+{y}")
