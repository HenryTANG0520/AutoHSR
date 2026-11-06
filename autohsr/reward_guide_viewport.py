"""Read the calibrated Reward Guide viewport."""

from dataclasses import dataclass
from typing import Literal

import cv2

from .daily_event_navigation import _SIZE, _anchor
from .daily_reward_guide_pages import reward_guide_page
from .screenshot_tool import MAX_PIXELS


_HEADING = (118, 95, 166, 116)
_HEADING_BANDS = ((174, 101, 238, 109), (350, 101, 451, 109))
# 640x360 reference. Keep activity art, names and timers. The heading,
# account-specific reward amounts, action controls and bottom HUD lie outside.
_CONTENT = (126, 114, 468, 315)


@dataclass(frozen=True)
class RewardGuideViewport:
    content_box: tuple[int, int, int, int]
    visible_section: Literal['ongoing'] = 'ongoing'


def _content_box(width, height):
    if (type(width) is not int or type(height) is not int or width < 960 or height < 540
            or width * height > MAX_PIXELS or abs(width / height - 16 / 9) > .02):
        return None
    left, top, right, bottom = _CONTENT
    return (round(left * width / _SIZE[0]), round(top * height / _SIZE[1]),
            round(right * width / _SIZE[0]), round(bottom * height / _SIZE[1]))


def reward_guide_viewport(scene, *, client_version, confidence) -> RewardGuideViewport | None:
    """Confirm the visible Ongoing section and return its native crop box.

    The heading proves which section is visible. The calibrated footage does
    not establish a scroll target, a scrollbar position or either list end.
    """
    if not reward_guide_page(scene, client_version=client_version, confidence=confidence):
        return None
    image = cv2.resize(scene.image, _SIZE, interpolation=cv2.INTER_AREA)
    if not _anchor(image, 'reward_guide_ongoing', _HEADING, .94):
        return None
    # At the start of a fade the heading still matches, but both orange bands dim.
    for left, top, right, bottom in _HEADING_BANDS:
        band = cv2.inRange(image[top:bottom, left:right], (20, 118, 218), (112, 200, 255))
        if cv2.countNonZero(band) < .75 * band.size:
            return None
    height, width = scene.image.shape[:2]
    box = _content_box(width, height)
    return RewardGuideViewport(box) if box is not None else None
