"""Read the first A0 node's battle and result feedback without sending input."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .currency_wars_auto import read_auto
from .currency_wars_match import read_match
from .currency_wars_node_ocr import BATTLE_FIELDS, NODE_PATTERN, bounded_battle_node
from .currency_wars_pages import RESULT_NODE_REGION, RESULT_NODE_TEXT, classify_page
from .currency_wars_prepare import trusted
from .models import ROI, normalize


CONTINUE_REGION = (.4, .79, .6, .86)
_TITLE_REGION = (.4, .17, .6, .25)
_LIFE_REGION = (.3, .43, .5, .5)
_LIFE = re.compile(r'小队生命值([0-9]{1,3})')
_FUSED_REWARD = re.compile(rf'({NODE_PATTERN})m奖励')
_DEFEAT = ('挑战结束', '挑战失败', '对局失败', '对局未完成', '前往结算')


@dataclass(frozen=True)
class FirstNodeFeedback:
    state: str
    node: str | None = None
    hp: int | None = None
    target: ROI | None = None
    auto_state: str = 'unknown'


_UNREADABLE = FirstNodeFeedback('unreadable')
_CONFLICTING = FirstNodeFeedback('conflicting')
_UNEXPECTED = FirstNodeFeedback('unexpected')


def _inside(box, region):
    return (len(box) == 4 and region[0] <= box[0] < box[2] <= region[2]
            and region[1] <= box[1] < box[3] <= region[3])


def _victory(visible, confidence, titles, buttons):
    numbers, trusted_numbers = set(), set()
    for token in visible.tokens:
        if not token.within(RESULT_NODE_REGION):
            continue
        value = normalize(token.text)
        exact = RESULT_NODE_TEXT.fullmatch(value)
        hint = exact or _FUSED_REWARD.fullmatch(value)
        if hint:
            numbers.add(hint[1])
        # In the reward layout the adjacent icon can appear as M in OCR.
        # That row can disagree with an independent read, but cannot prove it.
        if exact and token.score >= confidence:
            trusted_numbers.add(exact[1])
    if len(numbers) > 1:
        return _CONFLICTING
    if not trusted_numbers:
        return _UNREADABLE
    node = next(iter(trusted_numbers))
    if node != '1-1':
        return FirstNodeFeedback('unexpected', node=node)

    lives = [token for token in visible.tokens if token.within(_LIFE_REGION)
             and normalize(token.text).startswith('小队生命值')]
    if len(titles) > 1 or len(lives) > 1 or len(buttons) > 1:
        return _CONFLICTING
    if not (titles and lives and buttons and min(titles[0].score, lives[0].score, buttons[0].score) >= confidence
            and _inside(titles[0].box, _TITLE_REGION) and _inside(buttons[0].box, CONTINUE_REGION)):
        return _UNREADABLE
    life = _LIFE.fullmatch(normalize(lives[0].text))
    if life is None:
        return _UNREADABLE
    hp = int(life[1])
    if not 1 <= hp <= 100:
        return _CONFLICTING
    return FirstNodeFeedback('victory', node, hp, buttons[0].box)


def _battle(scene, visible, confidence):
    # Keep the native and thresholded field reads as the only positive proof.
    # An exact screen read within their crop may contradict that proof. A fused
    # OCR row extending into the percentage field cannot supply a node.
    numbers, boxes = set(), set()
    for name, region in BATTLE_FIELDS.items():
        for token in scene.field_reads.get(name, ()):
            if token is None or not _inside(token.box, region) or not 0 <= token.score <= 1:
                continue
            boxes.add(token.box)
            value = normalize(token.text)
            if re.fullmatch(NODE_PATTERN, value):
                numbers.add(value)
    numbers.update(normalize(token.text) for token in visible.tokens
                   if re.fullmatch(NODE_PATTERN, normalize(token.text))
                   and any(_inside(token.box, box) for box in boxes))
    if len(numbers) > 1:
        return _CONFLICTING
    _, node = bounded_battle_node(scene, confidence)
    if node is None:
        return _UNREADABLE
    if node != '1-1':
        return FirstNodeFeedback('unexpected', node=node)
    return FirstNodeFeedback('battle', node, auto_state=read_auto(scene, confidence).state)


def read_first_node_feedback(scene, confidence):
    """Read one frame. Its Continue target is evidence for the report."""
    from .currency_wars_overclock import ACTIVE_MATCH
    from .currency_wars_standard import NAVIGATION_BLOCKERS

    visible = trusted(scene, 0)
    if visible.has(tuple(label for label in ACTIVE_MATCH if label != '继续挑战') + NAVIGATION_BLOCKERS
                   + ('返回对局', '未完成对局', '对局尚未结算')):
        return _UNEXPECTED
    titles = [token for token in visible.tokens if normalize(token.text) == '挑战成功']
    buttons = [token for token in visible.tokens if normalize(token.text) == '继续挑战']
    if visible.has(_DEFEAT, exact=True):
        return _CONFLICTING if titles else _UNEXPECTED
    if not titles and any(not token.within(CONTINUE_REGION) for token in buttons):
        return _UNEXPECTED

    page = classify_page(trusted(scene, confidence).tokens)
    if page == 'unknown':
        return _UNREADABLE
    if classify_page(visible.tokens) != page:
        return _CONFLICTING
    if page == 'node_result':
        return _victory(visible, confidence, titles, buttons)
    if page == 'battle':
        return _battle(scene, visible, confidence)
    if page == 'preparation':
        match = read_match(scene, confidence)
        if match.node is None:
            return _UNREADABLE
        all_match = read_match(visible, 0)
        if (match.node, match.hp) != (all_match.node, all_match.hp):
            return _CONFLICTING
        if match.node != '1-1':
            return FirstNodeFeedback('unexpected', node=match.node)
        return FirstNodeFeedback('preparation', match.node, match.hp)
    return _UNEXPECTED
