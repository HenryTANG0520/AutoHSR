"""Read calibrated challenge feedback from an already visible window."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time

import cv2
import numpy as np

from . import challenge_pages as pages
from .currency_wars_identity import UID_COUNTEREVIDENCE, AccountNotObserved, account_key
from .models import FULL, ROI, AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, TaskResult, Token, normalize
from .storage import hold_read_sources, replace_file


OPERATION = 'challenge_result'
SAFE_NEXT = '请在前台打开高难结果页面后核对当前反馈。分数、星数及领奖需要各自的实机证据。'
MAX_AGE = 8.
MAX_BYTES = 64 * 1024 * 1024
UID_VETO_CONFIDENCE = .65
_NEXT_NODE = 'apocalyptic_result_next'
_CONTROLS = {
    'fiction_result_return': (pages.FICTION, '返回虚构叙事'),
    _NEXT_NODE: (pages.APOCALYPTIC, '前往节点二'),
    'apocalyptic_result_return': (pages.APOCALYPTIC, '返回末日幻影'),
}
_FAILURE = 'result_failure'
_BLOCKERS = ('验证码', '账号登录', '扫码登录', '用户协议', '资源下载', '更新游戏', '连接失败',
             '重新连接', '加载中', '获得奖励', '领取奖励', '是否退出', '将清空当前挑战队伍',
             '选择最高解锁关卡', '开启故事', '星际和平指南', '更换编队', '前往编队', '进入故事',
             '差分宇宙', '模拟宇宙', '货币战争', '支付', '购买', '充值', '确认领取')

# Full-frame regions from the 4.6 normal-mode "取象为文其四" result.
# The record badge beside 积分 and the goals below the node row have their own space.
_FICTION_STAGE = (.39, .075, .61, .129)
_FICTION_SUCCESS = (.38, .124, .62, .207)
_FICTION_TOTAL = (.40, .191, .558, .251)
_FICTION_TOTAL_ROW = (.32, .191, .68, .251)
_FICTION_NODE_ROW = (.25, .271, .75, .348)
_FICTION_NODE_ONE = (.30, .275, .47, .343)
_FICTION_NODE_TWO = (.53, .275, .70, .343)
_FICTION_FINAL_RETURN = (.38, .885, .62, .970)
_FICTION_STAGE_NAMES = ('取象为文其四', '取象为文·其四', '取象为文•其四')
_FICTION_SCORE_BLOCKERS = ('星启', '节点三', '节点3', '节点３', '前往节点',
                           '挑战失败', '挑战结束', '已挑战', '通关详情', '历史积分', '历史最高')
# The 4.6 correction restored the 40,000-point cap on the calibrated stage.
_FICTION_NODE_CAP = 40_000
_SCORE_WIDTH = str.maketrans('０１２３４５６７８９，：　', '0123456789,: ')
_SCORE_NUMBER = re.compile(r'(?:0|[1-9][0-9]{0,4}|[1-9][0-9]?,[0-9]{3})')

# Ordinary 4.6 Apocalyptic Shadow after the second node. The middle screen
# also says 挑战结束, but lacks the second score and these two bottom controls.
_APOCALYPTIC_TITLE = (.40, .165, .60, .249)
_APOCALYPTIC_TOTAL = (.42, .235, .58, .296)
_APOCALYPTIC_TOTAL_ROW = (.27, .235, .74, .296)
_APOCALYPTIC_ROWS = ((.262, .299, .745, .348), (.262, .348, .745, .394))
_APOCALYPTIC_RETRY = (.32, .848, .418, .915)
_APOCALYPTIC_RETURN = (.553, .848, .698, .915)
_APOCALYPTIC_SCORE_BLOCKERS = ('星启', '节点三', '节点3', '节点３', '前往节点', '退出',
                              '挑战失败', '已挑战', '通关详情', '历史积分', '历史最高', '快速通关',
                              '返回主界面', '返回主页')
_APOCALYPTIC_OCR_CONTROLS = {'apocalyptic_terminal_retry_ocr': '重新挑战',
                            'apocalyptic_terminal_return_ocr': '返回末日幻影'}

# The 16:9 normal-mode 4.6 "物竞天择" result. Its return caption is also
# used by permanent Forgotten Hall and Starward mode, so it is insufficient alone.
_CHAOS_TITLE = (.443, .137, .554, .179)
_CHAOS_SUCCESS = (.413, .180, .586, .252)
_CHAOS_ROUNDS = (.464, .253, .539, .306)
_CHAOS_ROUNDS_LABEL = (.460, .301, .543, .341)
_CHAOS_GOAL_ROWS = ((.267, .337, .474, .378), (.267, .379, .474, .425), (.267, .426, .474, .475))
_CHAOS_GOALS = ('取得胜利时剩余10轮以上', '取得胜利时剩余20轮以上', '没有角色无法战斗')
_CHAOS_RETURN = (.426, .836, .580, .920)
_CHAOS_TITLE_PATTERN = re.compile(r'物竞天择[·•]?其(?:[一二三四五六七八九]|十[一二]?)')
_CHAOS_RETURN_ANCHOR = 'chaos_terminal_return_ocr'
_CHAOS_RETURN_CAPTION = '返回忘却之庭'
_CHAOS_BLOCKERS = ('星启', '节点一', '节点二', '节点三', '节点3', '节点３', '前往节点',
                   '挑战失败', '挑战结束', '退出', '重新挑战', '角色编队', '通关详情',
                   '历史积分', '历史最高', '快速通关', '返回主界面', '返回主页')
_OCR_CONTROLS = _APOCALYPTIC_OCR_CONTROLS | {_CHAOS_RETURN_ANCHOR: _CHAOS_RETURN_CAPTION}
_CONTROL_CAPTIONS = {name: caption for name, (_, caption) in _CONTROLS.items()} | _OCR_CONTROLS


@dataclass(frozen=True)
class _ResultScore:
    total: int
    node_one: int
    node_two: int
    boxes: tuple[ROI, ...]

    def agrees_with(self, other):
        return (other is not None and self.total == other.total
                and self.node_one == other.node_one and self.node_two == other.node_two
                and all(pages._overlaps(a, b) for a, b in zip(self.boxes, other.boxes)))


@dataclass(frozen=True)
class _MemoryRounds:
    title: str
    value: int
    boxes: tuple[ROI, ...]

    def agrees_with(self, other):
        return (other is not None and self.title == other.title and self.value == other.value
                and all(pages._overlaps(a, b) for a, b in zip(self.boxes, other.boxes)))


@dataclass(frozen=True)
class Feedback:
    mode: str | None
    anchors: tuple[Token, ...]
    score: _ResultScore | None = None
    memory_rounds: _MemoryRounds | None = None


def _same_score_row(parts):
    centers = [token.center[1] for token in parts]
    top = max(t.box[1] for t in parts)
    bottom = min(t.box[3] for t in parts)
    return max(centers) - min(centers) <= .013 and bottom - top >= .25 * min(
        t.box[3] - t.box[1] for t in parts)


def _score_line(tokens, roi, minimum):
    parts = sorted((token for token in tokens if token.within(roi)), key=lambda token: token.box[0])
    if (not parts or any(t.score < minimum or not pages._inside(t.box, roi) for t in parts)
            or not _same_score_row(parts)
            or any(not 0 <= right.box[0] - left.box[2] <= .022 for left, right in zip(parts, parts[1:]))
            or any(pages._overlaps(t.box, other.box) for t in parts for other in tokens if t is not other)):
        return ()
    return tuple(parts)


def _score_text(parts):
    return ''.join(token.text.translate(_SCORE_WIDTH).strip(' ') for token in parts)


def _score_box(parts):
    return (min(t.box[0] for t in parts), min(t.box[1] for t in parts),
            max(t.box[2] for t in parts), max(t.box[3] for t in parts))


def _score_value(parts, label):
    pieces = [token.text.translate(_SCORE_WIDTH).strip(' ') for token in parts]
    text = ''.join(pieces)
    if not text.startswith(label):
        return None
    digits = text[len(label):].lstrip(' ')
    if label:
        digits = digits.removeprefix(':').lstrip(' ')
    # Label fragments may join on the same line. Two digit fragments need
    # the printed grouping comma to establish that they are one number.
    if (not _SCORE_NUMBER.fullmatch(digits) or not all(pieces)
            or any(left[-1].isdigit() and right[0].isdigit() for left, right in zip(pieces, pieces[1:]))):
        return None
    number_parts = [token for token, piece in zip(parts, pieces) if any(ch.isdigit() for ch in piece)]
    return int(digits.replace(',', '')), _score_box(number_parts)


def _read_fiction_score(tokens, words, minimum):
    if any(blocker in word for word in words for blocker in _FICTION_SCORE_BLOCKERS):
        return None
    stage_parts = _score_line(tokens, _FICTION_STAGE, minimum)
    success_parts = _score_line(tokens, _FICTION_SUCCESS, minimum)
    stage = _score_text(stage_parts).replace(' ', '') in _FICTION_STAGE_NAMES
    success = _score_text(success_parts).replace(' ', '') == '挑战成功'
    if not (stage and success):
        return None

    node_row = [token for token in tokens if pages._overlaps(token.box, _FICTION_NODE_ROW)]
    one = _score_line(node_row, _FICTION_NODE_ONE, minimum)
    two = _score_line(node_row, _FICTION_NODE_TWO, minimum)
    if not one or not two or len(one) + len(two) != len(node_row) or not _same_score_row(node_row):
        return None

    left_read = _score_value(one, '节点一')
    right_read = _score_value(two, '节点二')
    total_parts = _score_line(tokens, _FICTION_TOTAL, minimum)
    if any(token.within(_FICTION_TOTAL_ROW) and token not in total_parts
           and ('积分' in token.text or any(ch.isdecimal() for ch in token.text)) for token in tokens):
        return None
    total_read = _score_value(total_parts, '积分')
    if left_read is None or right_read is None or total_read is None:
        return None
    first, first_box = left_read
    second, second_box = right_read
    total, total_box = total_read
    if total == 0 or first > _FICTION_NODE_CAP or second > _FICTION_NODE_CAP or first + second != total:
        return None
    boxes = (_score_box(stage_parts), _score_box(success_parts), total_box, first_box, second_box)
    return _ResultScore(total, first, second, boxes)


def _apocalyptic_node(tokens, roi, label, minimum):
    left, top, right, bottom = roi
    row = [token for token in tokens if pages._overlaps(token.box, roi)]
    name = _score_line(row, (left, top, .356, bottom), minimum)
    value = _score_line(row, (.649, top, right, bottom), minimum)
    if (not name or not value or len(name) + len(value) != len(row)
            or not _same_score_row(row) or _score_text(name).replace(' ', '') != label):
        return None
    number = _score_value(value, '')
    if number is None:
        return None
    return name, value, number[0]


def _read_apocalyptic_terminal(tokens, words, minimum):
    if any(blocker in word for word in words for blocker in _APOCALYPTIC_SCORE_BLOCKERS):
        return None
    title = _score_line(tokens, _APOCALYPTIC_TITLE, minimum)
    retry = _score_line(tokens, _APOCALYPTIC_RETRY, minimum)
    leave = _score_line(tokens, _APOCALYPTIC_RETURN, minimum)
    controls = (retry, leave)
    labels = tuple(_APOCALYPTIC_OCR_CONTROLS.values())
    if (_score_text(title).replace(' ', '') != '挑战结束'
            or any(_score_text(parts).replace(' ', '') != label for parts, label in zip(controls, labels))
            or not _same_score_row((*retry, *leave))):
        return None
    total = _score_line(tokens, _APOCALYPTIC_TOTAL, minimum)
    if any(token.within(_APOCALYPTIC_TOTAL_ROW) and token not in total
           and ('积分' in token.text or any(ch.isdecimal() for ch in token.text)) for token in tokens):
        return None
    total_read = _score_value(total, '积分')
    first, second = (_apocalyptic_node(tokens, roi, label, minimum)
                     for roi, label in zip(_APOCALYPTIC_ROWS, ('节点一', '节点二')))
    if total_read is None or first is None or second is None:
        return None
    total_score, _ = total_read
    first_label, first_value, first_score = first
    second_label, second_value, second_score = second
    if total_score == 0 or first_score + second_score != total_score:
        return None

    groups = (title, total, first_label, first_value, second_label, second_value, *controls)
    known = [token for parts in groups for token in parts]
    remaining = [token for token in tokens if token not in known]
    duplicate_labels = ('挑战结束', '积分', '节点一', '节点二', *labels)
    remaining_words = tuple(normalize(token.text) for token in remaining) + pages._line_words(remaining, gap=.012)
    if any(label in word for word in remaining_words for label in duplicate_labels):
        return None
    score = _ResultScore(total_score, first_score, second_score, tuple(_score_box(parts) for parts in groups))
    anchors = tuple(Token(name, min(token.score for token in parts), _score_box(parts))
                    for name, parts in zip(_APOCALYPTIC_OCR_CONTROLS, controls))
    return score, anchors


def _read_chaos_terminal(tokens, words, minimum):
    if any(blocker in word for word in words for blocker in _CHAOS_BLOCKERS):
        return None
    regions = (_CHAOS_TITLE, _CHAOS_SUCCESS, _CHAOS_ROUNDS, _CHAOS_ROUNDS_LABEL,
               *_CHAOS_GOAL_ROWS, _CHAOS_RETURN)
    groups = tuple(_score_line(tokens, region, minimum) for region in regions)
    stage, success, raw_rounds, label, *goals, leave = groups
    title = _score_text(stage).replace(' ', '')
    value = _score_value(raw_rounds, '')
    if (not _CHAOS_TITLE_PATTERN.fullmatch(title) or _score_text(success).replace(' ', '') != '挑战成功'
            or _score_text(label).replace(' ', '') != '剩余轮' or value is None or value[0] > 30
            or tuple(normalize(_score_text(row)) for row in goals) != _CHAOS_GOALS
            or _score_text(leave).replace(' ', '') != _CHAOS_RETURN_CAPTION):
        return None

    known = [token for parts in groups for token in parts]
    extras = [token for token in tokens if token not in known]
    extra_words = tuple(normalize(token.text) for token in extras) + pages._line_words(extras, gap=.012)
    unique = ('物竞天择', '挑战成功', '剩余轮', *_CHAOS_GOALS, _CHAOS_RETURN_CAPTION)
    if any(label in word for word in extra_words for label in unique):
        return None
    if any(token.within((.31, .253, .69, .306))
           and _SCORE_NUMBER.fullmatch(_score_text((token,))) for token in extras):
        return None

    # OCR can drop the final 一 from 十一 on successive frames. Retain the
    # title for comparison, but publish only the independent rounds read.
    reading = _MemoryRounds(title, value[0], tuple(_score_box(parts) for parts in groups))
    anchor = Token(_CHAOS_RETURN_ANCHOR, min(token.score for token in leave), _score_box(leave))
    return Feedback(pages.MODE, (anchor,), memory_rounds=reading)


def observe_feedback(scene, confidence=.65):
    """Identify visible controls, failure and calibrated result fields."""
    clean = pages._clean(scene, confidence, blockers=())
    if clean is None:
        return None
    words = tuple(normalize(token.text) for token in clean.tokens) + pages._line_words(clean.tokens, gap=.012)
    if (any(word in ('确认', '取消', '确定') for word in words)
            or any(blocker in word for word in words for blocker in _BLOCKERS)):
        return None
    controls = {name: caption for name, (_, caption) in _CONTROLS.items()
                if any(caption in word for word in words)}
    modes = {mode for mode, title in pages._MODE_WORDS.items() if any(title in word for word in words)}
    modes.update(_CONTROLS[name][0] for name in controls)
    if not controls and modes.issubset({pages.MODE}):
        terminal = _read_chaos_terminal(clean.tokens, words, max(.85, confidence))
        if terminal is not None and not any(pages._hits(clean, name, FULL) for name in (*_CONTROLS, _FAILURE)):
            return terminal
        return None
    if not controls or len(modes) != 1 or any(_CHAOS_RETURN_CAPTION in word for word in words):
        return None

    anchors = []
    for name, caption in controls.items():
        hits = pages._hits(clean, name, FULL)
        if len(hits) > 1:
            return None
        if not hits:
            continue
        hit = hits[0]
        nearby = [token for token in clean.tokens if token.within(hit.box)]
        padded = tuple(edge + (-.004 if i < 2 else .004) for i, edge in enumerate(hit.box))
        if (any(t.score < max(.85, confidence) or not pages._inside(t.box, padded) for t in nearby)
                or any(pages._overlaps(a.box, b.box) for i, a in enumerate(nearby) for b in nearby[i + 1:])
                or pages._line_words(nearby, gap=.012) != (caption,)):
            continue
        anchors.append(hit)
    apocalyptic = modes == {pages.APOCALYPTIC}
    if not anchors and not apocalyptic:
        return None
    if any(pages._hits(clean, name, FULL) for name, (kind, _) in _CONTROLS.items() if kind not in modes):
        return None
    if apocalyptic:
        terminal = _read_apocalyptic_terminal(clean.tokens, words, max(.85, confidence))
        if terminal is not None and not pages._hits(clean, _FAILURE, FULL):
            score, structural_anchors = terminal
            return Feedback(pages.APOCALYPTIC, tuple(anchors) or structural_anchors, score)
    if not anchors:
        return None
    # The node-two caption contains no mode name. It can corroborate a
    # destination but the returned mode needs a mode-specific return crop.
    mode_anchor = next((a for a in anchors if a.text != _NEXT_NODE), None)
    mode = _CONTROLS[mode_anchor.text][0] if mode_anchor is not None else None
    score = None
    if mode_anchor is not None:
        failure = pages._hits(clean, _FAILURE, FULL)
        if len(failure) == 1 and not any(pages._overlaps(failure[0].box, a.box) for a in anchors):
            anchors.append(failure[0])
        if mode == pages.FICTION and not failure and pages._inside(mode_anchor.box, _FICTION_FINAL_RETURN):
            score = _read_fiction_score(clean.tokens, words, max(.85, confidence))
    return Feedback(mode, tuple(anchors), score)


@dataclass(frozen=True)
class _Frame:
    scene: Scene
    captured_at: float
    sequence: int
    feedback: Feedback
    pixel_sha256: str


@dataclass(frozen=True)
class _Receipt:
    frames: tuple[_Frame, _Frame]
    pngs: tuple[tuple[Path, str], ...]
    payload: bytes


def _pixels(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


def _same_feedback(first, second):
    rounds = first.memory_rounds
    same_rounds = rounds is second.memory_rounds or (rounds is not None and rounds.agrees_with(second.memory_rounds))
    return (first.mode == second.mode and same_rounds and len(first.anchors) == len(second.anchors)
            and all(a.text == b.text and pages._overlaps(a.box, b.box)
                    for a, b in zip(first.anchors, second.anchors)))


def _anchor_proof(anchor):
    label = _OCR_CONTROLS.get(anchor.text)
    if label is not None:
        return dict(source='ocr', text=label, box=list(anchor.box), score=anchor.score)
    return pages._proof(anchor.text, anchor)


class ResultReader:
    def __init__(self, context):
        if context.report.operation != OPERATION or not context.report.run_dir or context.report.challenge_result:
            raise AutomationError('高难结算观察需要独立入口和本次运行目录。')
        self.c = context
        self.directory = Path(context.report.run_dir).resolve(strict=True)
        self.epoch = context.runner.input_epoch
        self.account = None
        self.geometry = None
        self.confidence = context.settings.ocr_confidence
        context.vision.uid_counterevidence_floor = UID_VETO_CONFIDENCE
        self.deadline = time.monotonic() + 20
        self.receipt = None
        self.data = dict(schema=1, status='unknown', mode=None, level=None, half=None, node=None,
                         destination_node_in_caption=None, upper_half_score=None, lower_half_score=None,
                         node_one_score=None, node_two_score=None, total_score=None, remaining_rounds=None, stars=None,
                         settlement_status='unknown', outcome='unknown', visible_controls=[],
                         failure_marker_observed=None, completion_verified=False, rewards_verified=False,
                         evidence=[])
        context.report.challenge_result = self.data

    def _require_current(self, scene):
        if self.c.runner.stop_requested:
            raise Stopped('高难结果观察已停止。')
        if self.c.runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch:
            raise InputInterrupted('高难结果观察的输入代次已改变。')
        if (scene is not self.c.last_scene or scene.geometry is None
                or scene.geometry != self.geometry or not 0 <= time.monotonic() - scene.captured_at <= MAX_AGE):
            raise AutomationError('高难结果观察缺少同一窗口的新鲜画面。')

    def _read_account(self, scene):
        low = scene.field_reads.get(UID_COUNTEREVIDENCE, ())
        candidates = Scene([*scene.tokens, *low]) if low else scene
        try:
            candidate = account_key(candidates, min(UID_VETO_CONFIDENCE, self.confidence))
            if self.account is not None and self.account != candidate:
                raise AutomationError('高难结果观察期间账号已改变。')
            self.account = account_key(scene, max(.85, self.confidence))
        except AccountNotObserved:
            return False
        return True

    def _read_png(self, path):
        if path.parent != self.directory or path.suffix != '.png' or path.resolve(strict=True) != path:
            raise AutomationError('高难结果证据超出本次运行目录。')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if (len(raw) > MAX_BYTES or not raw.startswith(b'\x89PNG\r\n\x1a\n') or raw[12:16] != b'IHDR'
                or int.from_bytes(raw[16:20], 'big') != self.geometry.width
                or int.from_bytes(raw[20:24], 'big') != self.geometry.height):
            raise AutomationError('高难结果证据 PNG 的大小或窗口尺寸无效。')
        return raw

    def _save_frame(self, frame, name):
        path = Path(self.c.evidence(frame.scene, name)).absolute()
        raw = self._read_png(path)
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or _pixels(image) != frame.pixel_sha256:
            raise AutomationError('高难结果证据 PNG 与本次采集不同。')
        return dict(screenshot=path.name, sha256=hashlib.sha256(raw).hexdigest(), captured_at=frame.captured_at,
                    capture_sequence=frame.sequence, anchors=[_anchor_proof(a) for a in frame.feedback.anchors])

    def _check_sources(self, proof, receipt_path):
        self._require_current(proof.frames[-1].scene)
        for frame in proof.frames:
            if (frame.scene.geometry != self.geometry or frame.scene.captured_at != frame.captured_at
                    or _pixels(frame.scene.image) != frame.pixel_sha256 or not self._read_account(frame.scene)
                    or observe_feedback(frame.scene, self.confidence) != frame.feedback):
                raise AutomationError('高难结果观察的原画面或账号已改变。')
        for path, sha256 in proof.pngs:
            if hashlib.sha256(self._read_png(path)).hexdigest() != sha256:
                raise AutomationError('高难结果观察的落盘证据已改变。')
        if receipt_path.resolve(strict=True) != receipt_path:
            raise AutomationError('高难结果回执的来源路径已改变。')
        with receipt_path.open('rb') as stream:
            if stream.read(len(proof.payload) + 1) != proof.payload:
                raise AutomationError('高难结果回执内容已改变。')

    def _guard_publication(self, frames):
        # Consult the native foreground after the potentially slow OCR and file reads.
        self.c.window.guard(self.geometry)
        self._require_current(frames[-1].scene)
        now = time.monotonic()
        if now >= self.deadline or now - frames[0].captured_at > MAX_AGE:
            raise AutomationError('高难结果观察的双帧证据已过期。')

    def _publish(self, frames, score):
        self._require_current(frames[-1].scene)
        evidence = [self._save_frame(frame, f'challenge_result_{index}') for index, frame in enumerate(frames, 1)]
        if evidence[0]['screenshot'] == evidence[1]['screenshot']:
            raise AutomationError('高难结果观察需要分别保存两张新画面。')
        names = [anchor.text for anchor in frames[-1].feedback.anchors]
        mode = frames[-1].feedback.mode
        rounds = frames[-1].feedback.memory_rounds
        apocalyptic_score = score if mode == pages.APOCALYPTIC else None
        data = dict(self.data, status='feedback_verified' if mode else 'caption_verified', mode=mode,
                    visible_controls=[_CONTROL_CAPTIONS[name] for name in names if name in _CONTROL_CAPTIONS],
                    failure_marker_observed=True if _FAILURE in names else None,
                    destination_node_in_caption=2 if _NEXT_NODE in names else None,
                    node_one_score=apocalyptic_score.node_one if apocalyptic_score is not None else None,
                    node_two_score=apocalyptic_score.node_two if apocalyptic_score is not None else None,
                    total_score=score.total if score is not None else None,
                    remaining_rounds=rounds.value if rounds is not None else None,
                    evidence=evidence)
        path = self.directory / 'challenge-result.json'
        temporary = path.with_suffix('.tmp')
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        proof = _Receipt(frames, tuple((self.directory / row['screenshot'], row['sha256']) for row in evidence), payload)
        with temporary.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        def recheck():
            if path.exists() or path.is_symlink():
                raise AutomationError('本次已有高难结果回执，原记录保留。')
            self._check_sources(proof, temporary)
            self._guard_publication(frames)

        with hold_read_sources(path for path, _ in proof.pngs):
            replace_file(temporary, path, before_replace=recheck)
        self.receipt = proof
        return TaskResult(OPERATION, 'partial', '已保存双帧回执，待完成报告复核。')

    def save_report(self, temporary, write_report):
        destination = self.directory / 'report.json'
        proof = self.receipt
        if proof is None:
            write_report()
            replace_file(temporary, destination)
            return

        receipt_path = self.directory / 'challenge-result.json'
        original = self.data.copy()
        report = self.c.report
        result = next(item for item in report.results if item.task == OPERATION)
        try:
            with hold_read_sources([receipt_path, *(path for path, _ in proof.pngs)]):
                self.data.update(json.loads(proof.payload))
                if self.data['node_one_score'] is not None:
                    result.detail = '已核实本次末日幻影两个节点得分与总分，星数与领奖状态待核实。'
                elif self.data['total_score'] is not None:
                    result.detail = '已核实本次虚构叙事总分，星数与领奖状态待核实。'
                elif self.data['remaining_rounds'] is not None:
                    result.detail = '已核实本次混沌回忆剩余轮，关卡层号、星数与领奖状态待核实。'
                else:
                    result.detail = '已核实当前可见反馈，关卡成绩与领奖状态待核实。'
                payload = write_report()

                def recheck():
                    self._check_sources(proof, receipt_path)
                    with temporary.open(encoding='utf-8') as stream:
                        if stream.read(len(payload) + 1) != payload:
                            raise AutomationError('高难结果待发布报告已改变。')
                    self._guard_publication(proof.frames)

                replace_file(temporary, destination, before_replace=recheck)
        except (AutomationError, OSError, UnicodeError) as error:
            self.data.clear()
            self.data.update(original)
            if isinstance(error, Stopped):
                report.status = 'stopped'
            report.error = '高难结果报告发布未核实：' + str(error)
            result.detail = '高难结果报告未核实，保留本次原证据。'
            write_report()
            replace_file(temporary, destination)

    def run(self):
        previous = None
        last_scene = None
        latest_capture = 0.
        for attempt in range(8):
            if attempt:
                self.c.sleep(.3)
            if time.monotonic() >= self.deadline:
                break
            try:
                scene = self.c.snapshot()
            except EmptyCapture:
                previous = None
                continue
            last_scene = scene
            if self.geometry is None:
                self.geometry = scene.geometry
            self._require_current(scene)
            account_observed = self._read_account(scene)
            increasing = scene.captured_at > latest_capture
            latest_capture = max(latest_capture, scene.captured_at)
            feedback = observe_feedback(scene, self.confidence) if account_observed and increasing else None
            if feedback is None or scene.image.shape != (self.geometry.height, self.geometry.width, 3):
                previous = None
                continue
            frame = _Frame(scene, scene.captured_at, self.c.capture_sequence, feedback, _pixels(scene.image))
            if (previous is not None and frame.sequence == previous.sequence + 1
                    and frame.scene is not previous.scene and time.monotonic() - previous.captured_at <= MAX_AGE
                    and _same_feedback(previous.feedback, frame.feedback)):
                score = feedback.score
                if score is not None and not score.agrees_with(previous.feedback.score):
                    score = None
                return self._publish((previous, frame), score)
            previous = frame
        if last_scene is not None:
            path = self.c.evidence(last_scene, 'challenge_result_unverified')
            self.data['diagnostic_screenshot'] = Path(path).name
        return TaskResult(OPERATION, 'partial', '当前反馈缺少同账号连续双帧或已校准原件，结果待核实。')
