"""Verified lower daily-training milestones for the explicit reward-only run."""

import re

from .currency_wars_identity import AccountNotObserved, checked_account_key
from .free_rewards import reward_overlay
from .models import AutomationError, EmptyCapture, Stopped, normalize
from .policy import replenishment_dialog
from .workflows import REWARDS, REWARD_SLOTS, TITLE


_ACTIVITY_VALUE = (.15, .30, .205, .36)
_CLOSE = ('点击空白处关闭', '点击任意位置关闭', '点击空白处继续')
_MODAL = ('提示', '温馨提示', '确认', '确定', '取消', '选择奖励', '请选择奖励', '支付', '付款', '购买')


def _unique(scene, labels, area, confidence):
    tokens = [t for t in scene.tokens if t.within(area) and normalize(t.text) in labels]
    return tokens[0] if len(tokens) == 1 and confidence <= tokens[0].score <= 1 else None


def _blocked(scene):
    return (scene.has(('列车补给', '重新连接', '加载中'), exact=True)
            or scene.has(_MODAL, (.25, .18, .75, .86), exact=True) or replenishment_dialog(scene))


def _markers(workflow, scene, name, confidence):
    result = {}
    for x, y, _score in workflow._matches(scene, name, REWARDS):
        points = next((index * 100 for index, slot in enumerate(REWARD_SLOTS, 1)
                       if slot[0] < x < slot[2]), None)
        if points is None:
            continue
        caption = (x - .02, y + .025, x + .02, y + .066)
        numbers = [t for t in scene.tokens if t.within(caption) and re.fullmatch(r'[0-9]{1,3}', t.text.strip())]
        if len(numbers) == 1 and numbers[0].text.strip() == str(points) and confidence <= numbers[0].score <= 1:
            result[points] = (x, y)
    return result


def _band(workflow, scene, activity, confidence):
    if (_blocked(scene) or reward_overlay(scene) or scene.has(_CLOSE, exact=True)
            or scene.has('本日活跃度已满', (.14, .68, .89, .87), exact=True)
            or any(_unique(scene, (label,), TITLE, confidence) is None for label in ('星际和平指南', '每日实训'))):
        return None
    numbers = [t for t in scene.tokens if t.within(_ACTIVITY_VALUE) and re.fullmatch(r'[0-9]{1,3}', t.text.strip())]
    if (len(numbers) != 1 or int(numbers[0].text.strip()) != activity or not confidence <= numbers[0].score <= 1
            or workflow._icon(scene, 'daily_activity_badge', (.13, .23, .225, .37), threshold=.85) is None):
        return None
    gifts = _markers(workflow, scene, 'daily_reward', confidence)
    claimed = frozenset(_markers(workflow, scene, 'daily_completed', confidence))
    if claimed.intersection(gifts) or any(points > activity for points in claimed.union(gifts)):
        return None
    return gifts, claimed


def _after_claim(workflow, require_source, activity, confidence, points, previous):
    context = workflow.ctx
    candidate = None
    close_sent = False
    for _ in range(8):
        try:
            scene = workflow._snapshot()
            require_source(scene)
        except (AccountNotObserved, EmptyCapture):
            candidate = None
        else:
            band = _band(workflow, scene, activity, confidence)
            if band is not None and points in band[1] and previous.issubset(band[1]):
                signature = (frozenset(band[0]), band[1])
                if candidate == (context.capture_sequence - 1, signature):
                    return band
                candidate = (context.capture_sequence, signature)
            else:
                candidate = None
                if (not close_sent and not _blocked(scene)
                        and _unique(scene, ('获得物品',), (.25, .04, .75, .50), confidence)):
                    close = _unique(scene, _CLOSE, (.25, .65, .75, .97), confidence)
                    if close is not None:
                        close_sent = True
                        context.click(scene, close)
                        workflow._pause()
                        continue
        context.sleep(.25)
    return None


def claim_reached_milestones(workflow, scene, activity):
    context = workflow.ctx
    confidence = max(.85, workflow.settings.ocr_confidence)
    band = _band(workflow, scene, activity, confidence)
    confirmed = set()
    pending = None
    if band is not None and band[0]:
        window, geometry = context.window, scene.geometry
        epoch = context.scene_epoch
        occlusions = context.capture_occlusion_count
        try:
            key = window.current_window_key()
            account = checked_account_key(scene, confidence)

            def require_source(frame):
                if (frame is None or not key or context.window is not window or window.current_window_key() != key
                        or context.capture_occlusion_count != occlusions or frame.geometry != geometry
                        or frame is not context.last_scene or context.scene_epoch != epoch
                        or context.runner.input_epoch != epoch):
                    raise AutomationError('实训领奖的窗口或画面代次已变化。')
                if checked_account_key(frame, confidence) != account:
                    raise AutomationError('实训领奖期间当前账号已变化。')

            for _ in range(4):
                available, previous = band
                if not available:
                    break
                scene = context.last_scene
                require_source(scene)
                pending = max(available)
                context.click(scene, available[pending])
                workflow._pause()
                after = _after_claim(workflow, require_source, activity, confidence, pending, previous)
                if after is None:
                    break
                confirmed.update(after[1] - previous)
                pending, band = None, after
        except Stopped:
            raise
        except AutomationError as error:
            context.log(f'实训里程碑核对中断：{error}')
        scene = context.last_scene

    detail = f'实训活跃值为{activity}/500'
    if confirmed:
        detail += '，本次核实' + '、'.join(str(points) for points in sorted(confirmed)) + '档已领'
    if pending is not None:
        detail += f'，{pending}档本次领取反馈待核对'
    return workflow._result('daily', 'partial', detail + '，尚未确认每日任务完成。', scene)
