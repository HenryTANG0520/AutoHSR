"""Plan-owned points, bounded matches and rewards using the ordinary Runners."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import threading
import uuid

from .currency_wars_loop import CurrencyLoopRunner
from .currency_wars_loop_store import LoopStore, _immutable, _read, _write, loop_lock
from .currency_wars_points import game_week,local_now
from .currency_wars_points_run import _hash,read_receipt
from .currency_wars_weekly import (WeekGuard,WeekSpec,check_complete,check_sources,ensure_index,file_ref,
    inside,load_index,preflight,read_ref,reward_store,saved_report)
from .currency_wars_weekly_reward_store import RewardStore
from .models import AutomationError,RunReport,Stopped,TaskResult
from .plan_runner import PlanRunner


class CurrencyWeekRunner(PlanRunner):
    def __init__(self,settings,emit=None,*,slot,root,runner_factory=None,resume=False,daily=None):
        super().__init__(settings,emit,runner_factory=runner_factory,root=root)
        if type(resume) is not bool:raise ValueError('货币战争周常接续须为布尔值。')
        self.slot=slot;self.resume_week=resume;self.daily=daily;self.store=None
        self.report=RunReport(operation='currency_wars_weekly')
        self._monitor_end=threading.Event();self._control_hwnd=None

    _gap_controls=CurrencyLoopRunner._gap_controls

    def _send(self,event,phase):
        if event.get('type')=='paused':
            with self._lock:self._paused=bool(event.get('paused'))
        if event.get('type')!='finished':self.emit(dict(event,currency_weekly_stage=phase))

    def _summary(self):
        if self.store is None or self.store.data is None or self.store.data.get('weekly_plan') is None:return
        data=self.store.data;plan=data['weekly_plan']
        previous=self.report.currency_wars
        self.report.currency_wars=dict(mode='weekly_currency',loop_id=data['loop_id'],week=plan['week'],
            account_key=plan['account'],state=plan['state'],phase=plan['phase'],maximum=plan['maximum'],
            completed=data['completed'],loop_record=str(self.store.path),score_rewards_verified=plan['state']=='complete',
            acceptance_runs=0,development_only=True,daily=deepcopy(plan['daily']),
            children=previous.get('children',[]),already_complete=previous.get('already_complete',False),
            later_points_observed=bool(plan.get('reward_history')),
            read_only_recovery=previous.get('read_only_recovery',False),
            current_account_verified=previous.get('current_account_verified',False))

    def _child(self,phase,**options):
        self.emit(dict(type='currency_weekly_phase',stage=phase))
        child=self._run(self.settings,phase=phase,**options)
        self.report.currency_wars.setdefault('children',[]).append(dict(operation=child.get('operation'),run_dir=child.get('run_dir','')))
        return child

    def _loop_proof(self,report):
        store=self.store;data=store.data;plan=data['weekly_plan']
        ref=saved_report(store.root,report,'currency_wars_loop');body=report.get('currency_wars',{})
        if (body.get('loop_id')!=data['loop_id'] or body.get('completed')!=data['completed']
                or body.get('requested_runs')!=plan['maximum'] or body.get('until_points') is not True
                or body.get('status')!=data['status']):raise AutomationError('周常循环汇总与原账本不符。')
        check_sources(store)
        if data['status'] in ('complete','exhausted'):
            from .currency_wars_points_goal import observation
            observation(store)
        plan['loop_report']=ref;store.save()

    def _reward_phase(self):
        store=self.store;guard=WeekGuard(store,'rewards');plan=store.data['weekly_plan']
        rewards=reward_store(store)
        if rewards is None:
            current=RewardStore(store.root);current.load()
            previous_ids={h['reward']['id'] for h in plan.get('reward_history',[])}
            if current.data and current.data['id'] not in previous_ids and current.data.get('weekly_owner')==guard.owner:
                guard.bind_reward(current);store.load();rewards=reward_store(store)
        committed=rewards is not None and (rewards.path.parent/'receipt.json').exists()
        if committed:
            rewards.check_receipt();receipt=_read(rewards.path.parent/'receipt.json')
            report=_read(Path(receipt['report']))
        else:
            report=self._child('rewards',operation='currency_wars_rewards',currency_rewards_resume=rewards is not None,
                               currency_weekly_guard=guard)
        store.load();plan=store.data['weekly_plan']
        if report.get('status')!='success' or report.get('report_saved') is not True:
            self.report.status='stopped' if report.get('status')=='stopped' else 'partial'
            self.report.error=report.get('error','');self.report.safe_next=report.get('safe_next','')
            return
        ref=saved_report(store.root,report,'currency_wars_rewards')
        rewards=reward_store(store)
        if rewards is None:raise AutomationError('周常领奖未绑定原生尝试。')
        rewards.check_receipt()
        if report.get('currency_wars')!=rewards.data or rewards.data['rewards_verified'] is not True:
            raise AutomationError('周常领奖报告与原生回执不符。')
        plan['reward_report']=ref
        plan.update(phase='done',state='complete' if rewards.data['weekly_rewards_verified'] else 'exhausted')
        store.save();self.report.status='success' if plan['state']=='complete' else 'partial'
        self.report.safe_next=('本周积分及奖励已核实；本次开发局数不计独立验收。' if plan['state']=='complete'
                               else '本周已用完原局数上限，当前奖励已结清，积分仍未满；没有新增对局预算。')

    def _execute(self):
        self._checkpoint()
        if self.resume_week:
            self.store=preflight(self.root,True);plan=self.store.data['weekly_plan']
            if plan['state']=='complete' and (self.store.path.parent/'weekly.receipt.json').exists():
                check_complete(self.store);self.report.currency_wars['already_complete']=True
                self.report.currency_wars['read_only_recovery']=True
                self.report.status='success';return
            if plan['phase']=='done':
                if plan['state']=='complete':
                    rewards=reward_store(self.store)
                    if rewards is None:raise AutomationError('周常只读恢复缺少领奖原件。')
                    rewards.check_receipt()
                self.report.status='success' if plan['state']=='complete' else 'partial'
                self.report.currency_wars['read_only_recovery']=True
                self.report.safe_next='仅核对原目标和原生回执，补存周常审计报告；没有游戏输入或新增预算。'
                return
            plan['attempts'].append(self.report.run_dir);self.store.save()
        else:
            preflight(self.root)
            if game_week(local_now())!=self.slot.week:
                self.report.status='partial';self.report.safe_next='计划开始时的游戏周已结束；未迁移为新周目标。';return
            points=self._child('points',operation='currency_wars_points')
            if points.get('status')!='success' or points.get('report_saved') is not True:
                self.report.status='stopped' if points.get('status')=='stopped' else 'partial'
                self.report.error=points.get('error','');self.report.safe_next=points.get('safe_next','');return
            saved_report(self.root,points,'currency_wars_points')
            receipt=read_receipt(self.root,Path(points['currency_wars']['receipt_path']));observed=receipt['observation']
            if observed['period']['verified'] is not True or observed['game_week']!=self.slot.week or game_week(local_now())!=self.slot.week:
                self.report.status='partial';self.report.safe_next='当前积分的游戏周未核实为原计划周；未开局。';return
            existing=load_index(self.root,observed['account_key'],self.slot.week)
            self.report.currency_wars['current_account_verified']=True
            if existing is not None:
                self.store=existing;plan=existing.data['weekly_plan'];check_sources(existing)
                if plan['state']=='complete':
                    check_complete(existing);rewards=reward_store(existing)
                    if not observed['weekly_target_verified'] or observed['client']!=rewards.data['client']:
                        raise AutomationError('当前积分或客户端与原本周完成证据不同，未新增预算。')
                    self.report.status='success';self.report.currency_wars['already_complete']=True
                elif plan['state']=='exhausted' and observed['current']>reward_store(existing).data['current']:
                    # The current score can advance outside this budget. Keep
                    # the old partial receipt and claim only the new rewards;
                    # no match allowance or completed count is reset.
                    plan.setdefault('reward_history',[]).append(dict(reward=deepcopy(plan['reward']),report=deepcopy(plan['reward_report'])))
                    plan.update(state='active',phase='rewards',reward=None,reward_report=None)
                    plan['attempts'].append(self.report.run_dir);existing.save()
                    self._checkpoint();self._reward_phase()
                else:
                    self.report.status='partial';self.report.safe_next='该账号本周已有未完成或已耗尽的原目标；未新增预算，请核对并明确接续。'
                return
            spec=WeekSpec(self.slot.week,self.slot.due_at.isoformat(),observed['account_key'],self.settings.weekly_runs,
                          file_ref(self.root,observed['receipt_path']),self.daily,self.report.run_dir)
            result=self._child('loop',factory=CurrencyLoopRunner,runs=self.settings.weekly_runs,until_points=True,
                               weekly_plan=spec,root=self.root,runner_factory=self.factory)
            self.store=LoopStore(self.root);self.store.load()
            if self.store.data is None or self.store.data.get('weekly_plan') is None:
                self.report.status='partial';self.report.error=result.get('error','周常循环未创建');return
            self._loop_proof(result)
        store=self.store;data=store.data;plan=data['weekly_plan']
        if plan['phase']=='points':
            if self.resume_week:
                result=self._child('loop',factory=CurrencyLoopRunner,resume=True,root=self.root,runner_factory=self.factory)
                store.load();data=store.data;plan=data['weekly_plan'];self._loop_proof(result)
            if data['status']=='active':
                self.report.status='stopped' if result.get('status')=='stopped' else 'partial'
                self.report.error=result.get('error','');self.report.safe_next=result.get('safe_next','');return
            if data['status']=='expired':
                plan.update(phase='done',state='expired');store.save();self.report.status='partial'
                self.report.safe_next='原周目标已过期；原局及证据保留，没有领取新周奖励。';return
            if data['status'] not in ('complete','exhausted'):raise AutomationError('周常循环状态尚不能领取奖励。')
            plan['phase']='rewards';store.save()
        self._checkpoint();self._reward_phase()

    def run(self):
        started=datetime.now().astimezone();directory=self.root/(started.strftime('%Y%m%d_%H%M%S_%f')+'_currency_weekly_'+uuid.uuid4().hex[:8])
        directory.mkdir(parents=True);self.report.run_dir=str(directory);self.report.started_at=started.isoformat()
        self.report.source=str(self.root.parent);monitor=None;locked=False;lock=loop_lock(self.root/'currency-weekly-lock')
        try:
            lock.__enter__();locked=True
            monitor=threading.Thread(target=self._gap_controls,daemon=True);monitor.start()
            try:self._execute()
            finally:
                self._monitor_end.set();monitor.join(timeout=1)
        except Stopped as error:self.report.status,self.report.error='stopped',str(error)
        except Exception as error:
            self.report.status,self.report.error='partial',str(error)
            self.report.safe_next='保留原目标及子报告；仅明确接续剩余步骤，未知输入不重放。'
        finally:
            try:self._finish(directory)
            finally:
                if locked:lock.__exit__(None,None,None)
        return self.report

    def _finish(self,directory):
        self._summary();report=self.report;report.finished_at=datetime.now().astimezone().isoformat()
        report.results.append(TaskResult('weekly_currency','ok' if report.status=='success' else report.status,report.safe_next))
        try:
            report.report_saved=True;_write(directory/'report.json',report.to_dict())
            if report.status=='success' and self.store is not None:
                receipt_path=self.store.path.parent/'weekly.receipt.json'
                if receipt_path.exists():check_complete(self.store)
                else:
                    check_sources(self.store);rewards=reward_store(self.store);rewards.check_receipt()
                    if not rewards.data['weekly_rewards_verified']:raise AutomationError('本周积分奖励未完整核实。')
                    _immutable(receipt_path,dict(schema=1,loop_sha256=_hash(self.store.path),
                        reward_receipt_sha256=_hash(rewards.path.parent/'receipt.json'),report=file_ref(self.root,directory/'report.json'),
                        original_report=dict(path=str(Path(self.store.data['weekly_plan']['attempts'][-1])/'report.json'),
                            sha256=_hash(Path(self.store.data['weekly_plan']['attempts'][-1])/'report.json')
                            if (Path(self.store.data['weekly_plan']['attempts'][-1])/'report.json').is_file() else None),
                        read_only_recovery=report.currency_wars['read_only_recovery']))
        except (OSError,ValueError,AutomationError) as error:
            report.status='partial';report.report_write_error=str(error)
            report.error='周常汇总或完成回执保存失败：'+str(error)
            report.safe_next='原结果保留；明确接续只读补存周常报告，不重新执行日常或对局。'
            try:_write(directory/'report.json',report.to_dict())
            except (OSError,ValueError,AutomationError):report.report_saved=False
        self.emit(dict(type='finished',report=report.to_dict()))
