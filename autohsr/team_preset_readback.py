"""Read the currently displayed named team without selecting or editing it."""
import re

from .challenge_pages import _clean, _inside, _overlaps
from .challenge_plan import ChallengePlanError, _catalogue


_PRESET_NAMES = ('哈哈哈哈', '记忆', '组一辈子列车', '神主日')
_NAME = (.042, .060, .170, .107)
_CAPTIONS = (
    (.058, .653, .175, .840),
    (.286, .653, .446, .840),
    (.542, .653, .704, .840),
    (.720, .653, .875, .840),
)
_PATHS = frozenset(('毁灭', '巡猎', '智识', '同谐', '虚无', '存护', '丰饶', '记忆', '欢愉'))
_LEVEL = re.compile(r'(?:等级\s*|Lv\.?\s*)?([1-9][0-9]?)', re.IGNORECASE)


def _proof(token, value=None):
    return dict(text=token.text.strip(), value=token.text.strip() if value is None else value,
                box=list(token.box), score=token.score)


def _field(tokens, region, predicate, minimum):
    matches = [token for token in tokens if predicate(token.text.strip()) and _overlaps(token.box, region)]
    if len(matches) != 1 or matches[0].score < minimum or not _inside(matches[0].box, region):
        return None
    return matches[0]


def _level(value):
    match = _LEVEL.fullmatch(value)
    if match is not None and int(match.group(1)) <= 80:
        return int(match.group(1))
    return None


def _slot(tokens, region, names, minimum):
    path = _field(tokens, region, _PATHS.__contains__, minimum)
    name = _field(tokens, region, names.__contains__, minimum)
    level = _field(tokens, region, _level, minimum)
    result = dict(role=None, path=_proof(path) if path else None, level=None)
    if (not all((name, path, level)) or abs(name.box[0] - path.box[0]) > .018
            or not -.009 <= path.box[1] - name.box[3] <= .024
            or not .011 <= name.box[0] - level.center[0] <= .055
            or not name.box[1] - .015 <= level.center[1] <= path.box[3] + .012):
        return result
    return dict(role=_proof(name), path=_proof(path), level=_proof(level, _level(level.text.strip())))


def read_displayed_preset(scene, page, confidence=.65):
    """Read only the name printed under the verified ordinary team heading."""
    if page is None or page['source'].get('kind') != 'ordinary_team_4_6':
        return None
    clean = _clean(scene, .65, blockers=())
    if clean is None:
        return None
    minimum = max(.85, confidence)
    name = _field(clean.tokens, _NAME, _PRESET_NAMES.__contains__, minimum)
    title = page['source']['anchors']['title']['box']
    if (name is None or abs(title[0] - name.box[0]) > .024
            or not -.004 <= name.box[1] - title[3] <= .020):
        return None
    try:
        _, names = _catalogue()
    except ChallengePlanError:
        names = ()
    slots = [_slot(clean.tokens, region, names, minimum) for region in _CAPTIONS]
    labels = [slot['role']['value'] for slot in slots if slot['role'] is not None]
    for slot in slots:
        if slot['role'] is not None and labels.count(slot['role']['value']) > 1:
            slot.update(role=None, level=None)
    return dict(name=_proof(name), slots=slots)


def _agreement(first, second):
    if (first is not None and second is not None and first['value'] == second['value']
            and _overlaps(first['box'], second['box'])):
        return first['value']
    return None


def compare_displayed_presets(first, second):
    """Publish the independently visible names and paths that agree in both frames."""
    if first is None or second is None:
        return None
    name = _agreement(first['name'], second['name'])
    if name is None:
        return None
    slots = []
    for position, (left, right) in enumerate(zip(first['slots'], second['slots']), 1):
        path = _agreement(left['path'], right['path'])
        level = _agreement(left['level'], right['level'])
        role = _agreement(left['role'], right['role']) if path and level is not None else None
        slots.append(dict(position=position, role_name=role, visible_path=path, level=level if role else None))
    return dict(name=name, slots=slots, all_visible_members_named=all(slot['role_name'] for slot in slots))
