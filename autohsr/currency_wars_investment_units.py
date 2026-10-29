"""Investment role grants: immutable origin, fresh full roster and actual gains."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import re

from .currency_wars_character_rewards import _roster,require_roster
from .currency_wars_collector import collected_snapshot,first_unit_probe,roster_cells
from .currency_wars_equipment_catalog import inventory,inventory_counts
from .currency_wars_match import read_match,unit_name
from .models import AutomationError


def parse(value):
    if m:=re.fullmatch(r'获得([1-9])个随机([1-4])星([1-5])费角色',value):
        count,star,tier=map(int,m.groups());names=''
    elif m:=re.fullmatch(r'获得([1-9])个([1-4])星([1-5])费【([\u4e00-\u9fff]{1,20})】角色',value):
        count,star,tier=map(int,m.groups()[:3]);names=unit_name(m[4])
    elif m:=re.fullmatch(r'敌方目标被消灭后【借力球】的伤害分摊比例永久提高([0-9]{1,2}(?:\.[0-9]{1,2})?|100)%获得【黑塔】和【缇宝】',value):
        amount=int(Decimal(m[1])*100)
        if not 0<amount<=10000:return None,(),None
        # The visible sentence declares identities, not a gift star tier.
        return 'unit_gift',(('count',2),('star',0),('tier',0),('names','黑塔|缇宝'),
                            ('spillover_basis_points',amount)),90+amount/100
    else:return None,(),None
    return 'unit_gift',(('count',count),('star',star),('tier',tier),('names',names)),60+count*(star*8+tier*2)


def digest(value):
    from .currency_wars_investment_policy import digest as compute
    return compute(value)


def baseline(session):
    """No unobserved intervening action can stand in for a pre-grant roster."""
    from .currency_wars_standard_investment import _origin
    actions=session['actions'];index=session['investment']['origin_action_id']
    _origin(actions,index);start=actions[index]['target'][1]
    if index!=start+2:raise AutomationError('赠送角色缺少直接相邻的出战、继续与位面来源。')
    action=actions[start];basis=action.get('reward_basis',{});snapshot=basis.get('snapshot',{})
    units=require_roster(snapshot)
    if any(not u.get('traits') or not u.get('eligible_zones') for u in units):
        raise AutomationError('赠送角色的原阵容羁绊或适配位置未读全。')
    if (not action.get('before') or not action.get('after') or basis.get('node')!=action['target'][0]
            or snapshot.get('node')!=basis['node'] or snapshot.get('mode')!='standard'
            or snapshot.get('roster_complete') is not True
            or snapshot.get('rank')!=8 or snapshot.get('wealth')!=40
            or snapshot.get('game_version')!='4.6' or snapshot.get('rules_version')!='4.6'
            or type(basis.get('input_epoch')) is not int or basis['input_epoch']!=action.get('input_epoch')
            or snapshot.get('input_epoch')!=basis['input_epoch']
            or not isinstance(basis.get('run_dir'),str) or not basis['run_dir']
            or not isinstance(basis.get('inventory'),dict) or any(type(n) is not int or n<0 for n in basis['inventory'].values())
            or not isinstance(basis.get('cells'),dict) or len(basis['cells'])!=19
            or any(v[0] not in ('occupied','empty') for v in basis['cells'].values())):
        raise AutomationError('赠送角色缺少原出战前完整阵容、装备与库存来源。')
    cells=basis['cells'];keys={zone+':'+str(slot) for zone,maximum in (('front',4),('back',6),('bench',9)) for slot in range(1,maximum+1)}
    if (set(cells)!=keys or any(not isinstance(v,(list,tuple)) or len(v)!=2 or not re.fullmatch('[0-9a-f]{64}',v[1]) for v in cells.values())
            or {(u['zone']+':'+str(u['slot'])) for u in _roster(units)}!={key for key,v in cells.items() if v[0]=='occupied'}):
        raise AutomationError('赠送角色的原始十九格与完整阵容不一致。')
    return dict(start_action_id=start,basis=deepcopy(basis))


def eligible(option,session):
    if option.kind!='unit_gift':return True
    try:
        source=baseline(session);params=dict(option.parameters)
        free=sum(k.startswith('bench:') and v[0]=='empty' for k,v in source['basis']['cells'].items())
        return free>=params['count']
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False


def begin(session,choice,scene,confidence):
    data=session['investment'];claim=session['actions'][-1];source=baseline(session)
    if digest(source)!=choice.payload[8]:raise AutomationError('角色赠送的原始阵容来源已变化。')
    claim['investment_effect']['unit_delivery']=dict(origin=source,
        inventory_after=dict(inventory_counts(inventory(scene,confidence))))
    data['status']='unit_verifying'


def board_ready(scene,session,confidence=.65):
    data=session['investment'];claim=session['actions'][data['claim_action_id']]
    effect=claim['investment_effect'];state=read_match(scene,confidence)
    if not state or state.page!='preparation':return False
    board=[state.node,state.gold,state.hp,state.level,list(state.experience) if state.experience else None,
           list(state.deployment) if state.deployment else None]
    return (board==effect['board'] and inventory_counts(inventory(scene,confidence))==Counter(effect['unit_delivery']['inventory_after'])
        and all(c.state in ('occupied','empty') for c in roster_cells(scene,confidence)))


def action(scene,session,confidence):
    from .currency_wars_standard_investment import _claim
    from .currency_wars_standard_ledger import ledger_status
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars import observe
    claim=_claim(session);collection=session.get('collection',{});client=session.get('client',{})
    if (session.get('account_verified_run')!=collection.get('run_dir')
            or session.get('account_verified_epoch')!=collection.get('input_epoch')
            or client.get('verified_run')!=collection.get('run_dir') or client.get('input_epoch')!=collection.get('input_epoch')
            or client.get('version')!='4.6' or session.get('rules_version')!='4.6'
            or ledger_status(session['actions'],investment_projection=claim['id'])!='clear'):
        raise AutomationError('角色赠送核验缺少当前账号、版本或清晰的其他动作。')
    if observe(scene,confidence).page_kind=='character':return None
    if not board_ready(scene,session,confidence):raise AutomationError('角色赠送返回后的节点、资源或库存已变化，未继续交易。')
    probe=first_unit_probe(scene,confidence,collection.get('units'),session=session)
    if probe is None:raise AutomationError('角色赠送仍缺少完整的实际到账回执，未继续。')
    cell,target=probe
    return StandardAction('inspect_standard_unit','character',target,payload=(cell.zone,cell.slot,cell.node,cell.signature))


def _gains(before,after,params,bank_before,bank_after):
    old=_roster(before);new=_roster(after)
    if any(not u['traits'] or not u['eligible_zones'] for u in old+new):return None
    identity=lambda u:(u['name'],u['tier'],tuple(u['traits'] or ()),tuple(u['eligible_zones'] or ()))
    names=set(u['name'] for u in old+new);deltas={}
    for name in names:
        a=[u for u in old if u['name']==name];b=[u for u in new if u['name']==name]
        delta=sum(3**(u['star']-1) for u in b)-sum(3**(u['star']-1) for u in a)
        if delta<0:return None
        if delta==0:
            if a!=b:return None
            continue
        if len({identity(u) for u in a+b})!=1:return None
        if any(u['star']==4 for u in a+b):
            # Four-star grants are observed directly, never inferred by a
            # supposed three-to-four-star merge rule.
            if params['star']!=4 or any(u not in b for u in a) or any(u['star']!=4 for u in b if u not in a):return None
        if params['tier'] and any(u['tier']!=params['tier'] for u in b):return None
        for unit in a:
            if unit['zone']=='bench':continue
            current=next((u for u in b if (u['zone'],u['slot'])==(unit['zone'],unit['slot'])),None)
            if not current or current['star']<unit['star'] or Counter(unit['equipment'])-Counter(current['equipment']):return None
        deltas[name]=delta
    wanted=params['names'].split('|') if params['names'] else []
    if wanted and set(deltas)!=set(wanted):return None
    if params['star']:
        mass=3**(params['star']-1)
        if any(n%mass for n in deltas.values()) or sum(deltas.values())!=params['count']*mass:return None
    elif len(wanted)!=params['count'] or any(n not in (1,3,9,27) for n in deltas.values()):return None
    # Merges may return old gear to the bank; they cannot create or lose gear.
    stock=lambda units,bank:Counter(bank)+Counter(g for u in units for g in u['equipment'])
    if stock(old,bank_before)!=stock(new,bank_after):return None
    return dict(sorted(deltas.items()))


def verify(session,scene,epoch,confidence=.65):
    data=session.get('investment',{})
    if data.get('status')!='unit_verifying' or not session.get('collection',{}).get('complete'):return None
    from .currency_wars_standard_investment import _claim
    _claim(session)
    if not board_ready(scene,session,confidence):return '投资赠送角色核验时的资源或库存已变，原确认不重放。'
    snapshot=collected_snapshot(scene,session,epoch,'investment_units_delivered',confidence)
    if not snapshot.roster_complete:return None
    if any(u.equipment is None for u in snapshot.roster):
        data['observation_pending']='投资赠送后的角色装备尚未读全，未当空装备。';return None
    claim=session['actions'][data['claim_action_id']];result=claim['investment_effect']['unit_delivery']
    result['roster_after']=_roster([asdict(u) for u in snapshot.roster])
    result['verification_action_id']=len(session['actions'])-1
    result['profiles']=[]
    for u in snapshot.roster:
        r=session['collection']['units'][u.zone+':'+str(u.slot)]
        result['profiles'].append(dict(zone=u.zone,slot=u.slot,inspection_action_id=r.get('inspection_action_id'),
            close_action_id=r.get('collection_close_action_id'),signature=r['signature'],source=r['source'],
            run_dir=r['run_dir'],input_epoch=r['input_epoch']))
    result['base_copy_gains']=_gains(result['origin']['basis']['snapshot']['roster'],result['roster_after'],
        claim['investment_effect']['parameters'],result['origin']['basis']['inventory'],result['inventory_after'])
    if not valid(claim,session['actions'],require_complete=True):
        data['status']='unit_mismatch';return '投资赠送的角色、星级、费用、装备或来源未对应到账，未继续或重放。'
    data.pop('observation_pending',None)
    from .currency_wars_standard_investment import _finish
    _finish(session);return None


def valid(claim,actions,*,require_complete=False):
    try:
        target=claim['target'];delivery=claim['investment_effect']['unit_delivery'];params=claim['investment_effect']['parameters']
        prior=dict(actions=actions,investment=dict(origin_action_id=target[1]))
        if (type(claim.get('id')) is not int or not 0<=claim['id']<len(actions) or actions[claim['id']]!=claim
                or len(target)!=9 or digest(baseline(prior))!=target[8] or digest(delivery['origin'])!=target[8]
                or any(type(n) is not int or n<0 for n in delivery['inventory_after'].values())):return False
        if not (require_complete or claim.get('investment_verified') is True):return True
        old=delivery['origin']['basis']['snapshot']['roster'];new=_roster(delivery['roster_after'])
        gains=_gains(old,new,params,delivery['origin']['basis']['inventory'],delivery['inventory_after'])
        if not gains or gains!=delivery['base_copy_gains']:return False
        end=delivery['verification_action_id'];start=claim['id'];proofs=delivery['profiles']
        allowed={'inspect_standard_unit','close_standard_unit','close_standard_stale_unit','open_standard_equipment_recommendations'}
        if (type(end) is not int or not start<end<len(actions)
                or any(a.get('action') not in allowed or a.get('status')!='verified' or not a.get('before') or not a.get('after')
                       for a in actions[start+1:end+1])
                or len(proofs)!=len(new) or {(p['zone'],p['slot']) for p in proofs}!={(u['zone'],u['slot']) for u in new}):return False
        if len({(p['run_dir'],p['input_epoch']) for p in proofs})!=1:return False
        for proof in proofs:
            i,j=proof['inspection_action_id'],proof['close_action_id']
            if type(i) is not int or type(j) is not int or not start<i<j<=end:return False
            inspection,close=actions[i],actions[j];signature=inspection['target'][3]
            unit=next(u for u in new if (u['zone'],u['slot'])==(proof['zone'],proof['slot']))
            expected=claim['investment_effect']['board'];observed=inspection['collection_basis']
            if (inspection.get('action')!='inspect_standard_unit' or close.get('action')!='close_standard_unit'
                    or inspection['target']!=[proof['zone'],proof['slot'],target[0],signature]
                    or close['target']!=[target[0],proof['zone'],proof['slot'],signature,i]
                    or inspection.get('input_epoch')!=proof['input_epoch'] or close.get('input_epoch')!=proof['input_epoch']
                    or type(proof['input_epoch']) is not int or not proof.get('run_dir')
                    or inspection.get('inspection_run_dir')!=proof['run_dir']
                    or close['collection_receipt']['source']!=close['after']
                    or close['collection_receipt']['signature']!=proof['signature']
                    or digest([observed[k] for k in ('node','gold','hp','level','experience','deployment')])!=digest(expected)
                    or digest(close['collection_receipt']['basis'])!=digest(inspection['collection_basis'])
                    or close['collection_read']['source']!=proof['source'] or not proof['source']
                    or _roster([close['collection_read']['unit']])!=[unit]
                    or any(a.get('action')!='open_standard_equipment_recommendations' or a.get('input_epoch')!=proof['input_epoch']
                           or a.get('target',[])[:2]!=[proof['zone'],proof['slot']] for a in actions[i+1:j])):return False
        return True
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError,StopIteration):return False
