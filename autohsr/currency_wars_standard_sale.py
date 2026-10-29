"""Inspect one chosen bench unit, read its refund, then verify one sale.

The original full board and the intervening inspected identity remain bound to
one run/input epoch. No hidden portrait, name or refund is invented from a tier.
"""
from dataclasses import asdict
import hashlib
import json
import re

from .currency_wars_collector import collected_snapshot, owned_profile, roster_cells
from .currency_wars_deployment import _crop, _similarity, backend_layout
from .currency_wars_match import read_match
from .currency_wars_standard_policy import PREFERRED,preferred_names
from .currency_wars_standard_hud import experience_observed
from .currency_wars_state import StrategySnapshot
from .models import AutomationError, Token, normalize

POLICY = 'owned-sale-v1'
REFUND_ROI = (.83,.80,.90,.88)
BUTTON_ROI = (.90,.80,.98,.88)
POSITIONS = frozenset([f'front:{i}' for i in range(1,5)]+[f'back:{i}' for i in range(1,7)]+
                      [f'bench:{i}' for i in range(1,10)])


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


def choose_sale(snapshot, strategy='default'):
    from .currency_wars_standard_exchange import choose_exchange
    if strategy not in PREFERRED:
        raise AutomationError('出售策略不在已冻结范围内。')
    if not snapshot.roster_complete or snapshot.capacity is None:
        raise AutomationError('出售需要完整持有阵容。')
    field = tuple(unit for unit in snapshot.roster if unit.zone != 'bench')
    if len(field) != snapshot.capacity or choose_exchange(snapshot,strategy) is not None:
        return None  # Deploy useful units before discarding a possible improvement.
    from .currency_wars_names import snapshot_name
    keep = set(preferred_names(strategy,snapshot_name(snapshot))) | ({'昔涟','瓦尔特'} if strategy == 'aglaea' else set())
    keep |= {'开拓者','记忆开拓者'}
    candidates = []
    for unit in snapshot.roster:
        if unit.zone != 'bench' or unit.equipment != () or unit.star is None or unit.tier is None:
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
    prior = _scope(session,'inspect_standard_sale_unit')
    epoch = prior['collection']['input_epoch']
    snapshot = collected_snapshot(scene,prior,epoch,'standard_sale',confidence)
    if (snapshot.page != 'preparation' or snapshot.mode != 'standard' or snapshot.rank != 8 or snapshot.wealth != 40
            or snapshot.game_version != '4.6' or snapshot.rules_version != '4.6'
            or snapshot.transaction_status != 'clear' or not snapshot.node or snapshot.gold is None
            or snapshot.hp is None or snapshot.hp <= 0 or not experience_observed(scene,snapshot,confidence)
            or backend_layout(scene.image)[0] != 6 or overclock_board(scene)):
        raise AutomationError('出售缺少当前标准局、版本、余额、经验或完整阵容来源。')
    chosen = choose_sale(snapshot,prior.get('strategy','default'))
    if chosen is None:
        return None
    unit,reason = chosen
    cells = roster_cells(scene,confidence)
    cell = next(cell for cell in cells if (cell.zone,cell.slot) == ('bench',unit.slot))
    signatures = board_cells(scene,confidence)
    x,y = cell.point
    return StandardAction('inspect_standard_sale_unit','standard_sale_panel',
                          Token('查看待整理备战角色',1.,(x-.01,y-.01,x+.01,y+.01)),
                          details=(prior.get('strategy','default'),0.,(reason,),POLICY),
                          payload=(snapshot.node,snapshot.gold,snapshot.hp,snapshot.level,unit.slot,
                                   unit.name,unit.star,unit.tier,cell.signature,board_digest(signatures)))


def bind_intent(session, choice, scene, confidence=.65):
    from .currency_wars_standard_trading import _scope
    prior = _scope(session,'inspect_standard_sale_unit')
    snapshot = collected_snapshot(scene,prior,prior['collection']['input_epoch'],'before_standard_sale',confidence)
    action = session['actions'][-1]
    cells = board_cells(scene,confidence)
    if board_digest(cells) != choice.payload[9] or cells['bench:'+str(choice.payload[4])][1] != choice.payload[8]:
        raise AutomationError('待整理角色来源与已落盘查看意图不同。')
    unit = next(unit for unit in snapshot.roster if (unit.zone,unit.slot) == ('bench',choice.payload[4]))
    session['sale'] = dict(status='inspecting',inspect_action_id=action['id'],inspect_target=list(choice.payload),
                           unit=json.loads(json.dumps(asdict(unit))),snapshot=asdict(snapshot),cells=cells,
                           input_epoch=prior['collection']['input_epoch'],run_dir=prior['collection']['run_dir'],
                           shape=list(scene.image.shape),reason=choice.details[2][0],max_level_verified=snapshot.level==10)


