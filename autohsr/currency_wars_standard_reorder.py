"""A frozen whole-roster objective, reached through bounded verified moves.

The objective uses AutoHSR's existing baseline score, not a claim about game
balance. Positions are excluded from identity and tie breaking so moving a unit
cannot change the objective or invite a greedy move back to the old board.
"""
from dataclasses import asdict, replace
from functools import lru_cache
from itertools import combinations
import json
import re

from .currency_wars_collector import collected_snapshot, roster_cells
from .currency_wars_names import snapshot_name
from .currency_wars_standard_deployment import team_score
from .currency_wars_state import StrategySnapshot, UnitState
from .models import AutomationError

POLICY = 'whole-roster-reorder-v1'
MOVES = frozenset(('stage_standard_exchange', 'stage_standard_relocate'))


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def identity(unit):
    return (unit.name, unit.star, unit.tier, tuple(sorted(unit.traits or ())),
            tuple(sorted(unit.equipment or ())), tuple(sorted(unit.eligible_zones or ())))


def _validate(snapshot):
    if (not snapshot.roster_complete or type(snapshot.capacity) is not int or not 1 <= snapshot.capacity <= 10
            or len(snapshot.roster) > 19 or any(u.star is None or u.tier is None or u.traits is None
            or u.equipment is None or not u.eligible_zones for u in snapshot.roster)):
        raise AutomationError('全局整理需要完整角色、星级、费用、羁绊、装备与适配位置。')
    field = tuple(u for u in snapshot.roster if u.zone != 'bench')
    if (len(field) != snapshot.capacity or len({u.name for u in field}) != len(field)
            or any(u.zone not in u.eligible_zones for u in field)
            or any(u.slot>dict(front=4,back=6,bench=9)[u.zone] for u in snapshot.roster)):
        raise AutomationError('全局整理需要已核实且位置合法的满员阵容。')
    team_score(field)


