"""Explicitly armed, tick-driven scheduling with cooperative owned Runners.

Construction, save and enable never start a timer or a game. A caller explicitly
starts this controller and supplies ticks; only due slots construct its injected
executor's Runner. The executor freezes/revalidates targets and resource policy.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import threading
import time

from .schedule_plan import CHINA, ScheduleError, due_slot, json_copy, local_time, next_due
from .schedule_store import MANIFEST_BYTES, source_reference
from .run_control import stop_requested

_NO_SOURCE = object()
CHILD_TYPES = frozenset(('paused', 'task', 'workflow_step', 'workflow_identity',
                         'plan_phase', 'plan_daily_result', 'du_progress',
                         'currency_loop_phase', 'currency_loop_points', 'currency_loop_progress',
                         'notification_phase', 'notification_result', 'notification_summary'))
CHILD_STATUSES = frozenset(('success', 'partial', 'failed', 'stopped', 'skipped', 'running', 'waiting',
                           'accepted', 'rejected', 'unknown', 'cancelled', 'filtered'))


def _stop_intent(runner=None, report=None):
    if stop_requested(runner=runner, report=report):
        return True
    # Retain the formal report-verifier's earlier typed hint; unlike this
    # compatibility property, the shared helper has one stop_requested protocol.
    try:
        return getattr(runner, 'schedule_stopped', False) is True
    except Exception:
        return False


class _Cancelled(Exception):
    pass


@dataclass
class _Job:
    plan: dict
    revision: str
    manifest: dict
    slot: datetime
    claim: object
    cancel: threading.Event = field(default_factory=threading.Event)
    controls: threading.RLock = field(default_factory=threading.RLock)
    runner: object = None
    runner_paused: bool = False
    deadline: float | None = None
    reason: str = ''
    index: int = -1
    completed: int = 0
    thread: object = None


class Scheduler:
    """Executor: freeze(plan), revalidate(manifest), create(target, manifest, emit), busy().

    Fresh created Runners start unpaused and implement run/stop/toggle_pause.
    toggle_pause returns the resulting bool and paused events report actual state.
    Repeat creates a fresh Runner per attempt; the dispatcher must reject game
    repeats that would reserve more than the whole slot's explicit allowance.
    """
    def __init__(self, store, executor, *, clock=None, emit=None, monotonic=None):
        self.store, self.executor = store, executor
        self.clock = clock or (lambda: datetime.now(CHINA))
        self.emit = emit or (lambda event: None)
        self.monotonic = monotonic or time.monotonic
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._tick_lock = threading.Lock()
        self._enabled = {}
        self._seen = set()
        self._active = self._pending = None
        self._running = self._paused = False
        self._last = None

    def _emit(self, event):
        try:
            self.emit(event)
        except Exception:
            pass  # A UI observer cannot turn a game result into another run.

    def _event(self, kind, job=None, **values):
        data = dict(type='schedule_' + kind, **values)
        if job is not None:
            data.update(id=job.plan['id'], revision=job.revision, slot=job.slot.isoformat())
        self._emit(data)

    def enable(self, plan_id):
        plan, digest = self.store.load(plan_id)
        manifest = self.executor.freeze(deepcopy(plan))
        if not isinstance(manifest, dict):
            raise ScheduleError('计划执行器未返回有效冻结清单。')
        manifest = json_copy(manifest, maximum=MANIFEST_BYTES)
        now = local_time(self.clock()).replace(second=0, microsecond=0)
        with self._lock:
            self._enabled[plan_id] = dict(plan=plan, revision=digest, manifest=manifest, armed_at=now)
        self._event('enabled', id=plan_id, revision=digest, running=self._running)
        return self.snapshot()

    def disable(self, plan_id):
        with self._lock:
            self._enabled.pop(plan_id, None)
            pending = self._pending if self._pending is not None and self._pending.plan['id'] == plan_id else None
            if pending is not None:
                self._pending = None
        if pending is not None:
            self._finish(pending, 'stopped', 'disabled_before_start')
        self._event('disabled', id=plan_id)
        return self.snapshot()

    def start(self):
        now = local_time(self.clock()).replace(second=0, microsecond=0)
        with self._lock:
            if self._running:
                return self.snapshot()
            if self._active is not None:
                raise ScheduleError('原计划执行尚未退出；未重新启动计时。')
            for entry in self._enabled.values():
                entry['armed_at'] = now
            self._running, self._paused = True, False
        self._event('started', startup_minute='skip', missed_policy='skip')
        return self.snapshot()

    def _set_runner_pause(self, job, desired):
        with job.controls:
            runner = job.runner
            if runner is None or job.runner_paused == desired:
                return
            try:
                actual = runner.toggle_pause()
                if type(actual) is not bool or actual != desired:
                    raise ScheduleError('计划子任务暂停状态未核实。')
                job.runner_paused = actual
            except Exception:
                self._cancel(job, 'pause_unverified')

    def pause(self):
        with self._condition:
            self._paused = True
            active = self._active
            self._condition.notify_all()
        if active is not None:
            self._set_runner_pause(active, True)
        self._event('paused', paused=True)
        return self.snapshot()

    def resume(self):
        with self._condition:
            self._paused = False
            active = self._active
            self._condition.notify_all()
        if active is not None:
            self._set_runner_pause(active, False)
        self._launch_pending()
        self._event('paused', paused=False)
        return self.snapshot()

    def _cancel(self, job, reason):
        with self._condition:
            if not job.reason:
                job.reason = reason
            job.cancel.set()
            self._condition.notify_all()
        with job.controls:
            if job.runner is not None:
                try:
                    job.runner.stop()
                except Exception:
                    job.reason = 'stop_unverified'

    def stop(self, *, wait=False, timeout=None):
        with self._condition:
            self._running, self._paused = False, False
            active, pending = self._active, self._pending
            self._pending = None
            self._condition.notify_all()
        if pending is not None:
            self._finish(pending, 'stopped', 'controller_stopped')
        if active is not None:
            self._cancel(active, 'controller_stopped')
        self._event('stopped', waiting_for_owned_runner=active is not None)
        if wait:
            self.wait_idle(timeout)
        return self.snapshot()

    def wait_idle(self, timeout=None):
        """Wait for owned work to exit; never pretend stop() means it exited."""
        with self._condition:
            return self._condition.wait_for(lambda: self._active is None and self._pending is None, timeout)

    def snapshot(self):
        now = local_time(self.clock())
        with self._lock:
            plans = [dict(id=entry['plan']['id'], name=entry['plan']['name'], revision=entry['revision'],
                          next_due=next_due(entry['plan'], now).isoformat(), enabled=True)
                     for _, entry in sorted(self._enabled.items())]
            active, pending = self._active, self._pending
            def public(job):
                return None if job is None else dict(id=job.plan['id'], revision=job.revision,
                    slot=job.slot.isoformat(), index=job.index, completed=job.completed,
                    requested=job.plan['repeat']['count'], stopping=job.cancel.is_set())
            stopping = active is not None and active.cancel.is_set()
            state = 'stopping' if stopping else 'paused' if self._paused else 'running' if self._running else 'stopped'
            return dict(running=self._running, started=self._running, stopping=stopping, state=state,
                        paused=self._paused, plans=plans, enabled_ids=[row['id'] for row in plans],
                        next_times={row['id']: row['next_due'] for row in plans}, active=public(active),
                        runner_active=active is not None and active.runner is not None,
                        pending=public(pending), last=deepcopy(self._last),
                        timezone='Asia/Shanghai', missed_policy='skip', system_tasks_registered=False)

    def tick(self, now=None):
        """Inspect only this minute; caller polling also enforces wall timeouts."""
        if not self._tick_lock.acquire(blocking=False):
            return self.snapshot()
        try:
            now = local_time(now if now is not None else self.clock())
            with self._lock:
                active = self._active
                expired = active is not None and active.deadline is not None and self.monotonic() >= active.deadline
                running, paused = self._running, self._paused
                entries = list(sorted(self._enabled.items()))
            if active is not None and not active.cancel.is_set():
                with active.controls:
                    owned_runner = active.runner
                if stop_requested(runner=owned_runner):
                    with self._lock:
                        still_owned = self._active is active and not active.cancel.is_set()
                    if still_owned:
                        self.stop()
                        return self.snapshot()
            if expired:
                self._cancel(active, 'timeout')
            if not running or paused:
                return self.snapshot()
            for plan_id, entry in entries:
                with self._lock:
                    if not self._running or self._paused:
                        break
                slot = due_slot(entry['plan'], now)
                if slot is None or slot <= entry['armed_at']:
                    continue
                marker = (plan_id, entry['revision'], slot.isoformat())
                with self._lock:
                    if marker in self._seen:
                        continue
                    self._seen.add(marker)
                try:
                    _, current = self.store.load(plan_id)
                    if current != entry['revision']:
                        self.disable(plan_id)
                        self._event('skipped', id=plan_id, reason='plan_changed')
                        continue
                    claim, receipt = self.store.claim(entry['plan'], entry['revision'], slot, entry['manifest'])
                    if claim is None:
                        self._event('reused', id=plan_id, revision=entry['revision'], slot=slot.isoformat(),
                                    status='unknown' if receipt['status'] in ('claimed', 'running') else receipt['status'])
                        continue
                    job = _Job(deepcopy(entry['plan']), entry['revision'], deepcopy(entry['manifest']), slot, claim)
                    self._event('claimed', job, requested=job.plan['repeat']['count'])
                    self._admit(job)
                except Exception:
                    self._event('skipped', id=plan_id, reason='slot_unverified', status='unknown')
            return self.snapshot()
        finally:
            self._tick_lock.release()

    def _admit(self, job):
        with self._lock:
            active, pending = self._active, self._pending
            available = self._running and not self._paused
            if active is not None and job.plan['conflict'] == 'stop_owned' and pending is None and available:
                self._pending = job
                queue = True
            else:
                queue = False
        if queue:
            self._event('waiting', job, reason='stopping_owned_runner')
            self._cancel(active, 'replaced_by_schedule')
            return
        if not available:
            self._finish(job, 'skipped', 'controller_unavailable')
        elif active is not None or pending is not None:
            self._finish(job, 'skipped', 'owned_runner_busy')
        else:
            self._launch(job)

    def _launch(self, job, *, from_pending=False):
        with self._lock:
            if from_pending:
                if (self._pending is not job or self._active is not None or
                        not self._running or self._paused):
                    return
                self._pending = None
                reject = False
            else:
                reject = (self._active is not None or self._pending is not None or
                          not self._running or self._paused)
            if not reject:
                self._active = job  # Reserve before arbitrary injected preflight work.
        if reject:
            self._finish(job, 'skipped', 'controller_unavailable')
            return
        try:
            busy = self.executor.busy()
            if type(busy) is not bool:
                raise ScheduleError('外部执行权状态未核实。')
        except Exception:
            self._finish(job, 'unknown', 'conflict_unverified')
            self._release(job)
            return
        if busy:
            self._finish(job, 'skipped', 'external_runner_busy')
            self._release(job)
            return
        with self._lock:
            job.thread = threading.Thread(target=self._work, args=(job,),
                                          name='AutoHSR-schedule-' + job.plan['id'], daemon=False)
        try:
            job.thread.start()
        except Exception:
            self._finish(job, 'unknown', 'worker_start_failed')
            self._release(job)

    def _launch_pending(self):
        with self._lock:
            if not self._running or self._paused or self._active is not None or self._pending is None:
                return
            pending = self._pending
        self._launch(pending, from_pending=True)

    def _release(self, job):
        with self._condition:
            if self._active is job:
                self._active = None
            self._condition.notify_all()
        self._launch_pending()

    def _checkpoint(self, job):
        with self._condition:
            while True:
                if job.cancel.is_set() or not self._running:
                    raise _Cancelled()
                if not self._paused:
                    return
                self._condition.wait(.05)

    def _delay(self, job, seconds):
        remaining = float(seconds)
        while remaining > 0:
            self._checkpoint(job)
            before = self.monotonic()
            with self._condition:
                self._condition.wait(min(.05, remaining))
            remaining -= max(0, self.monotonic() - before)
        self._checkpoint(job)

    def _child_event(self, job, event):
        if not isinstance(event, dict):
            return
        if event.get('type') == 'paused' and type(event.get('paused')) is bool:
            with job.controls:
                job.runner_paused = event['paused']
            with self._condition:
                if self._active is job:
                    self._paused = event['paused']
                    self._condition.notify_all()
        child_type = event.get('type')
        if isinstance(child_type, str) and child_type in CHILD_TYPES:
            # Raw logs, identity observations, paths and reports stay with the
            # native Runner; public scheduling events use only safe state.
            safe = dict(child_type=child_type)
            if type(event.get('paused')) is bool:
                safe['paused'] = event['paused']
            if isinstance(event.get('status'), str) and event['status'] in CHILD_STATUSES:
                safe['status'] = event['status']
            if event.get('game_status') in ('success', 'partial', 'failed', 'stopped'):
                safe['game_status'] = event['game_status']
            for key in ('completed_runs', 'battle_completed', 'current', 'requested',
                        'profiles', 'requested_profiles', 'accepted'):
                if type(event.get(key)) is int and 0 <= event[key] <= 1000000:
                    safe[key] = event[key]
            self._event('child', job, **safe)

    @staticmethod
    def _result(report, source=_NO_SOURCE):
        report = report.to_dict() if hasattr(report, 'to_dict') else report
        if not isinstance(report, dict) or report.get('status') not in ('success', 'partial', 'failed', 'stopped'):
            raise ScheduleError('计划子任务返回了未知结果。')
        result = {name: deepcopy(report[name]) for name in
                  ('status', 'operation', 'report_saved', 'run_dir', 'started_at', 'finished_at') if name in report}
        if source is not _NO_SOURCE:
            source = source_reference(source)
            if source['operation'] != report.get('operation'):
                raise ScheduleError('计划原报告类型与返回结果不符。')
            result['source'] = source
        if report.get('report_saved') is not True:
            result.update(game_status=report['status'], status='unknown', reason='report_unverified')
        return json_copy(result)

    def _work(self, job):
        status, reason, pending_attempt = 'unknown', 'execution_unverified', False
        stop_observed = False
        try:
            for index in range(job.plan['repeat']['count']):
                stop_observed = False
                self._checkpoint(job)
                if index:
                    self._delay(job, job.plan['repeat']['interval_seconds'])
                _, current = self.store.load(job.plan['id'])
                if current != job.revision:
                    status, reason = 'failed', 'plan_changed'
                    break
                self.store.begin_attempt(job.claim, index)
                job.index, pending_attempt = index, True
                self._checkpoint(job)
                try:
                    checked = self.executor.revalidate(deepcopy(job.manifest))
                    if checked is not None and checked is not True:
                        raise ScheduleError('计划目标版本未核实。')
                except Exception:
                    status, reason = 'failed', 'target_unverified'
                    self.store.record_result(job.claim, index, dict(status=status, reason=reason))
                    pending_attempt = False
                    break
                self._checkpoint(job)
                runner = self.executor.create(deepcopy(job.plan['target']), deepcopy(job.manifest),
                                              lambda event: self._child_event(job, event))
                if any(not callable(getattr(runner, name, None)) for name in ('run', 'stop', 'toggle_pause')):
                    raise ScheduleError('计划执行器未返回可控制的原生运行入口。')
                with job.controls:
                    job.runner, job.runner_paused = runner, False
                with self._lock:
                    paused = self._paused
                self._set_runner_pause(job, paused)
                self._checkpoint(job)
                timeout = job.plan['timeout_seconds']
                job.deadline = self.monotonic() + timeout if timeout else None
                self._event('running', job, index=index, requested=job.plan['repeat']['count'])
                report = runner.run()
                # Stop intent must survive source validation and receipt-write
                # failures. Observe it before discarding the runner reference;
                # it controls future work, not the verification of this result.
                stop_observed = _stop_intent(runner=runner, report=report)
                if stop_observed and not job.cancel.is_set():
                    self.stop()
                with job.controls:
                    job.runner = None
                job.deadline = None
                summary = self._result(report, getattr(runner, 'schedule_source', _NO_SOURCE))
                self.store.record_result(job.claim, index, summary)
                pending_attempt = False
                status, reason = summary['status'], summary.get('reason', '')
                if status == 'success':
                    job.completed += 1
                self._event('result', job, index=index, status=status, completed=job.completed,
                            requested=job.plan['repeat']['count'])
                if (status == 'stopped' or summary.get('game_status') == 'stopped') and not job.cancel.is_set():
                    # A child's native F10 listener can consume a short press
                    # before any outer listener observes it. Treat its stopped
                    # report as a controller stop, not permission for tomorrow.
                    self.stop()
                if job.cancel.is_set():
                    if status != 'unknown':
                        if status == 'success' and job.completed < job.plan['repeat']['count']:
                            status = 'partial'
                        reason = job.reason or 'controller_stopped'
                    break
                if status != 'success':
                    break
        except _Cancelled:
            status, reason = ('partial' if job.completed else 'stopped'), job.reason or 'controller_stopped'
            if pending_attempt:
                try:
                    self.store.record_result(job.claim, job.index, dict(status='stopped', reason='cancelled_before_run'))
                except Exception:
                    status, reason = 'unknown', 'receipt_write_failed'
        except Exception:
            status, reason = 'unknown', 'execution_unverified'
            # The formal adapter may observe a native F10 stop and then reject
            # its missing/corrupt report. That stop hint controls future work;
            # it never turns this unverified slot into a verified stopped one.
            with job.controls:
                child_stopped = _stop_intent(runner=job.runner)
            if (stop_observed or child_stopped) and not job.cancel.is_set():
                self.stop()
        finally:
            if job.reason == 'stop_unverified':
                status, reason = 'unknown', 'stop_unverified'
            with job.controls:
                runner, job.runner = job.runner, None
            if runner is not None:
                try:
                    runner.stop()
                except Exception:
                    status, reason = 'unknown', 'stop_unverified'
            self._finish(job, status, reason)
            self._release(job)

    def _finish(self, job, status, reason):
        try:
            self.store.finish(job.claim, status, reason)
        except Exception:
            status, reason = 'unknown', 'receipt_write_failed'
        outcome = dict(id=job.plan['id'], revision=job.revision, slot=job.slot.isoformat(),
                       status=status, reason=reason, completed=job.completed,
                       requested=job.plan['repeat']['count'])
        with self._lock:
            self._last = outcome
        self._event('finished', job, status=status, reason=reason, completed=job.completed,
                    requested=job.plan['repeat']['count'])
