"""Independent, journalled collection of already marked DU rewards.

The initial page must be the open DU home. Candidate run/menu pages cannot
authorize a new game, and these receipts never establish weekly score rewards.
"""
from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
import re
import time

import numpy as np

from . import du_rewards as pages
from .currency_wars_identity import account_key
from .currency_wars_initial import evidence_ref, source_file_ref, _pixels
from .currency_wars_prepare import trusted
from .du_reward_store import RewardStore, digest
from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped, TaskResult, Token, normalize


@dataclass(frozen=True)
class RewardAction:
    id: int
    intent: str
    target: Token | None = None
    key: str | None = None
    drag: tuple[tuple[float, float], tuple[float, float]] | None = None


def _kind(scene):
    from .policy import replenishment_dialog
    # Static task descriptions are not payment dialogs. Require the known
    # resource panel or its separate, centered cancel/confirmation controls.
    cancel=scene.find('取消',(.25,.52,.50,.74),exact=True)
    confirm=scene.find(('确认','确定','确认购买','确认支付','确认付款','购买','支付','付款'),(.50,.52,.76,.74),exact=True)
    if replenishment_dialog(scene) or cancel is not None and confirm is not None and abs(cancel.center[1]-confirm.center[1])<.05:
        return None
    # An overlay can retain OCR from the home behind it. It always wins.
    if scene.has('获得物品', (.25, .04, .75, .25), exact=True):
        return 'reward_overlay' if scene.has('点击空白处关闭', (.25, .65, .75, .90), exact=True) else None
    if (scene.has('技能提升', (.35, .13, .65, .23), exact=True)
            and scene.has('前往查看剧情', (.35, .72, .65, .82), exact=True)):
        return 'moon_unlocked'
    if scene.has(('列车补给', '密码', '验证码', '重新连接', '是否退出')):
        return None
    return pages.page_kind(scene)


def _token_data(target):
    return None if target is None else dict(text=target.text, score=target.score, box=list(target.box))


def _action_data(action):
    return dict(id=action.id, intent=action.intent, target=_token_data(action.target), key=action.key,
                drag=[list(point) for point in action.drag] if action.drag is not None else None)


def _fit_state(scene):
    levels=[int(normalize(t.text)) for t in scene.tokens if t.within((.40,.33,.60,.46))
            and re.fullmatch(r'[1-9]\d{0,2}',normalize(t.text))]
    xp=[normalize(t.text) for t in scene.tokens if t.within((.40,.46,.60,.56))
        and (re.fullmatch(r'\d{1,5}/[1-9]\d{2,4}',normalize(t.text)) or normalize(t.text)=='已满级')]
    tiers=[(int(normalize(t.text)),t.center[0]) for t in scene.tokens if t.within((0,.80,1,.87))
           and re.fullmatch(r'[1-9]\d{0,2}',normalize(t.text))]
    if len(levels)!=1 or len(xp)!=1 or not tiers:
        raise AutomationError('拟合等级、经验或可见奖励档位未完整核实。')
    return dict(level=levels[0],xp=xp[0],tiers=tiers)


def _gallery_rows(scene):
    rows=[]
    for label,status in pages.gallery_milestone_rows(scene):
        y=label.center[1]
        values=[int(normalize(t.text)) for t in scene.tokens
            if t.within((.21,y+.01,.40,min(.80,y+.075))) and re.fullmatch(r'\d{1,5}',normalize(t.text))]
        if len(values)==1:rows.append((values[0],status))
    if len({value for value,_ in rows})!=len(rows):
        raise AutomationError('画廊奖励档位重复，未按行位置猜测。')
    return rows


