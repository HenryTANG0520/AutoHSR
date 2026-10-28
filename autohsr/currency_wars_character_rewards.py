"""Named-character gift choices; price, star and selection count stay separate.

March7th references: _check_hiring_book and _check_expert_invitation.
Pinned provenance and license: assets/upstream/March7thAssistant/source.json.
"""
from collections import Counter
from dataclasses import asdict
import re

from .currency_wars import observe
from .currency_wars_match import unit_name,read_match
from .currency_wars_prepare import trusted
from .currency_wars_equipment_catalog import GEAR
from .models import AutomationError,normalize


HIRING='hiring_selection'
EXPERT='expert_selection'
PREFERRED={
    'aglaea':('阿格莱雅','瓦尔特','昔涟','星期日','符玄','银狼','花火','风堇','藿藿','缇宝'),
    'seele':('希儿','瓦尔特','刻律德菈','符玄','花火','佩拉','风堇','缇宝'),
}
UNAVAILABLE=frozenset(('禁用','不可用','不可选择','已领取'))


def options(scene,kind,confidence=.65):
    clean=trusted(scene,confidence)
    if kind not in (HIRING,EXPERT) or observe(clean,confidence).page_kind!=kind:
        raise AutomationError('角色奖励选择页未核实。')
    tier=None
    if kind==HIRING:
        headers=[re.fullmatch(r'(?:([1-5])费)?聘用书',normalize(t.text)) for t in clean.tokens if t.within((.3,.02,.7,.10))]
        headers=[m for m in headers if m]
        if len(headers)!=1:raise AutomationError('聘用书种类或费用字段不唯一。')
        tier=int(headers[0][1]) if headers[0][1] else None
    names=sorted((t for t in clean.tokens if t.within((.14,.33,.90,.39))
                  and re.fullmatch(r'(?=.{1,40}$)[\u4e00-\u9fffa-z0-9·.]+',normalize(t.text))),key=lambda t:t.center[0])
    cash=[t for t in names if normalize(t.text)=='现金为王']
    if (not 1<=len(names)<=5 or len({unit_name(t.text) for t in names})!=len(names)
            or any(names[i].center[0]-names[i-1].center[0]<.10 for i in range(1,len(names)))
            or kind==EXPERT and (len(cash)!=1 or len(names)<2) or kind==HIRING and cash):
        raise AutomationError('角色候选名称、间距或现金分支未完整对应。')
    result=[]
    for slot,name in enumerate(names):
        if normalize(name.text)=='现金为王':continue
        x=name.center[0]
        traits=tuple(normalize(t.text) for t in sorted(clean.tokens,key=lambda t:(round(t.center[1],2),t.center[0]))
            if t not in names and t.within((x-.075,.25,x+.085,.335)) and normalize(t.text) not in UNAVAILABLE
            and re.fullmatch(r'[\u4e00-\u9fff]{1,14}',normalize(t.text)))
        if not 1<=len(traits)<=3:raise AutomationError('角色名字与当前羁绊字段未唯一关联。')
        unavailable=any(normalize(t.text) in UNAVAILABLE and t.within((x-.075,.15,x+.085,.43)) for t in clean.tokens)
        meta=dict(selection_count=1,expected_tier=tier,traits=list(traits),advisor_unlock_declared=kind==EXPERT,selectable=not unavailable)
        result.append((slot,unit_name(name.text),None,unit_name(name.text),0,name,meta))
    if not result:raise AutomationError('角色奖励候选为空。')
    return tuple(result)


def require_roster(snapshot):
    if not snapshot.get('roster_complete'):
        raise AutomationError('角色奖励缺少开启前完整持有阵容，未把未知当未拥有。')
    units=snapshot.get('roster',[])
    if any(type(u.get('star')) is not int or not 1<=u['star']<=4 or type(u.get('tier')) is not int or not 1<=u['tier']<=5
            or not isinstance(u.get('equipment'),(list,tuple)) or any(item not in GEAR for item in u['equipment']) for u in units):
        raise AutomationError('持有角色星级、费用或装备不完整，未把未知当空装备。')
    return units


def choose(candidates,data,strategy):
    units=require_roster(data['basis']['snapshot'])
    candidates=tuple(c for c in candidates if c[6]['selectable'])
    highest={u['name']:max(v['star'] for v in units if v['name']==u['name']) for u in units}
    if data['page']==EXPERT:
        wanted=(('银狼',) if strategy=='aglaea' else
                tuple(name for i,name in enumerate(PREFERRED.get(strategy,())) if highest.get(name,0)<3 and (i==0 or name not in highest)))
        choices=[c for c in candidates if c[1] in wanted and highest.get(c[1],0)<3]
        return min(choices,key=lambda c:(wanted.index(c[1]),c[1])) if choices else None
    if strategy not in ('default','aglaea','seele'):raise AutomationError('聘用书本局策略无效。')
    traits=Counter(t for u in units for t in u.get('traits') or ())
    preferred=PREFERRED.get(strategy,())
    def rank(c):
        name=c[1];priority=(200-preferred.index(name)*10 if name in preferred else 0) if highest.get(name,0)<3 else 0
        useful=30 if name not in highest else 15 if highest[name]<3 else 0
        synergy=sum(traits[t] for t in c[6]['traits'])
        return (-priority-useful-synergy,name)
    if not candidates:raise AutomationError('聘用书候选均明确不可选择，未点击。')
    return min(candidates,key=rank)


