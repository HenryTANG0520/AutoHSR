"""Single-frame settlement fields for the read-only Currency Wars report."""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

from .currency_wars_node_ocr import NODE_PATTERN
from .currency_wars_points import NUMBER, compact
from .currency_wars_prepare import trusted
from .models import Token, normalize


_TOP = (.41, .16, .59, .28)
_NEXT = (.45, .76, .55, .87)
_SUMMARY_TITLE = (.22, .15, .33, .25)
_SUMMARY_BOARD = (
    ('我的阵容', (.39, .33, .48, .42)),
    ('投资环境', (.39, .62, .48, .71)),
    ('投资策略', (.56, .62, .66, .71)),
)
_MODE_ROW = (.15, .41, .395, .48)
_STANDARD = ('标准博弈', '标准博奔')
_TIER = re.compile(r'(标准博[弈奔])?a8财富造物主([1-9][0-9]?)')
_RESULT_TITLES = ('对局未完成', '对局失败', '对局胜利')
_FAILURE = ('挑战结束', '挑战失败')
_OTHER_PAGES = ('常规挑战', '获得物品', '点击空白处关闭', '继续挑战', '对局记录', '积分奖励', '零和博弈')
_NODE = re.compile(rf'({NODE_PATTERN})(?:战斗|奖励|首领|遭遇)?')
_NODE_HINT = re.compile(rf'({NODE_PATTERN})[x×](?:战斗|奖励|首领|遭遇)?')
_NODE_ROWS = {'match_defeat': (.39, .24, .53, .32), 'summary': (.39, .15, .53, .25)}
_NODE_CROPS = {'match_defeat': (.403, .265, .435, .307), 'summary': (.402, .195, .430, .238)}
_HP = r'(?:0|[1-9][0-9]{0,2})(?:/100)?'
_HP_LABEL = re.compile(rf'小队生命值({_HP})?')
_HP_REGIONS = {'defeat_rating': (.43, .25, .56, .33), 'summary': (.69, .15, .87, .25)}
_HP_DIGITS = {'defeat_rating': (.535, .559), 'summary': (.811, .847)}
_NODE_KEY, _HP_KEY = 'currency_settlement.node', 'currency_settlement.hp'


@dataclass(frozen=True)
class SettlementObservation:
    page: str
    outcome: str
    node: str | None = None
    remaining_hp: int | None = None
    earned_points: int | None = None
    rank: int | None = None
    wealth: int | None = None


def _label(scene, labels, roi, confidence):
    labels = (labels,) if isinstance(labels, str) else labels
    tokens = [t for t in scene.tokens if t.within(roi) and normalize(t.text) in labels]
    return tokens[0] if len(tokens) == 1 and tokens[0].score >= confidence else None


def _standard_wealth(scene, confidence):
    row = [t for t in scene.tokens if t.within(_MODE_ROW)]
    tiers = [(t, m) for t in row if (m := _TIER.fullmatch(normalize(t.text)))]
    if len(tiers) != 1 or any('超频' in normalize(t.text) for t in row):
        return None
    token, match = tiers[0]
    if token.score < confidence or not (match[1] or _label(scene, _STANDARD, _MODE_ROW, confidence)):
        return None
    value = int(match[2])
    return value if value <= 50 else None


def _layout(scene, confidence):
    if scene.has(_OTHER_PAGES, exact=True):
        return None
    victory = scene.has(('对局胜利', '挑战成功'), exact=True)
    failure = scene.has((*_FAILURE, '对局失败', '对局未完成'), exact=True)
    if victory and failure:
        return None
    title = _label(scene, _RESULT_TITLES, _SUMMARY_TITLE, confidence)
    if title and _label(scene, ('下一页', '下顶'), _NEXT, confidence) and all(
            _label(scene, label, roi, confidence) for label, roi in _SUMMARY_BOARD):
        wealth = _standard_wealth(scene, confidence)
        if wealth is not None:
            return ('match_summary', 'victory', wealth) if normalize(title.text) == '对局胜利' else (
                'defeat_summary', 'defeat', wealth)
    if not _label(scene, _FAILURE, _TOP, confidence):
        return None
    if (_label(scene, '挑战进度', (.45, .32, .56, .405), confidence)
            and _label(scene, '前往结算', _NEXT, confidence)):
        return 'match_defeat', 'defeat', None
    if (_label(scene, '对局评价', (.45, .32, .56, .395), confidence)
            and _label(scene, '下一步', _NEXT, confidence)):
        return 'defeat_rating', 'defeat', None
    return None


def _node_tokens(scene, role):
    tokens = []
    for token in scene.tokens:
        if token.within(_NODE_ROWS[role]):
            value = normalize(token.text)
            exact = _NODE.fullmatch(value)
            hint = exact or _NODE_HINT.fullmatch(value)
            if hint:
                tokens.append((token, hint[1], bool(exact)))
    return tokens


def _bounded_values(scene, key, pattern, region, confidence):
    reads = scene.field_reads.get(key, ())
    if len(reads) != 2:
        return ()
    return tuple(compact(t.text) for t in reads if t is not None and t.within(region)
                 and max(.85, confidence) <= t.score <= 1 and re.fullmatch(pattern, compact(t.text)))


def _node(scene, role, confidence):
    tokens = _node_tokens(scene, role)
    if len(tokens) != 1:
        return None
    token, node, exact = tokens[0]
    if token.score < confidence:
        return None
    local = _bounded_values(scene, _NODE_KEY, NODE_PATTERN, _NODE_ROWS[role], confidence)
    if any(value != node for value in local):
        return None
    return node if exact or local == (node, node) else None


