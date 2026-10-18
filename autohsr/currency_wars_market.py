"""Bounded normal-shop purchases, independent of Gemi's own transactions."""
import time
import re
from dataclasses import asdict

import numpy as np

from .currency_wars import CurrencyWarsWorkflow
from .currency_wars_deployment import _crop,_texture,backend_layout,bench_face
from .currency_wars_match import read_match,verify_purchase
from .models import AutomationError,EmptyCapture,normalize


# A small A0 trial roster built around the observed starting follow-up units.
# This is a deterministic baseline, not an optimal-team claim.
ROSTER=('翡翠','砂金','灵砂','知更鸟','飞霄','阮梅','花火','藿藿','三月七','符玄','阿格莱雅','椒丘','乱破')


def overclock_board(scene):
    import cv2
    from .config import RESOURCE_ROOT
    if scene.image is None:
        return False
    image=cv2.resize(scene.image,(2560,1440))
    template=cv2.imread(str(RESOURCE_ROOT/'assets/templates/currency_overclock_4_6.png'))
    if template is None:
        raise AutomationError('超频模式图像缺失。')
    return bool(cv2.matchTemplate(image[1035:1098,300:380],template,cv2.TM_CCOEFF_NORMED).max()>=.92)


def normal_shop(scene,confidence=.65):
    state=read_match(scene,confidence)
    if not state or state.page!='shop' or not state.node or state.gold is None or state.probabilities is None:
        raise AutomationError('购买前商店节点、金币或概率未核实。')
    if backend_layout(scene.image)[0]!=6:
        raise AutomationError('当前不是已核实的普通商店布局，未干预代管交易。')
    if not overclock_board(scene):
        raise AutomationError('普通商店购买策略仅验证超频模式。')
    return state


def shop_trait_facts(scene,confidence=.65):
    traits={}
    for offer in read_match(scene,confidence).offers:
        left=.192+.14*offer.slot
        traits[offer.slot]=tuple(dict.fromkeys(normalize(t.text) for t in scene.tokens
            if confidence<=t.score<=1 and t.within((left,.165,left+.115,.265)) and
            re.fullmatch(r'[\u4e00-\u9fff]{2,10}',normalize(t.text)) and normalize(t.text)!='试用'))
    progress={}
    names=[t for t in scene.tokens if confidence<=t.score<=1 and t.within((.045,.12,.11,.76))
           and re.fullmatch(r'[\u4e00-\u9fff]{2,10}',normalize(t.text))]
    counts=[(t,re.fullmatch(r'([0-9]{1,2})/([1-9][0-9]?)',normalize(t.text))) for t in scene.tokens
            if confidence<=t.score<=1 and t.within((.045,.12,.11,.80))]
    for title in names:
        nearby=[m for token,m in counts if m and 0<token.center[1]-title.center[1]<.045]
        if len(nearby)==1:
            count,threshold=map(int,nearby[0].groups())
            if count<threshold:
                progress[normalize(title.text)]=(count,threshold)
    return traits,progress


def purchase_ranking(scene,confidence=.65):
    from .currency_wars_economy import Mode
    from .currency_wars_strategy import PurchaseSituation,rank_purchases
    state=normal_shop(scene,confidence)
    occupied=sum(_texture(_crop(scene.image,bench_face(slot)))>=15 for slot in range(1,10))
    if occupied>=5:
        return ()
    traits,progress=shop_trait_facts(scene,confidence)
    situation=PurchaseSituation(Mode.OVERCLOCK,state.gold,9-occupied)
    return rank_purchases(state.offers,situation,traits=traits,progress=progress,
                          preferences={name:max(1.,8.-index*.5) for index,name in enumerate(ROSTER)})


def purchase_choice(scene,confidence=.65):
    ranked=purchase_ranking(scene,confidence)
    state=read_match(scene,confidence)
    return next((o for o in state.offers if ranked and o.slot==ranked[0].slot),None)


def purchase_target(scene,offer,confidence=.65):
    state=normal_shop(scene,confidence)
    if purchase_choice(scene,confidence)!=offer or offer not in state.offers:
        raise AutomationError('购买候选、金额或备战空间已改变。')
    left=.192+.14*offer.slot
    names=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)==offer.name
           and t.within((left,.265,left+.115,.305))]
    if len(names)!=1:
        raise AutomationError('购买卡片名称不唯一。')
    return names[0]


