"""Classify the collection overview layout of the 4.6 Trailblazer Profile.

The caller owns account, window, freshness and consecutive frame checks.
This predicate has no input authority and makes no observation about rewards.
"""
import numpy as np

from .build_target_read import _has_split_label
from .challenge_pages import _inside
from .currency_wars_prepare import trusted
from .models import FULL, Scene, normalize
from .team_calibration_pages import calibration_overlay
from .vision import helper_overlay


_TITLE = (.028, .020, .132, .120)
_SUBTITLE = (.028, .045, .145, .160)
_RULE = (.835, .020, .950, .141)
_TABS = (
    ('战绩展示', (.348, .045, .454, .170)),
    ('角色展示', (.451, .045, .554, .170)),
    ('收集展示', (.550, .045, .662, .170)),
)
_SUBPAGES = ('战绩展示', '角色展示')
_SHOWCASE_BODY = (.55, .18, .94, .67)
_MODAL_BODY = (.18, .18, .82, .90)
_MODAL_LABELS = (
    '提示', '温馨提示', '确认', '确定', '取消', '知道了', '我知道了', '支援奖励', '奖励详情',
    '奖励明细', '选择角色', '确认修改', '兑换码', '手机装饰', '开拓穿搭', '列车补给',
    '新消息通知', '切换账号', '退出登录',
)
_MODAL_PHRASES = (
    '获得物品', '点击空白处关闭', '点击任意位置关闭', '点击空白处继续',
    '支付', '付款', '购买', '续订', '续购', '充值', '验证码', '扫码登录', '重新连接', '加载中',
)
# In the modal body these are counterevidence even when OCR only sees one
# fragment of a longer receipt or help heading.
_MODAL_BODY_PHRASES = ('支援奖励', '奖励详情', '奖励明细', '领取记录', '规则说明', '获得物')


def _landmark(scene, label, area, minimum, *, copies=1):
    # Check duplicates at the lower collection threshold, including an OCR
    # box for a different view or a modal that moved out of the expected area.
    matches = [token for token in scene.tokens if normalize(token.text) == label]
    local = [token for token in matches if _inside(token.box, area)]
    if len(matches) == copies and len(local) == 1 and local[0].score >= minimum:
        return local[0]
    return None


def _tab_highlight(image, token):
    height, width = image.shape[:2]
    x, y = token.center
    top, bottom = round((y - .007) * height), round((y + .007) * height)
    values = []
    # The strips are inside the pill, to either side of the four text glyphs.
    for offset in (-.034, .034):
        left = round((x + offset - .0035) * width)
        right = round((x + offset + .0035) * width)
        strip = image[top:bottom, left:right]
        darkest = strip.min(axis=2)
        near_white = (darkest >= 200) & (strip.max(axis=2) - darkest <= 24)
        values.append(float(near_white.mean()))
    return values


def visa_overview(scene, confidence=.85):
    """Return whether one frame matches the profile's collection overview."""
    if (not isinstance(scene, Scene) or type(confidence) not in (int, float) or not 0 <= confidence <= 1
            or not isinstance(scene.image, np.ndarray) or scene.image.dtype != np.uint8
            or scene.image.ndim != 3 or scene.image.shape[2] != 3
            or scene.image.shape[0] < 360 or scene.image.shape[1] < 640):
        return False
    visible = trusted(scene, .65)
    if (calibration_overlay(visible) or helper_overlay(visible)
            or visible.has(_MODAL_LABELS, exact=True) or visible.has(_MODAL_PHRASES)
            or visible.has(_MODAL_BODY_PHRASES, _MODAL_BODY)
            or visible.has('物品', _MODAL_BODY, exact=True)
            or visible.has(('支援角色', '星海同行'), _SHOWCASE_BODY, exact=True)
            or _has_split_label(visible, _MODAL_LABELS, FULL)
            or _has_split_label(visible, _MODAL_PHRASES, FULL, exact=False)):
        return False

    minimum = max(.85, confidence)
    title = _landmark(visible, '漫游签证', _TITLE, minimum)
    subtitle = _landmark(visible, '收集展示', _SUBTITLE, minimum, copies=2)
    rule = _landmark(visible, '规则说明', _RULE, minimum)
    tabs = [_landmark(visible, label, area, minimum, copies=2 if label == '收集展示' else 1)
            for label, area in _TABS]
    if title is None or subtitle is None or rule is None or any(tab is None for tab in tabs):
        return False
    if (_has_split_label(visible, _SUBPAGES, _SUBTITLE)
            or not .013 <= subtitle.center[1] - title.center[1] <= .045
            or abs(subtitle.center[0] - title.center[0]) > .025):
        return False
    tab_y = [tab.center[1] for tab in tabs]
    if (max(tab_y) - min(tab_y) > .012
            or not .023 <= tab_y[0] - title.center[1] <= .065
            or any(not .074 <= right.center[0] - left.center[0] <= .124 for left, right in zip(tabs, tabs[1:]))):
        return False

    battle, characters, collection = [_tab_highlight(scene.image, tab) for tab in tabs]
    return min(collection) >= .80 and max(battle + characters) <= .10
