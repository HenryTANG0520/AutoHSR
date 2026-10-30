"""Sequential task-tree execution with durable intentions and original reports."""
from __future__ import annotations

from copy import deepcopy
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
import operator
from pathlib import Path
import os
import threading
import time
import uuid

from .config import ROOT
from .models import RunReport, Stopped, TaskResult
from .storage import replace_file
from .task_workflow import GAME_TASKS, FIELDS, MAX_EXECUTIONS, WorkflowError, compile_recipe, task_spec
from .workflow_lease import workflow_lease


def _now():
    return datetime.now().astimezone().isoformat()


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')


def _write(path, value):
    raw = _bytes(value)
    if len(raw) > 64 * 1024 * 1024:
        raise WorkflowError('流程报告超过64 MiB；原报告保留。')
    temporary = path.with_suffix('.tmp')
    try:
        with temporary.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class WorkflowReport(RunReport):
    workflow: dict = field(default_factory=dict)


class _Halt(Exception):
    pass


class _Control(Exception):
    def __init__(self, kind):
        self.kind = kind


class TaskWorkflowRunner:
    def __init__(self, settings, document, emit=None, *, selected_path=None, base_dir=None,
                 root=None, runner_factory=None, plan_factory=None, currency_factory=None, warp_service=None):
        self.settings = replace(settings)
        self.recipe = compile_recipe(document, selected_path=selected_path, base_dir=base_dir)
        self.emit = emit or (lambda event: None)
        self.root = Path(root) if root is not None else ROOT / 'runs'
        self.factories = dict(runner=runner_factory, plan=plan_factory, currency=currency_factory)
        self.warp_service = warp_service
        self.specs = {}

        def prepare(nodes):
            for node in nodes:
                if not node.get('enabled', True):
                    continue
                if node['type'] == 'task':
                    self.specs[node['id']] = task_spec(self.settings, node, self.recipe.base_dir)
                prepare(node.get('steps', []))
                prepare(node.get('else_steps', []))
        prepare(self.recipe.steps)
        self.report = WorkflowReport(operation='task_workflow')
        self.child = None
        self._stop = threading.Event()
        self._end = threading.Event()
        self._lock = threading.RLock()
        self._paused = False
        self._control_hwnd = None
        self._started = False
        self._latest = {}
        self._input_blocked = False
        self._has_failure = False
        self._directory = None
        self._identity = None

    def stop(self):
        self._stop.set()
        with self._lock:
            if self.child is not None:
                self.child.stop()

    def toggle_pause(self):
        with self._lock:
            self._paused = self.child.toggle_pause() if self.child is not None else not self._paused
            value = self._paused
        self.emit(dict(type='paused', paused=value))
        return value

    def checkpoint(self):
        while True:
            if self._stop.is_set():
                raise Stopped('任务流程已停止；未继续后续步骤。')
            with self._lock:
                if not self._paused:
                    return
            self._stop.wait(.05)

    def _wait(self, seconds):
        # Paused time does not use the requested active waiting interval.
        remaining = seconds
        while remaining > 0:
            self.checkpoint()
            started = time.monotonic()
            self._stop.wait(min(.05, remaining))
            remaining -= time.monotonic() - started
        self.checkpoint()

    def _hotkeys(self):
        try:
            self._watch_hotkeys()
        except Exception:
            self.stop()
            self.emit(dict(type='log', level='error', message='流程快捷键监听失败，已请求停止。'))

    def _watch_hotkeys(self):
        from .windows import user32
        previous = bool(user32.GetAsyncKeyState(0x78) & 0x8000)
        while not self._end.wait(.05):
            if user32.GetAsyncKeyState(0x79) & 0x8001:
                self.stop()
            with self._lock:
                if self.child is not None:
                    previous = True
                    continue
                pressed = bool(user32.GetAsyncKeyState(0x78) & 0x8001)
                if pressed and not previous and self._control_hwnd is not None and user32.GetForegroundWindow() == self._control_hwnd:
                    self.toggle_pause()
                previous = pressed

    def _save(self):
        self.report.report_saved = True
        _write(self._directory / 'report.json', self.report.to_dict())

    def _record(self, data):
        # Intent is durable before child construction/run; no retry on failure.
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf8') + b'\n'
        with (self._directory / 'steps.jsonl').open('ab') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def _condition(self, condition):
        previous = self._latest.get(condition['step'])
        field = condition['field']
        if previous is None or type(previous.get(field)) is not FIELDS[field]:
            raise WorkflowError('条件依赖的步骤没有本次已知结果，未猜测为真或假。')
        compare = {'eq': operator.eq, 'ne': operator.ne, 'lt': operator.lt,
                   'le': operator.le, 'gt': operator.gt, 'ge': operator.ge}[condition['op']]
        return compare(previous[field], condition['value'])

    def _send(self, event, node):
        if event.get('type') == 'paused':
            with self._lock:
                self._paused = bool(event.get('paused'))
        # A child finishing cannot unlock the parent UI or claim total completion.
        if event.get('type') not in ('finished', 'warp_finished', 'warp_analysis_finished'):
            self.emit(dict(event, workflow_step=node['id'], workflow_task=node.get('task')))

    def _make_child(self, node):
        task = node['task']
        settings, options = self.specs[node['id']]
        options = deepcopy(options)
        if task == 'plan':
            from .plan_runner import PlanRunner
            factory = self.factories['plan'] or PlanRunner
        elif task == 'currency_wars_loop':
            from .currency_wars_loop import CurrencyLoopRunner
            factory = self.factories['currency'] or CurrencyLoopRunner
        else:
            from .app import Runner
            factory = self.factories['runner'] or Runner
        return factory(replace(settings), lambda event: self._send(event, node), **options)

    def _source(self, result, expected):
        if result.get('operation') != expected or result.get('report_saved') is not True:
            raise WorkflowError('任务未返回对应的已保存原始报告，未推进下一项。')
        path = Path(result.get('run_dir', '')) / 'report.json'
        with path.open('rb') as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024 or json.loads(raw) != json.loads(_bytes(result)):
            raise WorkflowError('原始报告与本次返回结果不一致，未推进下一项。')
        return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())

    def _facts(self, result):
        facts = dict(status=result.get('status', 'failed'))
        observed_daily = (result.get('daily_verified') is True or
                          any(row.get('task') == 'daily' for row in result.get('results', []) if isinstance(row, dict)))
        if (result.get('operation') in ('daily', 'plan') and observed_daily
                and type(result.get('daily_verified')) is bool):
            facts['daily_verified'] = result['daily_verified']
        currency = result.get('currency_wars', {})
        for name in ('victories', 'defeats', 'points_verified', 'rewards_verified'):
            if type(currency.get(name)) is FIELDS[name]:
                facts[name] = currency[name]
        if result.get('operation') == 'currency_wars_loop' and type(currency.get('completed')) is int:
            facts['completed_runs'] = currency['completed']
        if result.get('operation') == 'differential_universe':
            completed = result.get('differential_universe', {}).get('completed_runs')
            if type(completed) is int:
                facts['completed_runs'] = completed
        return facts

    def _copy_totals(self, result):
        # Static reservations admit at most one daily owner. DU post-daily is off.
        if result.get('operation') in ('daily', 'plan'):
            for key in ('stamina_spent', 'stamina_limit', 'stamina_pending', 'immersifiers_spent', 'immersifiers_pending',
                        'daily_verified', 'daily_synthesis', 'engagement', 'battle_completed', 'battle_requested',
                        'game_day', 'power_plan', 'team_selections', 'support_selections', 'weekly_plan'):
                if key in result:
                    setattr(self.report, key, deepcopy(result[key]))
        if result.get('currency_wars'):
            # Keep each task separately; a subsequent points query cannot erase victories.
            self.report.workflow.setdefault('currency_results', []).append(deepcopy(result['currency_wars']))
        if result.get('differential_universe'):
            self.report.differential_universe = deepcopy(result['differential_universe'])

    def _task(self, node, entry):
        game = node['task'] in GAME_TASKS
        if game and self._input_blocked:
            raise WorkflowError('此前游戏任务未核实完成；失败后继续只能处理本地步骤，不能再发送游戏输入。')
        self.checkpoint()
        expected = {'plan': 'plan', 'currency_wars_loop': 'currency_wars_loop'}.get(node['task'], node['task'])
        result = None
        identity_mark = self._identity.mark() if game else None
        try:
            if game:
                child = self._make_child(node)
                with self._lock:
                    self.child = child
                    if self._stop.is_set():
                        child.stop()
                    if self._paused:
                        child.toggle_pause()
                result = child.run()
                result = result.to_dict() if hasattr(result, 'to_dict') else result
            else:
                from .warp_service import run
                _, options = self.specs[node['id']]
                result = (self.warp_service or run)(**deepcopy(options), cancel=lambda: self.checkpoint(),
                                                   emit=lambda event: self._send(event, node))
                result = dict(result, operation=node['task'], report_saved=True,
                              run_dir=str(self._directory / ('tool-' + str(entry['sequence']))))
                Path(result['run_dir']).mkdir()
                _write(Path(result['run_dir']) / 'report.json', result)
            if not isinstance(result, dict) or result.get('status') not in ('success', 'partial', 'failed', 'stopped'):
                raise WorkflowError('任务返回了未知结果。')
            entry['source'] = self._source(result, expected)
            if not game or self._identity.has_step_proof(identity_mark):
                self._copy_totals(result)
            if game:
                self._identity.require_step(identity_mark)
                entry['account_verified'] = True
            entry['facts'] = self._facts(result)
            entry['status'] = result['status']
        except (Stopped, KeyboardInterrupt):
            self.stop()
            raise Stopped('当前任务已停止；流程未重试或继续下一项。')
        except Exception as error:
            entry.update(status='partial' if game else 'failed', error=str(error))
            entry['facts'] = {'status': entry['status']}
        finally:
            with self._lock:
                if self.child is not None:
                    child = self.child
                    hwnd = getattr(child, '_control_hwnd', None)
                    if not isinstance(hwnd, int):
                        hwnd = getattr(getattr(child, '_window', None), 'hwnd', None)
                    if isinstance(hwnd, int):
                        self._control_hwnd = hwnd
                    self.child = None
        if entry['status'] == 'stopped':
            raise Stopped('子任务已停止；未继续后续步骤。')
        if entry['status'] != 'success':
            self._has_failure = True
            self._input_blocked |= game
            if node.get('on_failure', 'stop') == 'stop':
                raise _Halt('步骤未完整完成；按失败策略停止。')

    def _steps(self, nodes, trail=()):
        for node in nodes:
            self.checkpoint()
            if len(self.report.workflow['steps']) >= MAX_EXECUTIONS:
                raise WorkflowError('流程已达到10000次执行上限，未继续。')
            entry = dict(sequence=len(self.report.workflow['steps']) + 1, step=node['id'], type=node['type'],
                         task=node.get('task'), trail=[list(item) for item in trail], status='running', started_at=_now())
            self.report.workflow['steps'].append(entry)
            self._record(dict(event='intent', **entry))
            self._save()
            self.emit(dict(type='workflow_step', step=node['id'], sequence=entry['sequence'], status='running'))
            try:
                if not node.get('enabled', True):
                    entry['status'] = 'skipped'
                elif node['type'] == 'task':
                    self._task(node, entry)
                elif node['type'] == 'wait':
                    self._wait(node['seconds'])
                elif node['type'] == 'if':
                    entry['condition'] = self._condition(node['condition'])
                    self._steps(node['steps'] if entry['condition'] else node.get('else_steps', []), trail)
                elif node['type'] in ('for', 'while'):
                    bound = node.get('count', node.get('max_iterations'))
                    for iteration in range(bound):
                        self.checkpoint()
                        if node['type'] == 'while' and not self._condition(node['condition']):
                            break
                        entry['iterations'] = iteration + 1
                        try:
                            self._steps(node['steps'], trail + ((node['id'], iteration),))
                        except _Control as control:
                            if control.kind == 'break':
                                break
                    else:
                        if node['type'] == 'while' and self._condition(node['condition']):
                            raise WorkflowError('while达到原定上限但条件仍成立；未声称循环已完成。')
                elif node['type'] in ('break', 'continue'):
                    raise _Control(node['type'])
                elif node['type'] == 'stop':
                    self.stop()
                    raise Stopped('流程遇到明确的停止步骤。')
                if entry['status'] == 'running':
                    entry['status'] = 'success'
            except _Control:
                entry['status'] = 'success'
                raise
            except (Stopped, KeyboardInterrupt):
                entry['status'] = 'stopped'
                raise
            except Exception as error:
                if entry['status'] == 'running':
                    entry['status'] = 'partial'
                entry.setdefault('error', str(error))
                raise
            finally:
                entry['finished_at'] = _now()
                self._latest[node['id']] = dict(entry.get('facts', {}), status=entry['status'])
                if node['type'] == 'task' and entry['status'] != 'skipped':
                    self._latest['@last'] = self._latest[node['id']]
                self._record(dict(event='result', **entry))
                self._save()
                self.emit(dict(type='workflow_step', step=node['id'], sequence=entry['sequence'], status=entry['status']))

    def run(self):
        with self._lock:
            if self._started:
                raise WorkflowError('同一流程Runner只能执行一次；不会重新创建预算。')
            self._started = True
        report = self.report
        directory = self.root / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_workflow_' + uuid.uuid4().hex[:8])
        directory.mkdir(parents=True)
        self._directory = directory
        report.run_dir, report.started_at, report.source = str(directory), _now(), str(self.root.parent)
        report.workflow = dict(name=self.recipe.document['name'], version=1, selected_path=list(self.recipe.path),
                               reservations=deepcopy(self.recipe.profile), steps=[], input_blocked=False,
                               automatic_retry=False, automatic_resume=False)
        monitor = None
        leases = ExitStack()
        try:
            leases.enter_context(workflow_lease())
            from .workflow_identity import WorkflowIdentity, account_scope
            required = any(node['task'] in GAME_TASKS for node in _tasks(self.recipe.steps))
            def publish_identity(public):
                report.workflow['identity'] = public
                self._save()
                self.emit(dict(type='workflow_identity', **public))
            self._identity = WorkflowIdentity(directory, required=required, publish=publish_identity)
            report.workflow['identity'] = self._identity.public()
            leases.enter_context(account_scope(self._identity))
            self.checkpoint()
            raw = _bytes(self.recipe.document)
            with (directory / 'workflow.json').open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            report.workflow['definition_sha256'] = hashlib.sha256(raw).hexdigest()
            self._save()
            if any(node['task'] in GAME_TASKS for node in _tasks(self.recipe.steps)):
                monitor = threading.Thread(target=self._hotkeys, name='AutoHSR-workflow-hotkeys', daemon=True)
                monitor.start()
            self._steps(self.recipe.steps)
            self.checkpoint()
            report.status = 'partial' if self._has_failure else 'success'
        except (Stopped, KeyboardInterrupt) as error:
            self.stop()
            report.status, report.error = 'stopped', str(error)
        except Exception as error:
            report.status = 'partial' if report.workflow['steps'] else 'failed'
            report.error = str(error)
        finally:
            self._end.set()
            if monitor is not None:
                monitor.join(timeout=1)
            report.workflow['input_blocked'] = self._input_blocked
            if self._identity is not None:
                report.workflow['identity'] = self._identity.public()
            report.finished_at = _now()
            report.safe_next = '查看各步骤原始报告；未完成步骤不自动重放。接续对局或领奖请使用对应正式入口。'
            report.results.append(TaskResult('task_workflow', 'ok' if report.status == 'success' else report.status,
                                             f"已记录{len(report.workflow['steps'])}次步骤执行；子任务结果分别保留。"))
            try:
                self._save()
            except Exception as error:
                report.report_saved = False
                report.report_write_error = str(error)
                report.status = 'partial'
                report.error = (report.error + '；' if report.error else '') + '流程报告保存失败。'
            try:
                self.emit(dict(type='finished', report=report.to_dict()))
            finally:
                leases.close()
        return report


def _tasks(nodes):
    for node in nodes:
        if node['type'] == 'task' and node.get('enabled', True):
            yield node
        if node.get('enabled', True):
            yield from _tasks(node.get('steps', []))
            yield from _tasks(node.get('else_steps', []))
