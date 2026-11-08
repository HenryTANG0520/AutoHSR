"""Phone camera entry and ordinary viewfinder checks for daily navigation."""

import math

from .build_target_read import _has_split_label
from .config import RESOURCE_ROOT
from .currency_wars_prepare import trusted
from .models import FULL, Token


CAMERA_LAYOUT_VERSION = '4.6.0'
_ASSETS = RESOURCE_ROOT / 'assets' / 'upstream' / 'March7thAssistant' / 'camera'
_MENU_ROI = (.95, .48, .995, .58)
_MENU_CENTER = (.964, .515, .982, .55)
_VIEWFINDER_ROI = (.83, .22, .995, .89)
_CAMERA_CONTROLS = ('缩放', '镜头缩放', '重置朝向', '切换镜头')
_OTHER_PHOTO_MODES = ('拍摄结束', '已发现目标', '发现目标', '目标已锁定', '目标识别',
                      '笑点', '拍摄评价', '任务拍摄', '编辑', '保存', '分享')


def _anchor(scene, vision, name, region, threshold):
    height, width = scene.image.shape[:2]
    if width <= 0 or not .54 <= height / width <= .59:
        return None
    match = vision.template(scene, _ASSETS / name, region, threshold, require_unique=True)
    if (match is None or len(match) != 3 or not all(math.isfinite(value) for value in match)
            or not threshold <= match[2] <= 1):
        return None
    x, y, score = match
    if region[0] <= x <= region[2] and region[1] <= y <= region[3]:
        return x, y, score
    return None


def camera_menu_target(scene, vision, confidence):
    match = _anchor(scene, vision, 'menu.png', _MENU_ROI, max(.92, confidence))
    if match is None:
        return None
    x, y, score = match
    if _MENU_CENTER[0] <= x <= _MENU_CENTER[2] and _MENU_CENTER[1] <= y <= _MENU_CENTER[3]:
        return Token('相机', score, (x-.006, y-.008, x+.006, y+.008))
    return None


def other_camera_mode(scene):
    visible = trusted(scene, .65)
    return visible.has(_OTHER_PHOTO_MODES, exact=True) or _has_split_label(visible, _OTHER_PHOTO_MODES, FULL)


def ordinary_viewfinder(scene, vision, confidence):
    if other_camera_mode(scene):
        return False
    visible = trusted(scene, confidence)
    if not visible.has(_CAMERA_CONTROLS, (.25, .53, .999, .98), exact=True):
        return False
    # The pale translucent template scores about .981 even on a flat patch.
    match = _anchor(scene, vision, 'shutter.png', _VIEWFINDER_ROI, max(.99, confidence))
    if match is None:
        return False
    x, y, _ = match
    return visible.has('F', (x-.07, y-.09, min(1., x+.065), min(1., y+.12)), exact=True)
