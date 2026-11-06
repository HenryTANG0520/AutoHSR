"""Read the 4.6 journey event entry and Gift of Odyssey sign-in page."""
from dataclasses import dataclass

import numpy as np

from .challenge_pages import _clean, _inside, _overlaps
from .models import normalize
from .team_calibration_pages import _grid_label, calibration_overlay, phone_team_target
from .vision import helper_overlay


_VERSION = '4.6.0'
_ENTRY = (.670, .476, .729, .520)
_SYNTHESIS = (.816, .476, .853, .520)
_SHOP = (.670, .357, .711, .401)

_TITLE = (.825, .148, .972, .215)
_NOTEBOOK = (.047, .051, .115, .101)
_RULES = (.870, .101, .972, .153)
_NOTEBOOK_LABELS = ('活动札记', '活动礼记')
_RULES_LABELS = ('活动说明', '1活动说明', '活动说期', '1活动说期')
_BLOCKERS = ('获得物品', '点击空白处关闭', '点空白处关闭', '确认购买', '退出登录',
             '切换账号', '重新连接', '加载中', '签到详情')
_CENTERS = ((.551, .551), (.638, .551), (.725, .551),
            (.551, .774), (.638, .774), (.725, .774), (.829, .774))
_RAILS = ((.593, .472), (.680, .472), (.768, .472), (.680, .688), (.768, .688))


@dataclass(frozen=True)
class OdysseyObservation:
    claimable_days: tuple[int, ...]
    claimed_days: tuple[int, ...]
    unknown_days: tuple[int, ...]


def _visible_scene(scene, client_version, confidence):
    if (type(client_version) is not str or client_version != _VERSION
            or type(confidence) not in (float, int) or not 0 <= confidence <= 1
            or not isinstance(getattr(scene, 'tokens', None), (list, tuple))):
        return None
    clean = _clean(scene, .65, blockers=())
    if (clean is None or calibration_overlay(clean) or helper_overlay(clean)
            or clean.has(_BLOCKERS, exact=True)
            or clean.has('活动说明', (.25, .06, .75, .88), exact=True)):
        return None
    return clean


def _label(scene, words, roi, minimum):
    hits = [token for token in scene.tokens if _overlaps(token.box, roi) and normalize(token.text) in words]
    if len(hits) != 1 or hits[0].score < minimum or not _inside(hits[0].box, roi):
        return None
    return hits[0]


def phone_journey_event_entry(scene, *, client_version, confidence=.65):
    """Observe the exact 4.6 旅情事记 caption on the independently verified phone grid."""
    clean = _visible_scene(scene, client_version, confidence)
    if clean is None or phone_team_target(clean, confidence) is None:
        return None
    if sum(normalize(token.text) == '旅情事记' for token in clean.tokens) != 1:
        return None
    minimum = max(.85, confidence)
    entry = _label(clean, ('旅情事记',), _ENTRY, minimum)
    synthesis = _grid_label(clean.tokens, '合成', _SYNTHESIS, minimum)
    shop = _grid_label(clean.tokens, '商店', _SHOP, minimum)
    if (entry is not None and synthesis is not None and shop is not None
            and abs(entry.center[1] - synthesis.center[1]) <= .010
            and .105 <= entry.center[1] - shop.center[1] <= .136
            and abs(entry.center[0] - shop.center[0]) <= .013):
        return entry
    return None


def _pale_fraction(image, x, y, dx, dy):
    height, width = image.shape[:2]
    patch = image[round((y - dy) * height):round((y + dy) * height),
                  round((x - dx) * width):round((x + dx) * width)]
    blue, green, red = np.moveaxis(patch, 2, 0)
    return float(np.mean((red >= 210) & (green >= 195) & (blue >= 160)))


def _day_state(scene, x, y, confidence):
    bounds = (x - .044, y - .022, x + .044, y + .022)
    label = _label(scene, ('领取', '已领取'), bounds, max(.75, confidence))
    if label is None:
        return 'unknown'
    pale = _pale_fraction(scene.image, x, y, .039, .017)
    if normalize(label.text) == '领取' and pale >= .40:
        return 'claimable'
    if normalize(label.text) == '已领取' and pale <= .10:
        return 'claimed'
    return 'unknown'


def read_gift_of_odyssey(scene, *, client_version, confidence=.65) -> OdysseyObservation | None:
    """Separate the verified page from each independently readable reward card."""
    clean = _visible_scene(scene, client_version, confidence)
    if clean is None:
        return None
    title = _label(clean, ('巡星之礼',), _TITLE, max(.90, confidence))
    if (title is None or any(token is not title and token.within(_TITLE) and len(normalize(token.text)) >= 3
                             for token in clean.tokens)
            or not _label(clean, _NOTEBOOK_LABELS, _NOTEBOOK, max(.80, confidence))
            or not _label(clean, _RULES_LABELS, _RULES, max(.80, confidence))):
        return None
    # The pale rails delimit three short columns and the separate full-height day seven.
    if any(_pale_fraction(clean.image, x, y, .003, .048) < .60 for x, y in _RAILS):
        return None
    observed = tuple(_day_state(clean, x, y, confidence) for x, y in _CENTERS)
    days = {state: tuple(day for day, status in enumerate(observed, 1) if status == state)
            for state in ('claimable', 'claimed', 'unknown')}
    return OdysseyObservation(days['claimable'], days['claimed'], days['unknown'])
