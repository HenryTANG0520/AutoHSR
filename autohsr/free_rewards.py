"""Observed free-reward controls; paid controls are never navigation targets."""
from __future__ import annotations

import re
from .models import Scene, Token, normalize

TITLE=(0,0,.32,.13)


def phone(scene):
    return scene.has('开拓等级',(.55,.05,.99,.35)) and scene.has(
        ('委托','星际和平指南','指南','无名勋礼'),(.55,.25,1,1))


def icon(scene,name,roi,threshold=.94):
    if scene.image is None:
        return None
    import cv2
    from .config import RESOURCE_ROOT
    from .vision import Vision
    h,w=scene.image.shape[:2]
    baseline=Scene(scene.tokens,cv2.resize(scene.image,(1920,round(h*1920/w))))
    path=RESOURCE_ROOT/'assets/templates'/f'{name}.png'
    if not path.is_file():
        return None
    match=Vision.__new__(Vision).template(baseline,path,roi,threshold)
    if match is None:
        return None
    x,y,score=match
    return Token(name,score,(x-.008,y-.010,x+.008,y+.010))


def mail_entry(scene):
    # Current phone skins omit the mailbox label. Match only the lower
    # envelope body, excluding its red notification badge, on a verified phone.
    return icon(scene,'phone_mail_body',(.95,.22,.995,.29)) if phone(scene) else None


def gold_fraction(scene,box):
    if scene.image is None:
        return None
    import cv2
    import numpy as np
    h,w=scene.image.shape[:2]
    x1,y1,x2,y2=(round(v*n) for v,n in zip(box,(w,h,w,h)))
    if not (0<=x1<x2<=w and 0<=y1<y2<=h):
        return None
    hsv=cv2.cvtColor(scene.image[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
    return float(np.mean((hsv[:,:,0]>=12)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>=100)&(hsv[:,:,2]>=170)))


def claim_enabled(scene,target):
    """Gold is enabled, neutral fill disabled, dark/occluded is unknown."""
    x,y=target.center
    box=(x-.045,y-.020,x+.045,y+.020)
    fraction=gold_fraction(scene,box)
    if fraction is None:
        return None
    if fraction>.35:
        return True
    import cv2
    import numpy as np
    h,w=scene.image.shape[:2]
    x1,y1,x2,y2=(round(v*n) for v,n in zip(box,(w,h,w,h)))
    hsv=cv2.cvtColor(scene.image[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
    neutral=(hsv[:,:,1]<60)&(hsv[:,:,2]>=70)
    return False if fraction<.05 and float(np.mean(neutral))>.45 else None


def mailbox(scene):
    return scene.has(('邮箱','邮件'),TITLE,exact=True) and (
        scene.has('暂无邮件') or (scene.has('删除已读',(0,.83,.40,.97),exact=True)
                                 and scene.has('全部领取',(.12,.83,.35,.97),exact=True)))


def mail_claimed(scene):
    if not mailbox(scene) or reward_overlay(scene):
        return False
    target=scene.find('全部领取',(.12,.83,.35,.97),exact=True)
    if target is None or claim_enabled(scene,target) is True:
        return False
    # Mail's disabled control is transparent rather than neutral-filled.
    # Its pale circled-arrow glyph has the opposite contrast to the enabled
    # gold button. Absence of gold alone cannot prove an empty mailbox.
    return icon(scene,'mail_disabled_arrow',(.16,.89,.195,.94)) is not None


def reward_overlay(scene):
    return scene.has('获得物品',(.25,.04,.75,.50),exact=True)


def battlepass_page(scene):
    if (reward_overlay(scene) or not scene.has('无名勋礼',TITLE,exact=True)
            or not scene.has('本周经验上限',(.60,.23,.85,.30))
            or not scene.has('剩余时间',(.16,.18,.40,.25))):
        return None
    if scene.has('任务',TITLE,exact=True) and all(scene.has(label,(.07,.31,.20,.74),exact=True)
                                                for label in ('本周任务','本期任务')):
        return 'tasks'
    if (scene.has('奖励',TITLE,exact=True)
            and scene.has('无名客的赠礼',(.07,.45,.20,.56),exact=True)
            and scene.has('无名客的荣勋',(.07,.69,.20,.79),exact=True)):
        return 'rewards'
    return None


def battlepass_modal(scene):
    return scene.has(('确认购买','支付','选择奖励','请选择奖励','购买等级','解锁无名客的荣勋'),
                     (.27,.30,.73,.72),exact=True)


def battlepass_tab(scene,kind):
    if battlepass_page(scene) is None or battlepass_modal(scene):
        return None
    if kind=='tasks':
        return icon(scene,'bp_tasks_tab',(.477,.025,.523,.08))
    if kind=='rewards':
        return icon(scene,'bp_rewards_tab',(.427,.025,.474,.08))
    return None


def task_category(scene,label):
    if battlepass_page(scene)!='tasks':
        return False
    target=scene.find(label,(.07,.31,.20,.74),exact=True)
    y=target.center[1] if target else 0
    fraction=gold_fraction(scene,(.079,y-.065,.084,y+.065)) if target else None
    return fraction is not None and fraction>.20


def battlepass_progress(scene):
    if battlepass_page(scene) is None:
        return None
    levels=[int(normalize(t.text)) for t in scene.tokens if t.within((.08,.18,.17,.28))
            and re.fullmatch(r'\d{1,3}',normalize(t.text))]
    ratios=[]
    for t in scene.tokens:
        if t.within((.74,.19,.83,.24)):
            match=re.fullmatch(r'(\d{1,5})/(\d{1,5})',normalize(t.text))
            if match and 0<=int(match[1])<=int(match[2]) and int(match[2])>0:
                ratios.append(tuple(map(int,match.groups())))
    return (levels[0],*ratios[0]) if len(levels)==len(ratios)==1 else None


def battlepass_settled(scene,kind):
    if kind not in ('tasks','rewards') or battlepass_page(scene)!=kind or battlepass_modal(scene):
        return False
    if scene.has('一键领取',(.60,.79,.98,.91),exact=True):
        return False
    if scene.image is None:
        return False
    import cv2
    import numpy as np
    h,w=scene.image.shape[:2]
    # A red notification on the current top tab contradicts "nothing to claim".
    x1,x2=(.458,.47) if kind=='rewards' else (.507,.52)
    hsv=cv2.cvtColor(scene.image[round(.02*h):round(.05*h),round(x1*w):round(x2*w)],cv2.COLOR_BGR2HSV)
    red=((hsv[:,:,0]<10)|(hsv[:,:,0]>170))&(hsv[:,:,1]>130)&(hsv[:,:,2]>160)
    if float(np.mean(red))>.07:
        return False
    if kind=='tasks':
        return scene.has(('追踪','已完成'),(.82,.33,.94,.77),exact=True)
    return True
