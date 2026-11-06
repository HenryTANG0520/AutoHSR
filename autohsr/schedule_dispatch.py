"""Frozen schedule targets use the existing task tree and native resource gates.

This module never registers an OS task or starts a Runner during validation.
Private manifests remain in the ignored schedule store, outside public events.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
import ctypes as C
import hashlib
import json
from pathlib import Path
import re

from .config import ROOT, Settings
from .schedule_plan import ScheduleError, ScheduleSourceUnverified, revision, validate as validate_plan
from .storage import hold_read_sources
from .task_workflow import GAME_TASKS, MAX_BYTES, compile_recipe, execution_tasks, loads, step_path, task_spec


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')


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


def _dependency_paths(configured):
    for node, current, options in configured:
        if node['task'] not in GAME_TASKS:
            for path in options.get('imports', []):
                yield path, 128 * 1024 * 1024
        if node['task'] == 'workflow_audio':
            yield options['path'], 32 * 1024 * 1024
        if node['task'] in ('workflow_image', 'workflow_text'):
            yield options['image'], 64 * 1024 * 1024
            if 'template' in options:
                yield options['template'], 64 * 1024 * 1024
        if node['task'] == 'workflow_game_image':
            yield options['workflow_screen_query']['template'], 64 * 1024 * 1024
        if node['task'] in ('daily', 'plan') and current.redemption_enabled and current.redemption_source == 'file':
            yield current.redemption_catalog, 256 * 1024


def _execution_busy():
    """Read both existing named markers without creating or stealing either."""
    from .workflow_lease import NAME, NATIVE_NAME, _kernel
    kernel = _kernel()
    for name in (NAME, NATIVE_NAME):
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

    def _checked_target(self, plan):
        target = validate_target(plan.get('target'))
        recipe, source = self._recipe(target)
        tasks = list(execution_tasks(recipe.steps))
        game = any(node['task'] in GAME_TASKS for node in tasks)
        if game and plan['repeat']['count'] != 1:
            raise ScheduleError('游戏计划重复须由同一任务树核对整批预算，不能分次建立新预算。')
        configured = []
        for node in tasks:
            if node['task'] == 'workflow_notify':
                raise ScheduleError('主动通知步骤须手动授权运行，应用内定时尚无该授权入口。')
            params = node.get('params', {})
            if node['task'] in GAME_TASKS and any(params.get(name) is True for name in
                    ('resume', 'resume_active', 'resume_weekly_currency')):
                raise ScheduleError('定时接续需要专用旧局版本协议；请先用手动原生入口核对。')
            try:
                current, options = task_spec(self.settings, node, recipe.base_dir)
            except Exception:
                raise ScheduleError('计划任务与冻结设置不兼容。') from None
            configured.append((node, current, options))
        return target, recipe, source, game, configured

    def preview_budget(self, plan):
        """Project one full trigger from an explicit saved definition or draft."""
        plan = validate_plan(plan)
        _, recipe, _, game, configured = self._checked_target(plan)
        return self._budget(plan, recipe, game, configured)

    def preview_activation(self, plan):
        """Bind the displayed budget to the sources that would be enabled."""
        plan = validate_plan(plan)
        checked = self._checked_target(plan)
        _, recipe, _, game, configured = checked
        return self._budget(plan, recipe, game, configured), self._manifest(checked)['sha256']

    @staticmethod
    def _budget(plan, recipe, game, configured):
        stamina = du_runs = 0
        # The compiled subtree reserves at most one daily and one DU owner
        # per possible path. Distinct enabled owners can only be alternatives.
        for node, current, options in configured:
            task = node['task']
            if task in ('daily', 'plan') and current.battle and current.allow_stamina_spend:
                stamina = max(stamina, current.stamina_limit)
            if task == 'differential_universe':
                du_runs = max(du_runs, options['du_runs'])
            elif task == 'plan' and current.weekly_enabled and current.weekly_mode == 'differential_universe':
                du_runs = max(du_runs, current.weekly_runs)
        count = plan['repeat']['count']
        return dict(id=plan['id'], revision=revision(plan), repeat_count=count, contains_game_tasks=game,
                    whole_batch=dict(workflow_steps=recipe.profile['executions'] * count,
                                     daily_stamina_max=stamina * count, du_runs_max=du_runs * count))

    def freeze(self, plan):
        return self._manifest(self._checked_target(plan))

    def _manifest(self, checked):
        target, recipe, source, game, configured = checked
        dependencies = {}
        for path, maximum in _dependency_paths(configured):
            entry = _fingerprint(path, maximum=maximum)
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
                    node['task'] in GAME_TASKS for node in execution_tasks(recipe.steps)):
                raise ValueError()
            for entry in manifest['dependencies']:
                if _fingerprint(entry['path'], maximum=entry['size']) != entry:
                    raise ValueError()
            if manifest['notification_versions']:
                from .notify_runtime import NotificationService
                service = self.notification_service or NotificationService()
                for name, version in manifest['notification_versions'].items():
                    service.store.require_version(name, version)
            Settings(**deepcopy(manifest['settings']))
        except Exception:
            raise ScheduleSourceUnverified('计划目标、输入文件、通知配置或冻结清单发生变化；未执行。') from None
        return True

    @contextmanager
    def _source_scope(self, manifest, bound_paths):
        paths = tuple(entry['path'] for entry in manifest['dependencies'])
        if bound_paths is not None and bound_paths != paths:
            raise ScheduleSourceUnverified('原生任务的输入文件与冻结计划不一致；未执行。')
        if manifest['source'] is not None:
            paths = (manifest['source']['path'], *paths)
        with ExitStack() as handles:
            try:
                handles.enter_context(hold_read_sources(paths))
            except (OSError, RuntimeError):
                raise ScheduleSourceUnverified('计划来源无法保持只读；未执行。') from None
            self.revalidate(manifest)
            yield

    def create(self, target, manifest, emit):
        manifest = deepcopy(manifest)
        self.revalidate(manifest)
        if target != manifest['target']:
            raise ScheduleError('计划目标与启用时冻结的版本不符。')
        settings = Settings(**deepcopy(manifest['settings']))
        try:
            recipe, source = self._recipe(target)
        except ScheduleError:
            raise ScheduleSourceUnverified('计划工作流在创建前无法读取；未执行。') from None
        if source != manifest['source']:
            raise ScheduleSourceUnverified('计划工作流在创建前发生变化；未执行。')
        factory = self.workflow_factory
        native = factory is None
        if native:
            from .task_workflow_run import TaskWorkflowRunner
            factory = TaskWorkflowRunner
        from .notify_runtime import hooks
        child_emit, wrap = hooks(settings, emit, service=self.notification_service)
        # TaskWorkflowRunner owns the existing sequence marker, child input mutex,
        # cross-step account proof, static budget and original child reports.
        runner = factory(settings, recipe.document, child_emit, selected_path=target.get('step_path'),
                         base_dir=recipe.base_dir, root=self.run_root)
        bound_paths = None
        if native:
            configured = ((node, *runner.specs[node['id']]) for node in execution_tasks(recipe.steps))
            bound_paths = tuple(dict.fromkeys(path for path, _ in _dependency_paths(configured)))
        return VerifiedScheduleRunner(wrap(runner), source_scope=lambda: self._source_scope(manifest, bound_paths))


class VerifiedScheduleRunner:
    """Reference the original saved report without rewriting its facts or bytes."""
    def __init__(self, runner, *, source_scope=nullcontext):
        self.runner = runner
        self._source_scope = source_scope
        self.schedule_source = None
        self.schedule_stopped = False

    def __getattr__(self, name):
        return getattr(self.runner, name)

    def run(self):
        with self._source_scope():
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
