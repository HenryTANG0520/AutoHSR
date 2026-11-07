"""Read-only redemption page contracts; no input or result-account attribution.

Reference: March7thAssistant 7cf6c6b tasks/daily/redemption.py and
assets/config/screens.json. Five unmodified upstream title/control crops only
corroborate local graphics. They do not establish a complete form or a result.
"""
from dataclasses import dataclass
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

ASSET_ROOT = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/redemption-ui'
ASSET_HASHES = {
    'title': 'ce1aaed2d948099704694f1ea23edac6d9d0490d3ef61b5408513e51866dff3a',
    'more': 'b382583d7e01d5e197232b3629f5e873c05afc2a38b91e4df255b1167cefa0b4',
    'paste': '91759b298da27844a960bdfb74aef19c8b0f50a6b7846b9e0f6cc5f633f3767d',
    'clear': 'c3b520b09db5d5d1d1854b52d0a97ef92b195426ddb4ba3e9b3ce657bded76ed',
    'confirm': 'fca9cb914730336a2c8c58a8c969f329825b3e367d23372e649b49918cb2ad9e',
}
PHONE_HEADER = (.55, 0, 1, .35)
MORE_MENU = (1261 / 1920, 1 / 1080, 1813 / 1920, 421 / 1080)
_MORE_CAPSULE_SCAN = (.845, .053, .976, .153)
_MORE_CAPSULE_CENTER = (.891, .081, .928, .119)
_EXPANDED_COLUMN = (.782, .099, .876, .361)
_CURRENT_PHONE_LEVEL = (.656, .213, .762, .274)
_CURRENT_PHONE_GRID = (
    ('好友', (.809, .353, .859, .405)), ('委托', (.878, .353, .927, .405)),
    ('成就', (.878, .474, .928, .524)), ('无名勋礼', (.732, .590, .801, .646)),
    ('指南', (.674, .711, .724, .764)),
)
PLACEHOLDERS = ('请输入兑换码', '请在此输入兑换码')
_NAVIGATION_PLACEHOLDERS = tuple(label + ending for label in PLACEHOLDERS for ending in ('', '...', '…', '⋯'))
_NAVIGATION_MODAL = (.20, .29, .80, .71)
_CURRENT_EMPTY_TITLE = (.443, .314, .557, .386)
_CURRENT_EMPTY_PLACEHOLDER = (.258, .467, .405, .509)
_CURRENT_EMPTY_PASTE = (.706, .465, .746, .511)
_CURRENT_EMPTY_CANCEL = (.371, .627, .427, .682)
_CURRENT_EMPTY_CONFIRM = (.589, .627, .646, .682)
STATUSES = {'兑换成功': 'redeemed', '兑换码已过期': 'expired',
            '无效的兑换码': 'invalid', '兑换码已被使用': 'already_used'}
FIELD_KEY = 'redemption.code'


@dataclass(frozen=True)
class Form:
    input_target: Token
    field_roi: tuple
    current_code: str | None
    empty: bool
    confirm_target: Token | None
    source_digest: str

    @property
    def basis(self):
        return dict(page='redemption_form', form_digest=self.source_digest, field_roi=list(self.field_roi),
                    input_box=list(self.input_target.box),
                    confirm_box=list(self.confirm_target.box) if self.confirm_target is not None else None,
                    code_sha256=hashlib.sha256(self.current_code.encode('utf8')).hexdigest()
                    if self.current_code is not None else None, empty=self.empty)


@dataclass(frozen=True)
class Result:
    status: str = 'unknown'
    close_target: Token | None = None
    key: str | None = None
    source_digest: str = ''

    @property
    def basis(self):
        return dict(page='redemption_result', status=self.status, result_digest=self.source_digest,
                    close_box=list(self.close_target.box) if self.close_target is not None else None, key=self.key)


def _inside(box, roi, margin=0):
    return (box[0] >= roi[0] + margin and box[1] >= roi[1] + margin and
            box[2] <= roi[2] - margin and box[3] <= roi[3] - margin)


def _valid_token(token, confidence):
    return (isinstance(token, Token) and type(token.score) in (int, float) and math.isfinite(token.score) and
            max(.85, confidence) <= token.score <= 1 and isinstance(token.box, (tuple, list)) and
            len(token.box) == 4 and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in token.box) and
            token.box[0] < token.box[2] and token.box[1] < token.box[3])


