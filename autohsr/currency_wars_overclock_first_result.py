"""Bounded observation after this ordinary A0 run has acknowledged 1-1 input."""
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
import json
import os
import time

from .currency_wars import TASK
from .currency_wars_identity import AccountNotObserved, account_key
from .currency_wars_overclock import (
    MAX_FRAME_AGE, MAX_JOURNAL_BYTES, _Evidence, _freeze_scene_pixels, _read_bytes, _require_frozen_scene,
)
from .currency_wars_overclock_first_result_pages import FirstNodeFeedback, read_first_node_feedback
from .currency_wars_state import strict_json
from .models import AutomationError, EmptyCapture, Scene, Stopped, TaskResult
from .storage import file_revision, replace_file


@dataclass(frozen=True, repr=False)
class _Frame:
    scene: Scene
    observation: FirstNodeFeedback
    proof: _Evidence
    image: object
    tokens: tuple
    fields: tuple
    occlusions: int


class _Observation:
    def __init__(self, context, preflight, journal, data, sent):
        self.c = context
        self.preflight = preflight
        self.path = journal
        self.data = data
        self.confidence = context.settings.ocr_confidence
        self.account = preflight.session.data['account_key']
        self.battle_proofs = ()
        if (context._legacy_first_node is not preflight or not preflight.sent or preflight.pending is None
                or preflight.pending[0] != journal or preflight.armed is None
                or journal.resolve(strict=True) != journal
                or data.get('action') != 'start_node' or data.get('origin_node') != '1-1'
                or data.get('action_status') != 'pending'
                or not preflight.armed[0].captured_at < sent <= time.monotonic()):
            raise AutomationError('1-1 缺少本次已返回的出战发送及落盘意图。')
        if data != preflight.pending[1]:
            raise AutomationError('1-1 原出战子账偏离本次唯一待核对意图。')
        self.geometry = preflight.armed[0].geometry
        self.window = context.window
        self.latest = sent
        self.deadline = sent + min(context.settings.battle_timeout, 180)
        self.gap_deadline = sent + 30
        self.saved = _read_bytes(journal, MAX_JOURNAL_BYTES)
        self.revision = file_revision(journal)
        if strict_json(self.saved.decode('utf-8')) != json.loads(json.dumps(data, ensure_ascii=False)):
            raise AutomationError('1-1 的待核对子账与本次记录不一致。')

    def _account(self, scene):
        if account_key(scene, max(.85, self.confidence)) != self.account:
            raise AutomationError('1-1 当前观察与原开局的账号不一致。')

    def _save(self, scene, observation, label):
        image = _freeze_scene_pixels(scene, self.geometry)
        tokens, fields = tuple(scene.tokens), tuple(scene.field_reads.items())
        captured_at, occlusions = scene.captured_at, self.c.capture_occlusion_count
        proof = self.preflight._proof(scene, self.c.evidence(scene, 'currency_first_node_' + label))
        if proof.captured_at != captured_at:
            raise AutomationError('1-1 保存反馈期间的画面时间已改变。')
        return _Frame(scene, observation, replace(proof, state=observation.state),
                      image, tokens, fields, occlusions)

    def _require_frame(self, frame, now):
        scene = frame.scene
        _require_frozen_scene(scene, frame.image, frame.tokens, self.geometry)
        if (scene.captured_at != frame.proof.captured_at
                or not 0 <= now - scene.captured_at <= MAX_FRAME_AGE
                or frame.occlusions != self.c.capture_occlusion_count
                or tuple(scene.field_reads.items()) != frame.fields):
            raise AutomationError('1-1 双帧观察的时间、遮挡或读数来源已改变。')

    def _publish(self, updates, frames=()):
        record = dict(self.data, **updates)
        payload = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(payload) > MAX_JOURNAL_BYTES:
            raise AutomationError('1-1 当前节点回执超过可核实大小。')
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_revision = file_revision(temporary)
        proofs = (*self.battle_proofs, *(frame.proof for frame in frames))

        @contextmanager
        def attempt():
            with ExitStack() as stack:
                _, unchanged = self.preflight._hold_input_sources(stack, *proofs)
                if (file_revision(self.path) != self.revision or _read_bytes(self.path, MAX_JOURNAL_BYTES) != self.saved
                        or file_revision(temporary) != temporary_revision
                        or _read_bytes(temporary, MAX_JOURNAL_BYTES) != payload):
                    raise AutomationError('1-1 原出战子账或待发布回执已改变。')
                if frames:
                    self.preflight._current(frames[-1].scene)
                    for frame in frames:
                        self._require_frame(frame, time.monotonic())
                        self._account(frame.scene)
                        if read_first_node_feedback(frame.scene, self.confidence) != frame.observation:
                            raise AutomationError('1-1 双帧观察的读数已改变。')
                unchanged()
                if (self.c.window is not self.window
                        or self.window.current_window_key() != self.preflight.session.data['window_key']):
                    raise AutomationError('1-1 的出战观察窗口已改变。')
                self.window.guard(self.geometry)
                if self.window.emergency_pressed() or self.c.runner.stop_requested:
                    raise Stopped('1-1 本次出战观察已停止，原回执保留。')
                if self.c.runner.input_epoch != self.preflight.epoch:
                    raise AutomationError('1-1 本次出战的输入代次已改变。')
                if frames:
                    if self.c.scene_epoch != self.preflight.epoch or self.c.last_scene is not frames[-1].scene:
                        raise AutomationError('1-1 本次结果画面已改变。')
                    now = time.monotonic()
                    if now >= min(self.deadline, self.gap_deadline):
                        raise AutomationError('1-1 的双帧回执已超出观察期限。')
                    for frame in frames:
                        self._require_frame(frame, now)
                yield

        replace_file(temporary, self.path, attempt_scope=attempt)
        self.revision = file_revision(self.path)
        self.saved = payload
        self.data.update(updates)

    def _terminal(self, reason, scene=None, status='unknown'):
        update = dict(action_status=status, reason=reason)
        if scene is not None and scene.image is not None:
            update['screenshot'] = str(self.c.evidence(scene, 'currency_first_node_result_unverified'))
        self._publish(update)

    def run(self):
        self._publish(dict(start_dispatched=True, dispatched_at=self.latest))
        pending = None
        while time.monotonic() < min(self.deadline, self.gap_deadline):
            try:
                scene = self.c.snapshot()
                self.preflight._current(scene)
                self._account(scene)
            except (EmptyCapture, AccountNotObserved):
                pending = None
                self.c.sleep(1)
                continue
            if time.monotonic() >= min(self.deadline, self.gap_deadline):
                break
            if scene.geometry != self.geometry:
                raise AutomationError('1-1 出战后的窗口位置或大小已改变。')
            stamp = scene.captured_at
            if stamp <= self.latest:
                pending = None
                self.c.sleep(1)
                continue
            self.latest = stamp
            observed = read_first_node_feedback(scene, self.confidence)
            state = observed.state
            if (state in ('conflicting', 'unexpected') or state == 'preparation' and self.battle_proofs
                    or state in ('battle', 'victory') and observed.node != '1-1'):
                return self._terminal('1-1 出战后出现冲突、异节点或未校准的结果页。', scene)
            if state not in ('battle', 'victory'):
                pending = None
                self.c.sleep(1)
                continue
            if state == 'battle':
                self.gap_deadline = stamp + 30
                if self.battle_proofs:
                    pending = None
                    self.c.sleep(2)
                    continue
            if (pending is None or pending.observation.state != state or pending.scene is scene
                    or pending.scene.image is scene.image or pending.occlusions != self.c.capture_occlusion_count
                    or time.monotonic() - pending.proof.captured_at > MAX_FRAME_AGE
                    or state == 'victory' and pending.observation.hp != observed.hp):
                pending = self._save(scene, observed, state + '_first')
                self.c.sleep(1)
                continue
            last = self._save(scene, observed, state + '_second')
            pair = pending, last
            feedback = [asdict(frame.proof) for frame in pair]
            if state == 'battle':
                auto = observed.auto_state if observed.auto_state == pending.observation.auto_state else 'unknown'
                self._publish(dict(battle_observed=True, battle_feedback=feedback, auto_state=auto,
                                   action_status='battle_observed', battle=last.proof.screenshot,
                                   screenshot=last.proof.screenshot), pair)
                self.battle_proofs = tuple(frame.proof for frame in pair)
                pending = None
                self.c.sleep(1)
                continue
            verified = bool(self.battle_proofs)
            return self._publish(dict(result_observed=True, result_feedback=feedback, node_verified=verified,
                                      action_status='verified' if verified else 'unknown',
                                      verification='current_1_1_battle_and_result' if verified else 'battle_unverified',
                                      reason='' if verified else '已观察到 1-1 胜利页，稳定战斗来源待核对。',
                                      remaining_hp=observed.hp, after=last.proof.screenshot,
                                      screenshot=last.proof.screenshot), pair)
        self._terminal('1-1 在限定时间内未取得本节点的完整双帧结果。', status='timeout')


def observe_first_node_result(context, preflight, journal, data):
    _Observation(context, preflight, journal, data, time.monotonic()).run()
    context.runner.emit(dict(type=TASK, data=data))
    detail = ('已核实本次 1-1 的战斗与胜利结果，停在结算页。' if data['node_verified']
              else data['reason'])
    context.log(detail)
    return TaskResult(TASK, 'partial', detail)
