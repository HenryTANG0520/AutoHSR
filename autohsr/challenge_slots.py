"""Read-only challenge slot evidence and explicit two-team comparison."""
from dataclasses import dataclass, field
import hashlib
import math
from types import MappingProxyType

import cv2
import numpy as np

from . import challenge_pages, challenge_roster
from .challenge_identities import unit_key
from .challenge_plan import ChallengePlan, MODE_LIMITS
from .currency_wars_identity import account_key
from .models import AutomationError, ROI, Scene


_APOCALYPTIC = 'apocalyptic_shadow'
_EMPTY = 'empty_slot_marker'


@dataclass(frozen=True)
class _SlotLayout:
    source: str
    offsets: tuple[tuple[ROI, ...], tuple[ROI, ...]]
    empty_marker: np.ndarray | None = None


# Team numerals, the generic node team control and the buff plus glyph do
# not locate member slots. Add only layouts backed by actual mode captures.
_SLOT_LAYOUTS = MappingProxyType({})


@dataclass(frozen=True)
class RosterCapture:
    scene: Scene = field(repr=False)
    input_epoch: int
    ordinal: int
    plan_digest: str


def _setup(page):
    kind = 'node_setup' if page.mode == _APOCALYPTIC else 'team_setup'
    return page.mode in MODE_LIMITS and page.kind == kind


def _node(page):
    return page.basis.get('selected_node') if page.mode == _APOCALYPTIC else None


def _team_origins(page):
    if page.mode == _APOCALYPTIC:
        nodes = page.basis.get('nodes', ())
        headers = [[row['label_box'] for row in nodes if row['node'] == team] for team in (1, 2)]
    else:
        matches = page.basis.get('matches', ())
        headers = [[hit['box'] for hit in matches if hit['asset'] == f'forgottenhall/team{team}.png']
                   for team in (1, 2)]
    if any(len(boxes) != 1 for boxes in headers):
        return None
    return tuple(tuple(boxes[0][:2]) for boxes in headers)


def _scope(page):
    return page.kind, page.mode, page.level, _node(page), _team_origins(page)


def _unknown_slot(position, box=None):
    return dict(position=position, box=list(box) if box is not None else None,
                occupancy='unknown', identity_status='unknown', asset_id=None)


def _unknown_teams():
    return [[_unknown_slot(position) for position in range(1, 5)] for _ in range(2)]


def _unknown(reason):
    return dict(schema=1, status='unknown', reason=reason, layout_source=None, teams=_unknown_teams(),
                availability='unknown', eight_slots_occupied=None, eight_identities_known=None,
                team_members_match=None, slot_order_match=None, execution_supported=False)


def _slot_boxes(layout, page):
    origins = _team_origins(page)
    if (not isinstance(layout, _SlotLayout) or not isinstance(layout.source, str) or not layout.source
            or origins is None or len(layout.offsets) != 2 or any(len(team) != 4 for team in layout.offsets)):
        return None
    teams = tuple(tuple((x + left, y + top, x + right, y + bottom) for left, top, right, bottom in row)
                  for (x, y), row in zip(origins, layout.offsets))
    boxes = [box for row in teams for box in row]
    for box in boxes:
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
            return None
    overlaps = challenge_roster._overlap
    list_roi = challenge_roster._result(page.mode)['roi']
    if (any(overlaps(box, list_roi) for box in boxes)
            or any(overlaps(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])):
        return None
    return teams


