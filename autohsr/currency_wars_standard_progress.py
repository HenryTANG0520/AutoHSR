"""Advance proven node results and terminal pages without replaying inputs."""
from __future__ import annotations

import math
import re

from .currency_wars import observe
from .currency_wars_ending import ENDING_STEPS, ending_target
from .currency_wars_equipment_mode import STANDARD_BOSSES
from .currency_wars_flow import active_plane, continue_target, plane_target
from .currency_wars_intro import boss_target
from .currency_wars_match import read_match
from .currency_wars_navigation import unique
from .currency_wars_node import result_node
from .currency_wars_prepare import trusted
from .currency_wars_standard_node import read_survived_loss, survived_loss_receipt
from .models import AutomationError, normalize


BOSS_INTRO_ACTION = 'advance_standard_boss_intro'
BOSS_INTRO_RETURN = 'standard_boss_intro_closed'
_BOSS_DETAIL = re.compile(r'等级[1-9][0-9]{0,2}.{2,40}')
_PROGRESS_INPUTS = frozenset(('continue_standard_node', 'advance_standard_next_plane',
                              'close_standard_arrival_shop', BOSS_INTRO_ACTION)) | {
                                  f'settle_standard_{page}' for page in ENDING_STEPS}


def progress_input_scope(intent, current, saved):
    """Require the same durable node and settlement evidence before dispatch."""
    from .currency_wars_defeat import INTENTS as DEFEAT_INPUTS
    from .currency_wars_standard_sale import same_target

    if intent not in _PROGRESS_INPUTS and intent not in DEFEAT_INPUTS:
        return False
    fields = ('node_attempt', 'status', 'start_verified', 'match_victory_observed',
              'victory_start_action_id', 'match_defeat_observed', 'defeat_start_action_id')
    reason = '节点推进的出战或结算来源与落盘记录不一致，未发送输入。'
    try:
        live, durable = current['actions'], saved['actions']
        start = current['node_attempt']['start_action_id']
        if (type(start) is not int or not 0 <= start < len(live)-1 or len(live) != len(durable)
                or not same_target([current.get(key) for key in fields], [saved.get(key) for key in fields])
                or not same_target(live[start], durable[start])
                or not same_target(live[-5:], durable[-5:])):
            raise AutomationError(reason)
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise AutomationError(reason) from error
    return True


def verified_attempt(session, *, allow_loss=False):
    attempt = session.get('node_attempt', {})
    node, index = attempt.get('node'), attempt.get('start_action_id')
    actions = session.get('actions', [])
    if (session.get('status') != 'active' or not session.get('start_verified')
            or not isinstance(node, str) or not re.fullmatch(r'[1-3]-[1-9][0-9]?', node)
            or attempt.get('status') not in ('verified', 'intro_pending', 'advanced')
            or not attempt.get('result') or type(index) is not int or not 0 <= index < len(actions)
            or actions[index].get('action') != 'start_standard_node'
            or actions[index].get('status') != 'verified'
            or not actions[index].get('target') or actions[index]['target'][0] != node
            or (attempt.get('node_verified') is not True
                and not (allow_loss and survived_loss_receipt(attempt, actions[index])))):
        raise AutomationError('节点推进缺少本局已核实出战与对应结果。')
    return attempt


def _history(session, intent, expected, payload):
    actions = session.get('actions', [])
    if actions and actions[-1].get('status') == 'pending':
        pending = actions[-1]
        if (pending.get('action'), pending.get('expected'), pending.get('target')) != (intent, expected, list(payload)):
            raise AutomationError('已有其他待核对动作，未推进节点。')
        actions = actions[:-1]  # Re-derive only this exact persisted proposal.
    if (not actions or any(a.get('status') != 'verified' for a in actions)
            or any(a.get('action') == intent and a.get('target') == list(payload) for a in actions)):
        raise AutomationError('节点动作已有提交或缺少已核实来源，未重复输入。')
    return actions


def boss_destination(node):
    plane, number = map(int, node.split('-'))
    following = f'{plane}-{number+1}'
    return following if following in STANDARD_BOSSES else None


def _intro_feedback(scene, destination, confidence):
    if destination is None:
        return None
    try:
        boss_target(scene, confidence)
    except AutomationError:
        return None
    details = {normalize(t.text) for t in trusted(scene, confidence).tokens
               if t.within((.45, .43, .85, .51)) and _BOSS_DETAIL.fullmatch(normalize(t.text))}
    if len(details) == 1:
        return dict(page_kind='boss_intro', expected_node=destination, enemy=details.pop())
    return None


