"""Identify the 4.6 event list and reward-guide controls."""
from functools import lru_cache

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .daily_event_pages import _NOTEBOOK, _NOTEBOOK_LABELS, _label, _visible_scene
from .models import Token


_SIZE = 640, 360
_BADGE = (104, 8, 136, 35)
_CAPTION = (126, 14, 176, 30)
_LIST = (15, 62, 82, 329)


@lru_cache(maxsize=5)
def _template(name):
    path = RESOURCE_ROOT / 'assets' / 'templates' / f'{name}.png'
    try:
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error):
        return None
    if image is not None and float(np.std(image, axis=(0, 1)).max()) >= 2:
        return image
    return None


def _scores(image, name, region):
    template = _template(name)
    if template is None:
        return None
    x, y, right, bottom = region
    patch = image[y:bottom, x:right]
    height, width = template.shape[:2]
    if not 0 < height <= patch.shape[0] or not 0 < width <= patch.shape[1]:
        return None
    scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
    return np.nan_to_num(scores, nan=-1., posinf=-1., neginf=-1.), width, height


def _anchor(image, name, region, minimum):
    match = _scores(image, name, region)
    return match is not None and float(match[0].max()) >= minimum


def _guide_control(image):
    badge = _scores(image, 'event_rewards_badge', _BADGE)
    if badge is None:
        return None
    scores, width, height = badge
    _, peak, _, (x, y) = cv2.minMaxLoc(scores)
    x, y = x + _BADGE[0], y + _BADGE[1]
    bright = np.all(image[y:y + height, x:x + width] >= 182, axis=2)
    if peak < .92 or float(bright.mean()) < .20:
        return None
    caption = _scores(image, 'event_rewards_caption', _CAPTION)
    if caption is None:
        return None
    scores, width, height = caption
    _, peak, _, (x, y) = cv2.minMaxLoc(scores)
    if peak < .91:
        return None
    x += _CAPTION[0]
    y += _CAPTION[1]
    return Token('奖励指南', peak, (x / _SIZE[0], y / _SIZE[1],
                                  (x + width) / _SIZE[0], (y + height) / _SIZE[1]))


def reward_guide_entry(scene, *, client_version, confidence):
    """Observe the top activity-list button by its badge and caption."""
    clean = _visible_scene(scene, client_version, confidence)
    if clean is None:
        return None
    image = cv2.resize(clean.image, _SIZE, interpolation=cv2.INTER_AREA)
    guide = _guide_control(image)
    if guide is None:
        return None
    notebook = _label(clean, _NOTEBOOK_LABELS, _NOTEBOOK, max(.80, confidence))
    if _odyssey_banner(image) is not None or notebook is not None and _activity_sidebar_visible(image):
        return guide
    return None


def _activity_sidebar_visible(image):
    rows = image[62:329].astype(np.int16)
    edge = np.abs(rows[:, 20:23] - rows[:, 15:18]).mean(axis=(1, 2))
    return sum(np.count_nonzero(band >= 35) >= 28 for band in np.array_split(edge, 4)) >= 3


def odyssey_list_entry(scene, *, client_version, confidence):
    """Return one visually distinct unselected banner in the activity list."""
    clean = _visible_scene(scene, client_version, confidence)
    if clean is None:
        return None
    image = cv2.resize(clean.image, _SIZE, interpolation=cv2.INTER_AREA)
    if _guide_control(image) is None:
        return None
    return _odyssey_banner(image)


def _odyssey_banner(image):
    match = _scores(image, 'event_odyssey_row', _LIST)
    if match is None:
        return None
    scores, width, height = match
    _, peak, _, (x, y) = cv2.minMaxLoc(scores)
    if peak < .93:
        return None
    # Ignore neighbouring matches on this banner, but reject a second distinct row.
    scores[max(0, y - height):y + height + 1, :] = -1
    if float(scores.max()) > peak - .12:
        return None
    x += _LIST[0]
    y += _LIST[1]
    return Token('巡星之礼', peak, (x / _SIZE[0], y / _SIZE[1],
                                  (x + width) / _SIZE[0], (y + height) / _SIZE[1]))
