"""Read the already open 4.6 regular Memory of Chaos floor-ten setup."""
import re

import cv2
import numpy as np

from . import challenge_pages as pages, challenge_roster as roster
from .challenge_plan import ChallengePlanError, _catalogue
from .challenge_slots import _REFERENCE_SIZE, _read_regular_slot, _regular_rim
from .models import normalize
from .team_preset_readback import _PRESET_NAMES


COLLECTION_FLOOR = .65
_PERIOD = '物竞天择'
_FLOOR = _PERIOD + '其十'
_NAME_REGION = (.015, .163, .174, .916)
_LEVEL = re.compile(r'等级([1-9][0-9]?)')
_COLUMNS = (.0537, .1212, .1888, .2563)
_NATIVE_4K = (2160, 3840)
_NATIVE_PHASES = ((0, 0), (1, 0), (0, 1), (1, 1))
_SETUP_COLUMNS = (.7166, .7646, .8127, .8608)
_SETUP_ROWS = (.699, .803)
_ANCHORS = {
    'mode_title': ('忘却之庭', (.04, .025, .115, .070)),
    'setup_title': ('编队', (.04, .052, .106, .102)),
    'stage': (_FLOOR, (.32, .102, .56, .159)),
    'goal': ('挑战目标', (.32, .269, .40, .327)),
    'teams': ('角色编队', (.32, .590, .40, .652)),
    'first_team_attributes': ('建议属性', (.557, .652, .637, .706)),
    'second_team_attributes': ('建议属性', (.557, .756, .637, .812)),
    'role_list': ('角色列表', (.055, .102, .124, .148)),
    'preset_list': ('预设编队', (.187, .102, .259, .148)),
}


def _field(tokens, box, matches, minimum):
    found = [token for token in tokens if pages._overlaps(token.box, box) and matches(normalize(token.text))]
    if len(found) == 1 and found[0].score >= minimum and pages._inside(found[0].box, box):
        return found[0]
    return None


def _proof(token, value):
    return dict(value=value, box=list(token.box), score=token.score)


def _tab_style(image, token):
    x1, y1, x2, y2 = token.box
    height, width = image.shape[:2]
    upper, lower = round((y1 + .003) * height), round((y2 - .004) * height)
    samples = []
    for left, right in ((x1 - .021, x1 - .013), (x2 + .013, x2 + .021)):
        patch = image[upper:lower, round(left * width):round(right * width)]
        if not patch.size:
            return None
        samples.append((float((patch.min(axis=2) >= 185).mean()),
                        float((patch.max(axis=2) <= 105).mean())))
    if all(bright >= .90 for bright, _ in samples):
        return 'selected'
    if all(dark >= .90 for _, dark in samples):
        return 'unselected'
    return None


def _setup_slots(image, has_empty_caption):
    # The 4.6 highlighted row contains brighter diamond outlines than the
    # regular Apocalypse reference. Require the same central glyph and rim.
    width, height = _REFERENCE_SIZE
    teams = []
    for y in _SETUP_ROWS:
        team = []
        for position, x in enumerate(_SETUP_COLUMNS, 1):
            a, b = x * width, y * height
            slot = _read_regular_slot(image, a, b, position, _regular_rim(image, a, b), empty_sector_limit=24)
            empty = has_empty_caption and slot['occupancy'] == 'empty'
            team.append(dict(position=position, box=slot['box'], occupancy='empty' if empty else 'unknown',
                             glyph=slot.get('evidence') if empty else None))
        teams.append(team)
    return teams


def _read_level(tokens, x, y, minimum):
    caption = _field(tokens, (x - .030, y + .108, x + .030, min(y + .154, .916)),
                     lambda value: value.startswith('等级'), minimum)
    match = _LEVEL.fullmatch(normalize(caption.text)) if caption else None
    if match and int(match[1]) <= 80 and caption.box[3] - caption.box[1] >= .016:
        return _proof(caption, int(match[1]))
    return None


