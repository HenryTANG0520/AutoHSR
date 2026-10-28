"""Evidence-only inventory, equipped-slot and recommendation recognition.

Pinned March7th icon bytes are recorded beside the upstream license. The two
additional native icons retain their existing local capture attribution.
"""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .currency_wars_deployment import _crop, _texture
from .currency_wars_match import read_match
from .models import AutomationError

FILES = dict(star='e1',life_flower='e2',pistol='e3',battery='e4',drill='e5',armor='e6',knife='e7',
             shoe='shoe',boots='boots',firestorm='firestorm',chainsaw='chainsaw',propeller='propeller',
             projector='projector',projector2='projector2',stove='stove',token='token',wrench='wrench',wrench2='wrench2')
NAMES = dict(star='幸运星',life_flower='生命之花',pistol='和平手枪',battery='光能电池',drill='以太钻头',
             armor='量产型装甲',knife='折叠小刀',shoe='轮滑鞋',boots='反重力皮靴',firestorm='火力风暴潮',
             chainsaw='高周波电锯',propeller='光速螺旋桨',hard_armor='很硬的甲',energy_sail='蓄能帆',
             projector='员工投影仪',projector2='完美投影仪',stove='冶金炉',token='好运令牌',wrench='拆装扳手',wrench2='拆装扳手2')
BASICS = frozenset(('star','life_flower','pistol','battery','drill','armor','knife','shoe'))
GEAR = BASICS | frozenset(('boots','firestorm','chainsaw','propeller','hard_armor','energy_sail'))
# Both formulas are explicit in the pinned equip_seele implementation and in
# the game's saved equipment tutorial. Unread formulas are not guessed.
RECIPES = {tuple(sorted(('shoe','knife'))):'firestorm',tuple(sorted(('star','knife'))):'chainsaw'}
SCALES = (.7,.8,.9,1.,1.1,1.2,4/3,1.5,1.6)


@lru_cache(maxsize=32)
def template(name):
    if name not in NAMES:
        raise AutomationError('装备参考名称不在已记录目录内。')
    if name not in FILES:
        from .currency_wars_equipment import equipment_template
        return equipment_template(name)
    root = RESOURCE_ROOT/'assets/upstream/March7thAssistant/equipment'
    metadata = json.loads((root/'sources.json').read_text(encoding='utf-8'))
    filename = FILES[name]+'.png'
    record = next(item for item in metadata['items'] if item['file']==filename)
    data = (root/filename).read_bytes()
    if hashlib.sha256(data).hexdigest() != record['sha256']:
        raise AutomationError('装备参考图哈希与固定来源不一致。')
    result = cv2.imdecode(np.frombuffer(data,dtype=np.uint8),cv2.IMREAD_COLOR)
    if result is None or min(result.shape[:2]) < 20:
        raise AutomationError('装备参考图无效。')
    return result


@lru_cache(maxsize=512)
def scaled(name, scale, native=False):
    if native:
        from .currency_wars_equipment import equipment_template
        image = equipment_template(name)
    else:
        image = template(name)
    return cv2.resize(image,None,fx=scale,fy=scale)


def identify(area, names=GEAR, scales=SCALES):
    if _texture(area) < 8:
        return None
    scores = []
    for name in sorted(names):
        best = 0.
        for scale in scales:
            for native in ((False,True) if name in ('battery','armor') else (False,)):
                ref = scaled(name,scale,native)
                if ref.shape[0] <= area.shape[0] and ref.shape[1] <= area.shape[1]:
                    best = max(best,float(cv2.matchTemplate(area,ref,cv2.TM_CCOEFF_NORMED).max()))
        scores.append((best,name))
    scores.sort(reverse=True)
    return scores[0][1] if scores and scores[0][0] >= .92 and (len(scores)==1 or scores[0][0]-scores[1][0] >= .025) else None


@dataclass(frozen=True)
class InventoryCell:
    slot: int
    point: tuple
    name: str | None
    signature: str
    textured: bool


def inventory(scene, confidence=.65):
    state = read_match(scene,confidence)
    if not state or state.page != 'preparation' or not state.node or scene.image is None:
        raise AutomationError('装备仓库需要当前备战页。')
    image = cv2.resize(scene.image,(2560,1440))
    result = []
    for column,x in enumerate((2350,2460)):
        for row,y in enumerate((330,430,535,640,745,845)):
            area = image[y-44:y+44,x-44:x+44]
            result.append(InventoryCell(column*6+row,(x/2560,y/1440),identify(area),
                                         hashlib.sha256(area.tobytes()).hexdigest(),_texture(area)>=15))
    return tuple(result)


def inventory_counts(cells):
    # Keep unrecognized occupied cells in the contract too. They cannot silently
    # disappear while a recognized item is equipped. An ambiguous reflow stops.
    return Counter(cell.name if cell.name else 'unknown:'+cell.signature for cell in cells if cell.name or cell.textured)


def slots(scene, confidence=.65):
    from .currency_wars_equipment import equipment_slots
    legacy = equipment_slots(scene,confidence)
    image = cv2.resize(scene.image,(2560,1440))
    result = []
    for x,old in zip((2195,2310,2420),legacy):
        name = identify(image[1040:1130,x-45:x+45])
        result.append('empty' if old=='empty' and name is None else name if old!='empty' and name else 'other')
    return tuple(result)


def recommendation_visible(scene, confidence=.65):
    from .currency_wars_prepare import trusted
    clean = trusted(scene,confidence)
    return clean.has('推荐装备',(.49,.51,.59,.57),exact=True) and clean.has('次选装备',(.49,.69,.59,.75),exact=True)


def recommendation_facts(scene, confidence=.65):
    if not recommendation_visible(scene,confidence) or scene.image is None:
        raise AutomationError('当前角色推荐装备面板未展开。')
    image = cv2.resize(scene.image,(2560,1440))
    found,recipes = [],[]
    for y in (.61,.79):
        for x in (.529,.600,.671):
            name = identify(_crop(image,(x-.027,y-.055,x+.027,y+.055)))
            if name:
                found.append(name)
                rows = (.590,.626) if y<.7 else (.766,.800)
                parts = [identify(_crop(image,(x+.0155,cy-.019,x+.0425,cy+.019)),BASICS,
                                  (.35,.4,.45,.5,.55,.6,.625,.65,2/3,.675,.7,.75,.8)) for cy in rows]
                if name not in BASICS and all(parts):
                    recipes.append(dict(product=name,components=sorted(parts)))
    return tuple(dict.fromkeys(found)),tuple(recipes)


def recommendations(scene, confidence=.65):
    return recommendation_facts(scene,confidence)[0]