def _paired_progress_evidence(action):
    frames = action.get('progress_frames')
    if not isinstance(frames, list) or len(frames) != 2:
        return False
    for frame in frames:
        if (not isinstance(frame, dict) or not isinstance(frame.get('evidence'), str) or not frame['evidence']
                or type(frame.get('captured_at')) not in (int, float) or not math.isfinite(frame['captured_at'])
                or type(frame.get('input_epoch')) is not int or frame['input_epoch'] != action.get('input_epoch')):
            return False
    first, last = frames
    return (first['captured_at'] < last['captured_at']
            and first['evidence'] != last['evidence'] == action.get('after'))


def _intro_source(actions, attempt):
    start, index = attempt['start_action_id'], attempt.get('continue_action_id')
    node = attempt['node']
    destination = boss_destination(node)
    reason = '强敌介绍缺少相邻首领的原出战与继续挑战证据。'
    if destination is None or type(index) is not int or index != start+1 or index >= len(actions):
        raise AutomationError(reason)
    source = actions[start]
    target = source.get('target')
    if (source.get('id') != start or source.get('action') != 'start_standard_node'
            or source.get('expected') != 'standard_node_entered' or source.get('status') != 'verified'
            or not source.get('before') or not source.get('after')
            or not isinstance(target, list) or len(target) != 4 or target[0] != node
            or (attempt.get('result_kind') != 'node_result' and not survived_loss_receipt(attempt, source))
            or not attempt.get('result')):
        raise AutomationError(reason)
    action = actions[index]
    feedback = action.get('feedback', {})
    if (action.get('id') != index or action.get('action') != 'continue_standard_node'
            or action.get('expected') != 'standard_node_advanced' or action.get('status') != 'verified'
            or action.get('target') != [node, start] or not action.get('before')
            or not isinstance(feedback, dict) or feedback.get('page_kind') != 'boss_intro'
            or feedback.get('expected_node') != destination or not isinstance(feedback.get('enemy'), str)
            or not _BOSS_DETAIL.fullmatch(feedback['enemy']) or not _paired_progress_evidence(action)):
        raise AutomationError(reason)
    return action


def boss_arrival_receipt(actions, attempt):
    """The intro is an intermediate page, so only its verified return advances the node."""
    intro = _intro_source(actions, attempt)
    index = attempt.get('arrival_action_id')
    node = intro['feedback']['expected_node']
    reason = '强敌介绍关闭缺少原介绍与实际相邻首领的到达回执。'
    if type(index) is not int or index != intro['id']+1 or index >= len(actions):
        raise AutomationError(reason)
    action = actions[index]
    feedback = action.get('feedback', {})
    if (action.get('id') != index or action.get('action') != BOSS_INTRO_ACTION
            or action.get('expected') != BOSS_INTRO_RETURN or action.get('status') != 'verified'
            or action.get('target') != [attempt['node'], attempt['start_action_id'], intro['id'], node]
            or not action.get('before') or not _paired_progress_evidence(action)
            or not isinstance(feedback, dict) or feedback.get('page_kind') not in ('preparation', 'shop')
            or feedback.get('node') != node or type(feedback.get('gold')) is not int or not 0 <= feedback['gold'] <= 99999
            or type(feedback.get('level')) is not int or not 1 <= feedback['level'] <= 10
            or (feedback['page_kind'] == 'preparation' and (feedback.get('node_type') != '首领'
                or type(feedback.get('hp')) is not int or not 0 < feedback['hp'] <= 100))):
        raise AutomationError(reason)
    return action