def _roster(units):
    """Canonical observed identities include position, cost and actual gear."""
    from .currency_wars_state import UnitState
    require_roster(dict(roster_complete=True,roster=units))
    result=[]
    for item in units:
        data=dict(item)
        for field in ('traits','equipment','eligible_zones'):
            if data.get(field) is not None:data[field]=tuple(data[field])
        unit=asdict(UnitState(**data))
        for field in ('traits','equipment','eligible_zones'):
            if unit[field] is not None:unit[field]=sorted(unit[field])
        result.append(unit)
    if len({(u['zone'],u['slot']) for u in result})!=len(result):
        raise AutomationError('顾问选择的阵容位置重复，未认定未变化。')
    return sorted(result,key=lambda u:(u['zone'],u['slot']))


def _acceptance(parent):
    """Only our verified invitation opening can settle an unchanged roster."""
    source=parent.get('reward_basis',{});target=parent.get('target',[])
    if (parent.get('status')!='verified' or not parent.get('before') or not parent.get('after')
            or not source.get('node') or not isinstance(target,(list,tuple))):return None
    kind=parent.get('action')
    if kind=='open_standard_bench_reward':
        if (len(target)!=3 or target[0]!=source['node'] or type(target[1]) is not int or not 1<=target[1]<=9
                or source.get('cells',{}).get('bench:'+str(target[1]))!=['reward',target[2]]):return None
    elif kind=='collect_standard_loot':
        if (len(target)!=3 or any(type(n) not in (int,float) for n in target)
                or not all(0<n<1 for n in target)):return None
    else:return None
    return dict(action_id=parent['id'],action=kind,target=list(target),node=source['node'])


def advisor_selection(data,units,scene,actions,confidence=.65):
    """Selection acceptance is separate from a delivered unit or a shop quote."""
    if (data.get('page')!=EXPERT or len(data.get('choice',[]))!=11
            or data['choice'][10] is not None):return None
    parent=actions[data['origin_action_id']];accepted=_acceptance(parent)
    if not accepted or accepted['node']!=data['choice'][0]:return None
    require_roster(parent['reward_basis']['snapshot'])
    before=_roster(parent['reward_basis']['snapshot']['roster'])
    after=_roster([asdict(u) for u in units])
    if before!=after:return None
    from .currency_wars_collector import roster_cells
    cells={c.zone+':'+str(c.slot):[c.state,c.signature] for c in roster_cells(scene,confidence)}
    if accepted['action']=='open_standard_bench_reward':
        if cells['bench:'+str(accepted['target'][1])][0]!='empty':return None
    protected={k:v for k,v in parent['reward_basis']['cells'].items() if v[0]=='reward'
               and k!='bench:'+str(data.get('box_slot'))}
    if any(cells[k]!=v for k,v in protected.items()):return None
    return dict(delivery_kind='advisor_selection',advisor_selection_verified=True,roster_unchanged=True,
                roster_after=after,accepted_selection=accepted,unit_verified=False)


def valid_advisor_selection(effect,target,parent):
    if (len(target)!=11 or target[2]!=EXPERT or target[10] is not None
            or effect.get('unit_verified') is not False or effect.get('advisor_selection_verified') is not True
            or effect.get('roster_unchanged') is not True or effect.get('other_roster_verified') is not True
            or effect.get('advisor_unlock_verified') is True or effect.get('purchase_verified') is True
            or effect.get('accepted_selection')!=_acceptance(parent)
            or not effect.get('accepted_selection') or not isinstance(effect.get('roster_after'),list)):
        return False
    before=_roster(parent['reward_basis']['snapshot']['roster'])
    if _roster(effect['roster_after'])!=before:return False
    selected=[u for u in before if u['name']==target[6]]
    stars=sorted((u['star'] for u in selected),reverse=True)
    gear=sorted(item for u in selected for item in u['equipment'])
    return (effect.get('stars_before')==stars and effect.get('stars_after')==stars
            and effect.get('tiers_after')==sorted(u['tier'] for u in selected)
            and effect.get('equipment_before')==gear and effect.get('equipment_after')==gear)


def observe_shop(session,scene,action,confidence=.65):
    """A visible priced quote proves availability, never a purchase."""
    if action.get('status')!='verified' or action.get('action') not in ('open_standard_shop','refresh_standard_shop'):
        return
    state=read_match(scene,confidence)
    if not state or state.page!='shop':return
    from .currency_wars_standard_rewards import valid_effect
    for source in session.get('actions',[]):
        target=source.get('target',[])
        if (source.get('action')!='choose_standard_reward' or len(target)!=11 or target[2]!=EXPERT
                or source.get('reward_verified') is not True or not valid_effect(source,session['actions'])
                or source['id']>=action['id']):continue
        for offer in state.offers:
            if offer.name!=target[6] or offer.cost is None:continue
            entry=dict(reward_action_id=source['id'],observation_action_id=action['id'],node=state.node,
                       name=offer.name,slot=offer.slot,price=offer.cost,source=action['after'])
            history=session.setdefault('advisor_shop_observations',[])
            if entry not in history:history.append(entry)
