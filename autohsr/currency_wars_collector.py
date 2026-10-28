"""Read owned unit slots; inspection never buys, sells or deploys anything."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .currency_wars_deployment import (_BENCH_CENTERS, _crop, _texture, backend_layout, bench_face)
from .currency_wars_match import read_match
from .currency_wars_prepare import trusted
from .models import AutomationError, Token
from .models import normalize

TIER_FIELD = (.957,.181,.970,.206)


@dataclass(frozen=True)
class RosterCell:
    zone: str
    slot: int
    node: str
    point: tuple[float, float]
    roi: tuple[float, float, float, float]
    state: str
    signature: str


def roster_cells(scene, confidence=.65):
    state = read_match(scene, confidence)
    if (state is None or state.page != 'preparation' or not state.node
            or not state.deployment or scene.image is None):
        raise AutomationError('阵容采集需要备战页、节点、部署人数和当前图像。')
    _, centers = backend_layout(scene.image)
    slots = [('front', i, (x/2560,530/1440), (x/2560-.025,.33,x/2560+.025,.41))
             for i, x in enumerate((990,1180,1370,1560), 1)]
    slots += [('back', i, (x,890/1440), (x-.025,.58,x+.025,.66))
              for i, x in enumerate(centers[:6], 1)]
    slots += [('bench', i, (x,1210/1440), bench_face(i)) for i, x in enumerate(_BENCH_CENTERS, 1)]
    clean = trusted(scene, confidence)
    result = []
    for zone, slot, point, roi in slots:
        crop = _crop(scene.image, roi)
        texture = _texture(crop)
        if texture < 8:
            occupancy = 'empty'
        elif texture >= 15:
            occupancy = 'occupied'
        else:
            raise AutomationError('角色槽处于不确定状态：' + zone + str(slot))
        if zone == 'bench' and clean.has('开启', (point[0]-.035,.78,point[0]+.035,.91), exact=True):
            occupancy = 'reward'
        result.append(RosterCell(zone, slot, state.node, point, roi, occupancy,
                                 hashlib.sha256(crop.tobytes()).hexdigest()))
    deployed = sum(cell.state == 'occupied' for cell in result if cell.zone != 'bench')
    if deployed != state.deployment[0]:
        raise AutomationError('角色槽与部署人数不一致，未把未知槽当成空位。')
    return tuple(result)


def first_unit_probe(scene, confidence=.65, known=None):
    cells = roster_cells(scene, confidence)
    known = known or {}
    candidates = [cell for cell in cells if cell.state == 'occupied' and
                  known.get(cell.zone+':'+str(cell.slot),{}).get('signature') != cell.signature]
    if not candidates:
        if any(cell.state == 'occupied' for cell in cells):
            return None
        raise AutomationError('当前没有已定位的持有角色，需先核实奖励或商店。')
    cell = min(candidates, key=lambda item:(item.zone != 'bench', item.zone, item.slot))
    x, y = cell.point
    target = Token('查看持有角色', 1., (x-.01,y-.01,x+.01,y+.01))
    return cell, target


def character_stars(scene):
    import cv2
    import numpy as np
    if scene.image is None:
        raise AutomationError('角色星级缺少图像。')
    image = _crop(scene.image, (.79,.14,.90,.178))
    height, width = scene.image.shape[:2]
    hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    # Bright yellow cores separate adjacent stars whose glow is connected.
    mask = cv2.inRange(hsv,np.array((10,80,230),np.uint8),np.array((40,255,255),np.uint8))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    stars = [(stat, center) for stat, center in zip(stats[1:],centers[1:]) if
             .004 <= stat[2]/width <= .013 and .009 <= stat[3]/height <= .022
             and .08 <= stat[4]/(stat[2]*stat[3]) <= .8]
    if not 1 <= len(stars) <= 4 or max(c[1] for _,c in stars)-min(c[1] for _,c in stars) > height*.005:
        raise AutomationError('角色星级图标不完整或不唯一。')
    return len(stars)


def owned_profile(scene, inspecting, confidence=.65):
    from .currency_wars_roster import read_character
    from .currency_wars_equipment_catalog import slots as equipment_slots
    from .currency_wars_state import UnitState
    profile = read_character(scene, confidence)
    if (not inspecting or profile.node != inspecting.get('node')
            or inspecting.get('zone') not in ('front','back','bench')
            or type(inspecting.get('slot')) is not int):
        raise AutomationError('角色面板与待采集位置/节点不一致。')
    clean = trusted(scene,confidence)
    tiers = [t for t in clean.tokens if t.within(TIER_FIELD) and re.fullmatch(r'[1-5]',normalize(t.text))]
    if len(tiers) != 1:
        raise AutomationError('角色费用档位未核实，未使用出售价格或星级代替。')
    traits = tuple(dict.fromkeys(normalize(t.text) for t in sorted(clean.tokens,key=lambda t:t.center[0])
                                if t.within((.72,.27,.98,.315)) and re.fullmatch(r'[\u4e00-\u9fff]{1,12}',normalize(t.text))))
    slots = equipment_slots(scene,confidence)
    equipment = tuple(item for item in slots if item != 'empty') if 'other' not in slots else None
    name = re.sub(r'lv\.?([0-9]{1,4})', r'Lv.\1', profile.name)
    return UnitState(name, inspecting['zone'], inspecting['slot'], star=character_stars(scene),
                     tier=int(tiers[0].text), traits=traits or None, equipment=equipment,
                     eligible_zones=profile.zones)


def supplement_character_tier(scene, reader):
    """Tight recognition in the OCR child, only on an owned-character panel."""
    from .currency_wars import observe
    if scene.image is None or observe(scene,.65).page_kind != 'character':
        return scene
    if any(t.within(TIER_FIELD) and re.fullmatch(r'[1-5]',normalize(t.text)) for t in trusted(scene).tokens):
        return scene
    import cv2
    from .models import Scene
    image = _crop(scene.image,TIER_FIELD)
    gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    fields = [reader.read_number(image), reader.read_number(cv2.threshold(gray,150,255,cv2.THRESH_BINARY)[1])]
    if (any(t is None or not .9 <= t.score <= 1 or not re.fullmatch(r'[1-5]',t.text) for t in fields)
            or len({t.text for t in fields}) != 1):
        return scene
    return Scene(scene.tokens+[Token(fields[0].text,min(t.score for t in fields),TIER_FIELD)],
                 scene.image,scene.geometry,scene.captured_at)


def session_snapshot(snapshot, session, epoch, source):
    """Stable session facts need their own sources, not visible roster slots."""
    from dataclasses import replace
    from .currency_wars_state import FactEvidence
    collection = session.get('collection', {})
    known = {}
    identity = (session.get('account_key') and session.get('account_verified_run') == collection.get('run_dir')
                and session.get('account_verified_epoch') == epoch)
    if identity and snapshot.page != 'unknown' and session.get('status') == 'active' and session.get('start_verified') and session.get('entry',{}).get('rank_verified'):
        known.update(mode='standard',rank=8,wealth=40)
    if session.get('environment'):
        known['environment'] = (session['environment']['name'],)
    from .currency_wars_standard_ledger import ledger_status
    if identity:
        known['transaction_status'] = ledger_status(session['actions'])
    sources = {}
    for name in ('mode','rank','wealth'):
        sources[name] = 'match_entry:'+session.get('match_id','unverified')
    sources['roster'] = 'collection:'+session.get('match_id','unverified')
    sources['transaction_status'] = 'session_ledger:'+session.get('match_id','unverified')
    client = session.get('client',{})
    if identity and client.get('verified_run') == collection.get('run_dir') and client.get('input_epoch') == epoch:
        known['game_version'] = client['version']
        sources['game_version'] = 'launcher_game_version:'+client['sha256']
        if session.get('rules_version') == client['version'] == '4.6':
            known['rules_version'] = '4.6'
            sources['rules_version'] = 'rules:currency_wars_economy:4.6'
    return replace(snapshot,**known,evidence=snapshot.evidence+tuple(FactEvidence(name,sources.get(name,source),epoch) for name in known))


def collected_snapshot(scene, session, epoch, source, confidence=.65, *, allow_reward_items=False):
    """Publish a complete roster only when every current slot is accounted for."""
    from dataclasses import replace
    from .currency_wars_state import snapshot_from_scene, UnitState, FactEvidence
    snapshot = session_snapshot(snapshot_from_scene(scene,epoch,confidence,source),session,epoch,source)
    collection = session.get('collection', {})
    try:
        cells = roster_cells(scene,confidence)
    except AutomationError:
        return snapshot
    if collection.get('input_epoch') != epoch or not collection.get('complete'):
        return snapshot
    if set(collection.get('units',{})) != {cell.zone+':'+str(cell.slot) for cell in cells if cell.state=='occupied'}:
        return snapshot
    units = []
    for cell in cells:
        if cell.state == 'reward':
            if not allow_reward_items:return snapshot
            continue  # Explicit origin-only view; ordinary battle/trading stays incomplete.
        if cell.state != 'occupied':
            continue
        record = collection.get('units',{}).get(cell.zone+':'+str(cell.slot))
        if not record or record.get('signature') != cell.signature or record.get('node') != cell.node:
            return snapshot
        data = dict(record['unit'])
        for name in ('traits','equipment','eligible_zones'):
            if data.get(name) is not None:
                data[name] = tuple(data[name])
        unit = UnitState(**data)
        if (unit.zone,unit.slot) != (cell.zone,cell.slot):
            return snapshot
        units.append(unit)
    known = dict(roster=tuple(units),roster_complete=True,bench_capacity=9,
                 bench_occupied=sum(unit.zone=='bench' for unit in units))
    proof = 'collection:'+session.get('match_id','unverified')
    return replace(snapshot,**known,evidence=snapshot.evidence+tuple(FactEvidence(name,proof,epoch) for name in known))
