"""Choose a visible character/basic-equipment pair, then verify confirmation."""
from __future__ import annotations

import re
import time

from .currency_wars import CurrencyWarsWorkflow, observe
from .models import AutomationError, EmptyCapture, normalize

# A simple defensive default, independent of character portraits or rarity.
# Each item name was read from the local basic-equipment/recipe UI.
BASICS = ('量产型装甲','光能电池','以太钻头','折叠小刀','和平手枪','幸运星')
# Capture 167 names all five advanced items; capture 168 verifies the sail's
# energy effect. Other advanced items are readable but are not policy choices.
SUPPLY_ITEMS = BASICS+('步步生花','流星飞翼','信心注入器','天基轨道炮','蓄能帆')
SUPPLY_PRIORITY = BASICS+('蓄能帆',)


def preferred_supply(options):
    known=[o for o in options if o[2] in SUPPLY_PRIORITY]
    if not known:
        raise AutomationError('补给没有已核实效果的装备选择。')
    return min(known,key=lambda o:(SUPPLY_PRIORITY.index(o[2]),o[0]))


def supply_options(scene, confidence=.65):
    if observe(scene,confidence).page_kind != 'supply_selection':
        raise AutomationError('补给候选页未核实。')
    options=[]
    for slot,cx in enumerate((.13,.315,.5,.685,.87),1):
        names=[t for t in scene.tokens if confidence<=t.score<=1 and
               t.within((cx-.08,.50,cx+.08,.55)) and
               re.fullmatch(r'[\u4e00-\u9fff·]{1,12}|archer',normalize(t.text))]
        items=[t for t in scene.tokens if confidence<=t.score<=1 and
               t.within((cx-.085,.61,cx+.085,.67)) and normalize(t.text) in SUPPLY_ITEMS]
        if len(names)!=1 or len(items)!=1:
            raise AutomationError('五组补给角色与装备未完整识别，未选择。')
        options.append((slot,normalize(names[0].text),normalize(items[0].text),names[0]))
    if len({o[1] for o in options})!=5:
        raise AutomationError('补给角色名称重复或不明确。')
    return tuple(options)


def supply_count(scene,confidence=.65):
    counts=[int(m[1]) for t in scene.tokens if confidence<=t.score<=1 and
            t.within((.84,.835,.94,.88)) and
            (m:=re.fullmatch(r'已选择([01])/1',normalize(t.text)))]
    if len(counts)!=1:
        raise AutomationError('补给已选数量未核实。')
    return counts[0]


def supply_choice(scene,confidence=.65):
    options=supply_options(scene,confidence)
    if supply_count(scene,confidence)!=0:
        raise AutomationError('补给已有选择，未重新点击或自动确认。')
    return preferred_supply(options)


def supply_confirm(scene,expected,confidence=.65):
    import numpy as np
    from .currency_wars_deployment import _crop
    options=supply_options(scene,confidence)
    if tuple(o[:3] for o in options)!=expected or supply_count(scene,confidence)!=1:
        raise AutomationError('补给选择反馈或候选组合不一致。')
    selected=preferred_supply(expected)[0]
    if scene.image is None:
        raise AutomationError('补给选中图像缺失。')
    highlighted=[]
    for slot,cx in enumerate((.13,.315,.5,.685,.87),1):
        patch=_crop(scene.image,(cx-.075,.59,cx+.075,.69))
        if patch.size and np.mean(np.min(patch,axis=2)>180)>.6:
            highlighted.append(slot)
    if highlighted!=[selected]:
        raise AutomationError('补给白色选中卡片与本次候选不一致。')
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and
             normalize(t.text)=='确认' and t.within((.85,.885,.93,.94))]
    if len(targets)!=1:
        raise AutomationError('补给确认按钮未核实。')
    return targets[0]


def choose_supply(c,scene,data,persist):
    choice=supply_choice(scene,c.settings.ocr_confidence)
    expected=tuple(o[:3] for o in supply_options(scene,c.settings.ocr_confidence))
    guard=CurrencyWarsWorkflow(c)
    for phase in ('select','confirm'):
        guard._require_current_scene(scene)
        action=dict(action=phase+'_supply',slot=choice[0],name=choice[1],equipment=choice[2],
                    status='pending',before=str(c.evidence(scene,'currency_supply_'+phase)))
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        c.currency_select_supply(scene,expected,choice[:3],confirm=phase=='confirm')
        elapsed=0.
        while elapsed<20:
            started=time.monotonic()
            inactive=c.runner.inactive_duration
            try:
                after=c.snapshot()
            except EmptyCapture:
                after=None
            if after is not None:
                guard._require_current_scene(after)
                kind=observe(after,c.settings.ocr_confidence).page_kind
                ready=kind in ('preparation','shop','bench_full') if phase=='confirm' else False
                if phase=='select' and kind=='supply_selection':
                    try:
                        supply_confirm(after,expected,c.settings.ocr_confidence)
                        ready=True
                    except AutomationError:
                        pass
                if ready:
                    action.update(status='verified',after=str(c.evidence(after,'currency_supply_'+phase+'_after')))
                    data.update(action_status='supply_'+phase+'_verified',screenshot=action['after'])
                    persist()
                    scene=after
                    break
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status']='unknown'
            if after is not None:
                data['screenshot']=str(c.evidence(after,'currency_supply_unknown'))
            data['action_status']='unknown'
            persist()
            return False
    return True
