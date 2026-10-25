"""A passive, transparent native window for BetterGI-style scrolling logs.

Styles are applied at CreateWindowEx, before any possible activation. The
window owns only its surface; it never captures or sends input to the game.
"""
from __future__ import annotations

from collections import deque
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import time


def overlay_bounds(left, top, width, height):
    if width < 960 or height < 540:
        return None
    # BetterGI: status (20,790,480,24), log (20,822,480,188), at 1920x1080.
    return (left+round(width*20/1920), top+round(height*790/1080),
            round(width*480/1920), round(height*220/1080))


class BitmapHeader(C.Structure):
    _fields_ = [('size', W.DWORD), ('width', W.LONG), ('height', W.LONG),
                ('planes', W.WORD), ('bits', W.WORD), ('compression', W.DWORD),
                ('image_size', W.DWORD), ('xppm', W.LONG), ('yppm', W.LONG),
                ('colors', W.DWORD), ('important', W.DWORD)]


class Blend(C.Structure):
    _fields_ = [('operation', C.c_ubyte), ('flags', C.c_ubyte),
                ('opacity', C.c_ubyte), ('alpha', C.c_ubyte)]


class NativePresentation:
    def __init__(self, *, protect_capture=True):
        self.protect_capture = protect_capture
        self.user32 = C.WinDLL('user32', use_last_error=True)
        self.gdi32 = C.WinDLL('gdi32', use_last_error=True)
        self.user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
            C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
        self.user32.CreateWindowExW.restype = W.HWND
        self.user32.DestroyWindow.argtypes = [W.HWND]
        self.user32.ShowWindow.argtypes = [W.HWND, C.c_int]
        self.user32.GetForegroundWindow.restype = W.HWND
        self.user32.IsWindow.argtypes = [W.HWND]
        self.user32.IsIconic.argtypes = [W.HWND]
        self.user32.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        self.user32.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        self.user32.SetWindowDisplayAffinity.argtypes = [W.HWND, W.DWORD]
        self.user32.SetWindowDisplayAffinity.restype = W.BOOL
        self.user32.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
        self.user32.SetWindowPos.restype = W.BOOL
        self.get_style = self.user32.GetWindowLongPtrW
        self.get_style.argtypes, self.get_style.restype = [W.HWND, C.c_int], C.c_ssize_t
        self.user32.GetDC.argtypes, self.user32.GetDC.restype = [W.HWND], W.HDC
        self.user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
        self.gdi32.CreateCompatibleDC.argtypes, self.gdi32.CreateCompatibleDC.restype = [W.HDC], W.HDC
        self.gdi32.CreateDIBSection.argtypes = [W.HDC, C.c_void_p, W.UINT, C.POINTER(C.c_void_p), W.HANDLE, W.DWORD]
        self.gdi32.CreateDIBSection.restype = W.HBITMAP
        self.gdi32.SelectObject.argtypes, self.gdi32.SelectObject.restype = [W.HDC, W.HANDLE], W.HANDLE
        self.gdi32.DeleteObject.argtypes = [W.HANDLE]
        self.gdi32.DeleteDC.argtypes = [W.HDC]
        self.user32.UpdateLayeredWindow.argtypes = [W.HWND, W.HDC, C.POINTER(W.POINT), C.POINTER(W.SIZE),
            W.HDC, C.POINTER(W.POINT), W.DWORD, C.POINTER(Blend), W.DWORD]
        self.user32.UpdateLayeredWindow.restype = W.BOOL
        self.user32.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
        self.user32.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
        self.user32.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
        self.user32.DispatchMessageW.restype = C.c_ssize_t

    def create(self):
        # Layered, transparent, tool window, no activation, present from birth.
        handle = self.user32.CreateWindowExW(0x080800a0, 'Static', 'AutoHSR 日志字幕',
            0x80000000, 0, 0, 1, 1, None, None, None, None)
        if not handle:
            raise OSError(C.get_last_error(), '创建日志字幕失败')
        if self.protect_capture and not self.user32.SetWindowDisplayAffinity(handle, 0x11):
            self.user32.DestroyWindow(handle)
            raise OSError(C.get_last_error(), '日志字幕无法从识别截图排除')
        return handle

    def game_bounds(self, handle):
        if (type(handle) is not int or not self.user32.IsWindow(handle)
                or self.user32.IsIconic(handle) or self.user32.GetForegroundWindow() != handle):
            return None
        rect, point = W.RECT(), W.POINT()
        if not self.user32.GetClientRect(handle, C.byref(rect)) or not self.user32.ClientToScreen(handle, C.byref(point)):
            return None
        return point.x, point.y, rect.right-rect.left, rect.bottom-rect.top

    def paint(self, handle, bounds, pixels):
        screen = self.user32.GetDC(None)
        memory = self.gdi32.CreateCompatibleDC(screen)
        bitmap = previous = None
        try:
            header = BitmapHeader(C.sizeof(BitmapHeader), bounds[2], -bounds[3], 1, 32, 0, 0, 0, 0, 0, 0)
            storage = C.c_void_p()
            bitmap = self.gdi32.CreateDIBSection(memory, C.byref(header), 0, C.byref(storage), None, 0)
            if not bitmap or not storage:
                raise OSError(C.get_last_error(), '日志字幕绘制失败')
            previous = self.gdi32.SelectObject(memory, bitmap)
            C.memmove(storage, pixels, len(pixels))
            if not self.user32.UpdateLayeredWindow(handle, screen, C.byref(W.POINT(*bounds[:2])),
                    C.byref(W.SIZE(*bounds[2:])), memory, C.byref(W.POINT()), 0,
                    C.byref(Blend(0, 0, 255, 1)), 2):
                raise OSError(C.get_last_error(), '日志字幕更新失败')
        finally:
            if previous:
                self.gdi32.SelectObject(memory, previous)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(memory)
            self.user32.ReleaseDC(None, screen)

    def show(self, handle, bounds):
        if not self.user32.SetWindowPos(handle, W.HWND(-1), *bounds, 0x0010 | 0x0040):
            raise OSError(C.get_last_error(), '日志字幕定位失败')

    def hide(self, handle):
        self.user32.ShowWindow(handle, 0)

    def destroy(self, handle):
        self.user32.DestroyWindow(handle)

    def pump(self):
        message = W.MSG()
        while self.user32.PeekMessageW(C.byref(message), None, 0, 0, 1):
            self.user32.TranslateMessage(C.byref(message))
            self.user32.DispatchMessageW(C.byref(message))


