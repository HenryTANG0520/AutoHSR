"""Visual fields in the calibrated ordinary 4.6 Chaos result."""
from dataclasses import dataclass

import cv2
import numpy as np

from .challenge_pages import _overlaps
from .models import ROI, normalize


@dataclass(frozen=True)
class Detail:
    level: int
    level_glyphs: tuple[ROI, ...]
    goal_stars: tuple[ROI, ROI, ROI]

    def agrees_with(self, other):
        return (other is not None and self.level == other.level
                and all(_overlaps(a, b) for a, b in zip(self.level_glyphs, other.level_glyphs))
                and all(_overlaps(a, b) for a, b in zip(self.goal_stars, other.goal_stars)))


def _patch(image, region):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = (round(value * size) for value, size in zip(region, (width, height, width, height)))
    return cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2HSV), x1, y1


def _level(image, caption, region, success):
    caption = normalize(caption)
    if caption not in ('物竞天择其十', '物竞天择其十一'):
        return None
    height, width = image.shape[:2]
    scale = width / 1280
    hsv, x, y = _patch(image, region)
    ink = cv2.inRange(hsv, (8, 0, 87), (48, 255, 255)) != 0
    columns = np.flatnonzero(ink.any(axis=0))
    runs = np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1)
    glyphs = []
    for columns in runs:
        rows, _ = np.nonzero(ink[:, columns])
        if len(rows) < 5 * scale**2:
            continue
        left, right = int(columns[0]), int(columns[-1]) + 1
        top, bottom = int(rows.min()), int(rows.max()) + 1
        glyphs.append((left, top, right, bottom))
    if (len(glyphs) not in (6, 7)
            or any(not 9 * scale <= right - left <= 15 * scale for left, _, right, _ in glyphs)
            or any(not 12 * scale <= b[0] - a[0] <= 16 * scale for a, b in zip(glyphs, glyphs[1:]))
            or any(not 8 * scale <= bottom - top <= 15 * scale for _, top, _, bottom in glyphs[:6])):
        return None

    # The title is centered above the success caption. A clipped final 一
    # would shift the entire visible title left by half a glyph.
    title_center = (x + (glyphs[0][0] + glyphs[-1][2]) / 2) / width
    if abs(title_center - (success[0] + success[2]) / 2) > .003:
        return None
    left, top, right, bottom = glyphs[5]
    cross = ink[top:bottom, left:right]
    bars = np.flatnonzero(cross.sum(axis=1) >= .70 * cross.shape[1])
    if (not bars.size or bars[-1] - bars[0] + 1 > 4 * scale
            or cross.sum(axis=0).max() < .65 * cross.shape[0]):
        return None

    if len(glyphs) == 7:
        last_left, last_top, last_right, last_bottom = glyphs[6]
        stroke = ink[last_top:last_bottom, last_left:last_right]
        if (stroke.shape[0] > 3 * scale or stroke.sum(axis=1).max() < .80 * stroke.shape[1]
                or abs((last_top + last_bottom) / 2 - (top + bars.mean() + .5)) > 3 * scale):
            return None
    elif caption.endswith('十一'):
        return None
    boxes = tuple(((x + a) / width, (y + b) / height, (x + c) / width, (y + d) / height)
                  for a, b, c, d in glyphs[5:])
    return len(glyphs) + 4, boxes


def _gold_star(image, row, goal):
    height, width = image.shape[:2]
    scale = width / 1280
    hsv, x, y = _patch(image, (.267, row[1], .305, row[3]))
    mask = cv2.inRange(hsv, (11, 45, 175), (39, 255, 255))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    components = [i for i, (_, _, _, _, area) in enumerate(stats) if i and area >= 10 * scale**2]
    if len(components) != 1:
        return None
    index = components[0]
    left, top, span_x, span_y, area = stats[index]
    if (not 12 * scale <= span_x <= 18.5 * scale or not 12 * scale <= span_y <= 18.5 * scale
            or not .24 <= area / (span_x * span_y) <= .45):
        return None
    shape = labels[top:top + span_y, left:left + span_x] == index
    if shape.sum(axis=0).max() < .80 * span_y or shape.sum(axis=1).max() < .80 * span_x:
        return None
    box = ((x + left) / width, (y + top) / height,
           (x + left + span_x) / width, (y + top + span_y) / height)
    center_x, center_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return box if .282 <= center_x <= .299 and abs(center_y - (goal[1] + goal[3]) / 2) <= .009 else None


def observe(image, caption, title_region, success_box, goal_regions, goal_boxes):
    level = _level(image, caption, title_region, success_box)
    if level is None:
        return None
    stars = tuple(_gold_star(image, region, box) for region, box in zip(goal_regions, goal_boxes))
    if any(star is None for star in stars) or max(s[0] for s in stars) - min(s[0] for s in stars) > .004:
        return None
    return Detail(*level, stars)
