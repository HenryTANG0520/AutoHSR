"""Opt-in end-of-run delivery; game reports remain unchanged on all outcomes."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import os
import string
import threading
import uuid

from .notify_profiles import DEFAULT_ROOT, MAX_BYTES, NotifyCancelled, NotifyError, ProfileStore, alias, text
from .notify_providers import execute
from .storage import replace_file

STATUSES = ('success', 'partial', 'failed', 'stopped')
TEMPLATE_FIELDS = {'operation', 'status', 'summary'}
OPERATIONS = {'daily': '日常', 'reward_only': '补领奖', 'plan': '日常与周常计划',
              'differential_universe': '差分宇宙', 'currency_wars_loop': '货币战争循环',
              'currency_wars_standard': '货币战争', 'currency_wars_points': '货币战争积分',
              'currency_wars_rewards': '货币战争领奖', 'task_workflow': '任务流程'}
STATUS_LABELS = dict(success='完成', partial='部分完成', failed='失败', stopped='停止')


def _template(value):
    text(value, maximum=4096)
    try:
        for _, field, spec, conversion in string.Formatter().parse(value):
            if field is not None and (field not in TEMPLATE_FIELDS or spec or conversion):
                raise ValueError()
    except ValueError:
        raise NotifyError('通知模板只支持operation、status、summary三个字段，不支持表达式或格式指令。') from None


def validate_settings(settings, *, strict=False):
    from .config import SettingsError
    if type(settings.notification_enabled) is not bool:
        raise SettingsError('notification_enabled', '通知总开关必须为布尔值。')
    if not strict and not settings.notification_enabled:
        return
    try:
        values = settings.notification_profiles
        if not isinstance(values, list) or len(values) > 32 or len(set(values)) != len(values):
            raise NotifyError('通知需要最多32个不重复配置名称。')
        for value in values:
            alias(value)
        statuses = settings.notification_statuses
        if not isinstance(statuses, list) or not statuses or any(type(s) is not str or s not in STATUSES for s in statuses) or len(set(statuses)) != len(statuses):
            raise NotifyError('通知状态须从success、partial、failed、stopped中明确选择。')
        if settings.notification_enabled and not values:
            raise NotifyError('启用通知需要明确选择已保存的通知配置。')
        _template(settings.notification_title)
        _template(settings.notification_body)
    except (NotifyError, TypeError):
        raise SettingsError('notification_profiles', '通知名称、状态或模板无效；请在通知设置核对。') from None


def report_message(settings, report):
    operation = OPERATIONS.get(report.get('operation'), '任务')
    status = STATUS_LABELS.get(report.get('status'), '未核实')
    if report.get('report_saved') is not True:
        status += '（报告未保存）'
    lines = ['本次运行：' + status]
    rows = report.get('results', [])
    if not isinstance(rows, list):
        rows = []
    tasks = {row.get('task') for row in rows if isinstance(row, dict) and isinstance(row.get('task'), str)}
    if report.get('daily_verified') is True or 'daily' in tasks:
        lines.append('每日实训：' + ('已核实' if report.get('daily_verified') is True else '未核实'))
    def number(value):
        return str(value) if type(value) is int and 0 <= value <= 1000000 else '未核实'
    if 'battle' in tasks or (type(report.get('stamina_spent')) is int and report['stamina_spent'] > 0):
        lines.append('副本完成：' + number(report.get('battle_completed')))
        lines.append('本次开拓力已记账：' + number(report.get('stamina_spent')) + '；待核对：' + number(report.get('stamina_pending')))
    du = report.get('differential_universe')
    if isinstance(du, dict) and du:
        lines.append('差分完成：' + number(du.get('completed_runs')) + '/' + number(du.get('requested_runs')))
    currency = report.get('currency_wars')
    if isinstance(currency, dict) and currency:
        if 'completed' in currency:
            lines.append('货币战争结算留档：' + number(currency.get('completed')) + '；胜利：' +
                         number(currency.get('victories')) + '；失败：' + number(currency.get('defeats')))
        if currency.get('points_verified') is True:
            lines.append('货币战争积分：已核实')
        if currency.get('rewards_verified') is True:
            lines.append('货币战争领奖：已核实')
    fields = dict(operation=operation, status=status, summary='\n'.join(lines))
    _template(settings.notification_title); _template(settings.notification_body)
    title, body = (settings.notification_title.format_map(fields), settings.notification_body.format_map(fields))
    if len(title.encode('utf-16-le')) > 320 or len(body.encode('utf-16-le')) > 8192:
        raise NotifyError('通知文本超过渠道通用长度上限，未截断为完整结果。')
    return title, body


def _write(path, value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
    if len(raw) > MAX_BYTES:
        raise NotifyError('通知回执超过64 KiB。')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    try:
        with temporary.open('wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(path):
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise NotifyError('同一条通知仍在发送，未重复提交。') from None
        try:
            yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class NotificationService:
    def __init__(self, *, root=None, request=None, local_send=None):
        self.root = Path(root) if root is not None else DEFAULT_ROOT
        self.store = ProfileStore(self.root)
        if request is None:
            from .notify_http import request
        self.request = request
        self.local_send = local_send

    def deliver(self, frozen, title, body, report_key, *, checkpoint=lambda: None):
        value, version = frozen
        identity, provider = value['id'], value['provider']
        key = hashlib.sha256((report_key + ':' + identity).encode('utf8')).hexdigest()
        path = self.root / 'attempts' / (key + '.json')
        public = dict(profile=identity, provider=provider, status='unknown', reused=False)
        with _lock(path.with_suffix('.lock')):
            if path.exists():
                try:
                    with path.open('rb') as stream:
                        raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError()
                    from .notify_profiles import loads
                    data = loads(raw)
                    if (not isinstance(data, dict) or data.get('schema') != 1 or data.get('key') != key or data.get('profile') != identity or
                            data.get('provider') != provider or not isinstance(data.get('actions'), list) or
                            data.get('status') not in ('pending', 'accepted', 'partial', 'rejected', 'unknown', 'cancelled')):
                        raise ValueError()
                    if any(not isinstance(action, dict) or action.get('phase') not in ('send', 'authorize', 'verify_room') or
                           type(action.get('index')) is not int or
                           action.get('status') not in ('pending', 'accepted', 'partial', 'rejected', 'unknown', 'cancelled', 'verified')
                           for action in data['actions']):
                        raise ValueError()
                    if data.get('profile_version') != version:
                        return dict(public, status='unknown', reused=True, reason='profile_changed')
                    if data['status'] == 'accepted' and (not any(a.get('phase') == 'send' for a in data['actions']) or
                            any(a.get('status') != ('accepted' if a.get('phase') == 'send' else 'verified') for a in data['actions'])):
                        raise ValueError()
                    return dict(public, status='unknown' if data['status'] == 'pending' else data['status'], reused=True)
                except (OSError, ValueError, TypeError):
                    raise NotifyError('旧通知回执无法核实，未重建或重复发送。') from None
            self.store.require_version(identity, version)
            data = dict(schema=1, key=key, profile=identity, provider=provider, status='pending', actions=[],
                        profile_version=version,
                        created_at=datetime.now().astimezone().isoformat(),
                        message_sha256=hashlib.sha256((title + '\n' + body).encode('utf8')).hexdigest())
            _write(path, data)
            def dispatch(phase, index):
                checkpoint(); self.store.require_version(identity, version)
                data['actions'].append(dict(phase=phase, index=index, status='pending'))
                _write(path, data)  # Durable before authorizing a network/local submission.
            def acknowledged(index, status):
                data['actions'][-1]['status'] = status
                _write(path, data)
            try:
                status = execute(value, title, body, key, request=self.request, checkpoint=checkpoint,
                                 dispatch=dispatch, acknowledged=acknowledged, local_send=self.local_send)
            except NotifyCancelled:
                status = 'unknown' if any(a['phase'] == 'send' and a['status'] == 'pending' for a in data['actions']) else 'cancelled'
            except Exception:
                status = 'unknown'
            data['status'] = status
            try:
                _write(path, data)
            except Exception:
                return dict(public, status='unknown', reason='receipt_write_failed')
            return dict(public, status=status)


class NotificationControl:
    def __init__(self, settings, emit, *, service=None):
        self.settings = replace(settings)
        self.emit = emit
        self.service = service or NotificationService()
        self.frozen = []
        self._stop = threading.Event()
        self._paused = threading.Event()
        self.game_done = False
        self._started = False
        self._run_lock = threading.Lock()
        self.run_token = uuid.uuid4().hex
        for identity in settings.notification_profiles:
            try:
                self.frozen.append((identity, self.service.store.load_version(identity)))
            except Exception:
                self.frozen.append((identity, None))

    def events(self, event):
        if event.get('type') != 'finished':
            self.emit(event)

    def checkpoint(self):
        while True:
            if self._stop.is_set():
                raise NotifyCancelled('通知发送已停止。')
            if not self._paused.is_set():
                return
            self._stop.wait(.05)

    def finish(self, report):
        report = report.to_dict() if hasattr(report, 'to_dict') else deepcopy(report)
        status = report.get('status')
        if status not in self.settings.notification_statuses:
            self.emit(dict(type='notification_summary', status='filtered', profiles=0))
            return
        title, body = report_message(self.settings, report)
        # Source path is hashed locally and never enters notification text.
        source = [report.get('run_dir') or self.run_token, report.get('started_at'), report.get('finished_at'), report.get('operation')]
        report_key = hashlib.sha256(json.dumps(source, ensure_ascii=False).encode('utf8')).hexdigest()
        outcomes = []
        for identity, frozen in self.frozen:
            try:
                self.checkpoint()
            except NotifyCancelled:
                break
            self.emit(dict(type='notification_phase', phase='notification', profile=identity,
                           game_status=status, status='running', requested_profiles=len(self.frozen)))
            if frozen is None:
                outcome = dict(profile=identity, status='rejected', reason='profile_unreadable')
            else:
                try:
                    outcome = self.service.deliver(frozen, title, body, report_key, checkpoint=self.checkpoint)
                except Exception:
                    outcome = dict(profile=identity, status='unknown', reason='notification_unverified')
            self.emit(dict(type='notification_result', **outcome))
            outcomes.append(outcome)
        self.emit(dict(type='notification_summary', status='cancelled' if self._stop.is_set() else
                       'accepted' if outcomes and all(row['status'] == 'accepted' for row in outcomes) else 'partial',
                       profiles=len(outcomes), requested_profiles=len(self.frozen),
                       accepted=sum(row['status'] == 'accepted' for row in outcomes)))


def _notification_key_state(runner):
    from .windows import user32
    hwnd = getattr(runner, '_control_hwnd', None)
    if type(hwnd) is not int or hwnd <= 0:
        hwnd = getattr(getattr(runner, '_window', None), 'hwnd', None)
    focused = type(hwnd) is int and hwnd > 0 and user32.GetForegroundWindow() == hwnd
    return (bool(user32.GetAsyncKeyState(0x78) & 0x8001),
            bool(user32.GetAsyncKeyState(0x79) & 0x8001), focused)


class NotificationRunner:
    def __init__(self, runner, control):
        self.runner, self.control = runner, control

    def __getattr__(self, name):
        return getattr(self.runner, name)

    @property
    def stop_requested(self):
        from .run_control import stop_requested
        return self.control._stop.is_set() or stop_requested(self.runner)

    def stop(self):
        self.control._stop.set()
        self.control._paused.clear()
        if not self.control.game_done:
            self.runner.stop()

    def toggle_pause(self):
        if not self.control.game_done:
            return self.runner.toggle_pause()
        if self.control._paused.is_set():
            self.control._paused.clear()
        else:
            self.control._paused.set()
        value = self.control._paused.is_set()
        self.control.emit(dict(type='paused', paused=value, phase='notification'))
        return value

    def _watch_notification_hotkeys(self, end):
        try:
            pause, stop, focused = _notification_key_state(self.runner)
            if stop:
                self.stop()
                return
            previous = pause
            while not end.wait(.05):
                pause, stop, focused = _notification_key_state(self.runner)
                if stop:
                    self.stop()
                    return
                if pause and not previous and focused:
                    self.toggle_pause()
                previous = pause
        except Exception:
            self.stop()
            self.control.emit(dict(type='log', level='error', phase='notification',
                                   message='通知快捷键监听失败，已停止后续通知。'))

    def _notify(self, report):
        # The child has released its inputs and joined its own hotkey listener.
        # Only the notification phase reads F9/F10 here, never concurrently with it.
        end = threading.Event()
        monitor = threading.Thread(target=self._watch_notification_hotkeys, args=(end,),
                                   name='AutoHSR-notification-hotkeys', daemon=True)
        monitor.start()
        try:
            self.control.finish(report)
        finally:
            end.set()
            monitor.join(timeout=1)

    def run(self):
        with self.control._run_lock:
            if self.control._started:
                raise NotifyError('同一个运行入口不会重复执行或重复通知。')
            self.control._started = True
        try:
            report = self.runner.run()
        except KeyboardInterrupt:
            self.stop()
            self.control.game_done = True
            raise
        except Exception:
            self.control.game_done = True
            try:
                self._notify(dict(status='failed', operation='unknown', report_saved=False))
            except (Exception, KeyboardInterrupt):
                pass
            raise
        self.control.game_done = True
        try:
            self._notify(report)
        except (Exception, KeyboardInterrupt):
            self.control.emit(dict(type='notification_summary', status='unknown', reason='notification_unverified'))
        data = report.to_dict() if hasattr(report, 'to_dict') else report
        self.control.emit(dict(type='finished', report=data))
        return report


def hooks(settings, emit, *, service=None):
    if not settings.notification_enabled:
        return emit, lambda runner: runner
    validate_settings(settings)
    control = NotificationControl(settings, emit, service=service)
    return control.events, lambda runner: NotificationRunner(runner, control)
