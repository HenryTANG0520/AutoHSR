"""Explicitly requested start of a locally calibrated overclock A0 match."""
import time

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_overclock import (
    ACTIVE_MATCH, _OPEN_A0, _SELECT, _START_A0, _target, read_overclock, read_overclock_start, start_overclock,
)
from .currency_wars_overclock_session import START_ACTION, START_FEEDBACK
from .currency_wars_prepare import trusted
from .currency_wars_standard import NAVIGATION_BLOCKERS
from .models import AutomationError,EmptyCapture,normalize


def unique(scene,label,roi,confidence):
    labels=(label,) if isinstance(label,str) else label
    found=[t for t in scene.tokens if confidence<=t.score<=1 and
           normalize(t.text).translate(str.maketrans('','','「」')) in labels and t.within(roi)]
    if len(found)!=1:
        raise AutomationError('开局按钮或模式证据不唯一：'+str(label))
    return found[0]


def overclock_selected(scene,confidence=.65):
    return read_overclock(scene,confidence,require_a0_details=True).state == 'overclock_selected'


def entry_target(scene,confidence=.65):
    if trusted(scene, confidence).has((*NAVIGATION_BLOCKERS, *ACTIVE_MATCH)):
        raise AutomationError('当前超频入口有未处理的旧局、认证或更新提示。')
    kind=observe(scene,confidence).page_kind
    if kind=='lobby':
        return 'open_mode','mode_select',unique(scene,'开始货币战争',(.65,.84,.99,.96),confidence)
    if kind=='mode_select':
        if overclock_selected(scene,confidence):
            return 'enter_overclock','difficulty_select',_target(scene,confidence,_OPEN_A0)
        return 'select_overclock','overclock_selected',_target(scene,confidence,_SELECT)
    if kind=='difficulty_select':
        return START_ACTION,START_FEEDBACK,_target(scene,confidence,_START_A0)
    if kind=='boss_preview':
        if read_overclock_start(scene, confidence).state != START_FEEDBACK:
            raise AutomationError('当前首领预览未核实为敌人难度 1。')
        return 'advance_boss_preview','plane_map',unique(scene,'下一步',(.74,.87,.84,.95),confidence)
    raise AutomationError('当前不是已校准的超频开局界面。')


def advance_entry(c,scene,data,persist):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(scene)
    name,expected,_=entry_target(scene,c.settings.ocr_confidence)
    if not getattr(c.runner,'currency_start_from_lobby',False) and name != 'advance_boss_preview':
        raise AutomationError('本次没有请求从主页开始整局验证。')
    if any(a.get('action')==name for a in data['actions']):
        raise AutomationError('同一开局步骤已提交，未重复执行。')
    if name == START_ACTION:
        result = start_overclock(c)
        opening = c.report.currency_wars
        data['opening'] = opening
        data['actions'].extend(opening['actions'])
        if result.status == 'ok':
            data.update(overclock_a0_started=True, action_status='entry_verified',
                        screenshot=opening['feedback'][-1]['screenshot'])
        else:
            data.update(action_status='unknown' if opening['actions'] else 'needs_decision', reason=result.detail)
        persist()
        return result.status == 'ok'
    action=dict(action=name,status='pending',next_page=expected,
                before=str(c.evidence(scene,'currency_entry_'+name)))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_advance_entry(scene,name)
    elapsed=0.
    while elapsed<25:
        started=time.monotonic()
        inactive=c.runner.inactive_duration
        try:
            after=c.snapshot()
        except EmptyCapture:
            after=None
        if after is not None:
            guard._require_current_scene(after)
            ready=(overclock_selected(after,c.settings.ocr_confidence) if expected=='overclock_selected'
                   else observe(after,c.settings.ocr_confidence).page_kind==expected)
            if ready:
                action.update(status='verified',after=str(c.evidence(after,'currency_entry_after_'+name)))
                data.update(action_status='entry_verified',screenshot=action['after'])
                if name=='open_mode':
                    data['started_from_lobby']=True
                persist()
                return True
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    action['status']='unknown'
    if c.last_scene is not None:
        action['after']=str(c.evidence(c.last_scene,'currency_entry_unknown'))
        data['screenshot']=action['after']
    data['action_status']='unknown'
    persist()
    return False
