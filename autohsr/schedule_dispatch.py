"""Frozen schedule targets use the existing task tree and native resource gates.

This module never registers an OS task or starts a Runner during validation.
Private manifests remain in the ignored schedule store, outside public events.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import ctypes as C
import hashlib
import json
from pathlib import Path
import re

from .config import ROOT, Settings
from .schedule_plan import ScheduleError
from .task_workflow import GAME_TASKS, MAX_BYTES, compile_recipe, loads, step_path, task_spec


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')


def _nodes(nodes):
    for node in nodes:
        if not node.get('enabled', True):
            continue
        yield node
        yield from _nodes(node.get('steps', []))
        yield from _nodes(node.get('else_steps', []))


def _text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 4096 or
            any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
        raise ScheduleError('计划目标路径无效。')
    return value


def validate_target(value):
    """Structure only: no target file, config, account or game is read."""
    if not isinstance(value, dict) or not isinstance(value.get('type'), str):
        raise ScheduleError('计划目标须明确选择workflow或task。')
    if value['type'] == 'workflow':
        if set(value) - {'type', 'path', 'step_path'} or 'path' not in value:
            raise ScheduleError('工作流目标包含未知字段或缺少路径。')
        _text(value['path'])
        try:
            step_path(value.get('step_path'))
        except Exception:
            raise ScheduleError('计划步骤路径无效。') from None
    elif value['type'] == 'task':
        if set(value) - {'type', 'task', 'params'} or 'task' not in value:
            raise ScheduleError('原生任务目标包含未知字段或缺少任务名。')
        try:
            compile_recipe(_single(value))
        except Exception:
            raise ScheduleError('计划中的正式任务或参数无效。') from None
    else:
        raise ScheduleError('计划只接受正式任务或任务树，不接受命令、脚本和坐标。')
    return deepcopy(value)


def _single(target):
    return dict(version=1, name='定时任务', steps=[dict(id='scheduled', type='task',
                task=target['task'], params=deepcopy(target.get('params', {})))])


def _fingerprint(path, *, maximum=128 * 1024 * 1024, raw=None):
    path = Path(path).resolve()
    if raw is not None:
        if len(raw) > maximum:
            raise ScheduleError('计划来源文件超过大小限制。')
        digest, size = hashlib.sha256(raw).hexdigest(), len(raw)
    else:
        size, hasher = 0, hashlib.sha256()
        try:
            with path.open('rb') as stream:
                while block := stream.read(65536):
                    size += len(block)
                    if size > maximum:
                        raise ScheduleError('计划来源文件超过大小限制。')
                    hasher.update(block)
        except OSError:
            raise ScheduleError('计划来源文件缺失或无法读取。') from None
        digest = hasher.hexdigest()
    return dict(path=str(path), sha256=digest, size=size)


def _execution_busy():
    """Read both existing named markers without creating or stealing either."""
    from .workflow_lease import NAME, _kernel
    kernel = _kernel()
    for name in (NAME, 'Local\\AutoHSR.DailyRunner'):
        C.set_last_error(0)
        handle = kernel.OpenMutexW(0x00100000, False, name)
        error = C.get_last_error()
        if handle:
            kernel.CloseHandle(handle)
            return True
        if error not in (0, 2):
            raise ScheduleError('无法核实当前执行权，未启动计划。')
    return False


class NativeScheduleExecutor:
    def __init__(self, settings, *, base_dir=None, run_root=None, workflow_factory=None,
                 busy_probe=None, notification_service=None):
        self.settings = replace(settings)
        self.base_dir = Path(base_dir or ROOT).resolve()
        self.run_root = Path(run_root) if run_root is not None else ROOT / 'runs'
        self.workflow_factory = workflow_factory
        self.busy_probe = busy_probe or _execution_busy
        self.notification_service = notification_service

    def busy(self):
        value = self.busy_probe()
        if type(value) is not bool:
            raise ScheduleError('当前执行权状态未核实。')
        return value

    def _recipe(self, target):
        target = validate_target(target)
        source = None
        if target['type'] == 'workflow':
            path = (self.base_dir / target['path']).resolve()
            try:
                with path.open('rb') as stream:
                    raw = stream.read(MAX_BYTES + 1)
                document = loads(raw)
            except Exception:
                raise ScheduleError('计划工作流无法读取或格式无效。') from None
            source = _fingerprint(path, maximum=MAX_BYTES, raw=raw)
            base = path.parent
        else:
            document, base = _single(target), self.base_dir
        try:
            recipe = compile_recipe(document, selected_path=target.get('step_path'), base_dir=base)
        except Exception:
            raise ScheduleError('计划工作流结构或资源预留无效。') from None
        return recipe, source

    def freeze(self, plan):
        target = validate_target(plan.get('target'))
        recipe, source = self._recipe(target)
        tasks = [node for node in _nodes(recipe.steps) if node['type'] == 'task']
        game = any(node['task'] in GAME_TASKS for node in tasks)
        if game and plan['repeat']['count'] != 1:
            raise ScheduleError('游戏计划重复须由同一任务树核对整批预算，不能分次建立新预算。')
        dependencies = {}
        for node in tasks:
            params = node.get('params', {})
            if node['task'] in GAME_TASKS and any(params.get(name) is True for name in
                    ('resume', 'resume_active', 'resume_weekly_currency')):
                raise ScheduleError('定时接续需要专用旧局版本协议；请先用手动原生入口核对。')
            try:
                _, options = task_spec(self.settings, node, recipe.base_dir)
            except Exception:
                raise ScheduleError('计划任务与冻结设置不兼容。') from None
            if node['task'] not in GAME_TASKS:
                for path in options.get('imports', []):
                    entry = _fingerprint(path)
                    dependencies[entry['path']] = entry
        versions = {}
        if self.settings.notification_enabled:
            from .notify_runtime import NotificationService, validate_settings
            try:
                validate_settings(self.settings)
                service = self.notification_service or NotificationService()
                for name in self.settings.notification_profiles:
                    _, versions[name] = service.store.load_version(name)
            except Exception:
                raise ScheduleError('计划通知配置尚未核实，未启用。') from None
        data = dict(schema=1, target=target, source=source, base_dir=str(recipe.base_dir),
                    settings=asdict(self.settings), dependencies=list(dependencies.values()),
                    notification_versions=versions, profile=recipe.profile, game=game)
        data['sha256'] = hashlib.sha256(_json(data)).hexdigest()
        return data

    def revalidate(self, manifest):
        expected = {'schema', 'target', 'source', 'base_dir', 'settings', 'dependencies',
                    'notification_versions', 'profile', 'game', 'sha256'}
        try:
            if (not isinstance(manifest, dict) or set(manifest) != expected or
                    type(manifest['schema']) is not int or manifest['schema'] != 1):
                raise ValueError()
            raw = {key: value for key, value in manifest.items() if key != 'sha256'}
            if not isinstance(manifest['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', manifest['sha256']):
                raise ValueError()
            if hashlib.sha256(_json(raw)).hexdigest() != manifest['sha256']:
                raise ValueError()
            recipe, source = self._recipe(manifest['target'])
            if source != manifest['source'] or str(recipe.base_dir) != manifest['base_dir'] or recipe.profile != manifest['profile']:
                raise ValueError()
            if type(manifest['game']) is not bool or manifest['game'] != any(
                    node['type'] == 'task' and node['task'] in GAME_TASKS for node in _nodes(recipe.steps)):
                raise ValueError()
            for entry in manifest['dependencies']:
                if _fingerprint(entry['path']) != entry:
                    raise ValueError()
            if manifest['notification_versions']:
                from .notify_runtime import NotificationService
                service = self.notification_service or NotificationService()
                for name, version in manifest['notification_versions'].items():
                    service.store.require_version(name, version)
            Settings(**deepcopy(manifest['settings']))
        except Exception:
            raise ScheduleError('计划目标、输入文件、通知配置或冻结清单发生变化；未执行。') from None
        return True

    def create(self, target, manifest, emit):
        self.revalidate(manifest)
        if target != manifest['target']:
            raise ScheduleError('计划目标与启用时冻结的版本不符。')
        settings = Settings(**deepcopy(manifest['settings']))
        recipe, source = self._recipe(target)
        if source != manifest['source']:
            raise ScheduleError('计划工作流在创建前发生变化；未执行。')
        if self.workflow_factory is None:
            from .task_workflow_run import TaskWorkflowRunner
            factory = TaskWorkflowRunner
        else:
            factory = self.workflow_factory
        from .notify_runtime import hooks
        child_emit, wrap = hooks(settings, emit, service=self.notification_service)
        # TaskWorkflowRunner owns the existing sequence marker, child input mutex,
        # cross-step account proof, static budget and original child reports.
        runner = factory(settings, recipe.document, child_emit, selected_path=target.get('step_path'),
                         base_dir=recipe.base_dir, root=self.run_root)
        return VerifiedScheduleRunner(wrap(runner))


class VerifiedScheduleRunner:
    """Reference the original saved report without rewriting its facts or bytes."""
    def __init__(self, runner):
        self.runner = runner
        self.schedule_source = None
        self.schedule_stopped = False

    def __getattr__(self, name):
        return getattr(self.runner, name)

    def run(self):
        report = self.runner.run()
        from .run_control import stop_requested
        self.schedule_stopped = stop_requested(self.runner, report)
        value = report.to_dict() if hasattr(report, 'to_dict') else report
        try:
            if not isinstance(value, dict) or value.get('report_saved') is not True:
                raise ValueError()
            directory = value.get('run_dir')
            if not isinstance(directory, str) or not directory:
                raise ValueError()
            path = (Path(directory) / 'report.json').resolve()
            with path.open('rb') as stream:
                raw = stream.read(64 * 1024 * 1024 + 1)
            if not raw or len(raw) > 64 * 1024 * 1024:
                raise ValueError()
            from .task_workflow import _pairs
            saved = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if _json(saved) != _json(value):
                raise ValueError()
            operation = value.get('operation')
            if not isinstance(operation, str) or not operation:
                raise ValueError()
        except Exception:
            raise ScheduleError('计划原任务报告未保存或与返回结果不一致；原报告保留，触发结果未核实。') from None
        self.schedule_source = dict(report_path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                                    size=len(raw), operation=operation)
        return report
