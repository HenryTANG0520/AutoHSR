"""Read the currently calibrated 4.6 Memory of Chaos crystal map."""
import re

import cv2
import numpy as np

from . import challenge_pages as pages
from .models import Token, normalize


LAYOUT = 'chaos_4_6_crystal_map'
SETUP_LAYOUT = 'chaos_4_6_crystal_setup'
CALIBRATED_LEVEL = 10
PERIOD = '物竞天择'
SETUP_TITLE = PERIOD + '其十'
_DIGITS = 'challenge.chaos_map.digits'
_HEADERS = (
    ('忘却之庭', (.039, .023, .118, .068)),
    ('混沌回忆', (.041, .054, .122, .098)),
    ('物竞天择', (.048, .102, .166, .172)),
    ('奇珍琳琅', (.081, .853, .178, .919)),
)
_LABELS = {
    8: (.074, .410, .163, .510),
    9: (.268, .486, .357, .585),
    10: (.447, .551, .537, .661),
    11: (.606, .405, .687, .489),
    12: (.810, .342, .890, .422),
}
_LOCKS = {11: (.605, .473, .690, .522), 12: (.813, .412, .893, .455)}
_BLOCKERS = tuple(word for word in pages._BLOCKED if word != '未解锁') + pages._SIDE_BLOCKED
_SETUP_TITLE_REGION = (.312, .099, .467, .159)
_SETUP_FIELDS = (
    _HEADERS[0],
    ('角色列表', (.053, .102, .126, .151)),
    ('预设编队', (.187, .102, .259, .151)),
    (SETUP_TITLE, _SETUP_TITLE_REGION),
    ('挑战目标', (.319, .278, .391, .322)),
    ('角色编队', (.319, .599, .392, .648)),
    ('建议属性', (.558, .653, .636, .708)),
    ('建议属性', (.558, .758, .636, .812)),
    ('「混沌回忆」', (.833, .882, .928, .937)),
)
_NODE_DIGITS = ((650, 736, 675, 774), (650, 850, 675, 888))
_RIM_ANGLES = np.arange(32) * (2 * np.pi / 32)
_RIM_RADII = np.arange(32, 44, .75)[:, None]
_RIM_X = (_RIM_RADII * np.cos(_RIM_ANGLES)).astype(np.float32)
_RIM_Y = (_RIM_RADII * np.sin(_RIM_ANGLES)).astype(np.float32)


def _one(tokens, text, region, minimum):
    matching = [token for token in tokens if normalize(token.text) == text and token.within(region)]
    if len(matching) != 1 or matching[0].score < minimum or not pages._inside(matching[0].box, region):
        return None
    return matching[0]


def _headers(scene, minimum):
    return tuple(_one(scene.tokens, name, roi, minimum) for name, roi in _HEADERS)


def collect_digits(scene, confidence, read_number):
    if _DIGITS in scene.field_reads:
        return
    view = pages._clean(scene, confidence, blockers=())
    minimum = max(.85, confidence)
    if view is None:
        return
    if all(_headers(view, minimum)):
        digits = _lock_digits(view, minimum, read_number)
    elif _one(view.tokens, SETUP_TITLE, _SETUP_TITLE_REGION, minimum):
        digits = _node_digits(view, minimum, read_number)
    else:
        return
    scene.field_reads[_DIGITS] = tuple(digits)


def _lock_digits(view, minimum, read_number):
    height, width = view.image.shape[:2]
    for number, region in _LOCKS.items():
        notice = _one(view.tokens, '未解锁', region, minimum)
        if notice is None or _one(view.tokens, str(number), _LABELS[number], minimum):
            continue
        left, top, right, _ = notice.box
        box = (left - .004, top - .053, right + .002, top - .003)
        x1, y1, x2, y2 = [round(value * size) for value, size in zip(box, (width, height, width, height))]
        digit = read_number(view.image[y1:y2, x1:x2])
        if isinstance(digit, Token) and digit.text == str(number) and digit.score >= minimum:
            yield Token(digit.text, digit.score, box)


