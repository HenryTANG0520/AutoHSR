"""One owned equipment drag, then an independently inspected worn result."""
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json

from .currency_wars_collector import collected_snapshot, owned_profile, roster_cells
from .currency_wars_deployment import backend_layout
from .currency_wars_equipment_catalog import BASICS, GEAR, RECIPES, inventory, inventory_counts
from .currency_wars_match import read_match
from .currency_wars_standard_sale import board_cells
from .currency_wars_standard_hud import experience_observed
from .models import AutomationError, Token

POLICY = 'owned-equipment-v1'


def gear_hash(items):
    return hashlib.sha256(json.dumps(sorted(items),separators=(',',':')).encode('ascii')).hexdigest()


def recipe_book(recipes=()):
    book = dict(RECIPES)
    for recipe in recipes:
        parts,product = recipe.get('components'),recipe.get('product')
        if (not isinstance(parts,(list,tuple)) or len(parts)!=2 or any(p not in BASICS for p in parts)
                or product not in GEAR-BASICS):
            raise AutomationError('当前推荐配方的材料或成品未完整核实。')
        key = tuple(sorted(parts))
        if key in book and book[key]!=product:
            raise AutomationError('当前配方与已有证据冲突，未合成。')
        book[key] = product
    return book


def resulting_gear(old, incoming, recipes=()):
    if old is None or incoming not in GEAR or len(old)>3 or any(item not in GEAR for item in old):
        return None
    basic = [item for item in old if item in BASICS]
    result = list(old)
    if incoming in BASICS and basic:
        product = recipe_book(recipes).get(tuple(sorted((basic[0],incoming)))) if len(basic)==1 else None
        if product is None:
            return None
        result.remove(basic[0]);result.append(product)
    elif len(result)<3:
        result.append(incoming)
    else:
        return None
    return tuple(sorted(result))


def choose_equipment(snapshot, cells, strategy='default', recommendations=None, recipes=None, *, fast_mode=False):
    from .currency_wars_equipment import available_slots
    from .currency_wars_equipment_mode import generic_allowed,validate_fast_mode
    validate_fast_mode(fast_mode)
    field = tuple(unit for unit in snapshot.roster if unit.zone != 'bench')
    available = tuple(cell for cell in cells if cell.name in GEAR)
    if not snapshot.roster_complete or len(field) != snapshot.capacity or not available:
        return None
    if strategy not in ('default','aglaea','seele'):
        raise AutomationError('装备策略不在本局冻结范围内。')
    core = next((unit for unit in field if unit.name == ('阿格莱雅' if strategy=='aglaea' else '希儿')),None)
    if strategy != 'default':
        if core is None or core.equipment is None:
            return None
        worn = Counter(core.equipment)
        complete = (worn['shoe']+2*worn['boots']>=4 and worn['propeller']>=1 if strategy=='aglaea'
                    else worn['firestorm']>=2 and worn['chainsaw']>=1)
        if not complete:
            desired = ('boots','shoe','propeller') if strategy=='aglaea' else ('firestorm','chainsaw','shoe','star','knife')
            for name in desired:
                for cell in available:
                    if cell.name != name:
                        continue
                    expected = resulting_gear(core.equipment,name,(recipes or {}).get(core.zone+':'+str(core.slot),()))
                    if expected is None:
                        continue
                    new = Counter(expected)
                    if strategy=='aglaea':
                        old_speed,new_speed = worn['shoe']+2*worn['boots'],new['shoe']+2*new['boots']
                        useful = (old_speed < new_speed <= 4 or new['propeller']>worn['propeller']==0)
                    else:
                        useful = (new['firestorm']>worn['firestorm'] and worn['firestorm']<2
                                  or new['chainsaw']>worn['chainsaw'] and worn['chainsaw']<1)
                        # Reserve both ingredients before starting a known pair;
                        # each material still has its own drag and worn proof.
                        if not useful and not any(item in BASICS for item in core.equipment):
                            counts = Counter(c.name for c in available)
                            useful = (name=='shoe' and worn['firestorm']<2 and counts['knife']>0
                                      or name=='star' and worn['chainsaw']<1 and counts['knife']>0)
                    if useful:
                        return core,cell,expected,'策略核心优先；使用已观察的成品或有来源的配方材料'
            return None  # Preserve core materials until its intended loadout is complete.
    if not generic_allowed(snapshot,fast_mode):return None
    for unit in sorted(field,key=lambda u:(-(u.tier or 0),-(u.star or 0),u.zone!='front',u.slot)):
        if unit.equipment is None:
            continue
        names = (recommendations or {}).get(unit.zone+':'+str(unit.slot),())
        formulas = (recipes or {}).get(unit.zone+':'+str(unit.slot),())
        book = recipe_book(formulas)
        for cell in sorted(available,key=lambda c:(names.index(c.name) if c.name in names else 99,c.slot)):
            expected = resulting_gear(unit.equipment,cell.name,formulas)
            if expected is None:
                continue
            if names:
                combines = cell.name in BASICS and any(item in BASICS for item in unit.equipment)
                allowed = (any(result in names and result not in unit.equipment for result in expected) if combines
                           else cell.name in names)
                if not allowed and cell.name in BASICS and not any(item in BASICS for item in unit.equipment):
                    counts = Counter(c.name for c in available)
                    allowed = any(product in names and cell.name in parts and
                                  not (Counter(parts)-counts) for parts,product in book.items())
            else:
                # Retain the four previously calibrated native defaults when
                # loading an older collection without recommendation evidence.
                padded = tuple(unit.equipment)+('empty',)*(3-len(unit.equipment))
                allowed = cell.name in ('battery','armor','hard_armor','energy_sail') and available_slots(unit,padded,cell.name)
            if allowed:
                return unit,cell,expected,'按当前角色已读推荐排序；保留已有装备并核实合成结果'
    return None


