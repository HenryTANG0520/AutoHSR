"""Wear calibrated defensive equipment on otherwise empty roles."""
from functools import lru_cache
import time

from .config import RESOURCE_ROOT
from .currency_wars import CurrencyWarsWorkflow
from .currency_wars_deployment import _crop,_texture,backend_layout
from .currency_wars_match import read_match
from .currency_wars_roster import read_character
from .currency_wars_sale import FieldIdentity,field_roi,validate_field_image
from .models import AutomationError,EmptyCapture


@lru_cache(maxsize=5)
def equipment_template(name):
    import cv2
    path=RESOURCE_ROOT/'assets/templates'/('currency_'+name+'_4_6.png')
    image=cv2.imread(str(path))
    if image is None or min(image.shape[:2])<30:
        raise AutomationError('已校准装备图像缺失。')
    return image


def _standard(scene):
    import cv2
    if scene.image is None:
        raise AutomationError('装备观察缺少图像。')
    return cv2.resize(scene.image,(2560,1440))


def equipment_items(scene,name,confidence=.65):
    import cv2
    state=read_match(scene,confidence)
    if not state or state.page!='preparation' or not state.node:
        raise AutomationError('装备整理需要明确备战节点。')
    image=_standard(scene)
    if name not in ('battery','hard_armor','armor','energy_sail'):
        raise AutomationError('装备种类未校准。')
    template=equipment_template(name)
    result=[]
    for x in (2350,2460):
        for y in (330,430,535,640,745,845):
            patch=image[y-42:y+42,x-42:x+42]
            if cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED).max()>=.92:
                result.append((x/2560,y/1440))
    return tuple(result)


def battery_items(scene,confidence=.65):
    return equipment_items(scene,'battery',confidence)


def equipment_fields(scene,excluded=(),confidence=.65):
    state=read_match(scene,confidence)
    if not state or state.page!='preparation' or not state.node:
        raise AutomationError('场上装备目标未核实。')
    _,centers=backend_layout(scene.image)
    found=[]
    for zone,positions,y in (('back',centers[:6],890/1440),('front',[x/2560 for x in (990,1180,1370,1560)],530/1440)):
        for slot,x in enumerate(positions,1):
            if (zone,slot) in excluded:
                continue
            provisional=FieldIdentity(zone,slot,(x,y),state.node,None)
            face=_crop(scene.image,field_roi(provisional))
            if _texture(face)>=15:
                found.append(FieldIdentity(zone,slot,(x,y),state.node,face.copy()))
    return tuple(found)


def equipment_slots(scene,confidence=.65):
    import cv2
    read_character(scene,confidence)
    image=_standard(scene)
    empty=equipment_template('empty_equipment')
    result=[]
    for x in (2195,2310,2420):
        area=image[1040:1130,x-45:x+45]
        empty_score=float(cv2.matchTemplate(area,empty,cv2.TM_CCOEFF_NORMED).max())
        scores={}
        for name in ('battery','hard_armor','armor','energy_sail'):
            template=equipment_template(name)
            scores[name]=max(float(cv2.matchTemplate(area,cv2.resize(template,None,fx=scale,fy=scale),cv2.TM_CCOEFF_NORMED).max())
                             for scale in (.6,.7,.8,.9,1.,1.1))
        matches=[name for name,score in scores.items() if score>=.85]
        result.append('empty' if empty_score>=.90 else matches[0] if len(matches)==1 else 'other')
    return tuple(result)


def available_slots(profile,slots,item_name):
    if item_name=='energy_sail':
        # Capture 168 explicitly recommends Sparkle. This advanced item cannot
        # combine with her basic battery; preserve that slot and require room.
        return profile.name=='花火' and 'empty' in slots and all(s in ('empty','battery','armor','hard_armor') for s in slots)
    if item_name=='hard_armor':
        return profile.name in ('符玄','阮梅','花火','藿藿') and 'empty' in slots and all(s in ('empty','battery','armor') for s in slots)
    return slots==('empty',)*3


