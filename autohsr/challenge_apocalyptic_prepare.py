"""Read-only preparation pages for the observed Apocalyptic Shadow layout."""
import re

from . import challenge_pages as pages
from .models import Token, normalize


_PERIOD = '支配遗忘'
_BOSSES = ('勾魂摄魄的支配者', '迷惘之渊的裁定者')
_NODE = r'节点(?:一\|?勾魂摄魄的支配者|二\|?迷惘之渊的裁定者)'
_CARD = re.compile(r'0([1-4])(尚未挑战|未解锁)?')
_DIGITS_AND_DIVIDER = str.maketrans('０１２３４５６７８９｜', '0123456789|')

# Normal 4.6 layout, calibrated against the continuous difficulty 03 sample.
# Use the whole box in the reference client area, including for counterevidence.
_TITLE = (.042, .028, .119, .080)
_SUBTITLE = (.043, .054, .117, .098)
_HOME_PERIOD = (.436, .497, .567, .551)
_HOME_BUTTON = (.391, .745, .607, .814)
_HOME_UNLOCK = (.453, .154, .550, .214)
_CARDS = tuple((left, .861, right, .923) for left, right in
               ((.197, .302), (.346, .449), (.494, .595), (.639, .742)))
_BOSS_HEADER = (.397, .103, .663, .168)
_BOSS_DIFFICULTY = (.400, .150, .454, .192)
_BOSS_REMINDER = (.640, .873, .739, .932)
_BOSS_BUTTON = (.744, .874, .938, .936)
_SETUP_HEADING = (.382, .108, .484, .168)
_SETUP_LEVEL = (.126, .182, .184, .219)
_SETUP_PERIOD = (.104, .216, .207, .267)
_SETUP_NODES = ((.499, .205, .706, .255), (.499, .466, .706, .518))
_SETUP_BUTTON = (.719, .874, .929, .954)

_NAVIGATION_CAPTIONS = ('前往挑战', '下一步', '前往编队')
_BLOCKERS = (tuple(word for word in pages._BLOCKED if word != '未解锁')
             + tuple(word for word in pages._SIDE_BLOCKED if word not in _NAVIGATION_CAPTIONS)
             + ('新难度等级解锁', '星启', '不可更换', '角色详情', '更换编队',
                '当前队伍', '领取奖励', '混沌回忆', '虚构叙事', '节点三', '节点3'))


def _text(token):
    return normalize(token.text).translate(_DIGITS_AND_DIVIDER)


def _field(scene, region, pattern, minimum):
    """One complete OCR field, including a contiguous same-row split."""
    parts = sorted((t for t in scene.tokens if pages._inside(t.box, region)),
                   key=lambda t: t.box[0])
    if not parts or any(t.score < minimum for t in parts):
        return None
    if any(not pages._same_line(parts[0], right) or not -.009 <= right.box[0] - left.box[2] <= .022
           for left, right in zip(parts, parts[1:])):
        return None
    text = ''.join(_text(t) for t in parts)
    if not re.fullmatch(pattern, text):
        return None
    return Token(text, min(t.score for t in parts),
                 (parts[0].box[0], min(t.box[1] for t in parts),
                  max(t.box[2] for t in parts), max(t.box[3] for t in parts)))


def _proof(token):
    return dict(text=token.text.replace('|', ''), box=list(token.box), score=token.score, source='ocr')


def _words(tokens):
    tokens = tuple(tokens)
    return tuple(map(_text, tokens)) + pages._line_words(tokens, gap=.018)


def _foreign_caption(scene, expected, region):
    # A weak but legible contradictory caption can veto. Only a strong,
    # unique exact field in the expected footer is positive evidence.
    outside = _words(t for t in scene.tokens if not pages._inside(t.box, region))
    return (any(caption in word for caption in _NAVIGATION_CAPTIONS for word in outside)
            or any(caption != expected and caption in word
                   for caption in _NAVIGATION_CAPTIONS for word in _words(scene.tokens)))


def _observation(kind, anchors, caption, button, *, level=None, **details):
    basis = dict(schema=1, page=kind, layout='domination_oblivion_normal',
                 anchors={name: _proof(token) for name, token in anchors.items()},
                 button=dict(expected_caption=caption, caption=_proof(button) if button else None,
                             caption_verified=button is not None, activation='unknown'),
                 execution_supported=False, **details)
    return pages.Observation(kind, pages.APOCALYPTIC, level, basis=basis)


def _lobby(scene, title, minimum):
    period = _field(scene, _HOME_PERIOD, _PERIOD, minimum)
    button = _field(scene, _HOME_BUTTON, '前往挑战', minimum)
    unlock = _words(t for t in scene.tokens if pages._inside(t.box, _HOME_UNLOCK))
    if (not period or not button or _foreign_caption(scene, '前往挑战', _HOME_BUTTON)
            or any(re.search(r'难度0[1-4]', word) for word in unlock)):
        return pages._unknown('incomplete_apocalyptic_lobby')
    anchors = dict(title=title, period=period, home_caption=button)
    cards = []
    for level, region in enumerate(_CARDS, 1):
        card = _field(scene, region, _CARD, minimum)
        match = _CARD.fullmatch(card.text) if card else None
        if match is None or int(match[1]) != level:
            return pages._unknown('incomplete_apocalyptic_difficulty_strip')
        anchors[f'card_{level}'] = card
        cards.append(dict(level=level, caption=match[2], box=list(card.box)))
    outside = _words(t for t in scene.tokens if not any(pages._inside(t.box, r) for r in _CARDS))
    if any('未解锁' in word for word in outside):
        return pages._unknown('apocalyptic_lock_outside_difficulty_strip')
    return _observation('lobby', anchors, '前往挑战', button, period=_PERIOD,
                        cards=cards, selected_level=None)


