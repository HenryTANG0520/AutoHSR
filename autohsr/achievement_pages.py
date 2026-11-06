"""Read 4.6 achievement pages and visible reward controls without issuing input."""
import re
from dataclasses import dataclass

import numpy as np

from .challenge_pages import _inside, _overlaps
from .currency_wars_prepare import trusted
from .free_rewards import claim_enabled, reward_overlay
from .models import normalize
from .team_calibration_pages import calibration_overlay
from .workflows import TITLE


ACHIEVEMENT_CATEGORIES = frozenset({
    '我开拓者', '通往群星的轨道', '战意奔涌', '流光遗痕', '果壳中的宇宙',
    '不屈者的荣光', '瞬息欢愉', '与你同行的回忆', '众秘探奇',
})
_CAROUSEL = (.06, .56, .96, .71)
_SUMMARY = (.28, .81, .60, .93)
_MODAL = (.20, .16, .83, .83)
_BLOCKERS = ('确认', '确定', '取消', '获得物品', '请选择', '筛选条件', '请输入关键词', '点击空白处关闭')
_CATEGORY_HEADER = (.07, .09, .29, .16)
_CATEGORY_PROGRESS = (.07, .14, .29, .22)
_SEARCH_BUTTON = (.78, .88, .96, .97)
_ROW_CLAIM = (.83, .23, .96, .88)
_BULK_CLAIM = (.70, .83, .94, .96)
_PROGRESS = re.compile(r'成就进度([0-9]{1,5})/([0-9]{1,5})')
_ROW_PROGRESS = re.compile(r'[0-9]+/[0-9]+')
_ROW_STATES = ('领取', '已领取', '已完成', '未完成', '进行中')
_RECEIPT_TITLE = (.38, .07, .62, .17)
_RECEIPT_CATEGORIES = (.05, .16, .30, .79)
_RECEIPT_ROWS = (.13, .18, .38, .78)
_RECEIPT_TOTAL = (.37, .79, .56, .88)
_RECEIPT_CONFIRM = (.40, .89, .62, .97)


@dataclass(frozen=True)
class AchievementListObservation:
    category: str
    # False leaves the reward state unknown, including rows outside the viewport.
    visible_claim: bool


def _page_blocked(scene):
    return (calibration_overlay(scene) or reward_overlay(scene) or scene.has(_BLOCKERS, _MODAL, exact=True)
            or scene.has('开拓等级', (.55, .05, .99, .35)))


def _labels(scene, words, region):
    return [token for token in scene.tokens if _overlaps(token.box, region) and normalize(token.text) in words]


def _unique(tokens, region, minimum):
    if len(tokens) == 1 and tokens[0].score >= minimum and _inside(tokens[0].box, region):
        return tokens[0]
    return None


def achievement_overview(scene, confidence=.85):
    visible = trusted(scene, .65)
    if _page_blocked(visible):
        return False
    minimum = max(.85, confidence)
    for label, region in (('成就', TITLE), ('达成成就', _SUMMARY)):
        found = [token for token in visible.tokens if token.within(region) and normalize(token.text) == label]
        if len(found) != 1 or found[0].score < minimum:
            return False
    cards = sorted((token for token in visible.tokens if token.within(_CAROUSEL)
                    and normalize(token.text) in ACHIEVEMENT_CATEGORIES), key=lambda token: token.center[0])
    if (len({normalize(token.text) for token in cards}) != len(cards)
            or any(right.center[0] - left.center[0] < .055 for left, right in zip(cards, cards[1:]))):
        return False
    strong = [token for token in cards if token.score >= minimum]
    return len(strong) >= 3 and max(token.center[1] for token in strong) - min(token.center[1] for token in strong) <= .075


def achievement_bulk_claim_visible(scene, confidence=.85) -> bool:
    """Read a gold bulk-claim control on the independently recognized overview."""
    if not achievement_overview(scene, confidence):
        return False
    visible = trusted(scene, .65)
    # The leading 一 was dropped by RapidOCR on the public 4.6 pre-claim frame.
    buttons = _labels(visible, ('一键领取奖励', '键领取奖励'), _BULK_CLAIM)
    button = _unique(buttons, _BULK_CLAIM, max(.85, confidence))
    return button is not None and claim_enabled(visible, button) is True


def _unambiguous_row_claim(scene, token):
    x, y = token.center
    # State text inside one button-sized slot is counterevidence. Another row remains independent.
    slot = (x - .045, y - .020, x + .045, y + .020)
    state = [candidate for candidate in scene.tokens if _overlaps(candidate.box, slot)
             and ((word := normalize(candidate.text)) in _ROW_STATES or _ROW_PROGRESS.fullmatch(word))]
    return len(state) == 1 and state[0] is token and claim_enabled(scene, token) is True


