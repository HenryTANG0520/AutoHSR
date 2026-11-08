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
import re
import threading
import time
from typing import TYPE_CHECKING
import uuid

from .config import ROOT
from .daily_observe import ACHIEVEMENT_CLAIM_OPERATION, EVENT_CLAIM_OPERATION
from .du_points_followup import FollowupWeek, followup_week_scope
from .models import AutomationError, RunReport, Stopped, TaskResult
from .storage import replace_file
from .task_workflow import (ASSIGNMENT_REWARDS_TASK, FIELDS, FREE_ATTACHMENT_TASK, GAME_CAPTURE_TASK, GAME_TASKS, GAME_VISION_TASKS,
                            MAX_EXECUTIONS, PAGE_TASK, REDEMPTION_TASK, TEMPLATE_TASKS,
                            TRAINING_REWARDS_TASK, TRAINING_SCAN_PAGE, TRAINING_SYNTHESIS_TASK, VISA_CHARACTERS_PAGE, VISION_TASKS,
                            WORKFLOW_FOREGROUND_TASKS, WorkflowError,
                            compile_recipe, execution_task, task_spec, workflow_notification_png_path)
from .task_workflow import execution_tasks as _tasks
from .workflow_lease import workflow_lease

if TYPE_CHECKING:
    from .reward_guide_notify import PngSource


def _now():
    return datetime.now().astimezone().isoformat()


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')


def _write(path, value, *, refresh=None):
    temporary = path.with_suffix('.tmp')

    def prepare(data):
        raw = _bytes(data)
        if len(raw) > 64 * 1024 * 1024:
            raise WorkflowError('流程报告超过64 MiB；原报告保留。')
        with temporary.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def before_replace():
        revised = refresh()
        if revised is not None:
            prepare(revised)

    try:
        prepare(value)
        if refresh is None:
            replace_file(temporary, path)
        else:
            replace_file(temporary, path, before_replace=before_replace)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class WorkflowReport(RunReport):
    workflow: dict = field(default_factory=dict)


class _Halt(Exception):
    pass


class _ConditionExpired(WorkflowError):
    pass


class _Control(Exception):
    def __init__(self, kind):
        self.kind = kind