@dataclass(frozen=True)
class EquipmentPlan:
    start: tuple
    end: tuple
    zone: str
    target_slot: int
    source_slot: int
    backend_slots: int = 6


def proposal(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_standard_trading import _scope
    from .currency_wars_market import overclock_board
    prior = _scope(session,'stage_standard_equipment')
    snapshot = collected_snapshot(scene,prior,prior['collection']['input_epoch'],'standard_equipment',confidence)
    if (snapshot.mode != 'standard' or snapshot.game_version != '4.6' or snapshot.rules_version != '4.6'
            or snapshot.transaction_status != 'clear' or snapshot.hp is None or snapshot.hp<=0
            or snapshot.gold is None or not experience_observed(scene,snapshot,confidence)
            or backend_layout(scene.image)[0]!=6 or overclock_board(scene)):
        raise AutomationError('装备分配缺少本局版本、完整阵容或清晰余额来源。')
    recommendations = {key:record.get('recommendations',()) for key,record in prior['collection']['units'].items()}
    recipes = {key:record.get('equipment_recipes',()) for key,record in prior['collection']['units'].items()}
    from .currency_wars_equipment_mode import stored_fast_mode
    chosen = choose_equipment(snapshot,inventory(scene,confidence),prior.get('strategy','default'),recommendations,recipes,
                              fast_mode=stored_fast_mode(prior))
    if chosen is None:
        return None
    unit,item,expected,reason = chosen
    cell = next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==(unit.zone,unit.slot))
    return StandardAction('stage_standard_equipment','standard_equipment_inspectable',
                          EquipmentPlan(item.point,cell.point,cell.zone,cell.slot,item.slot),
                          details=(unit.name,item.name,expected,reason,POLICY),
                          payload=(snapshot.node,snapshot.gold,snapshot.hp,snapshot.level,item.name,item.slot,
                                   cell.zone,cell.slot,item.signature,cell.signature,unit.name,unit.star,unit.tier,
                                   gear_hash(unit.equipment),gear_hash(expected)))


def bind_intent(session, choice, scene, confidence=.65):
    from .currency_wars_standard_trading import _scope
    prior = _scope(session,'stage_standard_equipment')
    state = read_match(scene,confidence)
    key = choice.payload[6]+':'+str(choice.payload[7])
    old = session['collection']['units'][key]
    expected = dict(old['unit'],equipment=list(choice.details[2]))
    if gear_hash(old['unit']['equipment']) != choice.payload[13] or gear_hash(expected['equipment']) != choice.payload[14]:
        raise AutomationError('装备意图的前后槽位与已采集角色不一致。')
    session['actions'][-1]['equipment_expected'] = dict(unit=json.loads(json.dumps(expected)),
        recommendations=old.get('recommendations',[]),equipment_recipes=old.get('equipment_recipes',[]),cells=board_cells(scene,confidence),
        board=[state.node,state.gold,state.hp,state.level,list(state.deployment),list(state.experience) if state.experience is not None else None],
        max_level_verified=state.level==10,
        counts=dict(inventory_counts(inventory(scene,confidence))),input_epoch=prior['collection']['input_epoch'],
        run_dir=prior['collection']['run_dir'])


def inspectable(choice, before, after, confidence=.65):
    first,last = read_match(before,confidence),read_match(after,confidence)
    if (not first or not last or first.page!='preparation' or last.page!='preparation'
            or not experience_observed(before,first,confidence) or not experience_observed(after,last,confidence)
            or (first.node,first.gold,first.hp,first.level)!=choice.payload[:4]
            or (last.node,last.gold,last.hp,last.level,last.deployment,last.experience) !=
               (first.node,first.gold,first.hp,first.level,first.deployment,first.experience)):
        return False
    try:
        old,new = inventory(before,confidence),inventory(after,confidence)
        source = next(cell for cell in old if cell.slot==choice.payload[5])
        expected = inventory_counts(old);expected[choice.payload[4]] -= 1
        return (source.name==choice.payload[4] and source.signature==choice.payload[8]
                and inventory_counts(new)==+expected and board_cells(before,confidence)==board_cells(after,confidence))
    except AutomationError:
        return False


