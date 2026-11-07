"""One explicit start, sequential ordinary Runners, one durable combined report."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import uuid

from .config import ROOT, SettingsError
from .models import AutomationError, RunReport, Stopped, TaskResult
from .run_control import stop_requested
from .storage import replace_file
from .weekly_plan import CHINA, WeeklyGuard, weekly_slot


def _daily_tasks(settings):
    return [task for task, field in (('assignments','assignments'), ('battle','battle'), ('daily','daily'),
        ('redemption','redemption_enabled'), ('mail','mail'), ('battlepass','battlepass')) if getattr(settings, field)]


class PlanRunner:
    def __init__(self, settings, emit=None, *, new_battle_run=False, runner_factory=None, root=None, now=None, resume_weekly_currency=False,
                 use_power_plan=False,new_power_plan=False,du_until_points=False,du_claim_weekly_rewards=False):
        from .app import Runner
        if (type(use_power_plan) is not bool or type(new_power_plan) is not bool or new_power_plan and not use_power_plan
                or use_power_plan and (resume_weekly_currency or not settings.battle)):
            raise ValueError('体力计划需要本次日常刷本任务，不能混入只接续原周常。')
        self.use_power_plan=use_power_plan;self.new_power_plan=new_power_plan
        if use_power_plan:settings.validate('power_plan')
        if (type(resume_weekly_currency) is not bool or resume_weekly_currency and
                (not settings.weekly_enabled or settings.weekly_mode!='currency_wars' or new_battle_run)):
            raise ValueError('接续货币战争周常须选择该周常，且不新增日常预算。')
        if (type(du_until_points) is not bool or du_until_points and
                (not settings.weekly_enabled or settings.weekly_mode != 'differential_universe')):
            raise ValueError('周期积分目标需要已启用的差分周常。')
        if type(du_claim_weekly_rewards) is not bool or du_claim_weekly_rewards and not du_until_points:
            raise ValueError('差分周常领奖需要明确开启本次周期积分目标。')
        self.du_until_points = du_until_points
        self.du_claim_weekly_rewards = du_claim_weekly_rewards
        self.settings = replace(settings)
        if resume_weekly_currency:
            self.settings=replace(self.settings,assignments=False,battle=False,daily=False,mail=False,battlepass=False,
                                  redemption_enabled=False)
        self.settings.validate("power_plan" if use_power_plan else "plan")
        if not self.settings.weekly_enabled and not _daily_tasks(self.settings):
            raise ValueError("请选择日常任务或加入周常。")
        self.emit = emit or (lambda event: None)
        self.factory = runner_factory or Runner
        self._native_factory = runner_factory is None
        self.root = Path(root) if root is not None else ROOT/"runs"
        self.slot = weekly_slot(self.settings, now)
        self.new_battle_run = new_battle_run
        self.resume_weekly_currency=resume_weekly_currency
        self.child = None
        self._control_hwnd = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._paused = False
        self.report = RunReport(operation="plan")

    @property
    def stop_requested(self) -> bool:
        if self._stop.is_set():
            return True
        with self._lock:
            child = self.child
        return child is not self and stop_requested(child)

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
                raise Stopped("计划已停止；未继续下一项。")
            with self._lock:
                paused = self._paused
            if not paused:
                return
            self._stop.wait(.1)

    def _send(self, event, phase):
        if event.get("type") == "paused":
            with self._lock:
                self._paused = bool(event.get("paused"))
        if event.get("type") != "finished":
            self.emit(dict(event, phase=phase))

    def _run(self, settings, *, phase, factory=None, before_child=None, **options):
        self._checkpoint()
        if before_child is not None:
            before_child()
        self.emit(dict(type="plan_phase", phase=phase))
        self._checkpoint()
        if before_child is not None:
            before_child()
        child = (factory or self.factory)(settings, lambda event: self._send(event, phase), **options)
        with self._lock:
            self.child = child
            if self._stop.is_set():
                child.stop()
            if self._paused:
                child.toggle_pause()
        result = None
        try:
            result = child.run()
            with self._lock:
                if self.child is child and stop_requested(child, result) and not self._stop.is_set():
                    self.stop()
            return result.to_dict() if hasattr(result, "to_dict") else result
        finally:
            with self._lock:
                if self.child is child:
                    if stop_requested(child, result) and not self._stop.is_set():
                        self.stop()
                    if hasattr(self,'_control_hwnd'):
                        hwnd=getattr(child,'_control_hwnd',None)
                        if not isinstance(hwnd,int):hwnd=getattr(getattr(child,'_window',None),'hwnd',None)
                        if isinstance(hwnd,int):self._control_hwnd=hwnd
                    self.child = None

    def _weekly_result(self, status, message):
        self.report.weekly_plan.update(status=status, message=message)
        result = TaskResult("weekly", "ok" if status in ("complete", "already_complete") else
                            "skipped" if status in ("disabled", "not_due") else "partial", message)
        self.report.results.append(result)
        self.emit(dict(type="task", **result.__dict__))

    def _copy_daily(self,daily,*,reused=False):
        report=self.report
        info = report.weekly_plan
        info['children'].append(dict(operation='daily',run_dir=daily.get('run_dir',''),reused=reused))
        info.update(daily_status=daily.get('status', 'unknown'),
                    daily_report_saved=daily.get('report_saved') is True)
        if daily.get('report_write_error'):
            info['daily_report_write_error'] = daily['report_write_error']
        for name in ('stamina_spent','stamina_limit','stamina_pending','immersifiers_spent','immersifiers_pending',
                     'battle_completed','battle_requested','daily_verified','daily_synthesis','redemption','engagement','game_day',
                     'error','input_error_field','safe_next','failure_task','support_selections'):
            if name in daily:setattr(report,name,deepcopy(daily[name]))
        if 'power_plan' in daily:report.power_plan=deepcopy(daily['power_plan'])
        report.results.extend(TaskResult(r['task'],r['status'],r.get('detail','')) for r in daily.get('results',[]))
        if reused:
            info.update(daily_reused=True, daily_handoff='reused')
            report.budget_scope='original_daily_run'
        self.emit(dict(type='plan_daily_result',report=deepcopy(daily),reused=reused))

    def _require_daily_source(self, daily, identity, mark):
        info = self.report.weekly_plan
        try:
            directory = Path(daily['run_dir'])
            root = self.root.resolve()
            resolved = directory.resolve(strict=True)
            path = resolved / 'report.json'
            if (not directory.is_absolute() or resolved != directory or resolved == root
                    or not resolved.is_relative_to(root) or resolved == Path(self.report.run_dir).resolve()
                    or path.resolve(strict=True) != path or daily.get('operation') != 'daily'):
                raise AutomationError('日常原报告不在本次原生运行目录。')
            with path.open('rb') as stream:
                raw = stream.read(64 * 1024 * 1024 + 1)
            if len(raw) > 64 * 1024 * 1024 or json.loads(raw) != json.loads(json.dumps(daily)):
                raise AutomationError('日常原报告与本次子任务结果不一致。')
            if self._native_factory or identity.public()['bound']:
                identity.require_step(mark)
                if not identity.has_step_proof(mark, run_dir=daily['run_dir']):
                    raise AutomationError('日常原报告缺少属于本次子运行的账号证据。')
            source = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
            if info.get('daily_source', source) != source:
                raise AutomationError('日常原报告在交接期间已变化。')
        except (AutomationError, OSError, ValueError, KeyError, TypeError) as error:
            info.update(daily_handoff='needs_review', daily_handoff_reason='日常原报告或账号来源待核对')
            raise AutomationError('日常原报告或账号来源待核对，未推进周常。') from error
        info['daily_source'] = source
        return source

    def _daily_handoff(self, daily):
        info = self.report.weekly_plan
        stopped = self.stop_requested or daily.get('status') == 'stopped'
        if stopped:
            reason = '日常或交接已停止'
        elif daily.get('report_saved') is not True:
            reason = '日常原报告未完整保存'
        elif daily.get('status') != 'success':
            reason = '所选日常仍有未核实项'
        elif 'daily' in info['daily_tasks'] and daily.get('daily_verified') is not True:
            reason = '所选实训奖励尚未核实'
        elif any(daily.get(field, 0) != 0 for field in ('stamina_pending', 'immersifiers_pending')):
            reason = '日常仍有资源待核对'
        else:
            info['daily_handoff'] = 'complete'
            return True
        info.update(daily_handoff='stopped' if stopped else 'needs_review', daily_handoff_reason=reason)
        self.report.status = 'stopped' if stopped else 'partial'
        self._weekly_result('not_started', f'{reason}；周常未开始。')
        return False

    def _finish_weekly_du_rewards(self, guard, settings, weekly, identity, mark):
        from .du_weekly_rewards import WeeklyRewardHandoff

        report = self.report
        info = report.weekly_plan
        child = {}
        info['score_rewards_receipt_state'] = 'needs_review'
        try:
            self._checkpoint()
            if info['objective'] != 'points':
                raise AutomationError('原固定局数周常已完成，本次缺少满额积分回执。')
            identity.require_step(mark)
            if not identity.has_step_proof(mark, run_dir=weekly['run_dir']):
                raise AutomationError('差分积分子任务缺少本次账号证明。')
            handoff = WeeklyRewardHandoff(guard.receipt)
            with handoff.hold_goal():
                previous = handoff.read_finished()
                self._checkpoint()
                handoff.require_current()
                if previous is not None:
                    info.update(score_rewards_verified=True, score_rewards_delivery_verified=True,
                                score_rewards_home_verified=True, score_rewards_receipt_state='reused',
                                score_rewards_receipt=str(handoff.path))
                    self._weekly_result('already_complete', '已只读核对原差分积分、到账、返回和周领奖回执。')
                    return
                if guard.reused_report is not None:
                    raise AutomationError('原积分目标已完成，缺少可复用的周领奖回执。')

                reward_mark = identity.mark()
                child = self._run(replace(settings, redemption_enabled=False), phase='weekly_rewards',
                                  operation='du_rewards', du_periodic_rewards=True, du_weekly_reward=handoff)
                info['children'].append(dict(operation='du_rewards', run_dir=child.get('run_dir', '')))
                record = handoff.inspect_child(child)
                if record is not None:
                    info.update(score_rewards_delivery_verified=record.get('periodic_rewards_verified') is True,
                                score_rewards_home_verified=bool(record.get('final_home_frames')))
                self._checkpoint()
                if record is None or child.get('status') != 'success' or child.get('report_saved') is not True:
                    raise AutomationError(child.get('error') or '独立周期领奖或报告尚未完整核实。')
                identity.require_step(reward_mark)
                if not identity.has_step_proof(reward_mark, run_dir=child['run_dir']):
                    raise AutomationError('独立周期领奖子任务缺少本次账号证明。')
                handoff.publish(child, record, checkpoint=self._checkpoint, stopped=lambda: self.stop_requested)
                info.update(score_rewards_verified=True, score_rewards_receipt_state='complete',
                            score_rewards_receipt=str(handoff.path))
                self._weekly_result('complete', '本周差分积分、到账、返回与周领奖回执均已核实。')
        except Exception as error:
            stopped = isinstance(error, Stopped) or self.stop_requested
            report.status = 'stopped' if stopped else 'partial'
            report.error = str(error)
            report.safe_next = child.get('safe_next') or '核对独立周期领奖和原周回执。'
            if stopped:
                self.stop()
                info['score_rewards_receipt_state'] = 'stopped'
            self._weekly_result('needs_review', '原周常目标已完成，周期领奖收尾待核对。')

    def _run_weekly_du(self, identity, *, require_daily_source=None):
        self.emit(dict(type="task", task="weekly", status="running", detail="核对本周演算记录"))
        guard = WeeklyGuard(self.root, self.settings, self.slot, until_points=self.du_until_points,
                            **(dict(strict_points_account=True) if self.du_claim_weekly_rewards else {}))
        maximum = guard.settings.weekly_runs
        weekly_settings = replace(self.settings, assignments=False, battle=False, daily=False,
                                  mail=False, battlepass=False, differential_universe_mode="periodic",
                                  differential_universe_runs=maximum,
                                  differential_universe_daily=False, differential_universe_save=False,
                                  differential_universe_rewards=False)
        mark = identity.mark() if self.du_claim_weekly_rewards else None

        def before_child():
            guard.require_current_week()
            if require_daily_source is not None:
                require_daily_source()

        weekly = self._run(weekly_settings, phase="weekly", operation="differential_universe",
                           du_runs=maximum, weekly_plan=guard, before_child=before_child,
                           **(dict(du_until_points=True) if guard.until_points else {}))
        report = self.report
        info = report.weekly_plan
        info["children"].append(dict(operation="differential_universe", run_dir=weekly.get("run_dir", "")))
        report.differential_universe = weekly.get("differential_universe", {})
        data = report.differential_universe
        objective = info["objective"]
        original = guard.reused_report
        if original is not None:
            receipt = guard.receipt.data
            data = original["differential_universe"]
            objective, maximum = receipt.get("objective", "fixed_runs"), receipt["requested_runs"]
            info.update(original_run_dir=original["run_dir"], due_at=receipt["due_at"])
        completed = data.get("completed_runs", 0)
        info.update(objective=objective, requested_runs=maximum, maximum_runs=maximum, completed_runs=completed,
                    new_completed_runs=0 if original is not None else completed, points_capped=None)
        status = weekly.get("status")
        stopped = self.stop_requested or status == "stopped"
        exhausted = objective == "points" and data.get("periodic_points_goal", {}).get("status") == "exhausted"
        if stopped or weekly.get("report_saved") is not True or not (status == "success" or status == "partial" and exhausted):
            report.status = "stopped" if stopped else "partial"
            report.error, report.safe_next = weekly.get("error", ""), weekly.get("safe_next", "")
            report.input_error_field = weekly.get("input_error_field", "")
            self._weekly_result("needs_review", "周常演算未完成；核对原报告后再处理。")
            return
        try:
            if original is not None:
                self._checkpoint()
                guard.require_current_week()
                state = guard.receipt.data["state"]
                info["reused_result"] = True
            else:
                state = guard.complete(weekly, checkpoint=self._checkpoint)
        except Stopped as error:
            self.stop()
            report.status, report.error = 'stopped', str(error)
            self._weekly_result('needs_review', '周常回执保存前收到停止，已保留子报告。')
            return
        if objective == "points":
            info["points_capped"] = state == "complete"
        if self.du_claim_weekly_rewards:
            info.update(goal_receipt_state=state, goal_receipt=str(guard.receipt.path))
        if state == "exhausted":
            report.status = "partial"
            self._weekly_result("exhausted", f"本周 {maximum} 局开局上限已用完，周期积分仍未满。")
        elif self.du_claim_weekly_rewards:
            self._finish_weekly_du_rewards(guard, weekly_settings, weekly, identity, mark)
        elif guard.already_complete:
            self._weekly_result("already_complete", "本周原演算目标已完成，已跳过。")
        elif objective == "points":
            self._weekly_result("complete", f"本周周期积分已满，核实 {completed} 局新开胜利。")
        else:
            self._weekly_result("complete", f"本周 {maximum} 局周期演算已完成；周积分奖励未核实。")

    def run(self):
        started = datetime.now(CHINA)
        directory = self.root/(started.strftime("%Y%m%d_%H%M%S_%f")+"_plan_"+uuid.uuid4().hex[:8])
        directory.mkdir(parents=True)
        report = self.report
        report.run_dir, report.started_at, report.source = str(directory), started.isoformat(), str(self.root.parent)
        report.weekly_plan = dict(week=self.slot.week, due_at=self.slot.due_at.isoformat(),
                                 mode=self.settings.weekly_mode, requested_runs=self.settings.weekly_runs,
                                 daily_tasks=_daily_tasks(self.settings),
                                 status="waiting", score_rewards_verified=False, children=[])
        report.weekly_plan['daily_handoff'] = 'not_started' if report.weekly_plan['daily_tasks'] else 'not_selected'
        if self.settings.weekly_mode == 'differential_universe':
            report.weekly_plan['objective'] = 'points' if self.du_until_points else 'fixed_runs'
        if self.du_claim_weekly_rewards:
            report.weekly_plan.update(score_rewards_requested=True, score_rewards_delivery_verified=False,
                                      score_rewards_home_verified=False, score_rewards_receipt_state='not_started')
        from .workflow_lease import sequence_lease
        from .workflow_identity import sequence_identity
        scopes = ExitStack()
        identity = None
        def publish_identity(public):
            report.execution_identity = deepcopy(public)
            self.emit(dict(type='execution_identity', **public))
        try:
            scopes.enter_context(sequence_lease())
            identity = scopes.enter_context(sequence_identity(directory, publish=publish_identity))
            publish_identity(identity.public())
            self._checkpoint()
            daily_reference=None
            require_daily_source = None
            if self.settings.weekly_enabled and self.settings.weekly_mode=='currency_wars':
                from .currency_wars_weekly import preflight,read_ref
                try:existing=preflight(self.root,self.resume_weekly_currency)
                except Exception:
                    from .currency_wars_loop_store import LoopStore
                    from .currency_wars_weekly import check_sources,unfinished
                    old=LoopStore(self.root)
                    if old.load() is not None and unfinished(old):
                        ref=old.data['weekly_plan']['daily']
                        if ref is not None:
                            _,original=read_ref(self.root,ref);self._copy_daily(original,reused=True)
                        check_sources(old)
                        target=old.data['weekly_plan']
                        report.currency_wars=dict(mode='weekly_currency',loop_id=old.data['loop_id'],week=target['week'],
                            maximum=target['maximum'],completed=old.data['completed'],state=target['state'],phase=target['phase'],
                            settled_games=old.data['completed'],defeats=old.data.get('defeats',0),
                            victories=old.data['completed']-old.data.get('defeats',0),
                            loop_record=str(old.path),score_rewards_verified=False,reused_result=True,current_account_verified=False,
                            acceptance_runs=0,development_only=True)
                        report.weekly_plan.update(week=target['week'],due_at=target['due_at'],requested_runs=target['maximum'],
                            maximum_runs=target['maximum'],completed_runs=old.data['completed'],
                            defeats=old.data.get('defeats',0),victories=old.data['completed']-old.data.get('defeats',0))
                    raise
                if self.resume_weekly_currency:
                    from .weekly_plan import WeeklySlot
                    target=existing.data['weekly_plan']
                    self.slot=WeeklySlot(target['week'],datetime.fromisoformat(target['due_at']),True)
                    report.weekly_plan.update(week=target['week'],due_at=target['due_at'],requested_runs=target['maximum'],daily_reused=True)
                    daily_reference=target['daily']
                    if daily_reference is not None:
                        _,original=read_ref(self.root,daily_reference);self._copy_daily(original,reused=True)
            daily_selected = bool(report.weekly_plan['daily_tasks'])
            if daily_selected:
                daily_mark = identity.mark()
                daily = self._run(self.settings, phase="daily", operation="daily", new_battle_run=self.new_battle_run,
                    **(dict(use_power_plan=True,new_power_plan=self.new_power_plan) if self.use_power_plan else {}))
                self._copy_daily(daily)
                if not self._daily_handoff(daily):
                    return report
                if self.settings.weekly_enabled and self.slot.due:
                    def require_daily_source():
                        return self._require_daily_source(daily, identity, daily_mark)

                    daily_reference = require_daily_source()
            self._checkpoint()
            report.status = "success"
            if not self.settings.weekly_enabled:
                self._weekly_result("disabled", "周常未加入。")
            elif not self.slot.due:
                self._weekly_result("not_due", "周常未到计划时间。")
            elif self.settings.weekly_mode == "currency_wars":
                from .currency_wars_weekly_run import CurrencyWeekRunner
                weekly=self._run(self.settings,phase='weekly',factory=CurrencyWeekRunner,slot=self.slot,root=self.root,
                                 runner_factory=self.factory,resume=self.resume_weekly_currency,daily=daily_reference,
                                 before_child=require_daily_source)
                data=weekly.get('currency_wars',{});report.currency_wars=data
                report.weekly_plan['children'].append(dict(operation='currency_wars_weekly',run_dir=weekly.get('run_dir','')))
                report.weekly_plan.update(score_rewards_verified=(weekly.get('status')=='success' and weekly.get('report_saved') is True
                    and data.get('score_rewards_verified') is True),
                    completed_runs=data.get('completed',0),maximum_runs=data.get('maximum',self.settings.weekly_runs),
                    victories=data.get('victories',data.get('completed',0)),defeats=data.get('defeats',0),
                    requested_runs=data.get('maximum',self.settings.weekly_runs))
                report.error,report.safe_next=weekly.get('error',''),weekly.get('safe_next','')
                if weekly.get('status')=='success' and weekly.get('report_saved') is True and data.get('score_rewards_verified') is True:
                    self._weekly_result('already_complete' if data.get('already_complete') else 'complete','本周货币战争积分及奖励已核实。')
                else:
                    report.status='stopped' if weekly.get('status')=='stopped' else 'partial'
                    reason = ('本周对局上限已用完，积分仍未满。' if data.get('state') == 'exhausted' else
                              '原周目标已过期。' if data.get('state') == 'expired' else '货币战争周常未完成。')
                    self._weekly_result(data.get('state') if data.get('state') in ('exhausted','expired') else 'needs_review',
                                        reason+('日常结果已保留。' if daily_reference is not None else '')+
                                        ('原目标已保留。' if data.get('loop_id') else ''))
            else:
                self._run_weekly_du(identity, require_daily_source=require_daily_source)
        except Stopped as exc:
            self.stop()
            report.status, report.error = "stopped", str(exc)
            self._weekly_result("not_started", "计划已停止；未继续下一项。")
        except Exception as exc:
            report.status, report.error = "partial" if report.results else "failed", str(exc)
            report.safe_next = "查看日常与周常各自的原始报告；未核实的开局不自动重放。"
            if isinstance(exc, SettingsError):
                report.input_error_field = exc.field
                report.safe_next = "请修改对应设置，再次开始。"
            self._weekly_result("needs_review", str(exc))
        finally:
            try:
                if identity is not None:
                    report.execution_identity = deepcopy(identity.public())
                report.finished_at = datetime.now(CHINA).isoformat()
                try:
                    report.report_saved = True
                    temp = directory/"report.tmp"
                    temp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                    replace_file(temp, directory/"report.json")
                except OSError as exc:
                    report.report_saved = False
                    if report.status != "stopped":
                        report.status = "partial"
                    report.report_write_error = str(exc)
                    report.error = (report.error+"；" if report.error else "")+"计划报告保存失败。"
                self.emit(dict(type="finished", report=report.to_dict()))
            finally:
                scopes.close()
        return report
