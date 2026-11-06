"""One bounded, evidence-backed reroll of a fresh periodic station round."""
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time

import numpy as np

from .currency_wars_prepare import trusted
from .du_station_policy import CARD_LABELS, LABELS
from .du_station_preview import (
    _reroll_button, station_cards, station_reroll_observation, three_card_station_row,
)
from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped, Token, normalize


PROMPT_BODY = '部分区域会被保留是否继续'
PROMPT_ROW = (.29, .427, .71, .568)
REQUEST = 'station_reroll_request'
CONFIRM = 'station_reroll_confirm'
LEDGER = 'differential-universe-ledger.json'


@dataclass(frozen=True)
class StationRound:
    count: int
    names: tuple[str, ...]
    target: Token | None


def _patch(image, region):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = region
    return image[round(y1*height):round(y2*height), round(x1*width):round(x2*width)]


def _visible_image(scene):
    image = scene.image
    if (isinstance(image, np.ndarray) and image.dtype == np.uint8 and image.ndim == 3
            and image.shape[2] == 3 and image.shape[0] >= 360
            and abs(image.shape[1]/image.shape[0]-16/9) <= .04):
        return image
    return None


def retention_prompt_visible(scene, confidence=.85):
    return any(token.within(PROMPT_ROW) and confidence <= token.score <= 1 and normalize(token.text) == PROMPT_BODY
               for token in scene.tokens)


def station_round(scene, confidence=.85):
    """Require all three unselected cards and a visible left-side control."""
    image = _visible_image(scene)
    if image is None or retention_prompt_visible(scene, min(.65, confidence)):
        return None
    clean = trusted(scene, confidence)
    if (clean.has('提示', (.36, .335, .65, .415), exact=True)
            or clean.has(('取消', '确认'), (.30, .585, .70, .666), exact=True)):
        return None
    if not clean.has('选择一张站点卡', (.38, .195, .63, .32), exact=True):
        return None
    # At the observed unselected stage the right-hand control is dark. A
    # selected or highlighted card cannot reuse the left-side target.
    right = _patch(image, (.524, .874, .689, .916))
    if np.mean(np.max(right, axis=2) < 155) < .70:
        return None
    observed = station_reroll_observation(scene, confidence)
    if observed['status'] != 'observed':
        return None
    cards = station_cards(scene)
    if not three_card_station_row(cards) or any(card.selected for card in cards):
        return None
    labels = [token for token in trusted(scene, min(.65, confidence)).tokens
              if token.within(CARD_LABELS) and normalize(token.text) in LABELS]
    if len(labels) != len(cards):
        return None
    names = []
    for card in cards:
        matches = [token for token in labels if card.holds_label(token)]
        if len(matches) != 1 or matches[0].score < confidence:
            return None
        names.append(normalize(matches[0].text))
    count = observed['displayed_count']
    target = Token(f'重抽{count}', 1., _reroll_button(image)) if count > 0 else None
    return StationRound(count, tuple(names), target)


def retention_confirmation(scene, confidence=.85):
    """Return the actual confirm text on the complete retained-area prompt."""
    image = _visible_image(scene)
    if image is None or not retention_prompt_visible(scene, confidence):
        return None
    seen = trusted(scene, min(.65, confidence))
    if seen.has('选择下一站', (0, 0, .32, .13), exact=True):
        return None  # Fade or competing page, including a leftover old prompt.
    header = [t for t in seen.tokens if t.within((.36, .335, .65, .415))]
    body = [t for t in seen.tokens if t.within(PROMPT_ROW)]
    controls = [t for t in seen.tokens if t.within((.30, .585, .70, .666))]
    if (len(header) != 1 or normalize(header[0].text) != '提示' or len(body) != 1
            or normalize(body[0].text) != PROMPT_BODY or len(controls) != 2
            or min(t.score for t in (*header, *body, *controls)) < confidence):
        return None
    cancel, confirm = sorted(controls, key=lambda t: t.center[0])
    if (normalize(cancel.text) != '取消' or not cancel.within((.31, .585, .48, .666))
            or normalize(confirm.text) != '确认' or not confirm.within((.52, .585, .69, .666))):
        return None
    if np.mean(np.min(_patch(image, (.292, .36, .707, .563)), axis=2) > 180) < .75:
        return None
    for button in (cancel, confirm):
        x, y = button.center
        if np.mean(np.min(_patch(image, (x-.046, y-.014, x+.046, y+.014)), axis=2) > 175) < .62:
            return None
    return confirm