def progress_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_defeat import proposal
    defeat=proposal(scene,session,confidence)
    if defeat is not None:return defeat
    kind = observe(scene, confidence).page_kind
    if kind == 'boss_intro' or session.get('node_attempt', {}).get('status') == 'intro_pending':
        attempt = verified_attempt(session, allow_loss=True)
        if kind != 'boss_intro' or attempt['status'] != 'intro_pending':
            raise AutomationError('本次强敌介绍仍待关闭核实，先保留原节点。')
        intro = _intro_source(session['actions'], attempt)
        current = _intro_feedback(scene, intro['feedback']['expected_node'], confidence)
        if current != intro['feedback']:
            raise AutomationError('当前强敌介绍与已核实到达画面不符。')
        payload = (attempt['node'], attempt['start_action_id'], intro['id'], current['expected_node'])
        history = _history(session, BOSS_INTRO_ACTION, BOSS_INTRO_RETURN, payload)
        if history[-1] is not intro:
            raise AutomationError('强敌介绍已经有后续输入，保留原结果待核对。')
        return StandardAction(BOSS_INTRO_ACTION, BOSS_INTRO_RETURN, boss_target(scene, confidence), payload=payload)
    if kind in ('node_result', 'node_loss'):
        attempt = verified_attempt(session, allow_loss=kind == 'node_loss')
        node, start_id = attempt['node'], attempt['start_action_id']
        if result_node(scene, confidence) != node or attempt['status'] != 'verified':
            raise AutomationError('当前结算与已核实节点不一致，未继续挑战。')
        if kind == 'node_loss':
            loss = read_survived_loss(scene, confidence)
            if (loss is None or loss[:2] != (node, attempt.get('remaining_hp'))
                    or not survived_loss_receipt(attempt, session['actions'][start_id])):
                raise AutomationError('当前失利结算与已核实生命值不符，未继续挑战。')
            target = loss[2]
        else:
            target = continue_target(scene, confidence)
        intent, expected, payload = 'continue_standard_node', 'standard_node_advanced', (node, start_id)
        history = _history(session, intent, expected, payload)
        if history[-1].get('id') != start_id:
            raise AutomationError('当前结算不是最近一次已核实出战的结果。')
        return StandardAction(intent, expected, target, payload=payload)
    if kind in ENDING_STEPS:
        attempt = verified_attempt(session)
        node, start_id = attempt['node'], attempt['start_action_id']
        if (not node.startswith('3-') or attempt.get('result_kind') != 'final_victory'
                or session.get('match_victory_observed') is not True
                or session.get('victory_start_action_id') != start_id):
            raise AutomationError('终局页面缺少本局最终节点胜利证据，未标记完成。')
        _, expected, target = ending_target(scene, confidence)
        intent, payload = 'settle_standard_'+kind, (node, start_id)
        history = _history(session, intent, expected, payload)
        if kind == 'final_victory':
            if result_node(scene, confidence) != node or history[-1].get('id') != start_id:
                raise AutomationError('最终胜利编号或出战来源不符。')
        else:
            previous = next(page for page, (_, next_page) in ENDING_STEPS.items() if next_page == kind)
            if (history[-1].get('action') != 'settle_standard_'+previous
                    or history[-1].get('expected') != kind or history[-1].get('target') != list(payload)):
                raise AutomationError('结算链缺少已核实前一页面，未跳步完成。')
        return StandardAction(intent, expected, target, payload=payload)
    if kind == 'plane_map' and session.get('node_attempt'):
        attempt = verified_attempt(session, allow_loss=True)
        node, start_id = attempt['node'], attempt['start_action_id']
        plane = int(node.split('-')[0])+1
        payload = (node, start_id, f'{plane}-1')
        intent, expected = 'advance_standard_next_plane', 'standard_plane_entered'
        history = _history(session, intent, expected, payload)
        previous = history[-1]
        if (plane > 3 or active_plane(scene, confidence) != plane
                or previous.get('action') != 'continue_standard_node'
                or previous.get('target') != [node, start_id]
                or previous.get('feedback') != dict(page_kind='plane_map', node=f'{plane}-1')):
            raise AutomationError('位面地图缺少对应节点继续及下一位面证据。')
        return StandardAction(intent, expected, plane_target(scene, confidence), payload=payload)
    if kind == 'shop' and session.get('node_attempt'):
        # Some nodes open the shop automatically. Close only the observed
        # arrival shop so the new board can be collected before any decisions.
        attempt = verified_attempt(session, allow_loss=True)
        node, start_id = attempt['node'], attempt['start_action_id']
        state = read_match(scene, confidence)
        payload = (state.node, state.gold, state.level, node, start_id)
        intent, expected = 'close_standard_arrival_shop', 'standard_arrival_shop_closed'
        actions = session.get('actions', [])
        previous = actions[-2] if actions and actions[-1].get('action') == intent and actions[-1].get('status') == 'pending' else (actions[-1] if actions else {})
        if previous.get('action') not in ('continue_standard_node', BOSS_INTRO_ACTION):
            return None  # A normally opened shop keeps its original contract.
        history = _history(session, intent, expected, payload)
        arrival = dict(page_kind='shop', node=state.node)
        if previous['action'] == BOSS_INTRO_ACTION:
            arrival.update(gold=state.gold, level=state.level)
            source_valid = boss_arrival_receipt(history, attempt) is previous
        else:
            source_valid = previous.get('target') == [node, start_id]
        if (not source_valid or previous.get('feedback') != arrival
                or state.gold is None or state.level is None):
            raise AutomationError('自动展开商店缺少同节点到达反馈或余额等级。')
        return StandardAction(intent, expected, unique(trusted(scene, confidence), '收起', (.81,.88,.89,.95)), payload=payload)
    return None


