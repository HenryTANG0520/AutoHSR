"""Typed equipped-sale targets and exact observed inventory-return proofs."""
from collections import Counter
from dataclasses import asdict
import json
import re

from .currency_wars_consumables import stock,counts,TOOLS
from .currency_wars_equipment_catalog import GEAR
from .models import AutomationError

TAG='gear-return-v1:'


def known(worn):
    return isinstance(worn,(tuple,list)) and 1<=len(worn)<=3 and all(type(name) is str and name in GEAR for name in worn)


def suffix(zone,worn):
    if not known(worn):raise AutomationError('携装出售的装备种类或数量未核实。')
    return zone,TAG+json.dumps(list(worn),separators=(',',':'))


def equipment(target):
    if not target or not isinstance(target[-1],str) or not target[-1].startswith(TAG):return ()
    if len(target) not in (12,14) or target[-2] not in ('front','back','bench'):
        raise ValueError('携装出售目标长度或区域无效')
    value=json.loads(target[-1][len(TAG):])
    if not known(value) or suffix(target[-2],value)[1]!=target[-1]:raise ValueError('携装出售目标装备无效')
    return tuple(value)


def validate_inventory(data):
    if type(data) is not dict or set(data)!={'cells','counts','capacity'}:raise ValueError('装备返还库存来源无效')
    cells=data['cells'];counts=Counter();free=0
    if not isinstance(cells,list) or len(cells)!=14:raise ValueError('装备返还库存不完整')
    for index,cell in enumerate(cells):
        if (type(cell) is not dict or set(cell)!={'slot','name','quantity','signature','textured'}
                or type(cell['slot']) is not int or cell['slot']!=index or type(cell['textured']) is not bool
                or not isinstance(cell['signature'],str) or re.fullmatch('[0-9a-f]{64}',cell['signature']) is None):
            raise ValueError('装备返还库存格无效')
        name,quantity=cell['name'],cell['quantity']
        if name is None:
            if quantity is not None or cell['textured']:raise ValueError('装备返还前存在未知库存')
            free+=int(index<12)
        elif name in GEAR and type(quantity) is int and quantity==1:counts[name]+=1
        elif name in TOOLS and type(quantity) is int and 0<=quantity<=99999:counts[name]+=quantity
        elif name in TOOLS and quantity=='infinite':counts[name+':infinite']+=1
        else:raise ValueError('装备返还库存名称或数量未核实')
    counts=+counts
    if (type(data['counts']) is not dict or any(type(v) is not int or v<=0 for v in data['counts'].values())
            or dict(counts)!=data['counts'] or type(data['capacity']) is not int or data['capacity']!=min(3,free)):
        raise ValueError('装备返还库存汇总或空位不符')
    return counts


def inventory(scene,confidence=.65):
    observed=stock(scene,confidence)
    cells=[dict(slot=c.slot,name=c.name,quantity=c.quantity,signature=c.signature,textured=c.textured) for c in observed]
    result=dict(cells=cells,counts=dict(counts(observed)),
                capacity=min(3,sum(c['slot']<12 and c['name'] is None and not c['textured'] for c in cells)))
    validate_inventory(result)
    return result


def capacity(scene,snapshot,confidence=.65):
    if not any(known(u.equipment) for u in snapshot.roster):return 0
    try:return inventory(scene,confidence)['capacity']
    except (AutomationError,TypeError,ValueError):return 0


def return_proof(before,after,worn):
    expected=validate_inventory(before)+Counter(worn)
    actual=validate_inventory(after)
    if actual!=expected:raise ValueError('出售后的装备未逐项返还，或其他库存发生变化')
    return dict(schema=1,equipment=list(worn),stock_before=dict(validate_inventory(before)),stock_after=dict(actual))


def valid_return(receipt,target):
    try:
        worn=equipment(target);proof=receipt.get('equipment_return')
        if not worn:return proof is None
        if type(receipt.get('schema')) is not int:return False
        if type(proof) is not dict or set(proof)!={'schema','equipment','stock_before','stock_after'}:return False
        if type(proof['schema']) is not int or proof['schema']!=1 or proof['equipment']!=list(worn):return False
        for side in ('stock_before','stock_after'):
            if type(proof[side]) is not dict or any(type(v) is not int or v<=0 or
                    k not in GEAR and k not in TOOLS and k not in {t+':infinite' for t in TOOLS} for k,v in proof[side].items()):return False
        return Counter(proof['stock_before'])+Counter(worn)==Counter(proof['stock_after'])
    except (TypeError,ValueError):return False


def valid_source(action,inspection):
    try:
        worn=equipment(action['target']);basis=inspection.get('equipped_sale_basis')
        if not worn:return basis is None and valid_return(action['receipt'],action['target'])
        from .currency_wars_standard_sale import choose_sale,inspection_target,target_zone,same_target,board_digest
        from .currency_wars_state import StrategySnapshot
        if (type(basis) is not dict or not same_target(basis['inspect_target'],inspection['target'])
                or not same_target(inspection_target(action['target']),inspection['target'])
                or basis['inspect_action_id']!=inspection['id'] or type(basis['input_epoch']) is not int
                or basis['input_epoch']!=inspection['input_epoch'] or basis['input_epoch']!=action['input_epoch']
                or not isinstance(basis['run_dir'],str) or not basis['run_dir']
                or board_digest(basis['cells'])!=action['target'][9]
                or basis['cells']!=action['receipt']['cells_before']):return False
        bank=validate_inventory(basis['inventory'])
        if basis['inventory']['capacity']<len(worn) or dict(bank)!=action['receipt']['equipment_return']['stock_before']:return False
        if target_zone(action['target'])!='bench' and inspection.get('field_sale_basis',{}).get('inventory')!=basis['inventory']:return False
        snapshot=StrategySnapshot.from_dict(json.loads(json.dumps(basis['snapshot'])))
        if (not snapshot.roster_complete or not snapshot.known('roster','roster_complete','node','gold','hp','level','capacity','mode','rank','wealth','game_version','rules_version')
                or (snapshot.mode,snapshot.rank,snapshot.wealth,snapshot.game_version,snapshot.rules_version)!=('standard',8,40,'4.6','4.6')
                or snapshot.transaction_status!='clear'
                or [snapshot.node,snapshot.gold,snapshot.hp,snapshot.level]!=action['target'][:4]
                or snapshot.input_epoch!=basis['input_epoch']):return False
        chosen=choose_sale(snapshot,basis['strategy'],equipped_capacity=basis['inventory']['capacity'])
        if chosen is None:return False
        unit,reason=chosen
        return (same_target(asdict(unit),basis['unit']) and reason==basis['reason'] and tuple(unit.equipment)==worn
                and (unit.zone,unit.slot,unit.name,unit.star,unit.tier)==(target_zone(action['target']),*action['target'][4:8])
                and valid_return(action['receipt'],action['target']))
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False
