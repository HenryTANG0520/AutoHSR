"""Read 4.6 badge declarations and the separate named gold receipt."""
from dataclasses import dataclass
import re

from .models import normalize


GRAIL_CARD = '都是这家伙的错'
_GRAIL_BADGE = '命运圣杯星徽'
_GRAIL_GRANT = f'获得【{_GRAIL_BADGE}】和10金币'
_GRAIL_CONDITION = '若未完美通关战斗'
_GOLD_CHIP = (.794, .742, .889, .820)
_GOLD_TITLE = (.789, .736, .897, .788)
_GOLD_AMOUNT = (.819, .774, .875, .825)
_BUNDLES = {
    '昼之半神星徽套组': ('昼之半神星徽', ('风堇',), '生命之环'),
    # The fixture reads 飞雪. Retain the observed label if either form is read.
    '追击星徽套组': ('追击星徽', ('飞雪', '飞霄'), '永动机'),
    '能量星徽套组': ('能量星徽', ('星期日',), '胜利之旗'),
}
_COUNT = r'([0-9]{1,2}|[一二两三])'
_LABEL = r'【([\u4e00-\u9fff]{1,16})】'
_DECLARATION = re.compile(rf'获得{_COUNT}个{_LABEL}和{_COUNT}个{_LABEL}以及{_COUNT}(?:个|件){_LABEL}')
_CN_COUNTS = {'一': 1, '二': 2, '两': 2, '三': 3}


@dataclass(frozen=True)
class BadgeDeclaration:
    badge: str
    badge_count: int | None
    other_rewards: tuple[tuple[str, int], ...]


def parse_badge_declaration(title, effect):
    title = normalize(title)
    if title == GRAIL_CARD:
        first, separator, remainder = effect.partition('。')
        if separator and normalize(first) == _GRAIL_GRANT and normalize(remainder).startswith(_GRAIL_CONDITION):
            # The card names the badge without a printed quantity.
            return BadgeDeclaration(_GRAIL_BADGE, None, (('金币', 10),))
        return None
    known = _BUNDLES.get(title)
    match = _DECLARATION.fullmatch(normalize(effect))
    if known is None or match is None:
        return None
    badge_count, badge, second_count, second, third_count, third = match.groups()
    if badge != known[0] or second not in known[1] or third != known[2]:
        return None
    counts = (badge_count, second_count, third_count)
    if any(count not in _CN_COUNTS and count not in ('1', '2', '3') for count in counts):
        return None
    amounts = [int(_CN_COUNTS.get(count, count)) for count in counts]
    return BadgeDeclaration(badge, amounts[0], ((second, amounts[1]), (third, amounts[2])))


def read_badge_declaration(name, parts, confidence):
    """Read the complete declaration from consecutive rows of the same card."""
    title = normalize(name.text)
    if title == GRAIL_CARD:
        # The grant ends in the second row. Later rows describe a separate conditional effect.
        parts = [t for t in parts if t.center[1] <= .55]
    elif title not in _BUNDLES:
        return None
    effect = badge_effect_text(name, parts, confidence)
    return parse_badge_declaration(title, effect) if effect is not None else None


def badge_effect_text(name, parts, confidence):
    """Read contiguous text from one card with its original row positions."""
    x = name.center[0]
    threshold = max(.85, confidence)
    if not parts or any(t.score < threshold or not x-.125 <= t.box[0] < t.box[2] <= x+.125
                        for t in (name, *parts)):
        return None

    # Use the same line and wrap distances as the investment refresh check.
    rows = []
    for token in sorted(parts, key=lambda t: t.center[1]):
        if not rows or token.center[1]-rows[-1][0].center[1] > .012:
            rows.append([])
        rows[-1].append(token)

    if rows[0][0].center[1] > .55:
        return None
    previous_line = None
    for row in rows:
        y = row[0].center[1]
        row.sort(key=lambda t: t.center[0])
        start = row[0].box[0]
        top = min(t.box[1] for t in row)
        bottom = max(t.box[3] for t in row)
        if previous_line is not None:
            previous_start, previous_y, previous_top, previous_bottom = previous_line
            overlap = min(bottom, previous_bottom) - max(top, previous_top)
            shorter_height = min(bottom - top, previous_bottom - previous_top)
            # OCR boxes can overlap at the line edges.
            if (y - previous_y > .05 or abs(start - previous_start) > .09
                    or overlap > shorter_height / 3):
                return None
        for left, right in zip(row, row[1:]):
            left_start, left_top, left_end, left_bottom = left.box
            right_start, right_top, right_end, right_bottom = right.box
            allowed_overlap = min(.012, (left_end - left_start) / 3, (right_end - right_start) / 3)
            if (not -allowed_overlap <= right_start - left_end <= .045
                    or min(left_bottom, right_bottom) <= max(left_top, right_top)):
                return None
        previous_line = start, y, top, bottom

    return ''.join(t.text for row in rows for t in row)


