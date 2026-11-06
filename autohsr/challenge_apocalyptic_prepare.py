"""Read-only preparation pages for the observed Apocalyptic Shadow layout."""
from dataclasses import replace
import re

import cv2
import numpy as np

from . import challenge_pages as pages
from .models import Token, normalize


_PERIOD = '支配遗忘'
_BOSSES = ('勾魂摄魄的支配者', '迷惘之渊的裁定者')
_NODE = r'节点(?:一\|?勾魂摄魄的支配者|二\|?迷惘之渊的裁定者)'
_CARD = re.compile(r'0([1-4])(尚未挑战|未解锁)?')
_DIGITS_AND_DIVIDER = str.maketrans('０１２３４５６７８９｜', '0123456789|')
COUNTEREVIDENCE = 'apocalyptic_prepare_counterevidence'
VETO_FLOOR = .65

# Normal 4.6 layout, calibrated against the continuous difficulty 03 sample.
# Use the whole box in the reference client area, including for counterevidence.
_TITLE = (.042, .028, .119, .080)
_SUBTITLE = (.043, .054, .117, .098)
_HOME_PERIOD = (.436, .497, .567, .551)
_HOME_BUTTON = (.391, .745, .607, .814)
_HOME_UNLOCK = (.453, .154, .550, .214)
_DIALOG_HEADER = (.357, .315, .642, .465)
_CARDS = tuple((left, .861, right, .923) for left, right in
               ((.197, .302), (.346, .449), (.494, .595), (.639, .742)))
# Client-relative bounds from the regular 4.6 overview after a level-04 run.
_PLAYED_MODE = (.465, .664, .559, .714)
_PLAYED_CHANGE = (.847, .658, .968, .713)
_PLAYED_NODE_LABELS = ((.352, .735, .422, .793), (.552, .735, .622, .793))
_PLAYED_NODE_POINTS = ((.433, .750, .512, .808), (.638, .750, .715, .808))
_PLAYED_RETRIES = ((.426, .802, .516, .850), (.626, .802, .722, .850))
_PLAYED_FIELD_CONFLICT = re.compile(r'[0-9]{1,6}|(?:0[1-4])?(?:尚未挑战|未解锁|快速通关)|节点[一二12]?')
_SELECTION_LINES = tuple((left, .918, right, .930) for left, right in
                         ((.213, .336), (.361, .484), (.511, .634), (.659, .783)))
_BOSS_HEADER = (.397, .103, .663, .168)
_BOSS_DIFFICULTY = (.400, .150, .454, .192)
_BOSS_REMINDER = (.640, .873, .739, .932)
_BOSS_BUTTON = (.744, .874, .938, .936)
# A fixed-team node detail has its own header and two footer buttons.
_LOCKED_HEADER = (.372, .104, .652, .171)
_LOCKED_DIFFICULTY = (.371, .149, .444, .195)
_LOCKED_TEAM = (.360, .703, .452, .766)
_LOCKED_STATUS = (.527, .806, .625, .862)
_LOCKED_ROLE_DETAIL = (.610, .870, .771, .938)
_LOCKED_CHALLENGE = (.777, .870, .975, .938)
_SETUP_HEADING = (.382, .108, .484, .168)
_SETUP_LEVEL = (.126, .182, .184, .219)
_SETUP_PERIOD = (.104, .216, .207, .267)
_SETUP_NODES = ((.499, .205, .706, .255), (.499, .466, .706, .518))
_SETUP_ROLE_DETAIL = (.574, .874, .689, .954)
_SETUP_BUTTON = (.719, .874, .929, .954)
_PICKER_LIST_TAB = (.058, .117, .119, .159)
_PICKER_PRESET_TAB = (.191, .117, .256, .159)
_PICKER_BADGES = (.021, .156, .294, .867)
_PICKER_WORDS = ('角色列表', '预设编队')

_NAVIGATION_CAPTIONS = ('前往挑战', '下一步', '前往编队', '更换编队')
_LOCKED_WORDS = ('当前队伍', '不可更换')
_BLOCKERS = (tuple(word for word in pages._BLOCKED if word != '未解锁')
             + tuple(word for word in pages._SIDE_BLOCKED if word not in _NAVIGATION_CAPTIONS)
             + ('新难度等级解锁', '星启', '更换编队', '领取奖励',
                '混沌回忆', '虚构叙事', '节点三', '节点3',
                '清空当前', '对应节点积分', '重置对应关卡'))
