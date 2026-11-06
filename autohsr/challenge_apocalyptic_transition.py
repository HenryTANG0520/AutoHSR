"""Read the observed regular 04 picker sequence without identifying a character."""
import cv2
import numpy as np

from .challenge_apocalyptic_prepare import same_page
from .challenge_pages import _overlaps
from .challenge_slots import _read_regular_slot, _regular_rim, _sample_regular_slot


_STAGES = ('before_setup', 'list_before_badge', 'badge_with_empty_slot',
           'list_after_insertion', 'returned_setup_one', 'returned_setup_two')
_COLUMNS = (40, 96, 153, 209)
_GRID = (16, 74, 235, 393)
_Y, _X = np.mgrid[-10:11, -10:11].astype(np.float32)
_PORTRAIT_CORE = np.hypot(_X, _Y) <= 10


def _same_badge(left, right):
    return left['node'] == right['node'] and _overlaps(left['box'], right['box'])


def _retained_badges(before, after):
    return all(sum(_same_badge(old, new) for new in after) == 1 for old in before)


def _added_badge(pages, node):
    before, early, filled = (page.basis['badges'] for page in pages)
    if (len(early) != len(before) + 1 or len(filled) != len(early)
            or not _retained_badges(before, early) or not _retained_badges(early, filled)
            or not _retained_badges(filled, early)):
        return None
    added = [badge for badge in early if not any(_same_badge(badge, old) for old in before)]
    return added[0] if len(added) == 1 and added[0]['node'] == node else None


def _similar(left, right, minimum):
    if min(left.std(), right.std()) < 8:
        return False
    return float(np.corrcoef(left.ravel(), right.ravel())[0, 1]) >= minimum


def _badge_bands(image, x):
    _, top, _, bottom = _GRID
    sides = [(image[top:bottom, a:z].min(axis=2) >= 185).mean(axis=1)
             for a, z in ((x - 20, x - 13), (x + 15, x + 21))]
    return np.minimum(*sides)


def _other_badge_changed(before, after, column, card_top, card_bottom):
    _, grid_top, _, _ = _GRID
    for x in _COLUMNS:
        prior, current = (np.convolve(_badge_bands(image, x) >= .85, [1, 1, 1], mode='same') >= 3
                          for image in (before, after))
        if x == column:
            prior[card_top - grid_top:card_bottom - grid_top] = False
            current[card_top - grid_top:card_bottom - grid_top] = False
        # Allow a one-row difference in the edge of an unchanged bar.
        prior_pad = np.convolve(prior, [1, 1, 1], mode='same') > 0
        current_pad = np.convolve(current, [1, 1, 1], mode='same') > 0
        if np.any(current & ~prior_pad) or np.any(prior & ~current_pad):
            return True
    return False


def _badge_card(badge, images):
    left, top, right, bottom = badge['box']
    badge_x, badge_y = (left + right) * 401, (top + bottom) * 227
    x = min(_COLUMNS, key=lambda col: abs(col - badge_x))
    y = round(badge_y)
    grid_l, grid_t, grid_r, grid_b = _GRID
    card = (x - 24, y - 39, x + 24, y + 18)
    l, t, r, b = card
    if (abs(x - badge_x) > 4 or not .020 <= right - left <= .040 or not .015 <= bottom - top <= .030
            or not (grid_l <= l < r <= grid_r and grid_t <= t < b <= grid_b)):
        return None

    def band(image):
        return float(_badge_bands(image, x)[y - 3 - grid_t:y + 4 - grid_t].mean())

    before, early, filled = images
    if band(before) > .35 or min(band(early), band(filled)) < .85:
        return None
    # Compare the visible face of this same rectangular card across the
    # selected overlay. No rectangular-to-circular identity is inferred.
    faces = [cv2.cvtColor(im[y - 27:y - 10, x - 10:x + 10], cv2.COLOR_BGR2GRAY) for im in images]
    if not all(_similar(a, z, .93) for a, z in zip(faces, faces[1:])):
        return None
    for image in (early, filled):
        if _other_badge_changed(before, image, x, t, b):
            return None
        delta = cv2.absdiff(before[grid_t:grid_b, grid_l:grid_r], image[grid_t:grid_b, grid_l:grid_r])
        delta[t - grid_t:b - grid_t, l - grid_l:r - grid_l] = 0
        if (delta.max(axis=2) > 30).mean() > .025:
            return None
    return [l / 802, t / 454, r / 802, b / 454]


