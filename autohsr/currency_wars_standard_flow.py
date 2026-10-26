"""Standard A8-40 development flow. Only observed and validated inputs run."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_navigation import locate, unique
from .currency_wars_prepare import trusted
from .currency_wars_session import StandardSession
from .currency_wars_standard import difficulty_page, selected_rank
from .models import AutomationError, EmptyCapture, TaskResult


@dataclass(frozen=True)
class StandardAction:
    intent: str
    expected: str
    target: object


def next_action(scene, confidence=.65):
    clean = trusted(scene, confidence)
    if difficulty_page(scene, confidence) and selected_rank(scene, confidence) == 40:
        return StandardAction('start_standard_a8_40', 'boss_preview',
                              unique(clean, '开始对局', (.75, .82, .99, .97)))
    kind = observe(scene, confidence).page_kind
    if kind == 'boss_preview':
        return StandardAction('advance_standard_preview', 'plane_map',
                              unique(clean, '下一步', (.74, .87, .84, .95)))
    if kind == 'plane_map':
        return StandardAction('advance_standard_plane', 'environment',
                              unique(clean, '点击空白处继续', (.43, .86, .57, .93)))
    raise AutomationError('标准对局当前页面需要局面采集或新动作校准：' + kind)


def evidence(c, scene, label):
    from .currency_wars_replay import save_sample
    screenshot = c.evidence(scene, label)
    save_sample(scene, screenshot, stage='entry')
    return str(screenshot)


def run_standard(c):
    if c.report.operation != 'currency_wars_standard':
        raise AutomationError('标准对局开发须使用独立入口。')
    # This initial path is intentionally not an acceptance counter. Any repair
    # or development continuation is recorded separately from ten frozen runs.
    store = StandardSession(Path(c.report.run_dir).parent/'currency-standard-session.json')
    c.currency_standard_session = store
    if store.data is not None and not c.runner.currency_resume:
        raise AutomationError('已有标准对局记录，请使用明确的接续入口核对当前局，未重开。')
    if c.runner.currency_resume:
        if store.data is None or store.data['status'] != 'active':
            raise AutomationError('没有已核实开始且可接续的标准对局；未知开局未重放。')
        if store.data['actions'] and store.data['actions'][-1]['status'] != 'verified':
            raise AutomationError('上次标准动作尚未核实，先核对反馈，未接续输入。')
        store.data.setdefault('continuations', []).append(str(c.report.run_dir))
        store.persist()
    else:
        result = locate(c)
        entry = c.report.currency_wars
        if not entry.get('rank_verified'):
            return result
        store.begin(c.report.run_dir, entry)
    c.report.currency_wars = store.data
    guard = CurrencyWarsWorkflow(c)
    scene = c.snapshot()
    for _ in range(40):
        c.checkpoint()
        guard._require_current_scene(scene)
        try:
            choice = next_action(scene, c.settings.ocr_confidence)
        except AutomationError as error:
            from .currency_wars_state import snapshot_from_scene
            current = snapshot_from_scene(scene, c.runner.input_epoch, c.settings.ocr_confidence,
                                          'standard_current')
            store.data.update(action_status='needs_observation', reason=str(error),
                              page_kind=observe(scene, c.settings.ocr_confidence).page_kind,
                              strategy_snapshot=asdict(current),
                              screenshot=evidence(c, scene, 'currency_standard_observe'))
            store.persist()
            break
        if choice.intent == 'start_standard_a8_40' and (store.data['status'] != 'start_pending' or store.data['actions']):
            raise AutomationError('已有标准开局提交，未开始第二个对局。')
        action = store.pending(choice.intent, c.runner.input_epoch,
                               evidence(c, scene, 'currency_standard_'+choice.intent), choice.expected)
        c.report.currency_wars = store.data
        c.log('标准A8-40开发：' + choice.intent)
        c.currency_standard_input(scene, choice)
        elapsed, after = 0., None
        while elapsed < 60:
            started, inactive = time.monotonic(), c.runner.inactive_duration
            try:
                after = c.snapshot()
            except EmptyCapture:
                after = None
            if after is not None:
                guard._require_current_scene(after)
                if observe(after, c.settings.ocr_confidence).page_kind == choice.expected:
                    action.update(status='verified', after=evidence(c, after, 'currency_standard_after_'+choice.intent))
                    store.data.update(action_status='transition_verified', screenshot=action['after'])
                    if choice.intent == 'start_standard_a8_40':
                        store.data['status'] = 'active'
                        store.data['start_verified'] = True
                    store.persist()
                    scene = after
                    break
            c.sleep(.5)
            elapsed += max(0., time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status'] = 'unknown'
            store.data.update(action_status='unknown', reason='标准动作转换未核实，未重复输入。')
            if after is not None:
                store.data['screenshot'] = evidence(c, after, 'currency_standard_transition_unknown')
            store.persist()
            break
    else:
        store.data.update(action_status='step_limit', reason='本次标准开发达到步骤上限。')
        store.persist()
    c.report.currency_wars = store.data
    c.runner.emit(dict(type=TASK, data=store.data))
    c.report.safe_next = '先读取标准对局当前局面，再接续已核实动作；不重开或重放未知交易。'
    return TaskResult(TASK, 'partial', store.data.get('reason', '标准对局开发未完成，已留证。'))
