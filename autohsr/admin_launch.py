"""Opt-in, per-user/per-installation elevated GUI launcher. No game operations.

Task Scheduler stores the authorization; config.json never acts as permission.
The task has no triggers, accepts no caller arguments, and uses an interactive
token for the same administrator account (no password or SYSTEM service).
"""
from __future__ import annotations

import base64
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import dataclass

from .config import ROOT


class AdminLaunchError(RuntimeError):
    pass


def is_admin() -> bool:
    return bool(C.windll.shell32.IsUserAnAdmin())


def current_sid() -> str:
    kernel = C.WinDLL("kernel32", use_last_error=True)
    advapi = C.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.LocalFree.argtypes = [C.c_void_p]
    advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    token, length, sid_text = W.HANDLE(), W.DWORD(), W.LPWSTR()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, C.byref(token)):
        raise C.WinError(C.get_last_error())
    try:
        advapi.GetTokenInformation(token, 1, None, 0, C.byref(length))
        buffer = C.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 1, buffer, length, C.byref(length)):
            raise C.WinError(C.get_last_error())
        sid_pointer = C.cast(buffer, C.POINTER(C.c_void_p))[0]
        if not advapi.ConvertSidToStringSidW(sid_pointer, C.byref(sid_text)):
            raise C.WinError(C.get_last_error())
        try:
            return sid_text.value
        finally:
            kernel.LocalFree(C.cast(sid_text, C.c_void_p))
    finally:
        kernel.CloseHandle(token)


@dataclass(frozen=True)
class LaunchSpec:
    root: Path
    executable: Path
    prefix: tuple[str, ...]
    sid: str

    @property
    def task_name(self) -> str:
        key = f"{self.sid}|{os.path.normcase(str(self.root))}"
        return "AutoHSR-Admin-v1-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]

    @property
    def arguments(self) -> str:
        return subprocess.list2cmdline([*self.prefix, "--admin-task"])

    @property
    def description(self) -> str:
        return f"AutoHSR admin launcher v1 | {self.sid} | {self.root}"


def launch_spec() -> LaunchSpec:
    executable = Path(sys.executable).resolve()
    prefix: tuple[str, ...] = ()
    if not getattr(sys, "frozen", False):
        windowed = executable.with_name("pythonw.exe")
        if windowed.is_file():
            executable = windowed
        # Ignore inherited PYTHON* and user-site packages during elevation.
        prefix = ("-E", "-s", "-m", "autohsr")
    return LaunchSpec(ROOT.resolve(), executable, prefix, current_sid())


