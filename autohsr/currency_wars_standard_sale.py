"""Inspect one chosen unit, read its refund, then verify one sale.

The original full board and the intervening inspected identity remain bound to
one run/input epoch. No hidden portrait, name or refund is invented from a tier.
"""
from dataclasses import asdict
from copy import deepcopy
import hashlib
import json
import re

from .currency_wars_collector import collected_snapshot, owned_profile, roster_cells
from .currency_wars_appearance import appearance,_decoded,same_appearance
from .currency_wars_deployment import _crop, _similarity, backend_layout
from .currency_wars_match import read_match
from .currency_wars_standard_policy import PREFERRED,preferred_names
from .currency_wars_standard_hud import experience_observed
from .currency_wars_state import StrategySnapshot
from .models import AutomationError, Token, normalize
from . import currency_wars_sale_equipment as gear_sale

POLICY = 'owned-sale-v1'
FIELD_POLICY = 'owned-field-sale-v1'
FIELD_INSPECT = 'inspect_standard_field_sale_unit'
FIELD_SELL = 'sell_standard_field_owned'
REFUND_ROI = (.83,.80,.90,.88)
BUTTON_ROI = (.90,.80,.98,.88)
POSITIONS = frozenset([f'front:{i}' for i in range(1,5)]+[f'back:{i}' for i in range(1,7)]+
                      [f'bench:{i}' for i in range(1,10)])


def target_zone(target):
    if gear_sale.equipment(target):return target[-2]
    if len(target) in (10,12):return 'bench'
    if len(target) in (11,13) and target[-1] in ('front','back'):return target[-1]
    raise ValueError('出售来源区域无效')


def inspection_target(target):
    return list(target[:10])+(list(target[12:]) if len(target) in (13,14) else [])


def same_target(left,right):
    return json.dumps(left,sort_keys=True,allow_nan=False)==json.dumps(right,sort_keys=True,allow_nan=False)


def board_digest(cells):
    if not isinstance(cells,dict) or set(cells) != POSITIONS:
        raise ValueError('出售的十九格来源不完整')
    if any(not isinstance(value,(list,tuple)) or len(value) != 2 or value[0] not in ('empty','occupied')
           or not isinstance(value[1],str) or re.fullmatch(r'[0-9a-f]{64}',value[1]) is None for value in cells.values()):
        raise ValueError('出售的角色槽来源无效')
    return hashlib.sha256(json.dumps(cells,sort_keys=True,separators=(',',':')).encode('ascii')).hexdigest()


def board_cells(scene, confidence=.65):
    result = {cell.zone+':'+str(cell.slot):[cell.state,cell.signature] for cell in roster_cells(scene,confidence)}
    board_digest(result)
    return result


