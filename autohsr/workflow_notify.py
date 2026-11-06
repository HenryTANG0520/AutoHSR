"""One explicitly authorized notification step with an anonymous child receipt."""
from copy import copy
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from .models import Stopped
from .notify_profiles import MAX_BYTES, NotifyCancelled, NotifyError, alias, loads, text
from .notify_runtime import NotificationService
from .storage import hold_read_sources, replace_file


_TITLE = 'AutoHSR · 任务流程通知'
_OUTCOMES = {
    'accepted': ('success', 'provider_accepted'),
    'rejected': ('failed', 'provider_rejected'),
    'partial': ('partial', 'provider_partial'),
    'unknown': ('partial', 'delivery_unknown'),
    'cancelled': ('stopped', 'stopped_before_send'),
}


def validate_message(message):
    message = text(message)
    if len(message.encode('utf-16-le')) > 8192:
        raise NotifyError('任务流程通知超过渠道通用长度上限。')
    return message


def _version(digest):
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise NotifyError('任务流程通知需要已核实的配置版本。')
    return digest


def freeze_profile(profile, *, service=None):
    """Read the explicitly selected private profile and return only its version."""
    service = NotificationService() if service is None else service
    return _version(service.store.load_version(alias(profile))[1])


def _write_new(path, value):
    temporary = None
    try:
        with NamedTemporaryFile('wb', dir=path.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value, ensure_ascii=False, indent=2).encode('utf8'))
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path, exclusive=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _result(directory, outcome, *, reason=None, reused=False, accepted=0, saved=True):
    status, default_reason = _OUTCOMES[outcome]
    notification = dict(status=outcome, reason=reason or default_reason, reused=reused)
    if accepted:
        notification['accepted_submissions'] = accepted
    return dict(operation='workflow_notify', status=status, report_saved=saved,
                run_dir=str(directory), notification=notification)


def _finish(directory, outcome, **facts):
    result = _result(directory, outcome, **facts)
    try:
        _write_new(directory / 'report.json', result)
    except OSError:
        result['report_saved'] = False
        result['notification']['reason'] = 'receipt_write_failed'
        if result['status'] == 'success':
            result['status'] = 'partial'
    return result


def _accepted_submissions(service, step_key, frozen, message, submitted):
    """Recover earlier accepted sends when a multi-target delivery stops later."""
    if not submitted:
        return 0
    value, version = frozen
    profile = value['id']
    key = hashlib.sha256(f'{step_key}:{profile}'.encode('utf8')).hexdigest()
    path = service.root / 'attempts' / (key + '.json')
    digest = hashlib.sha256((_TITLE + '\n' + message).encode('utf8')).hexdigest()
    try:
        with path.open('rb') as stream:
            data = loads(stream.read(MAX_BYTES + 1))
        if (not isinstance(data, dict) or type(data.get('schema')) is not int or data['schema'] != 1
                or data.get('key') != key or data.get('profile') != profile
                or data.get('provider') != value['provider'] or data.get('profile_version') != version
                or data.get('message_sha256') != digest or not isinstance(data.get('actions'), list)
                or data.get('status') not in ('pending', 'accepted', 'partial', 'rejected', 'unknown', 'cancelled')):
            return 0
        sends = []
        for action in data['actions']:
            if not isinstance(action, dict) or type(action.get('index')) is not int:
                return 0
            phase, index, status = action.get('phase'), action['index'], action.get('status')
            if phase == 'send' and index == len(sends) and status in (
                    'pending', 'accepted', 'partial', 'rejected', 'unknown', 'cancelled'):
                sends.append(status)
            elif phase not in ('authorize', 'verify_room') or index != -1 or sends:
                return 0
        return sends[:submitted].count('accepted')
    except (OSError, NotifyError):
        return 0


