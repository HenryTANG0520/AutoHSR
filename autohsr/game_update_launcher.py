"""Bind an official package offer to a verified Windows launcher handoff."""

from dataclasses import dataclass, field
import base64
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import re
import subprocess
import time

from .game_installation import installed_client, version_parts
from .game_update_status import check_game_update
from .models import AutomationError
from .redemption_server import HYP_KEYS, ServerResolution, _native_reader, _path, resolve
from .workflow_lease import native_idle_lease


_PUBLISHERS = {'cn': 'miHoYo Co.,Ltd.', 'global': 'COGNOSPHERE PTE. LTD.'}
_GAMES = {'cn': 'hkrpg_cn', 'global': 'hkrpg_global'}
_SIGNATURE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1')
$signature = Get-AuthenticodeSignature -LiteralPath $env:AUTOHSR_GAME_LAUNCHER_FILE
if ($signature.Status -ne 'Valid') { exit 1 }
$signature.SignerCertificate.GetNameInfo('SimpleName', $false)
"""


@dataclass(frozen=True)
class _Source:
    client: dict
    server: ServerResolution
    launcher: Path
    launcher_identity: tuple


@dataclass(frozen=True)
class LauncherOffer:
    channel: str
    action: str
    target: str
    source: _Source = field(repr=False)


class InstallationSourceChanged(AutomationError):
    pass


def _source(game_path, channel):
    client = installed_client(game_path)
    server = resolve(client['executable'])
    if server.server != channel:
        raise AutomationError('所选清单渠道与当前星铁安装不符。')
    try:
        key = dict(HYP_KEYS)[channel].rsplit('\\', 1)[0]
        value = _native_reader(key, 'InstallPath')
        root = _path(value, 'invalid_install_path').resolve(strict=True)
        if not re.fullmatch('[A-Za-z]:', root.drive):
            raise ValueError('launcher must be on a local drive')
        launcher = (root / 'launcher.exe').resolve(strict=True)
        if launcher.parent != root or launcher.name.casefold() != 'launcher.exe' or not launcher.is_file():
            raise ValueError('unexpected launcher')
        stat = launcher.stat()
    except (OSError, ValueError, RuntimeError, AutomationError):
        raise AutomationError('无法核实该渠道的官方启动器安装。') from None
    return _Source(client, server, launcher, (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))


def _target(report, action):
    if action == 'update' and report['update'] == 'available':
        return report['release_version']
    if action == 'pre_download' and report['pre_download'] == 'advertised':
        return report['pre_download_version']
    return None


def prepare_launcher(game_path, channel, action):
    """Read the current offer without running a launcher or issuing input."""
    if action not in ('update', 'pre_download'):
        raise ValueError('请选择游戏更新或预下载。')
    report = check_game_update(game_path, channel)
    target = _target(report, action)
    if target is None:
        return report, None
    try:
        source = _source(game_path, channel)
    except AutomationError:
        return dict(report, launcher='unverified'), None
    if source.client['full_version'] != report['installed_version']:
        return dict(report, launcher='installation_changed'), None
    return report, LauncherOffer(channel, action, target, source)


def _verify_publisher(launcher, channel):
    system = C.create_unicode_buffer(32768)
    if not C.windll.kernel32.GetSystemDirectoryW(system, len(system)):
        raise AutomationError('无法核实启动器的 Windows 签名。')
    powershell = Path(system.value) / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    command = base64.b64encode(_SIGNATURE.encode('utf-16le')).decode('ascii')
    env = dict(os.environ, AUTOHSR_GAME_LAUNCHER_FILE=str(launcher))
    try:
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', command],
                                capture_output=True, encoding='utf-8', errors='replace', timeout=12,
                                creationflags=subprocess.CREATE_NO_WINDOW, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise AutomationError('无法核实启动器的 Windows 签名。') from None
    if result.returncode or result.stdout.strip() != _PUBLISHERS[channel]:
        raise AutomationError('启动器的 Windows 签名与所选渠道不符。')


def _open(launcher, channel):
    shell = C.WinDLL('shell32', use_last_error=True)
    execute = shell.ShellExecuteW
    execute.argtypes = [W.HWND, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_int]
    execute.restype = C.c_ssize_t
    if execute(None, 'open', str(launcher), f'--game={_GAMES[channel]}', str(launcher.parent), 1) <= 32:
        raise AutomationError('Windows 未能打开官方启动器。')


def handoff(offer, *, cancelled=lambda: False):
    """Send one shell request after rechecking the offer and source."""
    path = offer.source.client['executable']
    stopped = dict(status='stopped', action=offer.action, channel=offer.channel, target=offer.target)
    if cancelled():
        return stopped
    report = check_game_update(path, offer.channel)
    if cancelled():
        return stopped
    if (_target(report, offer.action) != offer.target
            or report['installed_version'] != offer.source.client['full_version']):
        raise AutomationError('官方版本或安装已变化，请重新检查。')
    if _source(path, offer.channel) != offer.source:
        raise AutomationError('安装或启动器来源已变化，请重新检查。')
    _verify_publisher(offer.source.launcher, offer.channel)
    with native_idle_lease():
        if _source(path, offer.channel) != offer.source:
            raise AutomationError('安装或启动器来源已变化，请重新检查。')
        if cancelled():
            return stopped
        _open(offer.source.launcher, offer.channel)
    return dict(stopped, status='partial', launcher='open_requested', installation='unverified')


def verify_installation(offer):
    """Re-read the local version against the same handed-off update target."""
    if offer.action != 'update':
        raise ValueError('预下载状态由官方启动器核对。')
    path = offer.source.client['executable']
    current = installed_client(path)
    if resolve(path) != offer.source.server or current['executable'] != path:
        raise InstallationSourceChanged('星铁安装来源已变化，请重新检查。')
    installed = current['full_version']
    reached = version_parts(installed) >= version_parts(offer.target)
    return dict(status='success' if reached else 'partial', installed_version=installed,
                target=offer.target, channel=offer.channel)


def track_installation(offer, *, stop, emit, timeout=7200, interval=5):
    """Follow one fixed update target without further launcher or network actions."""
    if offer.action != 'update':
        raise ValueError('预下载完成状态需在官方启动器核对。')
    deadline = time.monotonic() + timeout
    candidate = None
    target = dict(target=offer.target, channel=offer.channel)
    while not stop.is_set():
        if time.monotonic() >= deadline:
            emit(dict(target, status='partial', tracking='timeout'))
            return
        try:
            report = verify_installation(offer)
        except InstallationSourceChanged:
            if not stop.is_set():
                emit(dict(target, status='failed', tracking='source_changed'))
            return
        except (AutomationError, OSError):
            candidate = None
            report = dict(target, status='partial', tracking='version_unavailable')
        else:
            installed = report['installed_version']
            reached = report['status'] == 'success'
            verified = reached and candidate == installed
            candidate = installed if reached else None
            report = dict(report, status='success' if verified else 'partial',
                          tracking='verified' if verified else 'confirming' if reached else 'waiting')
        if stop.is_set():
            return
        if time.monotonic() >= deadline:
            emit(dict(target, status='partial', tracking='timeout'))
            return
        emit(report)
        if report['tracking'] == 'verified':
            return
        stop.wait(min(interval, max(0, deadline - time.monotonic())))
