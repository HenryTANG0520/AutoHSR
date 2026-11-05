"""Capture one foreground game frame for local, read-only UI calibration.

Never focuses, starts, navigates, or sends input to the game. Originals and OCR
stay in a new local directory; stdout names an image only after redaction checks.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import unicodedata
import uuid


ROOT = Path(__file__).resolve().parents[1]
LABELS = ('current', 'preset_1', 'preset_2', 'preset_3', 'preset_4',
          'currency_lobby', 'currency_entry', 'chaos_lobby', 'chaos_setup',
          'fiction_lobby', 'fiction_setup', 'apocalyptic_lobby', 'apocalyptic_setup')
SAFE_VIEW = (0., .12, 1., .90)
# The phone profile occupies this area. Mask it on every page rather than
# assuming that the caller's label proves the current page or account layout.
PROFILE_MASK = (.50, 0., 1., .36)
REASONS = frozenset(('evidence_write_unverified', 'invalid_crop', 'crop_outside_privacy_bounds',
    'ocr_source_unverified', 'image_encoding_failed', 'invalid_label', 'capture_geometry_unverified',
    'ocr_source_empty', 'crop_empty', 'redaction_check_empty', 'redaction_check_sensitive',
    'sensitive_page', 'capture_or_redaction_unverified'))


class CaptureRejected(ValueError):
    """Only fixed reason codes from this tool may reach its public result."""
    def __init__(self, reason):
        super().__init__(reason if reason in REASONS else 'capture_or_redaction_unverified')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise CaptureRejected('evidence_write_unverified')


def _crop(value):
    if isinstance(value, str):
        try:
            value = tuple(float(part) for part in value.split(','))
        except ValueError:
            raise CaptureRejected('invalid_crop') from None
    if (not isinstance(value, (tuple, list)) or len(value) != 4
            or any(type(part) not in (int, float) or not math.isfinite(part) for part in value)
            or not (0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1)):
        raise CaptureRejected('invalid_crop')
    result = (max(value[0], SAFE_VIEW[0]), max(value[1], SAFE_VIEW[1]),
              min(value[2], SAFE_VIEW[2]), min(value[3], SAFE_VIEW[3]))
    if result[0] >= result[2] or result[1] >= result[3]:
        raise CaptureRejected('crop_outside_privacy_bounds')
    return result


def _tokens(scene):
    tokens = scene.tokens
    if not isinstance(tokens, (tuple, list)) or len(tokens) > 2000:
        raise CaptureRejected('ocr_source_unverified')
    records = []
    for token in tokens:
        if (not isinstance(token.text, str) or not token.text.strip() or len(token.text) > 4096
                or type(token.score) not in (int, float) or not math.isfinite(token.score)
                or not 0 <= token.score <= 1
                or not isinstance(token.box, (tuple, list)) or len(token.box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                       for v in token.box)
                or not (token.box[0] < token.box[2] and token.box[1] < token.box[3])):
            raise CaptureRejected('ocr_source_unverified')
        records.append(dict(text=token.text, score=token.score, box=list(token.box)))
    return records


def _sensitive(text):
    compact = re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', text).casefold())
    return re.search(r'u[i1l]d|[0-9]{6,}', compact) is not None


def _sensitive_page(records):
    labels = ('账号登录', '扫码登录', '验证码', '用户协议', '输入密码', '输入账号')
    return any(re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', item['text'])) in labels
               for item in records)


def _sensitive_bands(records):
    """Mask whole suspect rows, including separated UID labels and fragments."""
    rows = []
    for record in sorted(records, key=lambda item: (sum(item['box'][1::2]), item['box'][0])):
        box = record['box']
        center = (box[1]+box[3])/2
        row = next((row for row in rows if abs(center-(row['top']+row['bottom'])/2)
                    <= max(.008, (box[3]-box[1])/2, (row['bottom']-row['top'])/2)), None)
        if row is None:
            rows.append(dict(top=box[1], bottom=box[3], records=[record]))
        else:
            row['top'] = min(row['top'], box[1])
            row['bottom'] = max(row['bottom'], box[3])
            row['records'].append(record)
    bands = []
    for row in rows:
        joined = ''.join(item['text'] for item in sorted(row['records'], key=lambda item: item['box'][0]))
        if _sensitive(joined) or any(_sensitive(item['text']) for item in row['records']):
            bands.append((0., max(0., row['top']-.015), 1., min(1., row['bottom']+.015)))
    return bands


def _mask_rect(box, width, height):
    return (max(0, math.floor(box[0]*width)), max(0, math.floor(box[1]*height)),
            min(width, math.ceil(box[2]*width)), min(height, math.ceil(box[3]*height)))


def _version(window, reader):
    try:
        value = reader(window.current_executable())
        full = value['full_version']
        match = re.fullmatch(r'([1-9][0-9]?)\.([0-9]{1,2})\.[0-9]{1,4}', full)
        if (not match or value['version'] != match[1]+'.'+str(int(match[2]))
                or value['kind'] != 'launcher_game_version'):
            raise ValueError
        return dict(status='verified', version=value['version'], full_version=full, kind=value['kind'])
    except Exception:
        return dict(status='unknown', reason='client_version_unverified')


def _png(image):
    import cv2
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise CaptureRejected('image_encoding_failed')
    return encoded.tobytes()


def _default_vision():
    from autohsr.vision import Vision
    # Keep even low-confidence OCR candidates when deciding what to hide.
    return Vision(0.)


def _default_client(executable):
    from autohsr.currency_wars_identity import installed_client
    return installed_client(executable)


def capture_interface(window, *, output_root, label='current', crop=(0., 0., 1., 1.),
                      vision_factory=None, client_reader=None):
    """Read a supplied window once; injected fakes can exercise this without Tk.

    The label is bookkeeping, never page recognition or authority to navigate.
    Only a successfully checked public image is included in the returned value.
    """
    import numpy as np
    if label not in LABELS:
        raise CaptureRejected('invalid_label')
    requested_crop = _crop(crop)
    capture_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ_') + uuid.uuid4().hex[:12]
    directory = Path(output_root).resolve() / capture_id
    directory.mkdir(parents=True, exist_ok=False)
    metadata = dict(schema=1, operation='interface_capture', origin='foreground_game_window_capture',
        capture_id=capture_id, label=label,
        captured_at=datetime.now(timezone.utc).isoformat(), input_sent=False, focus_requested=False,
        navigation_performed=False, status='blocked', game_client=dict(status='unknown'), sources={})
    result = dict(schema=1, operation='interface_capture', capture_id=capture_id, label=label,
                  input_sent=False, focus_requested=False, navigation_performed=False)
    public_image = None
    try:
        # GameWindow.capture guards the *already foreground* window before and
        # after capture. Do not call focus, launch, release, or any input method.
        image, geometry = window.capture()
        if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
                or image.shape[2] != 3 or min(image.shape[:2]) < 1
                or image.shape[0]*image.shape[1] > 16_777_216
                or geometry.width != image.shape[1] or geometry.height != image.shape[0]):
            raise CaptureRejected('capture_geometry_unverified')
        height, width = image.shape[:2]
        raw = _png(image)
        _write(directory/'private/raw.png', raw)
        metadata['sources']['raw'] = dict(file='private/raw.png', sha256=_sha(raw), width=width, height=height)
        metadata['game_client'] = _version(window, client_reader or _default_client)
        vision = (vision_factory or _default_vision)()
        records = _tokens(vision.read(image.copy(), geometry))
        ocr = _json(dict(schema=1, source_sha256=_sha(raw), tokens=records))
        _write(directory/'private/ocr.json', ocr)
        metadata['sources']['ocr'] = dict(file='private/ocr.json', sha256=_sha(ocr))
        if not records:
            raise CaptureRejected('ocr_source_empty')
        if _sensitive_page(records):
            raise CaptureRejected('sensitive_page')
        masks = [_mask_rect(PROFILE_MASK, width, height)]
        masks.extend(_mask_rect(box, width, height) for box in _sensitive_bands(records))
        safe = image.copy()
        for left, top, right, bottom in masks:
            safe[top:bottom, left:right] = 0
        box = (math.ceil(requested_crop[0]*width), math.ceil(requested_crop[1]*height),
               math.floor(requested_crop[2]*width), math.floor(requested_crop[3]*height))
        if box[0] >= box[2] or box[1] >= box[3]:
            raise CaptureRejected('crop_empty')
        safe = safe[box[1]:box[3], box[0]:box[2]].copy()
        encoded = _png(safe)
        metadata['redaction'] = dict(policy='interface-uid-crop-v1', crop_px=box,
            source_size=[width, height], privacy_view=SAFE_VIEW, masks_px=masks,
            verification='pending', limitations='OCR checks supplement fixed privacy exclusions; unknown layouts are not certified.')
        # Re-read the *cropped, masked* pixels. Neither OCR pass is printed.
        checked = _tokens(vision.read(safe.copy()))
        checked_ocr = _json(dict(schema=1, source_sha256=_sha(encoded), tokens=checked))
        _write(directory/'private/public-ocr-check.json', checked_ocr)
        metadata['sources']['public_ocr_check'] = dict(file='private/public-ocr-check.json', sha256=_sha(checked_ocr))
        if not checked:
            raise CaptureRejected('redaction_check_empty')
        if _sensitive_page(checked):
            raise CaptureRejected('sensitive_page')
        if _sensitive_bands(checked):
            raise CaptureRejected('redaction_check_sensitive')
        _write(directory/'public'/f'{label}.png', encoded)
        public_image = dict(file=f'public/{label}.png', sha256=_sha(encoded), width=safe.shape[1], height=safe.shape[0])
        metadata['sources']['public_image'] = public_image
        metadata['redaction']['verification'] = 'fixed_exclusions_and_two_ocr_passes'
        metadata['status'] = 'ready'
    except CaptureRejected as error:
        metadata['reason'] = str(error)
    except Exception:
        # Third-party, OCR, Windows, and filesystem messages may contain paths,
        # full OCR, or account details. Never interpolate their text here.
        metadata['reason'] = 'capture_or_redaction_unverified'
    manifest = _json(metadata)
    _write(directory/'manifest.json', manifest)
    _write(directory/'manifest.sha256', (_sha(manifest)+'\n').encode('ascii'))
    result.update(status=metadata['status'], game_client=metadata['game_client'],
                  metadata=dict(file=f'{capture_id}/manifest.json', sha256=_sha(manifest)))
    if 'reason' in metadata:
        result['reason'] = metadata['reason']
    if metadata['status'] == 'ready' and public_image is not None:
        result['image'] = dict(public_image, file=f'{capture_id}/{public_image["file"]}')
    return result


def main(argv=None, *, window_factory=None, vision_factory=None, client_reader=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', choices=LABELS, default='current')
    parser.add_argument('--crop', type=_crop, default=(0., 0., 1., 1.),
                        help='normalized left,top,right,bottom; fixed privacy exclusions always apply')
    parser.add_argument('--output-root', type=Path, default=ROOT/'runs/interface-calibration')
    args = parser.parse_args(argv)
    try:
        if window_factory is None:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from autohsr.windows import find_game
            window_factory = find_game
        value = capture_interface(window_factory(), output_root=args.output_root, label=args.label,
            crop=args.crop, vision_factory=vision_factory, client_reader=client_reader)
    except Exception:
        value = dict(schema=1, operation='interface_capture', status='blocked', input_sent=False,
                     focus_requested=False, navigation_performed=False, reason='capture_unavailable')
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0 if value['status'] == 'ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
