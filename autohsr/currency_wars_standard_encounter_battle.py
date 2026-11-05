"""Start one verified encounter node through the existing standard battle entry."""
from __future__ import annotations

import re

from . import currency_wars_encounter as reader
from .currency_wars import observe
from .currency_wars_match import read_match
from .currency_wars_node import battle_node, result_nodes
from .currency_wars_pages import RESULT_NODE_REGION
from .currency_wars_prepare import trusted
from .currency_wars_standard_encounter import (
    _frame, _node_conflict, _pair, _scope, _source, arrival_evidence,
    overlay_visible, record_start, resolve_sources, same_account,
)
from .models import AutomationError, normalize


START = 'start_standard_node'
CLOSE = 'close_standard_arrival_shop'
BINDING = 'encounter_successor'
_CLOSE_EXPECTED = 'standard_arrival_shop_closed'
_START_EXPECTED = 'standard_node_entered'
_REASON = '遭遇出战缺少同次运行、原到达或收店回执，保留当前节点。'
_TRANSITION = ('战斗阶段', '战斗开始', '遭遇强敌来袭', '强敌来袭')
_NODE = re.compile(r'[1-3]-[1-9][0-9]?')
_REGULAR = ('战斗', '奖励', '首领')


def _preparation(scene, node, confidence):
    if overlay_visible(scene, confidence) or _node_conflict(scene, node, confidence):
        return None
    detect = getattr(reader, 'encounter_node_visible', None)
    clean = trusted(scene, min(.65, confidence))
    if (detect and detect(scene, confidence) is False
            or clean.has(_REGULAR, (.28, .07, .73, .105), exact=True)):
        return None
    state = read_match(scene, confidence)
    if (state is None or state.page != 'preparation' or state.node != node
            or not state.hp or state.gold is None or not state.level or state.deployment is None):
        return None
    return state


def _closed_shop(action, confirmed, attempt, scope):
    arrival = confirmed['feedback']
    feedback = action.get('feedback', {})
    binding = action.get(BINDING, {})
    deployment = feedback.get('deployment')
    if (action.get('id') != confirmed['id']+1 or action.get('action') != CLOSE
            or action.get('expected') != _CLOSE_EXPECTED or action.get('status') != 'verified'
            or action.get('input_epoch') != scope['input_epoch']
            or binding.get('arrival_action_id') != confirmed['id']
            or action.get('target') != [arrival['node'], arrival['gold'], arrival['level'],
                                        attempt['node'], attempt['start_action_id']]
            or feedback.get('page_kind') != 'preparation'
            or (feedback.get('node'), feedback.get('gold'), feedback.get('level'))
            != (arrival['node'], arrival['gold'], arrival['level'])
            or type(feedback.get('hp')) is not int or not 1 <= feedback['hp'] <= 100
            or not isinstance(deployment, list) or len(deployment) != 2
            or any(type(value) is not int for value in deployment)
            or not 0 <= deployment[0] <= deployment[1] <= 20):
        raise AutomationError(_REASON)
    before = binding['before']
    if before['captured_at'] < confirmed['encounter_frames'][-1]['captured_at']:
        raise AutomationError(_REASON)
    return _source(before, scope, action['before']), *_pair(action, scope, before)


def _history(session, node, *, closing=False, observing=False):
    history = session.get('node_history', [])
    attempt = history[-1] if history else {}
    stage = attempt.get('encounter', {})
    if stage.get('expected_node') != node:
        return None
    try:
        scope = stage['scope']
        run = session['account_verified_run'] if observing else scope['run_dir']
        epoch = session['account_verified_epoch'] if observing else scope['input_epoch']
        if (attempt.get('status') != 'advanced' or
                _scope(session, run, epoch) != dict(scope, run_dir=run, input_epoch=epoch)):
            raise AutomationError(_REASON)
        confirmed, refs = arrival_evidence(session, attempt)
        tail = session['actions'][confirmed['id']+1:]
        if any(action.get('status') != 'verified' or action.get('input_epoch') != scope['input_epoch']
               or action.get('action') in (START, 'continue_standard_node', 'advance_standard_next_plane')
               for action in tail):
            raise AutomationError(_REASON)
        if closing:
            if confirmed['feedback']['page_kind'] != 'shop' or tail:
                raise AutomationError(_REASON)
            latest = confirmed
        elif confirmed['feedback']['page_kind'] == 'shop':
            if not tail:
                raise AutomationError(_REASON)
            latest = tail[0]
            refs += _closed_shop(latest, confirmed, attempt, scope)
        else:
            latest = confirmed
        return scope, confirmed, latest, refs
    except (IndexError, KeyError, TypeError, ValueError, AttributeError) as error:
        raise AutomationError(_REASON) from error


def proposal(scene, session, state, confidence):
    from .currency_wars_node import _start_target
    from .currency_wars_standard_flow import StandardAction

    source = _history(session, state.node)
    if source is None:
        return None
    _, confirmed, _, _ = source
    if _preparation(scene, state.node, confidence) != state or not same_account(scene, session, confidence):
        raise AutomationError('遭遇备战页、同节点类型或账号发生冲突，未发送出战。')
    target = _start_target(scene, confidence, encounter=True)
    return StandardAction(START, _START_EXPECTED, target,
                          payload=(state.node, state.gold, state.hp, state.level),
                          encounter_arrival=confirmed['id'])


