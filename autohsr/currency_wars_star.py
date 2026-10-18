"""Preserve the observed Sparkle star preference and confirm current feedback."""
import re
import time

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_deployment import _crop
from .currency_wars_match import read_match
from .currency_wars_rewards import _node,_gold
from .models import AutomationError,EmptyCapture,normalize


def star_choice(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='star_selection':
        raise AutomationError('盛会之星候选页未核实。')
    options=[]
    for cx in (.422,.545,.669):
        found=[t for t in scene.tokens if confidence<=t.score<=1 and t.within((cx-.06,.30,cx+.06,.35))
               and re.fullmatch(r'盛会之星[一—-][\u4e00-\u9fff]{1,12}女士',normalize(t.text))]
        if len(found)!=1:
            raise AutomationError('盛会之星三名角色未完整识别。')
        options.append(found[0])
    flower=[t for t in options if re.fullmatch(r'盛会之星[一—-]花火女士',normalize(t.text))]
    if len(flower)!=1:
        raise AutomationError('没有已核实的花火强化候选。')
    return flower[0]


def star_selected(scene,confidence=.65):
    import numpy as np
    target=star_choice(scene,confidence)
    centers=(.422,.545,.669)
    selected=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='已选择'
              and t.within((.35,.14,.74,.20))]
    expected=min(centers,key=lambda x:abs(x-target.center[0]))
    if len(selected)!=1 or min(centers,key=lambda x:abs(x-selected[0].center[0]))!=expected or scene.image is None:
        return False
    border=_crop(scene.image,(expected-.059,.16,expected-.056,.33))
    return bool(border.size and np.mean(np.min(border,axis=2)>200)>=.15)


def star_confirm_target(scene,confidence=.65):
    if not star_selected(scene,confidence):
        raise AutomationError('花火的强化卡片选中反馈未核实。')
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='确认选择'
             and t.within((.68,.49,.87,.56))]
    if len(targets)!=1:
        raise AutomationError('强化角色确认按钮未核实。')
    return targets[0]


def choose_star(c,scene,data,persist):
    guard=CurrencyWarsWorkflow(c)
    origin=_node(scene,c.settings.ocr_confidence)
    gold=_gold(scene,c.settings.ocr_confidence)
    if origin is None or gold is None:
        raise AutomationError('强化角色选择前节点或金币未核实。')
    phases=('confirm',) if star_selected(scene,c.settings.ocr_confidence) else ('select','confirm')
    for phase in phases:
        guard._require_current_scene(scene)
        action=dict(action=phase+'_star',name='花火',origin_node=origin,status='pending',
                    before=str(c.evidence(scene,'currency_star_'+phase)))
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        c.currency_select_star(scene,confirm=phase=='confirm')
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
                current=read_match(after,c.settings.ocr_confidence)
                ready=(current is not None and current.page=='preparation' and current.node==origin and current.gold==gold
                       if phase=='confirm' else observe(after,c.settings.ocr_confidence).page_kind=='star_selection' and star_selected(after,c.settings.ocr_confidence))
                if ready:
                    action.update(status='verified',after=str(c.evidence(after,'currency_star_'+phase+'_after')))
                    data.update(action_status='star_'+phase+'_verified',screenshot=action['after'])
                    persist()
                    scene=after
                    break
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status']='unknown'
            if c.last_scene is not None:
                action['after']=str(c.evidence(c.last_scene,'currency_star_unknown'))
                data['screenshot']=action['after']
            data['action_status']='unknown'
            persist()
            return False
    return True