# Data is encoded separately; paths, quotes, $, backticks and non-ASCII names
# never become PowerShell code. Only the system PowerShell executable is used.
_TASK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$p = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($identity.User.Value -cne $p.sid) { throw 'Windows account changed; no task was modified.' }
    $accountAdmin = @($identity.Groups | ForEach-Object { $_.Value }) -contains 'S-1-5-32-544'
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $task = $null
    try { $task = $folder.GetTask($p.task_name) }
    catch {
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException }
        if ($e.HResult -ne -2147024894) { throw }
    }
    $owned = $task -and ($task.Definition.RegistrationInfo.Description -ceq $p.description)
    if ($p.operation -eq 'enable') {
        if (-not $accountAdmin) { throw 'The current Windows account must be an administrator.' }
        if ($task -and -not $owned) { throw 'A different task uses this name; it was not overwritten.' }
        $definition = $service.NewTask(0)
        $definition.RegistrationInfo.Description = $p.description
        $definition.Principal.UserId = $p.sid
        $definition.Principal.LogonType = 3
        $definition.Principal.RunLevel = 1
        $definition.Settings.Enabled = $true
        $definition.Settings.AllowDemandStart = $true
        $definition.Settings.DisallowStartIfOnBatteries = $false
        $definition.Settings.StopIfGoingOnBatteries = $false
        $definition.Settings.ExecutionTimeLimit = 'PT0S'
        $definition.Settings.MultipleInstances = 2
        $definition.Settings.AllowHardTerminate = $false
        $action = $definition.Actions.Create(0)
        $action.Path = $p.executable
        $action.Arguments = $p.arguments
        $action.WorkingDirectory = $p.root
        # TASK_CREATE_OR_UPDATE; interactive token, no stored password.
        $task = $folder.RegisterTaskDefinition($p.task_name, $definition, 6, $p.sid, $null, 3, $null)
        $owned = $true
    }
    if ($p.operation -eq 'disable' -and $task) {
        if (-not $owned) { throw 'Task ownership could not be verified; it was not deleted.' }
        # Deleting registration does not terminate a running assistant.
        $folder.DeleteTask($p.task_name, 0)
        $task = $null
    }
    $valid = $false
    if ($task -and $owned) {
        $d = $task.Definition
        $user = $d.Principal.UserId
        if (-not $user.StartsWith('S-1-')) {
            $user = ([Security.Principal.NTAccount]$user).Translate([Security.Principal.SecurityIdentifier]).Value
        }
        $a = $d.Actions.Item(1)
        $valid = $d.Actions.Count -eq 1 -and $a.Type -eq 0 -and
            $a.Path -ieq $p.executable -and $a.Arguments -ceq $p.arguments -and
            $a.WorkingDirectory -ieq $p.root -and $user -ceq $p.sid -and
            $d.Principal.LogonType -eq 3 -and $d.Principal.RunLevel -eq 1 -and
            $d.Triggers.Count -eq 0 -and $d.Settings.AllowDemandStart -and
            $d.Settings.MultipleInstances -eq 2 -and $d.Settings.ExecutionTimeLimit -eq 'PT0S' -and
            -not $d.Settings.DisallowStartIfOnBatteries -and -not $d.Settings.StopIfGoingOnBatteries -and
            -not $d.Settings.AllowHardTerminate
    }
    $enabled = $task -and $valid -and $task.Enabled
    if ($p.operation -eq 'run') {
        if (-not $enabled) { throw 'The registered launcher is disabled or no longer matches this installation.' }
        $null = $task.Run($null)
    }
    @{ exists = [bool]$task; valid = [bool]$valid; enabled = [bool]$enabled;
       account_is_admin = [bool]$accountAdmin; task_name = $p.task_name } | ConvertTo-Json -Compress
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
}
"""


def _task(operation: str, spec: LaunchSpec) -> dict:
    if operation not in ("status", "enable", "disable", "run"):
        raise ValueError("未知管理员启动操作。")
    payload = dict(operation=operation, task_name=spec.task_name, description=spec.description,
                   root=str(spec.root), executable=str(spec.executable), arguments=spec.arguments, sid=spec.sid)
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    script = _TASK_SCRIPT.replace("__PAYLOAD__", encoded)
    command = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    system = C.create_unicode_buffer(32768)
    if not C.windll.kernel32.GetSystemDirectoryW(system, len(system)):
        raise C.WinError()
    powershell = Path(system.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        data = json.loads(result.stdout.lstrip("\ufeff"))
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise AdminLaunchError(f"无法核实 Windows 管理员启动任务：{error}") from error
    if not isinstance(data, dict):
        raise AdminLaunchError("Windows 返回的启动任务状态不完整，未视为授权成功。")
    if result.returncode or "error" in data:
        raise AdminLaunchError("Windows 管理员启动操作失败：" + str(data.get("error", result.stderr.strip())))
    if (not isinstance(data, dict) or data.get("task_name") != spec.task_name or
            any(type(data.get(key)) is not bool for key in ("exists", "valid", "enabled", "account_is_admin")) or
            (data["enabled"] and not (data["exists"] and data["valid"]))):
        raise AdminLaunchError("Windows 返回的启动任务状态不完整，未视为授权成功。")
    return data


def status() -> dict:
    return _task("status", launch_spec())


def status_text(data: dict) -> str:
    if data["enabled"]:
        return "已启用 · 下次正常启动自动使用管理员权限"
    if data["exists"]:
        return "任务已禁用或路径已变化 · 请重新启用或移除"
    if not data["account_is_admin"]:
        return "未启用 · 需要当前 Windows 账户属于管理员组"
    return "未启用 · 首次开启需要 Windows 管理员授权"


def configure(operation: str, *, expected_sid: str | None = None) -> dict:
    if operation not in ("enable", "disable"):
        raise ValueError("请选择启用或移除管理员启动。")
    spec = launch_spec()
    if expected_sid is not None and spec.sid != expected_sid:
        raise AdminLaunchError("授权账户与当前登录账户不同，未修改启动任务。请使用当前账户的管理员权限。")
    before = _task("status", spec)
    if operation == "enable" and not before["account_is_admin"]:
        raise AdminLaunchError("此功能需要当前登录的 Windows 账户属于管理员组；不能借用其他账户授权。")
    if operation == "disable" and not before["exists"]:
        return before
    if not is_admin():
        _elevated_manage(spec, operation)
    else:
        _task(operation, spec)
    after = _task("status", spec)
    if (operation == "enable" and not after["enabled"]) or (operation == "disable" and after["exists"]):
        raise AdminLaunchError("操作后未能核实启动任务状态。请刷新状态后再检查，配置未自动保存。")
    return after


class _SHELLEXECUTEINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("fMask", C.c_ulong), ("hwnd", W.HWND),
                ("lpVerb", W.LPCWSTR), ("lpFile", W.LPCWSTR), ("lpParameters", W.LPCWSTR),
                ("lpDirectory", W.LPCWSTR), ("nShow", C.c_int), ("hInstApp", W.HINSTANCE),
                ("lpIDList", C.c_void_p), ("lpClass", W.LPCWSTR), ("hkeyClass", W.HKEY),
                ("dwHotKey", W.DWORD), ("hIcon", W.HANDLE), ("hProcess", W.HANDLE)]


def _elevated_manage(spec: LaunchSpec, operation: str) -> None:
    shell = C.WinDLL("shell32", use_last_error=True)
    kernel = C.WinDLL("kernel32", use_last_error=True)
    ole = C.WinDLL("ole32")
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    shell.ShellExecuteExW.argtypes = [C.POINTER(_SHELLEXECUTEINFO)]
    parameters = subprocess.list2cmdline([*spec.prefix, "--admin-launch", operation, "--admin-owner", spec.sid])
    info = _SHELLEXECUTEINFO(cbSize=C.sizeof(_SHELLEXECUTEINFO), fMask=0x40 | 0x100,
                            lpVerb="runas", lpFile=str(spec.executable), lpParameters=parameters,
                            lpDirectory=str(spec.root), nShow=0)
    initialized = ole.CoInitializeEx(None, 2) in (0, 1)
    try:
        if not shell.ShellExecuteExW(C.byref(info)):
            code = C.get_last_error()
            if code == 1223:
                raise AdminLaunchError("已取消 Windows 管理员授权，启动设置未改变。")
            raise AdminLaunchError(f"无法打开管理员授权：{C.WinError(code)}")
        try:
            deadline = time.monotonic() + 120
            while kernel.WaitForSingleObject(info.hProcess, 200) == 258:
                if time.monotonic() >= deadline:
                    raise AdminLaunchError("管理员操作等待超时，结果尚未核实。请刷新状态，不要重复授权。")
            code = W.DWORD()
            if not kernel.GetExitCodeProcess(info.hProcess, C.byref(code)) or code.value:
                raise AdminLaunchError("管理员操作未完成。请确认使用同一 Windows 账户，或检查系统任务计划程序策略。")
        finally:
            kernel.CloseHandle(info.hProcess)
    finally:
        if initialized:
            ole.CoUninitialize()


class TaskSession:
    """Named events live only while the GUI (or its waiting launcher) is alive."""
    def __init__(self, spec: LaunchSpec | None = None):
        spec = spec or launch_spec()
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
        self.kernel.CreateEventW.restype = W.HANDLE
        self.kernel.SetEvent.argtypes = [W.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.kernel.LocalFree.argtypes = [C.c_void_p]
        self.handles: list = []
        # Same account only; medium integrity lets the normal launcher contact
        # an existing elevated GUI even when that GUI created the events first.
        class SecurityAttributes(C.Structure):
            _fields_ = [("length", W.DWORD), ("descriptor", C.c_void_p), ("inherit", W.BOOL)]
        advapi = C.WinDLL("advapi32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.c_void_p]
        descriptor = C.c_void_p()
        sddl = f"D:(A;;GA;;;SY)(A;;GA;;;{spec.sid})S:(ML;;NW;;;ME)"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None):
            raise AdminLaunchError(f"无法限定启动反馈的账户权限：{C.WinError(C.get_last_error())}")
        security = SecurityAttributes(C.sizeof(SecurityAttributes), descriptor, False)
        try:
            for suffix, manual in (("Ready", True), ("Activate", False)):
                handle = self.kernel.CreateEventW(C.byref(security), manual, False, "Local\\" + spec.task_name + suffix)
                if not handle:
                    raise AdminLaunchError(f"无法建立管理员启动反馈：{C.WinError(C.get_last_error())}")
                self.handles.append(handle)
        except Exception:
            self.close()
            raise
        finally:
            self.kernel.LocalFree(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        for handle in self.handles:
            self.kernel.CloseHandle(handle)
        self.handles.clear()

    def wait_ready(self, timeout_ms: int = 20000) -> bool:
        return self.kernel.WaitForSingleObject(self.handles[0], timeout_ms) == 0

    def activate(self) -> None:
        self.kernel.SetEvent(self.handles[1])

    def attach(self, root, restore) -> None:
        def poll():
            if self.kernel.WaitForSingleObject(self.handles[1], 0) == 0:
                restore()
            root.after(300, poll)
        root.after(0, lambda: self.kernel.SetEvent(self.handles[0]))
        root.after(300, poll)


def handoff() -> bool:
    """Only default GUI startup may call this; never forward game/CLI arguments."""
    if is_admin():
        return False
    spec = launch_spec()
    data = _task("status", spec)
    if not data["exists"]:
        return False
    if not data["enabled"]:
        raise AdminLaunchError("管理员启动任务已禁用或与当前路径不符。可用 --no-admin-launch 打开设置，重新启用或移除。")
    with TaskSession(spec) as session:
        # A GUI can outlive task removal/re-registration. Reuse its live
        # feedback channel before asking Scheduler to start another process.
        if not session.wait_ready(0):
            _task("run", spec)
            if not session.wait_ready():
                raise AdminLaunchError("已发送管理员启动请求，但未收到界面就绪反馈；请检查任务栏或用 --no-admin-launch 排查。")
        session.activate()
    return True
