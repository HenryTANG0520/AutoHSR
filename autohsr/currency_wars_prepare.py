"""Bounded game startup for Currency Wars, without starting a match or spending."""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .models import AutomationError, EmptyCapture, Scene, TaskResult, Token, normalize
from .storage import replace_file
from .workflows import DailyWorkflow

PREPARATION_OPERATIONS = ('currency_wars_prepare', 'currency_wars_standard', 'currency_wars_points', 'currency_wars_rewards')


def trusted(scene, confidence=.65):
    tokens = [t for t in scene.tokens if math.isfinite(t.score) and confidence <= t.score <= 1
              and len(t.box) == 4 and all(math.isfinite(v) and 0 <= v <= 1 for v in t.box)
              and t.box[0] < t.box[2] and t.box[1] < t.box[3]]
    return Scene(tokens, scene.image, scene.geometry, scene.captured_at,scene.field_reads)


def click_target(scene, confidence=.65):
    scene = trusted(scene, confidence)
    if scene.has(('密码', '验证码', '扫码登录', '用户协议', '资源下载', '更新游戏')):
        raise AutomationError('启动需要人工完成账号验证、协议或更新，未操作认证界面。')
    builds = [t for t in scene.tokens if t.within((0, .95, .6, 1))
              and re.fullmatch(r'cnpr[o0]dwin[0-9.]+_d[0-9]+_a[0-9]+_l[0-9]+', normalize(t.text))]
    enters = [t for t in scene.tokens if t.within((.3, .88, .7, .98)) and normalize(t.text) == '点击进入']
    if (len(builds) == 1 and len(enters) == 1
            and scene.has('登出', (.9, .3, 1, .42), exact=True)
            and scene.has('退出', (.9, .42, 1, .5), exact=True)
            and not DailyWorkflow._navigation_page(scene)):
        return 'enter_game', enters[0]
    if DailyWorkflow._supply_overlay(scene):
        target = DailyWorkflow._supply_claim(scene)
        if target is not None:
            return ('close_supply' if DailyWorkflow._supply_revealed(scene) else 'claim_supply'), target
    if DailyWorkflow._login_reward_overlay(scene) and not scene.has(('购买', '支付', '付款', '续购', '续费')):
        target = scene.find(('点击空白处关闭', '点击任意位置关闭', '点击空白处继续'),
                            (.25, .65, .75, .97), exact=True)
        if target is not None:
            return 'close_login_reward', target
    raise AutomationError('当前没有完整核实的游戏启动或已有免费登录奖励入口。')


def key_allowed(scene, confidence=.65):
    scene = trusted(scene, confidence)
    return (observe(scene, confidence).page_kind == 'unknown' and DailyWorkflow._navigation_page(scene)
            and not DailyWorkflow._phone(scene) and not DailyWorkflow._login(scene)
            and not scene.has(('密码', '验证码', '扫码登录', '用户协议', '资源下载', '更新游戏')))


def ready_kind(scene, context):
    if getattr(context.runner, 'currency_locate', False):
        from .currency_wars_navigation import page_kind
        navigation = page_kind(scene, context.settings.ocr_confidence)
        if navigation != 'unknown':
            return navigation
    page = observe(scene, context.settings.ocr_confidence).page_kind
    if page != 'unknown':
        return page
    scene = trusted(scene, context.settings.ocr_confidence)
    if DailyWorkflow._phone(scene):
        return 'phone'
    if DailyWorkflow(context)._world(scene):
        return 'world'
    return None


