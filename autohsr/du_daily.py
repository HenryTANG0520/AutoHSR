"""Once-per-account game-day daily interlude after a verified DU return."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .models import AutomationError,RunReport,Stopped,normalize
from .storage import replace_file

CHINA=timezone(timedelta(hours=8))


def game_day(now=None):
    now=now or datetime.now(CHINA)
    if now.tzinfo is None:
        raise ValueError('游戏日需要带时区的时间。')
    return (now.astimezone(CHINA)-timedelta(hours=4)).date().isoformat()


def account_key(scene):
    values=[]
    for token in scene.tokens:
        if token.within((0,.95,.35,1)):
            match=re.fullmatch(r'uid[:：]?(\d{8,10})',normalize(token.text))
            if match:
                values.append(match.group(1))
    if len(values)!=1:
        raise AutomationError('通关后日常未核实当前账号标识，未领取或刷本。')
    return hashlib.sha256(values[0].encode('ascii')).hexdigest()[:24]


class DayJournal:
    def __init__(self,root,key,day):
        self.folder=Path(root)/'du-daily'/f'{day}-{key}'
        self.path=self.folder/'state.json'
        self.key,self.day=key,day
        self.data={}

    def begin(self,run_id):
        self.folder.mkdir(parents=True,exist_ok=True)
        self.data=dict(version=1,account_key=self.key,game_day=self.day,status='started',
                       phase='before_daily',du_run_id=run_id,batches=[],free_tasks=[])
        try:
            with self.path.open('x',encoding='utf8') as handle:
                json.dump(self.data,handle,ensure_ascii=False,indent=2)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            try:
                self.data=json.loads(self.path.read_text('utf8'))
            except (OSError,ValueError) as error:
                raise AutomationError('当日通关后日常记录无法读取，未重复执行。') from error
            if (self.data.get('version')!=1 or self.data.get('account_key')!=self.key
                    or self.data.get('game_day')!=self.day):
                raise AutomationError('当日通关后日常记录与账号或游戏日不一致。')
            if self.data.get('status')=='complete':
                return False
            raise AutomationError('当日通关后日常已有中断记录，须核实原结算；未重复消耗资源。')
        return True

    def save(self,**changes):
        self.data.update(changes,updated_at=datetime.now(CHINA).isoformat())
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf8')
        replace_file(temporary,self.path)


class _DailyRunner:
    """Share the live runner's controls while keeping settings and reports separate."""
    def __init__(self,parent,settings,report):
        self.parent,self.settings,self.report=parent,settings,report

    def __getattr__(self,name):
        return getattr(self.parent,name)

    def log(self,message,level='info'):
        self.parent.log('通关后日常：'+message,level)


def _context(flow,folder,settings,day):
    from .app import Context
    folder.mkdir(parents=True,exist_ok=True)
    report=RunReport(operation='daily',run_dir=str(folder),source=flow.ctx.report.source,
                     started_at=datetime.now(CHINA).isoformat(),game_day=day)
    context=Context(_DailyRunner(flow.ctx.runner,settings,report),flow.ctx.window,flow.ctx.vision)
    context.battle_budget=None
    return context


def _save_report(context,status):
    context.report.status=status
    context.report.finished_at=datetime.now(CHINA).isoformat()
    path=Path(context.report.run_dir)/'report.json'
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(context.report.to_dict(),ensure_ascii=False,indent=2),encoding='utf8')
    replace_file(temporary,path)
    return str(path)


def _free_task(journal,workflow,name,*,allow_incomplete_activity=False):
    result=_step(workflow.ctx,getattr(workflow,name),name)
    workflow.ctx.report.results.append(result)
    journal.data['free_tasks'].append(dict(result.__dict__))
    journal.save()
    if result.status!='ok':
        activity=workflow.ctx.report.engagement
        if not (allow_incomplete_activity and name=='daily' and type(activity) is int and activity<500):
            raise AutomationError('通关后日常尚未核实：'+result.detail)


def _step(context,action,name):
    # Use the same pause/focus recovery as normal dailies, bound to the daily
    # report so a token-only pending bill cannot be hidden by the DU report.
    from .app import Runner
    return Runner._resume_step(context.runner,action,name)


