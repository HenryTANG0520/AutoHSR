"""Anonymous visual states within an already verified message panel."""
from __future__ import annotations

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .models import AutomationError, Scene
from .vision import Vision


_UNREAD_BADGE = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/daily-message/unread_badge.png'
_LIST_BADGE_LANE = (.167, .244, .232, .80)
_REPLY_SLOT_CENTERS = (181, 197, 213)
_INNER_STRIPS = (slice(207, 227), slice(372, 389))
_OUTER_STRIPS = (slice(193, 198), slice(402, 407))


def unknown_panel_state() -> dict:
    return dict(conversation_status='unknown', unread_status='unknown',
                reply_status='unknown', reply_options=None)


def _conversation_selected(gray) -> bool:
    # Bright margins belong to the same highlighted row. Bridge the small gap
    # a row arrow or check mark can cut into the right strip.
    left = np.median(gray[66:221, 80:84], axis=1)
    right = np.median(gray[66:221, 170:176], axis=1)
    bright = np.flatnonzero(np.minimum(left, right) >= 191)
    groups = np.split(bright, np.flatnonzero(np.diff(bright) > 3) + 1)
    rows = [group for group in groups if len(group) >= 16]
    if len(rows) != 1 or not 17 <= rows[0][-1] - rows[0][0] + 1 <= 31:
        return False
    # Measure whether the pale header contains ink without reading the name.
    header = gray[46:57, 197:226]
    return np.median(header) >= 155 and np.count_nonzero(header < 125) >= 30


def _reply_options(gray) -> tuple[str, int | None]:
    visible = []
    for slot, y in enumerate(_REPLY_SLOT_CENTERS):
        core = slice(y - 3, y + 4)
        gap = slice(y + 7, y + 9)
        inner = [float(np.median(gray[core, x])) for x in _INNER_STRIPS]
        outer = [float(np.median(gray[core, x])) for x in _OUTER_STRIPS]
        contrast = min(a - b for a, b in zip(inner, outer))
        separation = min(value - np.median(gray[gap, x]) for value, x in zip(inner, _INNER_STRIPS))
        if min(inner) >= 225 and contrast >= 23 and separation >= 15:
            visible.append(slot)
        elif min(inner) >= 211 and contrast >= 8 and separation >= 8:
            return 'unknown', None
    if visible in ([0, 1], [0, 1, 2]):
        return 'options_visible', len(visible)
    return ('unknown', None) if visible else ('not_visible', None)


def _unread_badge_visible(frame, gray) -> bool:
    if not _UNREAD_BADGE.is_file():
        return False
    try:
        match = Vision.__new__(Vision).template(Scene([], frame), _UNREAD_BADGE, _LIST_BADGE_LANE, .94)
    except (AutomationError, OSError):
        return False
    if match is None:
        return False
    x, y = round(match[0] * frame.shape[1]), round(match[1] * frame.shape[0])
    blue, green, red = cv2.split(frame[y - 3:y + 4, x - 3:x + 4].astype(np.int16))
    red_pixels = (red >= 115) & (red - green >= 55) & (red - blue >= 45)
    portrait = gray[y + 3:y + 12, x - 12:x - 5]
    return np.count_nonzero(red_pixels) >= 8 and np.median(portrait) >= 95


def read_panel_state(frame) -> dict:
    """Read a verified panel normalized to 480×270 without exporting pixels or OCR."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    state = unknown_panel_state()
    if _unread_badge_visible(frame, gray):
        state['unread_status'] = 'badge_visible'
    if _conversation_selected(gray):
        state['conversation_status'] = 'selected'
        state['reply_status'], state['reply_options'] = _reply_options(gray)
    return state
