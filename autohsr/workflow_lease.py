"""One task workflow owns its whole sequence, including gaps between Runners."""
from contextlib import contextmanager
from contextvars import ContextVar
import ctypes as C
import threading

from .models import AutomationError

NAME = 'Local\\AutoHSR.TaskWorkflow'
_owner = ContextVar('autohsr_workflow_owner', default=None)


def _kernel():
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
    kernel.CreateMutexW.restype = C.c_void_p
    kernel.OpenMutexW.argtypes = [C.c_uint32, C.c_int, C.c_wchar_p]
    kernel.OpenMutexW.restype = C.c_void_p
    kernel.CloseHandle.argtypes = [C.c_void_p]
    return kernel


@contextmanager
def workflow_lease():
    if _owner.get() is not None:
        raise AutomationError('不能在运行中的任务流程里嵌套另一份任务流程。')
    kernel = _kernel()
    C.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, NAME)
    duplicate = C.get_last_error() == 183
    if not handle or duplicate:
        if handle:
            kernel.CloseHandle(handle)
        raise AutomationError('另一个任务流程仍在运行，请先停止。')
    token = _owner.set((handle, threading.get_ident()))
    try:
        yield
    finally:
        _owner.reset(token)
        kernel.CloseHandle(handle)


def require_workflow_access():
    """Native game entries admit only children running on the owning thread."""
    owner = _owner.get()
    if owner is not None and owner[1] == threading.get_ident():
        return
    kernel = _kernel()
    C.set_last_error(0)
    handle = kernel.OpenMutexW(0x00100000, False, NAME)  # SYNCHRONIZE, no creation
    error = C.get_last_error()
    if handle:
        kernel.CloseHandle(handle)
        raise AutomationError('任务流程持有执行权；请先停止流程再启动其他游戏任务。')
    if error not in (0, 2):
        raise AutomationError('无法核实任务流程的执行权，未访问游戏。')
