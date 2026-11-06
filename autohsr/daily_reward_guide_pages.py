"""Identify the open 4.6 Reward Guide on its Journey Highlights tab."""

import cv2

from .daily_event_navigation import _anchor, _SIZE
from .daily_event_pages import _label, _visible_scene


_TITLE = (5, 6, 80, 39)
_BANNER = (163, 54, 284, 87)
_TAB = (.046, .119, .126, .185)
_DIALOG = (.19, .12, .82, .88)
_DIALOG_LABELS = ('确认', '取消', '确定', '知道了', '验证码', '连接失败')

# Reference pixels at 640x360, excluding text, rewards and list artwork.
_SURFACES = (
    ((82, 43, 99, 69), (45, 137, 210), (125, 204, 255)),  # Amber selected tab.
    ((341, 53, 451, 84), (149, 135, 42), (255, 220, 130)),  # Cyan banner.
    ((365, 114, 447, 317), (208, 210, 208), (255, 255, 255)),  # Pale list body.
)


def _bright_surfaces(image):
    for (left, top, right, bottom), lower, upper in _SURFACES:
        mask = cv2.inRange(image[top:bottom, left:right], lower, upper)
        if cv2.countNonZero(mask) < .75 * mask.size:
            return False
    return True


def reward_guide_page(scene, *, client_version, confidence) -> bool:
    """Confirm the visible, selected Highlights layout from one fresh frame."""
    clean = _visible_scene(scene, client_version, confidence)
    if (clean is None or clean.has(_DIALOG_LABELS, _DIALOG, exact=True)
            or _label(clean, ('旅程热点',), _TAB, max(.85, confidence)) is None):
        return False
    image = cv2.resize(clean.image, _SIZE, interpolation=cv2.INTER_AREA)
    # Template correlation can remain high while the page fades out.
    return (_bright_surfaces(image)
            and _anchor(image, 'reward_guide_title', _TITLE, .94)
            and _anchor(image, 'reward_guide_highlights_banner', _BANNER, .93))