def _portrait_matches(native, image, roi, bank):
    if native.shape[:2] != _NATIVE_4K:
        return roster._scan_box(image, roi, bank)
    height, width = image.shape[:2]
    x1, y1, x2, y2 = (round(v * size) for v, size in zip(roi, (width, height, width, height)))
    matches = []
    # The 1080p template grid may start on either native pixel in each
    # dimension. Use every even-sized sampling crop inside this same slot.
    for dx, dy in _NATIVE_PHASES:
        raw = native[2 * y1 + dy:2 * y2 - dy, 2 * x1 + dx:2 * x2 - dx]
        patch = cv2.resize(raw, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        offset = (x1 + dx / 2, y1 + dy / 2)
        hits = roster._matches(patch, gray, bank, offset, (height, width))
        matches.extend(dict(hit, native_sample_phase=[dx, dy]) for hit in hits)
    return roster._distinct_matches(matches)


def _read_preset_slots(scene, tokens, y, minimum):
    levels = [_read_level(tokens, x, y, minimum) for x in _COLUMNS]
    if not any(levels):
        return None
    slots = [dict(position=position, level=level, portrait=None)
             for position, level in enumerate(levels, 1)]
    try:
        image = roster._scan_image(scene)
        if image is None:
            return slots
        bank = roster._scaled_references(image.shape[1])
        for x, slot in zip(_COLUMNS, slots):
            if slot['level'] is None:
                continue
            roi = (x - .033, y + .017, x + .033, min(y + .154, .916))
            matches, ambiguities = roster._group(_portrait_matches(scene.image, image, roi, bank))
            if len(matches) == 1 and not ambiguities:
                left, _, right, bottom = matches[0]['box']
                if abs((left + right) / 2 - x) <= .009 and abs(bottom - slot['level']['box'][1]) <= .022:
                    slot['portrait'] = matches[0]
    except (OSError, ValueError, KeyError, TypeError, cv2.error):
        for slot in slots:
            slot['portrait'] = None
    return slots


def _read_rows(scene, tokens, minimum):
    rows = []
    for name in _PRESET_NAMES:
        label = _field(tokens, _NAME_REGION, name.__eq__, minimum)
        if (label is None or label.text.strip() != name
                or any(other is not label and pages._overlaps(other.box, label.box) for other in tokens)):
            continue
        slots = _read_preset_slots(scene, tokens, label.center[1], minimum)
        if slots is not None:
            rows.append(dict(name=_proof(label, name), slots=slots))
    return sorted(rows, key=lambda row: row['name']['box'][1])


def observe(scene, confidence=COLLECTION_FLOOR):
    """A single local view. Neither tab, row nor slot evidence can send input."""
    clean = pages._clean(scene, min(confidence, COLLECTION_FLOOR), blockers=pages._BLOCKED + pages._SIDE_BLOCKED)
    if clean is None:
        return None
    minimum = max(.85, confidence)
    fields = {}
    for key, (text, region) in _ANCHORS.items():
        matches = (lambda value: value.startswith(_PERIOD)) if key == 'stage' else text.__eq__
        token = _field(clean.tokens, region, matches, minimum)
        if token is None or normalize(token.text) != text:
            return None
        fields[key] = token
    roles, presets = (_tab_style(clean.image, fields[key]) for key in ('role_list', 'preset_list'))
    if (roles, presets) not in (('selected', 'unselected'), ('unselected', 'selected')):
        return None
    tab = 'preset_list' if presets == 'selected' else 'role_list'
    caption = _field(clean.tokens, (.345, .397, .485, .465), '没有角色无法战斗'.__eq__, minimum)
    anchors = {key: _proof(token, _ANCHORS[key][0]) for key, token in fields.items()}
    anchors['empty_team_caption'] = _proof(caption, '没有角色无法战斗') if caption else None
    teams = _setup_slots(clean.image, caption is not None)
    rows = _read_rows(clean, clean.tokens, minimum) if tab == 'preset_list' else []
    return dict(mode=pages.MODE, level=10, tab=tab, anchors=anchors, setup_slots=teams, rows=rows)


def _same_field(first, second):
    return (first is not None and second is not None and first['value'] == second['value']
            and all(abs(a - b) <= .008 for a, b in zip(first['box'], second['box'])))


def compare(first, second):
    """Keep the page and each same-position portrait claim separate."""
    if (first['tab'] != second['tab'] or first['mode'] != second['mode'] or first['level'] != second['level']
            or not all(_same_field(first['anchors'][key], second['anchors'][key]) for key in _ANCHORS)
            or len(first['rows']) != len(second['rows'])
            or not all(_same_field(a['name'], b['name']) for a, b in zip(first['rows'], second['rows']))):
        return None
    try:
        names, _ = _catalogue()
    except ChallengePlanError:
        names = {}
    rows = []
    for left, right in zip(first['rows'], second['rows']):
        slots = []
        for a, b in zip(left['slots'], right['slots']):
            level = b['level']['value'] if _same_field(a['level'], b['level']) else None
            one, two = a['portrait'], b['portrait']
            identity = (two['asset_id'] if level is not None and one and two
                        and one['asset_id'] == two['asset_id'] and pages._overlaps(one['box'], two['box']) else None)
            slots.append(dict(position=b['position'], visible_level=level,
                              portrait_asset_id=identity, portrait_name=names.get(identity)))
        rows.append(dict(name=right['name']['value'], slots=slots))
    teams = [[dict(position=b['position'], occupancy='empty' if a['occupancy'] == b['occupancy'] == 'empty' else 'unknown')
              for a, b in zip(left, right)] for left, right in zip(first['setup_slots'], second['setup_slots'])]
    return dict(mode=second['mode'], level=second['level'], tab=second['tab'], visible_presets=rows,
                setup_slots=teams, eight_slots_empty=True if all(
                    slot['occupancy'] == 'empty' for team in teams for slot in team) else None)
