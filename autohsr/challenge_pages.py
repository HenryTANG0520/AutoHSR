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
import re
import time

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .models import Scene, Token, normalize


MODE = 'memory_of_chaos'
FICTION = 'pure_fiction'
APOCALYPTIC = 'apocalyptic_shadow'
_MODE_WORDS = {MODE: '混沌回忆', FICTION: '虚构叙事', APOCALYPTIC: '末日幻影'}
_AMBIGUOUS_LEVEL = object()
ASSET_ROOT = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/challenge-ui'
LEVEL_REGION = (540 / 1920, 406 / 1080, 1696 / 1920, 922 / 1080)
TEAM_REGION = (592 / 1920, 432 / 1080, 1911 / 1920, 980 / 1080)


def _region(left, top, right, bottom):
    return left / 1920, top / 1080, right / 1920, bottom / 1080


# Fixed upstream xywh crops converted to edges in the 1920x1080 reference.
_SIDE_TITLE = _region(0, 1, 552, 213)
_FICTION_LEVELS = _region(331, 97, 1893, 895)
_FICTION_TEAMS = _region(592, 556, 848, 980)
_FICTION_CONTROLS = _region(617, 432, 1911, 942)
_FICTION_CAPTION = _region(1546, 962, 1889, 1024)
# A complete layer header must be separate from the portrait list and teams.
_FICTION_LEVEL_HEADER = _region(592, 0, 1911, 432)
_APOCALYPTIC_LEVELS = _region(330, 90, 1892, 1080)
_APOCALYPTIC_DETAIL = _region(1624, 804, 1916, 872)
_APOCALYPTIC_NODE_ONE = _region(963, 209, 1761, 461)
_APOCALYPTIC_NODES = _region(755, 203, 1769, 747)
_APOCALYPTIC_RESET = _region(1280, 115, 1495, 174)
_BLOCKED = ('确认', '取消', '是否退出', '重新挑战', '挑战失败', '挑战成功', '获得奖励',
            '支付', '购买', '充值', '验证码', '连接失败', '重新连接', '加载中',
            '模拟宇宙', '货币战争', '未解锁', '无法挑战', '未开放', '已锁定')
_SIDE_BLOCKED = ('选择最高解锁关卡', '开启故事', '已更新', '切换命途', '下一步', '前往编队',
                 '挑战结束', '前往节点二', '返回末日幻影', '返回虚构叙事',
                 '将清空当前挑战队伍', '特遣支援挑战队伍')
_FICTION_REFERENCES = frozenset(('fiction_title', 'fiction_caption', 'fiction_star', 'fiction_modal'))
_OPTIONAL_REFERENCES = _FICTION_REFERENCES | {
    'apocalyptic_title', 'fiction_result_return', 'apocalyptic_result_next', 'apocalyptic_result_return',
    'result_failure',
}

