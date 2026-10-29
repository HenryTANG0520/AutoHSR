"""Monotone roster exchanges followed by two independently read identities.

A returned board only permits inspection. Movement is not verified until both
affected slots have the expected name/star/tier and have been closed back to
the unchanged board. No financial or battle action runs during this protocol.
"""
from dataclasses import asdict, dataclass, replace
import json

from .currency_wars import observe
from .currency_wars_collector import collected_snapshot, owned_profile, roster_cells
from .currency_wars_deployment import backend_layout
from .currency_wars_match import read_match
from .currency_wars_standard_deployment import team_score
from .models import AutomationError, Token

POLICY = 'owned-exchange-v1'
MOVES = frozenset(('stage_standard_exchange','stage_standard_relocate'))


@dataclass(frozen=True)
class ExchangeChoice:
    source: object
    target: object
    improvement: float


@dataclass(frozen=True)
class ExchangePlan:
    start: tuple
    end: tuple
    source_zone: str
    source_slot: int
    zone: str
    target_slot: int
    backend_slots: int = 6


def key(zone, slot):
    return zone+':'+str(slot)


def _proof_current(scene,data,name,proof,cells):
    if not data.get('empty'):return proof.get('signature')==cells[name].signature
    from .currency_wars_appearance import appearance,same_appearance
    return bool(proof.get('appearance') and same_appearance(proof['appearance'],appearance(scene,cells[name].roi)))


def choose_exchange(snapshot, strategy='default'):
    if (not snapshot.roster_complete or snapshot.capacity is None or
            any(unit.star is None or unit.tier is None or not unit.eligible_zones for unit in snapshot.roster)):
        raise AutomationError('换人需要完整角色、星级、费用与位置适配。')
    field = tuple(unit for unit in snapshot.roster if unit.zone != 'bench')
    if len(field) != snapshot.capacity:
        return None
    if len({unit.name for unit in field}) != len(field) or any(unit.zone not in unit.eligible_zones for unit in field):
        raise AutomationError('当前满员阵容存在重名或位置不适配，先核实。')
    from .currency_wars_names import snapshot_name
    alias=snapshot_name(snapshot)
    base = team_score(field, strategy,remembrance_name=alias)
    best = None
    for source in snapshot.roster:
        for target in field:
            if source == target or target.zone not in source.eligible_zones:
                continue
            if source.zone != 'bench' and source.zone not in target.eligible_zones:
                continue
            proposed = tuple(replace(source,zone=target.zone,slot=target.slot) if unit == target else
                             replace(target,zone=source.zone,slot=source.slot) if unit == source else unit for unit in field)
            if len({unit.name for unit in proposed}) != len(proposed):
                continue
            gain = team_score(proposed,strategy,remembrance_name=alias)-base
            order = (gain,source.zone == 'bench',-source.slot,target.zone == 'back',-target.slot)
            if gain > 0 and (best is None or order > best[0]):
                best = (order,ExchangeChoice(source,target,gain))
    return best[1] if best else None


