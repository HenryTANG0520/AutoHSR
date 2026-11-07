"""Send a user-selected local PNG through one frozen SMTP profile."""

from contextlib import ExitStack
from copy import copy
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zlib import error as DeflateError

from PIL import Image

from .models import Stopped
from .notify_local import MAX_PNG_ATTACHMENT_BYTES, send_smtp_png
from .notify_profiles import NotifyCancelled, NotifyError, alias
from .notify_runtime import NotificationService
from .reward_guide_export import _Rejected, _png_path, _read_png_image
from .reward_guide_stitch import _MAX_INPUT_EDGE, _MAX_INPUT_PIXELS, _MAX_PAGES
from .storage import file_revision, hold_read_sources
from .workflow_bundle import _path as local_path


_TITLE = 'AutoHSR · 活动日历提醒'
_BODY = '附件为本次明确选择的奖励指南图片。'
_REASONS = dict(accepted='provider_accepted', partial='provider_partial', rejected='provider_rejected',
                unknown='delivery_unknown', cancelled='stopped_before_send')


@dataclass(frozen=True)
class PngSource:
    path: Path
    revision: tuple
    digest: bytes


def _result(status, reason=None, *, reused=False):
    return dict(status=status, reason=reason or _REASONS[status], reused=reused)


def _read_bytes(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_PNG_ATTACHMENT_BYTES + 1)
    if not raw or len(raw) > MAX_PNG_ATTACHMENT_BYTES:
        raise _Rejected('attachment_limit' if raw else 'invalid_attachment')
    return raw


def _load_attachment(value, *, expected_source=None, min_edge=64):
    path = _png_path(value)
    revision = file_revision(path)
    with hold_read_sources((path,)):
        if _png_path(path) != path or file_revision(path) != revision:
            raise _Rejected('attachment_changed')
        if expected_source is not None and (expected_source.path != path or expected_source.revision != revision):
            raise _Rejected('attachment_changed')
        raw = _read_bytes(path)
    source = PngSource(path, revision, sha256(raw).digest())
    if expected_source is not None and expected_source != source:
        raise _Rejected('attachment_changed')
    try:
        image = _read_png_image(BytesIO(raw), max_height=_MAX_INPUT_EDGE * _MAX_PAGES, max_pixels=_MAX_INPUT_PIXELS,
                                min_edge=min_edge)
    except _Rejected as error:
        raise _Rejected('attachment_limit' if str(error) == 'limit' else 'invalid_attachment') from None
    pixels = image.tobytes()
    image_key = sha256(f'{image.width}x{image.height}:'.encode('ascii'))
    image_key.update(pixels)
    encoded = BytesIO()
    Image.frombytes('RGB', image.size, pixels).save(encoded, format='PNG')
    png = encoded.getvalue()
    if len(png) > MAX_PNG_ATTACHMENT_BYTES:
        raise _Rejected('attachment_limit')
    return source, png, image_key.hexdigest()


def freeze_png(image, *, min_edge=64):
    try:
        source, _, _ = _load_attachment(image, min_edge=min_edge)
    except (OSError, RuntimeError, TypeError, ValueError, SyntaxError, DeflateError,
            Image.DecompressionBombError):
        raise NotifyError('无法核实明确选择的本地 PNG。') from None
    return source


def _smtp_profile(profile, service):
    try:
        identity = alias(profile)
        path = local_path(service.store.path(identity))
        with hold_read_sources((path,)):
            if local_path(service.store.path(identity)) != path:
                raise OSError()
            frozen = service.store.load_version(identity)
        value, _ = frozen
        params = value['params']
        if value.get('id') != identity or not isinstance(params, dict):
            raise NotifyError('通知配置身份无法核实。')
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        raise _Rejected('invalid_profile') from None
    if value.get('provider') != 'smtp':
        raise _Rejected('unsupported_provider')
    if params.get('ssl', True) is not True and params.get('starttls', False) is not True:
        raise _Rejected('tls_required')
    return path, frozen


def freeze_smtp_profile(profile, *, service=None):
    service = NotificationService() if service is None else service
    try:
        _, (_, version) = _smtp_profile(profile, service)
    except _Rejected:
        raise NotifyError('本地 PNG 通知需要可核实且启用 SSL 或 STARTTLS 的 SMTP 方案。') from None
    return version