_FILES = {
    'title': 'screen/forgottenhall/memory_of_chaos.png',
    'team1': 'forgottenhall/team1.png', 'team2': 'forgottenhall/team2.png',
    'reset': 'forgottenhall/reset.png', 'switch': 'forgottenhall/switch.png',
    'star': 'forgottenhall/star.png', 'caption': 'forgottenhall/start.png',
    'fiction_title': 'screen/purefiction/purefiction.png',
    'fiction_caption': 'purefiction/start.png',
    'fiction_star': 'purefiction/star.png',
    'fiction_modal': 'purefiction/start_story.png',
    'apocalyptic_title': 'screen/apocalyptic/apocalyptic.png',
    'fiction_result_return': 'purefiction/back.png',
    'apocalyptic_result_next': 'apocalyptic/next_node.png',
    'apocalyptic_result_return': 'apocalyptic/back.png',
    'result_failure': 'purefiction/fail.png',
}
_HASHES = {
    'title': 'ae954987947ac37732b76e9da7e3e9dea1ff9200b6af08ea387effeb0708c5b4',
    'team1': 'b47cefb48b3df4a4f7522d1bcad3877d64c96fab79dd8e974bd068c4ed06bdc6',
    'team2': '69b67d8e7f985fc79dd830806a73d2704425df52f4bfd7e633da67de39ed2a3b',
    'reset': '84d8bc4f6bae35d242721f353b0d414571a29950e18b9b64186d9e06ab887032',
    'switch': '755a291709111ad4f340c55bd36b5f684369dbbd419caf89c7a012653e485a91',
    'star': '88eed2945f375bbd983dd52e5d7c8ff8a99b7e5b8b21bba7b335063fc57e728e',
    'caption': '0f8bc303e60c56ca5d8f3383f1c771ca530a106c561e2c843a929f5ccf67d031',
    'fiction_title': '94e5b67a38f1957268213321ecf4d5683a32b8e138c8913b1ed9d0b4be5fc857',
    'fiction_caption': '7d9471c5bed44b1d0cf29eb096962ef9733c141314e0a97b3f30ccc9e8dbe5c3',
    'fiction_star': 'ca15135a7ca2fabeeb97388ee3f77f46d21f084fdb6c13bb1e3907c9c8de4392',
    'fiction_modal': '96842542322542fc436551aa2a20f89ff4219002893523bdae46a6e2ecb68ead',
    'apocalyptic_title': 'b846e779820a8a7337e621ebe9b2e59ae006c26119d9299a7771db6982ce11a1',
    'fiction_result_return': 'f9994c2e977613f37330f7a26cbbbfd05e984044021984aa578a1d9126051b22',
    'apocalyptic_result_next': '1220e8197486e8f1972a7f0ef8111523c54b8df00c8752f326c96c11241fed2f',
    'apocalyptic_result_return': 'ddb1b2e5d43568f9823faf8ef8ce623f83dc588c229ff907918eeeb521ae95bd',
    'result_failure': 'e0bc3f80a2b7984e947cbf190114fa3dc31bbfd9f06bcbd4a6a380eeef816c33',
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


def _clean(scene, confidence, *, blockers=_BLOCKED):
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
    if any(any(word in normalize(token.text) for word in blockers) for token in observed):
        return None
    return Scene(observed, image, scene.geometry, stamp)


def _load_reference(rows, name, file):
    entries = [r for r in rows if r.get('file') == file]
    if len(entries) != 1:
        raise ValueError('ambiguous reference')
    row = entries[0]
    content = (ASSET_ROOT / file).read_bytes()
    if (len(content) > 65536 or row['sha256'] != _HASHES[name]
            or hashlib.sha256(content).hexdigest() != _HASHES[name]):
        raise ValueError('changed reference')
    image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if image is None or [image.shape[1], image.shape[0]] != row['size']:
        raise ValueError('invalid reference image')
    return image, row['sha256']


@lru_cache(maxsize=1)
def _references():
    errors = (OSError, ValueError, TypeError, KeyError, AttributeError)
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
            try:
                result[name] = _load_reference(rows, name, file)
            except errors:
                if name not in _OPTIONAL_REFERENCES:
                    raise
        return result
    except errors:
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


def _same_line(first, second):
    overlap = min(first.box[3], second.box[3]) - max(first.box[1], second.box[1])
    return overlap >= .25 * min(first.box[3] - first.box[1], second.box[3] - second.box[1])


def _line_words(tokens, gap=None):
    lines = []
    for token in sorted(tokens, key=lambda t: (t.center[1], t.box[0])):
        row = next((row for row in lines if _same_line(row[0], token)), None)
        if row is None:
            lines.append([token])
        else:
            row.append(token)
    words = []
    for row in lines:
        parts, right = [], None
        for token in sorted(row, key=lambda t: t.box[0]):
            if gap is not None and right is not None and token.box[0] - right > gap:
                words.append(''.join(parts))
                parts = []
            parts.append(normalize(token.text))
            right = max(right, token.box[2]) if right is not None else token.box[2]
        words.append(''.join(parts))
    return tuple(words)


def _mode(scene, name, roi):
    hits = _hits(scene, name, roi)
    if len(hits) != 1:
        return None
    hit = hits[0]
    words = _line_words(t for t in scene.tokens if t.within(hit.box))
    # These are the complete texts actually present in the pinned images.
    # A missing parent title/quote, reversed words or any extra text is not a
    # substring match. OCR may merge both title lines or split a printed line.
    allowed = {
        'title': (('忘却之庭', '混沌回忆'), ('忘却之庭混沌回忆',)),
        'caption': (('「混沌回忆」',), ('「混沌', '回忆」')),
        'fiction_title': (('虚构叙事',),),
        'fiction_caption': (('进入故事',),),
        'apocalyptic_title': (('末日幻影',),),
    }
    if words not in allowed.get(name, ()):
        return None
    return hit


def _split_level_headers(tokens, pattern):
    prefix = re.compile(r'第[0-9０-９]{0,2}')
    for first in tokens:
        text = normalize(first.text)
        if not prefix.fullmatch(text):
            continue
        right = sorted((t for t in tokens if t is not first and t.box[0] >= first.box[2] - .003
                        and _same_line(first, t)), key=lambda t: t.box[0])
        parts = [first]
        for part in right[:3]:
            if not -.003 <= part.box[0] - parts[-1].box[2] <= .02:
                break
            parts.append(part)
            text += normalize(part.text)
            if re.fullmatch(pattern, text):
                box = (first.box[0], min(t.box[1] for t in parts),
                       part.box[2], max(t.box[3] for t in parts))
                yield Token(text, min(t.score for t in parts), box)
                break
            if not prefix.fullmatch(text):
                break


def _current_level(scene, region=(0, 0, 1, .38), pattern=r'第(0?[1-9]|1[0-2])层', *, split=False):
    tokens = tuple(token for token in scene.tokens if _inside(token.box, region))
    if split:
        tokens += tuple(_split_level_headers(tokens, pattern))
    values = []
    for token in tokens:
        match = re.fullmatch(pattern, normalize(token.text))
        if match:
            values.append((int(match[1]), token))
    return values[0] if len(values) == 1 else _AMBIGUOUS_LEVEL if values else None


def _star_strip(label):
    left, top = label.box[:2]
    return left, top, left + 120 / 1920, top + 120 / 1080


def _stars(scene, label, all_labels, *, name='star', region=LEVEL_REGION, bgr=(112, 200, 255)):
    """Positive original star silhouettes only; absent stars never mean zero."""
    reference = _references().get(name)
    if reference is None:
        return None
    h, w = scene.image.shape[:2]
    roi = _star_strip(label)
    if not _inside(roi, region) or any(t is not label and t.within(roi) for t in all_labels):
        return None
    x1, y1, x2, y2 = [round(v * size) for v, size in zip(roi, (w, h, w, h))]
    patch = scene.image[y1:y2, x1:x2]
    # Each pinned upstream judge_stars uses a mode-specific gold colour.
    gold = np.max(np.abs(patch.astype(np.int16) - np.array(bgr)), axis=2) <= 20
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
    collected = _clean(scene, confidence)
    if collected is None or not (references := _references()):
        return _unknown('invalid_stale_blocked_or_missing_reference')
    # Collected text may veto an action before it reaches the stricter
    # positive threshold. Close fragments in the same OCR row can veto too.
    words = tuple(normalize(t.text) for t in collected.tokens) + _line_words(collected.tokens, gap=.02)
    modes = {mode for mode, name in _MODE_WORDS.items() if any(name in word for word in words)}
    if len(modes) > 1:
        return _unknown('conflicting_modes')
    minimum = max(.85, confidence)
    clean = Scene([t for t in collected.tokens if t.score >= minimum],
                  collected.image, collected.geometry, collected.captured_at)
    if modes == {MODE}:
        return _observe_chaos(clean)

    fiction_title = fiction_caption = apocalypse_title = None
    if not modes or FICTION in modes:
        fiction_title = _mode(clean, 'fiction_title', _SIDE_TITLE)
        fiction_caption = _mode(clean, 'fiction_caption', _FICTION_CAPTION)
    if not modes or APOCALYPTIC in modes:
        apocalypse_title = _mode(clean, 'apocalyptic_title', _SIDE_TITLE)
    if fiction_title or fiction_caption:
        modes.add(FICTION)
    if apocalypse_title or any(word in ('节点一', '节点二') for word in words):
        modes.add(APOCALYPTIC)
    if len(modes) > 1:
        return _unknown('conflicting_modes')
    if modes and any(fragment in word for word in words for fragment in _BLOCKED + _SIDE_BLOCKED):
        return _unknown('challenge_transition_or_dialog')
    if FICTION in modes:
        if not _FICTION_REFERENCES.issubset(references):
            return _unknown('missing_fiction_reference')
        return _observe_fiction(collected, minimum, fiction_title, fiction_caption)
    if APOCALYPTIC in modes:
        return _observe_apocalyptic(collected, minimum, apocalypse_title, words)
    return _observe_chaos(clean)


def _observe_chaos(clean):
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


def _short_levels(scene, region):
    labels = [t for t in scene.tokens if _inside(t.box, region) and re.fullmatch(r'0[1-4]', t.text)]
    if (len({t.text for t in labels}) != len(labels)
            or any(_overlaps(a.box, b.box) for index, a in enumerate(labels) for b in labels[index + 1:])):
        return []
    return sorted(labels, key=lambda t: int(t.text))


def _overlaps(first, second):
    return all(max(first[i], second[i]) < min(first[i + 2], second[i + 2]) for i in (0, 1))


def _observe_fiction(scene, minimum, title, caption):
    if (title or caption) and _hits(scene, 'fiction_modal', (0, 0, 1, 1)):
        return _unknown('fiction_story_dialog')
    current = _current_level(scene, _FICTION_LEVEL_HEADER, r'第([0-9０-９]{1,2})层', split=True)
    if current is _AMBIGUOUS_LEVEL or (current and not 1 <= current[0] <= 4):
        return _unknown('ambiguous_or_out_of_range_fiction_level')
    if current and current[1].score < minimum:
        current = None
    labels = _short_levels(scene, _FICTION_LEVELS)
    positive_labels = [label for label in labels if label.score >= minimum]
    teams = [_hits(scene, name, _FICTION_TEAMS) for name in ('team1', 'team2')]
    controls = {name: _hits(scene, name, _FICTION_CONTROLS) for name in ('reset', 'switch')}
    if caption or any(teams) or any(controls.values()):
        if (not caption or any(len(hits) != 1 for hits in teams) or not any(controls.values())
                or any(len(hits) > 1 for hits in controls.values())):
            return _unknown('incomplete_fiction_team_setup')
        if title and len(positive_labels) >= 2:
            return _unknown('conflicting_fiction_lobby_and_setup')
        one, two = teams[0][0], teams[1][0]
        if one.box[3] > two.box[1] or abs(one.center[0] - two.center[0]) >= .05:
            return _unknown('unpaired_fiction_team_headers')
        matches = [_proof('fiction_caption', caption), _proof('team1', one), _proof('team2', two)]
        matches.extend(_proof(name, hits[0]) for name, hits in controls.items() if hits)
        basis = dict(schema=1, page='team_setup', matches=matches, team_feedback='unknown',
                     role_availability='unknown', slot_feedback='unknown', execution_supported=False)
        if current:
            basis['level_box'] = list(current[1].box)
        return Observation('team_setup', FICTION, current[0] if current else None, basis=basis)

    if title is None or len(positive_labels) < 2:
        return _unknown('no_complete_fiction_lobby')
    if current and all(int(label.text) != current[0] for label in positive_labels):
        return _unknown('current_level_not_in_observed_group')
    levels, targets = [], []
    for label in positive_labels:
        stars = (_stars(scene, label, labels, name='fiction_star', region=_FICTION_LEVELS, bgr=(95, 198, 255))
                 if _inside(label.box, _star_strip(label)) else None)
        if stars and any(_overlaps(hit['box'], _star_strip(other)) for hit in stars['matches']
                         for other in labels if other is not label):
            stars = None
        row = dict(level=int(label.text), label_box=list(label.box), stars=stars['count'] if stars else None,
                   star_source=stars, available=None)
        if stars:
            row['selection_reference'] = 'level_label_with_positive_gold_star_strip'
            targets.append(('select_level', label))
        levels.append(row)
    basis = dict(schema=1, page='lobby', matches=[_proof('fiction_title', title)], levels=levels,
                 team_feedback='unknown', full_real_page_calibrated=False)
    if current:
        basis['level_box'] = list(current[1].box)
    stars = next((row['stars'] for row in levels if current and row['level'] == current[0]), None)
    return Observation('lobby', FICTION, current[0] if current else None, stars=stars,
                       targets=tuple(targets), basis=basis)


def _exact(scene, word, region):
    return [t for t in scene.tokens if normalize(t.text) == word and _inside(t.box, region)]


def _observe_apocalyptic(scene, minimum, title, words):
    one = _exact(scene, '节点一', _APOCALYPTIC_NODES)
    two = _exact(scene, '节点二', _APOCALYPTIC_NODES)
    reset = _hits(scene, 'reset', _APOCALYPTIC_RESET)
    detail = _exact(scene, '更换编队', _APOCALYPTIC_DETAIL)
    if one or two or reset:
        if (detail or len(one) != 1 or len(two) != 1 or len(reset) != 1
                or min(one[0].score, two[0].score) < minimum
                or not _inside(one[0].box, _APOCALYPTIC_NODE_ONE) or one[0].box[3] > two[0].box[1]):
            return _unknown('incomplete_apocalyptic_node_setup')
        basis = dict(schema=1, page='node_setup', matches=[_proof('reset', reset[0])],
                     nodes=[dict(node=1, label_box=list(one[0].box)), dict(node=2, label_box=list(two[0].box))],
                     selected_node=None, team_feedback='unknown', role_availability='unknown',
                     slot_feedback='unknown', execution_supported=False)
        return Observation('node_setup', APOCALYPTIC, basis=basis)
    if title is None or len(detail) > 1:
        return _unknown('unverified_apocalyptic_title_or_detail')
    basis = dict(schema=1, matches=[_proof('apocalyptic_title', title)], execution_supported=False)
    if detail:
        captions = _line_words((t for t in scene.tokens if _inside(t.box, _APOCALYPTIC_DETAIL)), gap=.02)
        if any('前往挑战' in word for word in captions):
            return _unknown('ambiguous_apocalyptic_challenge_caption')
        if detail[0].score < minimum:
            return _unknown('unverified_apocalyptic_detail')
        basis.update(page='level_detail', change_team_caption_box=list(detail[0].box))
        return Observation('level_detail', APOCALYPTIC, basis=basis)
    # The same caption may lead to setup or start battle. It cannot establish
    # a detail page, even if the lobby title is still visible behind it.
    if any('前往挑战' in word for word in words):
        return _unknown('ambiguous_apocalyptic_challenge_caption')
    labels = [t for t in _short_levels(scene, _APOCALYPTIC_LEVELS) if t.score >= minimum]
    if len(labels) < 2:
        return _unknown('no_apocalyptic_level_group')
    basis.update(page='lobby', levels=[dict(level=int(t.text), label_box=list(t.box),
                                          stars=None, available=None) for t in labels])
    return Observation('lobby', APOCALYPTIC, basis=basis)


def target(scene, intent, confidence=.65, level=None):
    if intent != 'select_level' or type(level) is not int or not 1 <= level <= 12:
        return None
    observation = observe(scene, confidence)
    if observation.kind != 'lobby':
        return None
    choices = [token for action, token in observation.targets if action == intent and int(token.text) == level]
    return choices[0] if len(choices) == 1 else None
