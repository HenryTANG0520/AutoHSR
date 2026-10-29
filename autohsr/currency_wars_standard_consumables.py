"""One observed owned tool use, followed by stock and complete-roster proof.

March7th references: equip_aglaea and equip_seele. Provenance and GPL license:
assets/upstream/March7thAssistant/source.json. Inputs use native Context.
"""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import re

from .currency_wars import observe
from .currency_wars_collector import collected_snapshot,first_unit_probe,owned_profile,roster_cells
from .currency_wars_consumables import TOOLS,EFFECTS,stock,counts
from .currency_wars_equipment_catalog import BASICS,GEAR,NAMES
from .currency_wars_match import read_match
from .currency_wars_prepare import trusted
from .currency_wars_standard_hud import experience_observed
from .models import AutomationError,Token,normalize

POLICY='standard-consumables-v1'
STAGE='stage_standard_consumable'
SELECT='choose_standard_consumable_gear'
PENDING='consumable_identity_pending'
MAX_NODE_USES=12


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def canonical(units):
    from .currency_wars_character_rewards import _roster
    return _roster(units)


def wanted(strategy,unit,bank):
    worn=Counter(unit.equipment or ())
    available=worn+Counter(bank)
    if strategy=='aglaea':
        return tuple((['boots'] if available['shoe']+2*available['boots']<4 else [])+
                     (['propeller'] if available['propeller']<1 else []))
    return tuple((['firestorm'] if available['firestorm']<2 else [])+(['chainsaw'] if available['chainsaw']<1 else []))


def proposal(scene,session,confidence=.65):
    from .currency_wars_standard_trading import _scope
    from .currency_wars_standard_equipment import EquipmentPlan,resulting_gear
    from .currency_wars_standard_flow import StandardAction
    if session.get('strategy') not in ('aglaea','seele'):return None
    prior=_scope(session,STAGE)
    snapshot=collected_snapshot(scene,prior,prior['collection']['input_epoch'],'consumable_origin',confidence)
    if (snapshot.mode!='standard' or snapshot.game_version!='4.6' or snapshot.rules_version!='4.6'
            or not snapshot.roster_complete or not experience_observed(scene,snapshot,confidence)):
        raise AutomationError('消耗品缺少本局、版本、完整持有阵容或经验来源。')
    from .currency_wars_character_rewards import require_roster
    require_roster(asdict(snapshot))
    core_name='阿格莱雅' if prior['strategy']=='aglaea' else '希儿'
    core=next((u for u in snapshot.roster if u.name==core_name and u.zone!='bench'),None)
    if core is None:return None
    used=sum(a.get('action')==STAGE and a.get('status')=='verified' and a.get('target',[None])[0]==snapshot.node for a in prior['actions'])
    if used>=MAX_NODE_USES:return None
    cells=stock(scene,confidence);bank=counts(cells)
    tools=[c for c in cells if c.name in TOOLS and (type(c.quantity) is int and c.quantity>0 or c.quantity=='infinite')]
    if not tools:return None
    by_name={name:sorted((c for c in tools if c.name==name),key=lambda c:c.slot) for name in TOOLS}
    source=target=None
    free=any(c.zone=='bench' and c.state=='empty' for c in roster_cells(scene,confidence))
    if core.star<3 and free:
        ordinary=by_name['projector'] if all(u.star<=3 for u in snapshot.roster if u.name==core.name) else []
        source=next(iter(by_name['projector2']+ordinary),None)
    desired=wanted(prior['strategy'],core,bank)
    if source is None and core.equipment:
        incoming=[name for name in wanted(prior['strategy'],core,Counter()) if bank[name]]
        recipes=prior['collection']['units'][core.zone+':'+str(core.slot)].get('equipment_recipes',())
        blocked=any(resulting_gear(core.equipment,name,recipes) is None for name in incoming)
        speed=Counter(core.equipment)['shoe']+2*Counter(core.equipment)['boots']
        if blocked or prior['strategy']=='aglaea' and speed==3 and bank['boots']:
            source=next(iter(by_name['wrench2']+by_name['wrench']),None)
    if source is None and desired:source=next(iter(by_name['token']),None)
    if source is None and desired and by_name['stove']:
        preserve={'shoe'} if prior['strategy']=='aglaea' else {'shoe','knife','star'}
        target=next((c for c in cells if c.slot<12 and c.name in BASICS-preserve),None)
        if target:source=by_name['stove'][0]
    if source is None:return None
    role=next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==(core.zone,core.slot))
    target=target or role
    target_point=target.point
    target_kind=target.name if EFFECTS[source.name]=='reroll' else core.name
    target_id=target.slot
    payload=(snapshot.node,snapshot.gold,snapshot.hp,snapshot.level,source.name,source.slot,source.quantity,source.signature,
             'inventory' if EFFECTS[source.name]=='reroll' else core.zone,target_id,target_kind,target.signature,digest(dict(bank)))
    return StandardAction(STAGE,'standard_consumable_applied',EquipmentPlan(source.point,target_point,
        'inventory' if EFFECTS[source.name]=='reroll' else core.zone,target_id,source.slot),
        details=(source.name,EFFECTS[source.name],core.name,POLICY),payload=payload)


