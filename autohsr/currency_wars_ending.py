"""Advance only the four locally observed terminal screens, one input at a time."""
import time

from .currency_wars import CurrencyWarsWorkflow,observe
from .models import AutomationError,EmptyCapture,normalize


ENDING_STEPS={
    'final_victory':(('前往结算',),'match_rating'),
    'match_rating':(('下一步',),'match_summary'),
    # The native sample OCR joins 下一页 as 下顶; only this screen accepts it.
    'match_summary':(('下一页','下顶'),'match_statistics'),
    'match_statistics':(('返回货币战争','返回货百战争'),'lobby'),
}


def ending_target(scene,confidence=.65):
    kind=observe(scene,confidence).page_kind
    if kind not in ENDING_STEPS:
        raise AutomationError('当前不是已校准的终局结算页。')
    labels,expected=ENDING_STEPS[kind]
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and
             normalize(t.text) in labels and t.within((.45,.79,.55,.87))]
    if len(targets)!=1:
        raise AutomationError('终局结算按钮不唯一或未核实。')
    return kind,expected,targets[0]


def advance_ending(c,scene,data,persist):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(scene)
    kind,expected,_=ending_target(scene,c.settings.ocr_confidence)
    if kind in ('final_victory','match_rating','match_summary'):
        data['match_victory_observed']=True
    action=dict(action='ending_'+kind,status='pending',next_page=expected,
                before=str(c.evidence(scene,'currency_ending_'+kind)))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_advance_ending(scene,kind)
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
            if observe(after,c.settings.ocr_confidence).page_kind==expected:
                action.update(status='verified',after=str(c.evidence(after,'currency_ending_'+expected+'_after')))
                data.update(action_status='ending_verified',screenshot=action['after'])
                if expected=='lobby':
                    data.update(action_status='returned_to_lobby',settlement_verified=True)
                persist()
                return True
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    action['status']='unknown'
    if c.last_scene is not None:
        action['after']=str(c.evidence(c.last_scene,'currency_ending_unknown'))
        data['screenshot']=action['after']
    data['action_status']='unknown'
    persist()
    return False
