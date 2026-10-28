"""Advance proven node results and terminal pages without replaying inputs."""
from __future__ import annotations

import re

from .currency_wars import observe
from .currency_wars_ending import ENDING_STEPS, ending_target
from .currency_wars_flow import active_plane, continue_target, plane_target
from .currency_wars_match import read_match
from .currency_wars_navigation import unique
from .currency_wars_node import result_node
from .currency_wars_prepare import trusted
from .models import AutomationError


def verified_attempt(session):
    attempt = session.get('node_attempt', {})
    node, index = attempt.get('node'), attempt.get('start_action_id')
    actions = session.get('actions', [])
    if (session.get('status') != 'active' or not session.get('start_verified')
            or not isinstance(node, str) or not re.fullmatch(r'[1-3]-[1-9][0-9]?', node)
            or attempt.get('node_verified') is not True or attempt.get('status') not in ('verified', 'advanced')
            or not attempt.get('result') or type(index) is not int or not 0 <= index < len(actions)
            or actions[index].get('action') != 'start_standard_node'
            or actions[index].get('status') != 'verified'
            or not actions[index].get('target') or actions[index]['target'][0] != node):
        raise AutomationError('节点推进缺少本局已核实出战与对应胜利结算。')
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


def progress_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    kind = observe(scene, confidence).page_kind
    if kind == 'node_result':
        attempt = verified_attempt(session)
        node, start_id = attempt['node'], attempt['start_action_id']
        if result_node(scene, confidence) != node or attempt['status'] != 'verified':
            raise AutomationError('当前结算与已核实节点不一致，未继续挑战。')
        intent, expected, payload = 'continue_standard_node', 'standard_node_advanced', (node, start_id)
        history = _history(session, intent, expected, payload)
        if history[-1].get('id') != start_id:
            raise AutomationError('当前结算不是最近一次已核实出战的结果。')
        return StandardAction(intent, expected, continue_target(scene, confidence), payload=payload)
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
        attempt = verified_attempt(session)
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
        attempt = verified_attempt(session)
        node, start_id = attempt['node'], attempt['start_action_id']
        state = read_match(scene, confidence)
        payload = (state.node, state.gold, state.level, node, start_id)
        intent, expected = 'close_standard_arrival_shop', 'standard_arrival_shop_closed'
        actions = session.get('actions', [])
        previous = actions[-2] if actions and actions[-1].get('action') == intent and actions[-1].get('status') == 'pending' else (actions[-1] if actions else {})
        if previous.get('action') != 'continue_standard_node':
            return None  # A normally opened shop keeps its original contract.
        history = _history(session, intent, expected, payload)
        if (history[-1].get('feedback') != dict(page_kind='shop', node=state.node)
                or history[-1].get('target') != [node, start_id]
                or state.gold is None or state.level is None):
            raise AutomationError('自动展开商店缺少同节点到达反馈或余额等级。')
        return StandardAction(intent, expected, unique(trusted(scene, confidence), '收起', (.81,.88,.89,.95)), payload=payload)
    return None


def advancement_feedback(scene, source_node, confidence=.65):
    plane, number = map(int, source_node.split('-'))
    state = read_match(scene, confidence)
    if state and state.page in ('preparation', 'shop') and state.node == f'{plane}-{number+1}':
        if state.page == 'preparation' and (state.hp is None or state.hp <= 0):
            return None
        return dict(page_kind=state.page, node=state.node)
    if observe(scene, confidence).page_kind == 'plane_map' and plane < 3:
        try:
            if active_plane(scene, confidence) == plane+1:
                return dict(page_kind='plane_map', node=f'{plane+1}-1')
        except AutomationError:
            pass
    return None


def progress_verified(session, choice, scene, confidence=.65):
    """Record feedback after the action is verified, preserving each node."""
    action = session['actions'][-1]
    if action.get('action') != choice.intent or action.get('status') != 'verified':
        raise AutomationError('推进结果缺少已核实动作。')
    if choice.intent == 'continue_standard_node':
        feedback = advancement_feedback(scene, choice.payload[0], confidence)
        if feedback is None:
            raise AutomationError('节点推进反馈未核实。')
        action['feedback'] = feedback
        attempt = session['node_attempt']
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
