"""Bounded equipment payloads; a pair never loses order or multiplicity."""
from collections import Counter
import re

from .currency_wars_equipment_catalog import GEAR, NAMES
from .models import AutomationError


ITEM_IDS = {name: key for key, name in NAMES.items() if key in GEAR}


def item_ids(value, *, optional=False):
    """Read the legacy string or the explicit two-item JSON list."""
    if value is None and optional:
        return ()
    values = (value,) if isinstance(value, str) else tuple(value) if type(value) is list and len(value) == 2 else ()
    if not values or any(type(item) is not str or item not in GEAR for item in values):
        raise AutomationError('奖励装备列表未完整对应已核实目录。')
    return values


def item_payload(values):
    values = tuple(values)
    value = values[0] if len(values) == 1 else list(values)
    item_ids(value)
    return value


def named_payload(names):
    names = tuple(names)
    if (not 1 <= len(names) <= 2 or any(type(name) is not str or not re.fullmatch(r'[\u4e00-\u9fff]{2,20}', name) for name in names)):
        raise AutomationError('奖励装备名称列表不完整。')
    return names[0] if len(names) == 1 else list(names)


def items_from_names(names):
    names = tuple(names)
    named_payload(names)
    # Unknown parts retain the whole visible candidate but authorize no subset.
    if any(name not in ITEM_IDS for name in names):
        return None
    return item_payload(ITEM_IDS[name] for name in names)


def stock_counts(value):
    if (type(value) is not dict or any(type(key) is not str or not (key in GEAR or re.fullmatch(r'unknown:[0-9a-f]{64}', key))
            or type(amount) is not int or not 1 <= amount <= 14 for key, amount in value.items()) or sum(value.values()) > 14):
        raise AutomationError('奖励库存计数来源无效，未知格不能当空库存。')
    return Counter(value)