def purchase_feedback(before,after,offer,confidence=.65):
    first,last=read_match(before,confidence),read_match(after,confidence)
    if first is None or last is None or verify_purchase(first,last,offer)!='verified':
        return False
    if tuple(o for o in first.offers if o.slot!=offer.slot)!=last.offers:
        return False
    if before.image is None or after.image is None or before.image.shape!=after.image.shape:
        return False
    # New roles or merges must also change a bench portrait, not just gold.
    return any(np.mean(np.abs(_crop(before.image,bench_face(slot)).astype(float)-
                              _crop(after.image,bench_face(slot)).astype(float)))>=8 for slot in range(1,10))


def buy_offer(c,before,offer,data,persist):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(before)
    purchase_target(before,offer,c.settings.ocr_confidence)
    previous=read_match(before,c.settings.ocr_confidence)
    action=dict(action='buy_shop_role',slot=offer.slot,name=offer.name,cost=offer.cost,gold_before=previous.gold,
                origin_node=previous.node,status='pending',before=str(c.evidence(before,'currency_buy_role_before')))
    action['decision']=asdict(purchase_ranking(before,c.settings.ocr_confidence)[0])
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_buy_offer(before,offer)
    elapsed=0.
    while elapsed<12:
        started=time.monotonic()
        inactive=c.runner.inactive_duration
        try:
            after=c.snapshot()
        except EmptyCapture:
            after=None
        if after is not None:
            guard._require_current_scene(after)
            if purchase_feedback(before,after,offer,c.settings.ocr_confidence):
                action.update(status='verified',gold_after=read_match(after,c.settings.ocr_confidence).gold,
                              after=str(c.evidence(after,'currency_buy_role_after')))
                data.update(action_status='purchase_verified',screenshot=action['after'])
                persist()
                return True
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    action['status']='unknown'
    if c.last_scene is not None:
        action['after']=str(c.evidence(c.last_scene,'currency_buy_role_unknown'))
        data['screenshot']=action['after']
    data['action_status']='unknown'
    persist()
    return False


def open_shop_target(scene,confidence=.65):
    state=read_match(scene,confidence)
    if not state or state.page!='preparation' or not state.node or state.gold is None:
        raise AutomationError('打开商店需要已核实的备战节点和金币。')
    if backend_layout(scene.image)[0]!=6:
        raise AutomationError('代管布局不自动打开商店。')
    if not overclock_board(scene):
        raise AutomationError('未核实超频模式，未自动打开商店。')
    matches=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='商店'
             and t.within((.81,.88,.89,.95))]
    if len(matches)!=1:
        raise AutomationError('商店入口不唯一。')
    return matches[0]


def open_shop(c,before,data,persist):
    guard=CurrencyWarsWorkflow(c)
    guard._require_current_scene(before)
    open_shop_target(before,c.settings.ocr_confidence)
    previous=read_match(before,c.settings.ocr_confidence)
    action=dict(action='open_shop',origin_node=previous.node,status='pending',
                before=str(c.evidence(before,'currency_open_shop_before')))
    data['actions'].append(action)
    data.update(action_status='pending',screenshot=action['before'])
    persist()
    c.currency_open_shop(before)
    elapsed=0.
    while elapsed<12:
        started=time.monotonic()
        inactive=c.runner.inactive_duration
        try:
            after=c.snapshot()
        except EmptyCapture:
            after=None
        if after is not None:
            guard._require_current_scene(after)
            current=read_match(after,c.settings.ocr_confidence)
            if current and current.page=='shop' and current.node==previous.node and current.gold==previous.gold:
                action.update(status='verified',after=str(c.evidence(after,'currency_open_shop_after')))
                data.update(action_status='shop_opened',screenshot=action['after'])
                persist()
                return True
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    action['status']='unknown'
    data['action_status']='unknown'
    if c.last_scene is not None:
        action['after']=str(c.evidence(c.last_scene,'currency_open_shop_unknown'))
        data['screenshot']=action['after']
    persist()
    return False
