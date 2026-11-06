"""Read the cultivation panel and its separate post-battle reminder."""
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import re
from unicodedata import normalize as unicode_normalize

import cv2
import numpy as np

from .build_target_read import ENTRY, MODAL_AREA, SECTIONS, SHORTFALL, _has_split_label
from .config import RESOURCE_ROOT
from .currency_wars_prepare import trusted
from .dungeons import BY_KEY
from .models import normalize


ROLE = (.35, .25, .56, .32)
STATUS = (.36, .31, .68, .414)
RELIC = (.36, .42, .78, .84)
NEEDS = (SHORTFALL, 'a' + SHORTFALL)
COMPLETE = '已完成等级行迹的提升'
SUFFICIENT = '已获得足够的等级和行迹材料'
STATUS_LABELS = (*NEEDS, COMPLETE, SUFFICIENT)
SPLIT_STATUS_LABELS = (*STATUS_LABELS, '已完成等级、行迹的提升')
RELIC_MARKERS = ('遗器推荐', '遗器装配不全', '隧洞遗器推荐', '位面饰品推荐')
AMOUNT = r'(?:0|[1-9][0-9]{0,8}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,2})'
RESULT_WAVES = re.compile(r'上轮挑战波次([1-9]|1[0-9]|2[0-4])')
WAVE_AREA = (.55, .78, .72, .84)
CALYX_STAMINA = BY_KEY['calyx_crimson'].cost
GALAXY_SANDBOX = '银河沙盘'
SLOT_LEFT = .37
SLOT_WIDTH = .06


@dataclass(frozen=True)
class ShortfallRow:
    observed_needed: tuple[int, ...]
    shown_stamina: int
    row_band: int
    slots: tuple[int, ...]
    materials: tuple[str | None, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class TargetPanel:
    state: str
    shortfall_rows: tuple[ShortfallRow, ...] = ()


@dataclass(frozen=True)
class ResultShortfall:
    observed_needed: tuple[int, ...]
    completed_rounds: int
    repeat_stamina: int


def _label_text(token):
    return normalize(token.text).replace('、', '')


def _label(fields, page, words, region):
    words = (words,) if isinstance(words, str) else words
    matches = [token for token in fields.tokens if token.within(region) and _label_text(token) in words]
    return matches[0] if len(matches) == 1 and matches[0] in page.tokens else None


def target_status_conflicts(fields):
    states = [t for t in fields.tokens if t.within(SECTIONS) and _label_text(t) in STATUS_LABELS]
    return len(states) > 1 or _has_split_label(fields, SPLIT_STATUS_LABELS, SECTIONS)


def _number_text(token):
    return re.sub(r'\s+', '', unicode_normalize('NFKC', token.text))


def _inside(token, region):
    x1, y1, x2, y2 = token.box
    return region[0] <= x1 < x2 <= region[2] and region[1] <= y1 < y2 <= region[3]


def _amount_tokens(fields, page, region):
    tokens = sorted((t for t in fields.tokens if t.within(region) and re.search(r'[0-9０-９]', t.text)),
                    key=lambda t: t.center[0])
    if (not 1 <= len(tokens) <= 4
            or any(t not in page.tokens or not _inside(t, region) or not re.fullmatch(AMOUNT, _number_text(t))
                   for t in tokens)
            or any(right.box[0] - left.box[2] < .022 for left, right in zip(tokens, tokens[1:]))):
        return ()
    return tuple(tokens)


def _amount(token):
    return int(_number_text(token).replace(',', ''))


@lru_cache(maxsize=1)
def _galaxy_sandbox_templates():
    # The bundled 海原电视塔 medallion has the same art as the 4.6
    # target slot. Use its center, clear of the medallion and search badge.
    try:
        raw = (RESOURCE_ROOT / 'assets/ui/survival/56e86ec575f7c498.png').read_bytes()
        if hashlib.sha256(raw).hexdigest() != 'b5d9b8c0edd026e8d2f9f55d2e01e11012580b960bddfed9108787e30998d41f':
            return ()
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error):
        return ()
    if image is None:
        return ()
    reference = image[41:86, 60:110]
    return tuple(cv2.resize(reference, (width, round(width * .9)), interpolation=cv2.INTER_AREA)
                 for width in range(15, 20))


def _slot_material(image, amount, slot):
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        return None
    height, width = image.shape[:2]
    if height < 450 or width < 800 or abs(width / height - 16 / 9) > .02:
        return None
    x = SLOT_LEFT + (slot + .5) * SLOT_WIDTH
    if abs(x - amount.center[0]) > .012:
        return None
    x = round(x * 852)
    y = round(amount.box[1] * 480)
    # Sample the art directly above this amount without the text or adjacent slot.
    left, top, right, bottom = (round(value * scale) for value, scale in
                                zip((x - 15, y - 22, x + 15, y - 1), (width/852, height/480) * 2))
    patch = cv2.resize(image[top:bottom, left:right], (30, 21), interpolation=cv2.INTER_AREA)
    for template in _galaxy_sandbox_templates():
        h, w = template.shape[:2]
        scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        # A match must lie on the slot's center, not on its visible border.
        rows, columns = np.ogrid[:scores.shape[0], :scores.shape[1]]
        aligned = (abs(columns + w / 2 - 15) <= 5) & (abs(rows + h / 2 - 11) <= 2.5)
        if np.any(scores[aligned] >= .84):
            return GALAXY_SANDBOX
    return None


