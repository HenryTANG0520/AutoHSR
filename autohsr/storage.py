"""Atomic publication and stable Windows evidence reads."""
from contextlib import ExitStack, contextmanager, nullcontext
import os
from pathlib import Path
from stat import S_ISREG
import time


REPLACE_RETRY_DELAYS=(.02,.04,.08,.16,.32,.50)


if os.name == 'nt':
    import ctypes as C
    from ctypes import wintypes as W
    from msvcrt import get_osfhandle

    class _FileBasicInfo(C.Structure):
        _fields_ = [('creation', C.c_longlong), ('access', C.c_longlong),
                    ('write', C.c_longlong), ('change', C.c_longlong), ('attributes', W.DWORD)]

    _kernel32 = C.WinDLL('kernel32', use_last_error=True)
    _get_file_basic_info = _kernel32.GetFileInformationByHandleEx
    _get_file_basic_info.argtypes = [W.HANDLE, C.c_int, C.POINTER(_FileBasicInfo), W.DWORD]
    _get_file_basic_info.restype = W.BOOL
    _open_file = _kernel32.CreateFileW
    _open_file.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    _open_file.restype = W.HANDLE
    _close_file = _kernel32.CloseHandle
    _close_file.argtypes = [W.HANDLE]
    _close_file.restype = W.BOOL
    _INVALID_FILE = W.HANDLE(-1).value


@contextmanager
def hold_read_sources(paths):
    """Keep local evidence readable with Windows sharing limited to readers."""
    with ExitStack() as handles:
        if os.name == 'nt':
            for value in dict.fromkeys(paths):
                path = Path(value).resolve(strict=True)
                if not path.is_file():
                    raise OSError('证据来源不是普通文件。')
                # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
                handle = _open_file(str(path), 0x80000000, 0x1, None, 3, 0x80, None)
                if handle == _INVALID_FILE:
                    raise C.WinError(C.get_last_error())
                handles.callback(_close_file, handle)
        yield


def file_revision(path: str | Path) -> tuple[int, int, int, int, int]:
    """Observe file identity and revision metadata without reading the contents."""
    with Path(path).open('rb') as stream:
        descriptor = stream.fileno()
        metadata = os.fstat(descriptor)
        if not S_ISREG(metadata.st_mode) or not metadata.st_ino:
            raise OSError('文件身份不可核实。')
        change = metadata.st_ctime_ns
        if os.name == 'nt':
            # Python 3.12's Windows st_ctime is creation time. Use the actual
            # change time so restoring mtime does not hide a regular edit.
            info = _FileBasicInfo()
            if not _get_file_basic_info(get_osfhandle(descriptor), 0, C.byref(info), C.sizeof(info)):
                raise C.WinError(C.get_last_error())
            change = info.change
        if not change:
            raise OSError('文件修订时间不可核实。')
        return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, change


def replace_file(source, destination, *, before_replace=None, attempt_scope=nullcontext):
    """Retry the rename, entering the optional scope for each attempt."""
    source,destination=Path(source),Path(destination)
    for attempt in range(len(REPLACE_RETRY_DELAYS)+1):
        if before_replace is not None:
            before_replace()
        with attempt_scope():
            try:
                source.replace(destination)
                return
            except OSError as error:
                sharing=isinstance(error,PermissionError) or getattr(error,'winerror',None) in (5,32,33)
                if not sharing or attempt==len(REPLACE_RETRY_DELAYS):
                    raise
        time.sleep(REPLACE_RETRY_DELAYS[attempt])
