"""Send a user-selected calendar PNG through one frozen SMTP profile."""

from contextlib import ExitStack
from copy import copy
from hashlib import sha256
from io import BytesIO
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


def _result(status, reason=None, *, reused=False):
    return dict(status=status, reason=reason or _REASONS[status], reused=reused)


def _read_bytes(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_PNG_ATTACHMENT_BYTES + 1)
    if not raw or len(raw) > MAX_PNG_ATTACHMENT_BYTES:
        raise _Rejected('attachment_limit' if raw else 'invalid_attachment')
    return raw


def _load_attachment(value):
    path = _png_path(value)
    revision = file_revision(path)
    with hold_read_sources((path,)):
        if _png_path(path) != path or file_revision(path) != revision:
            raise _Rejected('attachment_changed')
        raw = _read_bytes(path)
    try:
        image = _read_png_image(BytesIO(raw), max_height=_MAX_INPUT_EDGE * _MAX_PAGES, max_pixels=_MAX_INPUT_PIXELS)
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
    return path, revision, sha256(raw).digest(), png, image_key.hexdigest()


def send_reward_guide(image, profile, *, service=None, checkpoint=lambda: None):
    """Submit an explicit local image once per canonical PNG and profile alias."""
    stopped = submitted = False
    blocked = None

    def check():
        nonlocal stopped
        try:
            checkpoint()
        except (NotifyCancelled, Stopped, KeyboardInterrupt):
            stopped = True
            raise NotifyCancelled('活动日历通知已停止。') from None

    try:
        check()
        service = NotificationService() if service is None else service
        identity = alias(profile)
        profile_path = local_path(service.store.path(identity))
        with hold_read_sources((profile_path,)):
            if local_path(service.store.path(identity)) != profile_path:
                raise OSError()
            frozen = service.store.load_version(identity)
        value, version = frozen
        params = value['params']
        if value.get('id') != identity or not isinstance(params, dict):
            raise NotifyError('通知配置身份无法核实。')
    except (NotifyCancelled, KeyboardInterrupt):
        return _result('cancelled')
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return _result('rejected', 'invalid_profile')
    if value.get('provider') != 'smtp':
        return _result('rejected', 'unsupported_provider')
    if params.get('ssl', True) is not True and params.get('starttls', False) is not True:
        return _result('rejected', 'tls_required')

    try:
        check()
        path, revision, source_digest, png, image_key = _load_attachment(image)
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
            raise NotifyError('本次活动日历已进入提交，未重复发送。')
        submitted = True

    def send(provider, current, title, body):
        nonlocal blocked
        check()
        if provider != 'smtp' or current != params:
            blocked = 'profile_changed'
            raise NotifyError('活动日历的通知配置已变化。')
        with ExitStack() as locks:
            blocked = 'profile_changed'
            locks.enter_context(hold_read_sources((profile_path,)))
            if local_path(service.store.path(identity)) != profile_path:
                raise OSError()
            service.store.require_version(identity, version)
            blocked = 'attachment_changed'
            locks.enter_context(hold_read_sources((path,)))
            if (_png_path(path) != path or file_revision(path) != revision
                    or sha256(_read_bytes(path)).digest() != source_digest):
                raise OSError()
            blocked = None
            check()
            if service.local_send is None:
                status = send_smtp_png(params, title, body, png, before_submit=before_submit)
            else:
                status = service.local_send(provider, params, title, body, png=png, before_submit=before_submit)
            if (type(status) is not str or status not in _REASONS
                    or status in ('accepted', 'partial') and not submitted):
                raise NotifyError('活动日历未取得可核实的发送回执。')
            return status

    attempt = copy(service)
    attempt.local_send = send
    key = 'reward-guide-png-v1:' + image_key
    try:
        check()
        receipt = attempt.deliver(frozen, _TITLE, _BODY, key, checkpoint=check)
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
