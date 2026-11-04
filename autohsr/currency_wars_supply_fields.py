"""Pair complete supply columns without dropping a second visible equipment.

Only the existing equipment text band is read. Multi-item grammar is an offline
contract, not calibration for an unseen second row or an inferred hidden item.
"""
import re
import hashlib
import math

import cv2

from .currency_wars import observe
from .currency_wars_match import unit_name
from .models import AutomationError,Scene,Token,normalize


CENTERS={4:(.223,.407,.592,.777),5:(.13,.315,.5,.685,.87)}


def equipment_names(token):
    """One or two explicitly named items; repetitions retain multiplicity.

    Parse separators before normalize(), which otherwise removes punctuation.
    Counts, merged undecorated names and partial names never invent two items.
    Unknown complete names survive for custody but cannot authorize delivery.
    """
    if not isinstance(token, Token) or not isinstance(token.text, str):
        raise AutomationError('补给装备字段无效。')
    pieces = tuple(normalize(part) for part in re.split(r'[、+＋]', token.text))
    if (not re.fullmatch(r'[\u4e00-\u9fff\s、+＋]+', token.text)
            or not 1 <= len(pieces) <= 2 or any(not re.fullmatch(r'[\u4e00-\u9fff]{2,20}', part) for part in pieces)
            or any(char in token.text for char in '\n\r')):
        raise AutomationError('补给装备名称或显式件数未完整核实。')
    return pieces


def _name(token):
    return bool(re.fullmatch(r'[\u4e00-\u9fffa-z0-9·.]{1,40}',normalize(token.text)))


def _items(scene,confidence):
    # An extra item-shaped label outside the calibrated text band must not
    # silently disappear from the effect. It does not authorize a new layout.
    for token in scene.tokens:
        if token.within((.03,.55,.97,.80)) and not token.within((.03,.61,.97,.67)):
            try:equipment_names(token)
            except AutomationError:continue
            raise AutomationError('补给装备文字出现在未校准行，未忽略额外装备。')
    items=sorted((t for t in scene.tokens if t.within((.03,.61,.97,.67))),key=lambda t:t.center[0])
    if not items or len(items)>10:
        raise AutomationError('补给装备行数量与四／五卡布局不符，未把漏读当较少候选。')
    for token in items:
        equipment_names(token)
        if (not confidence<=token.score<=1 or len(token.box)!=4 or any(not math.isfinite(v) for v in token.box)
                or not 0<=token.box[0]<token.box[2]<=1 or not .61<=token.box[1]<token.box[3]<=.67):
            raise AutomationError('补给装备文字被截断、越界或可信度不足。')
    layouts=[]
    for centers in CENTERS.values():
        columns=[[] for _ in centers]
        for token in items:
            slots=[i for i,x in enumerate(centers) if abs(token.center[0]-x)<=.035
                   and x-.09<=token.box[0]<token.box[2]<=x+.09]
            if len(slots)!=1:break
            columns[slots[0]].append(token)
        else:
            if all(1<=len(column)<=2 for column in columns):layouts.append(columns)
    if len(layouts)!=1:
        raise AutomationError('补给装备行数量与四／五卡布局不符，未把漏读当较少候选。')
    result=[]
    for column in layouts[0]:
        if len(column)==1:
            result.append(column[0]);continue
        first,second=sorted(column,key=lambda t:(t.box[1],t.box[0]))
        horizontal=first.box[2]<=second.box[0] and abs(first.center[1]-second.center[1])<=.01
        vertical=first.box[3]<=second.box[1] and abs(first.center[0]-second.center[0])<=.02
        if not (horizontal or vertical) or any(len(equipment_names(t))!=1 for t in column):
            raise AutomationError('补给装备文字重叠或件数不明，未把重复OCR当作两件。')
        names=equipment_names(first)+equipment_names(second)
        result.append(Token('、'.join(names),min(t.score for t in column),
            (min(t.box[0] for t in column),min(t.box[1] for t in column),
             max(t.box[2] for t in column),max(t.box[3] for t in column))))
    return result


def _role(scene,slot,x,confidence):
    roi=(x-.09,.50,x+.09,.55)
    from .currency_wars_names import configured_name,pending_name
    configured=configured_name(scene,roi,confidence)
    if configured is not None:
        variants=[t for kind in ('raw','binary') for t in scene.field_reads.get('currency_supply_role_'+str(slot)+'_'+kind,())]
        if any(t is not None and t.score>=max(.9,confidence) and unit_name(t.text)!=unit_name(configured.text) for t in variants):
            raise AutomationError('配置角色名称与局部角色文字冲突。')
        return configured
    if pending_name(scene,roi):raise AutomationError('配置角色名称尚无完整可信来源。')
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