def _slot_bank(layout, width):
    bank = challenge_roster._scaled_references(width)
    marker = layout.empty_marker
    if marker is None:
        return bank
    if (not isinstance(marker, np.ndarray) or marker.dtype != np.uint8 or marker.ndim != 3
            or marker.shape[2] != 3 or not 8 <= min(marker.shape[:2]) <= max(marker.shape[:2]) <= 256):
        raise ValueError('invalid empty slot marker')
    scale = width / 1920
    image = cv2.resize(marker, (round(marker.shape[1] * scale), round(marker.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.std() < 8:
        raise ValueError('unreadable empty slot marker')
    source = dict(layout=layout.source, pixel_sha256=hashlib.sha256(marker.tobytes()).hexdigest())
    return (*bank, (_EMPTY, image, gray, source))


def _read_slot(image, box, position, bank):
    slot = _unknown_slot(position, box)
    candidates, ambiguities = challenge_roster._group(challenge_roster._scan_box(image, box, bank))
    if len(candidates) == 1 and not ambiguities:
        match = candidates[0]
        if match['asset_id'] == _EMPTY:
            return dict(slot, occupancy='empty', evidence=match)
        return dict(slot, occupancy='occupied', identity_status='exact', asset_id=match['asset_id'],
                    evidence=match)
    if not candidates and len(ambiguities) == 1 and _EMPTY not in ambiguities[0]['asset_ids']:
        return dict(slot, occupancy='occupied', identity_status='ambiguous',
                    alternatives=ambiguities[0]['asset_ids'], evidence=ambiguities[0]['matches'])
    return slot


def _observe_slots(scene, page):
    if not _setup(page):
        return _unknown('unverified_setup_page')
    layout = _SLOT_LAYOUTS.get(page.mode)
    if layout is None:
        return _unknown('missing_slot_calibration')
    if (type(page.level) is not int or not 1 <= page.level <= MODE_LIMITS[page.mode]
            or page.mode == _APOCALYPTIC and (type(_node(page)) is not int or _node(page) not in (1, 2))):
        return _unknown('unverified_level_or_node')
    image = challenge_roster._scan_image(scene)
    if image is None:
        return _unknown('invalid_or_stale_scene')
    try:
        boxes = _slot_boxes(layout, page)
        if boxes is None:
            return _unknown('invalid_slot_calibration')
        bank = _slot_bank(layout, image.shape[1])
        teams = [[_read_slot(image, box, position, bank) for position, box in enumerate(row, 1)]
                 for row in boxes]
    except (OSError, ValueError, KeyError, TypeError, cv2.error):
        return _unknown('unverified_slot_scan')
    if not challenge_roster._fresh(scene):
        return _unknown('scene_expired_during_scan')
    return dict(_unknown('single_capture'), status='observed', layout_source=layout.source, teams=teams)


def _setup_roster(scene, page):
    """Attach read-only detail to the observation from this same capture."""
    candidates = challenge_roster.observe_candidates(scene, mode=page.mode) if _setup(page) else None
    return dict(candidate_list=candidates, team_slots=_observe_slots(scene, page))


def observe_setup_roster(scene, confidence=.65):
    """Observe list candidates and independent slot states on a recognized setup page."""
    page = challenge_pages.observe(scene, confidence)
    return dict(mode=page.mode, level=page.level, selected_node=_node(page), **_setup_roster(scene, page))


def _consecutive(plan, first, second):
    if (not isinstance(first, RosterCapture) or not isinstance(second, RosterCapture)
            or not isinstance(first.scene, Scene) or not isinstance(second.scene, Scene)
            or type(first.plan_digest) is not str or type(second.plan_digest) is not str
            or first.scene is second.scene):
        return False
    if any(type(n) is not int or n < 0 for n in
           (first.input_epoch, second.input_epoch, first.ordinal, second.ordinal)):
        return False
    return (first.input_epoch == second.input_epoch and first.ordinal + 1 == second.ordinal
            and first.plan_digest == second.plan_digest == plan.digest
            and challenge_roster._fresh(first.scene) and challenge_roster._fresh(second.scene)
            and first.scene.captured_at < second.scene.captured_at)


def _shared_account(scenes, confidence):
    try:
        # A second complete UID at collection confidence is a conflict even
        # when only one of the two candidates clears the positive threshold.
        keys = {account_key(scene, threshold) for scene in scenes for threshold in (confidence, max(.85, confidence))}
    except (AutomationError, AttributeError, TypeError, ValueError):
        return None
    return keys.pop() if len(keys) == 1 else None


def _pixel_keys(scenes):
    images = tuple(scene.image for scene in scenes)
    if not all(isinstance(image, np.ndarray) and image.dtype == np.uint8 and image.size <= 16_777_216 * 3
               for image in images):
        return None
    return tuple((image.shape, hashlib.sha256(image.tobytes()).digest()) for image in images)


def _consensus(first, second):
    slot = _unknown_slot(first['position'], first['box'])
    if first['occupancy'] != second['occupancy'] or first['occupancy'] == 'unknown':
        return slot
    slot['occupancy'] = first['occupancy']
    slot['evidence'] = [first['evidence'], second['evidence']]
    if slot['occupancy'] == 'empty':
        return slot
    if first['asset_id'] is not None and first['asset_id'] == second['asset_id']:
        return dict(slot, identity_status='exact', asset_id=first['asset_id'])
    alternatives = {item['asset_id'] for item in (first, second) if item['asset_id'] is not None}
    alternatives.update(asset for item in (first, second) for asset in item.get('alternatives', ()))
    return dict(slot, identity_status='ambiguous', alternatives=sorted(alternatives))


def _compare(plan, first, second, node, captures):
    teams = [[_consensus(a, b) for a, b in zip(left, right)]
             for left, right in zip(first['teams'], second['teams'])]
    slots = [slot for team in teams for slot in team]
    identities = [slot['asset_id'] for slot in slots if slot['asset_id'] is not None]
    units = [unit_key(asset) for asset in identities]
    duplicate = len(set(units)) != len(units)
    empty = any(slot['occupancy'] == 'empty' for slot in slots)
    occupied = all(slot['occupancy'] == 'occupied' for slot in slots)
    complete = len(identities) == 8
    outside_team = any(slot['asset_id'] is not None and slot['asset_id'] not in expected
                       for team, expected in zip(teams, plan.teams) for slot in team)
    wrong_position = any(slot['asset_id'] is not None and slot['asset_id'] != expected
                         for slot, expected in zip(slots, plan.team1 + plan.team2))
    return dict(schema=1, status='compared', reason='consecutive_setup_captures',
                mode=plan.mode, level=plan.level_start, selected_node=node, captures=list(captures),
                layout_source=first['layout_source'], teams=teams, availability='unknown',
                eight_slots_occupied=False if empty else True if occupied else None,
                eight_identities_known=False if empty else True if complete else None,
                duplicate_unit=True if duplicate else False if complete else None,
                team_members_match=False if empty or duplicate or outside_team else True if complete else None,
                slot_order_match=False if empty or duplicate or wrong_position else True if complete else None,
                execution_supported=False)


def compare_roster_frames(plan, first, second, *, expected_node=None, confidence=.65):
    """Compare fresh captures with acquisition-time bindings from the same capture stream."""
    if not isinstance(plan, ChallengePlan) or not _consecutive(plan, first, second):
        return _unknown('invalid_capture_pair_or_plan')
    if plan.mode not in _SLOT_LAYOUTS:
        return _unknown('missing_slot_calibration')
    scenes = first.scene, second.scene
    captures = tuple(scene.captured_at for scene in scenes)
    pixels = _pixel_keys(scenes)
    if pixels is None:
        return _unknown('invalid_capture_pixels')
    if np.may_share_memory(scenes[0].image, scenes[1].image):
        return _unknown('reused_capture_buffer')
    pages = tuple(challenge_pages.observe(scene, confidence) for scene in scenes)
    if any(not _setup(page) or page.mode != plan.mode or page.level != plan.level_start for page in pages):
        return _unknown('wrong_mode_or_level')
    if plan.mode == _APOCALYPTIC:
        if (type(expected_node) is not int or expected_node not in (1, 2)
                or any(type(_node(page)) is not int or _node(page) != expected_node for page in pages)):
            return _unknown('wrong_or_unverified_node')
    elif expected_node is not None:
        return _unknown('unexpected_node')
    account = _shared_account(scenes, confidence)
    if account is None:
        return _unknown('unverified_or_changed_account')
    left, right = (_observe_slots(scene, page) for scene, page in zip(scenes, pages))
    if left['layout_source'] is None or left['layout_source'] != right['layout_source']:
        return _unknown('unverified_slot_sources')
    if any(a['box'] != b['box'] for row_a, row_b in zip(left['teams'], right['teams'])
           for a, b in zip(row_a, row_b)):
        return _unknown('changed_slot_geometry')
    current = tuple(challenge_pages.observe(scene, confidence) for scene in scenes)
    if (_pixel_keys(scenes) != pixels or tuple(map(_scope, current)) != tuple(map(_scope, pages))
            or tuple(scene.captured_at for scene in scenes) != captures
            or _shared_account(scenes, confidence) != account or not _consecutive(plan, first, second)):
        return _unknown('capture_pair_changed_during_scan')
    return _compare(plan, left, right, expected_node, captures)
