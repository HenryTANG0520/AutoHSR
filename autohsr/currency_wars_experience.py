"""One verified 4-gold experience purchase toward an explicit target level."""
import time
from .currency_wars import CurrencyWarsWorkflow
from .currency_wars_match import read_match,verify_experience
from .models import AutomationError,normalize


def target_level(scene,runner,confidence=.65):
    configured=getattr(runner,'currency_target_level',0)
    if configured:
        return configured
    if not getattr(runner,'currency_start_from_lobby',False):
        return 0
    from .currency_wars_market import overclock_board
    state=read_match(scene,confidence)
    if not state or not state.node or state.gold is None or state.gold<14 or not overclock_board(scene):
        return 0
    plane,node=map(int,state.node.split('-'))
    return (5 if node>=4 else 4) if plane==1 else 7 if plane==2 else 9


def experience_target(scene,confidence=.65):
    state=read_match(scene,confidence)
    if (state is None or state.page!='preparation' or not state.node or state.gold is None or state.gold<4
            or state.level is None or state.experience is None):
        raise AutomationError('升级需要明确备战节点、金币、等级与经验，且金币不少于4。')
    prices={normalize(t.text) for t in scene.tokens if t.score>=confidence and t.within((.153,.908,.174,.933))}
    if prices!={'4'}:
        raise AutomationError('购买经验价格未确认为4，未购买。')
    targets=[t for t in scene.tokens if t.score>=confidence and normalize(t.text)=='购买经验'
             and t.within((.1,.75,.2,.85))]
    if len(targets)!=1:
        raise AutomationError('购买经验按钮未核实。')
    return targets[0]


def buy_experience(c,before,data,persist):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(before)
    experience_target(before,c.settings.ocr_confidence)
    previous=read_match(before,c.settings.ocr_confidence)
    action=dict(action='buy_experience',status='pending',gold_before=previous.gold,
                before=str(c.evidence(before,'currency_experience_before')))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_buy_experience(before)
    elapsed=0.
    action['observations']=[]
    while True:
        started=time.monotonic()
        inactive=c.runner.inactive_duration
        after=c.snapshot()
        guard._require_current_scene(after)
        current=read_match(after,c.settings.ocr_confidence)
        status=verify_experience(previous,current) if current else 'unknown'
        path=str(c.evidence(after,'currency_experience_after'))
        action['observations'].append(dict(status=status,screenshot=path))
        if status=='verified':
            break
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        if elapsed>=8:
            break
    action.update(status=status,after=path,gold_after=current.gold if current else None)
    data.update(action_status=status,screenshot=action['after'])
    persist()
    return status=='verified'