_PLAYED_BLOCKERS = tuple(word for word in _BLOCKERS if word not in ('更换编队', '重新挑战'))


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


def _words_outside(scene, regions):
    return _words(t for t in scene.tokens if not any(pages._inside(t.box, region) for region in regions))


def _foreign_caption(scene, expected, region):
    # A weak but legible contradictory caption can veto. Only a strong,
    # unique exact field in the expected footer is positive evidence.
    outside = _words_outside(scene, (region,))
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
    if any('未解锁' in word for word in _words_outside(scene, _CARDS)):
        return pages._unknown('apocalyptic_lock_outside_difficulty_strip')
    return _observation('lobby', anchors, '前往挑战', button, period=_PERIOD,
                        cards=cards, selected_level=None)


def _selection_line(image):
    """Find one gold line spanning the card, below its text and stars."""
    height, width = image.shape[:2]
    candidates = []
    for level, region in enumerate(_SELECTION_LINES, 1):
        left, top, right, bottom = (round(value * size) for value, size in
                                    zip(region, (width, height, width, height)))
        hsv = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
        gold = cv2.inRange(hsv, (8, 18, 155), (42, 255, 255)) > 0
        coverage = gold.mean(axis=1)
        thirds = np.stack([part.mean(axis=1) for part in np.array_split(gold, 3, axis=1)])
        rows = np.flatnonzero((coverage >= .80) & (thirds.min(axis=0) >= .68))
        if rows.size:
            # A fill or a band cut off by the search boundary is ambiguous.
            span = rows[-1] - rows[0] + 1
            if rows[0] == 0 or rows[-1] == len(coverage) - 1 or span > round(.0046 * height):
                return None
            row = max(rows, key=lambda i: coverage[i])
            candidates.append((level, dict(
                box=[left / width, (top + int(row)) / height, right / width, (top + int(row) + 1) / height],
                source='gold_difficulty_underline', coverage=float(coverage[row]))))
    return candidates[0] if len(candidates) == 1 else None


def _played_field(scene, region, pattern, minimum):
    # A competing label, number or status may extend beyond the field.
    if any(pages._overlaps(t.box, region) and not pages._inside(t.box, region)
           and _PLAYED_FIELD_CONFLICT.fullmatch(_text(t))
           for t in scene.tokens):
        return None
    return _field(scene, region, pattern, minimum)


def _played_overview(scene, title, mode, change, words, minimum):
    period = _field(scene, _HOME_PERIOD, _PERIOD, minimum)
    labels = [_played_field(scene, region, label, minimum) for region, label in
              zip(_PLAYED_NODE_LABELS, ('节点一', '节点二'))]
    points = [_played_field(scene, region, r'[0-9]{1,4}', minimum) for region in _PLAYED_NODE_POINTS]
    other_pages = (*_LOCKED_WORDS, '角色详情', '本期不再提示', '首领信息', '角色编队')
    if (not title or not period or not all((*labels, *points))
            or abs(mode.center[1] - change.center[1]) > .016
            or not all(pages._same_line(label, score) for label, score in zip(labels, points))
            or abs(labels[0].center[1] - labels[1].center[1]) > .018
            or abs(points[0].center[1] - points[1].center[1]) > .018
            or _foreign_caption(scene, '更换编队', _PLAYED_CHANGE)
            or any('重新挑战' in word for word in _words_outside(scene, _PLAYED_RETRIES))
            or any('未解锁' in word for word in _words_outside(scene, _CARDS))
            or any(fragment in word for word in words for fragment in other_pages)):
        return pages._unknown('incomplete_apocalyptic_played_overview')
    selection = _selection_line(scene.image)
    if selection is None:
        return pages._unknown('unverified_apocalyptic_selected_difficulty')
    level, line = selection
    card = _played_field(scene, _CARDS[level - 1], r'0[1-4][0-9]{1,4}', minimum)
    scores = [int(token.text) for token in points]
    if (card is None or int(card.text[1]) != level or max(scores) > 4000
            or not 0 < sum(scores) == int(card.text[2:])):
        return pages._unknown('unverified_apocalyptic_played_difficulty')
    anchors = dict(title=title, period=period, regular_mode=mode, change_team=change, selected_card=card,
                   node_one=labels[0], node_two=labels[1], node_one_points=points[0], node_two_points=points[1])
    return _observation('played_overview', anchors, '更换编队', change, level=level, period=_PERIOD,
                        visible_selected_level=level, selection=line, visible_node_points=scores)