def _node_digits(view, minimum, read_number):
    image = cv2.resize(view.image, (1920, 1080), interpolation=cv2.INTER_AREA)
    for node, (x1, y1, x2, y2) in enumerate(_NODE_DIGITS, 1):
        patch = cv2.resize(image[y1:y2, x1:x2], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        digit = read_number(patch)
        if isinstance(digit, Token) and digit.text == str(node) and digit.score >= minimum:
            yield Token(digit.text, digit.score, tuple(_box(x1, y1, x2, y2)))


def _box(x1, y1, x2, y2):
    return [x1 / 1920, y1 / 1080, x2 / 1920, y2 / 1080]


def _pixels(token):
    return [round(value * size) for value, size in zip(token.box, (1920, 1080, 1920, 1080))]


def _gray_stars(image, label, shape, digest):
    left, _, _, bottom = _pixels(label)
    top, edge = bottom - 1, bottom + 43
    matches = []
    for index in range(3):
        center = left + 23 + index * 33
        start = center - 21
        patch = image[top:edge, start:center + 21]
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        scores = cv2.matchTemplate(gray, shape, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < .73:
            return None
        sample = patch[y:y + 25, x:x + 25][shape > 127]
        blue, green, red = np.median(sample, axis=0)
        if blue < red - 7 or blue > 210 or green < 80 or red - green > 45:
            return None
        matches.append(dict(box=_box(start + x, top + y, start + x + 25, top + y + 25), score=float(score)))
    if max(row['box'][1] for row in matches) - min(row['box'][1] for row in matches) > .006:
        return None
    if any(pages._overlaps(a['box'], b['box']) for a, b in zip(matches, matches[1:])):
        return None
    return dict(count=3, matches=matches, shape_sha256=digest)


def _lines(gray, low=60, high=150):
    edges = cv2.Canny(gray, low, high)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 22, minLineLength=32, maxLineGap=5)
    return () if lines is None else tuple(tuple(map(int, line)) for line in lines.reshape(-1, 4))


def _crystal(image, label):
    left, top, _, bottom = _pixels(label)
    x1, y1, x2, y2 = max(0, left - 185), top - 156, left - 2, bottom + 120
    patch = image[y1:y2, x1:x2]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    bright = float(np.mean(hsv[:, :, 2] >= 210))
    color = float(np.mean((hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 175)))
    if bright < .045 or color < .07:
        return None
    lines = _lines(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY))
    facets = sum(abs(x2 - x1) >= 16 and abs(y2 - y1) >= 16 and np.hypot(x2 - x1, y2 - y1) >= 42
                 for x1, y1, x2, y2 in lines)
    if facets < 4:
        return None
    return dict(box=_box(x1, y1, x2, y2), bright_fraction=bright, color_fraction=color, facet_segments=int(facets))


