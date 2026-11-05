"""Evidence and one-shot intents for the standard 4.6 encounter modal."""
from __future__ import annotations

import math
from pathlib import Path
import re
from dataclasses import asdict

from . import currency_wars_encounter as reader
from .currency_wars_equipment_mode import STANDARD_BOSSES
from .currency_wars_identity import account_key
from .currency_wars_initial import evidence_ref, source_file_ref
from .currency_wars_match import read_match
from .currency_wars_prepare import trusted
from .currency_wars_standard_node import survived_loss_receipt
from .models import AutomationError, normalize
from .storage import hold_read_sources


OFFER = 'encounter_selection'
SELECT = 'select_standard_encounter'
CONFIRM = 'confirm_standard_encounter'
SELECTED = 'standard_encounter_selected'
ARRIVED = 'standard_encounter_arrived'
INTENTS = frozenset((SELECT, CONFIRM))
_CONTINUE = 'continue_standard_node'
_ORIGIN = 'encounter_origin'
_ERROR = '遭遇缺少同局出战、结算、继续或当前弹卡证据，保留原节点待核对。'
_NODE_TEXT = re.compile(r'[1-3]-[1-9][0-9]?')


def _successor(node):
    if isinstance(node, str) and _NODE_TEXT.fullmatch(node):
        plane, number = map(int, node.split('-'))
        destination = f'{plane}-{number+1}'
        if number < 99 and destination not in STANDARD_BOSSES:
            return destination
    return None


def _scope(session, run_dir, epoch):
    client = session.get('client', {})
    if (type(epoch) is not int or epoch < 0 or session.get('status') != 'active' or session.get('start_verified') is not True
            or session.get('mode') != 'standard_development' or session.get('rank') != 8
            or session.get('wealth') != 40 or session.get('rules_version') != '4.6'
            or session.get('entry', {}).get('rank_verified') is not True
            or client.get('version') != '4.6' or client.get('verified_run') != str(run_dir)
            or client.get('input_epoch') != epoch or session.get('account_verified_run') != str(run_dir)
            or session.get('account_verified_epoch') != epoch
            or not re.fullmatch('[0-9a-f]{64}', str(client.get('sha256', '')))
            or not re.fullmatch('[0-9a-f]{64}', str(session.get('account_key', '')))):
        return None
    return dict(match_id=session['match_id'], account_key=session['account_key'],
                client_sha256=client['sha256'], run_dir=str(run_dir), input_epoch=epoch)


def same_account(scene, session, confidence):
    key = session.get('account_key')
    return (account_key(scene, max(.85, confidence)) == key
            and account_key(scene, min(.65, confidence)) == key)


def _frame(scene, path, scope):
    try:
        source = evidence_ref(scene, path, scope['run_dir'])
    except AutomationError as error:
        raise AutomationError('遭遇原画面无法绑定到本次采集，未发送后续输入。') from error
    return dict(captured_at=scene.captured_at, input_epoch=scope['input_epoch'], source=source)


def record_start(session, action, scene, phase, run_dir, epoch, confidence):
    scope = _scope(session, run_dir, epoch)
    if (scope is None or _successor(action['target'][0]) is None
            or phase == 'after' and action.get(_ORIGIN, {}).get('scope') != scope):
        return
    try:
        if not same_account(scene, session, confidence):
            return
    except AutomationError:
        return
    origin = action.setdefault(_ORIGIN, dict(scope=scope))
    origin[phase] = _frame(scene, action[phase], scope)


def record_result(c, session, attempt, action, scene):
    original = action.get(_ORIGIN, {})
    if 'after' not in original:
        return
    scope = _scope(session, c.report.run_dir, c.runner.input_epoch)
    if scope is None or original.get('scope') != scope:
        return
    try:
        if not same_account(scene, session, c.settings.ocr_confidence):
            return
    except AutomationError:
        return
    attempt['encounter_result_source'] = _frame(scene, attempt['result'], scope)