def begin_verification(session, choice, before, after, confidence=.65):
    if not inspectable(choice,before,after,confidence):
        raise AutomationError('装备拖动后的仓库变化尚未核实。')
    action = session['actions'][-1]
    session['equipment'] = dict(action_id=action['id'],status='verifying',
                                expected=action['equipment_expected'],counts=dict(inventory_counts(inventory(after,confidence))),
                                proof=None,inspection_attempts=0)
    action['equipment_verified'] = False
    key = choice.payload[6]+':'+str(choice.payload[7])
    session['collection']['units'].pop(key,None)
    session['collection']['complete'] = False


def _active(session):
    data = session.get('equipment')
    if not data or data.get('status')=='verified':
        return None
    index = data.get('action_id')
    actions = session.get('actions',[])
    if (data.get('status')!='verifying' or type(index) is not int or not 0<=index<len(actions)
            or actions[index].get('action')!='stage_standard_equipment' or actions[index].get('status')!='verified'
            or actions[index].get('equipment_expected')!=data.get('expected')):
        raise AutomationError('上次装备结果未核实，未再次穿戴或开始战斗。')
    return data


def panel_stale(session):
    data = _active(session)
    if data is None:
        return False
    inspecting = session.get('inspecting',{})
    return (inspecting.get('equipment_id')!=data.get('action_id')
        or inspecting.get('input_epoch')!=session.get('account_verified_epoch')
        or inspecting.get('run_dir')!=session.get('account_verified_run'))


def _board(scene, data, confidence):
    state = read_match(scene,confidence)
    lock = data['expected']['board']
    if (not state or state.page!='preparation'
            or not experience_observed(scene,state,confidence)
            or state.level==10 and data['expected'].get('max_level_verified') is not True
            or [state.node,state.gold,state.hp,state.level,list(state.deployment or ()),
                list(state.experience) if state.experience is not None else None]!=lock
            or board_cells(scene,confidence)!=data['expected']['cells']
            or inventory_counts(inventory(scene,confidence))!=Counter(data['counts'])):
        raise AutomationError('装备核验备战页的节点、余额、阵容或仓库已变。')
    return {(cell.zone,cell.slot):cell for cell in roster_cells(scene,confidence)}


def active_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    data = _active(session)
    if data is None:
        return None
    state = read_match(scene,confidence)
    if state and state.page=='character':
        stale = panel_stale(session)
        if not stale and not data.get('proof'):
            raise AutomationError('当前装备面板尚未记录独立穿戴证据。')
        if not stale:
            actual = owned_profile(scene,session['inspecting'],confidence)
            if json.loads(json.dumps(asdict(actual))) != data['proof']['unit']:
                raise AutomationError('当前装备面板与已读取结果不同，未关闭或标记完成。')
        return StandardAction('close_standard_equipment_stale_panel' if stale else 'close_standard_equipment_unit',
                              'standard_equipment_board',Token('关闭装备核验面板',1.,(.49,.49,.51,.51)),
                              payload=tuple(data['expected']['board'][:4])+(data['action_id'],))
    cells = _board(scene,data,confidence)
    unit = data['expected']['unit'];cell = cells[(unit['zone'],unit['slot'])]
    pending = session.get('rederiving_action') or {}
    if data['inspection_attempts']>=4 and pending.get('action')!='inspect_standard_equipment_unit':
        raise AutomationError('装备结果查看达到上限，未重新拖动。')
    x,y = cell.point
    return StandardAction('inspect_standard_equipment_unit','character',
                          Token('核实实际穿戴结果',1.,(x-.01,y-.01,x+.01,y+.01)),
                          payload=(cell.zone,cell.slot,cell.node,cell.signature,data['action_id']))


def record_profile(session, profile, inspecting, source, epoch):
    data = _active(session)
    if data is None or panel_stale(session):
        return None
    expected = data['expected']['unit'];actual = json.loads(json.dumps(asdict(profile)))
    if (any(actual[k]!=expected[k] for k in ('name','zone','slot','star','tier')) or profile.equipment is None
            or Counter(profile.equipment)!=Counter(expected['equipment'])):
        data.update(status='equipment_mismatch',actual=actual,source=source)
        return '实际穿戴结果或目标角色不符，未再次拖动、交易或出战。'
    data['proof'] = dict(unit=actual,signature=inspecting['signature'],input_epoch=epoch,
                         run_dir=session.get('account_verified_run'),source=source)
    record = session['collection']['units'][profile.zone+':'+str(profile.slot)]
    record['recommendations'] = data['expected'].get('recommendations',[])
    record['equipment_recipes'] = data['expected'].get('equipment_recipes',[])
    return None


def after_close(session, choice, scene, confidence=.65):
    data = _active(session);cells = _board(scene,data,confidence)
    if choice.intent=='close_standard_equipment_stale_panel':
        data['proof'] = None
        session.pop('inspecting',None)
        return
    proof = data.get('proof') or {};unit = data['expected']['unit']
    if (proof.get('signature')!=cells[(unit['zone'],unit['slot'])].signature
            or proof.get('input_epoch')!=session.get('account_verified_epoch')
            or proof.get('run_dir')!=session.get('account_verified_run')):
        raise AutomationError('装备结果面板返回后来源已过期。')
    data['status']='verified'
    session['actions'][data['action_id']]['equipment_verified']=True
    session.setdefault('equipment_history',[]).append(json.loads(json.dumps(data)))
