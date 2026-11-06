"""Read the 4.6 encounter notice and the separate green gold HUD chip."""
from __future__ import annotations

from dataclasses import replace
import re

import cv2
import numpy as np

from .currency_wars_prepare import trusted
from .models import Token, normalize


TITLE = '遭遇节点奖励'
TITLE_FIELD = 'currency_encounter_notice.title'
QUANTITY_FIELD = 'currency_encounter_notice.quantity'
GREEN_FIELD = 'currency_encounter_notice.hud_green'
NODE_FIELD = 'currency_encounter_notice.hud_node'
_TITLE = ((343/768, 195/480, 423/768, 214/480), (337/768, 195/480, 432/768, 213/480))
_ICON = (.479, .463, .522, .525)
_QUANTITY = (.502, .499, .523, .527)
_GREEN = (.813, .778, .894, .841)
_GREEN_NUMBER = (648/768, 377/480, 664/768, 395/480)
_NODE = (.105, .017, .302, .119)
_NODE_TEXT = re.compile(r'[1-3]-[1-9][0-9]?')
_AMOUNT = re.compile(r'[1-9][0-9]?')


def _image(scene):
    image = scene.image
    if (isinstance(image, np.ndarray) and image.ndim == 3 and image.shape[2] == 3
            and image.dtype == np.uint8 and image.shape[0] >= 360 and image.shape[1] >= 640):
        return image
    return None


def _crop(image, region):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = region
    return image[round(y1*height):round(y2*height), round(x1*width):round(x2*width)]


def _gold_icon(image):
    patch = cv2.resize(_crop(image, _ICON), (33, 30), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (8, 80, 85), (38, 255, 255))
    fraction = np.count_nonzero(mask) / mask.size
    if not .28 <= fraction <= .60:
        return False
    merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    outline = max(contours, key=cv2.contourArea)
    x, y, width, height = cv2.boundingRect(outline)
    # Bound the round gold tile and exclude a solid highlight or side ornament.
    return (1 <= x <= 6 and 0 <= y <= 6 and 22 <= width <= 31 and 19 <= height <= 28
            and .55 <= cv2.contourArea(outline)/(width*height) <= .82)


def _green_chip(image):
    patch = cv2.resize(_crop(image, _GREEN), (62, 30), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (40, 30, 120), (95, 255, 255))
    warm = cv2.inRange(hsv[:, :30], (8, 80, 85), (38, 255, 255))
    _, _, stats, _ = cv2.connectedComponentsWithStats(green)
    return (np.count_nonzero(warm) >= 17 and
            any(30 <= width <= 53 and 13 <= height <= 26 and area >= 360
                for _, _, width, height, area in stats[1:]))


def _zoom(image, region):
    return cv2.resize(_crop(image, region), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)


def _normalized_gray(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)


def _project(value, region):
    return None if value is None else Token(value.text, value.score, region)


def _read_tokens(scene, region, pattern, confidence):
    return [token for token in trusted(scene, confidence).tokens if token.within(region)
            and pattern.fullmatch(normalize(token.text))]


def supplement(scene, reader):
    """Bound the local fields to their observed pixel widgets in the OCR worker."""
    image = _image(scene)
    if image is None or not hasattr(reader, '_read_field') or not hasattr(reader, 'read_number'):
        return scene
    fields = dict(scene.field_reads)
    if _gold_icon(image):
        fields[TITLE_FIELD] = tuple(_project(reader._read_field(_normalized_gray(_zoom(image, roi)), r'.{4,12}'), roi)
                                    for roi in _TITLE)
        fields[QUANTITY_FIELD] = (_project(reader.read_number(_zoom(image, _QUANTITY)), _QUANTITY),)
    if _green_chip(image):
        fields[GREEN_FIELD] = (_project(reader.read_number(_zoom(image, _GREEN_NUMBER)), _GREEN_NUMBER),)
    if fields == scene.field_reads:
        return scene
    local = _read_tokens(reader.read(_zoom(image, _NODE)), (0, 0, 1, 1), _NODE_TEXT, .85)
    fields[NODE_FIELD] = (_project(local[0] if len(local) == 1 else None, _NODE),)
    return replace(scene, field_reads=fields)


def _read_field(scene, name, regions, pattern, confidence):
    values = scene.field_reads.get(name, ())
    if len(values) != len(regions):
        return None
    texts = []
    for token, region in zip(values, regions):
        if token is None or token.box != region or not max(.85, confidence) <= token.score <= 1:
            return None
        texts.append(normalize(token.text))
    return texts[0] if all(text == texts[0] for text in texts) and pattern.fullmatch(texts[0]) else None


def read_notice(scene, confidence):
    image = _image(scene)
    if image is None or not _gold_icon(image):
        return None
    competing = _read_tokens(scene, _TITLE[1], re.compile(r'[一-鿿]{2}节点奖励'), min(.65, confidence))
    if any(normalize(token.text) != TITLE for token in competing):
        return None
    title = _read_field(scene, TITLE_FIELD, _TITLE, re.compile(TITLE), confidence)
    quantity = _read_field(scene, QUANTITY_FIELD, (_QUANTITY,), _AMOUNT, confidence)
    return int(quantity) if title == TITLE and quantity is not None else None


def read_green(scene, confidence):
    image = _image(scene)
    if image is None or not _green_chip(image):
        return None
    quantity = _read_field(scene, GREEN_FIELD, (_GREEN_NUMBER,), _AMOUNT, confidence)
    return int(quantity) if quantity is not None else None


def read_node(scene, confidence):
    direct = {normalize(token.text) for token in _read_tokens(scene, _NODE, _NODE_TEXT, min(.65, confidence))}
    local = _read_field(scene, NODE_FIELD, (_NODE,), _NODE_TEXT, confidence)
    if local is not None and direct <= {local}:
        return local
    strong = {normalize(token.text) for token in _read_tokens(scene, _NODE, _NODE_TEXT, max(.85, confidence))}
    if local is None and len(strong) == 1 and strong == direct:
        return next(iter(strong))
    return None