def bind_input(session, choice, scene, run_dir, epoch):
    if choice.intent not in INTENTS and choice.intent != _CONTINUE:
        return False
    action = session['actions'][-1]
    scope = _scope(session, run_dir, epoch)
    if choice.intent == _CONTINUE and scope is not None and _successor(choice.payload[0]) is not None:
        start = session['actions'][choice.payload[1]].get(_ORIGIN, {})
        result = session['node_attempt'].get('encounter_result_source')
        if start.get('scope') == scope and 'after' in start and result is not None:
            action[_ORIGIN] = dict(scope=scope, before=_frame(scene, action['before'], scope))
            return True
    if choice.intent in INTENTS:
        if scope is None or session['node_attempt']['encounter']['scope'] != scope:
            raise AutomationError(_ERROR)
        action['encounter_before'] = _frame(scene, action['before'], scope)
        return True
    return False


def _panel(observation):
    return dict(cards=[asdict(card) for card in observation.cards],
                selected_slot=observation.selected_slot, selection_state=observation.selection_state,
                confirm_state=observation.confirm_state, refresh_remaining=observation.refresh_remaining)


def _lower_slot(cards):
    if (not isinstance(cards, list) or len(cards) != 2
            or any(not isinstance(card, dict) or card.get('slot') != index
                   or type(card.get('difficulty')) is not int or not 1 <= card['difficulty'] <= 4
                   or not isinstance(card.get('name'), str)
                   or not isinstance(card.get('reward_preview'), dict)
                   or type(card['reward_preview'].get('quantity')) is not int
                   or card['reward_preview']['quantity'] <= 0
                   for index, card in enumerate(cards, 1))):
        return None
    left, right = (card['difficulty'] for card in cards)
    if left != right:
        return 1 if left < right else 2
    return None


def _overlay_pixels(scene, confidence):
    detect = getattr(reader, 'encounter_overlay_present', None)
    return bool(detect and detect(scene, confidence))


def overlay_visible(scene, confidence, *, page_kind='unknown'):
    # Other verified modals have their own Choose button and card outlines.
    # Only a preparation, shop or unknown page can use residual pixels alone.
    return ((page_kind in ('unknown', 'preparation', 'shop') and _overlay_pixels(scene, confidence))
            or reader.read_encounter(scene, confidence) is not None)


def _node_conflict(scene, expected, confidence):
    return any(token.within((.1, .04, .29, .13)) and (text := normalize(token.text)) != expected
               and _NODE_TEXT.fullmatch(text) for token in trusted(scene, min(.65, confidence)).tokens)


def continuation_feedback(choice, scene, session, confidence):
    """A modal proves Continue took effect, while node arrival remains pending."""
    observation = reader.read_encounter(scene, confidence)
    destination = _successor(choice.payload[0])
    if (observation is not None and observation.layout_verified and destination is not None
            and _ORIGIN in session['actions'][-1] and not _node_conflict(scene, destination, confidence)):
        return dict(page_kind=OFFER, expected_node=destination, panel=_panel(observation))
    return None


def direct_arrival_ready(scene, page, confidence):
    if page in ('preparation', 'shop'):
        detect = getattr(reader, 'encounter_node_visible', None)
        if detect and detect(scene, confidence) is True:
            return False
    if page == 'preparation':
        # The pre-modal board also displays the new number and Start.
        kinds = [token for token in trusted(scene, confidence).tokens
                 if token.within((.28, .07, .73, .105)) and normalize(token.text) in ('战斗', '奖励', '首领')]
        return len(kinds) == 1
    return True


def _source(frame, scope, path=None):
    if (not isinstance(frame, dict) or frame.get('input_epoch') != scope['input_epoch']
            or type(frame.get('captured_at')) not in (int, float) or not math.isfinite(frame['captured_at'])
            or not isinstance(ref := frame.get('source'), dict)
            or not isinstance(ref.get('path'), str)
            or (path is not None and Path(ref['path']) != Path(path))
            or not re.fullmatch('[0-9a-f]{64}', str(ref.get('sha256', '')))
            or not re.fullmatch('[0-9a-f]{64}', str(ref.get('pixel_sha256', '')))):
        raise AutomationError(_ERROR)
    return ref


def _pair(action, scope, before):
    frames = action.get('encounter_frames')
    if not isinstance(frames, list) or len(frames) != 2:
        raise AutomationError(_ERROR)
    first, second = frames
    a, b = _source(first, scope), _source(second, scope, action['after'])
    if a['path'] == b['path'] or not before['captured_at'] < first['captured_at'] < second['captured_at']:
        raise AutomationError(_ERROR)
    return a, b