def _scene(scene, confidence):
    image = getattr(scene, 'image', None)
    captured = getattr(scene, 'captured_at', None)
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or
            image.shape[2] != 3 or image.shape[0] < 540 or image.shape[1] < 960 or
            image.shape[0] * image.shape[1] > 16777216 or type(captured) not in (int, float) or
            not math.isfinite(captured) or not 0 <= time.monotonic() - captured <= 8 or
            type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        return None
    tokens = [token for token in scene.tokens if _valid_token(token, confidence)]
    clean = Scene(tokens, image, scene.geometry, captured, scene.field_reads)
    # Redeeming a code is not a purchase. A payment/recovery dialog always wins
    # over any form or phone text still visible behind it.
    blocked = ('支付', '付款', '充值', '确认购买', '是否购买', '消耗星琼', '使用星琼',
               '使用燃料', '补充开拓力', '兑换开拓力', '星琼不足', '验证码', '扫码登录')
    if any(token.within((.1, .1, .94, .95)) and any(word in normalize(token.text) for word in blocked)
           for token in tokens):
        return None
    return clean


@lru_cache(maxsize=5)
def _template(name):
    try:
        raw = (ASSET_ROOT / (name + '.png')).read_bytes()
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != ASSET_HASHES[name]:
            return None
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    except (OSError, KeyError, ValueError):
        return None


