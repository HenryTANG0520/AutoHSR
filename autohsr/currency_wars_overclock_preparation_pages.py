"""Read the calibrated screens between the A0 preview and the first preparation."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .models import AutomationError, Token, normalize


PHASES = ('a0_boss_preview', 'a0_first_plane', 'a0_environment',
          'a0_insurance_selected', 'a0_first_preparation')
ACTIONS = ('advance_a0_boss_preview', 'advance_a0_first_plane',
           'select_a0_initial_insurance', 'confirm_a0_initial_insurance')
_INSURANCE = '人身意外险'
_NAME = re.compile(r'(?=.*[\u4e00-\u9fff])[\u4e00-\u9fffa-z0-9-]{2,24}')
_BOSS_NEXT = (.74, .87, .84, .95)
_PLANE_CONTINUE = (.43, .86, .57, .93)
_CONFIRM = (.50, .87, .65, .95)
_WHITE_SELECTED = .5
_WHITE_DISABLED = .05
_SHOP = (.80, .86, .89, .95)
_INITIAL_HUD = ('1-1', '100', '3', '0/4', '0/3')
_BUTTON_ROIS = {ACTIONS[0]: _BOSS_NEXT, ACTIONS[1]: _PLANE_CONTINUE, ACTIONS[3]: _CONFIRM}
_BLOCKED_PAGES = frozenset({
    'shop', 'character', 'bench_full', 'star_selection', 'equipment_info',
    'equipment_selection', 'advanced_equipment_selection', 'expert_selection', 'hiring_selection',
    'token_selection', 'supply_selection', 'investment_selection', 'encounter_selection',
})
_MODAL_CONTROLS = (
    '收起', '收起商店', '商店收起', '返回备战界面', '请选择投资策略', '请选择强化角色',
    '奖励选择', '选择奖励', '请选择奖励', '领取奖励', '获得奖励', '点击空白处关闭',
)
_MODAL_TITLE = re.compile(r'简易武装箱|进阶武装箱|专家邀请函|(?:[1-5]费)?聘用书|好运令牌|'
                          r'请选择[0-9]+(?:件|个|名|项)(?:奖励|装备|角色)?')


@dataclass(frozen=True)
class PreparationPage:
    state: str
    key: tuple[str, ...] = ()


_UNVERIFIED = PreparationPage('unverified'), None
_CONFLICTING = PreparationPage('conflicting'), None
_BLOCKED = PreparationPage('blocked'), None
_OTHER = PreparationPage('other_page'), None


def _control(scene, label, roi, confidence):
    matches = [token for token in scene.tokens if normalize(token.text) == label]
    if len(matches) > 1:
        return None, _CONFLICTING
    if not matches or matches[0].score < confidence or not matches[0].within(roi):
        return None, _UNVERIFIED
    return matches[0], None


def _image(scene):
    import numpy as np

    image = scene.image
    return (isinstance(image, np.ndarray) and image.dtype == np.uint8 and image.ndim == 3
            and image.shape[2] == 3 and min(image.shape[:2]) >= 32)


def _white(image, roi, cutoff):
    import numpy as np

    from .currency_wars_deployment import _crop

    patch = _crop(image, roi)
    return np.mean(np.min(patch, axis=2) > cutoff) if patch.size else None


def _boss(scene, visible, confidence):
    from .currency_wars_overclock import START_FEEDBACK, preview_factions, read_overclock_start

    preview = read_overclock_start(scene, confidence)
    if preview.state != START_FEEDBACK:
        return _CONFLICTING if preview.state in ('boss_difficulty_conflicting', 'controls_conflicting') else _UNVERIFIED
    factions = preview_factions(scene, confidence)
    if not valid_preparation_key(PHASES[0], factions):
        return _UNVERIFIED
    if preview_factions(visible, 0) != factions or read_overclock_start(visible, 0).state != START_FEEDBACK:
        return _CONFLICTING
    target, failure = _control(visible, '下一步', _BOSS_NEXT, confidence)
    return failure if failure is not None else (PreparationPage(PHASES[0], tuple(factions)), target)


def _plane(scene, visible, confidence):
    from .currency_wars_flow import active_plane

    target, failure = _control(visible, '点击空白处继续', _PLANE_CONTINUE, confidence)
    if failure is not None:
        return failure
    if not _image(scene):
        return _UNVERIFIED
    try:
        number = active_plane(scene, confidence)
    except AutomationError:
        return _UNVERIFIED
    if number != 1:
        return _CONFLICTING
    return PreparationPage(PHASES[1], ('1',)), target


def _environment(scene, visible, confidence):
    from .currency_wars_environment import CENTERS, standard_environment_options

    target, failure = _control(visible, '确认', _CONFIRM, confidence)
    if failure is not None:
        return failure
    if not _image(scene):
        return _UNVERIFIED
    try:
        options = standard_environment_options(scene, confidence)
    except AutomationError:
        return _UNVERIFIED
    if tuple(option.slot for option in options) != (0, 1, 2):
        return _UNVERIFIED
    names = tuple(normalize(option.name.text) for option in options)
    if len(set(names)) != 3:
        return _CONFLICTING
    if not all(_NAME.fullmatch(name) for name in names):
        return _UNVERIFIED

    insurance = [token for token in visible.tokens if normalize(token.text) == _INSURANCE]
    insurers = [option for option in options if normalize(option.name.text) == _INSURANCE]
    if insurance != [option.name for option in insurers]:
        return _CONFLICTING
    borders = [_white(scene.image, (center - .123, .20, center - .121, .79), 200) for center in CENTERS]
    confirmation = _white(scene.image, (.50, .895, .62, .925), 180)
    if None in borders or confirmation is None:
        return _UNVERIFIED
    highlighted = [slot for slot, brightness in enumerate(borders) if brightness >= _WHITE_SELECTED]
    if len(highlighted) > 1:
        return _CONFLICTING

    choice = insurers[0] if insurers and insurers[0].kind == 'boss_supply' else None
    card = choice.name if choice is not None else None
    if not highlighted:
        if confirmation >= _WHITE_SELECTED:
            return _CONFLICTING
        # The initial view has three dark borders and a disabled confirmation.
        if max(borders) > _WHITE_DISABLED or confirmation > _WHITE_DISABLED:
            return _UNVERIFIED
        return PreparationPage(PHASES[2], (*names, 'none')), card

    slot = highlighted[0]
    key = (*names, str(slot))
    if names[slot] == _INSURANCE:
        if choice is None or confirmation < _WHITE_SELECTED:
            return _UNVERIFIED
        return PreparationPage(PHASES[3], key), target
    return PreparationPage(PHASES[2], key), card


def _hud(match):
    if match is None or match.page != 'preparation':
        return None
    return match.node, match.hp, match.level, match.experience, match.deployment


def _preparation(scene, visible, confidence):
    from .currency_wars_match import read_match

    _, failure = _control(visible, '商店', _SHOP, confidence)
    if failure is not None:
        return failure
    values = _hud(read_match(scene, confidence))
    if values is None or None in values:
        return _UNVERIFIED
    node, hp, level, experience, deployment = values
    key = (node, str(hp), str(level), '/'.join(map(str, experience)), '/'.join(map(str, deployment)))
    if key != _INITIAL_HUD or _hud(read_match(visible, 0)) != values:
        return _CONFLICTING
    return PreparationPage(PHASES[4], key), None


def _read(scene, confidence):
    from .currency_wars import observe
    from .currency_wars_overclock import ACTIVE_MATCH
    from .currency_wars_prepare import trusted
    from .currency_wars_standard import NAVIGATION_BLOCKERS

    visible = trusted(scene, 0)
    if (visible.has((*ACTIVE_MATCH, *NAVIGATION_BLOCKERS, '返回对局', '未完成对局', '对局尚未结算'))
            or visible.has(_MODAL_CONTROLS, exact=True)
            or visible.has('刷新', (.8, .4, .89, .49), exact=True)
            or any(token.center[1] < .19 and _MODAL_TITLE.fullmatch(normalize(token.text))
                   for token in visible.tokens)):
        return _BLOCKED

    kind = observe(scene, confidence).page_kind
    weak_kind = observe(visible, 0).page_kind
    if kind in _BLOCKED_PAGES or weak_kind in _BLOCKED_PAGES:
        return _BLOCKED
    headers = (
        visible.has('本场对局首领', (.72, .66, .85, .74), exact=True),
        visible.has('点击空白处继续', _PLANE_CONTINUE, exact=True),
        visible.has('投资环境', (.4, .01, .6, .12), exact=True),
        visible.has('备战阶段', (.10, .01, .30, .09), exact=True),
    )
    if sum(headers) > 1 or (any(headers) and
            visible.has(('开始对局', '进入超频博弈', '进入标准博弈'), exact=True)):
        return _CONFLICTING
    if kind == 'boss_preview':
        return _boss(scene, visible, confidence)
    if kind == 'plane_map':
        return _plane(scene, visible, confidence)
    if kind == 'environment':
        return _environment(scene, visible, confidence)
    if kind == 'preparation':
        return _preparation(scene, visible, confidence)
    return _UNVERIFIED if kind == 'unknown' else _OTHER


def read_preparation(scene, confidence):
    return _read(scene, confidence)[0]


def valid_preparation_key(phase, key):
    """Apply the same phase key rules when reading a saved receipt."""
    if not isinstance(key, (tuple, list)) or not all(isinstance(item, str) for item in key):
        return False
    if phase == PHASES[0]:
        return len(key) == 3 and all(
            0 < len(name) <= 40 and name == normalize(name)
            and all(ord(char) >= 32 and char not in '「」『』' for char in name) for name in key)
    if phase == PHASES[1]:
        return tuple(key) == ('1',)
    if phase == PHASES[4]:
        return tuple(key) == _INITIAL_HUD
    if (phase not in PHASES[2:4] or len(key) != 4
            or len(set(key[:3])) != 3 or not all(_NAME.fullmatch(name) for name in key[:3])):
        return False
    if key[-1] == 'none':
        return phase == PHASES[2]
    return key[-1] in ('0', '1', '2') and (key[int(key[-1])] == _INSURANCE) == (phase == PHASES[3])


def preparation_target_box(action, box, *, slot=None):
    """Check the recorded geometry, with the insurance column when known."""
    if (action not in ACTIONS or not isinstance(box, (tuple, list)) or len(box) != 4
            or any(type(edge) not in (int, float) or not 0 <= edge <= 1 for edge in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        return False
    token = Token('', 1., tuple(box))
    if action != ACTIONS[2]:
        return token.within(_BUTTON_ROIS[action])

    from .currency_wars_environment import CENTERS

    if slot is not None and (type(slot) is not int or not 0 <= slot < len(CENTERS)):
        return False
    centers = CENTERS if slot is None else (CENTERS[slot],)
    return .34 <= token.center[1] <= .38 and any(
        center - .115 <= box[0] < box[2] <= center + .115 for center in centers)


def preparation_target(scene, action, confidence):
    if action not in ACTIONS:
        raise AutomationError('首次备战未授权此动作。')
    page, target = _read(scene, confidence)
    if (page.state != PHASES[ACTIONS.index(action)] or target is None
            or not preparation_target_box(action, target.box)):
        raise AutomationError('首次备战的当前阶段、目标或选中状态未核实。')
    return target
