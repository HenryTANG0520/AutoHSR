"""Attach observed encounter reward UI without granting an economic receipt."""
from __future__ import annotations

from .currency_wars_encounter_notice import TITLE, read_green, read_node, read_notice
from .currency_wars_standard_encounter import (
    _ORIGIN, _frame, _scope, arrival_evidence, dispatch_sources, require_files,
    resolve_sources, same_account,
)
from .currency_wars_standard_encounter_battle import BINDING, require_started
from .currency_wars_standard_progress import verified_attempt
from .models import AutomationError
from .storage import hold_read_sources


RECORD = 'encounter_reward_notice'
_WAIT = 8.0
_LINK_SECONDS = 4.0
_REASON = '遭遇奖励观察的原对局、结算或继续意图已改变。'


def _origin(session, choice, run_dir, epoch):
    if choice.intent != 'continue_standard_node':
        return None
    continuing = session['actions'][-1]
    attempt = session['node_attempt']
    start = session['actions'][attempt['start_action_id']]
    if BINDING not in start or _ORIGIN not in continuing:
        return None
    verified_attempt(session, allow_loss=True)
    require_started(session, start)
    scope = _scope(session, run_dir, epoch)
    if (scope is None or continuing[_ORIGIN]['scope'] != scope
            or continuing['status'] != 'pending' or continuing['action'] != choice.intent
            or continuing['expected'] != choice.expected or continuing['target'] != list(choice.payload)
            or attempt.get('result_kind') not in ('node_result', 'node_loss')
            or attempt.get('node') != choice.payload[0] or start['id'] != choice.payload[1]):
        raise AutomationError(_REASON)
    history = session['node_history'][-1]
    confirmed, refs = arrival_evidence(session, history)
    slot = confirmed['target'][4]
    preview = history['encounter']['panel']['cards'][slot-1]['reward_preview']
    amount = preview.get('quantity')
    if preview.get('kind') != 'gold' or type(amount) is not int or not 1 <= amount <= 99:
        return None
    plane, number = attempt['node'].split('-')
    return dict(scope=scope, node=attempt['node'], next_node=f'{plane}-{int(number)+1}',
                start_action_id=start['id'], continue_action_id=continuing['id'],
                encounter_arrival_action_id=confirmed['id'], result_kind=attempt['result_kind'],
                amount=amount), refs


def begin(session, choice, scene, run_dir, epoch):
    origin = _origin(session, choice, run_dir, epoch)
    if origin is not None:
        return RewardWatch(origin, scene)
    return None


class RewardWatch:
    """Collect the notice and a separate subsequent change in the HUD chip."""

    def __init__(self, origin, before):
        self.origin = origin
        self.last_stamp = before.captured_at
        self.last_scene = before
        self.notice = None
        self.green_before = None
        self.green_after = None
        self.latest_green = None
        self.link_stamp = None
        self.conflict = False

    def observe(self, scene, confidence, elapsed):
        if elapsed >= _WAIT or self.conflict or self.green_after is not None:
            return
        source, _ = self.origin
        if (scene is None or scene is self.last_scene or scene.captured_at <= self.last_stamp
                or read_node(scene, confidence) != source['next_node']):
            self.link_stamp = None
            self.latest_green = None
            return
        self.last_scene, self.last_stamp = scene, scene.captured_at
        amount = read_notice(scene, confidence)
        green = read_green(scene, confidence)
        if green is not None:
            self.latest_green = (green, scene)
        if amount is not None:
            if amount != source['amount']:
                self.conflict = True
                return
            if self.notice is None:
                self.notice = scene
            if self.latest_green is not None and self.latest_green[0] != amount:
                self.green_before = self.latest_green
                self.link_stamp = scene.captured_at
            else:
                self.link_stamp = None
            return
        if self.link_stamp is not None and scene.captured_at-self.link_stamp <= _LINK_SECONDS:
            if green == source['amount']:
                self.green_after = (green, scene)
            elif green is not None and green != self.green_before[0]:
                self.link_stamp = None

    def ready(self, elapsed):
        return self.conflict or self.green_after is not None or elapsed >= _WAIT

    def receipt(self, c, store, choice, guard, after, write_evidence):
        epoch, run_dir = c.runner.input_epoch, c.report.run_dir
        previous = store.require_pending(choice.intent, epoch)
        if previous != store.data or _origin(previous, choice, run_dir, epoch) != self.origin:
            raise AutomationError(_REASON)
        if self.conflict or self.notice is None:
            return None
        source, arrival = self.origin
        scope, confidence = source['scope'], c.settings.ocr_confidence
        if (read_notice(self.notice, confidence) != source['amount']
                or read_node(self.notice, confidence) != source['next_node']
                or not same_account(self.notice, previous, confidence)):
            raise AutomationError(_REASON)
        refs = (*resolve_sources(arrival, run_dir, store.path.parent),
                *dispatch_sources(previous, choice, run_dir, epoch, store.path.parent))
        with hold_read_sources(path for path, _ in refs):
            require_files(refs, run_dir)
            raw = write_evidence(self.notice, 'currency_standard_encounter_reward_notice')
            notice_frame = _frame(self.notice, raw, scope)
            before = self._green_evidence(self.green_before, previous, confidence, write_evidence, 'before', notice_frame)
            later = self._green_evidence(self.green_after, previous, confidence, write_evidence, 'after', notice_frame)
        if store.require_pending(choice.intent, epoch) != previous or store.data != previous:
            raise AutomationError(_REASON)
        guard._require_current_scene(after)
        if c.runner.input_epoch != epoch or not same_account(after, previous, confidence):
            raise AutomationError(_REASON)
        record = dict(status='reward_notice_observed', node=source['node'], next_node=source['next_node'],
                      start_action_id=source['start_action_id'], continue_action_id=source['continue_action_id'],
                      encounter_arrival_action_id=source['encounter_arrival_action_id'], result_kind=source['result_kind'],
                      notice=dict(title=TITLE, icon='gold', quantity=source['amount'], frame=notice_frame),
                      hud_green_before=before, hud_green_after=later, wallet_change=None)
        observed = [notice_frame['source'], *(item['frame']['source'] for item in (before, later) if item)]
        return record, resolve_sources((*arrival, *observed), run_dir, store.path.parent)

    def _green_evidence(self, observed, previous, confidence, write_evidence, phase, notice_frame):
        if observed is None:
            return None
        amount, scene = observed
        source, _ = self.origin
        if (read_green(scene, confidence) != amount or read_node(scene, confidence) != source['next_node']
                or not same_account(scene, previous, confidence)):
            raise AutomationError(_REASON)
        if scene is self.notice:
            return dict(quantity=amount, frame=notice_frame)
        raw = write_evidence(scene, 'currency_standard_encounter_reward_green_'+phase)
        return dict(quantity=amount, frame=_frame(scene, raw, source['scope']))