def _node_header(scene, header_region, difficulty_region, level_pattern, minimum):
    # OCR may fuse the difficulty numeral with the node/boss row, especially
    # at smaller resolutions. The label below still anchors its left edge.
    header = _field(scene, header_region, level_pattern + _NODE, minimum)
    difficulty = _field(scene, difficulty_region, '难度', minimum)
    if (not header or not difficulty or header.box[2] < .58
            or abs(header.box[0] - difficulty.box[0]) > .015 or header.center[1] >= difficulty.center[1]):
        return None
    return header, difficulty


def _boss_info(scene, title, heading, minimum):
    fields = _node_header(scene, _BOSS_HEADER, _BOSS_DIFFICULTY, r'0[1-4]', minimum)
    reminder = _field(scene, _BOSS_REMINDER, '本期不再提示', minimum)
    if fields is None or not reminder:
        return pages._unknown('incomplete_apocalyptic_boss_info')
    header, difficulty = fields
    index = 1 if header.text[4] == '一' else 2
    caption = '下一步' if index == 1 else '前往编队'
    if _foreign_caption(scene, caption, _BOSS_BUTTON):
        return pages._unknown('conflicting_apocalyptic_boss_info_caption')
    button = _field(scene, _BOSS_BUTTON, caption, minimum)
    return _observation('boss_info', dict(title=title, heading=heading, difficulty=difficulty,
                        header=header, reminder=reminder), caption, button,
                        level=int(header.text[:2]), node=index, boss=_BOSSES[index - 1], period=None)


def _locked_node_detail(scene, words, minimum):
    # Below the highest difficulty there is no Starward variant. Difficulty
    # 04 needs its own normal-mode proof before this layout can be used there.
    fields = _node_header(scene, _LOCKED_HEADER, _LOCKED_DIFFICULTY, r'0[1-3]', minimum)
    team = _field(scene, _LOCKED_TEAM, '当前队伍', minimum)
    locked = _field(scene, _LOCKED_STATUS, '不可更换', minimum)
    details = _field(scene, _LOCKED_ROLE_DETAIL, '角色详情', minimum)
    challenge = _field(scene, _LOCKED_CHALLENGE, '前往挑战', minimum)
    if (fields is None or not all((team, locked, details, challenge))
            or abs(details.center[1] - challenge.center[1]) > .016
            or _foreign_caption(scene, '前往挑战', _LOCKED_CHALLENGE)
            or any(fragment in word for word in words for fragment in ('未解锁', '本期不再提示', '角色编队'))):
        return pages._unknown('incomplete_apocalyptic_locked_node_detail')
    header, difficulty = fields
    if max(header.box[0], difficulty.box[0]) > .405:
        return pages._unknown('wrong_apocalyptic_locked_node_header_position')
    # A partly overlapping second numeral or node title still conflicts with
    # this header even if its box is too wide to be a positive field.
    for token in scene.tokens:
        value = _text(token)
        region = _LOCKED_DIFFICULTY if value.startswith('难度') else _LOCKED_HEADER
        if (pages._overlaps(token.box, region) and not pages._inside(token.box, region)
                and (value.startswith('难度') or value in _BOSSES
                     or re.match(r'(?:0[1-4](?:$|节点)|节点[一二12])', value))):
            return pages._unknown('conflicting_apocalyptic_locked_node_header')
    index = 1 if header.text[4] == '一' else 2
    anchors = dict(header=header, difficulty=difficulty, current_team=team,
                   team_lock=locked, role_detail=details, challenge_caption=challenge)
    return _observation('locked_node_detail', anchors, '前往挑战', challenge,
                        level=int(header.text[:2]), node=index, boss=_BOSSES[index - 1],
                        period=None, team_editability='locked', selected_level=None)


