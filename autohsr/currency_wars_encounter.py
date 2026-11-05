"""Observe the two-card encounter layout without authorizing input."""
from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np

from .currency_wars_prepare import trusted
from .models import normalize


# Regions describe the observed 4.6 panel, in fractions of the captured frame.
_HEADER = (.43, .045, .57, .14)
_COLUMNS = ((.271, .426), (.566, .735))
_TITLE = re.compile(r'[遭遗]遇其([一二三四])')
_DIFFICULTIES = {'一': 1, '二': 2, '三': 3, '四': 4}
_CONFIRM = (.49, .75, .64, .88)
_DETAILS = (.455, .17, .548, .29)
_REFRESH = (.30, .75, .45, .88)
_QUANTITY = r'(?:0|[1-9][0-9]{0,2})'
_REWARD = re.compile(rf'(金币|随机([1-5])费角色)(?:[×x]?({_QUANTITY}))?')
_REWARD_NUMBERS = ((.283, .582, .325, .65), (.586, .582, .633, .65))
_EDGES = (((.242, .271), (.425, .455)), ((.538, .572), (.722, .771)))
_OTHER_PAGE_FIELDS = (
    (('投资环境', '请选择投资策略', '补给阶段', '备战阶段'), (.29, .02, .71, .20)),
    (('挑战结束', '挑战失败', '挑战成功'), (.42, .17, .58, .26)),
    (('挑战进度', '对局评价', '强敌来袭'), (.43, .31, .62, .40)),
    (('点击空白处继续',), (.43, .70, .57, .77)),
    (('前往结算', '继续挑战', '下一步'), (.40, .79, .62, .88)),
)


@dataclass(frozen=True)
class EncounterCard:
    slot: int
    name: str
    difficulty: int | None
    reward_preview: dict | None


@dataclass(frozen=True)
class EncounterObservation:
    layout_verified: bool
    cards: tuple[EncounterCard, ...] = ()
    selected_slot: int | None = None
    selection_state: str = 'unknown'
    confirm_state: str = 'unknown'
    refresh_remaining: int | None = None


def _read(tokens, roi, pattern):
    x1, y1, x2, y2 = roi
    return [(token, match) for token in tokens if x1 <= token.box[0] < token.box[2] <= x2
            and y1 <= token.box[1] < token.box[3] <= y2
            and (match := re.fullmatch(pattern, normalize(token.text)))]


def _crop(image, roi):
    h, w = image.shape[:2]
    x1, y1, x2, y2 = roi
    return image[round(y1*h):round(y2*h), round(x1*w):round(x2*w)]


def _white(patch):
    low, high = patch.min(axis=2), patch.max(axis=2)
    return (low >= 188) & (high - low <= 38)


def _difficulty(image, tokens, column, name_token, title):
    left, right = column
    labels = _read(tokens, (left, .391, right, .438), '难度')
    if len(labels) != 1:
        return None
    label, _ = labels[0]
    x, y = label.center
    if abs(x - name_token.center[0]) > .045 or not .02 <= y - name_token.center[1] <= .065:
        return None
    patch = _crop(image, (left, max(.423, y + .010), right, min(.476, y + .068))).astype(np.int16)
    blue, green, red = patch.transpose(2, 0, 1)
    marks = (blue >= 105) & (blue >= green + 28) & (blue >= red + 20)
    # Each colored marker occupies a separate horizontal band.
    columns = marks.sum(axis=0) >= max(2, round(image.shape[0] * .0035))
    spans = np.flatnonzero(np.diff(np.pad(columns.astype(np.int8), (1, 1))))
    widths = spans[1::2] - spans[::2]
    width = image.shape[1]
    count = _DIFFICULTIES[title[-1]]
    if len(widths) == count and all(.012 * width <= band <= .040 * width for band in widths):
        return count
    return None


def _reward_preview(tokens, column, number_roi):
    left, right = column
    headings = _read(tokens, (left, .496, right, .573), '奖励预览')
    labels = _read(tokens, (left, .553, right, .628), _REWARD)
    if len(headings) != 1 or len(labels) != 1:
        return None
    label, match = labels[0]
    if not .025 <= label.center[1] - headings[0][0].center[1] <= .090:
        return None
    cost, inline = match.group(2, 3)
    # The displayed quantity sits on the item tile below and to the left of its name.
    numbers = [(token, value[0]) for token, value in _read(tokens, number_roi, _QUANTITY)
               if .006 <= token.center[1] - label.center[1] <= .045
               and -.006 <= label.box[0] - token.box[2] <= .065]
    quantity = inline
    if len(numbers) == 1:
        token, number = numbers[0]
        counters = _read(tokens, (left, .55, right, .68), r'(?:刷新(?:剩余)?次数|剩余次数)(?:[0-9]{1,2})?')
        counter_value = any(abs(token.center[1] - field.center[1]) <= .013
                            and -.006 <= token.box[0] - field.box[2] <= .035 for field, _ in counters)
        quantity = number if not counter_value and inline in (None, number) else None
    elif numbers:
        quantity = None
    return dict(kind='random_character' if cost else 'gold',
                quantity=int(quantity) if quantity not in (None, '0') else None,
                character_cost=int(cost) if cost else None)


