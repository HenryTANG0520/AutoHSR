"""Limited read-only challenge preparation observations.

Pinned title/control crops corroborate a page; they never prove selected roles,
four-person teams, a battle, a half transition or a successful result. There is
no input here. Full real page calibration remains outstanding.
"""
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
import math
import time

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .models import Scene, Token, normalize


MODE = 'memory_of_chaos'
_AMBIGUOUS_LEVEL = object()
ASSET_ROOT = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/challenge-ui'
LEVEL_REGION = (540 / 1920, 406 / 1080, 1696 / 1920, 922 / 1080)
TEAM_REGION = (592 / 1920, 432 / 1080, 1911 / 1920, 980 / 1080)
_FILES = {
    'title': 'screen/forgottenhall/memory_of_chaos.png',
    'team1': 'forgottenhall/team1.png', 'team2': 'forgottenhall/team2.png',
    'reset': 'forgottenhall/reset.png', 'switch': 'forgottenhall/switch.png',
    'star': 'forgottenhall/star.png', 'caption': 'forgottenhall/start.png',
}
_HASHES = {
    'title': 'ae954987947ac37732b76e9da7e3e9dea1ff9200b6af08ea387effeb0708c5b4',
    'team1': 'b47cefb48b3df4a4f7522d1bcad3877d64c96fab79dd8e974bd068c4ed06bdc6',
    'team2': '69b67d8e7f985fc79dd830806a73d2704425df52f4bfd7e633da67de39ed2a3b',
    'reset': '84d8bc4f6bae35d242721f353b0d414571a29950e18b9b64186d9e06ab887032',
    'switch': '755a291709111ad4f340c55bd36b5f684369dbbd419caf89c7a012653e485a91',
    'star': '88eed2945f375bbd983dd52e5d7c8ff8a99b7e5b8b21bba7b335063fc57e728e',
    'caption': '0f8bc303e60c56ca5d8f3383f1c771ca530a106c561e2c843a929f5ccf67d031',
}


@dataclass(frozen=True)
class Observation:
    kind: str = 'unknown'
    mode: str | None = None
    level: int | None = None
    half: int | None = None
    stars: int | None = None
    targets: tuple[tuple[str, Token], ...] = ()
    basis: dict = field(default_factory=dict)


def _unknown(reason):
    return Observation(basis=dict(schema=1, reason=reason))


def _inside(box, roi):
    return len(box) == 4 and all(a >= b for a, b in zip(box[:2], roi[:2])) and all(
        a <= b for a, b in zip(box[2:], roi[2:]))


def _clean(scene, confidence):
    image = getattr(scene, 'image', None)
    stamp = getattr(scene, 'captured_at', None)
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
            or image.shape[2] != 3 or image.shape[0] < 540 or image.shape[1] < 960
            or image.shape[0] * image.shape[1] > 16_777_216
            or abs(image.shape[1] / image.shape[0] - 16 / 9) > .02
            or type(stamp) not in (int, float) or not math.isfinite(stamp)
            or not 0 <= time.monotonic() - stamp <= 8
            or type(confidence) not in (int, float) or not math.isfinite(confidence)
            or not 0 <= confidence <= 1):
        return None
    observed = []
    for token in getattr(scene, 'tokens', ()):
        if (isinstance(token, Token) and type(token.text) is str and type(token.score) in (int, float)
                and math.isfinite(token.score) and confidence <= token.score <= 1
                and isinstance(token.box, (list, tuple)) and len(token.box) == 4
                and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in token.box)
                and token.box[0] < token.box[2] and token.box[1] < token.box[3]):
            observed.append(token)
    # Dialog text wins over a still visible lobby behind it.
    blocked = ('确认', '取消', '是否退出', '重新挑战', '挑战失败', '挑战成功', '获得奖励',
               '支付', '购买', '充值', '验证码', '连接失败', '重新连接', '加载中',
               '虚构叙事', '末日幻影', '模拟宇宙', '货币战争', '未解锁', '无法挑战', '未开放', '已锁定')
    if any(any(word in normalize(token.text) for word in blocked) for token in observed):
        return None
    tokens = [token for token in observed if token.score >= max(.85, confidence)]
    return Scene(tokens, image, scene.geometry, stamp)