def advancement_feedback(scene, source_node, confidence=.65):
    plane, number = map(int, source_node.split('-'))
    state = read_match(scene, confidence,include_rewards=True)
    if state and state.page in ('preparation', 'shop','supply_selection') and state.node == f'{plane}-{number+1}':
        if state.page == 'preparation' and (state.hp is None or state.hp <= 0):
            return None
        return dict(page_kind=state.page, node=state.node)
    kind = observe(scene, confidence).page_kind
    if kind == 'boss_intro':
        return _intro_feedback(scene, boss_destination(source_node), confidence)
    if kind == 'plane_map' and plane < 3:
        try:
            if active_plane(scene, confidence) == plane+1:
                return dict(page_kind='plane_map', node=f'{plane+1}-1')
        except AutomationError:
            pass
    return None


def node_progress_feedback(choice, scene, confidence=.65):
    if choice.expected == 'standard_node_advanced':
        return advancement_feedback(scene, choice.payload[0], confidence)
    if choice.expected != BOSS_INTRO_RETURN or len(choice.payload) != 4:
        return None
    expected_node = choice.payload[3]
    state = read_match(scene, confidence)
    if (expected_node != boss_destination(choice.payload[0]) or state is None
            or state.page not in ('preparation', 'shop') or state.node != expected_node
            or state.gold is None or state.level is None or not 1 <= state.level <= 10):
        return None
    feedback = dict(page_kind=state.page, node=state.node, gold=state.gold, level=state.level)
    if state.page == 'preparation':
        kinds = {normalize(t.text) for t in trusted(scene, confidence).tokens
                 if t.within((.28, .07, .73, .105)) and normalize(t.text) in ('战斗', '奖励', '首领')}
        if state.hp is None or not 1 <= state.hp <= 100 or kinds != {'首领'}:
            return None
        feedback.update(hp=state.hp, node_type='首领')
    return feedback


def progress_verified(session, choice, scene, confidence=.65):
    """Record feedback after the action is verified, preserving each node."""
    action = session['actions'][-1]
    if action.get('action') != choice.intent or action.get('status') != 'verified':
        raise AutomationError('推进结果缺少已核实动作。')
    from .currency_wars_defeat import completed
    if completed(session,choice,scene,confidence):return
    if choice.intent in ('continue_standard_node', BOSS_INTRO_ACTION):
        feedback = node_progress_feedback(choice, scene, confidence)
        if feedback is None:
            raise AutomationError('节点推进反馈未核实。')
        action['feedback'] = feedback
        attempt = session['node_attempt']
        if (choice.intent == 'continue_standard_node' and attempt.get('node_loss_verified') is True
                and not _paired_progress_evidence(action)):
            raise AutomationError('失利后的实际节点到达尚缺两份新鲜证据。')
        if feedback['page_kind'] == 'boss_intro':
            pending = dict(attempt, status='intro_pending', continue_action_id=action['id'])
            _intro_source(session['actions'], pending)
            attempt.update(pending)
            return
        if choice.intent == BOSS_INTRO_ACTION:
            completed_intro = dict(attempt, status='advanced', arrival_action_id=action['id'])
            boss_arrival_receipt(session['actions'], completed_intro)
            attempt.update(completed_intro)
        else:
            attempt.update(status='advanced', continue_action_id=action['id'])
        session.setdefault('node_history', []).append(dict(attempt))
    elif choice.intent == 'advance_standard_next_plane':
        session['expected_board'] = choice.payload[2]
    elif choice.intent == 'settle_standard_match_statistics':
        attempt = verified_attempt(session)
        chain = session['actions'][-4:]
        if (observe(scene, confidence).page_kind != 'lobby' or len(chain) != 4
                or attempt.get('result_kind') != 'final_victory'
                or session.get('victory_start_action_id') != attempt['start_action_id']
                or any(a.get('action') != 'settle_standard_'+page or a.get('status') != 'verified'
                       or a.get('expected') != ENDING_STEPS[page][1] or a.get('target') != list(choice.payload)
                       for a, page in zip(chain, ENDING_STEPS))):
            raise AutomationError('终局四步结算链不完整，未标记整局完成。')
        session.update(status='settled', completion_verified=True, settlement_verified=True,
                       action_status='settled', reason='标准开发对局胜利及结算返回已核实；不计入独立验收。')
