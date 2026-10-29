"""Ordered support preferences; never alter the user's own preset team."""
from dataclasses import dataclass
from functools import lru_cache
import json
from types import MappingProxyType

from .config import RESOURCE_ROOT,SettingsError


@lru_cache(maxsize=1)
def catalogue():
    path=RESOURCE_ROOT/'assets/upstream/March7thAssistant/support/sources.json'
    data=json.loads(path.read_text('utf8'))
    return MappingProxyType({item['character']:MappingProxyType(item) for item in data['images']})


@dataclass(frozen=True)
class Preference:
    character: str
    friend: str


def preferences(value):
    if type(value) is not list or len(value)>256:
        raise SettingsError('support_preferences','支援偏好须为最多256项的列表。')
    result=[];seen=set()
    for index,item in enumerate(value):
        if type(item) is not dict or set(item)!={'character','friend'} or any(type(item[k]) is not str for k in item):
            raise SettingsError('support_preferences',f'支援偏好第{index+1}项须含角色和好友名称。')
        character,friend=item['character'].strip(),item['friend'].strip()
        if character:
            names=catalogue()
            if character not in names:
                matches=[key for key,row in names.items() if row['name']==character]
                if len(matches)!=1:raise SettingsError('support_preferences',f'支援偏好第{index+1}项角色未知或名称不唯一，请选具体角色标识。')
                character=matches[0]
        if len(friend)>40 or not character and not friend:
            raise SettingsError('support_preferences',f'支援偏好第{index+1}项至少指定角色或好友，昵称最多40字。')
        key=character,friend
        if key in seen:raise SettingsError('support_preferences','支援偏好不能重复。')
        seen.add(key);result.append(Preference(*key))
    return tuple(result)


def validate(settings):
    value=preferences(settings.support_preferences)
    if type(settings.support_scroll_pages) is not int or not 1<=settings.support_scroll_pages<=20:
        raise SettingsError('support_scroll_pages','支援查找页数应为1～20，包含当前页。')
    if settings.support_fallback not in ('stop','friend','skip'):
        raise SettingsError('support_fallback','支援回退请选择stop、friend或skip。')
    if not value and settings.support_fallback!='stop':
        raise SettingsError('support_fallback','支援回退仅用于已配置的偏好。')
    return value