@lru_cache(maxsize=32)
def _optimize(keys, capacity, strategy, alias):
    from .currency_wars_standard_policy import owned_team_preference
    units = tuple(UnitState(k[0], 'bench', i+1, k[1], k[2], k[3], k[4], k[5]) for i,k in enumerate(keys))
    base = tuple((10,30,80,160)[u.star-1]+2*u.tier+owned_team_preference(u.name,strategy,alias) for u in units)
    overlap = {(i,j):3*len(set(units[i].traits) & set(units[j].traits)) for i,j in combinations(range(len(units)),2)}
    best = None
    for indices in combinations(range(len(units)), capacity):
        team = tuple(units[i] for i in indices)
        if len({u.name for u in team}) != capacity:continue
        front = tuple(i for i in indices if units[i].eligible_zones == ('front',))
        back = tuple(i for i in indices if units[i].eligible_zones == ('back',))
        flexible = tuple(i for i in indices if len(units[i].eligible_zones) == 2)
        bonus = {i:(25 if strategy=='seele' and units[i].name=='希儿' else
                    10 if strategy=='aglaea' and units[i].name=='风堇' and all(u.name!='藿藿' for u in team) else 0) for i in indices}
        ordered = sorted(flexible,key=lambda i:(-bonus[i],keys[i]))
        common = sum(base[i] for i in indices)+sum(overlap[i,j] for i,j in combinations(indices,2))
        for count in range(max(1,len(front),capacity-6),min(4,capacity-len(back))+1):
            chosen = frozenset(front+tuple(ordered[:count-len(front)]))
            score = common+sum(bonus[i] for i in chosen)+4*(count<capacity)-4*abs(count-max(1,capacity//3))
            goal = tuple((keys[i],'front' if i in chosen else 'back') for i in indices)
            rank = (score,sum(len(u.equipment) for u in team))
            if best is None or rank>best[0] or rank==best[0] and goal<best[1]:best=(rank,goal)
    if best is None:raise AutomationError('全部持有角色无法构成合法满员阵容。')
    return best[1],best[0][0]


def optimize(snapshot, strategy='default'):
    from .currency_wars_standard_policy import STRATEGIES
    if strategy not in STRATEGIES:raise AutomationError('全局整理策略不在已实现目录内。')
    _validate(snapshot)
    return _optimize(tuple(sorted(set(identity(u) for u in snapshot.roster))),snapshot.capacity,strategy,snapshot_name(snapshot))


def distance(roster, goal):
    # A selected copy in the wrong field zone needs one move; a bench copy may
    # need an intermediate exchange before it can reach its assigned zone.
    return sum(min((0 if u.zone==zone else 1 if u.zone!='bench' else 2 for u in roster if identity(u)==unit),default=100)
               for unit,zone in goal)


def choose_step(snapshot, goal, strategy='default'):
    """Every legal step strictly decreases a position-independent potential."""
    _validate(snapshot)
    roster = snapshot.roster;field = tuple(u for u in roster if u.zone!='bench')
    before = distance(roster,goal);base=team_score(field,strategy,remembrance_name=snapshot_name(snapshot));best=None
    occupied={(u.zone,u.slot) for u in roster}
    for source in roster:
        targets = [(u.zone,u.slot,u) for u in field if u!=source]
        if source.zone!='bench':
            targets += [(zone,slot,None) for zone,limit in (('front',4),('back',6)) for slot in range(1,limit+1)
                        if (zone,slot) not in occupied and zone!=source.zone]
        for zone,slot,target in targets:
            if zone not in source.eligible_zones or target is not None and source.zone!='bench' and source.zone not in target.eligible_zones:continue
            moved=tuple(replace(source,zone=zone,slot=slot) if u==source else
                        replace(target,zone=source.zone,slot=source.slot) if target is not None and u==target else u for u in roster)
            team=tuple(u for u in moved if u.zone!='bench')
            if len({u.name for u in team})!=len(team) or not any(u.zone=='front' for u in team):continue
            after=distance(moved,goal)
            if after>=before:continue
            gain=team_score(team,strategy,remembrance_name=snapshot_name(snapshot))-base
            rank=(before-after,gain,target is not None,source.zone=='bench',-source.slot,zone=='back',-slot)
            if best is None or rank>best[0]:best=(rank,(source,target,zone,slot,gain,before,after))
    if best is None:raise AutomationError('全局候选没有可核实且减少剩余移动的合法步骤，未盲目换位。')
    return best[1]


def active(session):
    return bool(session.get('reorder') and session['reorder'].get('status')!='verified')


def _snapshot(scene,session,confidence):
    snapshot=collected_snapshot(scene,session,session.get('collection',{}).get('input_epoch',-1),'standard_reorder',confidence)
    if not _scope(snapshot):
        raise AutomationError('全局整理缺少当前标准局、版本、账号或清晰账本来源。')
    _validate(snapshot)
    return snapshot


def _scope(snapshot):
    return bool((snapshot.page,snapshot.mode,snapshot.rank,snapshot.wealth,snapshot.game_version,snapshot.rules_version)
        ==('preparation','standard',8,40,'4.6','4.6') and snapshot.transaction_status=='clear'
        and snapshot.known('roster','roster_complete','node','gold','hp','level','capacity','mode','rank','wealth','game_version','rules_version','transaction_status')
        and snapshot.hp>0 and 1<=snapshot.level<=10 and (snapshot.experience is not None or snapshot.level==10))


def _load(session):
    try:
        data=session['reorder'];actions=list(session['actions']);pending=session.get('rederiving_action')
        if pending:actions.append(pending)
        index=data['action_id']
        if type(index) is not int or not 0<=index<len(actions):raise ValueError()
        root=actions[index];basis=data['basis'];snapshot=StrategySnapshot.from_dict(basis['snapshot'])
        goal,score=optimize(snapshot,basis['strategy'])
        if (not _scope(snapshot) or data.get('status')!='active' or root.get('reorder_root')!=index or root.get('action') not in MOVES
                or root.get('id')!=index or not root.get('before') or not root.get('reorder_basis')
                or type(root.get('input_epoch')) is not int or root['input_epoch']!=snapshot.input_epoch
                or packed(root['reorder_basis'])!=packed(basis) or packed(basis['goal'])!=packed(goal)
                or type(basis.get('score')) is not int or basis['score']!=score
                or not isinstance(data['steps'],list) or not data['steps'] or data['steps'][0]!=index
                or len(data['steps'])>2*snapshot.capacity or len(set(data['steps']))!=len(data['steps'])
                or data['steps']!=sorted(data['steps'])
                or score<=team_score(tuple(u for u in snapshot.roster if u.zone!='bench'),basis['strategy'],remembrance_name=snapshot_name(snapshot))):raise ValueError()
        remaining=distance(snapshot.roster,goal)
        running=snapshot
        for step_id in data['steps']:
            if type(step_id) is not int or not 0<=step_id<len(actions):raise ValueError()
            action=actions[step_id];step=action['reorder_step']
            if (action.get('reorder_root')!=index or action.get('action') not in MOVES
                    or action.get('id')!=step_id or not action.get('before')
                    or type(action.get('input_epoch')) is not int or action['input_epoch']<0
                    or (action is not pending and (action.get('status')!='verified' or not action.get('after')))
                    or action is pending and action.get('status')!='pending'
                    or action.get('decision',{}).get('policy')!=POLICY
                    or type(step['before']) is not int or type(step['after']) is not int
                    or step['before']!=remaining or not 0<=step['after']<remaining):raise ValueError()
            source,target,zone,slot,gain,start,end=choose_step(running,goal,basis['strategy'])
            payload=action.get('target',[])
            expected=(source.zone,source.slot,zone,slot,source.name,source.star,target.name if target else '',target.star if target else 0)
            identities={zone+':'+str(slot):asdict(replace(source,zone=zone,slot=slot))}
            if target is not None:identities[source.zone+':'+str(source.slot)]=asdict(replace(target,zone=source.zone,slot=source.slot))
            if (not isinstance(payload,list) or len(payload)!=14 or packed(payload[:4])!=packed([snapshot.node,snapshot.gold,snapshot.hp,snapshot.level])
                    or packed(payload[4:8]+payload[10:])!=packed(expected)
                    or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in payload[8:10])
                    or action['action']!=('stage_standard_exchange' if target else 'stage_standard_relocate')
                    or action.get('expected')!=('standard_exchange_inspectable' if target else 'standard_relocate_inspectable')
                    or (step['before'],step['after'])!=(start,end)
                    or packed(action.get('exchange_expected'))!=packed(identities)
                    or packed(action['decision'])!=packed(dict(source=source.name,target=target.name if target else '空位',improvement=gain,policy=POLICY))
                    or step_id!=data['steps'][-1] and (action.get('movement_verified') is not True or action.get('reorder_verified') is not True)):raise ValueError()
            running=replace(running,roster=tuple(replace(source,zone=zone,slot=slot) if u==source else
                replace(target,zone=source.zone,slot=source.slot) if target is not None and u==target else u for u in running.roster))
            remaining=step['after']
        return data,basis,snapshot,goal,score,actions
    except (KeyError,ValueError,TypeError,AttributeError) as exc:
        raise AutomationError('全局整理原始目标、步骤或递减记录不完整，未继续输入。') from exc


def _same_roster(snapshot,original):
    return (sorted(identity(u) for u in snapshot.roster)==sorted(identity(u) for u in original.roster)
            and all(getattr(snapshot,k)==getattr(original,k) for k in
                    ('node','gold','hp','level','experience','capacity','inventory','environment','investments','private_names')))


def proposal(scene,session,confidence=.65):
    from .currency_wars_standard_exchange import ExchangePlan
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_deployment import backend_layout
    from .currency_wars_market import overclock_board
    snapshot=_snapshot(scene,session,confidence);strategy=session.get('strategy','default')
    if active(session):
        data,basis,original,goal,score,actions=_load(session)
        if strategy!=basis['strategy'] or not _same_roster(snapshot,original):
            raise AutomationError('全局整理途中阵容属性、资源或策略变化，未沿用旧目标。')
        last=actions[data['steps'][-1]];own=last is session.get('rederiving_action')
        expected=last['reorder_step']['before' if own else 'after']
        if distance(snapshot.roster,goal)!=expected or not own and last.get('reorder_verified') is not True:
            raise AutomationError('上一步全局移动尚未通过完整阵容核验，未提交下一步。')
    else:
        goal,score=optimize(snapshot,strategy)
        field=tuple(u for u in snapshot.roster if u.zone!='bench')
        if score<=team_score(field,strategy,remembrance_name=snapshot_name(snapshot)):return None
        basis=json.loads(packed(dict(snapshot=asdict(snapshot),strategy=strategy,goal=goal,score=score)))
    source,target,zone,slot,gain,before,after=choose_step(snapshot,goal,strategy)
    cells={(c.zone,c.slot):c for c in roster_cells(scene,confidence)};a=cells[source.zone,source.slot];b=cells[zone,slot]
    if (backend_layout(scene.image)[0]!=6 or overclock_board(scene) or a.state!='occupied'
            or b.state!=('occupied' if target else 'empty')):raise AutomationError('全局整理当前来源、目标或标准布局不符。')
    plan=ExchangePlan(a.point,b.point,a.zone,a.slot,b.zone,b.slot)
    payload=(snapshot.node,snapshot.gold,snapshot.hp,snapshot.level,a.zone,a.slot,b.zone,b.slot,a.signature,b.signature,
             source.name,source.star,target.name if target else '',target.star if target else 0)
    return StandardAction('stage_standard_exchange' if target else 'stage_standard_relocate',
        'standard_exchange_inspectable' if target else 'standard_relocate_inspectable',plan,
        details=(source.name,target.name if target else '空位',gain,POLICY,basis,before,after),payload=payload)


def bind(session,choice,scene=None,confidence=.65):
    if choice.intent not in MOVES or len(choice.details)!=7 or choice.details[3]!=POLICY:return
    action=session['actions'][-1];basis=choice.details[4]
    if active(session):
        data,old,*_=_load(session)
        if packed(old)!=packed(basis):raise AutomationError('全局整理目标与落盘步骤不同。')
    else:
        action['reorder_basis']=json.loads(packed(basis))
        data=dict(status='active',action_id=action['id'],basis=json.loads(packed(action['reorder_basis'])),steps=[])
        session['reorder']=data
    action['reorder_root']=data['action_id']
    action['reorder_step']=dict(before=choice.details[5],after=choice.details[6])
    data['steps'].append(action['id'])
    if scene is not None:
        from .currency_wars_appearance import appearance
        changed={(choice.payload[4],choice.payload[5]),(choice.payload[6],choice.payload[7])}
        action['reorder_preserved']={}
        for cell in roster_cells(scene,confidence):
            record=session['collection']['units'].get(cell.zone+':'+str(cell.slot),{})
            if cell.state!='occupied' or (cell.zone,cell.slot) in changed or 'collection_close_action_id' not in record:continue
            action['reorder_preserved'][cell.zone+':'+str(cell.slot)]=dict(unit=json.loads(packed(record['unit'])),
                close_action_id=record['collection_close_action_id'],source_signature=record['signature'],
                before_signature=cell.signature,before=appearance(scene,cell.roi))


def preserve_return(session,scene,confidence=.65):
    from .currency_wars_appearance import appearance
    action=session['actions'][-1]
    cells={c.zone+':'+str(c.slot):c for c in roster_cells(scene,confidence)}
    for name,proof in action.get('reorder_preserved',{}).items():
        proof.update(after_signature=cells[name].signature,after=appearance(scene,cells[name].roi),after_source=action['after'])


def preserves(child,record,cell,actions):
    """Only this verified move's unchanged slots may retain an ordinary read."""
    from .currency_wars_appearance import same_appearance
    try:
        parent=child
        if child.get('action') in ('inspect_standard_exchange_unit','close_standard_exchange_unit','close_standard_exchange_stale_panel'):
            target=child['target'];index=target[4] if child['action']=='inspect_standard_exchange_unit' else target[6]
            if type(index) is not int or not 0<=index<child['id']:return False
            parent=actions[index]
            if child.get('input_epoch')!=parent.get('input_epoch'):return False
        if (parent.get('action') not in MOVES or parent.get('movement_verified') is not True
                or parent.get('input_epoch')!=record.get('input_epoch') or not valid_action(parent,actions)):return False
        name=cell.zone+':'+str(cell.slot);proof=parent['reorder_preserved'][name];target=parent['target']
        if (cell.zone,cell.slot) in ((target[4],target[5]),(target[6],target[7])):return False
        close=proof['close_action_id']
        return (type(close) is int and close==record['collection_close_action_id'] and close<parent['id']
            and packed(proof['unit'])==packed(record['unit']) and proof['source_signature']==record['signature']
            and proof['after_source']==parent['after'] and parent.get('after')
            and all(isinstance(proof[k],str) and re.fullmatch('[0-9a-f]{64}',proof[k]) for k in ('before_signature','after_signature'))
            and same_appearance(actions[close]['collection_receipt']['appearance'],proof['before'])
            and same_appearance(proof['before'],proof['after']))
    except (KeyError,IndexError,TypeError,ValueError):return False


def recommendation_probe(scene,session,confidence=.65):
    """New field profiles must also retain the existing crafting capability."""
    if not active(session):return None
    data,*_= _load(session)
    actions=list(session['actions'])
    if session.get('rederiving_action'):actions.append(session['rederiving_action'])
    if actions[data['steps'][-1]].get('movement_verified') is not True:return None
    for cell in roster_cells(scene,confidence):
        record=session.get('collection',{}).get('units',{}).get(cell.zone+':'+str(cell.slot),{})
        if cell.zone!='bench' and cell.state=='occupied' and 'recommendations' not in record:
            from .currency_wars_standard_flow import StandardAction
            from .models import Token
            x,y=cell.point
            return StandardAction('inspect_standard_unit','character',Token('核实整理后装备推荐',1.,(x-.01,y-.01,x+.01,y+.01)),
                payload=(cell.zone,cell.slot,cell.node,cell.signature))
    return None


def advance(session,scene,confidence=.65):
    if not active(session) or not session.get('collection',{}).get('complete'):return False
    data,basis,original,goal,score,actions=_load(session);last=actions[data['steps'][-1]]
    if last.get('movement_verified') is not True:return False
    snapshot=_snapshot(scene,session,confidence)
    if (session.get('strategy')!=basis['strategy'] or not _same_roster(snapshot,original)
            or distance(snapshot.roster,goal)!=last['reorder_step']['after']):
        raise AutomationError('全局移动后实际阵容、资源或剩余步骤不符，未继续整理或出战。')
    if any(u.zone!='bench' and 'recommendations' not in session['collection']['units'][u.zone+':'+str(u.slot)] for u in snapshot.roster):return False
    last['reorder_verified']=True
    if distance(snapshot.roster,goal)==0 or team_score(tuple(u for u in snapshot.roster if u.zone!='bench'),
            basis['strategy'],remembrance_name=snapshot_name(snapshot))>=score:
        data.update(status='verified',verified_run=session['account_verified_run'],verified_epoch=session['account_verified_epoch'])
        session.setdefault('reorder_history',[]).append(json.loads(packed(data)))
    return True


@lru_cache(maxsize=128)
def _valid_frozen_chain(serialized):
    # Only immutable decision/source fields are cached. Appearance preservation
    # is checked separately on every call; any edited decision changes this key.
    chain=json.loads(serialized);root=chain[0]['reorder_root']
    actions=[None]*(chain[-1]['id']+1)
    for item in chain:actions[item['id']]=item
    _load(dict(actions=actions,reorder=dict(status='active',action_id=root,
        basis=chain[0]['reorder_basis'],steps=[a['id'] for a in chain])))
    return True


def valid_action(action,actions):
    """The new free move is recognized only with its original whole-roster plan."""
    try:
        root=action['reorder_root']
        if type(root) is not int or not 0<=root<=action['id']<len(actions) or actions[action['id']]!=action:return False
        fields=('id','action','status','expected','before','after','input_epoch','target','decision','exchange_expected',
                'reorder_root','reorder_step','reorder_basis','movement_verified','reorder_verified')
        chain=[{k:a.get(k) for k in fields} for a in actions[:action['id']+1] if a.get('reorder_root')==root]
        return _valid_frozen_chain(packed(chain))
    except (AutomationError,KeyError,ValueError,TypeError,AttributeError):return False
