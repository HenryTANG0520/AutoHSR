"""Explicitly requested start of a locally calibrated overclock A0 match."""
import re
import time

from .currency_wars import CurrencyWarsWorkflow,observe
from .models import AutomationError,EmptyCapture,normalize


def unique(scene,label,roi,confidence):
    labels=(label,) if isinstance(label,str) else label
    found=[t for t in scene.tokens if confidence<=t.score<=1 and
           normalize(t.text).translate(str.maketrans('','','「」')) in labels and t.within(roi)]
    if len(found)!=1:
        raise AutomationError('开局按钮或模式证据不唯一：'+str(label))
    return found[0]


def overclock_selected(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='mode_select':
        return False
    try:
        unique(scene,'超频博弈',(.30,.11,.40,.18),confidence)
        unique(scene,'*无法通过该玩法模式提升职级',(.29,.27,.49,.34),confidence)
        unique(scene,'进入超频博弈',(.75,.85,.96,.94),confidence)
    except AutomationError:
        return False
    return True


def entry_target(scene,confidence=.65):
    kind=observe(scene,confidence).page_kind
    if kind=='lobby':
        return 'open_mode','mode_select',unique(scene,'开始货币战争',(.65,.84,.99,.96),confidence)
    if kind=='mode_select':
        if overclock_selected(scene,confidence):
            return 'enter_overclock','difficulty_select',unique(scene,'进入超频博弈',(.75,.85,.96,.94),confidence)
        return 'select_overclock','overclock_selected',unique(scene,'超频博弈',(0,.33,.2,.43),confidence)
    if kind=='difficulty_select':
        ranks=[t for t in scene.tokens if confidence<=t.score<=1 and t.within((.02,.26,.20,.33))]
        if len(ranks)!=1 or not re.fullmatch(r'a[0o]黑铁',normalize(ranks[0].text)):
            raise AutomationError('整局验证只允许已核实的超频 A0 黑铁1，当前难度不符。')
        unique(scene,'开局时获得【精密拆装扳手】',(.36,.34,.65,.39),confidence)
        unique(scene,'敌人难度+1',(.36,.38,.55,.44),confidence)
        return 'start_overclock_a0','boss_preview',unique(scene,'开始对局',(.80,.85,.97,.94),confidence)
    if kind=='boss_preview':
        unique(scene,'敌人难度1',(.02,.87,.15,.95),confidence)
        return 'advance_boss_preview','plane_map',unique(scene,'下一步',(.74,.87,.84,.95),confidence)
    raise AutomationError('当前不是已校准的超频开局界面。')


def advance_entry(c,scene,data,persist):
    if not getattr(c.runner,'currency_start_from_lobby',False):
        raise AutomationError('本次没有请求从主页开始整局验证。')
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(scene)
    name,expected,_=entry_target(scene,c.settings.ocr_confidence)
    if any(a.get('action')==name for a in data['actions']):
        raise AutomationError('同一开局步骤已提交，未重复执行。')
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
                if name=='start_overclock_a0':
                    data['overclock_a0_started']=True
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
