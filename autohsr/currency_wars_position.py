"""Repair an unsupported backend placement after an interrupted drag."""
import time

import numpy as np

from .currency_wars import CurrencyWarsWorkflow
from .currency_wars_deployment import _crop,_texture
from .currency_wars_equipment import equipment_fields
from .currency_wars_match import read_match
from .currency_wars_roster import read_character
from .currency_wars_sale import FieldIdentity,field_roi,validate_field_image
from .models import AutomationError,EmptyCapture


def misplaced_backend(scene,confidence=.65):
    # Do not make a healthy board depend on layout recognition just to inspect
    # a marker that is absent. Only the calibrated red eligibility badge can
    # trigger this additional identity/position check.
    if scene.image is None:
        return None
    marked=False
    for first in (710,805):
        for slot in range(6):
            x=(first+190*slot)/2560
            badge=_crop(scene.image,(x+.020,.563,x+.030,.580))
            red=(badge[:,:,2]>160)&(badge[:,:,1]<130)&(badge[:,:,0]<130)
            marked=marked or bool(red.size and np.mean(red)>.25)
    if not marked:
        return None
    for field in equipment_fields(scene,confidence=confidence):
        if field.zone!='back':
            continue
        x=field.point[0]
        badge=_crop(scene.image,(x+.020,.563,x+.030,.580))
        red=(badge[:,:,2]>160)&(badge[:,:,1]<130)&(badge[:,:,0]<130)
        if red.size and np.mean(red)>.25:
            return field
    return None


def position_plan(scene,field,profile,confidence=.65):
    validate_field_image(scene,field,confidence)
    state=read_match(scene,confidence)
    if (state.page!='preparation' or state.gold is None or state.deployment is None or
            field.zone!='back' or profile.node!=field.node or profile.zones!=('front',)):
        raise AutomationError('只纠正已核实为仅前台的后台角色。')
    marked=misplaced_backend(scene,confidence)
    if marked is None or marked.point!=field.point:
        raise AutomationError('后台角色不适配标记已改变。')
    for slot,x in enumerate((990,1180,1370,1560),1):
        provisional=FieldIdentity('front',slot,(x/2560,530/1440),field.node,None)
        if _texture(_crop(scene.image,field_roi(provisional)))<8:
            return provisional
    raise AutomationError('没有明确的前台空位，未换位。')


def correct_position(c,scene,field,data,persist):
    guard=CurrencyWarsWorkflow(c)
    initial=read_match(scene,c.settings.ocr_confidence)
    def record(action_name,s,**extra):
        guard._require_current_scene(s)
        a=dict(action=action_name,status='pending',source_zone=field.zone,source_slot=field.slot,
               before=str(c.evidence(s,'currency_'+action_name)),**extra)
        data['actions'].append(a)
        data.update(action_status='pending',screenshot=a['before'])
        persist()
        return a
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
    def finish(a,s):
        a['status']='verified' if s is not None else 'unknown'
        captured=s if s is not None else c.last_scene
        if captured is not None:
            a['after']=str(c.evidence(captured,'currency_'+a['action']+'_after'))
            data['screenshot']=a['after']
        data['action_status']=a['status']
        persist()
        return s is not None
    a=record('inspect_misplaced_role',scene)
    c.currency_open_field(scene,field)
    panel=wait_for(lambda s:read_character(s,c.settings.ocr_confidence).node==field.node)
    if not finish(a,panel):
        return False
    profile=read_character(panel,c.settings.ocr_confidence)
    a=record('close_misplaced_role',panel,name=profile.name,zones=profile.zones)
    c.currency_close_character(panel)
    def unchanged(s):
        validate_field_image(s,field,c.settings.ocr_confidence)
        current=read_match(s,c.settings.ocr_confidence)
        return current.page=='preparation' and current.gold==initial.gold and current.deployment==initial.deployment
    board=wait_for(unchanged)
    if not finish(a,board):
        return False
    try:
        target=position_plan(board,field,profile,c.settings.ocr_confidence)
    except AutomationError as error:
        data.update(action_status='needs_decision',reason=str(error))
        persist()
        return False
    a=record('correct_role_position',board,name=profile.name,target_zone='front',target_slot=target.slot)
    c.currency_correct_position(board,field,profile)
    def moved(s):
        current=read_match(s,c.settings.ocr_confidence)
        return (current and current.page=='preparation' and current.node==initial.node and current.gold==initial.gold
                and current.deployment==initial.deployment and current.hp==initial.hp
                and _texture(_crop(s.image,field_roi(field)))<8
                and _texture(_crop(s.image,field_roi(target)))>=15)
    board_after=wait_for(moved)
    if board_after is None:
        return finish(a,None)
    target=FieldIdentity(target.zone,target.slot,target.point,target.node,_crop(board_after.image,field_roi(target)).copy())
    proof=record('verify_corrected_role',board_after,name=profile.name)
    c.currency_open_field(board_after,target)
    panel=wait_for(lambda s:read_character(s,c.settings.ocr_confidence)==profile)
    if not finish(proof,panel) or not finish(a,panel):
        return False
    a=record('close_corrected_role',panel,name=profile.name)
    c.currency_close_character(panel)
    return finish(a,wait_for(moved))
