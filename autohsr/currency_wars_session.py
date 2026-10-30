"""Atomic continuity for one standard match; persisted input is never a replay."""
from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from pathlib import Path

from .currency_wars_state import strict_json
from .models import AutomationError
from .storage import replace_file
from .currency_wars_equipment_mode import FAST_FIELD,validate_fast_mode

MAX_ACTIONS = 4096
MAX_SESSION_BYTES = 64*1024*1024


def read_session(path):
    # Bound the actual read too: the file may grow after a stat check.
    with path.open('rb') as stream:
        raw=stream.read(MAX_SESSION_BYTES+1)
    if len(raw)>MAX_SESSION_BYTES:raise ValueError('对局记录超过64 MiB大小限制')
    return strict_json(raw.decode('utf-8'))


def require_session_access(data,resume):
    if not resume:
        if data is not None:raise AutomationError('已有标准对局记录，请使用明确的接续入口核对当前局，未重开。')
        return
    if data is None or data['status']!='active':
        raise AutomationError('没有已核实开始且可接续的标准对局；未知开局未重放。')
    if data['actions'] and data['actions'][-1]['status']!='verified' and data['actions'][-1]['action']!='open_standard_shop':
        raise AutomationError('上次标准动作尚未核实，先核对反馈，未接续输入。')


class StandardSession:
    def __init__(self, path):
        self.path = Path(path)
        self.data = None
        if self.path.exists():
            try:
                self.data = read_session(self.path)
                self.validate(self.data)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise AutomationError('标准对局记录需核对，未开始新对局：' + str(error)) from error

    @staticmethod
    def validate(data):
        if (type(data) is not dict or data.get('schema') != 1
                or not re.fullmatch(r'[0-9a-f]{32}', str(data.get('match_id', '')))
                or data.get('mode') != 'standard_development'
                or data.get('rank') != 8 or data.get('wealth') != 40
                or data.get('status') not in ('start_pending', 'active', 'settled', 'failed')
                or type(data.get('actions')) is not list or len(data['actions']) > MAX_ACTIONS
                or type(data.get('completion_verified')) is not bool
                or not isinstance(data.get('run_dir'), str)):
            raise ValueError('标准对局记录结构或难度无效')
        from .currency_wars_names import validate_name
        if 'remembrance_name' in data and validate_name(data['remembrance_name'])!=data['remembrance_name']:
            raise ValueError('对局记忆开拓者名称无效')
        if FAST_FIELD in data:validate_fast_mode(data[FAST_FIELD])
        if 'loop_owner' in data:
            from .currency_wars_loop_store import validate_owner
            validate_owner(data['loop_owner'])
        for index, action in enumerate(data['actions']):
            if (type(action) is not dict or action.get('id') != index
                    or not isinstance(action.get('action'), str)
                    or action.get('status') not in ('pending', 'verified', 'unknown')
                    or type(action.get('input_epoch')) is not int or action['input_epoch'] < 0):
                raise ValueError('标准对局动作记录无效')
        if data['completion_verified'] and data['status'] != 'settled':
            raise ValueError('未结算记录不能标记整局完成')
        if 'defeat_settlement_verified' in data:
            if type(data['defeat_settlement_verified']) is not bool:raise ValueError('失败结算标志无效')
            if data['defeat_settlement_verified']:
                from .currency_wars_defeat import settled
                if not settled(data):raise ValueError('失败结算缺少完整来源，不能标记结束')

    def persist(self):
        self.validate(self.data)
        raw=json.dumps(self.data,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
        if len(raw)>MAX_SESSION_BYTES:
            raise AutomationError('标准对局记录达到64 MiB上限，原文件保留，未提交新输入。')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(raw)
        replace_file(temporary, self.path)

    def begin(self, run_dir, entry):
        if self.data is not None:
            raise AutomationError('已有标准对局记录，须核对或接续，未创建第二个对局。')
        self.data = dict(schema=1, match_id=uuid.uuid4().hex, mode='standard_development', rank=8, wealth=40,
                         status='start_pending', run_dir=str(run_dir), entry=deepcopy(entry), actions=[],
                         completion_verified=False, action_status='observing', development_only=True)
        self.persist()

    def pending(self, action, epoch, before, expected):
        if self.data['actions'] and self.data['actions'][-1]['status'] != 'verified':
            raise AutomationError('上一步标准对局输入未核实，未发送后续动作。')
        if len(self.data['actions'])>=MAX_ACTIONS:
            raise AutomationError('标准对局动作记录达到本局上限，未追加或发送新动作。')
        item = dict(id=len(self.data['actions']), action=action, input_epoch=epoch, before=str(before),
                    expected=expected, status='pending')
        self.data['actions'].append(item)
        self.data.update(action_status='pending', screenshot=str(before))
        self.persist()
        return item

    def require_pending(self, action, epoch):
        # Read back the actual durable write, not only an in-memory intention.
        try:
            data = read_session(self.path)
            self.validate(data)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise AutomationError('标准对局输入记录未写入，未输入。') from error
        items = data['actions']
        if (data['match_id'] != self.data['match_id'] or data.get('remembrance_name','')!=self.data.get('remembrance_name','') or not items or
                data.get('loop_owner') != self.data.get('loop_owner') or
                data.get(FAST_FIELD,False) is not self.data.get(FAST_FIELD,False) or
                items[-1]['action'] != action or items[-1]['status'] != 'pending'
                or items[-1]['input_epoch'] != epoch):
            raise AutomationError('标准对局输入与本次已落盘意图不符。')
        return data