class TaskWorkflowRunner:
    def __init__(self, settings, document, emit=None, *, selected_path=None, base_dir=None,
                 root=None, runner_factory=None, plan_factory=None, currency_factory=None, warp_service=None,
                 notification_versions=None, notification_service=None, wait_for_foreground=False,
                 notification_image=None, allow_capture_notify=False):
        if type(wait_for_foreground) is not bool:
            raise WorkflowError('任务流前台等待选项无效。')
        self.settings = replace(settings)
        self.recipe = compile_recipe(document, selected_path=selected_path, base_dir=base_dir)
        aliases = step_notification_aliases(self.recipe)
        versions = {} if notification_versions is None else notification_versions
        if (type(versions) is not dict or set(versions) != set(aliases)
                or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
                       for value in versions.values())):
            raise WorkflowError('任务流程含主动通知，须先明确授权并核实通知方案。')
        self.notification_versions = dict(versions)
        images = step_notification_images(self.recipe)
        if images or notification_image is not None:
            if (not isinstance(notification_image, WorkflowNotificationImage)
                    or images != {(str(notification_image.source.path), notification_image.profile)}):
                raise WorkflowError('任务流程的图片通知须明确授权同一份本地 PNG 和 SMTP 方案。')
        self.notification_image = notification_image
        if type(allow_capture_notify) is not bool or bool(step_notification_captures(self.recipe)) != allow_capture_notify:
            raise WorkflowError('须明确授权本次任务流向已保存的截图通知方案发送游戏截图。')
        self.notification_service = notification_service
        self.emit = emit or (lambda event: None)
        self.root = Path(root) if root is not None else ROOT / 'runs'
        self.factories = dict(runner=runner_factory, plan=plan_factory, currency=currency_factory)
        self.warp_service = warp_service
        self.specs = {node['id']: task_spec(self.settings, node, self.recipe.base_dir)
                      for node in _tasks(self.recipe.steps)}
        self.report = WorkflowReport(operation='task_workflow')
        self.child = None
        self._stop = threading.Event()
        self._end = threading.Event()
        self._lock = threading.RLock()
        self._paused = False
        self._pause_generation = 0
        self._control_hwnd = None
        self._started = False
        self._latest = {}
        self._input_blocked = False
        self._notification_blocked = False
        self._has_failure = False
        self._directory = None
        self._identity = None
        self._du_points_step = None
        self._screen_sources = set()
        self._initial_foreground_pending = wait_for_foreground

    @property
    def stop_requested(self):
        """Control intent survives a partial or unsaved final report."""
        from .run_control import stop_requested
        return self._stop.is_set() or stop_requested(self.child)

    def _notice_stopped(self, report):
        from .run_control import stop_requested
        if stop_requested(self.child, report):
            self.stop()

    def stop(self):
        self._stop.set()
        with self._lock:
            if self.child is not None:
                self.child.stop()

    def toggle_pause(self):
        with self._lock:
            self._paused = self.child.toggle_pause() if self.child is not None else not self._paused
            self._pause_generation += 1
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
        report = self.report
        report.report_saved = True
        path = self._directory / 'report.json'
        if not report.finished_at or self._du_points_step is None:
            _write(path, report.to_dict())
            return
        expired = None

        def refresh():
            nonlocal expired
            change = self._expire_du_points_week()
            if change is None:
                return None
            expired, _ = change
            if report.status == 'success':
                report.status = 'partial'
                report.error = expired['error']
                report.results[-1].status = 'partial'
            return report.to_dict()

        _write(path, report.to_dict(), refresh=refresh)
        if expired is not None:
            self._emit_du_points_expiry(expired)

    def _record(self, data):
        # Intent is durable before child construction/run; no retry on failure.
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf8') + b'\n'
        with (self._directory / 'steps.jsonl').open('ab') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def _condition(self, condition):
        self.checkpoint()
        self._check_du_points_week()
        previous = self._latest.get(condition['step'])
        field = condition['field']
        if previous is None or type(previous.get(field)) is not FIELDS[field]:
            raise WorkflowError('条件依赖的步骤没有本次已知结果，未猜测为真或假。')
        if field in ('training_activity', 'synthesis_needed', 'photo_needed'):
            from .du_daily import game_day

            if previous.get('_training_game_day') != game_day():
                raise WorkflowError('实训条件已跨游戏日，请重新读取卡片。')
        compare = {'eq': operator.eq, 'ne': operator.ne, 'lt': operator.lt,
                   'le': operator.le, 'gt': operator.gt, 'ge': operator.ge}[condition['op']]
        return compare(previous[field], condition['value'])

    def _send(self, event, node):
        if event.get('type') == 'paused':
            with self._lock:
                paused = bool(event.get('paused'))
                if paused != self._paused:
                    self._pause_generation += 1
                self._paused = paused
        # A child finishing cannot unlock the parent UI or claim total completion.
        if event.get('type') not in ('finished', 'warp_finished', 'warp_analysis_finished'):
            self.emit(dict(event, workflow_step=node['id'], workflow_task=node.get('task')))

    def _make_child(self, node):
        task = node['task']
        settings, options = self.specs[node['id']]
        options = deepcopy(options)
        if self._initial_foreground_pending and not options.get('workflow_page_background'):
            self._initial_foreground_pending = False
            if task in WORKFLOW_FOREGROUND_TASKS or task in (
                    ACHIEVEMENT_CLAIM_OPERATION, EVENT_CLAIM_OPERATION, TRAINING_SYNTHESIS_TASK):
                options['observation_wait_for_foreground'] = True
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

    def _source(self, result, expected, *, native_points=False):
        if result.get('operation') != expected or result.get('report_saved') is not True:
            raise WorkflowError('任务未返回对应的已保存原始报告，未推进下一项。')
        path = Path(result.get('run_dir', '')) / 'report.json'
        if native_points and (not path.is_absolute() or path.resolve() != path.parent.resolve() / path.name):
            raise WorkflowError('差分积分的原始报告不在本次子任务目录。')
        with path.open('rb') as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024 or json.loads(raw) != json.loads(_bytes(result)):
            raise WorkflowError('原始报告与本次返回结果不一致，未推进下一项。')
        return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())

    def _facts(self, result):
        facts = dict(status=result.get('status', 'failed'))
        operation = result.get('operation')
        if operation in VISION_TASKS:
            field = 'image_found' if operation in TEMPLATE_TASKS else 'text_found'
            observation = result.get('workflow_screen') if operation in GAME_VISION_TASKS else result
            if facts['status'] == 'success' and isinstance(observation, dict) and type(observation.get(field)) is bool:
                facts[field] = observation[field]
            return facts
        if operation == PAGE_TASK:
            navigation = result.get('workflow_navigation')
            if facts['status'] == 'success' and isinstance(navigation, dict) and navigation.get('page_verified') is True:
                facts['page_verified'] = True
            return facts
        if operation == GAME_CAPTURE_TASK:
            capture = result.get('workflow_screen')
            if facts['status'] == 'success' and isinstance(capture, dict) and capture.get('captured') is True:
                facts['captured'] = True
            return facts
        if result.get('operation') == 'du_rewards':
            value = result.get('du_rewards', {}).get('rewards_verified')
            if type(value) is bool:
                facts['du_rewards_verified'] = value
            return facts
        if result.get('operation') == 'differential_universe':
            completed = result.get('differential_universe', {}).get('completed_runs')
            if type(completed) is int:
                facts['completed_runs'] = completed
            return facts
        observed_daily = (result.get('daily_verified') is True or
                          any(row.get('task') == 'daily' for row in result.get('results', []) if isinstance(row, dict)))
        if (operation in ('daily', 'plan', 'reward_only') and observed_daily
                and type(result.get('daily_verified')) is bool):
            facts['daily_verified'] = result['daily_verified']
        currency = result.get('currency_wars', {})
        for name in ('victories', 'defeats', 'points_verified', 'rewards_verified'):
            if type(currency.get(name)) is FIELDS[name]:
                facts[name] = currency[name]
        if result.get('operation') == 'currency_wars_loop' and type(currency.get('completed')) is int:
            facts['completed_runs'] = currency['completed']
        return facts

    def _copy_totals(self, result, *, weekly_only=False):
        # Static reservations admit at most one daily owner. DU post-daily is off.
        if result.get('operation') == 'du_rewards':
            self.report.du_rewards = deepcopy(result['du_rewards'])
            return
        if result.get('operation') == 'reward_only':
            self.report.daily_verified = result['daily_verified']
            self.report.engagement = result['engagement']
            return
        if result.get('operation') in ('daily', 'plan'):
            if 'weekly_plan' in result:
                self.report.weekly_plan = deepcopy(result['weekly_plan'])
        if result.get('operation') in ('daily', 'plan') and not weekly_only:
            for key in ('stamina_spent', 'stamina_limit', 'stamina_pending', 'immersifiers_spent', 'immersifiers_pending',
                        'daily_verified', 'daily_synthesis', 'train_supply', 'engagement', 'battle_completed', 'battle_requested',
                        'game_day', 'power_plan', 'team_selections', 'support_selections'):
                if key in result:
                    setattr(self.report, key, deepcopy(result[key]))
            from .redemption_report import report_summary
            if (summary := report_summary(result)) is not None:
                self.report.workflow['redemption_summary'] = summary
        if result.get('operation') != 'differential_universe' and result.get('currency_wars'):
            # Keep each task separately; a subsequent points query cannot erase victories.
            self.report.workflow.setdefault('currency_results', []).append(deepcopy(result['currency_wars']))
        if result.get('differential_universe'):
            self.report.differential_universe = deepcopy(result['differential_universe'])

    def _du_rewards(self, result, entry, node):
        value = result.get('du_rewards')
        if type(value) is not dict:
            raise WorkflowError('独立差分领奖没有返回原生领奖记录。')
        entry['du_rewards'] = deepcopy(value)
        requested = self.specs[node['id']][1]['du_use_cassettes']
        categories = value.get('requested_categories')
        expected_categories = {'拟合等级', '稳态数组', '可能性画廊'} | ({'月下奇谭'} if requested else set())
        if (type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('operation') != 'du_rewards'
                or value.get('status') not in ('running', 'complete', 'partial', 'unknown', 'stopped', 'abort_before_input')
                or type(value.get('rewards_verified')) is not bool
                or value.get('battle_started') is not False or value.get('use_cassettes') is not requested
                or type(categories) is not list or len(categories) != len(expected_categories)
                or any(type(category) is not str for category in categories)
                or set(categories) != expected_categories):
            raise WorkflowError('独立差分领奖记录与原生范围或明确卡带授权不一致。')
        if result.get('status') == 'success' and (value['status'] != 'complete' or value['rewards_verified'] is not True):
            raise WorkflowError('独立差分领奖尚未核实红点完成，不能按完整成功推进。')

    def _du_points_result(self, result, entry, maximum, identity_mark):
        from .task_workflow_du_points import current_projection, verify_native_receipt

        last = verify_native_receipt(result, entry['source'], maximum)
        try:
            self._identity.require_step(identity_mark)
        finally:
            result, expired = current_projection(result, last)
            # Preserve historical facts even if the account later changed.
            self._copy_totals(result)
        entry['account_verified'] = True
        entry['periodic_points_goal'] = deepcopy(result['differential_universe']['periodic_points_goal'])
        if expired:
            entry['error'] = '接收差分结果时游戏周已切换，原游戏周观察和已核实胜利保留。'
        return result

    def _expire_du_points_week(self):
        if self._du_points_step is None:
            return
        from .task_workflow_du_points import goal_for_current_week

        entry, on_failure, permission = self._du_points_step
        goal = entry['periodic_points_goal']
        message = '游戏周已切换。原周积分观察、已核实胜利和实际步骤结果保留。'
        try:
            current = (dict(goal, status='unverified', reason='game_week_changed') if permission.expired
                       else goal_for_current_week(goal, goal['observations'][-1]))
        except WorkflowError as error:
            current = dict(goal, status='unverified', reason='observation_time_unverified')
            message = str(error)
        if current is goal:
            return
        self._du_points_step = None
        self._has_failure = self._input_blocked = True
        self.report.workflow['input_blocked'] = True
        entry.update(status='partial', periodic_points_goal=current, error=message)
        entry['facts']['status'] = 'partial'
        self._latest[entry['step']]['status'] = 'partial'
        self.report.differential_universe['periodic_points_goal'] = deepcopy(current)
        self._record(dict(event='du_points_revalidation', checked_at=_now(), **entry))
        return entry, on_failure

    def _emit_du_points_expiry(self, entry):
        self.emit(dict(type='workflow_step', step=entry['step'], sequence=entry['sequence'], status='partial'))

    def _check_du_points_week(self):
        change = self._expire_du_points_week()
        if change is None:
            return
        entry, on_failure = change
        self._save()
        self._emit_du_points_expiry(entry)
        if on_failure == 'stop':
            raise _Halt(entry['error'])

    def _capture_attachment(self, reference, entry):
        from .reward_guide_notify import freeze_png

        capture_step = next((item for item in reversed(self.report.workflow['steps'])
                             if item['step'] == reference and item['trail'] == entry['trail']), None)
        if capture_step is None or capture_step['status'] != 'success' or 'capture' not in capture_step:
            raise WorkflowError('当前分支或循环没有已核实的截图回执。')
        capture = capture_step['capture']
        source = freeze_png(Path(capture_step['source']['path']).parent / capture['file'], min_edge=16)
        if source.digest.hex() != capture['sha256']:
            raise WorkflowError('截图文件与本次导出回执不符，未发送通知。')
        entry['attachment'] = dict(step=reference, sequence=capture_step['sequence'], sha256=capture['sha256'])
        return source

    def _local_task(self, node, entry):
        task = node['task']
        sequence = entry['sequence']
        options = deepcopy(self.specs[node['id']][1])
        if task == 'workflow_notify':
            if self._notification_blocked:
                raise WorkflowError('此前主动通知的提交待核对，未发送后续主动通知。')
            from .workflow_notify import send_step

            profile = options['profile']
            attachment = {'attachment': self.notification_image.source} if 'png' in options else {}
            if 'capture_from' in options:
                attachment = {'capture_attachment': self._capture_attachment(options['capture_from'], entry)}
            return send_step(profile, options['message'], directory=self._directory, checkpoint=self.checkpoint,
                             run_key=self._directory.name, sequence=sequence,
                             expected_version=self.notification_versions[profile], service=self.notification_service,
                             **attachment)
        if task == 'workflow_audio':
            from .workflow_audio import play

            result = play(options['path'], checkpoint=self.checkpoint, stopped=self._stop.is_set,
                          paused=lambda: self._paused)
        elif task in VISION_TASKS:
            from .workflow_vision import observe

            result = observe(**options, checkpoint=self.checkpoint)
        else:
            from .warp_service import run

            result = (self.warp_service or run)(**options, cancel=self.checkpoint,
                                               emit=lambda event: self._send(event, node))
        directory = self._directory / f'tool-{sequence}'
        result = dict(result, operation=task, report_saved=True, run_dir=str(directory))
        directory.mkdir()
        _write(directory / 'report.json', result)
        return result

    def _task(self, node, entry, *, enter=None):
        game = node['task'] in GAME_TASKS
        self.checkpoint()
        if game:
            self._check_du_points_week()
            if self._input_blocked:
                raise WorkflowError('此前游戏任务未核实完成；失败后继续只能处理本地步骤，不能再发送游戏输入。')
        scoped_attachment = node['task'] == FREE_ATTACHMENT_TASK
        scoped_assignment = node['task'] == ASSIGNMENT_REWARDS_TASK
        scoped_synthesis = node['task'] == TRAINING_SYNTHESIS_TASK
        scoped_daily = scoped_attachment or scoped_assignment or scoped_synthesis
        weekly_only = node['task'] == 'plan' and node.get('params', {}).get('tasks') == []
        expected = ('reward_only' if node['task'] == TRAINING_REWARDS_TASK
                    else 'daily' if scoped_daily else node['task'])
        child = result = None
        identity_mark = self._identity.mark() if game else None
        followup = self._du_points_step[2] if game and self._du_points_step is not None else None
        try:
            if game:
                with followup_week_scope(followup):
                    child = self._make_child(node)
                    with self._lock:
                        self.child = child
                        if self._stop.is_set():
                            child.stop()
                        if self._paused:
                            child.toggle_pause()
                    if enter is not None:
                        enter()
                    result = child.run()
                self._notice_stopped(result)
                result = result.to_dict() if hasattr(result, 'to_dict') else result
            else:
                if enter is not None:
                    enter()
                result = self._local_task(node, entry)
                self._notice_stopped(result)
            if not isinstance(result, dict) or result.get('status') not in ('success', 'partial', 'failed', 'stopped'):
                raise WorkflowError('任务返回了未知结果。')
            if node['task'] == 'workflow_notify':
                self._notification_blocked |= result['status'] == 'partial'
                if isinstance(result.get('notification'), dict):
                    entry['notification'] = deepcopy(result['notification'])
            options = self.specs[node['id']][1]
            native_points = options.get('du_until_points') is True
            if native_points and not self._identity.has_step_proof(identity_mark, run_dir=result.get('run_dir') or ''):
                raise WorkflowError('差分积分的原始报告未绑定本次子任务的账号观察。')
            if node['task'] in WORKFLOW_FOREGROUND_TASKS and result['status'] == 'success':
                run_dir = result.get('run_dir')
                if not run_dir or not self._identity.has_step_proof(identity_mark, run_dir=run_dir):
                    raise WorkflowError('游戏页面回执未绑定本次子任务的账号观察。')
                if len(self._facts(result)) != 2:
                    raise WorkflowError('游戏页面回执缺少已核实的布尔结果。')
                if node['task'] == PAGE_TASK and result['workflow_navigation'].get('target') != options['workflow_page']:
                    raise WorkflowError('已核实页面与本步骤请求的目标不符。')
                if options.get('workflow_page_background') is True and (
                        result['workflow_navigation'].get('control_mode') != 'background'):
                    raise WorkflowError('页面回执没有核实本次使用后台窗口。')
            entry['source'] = self._source(result, expected, native_points=native_points)
            weekly = result.get('weekly_plan')
            weekly_not_due = (
                weekly_only and result['status'] == 'success' and isinstance(weekly, dict)
                and weekly.get('status') == 'not_due' and weekly.get('daily_handoff') == 'not_selected'
                and weekly.get('daily_tasks') == [] and weekly.get('children') == []
            )
            if scoped_synthesis and result['status'] == 'success':
                from .daily_synthesis_search import synthesis_receipt

                synthesis = synthesis_receipt(result.get('daily_synthesis'))
                if synthesis is None or not self._identity.has_step_proof(identity_mark, run_dir=result.get('run_dir') or ''):
                    raise WorkflowError('独立实训合成缺少同账号的单件材料回执。')
                entry['synthesis'] = synthesis
            if node['task'] == GAME_CAPTURE_TASK and result['status'] == 'success':
                from .workflow_screen import verified_capture

                capture = verified_capture(result, options['workflow_screen_query']['region'])
                if capture is None:
                    raise WorkflowError('游戏截图的本地 PNG 与本次原始回执不符。')
                entry['capture'] = deepcopy(capture)
            if node['task'] == EVENT_CLAIM_OPERATION:
                from .daily_event_claim_flow import claim_receipt

                claim = claim_receipt(result, options['daily_event_claim_day'])
                if result['status'] == 'success' and (claim is None or not self._identity.has_step_proof(
                        identity_mark, run_dir=result.get('run_dir') or '')):
                    raise WorkflowError('巡星之礼缺少同账号指定日卡的已保存领取回执。')
                if claim is not None:
                    entry['daily_event_claim'] = claim
            if node['task'] == ACHIEVEMENT_CLAIM_OPERATION and result['status'] == 'success':
                from .achievement_bulk_claim import claim_receipt

                claim = claim_receipt(result.get('achievement_bulk_claim'))
                if claim is None or not self._identity.has_step_proof(identity_mark, run_dir=result.get('run_dir') or ''):
                    raise WorkflowError('成就领奖缺少同账号的已保存展示及回页回执。')
                entry['achievement_bulk_claim'] = claim
            if node['task'] == REDEMPTION_TASK:
                from .redemption_report import report_summary

                summary = report_summary(result)
                bound = self._identity.has_step_proof(identity_mark, run_dir=result.get('run_dir') or '')
                if result['status'] == 'success' and (not bound or summary['state'] not in ('completed', 'empty')):
                    raise WorkflowError('独立兑换缺少同账号的已保存批次结果。')
                if bound:
                    entry['redemption_summary'] = summary
                    self.report.workflow['redemption_summary'] = summary
            if node['task'] == PAGE_TASK and result['status'] == 'success' and options['workflow_page'] == 'daily_training':
                from .daily_training_observe import training_observation_receipt

                observation = training_observation_receipt(result['workflow_navigation'])
                if observation is not None:
                    entry['training_observation'] = deepcopy(observation)
            if node['task'] == PAGE_TASK and result['status'] == 'success' and options['workflow_page'] == TRAINING_SCAN_PAGE:
                from .daily_training_scan import scan_receipt

                scan = scan_receipt(result['workflow_navigation'])
                if scan is None:
                    raise WorkflowError('实训巡查缺少已保存的卡片回执。')
                entry['training_scan'] = deepcopy(scan)
            if node['task'] == PAGE_TASK and result['status'] == 'success' and options['workflow_page'] == VISA_CHARACTERS_PAGE:
                from .support_gift_observe import gift_receipt

                gift = gift_receipt(result['workflow_navigation'])
                if gift is not None:
                    entry['support_gift_observation'] = gift
            training = None
            if node['task'] == TRAINING_REWARDS_TASK:
                from .daily_training_rewards import reached_milestones_receipt

                training = reached_milestones_receipt(result)
                if training is not None and not self._identity.has_step_proof(
                        identity_mark, run_dir=result.get('run_dir') or ''):
                    raise WorkflowError('实训已达档位缺少本次同账号的原始回执。')
            attachment = None
            if scoped_attachment:
                from .daily_attachments import attachment_receipt

                attachment = attachment_receipt(result, options['daily_attachment_only'])
                if result['status'] == 'success' and (attachment is None or not self._identity.has_step_proof(
                        identity_mark, run_dir=result.get('run_dir') or '')):
                    raise WorkflowError('独立免费领奖缺少本次同账号的原始回执。')
            assignment = None
            if options.get('assignments_only'):
                from .daily_assignment_scope import assignment_receipt

                assignment = assignment_receipt(result)
                if scoped_assignment and result['status'] == 'success' and (assignment is None
                        or not self._identity.has_step_proof(identity_mark, run_dir=result.get('run_dir') or '')):
                    raise WorkflowError('独立持续委托缺少本次同账号的原始回执。')
                if assignment is not None and assignment['outcome'] == 'unknown':
                    entry['assignment'] = assignment
            if entry['type'] == 'screen_condition' and result['status'] == 'success':
                path = entry['source']['path']
                if path in self._screen_sources:
                    raise WorkflowError('实时条件重复使用了原始报告，未取得本次观察。')
                self._screen_sources.add(path)
            if node['task'] == 'du_rewards':
                self._du_rewards(result, entry, node)
            if native_points:
                result = self._du_points_result(result, entry, options['du_runs'], identity_mark)
            else:
                if not scoped_daily and (not game or weekly_not_due or self._identity.has_step_proof(identity_mark)):
                    self._copy_totals(result, weekly_only=weekly_only)
                if game and not weekly_not_due:
                    self._identity.require_step(identity_mark)
                    entry['account_verified'] = True
                if attachment is not None and self._identity.has_step_proof(
                        identity_mark, run_dir=result.get('run_dir') or ''):
                    entry['attachment'] = attachment
                if (assignment is not None and assignment['outcome'] != 'unknown'
                        and self._identity.has_step_proof(identity_mark, run_dir=result.get('run_dir', ''))):
                    entry['assignment'] = assignment
            entry['facts'] = {'status': result['status']} if scoped_daily else self._facts(result)
            if weekly_only:
                entry['facts'].pop('daily_verified', None)
            entry['status'] = result['status']
            training_source = entry.get('training_scan') or entry.get('training_observation')
            if entry['status'] == 'success' and training_source is not None:
                from .daily_training_observe import training_condition_facts

                entry['facts'].update(training_condition_facts(
                    training_source, result['workflow_navigation'].get('client_version')))
            if training is not None:
                entry['training_milestones'] = training
                if node.get('params', {}).get('reached_only') is True:
                    entry.update(status='success', native_status=result['status'])
                    entry['facts']['status'] = entry['status']
            if native_points and result['status'] == 'success':
                week = entry['periodic_points_goal']['observations'][-1]['game_week']
                self._du_points_step = entry, node.get('on_failure', 'stop'), FollowupWeek(week)
        except (Stopped, KeyboardInterrupt):
            self.stop()
            raise Stopped('当前任务已停止；流程未重试或继续下一项。')
        except _ConditionExpired:
            raise
        except Exception as error:
            self._notification_blocked |= node['task'] == 'workflow_notify'
            entry.update(status='partial' if game else 'failed', error=str(error))
            entry['facts'] = {'status': entry['status']}
        finally:
            with self._lock:
                if self.child is not None:
                    child = self.child
                    from .run_control import stop_requested
                    if stop_requested(child):
                        self.stop()
                    hwnd = getattr(child, '_control_hwnd', None)
                    if not isinstance(hwnd, int):
                        hwnd = getattr(getattr(child, '_window', None), 'hwnd', None)
                    if isinstance(hwnd, int):
                        self._control_hwnd = hwnd
                    self.child = None
        if entry['status'] == 'stopped':
            raise Stopped('子任务已停止；未继续后续步骤。')
        if followup is not None:
            self._check_du_points_week()
        if entry['status'] != 'success':
            self._has_failure = True
            self._input_blocked |= game
            if node.get('on_failure', 'stop') == 'stop':
                raise _Halt('步骤未完整完成；按失败策略停止。')
        return child

    def _begin_step(self, node, trail, **details):
        self.checkpoint()
        self._check_du_points_week()
        entries = self.report.workflow['steps']
        if len(entries) >= MAX_EXECUTIONS:
            raise WorkflowError('流程已达到10000次执行上限，未继续。')
        entry = dict(sequence=len(entries) + 1, step=node['id'], type=node['type'], task=node.get('task'),
                     trail=[list(item) for item in trail], status='running', started_at=_now())
        entry.update(details)
        entries.append(entry)
        self._record(dict(event='intent', **entry))
        self._save()
        self.emit(dict(type='workflow_step', step=node['id'], sequence=entry['sequence'], status='running'))
        return entry

    def _finish_step(self, entry):
        entry['finished_at'] = _now()
        self._record(dict(event='result', **entry))
        self._save()
        self.emit(dict(type='workflow_step', step=entry['step'], sequence=entry['sequence'], status=entry['status']))

    def _condition_boundary(self, generation, child):
        def check_generation():
            with self._lock:
                if self._stop.is_set():
                    raise Stopped('任务流程已停止；未进入实时条件分支。')
                if self._pause_generation != generation:
                    raise WorkflowError('暂停或恢复后实时条件已失效，未进入分支或继续循环。')

        try:
            self.checkpoint()
            check_generation()
            guard = getattr(child, 'guard_workflow_condition', None)
            if not callable(guard):
                raise WorkflowError('实时条件缺少本次原生观察的前台核验。')
            guard()
            check_generation()
        except Stopped:
            self.stop()
            raise
        except (AutomationError, WorkflowError, OSError) as error:
            self._input_blocked = True
            detail = str(error) if isinstance(error, WorkflowError) else '实时条件的前台或输入代次已失效，未进入分支或继续循环。'
            raise _ConditionExpired(detail) from None

    def _evaluate_condition(self, node, trail, phase, iteration=None):
        if 'screen_condition' not in node:
            return self._condition(node['condition']), None
        query = node['screen_condition']
        task = execution_task(node)
        details = {'phase': phase} if iteration is None else {'phase': phase, 'iteration': iteration}
        entry = self._begin_step(task, trail, type='screen_condition', **details)
        with self._lock:
            generation = self._pause_generation
        try:
            child = self._task(task, entry)

            def enter():
                self._condition_boundary(generation, child)

            enter()
            field = 'image_found' if task['task'] in TEMPLATE_TASKS else 'text_found'
            entry['condition'] = entry['facts'][field] is query['value']
        except (Stopped, KeyboardInterrupt):
            entry.update(status='stopped', facts={'status': 'stopped'})
            raise
        except Exception as error:
            if entry['status'] in ('running', 'success'):
                entry['status'] = 'partial'
            entry['facts'] = {'status': entry['status']}
            entry.setdefault('error', str(error))
            raise
        finally:
            self._finish_step(entry)
        enter()
        return entry['condition'], enter

    def _steps(self, nodes, trail=(), *, enter=None):
        for node in nodes:
            entry = self._begin_step(node, trail)
            try:
                enabled = node.get('enabled', True)
                guard = enter if enabled else None
                if guard is not None:
                    enter = None
                    if node['type'] != 'task':
                        guard()
                if not enabled:
                    entry['status'] = 'skipped'
                elif node['type'] == 'task':
                    self._task(node, entry, enter=guard)
                elif node['type'] == 'wait':
                    self._wait(node['seconds'])
                elif node['type'] == 'if':
                    entry['condition'], branch = self._evaluate_condition(node, trail, 'branch')
                    self._steps(node['steps'] if entry['condition'] else node.get('else_steps', []), trail, enter=branch)
                elif node['type'] in ('for', 'while'):
                    bound = node.get('count', node.get('max_iterations'))
                    for iteration in range(bound):
                        self.checkpoint()
                        branch = None
                        if node['type'] == 'while':
                            passed, branch = self._evaluate_condition(node, trail, 'iteration', iteration)
                            if not passed:
                                break
                        entry['iterations'] = iteration + 1
                        try:
                            self._steps(node['steps'], trail + ((node['id'], iteration),), enter=branch)
                        except _Control as control:
                            if control.kind == 'break':
                                break
                    else:
                        if node['type'] == 'while' and self._evaluate_condition(node, trail, 'limit', bound)[0]:
                            if 'screen_condition' in node:
                                entry['limit_reached'] = True
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
                facts = dict(entry.get('facts', {}), status=entry['status'])
                training_source = entry.get('training_scan') or entry.get('training_observation')
                if 'training_activity' in facts and training_source is not None:
                    facts['_training_game_day'] = training_source['game_day']
                self._latest[node['id']] = facts
                if node['type'] == 'task' and entry['status'] != 'skipped':
                    self._latest['@last'] = self._latest[node['id']]
                self._finish_step(entry)

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
            if required:
                monitor = threading.Thread(target=self._hotkeys, name='AutoHSR-workflow-hotkeys', daemon=True)
                monitor.start()
            self._steps(self.recipe.steps)
            self.checkpoint()
            self._check_du_points_week()
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


def step_notification_aliases(recipe):
    return tuple(dict.fromkeys(node['params']['profile'] for node in _tasks(recipe.steps)
                               if node['task'] == 'workflow_notify'))


def step_notification_images(recipe):
    return {(str(recipe.base_dir / workflow_notification_png_path(node['params']['png'])), node['params']['profile'])
            for node in _tasks(recipe.steps) if node['task'] == 'workflow_notify' and 'png' in node['params']}


def step_notification_captures(recipe):
    return {node['params']['profile'] for node in _tasks(recipe.steps)
            if node['task'] == 'workflow_notify' and 'capture_from' in node['params']}


@dataclass(frozen=True)
class WorkflowNotificationImage:
    profile: str
    source: PngSource


def freeze_step_notifications(recipe, *, service=None):
    from .workflow_notify import freeze_profile
    from .reward_guide_notify import freeze_capture_profile, freeze_smtp_profile

    checks = {profile: freeze_capture_profile for profile in step_notification_captures(recipe)}
    checks.update({profile: freeze_smtp_profile for _, profile in step_notification_images(recipe)})
    return {identity: checks.get(identity, freeze_profile)(identity, service=service)
            for identity in step_notification_aliases(recipe)}
