"""Find the already-authorized synthesis task past the initial training viewport."""

import numpy as np

from .currency_wars_identity import checked_account_key
from .daily_event_observe import read_event_installation
from .daily_synthesis import _task_game_day, task_target
from .daily_training_scan import (MAX_SCROLLS, TRAINING_CARD_VERSION, advanced, same_view,
                                  stable_viewport, visible_viewport)
from .models import AutomationError, Stopped
from .storage import hold_read_sources
from .workflow_screen import _CurrentFrames


def _synthesis_target(pair, view):
    first, second = (task_target(frame.scene) for frame in pair)
    return (first is not None and second is not None
            and all(abs(a - b) <= .006 for a, b in zip(first.box, second.box))
            and any(card['task'] == 'synthesis' and card['state'] == 'pending'
                    and abs(center - second.center[0]) <= .035
                    for card, center in zip(view.cards, view.centers)))


def find_hidden_card(workflow, scene, activity):
    """Return the current frame and whether a freshly settled synthesis card is actionable."""
    ctx = workflow.ctx
    window = getattr(ctx, 'window', None)
    if (ctx.report.operation != 'daily' or not (workflow.settings.daily and workflow.settings.daily_synthesis)
            or type(activity) is not int or not 0 <= activity < 500
            or not isinstance(scene.image, np.ndarray) or not callable(getattr(window, 'current_executable', None))):
        return scene, False
    confidence = max(.85, workflow.settings.ocr_confidence)
    initial = visible_viewport(workflow, scene, confidence)
    if initial is None or not initial.right_clipped or initial.activity != activity:
        return scene, False
    try:
        account = checked_account_key(scene, confidence)
        installation = read_event_installation(window)
    except Stopped:
        raise
    except AutomationError:
        return scene, False
    if installation.version != TRAINING_CARD_VERSION:
        return scene, False

    reader = _CurrentFrames(ctx)
    receipt = ctx.report.training_synthesis_search = dict(state='unverified', scrolls=[])

    def check(pair):
        reader.verify_pair(*pair)
        if pair[0].account != account:
            raise AutomationError('查找合成实训时账号变化，停止操作。')
        if any(not workflow._tab(frame.scene, '每日实训') or _task_game_day(frame.scene) != initial.game_day
               or workflow._activity(frame.scene) != activity for frame in pair):
            raise AutomationError('查找合成实训时页面、游戏日或活跃度已变化。')
        if read_event_installation(window) != installation:
            raise AutomationError('查找合成实训时客户端安装来源已变化。')

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
            return current, False
        if _synthesis_target(pair, view):
            receipt['state'] = 'found'
            return current, True
        if not view.right_clipped or scrolls == MAX_SCROLLS:
            receipt['state'] = 'limit' if view.right_clipped else 'right_edge_clear'
            return current, False

        def before_submit():
            check(pair)
            if (stable_viewport(workflow, tuple(frame.scene for frame in pair), confidence) != view
                    or len(receipt['scrolls']) != scrolls):
                raise AutomationError('合成实训滚动前卡片区或发送序号已变化。')
            reader.guard()
            receipt['scrolls'].append('unconfirmed')
            ctx.last_scene, ctx._scroll_anchor = None, None

        with hold_read_sources((installation.source,)):
            window.scroll_down_once(*view.anchor.center, reader.geometry, before_submit=before_submit)
        if len(receipt['scrolls']) != scrolls + 1:
            raise AutomationError('查找合成实训缺少滚动发送回执。')
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
            return pair[-1].scene, False
