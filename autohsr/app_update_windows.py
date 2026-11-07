"""Windows process and writer guards for portable installation updates."""

from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
from hashlib import sha256
import os
from pathlib import Path

from .app_update import UpdateError
from .workflow_lease import _kernel


@contextmanager
def install_lock(root):
    key = sha256(os.path.normcase(str(root)).encode('utf-8')).hexdigest()
    kernel = _kernel()
    C.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, 'Local\\AutoHSR.Install.' + key)
    duplicate = C.get_last_error() == 183
    try:
        if not handle or duplicate:
            raise UpdateError('installation_update_busy')
        yield
    finally:
        if handle:
            kernel.CloseHandle(handle)


class _Process(C.Structure):
    _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD), ('heap', C.c_size_t),
                ('module', W.DWORD), ('threads', W.DWORD), ('parent', W.DWORD), ('priority', W.LONG),
                ('flags', W.DWORD), ('name', W.WCHAR * 260)]


def require_closed(*executables):
    """Fail closed if a matching executable might still be running."""
    targets = {os.path.normcase(str(path)) for path in executables}
    kernel = _kernel()
    kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
    for function in (kernel.Process32FirstW, kernel.Process32NextW):
        function.argtypes = [W.HANDLE, C.POINTER(_Process)]
        function.restype = W.BOOL
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = W.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot in (None, W.HANDLE(-1).value):
        raise UpdateError('installation_process_unverified')
    try:
        entry = _Process(size=C.sizeof(_Process))
        found = kernel.Process32FirstW(snapshot, C.byref(entry))
        while found:
            if entry.name.casefold() == 'autohsr.exe':
                handle = kernel.OpenProcess(0x1000, False, entry.pid)
                if not handle and C.get_last_error() != 87:  # Process may have exited since the snapshot.
                    raise UpdateError('installation_process_unverified')
                if handle:
                    try:
                        name = C.create_unicode_buffer(32768)
                        length = W.DWORD(len(name))
                        if not kernel.QueryFullProcessImageNameW(handle, 0, name, C.byref(length)):
                            raise UpdateError('installation_process_unverified')
                        if os.path.normcase(str(Path(name.value).resolve())) in targets:
                            raise UpdateError('installation_running')
                    finally:
                        kernel.CloseHandle(handle)
            found = kernel.Process32NextW(snapshot, C.byref(entry))
        if C.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise UpdateError('installation_process_unverified')
    finally:
        kernel.CloseHandle(snapshot)