@lru_cache(maxsize=1)
def _references():
    try:
        raw = (ASSET_ROOT / 'sources.json').read_bytes()
        if len(raw) > 128 * 1024:
            return {}
        data = json.loads(raw)
        if data.get('commit') != '7cf6c6bed474539485d3b1504077ac352866829f':
            return {}
        rows = data['images']
        result = {}
        for name, file in _FILES.items():
            entries = [r for r in rows if r.get('file') == file]
            if len(entries) != 1:
                return {}
            row = entries[0]
            content = (ASSET_ROOT / file).read_bytes()
            if (len(content) > 65536 or row['sha256'] != _HASHES[name]
                    or hashlib.sha256(content).hexdigest() != _HASHES[name]):
                return {}
            image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
            if image is None or [image.shape[1], image.shape[0]] != row['size']:
                return {}
            result[name] = image, row['sha256']
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def _nms(scores, width, height, threshold):
    ys, xs = np.where((scores >= threshold) &
                     (scores >= cv2.dilate(scores, np.ones((3, 3), np.uint8))))
    candidates = sorted(((float(scores[y, x]), int(x), int(y)) for y, x in zip(ys, xs)), reverse=True)
    selected = []
    for score, x, y in candidates[:100]:
        if not any(abs(x - a) < width * .75 and abs(y - b) < height * .75 for _, a, b in selected):
            selected.append((score, x, y))
    return selected


