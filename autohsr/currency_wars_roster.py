"""Fill vacancies using positional eligibility read from each character panel."""
from __future__ import annotations

from dataclasses import dataclass
import re
import time

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_deployment import (_BENCH_CENTERS,_crop,_texture,_similarity,
    bench_face,backend_layout,plan_bench_deployment,verify_bench_deployment)
from .currency_wars_match import read_match
from .models import AutomationError,EmptyCapture,normalize


@dataclass(frozen=True)
class BenchCandidate:
    slot: int
    node: str
    portrait: object


@dataclass(frozen=True)
class CharacterProfile:
    name: str
    zones: tuple[str,...]
    node: str


def candidate_at(scene,slot,confidence=.65,*,require_vacancy=True):
    state=read_match(scene,confidence)
    if (not state or state.page not in (('preparation',) if require_vacancy else ('preparation','bench_full')) or not state.node or not state.deployment
            or require_vacancy and state.deployment[0]>=state.deployment[1]):
        raise AutomationError('自动部署需要明确的备战页、节点及出战空位。')
    portrait=_crop(scene.image,bench_face(slot))
    if _texture(portrait)<15:
        raise AutomationError('备战角色图像不足。')
    cx=_BENCH_CENTERS[slot-1]
    if any(t.score>=confidence and normalize(t.text)=='开启' and t.within((cx-.035,.78,cx+.035,.91)) for t in scene.tokens):
        raise AutomationError('该备战格是待开启物品，未作为角色。')
    return BenchCandidate(slot,state.node,portrait.copy())


def validate_candidate(scene,candidate,confidence=.65,*,require_vacancy=True):
    current=candidate_at(scene,candidate.slot,confidence,require_vacancy=require_vacancy)
    if current.node!=candidate.node or current.portrait.shape!=candidate.portrait.shape or _similarity(candidate.portrait,current.portrait)<.92:
        raise AutomationError('备战候选头像或节点已改变，未部署。')
    return current


def deployed_matches(scene,candidate):
    """Conservative portrait matching only skips a candidate; never moves one."""
    import cv2
    import numpy as np
    _,centers=backend_layout(scene.image)
    cx=_BENCH_CENTERS[candidate.slot-1]
    front_features=[_crop(scene.image,(cx-.0075,.833,cx+.0075,.858)),
                    _crop(scene.image,(cx-.008,.82,cx+.008,.85))]
    targets=[('back',i+1,x,890/1440,[candidate.portrait],(x-.039,.55,x+.039,.69)) for i,x in enumerate(centers[:6])]
    targets += [('front',i+1,x/2560,530/1440,front_features,(x/2560-.039,.295,x/2560+.039,.44)) for i,x in enumerate((990,1180,1370,1560))]
    found=[]
    for zone,slot,x,y,features,roi in targets:
        if any(_texture(p)<8 for p in features):
            continue
        area=_crop(scene.image,roi)
        scores=[]
        for feature in features:
            matches=[]
            for scale in np.linspace(.8,1.2,17):
                patch=cv2.resize(feature,None,fx=float(scale),fy=float(scale))
                if all(a<=b for a,b in zip(patch.shape[:2],area.shape[:2])):
                    matches.append(_similarity(patch,area))
            scores.append(max(matches,default=0.))
        if min(scores)>=.78:
            found.append((min(scores),zone,slot,(x,y)))
    return tuple(sorted(found,reverse=True))


def already_deployed(scene,candidate):
    return bool(deployed_matches(scene,candidate))


def next_candidate(scene,confidence=.65,excluded=()):
    for slot in range(1,10):
        if slot in excluded:
            continue
        try:
            candidate=candidate_at(scene,slot,confidence)
        except AutomationError:
            continue
        if not already_deployed(scene,candidate):
            return candidate
    raise AutomationError('没有已核实且未在场的备战候选，未自动补位。')