def _refresh_remaining(tokens):
    reads = _read(tokens, _REFRESH, r'剩余次数([0-9]{1,2})?')
    if len(reads) != 1:
        return None
    label, match = reads[0]
    digits = _read(tokens, _REFRESH, r'[0-9]{1,2}')
    adjacent = [part[0] for token, part in digits if abs(token.center[1] - label.center[1]) <= .013
                and 0 <= token.box[0] - label.box[2] <= .025]
    inline = match[1]
    if inline is not None and (not adjacent or adjacent == [inline]):
        return int(inline)
    if inline is None and len(adjacent) == 1:
        return int(adjacent[0])
    return None


def _button_state(image, token):
    x, y = token.center
    # Read the fill away from the glyphs, which are also visible when disabled.
    shoulders = [_crop(image, (x + left, y - .012, x + right, y + .016))
                 for left, right in ((-.078, -.037), (.037, .078))]
    if all(_white(patch).mean() >= .80 for patch in shoulders):
        return 'enabled'
    brightness = [patch.max(axis=2) for patch in shoulders]
    if all(((level >= 12) & (level <= 115)).mean() >= .85 for level in brightness):
        return 'disabled'
    return 'unknown'


def _edge_state(image, edges):
    sides = [_crop(image, (left, .42, right, .658)) for left, right in edges]
    # Selection adds a continuous white edge on both sides of the card.
    white_rows = [_white(patch).any(axis=1).mean() for patch in sides]
    if all(value >= .78 for value in white_rows):
        return 'highlighted'
    if all(value <= .12 for value in white_rows) and all((patch.max(axis=2) >= 20).mean() >= .75 for patch in sides):
        return 'plain'
    return 'unknown'


def read_encounter(scene, confidence=.65):
    """Read a candidate modal in the dedicated check, including unknown fields."""
    current = trusted(scene, confidence)
    if any(current.has(labels, region, exact=True) for labels, region in _OTHER_PAGE_FIELDS):
        return None
    tokens = current.tokens
    headers = _read(tokens, _HEADER, r'[遭遗]遇节点')
    names = [_read(tokens, (left, .32, right, .415), _TITLE) for left, right in _COLUMNS]
    confirms = _read(tokens, _CONFIRM, '选择')
    if not headers and not (confirms and any(names)):
        return None
    markers = [_read(tokens, (left, .395, right, .573), r'(?:难度|奖励预览)') for left, right in _COLUMNS]
    if (len(headers) != 1 or headers[0][1][0] != '遭遇节点' or len(confirms) != 1
            or any(len(column) != 1 or not column[0][1][0].startswith('遭') for column in names)
            or not all(markers)):
        return EncounterObservation(False)

    image = current.image
    visible_pixels = (isinstance(image, np.ndarray) and image.ndim == 3 and image.shape[2] == 3
                      and image.dtype == np.uint8 and image.shape[0] >= 270 and image.shape[1] >= 480)
    cards = []
    for slot, (column, name_reads, number_roi) in enumerate(zip(_COLUMNS, names, _REWARD_NUMBERS), 1):
        name, match = name_reads[0]
        title = match[0]
        difficulty = _difficulty(image, tokens, column, name, title) if visible_pixels else None
        cards.append(EncounterCard(slot, title, difficulty, _reward_preview(tokens, column, number_roi)))

    confirm = 'unknown'
    selection, selected_slot = 'unknown', None
    if visible_pixels:
        confirm = _button_state(image, confirms[0][0])
        left, right = (_edge_state(image, edges) for edges in _EDGES)
        details = _read(tokens, _DETAILS, r'查看[详评]情')
        if (confirm == 'enabled' and left == 'plain' and right == 'highlighted'
                and len(details) == 1 and details[0][1][0] == '查看详情'):
            selection, selected_slot = 'selected', 2
        elif (confirm == 'disabled' and left == right == 'plain' and not details
              and all(card.difficulty is not None for card in cards)):
            selection = 'unselected'

    return EncounterObservation(True, tuple(cards), selected_slot, selection, confirm, _refresh_remaining(tokens))