def _setup_headers(scene, minimum):
    role_heading = _field(scene, _SETUP_HEADING, '角色编队', minimum)
    one, two = (_field(scene, region, pattern, minimum) for region, pattern in
                zip(_SETUP_NODES, (r'节点一\|?' + _BOSSES[0], r'节点二\|?' + _BOSSES[1])))
    if not all((role_heading, one, two)) or abs(one.box[0] - two.box[0]) > .018:
        return None
    return dict(role_heading=role_heading, node_one=one, node_two=two)


def _picker_rails(image):
    # Read the two long rails to the right of the four circular slots.
    # A single remaining rail can occur while the list is closing.
    rails, contrast = [], []
    for y in (150, 185, 269, 305):
        patch = image[y - 5:y + 6, 563:667]
        luma = patch.min(axis=2).astype(np.int16)
        neutral = np.ptp(patch[2:-2], axis=2) <= 40
        light = (luma[2:-2] >= 145) & neutral
        rails.append(float(light.mean(axis=1).max()))
        peaks = luma[2:-2] - np.maximum(luma[:-4], luma[4:])
        contrast.append(float(((peaks >= 16) & neutral).mean(axis=1).max()))
    return tuple(rails), tuple(contrast)


def _candidate_picker(scene, heading, words, minimum):
    image = cv2.resize(scene.image, (802, 454), interpolation=cv2.INTER_AREA)
    rails, contrast = _picker_rails(image)
    if max(*rails, *contrast) < .80 and not any(word in words for word in _PICKER_WORDS):
        return None
    rail_pairs = (rails[:2], rails[2:])
    active = [node for node, pair in enumerate(rail_pairs, 1) if min(pair) >= .80]
    visible = sum(max(pair) >= .80 for pair in rail_pairs)
    listed = _field(scene, _PICKER_LIST_TAB, _PICKER_WORDS[0], minimum)
    preset = _field(scene, _PICKER_PRESET_TAB, _PICKER_WORDS[1], minimum)
    headers = _setup_headers(scene, minimum)
    button = _field(scene, _SETUP_BUTTON, '前往挑战', minimum)
    details = _field(scene, _SETUP_ROLE_DETAIL, '角色详情', minimum)
    if (len(active) != 1 or visible != 1
            or not all((listed, preset, headers, button, details))
            or abs(details.center[1] - button.center[1]) > .016
            or _foreign_caption(scene, '前往挑战', _SETUP_BUTTON)
            or image[59:66, 23:48].min(axis=2).mean() < 185
            or image[59:66, 134:159].min(axis=2).mean() > 80
            or _field(scene, _SETUP_PERIOD, _PERIOD, minimum)
            or _field(scene, _SETUP_LEVEL, r'难度0[1-4]', minimum)):
        return pages._unknown('unverified_apocalyptic_candidate_picker')
    badges = []
    for token in scene.tokens:
        value = _text(token)
        if not value.startswith('队伍') or not pages._overlaps(token.box, _PICKER_BADGES):
            continue
        if (not pages._inside(token.box, _PICKER_BADGES) or token.score < minimum
                or not re.fullmatch(r'队伍[12]', value)):
            return pages._unknown('unverified_apocalyptic_candidate_badge')
        badges.append(dict(_proof(Token(value, token.score, token.box)), node=int(value[-1])))
    anchors = dict(heading=heading, list_tab=listed, preset_tab=preset, role_detail=details,
                   challenge_caption=button, **headers)
    return _observation('candidate_picker', anchors, '前往挑战', button,
                        active_node=active[0], rails=list(rails), badges=badges, period=None)


def _node_setup(scene, title, heading, words, minimum):
    headers = _setup_headers(scene, minimum)
    period = _field(scene, _SETUP_PERIOD, _PERIOD, minimum)
    if not headers or not period or _foreign_caption(scene, '前往挑战', _SETUP_BUTTON):
        return pages._unknown('incomplete_apocalyptic_node_setup')
    anchors = dict(title=title, heading=heading, period=period, **headers)
    level = _field(scene, _SETUP_LEVEL, r'难度0[1-4]', minimum)
    if level is not None and any(re.fullmatch(r'(?:难度)?0[1-4]|难度', _text(t))
                                 and pages._overlaps(t.box, _SETUP_LEVEL)
                                 and not pages._inside(t.box, _SETUP_LEVEL) for t in scene.tokens):
        level = None
    if level is not None:
        anchors['level'] = level
    button = _field(scene, _SETUP_BUTTON, '前往挑战', minimum)
    if any('角色详情' in word for word in words):
        details = _field(scene, _SETUP_ROLE_DETAIL, '角色详情', minimum)
        outside = _words_outside(scene, (_SETUP_ROLE_DETAIL,))
        if (not details or not button or abs(details.center[1] - button.center[1]) > .016
                or any('角色详情' in word for word in outside)):
            return pages._unknown('unverified_apocalyptic_setup_role_detail')
        anchors['role_detail'] = details
    nodes = [dict(node=index, boss=boss, label_box=list(token.box)) for index, boss, token in
             zip((1, 2), _BOSSES, (headers['node_one'], headers['node_two']))]
    return _observation('node_setup', anchors, '前往挑战', button,
                        level=int(level.text[-2:]) if level else None, period=_PERIOD, nodes=nodes,
                        selected_node=None, team_feedback='unknown', role_availability='unknown',
                        slot_feedback='unknown')