def _need_rows(fields, page, heading, bottom, image):
    buttons = sorted((t for t in fields.tokens if t.within((.75, heading.box[3], .91, bottom))
                      and _label_text(t) == '进入'), key=lambda t: t.center[1])
    if any(lower.center[1] - upper.center[1] < .06 for upper, lower in zip(buttons, buttons[1:])):
        return ()
    rows = []
    for button in buttons:
        y = button.center[1]
        costs = _amount_tokens(fields, page, (.64, y - .025, .73, y + .025))
        items = _amount_tokens(fields, page, (.375, y + .008, .61, min(bottom, y + .057)))
        slots = tuple(int((token.center[0] - SLOT_LEFT) / SLOT_WIDTH) for token in items)
        if (button in page.tokens and len(costs) == 1 and _amount(costs[0]) in (10, 30)
                and items and len(set(slots)) == len(slots)):
            stamina = _amount(costs[0])
            materials = tuple(_slot_material(image, token, slot) if stamina == CALYX_STAMINA else None
                              for token, slot in zip(items, slots))
            rows.append(ShortfallRow(tuple(map(_amount, items)), stamina, round(y * 20), slots, materials))
    return tuple(rows)


def target_panel(scene, page, guide_entry, *, read_materials=False):
    """Return a current panel, its anchor, and whether conflicting roles veto fallback."""
    fields = trusted(scene, 0.)
    if (target_status_conflicts(fields)
            or fields.has(('挑战成功', '战斗失败', '挑战失败'), exact=True)
            or fields.has('获得途径', MODAL_AREA, exact=True)
            or _has_split_label(fields, ('获得途径',), MODAL_AREA)):
        return None, None, True
    role = _label(fields, page, '角色培养', ROLE)
    status = _label(fields, page, STATUS_LABELS, STATUS)
    if role is None or status is None or role.center[1] >= status.center[1]:
        return None, None, False
    if guide_entry is None:
        guide_entry = _label(fields, page, '培养目标', ENTRY)
        if guide_entry is None or _label(fields, page, '更换培养目标', (.14, .79, .36, .91)) is None:
            return None, None, False
    settings = _label(fields, page, '培养设置', (.14, .52, .95, .96))
    relics = [t for t in page.tokens if t.within(RELIC) and _label_text(t) in RELIC_MARKERS]
    if settings is None or not relics or settings.center[1] <= max(t.center[1] for t in relics):
        return None, None, False
    state = _label_text(status)
    if state in NEEDS:
        bottom = min(t.box[1] for t in relics)
        image = scene.image if read_materials else None
        return TargetPanel('target_resources_needed', _need_rows(fields, page, status, bottom, image)), guide_entry, False
    if state == COMPLETE:
        if not all(_label(fields, page, label, RELIC) for label in ('隧洞遗器推荐', '位面饰品推荐')):
            return None, None, False
        return TargetPanel('target_level_trace_complete'), guide_entry, False
    return TargetPanel('target_materials_sufficient'), guide_entry, False


def result_shortfall(scene, page):
    fields = trusted(scene, 0.)
    failures = ('战斗失败', '挑战失败')
    if (fields.has(failures, exact=True) or _has_split_label(fields, failures, (.30, .15, .70, .29))
            or fields.has('角色培养', ROLE, exact=True)
            or fields.has(('可能遭遇', '可能获取'), (.59, .20, .79, .63), exact=True)):
        return None, None
    for label, roi in (
        ('挑战成功', (.39, .16, .61, .27)), ('成功奖励', (.44, .35, .56, .42)),
        ('退出关卡', (.28, .87, .46, .95)), ('再来一次', (.59, .87, .72, .95)),
    ):
        if _label(fields, page, label, roi) is None:
            return None, None
    reminder = _label(fields, page, ('培养尚需', '1培养尚需', 'i培养尚需'), (.30, .62, .43, .68))
    if reminder is None:
        return None, None
    wave_tokens = [t for t in fields.tokens if t.within(WAVE_AREA)
                   and _label_text(t).startswith('上轮挑战波次')]
    prices = [t for t in fields.tokens if t.within((.53, .87, .61, .94))
              and _number_text(t).lower().startswith(('×', 'x'))]
    if (len(wave_tokens) != 1 or wave_tokens[0] not in page.tokens or len(prices) != 1
            or _has_split_label(fields, ('上轮挑战波次',), WAVE_AREA, exact=False)):
        return None, None
    wave = RESULT_WAVES.fullmatch(_label_text(wave_tokens[0]))
    price = re.fullmatch(r'[×x]([0-9]{1,3})', _number_text(prices[0]).lower())
    items = _amount_tokens(fields, page, (.59, reminder.center[1] - .022, .735, reminder.center[1] + .022))
    if (wave is None or price is None or prices[0].score < .80 or len(items) != 1 or items[0].box[0] < .684
            or int(price[1]) != int(wave[1]) * CALYX_STAMINA):
        return None, None
    return ResultShortfall((_amount(items[0]),), int(wave[1]), int(price[1])), reminder
