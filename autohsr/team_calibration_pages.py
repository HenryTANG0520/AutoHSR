"""Read the calibrated 4.6 phone grid for the preset calibration workflow."""
from __future__ import annotations

import re

from .challenge_pages import _clean, _inside, _overlaps
from .models import ROI, Scene, Token, normalize
from .policy import replenishment_dialog
from .workflows import DailyWorkflow


_OCR_FLOOR = .65
_LEVEL = (.656, .212, .764, .272)
_LEVEL_CAPTION = re.compile(r'开拓等级(?:\d{1,3})?')
# The observed 编队 caption is near (.687, .8454, .710, .8694).
_TEAM = (.676, .833, .722, .882)
_GUIDE = (.676, .713, .722, .762)
_BAG = (.743, .833, .790, .882)
_TASK = (.811, .833, .858, .882)

_BLOCKING_LABELS = frozenset((
    '提示', '温馨提示', '确定', '知道了', '我知道了', '兑换码', '漫游签证',
    '星际和平指南', '生存索引', '角色编队', '预设编队', '编队预设', '队伍预设',
    '队伍详情', '角色列表', '当前队伍', '切换命途',
))
_BLOCKING_PHRASES = (
    '确认', '取消', '是否', '前往编队', '进入编队', '将清空', '点击空白处关闭',
    '验证码', '扫码登录', '重新连接', '连接失败', '加载中',
)


def _grid_label(tokens: list[Token], label: str, region: ROI, minimum: float) -> Token | None:
    hits = [token for token in tokens if _overlaps(token.box, region)]
    if len(hits) != 1:
        return None
    token = hits[0]
    left, top, right, bottom = token.box
    if (token.text.strip() != label or token.score < minimum or not _inside(token.box, region)
            or not .016 <= right - left <= .034 or not .017 <= bottom - top <= .035):
        return None
    return token


def calibration_overlay(scene: Scene) -> bool:
    return (DailyWorkflow._login_blocked(scene) or DailyWorkflow._supply_overlay(scene)
            or DailyWorkflow._login_reward_overlay(scene) or replenishment_dialog(scene)
            or scene.has(('账号登录', '点击进入', '点击进入游戏'), exact=True))


def phone_team_target(scene: Scene, confidence: float = .65) -> Token | None:
    """Return the original 编队 token only on a verified current phone grid."""
    if (not isinstance(scene, Scene) or not isinstance(scene.tokens, (list, tuple))
            or type(confidence) not in (int, float) or not 0 <= confidence <= 1):
        return None
    clean = _clean(scene, _OCR_FLOOR, blockers=())
    if clean is None or calibration_overlay(clean):
        return None

    words = [normalize(token.text) for token in clean.tokens]
    if (words.count('编队') != 1 or _BLOCKING_LABELS.intersection(words)
            or any(phrase in word for phrase in _BLOCKING_PHRASES for word in words)):
        return None

    minimum = max(.85, confidence)
    levels = [token for token, word in zip(clean.tokens, words)
              if _LEVEL_CAPTION.fullmatch(word) and _overlaps(token.box, _LEVEL)]
    if len(levels) != 1 or levels[0].score < minimum or not _inside(levels[0].box, _LEVEL):
        return None

    team = _grid_label(clean.tokens, '编队', _TEAM, minimum)
    guide = _grid_label(clean.tokens, '指南', _GUIDE, minimum)
    bag = _grid_label(clean.tokens, '背包', _BAG, minimum)
    task = _grid_label(clean.tokens, '任务', _TASK, minimum)
    if team is None or guide is None or bag is None or task is None:
        return None

    team_x, team_y = team.center
    guide_x, guide_y = guide.center
    bag_x, bag_y = bag.center
    task_x, task_y = task.center
    if (abs(team_x - guide_x) > .010 or not .108 <= team_y - guide_y <= .132
            or max(team_y, bag_y, task_y) - min(team_y, bag_y, task_y) > .010
            or not .055 <= bag_x - team_x <= .082 or not .055 <= task_x - bag_x <= .082):
        return None
    return team