def _bound_origin(session, choice, run_dir, epoch):
    current = session['actions'][-1]
    prior = dict(session, actions=session['actions'][:-1])
    source = _history(prior, choice.payload[0], closing=choice.intent == CLOSE)
    if source is None:
        raise AutomationError(_REASON)
    scope, confirmed, latest, refs = source
    if (scope['run_dir'] != str(run_dir) or scope['input_epoch'] != epoch
            or current.get('input_epoch') != epoch or confirmed['id'] != choice.encounter_arrival
            or current.get('status') != 'pending' or current.get('action') != choice.intent
            or current.get('expected') != choice.expected or current.get('target') != list(choice.payload)):
        raise AutomationError(_REASON)
    return current, scope, latest, refs


def bind_input(session, choice, scene, run_dir, epoch):
    current, scope, latest, _ = _bound_origin(session, choice, run_dir, epoch)
    if scene.captured_at < latest['encounter_frames'][-1]['captured_at']:
        raise AutomationError(_REASON)
    current[BINDING] = dict(arrival_action_id=choice.encounter_arrival,
                            before=_frame(scene, current['before'], scope))


def dispatch_sources(session, choice, run_dir, epoch, runs_root):
    try:
        current, scope, latest, refs = _bound_origin(session, choice, run_dir, epoch)
        binding = current[BINDING]
        if (binding['arrival_action_id'] != choice.encounter_arrival
                or binding['before']['captured_at'] < latest['encounter_frames'][-1]['captured_at']):
            raise AutomationError(_REASON)
        if (choice.intent == START and
                (session['node_attempt'].get('status') != 'start_pending'
                 or session['node_attempt'].get('node') != choice.payload[0]
                 or session['node_attempt'].get('start_action_id') != current['id'])):
            raise AutomationError(_REASON)
        ref = _source(binding['before'], scope, current['before'])
        return resolve_sources((*refs, ref), run_dir, runs_root)
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        raise AutomationError(_REASON) from error


def entry_stamp(scene, node, confidence):
    """Transition screens supply no proof of entry, even with the right HUD number."""
    kind = observe(scene, confidence).page_kind
    clean = trusted(scene, min(.65, confidence))
    if (overlay_visible(scene, confidence, page_kind=kind) or clean.has(_TRANSITION, (.22, .15, .80, .78), exact=True)
            or clean.has('备战阶段', (.1, .01, .3, .09), exact=True)
            or clean.has('出战', (.9, .65, 1, .75), exact=True)):
        return None
    if kind == 'battle':
        visible = battle_node(scene, confidence)
        alternatives = {normalize(token.text) for token in clean.tokens
                        if token.within((.28, 0, .43, .05)) and _NODE.fullmatch(normalize(token.text))}
        if alternatives - {node} or visible is not None and visible != node:
            raise AutomationError('遭遇出战后读到其他战斗节点，保留原动作待核对。')
        if visible == node:
            return dict(page_kind=kind, node=node)
    elif kind in ('node_result', 'node_loss', 'match_defeat', 'final_victory'):
        if kind == 'final_victory':
            raise AutomationError('遭遇出战反馈与终局首领结算冲突，保留原动作待核对。')
        numbers = result_nodes(scene, min(.65, confidence))
        ordinary = {node + label for label in _REGULAR}
        conflicting_type = any(token.within(RESULT_NODE_REGION) and normalize(token.text) in ordinary
                               for token in clean.tokens)
        if numbers - {node} or conflicting_type:
            raise AutomationError('遭遇出战的结算节点或类型发生冲突，保留原动作待核对。')
        from .currency_wars_standard_node import entry_feedback, read_survived_loss
        if entry_feedback(scene, node, confidence):
            stamp = dict(page_kind=kind, node=node)
            if kind == 'node_loss':
                stamp['hp'] = read_survived_loss(scene, confidence)[1]
            return stamp
    return None


def feedback(choice, scene, confidence):
    node = choice.payload[0]
    if choice.intent == START:
        return entry_stamp(scene, node, confidence)
    state = _preparation(scene, node, confidence)
    if state and (state.node, state.gold, state.level) == choice.payload[:3]:
        return dict(page_kind='preparation', node=state.node, gold=state.gold,
                    level=state.level, hp=state.hp, deployment=list(state.deployment))
    return None


def complete(c, session, action, choice, after, scope):
    prior = dict(session, actions=session['actions'][:-1])
    source = _history(prior, choice.payload[0], closing=choice.intent == CLOSE)
    if source is None or source[0] != scope or source[1]['id'] != choice.encounter_arrival:
        raise AutomationError(_REASON)
    if choice.intent == CLOSE:
        _closed_shop(action, source[1], prior['node_history'][-1], scope)
    else:
        _pair(action, scope, action[BINDING]['before'])
        session['node_attempt']['status'] = 'observing'
        record_start(session, action, after, 'after', c.report.run_dir,
                     c.runner.input_epoch, c.settings.ocr_confidence)
    session.update(action_status='transition_verified', page_kind=action['feedback']['page_kind'])


def require_started(session, action):
    try:
        prior = dict(session, actions=session['actions'][:action['id']])
        source = _history(prior, action['target'][0], observing=True)
        if (source is None or action['action'] != START or action['expected'] != _START_EXPECTED
                or action[BINDING]['arrival_action_id'] != source[1]['id']
                or action['input_epoch'] != source[0]['input_epoch']
                or action['feedback']['page_kind'] not in ('battle', 'node_result', 'node_loss', 'match_defeat')
                or action['feedback']['node'] != action['target'][0]):
            raise AutomationError(_REASON)
        before = action[BINDING]['before']
        _source(before, source[0], action['before'])
        _pair(action, source[0], before)
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise AutomationError(_REASON) from error
