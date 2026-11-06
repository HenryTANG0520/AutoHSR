"""Observe the ordinary team page using the pinned emblem or the 4.6 layout."""
from __future__ import annotations

import hashlib
import re

import cv2
import numpy as np

from .challenge_pages import _clean, _inside, _overlaps
from .config import RESOURCE_ROOT
from .models import Scene, Token, normalize
from .team_calibration_pages import calibration_overlay


_EMBLEM = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/team-calibration/configure_team.png'
_EMBLEM_SHA256 = 'dc6004564d423eccbd98e50795e0c67d739b93b64aaeb7b7df0aa1a97068cda4'
# The shared emblem appears in the upper-left team heading. The independent
# number and status bands are from the pinned upstream Team.change_to.
_EMBLEM_REGION = (.015, .025, .072, .117)
_NUMBERS = (311 / 1920, 15 / 1080, 1687 / 1920, 115 / 1080)
_STATUS = (1507 / 1920, 955 / 1080, 1843 / 1920, 1013 / 1080)
_CAPTIONS = ('已启用', '启用队伍')
_NUMBER = re.compile(r'[0-9０-９]{2}')
_NATIVE_LAYOUT = 'ordinary_team_4_6'
_TITLE = (.042, .025, .110, .079)
_FAVORITE = (.077, .884, .164, .947)
_QUICK = (.638, .884, .735, .941)
_NATIVE_FIELDS = (('title', '队伍', _TITLE), ('favorite', '常用队伍', _FAVORITE),
                  ('quick', '快速编队', _QUICK))
_PRESET_HEADINGS = ('队伍预设', '预设编队', '编队预设')
_HEADING_AREAS = ((.01, .015, .16, .125), (.29, .17, .72, .50))
_OVERVIEW_HEADINGS = ('编队总览', '队伍总览')
_OVERVIEW_PANEL = (.01, .015, .55, .82)
_BLOCKING_LABELS = frozenset((
    '提示', '温馨提示', '确定', '知道了', '开拓等级', '支援', '角色列表', '角色详情',
    '位面饰品', '饰品提取', '混沌回忆', '虚构叙事', '末日幻影', '星启模式',
    '差分宇宙', '模拟宇宙', '货币战争', '开始挑战', '前往挑战', '进入故事',
    '编辑', '编辑队伍', '编辑队名', '保存', '保存队伍', '保存编队', '离队', '我的角色',
))
_BLOCKING_PHRASES = (
    '确认', '取消', '是否', '侵蚀隧洞', '饰品提取', '借用支援', '选择支援',
    '特遣支援', '前往节点', '点击空白处关闭',
    '加载中', '连接失败', '重新连接', '验证码',
)


def _emblem_hit(image: np.ndarray) -> dict | None:
    try:
        with _EMBLEM.open('rb') as stream:
            raw = stream.read(3280)
    except OSError:
        return None
    if len(raw) != 3279 or hashlib.sha256(raw).hexdigest() != _EMBLEM_SHA256:
        return None
    original = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if original is None or original.shape != (39, 36, 3):
        return None

    height, width = image.shape[:2]
    shape = (round(36 * width / 1920), round(39 * height / 1080))
    sample = cv2.resize(original, shape, interpolation=cv2.INTER_AREA)
    left, top, right, bottom = [
        round(fraction * size) for fraction, size in zip(_EMBLEM_REGION, (width, height, width, height))
    ]
    patch = image[top:bottom, left:right]
    # A small blur absorbs fractional-pixel placement after resizing.
    sample_gray, patch_gray = (
        cv2.GaussianBlur(cv2.cvtColor(part, cv2.COLOR_BGR2GRAY), (3, 3), .55)
        for part in (sample, patch)
    )
    scores = cv2.matchTemplate(patch_gray, sample_gray, cv2.TM_CCOEFF_NORMED)
    local_max = scores >= cv2.dilate(scores, np.ones((3, 3), dtype=np.uint8))
    ys, xs = np.where((scores >= .94) & local_max)
    hits = []
    for y, x in zip(ys, xs):
        x, y = int(x), int(y)
        observed = patch[y:y + shape[1], x:x + shape[0]]
        if np.abs(observed.astype(np.int16) - sample.astype(np.int16)).mean() <= 24:
            hits.append(dict(box=[(left + x) / width, (top + y) / height,
                                  (left + x + shape[0]) / width, (top + y + shape[1]) / height],
                             score=float(scores[y, x]), sha256=_EMBLEM_SHA256))
    return hits[0] if len(hits) == 1 else None


def _token_proof(token: Token) -> dict:
    return dict(text=token.text.strip(), box=list(token.box), score=float(token.score))


def _team_numbers(tokens: list[Token], minimum: float, *, native: bool = False) -> list[dict] | None:
    numbers = sorted((token for token in tokens if _NUMBER.fullmatch(token.text.strip())
                      and _overlaps(token.box, _NUMBERS)), key=lambda token: token.center[0])
    if len(numbers) < 2:
        return None
    values = [int(token.text.strip()) for token in numbers]
    if values[0] == 0:
        return None
    max_width, max_height = (.064, .052) if native else (.040, .042)
    for token in numbers:
        left, top, right, bottom = token.box
        if (not _inside(token.box, _NUMBERS) or token.score < minimum
                or not .006 <= right - left <= max_width or not .012 <= bottom - top <= max_height):
            return None
    y = [token.center[1] for token in numbers]
    if max(y) - min(y) > .012:
        return None
    for before, after, left, right in zip(values, values[1:], numbers, numbers[1:]):
        gap = right.center[0] - left.center[0]
        difference = after - before
        if native:
            # OCR can miss or join labels and shift their measured centers.
            if difference <= 0 or abs(gap - difference * .0625) > .022:
                return None
        elif difference != 1 or not .035 <= gap <= .18:
            return None
    return [dict(_token_proof(token), number=value) for token, value in zip(numbers, values)]


