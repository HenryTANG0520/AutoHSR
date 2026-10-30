"""Read-only server proof bound to the executable used by this run.

Only the two HYP package install-directory values are consulted. Registry key
presence alone does not identify the server of a running StarRail.exe.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

from .models import AutomationError, InputInterrupted, Stopped


MAX_PATH_LENGTH = 4096
METHOD = 'hyp_install_path_match_v1'
VALUE_NAME = 'GameInstallPath'
HYP_KEYS = (
    ('cn', r'Software\miHoYo\HYP\1_1\hkrpg_cn'),
    ('global', r'Software\Cognosphere\HYP\1_0\hkrpg_global'),
)
_ERRORS = {
    'invalid_executable': '当前游戏可执行文件路径无效，无法自动确定兑换服务器。',
    'registry_unavailable': '当前环境不能读取启动器安装来源，请明确选择兑换服务器。',
    'registry_unreadable': '无法完整读取启动器安装来源，请明确选择兑换服务器。',
    'invalid_install_path': '启动器安装来源无效，请明确选择兑换服务器。',
    'unmatched': '当前游戏未唯一匹配启动器安装来源，请明确选择兑换服务器。',
    'ambiguous': '当前游戏同时匹配多个服务器来源，请明确选择兑换服务器。',
    'invalid_resolution': '兑换服务器来源证明无效，请重新核对当前游戏。',
    'executable_changed': '当前游戏与兑换服务器来源证明不一致，请重新核对。',
}


class UnknownServerError(AutomationError):
    """Fail closed without including a registry value or installation path."""

    def __init__(self, reason='unmatched'):
        self.reason = reason if reason in _ERRORS else 'unmatched'
        super().__init__(_ERRORS[self.reason])


@dataclass(frozen=True)
class ServerResolution:
    server: str
    method: str
    executable_key: str
    source_digest: str

    def __post_init__(self):
        if not _valid_resolution(self):
            raise ValueError('兑换服务器来源证明无效。')

    def public_summary(self):
        return dict(server=self.server, method=self.method)

    def to_dict(self):
        """Private local proof; even this representation contains no raw paths."""
        return dict(server=self.server, method=self.method,
                    executable_key=self.executable_key, source_digest=self.source_digest)


def _native_reader(subkey, value_name):
    # Importing this module, or using an explicit server, must not access the
    # registry. No upstream module is imported: it also reads/writes game data.
    try:
        import winreg
    except ImportError:
        raise UnknownServerError('registry_unavailable') from None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as key:
            value, value_type = winreg.QueryValueEx(key, value_name)
    except FileNotFoundError:
        return None
    if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        raise UnknownServerError('invalid_install_path')
    return value


def _path(value, reason):
    if (type(value) is not str or not value or len(value) > MAX_PATH_LENGTH
            or value != value.strip()
            or any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp') for char in value)):
        raise UnknownServerError(reason)
    try:
        path = Path(value)
        if not path.is_absolute():
            raise UnknownServerError(reason)
        for part in path.parts[1:]:
            if (any(char in '<>:"|?*' for char in part)
                    or (part not in ('.', '..') and part != part.rstrip(' .'))):
                raise UnknownServerError(reason)
        return path
    except (OSError, ValueError):
        raise UnknownServerError(reason) from None


def _key(path):
    # normcase follows the host filesystem convention: Windows path casing is
    # immaterial, while a case-sensitive host must not conflate distinct files.
    canonical = os.path.normcase(os.fspath(path))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _valid_resolution(value):
    return (type(value) is ServerResolution and type(getattr(value, 'server', None)) is str
            and value.server in ('cn', 'global') and type(getattr(value, 'method', None)) is str
            and value.method == METHOD
            and all(type(item) is str and re.fullmatch(r'[0-9a-f]{64}', item)
                    for item in (getattr(value, 'executable_key', None),
                                 getattr(value, 'source_digest', None))))


def _executable_key(executable):
    try:
        value = os.fspath(executable)
    except (TypeError, ValueError, OSError):
        raise UnknownServerError('invalid_executable') from None
    current = _path(value, 'invalid_executable')
    try:
        if current.name.casefold() != 'starrail.exe':
            raise UnknownServerError('invalid_executable')
        current = current.resolve(strict=True)
        if current.name.casefold() != 'starrail.exe' or not current.is_file():
            raise UnknownServerError('invalid_executable')
        return _key(current)
    except (OSError, ValueError, RuntimeError):
        raise UnknownServerError('invalid_executable') from None


def require_binding(executable, resolution):
    """Recheck the executable binding without consulting the registry."""
    if not _valid_resolution(resolution):
        raise UnknownServerError('invalid_resolution')
    if _executable_key(executable) != resolution.executable_key:
        raise UnknownServerError('executable_changed')


def resolve(executable, *, reader=None):
    """Resolve cn/global only from one exact HYP/executable path match.

    ``reader(subkey, value_name)`` returns a string or None. None denotes a
    missing key/value, and an absolute stale installation is a nonmatch. Any
    unreadable or malformed source makes the complete observation unknown.
    This function does not inspect a process, UID, account, or executable bytes.
    """
    executable_key = _executable_key(executable)
    read = _native_reader if reader is None else reader
    if not callable(read):
        raise UnknownServerError('registry_unreadable')
    candidates = []
    matches = []
    for server, subkey in HYP_KEYS:
        try:
            install = read(subkey, VALUE_NAME)
        except (UnknownServerError, InputInterrupted, Stopped):
            raise
        except Exception:
            raise UnknownServerError('registry_unreadable') from None
        if install is None:
            candidates.append(dict(server=server, subkey=subkey, state='missing'))
            continue
        directory = _path(install, 'invalid_install_path')
        try:
            candidate = (directory / 'StarRail.exe').resolve(strict=False)
            candidate_key = _key(candidate)
        except (OSError, ValueError, RuntimeError):
            raise UnknownServerError('invalid_install_path') from None
        candidates.append(dict(server=server, subkey=subkey, state='candidate',
                               executable_key=candidate_key))
        if candidate_key == executable_key:
            matches.append(server)

    if len(matches) != 1:
        raise UnknownServerError('ambiguous' if matches else 'unmatched')
    source = dict(version=1, method=METHOD, hive='HKCU', value_name=VALUE_NAME,
                  executable_key=executable_key, candidates=candidates)
    source_digest = hashlib.sha256(json.dumps(source, ensure_ascii=True, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    return ServerResolution(matches[0], METHOD, executable_key, source_digest)
