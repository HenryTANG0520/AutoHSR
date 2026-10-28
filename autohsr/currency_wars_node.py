"""A bounded node battle using an already prepared team; no purchases or repeats."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_match import read_match
from .currency_wars_deployment import _crop, _texture
from .models import AutomationError, EmptyCapture, TaskResult, normalize


def loot_centers(scene):
    """Recognize colored crystal bodies, excluding pickup rings and their halos."""
    if scene.image is None:
        return ()
    import cv2
    import numpy as np
    image=cv2.resize(scene.image,(2560,1440))
    hsv=cv2.cvtColor(image[330:690,1700:2180],cv2.COLOR_BGR2HSV)
    found=[]
    # Blue pickup rings are smaller and slightly more purple than crystal
    # bodies. Hough alone accepted those rings and gaps between real crystals.
    for lower,upper,min_radius,max_radius in (
            ((85,45,170),(112,255,255),35,62),
            ((10,90,170),(35,255,255),28,72),
            ((0,0,145),(179,55,255),8,35)):
        mask=cv2.inRange(hsv,np.array(lower,np.uint8),np.array(upper,np.uint8))
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            _,_,width,height=cv2.boundingRect(contour)
            (x,y),radius=cv2.minEnclosingCircle(contour)
            area=cv2.contourArea(contour)
            if (min_radius<=radius<=max_radius and .75<width/height<1.33 and area>100
                    and area/(np.pi*radius*radius)>.65):
                # Ignore a pale highlight contained in an already found blue
                # or gold body; it is not a second crystal.
                if not any(np.hypot(x-a,y-b)<r for a,b,r in found):
                    found.append((float(x),float(y),float(radius)))
    return tuple(((x+1700)/2560,(y+330)/1440,r/2560) for x,y,r in found)


def start_target(scene, confidence=.65):
    state = read_match(scene, confidence)
    if (state is None or state.page != 'preparation' or not state.node or state.hp is None or state.hp <= 0
            or not state.deployment or state.deployment[0] != state.deployment[1]):
        raise AutomationError('节点验证需要无遮挡备战页、满员阵容和明确生命值。')
    if scene.image is None or not any(_texture(_crop(scene.image, (cx-.02,.34,cx+.02,.40))) >= 15
                                    for cx in (990/2560,1180/2560,1370/2560,1560/2560)):
        raise AutomationError('没有已确认的前台角色，未出战。')
    if not any(t.score >= confidence and normalize(t.text) in ('战斗','奖励','首领') and t.within((.28,.07,.73,.105)) for t in scene.tokens):
        raise AutomationError('当前节点尚未确认为战斗；未点击出战。')
    if loot_centers(scene):
        raise AutomationError('奖励区域仍有待领取晶矿，先处理掉落再出战。')
    target = next((t for t in scene.tokens if confidence <= t.score <= 1
                   and normalize(t.text) == '出战' and t.within((.9,.65,1,.75))), None)
    if target is None:
        raise AutomationError('出战按钮未核实。')
    return target


def result_node(scene, confidence=.65):
    values = {match[1] for t in scene.tokens if confidence <= t.score <= 1
              and t.within((.4,.24,.53,.30))
              and (match := re.fullmatch(r'([1-3]-[1-9][0-9]?)(?:战斗|奖励|首领)?', normalize(t.text)))}
    return next(iter(values)) if len(values) == 1 else None


def battle_node(scene, confidence=.65):
    from .currency_wars_node_ocr import bounded_battle_node
    attempted, value = bounded_battle_node(scene, confidence)
    if attempted:
        return value
    values = {normalize(t.text) for t in scene.tokens if confidence <= t.score <= 1
              and t.within((.30,0,.40,.05)) and re.fullmatch(r'[1-3]-[1-9][0-9]?',normalize(t.text))}
    return next(iter(values)) if len(values)==1 else None


def run_node(context, *, journal_name='currency-node.json', initial_scene=None):
    c = context
    c.checkpoint()
    before = initial_scene if initial_scene is not None else c.snapshot()
    observing = observe(before,c.settings.ocr_confidence).page_kind == 'battle'
    if observing:
        source_node = battle_node(before,c.settings.ocr_confidence)
        if source_node is None:
            raise AutomationError('正在战斗，但节点编号未核实；未发送输入。')
    else:
        start_target(before, c.settings.ocr_confidence)
        source_node = read_match(before, c.settings.ocr_confidence).node
    guard = CurrencyWarsWorkflow(c)
    before_path = c.evidence(before, 'currency_node_before')
    guard._require_current_scene(before)
    data = dict(mode='single_node_test', origin_node=source_node, node_verified=False,
                completion_verified=False, gameplay_enabled=False, action_status='pending',
                action='observe_existing_battle' if observing else 'start_node',
                before=str(before_path), screenshot=str(before_path))
    c.report.currency_wars = data
    journal = Path(c.report.run_dir) / journal_name
    def persist():
        journal.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    persist()
    c.checkpoint()
    guard._require_current_scene(before)
    if not observing:
        c.currency_start_node(before)
        data['start_dispatched']=True
        persist()
    elapsed, unseen, battle_seen = 0., 0., observing
    timeout = min(c.settings.battle_timeout, 180)
    while elapsed < timeout:
        started = time.monotonic()
        inactive = c.runner.inactive_duration
        try:
            scene = c.snapshot()
        except EmptyCapture:
            # A transition can be black for a few frames after a successful
            # start. Retry capture only; never replay the dispatched input.
            c.sleep(1)
            duration = max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
            elapsed += duration
            unseen += duration
            if unseen >= 30:
                data['action_status'] = 'capture_timeout'
                persist()
                break
            continue
        c.checkpoint()
        guard._require_current_scene(scene)
        kind = observe(scene, c.settings.ocr_confidence).page_kind
        if kind == 'battle':
            if battle_node(scene,c.settings.ocr_confidence)!=source_node:
                data.update(action_status='unknown',reason='战斗节点与本次来源不一致。',
                            screenshot=str(c.evidence(scene,'currency_node_wrong_battle')))
                persist()
                break
            unseen = 0.
            if not battle_seen:
                data['battle'] = str(c.evidence(scene, 'currency_node_battle'))
                data['action_status'] = 'battle_observed'
                persist()
            battle_seen = True
        elif kind in ('node_result','final_victory'):
            after_path = c.evidence(scene, 'currency_node_result')
            c.checkpoint()
            guard._require_current_scene(scene)
            same_node = result_node(scene, c.settings.ocr_confidence) == source_node
            # Combat is owned by the game's auto-battle. A short fight may
            # finish between OCR frames; the dispatched start plus a matching
            # victory result verifies the decision's outcome without requiring
            # an incidental screenshot during combat.
            verified=same_node and (battle_seen or data.get('start_dispatched',False))
            data.update(node_verified=verified,battle_observed=battle_seen,
                        final_victory=kind=='final_victory' and verified,
                        action_status='verified' if verified else 'unknown',
                        verification='matching_result_after_start' if verified and not battle_seen else 'battle_and_matching_result' if verified else 'unverified',
                        after=str(after_path))
            data['screenshot'] = data['after']
            persist()
            break
        elif kind not in ('unknown', 'preparation'):
            data.update(action_status='unknown', unexpected_page=kind,
                        screenshot=str(c.evidence(scene, 'currency_node_unexpected')))
            persist()
            break
        c.sleep(2)
        duration = max(0., time.monotonic()-started-(c.runner.inactive_duration-inactive))
        elapsed += duration
        if kind in ('unknown', 'preparation'):
            unseen += duration
            if unseen >= 30:
                data.update(action_status='unknown', screenshot=str(c.evidence(scene, 'currency_node_unrecognized')))
                persist()
                break
    else:
        data['action_status'] = 'timeout'
        persist()
    c.runner.emit(dict(type='currency_wars', data=data))
    detail = (f'{source_node} 节点战斗与胜利结算已验证；整局尚未完成。' if data['node_verified'] else
              '节点结果未确认；保留动作记录和截图，未重复出战。')
    c.log(detail)
    c.report.safe_next = '核对当前节点结算后继续；此测试不会点击继续挑战或重复出战。'
    return TaskResult(TASK, 'partial', detail)
