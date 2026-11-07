"""Bounded search for an authorized task in the native daily-training list."""

import numpy as np

from .currency_wars_identity import checked_account_key
from .daily_event_observe import read_event_installation
from .daily_synthesis import _task_game_day
from .daily_training_scan import (MAX_SCROLLS, TRAINING_CARD_VERSION, advanced, same_view,
                                  stable_viewport, visible_viewport)
from .models import AutomationError, Stopped
from .storage import hold_read_sources
from .workflow_screen import _CurrentFrames


def search_task(workflow, scene, activity, select, receipt, *, inspect_current=False, reward_only=False):
    """Return the latest training frame and the caller's decision for a settled card."""
    ctx = workflow.ctx
    window = getattr(ctx, 'window', None)
    operations = ('daily', 'reward_only') if reward_only else ('daily',)
    if (ctx.report.operation not in operations or type(activity) is not int or not 0 <= activity < 500
            or not isinstance(scene.image, np.ndarray) or not callable(getattr(window, 'current_executable', None))):
        return scene, None
    confidence = max(.85, workflow.settings.ocr_confidence)
    initial = visible_viewport(workflow, scene, confidence)
    if (initial is None or initial.activity != activity
            or not (inspect_current or initial.right_clipped)):
        return scene, None
    try:
        account = checked_account_key(scene, confidence)
        installation = read_event_installation(window)
    except Stopped:
        raise
    except AutomationError:
        return scene, None
    if installation.version != TRAINING_CARD_VERSION:
        return scene, None

    reader = _CurrentFrames(ctx)
    receipt.update(state='unverified', scrolls=[])

    def check(pair):
        reader.verify_pair(*pair)
        if pair[0].account != account:
            raise AutomationError('查找实训任务时账号变化，停止操作。')
        if any(not workflow._tab(frame.scene, '每日实训') or _task_game_day(frame.scene) != initial.game_day
               or workflow._activity(frame.scene) != activity for frame in pair):
            raise AutomationError('查找实训任务时页面、游戏日或活跃度已变化。')
        if read_event_installation(window) != installation:
            raise AutomationError('查找实训任务时客户端安装来源已变化。')

    def observe():
        first = reader.capture()
        ctx.sleep(.22)
        pair = first, reader.capture()
        check(pair)
        view = stable_viewport(workflow, tuple(frame.scene for frame in pair), confidence)
        return pair, view

    pair, view = observe()
    for scrolls in range(MAX_SCROLLS + 1):
        current = pair[-1].scene
        if view is None:
            return current, None
        result = select(pair, view, confidence)
        if result is not None:
            receipt['state'] = 'found'
            return current, result
        if not view.right_clipped or scrolls == MAX_SCROLLS:
            receipt['state'] = 'limit' if view.right_clipped else 'right_edge_clear'
            return current, None

        def before_submit():
            check(pair)
            if (stable_viewport(workflow, tuple(frame.scene for frame in pair), confidence) != view
                    or len(receipt['scrolls']) != scrolls):
                raise AutomationError('实训任务滚动前卡片区或发送序号已变化。')
            reader.guard()
            receipt['scrolls'].append('unconfirmed')
            ctx.last_scene, ctx._scroll_anchor = None, None

        with hold_read_sources((installation.source,)):
            window.scroll_down_once(*view.anchor.center, reader.geometry, before_submit=before_submit)
        if len(receipt['scrolls']) != scrolls + 1:
            raise AutomationError('查找实训任务缺少滚动发送回执。')
        receipt['scrolls'][-1] = 'sent'
        ctx.sleep(.22)
        for _ in range(3):
            pair, candidate = observe()
            if candidate is not None and advanced(view, candidate):
                view = candidate
                break
        else:
            if candidate is not None and same_view(view, candidate):
                receipt['state'] = 'no_movement'
            return pair[-1].scene, None