def choose_sale(snapshot, strategy='default', *, equipped_capacity=0):
    from .currency_wars_standard_exchange import choose_exchange
    if strategy not in PREFERRED:
        raise AutomationError('出售策略不在已冻结范围内。')
    if type(equipped_capacity) is not int or not 0<=equipped_capacity<=3:
        raise AutomationError('携装出售可核实的库存空位无效。')
    if not snapshot.roster_complete or snapshot.capacity is None:
        raise AutomationError('出售需要完整持有阵容。')
    field = tuple(unit for unit in snapshot.roster if unit.zone != 'bench')
    if (any(u.star is None or u.tier is None or not u.eligible_zones for u in snapshot.roster)
            or len({u.name for u in field})!=len(field) or any(u.zone not in u.eligible_zones for u in field)):
        raise AutomationError('出售前角色星级、费用、名字或位置适配未核实。')
    from .currency_wars_names import snapshot_name
    keep = set(preferred_names(strategy,snapshot_name(snapshot))) | ({'昔涟','瓦尔特'} if strategy == 'aglaea' else set())
    keep |= {'开拓者','记忆开拓者'}
    # March7th starts its on-field cleanup only after acquiring Seele.
    def supported(unit):
        return unit.equipment==() or gear_sale.known(unit.equipment) and len(unit.equipment)<=equipped_capacity
    if strategy=='seele' and any(unit.name=='希儿' for unit in snapshot.roster):
        field_candidates=[unit for unit in field if unit.name not in keep and supported(unit)
            and unit.star is not None and unit.tier is not None]
        if field_candidates:
            return min(field_candidates,key=lambda u:(u.star,u.tier,u.zone!='back',u.slot)),'field_out_of_strategy'
    if len(field) != snapshot.capacity or choose_exchange(snapshot,strategy) is not None:
        return None  # Deploy useful units before discarding a possible bench improvement.
    candidates = []
    for unit in snapshot.roster:
        if unit.zone != 'bench' or not supported(unit) or unit.star is None or unit.tier is None:
            continue
        same = [other for other in field if other.name == unit.name and other.star >= unit.star]
        reason = None
        if strategy != 'default':
            if unit.name not in keep:
                reason = 'out_of_strategy'
            elif strategy == 'seele' and unit.name != PREFERRED[strategy][0] and same:
                reason = 'redundant_support'
        elif same and max(other.star for other in same) >= 3:
            reason = 'max_star_duplicate'
        elif unit.eligible_zones and all(sum(other.zone == zone for other in field) >=
                                        (4 if zone == 'front' else 6) for zone in unit.eligible_zones):
            reason = 'position_saturated'
        if reason:
            candidates.append((unit.star,unit.tier,unit.slot,unit,reason))
    return min(candidates,key=lambda item:item[:3])[3:] if candidates else None


def proposal(scene, session, confidence=.65):
    from .currency_wars_standard_trading import _scope
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_market import overclock_board
    prior = _scope(session,FIELD_INSPECT if (session.get('actions') or [{}])[-1].get('action')==FIELD_INSPECT else 'inspect_standard_sale_unit')
    epoch = prior['collection']['input_epoch']
    snapshot = collected_snapshot(scene,prior,epoch,'standard_sale',confidence)
    if (snapshot.page != 'preparation' or snapshot.mode != 'standard' or snapshot.rank != 8 or snapshot.wealth != 40
            or snapshot.game_version != '4.6' or snapshot.rules_version != '4.6'
            or snapshot.transaction_status != 'clear' or not snapshot.node or snapshot.gold is None
            or snapshot.hp is None or snapshot.hp <= 0 or not experience_observed(scene,snapshot,confidence)
            or backend_layout(scene.image)[0] != 6 or overclock_board(scene)):
        raise AutomationError('出售缺少当前标准局、版本、余额、经验或完整阵容来源。')
    chosen = choose_sale(snapshot,prior.get('strategy','default'),equipped_capacity=gear_sale.capacity(scene,snapshot,confidence))
    if chosen is None:
        return None
    unit,reason = chosen
    cells = roster_cells(scene,confidence)
    cell = next(cell for cell in cells if (cell.zone,cell.slot) == (unit.zone,unit.slot))
    signatures = board_cells(scene,confidence)
    x,y = cell.point
    field=unit.zone!='bench'
    return StandardAction(FIELD_INSPECT if field else 'inspect_standard_sale_unit',
                          'standard_field_sale_panel' if field else 'standard_sale_panel',
                          Token('查看待整理角色',1.,(x-.01,y-.01,x+.01,y+.01)),
                          details=(prior.get('strategy','default'),0.,(reason,),FIELD_POLICY if field else POLICY),
                          payload=(snapshot.node,snapshot.gold,snapshot.hp,snapshot.level,unit.slot,
                                   unit.name,unit.star,unit.tier,cell.signature,board_digest(signatures))+
                                  (gear_sale.suffix(unit.zone,unit.equipment) if unit.equipment else (unit.zone,) if field else ()))


