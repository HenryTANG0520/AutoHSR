"""Frozen station preferences; navigation and beacon checks remain independent."""
from dataclasses import dataclass

from .models import AutomationError, normalize

LEGACY_LABELS = ('战斗','精英','首领','奖励','空白','休整','异常','事件','财富','冒险','铸造','商店')
LABELS = LEGACY_LABELS + ('奇遇','转化')
MANDATORY = frozenset(('首领','休整','转化'))
CARD_LABELS = (.20,.54,.73,.82)


def default_priorities():
    # March7thAssistant's optional custom profile, not AutoHSR's legacy order.
    return dict(zip(('战斗','精英','事件','奖励','异常','铸造','空白','商店','财富'),(1,1,2,2,2,2,3,3,3)))


@dataclass(frozen=True)
class StationPreferences:
    enabled: bool
    priority: tuple
    disabled: tuple
    confidence: float

    @classmethod
    def from_settings(cls,settings):
        from .config import SettingsError
        enabled=settings.differential_universe_station_custom
        ranks=settings.differential_universe_station_priority
        disabled=settings.differential_universe_station_disabled
        if type(enabled) is not bool:
            raise SettingsError('differential_universe_station_custom','自定义站点开关必须为布尔值。')
        if (type(ranks) is not dict or any(name not in LABELS or type(value) is not int
                or not 0<=value<=100 or name in MANDATORY and value!=0 for name,value in ranks.items())):
            raise SettingsError('differential_universe_station_priority','站点优先级须为已知站点到0～100整数的映射；首领、休整、转化固定为0。')
        if (type(disabled) is not list or any(type(name) is not str or name not in LABELS or name in MANDATORY for name in disabled)
                or len(set(disabled))!=len(disabled)):
            raise SettingsError('differential_universe_station_disabled','禁用站点须为不重复的已知站点列表，不能禁用首领、休整或转化。')
        return cls(enabled,tuple(ranks.items()),tuple(disabled),settings.ocr_confidence)

    def to_dict(self):
        return dict(enabled=self.enabled,priority=dict(self.priority),disabled=list(self.disabled),
                    mandatory=sorted(MANDATORY),unlisted_priority=100,confidence=self.confidence)

    def allowed(self,name):
        return name in LABELS and (not self.enabled or name not in self.disabled)

    def rank(self,name):
        if not self.enabled:return LEGACY_LABELS.index(name)
        return -1 if name in MANDATORY else dict(self.priority).get(name,100)

    def candidates(self,scene):
        labels=LABELS if self.enabled else LEGACY_LABELS
        return [t for t in scene.tokens if normalize(t.text) in labels and t.within(CARD_LABELS)
                and (not self.enabled or t.score>=self.confidence)]

    def ordered(self,candidates):
        if not self.enabled:
            return sorted(candidates,key=lambda t:(self.rank(normalize(t.text)),-t.score))
        return sorted((t for t in candidates if self.allowed(normalize(t.text))),
                      key=lambda t:(self.rank(normalize(t.text)),t.center[0],-t.score))

    def text_target(self,scene):
        if not self.enabled:
            for label in LEGACY_LABELS:
                target=scene.find(label,CARD_LABELS,exact=True)
                if target is not None:return target
            return None
        targets=self.ordered(self.candidates(scene))
        return targets[0] if targets else None

    def select(self,scene,template):
        target=self.text_target(scene)
        if not self.enabled and target is not None and normalize(target.text)=='战斗':
            return target,'station_select'
        combat_allowed=self.allowed('战斗')
        if (combat_allowed and (not self.enabled or target is None or self.rank('战斗')<=self.rank(normalize(target.text)))):
            match=template(scene,'du_station_combat',(.20,.32,.73,.73),threshold=.90)
            if isinstance(match,(tuple,list)) and len(match)==3 and match[2]>=.90:
                x,y,score=match
                conflicting=any(normalize(t.text)!='战斗' and abs(t.center[0]-x)<.065 for t in self.candidates(scene))
                from .models import Token
                icon=Token('差分宇宙战斗站点卡图标',score,(x-.02,y-.02,x+.02,y+.02))
                if not self.enabled or (not conflicting and (target is None or
                        (self.rank('战斗'),x)<(self.rank(normalize(target.text)),target.center[0]))):
                    return icon,'station_icon_select'
        if target is not None:return target,'station_select'
        if self.enabled and self.candidates(scene):
            raise AutomationError('当前可识别站点均已禁用；未重抽、未选择禁用项。')
        return None
