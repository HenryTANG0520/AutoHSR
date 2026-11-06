"""Recognize the 4.6 achievement overview from its independent page landmarks."""
from .currency_wars_prepare import trusted
from .models import normalize
from .team_calibration_pages import calibration_overlay
from .workflows import TITLE


_CATEGORIES = frozenset({
    '我开拓者', '通往群星的轨道', '战意奔涌', '流光遗痕', '果壳中的宇宙',
    '不屈者的荣光', '瞬息欢愉', '与你同行的回忆', '众秘探奇',
})
_CAROUSEL = (.06, .56, .96, .71)
_SUMMARY = (.28, .81, .60, .93)
_MODAL = (.20, .16, .83, .83)
_BLOCKERS = ('确认', '确定', '取消', '获得物品', '请选择', '筛选条件', '请输入关键词', '点击空白处关闭')


def achievement_overview(scene, confidence=.85):
    visible = trusted(scene, .65)
    if (calibration_overlay(visible) or visible.has(_BLOCKERS, _MODAL, exact=True)
            or visible.has('开拓等级', (.55, .05, .99, .35))):
        return False
    minimum = max(.85, confidence)
    for label, region in (('成就', TITLE), ('达成成就', _SUMMARY)):
        found = [token for token in visible.tokens if token.within(region) and normalize(token.text) == label]
        if len(found) != 1 or found[0].score < minimum:
            return False
    cards = sorted((token for token in visible.tokens if token.within(_CAROUSEL)
                    and normalize(token.text) in _CATEGORIES), key=lambda token: token.center[0])
    if (len({normalize(token.text) for token in cards}) != len(cards)
            or any(right.center[0] - left.center[0] < .055 for left, right in zip(cards, cards[1:]))):
        return False
    strong = [token for token in cards if token.score >= minimum]
    return len(strong) >= 3 and max(token.center[1] for token in strong) - min(token.center[1] for token in strong) <= .075