def _hits(scene, name, roi):
    reference = _references().get(name)
    if reference is None:
        return []
    image, _ = reference
    h, w = scene.image.shape[:2]
    scale = w / 1920
    image = cv2.resize(image, (max(1, round(image.shape[1] * scale)),
                              max(1, round(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    left, top, right, bottom = [round(v * size) for v, size in zip(roi, (w, h, w, h))]
    patch = scene.image[top:bottom, left:right]
    th, tw = image.shape[:2]
    if patch.shape[0] < th or patch.shape[1] < tw or image.std() < 8:
        return []
    values = cv2.matchTemplate(patch, image, cv2.TM_CCOEFF_NORMED)
    values = np.nan_to_num(values, nan=-1., posinf=-1., neginf=-1.)
    hits = []
    for score, x, y in _nms(values, tw, th, .96):
        observed = patch[y:y + th, x:x + tw]
        if (np.mean(np.abs(observed.astype(float) - image.astype(float))) > 20
                or observed.std() < image.std() * .80):
            continue
        hits.append(Token(name, score, ((left + x) / w, (top + y) / h,
                                       (left + x + tw) / w, (top + y + th) / h)))
    return hits


def _proof(name, token):
    return dict(asset=_FILES[name], sha256=_references()[name][1], box=list(token.box), score=token.score)


def _mode(scene, name, roi):
    hits = _hits(scene, name, roi)
    if len(hits) != 1:
        return None
    hit = hits[0]
    tokens = [t for t in scene.tokens if t.within(hit.box)]
    lines = []
    for token in sorted(tokens, key=lambda t: (t.center[1], t.box[0])):
        row = next((row for row in lines if min(row[0].box[3], token.box[3]) -
                    max(row[0].box[1], token.box[1]) >= .25 *
                    min(row[0].box[3] - row[0].box[1], token.box[3] - token.box[1])), None)
        if row is None:
            lines.append([token])
        else:
            row.append(token)
    words = tuple(''.join(normalize(t.text) for t in sorted(row, key=lambda t: t.box[0])) for row in lines)
    # These are the complete texts actually present in the pinned images.
    # A missing parent title/quote, reversed words or any extra text is not a
    # substring match. OCR may merge both title lines or split a printed line.
    allowed = {
        'title': (('忘却之庭', '混沌回忆'), ('忘却之庭混沌回忆',)),
        'caption': (('「混沌回忆」',), ('「混沌', '回忆」')),
    }
    if words not in allowed.get(name, ()):
        return None
    return hit


def _current_level(scene):
    import re
    values = []
    for token in scene.tokens:
        match = re.fullmatch(r'第(0?[1-9]|1[0-2])层', normalize(token.text))
        if match and _inside(token.box, (0, 0, 1, .38)):
            values.append((int(match[1]), token))
    return values[0] if len(values) == 1 else _AMBIGUOUS_LEVEL if values else None


def _stars(scene, label, all_labels):
    """Positive original star silhouettes only; absent stars never mean zero."""
    reference = _references().get('star')
    if reference is None:
        return None
    h, w = scene.image.shape[:2]
    roi = (label.box[0], label.box[1], label.box[0] + 120 / 1920, label.box[1] + 120 / 1080)
    if not _inside(roi, LEVEL_REGION) or any(t is not label and t.within(roi) for t in all_labels):
        return None
    x1, y1, x2, y2 = [round(v * size) for v, size in zip(roi, (w, h, w, h))]
    patch = scene.image[y1:y2, x1:x2]
    # The pinned upstream judge_stars explicitly filters this gold colour.
    gold = np.max(np.abs(patch.astype(np.int16) - np.array([112, 200, 255])), axis=2) <= 20
    shape = cv2.cvtColor(reference[0], cv2.COLOR_BGR2GRAY)
    shape = cv2.resize(shape, (max(1, round(shape.shape[1] * w / 1920)),
                               max(1, round(shape.shape[0] * w / 1920))), interpolation=cv2.INTER_NEAREST)
    shape = (shape > 127).astype(np.uint8) * 255
    values = cv2.matchTemplate(gold.astype(np.uint8) * 255, shape, cv2.TM_CCOEFF_NORMED)
    values = np.nan_to_num(values, nan=-1., posinf=-1., neginf=-1.)
    hits = _nms(values, shape.shape[1], shape.shape[0], .98)
    if not 1 <= len(hits) <= 3:
        return None
    boxes = []
    for score, x, y in hits:
        if x <= 0 or y <= 0 or x + shape.shape[1] >= patch.shape[1] - 1 or y + shape.shape[0] >= patch.shape[0] - 1:
            return None
        boxes.append(dict(box=[(x1 + x) / w, (y1 + y) / h,
                               (x1 + x + shape.shape[1]) / w, (y1 + y + shape.shape[0]) / h], score=score))
    return dict(count=len(hits), roi=list(roi), matches=boxes, sha256=reference[1])


def observe(scene, confidence=.65):
    import re
    clean = _clean(scene, confidence)
    if clean is None or not _references():
        return _unknown('invalid_stale_blocked_or_missing_reference')
    title = _mode(clean, 'title', (0, 0, .45, .35))
    current = _current_level(clean)
    if current is _AMBIGUOUS_LEVEL:
        return _unknown('ambiguous_current_level_header')
    groups = {key: _hits(clean, key, TEAM_REGION) for key in ('team1', 'team2', 'reset', 'switch')}
    caption = _mode(clean, 'caption', (.5, .75, 1, 1))
    if current and caption and all(len(v) == 1 for v in groups.values()):
        one, two = groups['team1'][0], groups['team2'][0]
        if one.center[1] < two.center[1] and abs(one.center[0] - two.center[0]) < .05:
            basis = dict(schema=1, page='team_setup', level_box=list(current[1].box),
                         matches=[_proof('caption', caption)] + [_proof(k, v[0]) for k, v in groups.items()],
                         team_feedback='unknown', execution_supported=False)
            return Observation('team_setup', MODE, current[0], basis=basis)
    if title is None or any(groups.values()):
        return _unknown('no_complete_lobby_or_unverified_team_setup')
    counters = [t for t in clean.tokens if _inside(t.box, (.35, 0, 1, .38))
                and re.fullmatch(r'(?:[0-9]|[12][0-9]|3[0-6])/36', normalize(t.text))]
    labels = [t for t in clean.tokens if _inside(t.box, LEVEL_REGION) and re.fullmatch(r'0[1-9]|1[0-2]', t.text)]
    if len(counters) != 1 or len(labels) < 2 or len({t.text for t in labels}) != len(labels):
        return _unknown('missing_or_ambiguous_counter_and_level_group')
    total = int(normalize(counters[0].text).split('/')[0])
    levels, targets = [], []
    for label in sorted(labels, key=lambda t: int(t.text)):
        stars = _stars(clean, label, labels)
        row = dict(level=int(label.text), label_box=list(label.box), stars=stars['count'] if stars else None,
                   star_source=stars, available=None)
        # No empty/locked/selected-state references exist. Positive gold stars
        # on this exact label provide only a previously reached level target.
        if stars:
            row['selection_reference'] = 'level_label_with_positive_gold_star_strip'
            targets.append(('select_level', label))
        levels.append(row)
    if sum(row['stars'] or 0 for row in levels) > total:
        return _unknown('level_stars_conflict_with_total')
    basis = dict(schema=1, page='lobby', matches=[_proof('title', title)], total_stars=total,
                 total_box=list(counters[0].box), levels=levels,
                 team_feedback='unknown', full_real_page_calibrated=False)
    if current:
        selected = next((row for row in levels if row['level'] == current[0]), None)
        if selected is None:
            return _unknown('current_level_not_in_observed_group')
        basis['level_box'] = list(current[1].box)
    stars = next((r['stars'] for r in levels if current and r['level'] == current[0]), None)
    return Observation('lobby', MODE, current[0] if current else None, stars=stars,
                       targets=tuple(targets), basis=basis)


def target(scene, intent, confidence=.65, level=None):
    if intent != 'select_level' or type(level) is not int or not 1 <= level <= 12:
        return None
    observation = observe(scene, confidence)
    if observation.kind != 'lobby':
        return None
    choices = [token for action, token in observation.targets if action == intent and int(token.text) == level]
    return choices[0] if len(choices) == 1 else None
