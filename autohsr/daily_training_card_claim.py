"""Claim an already-completed training card found in the later viewports."""

from dataclasses import dataclass

from .daily_event_observe import read_event_installation
from .daily_synthesis import _task_game_day
from .daily_synthesis_search import synthesis_target
from .daily_training_scan import TRAINING_CARD_VERSION, stable_viewport
from .daily_training_search import search_task
from .free_rewards import gold_fraction
from .models import AutomationError, normalize
from .storage import hold_read_sources
from .workflow_screen import _CurrentFrames


def _claim_button(scene, center, confidence):
    left, right = center - .065, center + .065
    controls = [token for token in scene.tokens
                if token.within((left, .73, right, .81)) and normalize(token.text) in ('领取', '已领取', '前往', '进行中')]
    if len(controls) != 1:
        return None
    token = controls[0]
    x1, y1, x2, y2 = token.box
    if (normalize(token.text) != '领取' or not confidence <= token.score <= 1
            or not (left <= x1 < x2 <= right and .73 <= y1 < y2 <= .81)):
        return None
    gold = gold_fraction(scene, token.box)
    return token if gold is not None and gold >= .40 else None


def _candidate(pair, view, confidence):
    for card, center in zip(view.cards, view.centers):
        if card['state'] != 'claimable':
            continue
        first, second = (_claim_button(frame.scene, center, confidence) for frame in pair)
        if first is not None and second is not None and all(abs(a-b) <= .006 for a, b in zip(first.box, second.box)):
            return pair, view, card, center, second
    return None


@dataclass(frozen=True)
class CardClaim:
    reader: _CurrentFrames
    workflow: object
    installation: object
    selection: tuple
    record: dict
    confidence: float

    def _check(self, pair):
        source, view, _, _, _ = self.selection
        self.reader.verify_pair(*pair)
        if pair[0].account != source[0].account:
            raise AutomationError('实训任务点数核验期间账号已变化。')
        if (read_event_installation(self.reader.window) != self.installation
                or any(not self.workflow._tab(frame.scene, '每日实训') or _task_game_day(frame.scene) != view.game_day
                       for frame in pair)):
            raise AutomationError('实训任务点数的客户端、游戏日或页面已变化。')

    def submit(self):
        ctx = self.reader.context
        pair, view, _, _, target = self.selection

        def before_submit():
            self._check(pair)
            current = stable_viewport(self.workflow, tuple(frame.scene for frame in pair), self.confidence)
            candidate = _candidate(pair, view, self.confidence) if current == view else None
            if (candidate is None or candidate[2:] != self.selection[2:]
                    or self.record['input'] != 'not_sent'
                    or not any(row is self.record for row in ctx.report.training_task_points)):
                raise AutomationError('实训任务点数的目标已变化或意图已使用。')
            self.reader.guard()
            self.record['input'] = 'unconfirmed'
            ctx.last_scene, ctx._scroll_anchor = None, None

        with hold_read_sources((self.installation.source,)):
            self.reader.window.click(*target.center, self.reader.geometry, before_submit=before_submit)
        if self.record['input'] != 'unconfirmed':
            raise AutomationError('实训任务点数缺少本次原生提交反馈。')
        self.record['input'] = 'sent'

    def confirm(self):
        ctx = self.reader.context
        _, before, card, center, _ = self.selection
        expected = min(500, before.activity + card['points'])
        states = ('claimed', 'activity_full') if expected == 500 else ('claimed',)
        for _ in range(4):
            ctx.sleep(.22)
            first = self.reader.capture()
            ctx.sleep(.22)
            pair = first, self.reader.capture()
            self._check(pair)
            view = stable_viewport(self.workflow, tuple(frame.scene for frame in pair), self.confidence)
            if view is None:
                continue
            if view.activity not in (before.activity, expected):
                break
            if view.activity == expected and any(
                    item['task'] == card['task'] and item['points'] == card['points']
                    and item['progress'] == card['progress'] and item['target'] == card['target']
                    and item['state'] in states and abs(position-center) <= .02
                    for item, position in zip(view.cards, view.centers)):
                self.reader.guard()
                self.record.update(feedback='confirmed', activity_after=expected)
                ctx.report.engagement = expected
                return pair[-1].scene
        raise AutomationError('实训任务点数已尝试领取，本次卡片和活跃度反馈待核对。')


def claim_hidden_points(workflow, scene, activity, *, look_for_synthesis=False):
    ctx = workflow.ctx
    look_for_synthesis = (look_for_synthesis and ctx.report.operation == 'daily'
                          and workflow.settings.daily and workflow.settings.daily_synthesis)
    receipt = {}
    record = dict(search=receipt, input='not_sent', feedback='unknown')

    def select(pair, view, confidence):
        claim = _candidate(pair, view, confidence)
        if claim is not None or not look_for_synthesis:
            return claim
        return synthesis_target(pair, view)

    selection = None
    try:
        current, selection = search_task(workflow, scene, activity, select, receipt, reward_only=True)
    finally:
        if selection == 'synthesis':
            ctx.report.training_synthesis_search = receipt
        elif receipt:
            ctx.report.training_task_points.append(record)
    if selection is None or selection == 'synthesis':
        return current, selection
    _, view, card, _, _ = selection
    record.update(task=card['task'], points=card['points'], game_day=view.game_day, activity_before=view.activity)
    if any(row is not record and row.get('input') in ('sent', 'unconfirmed')
           and (row.get('game_day'), row.get('task'), row.get('points')) == (view.game_day, card['task'], card['points'])
           for row in ctx.report.training_task_points):
        raise AutomationError('本次已尝试领取该实训卡的点数，请核对原结果。')
    reader = _CurrentFrames(ctx)
    installation = read_event_installation(reader.window)
    if installation.version != TRAINING_CARD_VERSION:
        raise AutomationError('实训任务点数的客户端版本已变化。')
    confidence = max(.85, workflow.settings.ocr_confidence)
    claim = CardClaim(reader, workflow, installation, selection, record, confidence)
    ctx.training_task_points_input(claim)
    return claim.confirm(), 'claimed'