def observe_achievement_list(scene, confidence=.85) -> AchievementListObservation | None:
    """Recognize the category view, with independent positive evidence of a visible claim."""
    visible = trusted(scene, .65)
    if _page_blocked(visible):
        return None
    minimum = max(.85, confidence)
    if (_unique(_labels(visible, ('成就',), TITLE), TITLE, minimum) is None
            or _unique(_labels(visible, ('搜索',), _SEARCH_BUTTON), _SEARCH_BUTTON, minimum) is None):
        return None
    categories = _labels(visible, ACHIEVEMENT_CATEGORIES, _CATEGORY_HEADER)
    progress = [token for token in visible.tokens if _overlaps(token.box, _CATEGORY_PROGRESS)
                and _PROGRESS.fullmatch(normalize(token.text))]
    heading = _unique(categories, _CATEGORY_HEADER, minimum)
    counter = _unique(progress, _CATEGORY_PROGRESS, minimum)
    if heading is None or counter is None:
        return None
    done, total = map(int, _PROGRESS.fullmatch(normalize(counter.text)).groups())
    if (total == 0 or done > total or counter.center[1] <= heading.center[1]
            or abs(counter.box[0] - heading.box[0]) > .03):
        return None
    claim = any(token.score >= minimum and _inside(token.box, _ROW_CLAIM)
                and _unambiguous_row_claim(visible, token) for token in _labels(visible, ('领取',), _ROW_CLAIM))
    return AchievementListObservation(heading.text, claim)


def _receipt_row_visible(scene, minimum, heading_bottom):
    image = scene.image
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        return False
    height, width = image.shape[:2]
    for token in scene.tokens:
        if token.score < minimum or token.box[1] <= heading_bottom or not _inside(token.box, _RECEIPT_ROWS):
            continue
        title = normalize(token.text)
        if (len(title) < 2 or title in ACHIEVEMENT_CATEGORIES or title in _BLOCKERS or title in _ROW_STATES
                or not any(character.isalpha() for character in title)):
            continue
        y = token.center[1]
        # The independent detail row has a light band continuing across the panel center.
        band = image[round((y - .012) * height):round((y + .012) * height), round(.55 * width):round(.74 * width)]
        if band.size and np.mean(np.all(band >= 195, axis=2)) >= .75:
            return True
    return False


def achievement_bulk_receipt_visible(scene, confidence=.85) -> bool:
    """Read the dedicated reward panel with at least one independently visible detail row."""
    visible = trusted(scene, .65)
    if _page_blocked(visible):
        return False
    minimum = max(.85, confidence)
    for text, region in (('成就奖励', _RECEIPT_TITLE), ('总计获得', _RECEIPT_TOTAL)):
        if _unique(_labels(visible, (text,), region), region, minimum) is None:
            return False
    confirm = _unique(_labels(visible, ('确认', '确定', '取消'), _RECEIPT_CONFIRM), _RECEIPT_CONFIRM, minimum)
    if confirm is None or normalize(confirm.text) != '确认':
        return False
    headings = sorted(_labels(visible, ACHIEVEMENT_CATEGORIES, _RECEIPT_CATEGORIES), key=lambda token: token.center[1])
    verified = [token for token in headings if token.score >= minimum and _inside(token.box, _RECEIPT_CATEGORIES)]
    if not verified or any(right.box[1] < left.box[3] for left, right in zip(headings, headings[1:])):
        return False
    return _receipt_row_visible(visible, minimum, verified[0].box[3])


def achievement_reward_panel_started(scene):
    return bool(_labels(trusted(scene, .65), ('成就奖励',), _RECEIPT_TITLE))


def observe_achievement_screen(scene, confidence):
    """Return a fixed page, optional category, and positive claim-control state."""
    overview = achievement_overview(scene, confidence)
    category = observe_achievement_list(scene, confidence)
    receipt = achievement_bulk_receipt_visible(scene, confidence)
    if (sum((overview, category is not None, receipt)) != 1
            or not receipt and achievement_reward_panel_started(scene)):
        return None
    if overview:
        return 'achievement_overview', None, 'bulk' if achievement_bulk_claim_visible(scene, confidence) else None
    if category is not None:
        return 'achievement_list', normalize(category.category), 'single' if category.visible_claim else None
    return 'achievement_receipt', None, None
