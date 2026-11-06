"""Read fixed investment badge bundles without changing the execution layout."""
from dataclasses import asdict, dataclass, replace
import re

import numpy as np

from .currency_wars_investment_badges import (
    _BUNDLES, _inside, badge_effect_text, bundle_declaration_conflicts, parse_badge_declaration,
)
from .currency_wars_prepare import trusted
from .models import Token, normalize


_READ_PREFIX = 'cw_badge.'
_TITLE = (.437, .066, .564, .112)
_GUIDE = (.757, .025, .829, .083)
_RETURN = (.851, .024, .981, .082)
_LEGEND = (.088, .069, .145, .116)
_BLOCKERS = ('密码', '验证码', '扫码登录', '用户协议', '资源下载', '更新游戏', '账号验证')


@dataclass(frozen=True)
class _Layout:
    centers: tuple
    titles: tuple
    counters: tuple
    button: tuple
    inset: bool = False


_LAYOUTS = (
    _Layout((.24, .50, .76), (.432, .479), (.764, .825), (.884, .938)),
    _Layout((.257, .50, .744), (.400, .446), (.710, .773), (.823, .884), True),
)


def _single(tokens, text, region, confidence):
    found = [token for token in tokens if token.within(region) and normalize(token.text) == text]
    if len(found) == 1 and found[0].score >= confidence and _inside(found[0], region):
        return found[0]
    return None


def _columns(tokens, layout, vertical, pattern, confidence):
    result = []
    for x in layout.centers:
        region = (x-.111, vertical[0], x+.111, vertical[1])
        fields = [t for t in tokens if t.within(region) and re.fullmatch(pattern, normalize(t.text))]
        if len(fields) != 1 or fields[0].score < confidence or not _inside(fields[0], region):
            return ()
        result.append(fields[0])
    return tuple(result)


def _layout(scene, confidence):
    from .vision import helper_overlay

    current = trusted(scene, confidence)
    image = current.image
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
            or image.shape[2] != 3 or image.shape[0] < 360 or image.shape[1] < 640
            or current.has(_BLOCKERS) or helper_overlay(current)):
        return None
    positive = max(.85, confidence)
    if (not _single(current.tokens, '请选择投资策略', _TITLE, positive)
            or not _single(current.tokens, '攻略', _GUIDE, positive)):
        return None
    returned = _single(current.tokens, '返回备战界面', _RETURN, positive)
    legend = _single(current.tokens, '图例', _LEGEND, positive)
    for layout in _LAYOUTS:
        if returned is None and (layout.inset or legend is None):
            continue
        names = _columns(current.tokens, layout, layout.titles, r'[a-z0-9\u4e00-\u9fff]{2,28}', positive)
        counters = _columns(current.tokens, layout, layout.counters, r'刷新次数[0-9]{1,2}', max(.80, confidence))
        button = _single(current.tokens, '确认', (.459, layout.button[0], .548, layout.button[1]), positive)
        if names and counters and button and len({normalize(t.text) for t in names}) == 3:
            return current, layout, names, button
    return None


def _crop(image, region):
    h, w = image.shape[:2]
    left, top, right, bottom = [round(value * size) for value, size in zip(region, (w, h, w, h))]
    return image[top:bottom, left:right], (left/w, top/h, right/w, bottom/h)


def _body_region(name, layout):
    x = name.center[0]
    return (x-.122, .443 if layout.inset else .473, x+.122, .580 if layout.inset else .623)


