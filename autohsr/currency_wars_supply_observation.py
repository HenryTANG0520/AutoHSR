"""Read the five-card, two-row supply layout seen in CN 4.6 replay."""
import numpy as np

from .currency_wars import observe
from .currency_wars_deployment import _crop
from .currency_wars_reward_items import ITEM_IDS
from .currency_wars_standard_supply_refresh import remaining
from .currency_wars_supply import supply_count
from .currency_wars_supply_fields import CENTERS, _name, equipment_names
from .models import AutomationError, normalize


_CENTERS = CENTERS[5]
_ROLE_ROW = (.448, .51)
_UPPER_ROW = (.565, .632)
_LOWER_ROW = (.661, .728)
_EQUIPMENT_PANEL = (.03, .535, .97, .75)
_CONFIRM = (.85, .875, .97, .949)


def _row(tokens, bounds, confidence, *, roles=False):
    top, bottom = bounds
    entries = [token for token in tokens if token.within((.02, top, .98, bottom))]
    if len(entries) != len(_CENTERS):
        raise AutomationError('双件补给的五列字段不完整。')
    result = []
    for center, token in zip(_CENTERS, sorted(entries, key=lambda item: item.center[0])):
        x1, y1, x2, y2 = token.box
        left, right = (center - .104, center + .069) if roles else (center - .075, center + .075)
        if (not confidence <= token.score <= 1 or not left <= x1 < x2 <= right
                or not top <= y1 < y2 <= bottom or not roles and abs(token.center[0] - center) > .044):
            raise AutomationError('双件补给字段越界或与本列不符。')
        if roles:
            if not _name(token):
                raise AutomationError('双件补给角色名称待核对。')
            result.append(token.text.strip())
        else:
            names = equipment_names(token)
            if len(names) != 1:
                raise AutomationError('双件补给的每个装备位置须独立可读。')
            name, = names
            result.append(dict(text=name, catalog_id=ITEM_IDS.get(name)))
    return result


def _white(image, roi):
    return np.min(_crop(image, roi), axis=2) > 185


def _highlighted(image, center):
    body = _white(image, (center - .073, .585, center + .073, .733))
    left = _white(image, (center - .099, .546, center - .076, .765))
    right = _white(image, (center + .076, .546, center + .099, .765))
    return (np.mean(body) >= .60 and np.max(left.mean(axis=0)) >= .75
            and np.max(right.mean(axis=0)) >= .75)


def read_double_supply(scene, confidence=.65):
    """Report visible names and selection without providing a target or receipt."""
    image = scene.image
    if (not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3
            or image.shape[0] < 360 or abs(image.shape[1] / image.shape[0] - 16 / 9) > .04
            or observe(scene, confidence).page_kind != 'supply_selection'):
        return None
    gear = [token for token in scene.tokens if token.within(_EQUIPMENT_PANEL)]
    if len(gear) != 2 * len(_CENTERS):
        return None
    try:
        roles = _row(scene.tokens, _ROLE_ROW, confidence, roles=True)
        upper = _row(gear, _UPPER_ROW, confidence)
        lower = _row(gear, _LOWER_ROW, confidence)
        count = supply_count(scene, confidence)
    except AutomationError:
        return None

    confirm = [token for token in scene.tokens if confidence <= token.score <= 1
               and normalize(token.text) == '确认' and token.within(_CONFIRM)]
    selected_slot = None
    confirm_state = 'unknown'
    if len(confirm) == 1:
        highlights = [slot for slot, center in enumerate(_CENTERS, 1) if _highlighted(image, center)]
        button = np.mean(_white(image, (.833, .899, .97, .923)))
        if count == 0 and not highlights and button <= .25:
            confirm_state = 'disabled'
        elif count == 1 and len(highlights) == 1 and button >= .55:
            selected_slot, = highlights
            confirm_state = 'enabled'
    try:
        refresh, _ = remaining(scene, confidence)
    except AutomationError:
        refresh = None
    cards = [dict(slot=slot, character=role, equipment=[first, second])
             for slot, (role, first, second) in enumerate(zip(roles, upper, lower), 1)]
    return dict(layout='five_cards_two_equipment_rows', cards=cards, selected_count=count,
                selected_slot=selected_slot, confirm_state=confirm_state, refresh_remaining=refresh)
