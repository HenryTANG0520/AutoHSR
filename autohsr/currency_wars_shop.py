"""Close a fully recognized shop without buying or refreshing its offers."""
import time
from .currency_wars import CurrencyWarsWorkflow
from .currency_wars_match import read_match
from .models import AutomationError,EmptyCapture,normalize


def close_shop_target(scene,confidence=.65):
    state=read_match(scene,confidence)
    if not state or state.page!='shop' or not state.node or state.gold is None:
        raise AutomationError('商店节点和金币未核实，未收起。')
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='收起'
             and t.within((.81,.88,.89,.95))]
    if len(targets)!=1:
        raise AutomationError('商店收起按钮未核实。')
    return targets[0]


def close_shop(c,scene,data,persist):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(scene)
    close_shop_target(scene,c.settings.ocr_confidence)
    previous=read_match(scene,c.settings.ocr_confidence)
    action=dict(action='close_shop',status='pending',origin_node=previous.node,
                before=str(c.evidence(scene,'currency_close_shop_before')))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_close_shop(scene)
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
            if current and current.page=='preparation' and current.node==previous.node and current.gold==previous.gold:
                action.update(status='verified',after=str(c.evidence(after,'currency_close_shop_after')))
                data.update(action_status='shop_closed',screenshot=action['after'])
                persist()
                return True
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    action['status']='unknown'
    data['action_status']='unknown'
    persist()
    return False
