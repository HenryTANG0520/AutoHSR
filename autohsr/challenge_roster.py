"""Read-only candidate portraits in the pinned challenge character-list crop.

These are asset identities, not ownership, availability, selection or team
feedback. The caller establishes its page; this module never supplies an input
target. Original whole portraits are used without support-card masks/layout.
"""
from functools import lru_cache
import hashlib
import json
import math
import re
import time

import cv2
import numpy as np

from .challenge_plan import MANIFEST_SHA256, UPSTREAM_COMMIT
from .config import RESOURCE_ROOT


ASSET_ROOT = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/support'
THRESHOLD = .96
AMBIGUITY_MARGIN = .025
MAX_MATCHES = 128
MAX_PER_ASSET = 32
# Upstream crop tuples are x/y/width/height at its 1920x1080 reference.
_SOURCES = {
    'memory_of_chaos': ('tasks/challenge/basechallenge.py', 75, (30, 115, 530, 810)),
    'pure_fiction': ('tasks/challenge/basechallenge.py', 75, (30, 115, 530, 810)),
    'apocalyptic_shadow': ('tasks/challenge/apocalyptic.py', 205, (30, 110, 550, 850)),
}


def _result(mode, status='unknown', reason='no_supported_full_portrait'):
    source = _SOURCES.get(mode) if type(mode) is str else None
    result = dict(schema=1, status=status, reason=reason,
        mode=mode if source else None, roi=None, source=None,
        candidates=[], ambiguities=[], ownership='unknown', availability='unknown',
        selected='unknown', complete='unknown', execution_supported=False,
        full_real_page_calibrated=False)
    if source:
        path, line, (x, y, width, height) = source
        result.update(roi=[x / 1920, y / 1080, (x + width) / 1920, (y + height) / 1080],
            source=dict(commit=UPSTREAM_COMMIT, path=path, line=line,
                crop_xywh=[x, y, width, height], reference_size=[1920, 1080],
                manifest_sha256=MANIFEST_SHA256, page_scope='caller_verified'))
    return result


def _fresh(scene):
    stamp = getattr(scene, 'captured_at', None)
    return (type(stamp) in (int, float) and math.isfinite(stamp)
            and 0 <= time.monotonic() - stamp <= 8)


@lru_cache(maxsize=1)
def _references():
    with (ASSET_ROOT / 'sources.json').open('rb') as stream:
        raw = stream.read(256 * 1024 + 1)
    if (len(raw) > 256 * 1024 or
            hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != MANIFEST_SHA256):
        raise ValueError('unverified_manifest')
    data = json.loads(raw)
    rows = data['images']
    if data['commit'] != UPSTREAM_COMMIT or type(rows) is not list or len(rows) != 105:
        raise ValueError('unverified_manifest')
    bank = []
    identities = set()
    for row in rows:
        identity = row['character']
        if (type(identity) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]{0,63}', identity)
                or identity in identities or row['file'] != identity + '.png'
                or row['source_path'] != 'assets/images/share/character/' + identity + '.png'
                or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                or not re.fullmatch('[0-9a-f]{40}', row['git_blob'])):
            raise ValueError('unverified_template')
        with (ASSET_ROOT / row['file']).open('rb') as stream:
            raw = stream.read(128 * 1024 + 1)
        if (not raw or len(raw) > 128 * 1024 or hashlib.sha256(raw).hexdigest() != row['sha256']
                or hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest() != row['git_blob']):
            raise ValueError('unverified_template')
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if (image is None or [image.shape[1], image.shape[0]] != row['size']
                or min(image.shape[:2]) < 32 or max(image.shape[:2]) > 256
                or image.std() < 8):
            raise ValueError('unverified_template')
        image.setflags(write=False)
        bank.append((identity, image, dict(file=row['file'], source_path=row['source_path'],
            git_blob=row['git_blob'], sha256=row['sha256'])))
        identities.add(identity)
    return tuple(bank)


