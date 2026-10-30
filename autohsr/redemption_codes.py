"""Bounded redemption catalog parsing; reading a local file never downloads."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlsplit

from .models import InputInterrupted, Stopped


MAX_BYTES = 256 * 1024
MAX_ROWS = 2000
MAX_CODE_LENGTH = 64
CATALOG_URLS = (
    'https://m7a.top/assets/config/redemption_codes.json',
    'https://github.kotori.top/https://m7a.top/assets/config/redemption_codes.json',
    'https://cdn.jsdelivr.net/gh/moesnow/March7thAssistant@main/assets/config/redemption_codes.json',
    'https://raw.githubusercontent.com/moesnow/March7thAssistant/refs/heads/main/assets/config/redemption_codes.json',
)


class CodesError(ValueError):
    pass


class CatalogFetchError(OSError):
    def __init__(self, attempts):
        super().__init__('兑换码表下载未取得有效结果；没有执行兑换。')
        self.attempts = tuple(deepcopy(attempts))


class CatalogCancelled(Stopped):
    pass


def validate_server(server):
    if type(server) is not str or server not in ('cn', 'global'):
        raise CodesError('兑换服务器必须明确为cn或global。')
    return server


def validate_code(code):
    # The original string is the ledger/input identity. No stripping, Unicode
    # normalization, or uppercase conversion may change it behind the caller.
    if type(code) is not str or not re.fullmatch(r'[A-Za-z0-9\u3400-\u9fff]{1,64}', code):
        raise CodesError('兑换码须为1至64个字母、数字或中文字符，不能含空白或控制符。')
    return code


@dataclass(frozen=True)
class CodeBatch:
    codes: tuple[str, ...]
    server: str
    source: dict
    skipped: tuple[dict, ...]

    def public_summary(self):
        reasons = {}
        for row in self.skipped:
            key = row['reason']
            reasons[key] = reasons.get(key, 0) + 1
        return dict(server=self.server, count=len(self.codes), skipped=len(self.skipped),
                    reasons=reasons, source_kind=self.source.get('kind'),
                    naive_expiry_assumed_utc=self.source.get('naive_expiry_assumed_utc', 0))


def _moment(now):
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise CodesError('码表核对时间必须带时区。')
    try:
        return now.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise CodesError('码表核对时间超出可表示范围。') from None


def _expiry(value):
    if value is None:
        return None, False
    if (type(value) is not str or len(value) > 64 or value != value.strip()
            or any(ord(c) < 32 for c in value) or not re.fullmatch(
                r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})?', value)):
        raise CodesError('码表过期时间必须为ISO时刻或null。')
    try:
        parsed = datetime.fromisoformat(value[:-1] + '+00:00' if value[-1:] in ('Z', 'z') else value)
    except ValueError:
        raise CodesError('码表过期时间无效。') from None
    assumed = parsed.tzinfo is None
    if assumed:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc), assumed
    except (ValueError, OverflowError):
        raise CodesError('码表过期时间超出可表示范围。') from None


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise CodesError('码表JSON含重复字段。')
        result[key] = value
    return result


def _decode(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise CodesError('码表必须是有界UTF-8 JSON，最多256 KiB。')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(CodesError('码表含非有限数值。')))
    except (UnicodeError, ValueError, RecursionError):
        raise CodesError('码表JSON格式无效。') from None


def _parse(rows, server, now, source):
    server = validate_server(server)
    now = _moment(now)
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise CodesError('码表须为最多2000行的JSON数组。')
    codes, skipped, seen = [], [], set()
    assumed_count = valid_rows = 0
    for index, row in enumerate(rows):
        reason = None
        if type(row) is not dict or len(row) > 16 or not {'server', 'expires_at', 'code'} <= row.keys():
            reason = 'invalid_row'
        else:
            try:
                row_server = validate_server(row['server'])
            except CodesError:
                reason = 'invalid_server'
            if reason is None:
                try:
                    code = validate_code(row['code'])
                except CodesError:
                    reason = 'invalid_code'
            if reason is None:
                try:
                    expires, assumed = _expiry(row['expires_at'])
                except CodesError:
                    reason = 'invalid_expiry'
            if reason is None:
                valid_rows += 1
                assumed_count += int(assumed)
                if row_server != server:
                    reason = 'other_server'
                elif expires is not None and expires <= now:
                    reason = 'expired'
                elif code in seen:
                    reason = 'duplicate'
                else:
                    seen.add(code)
                    codes.append(code)
        if reason:
            skipped.append(dict(row=index, reason=reason))
    metadata = dict(source, rows=len(rows), valid_rows=valid_rows, naive_expiry_assumed_utc=assumed_count)
    return CodeBatch(tuple(codes), server, metadata, tuple(skipped))


def from_values(values, server):
    validate_server(server)
    if type(values) not in (list, tuple) or len(values) > MAX_ROWS:
        raise CodesError('兑换码列表须为最多2000项的有限列表。')
    if sum(len(v.encode('utf-8', errors='surrogatepass')) for v in values if type(v) is str) > MAX_BYTES:
        raise CodesError('兑换码列表超过256 KiB。')
    codes, skipped, seen = [], [], set()
    for index, value in enumerate(values):
        try:
            code = validate_code(value)
        except CodesError:
            skipped.append(dict(row=index, reason='invalid_code'))
            continue
        if code in seen:
            skipped.append(dict(row=index, reason='duplicate'))
        else:
            seen.add(code)
            codes.append(code)
    return CodeBatch(tuple(codes), server, dict(kind='values', rows=len(values)), tuple(skipped))


def from_file(path, server, now=None):
    validate_server(server)
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_BYTES+1)
    except OSError:
        raise OSError('本地兑换码表不可读取。') from None
    return _parse(_decode(raw), server, now, dict(kind='file', sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)))


def _cancel(callback):
    if callback is not None and callback() is True:
        raise CatalogCancelled('码表下载已取消；没有执行兑换。')


def _request(url, *, timeout, max_bytes, cancel):
    if url not in CATALOG_URLS:
        raise CodesError('码表地址不在固定来源范围。')
    parsed = urlsplit(url)
    deadline = time.monotonic()+timeout
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=timeout, context=ssl.create_default_context())
    response = None
    try:
        _cancel(cancel)
        connection.connect()
        sock = connection.sock

        def remaining():
            _cancel(cancel)
            left = deadline-time.monotonic()
            if left <= 0:
                raise OSError('码表响应超过时限。')
            sock.settimeout(left)

        remaining()
        connection.request('GET', parsed.path, headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        remaining()
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise OSError('码表响应状态不受支持；未跟随跳转。')
        length = response.getheader('Content-Length')
        if length is not None and (not re.fullmatch(r'[0-9]{1,10}', length) or int(length) > max_bytes):
            raise OSError('码表响应大小不受支持。')
        body = bytearray()
        while True:
            remaining()
            chunk = response.read1(min(65536, max_bytes+1-len(body)))
            remaining()
            if not chunk:
                return bytes(body)
            body.extend(chunk)
            if len(body) > max_bytes:
                raise OSError('码表响应超过大小限制。')
    finally:
        if response is not None:
            response.close()
        connection.close()


def fetch_catalog(server, *, now=None, fetcher=None, cancel=None, timeout=10, max_bytes=MAX_BYTES):
    validate_server(server)
    now = _moment(now)
    if (type(timeout) not in (int, float) or not 0 < timeout <= 15
            or type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES
            or fetcher is not None and not callable(fetcher)
            or cancel is not None and not callable(cancel)):
        raise CodesError('码表下载范围或取消接口无效。')
    transport = _request if fetcher is None else fetcher
    attempts, cancelled = [], []

    def cancellation():
        try:
            _cancel(cancel)
        except BaseException as error:
            cancelled.append(error)
            raise

    for index, url in enumerate(CATALOG_URLS):
        cancellation()
        try:
            raw = transport(url, timeout=timeout, max_bytes=max_bytes, cancel=cancellation)
            if cancelled:
                raise cancelled[0]
            cancellation()
            if type(raw) is not bytes or len(raw) > max_bytes:
                raise CodesError('码表响应超过允许范围。')
            batch = _parse(_decode(raw), server, now,
                dict(kind='download', source_index=index, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)))
            if batch.source['rows'] and not batch.source['valid_rows']:
                raise CodesError('码表没有符合格式的条目。')
            return CodeBatch(batch.codes, batch.server, dict(batch.source, attempts=deepcopy(attempts)), batch.skipped)
        except (Stopped, InputInterrupted):
            raise
        except Exception:
            if cancelled:
                raise cancelled[0]
            attempts.append(dict(source_index=index, reason='unavailable_or_invalid'))
    raise CatalogFetchError(attempts)