def bind_intent(session, choice, scene, confidence=.65):
    from .currency_wars_standard_trading import _scope
    prior = _scope(session,choice.intent)
    snapshot = collected_snapshot(scene,prior,prior['collection']['input_epoch'],'before_standard_sale',confidence)
    action = session['actions'][-1]
    cells = board_cells(scene,confidence)
    zone=target_zone(choice.payload)
    if board_digest(cells) != choice.payload[9] or cells[zone+':'+str(choice.payload[4])][1] != choice.payload[8]:
        raise AutomationError('待整理角色来源与已落盘查看意图不同。')
    unit = next(unit for unit in snapshot.roster if (unit.zone,unit.slot) == (zone,choice.payload[4]))
    session['sale'] = dict(status='inspecting',inspect_action_id=action['id'],inspect_target=list(choice.payload),
                           unit=json.loads(json.dumps(asdict(unit))),snapshot=asdict(snapshot),cells=cells,
                           input_epoch=prior['collection']['input_epoch'],run_dir=prior['collection']['run_dir'],
                           shape=list(scene.image.shape),reason=choice.details[2][0],max_level_verified=snapshot.level==10)
    if gear_sale.equipment(choice.payload):
        bank=gear_sale.inventory(scene,confidence)
        if bank['capacity']<len(unit.equipment):raise AutomationError('当前可核实库存空位不足，未出售携装角色。')
        session['sale']['inventory']=bank
        action['equipped_sale_basis']=deepcopy(dict(session['sale'],strategy=prior.get('strategy','default')))
    if zone!='bench':
        action['field_sale_basis']=deepcopy(dict(session['sale'],strategy=prior.get('strategy','default')))
        action['field_sale_basis']['appearances']={c.zone+':'+str(c.slot):appearance(scene,c.roi)
            for c in roster_cells(scene,confidence) if c.state=='occupied'}


def _expected_profile(scene, target, confidence):
    profile = owned_profile(scene,dict(zone=target_zone(target),slot=target[4],node=target[0]),confidence)
    if (profile.name,profile.star,profile.tier,profile.equipment) != (target[5],target[6],target[7],gear_sale.equipment(target)):
        raise AutomationError('待整理角色的当前名字、星级、费用或冻结装备不符。')
    return profile


def panel_feedback(choice, before, after, confidence=.65):
    first,last = read_match(before,confidence),read_match(after,confidence)
    if (not first or not last or first.page != 'preparation' or last.page != 'character'
            or not experience_observed(before,first,confidence) or not experience_observed(after,last,confidence)
            or (first.node,first.gold,first.hp,first.level) != choice.payload[:4]
            or (last.node,last.level,last.experience,last.deployment) !=
               (first.node,first.level,first.experience,first.deployment)
            or last.hp not in (None,first.hp) or before.image is None or after.image is None
            or before.image.shape != after.image.shape):
        return False
    try:
        _expected_profile(after,choice.payload,confidence)
        for cell in roster_cells(before,confidence):
            # The right-hand panel occludes later cells. Their source comes
            # from the durable fresh-board click and independently read panel.
            if cell.roi[2] <= .70 and _similarity(_crop(before.image,cell.roi),_crop(after.image,cell.roi)) < .92:
                return False
        return True
    except AutomationError:
        return False


def refund_target(scene, confidence=.65):
    from .currency_wars_navigation import unique
    from .currency_wars_prepare import trusted
    clean = trusted(scene,confidence)
    readings = [normalize(t.text) for t in clean.tokens if t.within(REFUND_ROI)]
    if not readings or any(not re.fullmatch(r'\+(?:0|[1-9][0-9]?)',value) for value in readings):
        raise AutomationError('当前出售返还没有独立正号金额，未出售。')
    amounts = {int(value[1:]) for value in readings}
    if len(amounts) != 1:
        raise AutomationError('当前出售返还金额冲突，未出售。')
    return next(iter(amounts)),unique(clean,'出售',BUTTON_ROI)


def _sale(session):
    sale = session.get('sale')
    if not sale or sale.get('status') in ('verified','cancelled'):
        return None
    index = sale.get('inspect_action_id')
    actions = session.get('actions',[])
    try:
        valid_board = board_digest(sale.get('cells')) == sale.get('inspect_target',[None]*10)[9]
        zone=target_zone(sale.get('inspect_target',[]))
    except (ValueError,IndexError,TypeError):
        valid_board = False;zone=None
    if (sale.get('status') != 'inspecting' or type(index) is not int or not 0 <= index < len(actions)
            or actions[index].get('action') != (FIELD_INSPECT if zone in ('front','back') else 'inspect_standard_sale_unit')
            or actions[index].get('target') != sale.get('inspect_target')
            or not valid_board):
        raise AutomationError('出售查看链不完整，未继续输入。')
    return sale


