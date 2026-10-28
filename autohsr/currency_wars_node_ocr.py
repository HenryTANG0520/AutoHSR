"""Read battle node fields without the adjacent icon or progress percentage.

Full-screen OCR is retained as evidence. A bounded read must agree in native
and thresholded pixels; neither the expected node nor a substring is supplied
to the recognizer. Failed/conflicting field reads do not fall back to raw OCR.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace

from .currency_wars_pages import classify_page
from .models import Token, normalize


NODE_PATTERN = r'[1-3]-[1-9][0-9]?'
# Search regions, not number crops. Icon widths and number widths move the
# dividers, so a fixed number crop can cut a digit or include the percentage.
BATTLE_FIELDS = {
    'currency_battle_node.normal': (.335, 0, .412, .06),
    'currency_battle_node.reward': (.285, 0, .366, .06),
}
DIVIDERS = {'currency_battle_node.normal': (.375, .410),
            'currency_battle_node.reward': (.329, .365)}


def _field_box(image, name):
    """Locate the short percentage divider and the taller icon frame edge."""
    import cv2
    import numpy as np
    height, width = image.shape[:2]
    x1, y1, x2, y2 = BATTLE_FIELDS[name]
    left = round(x1*width)
    patch = image[:round(y2*height), left:round(x2*width)]
    if patch.size == 0 or height < 540 or width < 960:
        return None
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
    step = max(2, round(width/1920))
    contrast = gray[:, step:-step] - (gray[:, :-2*step]+gray[:, 2*step:])/2
    inside = (contrast[round(.008*height):round(.042*height)] > 5).mean(axis=0)
    outside = np.concatenate((contrast[:round(.004*height)],
                              contrast[round(.048*height):round(.055*height)]))
    outside = (outside > 5).mean(axis=0)
    low, high = DIVIDERS[name]
    columns = [i+step for i in range(len(inside)) if inside[i] >= .85 and outside[i] <= .35
               and low <= (left+i+step)/width <= high]
    if not columns or columns[-1]-columns[0] > max(3, round(.0015*width)):
        return None  # No unique divider; never infer the expected node width.
    right = columns[0]
    edges = (np.abs(gray[:round(.045*height), :-2*step]
                    - gray[:round(.045*height), 2*step:]) > 12).mean(axis=0)
    candidates = [i+step for i, score in enumerate(edges) if score >= .86
                  and right-round(.06*width) < i+step < right-round(.018*width)]
    if not candidates:
        return None
    start = max(candidates)+round(.001*width)
    end = right-round(.001*width)
    if not .018 <= (end-start)/width <= .055:
        return None
    return ((left+start)/width, round(.008*height)/height,
            (left+end)/width, round(.040*height)/height)


def refine_battle_node(scene, reader):
    if scene.image is None or classify_page(scene.tokens) != 'battle':
        return scene
    import cv2
    height, width = scene.image.shape[:2]
    reads = dict(scene.field_reads)
    for name in BATTLE_FIELDS:
        roi = _field_box(scene.image, name)
        if roi is None:
            reads[name] = (None, None)
            continue
        x1, y1, x2, y2 = roi
        patch = scene.image[round(y1*height):round(y2*height), round(x1*width):round(x2*width)]
        if patch.size == 0:
            reads[name] = (None, None)
            continue
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        binary = cv2.threshold(gray, 155, 255, cv2.THRESH_BINARY)[1]
        variants = []
        for pixels in (patch, cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)):
            token = reader.read_node(pixels)
            variants.append(None if token is None else Token(token.text, token.score, roi))
        reads[name] = tuple(variants)
    return replace(scene, field_reads=reads)


def _value(token, confidence):
    if (token is None or not math.isfinite(token.score) or not confidence <= token.score <= 1
            or not re.fullmatch(NODE_PATTERN, normalize(token.text))):
        return None
    return normalize(token.text)


def bounded_battle_node(scene, confidence=.65):
    """Return (attempted, value); attempted failure must not use legacy OCR."""
    attempted = any(name in scene.field_reads for name in BATTLE_FIELDS)
    if not attempted:
        return False, None
    values, agreed = set(), set()
    for name, region in BATTLE_FIELDS.items():
        variants = scene.field_reads.get(name, ())
        if len(variants) != 2:
            continue
        boxes = {t.box for t in variants if t is not None}
        if len(boxes) > 1:
            return True, None
        readings = [_value(t, max(.9, confidence)) if t is None or
                    (region[0] <= t.box[0] < t.box[2] <= region[2]
                     and region[1] <= t.box[1] < t.box[3] <= region[3]) else None for t in variants]
        values.update(value for value in readings if value is not None)
        if readings[0] is not None and readings[0] == readings[1]:
            agreed.add(readings[0])
    return True, next(iter(agreed)) if len(agreed) == 1 and agreed == values else None
