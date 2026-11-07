"""Windows notification-area icon and its native context menu."""

import ctypes as C
from ctypes import wintypes as W
from uuid import uuid4


_CALLBACK = 0x8001
_ICON_ID = 1
_NIM_ADD, _NIM_DELETE, _NIM_SETFOCUS, _NIM_SETVERSION = 0, 2, 3, 4
_NIN_SELECT, _NIN_KEYSELECT = 0x400, 0x401
_WM_CONTEXTMENU, _WM_LBUTTONDBLCLK, _WM_RBUTTONUP = 0x7b, 0x203, 0x205
_PROCEDURE = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class _IconData(C.Structure):
    _fields_ = [('size', W.DWORD), ('window', W.HWND), ('id', W.UINT), ('flags', W.UINT),
                ('message', W.UINT), ('icon', W.HANDLE), ('tip', W.WCHAR * 128),
                ('state', W.DWORD), ('mask', W.DWORD), ('info', W.WCHAR * 256),
                ('version', W.UINT), ('title', W.WCHAR * 64), ('info_flags', W.DWORD),
                ('guid', C.c_ubyte * 16), ('balloon', W.HANDLE)]


class _WindowClass(C.Structure):
    _fields_ = [('style', W.UINT), ('procedure', _PROCEDURE), ('cls_extra', C.c_int),
                ('win_extra', C.c_int), ('instance', W.HINSTANCE), ('icon', W.HANDLE),
                ('cursor', W.HANDLE), ('background', W.HANDLE), ('menu', W.LPCWSTR),
                ('name', W.LPCWSTR)]


def _bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


class NativeTray:
    """Own one icon and an invisible message window on the Tk thread."""

    def __init__(self, icon, dispatch):
        self.dispatch = dispatch
        self.visible = self.modern = False
        self.window = self.icon = None
        self.atom = 0
        self.name = 'AutoHSR.Tray.' + uuid4().hex
        user = C.WinDLL('user32', use_last_error=True)
        shell = C.WinDLL('shell32', use_last_error=True)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        self._notify = _bind(shell, 'Shell_NotifyIconW', W.BOOL, W.DWORD, C.POINTER(_IconData))
        self._default = _bind(user, 'DefWindowProcW', C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self._destroy = _bind(user, 'DestroyWindow', W.BOOL, W.HWND)
        self._unregister = _bind(user, 'UnregisterClassW', W.BOOL, W.LPCWSTR, W.HINSTANCE)
        self._free_icon = _bind(user, 'DestroyIcon', W.BOOL, W.HANDLE)
        self._new_menu = _bind(user, 'CreatePopupMenu', W.HMENU)
        self._append = _bind(user, 'AppendMenuW', W.BOOL, W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR)
        self._free_menu = _bind(user, 'DestroyMenu', W.BOOL, W.HMENU)
        self._popup = _bind(user, 'TrackPopupMenu', W.BOOL, W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int,
                            W.HWND, C.c_void_p)
        self._cursor = _bind(user, 'GetCursorPos', W.BOOL, C.POINTER(W.POINT))
        self._foreground = _bind(user, 'SetForegroundWindow', W.BOOL, W.HWND)
        self._post = _bind(user, 'PostMessageW', W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self._shell_ready = _bind(user, 'RegisterWindowMessageW', W.UINT, W.LPCWSTR)('TaskbarCreated')
        self.instance = _bind(kernel, 'GetModuleHandleW', W.HINSTANCE, W.LPCWSTR)(None)
        self._procedure = _PROCEDURE(self._receive)
        register = _bind(user, 'RegisterClassW', W.ATOM, C.POINTER(_WindowClass))
        create = _bind(user, 'CreateWindowExW', W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                       C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p)
        load = _bind(user, 'LoadImageW', W.HANDLE, W.HINSTANCE, W.LPCWSTR, W.UINT,
                     C.c_int, C.c_int, W.UINT)
        allow = _bind(user, 'ChangeWindowMessageFilterEx', W.BOOL, W.HWND, W.UINT, W.DWORD, C.c_void_p)
        try:
            self.icon = load(None, str(icon), 1, 0, 0, 0x50)
            if not self.icon:
                raise C.WinError(C.get_last_error())
            self.atom = register(C.byref(_WindowClass(procedure=self._procedure,
                                                     instance=self.instance, name=self.name)))
            if not self.atom:
                raise C.WinError(C.get_last_error())
            self.window = create(0x80, self.name, 'AutoHSR Tray', 0, 0, 0, 0, 0,
                                 None, None, self.instance, None)
            if not self.window:
                raise C.WinError(C.get_last_error())
            # Explorer can have lower integrity than the administrator GUI.
            # Limit its messages to this window and the two tray notifications.
            for message in (_CALLBACK, self._shell_ready):
                if not message or not allow(self.window, message, 1, None):
                    raise C.WinError(C.get_last_error())
        except OSError:
            self.close()
            raise

    def _data(self):
        return _IconData(size=C.sizeof(_IconData), window=self.window, id=_ICON_ID, flags=0x87,
                         message=_CALLBACK, icon=self.icon, tip='AutoHSR', version=4)

    def show(self):
        if not self.visible:
            data = self._data()
            self.visible = bool(self._notify(_NIM_ADD, C.byref(data)))
            if self.visible:
                self.modern = bool(self._notify(_NIM_SETVERSION, C.byref(data)))
        return self.visible

    def hide(self):
        if self.visible:
            self._notify(_NIM_DELETE, C.byref(self._data()))
            self.visible = False

    def close(self):
        self.hide()
        if self.window:
            self._destroy(self.window)
            self.window = None
        if self.atom:
            self._unregister(self.name, self.instance)
            self.atom = 0
        if self.icon:
            self._free_icon(self.icon)
            self.icon = None

    def _menu(self):
        menu = self._new_menu()
        if not menu:
            return
        try:
            point = W.POINT()
            if not self._cursor(C.byref(point)):
                return
            if not (self._append(menu, 0, 1, '打开助手') and self._append(menu, 0, 2, '退出助手')):
                return
            self._foreground(self.window)
            selection = self._popup(menu, 0x102, point.x, point.y, 0, self.window, None)
            self._post(self.window, 0, 0, 0)
            if selection in (1, 2):
                self.dispatch('open' if selection == 1 else 'exit')
            else:
                self._notify(_NIM_SETFOCUS, C.byref(self._data()))
        finally:
            self._free_menu(menu)

    def _receive(self, window, message, wparam, lparam):
        if message == self._shell_ready and self._shell_ready and self.visible:
            self.visible = False
            if not self.show():
                self.dispatch('unavailable')
            return 0
        if message == _CALLBACK and self.visible:
            icon_id = (lparam >> 16) & 0xffff if self.modern else wparam
            if icon_id != _ICON_ID:
                return 0
            event = lparam & 0xffff
            if event in ((_NIN_SELECT, _NIN_KEYSELECT) if self.modern else (_WM_LBUTTONDBLCLK,)):
                self.dispatch('open')
            elif event == (_WM_CONTEXTMENU if self.modern else _WM_RBUTTONUP):
                self._menu()
            return 0
        return self._default(window, message, wparam, lparam)