def _farm(flow,journal,workflow,settings):
    from .config import ROOT
    from .planar_resources import inventory
    from .recovery import BattleBudget,recovery_state
    from .workflows import DailyWorkflow
    bills=[ROOT/'runs']
    bills.extend(path.parent for folder in journal.folder.parent.glob('*-'+journal.key)
                 for path in folder.glob('batch-*/battle-session.json'))
    for folder in bills:
        pending=recovery_state(folder)
        if (pending.get('corrupt') or pending.get('pending') or pending.get('immersifiers_pending')
                or (pending.get('blocked') and pending.get('pending') is None)):
            raise AutomationError('仍有未核对的刷本资源记录，未开启通关后刷本。')
    scene=workflow._disable_quick_refill(workflow._open_calyx())
    available,tokens=workflow._available(scene),inventory(scene)
    if account_key(scene)!=journal.key or available is None or tokens is None:
        raise AutomationError('通关后刷本账号、开拓力或沉浸器余额未核实。')
    remaining=available//40+tokens
    journal.save(phase='farming',initial_stamina=available,initial_immersifiers=tokens,
                 planned_challenges=remaining,
                 preparation_evidence=str(workflow.ctx.evidence(scene,'du_daily_resources_before')))
    # Freeze the available challenge count. Regeneration during combat never
    # extends this day's resource plan, and each batch has its own durable bill.
    index=0
    while remaining:
        flow.ctx.checkpoint()
        index+=1
        count=min(6,remaining)
        batch_settings=replace(settings,challenge_count=count,rounds=count,stamina_limit=count*40)
        batch=_context(flow,journal.folder/f'batch-{index:02d}',batch_settings,journal.day)
        budget=BattleBudget(Path(batch.report.run_dir),batch_settings,batch.report)
        budget.begin()
        batch.battle_budget=budget
        record=dict(batch=index,requested=count,status='started',report=str(Path(batch.report.run_dir)/'report.json'))
        journal.data['batches'].append(record)
        journal.save(phase=f'farming_batch_{index}')
        try:
            result=_step(batch,DailyWorkflow(batch).battle,'battle')
            batch.report.results.append(result)
            if result.status!='ok' or batch.report.battle_completed!=count:
                raise AutomationError('通关后刷本批次未完整核实：'+result.detail)
            _save_report(batch,'success')
            budget.finish()
            record.update(status='complete',completed=count,stamina_spent=batch.report.stamina_spent,
                          immersifiers_spent=batch.report.immersifiers_spent)
            remaining-=count
            journal.save()
        except BaseException as error:
            batch.report.error=str(error)
            _save_report(batch,'stopped' if isinstance(error,Stopped) else 'failed')
            budget.finish()
            record.update(status='failed',error=str(error),stamina_pending=batch.report.stamina_pending,
                          immersifiers_pending=batch.report.immersifiers_pending)
            journal.save()
            raise
    journal.save(phase='free_rewards_after',farming_status='complete' if index else 'insufficient_resources')


def after_win(flow,scene,kind,*,root=None,now=None):
    """Called only after the run's victory and return were durably recorded."""
    if not getattr(flow.settings,'differential_universe_daily',False):
        return scene,kind
    from .config import ROOT
    from .du_rewards import home,settled_home
    from .differential_universe import classify_page
    from .workflows import DailyWorkflow
    completed=(flow.report.get('run_results') or [{}])[-1]
    if (completed.get('status') not in ('completed','returned_uncounted')
            or not completed.get('victory_evidence') or not completed.get('return_evidence')):
        raise AutomationError('没有本局已核实胜利和返回的证据，未开启通关后日常。')
    day=game_day(now)
    start_day=getattr(flow.settings,'differential_universe_daily_from','')
    if start_day and day<start_day:
        flow.report.setdefault('daily_interludes',[]).append(dict(game_day=day,
            status='before_start_day',start_day=start_day))
        flow._persist_ledger()
        flow.ctx.log(f'通关后日常从游戏日{start_day}开始；本游戏日跳过。')
        return scene,kind
    if not home(scene):
        scene,kind=flow._collect_rewards(scene,kind,'daily_interlude_home')
    if not home(scene):
        raise AutomationError('通关后日常须从已核实的差分宇宙主页开始。')
    scene=settled_home(flow,scene)
    journal=DayJournal(root or ROOT/'runs',account_key(scene),day)
    run_id=(flow.report.get('run_results') or [{}])[-1].get('run_id')
    if not journal.begin(run_id):
        flow.ctx.log('当前账号本游戏日的通关后日常已完成，继续差分宇宙。')
        return scene,kind
    entry=dict(game_day=journal.day,marker=str(journal.path),status='started')
    flow.report.setdefault('daily_interludes',[]).append(entry)
    flow._persist_ledger()
    settings=replace(flow.settings,dungeon_category='planar',target_name='浴火钢心',
        target_location='位面饰品',challenge_count=None,rounds=6,stamina_limit=240,
        use_support=False,assignments=True,battle=True,allow_stamina_spend=True,daily=True,
        mail=True,battlepass=True,auto_launch=False,differential_universe_daily=False)
    daily=_context(flow,journal.folder/'free-rewards',settings,journal.day)
    workflow=DailyWorkflow(daily)
    try:
        flow.ctx.key('esc')
        daily.wait(lambda p:workflow._world(p) or workflow._phone(p),timeout=20,description='返回大世界处理当日日常')
        _free_task(journal,workflow,'assignments')
        _free_task(journal,workflow,'daily',allow_incomplete_activity=True)
        _farm(flow,journal,workflow,settings)
        for name in ('daily','mail','battlepass'):
            _free_task(journal,workflow,name)
        report_path=_save_report(daily,'success')
        scene=flow.ctx.snapshot()
        scene,kind=flow._open_differential_universe(scene,classify_page(scene,flow.ctx))
        if kind not in ('home','mode_select','periodic_setup'):
            raise AutomationError('日常已处理，返回差分宇宙菜单尚未核实。')
        returned=str(flow.ctx.evidence(scene,'du_daily_return_verified'))
        journal.save(status='complete',phase='returned',daily_verified=daily.report.daily_verified,
                     free_report=report_path,return_evidence=returned)
        entry.update(status='complete',report=report_path,return_evidence=returned,
                     completed=sum(r.get('completed',0) for r in journal.data['batches']),
                     stamina_spent=sum(r.get('stamina_spent',0) for r in journal.data['batches']),
                     immersifiers_spent=sum(r.get('immersifiers_spent',0) for r in journal.data['batches']))
        flow._persist_ledger()
        return scene,kind
    except BaseException as error:
        daily.report.error=str(error)
        _save_report(daily,'stopped' if isinstance(error,Stopped) else 'failed')
        journal.save(status='failed',error=str(error))
        entry.update(status='failed',error=str(error))
        flow._persist_ledger()
        raise