def _opening(actions, attempt):
    node, start_id, index = attempt['node'], attempt['start_action_id'], attempt.get('continue_action_id')
    stage = attempt['encounter']
    destination, scope = stage['expected_node'], stage['scope']
    if (type(start_id) is not int or type(index) is not int or not 0 <= start_id < index < len(actions)
            or index != start_id+1 or destination != _successor(node)):
        raise AutomationError(_ERROR)
    start, opened = actions[start_id], actions[index]
    feedback = opened['feedback']
    if (start.get('id') != start_id or start.get('action') != 'start_standard_node'
            or start.get('expected') != 'standard_node_entered' or start.get('status') != 'verified'
            or len(start.get('target', ())) != 4 or start['target'][0] != node
            or not (attempt.get('result_kind') == 'node_result' and attempt.get('node_verified') is True
                    or survived_loss_receipt(attempt, start))
            or opened.get('id') != index or opened.get('status') != 'verified'
            or opened.get('action') != _CONTINUE or opened.get('expected') != 'standard_node_advanced'
            or opened.get('target') != [node, start_id] or feedback.get('page_kind') != OFFER
            or feedback.get('expected_node') != destination or stage['panel'] != feedback.get('panel')):
        raise AutomationError(_ERROR)
    original, continuing = start[_ORIGIN], opened[_ORIGIN]
    if (original['scope'] != continuing['scope'] or original['scope'] != scope
            or start['input_epoch'] != scope['input_epoch'] or opened['input_epoch'] != scope['input_epoch']):
        raise AutomationError(_ERROR)
    source_frames = (original['before'], original['after'], attempt['encounter_result_source'], continuing['before'])
    files = tuple(_source(frame, scope, path) for frame, path in
                  zip(source_frames, (start['before'], start['after'], attempt['result'], opened['before'])))
    stamps = [frame['captured_at'] for frame in source_frames]
    if not stamps[0] < stamps[1] <= stamps[2] <= stamps[3]:
        raise AutomationError(_ERROR)
    return opened, files + _pair(opened, scope, continuing['before'])


def _payload(attempt):
    stage = attempt['encounter']
    return (attempt['node'], attempt['start_action_id'], attempt['continue_action_id'],
            stage['expected_node'], _lower_slot(stage['panel']['cards']))


def _selected(actions, attempt, opened):
    index = opened['id']+1
    item, scope = actions[index], attempt['encounter']['scope']
    panel = dict(attempt['encounter']['panel'], selected_slot=_payload(attempt)[4],
                 selection_state='selected', confirm_state='enabled')
    if (item.get('id') != index or item.get('status') != 'verified' or item.get('action') != SELECT
            or item.get('expected') != SELECTED or item.get('target') != list(_payload(attempt))
            or item.get('input_epoch') != scope['input_epoch'] or item.get('feedback') != panel
            or item['encounter_before']['captured_at'] < opened['encounter_frames'][-1]['captured_at']):
        raise AutomationError(_ERROR)
    return item, (_source(item['encounter_before'], scope, item['before']),
                  *_pair(item, scope, item['encounter_before']))


def proposal(scene, session, confidence):
    from .currency_wars_standard_flow import StandardAction

    attempt, actions = session['node_attempt'], session['actions']
    try:
        opened, _ = _opening(actions, attempt)
        stage = attempt['encounter']
        if stage['scope'] != _scope(session, stage['scope']['run_dir'], stage['scope']['input_epoch']):
            raise AutomationError(_ERROR)
        payload = _payload(attempt)
        if (payload[4] is None or stage['panel']['selection_state'] != 'unselected'
                or stage['panel']['selected_slot'] is not None or stage['panel']['confirm_state'] != 'disabled'):
            raise AutomationError('遭遇候选难度、奖励预览或未选择状态不完整，等待人工核对。')
        detect = getattr(reader, 'read_encounter_targets', None)
        targets = detect(scene, confidence) if detect else None
        if (targets is None or not targets.observation.layout_verified or not same_account(scene, session, confidence)
                or _node_conflict(scene, stage['expected_node'], confidence)):
            raise AutomationError(_ERROR)
        panel = _panel(targets.observation)
        if len(actions) == opened['id']+1 and panel == stage['panel']:
            return StandardAction(SELECT, SELECTED, targets.cards[payload[4]-1], payload=payload)
        if len(actions) == opened['id']+2:
            selected, _ = _selected(actions, attempt, opened)
            if panel == selected['feedback']:
                return StandardAction(CONFIRM, ARRIVED, targets.choose, payload=(*payload, selected['id']))
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise AutomationError(_ERROR) from error
    raise AutomationError(_ERROR)