def _lock_graphics(image, label, notice):
    left, label_top, right, label_bottom = _pixels(label)
    _, top, _, bottom = _pixels(notice)
    center = (left + right) // 2
    x0, y0, x1, y1 = center - 83, top - 85, center + 83, bottom + 17
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    left_line = right_line = base_line = False
    for a, b, c, d in _lines(gray, 26, 90):
        if c < a:
            a, b, c, d = c, d, a, b
        if c - a >= 65 and abs(b - d) <= 4 and a < 83 < c and bottom - 5 <= y0 + (b + d) / 2 <= bottom + 13:
            base_line = True
        if c - a >= 18 and 1.2 <= abs(d - b) / (c - a) <= 2.3:
            middle = (a + c) / 2
            left_line |= d < b and middle < 73
            right_line |= d > b and middle > 93
    middle = (label_top + label_bottom) // 2 + 6
    ring = cv2.cvtColor(image[middle - 130:middle + 130, center - 136:center + 136], cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(cv2.GaussianBlur(ring, (5, 5), 0), cv2.HOUGH_GRADIENT, 1.1, 17,
                               param1=70, param2=25, minRadius=82, maxRadius=128)
    ring_observed = circles is not None and any(abs(x - 136) < 22 and abs(y - 130) < 22
                                               for x, y, _ in circles.reshape(-1, 3))
    return dict(triangle=bool(left_line and right_line and base_line), box=_box(x0, y0, x1, y1),
                ring_observed=bool(ring_observed))


def observe(scene, confidence):
    view = pages._clean(scene, confidence, blockers=_BLOCKERS)
    if view is None:
        return None
    minimum = max(.85, confidence)
    words = tuple(normalize(token.text) for token in view.tokens) + pages._line_words(view.tokens, gap=.02)
    if any(word in text for text in words for word in (*_BLOCKERS, '虚构叙事', '末日幻影', '星启模式')):
        return None
    if any(normalize(token.text) == SETUP_TITLE for token in view.tokens):
        return _observe_setup(scene, view, minimum, words)
    headers = _headers(view, minimum)
    if not all(headers):
        return None
    locks = {level: _one(view.tokens, '未解锁', region, minimum) for level, region in _LOCKS.items()}
    if not all(locks.values()) or any('未解锁' in normalize(token.text) and token not in locks.values() for token in view.tokens):
        return None
    levels, origins = {}, {}
    for level, roi in _LABELS.items():
        name = f'{level:02d}'
        numeric = [token for token in view.tokens if token.within(roi) and re.fullmatch(r'[0-9]{2}', normalize(token.text))]
        if len(numeric) > 1:
            return None
        label = _one(view.tokens, name, roi, minimum)
        origins[level] = 'screen_ocr'
        if label is None and level in locks and not numeric:
            label = _one(scene.field_reads.get(_DIGITS, ()), name, roi, minimum)
            origins[level] = 'lock_number_ocr'
        if label is None:
            return None
        levels[level] = label
    reference = pages._references().get('star')
    if reference is None:
        return None
    shape = cv2.resize(cv2.cvtColor(reference[0], cv2.COLOR_BGR2GRAY), (25, 25), interpolation=cv2.INTER_NEAREST)
    image = cv2.resize(view.image, (1920, 1080), interpolation=cv2.INTER_AREA)
    rows, targets = [], []
    for level, label in levels.items():
        row = dict(level=level, label_box=list(label.box), label_source=origins[level], available=None, stars=None)
        if level in locks:
            notice = locks[level]
            row.update(available=False, appearance='locked', lock_box=list(notice.box),
                       lock_graphics=_lock_graphics(image, label, notice))
        else:
            gray = _gray_stars(image, label, shape, reference[1])
            crystal = _crystal(image, label)
            if gray is not None and crystal is not None:
                row.update(stars=0, appearance='gray_stars_and_crystal', gray_stars=gray, crystal=crystal)
        rows.append(row)
    calibrated = next(row for row in rows if row['level'] == CALIBRATED_LEVEL)
    if calibrated.get('appearance') == 'gray_stars_and_crystal' and all(
            row['lock_graphics']['triangle'] for row in rows if row['available'] is False):
        calibrated.update(available=True, selection_reference='same_period_level_label_observed_to_team_setup')
        targets.append(('select_level', levels[CALIBRATED_LEVEL]))
    basis = dict(schema=1, page='lobby', layout=LAYOUT, period=PERIOD, levels=rows,
                 header_boxes=[list(token.box) for token in headers], selected_level=None,
                 team_feedback='unknown', full_real_page_calibrated=False)
    return pages.Observation('lobby', pages.MODE, targets=tuple(targets), basis=basis)


def _setup_slots(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    rows = []
    for y in (754, 868):
        row = []
        for x in (1376, 1469, 1561, 1653):
            radial = cv2.remap(gray, x + _RIM_X, y + _RIM_Y, cv2.INTER_LINEAR).astype(np.int16)
            edges = np.abs(np.diff(radial, axis=0)).max(axis=0)
            quadrants = (edges >= 15).reshape(4, 8).sum(axis=1)
            if min(quadrants) < 5 or sum(quadrants) < 27:
                return None
            row.append(_box(x - 43, y - 43, x + 43, y + 43))
        rows.append(row)
    return rows


def _setup_level_glyph(image, title):
    # The whole line can drop the trailing 一 or 二. Verify six actual glyphs
    # and the visible gap that would otherwise contain a seventh glyph.
    x0, y0 = 609, 119
    hsv = cv2.cvtColor(image[y0:159, x0:903], cv2.COLOR_BGR2HSV)
    ink = cv2.inRange(hsv, (0, 0, 180), (180, 75, 255)) != 0
    columns = np.flatnonzero(ink.sum(axis=0) >= 2)
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 2) + 1)
    glyphs = []
    for group in groups:
        rows, _ = np.nonzero(ink[:, group])
        if len(rows) >= 15:
            glyphs.append((int(group[0]), int(rows.min()), int(group[-1]) + 1, int(rows.max()) + 1))
    if (len(glyphs) != 6 or not 628 <= x0 + glyphs[0][0] <= 646
            or any(not 23 <= r - l <= 37 or not 23 <= b - t <= 38 for l, t, r, b in glyphs)
            or any(not 28 <= b[0] - a[0] <= 41 for a, b in zip(glyphs, glyphs[1:]))):
        return None
    left, top, right, bottom = glyphs[-1]
    cross = ink[top:bottom, left:right]
    if (right + 43 > hsv.shape[1] or cross.sum(axis=0).max() < .75 * cross.shape[0]
            or cross.sum(axis=1).max() < .75 * cross.shape[1]
            or np.mean(hsv[top:bottom, right + 4:right + 43, 2] >= 100) < .95):
        return None
    box = _box(x0 + left, y0 + top, x0 + right, y0 + bottom)
    return box if pages._overlaps(box, title.box) else None


