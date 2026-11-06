"""Tab evidence for the two exact battle-pass workflow pages."""

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .free_rewards import battlepass_modal, battlepass_page
from .models import AutomationError, Token


_SCALE_DIVISORS = {(540, 960): 2, (720, 1280): 3}
# The crop origins are recorded alongside the existing 1920-wide templates.
_TABS = {'rewards': (.45, (847, 44)), 'tasks': (.50, (943, 42))}
_STANDARD_ROIS = {'rewards': (.427, .025, .474, .08), 'tasks': (.477, .025, .523, .08)}
_MATCH_MINIMUM = .94


def _underline_coverage(image, center):
    height, width = image.shape[:2]
    strip = image[round(.093 * height):round(.104 * height),
                  round((center - .020) * width):round((center + .020) * width)]
    darkest = strip.min(axis=2)
    white = (darkest >= 215) & (strip.max(axis=2) - darkest <= 24)
    return float(white.mean(axis=1).max())


def small_selection_agrees(image, selected):
    """At the calibrated sizes, corroborate the OCR heading with the tab underline."""
    if image is None or image.shape[:2] not in _SCALE_DIVISORS:
        return True
    for kind, (center, _) in _TABS.items():
        coverage = _underline_coverage(image, center)
        if (kind == selected and coverage < .90) or (kind != selected and coverage > .10):
            return False
    return True


def _small_template(base, origin, scale, divisor):
    left, top = origin
    height, width = base.shape[:2]
    # Pad to the 2- or 3-pixel source grid before resampling. Resizing the
    # isolated crop shifts fine strokes when its origin is off that grid.
    aligned = cv2.copyMakeBorder(base, top % divisor, (-top - height) % divisor,
                                 left % divisor, (-left - width) % divisor, cv2.BORDER_REPLICATE)
    return cv2.resize(aligned, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)[1:-1, 1:-1]


def _tab_template(name):
    path = RESOURCE_ROOT / 'assets' / 'templates' / (name + '.png')
    return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR) if path.is_file() else None


def _unique_match(image, template, roi, name, *, stop_on_ambiguity=False):
    if template is None or not template.size:
        return None
    height, width = image.shape[:2]
    left, top, right, bottom = (round(value * size) for value, size in zip(roi, (width, height) * 2))
    template_height, template_width = template.shape[:2]
    if template_height > bottom - top or template_width > right - left:
        return None
    scores = cv2.matchTemplate(image[top:bottom, left:right], template, cv2.TM_CCOEFF_NORMED)
    hit_y, hit_x = np.where(scores >= _MATCH_MINIMUM)
    if not hit_x.size:
        return None
    # Neighboring scores can describe one peak. Separated positions cannot.
    if np.ptp(hit_x) > 2 or np.ptp(hit_y) > 2:
        if stop_on_ambiguity:
            raise AutomationError('无名勋礼目标页签存在多个匹配位置，未发送切换。')
        return None
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    x, y = (left + x + template_width / 2) / width, (top + y + template_height / 2) / height
    return Token(name, score, (x - .008, y - .010, x + .008, y + .010))


def small_battlepass_tab(image, target):
    """Match the existing inactive glyph at native small-client scale."""
    height, width = image.shape[:2]
    divisor = _SCALE_DIVISORS.get((height, width))
    if divisor is None:
        return None
    name = f'bp_{target}_tab'
    base = _tab_template(name)
    if base is None:
        return None
    center, origin = _TABS[target]
    template = _small_template(base, origin, width / 1920, divisor)
    token = _unique_match(image, template, (center - .020, .029, center + .020, .084), name)
    if token is not None:
        x, y = token.center
        if abs(x - center) <= .005 and .052 <= y <= .066:
            return token
    return None


def exact_battlepass_tab(scene, target):
    """Use the existing standard projection, rejecting competing matches before fallback."""
    if scene.image is None or battlepass_page(scene) is None or battlepass_modal(scene):
        return None
    height, width = scene.image.shape[:2]
    baseline = cv2.resize(scene.image, (1920, round(height * 1920 / width)))
    name = f'bp_{target}_tab'
    token = _unique_match(baseline, _tab_template(name), _STANDARD_ROIS[target], name, stop_on_ambiguity=True)
    return token if token is not None else small_battlepass_tab(scene.image, target)
