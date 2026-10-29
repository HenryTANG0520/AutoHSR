"""Optional, frozen weekly score target for the native standard loop.

Saved points prove a score observation only. Every actual input still requires
the native current-scene, account, epoch and durable-action checks.
"""
from __future__ import annotations

from datetime import date, datetime
import json

from .currency_wars_points import game_week, local_now
from .currency_wars_points_run import _hash, _read, read_receipt
from .models import AutomationError


def enabled(data):
    return data['options'].get('until_points', False)


def begin():
    return dict(week=game_week(local_now()), latest=None, observation=None, checked_completed=None)


def _summary(observation):
    return {key: observation[key] for key in ('game_week', 'observed_at', 'current', 'limit',
                                             'score_complete', 'weekly_target_verified')} | {
        'period_verified': observation['period']['verified']}


def validate(data):
    """Check journal structure without treating it as fresh input authority."""
    goal=data.get('points_goal')
    if not enabled(data):
        if goal is not None:
            raise AutomationError('按局数循环不应包含周积分目标。')
        return
    if type(goal) is not dict or set(goal)!={'week','latest','observation','checked_completed'}:
        raise AutomationError('周积分目标记录结构无效。')
    try:
        week=date.fromisoformat(goal['week'])
        valid=week.isoformat()==goal['week'] and week.weekday()==0
    except (TypeError,ValueError):
        valid=False
    if not valid:
        raise AutomationError('周积分目标的游戏周无效。')
    if goal['latest'] is None:
        if goal['observation'] is not None or goal['checked_completed'] is not None:
            raise AutomationError('周积分目标缺少原始回执。')
        return
    from .currency_wars_loop_store import _hex
    ref=goal['latest'];summary=goal['observation'];checked=goal['checked_completed']
    if (type(ref) is not dict or set(ref)!={'receipt','sha256','report','report_sha256'}
            or any(not isinstance(ref[k],str) for k in ('receipt','report'))
            or any(not _hex(ref[k],64) for k in ('sha256','report_sha256'))
            or type(summary) is not dict
            or set(summary)!={'game_week','observed_at','current','limit','score_complete','weekly_target_verified','period_verified'}
            or type(checked) is not int or not 0<=checked<=data['completed']
            or type(summary['current']) is not int or not 0<=summary['current']<=18000
            or type(summary['limit']) is not int or summary['limit']!=18000
            or any(type(summary[k]) is not bool for k in ('score_complete','period_verified','weekly_target_verified'))
            or summary['score_complete'] is not (summary['current']==summary['limit'])
            or summary['weekly_target_verified'] is not (summary['score_complete'] and summary['period_verified'])
            or not _hex(data.get('account_key'),64)):
        raise AutomationError('周积分目标的观察摘要、账号或回执无效。')
    try:
        timestamp=datetime.fromisoformat(summary['observed_at'])
        valid=game_week(timestamp)==summary['game_week']
    except (TypeError,ValueError):
        valid=False
    if not valid:
        raise AutomationError('周积分目标的观察时间无效。')


def record(store,child):
    """Bind only after the child report, receipt, OCR and image all agree."""
    observation=child.get('currency_wars',{})
    path=store._inside(observation.get('receipt_path',''))
    receipt=read_receipt(store.root,path)
    saved=_read(store._inside(receipt['report']))
    if saved!=json.loads(json.dumps(child)) or observation!=receipt['observation']:
        raise AutomationError('本次积分子报告与已保存回执不一致。')
    age=(local_now()-datetime.fromisoformat(observation['observed_at'])).total_seconds()
    if not -5<=age<=120:
        raise AutomationError('本次积分观察已过期或来自未来，未作为当前目标依据。')
    account=observation['account_key']
    if store.data['account_key'] not in (None,account):
        raise AutomationError('积分账号与本循环绑定账号不同，未改写目标或开始对局。')
    store.data['account_key']=account
    goal=store.data['points_goal']
    goal.update(latest=dict(receipt=str(path),sha256=_hash(path),report=receipt['report'],
                            report_sha256=receipt['report_sha256']),
                observation=_summary(observation),checked_completed=store.data['completed'])
    store.save()


def observation(store):
    """Read the exact receipt, never the replaceable latest pointer."""
    goal=store.data['points_goal'];ref=goal['latest']
    if ref is None:
        raise AutomationError('本循环尚未取得已保存的积分观察。')
    path=store._inside(ref['receipt'])
    if _hash(path)!=ref['sha256']:
        raise AutomationError('本循环积分回执已改变。')
    receipt=read_receipt(store.root,path);result=receipt['observation']
    if (receipt['report']!=ref['report'] or receipt['report_sha256']!=ref['report_sha256']
            or result['account_key']!=store.data['account_key'] or _summary(result)!=goal['observation']):
        raise AutomationError('本循环积分摘要与原始观察不一致。')
    return result


def expired(store):
    return store.data['points_goal']['week']!=game_week(local_now())


def require_start(store):
    if not enabled(store.data):
        return
    goal=store.data['points_goal'];data=store.data
    if expired(store):
        raise AutomationError('周积分目标已跨游戏周，未开始新局；原目标不自动迁移。')
    current=observation(store)
    age=(local_now()-datetime.fromisoformat(current['observed_at'])).total_seconds()
    if (current['game_week']!=goal['week'] or goal['checked_completed']!=data['completed']
            or not -5<=age<=120 or current['period']['verified'] is not True):
        raise AutomationError('周积分观察过期、周界未核实或未在本局前核对，未开局。')
    if current['score_complete'] is True:
        raise AutomationError('本周积分已满，未开始额外对局。')
    if data['options']['runs'] and data['completed']>=data['options']['runs']:
        raise AutomationError('本循环已达到局数上限，未追加预算。')