def exchange_proposal(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_market import overclock_board
    collection = session.get('collection',{})
    snapshot = collected_snapshot(scene,session,collection.get('input_epoch',-1),'standard_exchange',confidence)
    if (snapshot.page != 'preparation' or snapshot.mode != 'standard' or snapshot.rank != 8 or snapshot.wealth != 40
            or snapshot.game_version != '4.6' or snapshot.rules_version != '4.6'
            or snapshot.transaction_status != 'clear' or snapshot.node is None or snapshot.gold is None
            or snapshot.hp is None or snapshot.hp <= 0 or snapshot.level is None):
        raise AutomationError('换人缺少当前标准局、版本、余额或完整阵容来源。')
    chosen = choose_exchange(snapshot,session.get('strategy','default'))
    if chosen is None:
        return None
    cells = {(cell.zone,cell.slot):cell for cell in roster_cells(scene,confidence)}
    source, target = (cells[(unit.zone,unit.slot)] for unit in (chosen.source,chosen.target))
    if (source.state != 'occupied' or target.state != 'occupied' or backend_layout(scene.image)[0] != 6
            or overclock_board(scene)):
        raise AutomationError('换人来源、目标或标准布局未核实。')
    plan = ExchangePlan(source.point,target.point,source.zone,source.slot,target.zone,target.slot)
    payload = (snapshot.node,snapshot.gold,snapshot.hp,snapshot.level,source.zone,source.slot,
               target.zone,target.slot,source.signature,target.signature,
               chosen.source.name,chosen.source.star,chosen.target.name,chosen.target.star)
    return StandardAction('stage_standard_exchange','standard_exchange_inspectable',plan,
                          details=(chosen.source.name,chosen.target.name,chosen.improvement,POLICY),payload=payload)


def inspectable(choice, before, after, confidence=.65):
    first, last = read_match(before,confidence), read_match(after,confidence)
    if (not first or not last or last.page != 'preparation' or before.image is None or after.image is None
            or before.image.shape != after.image.shape or first.node != choice.payload[0]
            or (last.node,last.gold,last.hp,last.level,last.experience,last.deployment)
            != (first.node,first.gold,first.hp,first.level,first.experience,first.deployment)):
        return False
    try:
        a = {(cell.zone,cell.slot):cell for cell in roster_cells(before,confidence)}
        b = {(cell.zone,cell.slot):cell for cell in roster_cells(after,confidence)}
        changed = {(choice.payload[4],choice.payload[5]),(choice.payload[6],choice.payload[7])}
        source,target=(choice.payload[4],choice.payload[5]),(choice.payload[6],choice.payload[7])
        relocate=choice.intent=='stage_standard_relocate'
        if (a[source].state!='occupied' or a[target].state!=('empty' if relocate else 'occupied')
                or a[source].signature!=choice.payload[8] or a[target].signature!=choice.payload[9]):return False
        if relocate:
            from .currency_wars_appearance import appearance,same_appearance
            unchanged=all(a[p].state==b[p].state and (a[p].state=='empty' or
                same_appearance(appearance(before,a[p].roi),appearance(after,b[p].roi))) for p in a if p not in changed)
        else:unchanged=all(a[p].signature==b[p].signature for p in a if p not in changed)
        return (backend_layout(after.image)[0] == 6 and b[target].state=='occupied'
                and b[source].state==('empty' if relocate else 'occupied') and unchanged)
    except (AutomationError,KeyError):
        return False


def _active(session):
    data = session.get('exchange')
    if not data or data.get('status') == 'verified':
        return None
    if data.get('status') != 'verifying':
        raise AutomationError('上次换人身份未核实，先核对记录，未重复换人或开始战斗。')
    index = data.get('action_id')
    actions = session.get('actions',[])
    if (type(index) is not int or not 0 <= index < len(actions)
            or actions[index].get('action') not in MOVES
            or actions[index].get('status') != 'verified' or not actions[index].get('after')
            or actions[index].get('exchange_expected') != data.get('expected')):
        raise AutomationError('换人核验缺少已记录的同一次拖动来源。')
    action = actions[index]
    payload, board = action.get('target'),data.get('board')
    relocate=action['action']=='stage_standard_relocate'
    expected_keys={key(payload[6],payload[7])} if isinstance(payload,list) and len(payload)==14 else set()
    if not relocate and isinstance(payload,list) and len(payload)==14:expected_keys.add(key(payload[4],payload[5]))
    if (not isinstance(payload,list) or len(payload) != 14 or not isinstance(board,list) or len(board) != 6
            or payload[:4] != board[:4] or action.get('expected') != ('standard_relocate_inspectable' if relocate else 'standard_exchange_inspectable')
            or set(data.get('expected',{})) != expected_keys
            or relocate and (payload[4] not in ('front','back') or payload[6] not in ('front','back')
                            or payload[4]==payload[6] or payload[12:]!=['',0]
                            or data.get('empty')!=[key(payload[4],payload[5])])):
        raise AutomationError('换人核验节点或目标与原拖动意图不一致。')
    return data


def panel_stale(session):
    data = _active(session)
    inspecting = session.get('inspecting',{})
    return bool(data and (inspecting.get('input_epoch') != session.get('account_verified_epoch')
                         or inspecting.get('run_dir') != session.get('account_verified_run')))


def _board(scene, data, confidence):
    state = read_match(scene,confidence)
    lock = data['board']
    if (not state or state.page != 'preparation'
            or [state.node,state.gold,state.hp,state.level] != lock[:4]
            or list(state.deployment or ()) != lock[4]
            or (list(state.experience) if state.experience else None) != lock[5]):
        raise AutomationError('换人后节点、余额、生命、等级或部署人数变化，未继续输入。')
    cells = {key(cell.zone,cell.slot):cell for cell in roster_cells(scene,confidence)}
    if backend_layout(scene.image)[0] != 6 or any(name not in cells or cells[name].state != 'occupied' for name in data['expected']):
        raise AutomationError('换人后目标槽不完整或布局改变。')
    if data.get('empty'):
        from .currency_wars_appearance import appearance,same_appearance
        if (any(cells[name].state!='empty' for name in data['empty']) or any(
                cells[name].state!=state or state=='occupied' and not same_appearance(data['appearances'][name],appearance(scene,cells[name].roi))
                for name,state in data['occupancy'].items() if name not in data['expected'])):
            raise AutomationError('移位核验期间来源空位或其他角色发生变化。')
    return cells


def active_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    data = _active(session)
    if data is None:
        return None
    kind = observe(scene,confidence).page_kind
    if kind == 'character':
        inspecting = session.get('inspecting',{})
        if panel_stale(session):
            intent = 'close_standard_exchange_stale_panel'
        else:
            profile = owned_profile(scene,inspecting,confidence)
            name = key(profile.zone,profile.slot)
            proof = data.get('proofs',{}).get(name,{})
            if (inspecting.get('exchange_id') != data['action_id'] or not proof
                    or proof.get('unit') != json.loads(json.dumps(asdict(profile)))):
                raise AutomationError('当前角色信息尚未对应换人核验，未关闭面板。')
            intent = 'close_standard_exchange_unit'
        payload = tuple(data['board'][:4]) + tuple(data['board'][4]) + (data['action_id'],)
        return StandardAction(intent,'standard_exchange_board',
                              Token('关闭换人核验面板',1.,(.49,.49,.51,.51)),payload=payload)
    if kind != 'preparation':
        raise AutomationError('换人身份核验期间只允许查看对应角色面板。')
    cells = _board(scene,data,confidence)
    epoch = session.get('account_verified_epoch')
    proofs = data.get('proofs',{})
    for name in data['expected']:
        proof = proofs.get(name,{})
        if (proof.get('closed') and _proof_current(scene,data,name,proof,cells) and proof.get('input_epoch') == epoch
                and proof.get('run_dir') == session.get('account_verified_run')):
            continue
        inflight = session.get('rederiving_action') or {}
        if data.get('inspection_attempts',0) >= 6 and inflight.get('action') != 'inspect_standard_exchange_unit':
            raise AutomationError('换人身份核验达到观察上限，未重复拖动。')
        cell = cells[name]
        x,y = cell.point
        return StandardAction('inspect_standard_exchange_unit','character',
                              Token('核实换人后角色',1.,(x-.01,y-.01,x+.01,y+.01)),
                              payload=(cell.zone,cell.slot,cell.node,cell.signature,data['action_id']))
    raise AutomationError('换人核验尚未完成返回记录，未开始其他动作。')


def record_intent(session, choice, scene=None, confidence=.65):
    action = session['actions'][-1]
    if choice.intent in MOVES:
        units = session['collection']['units']
        source_key, target_key = key(choice.payload[4],choice.payload[5]),key(choice.payload[6],choice.payload[7])
        source = units[source_key]['unit']
        expected = {target_key:dict(source,zone=choice.payload[6],slot=choice.payload[7])}
        if choice.intent=='stage_standard_exchange':
            target=units[target_key]['unit']
            expected[source_key]=dict(target,zone=source['zone'],slot=source['slot'])
        action['exchange_expected'] = json.loads(json.dumps(expected))
        from .currency_wars_standard_reorder import bind
        bind(session,choice,scene,confidence)
    elif choice.intent == 'inspect_standard_exchange_unit':
        data = _active(session)
        data['inspection_attempts'] = data.get('inspection_attempts',0)+1
        if data.get('empty'):
            from .currency_wars_appearance import appearance
            cells=_board(scene,data,confidence);cell=cells[key(choice.payload[0],choice.payload[1])]
            if (cell.zone,cell.slot,cell.node,cell.signature)!=choice.payload[:4]:
                raise AutomationError('空位移动后的查看目标与当前槽位不符。')
            action['exchange_appearance']=appearance(scene,cell.roi)


def begin_verification(session, choice, before, after, confidence=.65):
    if not inspectable(choice,before,after,confidence):
        raise AutomationError('换人后备战页尚不可核验。')
    action = session['actions'][-1]
    state = read_match(after,confidence)
    session['exchange'] = dict(action_id=action['id'],status='verifying',
                               expected=json.loads(json.dumps(action['exchange_expected'])),proofs={},
                               board=[state.node,state.gold,state.hp,state.level,list(state.deployment),
                                      list(state.experience) if state.experience else None],inspection_attempts=0)
    action['movement_verified'] = False
    cells = roster_cells(after,confidence)
    from .currency_wars_standard_reorder import preserve_return
    preserve_return(session,after,confidence)
    if choice.intent=='stage_standard_relocate':
        from .currency_wars_appearance import appearance
        session['exchange'].update(empty=[key(choice.payload[4],choice.payload[5])],
            occupancy={key(c.zone,c.slot):c.state for c in cells},
            appearances={key(c.zone,c.slot):appearance(after,c.roi) for c in cells if c.state=='occupied'})
    old = session['collection']['units']
    session['collection']['units'] = {key(cell.zone,cell.slot):old[key(cell.zone,cell.slot)] for cell in cells
        if cell.state == 'occupied' and key(cell.zone,cell.slot) not in action['exchange_expected']
        and old.get(key(cell.zone,cell.slot),{}).get('signature') == cell.signature}
    session['collection']['complete'] = False


def record_profile(session, profile, inspecting, source, epoch):
    data = _active(session)
    if data is None or panel_stale(session):
        return None
    name = key(profile.zone,profile.slot)
    expected = data['expected'].get(name)
    actual = json.loads(json.dumps(asdict(profile)))
    global_move=session['actions'][data['action_id']].get('reorder_root') is not None
    properties_match=True
    if global_move and expected is not None:
        from .currency_wars_standard_reorder import identity
        from .currency_wars_state import UnitState
        original=UnitState(**{k:(tuple(v) if isinstance(v,list) else v) for k,v in expected.items()})
        properties_match=identity(profile)==identity(original)
    if (inspecting.get('exchange_id') != data['action_id'] or expected is None
            or any(actual[field] != expected[field] for field in ('name','star','tier'))
            or profile.zone != 'bench' and profile.zone not in (profile.eligible_zones or ()) or not properties_match):
        data.update(status='identity_mismatch',actual=actual,expected_slot=name,source=source)
        return '换人后角色名称、星级、费用或位置不符，未继续交易或战斗。'
    data['proofs'][name] = dict(unit=actual,signature=inspecting['signature'],input_epoch=epoch,
                              run_dir=session.get('account_verified_run'),source=source,closed=False)
    if data.get('empty'):
        action=session['actions'][inspecting['inspection_action_id']]
        if action.get('action')!='inspect_standard_exchange_unit' or not action.get('exchange_appearance'):
            raise AutomationError('空位移动后的角色面板没有本次查看外观来源。')
        data['proofs'][name]['appearance']=action['exchange_appearance']
    return None


def after_close(session, choice, scene, confidence=.65):
    data = _active(session)
    cells = _board(scene,data,confidence)
    if choice.intent == 'close_standard_exchange_stale_panel':
        session.pop('inspecting',None)
        return
    inspecting = session['inspecting']
    name = key(inspecting['zone'],inspecting['slot'])
    proof = data['proofs'].get(name,{})
    if (_proof_current(scene,data,name,proof,cells) and proof.get('input_epoch') == session.get('account_verified_epoch')
            and proof.get('run_dir') == session.get('account_verified_run')):
        proof['closed'] = True
        if data.get('empty'):
            proof['returned_signature']=cells[name].signature
            record=session['collection']['units'][name]
            record.update(inspection_signature=proof['signature'],signature=cells[name].signature,
                          exchange_inspection_signature=proof['signature'],
                          exchange_parent_action_id=data['action_id'])
    if all(data['proofs'].get(name,{}).get('closed') and _proof_current(scene,data,name,data['proofs'][name],cells)
           and data['proofs'][name]['input_epoch'] == session.get('account_verified_epoch')
           and data['proofs'][name]['run_dir'] == session.get('account_verified_run') for name in data['expected']):
        data['status'] = 'verified'
        session['actions'][data['action_id']]['movement_verified'] = True
        session.setdefault('exchange_history',[]).append(json.loads(json.dumps(data)))
        session['action_status'] = 'exchange_verified'
