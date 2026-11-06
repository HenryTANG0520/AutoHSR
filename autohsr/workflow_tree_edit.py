"""Detached task-tree editing. Only a fully compiled tree can become a recipe."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import count
import json
import re

from .task_workflow import (
    MAX_DEPTH, MAX_NODES, TASKS, Recipe, WorkflowError,
    _boolean, _condition, _integer, _keys, _params, _text, compile_recipe, loads,
)


_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
_COMMON_FIELDS = {'id', 'type', 'name', 'enabled'}
_STEP_FIELDS = {
    'task': {'task', 'params', 'on_failure'},
    'wait': {'seconds'},
    'if': {'condition', 'steps', 'else_steps'},
    'for': {'count', 'steps'},
    'while': {'condition', 'max_iterations', 'steps'},
    'break': set(),
    'continue': set(),
    'stop': set(),
}
_CHILD_BRANCHES = {'if': ('steps', 'else_steps'), 'for': ('steps',), 'while': ('steps',)}


@dataclass(frozen=True)
class WorkflowTreeRow:
    identity: str
    parent_id: str | None
    branch: str
    path: tuple[int, ...]
    node: dict


def _json_snapshot(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf8')
    except (TypeError, ValueError, RecursionError) as error:
        raise WorkflowError('流程编辑内容须为有效JSON。') from error
    snapshot = loads(raw)
    if snapshot != value:
        raise WorkflowError('流程编辑包含无法原样表示的非JSON类型。')
    return snapshot


def _kind(node):
    kind = node.get('type') if isinstance(node, dict) else None
    if not isinstance(kind, str) or kind not in _STEP_FIELDS:
        raise WorkflowError('请选择正式流程步骤类型。')
    return kind


def _validate_task(node):
    task = node.get('task')
    if not isinstance(task, str) or task not in TASKS:
        raise WorkflowError('未知正式任务。')
    try:
        _params(task, node.get('params', {}))
    except WorkflowError:
        raise
    except ValueError as error:
        raise WorkflowError(str(error)) from error
    if node.get('on_failure', 'stop') not in ('stop', 'continue'):
        raise WorkflowError('失败策略须为stop或continue。')


def _validate_step(node, kind, *, in_loop):
    _keys(node, _COMMON_FIELDS | _STEP_FIELDS[kind], ('id', 'type'))
    if 'name' in node:
        _text(node['name'])
    _boolean(node.get('enabled', True))
    if kind in ('if', 'while'):
        condition = node.get('condition')
        reference = condition.get('step') if isinstance(condition, dict) else None
        if not isinstance(reference, str) or (reference != '@last' and not _ID.fullmatch(reference)):
            raise WorkflowError('条件须填写步骤ID或@last。')
        # The official validator checks the field/operator/value. Ordering and
        # whether the reference is still present are checked at Apply time.
        _condition(condition, {reference})
    if kind in ('break', 'continue') and not in_loop:
        raise WorkflowError('break／continue只能位于循环中。')
    if kind == 'task':
        _validate_task(node)
    elif kind == 'wait':
        _integer(node.get('seconds'), 0, 3600)
    elif kind == 'for':
        _integer(node.get('count'), 1, 1000)
    elif kind == 'while':
        _integer(node.get('max_iterations'), 1, 1000)


def _scan(document):
    fields = ('version', 'name', 'steps')
    _keys(document, fields, fields)
    if type(document['version']) is not int or document['version'] != 1:
        raise WorkflowError('流程版本必须为1。')
    _text(document['name'])
    rows = {}

    def walk(nodes, parent, branch, path, in_loop, offset=0):
        if not isinstance(nodes, list) or len(path) >= MAX_DEPTH:
            raise WorkflowError('步骤列表无效或嵌套过深。')
        for index, node in enumerate(nodes, offset):
            kind = _kind(node)
            _validate_step(node, kind, in_loop=in_loop)
            identity = node['id']
            if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in rows:
                raise WorkflowError('步骤ID必须唯一，且以英文字母开头。')
            if len(rows) >= MAX_NODES:
                raise WorkflowError('流程最多256个步骤。')
            row_path = (*path, index)
            rows[identity] = WorkflowTreeRow(identity, parent, branch, row_path, node)
            if kind in _CHILD_BRANCHES:
                children = node.get('steps')
                inside_loop = in_loop or kind in ('for', 'while')
                walk(children, identity, 'steps', row_path, inside_loop)
                if 'else_steps' in node:
                    walk(node['else_steps'], identity, 'else_steps', row_path, inside_loop, len(children))

    walk(document['steps'], None, 'steps', (), False)
    return rows


def _editable_fields(fields):
    fields = _json_snapshot(fields)
    if not isinstance(fields, dict) or {'id', 'steps', 'else_steps'} & fields.keys():
        raise WorkflowError('请编辑单个步骤的属性，步骤ID和子树由编辑器管理。')
    return fields


def _index(siblings, identity):
    return next(index for index, node in enumerate(siblings) if node['id'] == identity)


class WorkflowTreeDraft:
    """In-memory editor with stable node IDs and atomic structural edits."""

    def __init__(self, document):
        self._commit(document)
        self._issued = set(self._rows)

    @property
    def name(self) -> str:
        return self._document['name']

    @name.setter
    def name(self, value):
        candidate = dict(self._document, name=_text(value))
        self._commit(candidate)

    def _commit(self, candidate):
        document = _json_snapshot(candidate)
        rows = _scan(document)
        self._document, self._rows = document, rows

    def rows(self) -> tuple[WorkflowTreeRow, ...]:
        return tuple(deepcopy(row) for row in self._rows.values())

    def _row(self, identity):
        if not isinstance(identity, str) or identity not in self._rows:
            raise WorkflowError('所选流程步骤已不存在。')
        return self._rows[identity]

    def _siblings(self, document, parent_id, branch):
        parent = document
        if parent_id is not None:
            for index in self._row(parent_id).path:
                primary = parent['steps']
                parent = primary[index] if index < len(primary) else parent['else_steps'][index - len(primary)]
        return parent.setdefault(branch, [])

    def _new_identity(self):
        references = {row.node['condition']['step'] for row in self._rows.values()
                      if row.node['type'] in ('if', 'while')}
        reserved = self._issued | references
        for number in count(len(self._issued) + 1):
            identity = f'step_{number}'
            if identity not in reserved:
                return identity

    def add(self, fields, *, parent_id=None, branch='steps', after=None) -> str:
        """Append or insert after a sibling. New control steps start empty."""
        branches = ('steps',) if parent_id is None else _CHILD_BRANCHES.get(self._row(parent_id).node['type'], ())
        if branch not in branches:
            raise WorkflowError('当前步骤没有这个可编辑分支。')
        if after is not None:
            anchor = self._row(after)
            if anchor.parent_id != parent_id or anchor.branch != branch:
                raise WorkflowError('插入位置须位于同一分支。')
        fields = _editable_fields(fields)
        kind = _kind(fields)
        if fields.get('name') is None:
            fields.pop('name', None)
        identity = self._new_identity()
        node = dict(fields, id=identity)
        if kind in _CHILD_BRANCHES:
            node['steps'] = []
        candidate = deepcopy(self._document)
        siblings = self._siblings(candidate, parent_id, branch)
        position = len(siblings) if after is None else _index(siblings, after) + 1
        siblings.insert(position, node)
        self._commit(candidate)
        self._issued.add(identity)
        return identity

    def update(self, identity, fields):
        """Patch node properties, retaining its type, ID, and children."""
        row = self._row(identity)
        fields = _editable_fields(fields)
        if fields.get('type', row.node['type']) != row.node['type']:
            raise WorkflowError('编辑属性时须保留原步骤类型。')
        candidate = deepcopy(self._document)
        siblings = self._siblings(candidate, row.parent_id, row.branch)
        node = siblings[_index(siblings, identity)]
        if 'name' in fields and fields['name'] is None:
            node.pop('name', None)
            fields.pop('name')
        node.update(fields)
        self._commit(candidate)

    def remove(self, identity):
        row = self._row(identity)
        candidate = deepcopy(self._document)
        siblings = self._siblings(candidate, row.parent_id, row.branch)
        siblings.pop(_index(siblings, identity))
        self._commit(candidate)

    def move(self, identity, delta) -> bool:
        row = self._row(identity)
        if type(delta) is not int:
            raise WorkflowError('步骤移动量须为整数。')
        candidate = deepcopy(self._document)
        siblings = self._siblings(candidate, row.parent_id, row.branch)
        index = _index(siblings, identity)
        destination = index + delta
        if destination == index or not 0 <= destination < len(siblings):
            return False
        siblings.insert(destination, siblings.pop(index))
        self._commit(candidate)
        return True

    def validate(self, *, base_dir=None) -> Recipe:
        return compile_recipe(self._document, base_dir=base_dir)