def bind_intent(session,choice,scene,confidence=.65):
    from .currency_wars_standard_trading import _scope
    prior=_scope(session,STAGE)
    snapshot=collected_snapshot(scene,prior,prior['collection']['input_epoch'],'consumable_origin',confidence)
    bank=dict(counts(stock(scene,confidence)))
    if digest(bank)!=choice.payload[12]:raise AutomationError('消耗品意图与当前库存不符。')
    source=next(c for c in stock(scene,confidence) if c.slot==choice.payload[5])
    if (source.name,source.quantity,source.signature)!=(choice.payload[4],choice.payload[6],choice.payload[7]):
        raise AutomationError('消耗品来源图标、数量或签名不符。')
    origin=dict(status='prepared',action_id=session['actions'][-1]['id'],target=list(choice.payload),
                before=json.loads(json.dumps(asdict(snapshot))),stock_before=bank,
                count_mode=source.quantity_source,
                run_dir=prior['collection']['run_dir'],input_epoch=prior['collection']['input_epoch'],
                strategy=prior['strategy'],records=json.loads(json.dumps(prior['collection']['units'])))
    session['actions'][-1]['consumable_origin']=origin
    session['actions'][-1]['consumable_verified']=False
    session['consumable']=json.loads(json.dumps(origin))


def _data(session):
    data=session.get('consumable')
    if not data or data.get('status')=='verified':return None
    index=data.get('action_id');actions=session.get('actions',[])
    if (data.get('status') not in ('prepared','awaiting','verifying') or type(index) is not int
            or not 0<=index<len(actions) or actions[index].get('action')!=STAGE
            or actions[index].get('target')!=data.get('target') or actions[index].get('status')!='verified'):
        raise AutomationError('上次消耗品结果未核实，未重复使用或继续交易。')
    return data


def spent(data):
    result=Counter(data['stock_before'])
    if data['target'][6]!='infinite':result[data['target'][4]]-=1
    return +result


def _board(scene,data,confidence=.65):
    state=read_match(scene,confidence)
    before=data['before']
    return bool(state and state.page=='preparation' and experience_observed(scene,state,confidence)
                and (state.node,state.gold,state.hp,state.level,state.experience)==
                    (before['node'],before['gold'],before['hp'],before['level'],tuple(before['experience']) if before['experience'] is not None else None)
                and state.deployment and state.deployment[1]==before['capacity'])