def _boss_info(scene, title, heading, minimum):
    # OCR may fuse the difficulty numeral with the node/boss row, especially
    # at smaller resolutions. The label below still anchors its left edge.
    header = _field(scene, _BOSS_HEADER, r'0[1-4]' + _NODE, minimum)
    difficulty = _field(scene, _BOSS_DIFFICULTY, '难度', minimum)
    reminder = _field(scene, _BOSS_REMINDER, '本期不再提示', minimum)
    if (not all((header, difficulty, reminder)) or header.box[2] < .58
            or abs(header.box[0] - difficulty.box[0]) > .015 or header.center[1] >= difficulty.center[1]):
        return pages._unknown('incomplete_apocalyptic_boss_info')
    index = 1 if header.text[4] == '一' else 2
    caption = '下一步' if index == 1 else '前往编队'
    if _foreign_caption(scene, caption, _BOSS_BUTTON):
        return pages._unknown('conflicting_apocalyptic_boss_info_caption')
    button = _field(scene, _BOSS_BUTTON, caption, minimum)
    return _observation('boss_info', dict(title=title, heading=heading, difficulty=difficulty,
                        header=header, reminder=reminder), caption, button,
                        level=int(header.text[:2]), node=index, boss=_BOSSES[index - 1], period=None)


def _node_setup(scene, title, heading, minimum):
    role_heading = _field(scene, _SETUP_HEADING, '角色编队', minimum)
    period = _field(scene, _SETUP_PERIOD, _PERIOD, minimum)
    one, two = (_field(scene, region, pattern, minimum) for region, pattern in
                zip(_SETUP_NODES, (r'节点一\|?' + _BOSSES[0], r'节点二\|?' + _BOSSES[1])))
    if (not all((role_heading, period, one, two))
            or abs(one.box[0] - two.box[0]) > .018
            or _foreign_caption(scene, '前往挑战', _SETUP_BUTTON)):
        return pages._unknown('incomplete_apocalyptic_node_setup')
    anchors = dict(title=title, heading=heading, role_heading=role_heading, period=period,
                   node_one=one, node_two=two)
    level = _field(scene, _SETUP_LEVEL, r'难度0[1-4]', minimum)
    if level is not None and any(re.fullmatch(r'(?:难度)?0[1-4]|难度', _text(t))
                                 and pages._overlaps(t.box, _SETUP_LEVEL)
                                 and not pages._inside(t.box, _SETUP_LEVEL) for t in scene.tokens):
        level = None
    if level is not None:
        anchors['level'] = level
    button = _field(scene, _SETUP_BUTTON, '前往挑战', minimum)
    nodes = [dict(node=index, boss=boss, label_box=list(token.box)) for index, boss, token in
             zip((1, 2), _BOSSES, (one, two))]
    return _observation('node_setup', anchors, '前往挑战', button,
                        level=int(level.text[-2:]) if level else None, period=_PERIOD, nodes=nodes,
                        selected_node=None, team_feedback='unknown', role_availability='unknown',
                        slot_feedback='unknown')


def observe(scene, confidence=.65):
    """Recognize the four observed preparations without generating a target."""
    clean = pages._clean(scene, confidence, blockers=())
    if clean is None:
        return pages._unknown('invalid_or_stale_apocalyptic_capture')
    words = _words(clean.tokens)
    if any(fragment in word for fragment in _BLOCKERS for word in words):
        return pages._unknown('apocalyptic_other_mode_transition_or_dialog')
    minimum = max(.85, confidence)
    title = _field(clean, _TITLE, '末日幻影', minimum)
    if title is None:
        return pages._unknown('missing_apocalyptic_title')
    subtitle = _field(clean, _SUBTITLE, '首领信息|编队', minimum)
    if subtitle is not None:
        if any('未解锁' in word for word in words):
            return pages._unknown('apocalyptic_lock_outside_lobby')
        if subtitle.text == '首领信息':
            return _boss_info(clean, title, subtitle, minimum)
        return _node_setup(clean, title, subtitle, minimum)
    subtitle_words = _words(t for t in clean.tokens if pages._inside(t.box, _SUBTITLE))
    if any(word in ('首领信息', '编队') for word in subtitle_words):
        return pages._unknown('unverified_apocalyptic_subtitle')
    return _lobby(clean, title, minimum)


def same_page(first, second):
    """The semantic anchors must agree and stay in the same screen positions."""
    if first.kind == 'unknown' or (first.kind, first.mode, first.level) != (second.kind, second.mode, second.level):
        return False
    a, b = first.basis['anchors'], second.basis['anchors']
    return a.keys() == b.keys() and all(
        a[name]['text'] == b[name]['text'] and pages._overlaps(a[name]['box'], b[name]['box'])
        for name in a)
