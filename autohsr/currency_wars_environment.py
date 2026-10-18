"""Choose only environment effects read completely from local captures."""
import time

import numpy as np

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_deployment import _crop
from .currency_wars_match import read_match
from .models import AutomationError,EmptyCapture,normalize


CENTERS=(.229,.50,.771)


def environment_choice(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='environment':
        raise AutomationError('投资环境页未核实。')
    for cx in CENTERS:
        names=[t for t in scene.tokens if confidence<=t.score<=1 and
               t.within((cx-.11,.34,cx+.11,.38)) and normalize(t.text)=='人身意外险']
        effect=sorted((t for t in scene.tokens if confidence<=t.score<=1 and
                       t.within((cx-.11,.38,cx+.11,.47))),key=lambda t:(round(t.center[1],2),t.center[0]))
        if len(names)==1 and ''.join(normalize(t.text) for t in effect)=='所有首领节点前都加入一个额外补给阶段':
            return names[0],cx
    raise AutomationError('没有完整核实效果的投资环境，未刷新或选择。')


def environment_confirm(scene,confidence=.65):
    _,cx=environment_choice(scene,confidence)
    if scene.image is None:
        raise AutomationError('环境选择缺少选中反馈图像。')
    chosen=[]
    for center in CENTERS:
        border=_crop(scene.image,(center-.123,.20,center-.121,.79))
        if border.size and np.mean(np.min(border,axis=2)>200)>=.5:
            chosen.append(center)
    button=_crop(scene.image,(.50,.895,.62,.925))
    if chosen!=[cx] or button.size==0 or np.mean(np.min(button,axis=2)>180)<.5:
        raise AutomationError('环境卡片边框或确认按钮与本次选择不符。')
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='确认' and
             t.within((.50,.87,.65,.95))]
    if len(targets)!=1:
        raise AutomationError('投资环境确认按钮不唯一。')
    return targets[0]


def choose_environment(c,scene,data,persist):
    name,_=environment_choice(scene,c.settings.ocr_confidence)
    guard=CurrencyWarsWorkflow(c)
    try:
        environment_confirm(scene,c.settings.ocr_confidence)
        phases=('confirm',)
    except AutomationError:
        phases=('select','confirm')
    for phase in phases:
        guard._require_current_scene(scene)
        action=dict(action=phase+'_environment',name=name.text,status='pending',
                    before=str(c.evidence(scene,'currency_environment_'+phase)))
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        c.currency_select_environment(scene,confirm=phase=='confirm')
        elapsed=0.
        while elapsed<20:
            started=time.monotonic()
            inactive=c.runner.inactive_duration
            try:
                after=c.snapshot()
            except EmptyCapture:
                after=None
            if after is not None:
                guard._require_current_scene(after)
                current=read_match(after,c.settings.ocr_confidence)
                ready=bool(current and current.page in ('shop','preparation') and current.node=='1-1') if phase=='confirm' else False
                if phase=='select':
                    try:
                        environment_confirm(after,c.settings.ocr_confidence)
                        ready=True
                    except AutomationError:
                        pass
                if ready:
                    action.update(status='verified',after=str(c.evidence(after,'currency_environment_after_'+phase)))
                    data.update(action_status='environment_verified',screenshot=action['after'])
                    if phase=='confirm':
                        data['environment']='人身意外险'
                    persist()
                    scene=after
                    break
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status']='unknown'
            if c.last_scene is not None:
                action['after']=str(c.evidence(c.last_scene,'currency_environment_unknown'))
                data['screenshot']=action['after']
            data['action_status']='unknown'
            persist()
            return False
    return True
