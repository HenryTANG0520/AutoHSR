"""Local immutable schedule versions and durable, single-claim minute slots."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .schedule_plan import (CHINA, MAX_BYTES, ScheduleError, due_slot, identity,
                            json_copy, loads, local_time, revision, validate)

RECEIPT_BYTES = 1024 * 1024
MANIFEST_BYTES = 262144
STATUSES = ('claimed', 'running', 'success', 'partial', 'failed', 'stopped', 'skipped', 'unknown')
TERMINAL = ('success', 'partial', 'failed', 'stopped', 'skipped', 'unknown')


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def source_reference(value):
    """Validate a private reference; the formal dispatcher verifies its bytes."""
    if (not isinstance(value, dict) or set(value) != {'report_path', 'sha256', 'size', 'operation'} or
            not isinstance(value['report_path'], str) or not value['report_path'].strip() or
            len(value['report_path']) > 4096 or any(ord(c) < 32 for c in value['report_path']) or
            not _digest(value['sha256']) or type(value['size']) is not int or
            not 1 <= value['size'] <= 64 * 1024 * 1024 or not isinstance(value['operation'], str) or
            not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value['operation'])):
        raise ScheduleError('计划原报告引用无效；未声明结果已核实。')
    return json_copy(value)


def _raw(value):
    value = json_copy(value, maximum=RECEIPT_BYTES)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf8')


def _read(path, maximum=RECEIPT_BYTES):
    try:
        with path.open('rb') as stream:
            raw = stream.read(maximum + 1)
        return loads(raw, maximum=maximum)
    except (OSError, ValueError):
        raise ScheduleError('计划或触发回执缺失、损坏或超过大小限制；未覆盖或重复执行。') from None


def _publish(path, value, *, exclusive=False):
    raw = _raw(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        return
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(path):
    """A local file lock, released by the OS on exit; no Windows named marker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ScheduleError('另一项计划存储操作仍在进行；未重复写入。') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class SlotClaim:
    key: str
    token: str


