"""Finite or until-stopped composition of existing, separately reported Runners.

Inspired by March7thAssistant run_sub_task/currencywars (pinned 7cf6c6b).
Only verified victories may advance; native unknown/failure is never a restart.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import threading
import uuid

from .config import ROOT
from .currency_wars_loop_store import LoopStore, _write, loop_lock, runs_value
from . import currency_wars_points_goal as points_goal
from .currency_wars_session import StandardSession
from .models import AutomationError, RunReport, Stopped, TaskResult


class CurrencyLoopRunner:
    def __init__(self, settings, emit=None, *, runs=None, resume=False, currency_strategy=None,
                 currency_remembrance_name=None, currency_fast_mode=None, until_points=None, runner_factory=None, root=None):
        from .app import Runner
        from .currency_wars_names import resolve_name, validate_name
        from .currency_wars_equipment_mode import resolve_fast_mode
        from .currency_wars_standard_policy import STRATEGIES
        if type(resume) is not bool:
            raise ValueError('循环接续开关必须为布尔值。')
        if until_points is not None and type(until_points) is not bool:
            raise ValueError('周积分循环开关必须为布尔值。')
        if currency_strategy is not None and currency_strategy not in STRATEGIES:
            raise ValueError('货币战争策略须为 default、aglaea 或 seele。')
        self.settings = replace(settings)
        self.settings.validate('currency_wars')
        self.overrides = dict(runs=runs, strategy=currency_strategy,
                              remembrance_name=None if currency_remembrance_name is None else validate_name(currency_remembrance_name),
                              equipment_fast_mode=currency_fast_mode, until_points=until_points)
        self.options = dict(runs=runs_value(settings.currency_runs if runs is None else runs),
                            strategy=currency_strategy or 'default',
                            remembrance_name=resolve_name(settings, currency_remembrance_name),
                            equipment_fast_mode=resolve_fast_mode(settings, currency_fast_mode),
                            until_points=settings.currency_until_points if until_points is None else until_points)
        self.resume = resume
        self.root = Path(root) if root is not None else ROOT/'runs'
        self.factory = runner_factory or Runner
        self.emit = emit or (lambda event: None)
        self.report = RunReport(operation='currency_wars_loop')
        self.child = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._paused = False
        self._monitor_end = threading.Event()
        self._control_hwnd = None

    def _gap_controls(self):
        """The child owns F9 while running; F10 also covers archival gaps."""
        from .windows import user32
        previous = {key: bool(user32.GetAsyncKeyState(key) & 0x8000) for key in (0x78,0x79)}
        if previous[0x79]:
            self.stop()
        while not self._monitor_end.wait(.05):
            for key in (0x78,0x79):
                # Reading GetAsyncKeyState clears its short-press history.
                # Leave F9 entirely to the live child; F10 is handled by
                # either reader so a short emergency press cannot be lost.
                with self._lock:
                    if key == 0x78 and self.child is not None:
                        previous[key] = True
                        continue
                    pressed = bool(user32.GetAsyncKeyState(key) & 0x8001)
                    if key == 0x79 and pressed:
                        self.stop()
                    elif pressed and not previous[key]:
                        if (self.child is None and self._control_hwnd is not None
                                and user32.GetForegroundWindow() == self._control_hwnd):
                            paused = self.toggle_pause()
                            self.emit(dict(type='paused', paused=paused))
                    previous[key] = pressed

    def stop(self):
        self._stop.set()
        with self._lock:
            if self.child is not None:
                self.child.stop()

    def toggle_pause(self):
        with self._lock:
            self._paused = self.child.toggle_pause() if self.child is not None else not self._paused
            return self._paused

    def _checkpoint(self):
        while True:
            if self._stop.is_set():
                raise Stopped('货币战争循环已停止；没有继续下一局。')
            with self._lock:
                if not self._paused:
                    return
            self._stop.wait(.1)

    def _send(self, event):
        if event.get('type') == 'paused':
            with self._lock:
                self._paused = bool(event.get('paused'))
        if event.get('type') != 'finished':
            self.emit(dict(event, loop_slot=self.report.currency_wars['completed']+1))

    def _summary(self, store):
        data = store.data
        if data is None:
            return
        children = {key: self.report.currency_wars[key] for key in ('last_child','last_points_child')
                    if key in self.report.currency_wars}
        self.report.currency_wars = dict(mode='standard_loop', loop_id=data['loop_id'],
            requested_runs=data['options']['runs'], completed=data['completed'], status=data['status'],
            active=deepcopy(data['active']), loop_record=str(store.path), development_only=True,
            acceptance_runs=0, **children, **{k: v for k, v in data['options'].items() if k != 'runs'})
        if points_goal.enabled(data):
            self.report.currency_wars.update(points_goal=deepcopy(data['points_goal']), rewards_verified=False)

    def _run_child(self, guard, resume):
        self._checkpoint()
        options = guard.store.data['options']
        child = self.factory(self.settings, self._send, operation='currency_wars_standard', currency_resume=resume,
                             currency_strategy=options['strategy'], currency_remembrance_name=options['remembrance_name'],
                             currency_fast_mode=options['equipment_fast_mode'], currency_loop_guard=guard)
        return self._run_bound_child(child)

    def _run_points(self):
        self._checkpoint()
        self.emit(dict(type='currency_loop_points', message='核对本周积分与倒计时；奖励不自动领取。'))
        child = self.factory(self.settings, self._send, operation='currency_wars_points')
        return self._run_bound_child(child)

    def _run_bound_child(self, child):
        with self._lock:
            self.child = child
            if self._stop.is_set():
                child.stop()
            if self._paused:
                child.toggle_pause()
        try:
            result = child.run()
            return result.to_dict() if hasattr(result, 'to_dict') else result
        finally:
            with self._lock:
                hwnd = getattr(getattr(child, '_window', None), 'hwnd', None)
                if isinstance(hwnd, int):
                    self._control_hwnd = hwnd
                self.child = None

    def _execute(self, store):
        self._checkpoint()
        if self.resume:
            if store.load() is None or store.data['status'] != 'active':
                raise AutomationError('没有可接续的未结束货币战争循环。')
            for key, value in self.overrides.items():
                saved = store.data['options'].get(key, False) if key == 'until_points' else store.data['options'][key]
                if value is not None and value != saved:
                    raise AutomationError('显式设置与循环冻结设置不同，未中途改写目标。')
        else:
            # A pre-existing match can never be silently adopted into a new loop.
            session = StandardSession(store.journal).data
            if session is not None and (session['status'] != 'settled' or session.get('loop_owner') is not None):
                raise AutomationError('已有未核对或其他循环所属对局；未创建新循环。')
            store.begin(self.options)
        store.check_tail()
        if store.data.get('archive_intent') is not None:
            store.archive(count=store.data['archive_intent']['count'])
        elif store.data.get('empty_archive_intent') is not None:
            store.archive_unstarted()
        elif store.data['active'] is None and store.journal.exists():
            store.archive(count=False, recover=self.resume)
        self._summary(store)
        while True:
            self._checkpoint()
            data = store.data
            until_points = points_goal.enabled(data)
            if not until_points and data['options']['runs'] and data['completed'] >= data['options']['runs']:
                data['status'] = 'complete'
                store.save()
                self.report.status = 'success'
                return
            store.check_tail()
            session = StandardSession(store.journal).data
            if session is not None and session['status'] == 'settled':
                # A stopped parent or manual native continuation can already
                # have finished this exact owned match. Archive read-only once.
                store.archive(recover=self.resume)
                self._summary(store)
                continue
            # Never navigate away from an owned match already submitted. Empty
            # reservations have no standard input and are preserved separately
            # before fresh points navigation, including explicit crash resume.
            submitted = session is not None and (session['status'] != 'start_pending' or bool(session['actions']))
            if until_points and not submitted:
                if data['active'] is not None:
                    store.archive_unstarted()
                if points_goal.expired(store):
                    self._finish_goal(store, 'expired', '周积分目标已跨游戏周；已保留旧目标，未开始新局。')
                    return
                self._summary(store)
                child = self._run_points()
                self.report.currency_wars['last_points_child'] = dict(run_dir=child.get('run_dir',''), status=child.get('status'))
                if child.get('status') != 'success' or child.get('report_saved') is not True:
                    self.report.status = 'stopped' if child.get('status') == 'stopped' else 'partial'
                    self.report.error = child.get('error','')
                    self.report.safe_next = '积分核对或报告保存未完成；未开新局，可明确接续原循环重新核对。'
                    return
                points_goal.record(store, child)
                current = points_goal.observation(store)
                self._summary(store)
                if points_goal.expired(store) or current['game_week'] != data['points_goal']['week']:
                    self._finish_goal(store, 'expired', '积分观察已进入另一游戏周；原目标不自动迁移。')
                    return
                if current['period']['verified'] is not True:
                    self.report.status = 'partial'
                    self.report.safe_next = '积分已留档，但游戏周倒计时未核实；未开始新局，明确接续后重新核对。'
                    return
                if current['weekly_target_verified'] is True:
                    self._finish_goal(store, 'complete', '本周积分已核实达标；积分奖励领取未核实。')
                    return
                if data['options']['runs'] and data['completed'] >= data['options']['runs']:
                    self._finish_goal(store, 'exhausted', '已达到本循环局数上限，积分仍未满；没有追加新局。')
                    return
                self._checkpoint()
                points_goal.require_start(store)
                session = StandardSession(store.journal).data
            guard = store.reserve()
            resume = session is not None and session['status'] == 'active'
            guard.require_access(session, resume)
            self._summary(store)
            self.emit(dict(type='currency_loop_phase', slot=data['completed']+1, resume=resume,
                           requested_runs=data['options']['runs']))
            child = self._run_child(guard, resume)
            self.report.currency_wars['last_child'] = dict(run_dir=child.get('run_dir', ''), status=child.get('status'))
            if child.get('status') != 'success' or child.get('report_saved') is not True:
                self.report.status = 'stopped' if child.get('status') == 'stopped' else 'partial'
                self.report.error = child.get('error', '')
                self.report.safe_next = '本局未完整结束或报告未保存；核对原报告，明确接续本循环，未知动作不重放。'
                return
            # A stop during the last feedback may still preserve/count the
            # verified completed match, but cannot allow the next start.
            store.archive()
            self._summary(store)
            self.emit(dict(type='currency_loop_progress', data=deepcopy(self.report.currency_wars)))

    def _finish_goal(self, store, status, message):
        store.data['status'] = status
        store.save()
        self.report.status = 'success' if status == 'complete' else 'partial'
        self.report.safe_next = message

    def run(self):
        started = datetime.now().astimezone()
        directory = self.root/(started.strftime('%Y%m%d_%H%M%S_%f')+'_currency_loop_'+uuid.uuid4().hex[:8])
        directory.mkdir(parents=True)
        report = self.report
        report.run_dir, report.started_at, report.source = str(directory), started.isoformat(), str(self.root.parent)
        store = LoopStore(self.root)
        monitor = None
        try:
            with loop_lock(self.root):
                monitor = threading.Thread(target=self._gap_controls, name='AutoHSR-currency-loop-hotkeys', daemon=True)
                monitor.start()
                try:
                    self._execute(store)
                finally:
                    self._monitor_end.set()
                    monitor.join(timeout=1)
        except Stopped as error:
            report.status, report.error = 'stopped', str(error)
        except Exception as error:
            report.status, report.error = 'partial' if store.data and store.data['completed'] else 'failed', str(error)
        finally:
            self._summary(store)
            report.safe_next = report.safe_next or '核对逐局记录；循环为开发运行，不计作独立验收，不自动领取周积分或开启饰品任务。'
            report.finished_at = datetime.now().astimezone().isoformat()
            report.results.append(TaskResult('currency_wars_loop', report.status,
                                             str(report.currency_wars.get('completed', 0))+'局结算已核实并留档。'))
            try:
                report.report_saved = True
                _write(directory/'report.json', report.to_dict())
            except (OSError, ValueError) as error:
                report.report_saved, report.report_write_error, report.status = False, str(error), 'partial'
            self.emit(dict(type='finished', report=report.to_dict()))
        return report