def feedback(choice, scene, session, confidence):
    stage = session['node_attempt']['encounter']
    if _node_conflict(scene, stage['expected_node'], confidence):
        return None
    if choice.intent == SELECT:
        observed = reader.read_encounter(scene, confidence)
        expected = dict(stage['panel'], selected_slot=choice.payload[4],
                        selection_state='selected', confirm_state='enabled')
        if observed is not None and observed.layout_verified and _panel(observed) == expected:
            return expected
        return None
    if overlay_visible(scene, confidence):
        return None
    state = read_match(scene, confidence)
    if (state is None or state.node != stage['expected_node'] or state.page not in ('preparation', 'shop')
            or state.gold is None or state.level is None or not 1 <= state.level <= 10):
        return None
    result = dict(page_kind=state.page, node=state.node, gold=state.gold, level=state.level)
    if state.page == 'shop':
        return result if state.probabilities is not None else None
    if state.hp and state.deployment is not None:
        return dict(result, hp=state.hp, deployment=list(state.deployment))
    return None


def arrival_receipt(session, attempt):
    try:
        actions = session['actions']
        opened, _ = _opening(actions, attempt)
        selected, _ = _selected(actions, attempt, opened)
        index, scope = selected['id']+1, attempt['encounter']['scope']
        item = actions[index]
        arrived = item['feedback']
        if (scope['match_id'] != session.get('match_id') or scope['account_key'] != session.get('account_key')
                or attempt.get('encounter_arrival_action_id') != index or item.get('id') != index
                or item.get('action') != CONFIRM or item.get('expected') != ARRIVED
                or item.get('status') != 'verified' or item.get('input_epoch') != scope['input_epoch']
                or item.get('target') != [*_payload(attempt), selected['id']]
                or arrived.get('page_kind') not in ('preparation', 'shop')
                or arrived.get('node') != attempt['encounter']['expected_node']
                or type(arrived.get('gold')) is not int or not 0 <= arrived['gold'] <= 9999
                or type(arrived.get('level')) is not int or not 1 <= arrived['level'] <= 10
                or item['encounter_before']['captured_at'] < selected['encounter_frames'][-1]['captured_at']):
            raise AutomationError(_ERROR)
        if arrived['page_kind'] == 'preparation':
            deployment = arrived.get('deployment')
            if (type(arrived.get('hp')) is not int or not 1 <= arrived['hp'] <= 100
                    or not isinstance(deployment, list) or len(deployment) != 2
                    or any(type(value) is not int for value in deployment)
                    or not 0 <= deployment[0] <= deployment[1] <= 20):
                raise AutomationError(_ERROR)
        _source(item['encounter_before'], scope, item['before'])
        _pair(item, scope, item['encounter_before'])
        return item
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise AutomationError(_ERROR) from error


