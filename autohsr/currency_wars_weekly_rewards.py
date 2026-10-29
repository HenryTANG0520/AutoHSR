"""Current controls for Currency Wars weekly rewards, separate from a match.

Reference: March7thAssistant.get_reward / wait_for_weekly_reward at 7cf6c6b.
No generic confirmation, purchase or full-inventory cleanup is authorized here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .currency_wars_navigation import page_kind, unique
from .currency_wars_points import read_points
from .currency_wars_prepare import trusted
from .free_rewards import claim_enabled
from .models import AutomationError, normalize

OPERATION='currency_wars_rewards'
BUTTON=(.65,.58,.98,.80)
CLOSE=(.25,.65,.75,.90)
EMPTY=('暂无可领取奖励','无可领取奖励','奖励已全部领取')


@dataclass(frozen=True)
class RewardAction:
    intent: str
    expected: str
    target: object = None
    key: str | None = None


def fuel_limit(scene,confidence=.85):
    clean=trusted(scene,confidence)
    rows=[]
    for token in sorted((t for t in clean.tokens if t.within((.20,.30,.80,.60))),key=lambda t:t.center[1]):
        if not rows or abs(token.center[1]-rows[-1][0].center[1])>.015:rows.append([])
        rows[-1].append(token)
    words=''.join(normalize(t.text) for row in rows for t in sorted(row,key=lambda t:t.box[0]))
    return '背包内助燃券持有数量已达上限' in words


def quantities(scene,confidence=.85):
    clean=trusted(scene,confidence)
    result=[]
    for token in clean.tokens:
        text=normalize(token.text).replace(',','').replace('，','')
        if token.within((.10,.24,.90,.64)) and re.fullmatch(r'[x×]?\d{1,7}',text):
            value=int(text.lstrip('x×'))
            if value>0:result.append(value)
    return result


def overlay(scene,confidence=.85):
    clean=trusted(scene,confidence)
    return (not fuel_limit(scene,confidence)
            and clean.has('获得物品',(.25,.04,.75,.25),exact=True)
            and clean.has('点击空白处关闭',CLOSE,exact=True) and bool(quantities(scene,confidence)))


def kind(scene,confidence=.85):
    if fuel_limit(scene,confidence):return 'fuel_ticket_limit'
    if overlay(scene,confidence):return 'reward_overlay'
    return page_kind(scene,confidence)


def panel_control(scene,confidence=.85):
    """Missing is unknown. A gold control and a neutral disabled one differ."""
    if kind(scene,confidence)!='points_rewards':
        raise AutomationError('当前不是已核实积分奖励面板。')
    read_points(scene,confidence)
    if scene.has(('确认购买','支付','购买','是否消耗','知道了'),(.20,.25,.80,.80),exact=True):
        raise AutomationError('积分面板存在其他弹窗，未点击领取。')
    # Count even low-confidence duplicates, rather than dropping conflicts.
    candidates=[t for t in scene.tokens if t.within(BUTTON) and normalize(t.text)=='一键领取']
    empty=[t for t in scene.tokens if t.within(BUTTON) and normalize(t.text) in EMPTY]
    if len(candidates)>1 or len(empty)>1 or candidates and empty:
        raise AutomationError('积分领取控件冲突或不唯一。')
    if empty:
        if empty[0] in trusted(scene,confidence).tokens:return 'settled',None
        raise AutomationError('积分无可领取状态置信度不足。')
    if len(candidates)!=1 or candidates[0] not in trusted(scene,confidence).tokens:
        raise AutomationError('积分领取按钮缺失或尚未核实，不能推断奖励已领。')
    target=candidates[0];enabled=claim_enabled(scene,target)
    if enabled is True:return 'available',target
    if enabled is False:return 'settled',target
    raise AutomationError('积分领取按钮可用状态未知。')


def next_action(scene,data,confidence=.85):
    phase=data['phase'];page=kind(scene,confidence)
    if phase=='lobby' and page=='lobby':
        points=read_points(scene,confidence)
        if points.current!=data['current']:raise AutomationError('积分已改变，未使用旧领取目标。')
        return RewardAction('open_points_rewards','points_rewards',unique(trusted(scene,confidence),'积分',(.16,.86,.25,.91)))
    if phase=='panel' and page=='points_rewards':
        points=read_points(scene,confidence)
        if points.current!=data['current']:raise AutomationError('面板积分与本次主页观察不符。')
        state,target=panel_control(scene,confidence)
        if state=='available':
            if not points.current:raise AutomationError('零积分与可领取控件冲突，未领取。')
            return RewardAction('claim_weekly_rewards','reward_overlay',target)
        return None
    if phase=='overlay' and page=='reward_overlay':
        return RewardAction('dismiss_weekly_rewards','points_rewards',unique(trusted(scene,confidence),'点击空白处关闭',CLOSE))
    if phase=='panel_settled' and page=='points_rewards':
        if read_points(scene,confidence).current!=data['current'] or panel_control(scene,confidence)[0]!='settled':
            raise AutomationError('返回前积分或不可领取状态已改变。')
        return RewardAction('return_weekly_lobby','lobby',key='esc')
    raise AutomationError('积分奖励当前页面与已记录阶段不符：'+phase+'/'+page)