def _steady_scope(scene):
    # The surveyed full page has one white selected top tab and one light
    # selected left group; unselected controls have a dark fill. Counters are
    # separate OCR tokens below the name, never an invented combined field.
    def light(roi):
        if scene.image is None:return False
        h,w=scene.image.shape[:2];x1,y1,x2,y2=[round(value*size) for value,size in zip(roi,(w,h,w,h))]
        patch=scene.image[y1:y2,x1:x2]
        return bool(patch.size and np.mean(np.min(patch[:,:,:3],axis=2)>170)>.65)
    tabs=[name for name,roi in (('测试',(.35,.10,.48,.13)),('难题',(.52,.10,.65,.13)))
          if scene.has(name,(.33,.07,.67,.15),exact=True) and light(roi)]
    groups=[]
    for token in scene.tokens:
        name=normalize(token.text);y=token.center[1]
        if not token.within((.02,.17,.21,.94)) or not re.fullmatch(r'[一-鿿]{2,10}',name):continue
        if not light((.02,max(.16,y-.02),.21,min(.96,y+.065))):continue
        counters=[re.fullmatch(r'(\d{1,3})/(\d{1,3})',normalize(t.text)) for t in scene.tokens
            if t.within((.02,y+.015,.21,min(.96,y+.065))) and re.fullmatch(r'\d{1,3}/\d{1,3}',normalize(t.text))]
        if len(counters)==1:
            counter=counters[0];groups.append(dict(group=name,done=int(counter[1]),total=int(counter[2])))
    if len(tabs)!=1 or len(groups)!=1:
        raise AutomationError('稳态数组当前选中页签、左栏分组或相邻进度未唯一核实。')
    return dict(tab=tabs[0],**groups[0])


def _steady_row(scene,target):
    y=target.center[1]
    labels=[t for t in scene.tokens if t.within((.24,max(.16,y-.075),.84,min(.96,y+.075)))
            and len(normalize(t.text))>=6 and not re.fullmatch(r'[x×]?\d+(?:/\d+)?',normalize(t.text))]
    if len(labels)!=1:
        raise AutomationError('稳态数组本项完整条件未唯一读取，未按领取按钮行猜测。')
    return dict(scope=_steady_scope(scene),condition=normalize(labels[0].text))


def _overlay(scene):
    if _kind(scene)!='reward_overlay':return None
    quantities=[]
    for token in scene.tokens:
        if token.within((.10,.24,.90,.67)):
            value=normalize(token.text)
            if re.fullmatch(r'[x×]?\d[\d,，]{0,9}',value):
                number=int(value.lstrip('x×').replace(',','').replace('，',''))
                if 0<number<=1000000000:quantities.append(number)
    return sorted(quantities) if quantities else None