def _same_portrait(images, center, *, shaded=False):
    x, y = center
    patches = [_sample_regular_slot(image, x, y, _X, _Y) for image in images]
    textures = [cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)[_PORTRAIT_CORE] for patch in patches]
    if not all(_similar(first, second, .94) for first, second in zip(textures, textures[1:])):
        return False
    return shaded or all(cv2.absdiff(first[_PORTRAIT_CORE], second[_PORTRAIT_CORE]).mean() <= 12
                         for first, second in zip(patches, patches[1:]))


def _slot_center(slot):
    left, top, right, bottom = slot['box']
    return (left + right) * 401, (top + bottom) * 227


def _occupancy(image, center, position):
    x, y = center
    return _read_regular_slot(image, x, y, position, _regular_rim(image, x, y))['occupancy']


def _inactive_row_unchanged(row, images):
    for slot in row:
        state = slot['occupancy']
        if state == 'unknown':
            return False
        center = _slot_center(slot)
        # The inactive row is dimmed while the picker is open. Require the
        # same portrait texture despite this change in absolute brightness.
        if state == 'occupied':
            if not _same_portrait(images, center, shaded=True):
                return False
        elif any(_occupancy(image, center, slot['position']) != 'empty' for image in images[:-2]):
            return False
    return True


def _inserted_slot(node, images, slots):
    if slots['status'] != 'compared' or slots.get('node_order') != [1, 2]:
        return None
    returned = slots['teams'][node - 1]
    if not _inactive_row_unchanged(slots['teams'][2 - node], images):
        return None
    changed = []
    setup, before, early, filled, first_return, second_return = images
    for slot in returned:
        if slot['occupancy'] == 'unknown':
            return None
        center = _slot_center(slot)
        states = [_occupancy(im, center, slot['position']) for im in (before, early, filled)]
        if states == ['empty', 'empty', 'occupied'] and slot['occupancy'] == 'occupied':
            changed.append(slot['position'])
            if not _same_portrait((filled, first_return, second_return), center):
                return None
        elif states != [slot['occupancy']] * 3 or _occupancy(setup, center, slot['position']) != slot['occupancy']:
            return None
        elif slot['occupancy'] == 'occupied' and not _same_portrait(images, center):
            return None
    return changed[0] if len(changed) == 1 else None


def compare_candidate_transition(frames, images, slots):
    """Use six successive captures already bound to the workflow's account and window."""
    if len(frames) != len(_STAGES) or len(images) != len(_STAGES):
        return None
    pages = tuple(frame.observation for frame in frames)
    first, *middle, returned_one, returned_two = pages
    if (first.kind != 'node_setup' or first.level != 4
            or not same_page(first, returned_one) or not same_page(returned_one, returned_two)
            or any(page.kind != 'candidate_picker' or page.level is not None for page in middle)
            or not all(same_page(a, b) for a, b in zip(middle, middle[1:]))):
        return None
    node = middle[0].basis['active_node']
    if any(page.basis['active_node'] != node for page in middle):
        return None
    badge = _added_badge(middle, node)
    if badge is None:
        return None
    client = tuple(cv2.resize(image, (802, 454), interpolation=cv2.INTER_AREA) for image in images[1:4])
    card = _badge_card(badge, client)
    position = _inserted_slot(node, images, slots) if card else None
    if position is None:
        return None
    references = {stage: dict(capture_sequence=frame.source['capture_sequence'], sha256=frame.source['sha256'])
                  for stage, frame in zip(_STAGES, frames)}
    return dict(schema=1, status='observed', level=4, picker_level=None, node=node, position=position,
                badge=badge, card_box=card, badge_before_occupancy=True, slot_change='empty_to_occupied',
                returned_portrait_verified=True, identity_status='unknown', execution_supported=False,
                frames=references)
