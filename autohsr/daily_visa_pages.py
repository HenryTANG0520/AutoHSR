"""Classify observed overview layouts of the 4.6 Trailblazer Profile.

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


VISA_LAYOUT_VERSION = '4.6.0'

_TITLE = (.028, .020, .132, .120)
_SUBTITLE = (.028, .045, .145, .160)
_RULE = (.835, .020, .950, .141)
_TABS = (
    ('战绩展示', (.348, .045, .454, .170)),
    ('角色展示', (.451, .045, .554, .170)),
    ('收集展示', (.550, .045, .662, .170)),
)
_SHOWCASE_BODY = (.55, .18, .94, .67)
_SUPPORT_HEADING = (.575, .198, .690, .307)
_COMPANION_HEADING = (.590, .540, .690, .635)
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


def _visa_tabs(scene, confidence, selected):
    if (not isinstance(scene, Scene) or type(confidence) not in (int, float) or not 0 <= confidence <= 1
            or not isinstance(scene.image, np.ndarray) or scene.image.dtype != np.uint8
            or scene.image.ndim != 3 or scene.image.shape[2] != 3
            or scene.image.shape[0] < 360 or scene.image.shape[1] < 640):
        return None
    visible = trusted(scene, .65)
    if (calibration_overlay(visible) or helper_overlay(visible)
            or visible.has(_MODAL_LABELS, exact=True) or visible.has(_MODAL_PHRASES)
            or visible.has(_MODAL_BODY_PHRASES, _MODAL_BODY)
            or visible.has('物品', _MODAL_BODY, exact=True)
            or _has_split_label(visible, _MODAL_LABELS, FULL)
            or _has_split_label(visible, _MODAL_PHRASES, FULL, exact=False)):
        return None

    minimum = max(.85, confidence)
    if selected == '角色展示':
        if (_landmark(visible, '支援角色', _SUPPORT_HEADING, minimum) is None
                or _landmark(visible, '星海同行', _COMPANION_HEADING, minimum) is None):
            return None
    elif visible.has(('支援角色', '星海同行'), _SHOWCASE_BODY, exact=True):
        return None

    title = _landmark(visible, '漫游签证', _TITLE, minimum)
    subtitle = _landmark(visible, selected, _SUBTITLE, minimum, copies=2)
    rule = _landmark(visible, '规则说明', _RULE, minimum)
    tabs = {label: _landmark(visible, label, area, minimum, copies=2 if label == selected else 1)
            for label, area in _TABS}
    if title is None or subtitle is None or rule is None or any(tab is None for tab in tabs.values()):
        return None
    if (_has_split_label(visible, tuple(label for label in tabs if label != selected), _SUBTITLE)
            or not .013 <= subtitle.center[1] - title.center[1] <= .045
            or abs(subtitle.center[0] - title.center[0]) > .025):
        return None
    ordered_tabs = tuple(tabs.values())
    tab_y = [tab.center[1] for tab in ordered_tabs]
    if (max(tab_y) - min(tab_y) > .012
            or not .023 <= tab_y[0] - title.center[1] <= .065
            or any(not .074 <= right.center[0] - left.center[0] <= .124
                   for left, right in zip(ordered_tabs, ordered_tabs[1:]))):
        return None

    active = _tab_highlight(scene.image, tabs[selected])
    inactive = (_tab_highlight(scene.image, tab) for label, tab in tabs.items() if label != selected)
    if min(active) >= .80 and all(max(pill) <= .10 for pill in inactive):
        return tabs
    return None


def visa_overview(scene, confidence=.85):
    """Return whether one frame matches the profile's collection overview."""
    return _visa_tabs(scene, confidence, '收集展示') is not None


def visa_support_section(scene, confidence=.85):
    """Return whether the selected character showcase has its support section."""
    return _visa_tabs(scene, confidence, '角色展示') is not None


def visa_character_tab(scene, *, client_version, confidence=.85):
    """Locate the unselected character tab on the calibrated collection page."""
    if client_version != VISA_LAYOUT_VERSION:
        return None
    tabs = _visa_tabs(scene, confidence, '收集展示')
    if tabs is None:
        return None
    tab = tabs['角色展示']
    height, width = scene.image.shape[:2]
    left, top, right, bottom = (round(value * size) for value, size in zip(tab.box, (width, height) * 2))
    pixels = scene.image[top:bottom, left:right]
    if pixels.shape[0] < 7 or pixels.shape[1] < 16:
        return None
    # Check the pale strokes in all four glyph positions against the dark tab
    # fill. OCR alone can retain the old label while the control is obscured.
    for glyph in np.array_split(pixels, 4, axis=1):
        bright = (glyph.min(axis=2) >= 110).mean()
        dark = (glyph.max(axis=2) <= 95).mean()
        if not .09 <= bright <= .42 or dark < .50:
            return None
    return tab
