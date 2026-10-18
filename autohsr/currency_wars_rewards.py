"""Open observed bench rewards and resolve calibrated one-click choices."""
import re
import time

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_deployment import _BENCH_CENTERS
from .currency_wars_match import read_match
from .currency_wars_supply import BASICS
from .models import AutomationError,EmptyCapture,normalize


def open_reward_target(scene,confidence=.65):
    state=read_match(scene,confidence)
    if not state or state.page!='preparation' or not state.node:
        raise AutomationError('开启备战物品需要明确的备战节点。')
    for slot,cx in enumerate(_BENCH_CENTERS,1):
        targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='开启'
                 and t.within((cx-.035,.78,cx+.035,.91))]
        if len(targets)==1:
            return slot,targets[0]
    raise AutomationError('没有已识别的备战物品开启按钮。')


def reward_choice(scene,confidence=.65):
    kind=observe(scene,confidence).page_kind
    if kind in ('equipment_selection','advanced_equipment_selection'):
        known=(BASICS+('轮滑鞋','生命之花') if kind=='equipment_selection' else
               ('电光履','反重力皮靴','武器大师','很硬的甲'))
        options=[]
        for cx in (.346,.497,.647,.799):
            matches=[t for t in scene.tokens if confidence<=t.score<=1 and
                     t.within((cx-.065,.25,cx+.065,.29)) and normalize(t.text) in known]
            if len(matches)!=1:
                raise AutomationError('武装箱四个候选未完整识别。')
            options.append(matches[0])
        if kind=='advanced_equipment_selection':
            # Capture 166 confirms 20% wearer mitigation and 18% team mitigation.
            selected=[t for t in options if normalize(t.text)=='很硬的甲']
            if len(selected)!=1:
                raise AutomationError('进阶武装箱没有已核实效果的通用减伤装备。')
            return kind,selected[0]
        priority=BASICS+('生命之花','轮滑鞋')
        return kind,min(options,key=lambda t:priority.index(normalize(t.text)))
    if kind=='expert_selection':
        cash=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='现金为王'
              and t.within((.75,.33,.83,.38))]
        amount=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='4'
                and t.within((.81,.26,.85,.30))]
        if len(cash)==len(amount)==1:
            return kind,cash[0]
        raise AutomationError('邀请函4金币选项未核实，未选择角色顾问。')
    raise AutomationError('当前不是已校准的奖励候选页。')


def _node(scene,confidence):
    values={normalize(t.text) for t in scene.tokens if confidence<=t.score<=1 and
            t.within((.1,.02,.30,.14)) and re.fullmatch(r'[1-3]-[1-9][0-9]?',normalize(t.text))}
    return next(iter(values)) if len(values)==1 else None


def _gold(scene,confidence):
    values={int(normalize(t.text)) for t in scene.tokens if confidence<=t.score<=1 and
            t.within((.851,.829,.87,.868)) and re.fullmatch(r'[0-9]{1,4}',normalize(t.text))}
    return next(iter(values)) if len(values)==1 else None


def reward_action(c,scene,data,persist,*,opening=False):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(scene)
    origin=_node(scene,c.settings.ocr_confidence)
    if not origin:
        raise AutomationError('奖励来源节点未核实。')
    if opening:
        slot,target=open_reward_target(scene,c.settings.ocr_confidence)
        name='open_bench_reward'
    else:
        kind,target=reward_choice(scene,c.settings.ocr_confidence)
        name='choose_'+kind
    gold=_gold(scene,c.settings.ocr_confidence)
    if not opening and kind=='expert_selection' and gold is None:
        raise AutomationError('邀请函领取前金币未核实。')
    action=dict(action=name,status='pending',origin_node=origin,name=target.text,
                before=str(c.evidence(scene,'currency_'+name)))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_open_reward(scene,slot) if opening else c.currency_choose_reward(scene,kind,target.text)
    elapsed=0.
    while elapsed<15:
        started=time.monotonic()
        inactive=c.runner.inactive_duration
        try:
            after=c.snapshot()
        except EmptyCapture:
            after=None
        if after is not None:
            guard._require_current_scene(after)
            next_kind=observe(after,c.settings.ocr_confidence).page_kind
            ready=(next_kind in ('equipment_selection','advanced_equipment_selection','expert_selection') if opening else next_kind=='preparation')
            if ready and not opening:
                current=read_match(after,c.settings.ocr_confidence)
                if kind=='expert_selection':
                    ready=current is not None and current.gold==gold+4
                elif gold is not None:
                    ready=current is not None and current.gold==gold
            if ready and _node(after,c.settings.ocr_confidence)==origin:
                action.update(status='verified',after=str(c.evidence(after,'currency_'+name+'_after')))
                data.update(action_status='reward_verified',screenshot=action['after'])
                persist()
                return True
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    action['status']='unknown'
    if c.last_scene is not None:
        action['after']=str(c.evidence(c.last_scene,'currency_'+name+'_unknown'))
        data['screenshot']=action['after']
    data['action_status']='unknown'
    persist()
    return False