def commit_feedback(c, store, guard, choice, captures, result, write_evidence):
    """Save the new pair and stage together, keeping a failed write pending."""
    previous = store.data
    scope = _scope(previous, c.report.run_dir, c.runner.input_epoch)
    if scope is None:
        raise AutomationError(_ERROR)
    first, after = (scene for _, scene in captures)
    if first is after:
        raise AutomationError(_ERROR)
    action = dict(previous['actions'][-1], status='verified',
                  after=write_evidence(after, 'currency_standard_after_'+choice.intent))
    session = dict(previous, actions=[*previous['actions'][:-1], action],
                   node_attempt=dict(previous['node_attempt']), screenshot=action['after'])
    session.pop('collection', None)
    frames = []
    for number, (stamp, scene) in enumerate(captures, 1):
        if scene.captured_at != stamp:
            raise AutomationError(_ERROR)
        path = action['after'] if number == 2 else write_evidence(scene, 'currency_standard_encounter_first')
        frames.append(_frame(scene, path, scope))
    action.update(encounter_frames=frames, feedback=result)
    attempt, actions = session['node_attempt'], session['actions']
    if action['action'] == _CONTINUE:
        pending = dict(attempt, status='encounter_pending', continue_action_id=action['id'],
                       encounter=dict(scope=scope, expected_node=result['expected_node'], panel=result['panel']))
        _opening(actions, pending)
        attempt.update(pending)
        session.update(action_status='encounter_observed', page_kind=OFFER)
    elif action['action'] == SELECT:
        opened, _ = _opening(actions, attempt)
        _selected(actions, attempt, opened)
        session.update(action_status='encounter_selection_verified', page_kind=OFFER)
    else:
        advanced = dict(attempt, status='advanced', encounter_arrival_action_id=action['id'])
        arrival_receipt(session, advanced)
        attempt.update(advanced)
        session['node_history'] = [*previous.get('node_history', []), dict(attempt)]
        session.update(action_status='transition_verified', page_kind=result['page_kind'])
    sources = dispatch_sources(previous, choice, scope['run_dir'], scope['input_epoch'], store.path.parent)
    sources += tuple((Path(frame['source']['path']), frame['source']) for frame in frames)
    with hold_read_sources(path for path, _ in sources):
        require_files(sources, scope['run_dir'])
        if store.require_pending(choice.intent, scope['input_epoch']) != previous:
            raise AutomationError('遭遇落盘意图已改变，保留原画面待核对。')
        if not same_account(after, previous, c.settings.ocr_confidence):
            raise AutomationError(_ERROR)
        c.checkpoint()
        c.window.guard(after.geometry)
        guard._require_current_scene(after)
        if c.runner.input_epoch != scope['input_epoch']:
            raise AutomationError(_ERROR)
        store.data = session
        try:
            store.persist()
        except Exception:
            store.data = previous
            raise
    c.report.currency_wars = session


def dispatch_sources(session, choice, run_dir, epoch, runs_root):
    """Resolve the original run files before the native read-hold begins."""
    items = session['actions']
    current = items[-1]
    if choice.intent not in INTENTS and (choice.intent != _CONTINUE or _ORIGIN not in current):
        return ()
    try:
        attempt = session['node_attempt']
        scope = _scope(session, run_dir, epoch)
        if scope is None or epoch != current['input_epoch']:
            raise AutomationError(_ERROR)
        if choice.intent == _CONTINUE:
            source = current[_ORIGIN]
            start = items[choice.payload[1]]
            original = start[_ORIGIN]
            if source['scope'] != scope or original['scope'] != scope or start['input_epoch'] != epoch:
                raise AutomationError(_ERROR)
            refs = (_source(original['before'], scope, start['before']),
                    _source(original['after'], scope, start['after']),
                    _source(attempt['encounter_result_source'], scope, attempt['result']),
                    _source(source['before'], scope, current['before']))
        else:
            opened, refs = _opening(items, attempt)
            if attempt['encounter']['scope'] != scope:
                raise AutomationError(_ERROR)
            if choice.intent == CONFIRM:
                _, selected = _selected(items, attempt, opened)
                refs += selected
            refs += (_source(current['encounter_before'], scope, current['before']),)
        directory = Path(run_dir).resolve(strict=True)
        if directory.parent != Path(runs_root).resolve():
            raise AutomationError(_ERROR)
        paths = tuple(Path(ref['path']).resolve(strict=True) for ref in refs)
        if any(path.parent != directory or str(path) != ref['path'] for path, ref in zip(paths, refs)):
            raise AutomationError(_ERROR)
        return tuple(zip(paths, refs))
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        raise AutomationError(_ERROR) from error


def require_files(refs, run_dir):
    reason = '遭遇原出战、结算、继续或弹卡证据已改变，未发送输入。'
    try:
        unchanged = all(source_file_ref(path, run_dir) == ref for path, ref in refs)
    except AutomationError as error:
        raise AutomationError(reason) from error
    if not unchanged:
        raise AutomationError(reason)