@lru_cache(maxsize=4)
def _scaled_references(width):
    scale = width / 1920
    bank = []
    for identity, original, source in _references():
        # Downscaled odd-sized originals cover a fractional pixel. Both
        # integer extents are legitimate quantization, not arbitrary UI zooms.
        widths = {max(1, math.floor(original.shape[1] * scale)), max(1, math.ceil(original.shape[1] * scale))}
        heights = {max(1, math.floor(original.shape[0] * scale)), max(1, math.ceil(original.shape[0] * scale))}
        for tw in sorted(widths):
            for th in sorted(heights):
                image = original if width == 1920 else cv2.resize(original, (tw, th), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                bank.append((identity, image, gray, source))
    return tuple(bank)


def _overlap(left, right):
    return (min(left[2], right[2]) > max(left[0], right[0])
            and min(left[3], right[3]) > max(left[1], right[1]))


def _matches(patch, gray, bank, offset, shape):
    matches = []
    height, width = shape
    for identity, image, template, source in bank:
        th, tw = template.shape
        if th > gray.shape[0] or tw > gray.shape[1]:
            continue
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        scores = np.nan_to_num(scores, nan=-1., posinf=-1., neginf=-1.)
        ys, xs = np.where((scores >= THRESHOLD - AMBIGUITY_MARGIN) &
                         (scores >= cv2.dilate(scores, np.ones((3, 3), np.uint8))))
        if len(xs) > MAX_PER_ASSET:
            raise ValueError('too_many_matches')
        kept = []
        for score, x, y in sorted(((float(scores[y, x]), int(x), int(y))
                                  for y, x in zip(ys, xs)), reverse=True):
            box = (x, y, x + tw, y + th)
            if any(_overlap(box, previous) for previous in kept):
                continue
            # A complete template must be inside the source crop. No partial
            # portrait or corner-badge retry can establish a candidate here.
            if x <= 0 or y <= 0 or x + tw >= patch.shape[1] or y + th >= patch.shape[0]:
                continue
            observed = patch[y:y + th, x:x + tw]
            if (np.mean(np.abs(observed.astype(np.int16) - image.astype(np.int16))) > 20
                    or observed.std() < image.std() * .8):
                continue
            kept.append(box)
            matches.append(dict(asset_id=identity, score=score,
                box=[(offset[0] + x) / width, (offset[1] + y) / height,
                     (offset[0] + x + tw) / width, (offset[1] + y + th) / height],
                template=dict(source)))
            if len(matches) > MAX_MATCHES:
                raise ValueError('too_many_matches')
    # Adjacent quantized extents of one original describe the same physical
    # portrait. Suppress only those same-asset peaks, never a competing ID.
    unique = []
    for item in sorted(matches, key=lambda item: item['score'], reverse=True):
        if not any(item['asset_id'] == prior['asset_id'] and _overlap(item['box'], prior['box']) for prior in unique):
            unique.append(item)
    return unique


def _group(matches):
    candidates, ambiguities = [], []
    remaining = list(matches)
    while remaining:
        component = [remaining.pop(0)]
        for current in component:
            linked = [item for item in remaining if _overlap(current['box'], item['box'])]
            for item in linked:
                remaining.remove(item)
                component.append(item)
        best = max(item['score'] for item in component)
        if best < THRESHOLD:
            continue
        # All component members passed the full-template pixel checks and the
        # lower ambiguity threshold. Never choose an ID by discarding a rival.
        plausible = component
        identities = sorted({item['asset_id'] for item in plausible})
        if len(identities) > 1:
            ambiguities.append(dict(asset_ids=identities, matches=plausible))
        else:
            # Same-identity peaks were suppressed per template above; an
            # overlap chain still cannot become two separately verified cards.
            if len(plausible) != 1:
                ambiguities.append(dict(asset_ids=identities, matches=plausible))
            else:
                candidates.append(plausible[0])
    return sorted(candidates, key=lambda item: (item['box'][1], item['box'][0], item['asset_id'])), ambiguities


def _scan_image(scene):
    image = getattr(scene, 'image', None)
    if (not _fresh(scene) or not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 540
            or image.shape[1] < 960 or image.shape[0] * image.shape[1] > 16_777_216
            or abs(image.shape[1] / image.shape[0] - 16 / 9) > .02):
        return None
    if image.shape[1] > 1920:
        image = cv2.resize(image, (1920, round(image.shape[0] * 1920 / image.shape[1])),
                           interpolation=cv2.INTER_AREA)
    return image


def _scan_box(image, roi, bank):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = [round(v * size) for v, size in zip(roi, (width, height, width, height))]
    patch = image[y1:y2, x1:x2]
    return _matches(patch, cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), bank, (x1, y1), (height, width))


def observe_candidates(scene, *, mode='memory_of_chaos'):
    """Return bounded JSON candidate evidence, with no click/selected authority."""
    result = _result(mode)
    if result['source'] is None:
        result['reason'] = 'unsupported_mode'
        return result
    image = _scan_image(scene)
    if image is None:
        result['reason'] = 'invalid_or_stale_scene'
        return result
    try:
        bank = _scaled_references(image.shape[1])
        candidates, ambiguities = _group(_scan_box(image, result['roi'], bank))
    except (OSError, ValueError, KeyError, TypeError, cv2.error):
        result['reason'] = 'unverified_reference_or_scan'
        return result
    if not _fresh(scene):
        result['reason'] = 'scene_expired_during_scan'
        return result
    result.update(candidates=candidates, ambiguities=ambiguities,
                  templates_checked=len({item[0] for item in bank}))
    if ambiguities:
        result.update(status='ambiguous', reason='overlapping_or_similar_asset_identities')
    elif candidates:
        result.update(status='observed', reason='whole_template_candidates_only')
    return result
