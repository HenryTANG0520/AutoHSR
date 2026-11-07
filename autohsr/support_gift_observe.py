"""Recognize the upstream gift indicator without assigning reward or payment state."""

from functools import lru_cache
from hashlib import sha256

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .daily_visa_pages import VISA_LAYOUT_VERSION
from .models import AutomationError


_ASSET = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/reward/support-gift.png'
_DIGEST = '19a7bfa037549d1e7aa45586ce1a66f9e58f295849a5b8c40a50e73292aefa31'
_SUPPORT_AREA = (.56, .18, .94, .54)


@lru_cache(maxsize=1)
def _template():
    try:
        with _ASSET.open('rb') as stream:
            raw = stream.read(4713)
        if len(raw) == 4712 and sha256(raw).hexdigest() == _DIGEST:
            return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    except (OSError, cv2.error):
        pass
    return None


def _gift_center(scene, vision):
    template = _template()
    match = getattr(vision, 'template', None)
    if template is None or not callable(match):
        return None
    try:
        found = match(scene, _ASSET, _SUPPORT_AREA, .975, require_unique=True)
    except (AutomationError, OSError, cv2.error):
        return None
    if not isinstance(found, tuple) or len(found) != 3:
        return None
    x, y, _ = found
    image = scene.image
    height, width = image.shape[:2]
    scaled = cv2.resize(template, None, fx=width / 1920, fy=width / 1920)
    sh, sw = scaled.shape[:2]
    left, top = round(x * width - sw / 2), round(y * height - sh / 2)
    patch = image[top:top + sh, left:left + sw]
    if patch.shape != (sh, sw, 3):
        return None
    color = scaled[:, :, :3].astype(np.int16)
    blue, green, red = color.transpose(2, 0, 1)
    opaque = scaled[:, :, 3] >= 240
    badge = opaque & (green < 90) & (red > 130) & (red > blue + 45)
    if not badge.any():
        return None
    difference = np.abs(patch.astype(np.int16) - color)
    if difference[opaque].mean() <= 18 and difference[badge].mean() <= 22:
        return x, y
    return None


def observe_support_gift(scenes, vision):
    first, second = (_gift_center(scene, vision) for scene in scenes)
    visible = first is not None and second is not None and all(abs(a - b) <= .006 for a, b in zip(first, second))
    return dict(indicator='visible' if visible else 'unknown',
                claimable_state='unknown', claim_receipt_status='not_observed')


def gift_receipt(navigation):
    value = navigation.get('support_gift_observation')
    if (navigation.get('target') == 'visa_characters' and navigation.get('page_verified') is True
            and navigation.get('client_version') == VISA_LAYOUT_VERSION
            and isinstance(value, dict) and value.get('indicator') in ('visible', 'unknown')
            and value == dict(indicator=value['indicator'], claimable_state='unknown',
                              claim_receipt_status='not_observed')):
        return dict(value)
    return None
