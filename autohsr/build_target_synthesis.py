"""Observe the displayed material recipe, keeping its controls separate from cultivation needs."""
from dataclasses import dataclass
import re

from .build_target_read import _has_split_label, guide_blocked
from .build_target_shortfall import AMOUNT, _amount, _inside, _label, _number_text
from .currency_wars_prepare import trusted
from .policy import FORBIDDEN


RECIPE_ITEM = (.59, .115, .70, .169)
RECIPE_HELD = (.59, .168, .75, .225)
RECIPE_QUANTITY = (.59, .745, .745, .793)
QUANTITY_CROP = (.60, .748, .745, .793)
SLIDER_END = (.750, .775, .806, .831)
SLIDER_PLUS = (.806, .775, .857, .831)
RECIPE_MATERIALS = ('梦现管锥',)
RECIPE_BLOCKED_TITLES = tuple(title for title in FORBIDDEN if title != '合成')


@dataclass(frozen=True)
class SynthesisPreview:
    material: str
    held: int
    selected_output: int
    slider_limit: int


def _quantity(fields, page, label, area):
    labels = [t for t in fields.tokens if t.within(area) and _number_text(t).startswith(label)]
    if (len(labels) != 1 or labels[0] not in page.tokens or not _inside(labels[0], area)
            or _has_split_label(fields, (label,), area, exact=False)):
        return None
    heading = labels[0]
    match = re.fullmatch(rf'{label}:?({AMOUNT})?', _number_text(heading))
    if match is None:
        return None
    values = [t for t in fields.tokens if t is not heading and t.within(area)
              and re.match(r'[0-9oO]', _number_text(t))]
    if match[1] is not None:
        return None if values else (heading, int(match[1].replace(',', '')))
    if not values:
        return heading, None
    if len(values) != 1:
        return None
    value = values[0]
    if (value in page.tokens and _inside(value, area) and re.fullmatch(AMOUNT, _number_text(value))
            and 0 <= value.box[0] - heading.box[2] <= .18 * (area[2] - area[0])
            and abs(value.center[1] - heading.center[1]) <= .25 * (area[3] - area[1])):
        return heading, _amount(value)
    return None


def _selected_crop(reader, scene):
    import cv2
    height, width = scene.image.shape[:2]
    x1, y1, x2, y2 = QUANTITY_CROP
    crop = scene.image[round(y1 * height):round(y2 * height), round(x1 * width):round(x2 * width)]
    if not crop.size:
        return None
    zoom = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    fields = trusted(reader.ctx.vision.read(zoom), 0.)
    quantity = _quantity(fields, trusted(fields, reader.confidence), '合成数量', (0, 0, 1, 1))
    return None if quantity is None else quantity[1]


def synthesis_preview(reader, scene, page):
    fields = trusted(scene, 0.)
    header = _label(fields, page, '合成', (.075, .012, .162, .052))
    if header is None or _label(fields, page, '材料合成', (.075, .052, .173, .099)) is None:
        return None, None
    if (guide_blocked(scene, forbidden=RECIPE_BLOCKED_TITLES)
            or fields.has(('挑战成功', '挑战失败', '角色培养'), exact=True)):
        return None, None
    if (_label(fields, page, '所需材料', (.59, .485, .71, .568)) is None
            or _label(fields, page, '合成', (.60, .879, .68, .945)) is None):
        return None, None
    titles = [t for t in fields.tokens if t.within(RECIPE_ITEM) and re.search(r'[\u3400-\u9fff]', t.text)]
    if (len(titles) != 1 or titles[0] not in page.tokens or not _inside(titles[0], RECIPE_ITEM)
            or titles[0].text.strip() not in RECIPE_MATERIALS):
        return None, None
    held = _quantity(fields, page, '当前持有', RECIPE_HELD)
    quantity = _quantity(fields, page, '合成数量', RECIPE_QUANTITY)
    plus = _label(fields, page, ('+', '＋'), SLIDER_PLUS)
    ends = [t for t in fields.tokens if t.within(SLIDER_END) and re.match(r'[0-9oO]', _number_text(t))]
    if (held is None or held[1] is None or quantity is None or plus is None or len(ends) != 1
            or ends[0] not in page.tokens or not _inside(ends[0], SLIDER_END)
            or not re.fullmatch(AMOUNT, _number_text(ends[0]))
            or ends[0].box[2] >= plus.box[0] or abs(ends[0].center[1] - plus.center[1]) > .015
            or ends[0].center[1] - quantity[0].center[1] < .014):
        return None, None
    limit = _amount(ends[0])
    selected = quantity[1] if quantity[1] is not None else _selected_crop(reader, scene)
    if selected is None or selected > limit:
        return None, None
    return SynthesisPreview(titles[0].text.strip(), held[1], selected, limit), header
