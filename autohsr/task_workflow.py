"""Strict, UI-neutral task trees; no coordinates, scripts, or implicit budgets.

Control-tree and selected-step concepts reference March7thAssistant's pinned
module/workflow (7cf6c6b). Task adapters use AutoHSR's own guarded Runners.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re

from .config import ROOT, Settings

MAX_BYTES = 1024 * 1024
MAX_NODES = 256
MAX_DEPTH = 12
MAX_EXECUTIONS = 10000
GAME_TASKS = {'daily', 'plan', 'differential_universe', 'currency_wars_loop',
              'currency_wars_points', 'currency_wars_rewards'}
TASKS = GAME_TASKS | {'warp_analysis', 'warp_export'}
DAILY_TASKS = ('assignments', 'battle', 'daily', 'mail', 'battlepass')
FIELDS = {'status': str, 'daily_verified': bool, 'completed_runs': int,
          'victories': int, 'defeats': int, 'points_verified': bool, 'rewards_verified': bool}


class WorkflowError(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowError('流程JSON包含重复字段。')
        result[key] = value
    return result


def loads(raw):
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            raise WorkflowError('流程文件超过1 MiB。')
        try:
            raw = raw.decode('utf-8-sig')
        except UnicodeError as error:
            raise WorkflowError('流程文件必须为UTF-8。') from error
    try:
        valid_size = isinstance(raw, str) and len(raw.encode('utf-8')) <= MAX_BYTES
    except UnicodeError as error:
        raise WorkflowError('流程文件不是有效的Unicode文本。') from error
    if not valid_size:
        raise WorkflowError('流程文件超过1 MiB或不是文本。')
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(WorkflowError('流程不能包含NaN或无穷值。')))
    except (ValueError, RecursionError) as error:
        if isinstance(error, WorkflowError):
            raise
        raise WorkflowError('流程JSON无效。') from error


def read(path):
    with Path(path).open('rb') as stream:
        return loads(stream.read(MAX_BYTES + 1))


def _keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise WorkflowError('流程包含未知字段或缺少必需字段。')


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise WorkflowError(f'流程整数必须在{low}～{high}之间。')
    return value


def _boolean(value):
    if type(value) is not bool:
        raise WorkflowError('流程开关必须为布尔值。')
    return value


def _text(value, limit=80):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise WorkflowError('流程文字为空、过长或包含控制字符。')
    return value


def step_path(value):
    if value is None:
        return ()
    if not isinstance(value, str) or not re.fullmatch(r'[/\\]*[0-9]+(?:[/\\][0-9]+)*[/\\]*', value):
        raise WorkflowError('步骤路径须为从0开始的序号，例如1/0。')
    parts = tuple(int(part) for part in value.replace('\\', '/').strip('/').split('/'))
    if len(parts) > MAX_DEPTH:
        raise WorkflowError('步骤路径过深。')
    return parts


def _condition(value, previous):
    _keys(value, ('step', 'field', 'op', 'value'), ('step', 'field', 'op', 'value'))
    field = value['field']
    if (not isinstance(value['step'], str) or not isinstance(field, str)
            or (value['step'] not in previous and not (value['step'] == '@last' and previous)) or field not in FIELDS):
        raise WorkflowError('条件只能引用前面步骤的已知结果字段。')
    if not isinstance(value['op'], str) or value['op'] not in ('eq', 'ne', 'lt', 'le', 'gt', 'ge'):
        raise WorkflowError('未知条件比较方式。')
    if type(value['value']) is not FIELDS[field] or (field == 'status' and value['value'] not in
            ('success', 'partial', 'failed', 'stopped', 'skipped')):
        raise WorkflowError('条件值的类型或状态无效。')
    if FIELDS[field] is not int and value['op'] not in ('eq', 'ne'):
        raise WorkflowError('只有计数字段支持大小比较。')
    if FIELDS[field] is int:
        _integer(value['value'], 0, 1000000)


def _params(task, params):
    allowed = {
        'daily': {'tasks', 'use_power_plan', 'stamina_limit', 'rounds', 'target_name', 'target_location',
                  'dungeon_category', 'challenge_count', 'use_support'},
        'plan': {'use_power_plan', 'resume_weekly_currency'},
        'differential_universe': {'runs', 'mode', 'team', 'save', 'rewards', 'resume_active', 'periodic_rank'},
        'currency_wars_loop': {'runs', 'resume', 'strategy', 'until_points', 'continue_after_defeat'},
        'currency_wars_points': set(),
        'currency_wars_rewards': {'resume'},
        'warp_analysis': {'imports'},
        'warp_export': {'imports', 'output', 'format', 'selected_uid'},
    }[task]
    _keys(params, allowed)
    for key in ('use_power_plan', 'use_support', 'resume_weekly_currency', 'save', 'rewards',
                'resume_active', 'resume', 'until_points', 'continue_after_defeat'):
        if key in params:
            _boolean(params[key])
    for key in ('target_name', 'target_location', 'team'):
        if key in params:
            _text(params[key], 120)
    if task == 'daily':
        selected = params.get('tasks')
        if ('tasks' in params and (not isinstance(selected, list) or not selected
                or any(not isinstance(t, str) or t not in DAILY_TASKS for t in selected)
                or len(set(selected)) != len(selected))):
            raise WorkflowError('日常任务须为不重复的正式任务名列表。')
        if params.get('use_power_plan', False) and selected is not None and 'battle' not in selected:
            raise WorkflowError('体力计划需要选择日常刷本。')
        if 'stamina_limit' in params:
            _integer(params['stamina_limit'], 0, 240)
        if 'rounds' in params:
            _integer(params['rounds'], 1, 100)
        if 'challenge_count' in params and params['challenge_count'] is not None:
            _integer(params['challenge_count'], 1, 6)
        if 'dungeon_category' in params:
            _text(params['dungeon_category'])
    if task in ('differential_universe', 'currency_wars_loop'):
        _integer(params.get('runs', 1), 1, 10)
    if task == 'differential_universe':
        if params.get('mode', 'periodic') not in ('periodic', 'normal'):
            raise WorkflowError('未知差分模式。')
        if params.get('resume_active', False) and params.get('runs', 1) != 1:
            raise WorkflowError('接续差分只能完成原有1局。')
        if 'periodic_rank' in params:
            _integer(params['periodic_rank'], 1, 10)
            if not params.get('resume_active', False):
                raise WorkflowError('接续难度需要明确接续差分。')
    if task == 'currency_wars_loop' and params.get('strategy', 'default') not in ('default', 'aglaea', 'seele'):
        raise WorkflowError('未知货币战争策略。')
    if task.startswith('warp_'):
        imports = params.get('imports')
        if not isinstance(imports, list) or not 1 <= len(imports) <= 32:
            raise WorkflowError('记录任务需要1～32份明确的本地JSON文件。')
        for path in imports:
            _text(path, 4096)
        if task == 'warp_export':
            _text(params.get('output'), 4096)
            if params.get('format', 'uigf') not in ('uigf', 'srgf', 'xlsx'):
                raise WorkflowError('未知记录导出格式。')
            if params.get('format') == 'xlsx' and Path(params['output']).suffix.lower() != '.xlsx':
                raise WorkflowError('Excel导出需要.xlsx扩展名。')
            if 'selected_uid' in params:
                from .warp_records import uid
                uid(params['selected_uid'])


def _profile(nodes):
    """Worst-case reservations: mutually exclusive branches use max, loops multiply."""
    total = dict(daily_calls=0, du_calls=0, currency_calls=0, du_runs=0, currency_games=0, executions=0)
    for node in nodes:
        kind = node['type']
        current = dict.fromkeys(total, 0)
        current['executions'] = 1
        if not node.get('enabled', True):
            total['executions'] += 1
            continue
        if kind == 'task':
            task = node['task']
            params = node.get('params', {})
            if task in ('daily', 'plan'):
                current['daily_calls'] = 1
            if task in ('differential_universe', 'plan'):
                current.update(du_calls=1, du_runs=params.get('runs', 1) if task != 'plan' else 10)
            if task in ('currency_wars_loop', 'plan'):
                current.update(currency_calls=1, currency_games=params.get('runs', 1) if task != 'plan' else 10)
        if kind in ('if', 'for', 'while'):
            nested = _profile(node['steps'])
            if kind == 'if':
                other = _profile(node.get('else_steps', []))
                nested = {key: max(nested[key], other[key]) for key in total}
            count = node.get('count', node.get('max_iterations', 1))
            for key in total:
                current[key] += nested[key] * count
        for key in total:
            total[key] += current[key]
    return total


@dataclass(frozen=True)
class Recipe:
    document: dict
    steps: list
    path: tuple
    profile: dict
    base_dir: Path


def compile_recipe(value, *, selected_path=None, base_dir=None):
    """Validate the whole tree, then reserve the selected subtree's maximum budget."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf8')
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise WorkflowError('流程不是可保存的JSON。') from error
    if len(encoded) > MAX_BYTES:
        raise WorkflowError('流程超过1 MiB。')
    document = deepcopy(value)
    _keys(document, ('version', 'name', 'steps'), ('version', 'name', 'steps'))
    if type(document['version']) is not int or document['version'] != 1:
        raise WorkflowError('流程版本必须为1。')
    _text(document['name'])
    seen = set()
    identities = set()

    def walk(nodes, depth=0, in_loop=False):
        if not isinstance(nodes, list) or depth >= MAX_DEPTH:
            raise WorkflowError('步骤列表无效或嵌套过深。')
        for node in nodes:
            if not isinstance(node, dict):
                raise WorkflowError('步骤必须为对象。')
            kind = node.get('type')
            fields = {'task': {'task', 'params', 'on_failure'}, 'wait': {'seconds'},
                      'if': {'condition', 'steps', 'else_steps'}, 'for': {'count', 'steps'},
                      'while': {'condition', 'max_iterations', 'steps'},
                      'break': set(), 'continue': set(), 'stop': set()}
            if not isinstance(kind, str) or kind not in fields:
                raise WorkflowError('未知步骤类型；底层坐标、脚本和原版YAML不能直接执行。')
            _keys(node, fields[kind] | {'id', 'name', 'enabled', 'type'}, ('id', 'type'))
            identity = node['id']
            if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', identity) or identity in identities:
                raise WorkflowError('步骤ID必须唯一，且以英文字母开头。')
            if len(identities) >= MAX_NODES:
                raise WorkflowError('流程最多256个步骤。')
            identities.add(identity)
            if 'name' in node:
                _text(node['name'])
            _boolean(node.get('enabled', True))
            if kind in ('if', 'while'):
                _condition(node.get('condition'), seen)
            if kind in ('break', 'continue') and not in_loop:
                raise WorkflowError('break／continue只能位于循环中。')
            if kind == 'task':
                if not isinstance(node.get('task'), str) or node['task'] not in TASKS:
                    raise WorkflowError('未知正式任务。')
                _params(node['task'], node.get('params', {}))
                if node.get('on_failure', 'stop') not in ('stop', 'continue'):
                    raise WorkflowError('失败策略须为stop或continue。')
            if kind == 'wait':
                _integer(node.get('seconds'), 0, 3600)
            if kind == 'for':
                _integer(node.get('count'), 1, 1000)
            if kind == 'while':
                _integer(node.get('max_iterations'), 1, 1000)
            if kind in ('if', 'for', 'while'):
                if not node.get('steps'):
                    raise WorkflowError('控制步骤必须包含子步骤。')
                walk(node['steps'], depth + 1, in_loop or kind in ('for', 'while'))
                if 'else_steps' in node:
                    walk(node['else_steps'], depth + 1, in_loop)
            seen.add(identity)

    if not isinstance(document['steps'], list) or not document['steps']:
        raise WorkflowError('流程至少需要一个步骤。')
    walk(document['steps'])
    path = step_path(selected_path)
    selected = document['steps']
    try:
        for offset, index in enumerate(path):
            node = selected[index]
            selected = [node] if offset == len(path) - 1 else node['steps'] + node.get('else_steps', [])
    except (IndexError, KeyError, TypeError) as error:
        raise WorkflowError('步骤路径越界或没有子步骤。') from error
    if path and selected[0]['type'] in ('break', 'continue'):
        raise WorkflowError('不能脱离循环单独执行break／continue。')
    profile = _profile(selected)
    if any(profile[key] > 1 for key in ('daily_calls', 'du_calls', 'currency_calls')):
        raise WorkflowError('一个流程路径最多一份日常预算、一个差分批次和一个货币战争批次；不能用重复步骤新增预算。')
    if profile['executions'] > MAX_EXECUTIONS:
        raise WorkflowError('流程展开超过10000步。')
    return Recipe(document, selected, path, profile, Path(base_dir or ROOT).resolve())


