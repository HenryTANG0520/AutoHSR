"""Bounded phone navigation and local calibration of daily reward pages."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

import numpy as np

from .achievement_pages import achievement_overview
from .daily_visa_pages import visa_overview
from .build_target_read import _has_split_label
from .currency_wars_identity import AccountNotObserved, checked_account_key
from .currency_wars_prepare import trusted
from .models import FULL, AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, TaskResult, Token, normalize
from .redemption_pages import MORE_MENU, phone_more_target, redemption_entry
from .storage import hold_read_sources, replace_file
from .team_calibration_pages import _grid_label, calibration_overlay
from .workflows import DailyWorkflow, TITLE


OPERATION = 'daily_reward_observe'
MODES = ('achievements', 'support')
SAFE_NEXT = '请核对本次成就导航与到页证据；有未核实的输入时先查看当前画面。'
SUPPORT_SAFE_NEXT = '请核对本次更多与漫游签证的分步回执；有未核实的输入时先查看当前画面。'
COLLECTION_FLOOR = .65
MAX_AGE = 8
MAX_CAPTURES = 6
MAX_PNG_BYTES = 64 * 1024 * 1024

_LEVEL = (.656, .212, .764, .272)
_ACHIEVEMENTS = (.884, .478, .921, .519)
_SYNTHESIS = (.816, .478, .852, .519)
_ASSIGNMENTS = (.884, .357, .921, .398)
_FRIENDS = (.815, .357, .852, .398)
_MENU_LABELS = ('漫游签证', '兑换码')
_BLOCKING = ('提示', '温馨提示', '确认', '确定', '取消', '知道了', '获得物品',
             '切换账号', '退出登录', '列车补给', '新消息通知', '点击空白处关闭', '前往成就',
             '支付', '付款', '购买', '续订', '续购', '重新连接', '加载中')


def _step_record():
    return dict(entry_input='not_sent', destination_status='unknown', before_frames=[], after_frames=[])


def initial_record(mode='achievements'):
    common = dict(schema=1, mode=mode, page_verified=False)
    if mode == 'support':
        return dict(**common, entry_input='not_sent', destination_status='unknown',
                    steps=dict(open_more=_step_record(), open_support=_step_record()))
    return dict(**common, **_step_record())


def _blocked(scene, *, allow_menu=False):
    labels = _BLOCKING if allow_menu else _BLOCKING + _MENU_LABELS
    return (calibration_overlay(scene) or scene.has(labels, exact=True)
            or _has_split_label(scene, labels, FULL))


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


def _support_more_target(scene, confidence):
    clean = trusted(scene, COLLECTION_FLOOR)
    if (_blocked(clean) or clean.has(('成就', '设置', '活动', '邮箱', '星际和平指南'), TITLE, exact=True)
            or clean.has(('兑换成功', '请输入兑换码', '请在此输入兑换码'), exact=True)):
        return None
    return phone_more_target(scene, confidence)


def _support_visa_target(scene, confidence):
    clean = trusted(scene, COLLECTION_FLOOR)
    if (_blocked(clean, allow_menu=True) or _has_split_label(clean, _MENU_LABELS, FULL)
            or clean.has((*_MENU_LABELS, '成就', '设置', '活动', '邮箱'), TITLE, exact=True)
            or clean.has(('兑换成功', '请输入兑换码', '请在此输入兑换码'), exact=True)):
        return None
    visas = [token for token in clean.tokens if normalize(token.text) == '漫游签证']
    codes = [token for token in clean.tokens if normalize(token.text) == '兑换码']
    if len(visas) != 1 or len(codes) != 1:
        return None
    visa = visas[0]
    if (visa.score < max(.85, confidence) or not visa.within(MORE_MENU)
            or redemption_entry(scene, confidence) != codes[0]):
        return None
    return visa


_TARGETS = dict(open_achievements=phone_achievement_target, open_more=_support_more_target,
                open_support=_support_visa_target)
_OVERVIEWS = dict(achievements=('achievement_overview', '成就总览'),
                  support=('support_collection_overview', '漫游签证收集展示'))


def _destination_hint(scene, confidence, mode):
    clean = trusted(scene, COLLECTION_FLOOR)
    if mode == 'achievements' and achievement_overview(scene, confidence):
        return 'achievement_overview'
    if mode == 'support' and visa_overview(scene, confidence):
        return 'support_collection_overview'
    if mode == 'support' and _support_visa_target(scene, confidence) is not None:
        return 'more_menu_still_visible'
    phone_target = _support_more_target if mode == 'support' else phone_achievement_target
    if phone_target(scene, confidence) is not None:
        return 'phone_still_visible'
    name = '漫游签证' if mode == 'support' else '成就'
    titles = [token for token in clean.tokens if normalize(token.text) == name]
    if (not _blocked(clean, allow_menu=mode == 'support') and len(titles) == 1 and titles[0].within(TITLE)
            and titles[0].score >= max(.85, confidence) and not clean.has('兑换码', exact=True)):
        # A title alone is useful evidence for calibration of the full page.
        return 'support_title_only' if mode == 'support' else 'achievement_title_only'
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
    action: str | None


class DailyRewardObserver:
    def __init__(self, context, mode='achievements'):
        self.c = context
        self.mode = mode
        self.window = context.window
        self.epoch = context.runner.input_epoch
        self.confidence = context.settings.ocr_confidence
        self.window_key = None
        self.geometry = None
        self.account = None
        self.directory = Path(context.report.run_dir).resolve()
        self.intent = None
        self.intent_bytes = None
        self.more_intent = None
        self.before = ()
        self.submission = None
        self.record = initial_record(mode)
        self.action = None
        self.step = None
        self.arrival = ()

    def guard_window(self):
        if self.c.runner.stop_requested:
            raise Stopped('日常奖励入口校准已停止。')
        if self.c.runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch:
            raise InputInterrupted('日常奖励入口校准的输入代次已改变。')
        if (self.c.window is not self.window or self.window_key is None
                or self.window.current_window_key() != self.window_key):
            raise AutomationError('日常奖励入口校准的窗口来源已改变。')
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
            raise AutomationError('日常奖励入口校准缺少同一窗口的新鲜画面。')

    def _account(self, scene):
        key = checked_account_key(scene, self.confidence)
        if self.account is not None and key != self.account:
            raise AutomationError('日常奖励入口校准期间当前账号已改变。')
        return key

    def _capture(self, action):
        scene = self.c.snapshot()
        if self.geometry is None:
            self.geometry = scene.geometry
        if self.geometry is None:
            raise AutomationError('日常奖励入口校准缺少当前窗口尺寸。')
        sequence = self.c.capture_sequence
        self._current(scene, sequence)
        self.account = self._account(scene)
        target = _TARGETS[action](scene, self.confidence) if action else None
        hint = ('more_menu' if action == 'open_support' else 'phone') if action else _destination_hint(
            scene, self.confidence, self.mode)
        return _Frame(scene, sequence, scene.captured_at, _pixels(scene), target, hint, action)

    @staticmethod
    def _adjacent(first, second):
        return (second.sequence == first.sequence + 1 and second.scene is not first.scene
                and not np.may_share_memory(first.scene.image, second.scene.image)
                and first.captured_at < second.captured_at
                and 0 <= time.monotonic() - first.captured_at <= MAX_AGE)

    @staticmethod
    def _same_target(first, second):
        return (first.action == second.action and first.target is not None and second.target is not None
                and all(abs(a - b) <= .006 for a, b in zip(first.target.box, second.target.box)))

    def _pair(self, action=None, *, after=None):
        previous, pair = None, ()
        for attempt in range(MAX_CAPTURES):
            if attempt or after is not None:
                self.c.sleep(.30)
            try:
                frame = self._capture(action)
            except (EmptyCapture, AccountNotObserved):
                previous, pair = None, ()
                continue
            if (action is not None and frame.target is None or after is not None and frame.captured_at <= after):
                previous, pair = None, ()
                continue
            if previous is not None and self._adjacent(previous, frame):
                if action is not None and self._same_target(previous, frame):
                    return previous, frame
                if action is None and previous.hint == frame.hint:
                    pair = previous, frame
                    if frame.hint in (_OVERVIEWS[self.mode][0], 'achievement_title_only', 'support_title_only'):
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
            raise AutomationError('日常奖励入口证据不在本次运行目录。')
        return path

    @staticmethod
    def _digest(path):
        with path.open('rb') as stream:
            raw = stream.read(MAX_PNG_BYTES + 1)
        if len(raw) > MAX_PNG_BYTES or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise AutomationError('日常奖励入口证据的图像格式异常。')
        return sha256(raw).hexdigest()

    def _verify_frame(self, frame):
        scene = frame.scene
        if (scene.geometry != self.geometry or scene.captured_at != frame.captured_at
                or not 0 <= time.monotonic() - frame.captured_at <= MAX_AGE
                or _pixels(scene) != frame.pixel_sha256 or self._account(scene) != self.account
                or frame.action is not None and _TARGETS[frame.action](scene, self.confidence) != frame.target
                or frame.action is None and _destination_hint(scene, self.confidence, self.mode) != frame.hint):
            raise AutomationError('日常奖励入口证据的原画面、账号或控件已变化。')

    def _save_pair(self, frames, phase):
        self._current(frames[-1].scene, frames[-1].sequence)
        rows = []
        for index, frame in enumerate(frames, 1):
            self._verify_frame(frame)
            path, digest = self.c.evidence(frame.scene, f'daily_reward_{phase}_{index}', with_sha256=True)
            path = self._path(path)
            if self._digest(path) != digest:
                raise AutomationError('日常奖励入口的落盘图像已变化。')
            rows.append(dict(screenshot=path.name, sha256=digest, capture_sequence=frame.sequence,
                             captured_at=frame.captured_at, hint=frame.hint,
                             entry_box=list(frame.target.box) if frame.target is not None else None))
        if len({row['screenshot'] for row in rows}) != 2:
            raise AutomationError('日常奖励入口校准需要独立的双帧截图。')
        self._current(frames[-1].scene, frames[-1].sequence)
        return rows

    def _save_intent(self, rows):
        data = dict(schema=1, mode=self.mode, intent=self.action, sources=rows)
        if self.more_intent is not None:
            parent, raw = self.more_intent
            data['previous_intent'] = dict(name=parent.name, sha256=sha256(raw).hexdigest())
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf8')
        with self.intent.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        self.intent_bytes = raw
        self.step.update(before_frames=rows, intent=self.intent.name)

    def _intents(self):
        if self.more_intent is not None:
            yield self.more_intent
        yield self.intent, self.intent_bytes

    def hold_intent(self):
        if self.intent_bytes is None or self.submission is None:
            raise AutomationError('缺少本次日常奖励入口的落盘意图。')
        paths = []
        for path, raw in self._intents():
            paths.append(path)
            paths.extend(self._path(self.directory / row['screenshot']) for row in json.loads(raw)['sources'])
        return hold_read_sources(paths)

    def authorize(self, scene):
        frame = self.submission
        if (self.step is None or self.step['entry_input'] != 'not_sent' or self.intent_bytes is None
                or len(self.before) != 2 or frame is None or frame.scene is not scene or frame.action != self.action
                or not self._adjacent(*self.before) or not self._same_target(*self.before)
                or not self._adjacent(self.before[-1], frame) or not self._same_target(self.before[-1], frame)):
            raise AutomationError('日常奖励入口缺少本次一次性意图及连续的当前目标。')
        if self.action == 'open_support':
            more = self.record['steps']['open_more']
            if (more['entry_input'] != 'sent' or more['destination_status'] != 'more_menu_verified'
                    or self.more_intent is None or self.step['before_frames'] != more['after_frames']):
                raise AutomationError('漫游签证缺少本次已发送且双帧核实的更多菜单。')
        self._current(scene, frame.sequence)
        for path, raw in self._intents():
            with path.open('rb') as stream:
                if stream.read(len(raw) + 1) != raw:
                    raise AutomationError('日常奖励入口意图在发送前已变化。')
            for row in json.loads(raw)['sources']:
                if self._digest(self._path(self.directory / row['screenshot'])) != row['sha256']:
                    raise AutomationError('日常奖励入口截图在发送前已变化。')
        for source in self.before:
            self._verify_frame(source)
        self._verify_frame(frame)
        self._current(scene, frame.sequence)
        return frame.target

    def _open(self, action, frames, *, rows=None):
        if action == 'open_support':
            if self.action != 'open_more' or self.step['destination_status'] != 'more_menu_verified':
                raise AutomationError('需要本次已核实的更多菜单才能进入漫游签证。')
            self.more_intent = self.intent, self.intent_bytes
        elif self.action is not None:
            raise AutomationError('本次日常奖励入口已有导航意图。')
        self.action, self.before = action, frames
        if action == 'open_achievements':
            self.step = self.record
            self.intent = self.directory / 'daily-reward-entry-intent.json'
        else:
            self.step = self.record['steps'][action]
            self.intent = self.directory / f'daily-reward-{action.replace("_", "-")}-intent.json'
        if rows is None:
            rows = self._save_pair(frames, 'before')
        self._save_intent(rows)
        self.submission = self._capture(action)
        return self.c.daily_reward_entry_input(self.submission.scene)

    def _diagnostic(self):
        if self.c.last_scene is not None:
            self.step['diagnostic_screenshot'] = self._path(
                self.c.evidence(self.c.last_scene, 'daily_reward_unverified')).name

    def save_verified_report(self, temporary, write_report):
        report = self.c.report
        destination = self.directory / 'report.json'
        result = report.results[-1]
        hint, label = _OVERVIEWS[self.mode]

        @contextmanager
        def stable_arrival():
            rows = self.step['after_frames']
            paths = [self._path(self.directory / row['screenshot']) for row in rows]
            with hold_read_sources(paths):
                if (len(self.arrival) != 2 or len(paths) != 2 or not self._adjacent(*self.arrival)
                        or any(frame.hint != hint for frame in self.arrival)):
                    raise AutomationError(f'{label}缺少本次连续到页证据。')
                last = self.arrival[-1]
                self._current(last.scene, last.sequence)
                for frame, path, row in zip(self.arrival, paths, rows):
                    self._verify_frame(frame)
                    if self._digest(path) != row['sha256'] or frame.sequence != row['capture_sequence']:
                        raise AutomationError(f'{label}到页证据在报告提交前已变化。')
                if temporary.read_text(encoding='utf8') != payload:
                    raise AutomationError(f'{label}报告临时文件在提交前已变化。')
                if self.window.emergency_pressed():
                    raise Stopped('F10 紧急停止。')
                self.guard_window()
                yield

        try:
            payload = write_report()
            replace_file(temporary, destination, attempt_scope=stable_arrival)
        except (OSError, AutomationError) as error:
            self.record.update(page_verified=False, destination_status='unknown')
            self.step['destination_status'] = 'unknown'
            stopped = isinstance(error, Stopped)
            if stopped:
                self.c.runner.stop()
            report.status = 'stopped' if stopped else 'partial'
            report.failure_task, report.error = OPERATION, str(error)
            result.status = report.status
            result.detail = f'{label}入口已发送，报告提交时的到页证据待核实。'
            write_report()
            replace_file(temporary, destination)

    def run(self):
        if (self.c.report.operation != OPERATION or self.mode != self.c.runner.daily_reward_mode
                or getattr(self.c, 'daily_reward_reader', None) is not None):
            raise AutomationError('日常奖励校准需要独立运行入口及明确模式。')
        self.c.daily_reward_reader = self
        self.c.report.daily_reward_observe = self.record
        self.window_key = self.window.current_window_key()
        self.guard_window()
        action = 'open_more' if self.mode == 'support' else 'open_achievements'
        label = '更多' if self.mode == 'support' else '成就'
        before = self._pair(action)
        if len(before) != 2:
            raise AutomationError(f'未从连续新画面核实当前账号的手机{label}入口。')
        sent_at = self._open(action, before)
        if self.mode == 'support':
            more = self._pair('open_support', after=sent_at)
            if not more:
                self._diagnostic()
                return TaskResult(OPERATION, 'partial', '更多已发送，当前账号的更多菜单仍待双帧核实。')
            rows = self._save_pair(more, 'after_more')
            self.step.update(after_frames=rows, destination_status='more_menu_verified')
            sent_at = self._open('open_support', more, rows=rows)
            label = '漫游签证'
        after = self._pair(after=sent_at)
        if after:
            self.step['after_frames'] = self._save_pair(after, 'after')
            self.step['destination_status'] = self.record['destination_status'] = after[-1].hint
            overview_hint, overview_label = _OVERVIEWS[self.mode]
            if after[-1].hint == overview_hint:
                self.arrival = after
                self.record['page_verified'] = True
                return TaskResult(OPERATION, 'ok', f'已双帧核实当前账号的{overview_label}。')
            detail = f'{label}入口已发送，已保留随后双帧，{label}页待核实。'
        else:
            self._diagnostic()
            detail = f'{label}入口已发送，尚未核实同账号的后续双帧。'
        return TaskResult(OPERATION, 'partial', detail)
