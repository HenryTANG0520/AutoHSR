"""Bounded navigation to Currency Wars; never submit a new match."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_prepare import prepare, trusted
from .models import AutomationError, EmptyCapture, TaskResult, Token, normalize
from .storage import replace_file
from .workflows import DailyWorkflow


@dataclass(frozen=True)
class NavigationAction:
    intent: str
    expected: tuple[str, ...]
    target: Token | None = None
    key: str | None = None


def unique(scene, labels, roi):
    labels = (labels,) if isinstance(labels, str) else labels
    def text(value):
        return normalize(value).translate(str.maketrans('', '', '「」『』'))
    matches = [t for t in scene.tokens if t.within(roi) and text(t.text) in
               tuple(text(label) for label in labels)]
    if len(matches) != 1:
        raise AutomationError('导航目标缺失或不唯一：' + '/'.join(labels))
    return matches[0]


def page_kind(scene, confidence=.65):
    scene = trusted(scene, confidence)
    if (scene.has('积分奖励', (.02, .28, .15, .35), exact=True)
            and scene.has('规则说明', (.78, .28, .9, .35), exact=True)
            and scene.has('当前积分', (.05, .63, .2, .70), exact=True)):
        return 'points_rewards'
    kind = observe(scene, confidence).page_kind
    if kind != 'unknown':
        return kind
    if DailyWorkflow._phone(scene):
        return 'phone'
    if scene.has(('旷宇纷争', '寰宇纷争'), (0, 0, .32, .13), exact=True):
        # A title/category in the left list does not prove the right panel.
        if (scene.has('零和博弈', (.70, .30, .86, .40), exact=True)
                and scene.has('晋升等级', (.40, .50, .57, .60), exact=True)
                and scene.has('奖励预览', (.55, .60, .70, .67), exact=True)
                and scene.has('前往参与', (.70, .75, .90, .90), exact=True)):
            return 'currency_guide'
        return 'universe_guide'
    if DailyWorkflow._guide(scene):
        return 'guide'
    return 'unknown'


def next_action(scene, context):
    confidence = context.settings.ocr_confidence
    clean = trusted(scene, confidence)
    if clean.has(('密码', '验证码', '扫码登录', '用户协议', '资源下载', '更新游戏')):
        raise AutomationError('导航出现账号验证、协议或更新，未输入。')
    kind = page_kind(scene, confidence)
    if kind == 'points_rewards':
        return NavigationAction('close_points_rewards', ('lobby',), key='esc')
    if kind == 'phone':
        return NavigationAction('open_guide', ('guide', 'universe_guide', 'currency_guide'),
                                unique(clean, ('指南', '星际和平指南'), (.55, .25, 1, 1)))
    if kind == 'guide':
        match = context.template(scene, 'du_guide_tab', (.28, .15, .35, .24), threshold=.85)
        if match is None:
            raise AutomationError('未识别指南玩法页签，未猜测坐标。')
        x, y, score = match
        if not (.28 <= x <= .35 and .15 <= y <= .24 and .85 <= score <= 1):
            raise AutomationError('指南页签匹配位置无效。')
        return NavigationAction('open_universe_guide', ('universe_guide', 'currency_guide'),
                                Token('玩法指南页签', score, (x-.018, y-.018, x+.018, y+.018)))
    if kind == 'universe_guide':
        return NavigationAction('select_currency_guide', ('currency_guide',),
                                unique(clean, '货币战争', (.14, .26, .35, .82)))
    if kind == 'currency_guide':
        return NavigationAction('participate', ('world_entry', 'lobby'),
                                unique(clean, '前往参与', (.70, .75, .90, .90)))
    if kind == 'world_entry':
        match = context.template(scene, 'du_interaction_f', (.45, .30, .80, .75), threshold=.88)
        if match is None:
            raise AutomationError('已到货币战争地点，但尚未识别对应F交互提示。')
        x, y, score = match
        label = unique(clean, '货币战争', (.4, .3, .85, .8))
        if not (.88 <= score <= 1 and 0 < label.center[0]-x < .22 and abs(label.center[1]-y) < .04):
            raise AutomationError('货币战争名称与F图标位置不对应。')
        return NavigationAction('interact_currency', ('lobby',), key='f')
    if kind == 'lobby':
        return NavigationAction('open_mode', ('mode_select', 'points_rewards'),
                                unique(clean, '开始货币战争', (.65, .84, .99, .96)))
    if kind == 'mode_select':
        if standard_selected(scene, confidence):
            return None
        return NavigationAction('select_standard', ('standard_selected',),
                                unique(clean, '标准博弈', (0, .16, .2, .27)))
    raise AutomationError('尚未校准当前导航页面：' + kind)


def standard_selected(scene, confidence=.65):
    clean = trusted(scene, confidence)
    return (observe(scene, confidence).page_kind == 'mode_select'
            and clean.has('标准博弈', (.30, .11, .40, .18), exact=True)
            and clean.has('进入标准博弈', (.75, .85, .96, .94), exact=True))


def locate(c):
    if c.report.operation != 'currency_wars_prepare' or not c.runner.currency_locate:
        raise AutomationError('定位入口需要显式的货币战争导航操作。')
    result = prepare(c)
    bootstrap = c.report.currency_wars
    if not bootstrap.get('game_ready'):
        return result
    data = dict(mode='entry_navigation', startup=bootstrap, actions=[], entry_ready=False,
                completion_verified=False, action_status='observing')
    journal = Path(c.report.run_dir) / 'currency-navigation.json'
    def persist():
        c.report.currency_wars = data
        temp = journal.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        replace_file(temp, journal)
    def evidence(scene, label):
        screenshot = c.evidence(scene, label)
        from .currency_wars_replay import save_sample
        save_sample(scene, screenshot, stage='entry')
        return str(screenshot)
    guard = CurrencyWarsWorkflow(c)
    used = set()
    persist()
    scene = c.snapshot()
    for _ in range(16):
        c.checkpoint()
        guard._require_current_scene(scene)
        if standard_selected(scene, c.settings.ocr_confidence):
            data.update(entry_ready=True, page_kind='standard_selected', action_status='entry_ready',
                        screenshot=evidence(scene, 'currency_navigation_ready'))
            persist()
            break
        try:
            choice = next_action(scene, c)
        except AutomationError as error:
            data.update(action_status='needs_observation', reason=str(error),
                        screenshot=evidence(scene, 'currency_navigation_unknown'))
            persist()
            break
        if choice is None or choice.intent in used:
            data.update(action_status='unknown', reason='导航步骤已提交或没有新目标，未重复输入。')
            persist()
            break
        used.add(choice.intent)
        action = dict(action=choice.intent, status='pending', expected=list(choice.expected),
                      before=evidence(scene, 'currency_navigation_' + choice.intent))
        data['actions'].append(action)
        data.update(action_status='pending', screenshot=action['before'])
        persist()
        c.log('货币战争入口导航：' + choice.intent)
        c.currency_navigation_input(scene, choice)
        elapsed, after = 0., None
        while elapsed < 60:
            started, inactive = time.monotonic(), c.runner.inactive_duration
            try:
                after = c.snapshot()
            except EmptyCapture:
                after = None
            if after is not None:
                guard._require_current_scene(after)
                kind = page_kind(after, c.settings.ocr_confidence)
                if kind in choice.expected or ('standard_selected' in choice.expected and
                                               standard_selected(after, c.settings.ocr_confidence)):
                    action.update(status='verified', after=evidence(after, 'currency_navigation_after_' + choice.intent))
                    data.update(action_status='transition_verified', screenshot=action['after'])
                    persist()
                    scene = after
                    # A verified rewards detour can consume the first entry
                    # click. After closing it, derive one new lobby click.
                    if choice.intent == 'close_points_rewards':
                        used.discard('open_mode')
                    break
            c.sleep(.5)
            elapsed += max(0., time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status'] = 'unknown'
            data.update(action_status='unknown', reason='导航转换未核实，保留提交记录，不重复输入。')
            if after is not None:
                data['screenshot'] = evidence(after, 'currency_navigation_transition_unknown')
            persist()
            break
    else:
        data.update(action_status='step_limit', reason='入口导航超过步骤上限。')
        persist()
    c.runner.emit(dict(type=TASK, data=data))
    c.report.safe_next = '核对标准博弈难度与A8-40控制；本次未提交新对局。'
    return TaskResult(TASK, 'partial', '已定位标准博弈配置，未开始对局。' if data['entry_ready'] else
                      data.get('reason', '导航未完成，已留证。'))