def stale(session):
    sale = session.get('sale',{})
    return (sale.get('status') == 'inspecting' and
            (sale.get('input_epoch') != session.get('account_verified_epoch')
             or sale.get('run_dir') != session.get('account_verified_run')))


def _field_basis(sale, item, strategy):
    try:
        basis=item['field_sale_basis']
        frozen={key:basis[key] for key in sale}
        if (json.dumps(frozen,sort_keys=True,allow_nan=False)!=json.dumps(sale,sort_keys=True,allow_nan=False)
                or basis['strategy']!=strategy or strategy!='seele' or item.get('expected')!='standard_field_sale_panel'
                or type(item.get('id')) is not int or item['id']!=sale['inspect_action_id']
                or type(item.get('input_epoch')) is not int or item['input_epoch']!=sale['input_epoch']
                or not item.get('before') or not item.get('after')
                or set(basis['appearances'])!={k for k,v in basis['cells'].items() if v[0]=='occupied'}):raise ValueError('来源不符')
        for value in basis['appearances'].values():_decoded(value)
        return basis
    except (AttributeError,IndexError,KeyError,TypeError,ValueError) as error:
        raise AutomationError('场上出售缺少本次完整阵容、原局部图像或正式查看来源。') from error


def active_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_standard_trading import _scope
    pending = session.get('rederiving_action') or {}
    planned = session.get('sale',{})
    if (pending.get('action') in ('inspect_standard_sale_unit',FIELD_INSPECT) and pending.get('status') == 'pending'
            and pending.get('id') == planned.get('inspect_action_id') == len(session.get('actions',[]))
            and pending.get('target') == planned.get('inspect_target')):
        return None
    sale = _sale(session)
    if sale is None:
        return None
    index = sale['inspect_action_id']
    item = session['actions'][index]
    state = read_match(scene,confidence)
    if item['status'] == 'pending' and state and state.page == 'preparation':
        return None  # Only the exact inspect proposal can be re-derived by Context.
    if item['status'] != 'verified' or not item.get('after') or not state or state.page != 'character':
        raise AutomationError('出售查看尚未核实，未输入或开始战斗。')
    if stale(session):
        return StandardAction('close_standard_sale_stale_panel','standard_sale_cancelled',
                              Token('关闭旧代次待整理角色面板',1.,(.49,.49,.51,.51)),
                              payload=tuple(sale['inspect_target'][:4]))
    field=target_zone(sale['inspect_target'])!='bench'
    prior = _scope(session,FIELD_SELL if field else 'sell_standard_owned')
    if field:_field_basis(sale,item,prior.get('strategy','default'))
    if not prior['actions'] or prior['actions'][-1]['id'] != index:
        raise AutomationError('查看待整理角色后出现其他输入，未出售。')
    target = sale['inspect_target']
    if ((state.node,state.level,state.experience,state.deployment) !=
            (target[0],target[3],tuple(sale['snapshot']['experience']) if sale['snapshot']['experience'] is not None else None,
             (sum(u['zone'] != 'bench' for u in sale['snapshot']['roster']),sale['snapshot']['capacity']))
            or not experience_observed(scene,state,confidence) or state.level==10 and sale.get('max_level_verified') is not True
            or state.hp not in (None,target[2]) or scene.image is None or list(scene.image.shape) != sale['shape']):
        raise AutomationError('待整理角色面板的节点、等级或出战人数已变。')
    profile = _expected_profile(scene,target,confidence)
    expected = json.loads(json.dumps(sale['unit']))
    if json.loads(json.dumps(asdict(profile))) != expected:
        raise AutomationError('当前待整理角色与原始位置适配或标签不一致。')
    snapshot = StrategySnapshot.from_dict(json.loads(json.dumps(sale['snapshot'])))
    if gear_sale.equipment(target):
        bank=sale.get('inventory');gear_sale.validate_inventory(bank)
        if bank['capacity']<len(gear_sale.equipment(target)) or not same_target(
                prior['actions'][index].get('equipped_sale_basis'),dict(sale,strategy=prior.get('strategy','default'))):
            raise AutomationError('携装出售缺少冻结库存与原始查看来源。')
    chosen = choose_sale(snapshot,prior.get('strategy','default'),equipped_capacity=sale.get('inventory',{}).get('capacity',0))
    if chosen is None or asdict(chosen[0]) != asdict(profile) or chosen[1] != sale['reason']:
        raise AutomationError('原始整理决策已不适用，未出售。')
    refund,button = refund_target(scene,confidence)
    payload=tuple(target[:10])+(refund,index)+(tuple(target[10:]) if gear_sale.equipment(target) or field else ())
    return StandardAction(FIELD_SELL if field else 'sell_standard_owned',
                          'standard_field_owned_sold' if field else 'standard_owned_sold',button,
                          details=(prior.get('strategy','default'),0.,(sale['reason'],),FIELD_POLICY if field else POLICY),payload=payload)


