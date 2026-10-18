"""Collect a visible crystal once, then verify disappearance or a reward choice."""
import math
import time

import numpy as np

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_deployment import _crop,_texture,bench_face
from .currency_wars_match import read_match
from .currency_wars_node import loot_centers
from .models import AutomationError,EmptyCapture


def loot_target(scene,confidence=.65):
    state=read_match(scene,confidence)
    if state is None or state.page!='preparation' or not state.node or state.gold is None:
        raise AutomationError('领取晶矿需要明确的备战节点与金币。')
    if scene.image is None or not any(_texture(_crop(scene.image,bench_face(slot)))<8 for slot in range(1,10)):
        raise AutomationError('备战区没有已核实空位，先部署或整理角色再领取晶矿。')
    candidates=loot_centers(scene)
    if not candidates:
        raise AutomationError('没有已核实的奖励晶矿。')
    return min(candidates,key=lambda p:(p[2],p[1],p[0]))


def loot_feedback(before,after,target,confidence=.65):
    kind=observe(after,confidence).page_kind
    if kind=='bench_full':
        return 'unchanged'
    if kind in ('equipment_selection','advanced_equipment_selection','expert_selection'):
        return 'choice_opened'
    first,last=read_match(before,confidence),read_match(after,confidence)
    if (first is None or last is None or last.page!='preparation' or first.node!=last.node
            or first.hp!=last.hp or first.gold is None or last.gold is None or last.gold<first.gold
            or before.image is None or after.image is None or before.image.shape!=after.image.shape):
        return 'unknown'
    x,y,radius=target
    previous_crystals,current_crystals=loot_centers(before),loot_centers(after)
    if not any(math.hypot((a-x)*2560,(b-y)*1440)<max(8,radius*2560*.25) for a,b,_ in previous_crystals):
        return 'unknown'
    if any(math.hypot((a-x)*2560,(b-y)*1440)<max(18,radius*2560*.8) for a,b,_ in current_crystals):
        return 'unchanged'
    if len(previous_crystals)-len(current_crystals)!=1:
        return 'unknown'
    roi=(x-radius,y-radius*2560/1440,x+radius,y+radius*2560/1440)
    a,b=_crop(before.image,roi),_crop(after.image,roi)
    difference=float(np.mean(np.abs(a.astype(float)-b.astype(float))))
    return 'disappeared' if difference>=8 else 'unknown'


def collect_loot(c,before,data,persist):
    guard=CurrencyWarsWorkflow(c)
    target=loot_target(before,c.settings.ocr_confidence)
    guard._require_current_scene(before)
    action=dict(action='collect_loot',status='pending',target=list(target),
                before=str(c.evidence(before,'currency_loot_before')))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_collect_loot(before,target)
    elapsed,absent=0.,0
    feedback='unknown'
    after=None
    while elapsed<10:
        started=time.monotonic()
        inactive=c.runner.inactive_duration
        try:
            after=c.snapshot()
        except EmptyCapture:
            after=None
        if after is not None:
            guard._require_current_scene(after)
            feedback=loot_feedback(before,after,target,c.settings.ocr_confidence)
            absent=absent+1 if feedback=='disappeared' else 0
            if absent>=2 or feedback in ('choice_opened','unchanged') and observe(after,c.settings.ocr_confidence).page_kind=='bench_full':
                break
            if feedback=='choice_opened':
                break
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    status='verified' if feedback=='choice_opened' or absent>=2 else 'unknown'
    if after is not None and observe(after,c.settings.ocr_confidence).page_kind=='bench_full':
        status='overflow_pending'
    action.update(status=status,feedback=feedback)
    if after is not None:
        action['after']=str(c.evidence(after,'currency_loot_after'))
        data['screenshot']=action['after']
    data['action_status']=status
    persist()
    return status=='verified'