def _observe_setup(scene, view, minimum, words):
    if any(word in text for text in words for word in ('未解锁', '节点三', '通关星数', '返回忘却之庭')):
        return None
    titles = [token for token in view.tokens if token.within(_SETUP_TITLE_REGION)
              and (PERIOD in normalize(token.text) or re.fullmatch(r'第[0-9一二三四五六七八九十]+层', normalize(token.text)))]
    fields = [_one(view.tokens, text, region, minimum) for text, region in _SETUP_FIELDS]
    if len(titles) != 1 or not all(fields):
        return None
    digits = scene.field_reads.get(_DIGITS, ())
    nodes = []
    for node, xyxy in enumerate(_NODE_DIGITS, 1):
        region = _box(*xyxy)
        digit = _one(digits, str(node), region, minimum)
        if digit is None or any(token.within(region) and re.fullmatch(r'[1-3]', normalize(token.text))
                                and normalize(token.text) != str(node) for token in view.tokens):
            return None
        nodes.append(dict(node=node, digit_box=list(digit.box)))
    image = cv2.resize(view.image, (1920, 1080), interpolation=cv2.INTER_AREA)
    glyph = _setup_level_glyph(image, titles[0])
    slots = _setup_slots(image) if glyph is not None else None
    if slots is None:
        return None
    for row, boxes in zip(nodes, slots):
        row['visible_slot_boxes'] = boxes
    basis = dict(schema=1, page='team_setup', layout=SETUP_LAYOUT, period=PERIOD,
                 level_box=list(titles[0].box), level_glyph_box=glyph, field_boxes=[list(token.box) for token in fields],
                 nodes=nodes, team_feedback='unknown', execution_supported=False)
    return pages.Observation('team_setup', pages.MODE, CALIBRATED_LEVEL, basis=basis)