def prepare(c):
    """A dedicated formal operation. The ordinary read-only entry cannot call it."""
    if c.report.operation not in PREPARATION_OPERATIONS:
        raise AutomationError('游戏启动准备需要独立的货币战争准备入口。')
    data = dict(mode='startup_prepare', actions=[], game_ready=False, completion_verified=False,
                action_status='observing', screenshot='')
    journal = Path(c.report.run_dir) / 'currency-prepare.json'
    def persist():
        c.report.currency_wars = data
        temp = journal.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        replace_file(temp, journal)
    guard = CurrencyWarsWorkflow(c)
    persist()
    used = set()
    escapes = 0
    elapsed = 0.
    scene = None
    while elapsed < 30:
        started = time.monotonic()
        inactive = c.runner.inactive_duration
        try:
            scene = c.snapshot()
            break
        except EmptyCapture:
            c.sleep(.5)
            elapsed += max(0., time.monotonic() - started - (c.runner.inactive_duration - inactive))
    if scene is None:
        raise AutomationError('启动后30秒仍无有效画面，未发送输入。')
    for _ in range(12):
        c.checkpoint()
        guard._require_current_scene(scene)
        kind = ready_kind(scene, c)
        if kind and kind != 'world':
            data.update(game_ready=True, page_kind=kind, action_status='game_ready',
                        screenshot=str(c.evidence(scene, 'currency_prepare_ready')))
            persist()
            c.runner.emit(dict(type=TASK, data=data))
            c.report.safe_next = '按当前真实页面继续定位标准博弈和A8-40；准备完成不等于已开始或通关。'
            return TaskResult(TASK, 'partial', f'游戏启动准备已核实：{kind}；尚未开始新的货币战争对局。')
        if kind == 'world':
            intent, target = 'open_phone', None
        else:
            try:
                intent, target = click_target(scene, c.settings.ocr_confidence)
            except AutomationError as error:
                if key_allowed(scene, c.settings.ocr_confidence) and not DailyWorkflow(c)._in_battle(scene) and escapes < 5:
                    intent, target = 'back_to_world', None
                    escapes += 1
                else:
                    data.update(action_status='needs_observation', reason=str(error),
                                screenshot=str(c.evidence(scene, 'currency_prepare_unknown')))
                    persist()
                    break
        if intent != 'back_to_world' and intent in used:
            data.update(action_status='unknown', reason='同一步骤已有提交记录，未重复发送。')
            persist()
            break
        used.add(intent)
        action = dict(action=intent, status='pending', before=str(c.evidence(scene, 'currency_prepare_' + intent)))
        data['actions'].append(action)
        data.update(action_status='pending', screenshot=action['before'])
        persist()
        c.log('货币战争启动准备：' + intent)
        before_title = tuple(normalize(t.text) for t in scene.tokens if t.within((0, 0, .32, .13)))
        if target is None:
            c.currency_prepare_back(scene)
        else:
            c.currency_prepare_click(scene, intent, target)
        elapsed = 0.
        after = None
        while elapsed < (120 if intent == 'enter_game' else 45):
            started = time.monotonic()
            inactive = c.runner.inactive_duration
            try:
                after = c.snapshot()
            except EmptyCapture:
                after = None
            verified = False
            if after is not None:
                guard._require_current_scene(after)
                kind = ready_kind(after, c)
                clean = trusted(after, c.settings.ocr_confidence)
                if intent == 'enter_game':
                    verified = bool(kind or DailyWorkflow._supply_overlay(clean) or DailyWorkflow._login_reward_overlay(clean))
                elif intent == 'claim_supply':
                    verified = bool(DailyWorkflow._supply_revealed(clean) or kind or DailyWorkflow._login_reward_overlay(clean))
                elif intent in ('close_supply', 'close_login_reward'):
                    verified = bool(kind or intent == 'close_supply' and DailyWorkflow._login_reward_overlay(clean))
                elif intent == 'open_phone':
                    verified = kind == 'phone'
                else:
                    title = tuple(normalize(t.text) for t in clean.tokens if t.within((0, 0, .32, .13)))
                    verified = bool(kind or key_allowed(clean, c.settings.ocr_confidence) and title != before_title)
                if verified:
                    action.update(status='verified', after=str(c.evidence(after, 'currency_prepare_after_' + intent)))
                    data.update(action_status='transition_verified', screenshot=action['after'])
                    persist()
                    scene = after
                    break
            c.sleep(.5)
            elapsed += max(0., time.monotonic() - started - (c.runner.inactive_duration - inactive))
        else:
            action['status'] = 'unknown'
            data.update(action_status='unknown', reason='启动转换超时，未重复提交。')
            if after is not None:
                data['screenshot'] = str(c.evidence(after, 'currency_prepare_transition_unknown'))
            persist()
            break
    else:
        data.update(action_status='step_limit', reason='启动准备超过步骤上限。')
        persist()
    c.runner.emit(dict(type=TASK, data=data))
    c.report.safe_next = '先核对当前页面及准备记录；未知提交不重放，未开始货币战争。'
    return TaskResult(TASK, 'partial', data.get('reason', '启动准备未完成，已留证。'))
