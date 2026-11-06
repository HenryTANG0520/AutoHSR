"""Offline evidence protocol for one bulk achievement claim and one confirmation."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from uuid import uuid4

import numpy as np

from .achievement_pages import (
    achievement_bulk_claim_target, achievement_bulk_slot_empty, achievement_jade_overlay_amount,
    achievement_overview_signature, achievement_receipt_fields,
)
from .currency_wars_prepare import trusted
from .free_rewards import reward_overlay
from .models import Scene, normalize
from .storage import hold_read_sources
from .team_calibration_pages import calibration_overlay


MAX_AGE = 8
_FILES = {'claim': 'achievement-bulk-intent.json', 'confirm': 'achievement-bulk-confirm-intent.json'}
_SEND_FILES = {name: file.replace('-intent.json', '-send.json') for name, file in _FILES.items()}


@dataclass(frozen=True)
class ClaimScope:
    """Already verified by the caller's native capture boundary."""
    account_key: str
    window: int
    input_epoch: int
    client_version: str


def _valid_scope(scope):
    return (type(scope.account_key) is str and re.fullmatch(r'[0-9a-f]{64}', scope.account_key) is not None
            and type(scope.window) is int and scope.window > 0
            and type(scope.input_epoch) is int and scope.input_epoch >= 0 and scope.client_version == '4.6.0')


@dataclass(frozen=True)
class ClaimFrame:
    scope: ClaimScope
    sequence: int
    scene: Scene
    # Only set after checking the original button region and marked cards are fully visible and cleared.
    controls_cleared: bool = False
    # Separate visual proof of the currency icon immediately to the left of the wallet value.
    jade_icon_verified: bool = False


@dataclass(frozen=True)
class BulkClaimResult:
    bulk_input: str = 'not_sent'
    confirm_input: str = 'not_sent'
    receipt_total: int | None = None
    overlay_quantity: int | None = None
    overview_return_verified: bool = False
    overview_controls_cleared: bool = False
    jade_balance_before: int | None = None
    jade_balance_after: int | None = None
    jade_balance_delta: int | None = None
    jade_attributed: int | None = None
    stopped: bool = False


@dataclass(frozen=True)
class _Intent:
    action: str
    digest: str
    raw: bytes
    prepared_at: float
    current: ClaimFrame
    sources: tuple[tuple[ClaimFrame, dict], ...]
    target_box: tuple[float, float, float, float]


def _capture_source(frame):
    pixels = frame.scene.image
    if not isinstance(pixels, np.ndarray) or pixels.ndim != 3 or pixels.size == 0:
        raise ValueError('成就领奖缺少原始客户区图像。')
    tokens = [(t.text, t.score, t.box) for t in trusted(frame.scene, .65).tokens]
    ocr = json.dumps(tokens, ensure_ascii=False, allow_nan=False).encode('utf-8')
    return dict(sequence=frame.sequence, captured_at=frame.scene.captured_at, size=list(pixels.shape),
                pixel_sha256=sha256(pixels.tobytes()).hexdigest(), ocr_sha256=sha256(ocr).hexdigest())


