"""Pair four/five complete supply columns; missing names are not fewer cards."""
import re
import hashlib

import cv2

from .currency_wars import observe
from .currency_wars_match import unit_name
from .models import AutomationError,Scene,Token,normalize


CENTERS={4:(.223,.407,.592,.777),5:(.13,.315,.5,.685,.87)}


def _name(token):
    return bool(re.fullmatch(r'[\u4e00-\u9fffa-z0-9·.]{1,40}',normalize(token.text)))


def _items(scene,confidence):
    items=sorted((t for t in scene.tokens if t.within((.03,.61,.97,.67))),key=lambda t:t.center[0])
    if (len(items) not in CENTERS or any(not confidence<=t.score<=1 or not re.fullmatch(r'[\u4e00-\u9fff]{2,20}',normalize(t.text)) for t in items)
            or any(abs(t.center[0]-x)>.035 for t,x in zip(items,CENTERS[len(items)]))):
        raise AutomationError('补给装备行数量与四／五卡布局不符，未把漏读当较少候选。')
    return items


def _role(scene,slot,x,confidence):
    roi=(x-.09,.50,x+.09,.55)
    raw=[t for t in scene.tokens if t.within(roi)]
    if len(raw)>1 or any(not confidence<=t.score<=1 or not _name(t) for t in raw):
        raise AutomationError('补给角色文字冲突或可信度不足。')
    keys=tuple('currency_supply_role_'+str(slot)+'_'+kind for kind in ('raw','binary'))
    variants=[]
    if any(k in scene.field_reads for k in keys):
        for key in keys:
            reads=scene.field_reads.get(key,())
            if (len(reads)!=1 or reads[0] is None or not max(.9,confidence)<=reads[0].score<=1
                    or not reads[0].within(roi) or not _name(reads[0])):
                raise AutomationError('缺失补给角色的两份局部来源不完整。')
            variants.append(reads[0])
        if len({unit_name(t.text) for t in raw+variants})!=1:
            raise AutomationError('补给角色的原图、二值图与全图文字不符。')
    tokens=raw or variants[:1]
    if len(tokens)!=1:raise AutomationError('补给角色名称缺失，未默认该列。')
    return tokens[0]


def rows(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='supply_selection':raise AutomationError('当前不是补给选择页。')
    items=_items(scene,confidence);result=[]
    for slot,(x,item) in enumerate(zip(CENTERS[len(items)],items)):
        try:name=_role(scene,slot,x,confidence)
        except AutomationError:
            if scene.image is None:raise
            # Keep an unreadable unselected column by image identity. It cannot
            # become a selected unit or silently disappear from the table.
            image=cv2.resize(scene.image,(2560,1440));roi=(x-.09,.50,x+.09,.55)
            patch=image[round(.50*1440):round(.55*1440),round((x-.09)*2560):round((x+.09)*2560)]
            signature=hashlib.sha256(str(slot).encode()+patch.tobytes()).hexdigest()
            name=Token('unknown:'+signature,1.,roi)
        result.append((slot,name,item))
    if len({name.text if name.text.startswith('unknown:') else unit_name(name.text) for _,name,item in result})!=len(result):
        raise AutomationError('补给角色名称重复。')
    return tuple(result)


def supplement_supply_fields(scene,reader):
    if scene.image is None or observe(scene,.65).page_kind!='supply_selection' or not hasattr(reader,'read'):return scene
    try:items=_items(scene,.65)
    except AutomationError:return scene
    fields=dict(scene.field_reads);h,w=scene.image.shape[:2]
    for slot,x in enumerate(CENTERS[len(items)]):
        try:_role(scene,slot,x,.65);continue
        except AutomationError:pass
        x1,y1,x2,y2=x-.09,.50,x+.09,.55
        patch=scene.image[round(y1*h):round(y2*h),round(x1*w):round(x2*w)]
        binary=cv2.threshold(cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY),160,255,cv2.THRESH_BINARY)[1]
        for kind,sample in zip(('raw','binary'),(patch,binary)):
            local=reader.read(cv2.resize(sample,None,fx=3,fy=3))
            if len(local.tokens)>8:raise AutomationError('补给角色局部文字超出可核验范围。')
            fields['currency_supply_role_'+str(slot)+'_'+kind]=tuple(Token(t.text,t.score,
                (x1+t.box[0]*(x2-x1),y1+t.box[1]*(y2-y1),x1+t.box[2]*(x2-x1),y1+t.box[3]*(y2-y1))) for t in local.tokens) or (None,)
    return Scene(scene.tokens,scene.image,scene.geometry,scene.captured_at,fields)