def _deliver(service, profile, message, frozen, step_key, directory, checkpoint):
    stopped = False
    profile_changed = False
    submitted = 0

    def check():
        nonlocal stopped
        try:
            checkpoint()
        except (Stopped, NotifyCancelled):
            stopped = True
            raise NotifyCancelled('任务流程已停止。') from None

    def guarded(transport, args, *, sending):
        nonlocal profile_changed, submitted
        check()
        ready = False
        try:
            with hold_read_sources((service.store.path(profile),)):
                service.store.require_version(profile, frozen[1])
                # The provider's durable pending action already exists here.
                check()
                ready = True
                if sending:
                    submitted += 1
                return transport(*args)
        except NotifyCancelled:
            raise
        except (NotifyError, OSError):
            if not ready:
                check()
                profile_changed = True
            raise

    def request(call):
        return guarded(service.request, (call,), sending=call.phase == 'send')

    def local_send(*args):
        from .notify_local import send
        return guarded(service.local_send or send, args, sending=True)

    # Preserve the shared store and other users of the service's transports.
    attempt = copy(service)
    attempt.request = request
    attempt.local_send = local_send
    interrupted = False
    try:
        check()
        receipt = attempt.deliver(frozen, _TITLE, message, step_key, checkpoint=check)
    except KeyboardInterrupt:
        interrupted = stopped = True
        receipt = {}
    except Exception:
        receipt = {}
    if not isinstance(receipt, dict):
        receipt = {}
    reused = receipt.get('reused') is True
    outcome = receipt.get('status')
    if type(outcome) is not str or outcome not in _OUTCOMES:
        outcome = 'unknown'
    if reused:
        return _finish(directory, 'unknown', reason='already_attempted', reused=True)
    if stopped and not submitted:
        return _finish(directory, 'cancelled')
    if profile_changed and not submitted:
        return _finish(directory, 'rejected', reason='profile_changed')
    if outcome == 'unknown' and not submitted and receipt.get('reused') is False:
        return _finish(directory, 'rejected', reason='submission_not_started')
    accepted = 0
    reason = None
    if outcome in ('unknown', 'cancelled'):
        accepted = _accepted_submissions(service, step_key, frozen, message, submitted)
        if stopped and accepted:
            outcome, reason = 'partial', 'stopped_after_submission'
        else:
            outcome = 'unknown'
            if receipt.get('reason') == 'receipt_write_failed':
                reason = 'provider_receipt_write_failed'
    result = _finish(directory, outcome, reason=reason, accepted=accepted)
    if interrupted:
        raise KeyboardInterrupt
    return result


def send_step(profile, message, *, expected_version, directory, checkpoint, run_key, sequence, service=None):
    """Submit a frozen profile once for this run and publish an anonymous local receipt."""
    profile, message, expected_version = alias(profile), validate_message(message), _version(expected_version)
    if type(sequence) is not int or not 1 <= sequence <= 10000:
        raise NotifyError('任务流程通知需要有效的步骤序号。')
    raw_key = json.dumps(['workflow_notify', text(run_key, maximum=512), sequence]).encode('utf8')
    step_key = hashlib.sha256(raw_key).hexdigest()
    checkpoint()
    directory = Path(directory).resolve() / f'notify-{sequence}'
    try:
        directory.mkdir()
    except FileExistsError:
        return _result(directory, 'unknown', reason='already_attempted', reused=True, saved=False)
    except OSError:
        return _result(directory, 'rejected', reason='intent_write_failed', saved=False)
    try:
        _write_new(directory / 'intent.json', dict(schema=1, key=step_key, status='pending'))
    except OSError:
        return _result(directory, 'rejected', reason='intent_write_failed', saved=False)
    try:
        checkpoint()
    except (Stopped, NotifyCancelled):
        return _finish(directory, 'cancelled')
    service = NotificationService() if service is None else service
    try:
        frozen = service.store.load_version(profile)
    except (NotifyError, OSError):
        return _finish(directory, 'rejected', reason='profile_unreadable')
    if frozen[1] != expected_version:
        return _finish(directory, 'rejected', reason='profile_changed')
    return _deliver(service, profile, message, frozen, step_key, directory, checkpoint)
