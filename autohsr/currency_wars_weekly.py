"""Weekly Currency Wars ownership on the existing native loop journal.

The weekly index is immutable: another plan click never adds new match budget.
Current account observations and native child receipts remain separate proofs.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from .currency_wars_loop_store import LoopStore, _hex, _immutable, _read, _write
from .currency_wars_points import game_week, local_now
from .currency_wars_points_run import _hash, read_receipt
from .models import AutomationError


def inside(root,value):
    path=Path(value).resolve();root=Path(root).resolve()
    if not path.is_relative_to(root) or path==root:raise AutomationError('周常证据不在本地运行目录内。')
    return path


def file_ref(root,value):
    path=inside(root,value)
    return dict(path=str(path),sha256=_hash(path))


def read_ref(root,ref):
    if type(ref) is not dict or set(ref)!={'path','sha256'} or not _hex(ref['sha256'],64):
        raise AutomationError('周常证据引用无效。')
    path=inside(root,ref['path'])
    if _hash(path)!=ref['sha256']:raise AutomationError('周常原报告或回执已改变。')
    return path,_read(path)


def saved_report(root,report,operation):
    path=inside(root,report['run_dir'])/'report.json';ref=file_ref(root,path)
    if (_read(path)!=json.loads(json.dumps(report)) or report.get('report_saved') is not True
            or report.get('operation')!=operation):raise AutomationError('周常子报告未完整保存或与原件不符。')
    return ref


def index_path(root,account,week):
    if not _hex(account,64) or game_week(datetime.fromisoformat(week+'T04:00:00+08:00'))!=week:
        raise AutomationError('周常账号或游戏周索引无效。')
    return Path(root)/'currency-weekly-index'/account/(week+'.json')


@dataclass(frozen=True)
class WeekSpec:
    week: str
    due_at: str
    account: str
    maximum: int
    initial_points: dict
    daily: dict | None
    run_dir: str

    def metadata(self):
        return dict(schema=1,week=self.week,due_at=self.due_at,account=self.account,maximum=self.maximum,
                    initial_points=deepcopy(self.initial_points),daily=deepcopy(self.daily),
                    state='active',phase='points',reward=None,loop_report=None,reward_report=None,
                    attempts=[self.run_dir],loop_attempts=[],reward_history=[])


def validate_week(data):
    plan=data.get('weekly_plan')
    if plan is None:return
    if (type(plan) is not dict or type(plan.get('schema')) is not int or plan['schema']!=1
            or plan.get('state') not in ('active','complete','exhausted','expired')
            or plan.get('phase') not in ('points','rewards','done')
            or type(plan.get('maximum')) is not int or not 1<=plan['maximum']<=10
            or plan['maximum']!=data['options']['runs'] or data['options'].get('until_points') is not True
            or not _hex(plan.get('account'),64) or plan['account']!=data['account_key']
            or plan.get('week')!=data['points_goal']['week']
            or not isinstance(plan.get('attempts'),list) or not plan['attempts']
            or not isinstance(plan.get('loop_attempts'),list)):
        raise AutomationError('货币战争周常目标、预算或归属无效。')
    due=datetime.fromisoformat(plan['due_at'])
    if due.tzinfo is None or game_week(due)!=plan['week']:
        raise AutomationError('货币战争周常计划时间与冻结周不符。')
    reward=plan.get('reward')
    if reward is not None and (type(reward) is not dict or set(reward)!={'id','path'} or not _hex(reward['id'])):
        raise AutomationError('货币战争周常领奖归属无效。')
    if (plan['state']!='active' and plan['phase']!='done'
            or plan['phase']=='rewards' and data['status'] not in ('complete','exhausted')
            or plan['phase']=='done' and (plan['state']=='active' or data['status']=='active')
            or plan['state']=='expired' and data['status']!='expired'
            or plan['state']=='exhausted' and data['status']!='exhausted'
            or plan['phase']=='points' and (reward is not None or plan.get('reward_report') is not None)
            or plan['phase']=='done' and plan['state'] in ('complete','exhausted')
               and (reward is None or plan.get('reward_report') is None)):
        raise AutomationError('货币战争周常阶段与原循环不符。')


def unfinished(store):
    plan=store.data.get('weekly_plan') if store.data else None
    return plan is not None and (plan['state']=='active' or plan['state']=='complete' and not (store.path.parent/'weekly.receipt.json').is_file())


def ensure_index(store):
    plan=store.data['weekly_plan']
    path=index_path(store.root,plan['account'],plan['week']);path.parent.mkdir(parents=True,exist_ok=True)
    _immutable(path,dict(schema=1,loop_id=store.data['loop_id']))


def load_index(root,account,week):
    path=index_path(root,account,week)
    if not path.exists():return None
    entry=_read(path)
    if type(entry) is not dict or set(entry)!={'schema','loop_id'} or type(entry['schema']) is not int or entry['schema']!=1 or not _hex(entry['loop_id']):
        raise AutomationError('货币战争周常索引损坏，未重建预算。')
    store=LoopStore(root);store.path=store.root/'currency-loops'/entry['loop_id']/'loop.json'
    store.data=_read(store.path);store.validate(store.data)
    plan=store.data.get('weekly_plan',{})
    if plan.get('account')!=account or plan.get('week')!=week:raise AutomationError('周常索引与原目标不一致。')
    return store


def preflight(root,resume=False):
    store=LoopStore(root);data=store.load()
    if resume:
        if data is None or data.get('weekly_plan') is None:raise AutomationError('没有可接续的货币战争周常目标。')
        ensure_index(store);check_sources(store)
        return store
    if data is not None and (unfinished(store) or data['status']=='active'):
        raise AutomationError('已有未结束循环或货币战争周常；未开始日常或新增预算，请明确接续原目标。')
    from .currency_wars_points_run import require_no_active_match
    from .currency_wars_session import StandardSession
    require_no_active_match(StandardSession(store.journal).data)
    if data is not None and data.get('weekly_plan') and data['weekly_plan']['state']=='complete':check_complete(store)
    return store


def check_sources(store):
    plan=store.data['weekly_plan']
    if store.data['completed']==0:store.check_tail()
    previous=None
    for slot in range(1,store.data['completed']+1):
        receipt_path=store.path.parent/(str(slot)+'.session.receipt.json')
        receipt=_read(receipt_path);digest=_hash(receipt_path)
        if receipt.get('previous')!=previous:raise AutomationError('周常逐局回执链不连续。')
        audit=LoopStore(store.root);audit.path=store.path
        audit.data=dict(store.data,completed=slot,last_receipt=digest)
        audit.check_tail();previous=digest
    if previous!=store.data['last_receipt']:raise AutomationError('周常末次回执与逐局来源不符。')
    path,_=read_ref(store.root,plan['initial_points']);receipt=read_receipt(store.root,path)
    observed=receipt['observation']
    if observed['account_key']!=plan['account'] or observed['game_week']!=plan['week'] or observed['period']['verified'] is not True:
        raise AutomationError('周常初始积分观察归属不符。')
    if plan['daily'] is not None:
        _,daily=read_ref(store.root,plan['daily'])
        if daily.get('operation')!='daily' or daily.get('status')!='success' or daily.get('report_saved') is not True:
            raise AutomationError('原日常报告未完整完成，不能作为周常来源。')
    for key in ('loop_report','reward_report'):
        if plan[key] is not None:read_ref(store.root,plan[key])
    if plan['loop_report'] is not None:
        _,reported=read_ref(store.root,plan['loop_report']);body=reported.get('currency_wars',{})
        if (reported.get('operation')!='currency_wars_loop' or reported.get('report_saved') is not True
                or body.get('loop_id')!=store.data['loop_id'] or body.get('requested_runs')!=plan['maximum']
                or type(body.get('completed')) is not int or not 0<=body['completed']<=store.data['completed']
                or body.get('weekly_plan',{}).get('account')!=plan['account']):
            raise AutomationError('周常原循环报告与冻结归属不符。')
    for history in plan.get('reward_history',[]):
        old=deepcopy(store.data);old['weekly_plan']['reward']=history['reward']
        original=LoopStore(store.root);original.path=store.path;original.data=old
        rewards=reward_store(original);rewards.check_receipt();read_ref(store.root,history['report'])
    if plan.get('reward_report') is not None:
        rewards=reward_store(store)
        if rewards is None:raise AutomationError('周常领奖报告缺少原生归属。')
        rewards.check_receipt()
        path,reported=read_ref(store.root,plan['reward_report'])
        receipt=_read(rewards.path.parent/'receipt.json')
        if str(path)!=receipt['report'] or reported.get('currency_wars')!=rewards.data:
            raise AutomationError('周常领奖报告并非所绑定原生回执的原件。')


class WeekGuard:
    """Typed native-child permission for one already frozen weekly target."""
    def __init__(self,store,stage):
        if stage not in ('points','rewards'):raise ValueError('周常阶段无效。')
        plan=store.data['weekly_plan']
        self.root=store.root;self.loop_id=store.data['loop_id'];self.stage=stage
        self.account,self.week=plan['account'],plan['week']

    @property
    def owner(self):return dict(loop_id=self.loop_id,account=self.account,week=self.week)

    def current(self):
        store=LoopStore(self.root);store.load()
        if store.data is None or store.data['loop_id']!=self.loop_id:raise AutomationError('周常当前目标归属改变。')
        plan=store.data.get('weekly_plan',{})
        if (plan.get('state')!='active' or plan.get('phase')!=self.stage or plan.get('account')!=self.account
                or plan.get('week')!=self.week):raise AutomationError('周常冻结目标或执行阶段改变。')
        ensure_index(store)
        return store

    def require_observation(self,account,week,current=None):
        store=self.current()
        if account!=self.account or week!=self.week:raise AutomationError('当前账号／游戏周与周常目标不符。')
        if self.stage=='rewards' and current is not None:
            prior=store.data['points_goal']['observation']
            if prior is None or current<prior['current']:raise AutomationError('当前积分低于周常原观察，未继续领奖。')

    def bind_reward(self,rewards):
        store=self.current();plan=store.data['weekly_plan']
        data=rewards.data
        if data.get('weekly_owner')!=self.owner:raise AutomationError('原生领奖未绑定本周目标。')
        ref=dict(id=data['id'],path=str(rewards.path))
        if plan['reward'] not in (None,ref):raise AutomationError('已有本周领奖尝试，未开启第二次。')
        plan['reward']=ref;store.save()


def native_gate(root,operation,loop_guard=None,weekly_guard=None,*,standard_resume=False,rewards_resume=False):
    store=LoopStore(root);store.load()
    if store.data and store.data.get('weekly_plan',{}).get('state')=='complete' and not unfinished(store):check_complete(store)
    if store.data is None or not unfinished(store):
        if weekly_guard is not None:raise AutomationError('周常原目标不再等待当前步骤。')
        return None
    plan=store.data['weekly_plan']
    if weekly_guard is not None:
        if not isinstance(weekly_guard,WeekGuard) or weekly_guard.loop_id!=store.data['loop_id']:
            raise AutomationError('周常子流程归属无效。')
        weekly_guard.current();return weekly_guard
    if operation=='currency_wars_standard' and plan['phase']=='points':
        owner=loop_guard.store.data.get('weekly_plan') if loop_guard is not None else None
        if owner is not None and loop_guard.store.data['loop_id']==store.data['loop_id']:
            return WeekGuard(store,'points')
        if standard_resume:
            from .currency_wars_session import StandardSession
            session=StandardSession(store.journal).data
            if (session and session.get('loop_owner',{}).get('loop_id')==store.data['loop_id']
                    and session.get('account_key')==plan['account']):return WeekGuard(store,'points')
    if operation=='currency_wars_rewards' and rewards_resume and plan['phase']=='rewards':
        from .currency_wars_weekly_reward_store import RewardStore
        rewards=RewardStore(root);rewards.load()
        guard=WeekGuard(store,'rewards')
        if rewards.data and rewards.data.get('weekly_owner')==guard.owner:
            guard.bind_reward(rewards);return guard
    raise AutomationError('货币战争周常尚未结束；未进入其他输入任务，请明确接续原周常。')


def reward_store(store):
    from .currency_wars_weekly_reward_store import RewardStore
    ref=store.data['weekly_plan']['reward']
    if ref is None:return None
    rewards=RewardStore(store.root)
    rewards.path=inside(store.root,ref['path']);rewards.data=_read(rewards.path);rewards.validate(rewards.data)
    expected=store.root/'currency-weekly-rewards'/ref['id']/'session.json'
    if (rewards.path!=expected or rewards.data['id']!=ref['id'] or rewards.data.get('weekly_owner')!=WeekGuard(store,'rewards').owner):
        raise AutomationError('周常领奖原件归属或路径不符。')
    return rewards


def check_complete(store):
    check_sources(store);plan=store.data['weekly_plan']
    receipt=_read(store.path.parent/'weekly.receipt.json')
    path,report=read_ref(store.root,receipt['report'])
    rewards=reward_store(store)
    if rewards is None:raise AutomationError('周常完成缺少原生领奖来源。')
    rewards.check_receipt()
    body=report.get('currency_wars',{})
    original=receipt.get('original_report',{})
    original_path=inside(store.root,original.get('path',''))
    if (plan['state']!='complete' or type(receipt.get('schema')) is not int or receipt['schema']!=1 or receipt.get('loop_sha256')!=_hash(store.path)
            or receipt.get('reward_receipt_sha256')!=_hash(rewards.path.parent/'receipt.json')
            or report.get('status')!='success' or report.get('report_saved') is not True
            or report.get('operation')!='currency_wars_weekly' or rewards.data['weekly_rewards_verified'] is not True
            or body.get('mode')!='weekly_currency' or body.get('loop_id')!=store.data['loop_id']
            or body.get('week')!=plan['week'] or body.get('account_key')!=plan['account']
            or body.get('score_rewards_verified') is not True or body.get('completed')!=store.data['completed']):
        raise AutomationError('货币战争周常原报告、积分或奖励回执不完整。')
    if (original_path!=inside(store.root,plan['attempts'][-1])/'report.json'
            or original.get('sha256')!=(_hash(original_path) if original_path.is_file() else None)
            or receipt.get('read_only_recovery') is not body.get('read_only_recovery')):
        raise AutomationError('周常原报告或只读恢复归属改变。')
    return path
