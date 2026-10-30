"""Bounded single-attempt HTTP notifications; credentials never enter errors."""
from dataclasses import dataclass, field
import ipaddress
import json
import re
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler

from .notify_profiles import NotifyError, text, _pairs


@dataclass(repr=False)
class Call:
    url: str
    method: str = 'POST'
    data: bytes | None = None
    headers: dict = field(default_factory=dict)
    phase: str = 'send'


@dataclass
class Reply:
    status: int
    body: bytes


def url(value, *, insecure=False):
    text(value, maximum=16384)
    if any(c.isspace() for c in value) or any(c in value for c in ('\r', '\n', '\0')):
        raise NotifyError('通知地址无效。')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or parsed.port == 0):
            raise ValueError()
        local = parsed.hostname.lower() == 'localhost'
        try:
            local |= ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme == 'http' and not (local or insecure):
            raise ValueError()
    except ValueError:
        raise NotifyError('通知地址需要HTTPS，或明确允许的HTTP；不接受地址中的用户名与密码。') from None
    return value


def headers(value):
    if not isinstance(value, dict) or len(value) > 32:
        raise NotifyError('通知headers必须为最多32项的对象。')
    for key, val in value.items():
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9!#$%&\'*+.^_`|~-]{1,80}', key)
                or key.lower() in ('host', 'content-length', 'transfer-encoding', 'proxy-authorization')):
            raise NotifyError('通知包含不支持的请求头。')
        text(val)
        if '\n' in val or '\t' in val:
            raise NotifyError('通知请求头不能包含换行或制表符。')
    return dict(value)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None


def request(call):
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    deadline = time.monotonic() + 30
    try:
        response = opener.open(Request(call.url, data=call.data, headers=call.headers, method=call.method), timeout=15)
    except HTTPError as error:
        response = error
    except Exception:
        raise NotifyError('通知请求未取得可核实响应；状态未知，不自动重试。') from None
    try:
        with response:
            chunks = bytearray()
            reader = getattr(response, 'read1', response.read)
            while True:
                if time.monotonic() >= deadline:
                    raise NotifyError('通知响应超过观察时限；状态未知。')
                block = reader(min(65536, 1024 * 1024 + 1 - len(chunks)))
                if not block:
                    break
                chunks.extend(block)
                if len(chunks) > 1024 * 1024:
                    raise NotifyError('通知响应超过1 MiB；状态未知。')
            return Reply(response.code, bytes(chunks))
    except NotifyError:
        raise
    except Exception:
        raise NotifyError('通知响应读取未完成；状态未知，不自动重试。') from None


def json_body(reply):
    try:
        value = json.loads(reply.body.decode('utf8'), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeError, RecursionError):
        return {}