def _write_once(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read_jade_balance(frame):
    visible = trusted(frame.scene, .65)
    if reward_overlay(visible) or calibration_overlay(visible):
        return None
    scene = trusted(visible, .85)
    if (frame.jade_icon_verified is not True
            or not scene.has('跃迁', (.04, .02, .10, .08), exact=True)
            or not scene.has('角色活动跃迁', (.15, .12, .30, .21), exact=True)):
        return None
    amounts = [normalize(t.text) for t in scene.tokens if t.within((.86, .04, .92, .08))]
    banners = [normalize(t.text) for t in scene.tokens if t.within((.04, .065, .15, .10))]
    if len(amounts) != 1 or len(banners) != 1 or not re.fullmatch(r'[0-9]{1,9}', amounts[0]):
        return None
    return banners[0], int(amounts[0])


class AchievementBulkReplay:
    """Record an offline attempt. External send receipts are observations, never requests."""

    def __init__(self, directory, scope: ClaimScope):
        self.directory = Path(directory).resolve(strict=True)
        if not self.directory.is_dir() or not _valid_scope(scope):
            raise ValueError('成就领奖缺少已核实的 4.6.0 窗口、账号或输入代次。')
        if any(os.path.lexists(self.directory / name) for name in (*_FILES.values(), *_SEND_FILES.values())):
            raise FileExistsError('已有成就领奖意图，原件保留并停止重放。')
        self.scope = scope
        self.result = BulkClaimResult()
        self._phase = 'start'
        self._last_at = 0
        self._last_sequence = 0
        self._overview = None
        self._wallet_view = None
        self._pending = None
        self._claim_intent = None
        self._claim_send = None
        self._journal_digests = {}

    def journal_digests(self):
        return dict(self._journal_digests)

    def _check(self, phase):
        if self._phase != phase:
            raise ValueError('成就领奖阶段不符或本次已停止。')

    def _pair(self, frames):
        first, last = frames
        self._require_scope(first, last)
        if (type(first.sequence) is not int or type(last.sequence) is not int
                or not self._last_sequence < first.sequence == last.sequence - 1
                or first.scene is last.scene
                or first.scene.geometry != last.scene.geometry
                or np.may_share_memory(first.scene.image, last.scene.image)
                or not self._last_at < first.scene.captured_at < last.scene.captured_at
                or not math.isfinite(last.scene.captured_at)
                or last.scene.captured_at - first.scene.captured_at > MAX_AGE):
            raise ValueError('成就领奖需要同窗口、同账号、同代次的两张连续新帧。')
        if self._phase not in ('start', 'returned') and first.scene.captured_at - self._last_at > MAX_AGE:
            self.stop()
            raise ValueError('成就领奖反馈超出本阶段时限，保留已记录结果。')
        return first, last

    def _require_scope(self, *frames):
        if any(frame.scope != self.scope for frame in frames):
            self.stop()
            raise ValueError('成就领奖的窗口、账号或输入代次发生变化。')

    def stop(self):
        pending, self._pending = self._pending, None
        observed = {}
        if pending is not None:
            field = 'bulk_input' if pending.action == 'claim' else 'confirm_input'
            observed[field] = 'unknown'
        self.result = replace(self.result, stopped=True, **observed)
        self._phase = 'stopped'

    def _advance(self, phase, frame, **observed):
        self._phase = phase
        self._last_at = frame.scene.captured_at
        self._last_sequence = frame.sequence
        self.result = replace(self.result, **observed)

    def observe_balance_before(self, frames):
        self._check('start')
        if self._wallet_view is not None:
            raise ValueError('本次领取的星琼基线已冻结。')
        first, last = self._pair(frames)
        read = _read_jade_balance(first)
        if read is None or read != _read_jade_balance(last):
            return False
        self._wallet_view, balance = read
        self._advance('start', last, jade_balance_before=balance)
        return True

    def reserve_claim(self, frames, current, now):
        self._check('start')
        first, last = self._pair(frames)
        self._require_scope(current)
        signature = achievement_overview_signature(first.scene)
        if signature is None or any(achievement_overview_signature(frame.scene) != signature
                                    for frame in (last, current)):
            raise ValueError('领取前缺少一致的成就总览。')
        digest = self._reserve('claim', first, last, current, now, achievement_bulk_claim_target)
        self._overview = signature
        return digest

    def observe_receipt(self, frames):
        self._check('claimed')
        first, last = self._pair(frames)
        a, b = (achievement_receipt_fields(frame.scene) for frame in (first, last))
        if a is None or b is None or a[0] != b[0]:
            return False
        self._advance('receipt', last, receipt_total=a[0])
        return True

    def reserve_confirmation(self, frames, current, now):
        self._check('receipt')
        first, last = self._pair(frames)
        self._require_scope(current)
        self._verify_claim_intent()

        def target(scene):
            fields = achievement_receipt_fields(scene, established_total=self.result.receipt_total)
            return fields[1] if fields is not None and fields[0] == self.result.receipt_total else None

        return self._reserve('confirm', first, last, current, now, target)

    def _reserve(self, action, first, last, current, now, read_target):
        if (type(current.sequence) is not int
                or current.sequence != last.sequence + 1 or current.scene is last.scene
                or current.scene.geometry != last.scene.geometry
                or np.may_share_memory(current.scene.image, last.scene.image)
                or np.may_share_memory(current.scene.image, first.scene.image)
                or not last.scene.captured_at < current.scene.captured_at <= now
                or not math.isfinite(now) or now - first.scene.captured_at > MAX_AGE):
            raise ValueError('成就领奖的第三张发送前画面已失效。')
        targets = tuple(read_target(frame.scene) for frame in (first, last, current))
        target = targets[-1]
        if target is None or any(other is None or any(abs(a - b) > .006 for a, b in zip(other.box, target.box))
                                 for other in targets[:2]):
            raise ValueError('成就领奖缺少连续一致的唯一控件。')
        sources = tuple((frame, _capture_source(frame)) for frame in (first, last, current))
        raw = json.dumps(dict(schema=1, operation='achievement_bulk_claim', action=action, nonce=uuid4().hex,
                              scope=asdict(self.scope), frames=[source for _, source in sources], target_box=target.box,
                              previous_claim=self._claim_intent,
                              previous_send=sha256(self._claim_send).hexdigest() if self._claim_send else None,
                              receipt_total=self.result.receipt_total,
                              prepared_at=now), sort_keys=True, allow_nan=False).encode('utf-8')
        try:
            _write_once(self.directory / _FILES[action], raw)
        except OSError:
            self.stop()
            raise
        digest = sha256(raw).hexdigest()
        self._journal_digests[_FILES[action]] = digest
        self._pending = _Intent(action, digest, raw, now, current, sources, target.box)
        self._phase = f'{action}_reserved'
        return digest

    def _verify_claim_intent(self):
        try:
            with (self.directory / _FILES['claim']).open('rb') as stream:
                original = stream.read(8193)
            with (self.directory / _SEND_FILES['claim']).open('rb') as stream:
                sent = stream.read(len(self._claim_send) + 1)
            if len(original) > 8192 or sha256(original).hexdigest() != self._claim_intent or sent != self._claim_send:
                raise ValueError('原一键领取意图或发送记录已变化。')
        except (OSError, ValueError):
            self.stop()
            raise

    def record_send(self, intent_digest, outcome, sent_at, *, scope):
        """Accept a recorded send result bound to the exclusively reserved offline intent."""
        intent = self._pending
        if intent is None or intent.digest != intent_digest:
            raise ValueError('成就领奖发送记录不属于本次排他意图。')
        if (scope != self.scope or outcome not in ('sent', 'not_sent', 'unknown')
                or not math.isfinite(sent_at)
                or not intent.prepared_at <= sent_at <= intent.current.scene.captured_at + MAX_AGE):
            self.stop()
            raise ValueError('成就领奖发送记录不属于本次新鲜意图。')
        try:
            with self.hold_submission(intent.action):
                self._verify_pending(intent)
                raw = json.dumps(dict(intent=intent.digest, outcome=outcome, sent_at=sent_at),
                                 sort_keys=True, allow_nan=False).encode('utf-8')
                _write_once(self.directory / _SEND_FILES[intent.action], raw)
        except (OSError, ValueError):
            self.stop()
            raise
        self._journal_digests[_SEND_FILES[intent.action]] = sha256(raw).hexdigest()
        self._pending = None
        field = 'bulk_input' if intent.action == 'claim' else 'confirm_input'
        if outcome != 'sent':
            self._advance('stopped', intent.current, **{field: outcome, 'stopped': True})
            return
        if intent.action == 'claim':
            self._claim_intent = intent.digest
            self._claim_send = raw
        self._advance('claimed' if intent.action == 'claim' else 'confirmed', intent.current, **{field: outcome})
        self._last_at = sent_at

    @contextmanager
    def hold_submission(self, action, evidence=()):
        if self._pending is None or self._pending.action != action:
            raise ValueError('成就领奖缺少本次动作的排他意图。')
        paths = [self.directory / _FILES[action], *evidence]
        if action == 'confirm':
            paths.extend(self.directory / name for name in (_FILES['claim'], _SEND_FILES['claim']))
        with hold_read_sources(paths):
            yield

    def _verify_pending(self, intent):
        if intent.action == 'confirm':
            self._verify_claim_intent()
        with (self.directory / _FILES[intent.action]).open('rb') as stream:
            if stream.read(len(intent.raw) + 1) != intent.raw:
                raise ValueError('成就领奖排他意图已变化。')
        if any(_capture_source(frame) != saved for frame, saved in intent.sources):
            raise ValueError('成就领奖发送证据已变化。')

    def authorize_submission(self, action, current, now):
        """Recheck a pending intent inside the caller's native evidence lock."""
        intent = self._pending
        if (intent is None or intent.action != action or intent.current is not current
                or current.scope != self.scope or not math.isfinite(now)
                or not intent.prepared_at <= now <= intent.sources[0][1]['captured_at'] + MAX_AGE):
            raise ValueError('成就领奖缺少当前发送前画面和未提交意图。')
        self._verify_pending(intent)
        if action == 'claim':
            target = achievement_bulk_claim_target(current.scene)
        else:
            fields = achievement_receipt_fields(current.scene, established_total=self.result.receipt_total)
            target = fields[1] if fields is not None and fields[0] == self.result.receipt_total else None
        if target is None or target.box != intent.target_box:
            raise ValueError('成就领奖的唯一控件已改变。')
        return target

    def observe_overlay(self, frames):
        self._check('confirmed')
        first, last = self._pair(frames)
        amounts = tuple(achievement_jade_overlay_amount(frame.scene) for frame in (first, last))
        if amounts != (self.result.receipt_total, self.result.receipt_total):
            return False
        self._advance('overlay', last, overlay_quantity=amounts[0])
        return True

    def observe_return(self, frames):
        self._check('overlay')
        first, last = self._pair(frames)
        if any(achievement_overview_signature(frame.scene) != self._overview for frame in (first, last)):
            return False
        cleared = all(frame.controls_cleared is True and achievement_bulk_slot_empty(frame.scene)
                      for frame in (first, last))
        self._advance('returned', last, overview_return_verified=True, overview_controls_cleared=cleared)
        return True

    def observe_balance_after(self, frames, *, isolated_wallet_interval=False):
        self._check('returned')
        first, last = self._pair(frames)
        read = _read_jade_balance(first)
        if read is None or read != _read_jade_balance(last):
            return False
        view, after = read
        before = self.result.jade_balance_before
        delta = after - before if before is not None and view == self._wallet_view else None
        attributed = (delta if isolated_wallet_interval is True and self.result.overview_controls_cleared
                      and first.scene.captured_at - self._last_at <= MAX_AGE
                      and delta == self.result.overlay_quantity else None)
        self._advance('closed', last, jade_balance_after=after, jade_balance_delta=delta, jade_attributed=attributed)
        return True
