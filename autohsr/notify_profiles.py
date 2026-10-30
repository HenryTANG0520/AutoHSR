"""Strict, private notification profiles and Windows current-user DPAPI storage."""
from __future__ import annotations

from copy import deepcopy
import ctypes as C
from ctypes import wintypes as W
import json
import hashlib
import os
from pathlib import Path
import re
import uuid

from .config import ROOT
from .storage import replace_file

MAX_BYTES = 65536
DEFAULT_ROOT = ROOT / 'notifications.local'
MAGIC = b'AHSR-NOTIFY-1\0'
ENTROPY = b'AutoHSR-notification-profile-v1'
PROVIDERS = ('telegram', 'matrix', 'onebot', 'smtp', 'gocqhttp', 'wechatworkapp', 'wechatworkbot',
             'custom', 'lark', 'serverchan3', 'serverchanturbo', 'kook', 'webhook', 'meow', 'bark',
             'dingtalk', 'discord', 'gotify', 'pushdeer', 'pushplus', 'qmsg', 'qqbot', 'winotify')


class NotifyError(ValueError):
    """Only stable, non-secret error text may cross this boundary."""


class NotifyCancelled(NotifyError):
    pass


def alias(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value):
        raise NotifyError('通知配置名称须为小写字母开头的1～64位字母、数字、下划线或连字符。')
    return value


def text(value, *, maximum=8192, required=True):
    if (not isinstance(value, str) or len(value) > maximum or required and not value.strip()
            or any(ord(c) < 32 and c not in '\n\t' or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise NotifyError('通知字段为空、过长或包含无效字符。')
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise NotifyError('通知JSON包含重复字段。')
        result[key] = value
    return result


def loads(raw):
    try:
        if isinstance(raw, bytes):
            if len(raw) > MAX_BYTES:
                raise NotifyError('通知配置超过64 KiB。')
            raw = raw.decode('utf-8-sig')
        if not isinstance(raw, str) or len(raw.encode('utf8')) > MAX_BYTES:
            raise NotifyError('通知配置超过64 KiB或不是文本。')
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(NotifyError('通知JSON不能包含NaN或无穷值。')))
    except (ValueError, UnicodeError, RecursionError):
        raise NotifyError('通知JSON无效；未输出配置内容。') from None


def profile(value):
    if (not isinstance(value, dict) or set(value) != {'id', 'provider', 'params'}
            or not isinstance(value['provider'], str) or value['provider'] not in PROVIDERS
            or not isinstance(value['params'], dict)):
        raise NotifyError('通知配置需要id、已知provider和params对象。')
    alias(value['id'])
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf8')
        if len(raw) > MAX_BYTES:
            raise ValueError()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise NotifyError('通知配置必须是最多64 KiB的JSON对象。') from None
    from .notify_providers import validate
    validate(value['provider'], value['params'])
    return deepcopy(value)


class _Blob(C.Structure):
    _fields_ = [('cbData', W.DWORD), ('pbData', C.POINTER(C.c_ubyte))]


def _blob(raw):
    buffer = (C.c_ubyte * len(raw)).from_buffer_copy(raw)
    return _Blob(len(raw), C.cast(buffer, C.POINTER(C.c_ubyte))), buffer


def crypt(raw, *, decrypt=False):
    """Current-user DPAPI with no UI, no machine-wide scope, no plaintext files."""
    if os.name != 'nt' or not isinstance(raw, bytes) or not raw or len(raw) > 2 * MAX_BYTES:
        raise NotifyError('通知凭据需要Windows当前用户保护，或数据大小无效。')
    source, source_buffer = _blob(raw)
    entropy, entropy_buffer = _blob(ENTROPY)
    output = _Blob()
    library = C.WinDLL('crypt32', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree.restype = C.c_void_p
    if decrypt:
        function = library.CryptUnprotectData
        function.argtypes = [C.POINTER(_Blob), C.c_void_p, C.POINTER(_Blob), C.c_void_p, C.c_void_p,
                             W.DWORD, C.POINTER(_Blob)]
        arguments = [C.byref(source), None, C.byref(entropy), None, None, 1, C.byref(output)]
    else:
        function = library.CryptProtectData
        function.argtypes = [C.POINTER(_Blob), W.LPCWSTR, C.POINTER(_Blob), C.c_void_p, C.c_void_p,
                             W.DWORD, C.POINTER(_Blob)]
        arguments = [C.byref(source), None, C.byref(entropy), None, None, 1, C.byref(output)]
    function.restype = W.BOOL
    try:
        if not function(*arguments):
            raise NotifyError('当前Windows用户无法保护或读取通知凭据。')
        if not 0 < output.cbData <= 2 * MAX_BYTES:
            raise NotifyError('通知凭据保护结果无效。')
        return C.string_at(output.pbData, output.cbData)
    finally:
        if output.pbData:
            kernel.LocalFree(C.cast(output.pbData, C.c_void_p))


class ProfileStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else DEFAULT_ROOT

    def path(self, identity):
        return self.root / 'profiles' / (alias(identity) + '.dpapi')

    def save(self, value, *, replace=False):
        value = profile(value)
        path = self.path(value['id'])
        if type(replace) is not bool or path.exists() and not replace:
            raise NotifyError('通知配置已存在；修改须明确选择替换。')
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf8')
        encoded = MAGIC + crypt(raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
            if replace and path.exists():
                with path.open('rb') as stream:
                    previous = stream.read(2 * MAX_BYTES + 1)
                if len(previous) > 2 * MAX_BYTES:
                    raise NotifyError('原通知配置超限，未覆盖。')
                backup = path.with_name(path.stem + '.' + uuid.uuid4().hex + '.dpapi.bak')
                with backup.open('xb') as stream:
                    stream.write(previous); stream.flush(); os.fsync(stream.fileno())
                replace_file(temporary, path)
            elif os.name == 'nt':
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        except FileExistsError:
            raise NotifyError('通知配置由其他操作创建，未覆盖。') from None
        finally:
            temporary.unlink(missing_ok=True)
        return dict(id=value['id'], provider=value['provider'], credentials_saved=True)

    def load_private(self, identity):
        return self.load_version(identity)[0]

    def load_version(self, identity):
        try:
            with self.path(identity).open('rb') as stream:
                raw = stream.read(2 * MAX_BYTES + 1)
            if len(raw) > 2 * MAX_BYTES or not raw.startswith(MAGIC):
                raise ValueError()
            value = profile(loads(crypt(raw[len(MAGIC):], decrypt=True)))
            if value['id'] != identity:
                raise ValueError()
            return value, hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError):
            raise NotifyError('通知配置缺失、损坏或不属于当前Windows用户。') from None

    def require_version(self, identity, digest):
        try:
            with self.path(identity).open('rb') as stream:
                raw = stream.read(2 * MAX_BYTES + 1)
            if len(raw) > 2 * MAX_BYTES or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError()
        except (OSError, ValueError):
            raise NotifyError('通知凭据在本次运行后改变或丢失，未改发到新对象。') from None

    def list_public(self):
        directory = self.root / 'profiles'
        if not directory.exists():
            return []
        rows = []
        for path in sorted(directory.glob('*.dpapi')):
            try:
                value = self.load_private(path.stem)
                rows.append(dict(id=value['id'], provider=value['provider'], readable=True))
            except NotifyError:
                rows.append(dict(id=path.stem, readable=False))
        return rows
