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
PLACEHOLDERS = ('请输入兑换码', '请在此输入兑换码')
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


def _matches(scene, name, roi=(0, 0, 1, 1)):
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
    ys, xs = np.where((scores >= .96) & (scores >= cv2.dilate(scores, np.ones((3, 3), np.uint8))))
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
    return bool(clean and clean.has('开拓等级', (.55, .05, .99, .35), exact=True) and
                clean.has(('委托', '星际和平指南', '指南', '无名勋礼'), (.55, .25, 1, 1), exact=True) and
                not clean.has(('兑换码', '兑换成功', '请输入兑换码'), (.15, .15, .85, .85), exact=True))


def phone_more_target(scene, confidence=.65):
    clean = _scene(scene, confidence)
    if not clean or not phone(scene, confidence):
        return None
    hits = _matches(clean, 'more', PHONE_HEADER)
    return hits[0] if len(hits) == 1 else None


def redemption_entry(scene, confidence=.65):
    clean = _scene(scene, confidence)
    if clean is None:
        return None
    entry = _unique(clean.tokens, ('兑换码',), MORE_MENU)
    visa = _unique(clean.tokens, ('漫游签证',), MORE_MENU)
    menu = {normalize(token.text) for token in clean.tokens if token.within((.55, .25, 1, 1)) and
            normalize(token.text) in ('委托', '星际和平指南', '指南', '无名勋礼', '好友', '成就')}
    if (entry is None or visa is None or len(menu) < 2 or
            abs(entry.center[0] - visa.center[0]) > .08 or
            not .015 <= abs(entry.center[1] - visa.center[1]) <= .18 or
            len(_matches(clean, 'more', PHONE_HEADER)) != 1):
        return None
    return entry


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