class RewardWorkflow:
    def __init__(self,context,*,use_cassettes=False):
        if context.report.operation!='du_rewards' or type(use_cassettes) is not bool:
            raise AutomationError('独立差分领奖需要明确操作和布尔卡带授权。')
        self.c=context;self.epoch=context.runner.input_epoch
        self.run_dir=str(Path(context.report.run_dir).resolve(strict=True))
        self.hwnd=getattr(context.window,'hwnd',None)
        if type(self.epoch) is not int or self.epoch<0 or type(self.hwnd) is not int or self.hwnd<=0:
            raise AutomationError('差分领奖当前窗口或输入代次未核实。')
        self.confidence=max(.85,context.settings.ocr_confidence)
        self.data=dict(schema=1,operation='du_rewards',status='running',rewards_verified=False,
            safe_to_restart=False,battle_started=False,use_cassettes=use_cassettes,input_epoch=self.epoch,
            window=self.hwnd,account_key=None,actions=[],claims=[],observations=[],obligation=None,
            requested_categories=['拟合等级','稳态数组','可能性画廊']+(['月下奇谭'] if use_cassettes else []),
            skipped_optional_categories=[],all_notifications_cleared=False,
            remaining_categories=[],cassettes=dict(initial_balance=None,limit=0,spent_verified=0))
        self.store=RewardStore(self.run_dir,self.data)
        context.report.du_rewards=self.data;context.du_rewards_workflow=self
        self.request=None;self.store.persist()

    def _clean(self,scene):
        return trusted(scene,self.confidence)

    def _fresh(self,scene,*,allow_identity_gap=False):
        self.c.checkpoint()
        if (self.c.runner.input_epoch!=self.epoch or self.c.scene_epoch!=self.epoch
                or str(Path(self.c.report.run_dir).resolve())!=self.run_dir
                or getattr(self.c.window,'hwnd',None)!=self.hwnd or scene is not self.c.last_scene):
            raise InputInterrupted('差分领奖运行、窗口或输入代次改变；旧目标不重放。')
        stamp=getattr(scene,'captured_at',None)
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=time.monotonic()-stamp<=8:
            raise AutomationError('差分领奖需要当前新鲜画面。')
        if self.data['account_key'] is not None:
            clean=self._clean(scene)
            if _kind(clean)=='home' or any('uid' in normalize(t.text) for t in clean.tokens):
                try:current=account_key(clean,self.confidence)
                except AutomationError:
                    if allow_identity_gap:return False
                    raise
                if current!=self.data['account_key']:
                    raise AutomationError('差分领奖账号改变，未继续输入。')
        return True

    def _source(self,scene,label,feedback=None):
        self._fresh(scene)
        path=self.c.evidence(scene,'du_rewards_'+label+'_'+str(len(self.data['observations'])))
        ref=evidence_ref(scene,path,self.run_dir)
        self._fresh(scene)
        item=dict(id=len(self.data['observations']),evidence=ref,captured_at=scene.captured_at,
            kind=_kind(self._clean(scene)),tokens_digest=digest([_token_data(t) for t in self._clean(scene).tokens]),
            input_epoch=self.epoch,window=self.hwnd)
        if feedback is not None:item['readback']=deepcopy(feedback)
        self.data['observations'].append(item)
        return item

    def _wait(self,kind,check=None,*,label='feedback',timeout=20,after=0):
        started=time.monotonic();inactive=self.c.runner.inactive_duration
        frames=[];signature=None;last=after;scene=None
        for _ in range(80):
            self.c.checkpoint()
            elapsed=time.monotonic()-started-(self.c.runner.inactive_duration-inactive)
            if elapsed>=timeout:break
            try:scene=self.c.snapshot()
            except EmptyCapture:scene=None
            if scene is not None:
                if not self._fresh(scene,allow_identity_gap=True):
                    frames=[];signature=None;self.c.sleep(.15);continue
                clean=self._clean(scene)
                try:
                    value=check(clean) if _kind(clean)==kind and check is not None else kind if _kind(clean)==kind else None
                except (InputInterrupted,Stopped):raise
                except AutomationError:value=None  # Incomplete animated fields remain unknown.
                if value is not None and value is not False:
                    current=digest(value)
                    if signature!=current:frames=[]
                    signature=current
                    if scene.captured_at>last:
                        item=self._source(scene,label,value)
                        if any(self.data['observations'][index]['evidence']['path']==item['evidence']['path'] for index in frames):
                            raise AutomationError('差分领奖两帧不能来自同一PNG文件。')
                        frames.append(item['id']);last=scene.captured_at
                        self.store.persist()
                        if time.monotonic()-started-(self.c.runner.inactive_duration-inactive)>=timeout:
                            raise AutomationError('差分领奖反馈持久化超过期限。')
                        if len(frames)==2:return scene,frames
                    else:frames=[];signature=None
                else:frames=[];signature=None
            else:frames=[];signature=None
            self.c.sleep(.15)
        raise AutomationError('差分领奖未取得两份对应的新鲜反馈；原意图保留，未重复输入。')

    def _derive(self,scene,action):
        clean=self._clean(scene);kind=_kind(clean)
        if action.drag is not None:
            return (action.intent=='du_reward_gallery_pan' and kind=='gallery_home'
                    and action.drag==pages.gallery_pan_plan(clean))
        if action.key is not None:
            destinations={'fit_rewards':'home','steady_rewards':'home','moon_rewards':'home',
                'gallery_home':'home','gallery_category':'gallery_home','gallery_milestones':'gallery_category',
                'moon_story':'moon_rewards'}
            return action.key=='esc' and action.intent=='du_reward_back_'+destinations.get(kind,'invalid')
        if action.intent=='du_reward_dismiss':
            return (kind=='reward_overlay' and self.data['obligation'] is not None
                    and action.target==clean.find('点击空白处关闭',(.25,.65,.75,.90),exact=True))
        if action.intent=='du_reward_unlock':
            budget=self.data['cassettes'];obligation=self.data['obligation']
            return (kind=='moon_rewards' and self.data['use_cassettes'] is True and obligation is not None
                and obligation.get('source')=='月下奇谭' and obligation.get('status')=='pending'
                and budget['spent_verified']+100<=budget['limit']
                and pages.moon_balance(clean)==obligation.get('balance_before')==budget['initial_balance']-budget['spent_verified']
                and obligation.get('amount')==100
                and action.target==pages.moon_unlock_target(clean))
        try:pages.guard_click(clean,action.target,action.intent)
        except (AutomationError,AttributeError,TypeError):return False
        return kind=='home' if action.intent=='du_reward_open' else kind not in (None,'home')

    def authorize(self,scene,action):
        self._fresh(scene);self.store.require_durable()
        if (type(action) is not RewardAction or self.request!=action
                or action.id!=len(self.data['actions'])-1):
            raise AutomationError('差分领奖动作不是本次待提交意图。')
        row=self.data['actions'][action.id]
        if (row['status']!='pending' or row['request']!=_action_data(action)
                or sum(value is not None for value in (action.target,action.key,action.drag))!=1
                or not self._derive(scene,action)):
            raise AutomationError('差分领奖目标或独立意图改变，未输入。')
        before=self.data['observations'][row['before']]
        if (before['captured_at']!=scene.captured_at
                or before['tokens_digest']!=digest([_token_data(t) for t in self._clean(scene).tokens])
                or source_file_ref(before['evidence']['path'],self.run_dir)!=before['evidence']
                or before['evidence']['pixel_sha256']!=_pixels(scene.image)):
            raise AutomationError('差分领奖当前图像与落盘来源不符，未输入。')

    def _transition(self,scene,intent,kind,*,target=None,key=None,drag=None,check=None,timeout=20):
        if len(self.data['actions'])>=240:raise AutomationError('差分领奖达到有限动作上限。')
        before=self._source(scene,'before')
        action=RewardAction(len(self.data['actions']),intent,target,key,drag)
        row=dict(id=action.id,request=_action_data(action),status='pending',before=before['id'],after=[])
        self.data['actions'].append(row);self.request=action;self.store.persist()
        self.c.du_rewards_input(scene,action)
        row['status']='submitted';self.store.persist()
        after,frames=self._wait(kind,check,label=intent,timeout=timeout,after=scene.captured_at)
        row.update(status='verified',after=frames);self.request=None;self.store.persist()
        return after

    def _back(self,scene,destination,check=None):
        return self._transition(scene,'du_reward_back_'+destination,destination,key='esc',check=check)

    def _claim(self,scene,intent,target,source,identity,returned):
        claim=dict(id=len(self.data['claims']),source=source,identity=deepcopy(identity),status='pending',
                   action_id=len(self.data['actions']))
        self.data['claims'].append(claim);self.data['obligation']=claim;self.store.persist()
        scene=self._transition(scene,intent,'reward_overlay',target=target,check=_overlay)
        claim['status']='received';claim['overlay']=deepcopy(self.data['actions'][-1]['after']);self.store.persist()
        close=self._clean(scene).find('点击空白处关闭',(.25,.65,.75,.90),exact=True)
        expected={'拟合等级':'fit_rewards','稳态数组':'steady_rewards','可能性画廊':'gallery_milestones'}[source]
        scene=self._transition(scene,'du_reward_dismiss',expected,target=close,check=returned)
        claim.update(status='verified',return_action_id=self.data['actions'][-1]['id'],
            return_frames=deepcopy(self.data['actions'][-1]['after']))
        self.data['obligation']=None;self.store.persist()
        return scene

    def _fit(self,scene):
        for _ in range(30):
            clean=self._clean(scene);dots=pages.red_dots(clean,(0,.67,1,.87))
            if not dots:return scene
            target=dots[0];state=_fit_state(clean)
            near=[(tier,x) for tier,x in state['tiers'] if abs(x-target.center[0])<.035]
            if len(near)!=1 or near[0][0]>state['level']:
                raise AutomationError('拟合红点未唯一绑定已达等级的奖励档位。')
            tier,x=near[0]
            def returned(page):
                after=_fit_state(page)
                if (after['level']!=state['level'] or after['xp']!=state['xp']
                        or any(abs(dot.center[0]-target.center[0])<.035 for dot in pages.red_dots(page,(0,.67,1,.87)))):return None
                anchors=[number for number,position in after['tiers'] if any(number==old and abs(position-oldx)<.015 for old,oldx in state['tiers'])]
                # Claimed tier numerals can darken out of OCR. A surviving
                # neighboring tier and the unchanged XP/cap panel bind viewport.
                if not anchors:return None
                other_before=sorted(round(dot.center[0],3) for dot in dots[1:])
                other_after=sorted(round(dot.center[0],3) for dot in pages.red_dots(page,(0,.67,1,.87)))
                return dict(tier=tier,state=[after['level'],after['xp']],others=other_after) if other_before==other_after else None
            scene=self._claim(scene,'du_reward_dot',target,'拟合等级',dict(tier=tier,state=state),returned)
        raise AutomationError('拟合等级领取达到有限次数。')

    def _steady(self,scene):
        visited=set()
        for _ in range(60):
            clean=self._clean(scene)
            claims=[t for t in clean.tokens if normalize(t.text)=='领取' and t.within((.86,.18,.98,.95))]
            if claims:
                target=sorted(claims,key=lambda t:t.center[1])[0];identity=_steady_row(clean,target)
                def returned(page):
                    scope=_steady_scope(page)
                    if (scope['tab'],scope['group'],scope['total'])!=(identity['scope']['tab'],identity['scope']['group'],identity['scope']['total']):return None
                    labels=[t for t in page.tokens if normalize(t.text)==identity['condition'] and t.within((.24,.16,.84,.96))]
                    if len(labels)!=1:return None
                    y=labels[0].center[1]
                    claimed=page.has('已领取',(.85,max(.16,y-.06),.99,min(.97,y+.06)),exact=True)
                    still=page.has('领取',(.85,max(.16,y-.06),.99,min(.97,y+.06)),exact=True)
                    if still or not claimed:return None
                    return dict(condition=identity['condition'],scope=scope,claimed=claimed)
                scene=self._claim(scene,'du_reward_claim',target,'稳态数组',identity,returned);continue
            targets=pages.steady_targets(clean)
            if not targets:return scene
            scope=_steady_scope(clean)
            targets=[t for t in targets if normalize(t.text) not in (scope['tab'],scope['group'])]
            if not targets:return scene
            target=next((t for t in targets if (normalize(t.text),tuple(t.box)) not in visited),None)
            if target is None:raise AutomationError('稳态数组红点没有新的到账进展，未重复进入。')
            visited.add((normalize(target.text),tuple(target.box)))
            def changed(page):
                value=_steady_scope(page)
                return value if normalize(target.text) in (value['tab'],value['group']) else None
            scene=self._transition(scene,'du_reward_steady_tab','steady_rewards',target=target,check=changed)
        raise AutomationError('稳态数组领取达到有限次数。')

    def _gallery(self,scene):
        category=None;visits={};pans={}
        for _ in range(180):
            clean=self._clean(scene);kind=_kind(clean)
            if kind=='gallery_home':
                targets=pages.gallery_targets(clean)
                if not targets:
                    if not pages.red_dots(clean):return scene
                    plan=pages.gallery_pan_plan(clean);signature=pages.gallery_signature(clean)
                    if plan is None or pans.get(signature,0)>=2 or sum(pans.values())>=12:
                        raise AutomationError('画廊未绑定红点或翻页未核实，未宣称领完。')
                    pans[signature]=pans.get(signature,0)+1
                    scene=self._transition(scene,'du_reward_gallery_pan','gallery_home',drag=plan,
                        check=lambda page:list(pages.gallery_signature(page)) if pages.gallery_signature(page)!=signature else None)
                    continue
                progress=len(self.data['claims'])
                target=next((t for t in targets if normalize(t.text) not in visits or progress>visits[normalize(t.text)]),None)
                if target is None:raise AutomationError('画廊红点重入没有到账进展，未重复进入。')
                category=normalize(target.text);visits[category]=progress
                scene=self._transition(scene,'du_reward_gallery_category','gallery_category',target=target,
                    check=lambda page:category if page.has(target.text,(0,0,.32,.13),exact=True) else None)
            elif kind=='gallery_category':
                if category is None:raise AutomationError('画廊分类缺少本次主页导航来源。')
                target=pages.gallery_progress_target(clean)
                if target is None:scene=self._back(scene,'gallery_home');continue
                scene=self._transition(scene,'du_reward_gallery_progress','gallery_milestones',target=target)
            elif kind=='gallery_milestones':
                rows=_gallery_rows(clean);available=[(value,status) for value,status in rows if normalize(status.text)=='领取']
                raw_claims=[t for t in clean.tokens if t.within((.68,.27,.79,.79)) and normalize(t.text)=='领取']
                if not available:
                    if raw_claims:raise AutomationError('画廊可领取项的完整阈值未读清，未猜测领取。')
                    scene=self._back(scene,'gallery_category');continue
                if category is None:raise AutomationError('画廊领奖没有本次分类来源。')
                threshold,target=available[0]
                def returned(page):
                    found=[status for value,status in _gallery_rows(page) if value==threshold]
                    return dict(category=category,threshold=threshold,status='claimed') if len(found)==1 and normalize(found[0].text)=='已领取' else None
                scene=self._claim(scene,'du_reward_gallery_claim',target,'可能性画廊',dict(category=category,threshold=threshold),returned)
            else:raise AutomationError('画廊领奖转换进入未知页面。')
        raise AutomationError('画廊领奖达到有限动作上限。')

    def _moon(self,scene):
        budget=self.data['cassettes']
        reobserve=False
        for _ in range(24):
            if reobserve:
                scene,_=self._wait('moon_rewards',lambda page:pages.moon_balance(page),label='cassette_before',after=scene.captured_at)
            clean=self._clean(scene);balance=pages.moon_balance(clean)
            if balance is None:raise AutomationError('月下卡带余额未唯一读取。')
            if budget['initial_balance'] is None:
                budget.update(initial_balance=balance,limit=(balance//100)*100);self.store.persist()
            if balance!=budget['initial_balance']-budget['spent_verified']:
                raise AutomationError('月下卡带余额不同于冻结余额及已核实消耗，未扩大或继续消费。')
            target=pages.moon_unlock_target(clean)
            if target is None:
                if pages.red_dots(clean,(.81,.73,.86,.80)):
                    self.data['remaining_categories'].append('月下奇谭')
                return scene
            if not self.data['use_cassettes'] or budget['spent_verified']+100>budget['limit']:
                self.data['remaining_categories'].append('月下奇谭');return scene
            claim=dict(id=len(self.data['claims']),source='月下奇谭',status='pending',balance_before=balance,
                amount=100,action_id=len(self.data['actions']))
            self.data['claims'].append(claim);self.data['obligation']=claim;self.store.persist()
            scene=self._transition(scene,'du_reward_unlock','moon_unlocked',target=target,timeout=60,
                check=lambda page:'skill_and_story' if page.has('技能提升',(.35,.13,.65,.23),exact=True) and page.has('前往查看剧情',(.35,.72,.65,.82),exact=True) else None)
            claim.update(status='received',unlock_frames=deepcopy(self.data['actions'][-1]['after']));self.store.persist()
            target=self._clean(scene).find('前往查看剧情',(.35,.72,.65,.82),exact=True)
            scene=self._transition(scene,'du_reward_story_open','moon_story',target=target)
            scene=self._back(scene,'moon_rewards',check=lambda page:dict(balance=balance-100)
                if pages.moon_balance(page)==balance-100 else None)
            claim.update(status='verified',balance_after=balance-100,return_action_id=self.data['actions'][-1]['id'],
                return_frames=deepcopy(self.data['actions'][-1]['after']))
            budget['spent_verified']+=100;self.data['obligation']=None;self.store.persist()
            # A further debit always uses another fresh pair, independent of
            # the preceding return. External growth cannot enlarge the ceiling.
            reobserve=pages.moon_unlock_target(self._clean(scene)) is not None
            if not reobserve:return scene
        self.data['remaining_categories'].append('月下奇谭')
        return scene

    def _home(self,page):
        signature=pages.home_signature(page)
        if signature is None:return None
        return dict(account=account_key(page,self.confidence),entries=[round(value,2) for value in signature],
            marked=sorted(normalize(t.text) for t in pages.home_targets(page)))

    def run(self):
        try:
            scene,frames=self._wait('home',self._home,label='initial_home')
            self.data.update(account_key=account_key(self._clean(scene),self.confidence),home_frames=frames);self.store.persist()
            visits={}
            for _ in range(40):
                clean=self._clean(scene);targets=pages.home_targets(clean)
                remaining=[]
                self.data['skipped_optional_categories']=(['月下奇谭'] if not self.data['use_cassettes']
                    and any(normalize(t.text)=='月下奇谭' for t in targets) else [])
                self.data['remaining_categories']=remaining
                candidates=[t for t in targets if self.data['use_cassettes'] or normalize(t.text)!='月下奇谭']
                # A frozen cassette ceiling can leave a visible, valid moon red dot.
                budget=self.data['cassettes']
                if budget['initial_balance'] is not None and budget['spent_verified']>=budget['limit']:
                    candidates=[t for t in candidates if normalize(t.text)!='月下奇谭']
                    if any(normalize(t.text)=='月下奇谭' for t in targets):self.data['remaining_categories'].append('月下奇谭')
                if sum(claim['source']=='月下奇谭' for claim in self.data['claims'])>=24:
                    candidates=[t for t in candidates if normalize(t.text)!='月下奇谭']
                    if any(normalize(t.text)=='月下奇谭' for t in targets):self.data['remaining_categories'].append('月下奇谭')
                if not candidates:
                    known=pages.red_dots(clean,(.66,.23,.995,.70))
                    if len(known)>len(targets) or any(not dot.within((.66,.23,.995,.70)) for dot in pages.red_dots(clean)):
                        self.data['remaining_categories'].append('未绑定红点')
                    self.data['remaining_categories']=sorted(set(self.data['remaining_categories']))
                    self.data.update(status='partial' if self.data['remaining_categories'] else 'complete',
                        rewards_verified=not self.data['remaining_categories'],safe_to_restart=True,
                        all_notifications_cleared=not targets and not self.data['remaining_categories'],
                        final_home_frames=frames)
                    self.store.persist()
                    return TaskResult('du_rewards','partial' if self.data['remaining_categories'] else 'ok',
                        '已保留已领取结果；所选奖励仍有未核实项目。' if self.data['remaining_categories'] else '差分所选红点奖励及同账号主页返回已核实；未开始对局。')
                progress=len(self.data['claims'])
                target=next((t for t in candidates if normalize(t.text) not in visits or progress>visits[normalize(t.text)]),None)
                if target is None:raise AutomationError('差分主页红点没有新的到账进展，未重复进入。')
                name=normalize(target.text);visits[name]=progress
                expected={'拟合等级':'fit_rewards','稳态数组':'steady_rewards','可能性画廊':'gallery_home','月下奇谭':'moon_rewards'}[name]
                scene=self._transition(scene,'du_reward_open',expected,target=target)
                if name=='拟合等级':scene=self._fit(scene)
                elif name=='稳态数组':scene=self._steady(scene)
                elif name=='可能性画廊':scene=self._gallery(scene)
                else:scene=self._moon(scene)
                scene=self._back(scene,'home',self._home);frames=deepcopy(self.data['actions'][-1]['after'])
            raise AutomationError('差分主页红点遍历达到有限上限。')
        except Exception as error:
            for action in self.data['actions']:
                if action['status'] in ('pending','submitted'):action['status']='unknown'
            unsent=not self.data['actions'] and not self.data['claims'] and self.data['obligation'] is None
            self.data.update(status='abort_before_input' if unsent else 'unknown',rewards_verified=False,
                safe_to_restart=unsent,failure_type=type(error).__name__)
            try:self.store.persist()
            except (OSError,ValueError,AutomationError):pass
            raise


def run_rewards(context, *, use_cassettes=False):
    return RewardWorkflow(context,use_cassettes=use_cassettes).run()
