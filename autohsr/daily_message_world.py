"""Read-only location of the red-marked SMS bubble in the calibrated PC world HUD."""
from __future__ import annotations

import cv2
import numpy as np

from .challenge_pages import _clean
from .config import RESOURCE_ROOT
from .daily_message_observe import message_panel
from .daily_reward_observe import COLLECTION_FLOOR, _blocked
from .models import AutomationError, Scene, Token
from .vision import Vision, helper_overlay
from .workflows import DailyWorkflow


_WIDTH, _HEIGHT = 852, 480
_TEMPLATES = RESOURCE_ROOT / 'assets/templates'
_BUBBLE = _TEMPLATES / 'daily_message_world_bubble.png'
_WORLD_ANCHOR = _TEMPLATES / 'world_character.png'
_WORLD_ROI = (.93, 0, 1, .09)
_BUBBLE_ROI = (86, 84, 137, 123)
_BADGE_ROI = (86, 76, 144, 123)
_CLOSE_HINTS = ('点击空白处关闭', '点击任意位置关闭', '点击空白处继续')


def _matched_bubble(frame, glyph, mask):
    left, top, right, bottom = _BUBBLE_ROI
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(gray[top:bottom, left:right], glyph, cv2.TM_CCOEFF_NORMED, mask=mask)
    rows, columns = np.nonzero(np.isfinite(scores) & (scores >= .88))
    if not rows.size:
        return None
    xs, ys = columns + left, rows + top

    badge_left, badge_top, badge_right, badge_bottom = _BADGE_ROI
    b, g, r = cv2.split(frame[badge_top:badge_bottom, badge_left:badge_right].astype(np.int16))
    red = (r >= 142) & (r - g >= 43) & (r - b >= 22) & (g < 177)
    _, _, stats, centers = cv2.connectedComponentsWithStats(red.astype(np.uint8), connectivity=8)
    candidate = None
    for (_, _, width, height, area), (cx, cy) in zip(stats[1:], centers[1:]):
        if not (8 <= width <= 14 and 8 <= height <= 15 and .65 <= width / height <= 1.5 and 38 <= area <= 120):
            continue
        dx, dy = cx + badge_left - xs, cy + badge_top - ys
        aligned = np.flatnonzero((19 <= dx) & (dx <= 24) & (-1 <= dy) & (dy <= 4))
        if aligned.size:
            if candidate is not None:
                return None
            best = aligned[np.argmax(scores[rows[aligned], columns[aligned]])]
            candidate = int(xs[best]), int(ys[best]), min(1., float(scores[rows[best], columns[best]]))
    if candidate is None:
        return None

    x, y, score = candidate
    height, width = glyph.shape
    # Normalized correlation keeps matching the glyph during the first fade.
    # Check the original white pixels on the left, clear of the badge and pointer.
    stencil = (glyph[4:17, :16] >= 210) & (mask[4:17, :16] != 0)
    if not stencil.any() or np.median(gray[y + 4:y + 17, x:x + 16][stencil]) < 246:
        return None
    return Token('world_message_badge', score, (x / _WIDTH, y / _HEIGHT, (x + width) / _WIDTH, (y + height) / _HEIGHT))


def world_message_target(scene: Scene) -> Token | None:
    """Return the observed bubble box in this scene. The box carries no input authority."""
    clean = _clean(scene, COLLECTION_FLOOR, blockers=())
    if (clean is None or helper_overlay(clean) or _blocked(clean) or DailyWorkflow._phone(clean)
            or DailyWorkflow._navigation_page(clean) or DailyWorkflow._login(clean)
            or clean.has('获得物品', (.25, .04, .75, .50))
            or clean.has(_CLOSE_HINTS, (.25, .65, .75, .97), exact=True)):
        return None
    try:
        reference = cv2.imdecode(np.frombuffer(_BUBBLE.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
        if reference is None or reference.shape != (22, 25, 4):
            return None
        frame = cv2.resize(clean.image, (_WIDTH, _HEIGHT), interpolation=cv2.INTER_AREA)
        glyph = cv2.cvtColor(reference[:, :, :3], cv2.COLOR_BGR2GRAY)
        target = _matched_bubble(frame, glyph, reference[:, :, 3].copy())
        if (target is None or Vision.__new__(Vision).template(clean, _WORLD_ANCHOR, _WORLD_ROI, .65) is None
                or message_panel(clean)):
            return None
        return target
    except (AutomationError, OSError, cv2.error):
        return None
