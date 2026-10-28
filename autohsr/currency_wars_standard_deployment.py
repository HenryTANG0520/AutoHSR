"""Fill vacant standard-board slots from the verified owned roster, without trades."""
from itertools import combinations, product

from .currency_wars_collector import collected_snapshot, roster_cells
from .currency_wars_deployment import plan_bench_deployment, verify_bench_deployment
from .currency_wars_match import read_match
from .models import AutomationError

POLICY = 'owned-deployment-v3'


def team_score(team, strategy='default', *, zones=None):
    from .currency_wars_standard_policy import owned_team_preference
    positions = tuple(zones) if zones is not None else tuple(unit.zone for unit in team)
    front, back = positions.count('front'), positions.count('back')
    if not front or front > 4 or back > 6 or len(positions) != len(team):
        raise AutomationError('阵容需要合法前后台位置与至少一名前台角色。')
    strength = sum((10,30,80,160)[unit.star-1]+2*unit.tier for unit in team)
    overlap = sum(len(set(a.traits or ()) & set(b.traits or ())) for a,b in combinations(team,2))
    preference = sum(owned_team_preference(unit.name,strategy) for unit in team)
    if strategy == 'seele':
        preference += sum(25 for unit,zone in zip(team,positions) if unit.name == '希儿' and zone == 'front')
    if strategy == 'aglaea' and not any(unit.name == '藿藿' for unit in team):
        preference += sum(10 for unit,zone in zip(team,positions) if unit.name == '风堇' and zone == 'front')
    return strength+preference+3*overlap+4*bool(back)-4*abs(front-max(1,len(team)//3))


def choose_deployment(snapshot, strategy='default'):
    """Enumerate unique owned teams and legal positions; scores are a baseline."""
    if (not snapshot.roster_complete or snapshot.capacity is None
            or any(u.star is None or u.tier is None or not u.eligible_zones for u in snapshot.roster)):
        raise AutomationError('部署需要完整持有角色、星级、费用和适配位置。')
    field = tuple(u for u in snapshot.roster if u.zone != 'bench')
    if (len({u.name for u in field}) != len(field)
            or any(u.zone not in u.eligible_zones for u in field)):
        raise AutomationError('当前场上存在重复角色或位置不适配，先核对阵容。')
    missing = snapshot.capacity-len(field)
    if missing <= 0:
        return None
    bench = tuple(u for u in snapshot.roster if u.zone == 'bench'
                  and u.name not in {f.name for f in field})
    if missing > len(bench):
        raise AutomationError('持有的不同角色不足以满员，需另行核实商店策略。')
    best = None
    for selected in combinations(bench, missing):
        team = field+selected
        if len({u.name for u in team}) != len(team):
            continue
        for zones in product(*(u.eligible_zones for u in selected)):
            positions = tuple(u.zone for u in field)+zones
            front, back = positions.count('front'), positions.count('back')
            if not front or front > 4 or back > 6:
                continue
            score = team_score(team,strategy,zones=positions)
            key = (score, tuple(-u.slot for u in selected), tuple(z == 'back' for z in zones))
            if best is None or key > best[0]:
                best = (key, selected, zones)
    if best is None:
        raise AutomationError('持有角色无法组成合法且有前台的满员阵容。')
    # Deploy the front line first, preserving the selected team's legal assignment.
    unit, zone = min(zip(best[1],best[2]), key=lambda pair:(pair[1]!='front',-pair[0].star,pair[0].slot))
    return unit, zone, best[0][0]


def standard_deployment(scene, session, confidence=.65):
    collection = session.get('collection',{})
    # Input authority re-derives this same proposal after writing its intent.
    # Exclude only that pending free deployment while checking the PRIOR ledger;
    # unknown moves and paid intents still block, and no journal is rewritten.
    prior = session
    actions = session.get('actions',[])
    if actions and actions[-1].get('action') in ('deploy_standard_owned','start_standard_node') and actions[-1].get('status')=='pending':
        prior = dict(session,actions=actions[:-1])
    snapshot = collected_snapshot(scene,prior,collection.get('input_epoch',-1),'standard_deployment',confidence)
    if (snapshot.page != 'preparation' or snapshot.mode != 'standard' or snapshot.rank != 8
            or snapshot.wealth != 40 or snapshot.game_version != '4.6' or snapshot.rules_version != '4.6'
            or snapshot.transaction_status != 'clear' or snapshot.gold is None or snapshot.hp is None
            or snapshot.hp <= 0 or snapshot.level is None):
        raise AutomationError('标准部署的当前节点、同局来源、版本或余额事实不足。')
    choice = choose_deployment(snapshot,session.get('strategy','default'))
    if choice is None:
        return None
    unit, zone, score = choice
    plan = plan_bench_deployment(scene,confidence,source_slot=unit.slot,zone=zone)
    if plan.backend_slots != 6:
        raise AutomationError('标准部署尚未核实当前后台布局。')
    record = collection['units']['bench:'+str(unit.slot)]
    payload = (snapshot.node,snapshot.gold,snapshot.hp,snapshot.level,unit.slot,zone,
               plan.target_slot,record['signature'])
    return plan, unit, score, payload


def deployment_feedback(before, after, plan, confidence=.65):
    previous, current = read_match(before,confidence), read_match(after,confidence)
    if (not previous or not current or previous.hp is None or previous.level is None
            or (current.hp,current.level) != (previous.hp,previous.level)):
        return dict(status='unknown',reason='life_or_level_changed')
    return verify_bench_deployment(before,after,plan,confidence)


def transfer_collection(session, before, after, plan, source, confidence=.65):
    """Carry only visually unchanged slots, plus the verified source-to-target move."""
    if deployment_feedback(before,after,plan,confidence)['status'] != 'verified':
        raise AutomationError('部署反馈未核实，未迁移角色身份。')
    old = session['collection']['units']
    moved = old.get('bench:'+str(plan.source_slot))
    if not moved:
        raise AutomationError('部署来源缺少已采集身份。')
    records = {}
    for cell in roster_cells(after,confidence):
        if cell.state != 'occupied':
            continue
        key = cell.zone+':'+str(cell.slot)
        if (cell.zone,cell.slot) == (plan.zone,plan.target_slot):
            unit = dict(moved['unit'],zone=cell.zone,slot=cell.slot)
            records[key] = dict(unit=unit,signature=cell.signature,node=cell.node,source=source,
                                moved_from=moved['source'])
        elif old.get(key,{}).get('signature') == cell.signature and old[key].get('node') == cell.node:
            records[key] = old[key]
    session['collection'].update(units=records,complete=False)
