"""Immutable multi-dungeon targets; execution never edits saved preferences."""
from dataclasses import dataclass,asdict
import hashlib
import json

from .dungeons import CATEGORIES


@dataclass(frozen=True)
class PowerItem:
    category: str
    target: str
    location: str
    count: int

    @property
    def dungeon(self):return next(c for c in CATEGORIES if c.key==self.category)

    def to_dict(self):return asdict(self)


def items(value):
    from .config import SettingsError
    if type(value) is not list or len(value)>1000:
        raise SettingsError('power_plan','体力计划须为最多1000项的列表。')
    result=[];categories={c.key:c for c in CATEGORIES}
    for i,raw in enumerate(value):
        if (type(raw) is not dict or set(raw)!={'category','target','location','count'}
                or type(raw['category']) is not str or raw['category'] not in categories
                or any(type(raw[k]) is not str or not 2<=len(raw[k].strip())<=100 for k in ('target','location'))
                or type(raw['count']) is not int or not 1<=raw['count']<=9999):
            raise SettingsError('power_plan',f'体力计划第{i+1}项须含明确分类、名称、地点和1～9999的整数次数。')
        result.append(PowerItem(raw['category'],raw['target'].strip(),raw['location'].strip(),raw['count']))
    return tuple(result)


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def spec_digest(value):
    return digest(sorted(value,key=digest))


def row_keys(value):
    seen={};result=[]
    for raw in value:
        key=digest(raw);ordinal=seen.get(key,0);seen[key]=ordinal+1
        result.append(digest([key,ordinal]))
    return result


def plan_spec(settings):
    from .config import SettingsError
    value=items(settings.power_plan)
    if not value:raise SettingsError('power_plan','请先配置至少一项体力计划。')
    for name in ('power_plan_keep','power_plan_fill'):
        if type(getattr(settings,name)) is not bool:raise SettingsError(name,'保留体力计划和补刷默认副本开关必须为布尔值。')
    return value,spec_digest([item.to_dict() for item in value])