def sale_feedback(choice, before, after, session, confidence=.65):
    if session is None:
        return None
    try:
        if active_action(before,session,confidence) != choice:
            return None
        sale = _sale(session)
        field=target_zone(choice.payload)!='bench'
        state = read_match(after,confidence)
        if (not state or state.page != 'preparation' or after.image is None or list(after.image.shape) != sale['shape']
                or (state.node,state.gold,state.hp,state.level) !=
                   (choice.payload[0],choice.payload[1]+choice.payload[10],choice.payload[2],choice.payload[3])
                or state.experience != (tuple(sale['snapshot']['experience']) if sale['snapshot']['experience'] is not None else None)
                or not experience_observed(after,state,confidence)
                or state.deployment != (sum(u['zone'] != 'bench' for u in sale['snapshot']['roster'])-int(field),sale['snapshot']['capacity'])
                or backend_layout(after.image)[0] != 6):
            return None
        old,new = sale['cells'],board_cells(after,confidence)
        source = target_zone(choice.payload)+':'+str(choice.payload[4])
        appearances={c.zone+':'+str(c.slot):appearance(after,c.roi) for c in roster_cells(after,confidence) if c.state=='occupied'} if field else None
        if field:
            original=session['actions'][sale['inspect_action_id']]['field_sale_basis']['appearances']
            if (new[source][0]!='empty' or any(old[k][0]!=new[k][0] or old[k][0]=='occupied'
                    and not same_appearance(original[k],appearances[k]) for k in old if k!=source)):return None
        elif new[source][0] != 'empty' or any(old[k] != new[k] for k in old if k != source):return None
        receipt=dict(schema=1,currency='match_gold',node=state.node,gold_before=choice.payload[1],gold_after=state.gold,
                    refund=choice.payload[10],slot=choice.payload[4],name=choice.payload[5],star=choice.payload[6],tier=choice.payload[7],
                    level_after=state.level,hp_after=state.hp,inspect_action_id=choice.payload[11],
                    source_before=choice.payload[8],source_empty=True,board_before=choice.payload[9],board_after=board_digest(new),
                    cells_before=old,cells_after=new)
        if field:
            receipt.update(zone=target_zone(choice.payload),deployment_before=[state.deployment[0]+1,state.deployment[1]],
                deployment_after=list(state.deployment),experience_before=list(sale['snapshot']['experience']) if sale['snapshot']['experience'] is not None else None,
                experience_after=list(state.experience) if state.experience is not None else None,
                appearances_before=deepcopy(original),appearances_after=appearances)
        if state.level==10:
            receipt.update(max_level_verified=True,experience_before=None,experience_after=None)
        if gear_sale.equipment(choice.payload):
            receipt['equipment_return']=gear_sale.return_proof(sale['inventory'],gear_sale.inventory(after,confidence),gear_sale.equipment(choice.payload))
        return receipt
    except (AutomationError,ValueError,KeyError,TypeError):
        return None