def _matches(scene, name, roi=(0, 0, 1, 1), *, minimum=.96):
    original = _template(name)
    if original is None:
        return []
    h, w = scene.image.shape[:2]
    scale = w / 1920
    sample = cv2.resize(original, (max(1, round(original.shape[1] * scale)),
                                  max(1, round(original.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    mask = sample[:, :, 3] if sample.ndim == 3 and sample.shape[2] == 4 else None
    sample = sample[:, :, :3] if sample.ndim == 3 else cv2.cvtColor(sample, cv2.COLOR_GRAY2BGR)
    left, top, right, bottom = (round(value * size) for value, size in zip(roi, (w, h, w, h)))
    patch = scene.image[top:bottom, left:right]
    sh, sw = sample.shape[:2]
    if patch.shape[0] < sh or patch.shape[1] < sw or np.std(sample) < 8:
        return []
    scores = cv2.matchTemplate(patch, sample, cv2.TM_CCORR_NORMED if mask is not None else cv2.TM_CCOEFF_NORMED,
                               mask=mask)
    scores = np.nan_to_num(scores, nan=-1., posinf=-1., neginf=-1.)
    ys, xs = np.where((scores >= minimum) & (scores >= cv2.dilate(scores, np.ones((3, 3), np.uint8))))
    candidates = sorted(((float(scores[y, x]), int(x), int(y)) for y, x in zip(ys, xs)), reverse=True)
    hits, centers = [], []
    selected = mask > 0 if mask is not None else np.ones((sh, sw), dtype=bool)
    for score, x, y in candidates[:100]:
        if any(abs(x - old_x) < sw * .75 and abs(y - old_y) < sh * .75 for old_x, old_y in centers):
            continue
        current = patch[y:y + sh, x:x + sw]
        # Correlation alone also accepts a disabled/dimmed glyph. Preserve the
        # reference's visible contrast and local intensity before any target.
        if (np.mean(np.abs(current.astype(float)[selected] - sample.astype(float)[selected])) > 26 or
                np.std(current[selected]) < np.std(sample[selected]) * .70):
            continue
        centers.append((x, y))
        hits.append(Token('redemption_' + name, score,
                          ((left + x) / w, (top + y) / h, (left + x + sw) / w, (top + y + sh) / h)))
    return hits


def _unique(tokens, labels, roi=(0, 0, 1, 1)):
    labels = {normalize(value) for value in labels}
    matches = [token for token in tokens if token.within(roi) and normalize(token.text) in labels]
    return matches[0] if len(matches) == 1 else None


def phone(scene, confidence=.65):
    clean = _scene(scene, confidence)
    # The live phone can OCR the label and its adjacent level as one token.
    return bool(clean and any(token.within((.55, .05, .99, .35))
                              and re.fullmatch(r'开拓等级(?:[0-9]{1,3})?', normalize(token.text))
                              for token in clean.tokens) and
                clean.has(('委托', '星际和平指南', '指南', '无名勋礼'), (.55, .25, 1, 1), exact=True) and
                not clean.has(('兑换码', '兑换成功', '请输入兑换码'), (.15, .15, .85, .85), exact=True))


def _current_phone_grid(scene):
    levels = [token for token in scene.tokens if token.within(_CURRENT_PHONE_LEVEL)
              and re.fullmatch(r'开拓等级(?:[0-9]{1,3})?', normalize(token.text))]
    return len(levels) == 1 and all(_unique(scene.tokens, (label,), region) is not None
                                    for label, region in _CURRENT_PHONE_GRID)


def _more_ellipsis(dark):
    height, width = dark.shape
    left, right = round(.23 * width), round(.77 * width)
    top, bottom = round(.23 * height), round(.77 * height)
    _, _, stats, centers = cv2.connectedComponentsWithStats(dark[top:bottom, left:right].astype(np.uint8))
    if len(stats) != 4:
        return False
    areas = stats[1:, cv2.CC_STAT_AREA]
    if max(areas) > 2.25 * min(areas):
        return False
    for _, _, w, h, area in stats[1:]:
        if (not .055 <= w / height <= .23 or not .055 <= h / height <= .23
                or not .5 <= w / h <= 2 or area < .5 * w * h):
            return False
    xs = sorted((x + left + .5) / width for x, _ in centers[1:])
    ys = [(y + top + .5) / height for _, y in centers[1:]]
    first, second = xs[1] - xs[0], xs[2] - xs[1]
    return (.45 <= xs[1] <= .55 and .068 <= first <= .128 and .068 <= second <= .128
            and abs(first - second) <= .025 and .40 <= min(ys) <= max(ys) <= .60 and max(ys) - min(ys) <= .085)


def _more_capsules(scene):
    # The two 4.6 closed states preserve the contour and ellipsis geometry at different sizes.
    height, width = scene.image.shape[:2]
    left, top, right, bottom = (round(value * size) for value, size in zip(_MORE_CAPSULE_SCAN,
                                                                        (width, height, width, height)))
    patch = scene.image[top:bottom, left:right]
    low, high = patch.min(axis=2), patch.max(axis=2)
    white = (low >= 230) & (high - low <= 18)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8))
    matches = []
    for index, component in enumerate(stats[1:], 1):
        x, y, w, h, area = map(int, component)
        if (not .030 <= w / width <= .043 or not .026 <= h / height <= .039 or not 1.85 <= w / h <= 2.42
                or not .78 <= area / (w * h) <= .94 or not 0 < x < x + w < patch.shape[1]
                or not 0 < y < y + h < patch.shape[0]):
            continue
        shape = labels[y:y + h, x:x + w] == index
        top_edge, bottom_edge = shape[round(.07 * (h - 1))], shape[round(.93 * (h - 1))]
        if not (.58 <= top_edge.mean() <= .89 and .58 <= bottom_edge.mean() <= .89
                and shape[round(.34 * (h - 1))].mean() >= .91 and shape[round(.66 * (h - 1))].mean() >= .91):
            continue
        if _more_ellipsis(high[y:y + h, x:x + w] <= 120):
            matches.append(Token('redemption_more', 1., ((left + x) / width, (top + y) / height,
                                                         (left + x + w) / width, (top + y + h) / height)))
    return matches


def phone_more_target(scene, confidence=.65):
    clean = _scene(scene, confidence)
    if not clean or not phone(scene, confidence):
        return None
    hits = _matches(clean, 'more', PHONE_HEADER)
    if len(hits) > 1:
        return None
    capsules = _more_capsules(clean)
    if hits:
        x, y = hits[0].center
        if any(not _inside((x, y, x, y), capsule.box) for capsule in capsules):
            return None
        return hits[0]
    if (len(capsules) != 1 or not capsules[0].within(_MORE_CAPSULE_CENTER)
            or not _current_phone_grid(clean) or _unique(clean.tokens, ('合成',), (.810, .474, .861, .524)) is None
            or clean.has(('漫游签证', '手机装饰', '开拓穿搭', '兑换码', '确认', '取消', '提示', '点击空白处关闭'), exact=True)):
        return None
    return capsules[0]


def _expanded_more_menu(scene, visa, entry):
    # The open 4.6 menu hides the closed ellipsis and the synthesis label.
    if scene.has(('确认', '取消', '提示', '点击空白处关闭', '请输入兑换码'), exact=True):
        return False
    if not _current_phone_grid(scene):
        return False
    decoration = _unique(scene.tokens, ('手机装饰',), MORE_MENU)
    outfit = _unique(scene.tokens, ('开拓穿搭',), MORE_MENU)
    if decoration is None or outfit is None:
        return False
    rows = (visa, decoration, outfit, entry)
    if any(not row.within(_EXPANDED_COLUMN) for row in rows):
        return False
    columns = [row.center[0] for row in rows]
    gaps = [lower.center[1] - upper.center[1] for upper, lower in zip(rows, rows[1:])]
    return (max(columns) - min(columns) <= .045 and min(gaps) >= .045 and max(gaps) <= .088
            and max(gaps) - min(gaps) <= .027
            and all(upper.box[3] < lower.box[1] for upper, lower in zip(rows, rows[1:])))


def redemption_entry(scene, confidence=.65):
    clean = _scene(scene, confidence)
    if clean is None:
        return None
    entry = _unique(clean.tokens, ('兑换码',), MORE_MENU)
    visa = _unique(clean.tokens, ('漫游签证',), MORE_MENU)
    menu = {normalize(token.text) for token in clean.tokens if token.within((.55, .25, 1, 1)) and
            normalize(token.text) in ('委托', '星际和平指南', '指南', '无名勋礼', '好友', '成就')}
    if entry is None or visa is None or len(menu) < 2 or abs(entry.center[0] - visa.center[0]) > .08:
        return None
    span = abs(entry.center[1] - visa.center[1])
    if not .015 <= span <= .23:
        return None
    if span <= .18:
        return entry if len(_matches(clean, 'more', PHONE_HEADER)) == 1 else None
    return entry if _expanded_more_menu(clean, visa, entry) else None


def _title_hit(clean, title):
    hits = [hit for hit in _matches(clean, 'title') if _inside((title.center[0], title.center[1],
            title.center[0], title.center[1]), hit.box)]
    return hits[0] if len(hits) == 1 else None


def _confirm(clean, token):
    hits = [hit for hit in _matches(clean, 'confirm') if hit.box[0] <= token.center[0] <= hit.box[2]
            and hit.box[1] <= token.center[1] <= hit.box[3]]
    return hits[0] if len(hits) == 1 else None


def _shell(clean):
    title = _unique(clean.tokens, ('兑换码',))
    cancel = _unique(clean.tokens, ('取消',))
    confirm = _unique(clean.tokens, ('确认',))
    if (title is None or cancel is None or confirm is None or _title_hit(clean, title) is None or
            cancel.center[0] >= confirm.center[0] or title.box[3] >= min(cancel.box[1], confirm.box[1]) or
            abs(cancel.center[1] - confirm.center[1]) > max(cancel.box[3] - cancel.box[1], confirm.box[3] - confirm.box[1]) * 1.5):
        return None
    return title, cancel, confirm


def _geometry(clean):
    shell = _shell(clean)
    if shell is None:
        return None
    title, cancel, confirm = shell
    band = (.05, title.box[3], .95, min(cancel.box[1], confirm.box[1]))
    icons = [(name, hit) for name in ('paste', 'clear') for hit in _matches(clean, name, band)]
    if len(icons) != 1:
        return None
    name, icon = icons[0]
    h, w = clean.image.shape[:2]
    x1, y1, x2, y2 = (round(value * size) for value, size in zip(band, (w, h, w, h)))
    patch = clean.image[y1:y2, x1:x2]
    ix, iy = round(icon.box[0] * w), round(icon.box[1] * h)
    iw, ih = max(1, round((icon.box[2] - icon.box[0]) * w)), max(1, round((icon.box[3] - icon.box[1]) * h))
    # Recover the current field's actual light background connected to the
    # matched icon corner. No fixed form coordinates or guessed empty region.
    background = clean.image[iy, ix].astype(float)
    if np.min(background) < 210:
        return None
    mask = (np.max(np.abs(patch.astype(float) - background), axis=2) <= 16).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    label = int(labels[iy - y1, ix - x1])
    if label == 0:
        return None
    left, top, width, height, area = map(int, stats[label])
    if (left <= 1 or top <= 1 or left + width >= patch.shape[1] - 1 or top + height >= patch.shape[0] - 1 or
            not max(iw * 6, w * .18) <= width <= w * .84 or not ih <= height <= ih * 5 or
            not 3 <= width / height <= 30 or area < width * height * .72 or
            not left + width * .70 <= ix - x1 <= left + width - iw):
        return None
    pad = max(2, round(ih * .18))
    roi = ((x1 + left + pad) / w, (y1 + top + pad) / h,
           (ix - pad) / w, (y1 + top + height - pad) / h)
    if roi[2] <= roi[0] or roi[3] <= roi[1]:
        return None
    target = Token('兑换码输入框', min(title.score, icon.score), roi)
    return roi, target, shell, name


def field_region(scene, confidence=.65):
    clean = _scene(scene, confidence)
    geometry = _geometry(clean) if clean is not None else None
    return geometry[0] if geometry is not None else None


def _code(clean, roi, confidence):
    fields = clean.field_reads.get(FIELD_KEY)
    if not isinstance(fields, (tuple, list)) or len(fields) != 2:
        return None
    h, w = clean.image.shape[:2]
    values = []
    for token in fields:
        if (not _valid_token(token, confidence) or
                any(abs(a - b) > 1 / min(w, h) for a, b in zip(token.box, roi)) or
                not isinstance(token.text, str) or not re.fullmatch(r'[A-Za-z0-9\u3400-\u9fff]{1,64}', token.text)):
            return None
        values.append(token.text)
    if values[0] != values[1] or values[0] in PLACEHOLDERS:
        return None
    for token in clean.tokens:
        if not _inside(token.box, roi):
            continue
        if any(mark in token.text for mark in ('…', '...', '⋯')):
            return None
        if re.fullmatch(r'[A-Za-z0-9\u3400-\u9fff]{1,64}', token.text) and token.text not in PLACEHOLDERS and token.text != values[0]:
            return None
    return values[0]


def _proof(clean, boxes, detail):
    h, w = clean.image.shape[:2]
    region = (max(0, min(box[0] for box in boxes) - .02), max(0, min(box[1] for box in boxes) - .02),
              min(1, max(box[2] for box in boxes) + .02), min(1, max(box[3] for box in boxes) + .02))
    x1, y1, x2, y2 = (round(value * size) for value, size in zip(region, (w, h, w, h)))
    value = dict(region=region, detail=detail, pixels=hashlib.sha256(clean.image[y1:y2, x1:x2].tobytes()).hexdigest())
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf8')).hexdigest()


def read_form(scene, confidence=.65):
    clean = _scene(scene, confidence)
    geometry = _geometry(clean) if clean is not None else None
    if geometry is None:
        return None
    roi, target, shell, icon_kind = geometry
    placeholders = [token for token in clean.tokens if token.text in PLACEHOLDERS and _inside(token.box, roi)]
    if len(placeholders) > 1:
        return None
    code = _code(clean, roi, confidence)
    if placeholders and (code is not None or icon_kind != 'paste'):
        return None
    empty = bool(placeholders)
    if empty:
        code = None
    confirm = _confirm(clean, shell[2]) if code is not None and not empty else None
    digest = _proof(clean, [roi, *(token.box for token in shell)],
                    dict(code=code, empty=empty, icon=icon_kind))
    return Form(target, roi, code, empty, confirm, digest)


def _pixels(image, roi):
    height, width = image.shape[:2]
    left, top, right, bottom = (round(value * size) for value, size in zip(roi, (width, height, width, height)))
    return image[top:bottom, left:right]


def _current_empty_field(image):
    # Both blank parts of the grey field have two thin darker edges, with a
    # lighter modal body just outside. A pasted icon alone cannot prove this.
    for left, right in ((.37, .48), (.53, .68)):
        above = np.median(_pixels(image, (left, .450, right, .460)))
        upper_edge = np.median(_pixels(image, (left, .464, right, .472)), axis=(1, 2)).min()
        inside = np.median(_pixels(image, (left, .479, right, .500)))
        lower_edge = np.median(_pixels(image, (left, .506, right, .514)), axis=(1, 2)).min()
        below = np.median(_pixels(image, (left, .519, right, .529)))
        outside = min(above, below)
        if outside < 185 or not 150 <= inside <= outside - 8 or max(upper_edge, lower_edge) > inside - 18:
            return False
    return True


def navigation_empty_form_controls(scene, confidence):
    """Identify only the empty 4.6 navigation destination and its two button labels."""
    clean = _scene(scene, .85)
    if clean is None:
        return None
    title = _unique(clean.tokens, ('兑换码',))
    placeholder = _unique(clean.tokens, _NAVIGATION_PLACEHOLDERS)
    cancel = _unique(clean.tokens, ('取消',))
    confirm = _unique(clean.tokens, ('确认',))
    labels = (title, placeholder, cancel, confirm)
    if (None in labels or min(title.score, cancel.score, confirm.score) < confidence
            or any(token.within(_NAVIGATION_MODAL) and token not in labels for token in scene.tokens)):
        return None

    regions = (_CURRENT_EMPTY_TITLE, _CURRENT_EMPTY_PLACEHOLDER, _CURRENT_EMPTY_CANCEL, _CURRENT_EMPTY_CONFIRM)
    if not all(_inside(token.box, region) for token, region in zip(labels, regions)):
        form = read_form(scene, confidence)
        return (cancel, confirm) if form is not None and form.empty and _inside(placeholder.box, form.field_roi) else None

    height, width = clean.image.shape[:2]
    if abs(width / height - 16 / 9) > .02 or abs(cancel.center[1] - confirm.center[1]) > .014:
        return None
    # The current 4K skin renders the old title/paste artwork slightly
    # differently. These floors apply only within the calibrated modal ROIs.
    titles = _matches(clean, 'title', _CURRENT_EMPTY_TITLE, minimum=.94)
    paste = _matches(clean, 'paste', _CURRENT_EMPTY_PASTE, minimum=.93)
    if (len(titles) != 1 or not title.within(titles[0].box) or len(paste) != 1
            or abs(placeholder.center[1] - paste[0].center[1]) > .014
            or not _current_empty_field(clean.image)):
        return None
    light_cancel = np.median(_pixels(clean.image, (.321, .639, .366, .669)))
    dim_confirm = np.median(_pixels(clean.image, (.577, .639, .596, .669)))
    return (cancel, confirm) if light_cancel >= 175 and dim_confirm <= 85 else None


def _result_word(value):
    return STATUSES.get(value.strip().rstrip('。！!'))


def read_result(scene, confidence=.65):
    clean = _scene(scene, confidence)
    if clean is None:
        return Result()
    words = [(token, _result_word(token.text)) for token in clean.tokens if _result_word(token.text) is not None]
    if len(words) != 1:
        return Result()
    word, status = words[0]
    geometry = _geometry(clean)
    if geometry is not None:
        roi, _, shell, _ = geometry
        # An inline error leaves the submit button on the form. It is never a
        # result-dismiss target; only the proven form's Esc path is available.
        if (status != 'redeemed' and roi[3] < word.center[1] < min(shell[1].box[1], shell[2].box[1]) and
                roi[0] <= word.center[0] <= roi[2]):
            return Result(status, key='esc', source_digest=_proof(clean, [roi, word.box], status))
        return Result()
    confirm = _unique(clean.tokens, ('确认',))
    button = _confirm(clean, confirm) if confirm is not None else None
    titles = [token for token in clean.tokens if normalize(token.text) in ('提示', '兑换码', '兑换成功') and
              token is not word and token.box[3] < word.box[1]]
    if status == 'redeemed':
        # Success also needs an independent explicit mail-delivery body. A
        # static success label plus a generic confirm cannot verify a result.
        mail = [token for token in clean.tokens if re.fullmatch(
            r'奖励(?:将|已)?通过(?:游戏内)?邮件(?:发放|发送)[，,。！! ]*(?:请注意查收[。！!]*)?', token.text)]
        if word in [token for token in clean.tokens if normalize(token.text) == '兑换成功'] and len(mail) == 1:
            body = mail[0]
            if word.box[3] < body.box[1] and button is not None and body.box[3] < button.box[1]:
                return Result(status, button, source_digest=_proof(clean, [word.box, body.box, button.box], status))
        return Result()
    if (len(titles) != 1 or button is None or word.box[3] >= button.box[1] or
            not min(titles[0].box[0], button.box[0]) - .12 <= word.center[0] <= max(titles[0].box[2], button.box[2]) + .12):
        return Result()
    return Result(status, button, source_digest=_proof(clean, [titles[0].box, word.box, button.box], status))