def send_reward_guide(image, profile, *, service=None, checkpoint=lambda: None):
    return send_local_png(image, profile, _TITLE, _BODY, service=service, checkpoint=checkpoint)


def send_local_png(image, profile, title, body, *, service=None, checkpoint=lambda: None,
                   expected_version=None, expected_source=None, workflow_step_key=None):
    """Submit a PNG once, scoped to a capture step or the usual image and profile."""
    stopped = submitted = False
    blocked = None

    def check():
        nonlocal stopped
        try:
            checkpoint()
        except (NotifyCancelled, Stopped, KeyboardInterrupt):
            stopped = True
            raise NotifyCancelled('图片通知已停止。') from None

    try:
        check()
        service = NotificationService() if service is None else service
        profile_path, frozen = _smtp_profile(profile, service)
        value, version = frozen
    except (NotifyCancelled, KeyboardInterrupt):
        return _result('cancelled')
    except _Rejected as error:
        return _result('rejected', str(error))
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return _result('rejected', 'invalid_profile')
    if expected_version is not None and expected_version != version:
        return _result('rejected', 'profile_changed')
    identity, params = value['id'], value['params']

    try:
        check()
        source, png, image_key = _load_attachment(image, expected_source=expected_source,
                                                  min_edge=64 if workflow_step_key is None else 16)
    except (NotifyCancelled, KeyboardInterrupt):
        return _result('cancelled')
    except _Rejected as error:
        return _result('rejected', str(error))
    except (OSError, RuntimeError, TypeError, ValueError, SyntaxError, DeflateError, Image.DecompressionBombError):
        return _result('rejected', 'invalid_attachment')

    def before_submit():
        nonlocal submitted
        check()
        if submitted:
            raise NotifyError('本次图片通知已进入提交，未重复发送。')
        submitted = True

    def send(provider, current, title, body):
        nonlocal blocked
        check()
        if provider != 'smtp' or current != params:
            blocked = 'profile_changed'
            raise NotifyError('图片通知的配置已变化。')
        with ExitStack() as locks:
            blocked = 'profile_changed'
            locks.enter_context(hold_read_sources((profile_path,)))
            if local_path(service.store.path(identity)) != profile_path:
                raise OSError()
            service.store.require_version(identity, version)
            blocked = 'attachment_changed'
            path = source.path
            locks.enter_context(hold_read_sources((path,)))
            if (_png_path(path) != path or file_revision(path) != source.revision
                    or sha256(_read_bytes(path)).digest() != source.digest):
                raise OSError()
            blocked = None
            check()
            if service.local_send is None:
                status = send_smtp_png(params, title, body, png, before_submit=before_submit)
            else:
                status = service.local_send(provider, params, title, body, png=png, before_submit=before_submit)
            if (type(status) is not str or status not in _REASONS
                    or status in ('accepted', 'partial') and not submitted):
                raise NotifyError('图片通知未取得可核实的发送回执。')
            return status

    attempt = copy(service)
    attempt.local_send = send
    key = ('reward-guide-png-v1:' + image_key if workflow_step_key is None
           else f'workflow-capture-png-v1:{workflow_step_key}')
    try:
        check()
        receipt = attempt.deliver(frozen, title, body, key, checkpoint=check)
    except (NotifyCancelled, KeyboardInterrupt):
        return _result('unknown' if submitted else 'cancelled')
    except (NotifyError, OSError):
        return _result('unknown', 'receipt_unverified')

    if stopped and not submitted:
        return _result('cancelled')
    if blocked is not None:
        return _result('rejected', blocked)
    if not isinstance(receipt, dict):
        return _result('unknown', 'receipt_unverified')
    status = receipt.get('status')
    if type(status) is not str or status not in _REASONS:
        status = 'unknown'
    reused = receipt.get('reused') is True
    reason = receipt.get('reason')
    if reason not in ('receipt_write_failed', 'profile_changed'):
        reason = None
    if not reused and not submitted and status not in ('rejected', 'cancelled') and reason is None:
        return _result('rejected', 'submission_not_started')
    return _result(status, reason, reused=reused)
