"""Choices backed by names and effect text observed in the current game UI."""
from __future__ import annotations

import time

from .currency_wars import CurrencyWarsWorkflow, observe
from .currency_wars_deployment import _crop
from .models import AutomationError, EmptyCapture, normalize


def investment_choice(scene,confidence=.65):
    if observe(scene,confidence).page_kind != 'investment_selection':
        raise AutomationError('投资策略候选页未核实。')
    # Universal effects only. Synergy-specific and unfamiliar cards need a new
    # decision; neither rerolls nor names alone authorize an effect.
    effects=(('爆仓','我方小队攻击敌方目标后若其生命值百分比少于16%将其【斩杀】'),
             ('延迟收益','在战斗开始100行动值后我方小队伤害增幅提高40%'),
             ('保守派','我方小队获得8%伤害减免进入战斗时生命上限最低的角色额外获得12%伤害减免获得一件【进阶武装箱】'))
    for name,effect in effects:
        for cx in (.24,.50,.76):
            titles=[t for t in scene.tokens if confidence <= t.score <= 1 and
                    normalize(t.text)==normalize(name) and t.within((cx-.10,.43,cx+.10,.48))]
            description=[t for t in scene.tokens if confidence <= t.score <= 1 and
                         t.within((cx-.10,.48,cx+.10,.60))]
            description.sort(key=lambda t:(round(t.center[1],2),t.center[0]))
            if len(titles)==1 and ''.join(normalize(t.text) for t in description)==effect:
                return name,titles[0]
    raise AutomationError('当前没有已核实效果的通用投资策略，未刷新或选择。')


def investment_confirm(scene,name,confidence=.65):
    import numpy as np
    selected,title=investment_choice(scene,confidence)
    if selected != name or scene.image is None:
        raise AutomationError('投资策略选择与本次记录不一致。')
    patch=_crop(scene.image,(.43,.892,.57,.925))
    if patch.size==0 or np.mean(np.min(patch,axis=2)>180) < .6:
        raise AutomationError('投资策略确认按钮尚未启用，未确认。')
    # An enabled confirm button alone can belong to a different selected card.
    # The selected card has a white outer edge; require that edge only on the
    # policy's candidate. ROI calibrated from the native plane-three capture.
    chosen=[]
    for cx in (.24,.50,.76):
        border=_crop(scene.image,(cx-.106,.198,cx-.103,.722))
        if border.size and np.mean(np.min(border,axis=2)>200) >= .15:
            chosen.append(cx)
    expected=min((.24,.50,.76),key=lambda cx:abs(cx-title.center[0]))
    if chosen!=[expected]:
        raise AutomationError('投资策略卡片选中边框与候选不一致，未确认。')
    return next(t for t in scene.tokens if t.score >= confidence and
                normalize(t.text)=='确认' and t.within((.47,.89,.53,.93)))


def choose_investment(c,scene,data,persist):
    name,_=investment_choice(scene,c.settings.ocr_confidence)
    guard=CurrencyWarsWorkflow(c)
    for phase in ('select','confirm'):
        guard._require_current_scene(scene)
        before=str(c.evidence(scene,'currency_investment_'+phase))
        action=dict(action=phase+'_investment',name=name,status='pending',before=before)
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=before)
        persist()
        c.currency_select_investment(scene,name,confirm=phase=='confirm')
        elapsed=0.
        while elapsed < 20:
            started=time.monotonic()
            inactive=c.runner.inactive_duration
            try:
                after=c.snapshot()
            except EmptyCapture:
                after=None
            if after is not None:
                guard._require_current_scene(after)
                kind=observe(after,c.settings.ocr_confidence).page_kind
                ready=kind in ('preparation','shop') if phase=='confirm' else False
                if phase=='select' and kind=='investment_selection':
                    try:
                        investment_confirm(after,name,c.settings.ocr_confidence)
                        ready=True
                    except AutomationError:
                        pass
                if ready:
                    action.update(status='verified',after=str(c.evidence(after,'currency_investment_'+phase+'_after')))
                    data.update(action_status='investment_'+phase+'_verified',screenshot=action['after'])
                    persist()
                    scene=after
                    break
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status']='unknown'
            if after is not None:
                data['screenshot']=str(c.evidence(after,'currency_investment_unknown'))
            data['action_status']='unknown'
            persist()
            return False
    return True
