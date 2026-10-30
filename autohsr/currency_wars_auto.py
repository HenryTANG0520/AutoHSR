"""Read-only CW auto control observations; no off target or input authority.

Real CW crops and independent DU-on/planar-disabled references are recorded in
assets/currency-auto/sources.json. There is no calibrated real off sample. A
white glyph, a missing C, or an absent control therefore never means off/on.
The caller still owns fresh-scene, node, account, version and input-epoch gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import math
from typing import Literal

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .currency_wars import observe


AUTO_ROI = (.88, .0, .95, .10)
PAUSE_ROI = (.95, .0, 1., .10)
ON_SCORE = .92
REFERENCE_SCORE = .90
DIM_SCORE = .92
PAUSE_SCORE = .92

_REFERENCES = {
    'on': ('currency-auto/auto_on.png', '9c5726bc2f89f0ee62ccbecaf1bc0c903f7c0dff6b868fd3d6a6065cc8cdfbea', 2),
    'dim': ('currency-auto/auto_dim.png', '7b731bfa15a81219e9ac88e43132c100b1f4015865a6a444eac49229381f0382', 2),
    'du_on': ('templates/du_auto_anchor.png', '1755526a68729798a367b3cc62981c23f33ee4bc5e3a63d018d64508f3daebea', 1),
    'planar_dim': ('templates/planar_auto_dim.png', '11432bf8abb34d47ccddaeb6e3bb9fbc5889d9d62b447c13aed48c8c4439b3e4', 1),
    'pause': ('templates/du_battle_pause.png', 'eec8ec6a5296ff0567276398bda21fca4cc0968820d73a4b8bd535197a27b5ef', 1),
}


@dataclass(frozen=True)
class AutoObservation:
    state: Literal['on', 'disabled', 'unknown']
    score: float
    diagnostics: tuple[tuple[str, str | float | bool], ...]

    def to_dict(self):
        """Anonymous JSON data; no points, identity, images or local paths."""
        return dict(state=self.state, score=self.score, diagnostics=dict(self.diagnostics))


def _result(state='unknown', score=0., *, reason, **diagnostics):
    values = dict(reason=reason, off_calibrated=False, **diagnostics)
    return AutoObservation(state, round(float(score), 6), tuple(values.items()))


@lru_cache(maxsize=1)
def _templates():
    result = {}
    for key, (relative, expected, divisor) in _REFERENCES.items():
        raw = (RESOURCE_ROOT / 'assets' / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('reference_hash')
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('reference_image')
        if divisor != 1:
            image = cv2.resize(image, None, fx=1/divisor, fy=1/divisor)
        result[key] = image
    return result


def _match(image, template, roi):
    left, top, right, bottom = (round(v*s) for v, s in zip(roi, (1920, 1080, 1920, 1080)))
    patch = image[top:bottom, left:right]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    needle = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    th, tw = needle.shape
    scores = cv2.matchTemplate(gray, needle, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(scores)
    if not math.isfinite(score):
        return 0., (0, 0, tw, th), False
    x, y = point
    # Nearby pixel maxima describe one glyph; a separate equally plausible
    # glyph is ambiguous, even when the best match alone exceeds a threshold.
    remaining = scores.copy()
    remaining[max(0, y-th//2):y+th//2+1, max(0, x-tw//2):x+tw//2+1] = -1
    second = float(remaining.max())
    unique = not math.isfinite(second) or second < min(.88, score-.04)
    return float(score), (left+x, top+y, tw, th), unique


def _aligned(first, second):
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return abs(ax+aw/2-bx-bw/2) <= 3 and abs(ay+ah/2-by-bh/2) <= 3


def _group(auto, pause):
    ax, ay, aw, ah = auto
    px, py, pw, ph = pause
    dx = px+pw/2-ax-aw/2
    dy = py+ph/2-ay-ah/2
    return 70 <= dx <= 135 and abs(dy) <= 10


def _gold(image, box, template):
    x, y, width, height = box
    patch = cv2.cvtColor(image[y:y+height, x:x+width], cv2.COLOR_BGR2HSV)
    ref = cv2.cvtColor(template, cv2.COLOR_BGR2HSV)
    mask = (ref[:, :, 0] >= 15) & (ref[:, :, 0] <= 40) & (ref[:, :, 1] > 80) & (ref[:, :, 2] > 150)
    gold = (patch[:, :, 0] >= 15) & (patch[:, :, 0] <= 40) & (patch[:, :, 1] > 80) & (patch[:, :, 2] > 150)
    return float(gold.mean()), float(gold[mask].mean()) if mask.any() else 0.


def read_auto(scene, confidence=.65) -> AutoObservation:
    """Observe on/disabled/unknown, without creating a clickable location.

    This pure pixel/page reader does not authorize input or prove that a toggle
    happened. In particular, unknown and disabled must never become off.
    """
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        return _result(reason='invalid_confidence')
    if scene is None or not hasattr(scene, 'tokens') or observe(scene, confidence).page_kind != 'battle':
        return _result(reason='not_cw_battle')
    image = getattr(scene, 'image', None)
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
            or image.shape[2] != 3 or image.shape[0] < 540 or image.shape[1] < 960
            or abs(image.shape[1]/image.shape[0]-16/9) > .01):
        return _result(reason='unsupported_image')
    try:
        references = _templates()
    except (OSError, ValueError, cv2.error):
        return _result(reason='reference_unavailable')
    normalized = cv2.resize(image, (1920, 1080))
    matches = {key: _match(normalized, template, PAUSE_ROI if key == 'pause' else AUTO_ROI)
               for key, template in references.items()}
    scores = {key: round(value[0], 6) for key, value in matches.items()}
    score = max(scores['on'], scores['dim'])
    pause_score, pause_box, pause_unique = matches['pause']
    if pause_score < PAUSE_SCORE or not pause_unique:
        return _result(score=score, reason='pause_context_missing', **scores)
    on_score, on_box, on_unique = matches['on']
    du_score, du_box, du_unique = matches['du_on']
    dim_score, dim_box, dim_unique = matches['dim']
    planar_score, planar_box, planar_unique = matches['planar_dim']
    gold, coverage = _gold(normalized, on_box, references['on'])
    on = (on_score >= ON_SCORE and du_score >= REFERENCE_SCORE and on_unique and du_unique
          and _aligned(on_box, du_box) and _group(on_box, pause_box)
          and gold >= .12 and coverage >= .75)
    dim_gold, _ = _gold(normalized, dim_box, references['on'])
    disabled = (dim_score >= DIM_SCORE and planar_score >= DIM_SCORE and dim_unique and planar_unique
                and _aligned(dim_box, planar_box) and _group(dim_box, pause_box) and dim_gold < .02)
    diagnostics = dict(scores, gold_fraction=round(gold, 6), gold_coverage=round(coverage, 6))
    if on and not disabled:
        return _result('on', on_score, reason='cw_and_real_on_reference', **diagnostics)
    if disabled and not on:
        return _result('disabled', dim_score, reason='cw_and_real_disabled_reference', **diagnostics)
    return _result(score=score, reason='state_not_calibrated' if not on and not disabled else 'conflicting_states',
                   **diagnostics)
