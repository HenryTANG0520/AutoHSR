"""Identify a settled horizontal daily-training viewport before and after scrolling."""

from collections import Counter
from dataclasses import dataclass
from datetime import date

import cv2
import numpy as np

from .daily_synthesis import _task_game_day
from .daily_training_cards import TRAINING_CARD_VERSION, _card, valid_cards
from .daily_training_rewards import _blocked
from .free_rewards import reward_overlay
from .models import AutomationError, Token


MAX_SCROLLS = 4
SCAN_ACTION = 'scroll_daily_training'
_SIZE = (640, 360)
_LEFT, _RIGHT = 92, 552
_STATES = ('no_movement', 'limit', 'unverified')


@dataclass(frozen=True)
class Viewport:
    activity: int
    game_day: str
    cards: tuple
    centers: tuple
    right_clipped: bool

    @property
    def anchor(self):
        x = self.centers[len(self.centers) // 2]
        return Token('每日实训卡片区', 1., (x - .01, .54, x + .01, .58))


def _columns(image):
    view = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), _SIZE, interpolation=cv2.INTER_AREA)
    # The pale card bodies have dark gutters. Use the upper body to avoid
    # the activity graphics, the reward buttons and the decorated bottom edge.
    profile = np.median(view[153:215, _LEFT:_RIGHT], axis=0)
    edges = np.flatnonzero(np.diff(np.r_[False, profile >= 235, False])) + _LEFT
    return [(int(left), int(right)) for left, right in zip(edges[::2], edges[1::2])]


def visible_viewport(workflow, scene, confidence):
    if _blocked(scene) or reward_overlay(scene):
        return None
    activity = workflow._activity(scene)
    if activity is None:
        return None
    try:
        day = _task_game_day(scene)
    except AutomationError:
        return None
    runs = _columns(scene.image)
    columns = [(left, right) for left, right in runs if 80 <= right-left <= 100]
    if not 1 <= len(columns) <= 4:
        return None
    width = _SIZE[0]
    positions = tuple((left + right) / (2 * width) for left, right in columns)
    if any(not .160 <= b - a <= .189 for a, b in zip(positions, positions[1:])):
        return None
    cards = [_card(scene, (max(_LEFT, left-5)/width, min(_RIGHT, right+5)/width), activity, confidence)
             for left, right in columns]
    counts = Counter((card['task'], card['points']) for card in cards if card is not None)
    selected = [(x, card) for x, card in zip(positions, cards)
                if card is not None and counts[card['task'], card['points']] == 1]
    if not selected:
        return None
    right_clipped = any(right == _RIGHT and 8 <= right-left < 80 for left, right in runs)
    return Viewport(activity, day, tuple(card for _, card in selected), tuple(x for x, _ in selected), right_clipped)


def stable_viewport(workflow, scenes, confidence):
    first, second = (visible_viewport(workflow, scene, confidence) for scene in scenes)
    if (first is None or second is None or first.cards != second.cards
            or first.activity != second.activity or first.game_day != second.game_day
            or first.right_clipped != second.right_clipped
            or any(abs(a - b) > .006 for a, b in zip(first.centers, second.centers))):
        return None
    return second


def _key(card):
    return card['task'], card['points']


def advanced(before, after):
    old = {_key(card): x for card, x in zip(before.cards, before.centers)}
    new = {_key(card): x for card, x in zip(after.cards, after.centers)}
    offsets = [old[key] - new[key] for key in old.keys() & new.keys()]
    return bool(offsets) and min(offsets) > .012 and max(offsets) - min(offsets) <= .018


def same_view(first, second):
    return (first.cards == second.cards and first.right_clipped == second.right_clipped
            and all(abs(a - b) <= .012 for a, b in zip(first.centers, second.centers)))


def combined_cards(views):
    by_task = {}
    for view in views:
        for card in view.cards:
            variants = by_task.setdefault(_key(card), [])
            if card not in variants:
                variants.append(card)
    return [variants[0] for variants in by_task.values() if len(variants) == 1]


def scan_receipt(navigation):
    from .task_workflow import TRAINING_SCAN_PAGE

    value = navigation.get('training_scan')
    if (navigation.get('target') != TRAINING_SCAN_PAGE or navigation.get('page_verified') is not True
            or navigation.get('client_version') != TRAINING_CARD_VERSION
            or not isinstance(value, dict) or value.keys() not in (
                {'state', 'views', 'cards', 'activity'}, {'state', 'views', 'cards', 'activity', 'game_day'})):
        return None
    if 'game_day' in value:
        day = value['game_day']
        try:
            if type(day) is not str or date.fromisoformat(day).isoformat() != day:
                return None
        except ValueError:
            return None
    state, views, cards, activity = (value[key] for key in ('state', 'views', 'cards', 'activity'))
    if (state not in _STATES or type(views) is not int or not 0 <= views <= MAX_SCROLLS + 1
            or type(activity) is not int or not 0 <= activity <= 500
            or (views == 0 and state != 'unverified')
            or (state == 'limit') != (views == MAX_SCROLLS + 1)
            or not (cards == [] or valid_cards(cards, activity, limit=4 * views))):
        return None
    actions = navigation.get('actions')
    if not isinstance(actions, list) or any(not isinstance(action, dict) for action in actions):
        return None
    scrolls = [action for action in actions if action.get('action') == SCAN_ACTION]
    if (len(scrolls) != min(views, MAX_SCROLLS)
            or any((row.get('input_status'), row.get('destination_status'), row.get('destination_page'))
                   != ('sent', 'verified', 'daily_training') for row in scrolls)):
        return None
    return value
