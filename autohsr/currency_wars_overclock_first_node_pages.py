"""Read the existing A0 first-node board and the two calibrated drop deliveries."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .currency_wars_collector import RosterCell, roster_cells
from .currency_wars_equipment import battery_items
from .currency_wars_loot import loot_feedback
from .currency_wars_match import MatchState, read_match
from .currency_wars_node import loot_centers
from .currency_wars_overclock_preparation_pages import _SHOP, _control, _image, read_preparation
from .currency_wars_prepare import trusted
from .models import AutomationError, Token


Crystal = tuple[float, float, float]
StockPoint = tuple[float, float]
_INCOMPATIBLE_CONTROLS = ('开始对局', '进入标准博弈', '进入超频博弈', '确认', '下一步', '点击空白处继续')


@dataclass(frozen=True)
class FirstNodeBoard:
    match: MatchState
    cells: tuple[RosterCell, ...]
    crystals: tuple[Crystal, ...]
    batteries: tuple[StockPoint, ...]
    target: Token | None


@dataclass(frozen=True)
class DropDelivery:
    kind: str
    value: int | StockPoint
    remaining: tuple[Crystal, ...]


def read_first_node_board(scene, confidence):
    """Read one board. A detected battle button is only an observation."""
    visible = trusted(scene, 0)
    match = read_match(scene, confidence)
    if (not _image(scene) or match is None or match.page != 'preparation' or match.node != '1-1'
            or match.hp is None or match.hp <= 0 or match.level is None or match.experience is None
            or match.deployment is None or not match.deployment[1] or match.gold is None
            or read_match(visible, 0) != match):
        raise AutomationError('超频 1-1 备战的节点、生命、等级、经验、部署或金币未完整核实。')

    shop, _ = _control(visible, '商店', _SHOP, confidence)
    if (shop is None or visible.has(_INCOMPATIBLE_CONTROLS, exact=True)
            or read_preparation(scene, confidence).state == 'blocked'):
        raise AutomationError('超频 1-1 需要无遮挡且商店已收起的备战画面。')

    cells = roster_cells(scene, confidence)
    if cells != roster_cells(visible, 0):
        raise AutomationError('超频 1-1 的角色或奖励占位存在冲突。')
    target, _ = _control(visible, '出战', (.9, .65, 1., .75), max(.85, confidence))
    return FirstNodeBoard(match, cells, loot_centers(scene), battery_items(scene, confidence), target)


def _valid_crystal(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(type(field) in (int, float) and 0 < field < 1 for field in value))


def _near(left, right):
    x, y, radius = left
    a, b, other = right
    smaller = min(radius, other)
    return (math.hypot((x - a) * 2560, (y - b) * 1440) < max(8, smaller * 2560 * .25)
            and abs(radius - other) <= .25 * smaller)


def same_crystals(a, b):
    """Require an unambiguous one-to-one correspondence of crystal candidates."""
    if (not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple))
            or len(a) != len(b) or not all(_valid_crystal(item) for group in (a, b) for item in group)):
        return False
    used = set()
    for center in a:
        indices = [index for index, item in enumerate(b) if _near(center, item)]
        if len(indices) != 1 or indices[0] in used:
            return False
        used.add(indices[0])
    return True


def _crystal_kind(scene, point):
    """Use the existing detector's color bands on the body's inner circle."""
    import cv2
    import numpy as np

    x, y, radius = point
    x, y, radius = x * 2560, y * 1440, radius * 2560
    left, right = max(0, math.floor(x - radius)), min(2560, math.ceil(x + radius))
    top, bottom = max(0, math.floor(y - radius)), min(1440, math.ceil(y + radius))
    grid_y, grid_x = np.ogrid[top:bottom, left:right]
    inside = (grid_x - x) ** 2 + (grid_y - y) ** 2 <= (.95 * radius) ** 2
    if not inside.any():
        return None
    image = cv2.resize(scene.image, (2560, 1440))[top:bottom, left:right]
    hue, saturation, brightness = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[inside].T
    blue = ((85 <= hue) & (hue <= 112) & (saturation >= 45) & (brightness >= 170)).mean()
    gray = ((saturation <= 55) & (brightness >= 145)).mean()
    gold = ((10 <= hue) & (hue <= 35) & (saturation >= 90) & (brightness >= 170)).mean()
    if 8 <= radius <= 35 and gray >= .50 and max(blue, gold) <= .15:
        return 'gray'
    if 35 <= radius <= 62 and blue >= .50 and max(gray, gold) <= .15:
        return 'blue'
    return None


def opening_crystal_target(scene, crystals, kind):
    """Only the observed gray/blue ordering supplies an opening pickup target."""
    expected = {'gray', 'blue'} if kind == 'gray' else {'blue'}
    if len(crystals) != len(expected):
        return None
    detected = {_crystal_kind(scene, point): point for point in crystals}
    return detected.get(kind) if set(detected) == expected else None


def _occupancy(board):
    return tuple((cell.zone, cell.slot, cell.point, cell.state) for cell in board.cells)


def drop_delivery(before, after, target, confidence):
    """Classify one verified disappearance as the calibrated gold or battery delivery."""
    if not _valid_crystal(target):
        return None
    try:
        first, last = (read_first_node_board(scene, confidence) for scene in (before, after))
    except AutomationError:
        return None
    if (replace(first.match, gold=last.match.gold) != last.match or _occupancy(first) != _occupancy(last)
            or loot_feedback(before, after, target, confidence) != 'disappeared'):
        return None

    matches = [index for index, item in enumerate(first.crystals) if _near(item, target)]
    if len(matches) != 1:
        return None
    index = matches[0]
    remaining = first.crystals[:index] + first.crystals[index + 1:]
    if not same_crystals(remaining, last.crystals):
        return None

    kind = _crystal_kind(before, first.crystals[index])
    if (kind == 'gray' and len(first.crystals) == 2 and last.match.gold == first.match.gold + 2
            and first.batteries == last.batteries):
        return DropDelivery('gold', 2, last.crystals)
    if kind == 'blue' and len(first.crystals) == 1 and first.match.gold == last.match.gold:
        existing, current = set(first.batteries), set(last.batteries)
        added = current - existing
        if existing <= current and len(added) == 1:
            return DropDelivery('battery', added.pop(), last.crystals)
    return None