def _expected_profile(scene, target, confidence):
    profile = owned_profile(scene,dict(zone='bench',slot=target[4],node=target[0]),confidence)
    if (profile.name,profile.star,profile.tier,profile.equipment) != (target[5],target[6],target[7],()):
        raise AutomationError('待整理角色的当前名字、星级、费用或空装备不符。')
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
    except (ValueError,IndexError,TypeError):
        valid_board = False
    if (sale.get('status') != 'inspecting' or type(index) is not int or not 0 <= index < len(actions)
            or actions[index].get('action') != 'inspect_standard_sale_unit'
            or actions[index].get('target') != sale.get('inspect_target')
            or not valid_board):
        raise AutomationError('出售查看链不完整，未继续输入。')
    return sale


def stale(session):
    sale = session.get('sale',{})
    return (sale.get('status') == 'inspecting' and
            (sale.get('input_epoch') != session.get('account_verified_epoch')
             or sale.get('run_dir') != session.get('account_verified_run')))


def active_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_standard_trading import _scope
    pending = session.get('rederiving_action') or {}
    planned = session.get('sale',{})
    if (pending.get('action') == 'inspect_standard_sale_unit' and pending.get('status') == 'pending'
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
    prior = _scope(session,'sell_standard_owned')
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
    chosen = choose_sale(snapshot,prior.get('strategy','default'))
    if chosen is None or asdict(chosen[0]) != asdict(profile) or chosen[1] != sale['reason']:
        raise AutomationError('原始整理决策已不适用，未出售。')
    refund,button = refund_target(scene,confidence)
    return StandardAction('sell_standard_owned','standard_owned_sold',button,
                          details=(prior.get('strategy','default'),0.,(sale['reason'],),POLICY),
                          payload=tuple(target)+(refund,index))


def sale_feedback(choice, before, after, session, confidence=.65):
    if session is None:
        return None
    try:
        if active_action(before,session,confidence) != choice:
            return None
        sale = _sale(session)
        state = read_match(after,confidence)
        if (not state or state.page != 'preparation' or after.image is None or list(after.image.shape) != sale['shape']
                or (state.node,state.gold,state.hp,state.level) !=
                   (choice.payload[0],choice.payload[1]+choice.payload[10],choice.payload[2],choice.payload[3])
                or state.experience != (tuple(sale['snapshot']['experience']) if sale['snapshot']['experience'] is not None else None)
                or not experience_observed(after,state,confidence)
                or state.deployment != (sum(u['zone'] != 'bench' for u in sale['snapshot']['roster']),sale['snapshot']['capacity'])
                or backend_layout(after.image)[0] != 6):
            return None
        old,new = sale['cells'],board_cells(after,confidence)
        source = 'bench:'+str(choice.payload[4])
        if new[source][0] != 'empty' or any(old[k] != new[k] for k in old if k != source):
            return None
        receipt=dict(schema=1,currency='match_gold',node=state.node,gold_before=choice.payload[1],gold_after=state.gold,
                    refund=choice.payload[10],slot=choice.payload[4],name=choice.payload[5],star=choice.payload[6],tier=choice.payload[7],
                    level_after=state.level,hp_after=state.hp,inspect_action_id=choice.payload[11],
                    source_before=choice.payload[8],source_empty=True,board_before=choice.payload[9],board_after=board_digest(new),
                    cells_before=old,cells_after=new)
        if state.level==10:
            receipt.update(max_level_verified=True,experience_before=None,experience_after=None)
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
        session['collection']['units'].pop('bench:'+str(sale['unit']['slot']),None)
        session.setdefault('discarded_units',[]).append(dict(node=sale['inspect_target'][0],name=sale['unit']['name'],
                                                           action_id=session['actions'][-1]['id'],reason=sale['reason']))
        nodes = session.get('shop_observed_nodes',[])
        if sale['inspect_target'][0] in nodes:
            nodes.remove(sale['inspect_target'][0])