def bundle_declaration_conflicts(effect, declaration):
    """Retain differing quantities and recognized names in complete alternate reads."""
    match = _DECLARATION.fullmatch(normalize(effect))
    if match is None:
        return False
    badge_count, badge, role_count, role, item_count, item = match.groups()
    counts = tuple(int(_CN_COUNTS.get(count, count)) for count in (badge_count, role_count, item_count))
    expected_counts = (declaration.badge_count, *(count for _, count in declaration.other_rewards))
    if counts != expected_counts:
        return True
    expected_role, expected_item = (name for name, _ in declaration.other_rewards)
    return (badge.endswith('星徽') and not declaration.badge.endswith(badge)
            or role != expected_role and any(role in bundle[1] for bundle in _BUNDLES.values())
            or item != expected_item and any(item == bundle[2] for bundle in _BUNDLES.values()))


def _inside(token, region):
    left, top, right, bottom = region
    x1, y1, x2, y2 = token.box
    return left <= x1 < x2 <= right and top <= y1 < y2 <= bottom


def read_grail_gold_receipt(scene, confidence=.65):
    """Read the current named +10 gold chip independently from badge custody."""
    import cv2
    import numpy as np

    from .currency_wars_match import read_match
    from .currency_wars_prepare import trusted

    current = trusted(scene, confidence)
    titles = [t for t in current.tokens if t.within(_GOLD_TITLE) and re.fullmatch(r'[一-鿿]{4,16}', normalize(t.text))]
    amounts = [t for t in current.tokens if t.within(_GOLD_AMOUNT) and re.fullmatch(r'[0-9]{1,3}', normalize(t.text))]
    if len(titles) != 1 or len(amounts) != 1:
        return None
    title, amount = titles[0], amounts[0]
    if (normalize(title.text) != GRAIL_CARD or normalize(amount.text) != '10'
            or not _inside(title, _GOLD_TITLE) or not _inside(amount, _GOLD_AMOUNT)
            or min(title.score, amount.score) < .85 or abs(title.center[0] - amount.center[0]) > .027
            or not .022 <= amount.center[1] - title.center[1] <= .055):
        return None
    match = read_match(scene, confidence)
    if match is None or match.page not in ('preparation', 'shop') or match.node is None or match.gold is None:
        return None
    image = current.image
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
            or image.shape[2] != 3 or image.shape[0] < 360 or image.shape[1] < 640):
        return None
    height, width = image.shape[:2]
    left, top, right, bottom = [round(v*s) for v, s in zip(_GOLD_CHIP, (width, height, width, height))]
    hue, saturation, value = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV).transpose(2, 0, 1)
    green = (hue >= 40) & (hue <= 95) & (saturation >= 25) & (value >= 125)
    warm = (hue >= 8) & (hue <= 42) & (saturation >= 75) & (value >= 95)
    half = green.shape[0] // 2
    _, _, components, _ = cv2.connectedComponentsWithStats(green.astype(np.uint8))
    if (min(green[:half].mean(), green[half:].mean()) < .40 or not .035 <= warm[half:].mean() <= .22
            or not any(y < half < y + h and area >= .38 * green.size for _, y, _, h, area in components[1:])):
        return None
    return dict(title=GRAIL_CARD, node=match.node, gold_received=10, wallet=match.gold, badge_delivery_verified=False)