def _native_source(tokens: list[Token], words: list[str], status: Token, minimum: float) -> dict | None:
    fields = {}
    for key, label, region in _NATIVE_FIELDS:
        matches = [token for token, word in zip(tokens, words) if word == label]
        if len(matches) != 1:
            return None
        token = matches[0]
        if token.text.strip() != label or token.score < minimum or not _inside(token.box, region):
            return None
        if key != 'title' and any(other is not token and _overlaps(other.box, region) for other in tokens):
            return None
        fields[key] = token
    centers_y = [fields['favorite'].center[1], fields['quick'].center[1], status.center[1]]
    if max(centers_y) - min(centers_y) > .012:
        return None
    return dict(kind=_NATIVE_LAYOUT, box=list(fields['title'].box),
                anchors={key: _token_proof(token) for key, token in fields.items()})


def observe_team_page(scene: Scene, confidence: float = .65) -> dict | None:
    """Return ordinary team page evidence from the current scene."""
    if (not isinstance(scene, Scene) or not isinstance(scene.tokens, (tuple, list))
            or type(confidence) not in (int, float) or not 0 <= confidence <= 1):
        return None
    clean = _clean(scene, .65, blockers=())
    if clean is None or calibration_overlay(clean):
        return None
    words = [normalize(token.text) for token in clean.tokens]
    if (_BLOCKING_LABELS.intersection(words)
            or any(phrase in word for word in words for phrase in _BLOCKING_PHRASES)
            or any(word in _PRESET_HEADINGS and any(_overlaps(token.box, area) for area in _HEADING_AREAS)
                   for token, word in zip(clean.tokens, words))
            or any(word in _OVERVIEW_HEADINGS and _overlaps(token.box, _OVERVIEW_PANEL)
                   for token, word in zip(clean.tokens, words))):
        return None

    status = [token for token, word in zip(clean.tokens, words) if word in _CAPTIONS]
    minimum = max(.85, confidence)
    if (len(status) != 1 or status[0].text.strip() not in _CAPTIONS or status[0].score < minimum
            or not _inside(status[0].box, _STATUS)
            or any(token is not status[0] and _overlaps(token.box, _STATUS) for token in clean.tokens)):
        return None
    native = (any('快速编队' in word or '常用队伍' in word for word in words)
              or any(_overlaps(token.box, _FAVORITE) or _overlaps(token.box, _QUICK) for token in clean.tokens))
    numbers = _team_numbers(clean.tokens, minimum, native=native)
    if numbers is None:
        return None
    source = _native_source(clean.tokens, words, status[0], minimum) if native else _emblem_hit(clean.image)
    if source is None:
        return None
    return dict(schema=1, source=source, status=_token_proof(status[0]), team_numbers=numbers)


def _same_native_page(source, other_source, numbers, other_numbers) -> bool:
    if source.get('kind') != _NATIVE_LAYOUT or other_source.get('kind') != _NATIVE_LAYOUT:
        return False
    for key, _, _ in _NATIVE_FIELDS:
        anchor, other = source['anchors'][key], other_source['anchors'][key]
        if anchor['text'] != other['text'] or not _overlaps(anchor['box'], other['box']):
            return False
    by_number = {item['number']: item['box'] for item in numbers}
    other_by_number = {item['number']: item['box'] for item in other_numbers}
    shared = by_number.keys() & other_by_number.keys()
    # Wider OCR boxes on adjacent numbers can overlap without a column conflict.
    def center_x(box):
        return (box[0] + box[2]) / 2

    return (len(shared) >= 2
            and all(_overlaps(by_number[number], other_by_number[number]) for number in shared)
            and not any(left != right and abs(center_x(left_box) - center_x(right_box)) < .026
                        for left, left_box in by_number.items() for right, right_box in other_by_number.items()))


def same_team_page(first: dict | None, second: dict | None) -> bool:
    """Require agreeing page anchors and status from two scenes."""
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    try:
        source, other_source = first['source'], second['source']
        status, other_status = first['status'], second['status']
        numbers, other_numbers = first['team_numbers'], second['team_numbers']
        if (first['schema'] != 1 or second['schema'] != 1 or status['text'] not in _CAPTIONS
                or status['text'] != other_status['text'] or not _overlaps(status['box'], other_status['box'])):
            return False
        if source.get('kind') is not None or other_source.get('kind') is not None:
            return _same_native_page(source, other_source, numbers, other_numbers)
        return (source['sha256'] == other_source['sha256'] == _EMBLEM_SHA256
                and _overlaps(source['box'], other_source['box'])
                and len(numbers) == len(other_numbers) >= 2
                and all(left['number'] == right['number'] and _overlaps(left['box'], right['box'])
                        for left, right in zip(numbers, other_numbers)))
    except (AttributeError, IndexError, KeyError, TypeError):
        return False
