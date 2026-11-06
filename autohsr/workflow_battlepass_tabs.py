"""Small-client tab evidence for the two exact battle-pass workflow pages."""

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .models import Token


_SCALE_DIVISORS = {(540, 960): 2, (720, 1280): 3}
# The crop origins are recorded alongside the existing 1920-wide templates.
_TABS = {'rewards': (.45, (847, 44)), 'tasks': (.50, (943, 42))}
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


def _small_template(path, origin, scale, divisor):
    base = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if base is None:
        return None
    left, top = origin
    height, width = base.shape[:2]
    # Pad to the 2- or 3-pixel source grid before resampling. Resizing the
    # isolated crop shifts fine strokes when its origin is off that grid.
    aligned = cv2.copyMakeBorder(base, top % divisor, (-top - height) % divisor,
                                 left % divisor, (-left - width) % divisor, cv2.BORDER_REPLICATE)
    return cv2.resize(aligned, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)[1:-1, 1:-1]


def small_battlepass_tab(image, target):
    """Match the existing inactive glyph at native small-client scale."""
    height, width = image.shape[:2]
    divisor = _SCALE_DIVISORS.get((height, width))
    if divisor is None:
        return None
    center, origin = _TABS[target]
    name = f'bp_{target}_tab'
    path = RESOURCE_ROOT / 'assets' / 'templates' / (name + '.png')
    if not path.is_file():
        return None
    template = _small_template(path, origin, width / 1920, divisor)
    if template is None or not template.size:
        return None
    left, right = round((center - .020) * width), round((center + .020) * width)
    top, bottom = round(.029 * height), round(.084 * height)
    template_height, template_width = template.shape[:2]
    if template_height > bottom - top or template_width > right - left:
        return None
    scores = cv2.matchTemplate(image[top:bottom, left:right], template, cv2.TM_CCOEFF_NORMED)
    hit_y, hit_x = np.where(scores >= _MATCH_MINIMUM)
    if not hit_x.size or np.ptp(hit_x) > 2 or np.ptp(hit_y) > 2:
        return None
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    x, y = (left + x + template_width / 2) / width, (top + y + template_height / 2) / height
    if abs(x - center) > .005 or not .052 <= y <= .066:
        return None
    return Token(name, score, (x - .008, y - .010, x + .008, y + .010))
