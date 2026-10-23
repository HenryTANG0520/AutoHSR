"""Opt-in, screenshot-driven collection of existing DU notification rewards."""
from __future__ import annotations

import re
from .models import AutomationError,Token,normalize

HOME_LABELS=('拟合等级','月下奇谭','稳态数组','可能性画廊')
GALLERY_LABELS=('祝福','奇物','惊世奇迹','方程','加权奇物','事件')


def home(scene):
    return (scene.has('差分宇宙',(0,0,.32,.13)) and scene.has('乐园漫记',(0,0,.32,.20))
            and scene.has('开始游戏',(.65,.80,1,1),exact=True))


def red_dots(scene,roi=(0,0,1,1)):
    """Small red circular badges with a white interior mark, not red artwork."""
    if scene.image is None:
        return []
    import cv2
    import numpy as np
    h,w=scene.image.shape[:2]
    x1,y1,x2,y2=(round(roi[0]*w),round(roi[1]*h),round(roi[2]*w),round(roi[3]*h))
    patch=scene.image[y1:y2,x1:x2]
    if not patch.size:
        return []
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    mask=(((hsv[:,:,0]<9)|(hsv[:,:,0]>171))&(hsv[:,:,1]>140)&(hsv[:,:,2]>140)).astype('uint8')*255
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    dots=[]
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        if not (.010*h<=bh<=.032*h and .65<=bw/bh<=1.5):
            continue
        area=cv2.contourArea(contour)
        perimeter=cv2.arcLength(contour,True)
        if (not .55<=area/(bw*bh)<=.90 or perimeter<=0
                or 4*np.pi*area/(perimeter*perimeter)<.70):
            continue
        inner=hsv[y+bh//4:y+3*bh//4,x+bw//4:x+3*bw//4]
        if not inner.size or np.mean((inner[:,:,1]<85)&(inner[:,:,2]>190))<.05:
            continue
        dots.append(Token('差分宇宙红点',.99,((x1+x)/w,(y1+y)/h,(x1+x+bw)/w,(y1+y+bh)/h)))
    return sorted(dots,key=lambda t:(t.center[1],t.center[0]))


def home_targets(scene):
    if not home(scene):
        return []
    dots=red_dots(scene,(.66,.23,.995,.70))
    targets=[]
    for label in HOME_LABELS:
        token=scene.find(label,(.66,.23,.99,.70),exact=True)
        if token and any(-.012<dot.center[0]-token.box[2]<.045
                         and -.04<dot.center[1]-token.center[1]<.01 for dot in dots):
            targets.append(token)
    return targets


def page_kind(scene):
    if home(scene):
        return 'home'
    if scene.has('获得物品',(.25,.04,.75,.25),exact=True) and scene.has('点击空白处关闭',(.25,.65,.75,.90),exact=True):
        return 'reward_overlay'
    if (scene.has('可能性画廊',(0,0,.32,.13),exact=True)
            and scene.has('奖励领取进度',(.65,0,.85,.13))
            and scene.has('收集进度',(.83,0,.98,.13))):
        return 'gallery_home'
    progress=[t for t in scene.tokens if t.within((.06,.87,.26,.96))
              and re.fullmatch(r'奖励进度\d+/\d+',normalize(t.text))]
    if (scene.has(GALLERY_LABELS,(0,0,.32,.13),exact=True) and progress
            and scene.has('一览',(.05,.10,.72,.18))):
        return 'gallery_category'
    if (scene.has(('奇迹返现','并奇迹返现'),(.20,.20,.42,.27),exact=True)
            and len([t for t in scene.tokens if t.within((.21,.27,.40,.79))
                     and normalize(t.text)=='累计解锁数量达到'])>=2):
        return 'gallery_milestones'
    if (scene.has('月下奇谭',(.18,.14,.40,.20)) and scene.has('道具一览',(.12,.58,.30,.65),exact=True)
            and scene.has(('使用卡带获取下一道具','所有道具均已获得'),(.62,.64,.86,.73),exact=True)):
        return 'moon_rewards'
    if (scene.has('技能提升',(.35,.13,.65,.23),exact=True)
            and scene.has('前往查看剧情',(.35,.72,.65,.82),exact=True)):
        return 'moon_unlocked'
    if (scene.has('事件',(0,0,.32,.13),exact=True) and scene.has('差分宇宙',(0,0,.32,.13))
            and scene.has('秘闻',(.05,.75,.30,.91),exact=True)):
        return 'moon_story'
    if (scene.has('稳态数组',(0,0,.32,.13),exact=True) and
            scene.has('测试',(.33,.07,.50,.15),exact=True) and scene.has('难题',(.50,.07,.67,.15),exact=True)):
        return 'steady_rewards'
    if not scene.has('差分宇宙',(0,0,.32,.13)):
        return None
    # The fitting-level screen has a central XP counter and a horizontal row
    # of numbered reward tiers, including tiers above the current level.
    xp=[t for t in scene.tokens if t.within((.40,.46,.60,.56))
        and re.fullmatch(r'\d{1,5}/[1-9]\d{2,4}',normalize(t.text))]
    tiers=[t for t in scene.tokens if t.within((0,.80,1,.87))
           and re.fullmatch(r'[1-9]\d{0,2}',normalize(t.text))]
    if len(xp)==1 and len(tiers)>=3:
        return 'fit_rewards'
    return None


def gallery_targets(scene):
    if page_kind(scene)!='gallery_home':
        return []
    dots=red_dots(scene,(.02,.30,.98,.88))
    return [t for t in scene.tokens if normalize(t.text) in GALLERY_LABELS
        and t.within((.02,.30,.98,.88)) and any(
            -.012<dot.center[0]-t.box[2]<.045
            and -.04<dot.center[1]-t.center[1]<.01 for dot in dots)]


def gallery_progress_target(scene):
    if page_kind(scene)!='gallery_category' or not red_dots(scene,(.06,.85,.26,.96)):
        return None
    return next((t for t in scene.tokens if t.within((.06,.87,.26,.96))
        and re.fullmatch(r'奖励进度\d+/\d+',normalize(t.text))),None)


def moon_balance(scene):
    if page_kind(scene)!='moon_rewards':
        return None
    values=[int(normalize(t.text)) for t in scene.tokens if t.within((.86,.03,.94,.09))
            and re.fullmatch(r'\d{1,5}',normalize(t.text))]
    return values[0] if len(values)==1 else None


def moon_unlock_target(scene):
    balance=moon_balance(scene)
    if balance is None or balance<100:
        return None
    target=scene.find('解锁',(.73,.74,.84,.81),exact=True)
    price=scene.has('×100',(.68,.74,.73,.81),exact=True)
    return target if price and red_dots(scene,(.81,.73,.86,.80)) else None


def steady_targets(scene):
    if page_kind(scene)!='steady_rewards':
        return []
    targets=[]
    for dot in red_dots(scene,(.01,.05,.67,.94)):
        if dot.within((.33,.05,.67,.15)):
            roi=(.33,.07,.50,.15) if dot.center[0]<.50 else (.50,.07,.67,.15)
            token=scene.find(('测试','难题'),roi,exact=True)
        elif dot.within((.01,.16,.23,.94)):
            names=[t for t in scene.tokens if t.within((.02,.17,.21,.94))
                   and re.fullmatch(r'[一-鿿]{2,10}',normalize(t.text))
                   and abs(t.center[1]-dot.center[1])<.045]
            token=min(names,key=lambda t:abs(t.center[1]-dot.center[1]),default=None)
        else:
            token=None
        if token and token not in targets:
            targets.append(token)
    return targets


def guard_click(scene,target,intent):
    allowed=False
    if intent=='du_reward_open':
        allowed=target in home_targets(scene)
    elif intent=='du_reward_dot' and page_kind(scene)=='fit_rewards':
        allowed=any(abs(dot.center[0]-target.center[0])<.002 and abs(dot.center[1]-target.center[1])<.002
                    for dot in red_dots(scene,(0,.67,1,.87)))
    elif intent=='du_reward_dismiss':
        allowed=(page_kind(scene)=='reward_overlay' and normalize(target.text)=='点击空白处关闭'
                 and target.within((.25,.65,.75,.90)))
    elif intent=='du_reward_unlock':
        allowed=target==moon_unlock_target(scene)
    elif intent=='du_reward_story_open':
        allowed=(page_kind(scene)=='moon_unlocked' and normalize(target.text)=='前往查看剧情'
                 and target.within((.35,.72,.65,.82)))
    elif intent=='du_reward_steady_tab':
        allowed=target in steady_targets(scene)
    elif intent=='du_reward_claim':
        allowed=(page_kind(scene)=='steady_rewards' and normalize(target.text)=='领取'
                 and target.within((.86,.18,.98,.95)))
    elif intent=='du_reward_gallery_category':
        allowed=target in gallery_targets(scene)
    elif intent=='du_reward_gallery_progress':
        allowed=target==gallery_progress_target(scene)
    elif intent=='du_reward_gallery_claim':
        allowed=(page_kind(scene)=='gallery_milestones' and target in scene.tokens
                 and normalize(target.text)=='领取' and target.within((.68,.27,.79,.79)))
    if not allowed:
        raise AutomationError('未核实差分宇宙领奖页面、红点或已获得奖励提示，未点击。')


def collect(workflow,scene):
    """Collect only marked existing rewards; retain before/after evidence."""
    report=workflow.report.setdefault('reward_collection',{'claims':[],'visits':[]})
    if not workflow.settings.differential_universe_rewards:
        report['status']='disabled'
        return scene
    report['status']='collecting'
    report.pop('home_evidence',None)
    report.pop('failure_reason',None)
    workflow._persist_ledger()
    try:
        return _collect(workflow,scene,report)
    except AutomationError as error:
        if report['status']=='collecting':
            report['status']='failed'
        report['failure_reason']=str(error)
        workflow._persist_ledger()
        raise


def _collect(workflow,scene,report):
    ctx=workflow.ctx
    if page_kind(scene) in ('gallery_home','gallery_category','gallery_milestones'):
        scene=collect_gallery(workflow,scene,report)
        ctx.key('esc')
        scene=ctx.wait(home,timeout=20,description='画廊断点领奖后返回主页')
    if not home(scene):
        raise AutomationError('红点领奖须从差分宇宙主页开始。')
    visited={}
    for _ in range(24):
        targets=home_targets(scene)
        if not targets:
            if red_dots(scene):
                report['status']='unhandled_notification'
                report['home_evidence']=str(ctx.evidence(scene,'du_rewards_unhandled_red_dot'))
                workflow._persist_ledger()
                raise AutomationError('差分宇宙主页仍有未绑定到已支持入口的红点，已留证，未报告全部领完。')
            report['status']='complete'
            report['home_evidence']=str(ctx.evidence(scene,'du_rewards_home_verified'))
            workflow._persist_ledger()
            return scene
        # Other categories can award fitting XP and unlock a new tier after
        # this entry was cleared. Revisit only after a verified reward receipt.
        progress=len(report['claims'])
        target=next((t for t in targets if t.text not in visited or progress>visited[t.text]),None)
        if target is None:
            raise AutomationError('红点入口返回后没有新的奖励到账进展，停止重复进入领奖。')
        label=target.text
        visited[label]=progress
        report['visits'].append(label)
        workflow._persist_ledger()
        ctx.click(scene,target,du_intent='du_reward_open')
        scene=ctx.last_scene
        scene=ctx.wait(lambda p:page_kind(p) not in (None,'home'),timeout=20,description=label+'奖励页加载')
        if page_kind(scene)=='moon_rewards':
            scene=collect_moon(workflow,scene,report)
        elif page_kind(scene)=='fit_rewards':
            scene=collect_fit(workflow,scene,report,label)
        elif page_kind(scene)=='steady_rewards':
            scene=collect_steady(workflow,scene,report)
        elif page_kind(scene)=='gallery_home':
            scene=collect_gallery(workflow,scene,report)
        else:
            raise AutomationError(f'{label}奖励页尚未支持，已保留画面等待完善。')
        workflow._persist_ledger()
        ctx.key('esc')
        scene=ctx.wait(home,timeout=20,description='返回差分宇宙主页复核红点')
    raise AutomationError('差分宇宙红点入口遍历达到上限。')


def collect_gallery(workflow,scene,report):
    ctx=workflow.ctx
    visited=set()
    for _ in range(240):
        kind=page_kind(scene)
        if kind=='gallery_home':
            targets=gallery_targets(scene)
            if not targets:
                if red_dots(scene):
                    raise AutomationError('可能性画廊仍有未绑定分类的红点，未报告全部领取。')
                return scene
            target=next((t for t in targets if t.text not in visited),None)
            if target is None:
                raise AutomationError('画廊分类返回后仍有红点，停止重复进入。')
            visited.add(target.text)
            ctx.click(scene,target,du_intent='du_reward_gallery_category')
            scene=ctx.wait(lambda page:page_kind(page)=='gallery_category',timeout=20,
                           description='画廊分类与奖励进度')
        elif kind=='gallery_category':
            target=gallery_progress_target(scene)
            if target is None:
                ctx.key('esc')
                scene=ctx.wait(lambda page:page_kind(page)=='gallery_home',timeout=20,
                               description='返回可能性画廊')
                continue
            ctx.click(scene,target,du_intent='du_reward_gallery_progress')
            scene=ctx.wait(lambda page:page_kind(page)=='gallery_milestones',timeout=20,
                           description='画廊已解锁奖励列表')
        elif kind=='gallery_milestones':
            target=scene.find('领取',(.68,.27,.79,.79),exact=True)
            if target is None:
                ctx.key('esc')
                scene=ctx.wait(lambda page:page_kind(page)=='gallery_category',timeout=20,
                               description='关闭画廊奖励进度')
                continue
            before=str(ctx.evidence(scene,'du_gallery_before_claim'))
            ctx.click(scene,target,du_intent='du_reward_gallery_claim')
            scene=ctx.wait(lambda page:page_kind(page)=='reward_overlay',timeout=20,
                           description='核实画廊奖励到账')
            report['claims'].append({'source':'可能性画廊','before':before,
                'after':str(ctx.evidence(scene,'du_gallery_claim_verified'))})
            target=scene.find('点击空白处关闭',(.25,.65,.75,.90),exact=True)
            ctx.click(scene,target,du_intent='du_reward_dismiss')
            scene=ctx.wait(lambda page:page_kind(page)=='gallery_milestones',timeout=20,
                           description='返回画廊奖励列表')
        else:
            raise AutomationError('画廊领奖进入未知页面，已保留当前画面。')
    raise AutomationError('可能性画廊领奖达到次数上限。')


def collect_fit(workflow,scene,report,label):
    ctx=workflow.ctx
    for _ in range(30):
        kind=page_kind(scene)
        if kind=='reward_overlay':
            ctx.evidence(scene,'du_reward_received')
            target=scene.find('点击空白处关闭',(.25,.65,.75,.90),exact=True)
            ctx.click(scene,target,du_intent='du_reward_dismiss')
            scene=ctx.wait(lambda p:page_kind(p)=='fit_rewards',timeout=15,description='返回拟合奖励页')
            continue
        dots=red_dots(scene,(0,.67,1,.87))
        if not dots:
            return scene
        target=dots[0]
        before=str(ctx.evidence(scene,'du_reward_before_claim'))
        ctx.click(scene,target,du_intent='du_reward_dot')
        scene=ctx.wait(lambda p:page_kind(p)=='reward_overlay',timeout=15,description='核实红点奖励到账')
        report['claims'].append({'source':label,'result':page_kind(scene),'before':before,'after':str(ctx.evidence(scene,'du_reward_claim_verified'))})
    raise AutomationError('差分宇宙领奖达到单页次数上限。')


def collect_moon(workflow,scene,report):
    ctx=workflow.ctx
    for _ in range(24):
        target=moon_unlock_target(scene)
        if target is None:
            return scene
        balance=moon_balance(scene)
        before=str(ctx.evidence(scene,'du_cassette_before_unlock'))
        ctx.click(scene,target,du_intent='du_reward_unlock')
        scene=ctx.wait(lambda p:page_kind(p)=='moon_unlocked',timeout=60,description='已有卡带解锁动画')
        after=str(ctx.evidence(scene,'du_cassette_unlocked'))
        target=scene.find('前往查看剧情',(.35,.72,.65,.82),exact=True)
        ctx.click(scene,target,du_intent='du_reward_story_open')
        scene=ctx.wait(lambda p:page_kind(p)=='moon_story',timeout=20,description='月下奇谭秘闻页')
        ctx.key('esc')
        scene=ctx.wait(lambda p:page_kind(p)=='moon_rewards',timeout=20,description='返回月下奇谭')
        if moon_balance(scene)!=balance-100:
            raise AutomationError('月下卡带解锁后余额没有核实减少100，停止重复解锁。')
        report['claims'].append({'source':'月下奇谭','mode_cassettes_used':100,'balance_after':balance-100,'before':before,'after':after})
    raise AutomationError('月下奇谭解锁达到次数上限。')


def collect_steady(workflow,scene,report):
    ctx=workflow.ctx
    visited=set()
    for _ in range(60):
        if page_kind(scene)=='reward_overlay':
            target=scene.find('点击空白处关闭',(.25,.65,.75,.90),exact=True)
            ctx.click(scene,target,du_intent='du_reward_dismiss')
            scene=ctx.wait(lambda p:page_kind(p)=='steady_rewards',timeout=20,description='返回稳态数组')
            continue
        target=scene.find('领取',(.86,.18,.98,.95),exact=True)
        if target:
            before=str(ctx.evidence(scene,'du_steady_before_claim'))
            ctx.click(scene,target,du_intent='du_reward_claim')
            scene=ctx.wait(lambda p:page_kind(p)=='reward_overlay',timeout=20,description='核实稳态数组奖励到账')
            report['claims'].append({'source':'稳态数组','before':before,'after':str(ctx.evidence(scene,'du_steady_claim_verified'))})
            continue
        targets=steady_targets(scene)
        if not targets:
            return scene
        target=next((t for t in targets if t.text not in visited),None)
        if target is None:
            raise AutomationError('稳态数组分组仍有红点但当前没有核实到领取按钮，停止重复进入。')
        visited.add(target.text)
        ctx.click(scene,target,du_intent='du_reward_steady_tab')
        scene=ctx.wait(lambda p:page_kind(p)=='steady_rewards',timeout=20,description='稳态数组红点分组')
    raise AutomationError('稳态数组领奖达到次数上限。')