def read_character(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='character':
        raise AutomationError('角色信息面板未核实。')
    state=read_match(scene,confidence)
    names=[normalize(t.text) for t in scene.tokens if confidence<=t.score<=1 and
           t.within((.775,.19,.91,.235)) and re.fullmatch(r'(?=.{1,40}$)(?=.*[\u4e00-\u9fff])[\u4e00-\u9fffa-z0-9.]+',normalize(t.text))]
    from .currency_wars_names import configured_name,pending_name
    named=configured_name(scene,(.775,.19,.91,.235),confidence)
    if named is not None:names=[normalize(named.text)]
    elif pending_name(scene,(.775,.19,.91,.235)):names=[]
    modes=[normalize(t.text) for t in scene.tokens if confidence<=t.score<=1 and
           t.within((.78,.22,.90,.28)) and normalize(t.text) in ('前台','后台','前后台','日后台')]
    if not state or not state.node or len(names)!=1 or len(modes)!=1:
        raise AutomationError('角色名称、前后台适配或节点未完整识别。')
    zones={'前台':('front',),'后台':('back',),'日后台':('back',),'前后台':('front','back')}[modes[0]]
    return CharacterProfile(names[0],zones,state.node)


def eligible_plan(scene,candidate,profile,confidence=.65):
    validate_candidate(scene,candidate,confidence)
    if profile.node!=candidate.node:
        raise AutomationError('角色位置证据来自其他节点。')
    for zone in profile.zones:
        try:
            return plan_bench_deployment(scene,confidence,source_slot=candidate.slot,zone=zone)
        except AutomationError:
            pass
    raise AutomationError('该角色支持的位置没有空格。')


def deploy_candidate(c,scene,candidate,data,persist):
    guard=CurrencyWarsWorkflow(c)
    def record(action_kind,current,**extra):
        guard._require_current_scene(current)
        action=dict(action=action_kind,source_slot=candidate.slot,status='pending',
                    before=str(c.evidence(current,'currency_'+action_kind)),**extra)
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        return action
    def observe_until(predicate):
        elapsed=0.
        last=None
        while elapsed<15:
            started=time.monotonic()
            inactive=c.runner.inactive_duration
            try:
                last=c.snapshot()
            except EmptyCapture:
                last=None
            if last is not None:
                guard._require_current_scene(last)
                try:
                    if predicate(last):
                        return last
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
        elif c.last_scene is not None:
            action['after']=str(c.evidence(c.last_scene,'currency_'+action['action']+'_unknown'))
            data['screenshot']=action['after']
        data['action_status']=action['status']
        persist()
        return after is not None
    action=record('inspect_bench',scene)
    c.currency_open_bench(scene,candidate)
    def panel(s):
        return read_character(s,c.settings.ocr_confidence).node==candidate.node
    after=observe_until(panel)
    if not finish(action,after):
        return False
    profile=read_character(after,c.settings.ocr_confidence)
    action['name'],action['zones']=profile.name,profile.zones
    action=record('close_character',after,name=profile.name)
    c.currency_close_character(after)
    def closed(s):
        validate_candidate(s,candidate,c.settings.ocr_confidence)
        previous,current=read_match(scene),read_match(s)
        return (previous.gold is not None and current.gold==previous.gold and
                previous.deployment==current.deployment)
    current=observe_until(closed)
    if not finish(action,current):
        return False
    try:
        plan=eligible_plan(current,candidate,profile,c.settings.ocr_confidence)
    except AutomationError as error:
        data.update(action_status='candidate_ineligible',reason=str(error))
        persist()
        return True
    action=record('deploy_candidate',current,name=profile.name,zone=plan.zone,target_slot=plan.target_slot,
                  start=list(plan.start),end=list(plan.end),
                  waypoints=[(plan.start[0],.735),(plan.end[0],.735)] if plan.zone=='back' else [])
    c.currency_deploy_candidate(current,candidate,profile)
    after=observe_until(lambda s:verify_bench_deployment(current,s,plan,c.settings.ocr_confidence)['status']=='verified')
    if after is not None:
        action['feedback']=verify_bench_deployment(current,after,plan,c.settings.ocr_confidence)
    return finish(action,after)