def cancelled_feedback(scene, session, confidence=.65):
    try:
        sale = _sale(session)
        state = read_match(scene,confidence)
        return bool(sale and state and state.page == 'preparation'
                    and (state.node,state.gold,state.hp,state.level) == tuple(sale['inspect_target'][:4])
                    and board_cells(scene,confidence) == sale['cells'])
    except (AutomationError,ValueError):
        return False


def finish(session, *, cancelled=False):
    sale = session['sale']
    sale['status'] = 'cancelled' if cancelled else 'verified'
    session.setdefault('sale_history',[]).append(json.loads(json.dumps(sale)))
    if cancelled:
        session.pop('collection',None)
    else:
        session['collection']['units'].pop(sale['unit']['zone']+':'+str(sale['unit']['slot']),None)
        session['collection']['complete']=False
        session.setdefault('discarded_units',[]).append(dict(node=sale['inspect_target'][0],name=sale['unit']['name'],
                                                           action_id=session['actions'][-1]['id'],reason=sale['reason']))
        nodes = session.get('shop_observed_nodes',[])
        if sale['inspect_target'][0] in nodes:
            nodes.remove(sale['inspect_target'][0])
        if gear_sale.equipment(sale['inspect_target']):
            # A returned inventory is not a new inspection of every survivor.
            session.pop('collection',None)


def valid_field_source(action, inspection):
    """The field-sale credit keeps its original complete roster and policy."""
    try:
        if (action.get('action')!=FIELD_SELL or action.get('expected')!='standard_field_owned_sold'
                or inspection.get('action')!=FIELD_INSPECT or inspection.get('expected')!='standard_field_sale_panel'):
            return False
        basis=inspection['field_sale_basis'];target=action['target']
        if (not same_target(basis['inspect_target'],inspection['target']) or not same_target(inspection_target(target),inspection['target'])
                or any(type(value) is not int for value in (basis['inspect_action_id'],inspection['id'],basis['input_epoch'],action['input_epoch']))
                or basis['inspect_action_id']!=inspection['id'] or basis['input_epoch']!=action['input_epoch']
                or not isinstance(basis['run_dir'],str) or not basis['run_dir'] or basis['strategy']!='seele'
                or basis['reason']!='field_out_of_strategy' or basis['cells']!=action['receipt']['cells_before']
                or basis['appearances']!=action['receipt']['appearances_before']):return False
        snapshot=StrategySnapshot.from_dict(json.loads(json.dumps(basis['snapshot'])))
        if (not snapshot.roster_complete or not snapshot.known('roster','roster_complete','node','gold','hp','level','capacity','mode','rank','wealth','game_version','rules_version')
                or (snapshot.mode,snapshot.rank,snapshot.wealth,snapshot.game_version,snapshot.rules_version)!=('standard',8,40,'4.6','4.6')
                or snapshot.input_epoch!=basis['input_epoch'] or [snapshot.node,snapshot.gold,snapshot.hp,snapshot.level]!=target[:4]
                or action['receipt']['experience_before']!=(list(snapshot.experience) if snapshot.experience is not None else None)
                or action['receipt']['deployment_before']!=[sum(u.zone!='bench' for u in snapshot.roster),snapshot.capacity]):return False
        equipped=inspection.get('equipped_sale_basis',{}).get('inventory',{})
        chosen=choose_sale(snapshot,basis['strategy'],equipped_capacity=equipped.get('capacity',0))
        if chosen is None:return False
        unit,reason=chosen
        return (reason==basis['reason'] and same_target(asdict(unit),basis['unit'])
                and (unit.zone,unit.slot,unit.name,unit.star,unit.tier)==(target_zone(target),target[4],*target[5:8])
                and set(basis['cells'])==POSITIONS
                and {u.zone+':'+str(u.slot) for u in snapshot.roster}=={k for k,v in basis['cells'].items() if v[0]=='occupied'})
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False
