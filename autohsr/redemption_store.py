"""Private, durable redemption intents and immutable per-scope receipts."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import uuid

import numpy as np
from PIL import Image

from .models import AutomationError
from .redemption_codes import validate_code, validate_server
from .storage import replace_file


TERMINAL_STATUSES = frozenset(('redeemed', 'already_used', 'expired', 'invalid'))
ALL_STATUSES = TERMINAL_STATUSES | {'pending', 'unknown'}
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_BASIS_BYTES = 64 * 1024


class RedemptionStoreError(AutomationError):
    pass


def _fail(message='兑换记录或来源需核对；原件保留，未授权重复提交。'):
    raise RedemptionStoreError(message)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _pairs(items):
    data = {}
    for key, value in items:
        if key in data:
            _fail()
        data[key] = value
    return data


def _scope(account_key, server, code):
    if type(account_key) is not str or not re.fullmatch('[0-9a-f]{64}', account_key):
        _fail('兑换账号本地标识未核实。')
    try:
        validate_server(server)
        validate_code(code)
    except ValueError:
        _fail('兑换服务器或原始兑换码无效。')
    return account_key, server, code


def _basis(value):
    if type(value) is not dict or not value:
        _fail('兑换意图缺少明确页面来源。')
    try:
        raw = _json(value)
        if len(raw) > MAX_BASIS_BYTES:
            _fail('兑换页面来源超过有界记录范围。')
        return json.loads(raw, object_pairs_hook=_pairs)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail('兑换页面来源不是有界JSON对象。')


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _valid_stamp(value):
    if type(value) is not str:
        return False
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.tzinfo is not None and stamp.utcoffset() is not None
    except ValueError:
        return False


def _file(path, run_dir):
    try:
        root = Path(run_dir).resolve(strict=True)
        file = Path(path).resolve(strict=True)
        if not root.is_dir() or not file.is_file() or not file.is_relative_to(root):
            _fail('兑换证据必须来自本次运行目录。')
        with file.open('rb') as stream:
            raw = stream.read(32*1024*1024+1)
        if len(raw) > 32*1024*1024:
            _fail()
        with Image.open(io.BytesIO(raw)) as bitmap:
            if bitmap.format != 'PNG' or bitmap.width*bitmap.height > 16_777_216:
                _fail()
            image = np.asarray(bitmap.convert('RGB'))
        return dict(path=str(file), sha256=hashlib.sha256(raw).hexdigest(),
            pixel_sha256=hashlib.sha256(str(tuple(image.shape)).encode('ascii')+image.tobytes()).hexdigest(),
            shape=list(image.shape))
    except (OSError, TypeError, ValueError, Image.DecompressionBombError):
        _fail('兑换证据不可读取或不在本次运行范围；未补造来源。')


def _scope_data(entry):
    return {key: entry[key] for key in ('schema', 'id', 'account_key', 'server', 'code', 'run_dir', 'epoch')}


def _claim_digest(entry):
    return _digest(dict(scope=_scope_data(entry), claim={k: v for k, v in entry['claim'].items() if k != 'digest'}))


def _result_digest(entry):
    return _digest(dict(scope=_scope_data(entry), claim_digest=entry['claim']['digest'],
                        result={k: v for k, v in entry['result'].items() if k != 'digest'}))


def _validate_ref(reference, run_dir, *, verify=False):
    if (type(reference) is not dict or set(reference) != {'path', 'sha256', 'pixel_sha256', 'shape'}
            or type(reference['path']) is not str or not Path(reference['path']).is_absolute()
            or not Path(reference['path']).is_relative_to(Path(run_dir))
            or any(type(reference[k]) is not str or not re.fullmatch('[0-9a-f]{64}', reference[k])
                   for k in ('sha256', 'pixel_sha256'))
            or type(reference['shape']) is not list or len(reference['shape']) != 3
            or any(type(v) is not int or v <= 0 for v in reference['shape']) or reference['shape'][2] != 3):
        _fail()
    if verify and _file(reference['path'], run_dir) != reference:
        _fail('兑换原证据已改变；未覆写原回执。')


def _validate_entry(entry, *, verify=False):
    if (type(entry) is not dict or set(entry) != {'schema', 'id', 'account_key', 'server', 'code',
            'status', 'run_dir', 'epoch', 'claim', 'result'} or type(entry.get('schema')) is not int or entry.get('schema') != 1
            or type(entry.get('id')) is not str or not re.fullmatch('[0-9a-f]{32}', entry['id'])
            or entry.get('status') not in ALL_STATUSES or type(entry.get('epoch')) is not int or entry['epoch'] < 0
            or type(entry.get('run_dir')) is not str or not Path(entry['run_dir']).is_absolute()):
        _fail()
    _scope(entry['account_key'], entry['server'], entry['code'])
    claim = entry['claim']
    if (type(claim) is not dict or set(claim) != {'evidence', 'basis', 'recorded_at', 'digest'}
            or not _valid_stamp(claim['recorded_at']) or _basis(claim['basis']) != claim['basis']
            or claim['digest'] != _claim_digest(entry)):
        _fail()
    _validate_ref(claim['evidence'], entry['run_dir'], verify=verify)
    result = entry['result']
    if entry['status'] == 'pending':
        if result is not None:
            _fail()
    else:
        if (type(result) is not dict or set(result) != {'status', 'evidence', 'basis', 'recorded_at', 'digest'}
                or result['status'] != entry['status'] or not _valid_stamp(result['recorded_at'])
                or _basis(result['basis']) != result['basis'] or type(result['evidence']) is not list
                or not 1 <= len(result['evidence']) <= 4 or result['digest'] != _result_digest(entry)):
            _fail()
        paths = [r.get('path') for r in result['evidence']]
        if len(set(paths)) != len(paths) or entry['status'] in TERMINAL_STATUSES and len(paths) < 2:
            _fail()
        for reference in result['evidence']:
            _validate_ref(reference, entry['run_dir'], verify=verify)


class RedemptionStore:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def _read(self):
        if not self.path.exists():
            return dict(schema=1, generation=0, entries=[])
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(MAX_LEDGER_BYTES+1)
            if len(raw) > MAX_LEDGER_BYTES:
                _fail()
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
            if (type(data) is not dict or set(data) != {'schema', 'generation', 'entries'}
                    or type(data['schema']) is not int or data['schema'] != 1
                    or type(data['generation']) is not int or data['generation'] < 0
                    or type(data['entries']) is not list or len(data['entries']) > MAX_ENTRIES):
                _fail()
            ids, scopes = set(), set()
            for entry in data['entries']:
                _validate_entry(entry)
                scope = _scope(entry['account_key'], entry['server'], entry['code'])
                if entry['id'] in ids or scope in scopes:
                    _fail()
                ids.add(entry['id']); scopes.add(scope)
            return data
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            _fail('兑换账本损坏或不可读取；保留原件，未创建替代记录。')

    @contextmanager
    def _locked(self):
        lock = self.path.with_name(self.path.name+'.lock')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError:
            _fail('兑换账本正由其他提交持有或需核对，未覆盖已有意图。')
        try:
            yield
        finally:
            os.close(descriptor)
            try:
                lock.unlink()
            except OSError:
                _fail('兑换账本执行归属未能释放；保留已有记录。')

    def _write(self, data):
        try:
            raw = _json(data)
            if len(raw) > MAX_LEDGER_BYTES:
                _fail('兑换账本已达有界上限，未授权新输入。')
            temporary = self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.pending')
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            replace_file(temporary, self.path)
        except (OSError, TypeError, ValueError):
            _fail('兑换记录未能原子保存；不得提交或重放兑换。')

    @staticmethod
    def _find(data, account_key, server, code):
        return next((entry for entry in data['entries'] if
            (entry['account_key'], entry['server'], entry['code']) == (account_key, server, code)), None)

    def lookup(self, account_key, server, code):
        _scope(account_key, server, code)
        entry = self._find(self._read(), account_key, server, code)
        if entry is not None:
            _validate_entry(entry, verify=True)
        return deepcopy(entry)

    def claim(self, account_key, server, code, *, run_dir, epoch, evidence, basis):
        _scope(account_key, server, code)
        if type(epoch) is not int or epoch < 0:
            _fail('兑换输入代次未核实。')
        proof = _file(evidence, run_dir)
        origin = _basis(basis)
        with self._locked():
            data = self._read()
            if self._find(data, account_key, server, code) is not None or len(data['entries']) >= MAX_ENTRIES:
                _fail('该账号与服务器已有此原始兑换码记录；未创建重复提交。')
            entry = dict(schema=1, id=uuid.uuid4().hex, account_key=account_key, server=server, code=code,
                status='pending', run_dir=str(Path(run_dir).resolve(strict=True)), epoch=epoch,
                claim=dict(evidence=proof, basis=origin, recorded_at=_stamp()), result=None)
            entry['claim']['digest'] = _claim_digest(entry)
            _validate_entry(entry, verify=True)
            data['entries'].append(entry); data['generation'] += 1
            self._write(data)
        return deepcopy(entry)

    def require_pending(self, entry_id, account_key, server, code, epoch):
        _scope(account_key, server, code)
        entry = self._find(self._read(), account_key, server, code)
        if (entry is None or entry['id'] != entry_id or entry['status'] != 'pending'
                or type(epoch) is not int or entry['epoch'] != epoch):
            _fail('兑换输入与实际落盘的本次待提交意图不符。')
        _validate_entry(entry, verify=True)
        return deepcopy(entry)

    def finish(self, entry_id, status, *, evidence, basis):
        if type(status) is not str or status not in TERMINAL_STATUSES | {'unknown'}:
            _fail('兑换结果类型未独立核实。')
        paths = list(evidence) if type(evidence) in (list, tuple) else [evidence]
        if not 1 <= len(paths) <= 4 or status in TERMINAL_STATUSES and len(paths) < 2:
            _fail('兑换终态须有两份独立结果证据。')
        with self._locked():
            data = self._read()
            entry = next((e for e in data['entries'] if e['id'] == entry_id), None)
            if entry is None:
                _fail()
            _validate_entry(entry, verify=True)
            refs = [_file(path, entry['run_dir']) for path in paths]
            if len({r['path'] for r in refs}) != len(refs):
                _fail('兑换结果不能重复使用同一证据文件。')
            origin = _basis(basis)
            if entry['status'] != 'pending':
                old = entry['result']
                if entry['status'] == status and old['evidence'] == refs and old['basis'] == origin:
                    return deepcopy(entry)
                _fail('兑换原终态或未知回执不可覆盖；没有重发提交。')
            entry['status'] = status
            entry['result'] = dict(status=status, evidence=refs, basis=origin, recorded_at=_stamp())
            entry['result']['digest'] = _result_digest(entry)
            _validate_entry(entry, verify=True)
            data['generation'] += 1
            self._write(data)
        return deepcopy(entry)

    def public_summary(self, account_key=None, server=None):
        if account_key is not None and (type(account_key) is not str or not re.fullmatch('[0-9a-f]{64}', account_key)):
            _fail()
        if server is not None:
            validate_server(server)
        counts = {status: 0 for status in sorted(ALL_STATUSES)}
        for entry in self._read()['entries']:
            if (account_key is None or entry['account_key'] == account_key) and (server is None or entry['server'] == server):
                counts[entry['status']] += 1
        return dict(server=server, total=sum(counts.values()), statuses=counts)
