"""Observe the ordinary team page using the pinned emblem and separate OCR fields."""
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
_PRESET_HEADINGS = ('队伍预设', '预设编队', '编队预设')
_HEADING_AREAS = ((.01, .015, .16, .125), (.29, .17, .72, .50))
_BLOCKING_LABELS = frozenset((
    '提示', '温馨提示', '确定', '知道了', '开拓等级', '支援', '角色列表', '角色详情',
    '位面饰品', '饰品提取', '混沌回忆', '虚构叙事', '末日幻影', '星启模式',
    '差分宇宙', '模拟宇宙', '货币战争', '快速编队', '开始挑战', '前往挑战', '进入故事',
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


def _team_numbers(tokens: list[Token], minimum: float) -> list[dict] | None:
    numbers = sorted((token for token in tokens if _NUMBER.fullmatch(token.text.strip())
                      and _overlaps(token.box, _NUMBERS)), key=lambda token: token.center[0])
    if len(numbers) < 2:
        return None
    values = [int(token.text.strip()) for token in numbers]
    if values[0] == 0:
        return None
    for token in numbers:
        left, top, right, bottom = token.box
        if (not _inside(token.box, _NUMBERS) or token.score < minimum
                or not .006 <= right - left <= .040 or not .012 <= bottom - top <= .042):
            return None
    y = [token.center[1] for token in numbers]
    if max(y) - min(y) > .012:
        return None
    for before, after, left, right in zip(values, values[1:], numbers, numbers[1:]):
        if after != before + 1 or not .035 <= right.center[0] - left.center[0] <= .18:
            return None
    return [dict(_token_proof(token), number=value) for token, value in zip(numbers, values)]


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
                   for token, word in zip(clean.tokens, words))):
        return None

    status = [token for token, word in zip(clean.tokens, words) if word in _CAPTIONS]
    minimum = max(.85, confidence)
    if (len(status) != 1 or status[0].text.strip() not in _CAPTIONS or status[0].score < minimum
            or not _inside(status[0].box, _STATUS)
            or any(token is not status[0] and _overlaps(token.box, _STATUS) for token in clean.tokens)):
        return None
    numbers = _team_numbers(clean.tokens, minimum)
    if numbers is None:
        return None
    emblem = _emblem_hit(clean.image)
    if emblem is None:
        return None
    return dict(schema=1, source=emblem, status=_token_proof(status[0]), team_numbers=numbers)


def same_team_page(first: dict | None, second: dict | None) -> bool:
    """Require the same observed emblem, status and number row in two scenes."""
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    try:
        source, other_source = first['source'], second['source']
        status, other_status = first['status'], second['status']
        numbers, other_numbers = first['team_numbers'], second['team_numbers']
        return (first['schema'] == second['schema'] == 1
                and source['sha256'] == other_source['sha256'] == _EMBLEM_SHA256
                and _overlaps(source['box'], other_source['box'])
                and status['text'] in _CAPTIONS and status['text'] == other_status['text']
                and _overlaps(status['box'], other_status['box'])
                and len(numbers) == len(other_numbers) >= 2
                and all(left['number'] == right['number'] and _overlaps(left['box'], right['box'])
                        for left, right in zip(numbers, other_numbers)))
    except (IndexError, KeyError, TypeError):
        return False
