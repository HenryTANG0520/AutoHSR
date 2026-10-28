"""Observed tool stock, including finite counters and an independent infinity glyph."""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import re

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .currency_wars_equipment_catalog import GEAR,SCALES,scaled
from .currency_wars_match import read_match
from .currency_wars_prepare import trusted
from .models import AutomationError,Scene,Token,normalize

TOOLS=frozenset(('projector','projector2','wrench','wrench2','stove','token'))
EFFECTS=dict(projector='copy',projector2='copy',wrench='remove',wrench2='remove',stove='reroll',token='choice')


@dataclass(frozen=True)
class StockCell:
    slot:int
    point:tuple
    name:str|None
    quantity:int|str|None
    signature:str
    textured:bool
    count_roi:tuple
    quantity_source:str|None


@lru_cache(maxsize=1)
def native_wrench():
    manifest=json.loads((RESOURCE_ROOT/'assets/currency-consumables/sources.json').read_text(encoding='utf-8'))
    entry=manifest['items'][0]
    raw=(RESOURCE_ROOT/'assets/currency-consumables'/entry['file']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise AutomationError('原生扳手参考哈希不符。')
    return cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)


def _match(area):
    from .currency_wars_deployment import _texture
    if _texture(area)<8:return None
    return _match_pixels(area.tobytes(),area.shape)


@lru_cache(maxsize=256)
def _match_pixels(raw,shape):
    area=np.frombuffer(raw,dtype=np.uint8).reshape(shape)
    scores=[]
    for name in sorted(GEAR|TOOLS):
        best=0.
        for scale in SCALES:
            refs=[scaled(name,scale)]
            if name=='wrench2':refs.append(cv2.resize(native_wrench(),None,fx=scale,fy=scale))
            if name in ('battery','armor'):refs.append(scaled(name,scale,True))
            for ref in refs:
                if ref.shape[0]<=area.shape[0] and ref.shape[1]<=area.shape[1]:
                    best=max(best,float(cv2.matchTemplate(area,ref,cv2.TM_CCOEFF_NORMED).max()))
        scores.append((best,name))
    scores.sort(reverse=True)
    return scores[0][1] if scores[0][0]>=.92 and scores[0][0]-scores[1][0]>=.025 else None


def infinity(area):
    if area is None or not area.size:return False
    gray=cv2.cvtColor(area,cv2.COLOR_BGR2GRAY)
    contours,hierarchy=cv2.findContours((gray>220).astype(np.uint8)*255,cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:return False
    for i,contour in enumerate(contours):
        x,y,w,h=cv2.boundingRect(contour)
        if not 1.45<=w/max(h,1)<=3.5 or h<area.shape[0]*.20:continue
        holes=[cv2.boundingRect(c) for j,c in enumerate(contours) if hierarchy[0][j][3]==i and cv2.contourArea(c)>2]
        if len(holes)!=2:continue
        holes.sort()
        a,b=holes
        if a[0]+a[2]<b[0] and abs(a[1]+a[3]/2-b[1]-b[3]/2)<h*.3:return True
    return False


def _no_badge(area):
    if area is None or not area.size:return False
    mask=(np.min(area,axis=2)>220).astype(np.uint8)
    total,_,stats,_=cv2.connectedComponentsWithStats(mask)
    h,w=mask.shape
    return not any(s[4]>=4 and .2*h<=s[3]<=.85*h and s[2]<=.85*w for s in stats[1:total])


def _quantity(scene,slot,roi,area,confidence):
    readings=[t for t in scene.tokens if t.within(roi)]
    variants=scene.field_reads.get('currency_consumable_'+str(slot),())
    endless=infinity(area)
    # Lower inventory cards contain individual objects. A visibly absent badge
    # is different from an unreadable badge; top permanent controls always
    # require their explicit number or infinity symbol.
    if (slot<12 and not endless and not any(t.within(roi) for t in scene.tokens)
            and not any(t is not None for t in variants) and _no_badge(area)):return 1
    if variants and (len(variants)!=2 or any(t is None or t.score<max(.9,confidence) for t in variants)):
        return None
    readings+=list(variants)
    if any(t.score<max(.9,confidence) for t in readings):return None
    values={normalize(t.text) for t in readings}
    if endless:
        return 'infinite' if not values or values<={'∞'} else None
    if len(values)==1 and re.fullmatch(r'[0-9]{1,2}',next(iter(values))):return int(next(iter(values)))
    return None


def stock(scene,confidence=.65):
    from .currency_wars_deployment import _texture
    state=read_match(scene,confidence)
    if not state or state.page!='preparation' or not state.node or scene.image is None:
        raise AutomationError('消耗品库存需要当前备战页与节点。')
    image=cv2.resize(scene.image,(2560,1440));result=[]
    locations=[(c*6+r,x,y,(x-44,y-44,x+44,y+44),(x+24,y+25,x+60,y+60))
               for c,x in enumerate((2350,2460)) for r,y in enumerate((330,430,535,640,745,845))]
    locations += [(12,2350,210,(2295,140,2410,280),(2380,238,2410,272)),
                  (13,2460,210,(2415,140,2530,280),(2460,238,2510,272))]
    for slot,x,y,box,count_box in locations:
        x1,y1,x2,y2=box;area=image[y1:y2,x1:x2];name=_match(area)
        roi=tuple(v/d for v,d in zip(count_box,(2560,1440,2560,1440)))
        a,b,c,d=count_box;quantity=_quantity(scene,slot,roi,image[b:d,a:c],confidence) if name in TOOLS else 1 if name in GEAR else None
        full=image[min(y1,b):max(y2,d),min(x1,a):max(x2,c)]
        explicit=any(t.within(roi) for t in trusted(scene,confidence).tokens) or any(scene.field_reads.get('currency_consumable_'+str(slot),()))
        mode='infinity' if quantity=='infinite' else 'visible_counter' if type(quantity) is int and explicit else 'single_cell' if quantity==1 else None
        result.append(StockCell(slot,(x/2560,y/1440),name,quantity,hashlib.sha256(full.tobytes()).hexdigest(),_texture(full)>=15,roi,mode))
    return tuple(result)


def counts(cells):
    result=Counter()
    for cell in cells:
        if cell.name and type(cell.quantity) is int:result[cell.name]+=cell.quantity
        elif cell.name and cell.quantity=='infinite':result[cell.name+':infinite']+=1
        elif cell.textured or cell.name:result['unknown:'+cell.signature]+=1
    return +result


def supplement_counts(scene,reader):
    state=read_match(scene)
    if state is None or state.page!='preparation' or scene.image is None or not hasattr(reader,'read_number'):return scene
    fields=dict(scene.field_reads);h,w=scene.image.shape[:2]
    for cell in stock(scene):
        if cell.name not in TOOLS or cell.quantity is not None:continue
        x1,y1,x2,y2=cell.count_roi
        area=scene.image[round(y1*h):round(y2*h),round(x1*w):round(x2*w)]
        variants=[]
        for sample in (area,cv2.threshold(cv2.cvtColor(area,cv2.COLOR_BGR2GRAY),160,255,cv2.THRESH_BINARY)[1]):
            reading=reader.read_number(cv2.resize(sample,None,fx=3,fy=3))
            variants.append(Token(reading.text,reading.score,cell.count_roi) if reading is not None else None)
        fields['currency_consumable_'+str(cell.slot)]=tuple(variants)
    return Scene(scene.tokens,scene.image,scene.geometry,scene.captured_at,fields)
