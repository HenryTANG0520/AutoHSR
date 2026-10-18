"""Free one bench slot only after proving the same named role is on the field."""
from dataclasses import dataclass
import re
import time

from .currency_wars import CurrencyWarsWorkflow
from .currency_wars_deployment import _crop,_texture,_similarity,bench_face
from .currency_wars_match import read_match
from .currency_wars_roster import candidate_at,validate_candidate,deployed_matches,read_character
from .models import AutomationError,EmptyCapture,normalize


@dataclass(frozen=True)
class FieldIdentity:
    zone: str
    slot: int
    point: tuple[float,float]
    node: str
    portrait: object


def field_roi(field):
    x=field.point[0]
    return (x-.025,.58,x+.025,.66) if field.zone=='back' else (x-.025,.33,x+.025,.41)


def validate_field_image(scene,field,confidence=.65):
    if type(field.slot) is not int or field.zone not in ('front','back') or not 1<=field.slot<=(4 if field.zone=='front' else 6):
        raise AutomationError('在场槽位超出已校准区域。')
    allowed=(((990,1180,1370,1560)[field.slot-1]/2560,530/1440),) if field.zone=='front' else tuple(
        ((first+190*(field.slot-1))/2560,890/1440) for first in (710,805))
    if field.point not in allowed:
        raise AutomationError('在场槽位坐标与序号不一致。')
    state=read_match(scene,confidence)
    if not state or state.node!=field.node or scene.image is None:
        raise AutomationError('在场角色节点未核实。')
    patch=_crop(scene.image,field_roi(field))
    if patch.shape!=field.portrait.shape or _texture(patch)<15 or _similarity(field.portrait,patch)<.92:
        raise AutomationError('在场角色头像已改变。')


def duplicate_candidate(scene,confidence=.65):
    state=read_match(scene,confidence)
    if not state or state.page not in ('preparation','bench_full') or not state.node or state.gold is None:
        raise AutomationError('整理备战席需要明确备战节点和金币。')
    # The first four bench slots remain visible under the character panel.
    # More distant candidates need a separate unobscured verification path.
    for slot in range(1,5):
        try:
            candidate=candidate_at(scene,slot,confidence,require_vacancy=False)
        except AutomationError:
            continue
        matches=deployed_matches(scene,candidate)
        if matches and matches[0][0]>=.90:
            _,zone,index,point=matches[0]
            provisional=FieldIdentity(zone,index,point,state.node,None)
            return candidate,FieldIdentity(zone,index,point,state.node,_crop(scene.image,field_roi(provisional)).copy())
    raise AutomationError('没有头像明确对应在场角色的备战副本，未出售独有角色。')


def sale_target(scene,candidate,field,field_profile,confidence=.65):
    if not 1<=candidate.slot<=4:
        raise AutomationError('仅验证角色面板下仍可见的前四个备战格。')
    profile=read_character(scene,confidence)
    if profile.name!=field_profile.name or profile.node!=candidate.node or profile.node!=field.node:
        raise AutomationError('备战角色与在场角色名称或节点不一致，未出售。')
    validate_field_image(scene,field,confidence)
    patch=_crop(scene.image,bench_face(candidate.slot))
    if patch.shape!=candidate.portrait.shape or _similarity(candidate.portrait,patch)<.92:
        raise AutomationError('待出售备战头像已改变。')
    prices={int(m[1]) for t in scene.tokens if confidence<=t.score<=1 and t.within((.83,.80,.92,.88))
            and (m:=re.fullmatch(r'\+([1-9][0-9]?)',normalize(t.text)))}
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='出售'
             and t.within((.88,.80,.98,.88))]
    if len(prices)!=1 or len(targets)!=1:
        raise AutomationError('备战副本出售金额和按钮未核实。')
    return next(iter(prices)),targets[0]


def sell_duplicate(c,scene,candidate,field,data,persist):
    guard=CurrencyWarsWorkflow(c)
    initial=read_match(scene,c.settings.ocr_confidence)
    last_error=''
    def record(action_kind,s,**extra):
        guard._require_current_scene(s)
        action=dict(action=action_kind,status='pending',source_slot=candidate.slot,
                    before=str(c.evidence(s,'currency_'+action_kind)),**extra)
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        return action
    def wait_for(predicate):
        nonlocal last_error
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
                except AutomationError as error:
                    last_error=str(error)
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        return None
    def finish(action,after):
        action['status']='verified' if after is not None else 'unknown'
        if after is not None:
            action['after']=str(c.evidence(after,'currency_'+action['action']+'_after'))
            data['screenshot']=action['after']
        elif c.last_scene is not None:
            action['after']=str(c.evidence(c.last_scene,'currency_'+action['action']+'_unknown'))
            action['reason']=last_error or '等待明确反馈超时。'
            data['screenshot']=action['after']
        data['action_status']=action['status']
        persist()
        return after is not None
    action=record('inspect_field_duplicate',scene,zone=field.zone,field_slot=field.slot)
    c.currency_open_field(scene,field)
    after=wait_for(lambda s:read_character(s,c.settings.ocr_confidence).node==candidate.node)
    if not finish(action,after):
        return False
    field_profile=read_character(after,c.settings.ocr_confidence)
    action['name']=field_profile.name
    action=record('close_field_duplicate',after)
    c.currency_close_character(after)
    def unchanged(s):
        validate_candidate(s,candidate,c.settings.ocr_confidence,require_vacancy=False)
        validate_field_image(s,field,c.settings.ocr_confidence)
        current=read_match(s,c.settings.ocr_confidence)
        return current.gold==initial.gold and current.deployment==initial.deployment
    current=wait_for(unchanged)
    if not finish(action,current):
        return False
    action=record('inspect_sale_candidate',current)
    c.currency_open_sale_candidate(current,candidate,field)
    after=wait_for(lambda s:bool(sale_target(s,candidate,field,field_profile,c.settings.ocr_confidence)))
    if not finish(action,after):
        return False
    price,_=sale_target(after,candidate,field,field_profile,c.settings.ocr_confidence)
    action=record('sell_duplicate',after,price=price,name=field_profile.name,gold_before=initial.gold)
    c.currency_sell_duplicate(after,candidate,field,field_profile)
    def sold(s):
        current=read_match(s,c.settings.ocr_confidence)
        validate_field_image(s,field,c.settings.ocr_confidence)
        source=_crop(s.image,bench_face(candidate.slot))
        gone=_texture(source)<8
        if initial.page=='bench_full' and not gone and source.shape==candidate.portrait.shape:
            # A waiting crystal reward can immediately occupy the released slot.
            # Require a clearly different portrait, exact sale proceeds and the
            # unchanged field; never require another click on that crystal.
            gone=_texture(source)>=15 and _similarity(candidate.portrait,source)<.5
        return (current.page in ('preparation','bench_full') and current.deployment==initial.deployment and
                current.gold==initial.gold+price and gone)
    after=wait_for(sold)
    if after is not None:
        action['gold_after']=read_match(after,c.settings.ocr_confidence).gold
        action['source_empty']=_texture(_crop(after.image,bench_face(candidate.slot)))<8
        action['overflow_reward_filled_slot']=initial.page=='bench_full' and not action['source_empty']
    return finish(action,after)
