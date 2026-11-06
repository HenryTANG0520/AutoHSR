"""Read the cultivation panel and its separate post-battle reminder."""
from dataclasses import dataclass
import re
from unicodedata import normalize as unicode_normalize

from .build_target_read import ENTRY, MODAL_AREA, SECTIONS, SHORTFALL, _has_split_label
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


@dataclass(frozen=True)
class ShortfallRow:
    observed_needed: tuple[int, ...]
    shown_stamina: int
    row_band: int
    slots: tuple[int, ...]


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


def _need_rows(fields, page, heading, bottom):
    buttons = sorted((t for t in fields.tokens if t.within((.75, heading.box[3], .91, bottom))
                      and _label_text(t) == '进入'), key=lambda t: t.center[1])
    if any(lower.center[1] - upper.center[1] < .06 for upper, lower in zip(buttons, buttons[1:])):
        return ()
    rows = []
    for button in buttons:
        y = button.center[1]
        costs = _amount_tokens(fields, page, (.64, y - .025, .73, y + .025))
        items = _amount_tokens(fields, page, (.375, y + .008, .61, min(bottom, y + .057)))
        slots = tuple(int((token.center[0] - .37) / .06) for token in items)
        if (button in page.tokens and len(costs) == 1 and _amount(costs[0]) in (10, 30)
                and items and len(set(slots)) == len(slots)):
            rows.append(ShortfallRow(tuple(map(_amount, items)), _amount(costs[0]), round(y * 20), slots))
    return tuple(rows)


def target_panel(scene, page, guide_entry):
    """Return a current panel, its anchor, and whether conflicting roles veto fallback."""
    fields = trusted(scene, 0.)
    states = [t for t in fields.tokens if t.within(SECTIONS) and _label_text(t) in STATUS_LABELS]
    if (len(states) > 1 or _has_split_label(fields, SPLIT_STATUS_LABELS, SECTIONS)
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
        return TargetPanel('target_resources_needed', _need_rows(fields, page, status, bottom)), guide_entry, False
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