def equipment_plan(scene,field,item,profile_scene,item_name,confidence=.65):
    state=read_match(scene,confidence)
    if not state or state.gold is None:
        raise AutomationError('装备穿戴前金币未核实。')
    validate_field_image(scene,field,confidence)
    if item not in equipment_items(scene,item_name,confidence):
        raise AutomationError('待穿戴装备图像已改变。')
    profile=read_character(profile_scene,confidence)
    if profile.node!=field.node or not available_slots(profile,equipment_slots(profile_scene,confidence),item_name):
        raise AutomationError('目标角色装备槽或适配不符合已核实策略，未自动合成或覆盖。')
    return item,field.point


def battery_plan(scene,field,item,profile_scene,confidence=.65):
    return equipment_plan(scene,field,item,profile_scene,'battery',confidence)


def equip_battery(c,scene,field,item,data,persist,*,item_name='battery'):
    guard=CurrencyWarsWorkflow(c)
    initial=read_match(scene,c.settings.ocr_confidence)
    original_count=len(equipment_items(scene,item_name,c.settings.ocr_confidence))
    def record(kind,s,**extra):
        guard._require_current_scene(s)
        action=dict(action=kind,status='pending',zone=field.zone,field_slot=field.slot,
                    before=str(c.evidence(s,'currency_'+kind)),**extra)
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        return action
    def wait_for(predicate):
        elapsed=0.
        while elapsed<15:
            started=time.monotonic()
            inactive=c.runner.inactive_duration
            try:
                after=c.snapshot()
            except EmptyCapture:
                after=None
            if after is not None:
                guard._require_current_scene(after)
                try:
                    if predicate(after):
                        return after
                except AutomationError:
                    pass
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        return None
    def finish(action,after):
        action['status']='verified' if after is not None else 'unknown'
        if after is not None:
            action['after']=str(c.evidence(after,'currency_'+action['action']+'_after'))
            data['screenshot']=action['after']
        data['action_status']=action['status']
        persist()
        return after is not None
    action=record('inspect_equipment_role',scene)
    c.currency_open_field(scene,field)
    profile_scene=wait_for(lambda s:read_character(s,c.settings.ocr_confidence).node==field.node)
    if not finish(action,profile_scene):
        return False
    profile=read_character(profile_scene,c.settings.ocr_confidence)
    original_slots=equipment_slots(profile_scene,c.settings.ocr_confidence)
    available=available_slots(profile,original_slots,item_name)
    action=record('close_equipment_role',profile_scene)
    c.currency_close_character(profile_scene)
    def board(s,count):
        validate_field_image(s,field,c.settings.ocr_confidence)
        current=read_match(s,c.settings.ocr_confidence)
        return (current.page=='preparation' and current.gold==initial.gold and current.deployment==initial.deployment
                and len(equipment_items(s,item_name,c.settings.ocr_confidence))==count)
    current=wait_for(lambda s:board(s,original_count))
    if not finish(action,current):
        return False
    if not available:
        data['action_status']='equipment_role_occupied'
        persist()
        return True
    action=record('equip_'+item_name,current,name=profile.name,item=list(item),original_slots=list(original_slots))
    if item_name=='battery':
        c.currency_equip_battery(current,field,item,profile_scene)
    else:
        c.currency_equip_item(current,field,item,profile_scene,item_name)
    after=wait_for(lambda s:board(s,original_count-1))
    if after is None:
        return finish(action,None)
    verification=record('verify_equipped_'+item_name,after)
    c.currency_open_field(after,field)
    def equipped(s):
        current_profile=read_character(s,c.settings.ocr_confidence)
        slots=equipment_slots(s,c.settings.ocr_confidence)
        expected=list(original_slots)
        expected[expected.index('empty')]=item_name
        return current_profile==profile and sorted(slots)==sorted(expected)
    panel=wait_for(equipped)
    if not finish(verification,panel) or not finish(action,panel):
        return False
    action=record('close_equipped_role',panel)
    c.currency_close_character(panel)
    after=wait_for(lambda s:board(s,original_count-1))
    return finish(action,after)
