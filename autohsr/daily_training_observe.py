"""Anonymous task and milestone facts from the verified daily-training page."""

from datetime import date

from .currency_wars_prepare import trusted
from .daily_support import read_state
from .daily_synthesis import _task_game_day, task_target
from .daily_training_cards import TRAINING_CARD_VERSION, stable_cards, valid_cards
from .daily_training_rewards import _band, _blocked, _reached_points
from .free_rewards import reward_overlay
from .models import AutomationError


_SUPPORT_STATES = {'unknown', 'needed', 'completed', 'activity_full'}
_SYNTHESIS_STATES = {'unknown', 'available', 'activity_full'}
_FIELDS = {'game_day', 'activity', 'support_task', 'synthesis_task', 'milestones'}


def _read(workflow, scene, confidence):
    if _blocked(scene) or reward_overlay(scene):
        return None, 'unknown', 'unknown', None
    badge = workflow._icon(scene, 'daily_activity_badge', (.13, .23, .225, .37), threshold=.85)
    support, activity = read_state(scene, badge_verified=badge is not None, confidence=confidence)
    if activity is None:
        return None, 'unknown', 'unknown', None
    synthesis = 'activity_full' if activity == 500 else 'unknown'
    if activity < 500:
        # Require the complete card in both the raw and confidence-filtered views.
        target = task_target(scene)
        if target is not None and task_target(trusted(scene, confidence)) == target:
            synthesis = 'available'
    band = _band(workflow, scene, activity, confidence)
    milestones = None
    if band is not None and set(band[0]).union(band[1]) == set(_reached_points(activity)):
        milestones = dict(claimed=sorted(band[1]), claimable=sorted(band[0]))
    return activity, support, synthesis, milestones


def observe_training(workflow, scenes, confidence, *, client_version=None):
    try:
        first_day, second_day = (_task_game_day(scene) for scene in scenes)
    except AutomationError:
        return None
    if first_day != second_day:
        return None
    first, second = scenes
    first_activity, first_support, first_synthesis, first_milestones = _read(workflow, first, confidence)
    activity, support, synthesis, milestones = _read(workflow, second, confidence)
    if activity is None or activity != first_activity:
        return None
    result = dict(game_day=second_day, activity=activity,
                  support_task=support if support == first_support else 'unknown',
                  synthesis_task=synthesis if synthesis == first_synthesis else 'unknown',
                  milestones=milestones if milestones == first_milestones else None)
    if client_version == TRAINING_CARD_VERSION:
        cards = stable_cards(scenes, activity, confidence)
        if cards:
            result['visible_tasks'] = cards
    return result


def training_observation_receipt(navigation):
    if navigation.get('target') != 'daily_training' or navigation.get('page_verified') is not True:
        return None
    value = navigation.get('training_observation')
    if not isinstance(value, dict) or value.keys() not in (_FIELDS, _FIELDS | {'visible_tasks'}):
        return None
    day, activity = value['game_day'], value['activity']
    support, synthesis = value['support_task'], value['synthesis_task']
    if (type(day) is not str or type(activity) is not int or not 0 <= activity <= 500
            or type(support) is not str or support not in _SUPPORT_STATES
            or type(synthesis) is not str or synthesis not in _SYNTHESIS_STATES
            or (support == 'activity_full') != (activity == 500)
            or (synthesis == 'activity_full') != (activity == 500)):
        return None
    if 'visible_tasks' in value and (navigation.get('client_version') != TRAINING_CARD_VERSION
                                    or not valid_cards(value['visible_tasks'], activity)):
        return None
    try:
        if date.fromisoformat(day).isoformat() != day:
            return None
    except ValueError:
        return None
    milestones = value['milestones']
    if milestones is not None:
        if not isinstance(milestones, dict) or milestones.keys() != {'claimed', 'claimable'}:
            return None
        claimed, claimable = milestones['claimed'], milestones['claimable']
        if (not isinstance(claimed, list) or not isinstance(claimable, list)
                or any(type(points) is not int for points in claimed + claimable)
                or sorted(claimed + claimable) != _reached_points(activity)
                or claimed != sorted(claimed) or claimable != sorted(claimable)):
            return None
    return value


def training_condition_facts(receipt, client_version):
    """Project only facts from an already validated training receipt."""
    if 'game_day' not in receipt:
        return {}
    activity = receipt['activity']
    facts = dict(training_activity=activity)
    if activity == 500:
        facts['synthesis_needed'] = False
        facts['photo_needed'] = False
    elif client_version == TRAINING_CARD_VERSION and receipt.get('state') != 'unverified':
        cards = receipt.get('cards', receipt.get('visible_tasks', ()))
        card = next((item for item in cards if item['task'] == 'synthesis'), None)
        available = receipt.get('synthesis_task') == 'available'
        if card is not None:
            pending = card['state'] == 'pending'
            if pending or not available:
                facts['synthesis_needed'] = pending
        elif available:
            facts['synthesis_needed'] = True
        photo = next((item for item in cards if item['task'] == 'photo'), None)
        if photo is not None:
            facts['photo_needed'] = photo['state'] == 'pending'
    return facts
