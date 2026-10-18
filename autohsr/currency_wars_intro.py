"""Dismiss the observed strong-enemy introduction, then reobserve the board."""
import time
from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_match import read_match
from .models import AutomationError,EmptyCapture,normalize


def boss_target(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='boss_intro':
        raise AutomationError('强敌介绍页未核实。')
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='点击空白处继续'
             and t.within((.43,.70,.57,.77))]
    if len(targets)!=1:
        raise AutomationError('强敌介绍继续提示不唯一。')
    return targets[0]


def advance_boss(c,scene,data,persist):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(scene)
    boss_target(scene,c.settings.ocr_confidence)
    action=dict(action='advance_boss_intro',status='pending',before=str(c.evidence(scene,'currency_boss_intro')))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_advance_boss(scene)
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
            current=read_match(after,c.settings.ocr_confidence)
            if current and current.page in ('preparation','shop') and current.node:
                action.update(status='verified',next_node=current.node,
                              after=str(c.evidence(after,'currency_boss_intro_after')))
                data.update(action_status='boss_intro_verified',screenshot=action['after'])
                persist()
                return True
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    action['status']='unknown'
    data['action_status']='unknown'
    persist()
    return False