class ScheduleStore:
    def __init__(self, root):
        self.root = Path(root)

    def _definition(self, plan_id, digest):
        identity(plan_id)
        if not _digest(digest):
            raise ScheduleError('计划版本指纹无效。')
        return self.root / 'definitions' / plan_id / (digest + '.json')

    def save(self, value, *, replace=False, expected_revision=None):
        plan, digest = validate(value), revision(value)
        if type(replace) is not bool or expected_revision is not None and not _digest(expected_revision):
            raise ScheduleError('计划替换选项或原版本指纹无效。')
        pointer = self.root / 'plans' / (plan['id'] + '.json')
        with _lock(self.root / 'store.lock'):
            previous = self.load(plan['id'])[1] if pointer.exists() else None
            if previous is not None and not replace:
                raise ScheduleError('计划已存在；更新须明确替换。')
            if expected_revision is not None and previous != expected_revision:
                raise ScheduleError('计划版本已改变；未覆盖其他保存结果。')
            path = self._definition(plan['id'], digest)
            if path.exists():
                if _read(path, MAX_BYTES) != plan:
                    raise ScheduleError('原计划版本内容不符；未覆盖。')
            else:
                _publish(path, plan, exclusive=True)
            _publish(pointer, dict(schema=1, id=plan['id'], revision=digest))
        return dict(plan=deepcopy(plan), revision=digest, enabled=False)

    def load(self, plan_id):
        pointer = _read(self.root / 'plans' / (identity(plan_id) + '.json'), MAX_BYTES)
        if (not isinstance(pointer, dict) or set(pointer) != {'schema', 'id', 'revision'} or
                type(pointer['schema']) is not int or pointer['schema'] != 1 or pointer['id'] != plan_id):
            raise ScheduleError('计划当前版本指针无效；未执行。')
        return self._saved_plan(plan_id, pointer['revision']), pointer['revision']

    def _saved_plan(self, plan_id, digest):
        plan = validate(_read(self._definition(plan_id, digest), MAX_BYTES))
        if plan['id'] != plan_id or revision(plan) != digest:
            raise ScheduleError('计划版本内容与指纹不符；未执行。')
        return plan

    def list_public(self):
        directory = self.root / 'plans'
        if not directory.exists():
            return []
        values = []
        for path in sorted(directory.glob('*.json')):
            try:
                plan, digest = self.load(path.stem)
                values.append(dict(id=plan['id'], name=plan['name'], revision=digest,
                                   time=plan['time'], weekdays=plan['weekdays'], readable=True,
                                   enabled=False))
            except ScheduleError:
                values.append(dict(id=path.stem, readable=False, enabled=False))
        return values

    def _receipt_path(self, key):
        if not _digest(key):
            raise ScheduleError('计划触发指纹无效。')
        return self.root / 'slots' / (key + '.json')

    def _receipt(self, path):
        value = _read(path)
        required = {'schema', 'key', 'plan_id', 'revision', 'slot', 'manifest', 'status', 'token', 'attempts', 'reason'}
        if (not isinstance(value, dict) or set(value) != required or type(value.get('schema')) is not int or
                value['schema'] != 1 or value.get('key') != path.stem or not _digest(value.get('revision')) or
                not isinstance(value.get('token'), str) or not re.fullmatch(r'[0-9a-f]{32}', value['token']) or
                value.get('status') not in STATUSES or not isinstance(value.get('manifest'), dict) or
                not isinstance(value.get('attempts'), list) or len(value['attempts']) > 1000 or
                not isinstance(value.get('reason'), str)):
            raise ScheduleError('旧触发回执结构无效；未重建或重复执行。')
        identity(value['plan_id'])
        try:
            slot = local_time(datetime.fromisoformat(value['slot']))
            if slot.second or slot.microsecond or slot.isoformat() != value['slot']:
                raise ValueError()
        except (TypeError, ValueError):
            raise ScheduleError('旧触发时间无效；未重复执行。') from None
        key = self._slot_key(value['plan_id'], value['revision'], slot)
        if key != value['key']:
            raise ScheduleError('旧触发时间与指纹不符；未重复执行。')
        plan = self._saved_plan(value['plan_id'], value['revision'])
        if len(value['attempts']) > plan['repeat']['count']:
            raise ScheduleError('旧触发次数超过原计划；未重复执行。')
        for index, attempt in enumerate(value['attempts']):
            if (not isinstance(attempt, dict) or set(attempt) != {'index', 'status', 'result'} or
                    type(attempt['index']) is not int or attempt['index'] != index or
                    attempt['status'] not in ('pending', 'success', 'partial', 'failed', 'stopped', 'unknown') or
                    not isinstance(attempt['result'], dict) or
                    (attempt['result'] != {} if attempt['status'] == 'pending' else
                     attempt['result'].get('status') != attempt['status'])):
                raise ScheduleError('旧计划执行回执无效；未重复执行。')
            if 'source' in attempt['result']:
                source = source_reference(attempt['result']['source'])
                if source['operation'] != attempt['result'].get('operation'):
                    raise ScheduleError('旧计划原报告类型不符；未重复执行。')
        if value['status'] == 'success' and (len(value['attempts']) != plan['repeat']['count'] or
                any(attempt['status'] != 'success' for attempt in value['attempts'])):
            raise ScheduleError('旧计划成功回执缺少执行证明；未重复执行。')
        return value

    @staticmethod
    def _slot_key(plan_id, digest, slot):
        return hashlib.sha256((plan_id + '\0' + digest + '\0' + slot.isoformat()).encode('utf8')).hexdigest()

    def claim(self, value, digest, slot, manifest):
        plan, slot = validate(value), local_time(slot)
        if revision(plan) != digest or due_slot(plan, slot) != slot or slot.second or slot.microsecond:
            raise ScheduleError('计划触发时间或版本不符。')
        if self._saved_plan(plan['id'], digest) != plan:
            raise ScheduleError('触发定义与原保存版本不符。')
        if not isinstance(manifest, dict):
            raise ScheduleError('计划冻结清单须为对象。')
        manifest = json_copy(manifest, maximum=MANIFEST_BYTES)
        key = self._slot_key(plan['id'], digest, slot)
        path = self._receipt_path(key)
        data = dict(schema=1, key=key, plan_id=plan['id'], revision=digest, slot=slot.isoformat(),
                    manifest=manifest, status='claimed', token=uuid.uuid4().hex, attempts=[], reason='')
        with _lock(self.root / 'store.lock'):
            if path.exists():
                return None, deepcopy(self._receipt(path))
            _publish(path, data, exclusive=True)  # Intent is durable before a runner can be constructed.
        return SlotClaim(key, data['token']), deepcopy(data)

    def _change(self, claim, change):
        if not isinstance(claim, SlotClaim):
            raise ScheduleError('触发认领对象无效。')
        path = self._receipt_path(claim.key)
        with _lock(self.root / 'store.lock'):
            value = self._receipt(path)
            if value['token'] != claim.token or value['status'] in TERMINAL:
                raise ScheduleError('计划触发已结束或不属于本次执行；未重写。')
            change(value)
            _publish(path, value)
        return deepcopy(value)

    def begin_attempt(self, claim, index):
        def change(value):
            maximum = self._saved_plan(value['plan_id'], value['revision'])['repeat']['count']
            if type(index) is not int or index != len(value['attempts']) or not 0 <= index < maximum or (
                    value['attempts'] and value['attempts'][-1]['status'] != 'success'):
                raise ScheduleError('计划前次结果未核实成功；未开始下一次。')
            value['status'] = 'running'
            value['attempts'].append(dict(index=index, status='pending', result={}))
        return self._change(claim, change)

    def record_result(self, claim, index, summary):
        summary = json_copy(summary, maximum=MAX_BYTES)
        if not isinstance(summary, dict) or summary.get('status') not in ('success', 'partial', 'failed', 'stopped', 'unknown'):
            raise ScheduleError('计划子任务结果无效。')
        if 'source' in summary:
            source = source_reference(summary['source'])
            if source['operation'] != summary.get('operation'):
                raise ScheduleError('计划原报告类型不符。')
        def change(value):
            if (type(index) is not int or index != len(value['attempts']) - 1 or
                    not value['attempts'] or value['attempts'][-1]['status'] != 'pending'):
                raise ScheduleError('计划子任务回执顺序无效。')
            value['attempts'][-1].update(status=summary['status'], result=summary)
        return self._change(claim, change)

    def finish(self, claim, status, reason=''):
        if status not in TERMINAL or not isinstance(reason, str) or len(reason) > 128:
            raise ScheduleError('计划终态或原因无效。')
        def change(value):
            maximum = self._saved_plan(value['plan_id'], value['revision'])['repeat']['count']
            if status == 'success' and (len(value['attempts']) != maximum or
                    any(row['status'] != 'success' for row in value['attempts'])):
                raise ScheduleError('计划未核实全部成功；未写成功。')
            value.update(status=status, reason=reason)
        return self._change(claim, change)

    def receipts(self, plan_id=None):
        if plan_id is not None:
            identity(plan_id)
        directory = self.root / 'slots'
        if not directory.exists():
            return []
        values = []
        for path in sorted(directory.glob('*.json')):
            value = self._receipt(path)
            if plan_id is None or value['plan_id'] == plan_id:
                values.append(value)
        return values
