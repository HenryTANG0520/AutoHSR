"""Explicit Windows integration check; registers only an on-demand GUI task.

Run elevated. Uses this user's Explorer token to test ordinary desktop startup.
Never starts a game. Only newly created AutoHSR test windows are closed.
"""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autohsr import admin_launch as admin
from autohsr.windows import ENUMPROC, is_elevated, process_path, user32


def windows(executable):
    found = {}
    # A venv's pythonw.exe is a redirector; the GUI window belongs to the
    # base interpreter process it starts, while the scheduled action stays venv.
    executables = {executable}
    if executable.name.lower().startswith('python'):
        executables.add(Path(sys._base_executable).with_name(executable.name))
    @ENUMPROC
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = C.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, len(title))
            if title.value.startswith('AutoHSR ·') and Path(process_path(hwnd)) in executables:
                pid = W.DWORD()
                user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
                found[int(hwnd)] = pid.value
        return True
    user32.EnumWindows(collect, 0)
    return found


class STARTUPINFO(C.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                ('x', W.DWORD), ('y', W.DWORD), ('width', W.DWORD), ('height', W.DWORD),
                ('xchars', W.DWORD), ('ychars', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                ('show', W.WORD), ('reserved_size', W.WORD), ('reserved_data', C.c_void_p),
                ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]


class PROCESSINFO(C.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]


def ordinary_start(spec):
    """Launch with the interactive desktop shell's unelevated primary token."""
    kernel = C.WinDLL('kernel32', use_last_error=True)
    advapi = C.WinDLL('advapi32', use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    advapi.DuplicateTokenEx.argtypes = [W.HANDLE, W.DWORD, C.c_void_p, C.c_int, C.c_int, C.POINTER(W.HANDLE)]
    advapi.CreateProcessWithTokenW.argtypes = [W.HANDLE, W.DWORD, W.LPCWSTR, W.LPWSTR, W.DWORD,
                                             C.c_void_p, W.LPCWSTR, C.POINTER(STARTUPINFO), C.POINTER(PROCESSINFO)]
    user32.GetShellWindow.restype = W.HWND
    pid, token, duplicate, length, elevated = W.DWORD(), W.HANDLE(), W.HANDLE(), W.DWORD(), W.DWORD()
    user32.GetWindowThreadProcessId(user32.GetShellWindow(), C.byref(pid))
    process = kernel.OpenProcess(0x1000, False, pid.value)
    info = PROCESSINFO()
    try:
        if not process or not advapi.OpenProcessToken(process, 0xA, C.byref(token)):
            raise C.WinError(C.get_last_error())
        if not advapi.GetTokenInformation(token, 20, C.byref(elevated), C.sizeof(elevated), C.byref(length)):
            raise C.WinError(C.get_last_error())
        assert not elevated.value, 'Explorer token is elevated; this would not test ordinary startup'
        if not advapi.DuplicateTokenEx(token, 0x2000000, None, 2, 1, C.byref(duplicate)):
            raise C.WinError(C.get_last_error())
        startup = STARTUPINFO(cb=C.sizeof(STARTUPINFO), desktop='winsta0\\default')
        command = C.create_unicode_buffer(subprocess.list2cmdline([str(spec.executable), *spec.prefix]))
        if not advapi.CreateProcessWithTokenW(duplicate, 1, str(spec.executable), command, 0x8000000,
                                             None, str(spec.root), C.byref(startup), C.byref(info)):
            raise C.WinError(C.get_last_error())
        assert kernel.WaitForSingleObject(info.process, 30000) == 0, 'Ordinary launcher did not finish'
        code = W.DWORD()
        assert kernel.GetExitCodeProcess(info.process, C.byref(code)) and code.value == 0, f'Launcher exit: {code.value}'
        return info.pid
    finally:
        for handle in (info.thread, info.process, duplicate, token, process):
            if handle:
                kernel.CloseHandle(handle)


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.1)
    raise AssertionError('Expected Windows state was not observed')


def fingerprint(spec):
    # Preserve config, ledgers and JSON reports. Raw capture archives can be
    # enormous; opening the GUI never writes them and need not rehash pixels.
    paths = list((spec.root / 'runs').rglob('*.json'))
    paths += [spec.root / 'config.json', spec.root / 'dungeons.local.json']
    return {str(p.relative_to(spec.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--keep-enabled', action='store_true')
    args = parser.parse_args()
    assert admin.is_admin(), 'Run this integration check elevated'
    if args.package:
        executable = args.package.resolve(strict=True)
        spec = admin.LaunchSpec(executable.parent, executable, (), admin.current_sid())
    else:
        spec = admin.launch_spec()
    initial = admin._task('status', spec)
    baseline = windows(spec.executable)
    assert not baseline, 'Close idle AutoHSR windows before running this check'
    before = fingerprint(spec)
    print(f'Preserved JSON/config baseline: {len(before)} files', flush=True)
    checks, launchers, guis = [], [], []
    user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    try:
        for operation in ('enable', 'disable', 'enable'):
            result = subprocess.run([str(spec.executable), *spec.prefix, '--admin-launch', operation],
                                    cwd=spec.root, timeout=30, capture_output=True)
            assert result.returncode == 0, f'{operation} failed'
            data = admin._task('status', spec)
            assert data['enabled'] == (operation == 'enable')
            assert data['exists'] == (operation == 'enable')
            checks.append(operation + '_verified')
            print(checks[-1], flush=True)
        # Two independent launches, plus opening an already running GUI.
        for index in range(2):
            launchers.append(ordinary_start(spec))
            visible = wait_for(lambda: windows(spec.executable))
            assert len(visible) == 1
            hwnd, gui_pid = next(iter(visible.items()))
            assert is_elevated(hwnd) is True
            guis.append(gui_pid)
            checks.append(f'ordinary_start_{index + 1}_opened_elevated_gui')
            print(checks[-1], flush=True)
            launchers.append(ordinary_start(spec))
            assert windows(spec.executable) == visible, 'Duplicate GUI created'
            checks.append(f'ordinary_repeat_{index + 1}_reused_gui')
            user32.PostMessageW(hwnd, 0x10, 0, 0)
            wait_for(lambda: not windows(spec.executable))
            # Let Task Scheduler observe the GUI's exit before the next launch.
            time.sleep(.4)
        assert before == fingerprint(spec), 'Config or existing evidence changed'
        checks.append('configuration_and_existing_evidence_unchanged')
        success = True
    finally:
        for hwnd in set(windows(spec.executable)) - set(baseline):
            user32.PostMessageW(hwnd, 0x10, 0, 0)
        if not args.keep_enabled and not initial['exists']:
            admin._task('disable', spec)
    report = dict(success=success, package=bool(args.package), game_started=False,
                  task=admin._task('status', spec), checks=checks, ordinary_launcher_pids=launchers,
                  elevated_gui_pids=guis, preserved_files=len(before))
    output = ROOT / 'runs' / ('admin-launch-package.json' if args.package else 'admin-launch-source.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
