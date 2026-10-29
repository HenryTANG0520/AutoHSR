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


class StandardSession:
    def __init__(self, path):
        self.path = Path(path)
        self.data = None
        if self.path.exists():
            try:
                if self.path.stat().st_size > 4*1024*1024:
                    raise ValueError('对局记录超过大小限制')
                self.data = strict_json(self.path.read_text(encoding='utf-8'))
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
                or type(data.get('actions')) is not list or len(data['actions']) > 4096
                or type(data.get('completion_verified')) is not bool
                or not isinstance(data.get('run_dir'), str)):
            raise ValueError('标准对局记录结构或难度无效')
        from .currency_wars_names import validate_name
        if 'remembrance_name' in data and validate_name(data['remembrance_name'])!=data['remembrance_name']:
            raise ValueError('对局记忆开拓者名称无效')
        for index, action in enumerate(data['actions']):
            if (type(action) is not dict or action.get('id') != index
                    or not isinstance(action.get('action'), str)
                    or action.get('status') not in ('pending', 'verified', 'unknown')
                    or type(action.get('input_epoch')) is not int or action['input_epoch'] < 0):
                raise ValueError('标准对局动作记录无效')
        if data['completion_verified'] and data['status'] != 'settled':
            raise ValueError('未结算记录不能标记整局完成')

    def persist(self):
        self.validate(self.data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
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
        item = dict(id=len(self.data['actions']), action=action, input_epoch=epoch, before=str(before),
                    expected=expected, status='pending')
        self.data['actions'].append(item)
        self.data.update(action_status='pending', screenshot=str(before))
        self.persist()
        return item

    def require_pending(self, action, epoch):
        # Read back the actual durable write, not only an in-memory intention.
        try:
            data = strict_json(self.path.read_text(encoding='utf-8'))
            self.validate(data)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise AutomationError('标准对局输入记录未写入，未输入。') from error
        items = data['actions']
        if (data['match_id'] != self.data['match_id'] or data.get('remembrance_name','')!=self.data.get('remembrance_name','') or not items or
                items[-1]['action'] != action or items[-1]['status'] != 'pending'
                or items[-1]['input_epoch'] != epoch):
            raise AutomationError('标准对局输入与本次已落盘意图不符。')
        return data