class GameLogOverlay:
    def __init__(self, root, game_handle, warn, *, presentation=None):
        self.root, self.game_handle, self.warn = root, game_handle, warn
        self.presentation = presentation or NativePresentation()
        self.lines = deque(maxlen=40)
        self.enabled, self.active, self.visible, self.closed = True, False, False, False
        self.status, self.linger_until = '准备就绪', 0.0
        self._bounds, self._timer, self._dirty = None, None, True
        try:
            self.handle = self.presentation.create()
        except OSError as error:
            self.handle = None
            warn(f'日志字幕已隐藏，以免影响游戏识别：{error}', 'warning')
        self._tick()

    def begin(self, status):
        self.lines.clear()
        self.active, self.linger_until = True, 0.0
        self.set_status(status)

    def append(self, message, level='info'):
        tag = {'info': 'INF', 'warning': 'WRN', 'error': 'ERR'}.get(level, 'INF')
        self.lines.append((f"[{time.strftime('%H:%M:%S')} {tag}] {message}", level))
        self._dirty = True

    def set_status(self, value):
        if self.status != value:
            self.status, self._dirty = value, True

    def set_enabled(self, value):
        self.enabled = bool(value)
        if not self.enabled:
            self._hide()

    def finish(self, status):
        self.active, self.linger_until = False, time.monotonic()+6
        self.set_status(status)

    def _hide(self):
        if self.visible:
            self.presentation.hide(self.handle)
            self.visible = False

    def _render(self, bounds, game_width):
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        width, height = bounds[2:]
        size = max(12, round(12*game_width/1920))
        fonts = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'
        font = ImageFont.truetype(str(fonts/'msyh.ttc'), size)
        image = Image.new('RGBA', (width, height))
        shadow = Image.new('RGBA', image.size)
        draw, shade = ImageDraw.Draw(image), ImageDraw.Draw(shadow)
        gap, line_height = max(1, round(size*.12)), round(size*1.45)

        def wrap(text):
            result, current = [], ''
            for char in text:
                if char == '\n' or (current and draw.textlength(current+char, font=font) > width-4):
                    result.append(current)
                    current = ''
                if char != '\n':
                    current += char
            return result+[current] if current else result

        def text(y, value, color):
            shade.text((1, y+1), value, font=font, fill=(0, 0, 0, 160))
            draw.text((0, y), value, font=font, fill=color)

        heading = wrap(f'AutoHSR · {self.status} | F9 暂停 F10 停止')
        for index, row in enumerate(heading):
            text(index*line_height, row, '#90ee90')
        start = max(round(32*game_width/1920), len(heading)*line_height+gap)
        rows = [(row, level) for value, level in self.lines for row in wrap(value)]
        count = max(0, (height-start)//(line_height+gap))
        colors = {'info': '#d3d3d3', 'warning': '#ffda82', 'error': '#ff9393'}
        for index, (row, level) in enumerate(rows[-count:] if count else []):
            text(start+index*(line_height+gap), row, colors.get(level, colors['info']))
        image = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(.7)), image)
        # UpdateLayeredWindow expects premultiplied BGRA, including text edges.
        return image.convert('RGBa').tobytes('raw', 'BGRa')

    def _tick(self):
        if self.closed:
            return
        try:
            game = self.presentation.game_bounds(self.game_handle()) if self.handle else None
            bounds = overlay_bounds(*game) if game else None
            if (not self.enabled or not self.handle or not bounds
                    or not (self.active or time.monotonic() < self.linger_until)):
                self._hide()
            else:
                if bounds != self._bounds:
                    self._bounds, self._dirty = bounds, True
                if self._dirty:
                    self.presentation.paint(self.handle, bounds, self._render(bounds, game[2]))
                    self._dirty = False
                self.presentation.show(self.handle, bounds)
                self.visible = True
        except (OSError, ValueError) as error:
            self._hide()
            self.enabled = False
            self.warn(f'日志字幕已隐藏，文件日志继续保留：{error}', 'warning')
        if self.root is not None:
            self._timer = self.root.after(200, self._tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self._timer is not None:
            self.root.after_cancel(self._timer)
        if self.handle:
            self.presentation.destroy(self.handle)
