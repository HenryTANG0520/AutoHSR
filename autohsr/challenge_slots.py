"""Read-only challenge slot evidence and explicit two-team comparison."""
from dataclasses import dataclass, field
import hashlib
import math
from types import MappingProxyType

import cv2
import numpy as np

from . import challenge_pages, challenge_roster
from .challenge_account import verified_account
from .challenge_identities import unit_key
from .challenge_plan import ChallengePlan, MODE_LIMITS
from .models import AutomationError, ROI, Scene


_APOCALYPTIC = 'apocalyptic_shadow'
_EMPTY = 'empty_slot_marker'

# Regular Domination of Oblivion 04, measured in the 802x454 client crop.
# These are eight circular slots under the two node headers, separate from
# the editor's rectangular character cards and the far-right node controls.
_REGULAR_04_LAYOUT = 'domination_oblivion_regular_04_circles'
_REFERENCE_SIZE = (802, 454)
_SLOT_ROWS = tuple(tuple((x, y) for x in (430., 467., 503., 539.)) for y in (168., 287.5))
_SLOT_Y, _SLOT_X = np.mgrid[-17:18, -17:18].astype(np.float32)
_SLOT_DISK = np.hypot(_SLOT_X, _SLOT_Y) <= 12.8
_SLOT_SECTORS = tuple(_SLOT_DISK & side for side in
                      (_SLOT_X < -4, _SLOT_X > 4, _SLOT_Y < -5, _SLOT_Y > 5))
_GLYPH_CENTER = np.abs(_SLOT_X) <= 1
_GLYPH_HEAD = _GLYPH_CENTER & (_SLOT_Y >= -6) & (_SLOT_Y <= -4)
_GLYPH_BODY = _GLYPH_CENTER & (_SLOT_Y >= -1) & (_SLOT_Y <= 3)
_GLYPH_GAP = _GLYPH_CENTER & (_SLOT_Y == -2)
_GLYPH_BACKGROUND = _SLOT_DISK & (np.abs(_SLOT_X) >= 5)
_RIM_ANGLES = np.arange(32) * (2 * np.pi / 32)
_RIM_RADII = np.arange(13.5, 18.01, .75)[:, None]
_RIM_X = (_RIM_RADII * np.cos(_RIM_ANGLES)).astype(np.float32)
_RIM_Y = (_RIM_RADII * np.sin(_RIM_ANGLES)).astype(np.float32)


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
        keys = {verified_account(scene, confidence) for scene in scenes}
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
    return dict(slot, identity_status='ambiguous', alternatives=sorted(alternatives)) if alternatives else slot


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


def _sample_regular_slot(image, x, y, sample_x, sample_y):
    height, width = image.shape[:2]
    return cv2.remap(image, (sample_x + x) * (width / _REFERENCE_SIZE[0]),
                     (sample_y + y) * (height / _REFERENCE_SIZE[1]), cv2.INTER_LINEAR)


def _regular_rim(image, x, y):
    radial = _sample_regular_slot(image, x, y, _RIM_X, _RIM_Y).astype(np.int16)
    edges = np.abs(np.diff(radial, axis=0)).max(axis=(0, 2))
    return tuple(int(count) for count in (edges >= 19).reshape(4, 8).sum(axis=1))


def _has_regular_rim(arcs):
    return min(arcs) >= 3 and sum(arcs) >= 23


def _read_regular_slot(image, x, y, position, arcs, *, empty_sector_limit=18):
    width, height = _REFERENCE_SIZE
    slot = _unknown_slot(position, ((x - 17.5) / width, (y - 17.5) / height,
                                    (x + 17.5) / width, (y + 17.5) / height))
    if not _has_regular_rim(arcs):
        return slot
    gray = cv2.cvtColor(_sample_regular_slot(image, x, y, _SLOT_X, _SLOT_Y), cv2.COLOR_BGR2GRAY)
    ranges = [float(np.quantile(gray[sector], .9) - np.quantile(gray[sector], .1)) for sector in _SLOT_SECTORS]
    evidence = dict(rim_arcs=list(arcs), sector_luma_ranges=ranges, box=slot['box'])
    background = float(np.median(gray[_GLYPH_BACKGROUND]))
    head, body, gap = (float(gray[part].mean()) for part in (_GLYPH_HEAD, _GLYPH_BODY, _GLYPH_GAP))
    if (background <= 65 and abs(head - body) <= 28 and min(head, body) - background >= 30
            and min(head, body) - gap >= 12):
        if max(ranges) > empty_sector_limit:
            return slot
        return dict(slot, occupancy='empty', evidence=dict(evidence, source='empty_slot_glyph',
                    glyph_luma=[head, body, gap, background]))
    # The pointer can span all sectors of a dark empty slot but covers less
    # of the interior than the visible portraits in the reference frames.
    lit_fraction = float((gray[_SLOT_DISK] >= 48).mean())
    if min(ranges) >= 27 and lit_fraction >= .56:
        return dict(slot, occupancy='occupied', evidence=dict(evidence, source='circular_portrait',
                    lit_fraction=lit_fraction))
    return slot


def _compare_apocalyptic_setup(plan, frames, images):
    """Compare slot pixels from the preparation workflow's held source pair."""
    if plan.mode != _APOCALYPTIC or plan.level_start != 4 or len(frames) != 2 or len(images) != 2:
        return _unknown('unverified_regular_apocalyptic_setup')
    for frame in frames:
        page = frame.observation
        nodes = [node['node'] for node in page.basis.get('nodes', ())]
        if (page.kind != 'node_setup' or page.mode != plan.mode or page.level != plan.level_start
                or page.basis.get('layout') != 'domination_oblivion_normal' or nodes != [1, 2]):
            return _unknown('unverified_regular_apocalyptic_setup')
    # The recording and alternate client crops differ slightly horizontally.
    # One shift must support both rows in both frames, with disjoint slots.
    alignments = []
    for shift in (0, -2, 2, -4, 4):
        rims = [tuple(tuple(_regular_rim(image, x + shift, y) for x, y in row) for row in _SLOT_ROWS)
                for image in images]
        agreed = sum(_has_regular_rim(a) and _has_regular_rim(b)
                     for row_a, row_b in zip(*rims) for a, b in zip(row_a, row_b))
        strength = sum(sum(arcs) for frame in rims for row in frame for arcs in row)
        alignments.append(((agreed, strength), shift, rims))
    _, shift, rims = max(alignments, key=lambda item: item[0])
    if any(sum(map(_has_regular_rim, row)) < 3 for frame in rims for row in frame):
        return _unknown('unverified_regular_apocalyptic_slot_rows')
    readings = []
    for image, frame_rims in zip(images, rims):
        teams = []
        for row, row_rims in zip(_SLOT_ROWS, frame_rims):
            teams.append([_read_regular_slot(image, x + shift, y, position, arcs)
                          for position, ((x, y), arcs) in enumerate(zip(row, row_rims), 1)])
        readings.append(dict(layout_source=_REGULAR_04_LAYOUT, teams=teams))
    captures = [frame.source['captured_at'] for frame in frames]
    result = _compare(plan, readings[0], readings[1], None, captures)
    if all(slot['occupancy'] == 'unknown' for team in result['teams'] for slot in team):
        return _unknown('no_agreed_regular_apocalyptic_slot_state')
    return dict(result, node_order=[1, 2])


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
