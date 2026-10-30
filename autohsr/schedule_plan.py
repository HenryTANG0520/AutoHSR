"""Strict, inert in-process schedule definitions and Beijing-time calculations.

The minute-slot and next-time concepts reference March7thAssistant 7cf6c6b,
app/common/schedule.py (scheduled_task_slot / next_scheduled_datetime). No Qt,
timer, game input, startup registration or resource authorization is imported.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

CHINA = timezone(timedelta(hours=8))
MAX_BYTES = 65536
MAX_REPEAT = 1000


class ScheduleError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value):
        raise ScheduleError('计划名称标识须为小写字母开头的1～64位字母、数字、下划线或连字符。', 'id')
    return value


def _text(value, maximum=80):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum or
            any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ScheduleError('计划文字为空、过长或包含无效字符。')
    return value


def _keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ScheduleError('计划包含未知字段或缺少必需字段。')


def _integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise ScheduleError(f'计划{field}须为{low}～{high}的整数。', field)
    return value


def json_copy(value, *, maximum=MAX_BYTES):
    """Bound arbitrary dispatcher JSON without accepting custom objects or NaN."""
    def check(item, depth=0):
        if depth > 20:
            raise ScheduleError('计划JSON嵌套过深。')
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ScheduleError('计划JSON字段名须为文字。')
            for child in item.values():
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ScheduleError('计划JSON包含不支持的数据类型。')
    check(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                         separators=(',', ':')).encode('utf8')
        if len(raw) > maximum:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ScheduleError('计划JSON无效或超过大小限制。') from None
    return deepcopy(value)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ScheduleError('计划JSON包含重复字段。')
        value[key] = item
    return value


def loads(raw, *, maximum=MAX_BYTES):
    try:
        if isinstance(raw, bytes):
            if len(raw) > maximum:
                raise ValueError()
            raw = raw.decode('utf-8-sig')
        if not isinstance(raw, str) or len(raw.encode('utf8')) > maximum:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        return json_copy(value, maximum=maximum)
    except (ValueError, UnicodeError, RecursionError):
        raise ScheduleError('计划JSON无效或超过大小限制。') from None


def validate(value):
    """Return a canonical private definition; saving it never arms execution."""
    value = json_copy(value)
    _keys(value, ('version', 'id', 'name', 'time', 'weekdays', 'target', 'repeat',
                  'conflict', 'timeout_seconds'), ('version', 'id', 'name', 'time', 'target'))
    if type(value['version']) is not int or value['version'] != 1:
        raise ScheduleError('计划版本须为1。', 'version')
    identity(value['id']); _text(value['name'])
    if not isinstance(value['time'], str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value['time']):
        raise ScheduleError('计划时间须为北京时间HH:MM。', 'time')
    weekdays = value.get('weekdays', list(range(1, 8)))
    if (not isinstance(weekdays, list) or not weekdays or len(weekdays) > 7 or
            any(type(day) is not int or not 1 <= day <= 7 for day in weekdays) or
            len(set(weekdays)) != len(weekdays)):
        raise ScheduleError('计划星期须为不重复的1～7整数列表。', 'weekdays')
    value['weekdays'] = sorted(weekdays)
    target = value['target']
    if not isinstance(target, dict):
        raise ScheduleError('计划目标须为任务或流程对象。', 'target')
    if target.get('type') == 'task':
        _keys(target, ('type', 'task', 'params'), ('type', 'task'))
        if not isinstance(target['task'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', target['task']):
            raise ScheduleError('计划任务标识无效。', 'target')
        if not isinstance(target.get('params', {}), dict):
            raise ScheduleError('计划任务参数须为对象。', 'target')
        target.setdefault('params', {})
    elif target.get('type') == 'workflow':
        _keys(target, ('type', 'path', 'step_path'), ('type', 'path'))
        _text(target['path'], 4096)
        if 'step_path' in target and (not isinstance(target['step_path'], str) or
                not re.fullmatch(r'[0-9]+(?:/[0-9]+){0,11}', target['step_path'])):
            raise ScheduleError('计划步骤路径须为从0开始的序号，例如0/1。', 'target')
    else:
        raise ScheduleError('计划目标类型须为task或workflow。', 'target')
    repeat = value.get('repeat', {})
    _keys(repeat, ('count', 'interval_seconds'))
    value['repeat'] = dict(count=_integer(repeat.get('count', 1), 1, MAX_REPEAT, 'repeat.count'),
                          interval_seconds=_integer(repeat.get('interval_seconds', 0), 0, 86400, 'repeat.interval_seconds'))
    conflict = value.get('conflict', 'skip')
    if conflict not in ('skip', 'stop_owned'):
        raise ScheduleError('计划冲突策略须为skip或stop_owned。', 'conflict')
    value['conflict'] = conflict
    value['timeout_seconds'] = _integer(value.get('timeout_seconds', 0), 0, 604800, 'timeout_seconds')
    return json_copy(value)


def read(path):
    """Read only the explicitly selected definition; never load game settings."""
    try:
        with Path(path).open('rb') as stream:
            return validate(loads(stream.read(MAX_BYTES + 1)))
    except OSError:
        raise ScheduleError('计划文件无法读取。') from None


def revision(value):
    raw = json.dumps(validate(value), ensure_ascii=False, allow_nan=False, sort_keys=True,
                     separators=(',', ':')).encode('utf8')
    return hashlib.sha256(raw).hexdigest()


def local_time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ScheduleError('计划时钟须提供含时区的时间。')
    return value.astimezone(CHINA)


def due_slot(value, now):
    """Only this minute is eligible; never look back after sleep or downtime."""
    plan, now = validate(value), local_time(now)
    hour, minute = map(int, plan['time'].split(':'))
    if now.isoweekday() not in plan['weekdays'] or (now.hour, now.minute) != (hour, minute):
        return None
    return now.replace(second=0, microsecond=0)


def next_due(value, now):
    plan, now = validate(value), local_time(now)
    hour, minute = map(int, plan['time'].split(':'))
    for offset in range(8):
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=offset)
        if candidate.isoweekday() in plan['weekdays'] and candidate > now:
            return candidate
    raise ScheduleError('计划无法计算下一次运行时间。')


def preview(value, now, *, count=5):
    plan = validate(value)
    _integer(count, 1, 30, 'preview.count')
    times, cursor = [], local_time(now)
    for _ in range(count):
        cursor = next_due(plan, cursor)
        times.append(cursor.isoformat())
    return dict(id=plan['id'], name=plan['name'], revision=revision(plan), timezone='Asia/Shanghai',
                next_times=times, repeat=deepcopy(plan['repeat']), conflict=plan['conflict'],
                timeout_seconds=plan['timeout_seconds'], saved_does_not_enable=True,
                missed_policy='skip', startup_minute='skip', system_tasks_registered=False)