def task_spec(settings: Settings, node, base_dir):
    """Freeze a separate Settings copy; native constructors keep their own gates."""
    task, params = node['task'], deepcopy(node.get('params', {}))
    current = replace(settings)
    options = {}
    if task == 'daily':
        selected = params.pop('tasks', [name for name in DAILY_TASKS if getattr(current, name)])
        if not selected:
            raise WorkflowError('日常需要选择任务；体力计划需要刷本。')
        for key in DAILY_TASKS:
            setattr(current, key, key in selected)
        options['use_power_plan'] = params.pop('use_power_plan', False)
        if options['use_power_plan'] and 'battle' not in selected:
            raise WorkflowError('体力计划需要选择日常刷本。')
        for key, value in params.items():
            setattr(current, key, value)
        current.validate('power_plan' if options['use_power_plan'] else 'daily')
        options['operation'] = 'daily'
    elif task == 'plan':
        options = params
        current.validate('power_plan' if params.get('use_power_plan') else 'plan')
        if params.get('use_power_plan') and (not current.battle or params.get('resume_weekly_currency')):
            raise WorkflowError('体力计划需要本次刷本，不能混入原周常接续。')
        if params.get('resume_weekly_currency') and (not current.weekly_enabled or current.weekly_mode != 'currency_wars'):
            raise WorkflowError('计划接续须启用货币战争周常。')
    elif task == 'differential_universe':
        current.differential_universe_mode = params.get('mode', 'periodic')
        current.differential_universe_save = params.get('save', False)
        current.differential_universe_rewards = params.get('rewards', False)
        current.differential_universe_daily = False
        current.differential_universe_daily_from = ''
        if 'team' in params:
            current.differential_universe_team = params['team']
        options = dict(operation=task, du_runs=params.get('runs', 1), du_resume_active=params.get('resume_active', False),
                       du_periodic_rank=params.get('periodic_rank'))
        current.validate('differential_universe')
    elif task == 'currency_wars_loop':
        options = {('currency_strategy' if key == 'strategy' else key): value for key, value in params.items()}
        options.setdefault('runs', 1)
        current.validate('currency_wars')
    elif task in ('currency_wars_points', 'currency_wars_rewards'):
        options = dict(operation=task)
        if task == 'currency_wars_rewards':
            options['currency_rewards_resume'] = params.get('resume', False)
        current.validate('currency_wars')
    else:
        options = params
        options['imports'] = [str((base_dir / path).resolve()) for path in params['imports']]
        if 'output' in options:
            options['output'] = str((base_dir / options['output']).resolve())
        options['analysis_only'] = task == 'warp_analysis'
    return current, options
