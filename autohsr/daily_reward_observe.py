"""One-shot phone navigation and local calibration of the achievements page."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

import numpy as np

from .build_target_read import _has_split_label
from .currency_wars_identity import AccountNotObserved, checked_account_key
from .currency_wars_prepare import trusted
from .models import FULL, AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, TaskResult, Token, normalize
from .storage import hold_read_sources
from .team_calibration_pages import _grid_label, calibration_overlay
from .workflows import DailyWorkflow, TITLE


OPERATION = 'daily_reward_observe'
SAFE_NEXT = '请核对本次成就导航与到页证据；有未核实的输入时先查看当前画面。'
COLLECTION_FLOOR = .65
MAX_AGE = 8
MAX_CAPTURES = 6
MAX_PNG_BYTES = 64 * 1024 * 1024

_LEVEL = (.656, .212, .764, .272)
_ACHIEVEMENTS = (.884, .478, .921, .519)
_SYNTHESIS = (.816, .478, .852, .519)
_ASSIGNMENTS = (.884, .357, .921, .398)
_FRIENDS = (.815, .357, .852, .398)
_BLOCKING = ('提示', '温馨提示', '确认', '确定', '取消', '知道了', '获得物品', '兑换码', '漫游签证',
             '切换账号', '退出登录', '列车补给', '新消息通知', '点击空白处关闭', '前往成就',
             '支付', '付款', '购买', '续订', '续购', '重新连接', '加载中')


def initial_record():
    return dict(schema=1, mode='achievements', entry_input='not_sent', destination_status='unknown',
                page_verified=False, before_frames=[], after_frames=[])


def _blocked(scene):
    return (calibration_overlay(scene) or scene.has(_BLOCKING, exact=True)
            or _has_split_label(scene, _BLOCKING, FULL))


def phone_achievement_target(scene, confidence):
    clean = trusted(scene, COLLECTION_FLOOR)
    if (not DailyWorkflow._phone(clean) or _blocked(clean)
            or clean.has(('成就', '设置', '活动', '邮箱', '星际和平指南'), TITLE, exact=True)):
        return None
    minimum = max(.85, confidence)
    levels = [token for token in clean.tokens if token.within(_LEVEL)
              and re.fullmatch(r'开拓等级(?:[0-9]{1,3})?', normalize(token.text))]
    entries = [token for token in clean.tokens if normalize(token.text) == '成就']
    if len(levels) != 1 or levels[0].score < minimum or len(entries) != 1:
        return None
    achievement = _grid_label(clean.tokens, '成就', _ACHIEVEMENTS, minimum)
    synthesis = _grid_label(clean.tokens, '合成', _SYNTHESIS, minimum)
    assignment = _grid_label(clean.tokens, '委托', _ASSIGNMENTS, minimum)
    friend = _grid_label(clean.tokens, '好友', _FRIENDS, minimum)
    if not all((achievement, synthesis, assignment, friend)):
        return None
    ax, ay = achievement.center
    sx, sy = synthesis.center
    bx, by = assignment.center
    fx, fy = friend.center
    if (abs(ay - sy) <= .010 and abs(by - fy) <= .010 and abs(ax - bx) <= .010
            and abs(sx - fx) <= .010 and .053 <= ax - sx <= .083 and .105 <= ay - by <= .136):
        return achievement
    return None


def _destination_hint(scene, confidence):
    clean = trusted(scene, COLLECTION_FLOOR)
    if phone_achievement_target(scene, confidence) is not None:
        return 'phone_still_visible'
    titles = [token for token in clean.tokens if normalize(token.text) == '成就']
    if (not _blocked(clean) and len(titles) == 1 and titles[0].within(TITLE)
            and titles[0].score >= max(.85, confidence)):
        # A title alone is useful evidence for calibration of the full page.
        return 'achievement_title_only'
    return 'unknown'


def _pixels(scene):
    return sha256(scene.image.tobytes()).hexdigest()


@dataclass(frozen=True)
class _Frame:
    scene: Scene
    sequence: int
    captured_at: float
    pixel_sha256: str
    target: Token | None
    hint: str


class DailyRewardObserver:
    def __init__(self, context):
        self.c = context
        self.window = context.window
        self.epoch = context.runner.input_epoch
        self.confidence = context.settings.ocr_confidence
        self.window_key = None
        self.geometry = None
        self.account = None
        self.directory = Path(context.report.run_dir).resolve()
        self.intent = self.directory / 'daily-reward-entry-intent.json'
        self.intent_bytes = None
        self.before = ()
        self.submission = None
        self.record = initial_record()

    def guard_window(self):
        if self.c.runner.stop_requested:
            raise Stopped('成就入口校准已停止。')
        if self.c.runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch:
            raise InputInterrupted('成就入口校准的输入代次已改变。')
        if (self.c.window is not self.window or self.window_key is None
                or self.window.current_window_key() != self.window_key):
            raise AutomationError('成就入口校准的窗口来源已改变。')
        self.window.guard(self.geometry)

    def _current(self, scene, sequence):
        self.guard_window()
        image = scene.image
        if (self.c.report.operation != OPERATION or self.c.daily_reward_reader is not self
                or self.c.report.daily_reward_observe is not self.record or self.c.last_scene is not scene
                or self.c.capture_sequence != sequence or scene.geometry != self.geometry
                or not 0 <= time.monotonic() - scene.captured_at <= MAX_AGE
                or not isinstance(image, np.ndarray) or image.dtype != np.uint8
                or image.shape != (self.geometry.height, self.geometry.width, 3)):
            raise AutomationError('成就入口校准缺少同一窗口的新鲜画面。')

    def _account(self, scene):
        key = checked_account_key(scene, self.confidence)
        if self.account is not None and key != self.account:
            raise AutomationError('成就入口校准期间当前账号已改变。')
        return key

    def _capture(self, *, before):
        scene = self.c.snapshot()
        if self.geometry is None:
            self.geometry = scene.geometry
        if self.geometry is None:
            raise AutomationError('成就入口校准缺少当前窗口尺寸。')
        sequence = self.c.capture_sequence
        self._current(scene, sequence)
        self.account = self._account(scene)
        target = phone_achievement_target(scene, self.confidence) if before else None
        hint = 'phone' if before else _destination_hint(scene, self.confidence)
        return _Frame(scene, sequence, scene.captured_at, _pixels(scene), target, hint)

    @staticmethod
    def _adjacent(first, second):
        return (second.sequence == first.sequence + 1 and second.scene is not first.scene
                and not np.may_share_memory(first.scene.image, second.scene.image)
                and first.captured_at < second.captured_at
                and 0 <= time.monotonic() - first.captured_at <= MAX_AGE)

    @staticmethod
    def _same_target(first, second):
        return (first.target is not None and second.target is not None
                and all(abs(a - b) <= .006 for a, b in zip(first.target.box, second.target.box)))

    def _pair(self, *, after=None):
        previous, pair = None, ()
        for attempt in range(MAX_CAPTURES):
            if attempt or after is not None:
                self.c.sleep(.30)
            try:
                frame = self._capture(before=after is None)
            except (EmptyCapture, AccountNotObserved):
                previous, pair = None, ()
                continue
            if (after is None and frame.target is None or after is not None and frame.captured_at <= after):
                previous, pair = None, ()
                continue
            if previous is not None and self._adjacent(previous, frame):
                if after is None and self._same_target(previous, frame):
                    return previous, frame
                if after is not None and previous.hint == frame.hint:
                    pair = previous, frame
                    if frame.hint == 'achievement_title_only':
                        return pair
                else:
                    pair = ()
            else:
                pair = ()
            previous = frame
        return pair

    def _path(self, path):
        path = Path(path).absolute()
        if path.parent != self.directory or path.suffix != '.png' or path.resolve(strict=True) != path:
            raise AutomationError('成就入口证据不在本次运行目录。')
        return path

    @staticmethod
    def _digest(path):
        with path.open('rb') as stream:
            raw = stream.read(MAX_PNG_BYTES + 1)
        if len(raw) > MAX_PNG_BYTES or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise AutomationError('成就入口证据的图像格式异常。')
        return sha256(raw).hexdigest()

    def _verify_frame(self, frame):
        scene = frame.scene
        if (scene.geometry != self.geometry or scene.captured_at != frame.captured_at
                or not 0 <= time.monotonic() - frame.captured_at <= MAX_AGE
                or _pixels(scene) != frame.pixel_sha256 or self._account(scene) != self.account
                or frame.target is not None and phone_achievement_target(scene, self.confidence) != frame.target
                or frame.hint != 'phone' and _destination_hint(scene, self.confidence) != frame.hint):
            raise AutomationError('成就入口证据的原画面、账号或控件已变化。')

    def _save_pair(self, frames, phase):
        self._current(frames[-1].scene, frames[-1].sequence)
        rows = []
        for index, frame in enumerate(frames, 1):
            self._verify_frame(frame)
            path, digest = self.c.evidence(frame.scene, f'daily_reward_{phase}_{index}', with_sha256=True)
            path = self._path(path)
            if self._digest(path) != digest:
                raise AutomationError('成就入口的落盘图像已变化。')
            rows.append(dict(screenshot=path.name, sha256=digest, capture_sequence=frame.sequence,
                             captured_at=frame.captured_at, hint=frame.hint,
                             entry_box=list(frame.target.box) if frame.target is not None else None))
        if len({row['screenshot'] for row in rows}) != 2:
            raise AutomationError('成就入口校准需要独立的双帧截图。')
        self._current(frames[-1].scene, frames[-1].sequence)
        return rows

    def _save_intent(self):
        rows = self._save_pair(self.before, 'before')
        raw = json.dumps(dict(schema=1, mode='achievements', intent='open_achievements', sources=rows),
                         ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf8')
        with self.intent.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        self.intent_bytes = raw
        self.record.update(before_frames=rows, intent=self.intent.name)

    def hold_intent(self):
        if self.intent_bytes is None or self.submission is None:
            raise AutomationError('缺少本次成就入口的落盘意图。')
        rows = json.loads(self.intent_bytes)['sources']
        return hold_read_sources([self.intent, *(self._path(self.directory / row['screenshot']) for row in rows)])

    def authorize(self, scene):
        frame = self.submission
        if (self.record['entry_input'] != 'not_sent' or self.intent_bytes is None or len(self.before) != 2
                or frame is None or frame.scene is not scene or not self._adjacent(*self.before)
                or not self._adjacent(self.before[-1], frame) or not self._same_target(self.before[-1], frame)):
            raise AutomationError('成就入口缺少本次一次性意图及连续的当前目标。')
        self._current(scene, frame.sequence)
        with self.intent.open('rb') as stream:
            if stream.read(len(self.intent_bytes) + 1) != self.intent_bytes:
                raise AutomationError('成就入口意图在发送前已变化。')
        for source, row in zip(self.before, json.loads(self.intent_bytes)['sources']):
            self._verify_frame(source)
            if self._digest(self._path(self.directory / row['screenshot'])) != row['sha256']:
                raise AutomationError('成就入口截图在发送前已变化。')
        self._verify_frame(frame)
        self._current(scene, frame.sequence)
        return frame.target

    def run(self):
        if self.c.report.operation != OPERATION or getattr(self.c, 'daily_reward_reader', None) is not None:
            raise AutomationError('成就校准需要独立运行入口。')
        self.c.daily_reward_reader = self
        self.c.report.daily_reward_observe = self.record
        self.window_key = self.window.current_window_key()
        self.guard_window()
        self.before = self._pair()
        if len(self.before) != 2:
            raise AutomationError('未从连续新画面核实当前账号的手机成就入口。')
        self._save_intent()
        self.submission = self._capture(before=True)
        sent_at = self.c.daily_reward_entry_input(self.submission.scene)
        after = self._pair(after=sent_at)
        if after:
            self.record['after_frames'] = self._save_pair(after, 'after')
            self.record['destination_status'] = after[-1].hint
            detail = '成就入口已发送，已保留随后双帧，成就页待核实。'
        else:
            if self.c.last_scene is not None:
                self.record['diagnostic_screenshot'] = self._path(
                    self.c.evidence(self.c.last_scene, 'daily_reward_unverified')).name
            detail = '成就入口已发送，尚未核实同账号的后续双帧。'
        return TaskResult(OPERATION, 'partial', detail)