class StationReroll:
    def __init__(self, workflow, scene):
        from .currency_wars_identity import checked_account_key
        from .currency_wars_points import game_week, local_now
        from .du_archive_store import start_source
        from .weekly_plan import CHINA

        self.workflow, self.context = workflow, workflow.ctx
        self.confidence = max(.85, workflow.settings.ocr_confidence)
        self.week = game_week(local_now())
        self.account = checked_account_key(scene, self.confidence)
        self.epoch = self.context.scene_epoch
        self.window, self.geometry = self.context.window, scene.geometry
        self.hwnd = self.window.hwnd
        self.run_number = workflow.report['current_run']
        self.entry = (workflow.report['run_results'] or [{}])[-1].copy()
        self.session_id = workflow.session_id
        difficulty = self.entry.get('difficulty_evidence', {})
        rank = self.entry.get('difficulty_rank')
        if (not workflow.station_reroll_enabled or workflow.resume_active
                or self.entry.get('run') != self.run_number or self.entry.get('origin') != 'fresh'
                or self.entry.get('mode') != '周期演算' or self.entry.get('status') != 'running'
                or self.entry.get('difficulty_verified') is not True
                or type(rank) is not int or not 1 <= rank <= 10 or difficulty.get('verified') is not True
                or difficulty.get('requested_rank') != rank or difficulty.get('displayed_rank_after') != rank
                or type(self.hwnd) is not int or self.hwnd <= 0
                or game_week(datetime.fromtimestamp(self.entry['started_at'], CHINA)) != self.week
                or any(action.get('run') == self.run_number and action.get('intent') in (REQUEST, CONFIRM)
                       for action in workflow.report['actions'])):
            raise AutomationError('选站重抽需要本周已核实的新开周期局，每局至多尝试一次。')
        self.directory = Path(self.context.report.run_dir).resolve(strict=True)
        self.ledger = self.directory / LEDGER
        journal = self._journal()
        self.start = start_source(journal, self.entry, self.directory)
        if journal['actions'][self.start['action_index']]['intent'] != 'periodic_start':
            raise AutomationError('选站重抽缺少本次周期启动提交。')
        self.deadline = self._active_time() + 15
        self.request = None
        self.confirm = None
        self.pending = None
        self.dispatched = False
        self._check_capture(scene)

    def _active_time(self):
        return time.monotonic() - self.workflow._inactive()

    def _journal(self):
        from .du_archive_store import read

        journal = read(self.ledger)
        if (journal.get('session_id') != self.session_id or journal.get('current_run') != self.run_number
                or not journal.get('run_results') or journal['run_results'][-1] != self.entry):
            raise AutomationError('选站重抽的原周期运行账本已改变。')
        return journal

    def _check_capture(self, scene, *, check_account=True):
        from .currency_wars_identity import account_key, checked_account_key
        from .currency_wars_points import game_week, local_now

        context = self.context
        if (self.window is not context.window or self.window.hwnd != self.hwnd
                or self.geometry is None or scene.geometry != self.geometry
                or type(self.epoch) is not int or self.epoch < 0 or scene is not context.last_scene
                or context.scene_epoch != self.epoch or context.runner.input_epoch != self.epoch
                or not 0 <= time.monotonic() - scene.captured_at <= 8):
            raise InputInterrupted('选站重抽的当前窗口、画面或输入代次已改变。')
        if self._active_time() >= self.deadline or game_week(local_now()) != self.week:
            raise AutomationError('选站重抽观察已到期或已跨周，原意图保留。')
        self.workflow._weekly_boundary()
        if check_account:
            if account_key(scene, .65) != self.account or checked_account_key(scene, self.confidence) != self.account:
                raise AutomationError('选站重抽的当前账号已改变。')

    def _pair(self, observe, *, after=0, first=None):
        from .currency_wars_identity import AccountNotObserved

        context = self.context
        prior = first
        for _ in range(16):
            context.sleep(.28)
            try:
                scene = context.snapshot()
            except EmptyCapture:
                prior = None
                continue
            try:
                self._check_capture(scene)
            except AccountNotObserved:
                result = None
            else:
                result = observe(scene)
            if result is None or scene.captured_at <= after:
                prior = None
                continue
            occlusions = context.capture_occlusion_count
            if (prior and prior[0] is not scene and prior[0].captured_at < scene.captured_at
                    and prior[1] == result and prior[2] == occlusions):
                return prior[0], scene, result
            prior = (scene, result, occlusions)
        raise AutomationError('选站重抽未得到连续清晰的双帧反馈，原意图待核对。')

    def _save_pair(self, label, first, last):
        from .currency_wars_initial import evidence_ref

        sources = []
        for number, scene in enumerate((first, last), 1):
            path = self.context.evidence(scene, f'du_station_reroll_{label}_{number}')
            sources.append(evidence_ref(scene, path, self.directory))
        if sources[0]['path'] == sources[1]['path']:
            raise AutomationError('选站重抽缺少两份独立的原图。')
        return sources

    def _station_facts(self, scene):
        result = station_round(scene, self.confidence)
        return (result.count, result.names) if result is not None else None

    def _send(self, intent, pair, target):
        from .storage import file_revision

        first, scene, facts = pair
        refs = self._save_pair(intent, first, scene)
        self._check_capture(scene)
        detail = dict(game_week=self.week, input_epoch=self.epoch, run_id=self.entry['run_id'],
                      source_frames=refs, source_times=[first.captured_at, scene.captured_at])
        if intent == CONFIRM:
            detail.update(request_index=self.request['index'], station_count=self.request['station_count'],
                          station_cards=self.request['station_cards'].copy())
        else:
            detail.update(station_count=facts[0], station_cards=list(facts[1]))
        record = self.workflow._record_click(scene, target, intent, **detail)
        revision = file_revision(self.ledger)
        self.pending = record
        self.dispatched = False
        try:
            self.context.differential_universe_station_reroll_click(scene, target, self)
            if not self.dispatched:
                raise AutomationError('选站重抽没有进入原生提交检查。')
        except (AutomationError, OSError):
            record.update(status='unknown' if self.dispatched else 'not_sent', feedback_status='unverified')
            self._persist_status(revision)
            raise
        finally:
            self.pending = None
        record.update(status='sent', feedback_status='unverified')
        self._persist_status(revision)
        return record

    def _persist_status(self, revision):
        from .storage import file_revision

        def unchanged():
            if file_revision(self.ledger) != revision:
                raise AutomationError('选站重抽原账本已有外部更改，保留原记录。')

        self.workflow._persist_ledger(before_replace=unchanged)

    def dispatch(self, scene, target):
        from .currency_wars_initial import require_evidence_pixels, source_file_ref
        from .du_archive_store import start_source
        from .policy import replenishment_dialog
        from .storage import hold_read_sources

        context, record = self.context, self.pending
        if record is None or record['status'] != 'requested' or self.dispatched:
            raise AutomationError('缺少本次选站重抽的单次待提交意图。')
        self._check_capture(scene)
        intent = record['intent']
        sources = record['source_frames'].copy()
        if intent == CONFIRM:
            if self.request is None or self.request['status'] != 'sent':
                raise AutomationError('选站重抽确认缺少本次已发送的请求。')
            sources.extend(self.request['source_frames'])
        image, tokens, fields = scene.image, tuple(scene.tokens), scene.field_reads.copy()
        stamp, occlusions = scene.captured_at, context.capture_occlusion_count
        proposed = deepcopy(record)

        with ExitStack() as held:
            def before_send():
                context.checkpoint()
                self._check_capture(scene)
                held.enter_context(hold_read_sources((self.ledger,
                    *(ref['path'] for ref in (*self.start['images'], *sources)))))
                journal = self._journal()
                if (journal['actions'][-1] != record
                        or start_source(journal, self.entry, self.directory) != self.start
                        or any(source_file_ref(ref['path'], self.directory) != ref for ref in sources)
                        or intent == CONFIRM and journal['actions'][-2] != self.request):
                    raise AutomationError('选站重抽已落盘的意图或原始画面已改变。')
                if image.flags.writeable:
                    image.setflags(write=False)
                    held.callback(image.setflags, write=True)
                require_evidence_pixels(scene, record['source_frames'][-1])
                if intent == REQUEST:
                    current = station_round(scene, self.confidence)
                    verified = (current is not None and current.target == target and current.count > 0
                                and (current.count, list(current.names)) == (record['station_count'], record['station_cards'])
                                and all(not self.workflow.station_preferences.allowed(name) for name in current.names))
                else:
                    verified = retention_confirmation(scene, self.confidence) == target
                if not verified or replenishment_dialog(scene):
                    raise AutomationError('选站重抽的当前卡片、次数或专用确认未核实。')

            def before_submit():
                self._check_capture(scene)
                self.window.guard(self.geometry)
                if self.window.emergency_pressed() or context.runner.stop_requested:
                    raise Stopped('选站重抽已停止，未发送当前输入。')
                self._check_capture(scene, check_account=False)
                if (self.pending is not record or proposed != record or scene.image is not image or image.flags.writeable
                        or tuple(scene.tokens) != tokens or scene.captured_at != stamp
                        or scene.field_reads != fields
                        or context.capture_occlusion_count != occlusions):
                    raise InputInterrupted('选站重抽的当前证据已改变，未发送输入。')
                self.dispatched = True

            self.window.click(*target.center, self.geometry, before_send=before_send, before_submit=before_submit)

    def run(self, scene):
        context = self.context
        observed = self._station_facts(scene)
        if (observed is None or observed[0] <= 0
                or any(self.workflow.station_preferences.allowed(name) for name in observed[1])):
            raise AutomationError('选站重抽缺少完整三张禁用卡、未选中页面或可用次数。')

        def original(current):
            facts = self._station_facts(current)
            return facts if facts == observed else None

        def prompt(current):
            return PROMPT_BODY if retention_confirmation(current, self.confidence) is not None else None

        def changed(current):
            facts = self._station_facts(current)
            return facts if facts is not None and facts[0] == observed[0]-1 and Counter(facts[1]) != Counter(observed[1]) else None

        before = self._pair(original, first=(scene, observed, context.capture_occlusion_count))
        target = station_round(before[1], self.confidence).target
        self.deadline = self._active_time() + 15
        try:
            self.request = self._send(REQUEST, before, target)
            modal = self._pair(prompt, after=before[1].captured_at)
            self.confirm = self._send(CONFIRM, modal, retention_confirmation(modal[1], self.confidence))
            after = self._pair(changed, after=modal[1].captured_at)
            self._publish_receipt(after)
            return after[1], self.workflow._observe(after[1], 'station_reroll_verified')
        except InputInterrupted as error:
            raise AutomationError('选站重抽已中断，保留原意图和画面，未重发。') from error

    def _publish_receipt(self, pair):
        from .currency_wars_initial import require_evidence_pixels, source_file_ref
        from .storage import file_revision, hold_read_sources

        first, scene, facts = pair
        feedback = self._save_pair('feedback', first, scene)
        sources = [*self.start['images'], *self.request['source_frames'], *self.confirm['source_frames'], *feedback]
        image, tokens, fields = scene.image, tuple(scene.tokens), scene.field_reads.copy()
        stamp, occlusions = scene.captured_at, self.context.capture_occlusion_count
        with ExitStack() as held:
            held.enter_context(hold_read_sources(ref['path'] for ref in sources))
            if image.flags.writeable:
                image.setflags(write=False)
                held.callback(image.setflags, write=True)
            revision = file_revision(self.ledger)
            if (self._journal()['actions'][-2:] != [self.request, self.confirm]
                    or any(source_file_ref(ref['path'], self.directory) != ref for ref in sources)):
                raise AutomationError('选站重抽的反馈原图或已发送记录改变，保留待核对。')
            require_evidence_pixels(scene, feedback[-1])

            def before_replace():
                if file_revision(self.ledger) != revision:
                    raise AutomationError('选站重抽原账本已有外部更改，保留原记录。')
                self._check_capture(scene)
                self.window.guard(self.geometry)
                if self.window.emergency_pressed() or self.context.runner.stop_requested:
                    raise Stopped('选站重抽在反馈发布前停止，保留待核对。')
                self._check_capture(scene, check_account=False)
                if (scene.image is not image or image.flags.writeable or tuple(scene.tokens) != tokens
                        or scene.field_reads != fields or scene.captured_at != stamp
                        or self.context.capture_occlusion_count != occlusions):
                    raise InputInterrupted('选站重抽的反馈证据已改变，保留待核对。')

            previous = self.confirm.copy()
            self.confirm.update(feedback_status='verified', feedback_frames=feedback,
                                feedback_times=[first.captured_at, scene.captured_at],
                                station_count_after=facts[0], station_cards_after=list(facts[1]))
            self.request['feedback_status'] = 'verified'
            try:
                self.workflow._persist_ledger(before_replace=before_replace)
            except (AutomationError, OSError):
                self.confirm.clear()
                self.confirm.update(previous)
                self.request['feedback_status'] = 'unverified'
                raise
