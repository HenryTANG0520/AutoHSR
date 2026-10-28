"""Typed free rewards with origin custody and independent delivered effects."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import re

import numpy as np

from .currency_wars import observe
from .currency_wars_collector import collected_snapshot, first_unit_probe, owned_profile, roster_cells
from .currency_wars_deployment import _crop
from .currency_wars_equipment_catalog import GEAR, NAMES, inventory, inventory_counts
from .currency_wars_match import read_match, unit_name
from .currency_wars_prepare import trusted
from .currency_wars_standard_ledger import ledger_status
from .currency_wars_standard_policy import PREFERRED
from .models import AutomationError, Token, normalize

PAGES = frozenset(('equipment_selection','advanced_equipment_selection','expert_selection','supply_selection'))
ITEM_IDS = {name:key for key,name in NAMES.items() if key in GEAR}
POLICY = 'standard-rewards-v1'


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def _scope(session, intent):
    from .currency_wars_standard_trading import _prior
    prior = _prior(session,intent)
    collection,client = prior.get('collection',{}),prior.get('client',{})
    if (prior.get('status')!='active' or not prior.get('start_verified') or not prior.get('entry',{}).get('rank_verified')
            or not prior.get('account_key') or prior.get('account_verified_run')!=collection.get('run_dir')
            or prior.get('account_verified_epoch')!=collection.get('input_epoch')
            or client.get('verified_run')!=collection.get('run_dir') or client.get('input_epoch')!=collection.get('input_epoch')
            or client.get('version')!='4.6' or prior.get('rules_version')!='4.6'
            or ledger_status(prior.get('actions',[]))!='clear'):
        raise AutomationError('标准奖励缺少同局、账号、版本或已核实动作来源。')
    return prior


def basis(scene, session, intent, confidence=.65):
    prior = _scope(session,intent)
    state = read_match(scene,confidence)
    if (not state or state.page!='preparation' or not state.node or state.gold is None or state.hp is None
            or state.hp<=0 or state.level is None or state.experience is None or not state.deployment):
        raise AutomationError('领取前备战节点、余额、生命、等级或人数不完整。')
    snapshot = collected_snapshot(scene,prior,prior['collection']['input_epoch'],'reward_origin',confidence,allow_reward_items=True)
    cells = {c.zone+':'+str(c.slot):[c.state,c.signature] for c in roster_cells(scene,confidence)}
    return dict(node=state.node,gold=state.gold,hp=state.hp,level=state.level,experience=list(state.experience),
                deployment=list(state.deployment),cells=cells,inventory=dict(inventory_counts(inventory(scene,confidence))),
                snapshot=json.loads(json.dumps(asdict(snapshot))),run_dir=prior['collection']['run_dir'],
                input_epoch=prior['collection']['input_epoch'])


def bind_source(session, choice, scene, confidence=.65):
    try:
        session['actions'][-1]['reward_basis'] = basis(scene,session,choice.intent,confidence)
    except AutomationError as error:
        if choice.intent!='collect_standard_loot':raise
        # Preserve the existing bounded disappearance-only collector. A later
        # modal cannot use this missing basis to authorize any reward input.
        session['actions'][-1]['reward_basis_missing'] = str(error)


def open_bench_action(scene, session, confidence=.65):
    from .currency_wars_rewards import open_reward_target
    from .currency_wars_standard_flow import StandardAction
    if not any(normalize(t.text)=='开启' and t.within((.18,.78,.80,.92)) for t in trusted(scene,confidence).tokens):
        return None
    slot,target = open_reward_target(scene,confidence)
    source = basis(scene,session,'open_standard_bench_reward',confidence)
    if source['cells']['bench:'+str(slot)][0]!='reward':
        raise AutomationError('待开启位置没有对应的奖励物品，未点击。')
    return StandardAction('open_standard_bench_reward','standard_reward_opened',target,
                          payload=(source['node'],slot,source['cells']['bench:'+str(slot)][1]))


def _hud(scene, confidence):
    state = read_match(scene,confidence,include_rewards=True)
    if not state or not state.node:
        raise AutomationError('当前奖励页面的节点未核实。')
    return state


def _active(session):
    data = session.get('reward')
    if not data or data.get('status')=='verified':
        return None
    index = data.get('origin_action_id')
    actions = session.get('actions',[])
    if (data.get('status') not in ('awaiting','unit_verifying') or type(index) is not int or not 0<=index<len(actions)
            or actions[index].get('status')!='verified' or not actions[index].get('after')):
        raise AutomationError('上次奖励效果或来源未核实，未重复选择或继续交易。')
    return data


def enter(session, choice, scene, confidence=.65):
    kind = observe(scene,confidence).page_kind
    if kind not in PAGES:
        return
    action = session['actions'][-1]
    if choice.intent in ('collect_standard_loot','open_standard_bench_reward'):
        source = action.get('reward_basis')
    elif choice.intent=='continue_standard_node' and kind=='supply_selection':
        start = session.get('node_attempt',{}).get('start_action_id')
        source = session['actions'][start].get('reward_basis') if type(start) is int else None
        if not source or not source['snapshot'].get('roster_complete'):
            raise AutomationError('补给到达缺少本次出战前完整持有阵容。')
        source = json.loads(json.dumps(source))
        source['node'] = action['feedback']['node']
    else:
        return
    state = _hud(scene,confidence)
    if not source:
        return  # Existing loot collection may stop here for missing new facts.
    if state.node!=source['node']:
        raise AutomationError('奖励候选与已核实开启／节点到达来源不一致。')
    source = json.loads(json.dumps(source))
    source['modal_fields'] = []
    for name in ('gold','hp','level','experience','deployment'):
        value = getattr(state,name)
        if value is not None:
            source[name] = list(value) if isinstance(value,tuple) else value
            source['modal_fields'].append(name)
    if state.gold is not None:
        source['gold'] = state.gold
    session['reward'] = dict(status='awaiting',page=kind,origin_action_id=action['id'],basis=source,
                             same_node_supply_allowed=session.get('environment',{}).get('kind')=='boss_supply',
                             money_observed=state.gold is not None,box_slot=choice.payload[1]
                             if choice.intent=='open_standard_bench_reward' else None)
    action['reward_allow_same_node'] = session['reward']['same_node_supply_allowed']
    action['reward_verified'] = False


def _options(scene, kind, confidence):
    clean = trusted(scene,confidence)
    result = []
    if kind=='expert_selection':
        cash = [t for t in clean.tokens if normalize(t.text)=='现金为王' and t.within((.2,.30,.9,.39))]
        if len(cash)!=1:
            raise AutomationError('邀请函现金候选未唯一核实。')
        x = cash[0].center[0]
        amounts = {normalize(t.text) for t in clean.tokens if t.within((x-.06,.25,x+.06,.30))}
        if len(amounts)!=1 or not re.fullmatch(r'[0-9]{1,2}',next(iter(amounts))):
            raise AutomationError('邀请函实际金币数未独立核实，未按旧常量领取。')
        return ((0,'现金为王',None,None,int(next(iter(amounts))),cash[0]),)
    if kind=='supply_selection':
        names = sorted([t for t in clean.tokens if t.within((.03,.50,.97,.55))
                        and re.fullmatch(r'[\u4e00-\u9fffa-z0-9·.]{1,40}',normalize(t.text))],key=lambda t:t.center[0])
        if len(names) not in (4,5) or len({unit_name(t.text) for t in names})!=len(names):
            raise AutomationError('补给四／五组角色名称不完整或重复。')
        for i,name in enumerate(names):
            x = name.center[0]
            items = [t for t in clean.tokens if t.within((x-.085,.61,x+.085,.67))
                     and re.fullmatch(r'[\u4e00-\u9fff]{2,20}',normalize(t.text))]
            if len(items)!=1 or i and x-names[i-1].center[0]<.12:
                raise AutomationError('补给角色与装备未成对唯一识别。')
            item = normalize(items[0].text)
            result.append((i,unit_name(name.text),ITEM_IDS.get(item),unit_name(name.text),0,name))
    else:
        for i,x in enumerate((.346,.497,.647,.799)):
            names = [t for t in clean.tokens if t.within((x-.065,.25,x+.065,.29))
                     and re.fullmatch(r'[\u4e00-\u9fff]{2,20}',normalize(t.text))]
            if len(names)!=1:
                raise AutomationError('武装箱四格装备名称未完整识别。')
            name = normalize(names[0].text)
            result.append((i,name,ITEM_IDS.get(name),None,0,names[0]))
    return tuple(result)


def _priority(data, strategy):
    units = data['basis']['snapshot'].get('roster',[])
    core = '阿格莱雅' if strategy=='aglaea' else '希儿'
    if strategy in ('aglaea','seele') and (not data['basis']['snapshot'].get('roster_complete')
            or any(unit['name']==core and unit.get('equipment') is None for unit in units)):
        raise AutomationError('核心策略奖励缺少完整持有阵容或实际核心装备，未按空装备推断。')
    worn = Counter(item for unit in units if unit['name']==core for item in unit.get('equipment') or ())
    if strategy=='aglaea' and worn['shoe']+2*worn['boots']<4:
        return ('boots','shoe','propeller','hard_armor','armor','battery')
    if strategy=='seele':
        stock = Counter(data['basis']['inventory'])+worn
        needed = []
        if worn['firestorm']<2:
            needed += ['shoe'] if stock['knife'] and not stock['shoe'] else ['knife'] if stock['shoe'] else []
            needed += ['firestorm','knife','shoe']
        if worn['chainsaw']<1:
            needed += ['star'] if stock['knife'] and not stock['star'] else ['knife'] if stock['star'] else []
            needed += ['chainsaw','knife','star']
        return tuple(dict.fromkeys(needed+['hard_armor','armor','battery']))
    return ('armor','battery','hard_armor','energy_sail','knife','star','shoe','boots','propeller','pistol','drill','life_flower','firestorm','chainsaw')


def _chosen(scene, data, strategy, confidence):
    options = _options(scene,data['page'],confidence)
    if data['page']=='expert_selection':
        return options[0],options
    priorities = _priority(data,strategy)
    units = data['basis']['snapshot'].get('roster',[])
    owned = {unit['name'] for unit in units}
    ranking = []
    for option in options:
        if option[2] is None:
            continue  # Unidentified effects cannot become a default first choice.
        score = 100-5*priorities.index(option[2]) if option[2] in priorities else 5
        if option[3] and strategy!='default' and option[3] in PREFERRED[strategy]:
            index = PREFERRED[strategy].index(option[3])
            highest = max((u.get('star') or 0 for u in units if u['name']==option[3]),default=0)
            score += 100 if index==0 and highest<3 else max(10,45-index*3) if option[3] not in owned else 0
        ranking.append((-score,option[0],option))
    if not ranking:
        raise AutomationError('奖励没有已识别效果的可核验候选，未默认第一项。')
    return min(ranking,key=lambda item:item[:2])[2],options


def _selected_supply(scene, option, options, confidence):
    from .currency_wars_supply import supply_count
    if supply_count(scene,confidence)!=1 or scene.image is None:
        return False
    highlighted = []
    for entry in options:
        x = entry[5].center[0]
        region = _crop(scene.image,(x-.065,.59,x+.065,.69))
        if region.size and np.mean(np.min(region,axis=2)>180)>.6:
            highlighted.append(entry[0])
    return highlighted==[option[0]]


def active_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    data = _active(session)
    if data is None:
        if observe(scene,confidence).page_kind in PAGES:
            raise AutomationError('当前奖励缺少本局已核实开启或到达来源，未选择。')
        return None
    if data['status']=='unit_verifying':
        return _unit_action(scene,session,data,confidence)
    prior = _scope(session,'confirm_standard_supply' if observe(scene,confidence).page_kind=='supply_selection'
                   and session.get('actions') and session['actions'][-1].get('action')=='select_standard_supply' else 'choose_standard_reward')
    state = _hud(scene,confidence)
    if state.page!=data['page'] or state.node!=data['basis']['node'] or state.gold not in (None,data['basis']['gold']):
        raise AutomationError('奖励候选的页面、节点或已观察余额已变。')
    option,options = _chosen(scene,data,prior.get('strategy','default'),confidence)
    if data['page']=='expert_selection' and (not data['money_observed'] or state.gold is None):
        raise AutomationError('邀请函领取前当前金币不可见，未用旧余额推断到账。')
    descriptors = [list(o[:5]) for o in options]
    payload = (state.node,data['origin_action_id'],data['page'],option[0],option[1],option[2],option[3],option[4],_digest(descriptors))
    intent,expected,target = 'choose_standard_reward','standard_reward_returned',option[5]
    if data['page']=='supply_selection':
        from .currency_wars_supply import supply_count
        count = supply_count(scene,confidence)
        if count==0:
            intent,expected = 'select_standard_supply','standard_supply_selected'
        else:
            previous = prior.get('actions',[])[-1] if prior.get('actions') else {}
            if (previous.get('action')!='select_standard_supply' or previous.get('target')!=list(payload)
                    or not _selected_supply(scene,option,options,confidence)):
                raise AutomationError('补给选中项与已落盘的本次选择不一致，未确认。')
            from .currency_wars_navigation import unique
            intent = 'confirm_standard_supply'
            target = unique(trusted(scene,confidence),'确认',(.85,.885,.93,.94))
    return StandardAction(intent,expected,target,details=(option[1],option[2],option[3],option[4],POLICY),payload=payload)


def feedback(choice, before, after, session, confidence=.65):
    data = _active(session)
    if data is None or data['status']!='awaiting':
        return False
    if choice.expected=='standard_supply_selected':
        try:
            option,options = _chosen(after,data,session.get('strategy','default'),confidence)
            return _digest([list(o[:5]) for o in options])==choice.payload[8] and _selected_supply(after,option,options,confidence)
        except AutomationError:
            return False
    state = read_match(after,confidence)
    expected_nodes = {choice.payload[0]}
    if data['page']=='supply_selection':
        plane,number = map(int,choice.payload[0].split('-'))
        expected_nodes = {f'{plane}-{number+1}'}
        if data.get('same_node_supply_allowed'):expected_nodes.add(choice.payload[0])
    if not state or state.page!='preparation' or state.node not in expected_nodes or state.gold is None or state.hp is None or state.hp<=0:
        return False
    if (data['money_observed'] or data['page']!='supply_selection') and state.gold!=data['basis']['gold']+choice.payload[7]:
        return False
    strict = data['page']!='supply_selection'
    if (not state.deployment or state.level is None or state.experience is None
            or (strict or 'hp' in data['basis']['modal_fields']) and state.hp!=data['basis']['hp']
            or (strict or 'level' in data['basis']['modal_fields']) and state.level!=data['basis']['level']
            or (strict or 'experience' in data['basis']['modal_fields']) and state.experience!=tuple(data['basis']['experience'])
            or (strict or 'deployment' in data['basis']['modal_fields']) and state.deployment!=tuple(data['basis']['deployment'])):
        return False
    try:
        old,new = Counter(data['basis']['inventory']),inventory_counts(inventory(after,confidence))
        if choice.payload[5]:old[choice.payload[5]]+=1
        if old!=new:
            return False
        if not choice.payload[6]:
            cells = {c.zone+':'+str(c.slot):[c.state,c.signature] for c in roster_cells(after,confidence)}
            for key,value in data['basis']['cells'].items():
                if key=='bench:'+str(data.get('box_slot')):
                    if cells[key][0]!='empty':return False
                elif cells[key]!=value:return False
            return state.deployment==tuple(data['basis']['deployment'])
        return True
    except AutomationError:
        return False


def returned(session, choice, scene, confidence=.65):
    data = _active(session);action = session['actions'][-1]
    state = read_match(scene,confidence)
    action['reward_effect'] = dict(node=choice.payload[0],node_after=state.node,origin_action_id=data['origin_action_id'],page=data['page'],
        name=choice.payload[4],item=choice.payload[5],unit=choice.payload[6],gold=choice.payload[7],
        gold_before=data['basis']['gold'] if data['money_observed'] or data['page']!='supply_selection' else None,gold_after=state.gold,
        inventory_checked=True,unit_verified=not bool(choice.payload[6]))
    action['reward_verified'] = not bool(choice.payload[6])
    data.update(claim_action_id=action['id'],choice=list(choice.payload),
                after_board=[state.node,state.gold,state.hp,state.level,list(state.deployment),list(state.experience)],
                after_inventory=dict(inventory_counts(inventory(scene,confidence))))
    if choice.payload[6]:
        data['status']='unit_verifying'
        session.pop('collection',None)
    else:
        _finish(session)


def _finish(session, preserve_collection=False):
    data = session['reward'];data['status']='verified'
    session['actions'][data['origin_action_id']]['reward_verified']=True
    session['actions'][data['claim_action_id']]['reward_verified']=True
    session.setdefault('reward_history',[]).append(json.loads(json.dumps(data)))
    session['action_status']='reward_verified'
    if not preserve_collection:session.pop('collection',None)
    node = data['basis']['node']
    if node in session.get('shop_observed_nodes',[]):session['shop_observed_nodes'].remove(node)


def _unit_action(scene, session, data, confidence):
    from .currency_wars_standard_flow import StandardAction
    state = read_match(scene,confidence)
    if not state:
        raise AutomationError('补给角色核验需要当前备战或角色面板。')
    if state.page=='character':
        inspecting = session.get('inspecting',{})
        if panel_stale(session):
            intent = 'close_standard_reward_stale_panel'
        else:
            profile = owned_profile(scene,inspecting,confidence)
            record = session.get('collection',{}).get('units',{}).get(profile.zone+':'+str(profile.slot),{})
            if record.get('unit')!=asdict(profile):
                raise AutomationError('补给核验的当前角色尚未记入新采集。')
            intent = 'close_standard_reward_unit'
        return StandardAction(intent,'standard_reward_unit_board',Token('关闭补给角色核验面板',1.,(.49,.49,.51,.51)))
    if not board_ready(scene,data,confidence):
        raise AutomationError('补给核验时的节点、余额、人数或仓库已变。')
    probe = first_unit_probe(scene,confidence,session.get('collection',{}).get('units'))
    if probe is None:
        raise AutomationError('补给全部角色已采集，仍缺结果核实记录。')
    cell,target = probe
    return StandardAction('inspect_standard_reward_unit','character',target,
                          payload=(cell.zone,cell.slot,cell.node,cell.signature))


def board_ready(scene, data, confidence=.65):
    state = read_match(scene,confidence)
    return bool(state and state.page=='preparation' and state.deployment and state.experience and
                [state.node,state.gold,state.hp,state.level,list(state.deployment),list(state.experience)]==data['after_board']
                and inventory_counts(inventory(scene,confidence))==Counter(data['after_inventory']))


def panel_stale(session):
    data = session.get('reward',{})
    inspecting = session.get('inspecting',{})
    return data.get('status')=='unit_verifying' and (inspecting.get('run_dir')!=session.get('account_verified_run')
        or inspecting.get('input_epoch')!=session.get('account_verified_epoch'))


def verify_unit(session, scene, epoch, confidence=.65):
    data = session.get('reward',{})
    if data.get('status')!='unit_verifying' or not session.get('collection',{}).get('complete'):
        return None
    if not board_ready(scene,data,confidence):
        return '补给角色核验时状态已变，未重复领取。'
    snapshot = collected_snapshot(scene,session,epoch,'delivered_supply',confidence)
    if not snapshot.roster_complete:
        return None
    name = data['choice'][6];before = data['basis']['snapshot'].get('roster',[])
    old = sorted((u['star'] for u in before if u['name']==name),reverse=True)
    new = sorted((u.star for u in snapshot.roster if u.name==name),reverse=True)
    others_old = Counter((u['name'],u['star'],u['tier'],tuple(u.get('equipment') or ())) for u in before if u['name']!=name)
    others_new = Counter((u.name,u.star,u.tier,tuple(u.equipment or ())) for u in snapshot.roster if u.name!=name)
    if (not data['basis']['snapshot'].get('roster_complete') or new<=old or others_old!=others_new):
        data.update(status='unit_mismatch',observed_stars=new,original_stars=old)
        return '补给角色或其余持有阵容未对应交付，原领取意图保留且不重放。'
    data.update(observed_stars=new,original_stars=old)
    effect = session['actions'][data['claim_action_id']]['reward_effect']
    effect.update(unit_verified=True,stars_before=old,stars_after=new,other_roster_verified=True)
    _finish(session,preserve_collection=True)
    return None


def valid_effect(action, actions):
    try:
        return _valid_effect(action,actions)
    except (AttributeError,IndexError,KeyError,TypeError,ValueError):
        return False  # A damaged local receipt cannot clear the ledger.


def _valid_effect(action, actions):
    target,effect = action.get('target',[]),action.get('reward_effect',{})
    if (not isinstance(target,(list,tuple)) or len(target)!=9 or not isinstance(effect,dict)
            or not isinstance(target[0],str) or not re.fullmatch(r'[1-3]-[1-9][0-9]?',target[0])
            or type(target[3]) is not int or not 0<=target[3]<=4 or not isinstance(target[4],str) or not 0<len(target[4])<=80
            or target[5] is not None and target[5] not in GEAR
            or not action.get('before') or not action.get('after')
            or type(target[1]) is not int or not 0<=target[1]<action.get('id',0)
            or not 0<=target[1]<len(actions) or actions[target[1]].get('status')!='verified'
            or actions[target[1]].get('action') not in ('collect_standard_loot','open_standard_bench_reward','continue_standard_node')
            or target[2] not in PAGES or not isinstance(target[8],str) or not re.fullmatch(r'[0-9a-f]{64}',target[8])
            or (effect.get('node'),effect.get('origin_action_id'),effect.get('page'),effect.get('name'),
                effect.get('item'),effect.get('unit'),effect.get('gold')) != (target[0],target[1],target[2],*target[4:8])
            or type(target[7]) is not int or not 0<=target[7]<=99 or effect.get('inventory_checked') is not True
            or type(effect.get('gold_after')) is not int or not 0<=effect['gold_after']<=99999):
        return False
    kind = target[2]
    if kind=='supply_selection':
        previous = actions[action['id']-1]
        if (action.get('action')!='confirm_standard_supply' or not isinstance(target[6],str)
                or target[4]!=target[6] or target[5] not in GEAR or target[7]!=0
                or previous.get('action')!='select_standard_supply' or previous.get('status')!='verified'
                or previous.get('target')!=list(target) or not previous.get('before') or not previous.get('after')):
            return False
    elif action.get('action')!='choose_standard_reward' or target[6] is not None:
        return False
    elif kind=='expert_selection':
        if target[3]!=0 or target[4]!='现金为王' or target[5] is not None:
            return False
    elif (target[3]>3 or target[5] not in GEAR or target[4]!=NAMES[target[5]] or target[7]!=0):
        return False
    parent = actions[target[1]]
    if not parent.get('before') or not parent.get('after'):
        return False
    if parent.get('action')=='continue_standard_node':
        entry = parent.get('target',[])
        if (kind!='supply_selection' or len(entry)!=2 or type(entry[1]) is not int or not 0<=entry[1]<target[1]
                or actions[entry[1]].get('action')!='start_standard_node' or actions[entry[1]].get('status')!='verified'
                or not actions[entry[1]].get('reward_basis',{}).get('snapshot',{}).get('roster_complete')
                or parent.get('feedback')!=dict(page_kind='supply_selection',node=target[0])):
            return False
    elif kind=='supply_selection' or parent.get('reward_basis',{}).get('node')!=target[0]:
        return False
    before = effect.get('gold_before')
    plane,number = map(int,target[0].split('-'))
    nodes = {target[0]}
    if target[2]=='supply_selection':
        nodes = {f'{plane}-{number+1}'}
        if parent.get('reward_allow_same_node'):nodes.add(target[0])
    if effect.get('node_after') not in nodes:
        return False
    if (before is not None and (type(before) is not int or effect['gold_after']!=before+target[7])
            or target[2]=='expert_selection' and before is None):
        return False
    if action.get('reward_verified') is True and target[6]:
        old,new = effect.get('stars_before'),effect.get('stars_after')
        if (effect.get('unit_verified') is not True or effect.get('other_roster_verified') is not True
                or not isinstance(old,list) or not isinstance(new,list)
                or any(type(s) is not int or not 1<=s<=4 for s in old+new)
                or old!=sorted(old,reverse=True) or new!=sorted(new,reverse=True) or new<=old):
            return False
    return True