def _full_body_variants(scene, reader, slot):
    import cv2

    # At the regular layout the entire, short declaration fits inside this band.
    x = (.24, .495, .76)[slot]
    pixels, (left, top, right, bottom) = _crop(scene.image, (x-.119, .456, x+.119, .623))
    for scale, channel in ((1., 'color'), (1.8, 'color'), (2.5, 'color'), (2.5, 'gray'), (2.5, 'green')):
        sample = pixels
        if channel != 'color':
            values = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY) if channel == 'gray' else pixels[:, :, 1]
            sample = cv2.cvtColor(values, cv2.COLOR_GRAY2BGR)
        if scale != 1.:
            sample = cv2.resize(sample, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        tokens = reader.read(sample).tokens
        yield tuple(Token(t.text, t.score, (left+t.box[0]*(right-left), top+t.box[1]*(bottom-top),
                                            left+t.box[2]*(right-left), top+t.box[3]*(bottom-top)))
                    for t in tokens)


def _inset_body_variants(scene, reader, name):
    import cv2

    # The tinted role name can split a line in the detector. Reuse the full-frame
    # boxes to locate each consecutive line and recognize the entire strip.
    x = name.center[0]
    strips = []
    for y in (.464, .490, .516):
        hits = [t for t in scene.tokens if t.within((x-.117, y-.014, x+.117, y+.014))]
        if not hits or any(not x-.117 <= t.box[0] < t.box[2] <= x+.117 for t in hits):
            return
        left = max(x-.117, min(t.box[0] for t in hits)-.004)
        right = min(x+.117, max(t.box[2] for t in hits)+.005)
        pixels, box = _crop(scene.image, (left, y-.014, right, y+.014))
        strips.append((pixels, box))
    for grayscale in (False, True):
        tokens = []
        for pixels, box in strips:
            sample = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY) if grayscale else pixels
            sample = cv2.resize(sample, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
            if grayscale:
                sample = cv2.cvtColor(sample, cv2.COLOR_GRAY2BGR)
            value = reader._read_field(sample, r'.{1,80}')
            if value is not None:
                tokens.append(Token(value.text, value.score, box))
        if len(tokens) == len(strips):
            yield tuple(tokens)


def supplement_bundle_observation(scene, reader):
    """Preserve narrow reads separately so native investment never uses them."""
    verified = _layout(scene, reader.confidence)
    if verified is None:
        return scene
    current, layout, names, _ = verified
    reads = dict(scene.field_reads)
    for slot, name in enumerate(names):
        if normalize(name.text) not in _BUNDLES:
            continue
        variants = (_inset_body_variants(current, reader, name) if layout.inset
                    else _full_body_variants(current, reader, slot))
        for index, parts in enumerate(variants):
            if 1 <= len(parts) <= 8 and len(reads) < 32:
                reads[f'{_READ_PREFIX}s{slot}.{index}'] = parts
    return replace(scene, field_reads=reads) if reads != scene.field_reads else scene


def _selection(scene, layout, button):
    white = np.min(scene.image, axis=2)
    bright = white > 202
    outlines = []
    for x in layout.centers:
        edges = []
        for sign in (-1, 1):
            left, right = sorted((x+sign*.089, x+sign*.116))
            strip, _ = _crop(bright, (left, .541, right, .675))
            upper, lower = np.array_split(strip, 2, axis=0)
            edges.append(float(np.minimum(upper.mean(axis=0), lower.mean(axis=0)).max()))
        outlines.append(edges)
    x, y = button.center
    button_pixels, _ = _crop(bright, (x-.061, y-.017, x+.061, y+.017))
    lit = float(button_pixels.mean())
    marked = [slot for slot, edges in enumerate(outlines) if min(edges) >= .62]
    if not marked and lit <= .20 and max(value for edges in outlines for value in edges) <= .15:
        return 'unselected', None
    if len(marked) != 1 or lit < .60:
        return 'unverified', None
    slot = marked[0]
    if any(max(edges) > .15 for i, edges in enumerate(outlines) if i != slot):
        return 'unverified', None
    x = layout.centers[slot]
    icon, _ = _crop(white, (x-.045, .248, x+.045, .375))
    return ('unverified', None) if (icon > 235).mean() >= .20 else ('selected', slot)


def read_bundle_observation(scene, confidence=.65):
    """Return only complete independent badge, role and gear declarations."""
    verified = _layout(scene, confidence)
    if verified is None:
        return []
    current, layout, names, button = verified
    state, selected = _selection(current, layout, button)
    declarations = []
    all_tokens = trusted(scene, 0).tokens
    for slot, name in enumerate(names):
        title = normalize(name.text)
        if title not in _BUNDLES:
            continue
        left, top, right, bottom = _body_region(name, layout)
        tail = (left, bottom, right, layout.counters[0]-.01)
        if any(t.within(tail) for t in all_tokens):
            continue
        full = badge_effect_text(name, [t for t in all_tokens if t.within((left, top, right, bottom))], confidence)
        variants = []
        for index in range(2 if layout.inset else 5):
            parts = current.field_reads.get(f'{_READ_PREFIX}s{slot}.{index}', ())
            if parts and all(isinstance(t, Token) and _inside(t, (left, top-.006, right, bottom)) for t in parts):
                variants.append(badge_effect_text(name, parts, confidence))
        parsed = [parse_badge_declaration(title, effect) for effect in variants if effect is not None]
        declaration = parse_badge_declaration(title, full) if full is not None else None
        if declaration is None:
            exact = [item for item in parsed if item is not None]
            if len(exact) < 2:
                continue
            declaration = exact[0]
        if any(effect is not None and bundle_declaration_conflicts(effect, declaration) for effect in (full, *variants)):
            continue
        slot_state = 'other_selected' if selected is not None and slot != selected else state
        declarations.append(dict(slot=slot, title=title, status='delivery_unverified', delivery_verified=False,
                                 selection_state=slot_state, **asdict(declaration)))
    return declarations