def options(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='token_selection':raise AutomationError('当前不是好运令牌选择页。')
    names=sorted((t for t in trusted(scene,confidence).tokens if t.within((.25,.22,.90,.30))
                  and re.fullmatch(r'[\u4e00-\u9ffa-z0-9]{2,24}',normalize(t.text))),key=lambda t:t.center[0])
    if (len(names)!=4 or len({normalize(t.text) for t in names})!=4
            or any(names[i].center[0]-names[i-1].center[0]<.1 for i in range(1,4))):
        raise AutomationError('令牌四件进阶装备未完整对应，未默认第一项。')
    return tuple((next((k for k,v in NAMES.items() if k in GEAR-BASICS and normalize(v)==normalize(t.text)),
                       'unknown:'+normalize(t.text)),t) for t in names)


def active_action(scene,session,confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    raw=session.get('consumable',{})
    pending=session.get('rederiving_action') or {}
    if raw.get('status')=='prepared' and pending.get('action')==STAGE and pending.get('id')==raw.get('action_id'):
        return None
    data=_data(session)
    if data is None:return None
    if data['status']=='awaiting':
        candidates=options(scene,confidence)
        state=read_match(scene,confidence,include_rewards=True)
        if (not state or state.node!=data['before']['node'] or state.gold not in (None,data['before']['gold'])
                or digest([n for n,t in candidates])!=data.get('options_digest')):
            raise AutomationError('令牌选择的来源节点、余额或完整候选已变。')
        unit=dict(next(u for u in data['before']['roster'] if (u['zone'],u['slot'])==tuple(data['target'][8:10])))
        from .currency_wars_state import UnitState
        for key in ('traits','equipment','eligible_zones'):
            if unit.get(key) is not None:unit[key]=tuple(unit[key])
        preferred=wanted(data['strategy'],UnitState(**unit),data['stock_before'])
        choices=[(preferred.index(name),name,token) for name,token in candidates if name in preferred]
        if not choices:raise AutomationError('令牌当前候选没有缺少的策略装备，未默认第一项。')
        _,name,target=min(choices,key=lambda c:c[:2])
        return StandardAction(SELECT,'standard_consumable_returned',target,
                              payload=(data['before']['node'],data['action_id'],name,digest([n for n,t in candidates])))
    state=read_match(scene,confidence)
    if state and state.page=='character':
        stale=panel_stale(session)
        profile=owned_profile(scene,session.get('inspecting'),confidence) if not stale else None
        if profile:
            record=session['collection']['units'].get(profile.zone+':'+str(profile.slot),{})
            if record.get('unit')!=asdict(profile):raise AutomationError('消耗品角色尚未记入本次重采。')
            if profile.zone!='bench' and 'recommendations' not in record:
                from .currency_wars_navigation import unique
                return StandardAction('open_standard_consumable_recommendations','standard_equipment_recommendations',
                    unique(trusted(scene,confidence),'装备推荐',(.72,.70,.85,.80)),payload=(profile.zone,profile.slot,profile.name,record['signature']))
        return StandardAction('close_standard_consumable_stale_panel' if stale else 'close_standard_consumable_unit',
                              'standard_consumable_board',Token('关闭消耗品角色核验',1.,(.49,.49,.51,.51)))
    if not board_ready(scene,data,confidence):raise AutomationError('消耗品重采期间节点、库存或资源已变。')
    probe=first_unit_probe(scene,confidence,session.get('collection',{}).get('units'),session=session)
    if probe is None:raise AutomationError(data.get('observation_pending') or '消耗品角色已重采，仍未核实预期结果。')
    cell,target=probe
    return StandardAction('inspect_standard_consumable_unit','character',target,payload=(cell.zone,cell.slot,cell.node,cell.signature,data['action_id']))


def feedback(choice,before,after,session,confidence=.65):
    raw=session.get('consumable',{})
    if not raw:return False
    if choice.intent==STAGE and EFFECTS[choice.payload[4]]=='choice':
        state=read_match(after,confidence,include_rewards=True)
        try:return bool(state and state.node==choice.payload[0] and state.gold in (None,choice.payload[1]) and options(after,confidence))
        except AutomationError:return False
    if not _board(after,raw,confidence):return False
    actual=counts(stock(after,confidence));expected=spent(raw);effect=EFFECTS[raw['target'][4]]
    if effect=='remove':
        unit=next(u for u in raw['before']['roster'] if (u['zone'],u['slot'])==tuple(raw['target'][8:10]))
        expected.update(unit['equipment'])
    elif effect=='reroll':
        expected[raw['target'][10]]-=1;expected=+expected
        extra=actual-expected
        return not expected-actual and sum(extra.values())==1 and all(k in BASICS and k!=raw['target'][10] for k in extra)
    elif effect=='choice':
        if choice.intent!=SELECT:return False
        expected[choice.payload[2]]+=1
    return actual==expected


def applied(session,choice,scene,confidence=.65):
    data=session['consumable']
    if choice.intent==STAGE and EFFECTS[data['target'][4]]=='choice':
        data.update(status='awaiting',options_digest=digest([n for n,t in options(scene,confidence)]))
        session['actions'][data['action_id']]['consumable_options_digest']=data['options_digest']
        return
    state=read_match(scene,confidence)
    data.update(status='verifying',after_stock=dict(counts(stock(scene,confidence))),
                after_board=[state.node,state.gold,state.hp,state.level,state.experience,list(state.deployment)])
    if choice.intent==SELECT:data['selected_item']=choice.payload[2]
    if EFFECTS[data['target'][4]]=='reroll':
        base=spent(data);base[data['target'][10]]-=1
        data['selected_item']=next(iter(Counter(data['after_stock'])-(+base)))
    session.pop('collection',None)
    session['actions'][data['action_id']]['consumable_effect']=dict(stock_after=data['after_stock'],selected_item=data.get('selected_item'))
    session['actions'][data['action_id']]['consumable_effect']['quantity_used']=0 if data['target'][6]=='infinite' else 1


def board_ready(scene,data,confidence=.65):
    state=read_match(scene,confidence)
    return bool(_board(scene,data,confidence) and counts(stock(scene,confidence))==Counter(data.get('after_stock',{}))
                and state.deployment and list(state.deployment)==data['after_board'][5])


def panel_stale(session):
    data=session.get('consumable',{});inspecting=session.get('inspecting',{})
    if data.get('status')!='verifying':return False
    try:
        index=inspecting['inspection_action_id'];actions=session['actions'];action=actions[index]
        if (inspecting.get('consumable_id')!=data.get('action_id')
                or inspecting.get('input_epoch')!=session.get('account_verified_epoch')
                or inspecting.get('run_dir')!=session.get('account_verified_run')
                or action.get('id')!=index or action.get('action')!='inspect_standard_consumable_unit'
                or action.get('status')!='verified' or action.get('input_epoch')!=inspecting['input_epoch']
                or action.get('inspection_run_dir')!=inspecting['run_dir']
                or action.get('before')!=inspecting.get('before') or action.get('after')!=inspecting.get('after')
                or action.get('target')!=[inspecting['zone'],inspecting['slot'],inspecting['node'],inspecting['signature'],data['action_id']]):return True
        children=actions[index+1:]
        return len(children)>1 or any(c.get('action')!='open_standard_consumable_recommendations'
            or c.get('status')!='verified' or c.get('input_epoch')!=inspecting['input_epoch']
            or c.get('target',[])[:2]!=[inspecting['zone'],inspecting['slot']]
            or c.get('target',[None]*4)[3]!=inspecting['signature'] for c in children)
    except (KeyError,IndexError,TypeError):return True


def verify(session,scene,epoch,confidence=.65):
    data=session.get('consumable',{})
    if data.get('status')!='verifying' or not session.get('collection',{}).get('complete'):return None
    if not board_ready(scene,data,confidence):return '消耗品返回后的资源或库存已变，原使用记录保留。'
    snapshot=collected_snapshot(scene,session,epoch,'consumable_delivered',confidence)
    if not snapshot.roster_complete:return None
    if any(u.equipment is None for u in snapshot.roster):
        data['observation_pending']='消耗品后的角色装备未知，未当空装备或重发使用。';return None
    effect=session['actions'][data['action_id']]['consumable_effect']
    effect['roster_after']=canonical([asdict(u) for u in snapshot.roster])
    effect['verification_action_id']=session['actions'][-1]['id']
    effect['profile_proofs']=[dict(zone=u.zone,slot=u.slot,
        inspection_action_id=session['collection']['units'][u.zone+':'+str(u.slot)].get('inspection_action_id'),
        signature=session['collection']['units'][u.zone+':'+str(u.slot)]['signature'],
        source=session['collection']['units'][u.zone+':'+str(u.slot)]['source'],
        run_dir=session['collection']['run_dir'],input_epoch=epoch) for u in snapshot.roster]
    if not valid_effect(session['actions'][data['action_id']],session['actions'],require_complete=True):
        data['status']='mismatch';return '消耗品的实际角色、装备或物品结果不符，未重发。'
    data['status']='verified'
    session['actions'][data['action_id']]['consumable_verified']=True
    session.setdefault('consumable_history',[]).append(json.loads(json.dumps(data)))
    session['action_status']='consumable_verified'
    return None


def valid_effect(action,actions,*,require_complete=False):
    try:
        target=action['target'];origin=action['consumable_origin'];effect=action.get('consumable_effect',{})
        if (len(target)!=13 or action.get('action')!=STAGE or type(action.get('id')) is not int
                or not 0<=action['id']<len(actions) or actions[action['id']]!=action
                or origin.get('target')!=target or origin.get('action_id')!=action['id']
                or target[4] not in TOOLS or digest(origin['stock_before'])!=target[12]
                or not action.get('before') or not action.get('after') or origin['before']['node']!=target[0]
                or any(type(n) is not int for n in target[1:4]) or not 0<=target[1]<=99999 or not 0<target[2]<=100 or not 1<=target[3]<=10
                or type(target[5]) is not int or not 0<=target[5]<=13
                or not (type(target[6]) is int and 1<=target[6]<=99 or target[6]=='infinite')
                or any(not isinstance(target[i],str) or not re.fullmatch('[0-9a-f]{64}',target[i]) for i in (7,11,12))
                or target[8] not in ('front','back','inventory') or type(target[9]) is not int
                or not 0<=target[9]<=dict(front=4,back=6,inventory=13)[target[8]]
                or target[8]!='inventory' and target[9]<1
                or not isinstance(target[0],str) or not re.fullmatch(r'[1-3]-[1-9][0-9]?',target[0])
                or [origin['before'][k] for k in ('node','gold','hp','level')]!=target[:4]
                or origin['before'].get('roster_complete') is not True or origin['before'].get('mode')!='standard'
                or origin['before'].get('game_version')!='4.6' or origin['before'].get('rules_version')!='4.6'
                or type(action.get('input_epoch')) is not int or action['input_epoch']<0 or action['input_epoch']!=origin.get('input_epoch')
                or not isinstance(origin.get('run_dir'),str) or not origin['run_dir']
                or origin.get('strategy') not in ('aglaea','seele')
                or any(type(v) is not int or v<0 for v in origin['stock_before'].values())):return False
        old=canonical(origin['before']['roster']);kind=EFFECTS[target[4]]
        if kind=='reroll':
            if target[8]!='inventory' or target[9]>=12 or target[10] not in BASICS or not origin['stock_before'].get(target[10]):return False
        else:
            if target[8]=='inventory':return False
            unit=next(u for u in old if (u['zone'],u['slot'])==tuple(target[8:10]))
            if unit['name']!=target[10] or unit['name']!=dict(aglaea='阿格莱雅',seele='希儿')[origin['strategy']]:return False
        mode=origin.get('count_mode')
        if (mode not in ('visible_counter','single_cell','infinity')
                or mode=='single_cell' and (target[5]>=12 or target[6]!=1)
                or (mode=='infinity')!=(target[6]=='infinite')):return False
        if target[6]=='infinite':
            if origin['stock_before'].get(target[4]+':infinite',0)<1:return False
        elif origin['stock_before'].get(target[4],0)<target[6]:return False
        if not (action.get('consumable_verified') is True or require_complete):return True
        if effect.get('quantity_used')!=(0 if target[6]=='infinite' else 1):return False
        end=effect['verification_action_id']
        allowed={'inspect_standard_consumable_unit','close_standard_consumable_unit','close_standard_consumable_stale_panel',
                 'open_standard_consumable_recommendations',SELECT}
        if (type(end) is not int or not action['id']<=end<len(actions)
                or any(a.get('action') not in allowed or a.get('status')!='verified' or not a.get('before') or not a.get('after')
                       for a in actions[action['id']+1:end+1])):return False
        if any(type(v) is not int or v<0 for v in effect['stock_after'].values()):return False
        new=canonical(effect['roster_after'])
        proofs=effect['profile_proofs']
        if (not isinstance(proofs,list) or len(proofs)!=len(new)
                or {(p['zone'],p['slot']) for p in proofs}!={(u['zone'],u['slot']) for u in new}):return False
        for proof in proofs:
            index=proof['inspection_action_id']
            if type(index) is not int or not action['id']<index<=end:return False
            inspection=actions[index]
            if (inspection.get('action')!='inspect_standard_consumable_unit' or inspection.get('status')!='verified'
                    or inspection.get('input_epoch')!=proof['input_epoch'] or inspection.get('inspection_run_dir')!=proof['run_dir']
                    or inspection.get('target')!=[proof['zone'],proof['slot'],target[0],proof['signature'],action['id']]
                    or not proof.get('source')):return False
        base=spent(origin);bank=Counter(effect['stock_after'])
        if kind=='copy':
            name=target[10];a=[u for u in old if u['name']==name];b=[u for u in new if u['name']==name]
            core=next(u for u in new if (u['zone'],u['slot'])==tuple(target[8:10]))
            identity=lambda units:{digest({k:u[k] for k in ('name','tier','traits','eligible_zones')}) for u in units}
            if (sorted((u['star'] for u in b),reverse=True)<=sorted((u['star'] for u in a),reverse=True)
                    or identity(a)!=identity(b)
                    or core['name']!=name or core['tier']!=unit['tier'] or core['star']<unit['star']
                    or Counter(unit['equipment'])-Counter(core['equipment'])
                    or Counter(g for u in a for g in u['equipment'])!=Counter(g for u in b for g in u['equipment'])):return False
            if target[4]=='projector':
                if any(u['star']>3 for u in a+b) or sum(3**(u['star']-1) for u in b)-sum(3**(u['star']-1) for u in a)!=1:return False
            return bank==base and [u for u in old if u['name']!=name]==[u for u in new if u['name']!=name]
        if kind=='remove':
            unit=next(u for u in old if (u['zone'],u['slot'])==tuple(target[8:10]))
            base.update(unit['equipment']);unit['equipment']=[]
            return old==new and bank==base
        item=effect.get('selected_item')
        if kind=='reroll':
            if item not in BASICS or item==target[10]:return False
            base[target[10]]-=1;base=+base
        elif kind=='choice':
            if item not in GEAR-BASICS:return False
            claims=[a for a in actions if a.get('action')==SELECT and a.get('status')=='verified' and a.get('target',[])[:2]==[target[0],action['id']]]
            if (len(claims)!=1 or len(claims[0]['target'])!=4 or claims[0]['target'][2]!=item
                    or claims[0]['target'][3]!=action.get('consumable_options_digest')
                    or not claims[0].get('before') or not claims[0].get('after')):return False
        base[item]+=1
        return old==new and bank==base
    except (AutomationError,KeyError,TypeError,ValueError,IndexError,AttributeError,StopIteration):return False


def valid_selection(action,actions):
    try:
        target=action['target']
        if (action.get('action')!=SELECT or len(target)!=4 or type(target[1]) is not int
                or not 0<=target[1]<action['id'] or target[2] not in GEAR-BASICS
                or not action.get('before') or not action.get('after')):return False
        source=actions[target[1]]
        return (source.get('action')==STAGE and source.get('status')=='verified' and source['target'][4]=='token'
                and source['target'][0]==target[0] and source.get('consumable_options_digest')==target[3]
                and valid_effect(source,actions))
    except (KeyError,IndexError,TypeError):return False