def _life_fields(scene, role):
    region = _HP_REGIONS[role]
    labels = [t for t in scene.tokens if t.within(region) and _HP_LABEL.fullmatch(normalize(t.text))]
    if len(labels) != 1:
        return None, []
    label = labels[0]
    inline = _HP_LABEL.fullmatch(normalize(label.text))[1]
    following = [t for t in scene.tokens if t.within(region) and t.box[0] >= label.box[2]
                 and abs(t.center[1] - label.center[1]) <= .013 and re.search(r'[0-9０-９]', t.text)]
    return label, ([(label, inline)] if inline is not None else []) + [(t, compact(t.text)) for t in following]


def _life(scene, role, confidence):
    label, numbers = _life_fields(scene, role)
    if label is None or label.score < confidence or len(numbers) > 1:
        return None
    local = tuple(int(value.split('/')[0]) for value in
                  _bounded_values(scene, _HP_KEY, _HP, _HP_REGIONS[role], confidence))
    if numbers:
        token, value = numbers[0]
        if token.score < max(.85, confidence) or not re.fullmatch(_HP, value):
            return None
        hp = int(value.split('/')[0])
        if any(value != hp for value in local):
            return None
    elif len(local) == 2 and local[0] == local[1]:
        hp = local[0]
    else:
        return None
    return hp if hp <= 100 else None


def _earned_points(scene, confidence):
    label = _label(scene, '积分', (.145, .585, .22, .655), confidence)
    if label is None:
        return None
    values = [t for t in scene.tokens if t.within((.30, .585, .393, .655))
              and abs(t.center[1] - label.center[1]) <= .013 and re.search(r'[0-9０-９]', t.text)]
    if len(values) != 1 or values[0].score < max(.85, confidence):
        return None
    value = compact(values[0].text)
    return int(value.replace(',', '')) if re.fullmatch(NUMBER, value) else None


def read_settlement(scene, confidence=.65):
    """Use only the current result page, with no inferred match or reward receipts."""
    visible = trusted(scene, 0)
    layout = _layout(visible, confidence)
    if layout is None:
        return None
    page, outcome, wealth = layout
    if page == 'match_defeat':
        node = _node(visible, page, confidence)
        return SettlementObservation(page, outcome, node=node) if node is not None else None
    role = 'defeat_rating' if page == 'defeat_rating' else 'summary'
    hp = _life(visible, role, confidence)
    if hp is not None and (hp == 0) != (outcome == 'defeat'):
        return None
    if page == 'defeat_rating':
        return SettlementObservation(page, outcome, remaining_hp=hp) if hp == 0 else None
    return SettlementObservation(page, outcome, node=_node(visible, role, confidence), remaining_hp=hp,
                                 earned_points=_earned_points(visible, confidence), rank=8, wealth=wealth)


def _crop(image, roi):
    h, w = image.shape[:2]
    x1, y1, x2, y2 = roi
    return image[round(y1*h):round(y2*h), round(x1*w):round(x2*w)]


def _life_crop(image, role, label):
    import cv2

    x1, x2 = _HP_DIGITS[role]
    roi = (x1, label.box[1] - .004, x2, label.box[3] + .004)
    field = _crop(image, roi)
    if field.size == 0:
        return roi, ()
    brightness = field.max(axis=2)
    # Separate the actual digits from the adjacent heart. Color locates the
    # field here. The value still requires two OCR reads.
    contrast = (cv2.subtract(field[:, :, 2], cv2.max(field[:, :, 0], field[:, :, 1]))
                if role == 'defeat_rating' else brightness)
    _, mask = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    x, y, w, h = cv2.boundingRect(mask)
    if not 4 <= h <= .92 * field.shape[0] or not 2 <= w < field.shape[1]:
        return roi, ()
    pad = max(1, round(h/9))
    bounds = (slice(max(0, y-pad), y+h+pad), slice(max(0, x-pad), x+w+2*pad))
    color = field[bounds]
    gray = cv2.normalize(brightness[bounds], None, 0, 255, cv2.NORM_MINMAX)
    return roi, (color, cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))


def supplement_settlement_fields(scene, reader, confidence=.65):
    """Keep bounded digit reads separate from the shared page/action OCR."""
    visible = trusted(scene, 0)
    layout = _layout(visible, confidence)
    if layout is None or scene.image is None:
        return scene
    import cv2

    page, outcome, _ = layout
    fields = dict(scene.field_reads)
    role = page if page in ('match_defeat', 'defeat_rating') else 'summary'
    if role in _NODE_ROWS:
        tokens = _node_tokens(visible, role)
        if len(tokens) == 1 and tokens[0][0].score >= confidence and not tokens[0][2]:
            roi = _NODE_CROPS[role]
            crop = _crop(scene.image, roi)
            if crop.size:
                patch = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
                _, binary = cv2.threshold(patch.max(axis=2), 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                values = (reader.read_node(patch), reader.read_node(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)))
                fields[_NODE_KEY] = tuple(Token(t.text, t.score, roi) if t else None for t in values)
    if outcome == 'defeat' and role in _HP_REGIONS:
        label, numbers = _life_fields(visible, role)
        if label is not None and label.score >= confidence and not numbers:
            roi, views = _life_crop(scene.image, role, label)
            if views:
                values = [reader.read_number(cv2.resize(view, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
                          for view in views]
                fields[_HP_KEY] = tuple(Token(t.text, t.score, roi) if t else None for t in values)
    return replace(scene, field_reads=fields)
