"""Read complete badge declarations from the redacted 4.6 investment fixture."""
from dataclasses import dataclass
import re

from .models import normalize


_BUNDLES = {
    '昼之半神星徽套组': ('昼之半神星徽', ('风堇',), '生命之环'),
    # The fixture reads 飞雪. Retain the observed label if either form is read.
    '追击星徽套组': ('追击星徽', ('飞雪', '飞霄'), '永动机'),
}
_COUNT = r'([1-3一二两三])'
_LABEL = r'【([\u4e00-\u9fff]{1,16})】'
_DECLARATION = re.compile(rf'获得{_COUNT}个{_LABEL}和{_COUNT}个{_LABEL}以及{_COUNT}(?:个|件){_LABEL}')
_CN_COUNTS = {'一': 1, '二': 2, '两': 2, '三': 3}


@dataclass(frozen=True)
class BadgeDeclaration:
    badge: str
    badge_count: int
    other_rewards: tuple[tuple[str, int], tuple[str, int]]


def parse_badge_declaration(title, effect):
    known = _BUNDLES.get(normalize(title))
    match = _DECLARATION.fullmatch(normalize(effect))
    if known is None or match is None:
        return None
    badge_count, badge, second_count, second, third_count, third = match.groups()
    if badge != known[0] or second not in known[1] or third != known[2]:
        return None
    amounts = [int(_CN_COUNTS.get(count, count)) for count in (badge_count, second_count, third_count)]
    return BadgeDeclaration(badge, amounts[0], ((second, amounts[1]), (third, amounts[2])))


def read_badge_declaration(name, parts, confidence):
    """Read the complete declaration from consecutive rows of the same card."""
    x = name.center[0]
    threshold = max(.85, confidence)
    if (normalize(name.text) not in _BUNDLES or not parts
            or any(t.score < threshold or not x-.125 <= t.box[0] < t.box[2] <= x+.125
                   for t in (name, *parts))):
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

    return parse_badge_declaration(name.text, ''.join(t.text for row in rows for t in row))