def observe(scene, confidence=.65):
    """Recognize observed preparation layouts without generating a target."""
    floor = confidence
    if type(confidence) in (int, float) and VETO_FLOOR < confidence <= 1:
        floor = VETO_FLOOR
        weak = getattr(scene, 'field_reads', {}).get(COUNTEREVIDENCE, ())
        if weak:
            scene = replace(scene, tokens=[*scene.tokens, *weak])
    clean = pages._clean(scene, floor, blockers=())
    if clean is None:
        return pages._unknown('invalid_or_stale_apocalyptic_capture')
    words = _words(clean.tokens)
    minimum = max(.85, confidence)
    mode = _field(clean, _PLAYED_MODE, '常规模式', minimum)
    change = _field(clean, _PLAYED_CHANGE, '更换编队', minimum)
    played = mode is not None and change is not None
    blockers = _PLAYED_BLOCKERS if played else _BLOCKERS
    dialog = _words(t for t in clean.tokens if pages._overlaps(t.box, _DIALOG_HEADER))
    subtitle_words = _words(t for t in clean.tokens if pages._overlaps(t.box, _SUBTITLE))
    has_subtitle = any(word in ('首领信息', '编队') for word in subtitle_words)
    locked = any(fragment in word for word in words for fragment in _LOCKED_WORDS)
    if '提示' in dialog or any(fragment in word for fragment in blockers for word in words):
        return pages._unknown('apocalyptic_other_mode_transition_or_dialog')
    if any('快速通关' in word for word in words) and (
            has_subtitle or locked or any('快速通关' in word for word in _words_outside(clean, _CARDS))):
        return pages._unknown('apocalyptic_quick_clear_overlay')
    title = _field(clean, _TITLE, '末日幻影', minimum)
    if played:
        if has_subtitle:
            return pages._unknown('conflicting_apocalyptic_subtitle')
        return _played_overview(clean, title, mode, change, words, minimum)
    if locked:
        return _locked_node_detail(clean, words, minimum)
    subtitle = _field(clean, _SUBTITLE, '首领信息|编队', minimum)
    if subtitle and subtitle.text == '编队' and not any('未解锁' in word for word in words):
        picker = _candidate_picker(clean, subtitle, words, minimum)
        if picker is not None:
            return picker
    if title is None:
        return pages._unknown('missing_apocalyptic_title')
    if subtitle is not None:
        if any('未解锁' in word for word in words):
            return pages._unknown('apocalyptic_lock_outside_lobby')
        if subtitle.text == '首领信息':
            if any('角色详情' in word for word in words):
                return pages._unknown('conflicting_apocalyptic_role_detail')
            return _boss_info(clean, title, subtitle, minimum)
        return _node_setup(clean, title, subtitle, words, minimum)
    if has_subtitle:
        return pages._unknown('unverified_apocalyptic_subtitle')
    if any('角色详情' in word for word in words):
        return pages._unknown('conflicting_apocalyptic_role_detail')
    return _lobby(clean, title, minimum)


def same_page(first, second):
    """The semantic anchors must agree and stay in the same screen positions."""
    if first.kind == 'unknown' or (first.kind, first.mode, first.level) != (second.kind, second.mode, second.level):
        return False
    a, b = first.basis['anchors'], second.basis['anchors']
    return a.keys() == b.keys() and all(
        a[name]['text'] == b[name]['text'] and pages._overlaps(a[name]['box'], b[name]['box'])
        for name in a)
