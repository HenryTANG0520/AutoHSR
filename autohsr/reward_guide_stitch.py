"""Join verified Reward Guide list crops in their original scroll order."""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np


_MAX_PAGES = 3
_MAX_INPUT_EDGE = 4096
_MAX_INPUT_PIXELS = 12_000_000
_MAX_CANDIDATES = 16
_PIXEL_TOLERANCE = 4

StitchStatus = Literal['ok', 'invalid', 'limit', 'duplicate', 'ambiguous', 'no_overlap',
                       'wrong_direction', 'inconsistent']


@dataclass(frozen=True)
class RewardGuideStitch:
    status: StitchStatus
    image: np.ndarray | None = None
    overlap_rows: tuple[int, ...] = ()


def _vertical_edges(image):
    height, width = image.shape[:2]
    narrow = cv2.resize(image, (min(width, 192), height), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(narrow, cv2.COLOR_BGR2GRAY)
    return np.diff(gray.astype(np.float32), axis=0)


def _informative(edges):
    active = np.abs(edges) >= 5
    return (np.count_nonzero(active.any(axis=1)) >= max(3, edges.shape[0] // 8)
            and np.count_nonzero(active.any(axis=0)) >= max(8, edges.shape[1] // 8))


def _same_pixels(first, second):
    return cv2.norm(first, second, cv2.NORM_INF) <= _PIXEL_TOLERANCE


def _verified_overlaps(first, second, first_edges, second_edges, minimum):
    """Return compatible row counts, or None when too many candidates remain."""
    height = first.shape[0]
    rows = np.arange(minimum, height)
    # At an overlap of k rows the old bottom strip begins at k-minimum in
    # the new crop, and the new top strip begins at height-k in the old crop.
    anchors = ((first_edges[-(minimum - 1):], second_edges, rows - minimum),
               (second_edges[:minimum - 1], first_edges, height - rows))
    eligible = np.ones(len(rows), dtype=bool)
    used_anchor = False
    for strip, search, indices in anchors:
        if _informative(strip):
            used_anchor = True
            scores = cv2.matchTemplate(search, strip, cv2.TM_CCOEFF_NORMED)[:, 0]
            eligible &= scores[indices] >= .97
    if not used_anchor:
        return ()
    candidates = rows[eligible]
    if len(candidates) > _MAX_CANDIDATES:
        return None
    return tuple(int(k) for k in candidates if _same_pixels(first[-k:], second[:k]))


def stitch_reward_guide(crops: list[np.ndarray] | tuple[np.ndarray, ...]) -> RewardGuideStitch:
    """Join 1–3 fixed-size BGR crops from a caller-verified continuous source.

    Supply stable, equal crop rectangles in downward scroll order. An ``ok``
    result covers the supplied crops. Failed joins expose only the earlier
    verified overlap sizes. Page identity and list completeness are upstream.
    """
    if not isinstance(crops, (list, tuple)) or not crops:
        return RewardGuideStitch('invalid')
    if len(crops) > _MAX_PAGES:
        return RewardGuideStitch('limit')
    if any(not isinstance(crop, np.ndarray) or crop.dtype != np.uint8
           or crop.ndim != 3 or crop.shape[2] != 3 or min(crop.shape[:2]) < 64
           for crop in crops):
        return RewardGuideStitch('invalid')
    height, width = crops[0].shape[:2]
    if any(crop.shape != crops[0].shape for crop in crops):
        return RewardGuideStitch('invalid')
    if max(height, width) > _MAX_INPUT_EDGE or height * width * len(crops) > _MAX_INPUT_PIXELS:
        return RewardGuideStitch('limit')

    # Keep owned pixels for both matching and assembly, including crop views.
    frames = tuple(crop.copy(order='C') for crop in crops)
    if len(frames) == 1:
        return RewardGuideStitch('ok', frames[0])
    edges = tuple(_vertical_edges(frame) for frame in frames)
    minimum = max(32, height // 8)
    overlaps = []
    starts = [0]
    for i in range(1, len(frames)):
        current = frames[i]
        prefix = tuple(overlaps)
        if any(_same_pixels(previous, current) for previous in frames[:i]):
            return RewardGuideStitch('duplicate', overlap_rows=prefix)
        forward = _verified_overlaps(frames[i - 1], current, edges[i - 1], edges[i], minimum)
        reverse = _verified_overlaps(current, frames[i - 1], edges[i], edges[i - 1], minimum)
        if forward is None or reverse is None or len(forward) + len(reverse) > 1:
            return RewardGuideStitch('ambiguous', overlap_rows=prefix)
        if not forward:
            return RewardGuideStitch('wrong_direction' if reverse else 'no_overlap', overlap_rows=prefix)

        overlap = forward[0]
        start = starts[-1] + height - overlap
        # A short second scroll can expose pixels also present in the first crop.
        for previous, previous_start in zip(frames[:i - 1], starts[:-1]):
            shared = previous_start + height - start
            if shared > 0 and not _same_pixels(previous[-shared:], current[:shared]):
                return RewardGuideStitch('inconsistent', overlap_rows=prefix)
        starts.append(start)
        overlaps.append(overlap)

    image = np.concatenate((frames[0], *(frame[k:] for frame, k in zip(frames[1:], overlaps))))
    return RewardGuideStitch('ok', image, tuple(overlaps))
