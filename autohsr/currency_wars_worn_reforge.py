"""Role-wide reforge is a distinct target and a separately observed result.

Native 4.6 tutorials 67/68 supply the mechanic, with hashes in
assets/currency-consumables/sources.json. Unknown/special gear stays unknown.
"""
from collections import Counter
from dataclasses import asdict
import json

from .currency_wars_equipment_catalog import BASICS,GEAR
from .models import AutomationError

POLICY='worn-reforge-v1'
PROTECTED=dict(aglaea=frozenset(('shoe','boots','propeller')),
    seele=frozenset(('shoe','knife','star','firestorm','chainsaw')))


def same(left,right):
    return json.dumps(left,sort_keys=True,allow_nan=False)==json.dumps(right,sort_keys=True,allow_nan=False)


def worn_target(target):
    return isinstance(target,(list,tuple)) and len(target)==13 and target[4]=='stove' and target[8] in ('front','back')


def quality(items):
    if (not isinstance(items,(list,tuple)) or not 1<=len(items)<=3
            or any(not isinstance(item,str) or item not in GEAR for item in items)):
        raise ValueError('全身重铸需要完整已识别装备')
    return dict(Counter('basic' if item in BASICS else 'advanced' for item in items))


def eligible(strategy,unit,node,actions):
    try:quality(unit.equipment)
    except ValueError:return False
    if strategy not in PROTECTED or any(item in PROTECTED[strategy] for item in unit.equipment):return False
    for action in actions:
        target=action.get('target',[])
        if (action.get('action')=='stage_standard_consumable' and worn_target(target)
                and target[0]==node and target[10]==unit.name):return False
    return True


def bind(origin,scene,choice,confidence=.65):
    from .currency_wars_collector import roster_cells
    target=choice.payload
    unit=next(u for u in origin['before']['roster'] if (u['zone'],u['slot'])==tuple(target[8:10]))
    cell=next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==tuple(target[8:10]))
    origin['worn_reforge']=dict(policy=POLICY,equipment_before=list(unit['equipment']),
        quality_before=quality(unit['equipment']),source=[cell.zone,cell.slot,cell.signature])
    if not valid_origin(origin,target):raise AutomationError('全身重铸的原穿戴、品质或目标来源未核实。')


def valid_origin(origin,target):
    try:
        if not worn_target(target):return False
        unit=next(u for u in origin['before']['roster'] if (u['zone'],u['slot'])==tuple(target[8:10]))
        data=origin['worn_reforge'];strategy=origin['strategy']
        return (strategy in PROTECTED and unit['name']==target[10]==dict(aglaea='阿格莱雅',seele='希儿')[strategy]
            and data['policy']==POLICY and same(data['equipment_before'],unit['equipment'])
            and same(data['quality_before'],quality(unit['equipment']))
            and not any(item in PROTECTED[strategy] for item in unit['equipment'])
            and same(data['source'],[target[8],target[9],target[11]]))
    except (KeyError,IndexError,TypeError,ValueError,StopIteration):return False


def record_profile(session,unit,inspecting,source,epoch):
    data=session.get('consumable',{})
    if not worn_target(data.get('target',[])) or data.get('status')!='verifying':return None
    if (unit.zone,unit.slot)!=tuple(data['target'][8:10]):return None
    from .currency_wars_standard_consumables import panel_stale
    if (panel_stale(session) or not source or type(epoch) is not int
            or epoch!=session.get('account_verified_epoch')):return '全身重铸面板来源已失效，未发布穿戴结果。'
    session['actions'][inspecting['inspection_action_id']]['worn_reforge_profile']=dict(
        unit=json.loads(json.dumps(asdict(unit))),source=source,run_dir=inspecting['run_dir'],input_epoch=epoch)
    return None


def valid_prefix(action,actions):
    target=action['target']
    return (valid_origin(action['consumable_origin'],target)
        and not any(a.get('action')=='stage_standard_consumable' and worn_target(a.get('target',[]))
            and a['target'][0]==target[0] and a['target'][10]==target[10] for a in actions[:action['id']]))


def publish(effect,snapshot,target):
    unit=next(u for u in snapshot.roster if (u.zone,u.slot)==tuple(target[8:10]))
    effect['worn_after']=list(unit.equipment)


def valid_result(action,actions,old,new):
    try:
        origin=action['consumable_origin'];target=action['target'];effect=action['consumable_effect']
        if not valid_prefix(action,actions) or type(effect.get('quantity_used')) is not int:return False
        after=effect['worn_after'];before=origin['worn_reforge']['equipment_before']
        if quality(after)!=quality(before):return False
        proof=next(p for p in effect['profile_proofs'] if (p['zone'],p['slot'])==tuple(target[8:10]))
        profile=actions[proof['inspection_action_id']]['worn_reforge_profile']
        observed=profile['unit'];current=next(u for u in new if (u['zone'],u['slot'])==tuple(target[8:10]))
        from .currency_wars_character_rewards import _roster
        if (not same(observed['equipment'],after) or profile['source']!=proof['source']
                or type(profile['input_epoch']) is not int
                or profile['run_dir']!=proof['run_dir'] or profile['input_epoch']!=proof['input_epoch']
                or any(type(p['input_epoch']) is not int or p['input_epoch']!=profile['input_epoch']
                    or p['run_dir']!=profile['run_dir'] for p in effect['profile_proofs'])
                or not same(_roster([observed])[0],current)):return False
        changed=not same(before,after)
        if target[6]=='infinite' and not changed:return False
        if effect.get('worn_result')!=('changed_observed' if changed else 'unchanged_observed'):return False
        original=next(u for u in old if (u['zone'],u['slot'])==tuple(target[8:10]))
        original['equipment']=sorted(after)
        from .currency_wars_standard_consumables import spent
        return old==new and Counter(effect['stock_after'])==spent(origin)
    except (AutomationError,AttributeError,KeyError,IndexError,TypeError,ValueError,StopIteration):return False
