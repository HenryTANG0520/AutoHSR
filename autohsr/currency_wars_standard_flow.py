"""Standard A8-40 development flow. Only observed and validated inputs run."""
from __future__ import annotations

import hashlib
import json
import math
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_environment import (ENVIRONMENT_CONFIRM, ENVIRONMENT_SELECT, ENVIRONMENT_SELECTED,
    environment_decision, environment_decision_matches, environment_selection_slot,
    standard_environment_choice, standard_environment_confirm)
from .currency_wars_navigation import locate, unique
from .currency_wars_prepare import trusted
from .currency_wars_session import StandardSession,require_session_access
from .currency_wars_standard import difficulty_page, selected_rank
from .models import AutomationError, EmptyCapture, InputInterrupted, TaskResult
from .models import Token, normalize


@dataclass(frozen=True)
class StandardAction:
    intent: str
    expected: str
    target: object
    details: tuple = ()
    payload: tuple = ()
    encounter_arrival: int | None = None


def _preparation_probe(scene,confidence,known,session=None):
    from .currency_wars_collector import first_unit_probe,roster_cells
    # A fresh nineteen-cell scan can prove zero owned units. Failure to read
    # the layout or match the HUD still raises rather than authorizing a shop.
    if any(c.state=='occupied' for c in roster_cells(scene,confidence)):
        return first_unit_probe(scene,confidence,known,session=session)
    if known:
        raise AutomationError('当前空阵容与已采集角色不符，未沿用缓存或自动开店。')
    return None


_LOOT_SALE_INSPECTIONS = frozenset(('inspect_standard_unit', 'close_standard_unit', 'close_standard_stale_unit',
                                    'open_standard_equipment_recommendations'))
_LOOT_REWARD_PAGES = frozenset(('equipment_selection', 'advanced_equipment_selection',
                                'expert_selection', 'hiring_selection'))
_LOOT_REWARD_READS = frozenset(('inspect_standard_reward_unit', 'close_standard_reward_unit',
                                 'close_standard_reward_stale_panel'))
_LOOT_BOX_OPEN = 'open_standard_bench_reward'
_LOOT_BOARD_FIELDS = ('node', 'hp', 'level', 'experience', 'deployment')
_LOOT_SALE_COLLECTION = _LOOT_SALE_INSPECTIONS | _LOOT_REWARD_READS | {
    'collect_standard_loot', 'choose_standard_reward', _LOOT_BOX_OPEN}
_UNRESOLVED_LOOT_BOX = object()


def _loot_sale_basis(scene, confidence, session):
    from .currency_wars_match import read_match
    from .currency_wars_node import loot_centers
    crystals = loot_centers(scene)
    if not crystals:
        return None
    state = read_match(scene, confidence)
    if not state or state.page != 'preparation' or not state.deployment:
        raise AutomationError('晶矿腾位查看缺少当前备战和出战人数。')
    basis = dict(crystals=[list(center) for center in crystals],
                 experience=list(state.experience) if state.experience is not None else None,
                 deployment=list(state.deployment))
    if state.node not in session.get('shop_observed_nodes', []):
        pickup = _loot_sale_continuation(scene, state, session, confidence)
        if pickup is None:
            raise AutomationError('晶矿腾位缺少本节点商店或已核实的前次领取。')
        basis['pickup_action_id'] = pickup['id']
    return basis


def _loot_sale_digest(basis):
    data = json.dumps(basis, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def _loot_sale_source(action):
    decision = action.get('decision')
    marker = decision.get('loot_sale_basis_sha256') if isinstance(decision, dict) else None
    if marker is None and 'loot_sale_basis' not in action:
        return None
    basis = action.get('loot_sale_basis')
    if isinstance(basis, dict):
        try:
            if marker == _loot_sale_digest(basis):
                return basis
        except (TypeError, ValueError):
            pass
    raise AutomationError('晶矿腾位出售的原晶矿来源缺失或不一致。')


def _loot_sale_index(actions, followups=_LOOT_SALE_INSPECTIONS):
    index = len(actions)-1
    while index >= 0 and actions[index].get('action') in followups:
        index -= 1
    if index >= 1 and actions[index].get('action') == 'sell_standard_owned':
        return index
    return None


def _loot_pickup_sale(actions, index, limit):
    if type(index) is not int or not 0 <= index < limit:
        raise AutomationError('连续晶矿缺少前次领取记录。')
    action = actions[index]
    sale_id = action.get('loot_sale_action_id')
    if (action.get('id') != index or action.get('action') != 'collect_standard_loot' or action.get('status') != 'verified'
            or not isinstance(action.get('loot_pickup'), dict) or type(sale_id) is not int or not 1 <= sale_id < index
            or actions[sale_id].get('action') != 'sell_standard_owned'):
        raise AutomationError('连续晶矿缺少前次已核实的腾位出售和领取回执。')
    return sale_id


def _loot_reward_proof(origin):
    return origin.get('loot_box_open' if origin.get('action') == _LOOT_BOX_OPEN else 'loot_pickup')


def _loot_reward_origin(session):
    reward = session.get('reward', {})
    index = reward.get('origin_action_id')
    actions = session.get('actions', [])
    cursor = len(actions)-1
    if cursor >= 0 and actions[cursor].get('status') == 'pending':
        cursor -= 1
    while cursor >= 0 and actions[cursor].get('action') in _LOOT_REWARD_READS:
        cursor -= 1
    claim = None
    if cursor >= 0 and actions[cursor].get('action') == 'choose_standard_reward':
        claim = actions[cursor]
        cursor -= 1
    if cursor >= 0 and actions[cursor].get('action') == _LOOT_BOX_OPEN:
        origin = actions[cursor]
        proof = _loot_reward_proof(origin)
        pickup = _loot_waiting_box(actions[:cursor])
        if pickup is not None or 'loot_box_pickup_action_id' in origin or 'loot_box_open' in origin:
            if (type(index) is not int or index != cursor or origin.get('id') != cursor or origin.get('status') != 'verified'
                    or pickup is None or not _loot_opened_box(origin, pickup, pickup['loot_pickup']['remaining'])
                    or proof['reward_page'] != reward.get('page') or origin['target'][1] != reward.get('box_slot')
                    or proof['gold_before_claim'] != reward.get('basis', {}).get('gold')):
                raise AutomationError('晶矿备战箱的开启来源与当前选奖记录不一致。')
            status = reward.get('status')
            if claim is None and status == 'awaiting':
                return origin
            target = claim.get('target') if claim is not None else None
            if (claim is not None and claim.get('status') == 'verified'
                    and claim.get('id') == reward.get('claim_action_id') == cursor+1
                    and isinstance(target, list) and len(target) >= 3 and target[1] == cursor):
                if status == 'unit_verifying':
                    return origin
                from .currency_wars_standard_rewards import valid_effect
                if (status == 'verified' and origin.get('reward_verified') is True
                        and claim.get('reward_verified') is True and valid_effect(claim, actions)):
                    return None
            raise AutomationError('晶矿备战箱的选奖尚未核实。')
    if (reward.get('status') not in ('awaiting', 'unit_verifying') or type(index) is not int
            or not 0 <= index < len(actions)):
        return None
    origin = actions[index]
    proof = _loot_reward_proof(origin)
    if origin.get('action') == _LOOT_BOX_OPEN:
        if 'loot_box_pickup_action_id' in origin or 'loot_box_open' in origin:
            raise AutomationError('不能用历史开箱替代当前晶矿备战箱。')
        return None
    if (origin.get('action') == 'collect_standard_loot' and origin.get('status') == 'verified'
            and isinstance(origin.get('reward_basis'), dict)
            and isinstance(proof, dict) and isinstance(proof.get('reward_page'), str)
            and proof['reward_page'] in _LOOT_REWARD_PAGES
            and proof['reward_page'] == reward.get('page') and isinstance(proof.get('remaining'), list)
            and type(proof.get('gold_before_claim')) is int):
        _loot_pickup_sale(actions, index, len(actions))
        return origin
    return None


def _loot_sale_input_chain(intent, session):
    actions = session.get('actions', [])
    if not actions:
        return None
    if intent == 'inspect_standard_sale_unit':
        source = len(actions)-1
    elif intent == 'sell_standard_owned':
        source = len(actions)-2
    elif intent == 'choose_standard_reward' or intent in _LOOT_REWARD_READS:
        origin = _loot_reward_origin(session)
        if origin is None:
            return None
        pickup = actions[origin['loot_box_pickup_action_id']] if origin['action'] == _LOOT_BOX_OPEN else origin
        source = pickup['loot_sale_action_id']-1
    elif intent == _LOOT_BOX_OPEN:
        pickup = _loot_waiting_box(actions[:-1])
        if pickup is None and 'loot_box_pickup_action_id' not in actions[-1]:
            return None
        if pickup is None or not _loot_box_open_source(actions[-1], pickup):
            raise AutomationError('晶矿备战箱的落盘槽位与原领取回执不一致。')
        source = pickup['loot_sale_action_id']-1
    elif intent == 'collect_standard_loot' or intent in _LOOT_SALE_INSPECTIONS:
        prior = actions[:-1]
        pickup = _loot_waiting_box(prior) if intent in _LOOT_SALE_INSPECTIONS else None
        index = pickup['loot_sale_action_id'] if pickup is not None else _loot_sale_index(prior)
        if index is None and intent == 'collect_standard_loot':
            index = actions[-1].get('loot_sale_action_id')
        if index is None:
            return None
        if type(index) is not int or not 1 <= index < len(actions)-1:
            raise AutomationError('晶矿领取的落盘出售来源无效。')
        source = index-1
    else:
        return None
    basis = _loot_sale_source(actions[source]) if source >= 0 else None
    if basis is None:
        return None
    return actions[_loot_sale_root(actions, source, basis):]


def loot_sale_input_scope(choice, current, saved):
    """Require the durable sale chain before re-deriving a scoped input."""
    from .currency_wars_standard_sale import same_target

    live_chain = _loot_sale_input_chain(choice.intent, current)
    saved_chain = _loot_sale_input_chain(choice.intent, saved)
    if live_chain is None and saved_chain is None:
        return False
    reason = '晶矿腾位出售与已落盘来源不一致，未发送输入。'
    try:
        same_chain = same_target(live_chain, saved_chain) and same_target(current.get('sale'), saved.get('sale'))
        if choice.intent == 'choose_standard_reward' or choice.intent in _LOOT_REWARD_READS:
            same_chain = same_chain and same_target(current.get('reward'), saved.get('reward'))
    except (TypeError, ValueError) as error:
        raise AutomationError(reason) from error
    if not same_chain:
        raise AutomationError(reason)
    return True


def _same_loot_centers(previous, current):
    if not isinstance(previous, list) or not isinstance(current, (list, tuple)) or len(previous) != len(current):
        return False
    if any(not isinstance(center, (list, tuple)) or len(center) != 3 or
           any(type(value) not in (int, float) or not 0 < value < 1 for value in center)
           for centers in (previous, current) for center in centers):
        return False
    matches = []
    for center in previous:
        x, y, radius = center
        nearby = [index for index, (a, b, r) in enumerate(current)
                  if math.hypot(a-x, (b-y)*9/16) < max(18/2560, .8*radius)
                  and abs(r-radius) <= .25*radius]
        if len(nearby) != 1:
            return False
        matches.append(nearby[0])
    return len(set(matches)) == len(current)


def _loot_remaining(crystals, target):
    if not isinstance(crystals, list):
        return None
    matches = [index for index, center in enumerate(crystals) if _same_loot_centers([center], [target])]
    if len(matches) != 1:
        return None
    return crystals[:matches[0]] + crystals[matches[0]+1:]


def _loot_board_values(state):
    return (state.node, state.hp, state.level, list(state.experience) if state.experience is not None else None,
            list(state.deployment or ()))


def _loot_basis_values(basis):
    return tuple(basis.get(key) for key in _LOOT_BOARD_FIELDS)


def _loot_bench_delta(before, after):
    """Return one new box, () for no box change, or None for ambiguous delivery."""
    if not isinstance(before, dict) or not isinstance(after, dict) or before.keys() != after.keys():
        return None
    bench = {f'bench:{slot}': slot for slot in range(1, 10)}
    if not bench.keys() <= before.keys() or any(
            not isinstance(cell, list) or len(cell) != 2 or cell[0] not in ('empty', 'occupied', 'reward')
            for cells in (before, after) for cell in cells.values()):
        return None
    old = {key: cell for key, cell in before.items() if cell[0] == 'reward'}
    new = {key: cell for key, cell in after.items() if cell[0] == 'reward'}
    if old == new:
        return ()
    added = new.keys() - old.keys()
    if len(added) != 1:
        return None
    key = next(iter(added))
    if (key not in bench or before[key][0] != 'empty' or before[key][1] == new[key][1]
            or any(after[other] != cell for other, cell in before.items() if other != key)):
        return None
    return [bench[key], new[key][1]]


def _loot_box_marker(pickup):
    box = pickup['loot_pickup'].get('bench_box')
    before = pickup['reward_basis'].get('cells')
    if not isinstance(box, list) or len(box) != 2 or not isinstance(before, dict):
        return None
    slot, signature = box
    if type(slot) is not int or not 1 <= slot <= 9 or not isinstance(signature, str) or len(signature) != 64:
        return None
    cell = before.get(f'bench:{slot}')
    if (not isinstance(cell, list) or len(cell) != 2 or cell[0] != 'empty' or cell[1] == signature
            or any(char not in '0123456789abcdef' for char in signature)):
        return None
    return box


def _loot_box_open_source(action, pickup):
    box = _loot_box_marker(pickup)
    before, collected_before = action.get('reward_basis'), pickup['reward_basis']
    return (box is not None and action.get('action') == _LOOT_BOX_OPEN
            and action.get('expected') == 'standard_reward_opened' and action.get('before')
            and action.get('loot_box_pickup_action_id') == pickup['id']
            and action.get('target') == [collected_before['node'], *box]
            and isinstance(before, dict) and _loot_basis_values(before) == _loot_basis_values(collected_before)
            and before.get('gold') == pickup['loot_pickup']['gold_after']
            and _loot_bench_delta(collected_before.get('cells'), before.get('cells')) == box)


def _loot_opened_box(action, pickup, remaining):
    proof = action.get('loot_box_open')
    return (_loot_box_open_source(action, pickup) and action.get('after') and isinstance(proof, dict)
            and isinstance(proof.get('reward_page'), str) and proof['reward_page'] in _LOOT_REWARD_PAGES
            and type(proof.get('gold_before_claim')) is int
            and proof['gold_before_claim'] == pickup['loot_pickup']['gold_after']
            and _same_loot_centers(remaining, proof.get('remaining')))


def _loot_unit_read_matches(returned, claim, actions, end, node, slot):
    proof = returned.get('unit_slot_read')
    if not isinstance(proof, dict):
        return False
    read_id, signature = proof.get('action_id'), proof.get('signature')
    if (type(read_id) is not int or not claim['id'] < read_id < end-1
            or not isinstance(signature, str) or len(signature) != 64
            or any(char not in '0123456789abcdef' for char in signature)):
        return False
    read, close = actions[read_id:read_id+2]
    return (read.get('action') == 'inspect_standard_reward_unit' and read.get('expected') == 'character'
            and read.get('target') == ['bench', slot, node, signature]
            and close.get('action') == 'close_standard_reward_unit'
            and close.get('expected') == 'standard_reward_unit_board'
            and type(read.get('input_epoch')) is int and read['input_epoch'] == close.get('input_epoch')
            and all(a.get('status') == 'verified' and a.get('before') and a.get('after') for a in (read, close)))


def _loot_reward_gold(origin, claim, actions, remaining, end):
    from .currency_wars_standard_rewards import valid_effect

    proof = _loot_reward_proof(origin)
    returned = claim.get('loot_reward_return')
    if (claim.get('id') != origin['id']+1 or claim.get('expected') != 'standard_reward_returned'
            or origin.get('reward_verified') is not True or claim.get('reward_verified') is not True
            or not isinstance(returned, dict) or not _same_loot_centers(remaining, returned.get('remaining'))
            or not valid_effect(claim, actions)):
        return None
    effect, before = claim['reward_effect'], origin['reward_basis']
    cells = before.get('cells')
    slot = returned.get('added_bench_slot')
    if (effect['origin_action_id'] != origin['id'] or effect['page'] != proof['reward_page']
            or effect['node_after'] != before['node'] or type(effect.get('gold_before')) is not int
            or effect['gold_before'] != proof['gold_before_claim'] or type(returned.get('gold_after')) is not int
            or effect['gold_after'] != returned['gold_after'] or not isinstance(cells, dict)
            or type(slot) is not int or not 0 <= slot <= 9):
        return None
    delivery = effect.get('delivery_kind')
    if delivery == 'unit':
        if returned.get('unit_slot_verified') is not True:
            return None
        cell = cells.get(f'bench:{slot}') if slot else None
        initial_state = 'reward' if slot and origin['action'] == _LOOT_BOX_OPEN and slot == origin['target'][1] else 'empty'
        if slot and (not isinstance(cell, list) or not cell or cell[0] != initial_state
                     or not _loot_unit_read_matches(returned, claim, actions, end, before['node'], slot)):
            return None
    elif slot or (effect.get('unit') and delivery != 'advisor_selection'):
        return None
    return effect['gold_after']


def _loot_pickup_chain(actions, index, end, basis, *, waiting_for_box=False):
    """Rebuild the remaining set and balance between two sales."""
    receipt = actions[index]['receipt']
    values = (receipt['node'], receipt['hp_after'], receipt['level_after'], basis.get('experience'), basis.get('deployment'))
    remaining, gold, pickup = basis.get('crystals'), receipt['gold_after'], None
    unopened, open_reward, read_reward_unit = None, None, False
    for offset, action in enumerate(actions[index+1:end], index+1):
        intent = action.get('action')
        if (action.get('id') != offset or action.get('status') != 'verified'
                or intent not in _LOOT_SALE_COLLECTION):
            return None
        if open_reward is not None:
            gold = (_loot_reward_gold(open_reward, action, actions, remaining, end)
                    if intent == 'choose_standard_reward' else None)
            if gold is None:
                return None
            read_reward_unit = bool(action['reward_effect'].get('unit'))
            open_reward = None
            continue
        if unopened is not None:
            if intent in _LOOT_SALE_INSPECTIONS and action.get('before') and action.get('after'):
                continue
            if not _loot_opened_box(action, unopened, remaining):
                return None
            open_reward, unopened = action, None
            continue
        if intent in ('choose_standard_reward', _LOOT_BOX_OPEN):
            return None
        if intent in _LOOT_REWARD_READS:
            if not read_reward_unit or not action.get('before') or not action.get('after'):
                return None
            if intent == 'inspect_standard_reward_unit':
                target = action.get('target')
                if not isinstance(target, (tuple, list)) or len(target) != 4 or target[2] != values[0]:
                    return None
            continue
        if intent != 'collect_standard_loot':
            continue
        read_reward_unit = False
        proof, before = action.get('loot_pickup'), action.get('reward_basis')
        remaining = _loot_remaining(remaining, action.get('target'))
        if (action.get('loot_sale_action_id') != index or action.get('expected') != 'loot_collected'
                or any(not isinstance(action.get(key), str) or not action[key] for key in ('before', 'after'))
                or not isinstance(proof, dict) or not isinstance(before, dict) or remaining is None
                or _loot_basis_values(before) != values
                or before.get('gold') != gold or not _same_loot_centers(remaining, proof.get('remaining'))):
            return None
        pickup = action
        if ('bench_box' in proof) != (action.get('loot_pickup_kind') == 'bench_box'):
            return None
        if 'reward_page' in proof:
            page, modal_gold = proof['reward_page'], proof.get('gold_before_claim')
            if ('bench_box' in proof or not isinstance(page, str) or page not in _LOOT_REWARD_PAGES
                    or type(modal_gold) is not int or not gold <= modal_gold <= 99999):
                return None
            open_reward = action
        else:
            after_gold = proof.get('gold_after')
            if type(after_gold) is not int or not gold <= after_gold <= 99999:
                return None
            gold = after_gold
            if 'bench_box' in proof:
                if _loot_box_marker(pickup) is None:
                    return None
                unopened = pickup
    if waiting_for_box:
        return (values, remaining, gold, pickup) if unopened is not None else None
    return (values, remaining, gold, pickup) if unopened is None and open_reward is None and pickup is not None and remaining else None


def _loot_waiting_box(actions):
    """Recover an unopened box only from the current verified loot sequence."""
    cursor = len(actions)-1
    while cursor >= 0 and actions[cursor].get('action') in _LOOT_SALE_INSPECTIONS:
        cursor -= 1
    if cursor < 0:
        return None
    pickup = actions[cursor]
    proof = pickup.get('loot_pickup')
    if pickup.get('loot_pickup_kind') != 'bench_box' and (not isinstance(proof, dict) or 'bench_box' not in proof):
        return None
    index = _loot_pickup_sale(actions, cursor, len(actions))
    basis = _verified_loot_sale(actions, index)
    chain = _loot_pickup_chain(actions, index, len(actions), basis, waiting_for_box=True) if basis is not None else None
    if chain is None or chain[3] is not pickup:
        raise AutomationError('晶矿备战箱缺少完整的领取和槽位来源。')
    _loot_sale_root(actions, index-1, basis)
    return pickup


def _loot_sale_root(actions, source, basis):
    """Trace only earlier verified pickups, one segment per sale."""
    while 'pickup_action_id' in basis:
        pickup_id = basis['pickup_action_id']
        index = _loot_pickup_sale(actions, pickup_id, source)
        parent = _verified_loot_sale(actions, index)
        chain = _loot_pickup_chain(actions, index, source, parent) if parent is not None else None
        if chain is not None:
            (node, hp, level, experience, deployment), remaining, gold, pickup = chain
            target = actions[source].get('target')
            if (pickup.get('id') == pickup_id and isinstance(target, (list, tuple))
                    and tuple(target[:4]) == (node, gold, hp, level)
                    and basis.get('experience') == experience and basis.get('deployment') == deployment
                    and _same_loot_centers(remaining, basis.get('crystals'))):
                source, basis = index-1, parent
                continue
        raise AutomationError('连续晶矿的前次出售、领取或剩余来源不一致。')
    return source


def _loot_sale_continuation(scene, state, session, confidence):
    from .currency_wars_node import loot_centers
    from .currency_wars_standard_hud import experience_observed

    actions = session.get('actions', [])
    index = _loot_sale_index(actions, _LOOT_SALE_COLLECTION)
    if index is None or not state or state.page != 'preparation' or not experience_observed(scene, state, confidence):
        return None
    basis = _verified_loot_sale(actions, index)
    chain = _loot_pickup_chain(actions, index, len(actions), basis) if basis is not None else None
    if chain is not None:
        values, remaining, gold, pickup = chain
        if (_loot_board_values(state) == values and gold == state.gold
                and _same_loot_centers(remaining, loot_centers(scene))):
            _loot_sale_root(actions, index-1, basis)
            return pickup
    return None


def _loot_pickup_origin(scene, session, confidence):
    actions = session.get('actions', [])
    index = _loot_sale_index(actions)
    if index is not None and _loot_sale_source(actions[index-1]) is not None:
        return index
    from .currency_wars_match import read_match
    pickup = _loot_sale_continuation(scene, read_match(scene, confidence), session, confidence)
    return pickup['loot_sale_action_id'] if pickup else None


def _loot_board_feedback(scene, state, before, remaining, confidence):
    from .currency_wars_node import loot_centers
    from .currency_wars_standard_hud import experience_observed

    if (not before or not state or state.page != 'preparation' or not experience_observed(scene, state, confidence)
            or _loot_board_values(state) != _loot_basis_values(before)
            or state.gold is None or not before['gold'] <= state.gold <= 99999
            or not _same_loot_centers(remaining, loot_centers(scene))):
        return None
    return dict(remaining=remaining, gold_after=state.gold)


def _loot_overflow_feedback(before, after, target, crystals, remaining, confidence):
    """Observe the target during a full-bench notice, independently of delivery."""
    from .currency_wars_loot import changed_crystal_pixels
    from .currency_wars_match import read_match
    from .currency_wars_node import loot_centers
    from .currency_wars_pages import is_bench_full_notice
    from .currency_wars_standard_hud import experience_observed

    notices = {normalize(t.text) for t in trusted(after, confidence).tokens if is_bench_full_notice(t)}
    if len(notices) != 1 or remaining is None:
        return None
    initial, current = read_match(before, confidence), read_match(after, confidence)
    if (not initial or not current or initial.page != 'preparation' or current.page != 'bench_full'
            or not initial.node or initial.hp is None or initial.hp <= 0 or not initial.deployment
            or _loot_board_values(current) != _loot_board_values(initial)
            or not experience_observed(before, initial, confidence) or not experience_observed(after, current, confidence)
            or initial.gold is None or current.gold is None or not initial.gold <= current.gold <= 99999
            or before.image is None or after.image is None or before.image.shape != after.image.shape):
        return None
    observed = loot_centers(after)
    if _same_loot_centers(crystals, observed):
        crystal_state = 'present'
    elif _same_loot_centers(remaining, observed) and changed_crystal_pixels(before, after, target):
        crystal_state = 'removed'
    else:
        crystal_state = 'unclear'
    return dict(node=current.node, notice=next(iter(notices)), crystal_state=crystal_state,
                delivery_status='unverified', gold_before=initial.gold, gold_after=current.gold)


def _record_loot_overflow(c, store, action, proof, earlier, later):
    observed = action.setdefault('loot_overflow_observations', [])
    if any(item['crystal_state'] == proof['crystal_state'] for item in observed):
        return
    frames = [dict(captured_at=frame.captured_at, evidence=evidence(c, frame, 'currency_standard_loot_overflow'))
              for frame in (earlier, later)]
    observed.append(dict(proof, frames=frames))
    store.persist()


def _loot_timeout_reason(action):
    observations = action.get('loot_overflow_observations', [])
    if observations:
        crystal_state = observations[-1]['crystal_state']
        ground = {'removed': '已看到本次点击的晶矿消失',
                  'present': '仍看得到本次点击的晶矿',
                  'unclear': '本次点击的晶矿状态未核实'}[crystal_state]
        return '观察到备战席已满，' + ground + '。奖励交付仍待核对，已停止本次输入。'
    return '标准动作转换未核实，未重复输入。'


def _loot_returned_after_overflow(before, after, action, remaining, confidence):
    from .currency_wars_match import read_match

    state = read_match(after, confidence, include_rewards=True)
    source = action.get('reward_basis')
    if state and state.page in _LOOT_REWARD_PAGES:
        return _loot_modal_feedback(state, source, remaining) is not None
    if source is None:
        previous = read_match(before, confidence)
        if previous is None or previous.gold is None:
            return False
        source = dict(zip(_LOOT_BOARD_FIELDS, _loot_board_values(previous)), gold=previous.gold)
    return _loot_board_feedback(after, state, source, remaining, confidence) is not None


def _loot_modal_feedback(state, before, remaining):
    if before and state and state.page in _LOOT_REWARD_PAGES and remaining is not None:
        if state.node != before['node']:
            return None
        observed = dict(hp=state.hp, level=state.level,
                        experience=list(state.experience) if state.experience else None,
                        deployment=list(state.deployment) if state.deployment else None)
        if any(value is not None and value != before[key] for key, value in observed.items()):
            return None
        gold = before['gold'] if state.gold is None else state.gold
        if before['gold'] <= gold <= 99999:
            # The reward overlay hides the ground. The surviving crystals
            # still need to be observed on the return to preparation.
            return dict(remaining=remaining, reward_page=state.page, gold_before_claim=gold)
    return None


def _loot_live_box(scene, before, confidence):
    from .currency_wars_collector import roster_cells
    from .currency_wars_rewards import open_reward_target

    try:
        cells = {f'{cell.zone}:{cell.slot}': [cell.state, cell.signature]
                 for cell in roster_cells(scene, confidence)}
        box = _loot_bench_delta(before.get('cells'), cells)
        if box:
            open_reward_target(scene, confidence, slot=box[0])
        return box
    except AutomationError:
        return None


def _loot_pickup_feedback(scene, action, remaining, confidence):
    from .currency_wars_match import read_match

    before = action.get('reward_basis')
    state = read_match(scene, confidence, include_rewards=True)
    if not before or not state or state.page != 'preparation':
        return _loot_modal_feedback(state, before, remaining)
    result = _loot_board_feedback(scene, state, before, remaining, confidence)
    box = _loot_live_box(scene, before, confidence)
    if box == ():
        return result  # Ordinary disappearance may still be verified without continuation.
    if box and result is not None:
        return dict(result, bench_box=box)
    if box is None and not any(cell[0] == 'reward' for cell in before['cells'].values()) and not any(
            normalize(t.text) == '开启' and t.within((.18, .78, .80, .92)) for t in trusted(scene, confidence).tokens):
        return None  # No box signal; retain the existing disappearance-only outcome.
    return _UNRESOLVED_LOOT_BOX


def _loot_box_board(scene, pickup, confidence):
    from .currency_wars_match import read_match

    before, proof = pickup['reward_basis'], pickup['loot_pickup']
    state = read_match(scene, confidence)
    result = _loot_board_feedback(scene, state, before, proof['remaining'], confidence)
    if (result is None or result['gold_after'] != proof['gold_after']
            or _loot_live_box(scene, before, confidence) != proof['bench_box']):
        raise AutomationError('晶矿备战箱的原槽、其余备战格或剩余晶矿未重新核实。')
    return proof['bench_box'][0]


def _loot_box_feedback(scene, action, pickup, confidence):
    from .currency_wars_match import read_match

    result = _loot_modal_feedback(read_match(scene, confidence, include_rewards=True),
                                  action['reward_basis'], pickup['loot_pickup']['remaining'])
    if result is not None and result['gold_before_claim'] == pickup['loot_pickup']['gold_after']:
        return result
    return None


def _loot_reward_feedback(scene, origin, choice, confidence):
    from .currency_wars_match import read_match
    from .currency_wars_standard_rewards import added_loot_bench_slot

    before, proof = origin['reward_basis'], _loot_reward_proof(origin)
    state = read_match(scene, confidence)
    result = _loot_board_feedback(scene, state, before, proof['remaining'], confidence)
    if result is None or result['gold_after'] != proof['gold_before_claim'] + choice.payload[7]:
        return None
    box_slot = origin['target'][1] if origin['action'] == _LOOT_BOX_OPEN else None
    slot = added_loot_bench_slot(scene, before['cells'], confidence, box_slot=box_slot)
    if slot is None:
        return None
    return dict(result, added_bench_slot=slot)


def _loot_sale_board(scene, session, sale_index, receipt, confidence):
    from .currency_wars_collector import roster_cells
    from .currency_wars_standard_collection import _board, retained
    from .currency_wars_standard_sale import same_target

    actions = session['actions']
    records = session.get('collection', {}).get('units', {})
    sale = session.get('sale', {})
    original_units = {(unit['zone'], unit['slot']): unit for unit in sale.get('snapshot', {}).get('roster', ())}
    current = {(cell.zone, cell.slot): cell for cell in roster_cells(scene, confidence)}
    if len(current) != len(receipt['cells_after']):
        return False
    for (zone, slot), cell in current.items():
        key = f'{zone}:{slot}'
        observed = receipt['cells_after'].get(key)
        if not observed or cell.state != observed[0]:
            return False
        if cell.signature == observed[1]:
            continue
        # Permit an occupied slot's new signature only after its ordinary
        # inspection starts from the exact sold-board slot and closes cleanly.
        record = records.get(key, {})
        original = original_units.get((zone, slot))
        inspect_id = record.get('inspection_action_id')
        close_id = record.get('collection_close_action_id')
        if (cell.state != 'occupied' or not original or sale.get('status') != 'verified'
                or sale.get('inspect_action_id') != receipt['inspect_action_id']
                or type(inspect_id) is not int or type(close_id) is not int
                or not sale_index < inspect_id < close_id < len(actions)
                or actions[inspect_id].get('target') != [zone, slot, cell.node, observed[1]]
                or not same_target(actions[inspect_id].get('collection_basis'), _board(scene, confidence))
                or any(original.get(field) is not None and not same_target(original[field], record['unit'].get(field))
                       for field in ('name', 'star', 'tier', 'eligible_zones', 'equipment'))
                or not retained(scene, cell, record, session)):
            return False
    return True


def _verified_loot_sale(actions, index):
    sale, source = actions[index], actions[index-1]
    basis = _loot_sale_source(source)
    if basis is None:
        return None
    from .currency_wars_standard_ledger import valid_receipt
    from .currency_wars_standard_sale import inspection_target, same_target
    if (sale.get('id') != index or source.get('id') != index-1 or not valid_receipt(sale)
            or source.get('action') != 'inspect_standard_sale_unit'
            or source.get('status') != 'verified' or not source.get('before') or not source.get('after')
            or sale['receipt'].get('inspect_action_id') != source.get('id')
            or not same_target(source.get('target'), inspection_target(sale['target']))):
        raise AutomationError('晶矿腾位出售缺少已核实的原查看与交易回执。')
    return basis


def _loot_sale_followup(scene, session, confidence):
    """The verified sale stays final even if its original loot is now unclear."""
    actions = session.get('actions', [])
    index = _loot_sale_index(actions)
    if index is None:
        return False
    basis = _verified_loot_sale(actions, index)
    if basis is None:
        return False
    if any(action.get('status') != 'verified' for action in actions[index+1:]):
        raise AutomationError('晶矿腾位出售后的阵容采集尚未核实。')
    _loot_sale_root(actions, index-1, basis)
    # A resumed run may need to rebuild its role observations. The role panel
    # can cover crystals, so only finish an already verified collection view.
    kind = observe(scene, confidence).page_kind
    if kind == 'character' and index < len(actions)-1 and actions[-1].get('action') in (
            'inspect_standard_unit', 'open_standard_equipment_recommendations'):
        return True
    from .currency_wars_match import read_match
    from .currency_wars_standard_hud import experience_observed
    from .currency_wars_node import loot_centers
    from .currency_wars_loot import loot_target
    state, receipt = read_match(scene, confidence), actions[index]['receipt']
    reason = '已保留出售回执；原晶矿、空位或备战读数尚未重新核实。'
    if (kind != 'preparation' or not state
            or (state.node, state.gold, state.hp, state.level) !=
                (receipt['node'], receipt['gold_after'], receipt['hp_after'], receipt['level_after'])
            or list(state.deployment or ()) != basis.get('deployment') or not experience_observed(scene, state, confidence)
            or (list(state.experience) if state.experience is not None else None) != basis.get('experience')
            or not _same_loot_centers(basis.get('crystals'), loot_centers(scene))):
        raise AutomationError(reason)
    try:
        same_board = _loot_sale_board(scene, session, index, receipt, confidence)
    except (AutomationError, AttributeError, KeyError, TypeError, ValueError) as error:
        raise AutomationError(reason) from error
    if not same_board:
        raise AutomationError(reason)
    loot_target(scene, confidence)
    return True


def next_action(scene, confidence=.65, *, session=None):
    """Re-derive only the exact in-flight proposal; never replay old unknown IO."""
    session = session or {}
    actions = session.get('actions', [])
    pending = actions[-1] if actions and actions[-1].get('status') == 'pending' else None
    prior = dict(session, actions=actions[:-1], rederiving_action=pending) if pending else session
    loot_sale = _loot_sale_followup(scene, prior, confidence)
    loot_box = _loot_waiting_box(prior.get('actions', []))
    _loot_reward_origin(prior)
    choice = _next_action(scene, confidence, session=prior, loot_box=loot_box)
    if loot_sale and choice.intent != 'collect_standard_loot' and choice.intent not in _LOOT_SALE_INSPECTIONS:
        raise AutomationError('晶矿腾位已核实，只允许重新采集阵容或领取当前晶矿。')
    if loot_box is not None and choice.intent != _LOOT_BOX_OPEN and choice.intent not in _LOOT_SALE_INSPECTIONS:
        raise AutomationError('晶矿备战箱待开启，只允许重新采集阵容或开启原槽。')
    if pending and (choice.intent != pending.get('action') or choice.expected != pending.get('expected')
                    or json.dumps(list(choice.payload),sort_keys=True,allow_nan=False)!=json.dumps(pending.get('target', []),sort_keys=True,allow_nan=False)):
        raise AutomationError('当前页面推导结果与已落盘意图不同，未替换或重放动作。')
    if (pending and choice.intent.startswith((ENVIRONMENT_SELECT, ENVIRONMENT_CONFIRM))
            and not environment_decision_matches(pending.get('decision'), choice.details)):
        raise AutomationError('当前投资环境效果与落盘意图不一致，未发送输入。')
    if pending and choice.intent == 'inspect_standard_sale_unit':
        if _loot_sale_source(pending) != _loot_sale_basis(scene, confidence, prior):
            raise AutomationError('晶矿腾位查看与原准备页来源不一致。')
    if pending and choice.intent == 'collect_standard_loot':
        if pending.get('loot_sale_action_id') != _loot_pickup_origin(scene, prior, confidence):
            raise AutomationError('晶矿领取与原落盘腾位来源不一致。')
    if pending and choice.intent == _LOOT_BOX_OPEN and (
            loot_box is not None or 'loot_box_pickup_action_id' in pending):
        if loot_box is None or not _loot_box_open_source(pending, loot_box):
            raise AutomationError('晶矿备战箱开启与原落盘领取来源不一致。')
    return choice


def _next_action(scene, confidence=.65, *, session=None, loot_box=None):
    from .currency_wars_standard_encounter import overlay_visible, proposal as encounter_proposal
    if session and session.get('node_attempt', {}).get('status') == 'encounter_pending':
        return encounter_proposal(scene, session, confidence)
    kind = observe(scene, confidence).page_kind
    if overlay_visible(scene, confidence, page_kind=kind):
        raise AutomationError('当前遭遇或过渡缺少本次继续回执，未选择或确认。')
    if session and session.get('node_attempt', {}).get('status') == 'intro_pending':
        from .currency_wars_standard_progress import progress_action
        return progress_action(scene, session, confidence)
    from .currency_wars_standard_popup import active_action as popup_action
    popup=popup_action(scene,session or {},confidence)
    if popup is not None:return popup
    from .currency_wars_standard_consumables import active_action as consumable_action
    consumable=consumable_action(scene,session or {},confidence)
    if consumable is not None:return consumable
    from .currency_wars_standard_investment import active_action as investment_action
    investment = investment_action(scene,session or {},confidence)
    if investment is not None:return investment
    from .currency_wars_standard_equipment import active_action as equipment_action
    equipment = equipment_action(scene,session or {},confidence)
    if equipment is not None:
        return equipment
    from .currency_wars_standard_sale import active_action as sale_action, same_target
    sale = sale_action(scene,session or {},confidence)
    if sale is not None:
        return sale
    from .currency_wars_standard_exchange import active_action
    verification = active_action(scene, session or {}, confidence)
    if verification is not None:
        return verification
    from .currency_wars_standard_rewards import active_action as reward_action
    reward = reward_action(scene,session or {},confidence)
    if reward is not None:
        return reward
    clean = trusted(scene, confidence)
    if difficulty_page(scene, confidence) and selected_rank(scene, confidence) == 40:
        return StandardAction('start_standard_a8_40', 'boss_preview',
                              unique(clean, '开始对局', (.75, .82, .99, .97)))
    if kind == 'shop':
        from .currency_wars_initial_shop import proposal as initial_shop_proposal
        initial_shop = initial_shop_proposal(scene, session or {}, confidence)
        if initial_shop is not None:
            return initial_shop
    from .currency_wars_standard_reorder import active as reordering,proposal as reorder_proposal
    if reordering(session or {}):
        if kind not in ('preparation','character'):
            raise AutomationError('全局整理尚未完成，只允许核实当前角色与移动。')
        if kind=='preparation':
            probe=_preparation_probe(scene,confidence,session.get('collection',{}).get('units'),session)
            if probe is not None:
                cell,target=probe
                return StandardAction('inspect_standard_unit','character',target,payload=(cell.zone,cell.slot,cell.node,cell.signature))
            from .currency_wars_standard_reorder import recommendation_probe
            recommendation=recommendation_probe(scene,session,confidence)
            if recommendation is not None:return recommendation
            return reorder_proposal(scene,session,confidence)
    from .currency_wars_standard_progress import progress_action
    progress = progress_action(scene, session or {}, confidence)
    if progress is not None:
        return progress
    if kind == 'boss_preview':
        return StandardAction('advance_standard_preview', 'plane_map',
                              unique(clean, '下一步', (.74, .87, .84, .95)))
    if kind == 'plane_map':
        return StandardAction('advance_standard_plane', 'environment',
                              unique(clean, '点击空白处继续', (.43, .86, .57, .93)))
    if kind == 'shop':
        from .currency_wars_standard_trading import purchase_action, shop_return_values
        from .currency_wars_standard_market import close_standard_shop
        last=(session or {}).get('actions',[])
        last=last[-1] if last else {}
        if last.get('action')=='refresh_standard_shop' and last.get('receipt',{}).get('bonus_xp',0)>0:
            payload,_=shop_return_values(scene,session,confidence)
            return StandardAction('close_standard_shop','standard_shop_closed',close_standard_shop(scene,session,confidence),payload=payload)
        purchase = purchase_action(scene, session or {}, confidence)
        if purchase is not None:
            return purchase
        from .currency_wars_standard_refresh import refresh_action
        refresh = refresh_action(scene,session or {},confidence)
        if refresh is not None:
            return refresh
        from .currency_wars_standard_market import close_standard_shop
        target = close_standard_shop(scene,session or {},confidence)
        payload, purchased = shop_return_values(scene, session, confidence)
        return StandardAction('close_standard_shop_after_purchase' if purchased else 'close_standard_shop',
                              'standard_shop_closed', target, payload=payload)
    if kind == 'environment':
        if scene.image is None:
            raise AutomationError('环境选择缺少当前图像，未发送输入。')
        expected_board = session.get('expected_board')
        later_plane = expected_board in ('2-1', '3-1')
        actions = session.get('actions', [])
        if later_plane:
            tail = actions[:-1] if actions and actions[-1].get('action', '').startswith(ENVIRONMENT_SELECT) else actions
            entrance = tail[-1] if tail else {}
            target = entrance.get('target')
            if (entrance.get('action') != 'advance_standard_next_plane' or entrance.get('status') != 'verified'
                    or entrance.get('expected') != 'standard_plane_entered'
                    or not isinstance(target, list) or len(target) != 3 or target[2] != expected_board):
                raise AutomationError('当前投资环境缺少已核实的后续位面入口，未选取或确认。')
            actions = actions[len(tail):]
        elif expected_board not in (None, '1-1') or any(
                action.get('action', '').startswith(ENVIRONMENT_CONFIRM) for action in actions):
            raise AutomationError('当前记录缺少新的初始环境来源，未重复选取或确认。')
        selection = next((action for action in reversed(actions)
                          if action.get('action', '').startswith(ENVIRONMENT_SELECT)), None)
        slot = None
        if selection is not None:
            slot = environment_selection_slot(selection['action'], selection.get('expected'))
            after = selection.get('after')
            if (selection is not actions[-1] or selection.get('status') != 'verified' or slot is None
                    or not isinstance(after, str) or not after.strip()
                    or selection.get('target', []) not in ([], [expected_board])):
                raise AutomationError('已有投资环境选择缺少同位面核实反馈，未重选或确认。')
        choice = standard_environment_choice(scene, confidence, slot=slot)
        if selection is not None and not environment_decision_matches(selection.get('decision'), choice.details):
            raise AutomationError('当前投资环境效果与已核实选取不一致，未确认。')
        board_target = (expected_board,) if expected_board else ()
        try:
            target = standard_environment_confirm(scene, choice, confidence)
        except AutomationError:
            if selection is not None:
                raise
            return StandardAction(ENVIRONMENT_SELECT+str(choice.slot), ENVIRONMENT_SELECTED+str(choice.slot),
                                  choice.name, choice.details, payload=board_target if later_plane else ())
        return StandardAction(ENVIRONMENT_CONFIRM+str(choice.slot), 'initial_board', target, choice.details,
                              payload=board_target)
    if kind == 'preparation':
        box_slot = _loot_box_board(scene, loot_box, confidence) if loot_box is not None else None
        initial = (session or {}).get('initial_environment')
        if initial and initial.get('post_choice_observation') is None:
            from .currency_wars_initial import validate_origin
            validate_origin(session, require_accepted=True)
            probe = _preparation_probe(scene, confidence, session.get('collection', {}).get('units'), session)
            if probe is None:
                raise AutomationError('初始环境确认后的当前阵容尚未留证，未领取掉落、开箱或交易。')
            cell, target = probe
            return StandardAction('inspect_standard_unit', 'character', target,
                                  payload=(cell.zone, cell.slot, cell.node, cell.signature))
        from .currency_wars_node import loot_centers
        if 'strategy' in (session or {}) and (loot_centers(scene) or any(
                normalize(t.text)=='开启' and t.within((.18,.78,.80,.92)) for t in clean.tokens)):
            probe = _preparation_probe(scene,confidence,session.get('collection',{}).get('units'),session)
            if probe is not None:
                cell,target = probe
                return StandardAction('inspect_standard_unit','character',target,
                                      payload=(cell.zone,cell.slot,cell.node,cell.signature))
        if 'strategy' in (session or {}):
            from .currency_wars_standard_rewards import open_bench_action
            opening = open_bench_action(scene,session,confidence,slot=box_slot)
            if opening is not None:return opening
        from .currency_wars_loot import loot_target
        if loot_centers(scene):
            from .currency_wars_collector import roster_cells
            bench = [cell for cell in roster_cells(scene,confidence) if cell.zone=='bench']
            # Capacity handling requires all nine currently owned bench cells.
            if len(bench)==9 and {cell.slot for cell in bench}==set(range(1,10)) and all(cell.state=='occupied' for cell in bench):
                from .currency_wars_standard_deployment import standard_deployment, POLICY
                deployment = standard_deployment(scene,session or {},confidence)
                if deployment is not None:
                    plan,unit,score,payload = deployment
                    return StandardAction('deploy_standard_owned','standard_owned_deployed',plan,
                                          details=(unit.name,unit.star,unit.tier,plan.zone,score,POLICY),payload=payload)
                from .currency_wars_match import read_match
                state = read_match(scene, confidence)
                if ('strategy' in (session or {}) and state and state.deployment
                        and state.deployment[0] == state.deployment[1]
                        and (state.node in session.get('shop_observed_nodes', [])
                             or _loot_sale_continuation(scene, state, session, confidence) is not None)):
                    from .currency_wars_standard_sale import proposal as sale_proposal
                    sale = sale_proposal(scene, session, confidence)
                    if sale is not None and sale.intent == 'inspect_standard_sale_unit':
                        return sale
            x, y, radius = loot_target(scene, confidence)
            return StandardAction('collect_standard_loot', 'loot_collected',
                                  Token('已核实奖励晶矿', 1., (x-radius,y-radius*16/9,x+radius,y+radius*16/9)),
                                  payload=(x,y,radius))
        probe = _preparation_probe(scene,confidence,(session or {}).get('collection',{}).get('units'),session)
        if probe is None:
            from .currency_wars_standard_market import open_standard_shop
            from .currency_wars_match import read_match
            state = read_match(scene,confidence)
            if 'strategy' in (session or {}):
                from .currency_wars_standard_sale import proposal as sale_proposal
                sale = sale_proposal(scene,session,confidence)
                if sale is not None:
                    return sale
            if state.node in (session or {}).get('shop_observed_nodes',[]):
                if 'strategy' in (session or {}) and state.deployment and state.deployment[0] == state.deployment[1]:
                    from .currency_wars_standard_exchange import exchange_proposal
                    exchange = exchange_proposal(scene, session, confidence)
                    if exchange is not None:
                        return exchange
                    reorder=reorder_proposal(scene,session,confidence)
                    if reorder is not None:return reorder
                from .currency_wars_standard_deployment import standard_deployment, POLICY
                deployment = standard_deployment(scene,session or {},confidence)
                if deployment is None:
                    if 'strategy' in (session or {}):
                        from .currency_wars_standard_trading import experience_action
                        experience = experience_action(scene, session, confidence)
                        if experience is not None:
                            return experience
                        from .currency_wars_standard_equipment import proposal as equipment_proposal
                        equipment = equipment_proposal(scene,session,confidence)
                        if equipment is not None:
                            return equipment
                        from .currency_wars_standard_consumables import proposal as consumable_proposal
                        consumable=consumable_proposal(scene,session,confidence)
                        if consumable is not None:return consumable
                    attempt = (session or {}).get('node_attempt',{})
                    actions = (session or {}).get('actions',[])
                    inflight = (session or {}).get('rederiving_action') or (actions[-1] if actions else {})
                    own_pending = bool(inflight.get('action')=='start_standard_node'
                                       and inflight.get('status')=='pending'
                                       and attempt.get('start_action_id')==inflight.get('id')
                                       and attempt.get('status')=='start_pending')
                    if attempt.get('node')==state.node and not own_pending:
                        raise AutomationError('本节点已有出战提交，未重复出战。')
                    from .currency_wars_standard_encounter_battle import proposal as encounter_start
                    encounter = encounter_start(scene, session, state, confidence)
                    if encounter is not None:
                        return encounter
                    from .currency_wars_node import start_target
                    return StandardAction('start_standard_node','standard_node_entered',start_target(scene,confidence),
                                          payload=(state.node,state.gold,state.hp,state.level))
                plan,unit,score,payload = deployment
                return StandardAction('deploy_standard_owned','standard_owned_deployed',plan,
                                      details=(unit.name,unit.star,unit.tier,plan.zone,score,POLICY),payload=payload)
            target = open_standard_shop(scene,session or {},confidence)
            return StandardAction('open_standard_shop','standard_shop_observe',target,
                                  payload=(state.node,state.gold,state.hp,state.level))
        cell, target = probe
        return StandardAction('inspect_standard_unit', 'character', target,
                              payload=(cell.zone,cell.slot,cell.node,cell.signature))
    if kind == 'character':
        from .currency_wars_standard_collection import stale,close_action,profile as current_profile,close_current
        if stale(session or {}):return close_action(scene,session or {},confidence)
        profile = current_profile(scene,session,confidence)
        key = profile.zone+':'+str(profile.slot)
        record = (session or {}).get('collection',{}).get('units',{}).get(key)
        if not record or not same_target(record.get('unit'), asdict(profile)):
            raise AutomationError('当前角色信息尚未记入本次采集，未关闭面板。')
        if 'strategy' in (session or {}) and profile.zone != 'bench' and 'recommendations' not in record:
            return StandardAction('open_standard_equipment_recommendations','standard_equipment_recommendations',
                                  unique(clean,'装备推荐',(.72,.70,.85,.80)),
                                  payload=(profile.zone,profile.slot,profile.name,record['signature']))
        return close_current(scene,session,confidence)
    raise AutomationError('标准对局当前页面需要局面采集或新动作校准：' + kind)


def evidence(c, scene, label):
    from .currency_wars_replay import save_sample
    screenshot = c.evidence(scene, label)
    save_sample(scene, screenshot, stage='entry')
    return str(screenshot)


def transition_ready(choice, scene, confidence=.65, *, before=None, session=None):
    if choice.expected == 'standard_initial_shop_closed':
        from .currency_wars_initial_shop import feedback
        return session is not None and feedback(choice, scene, session, confidence, before=before)
    from .currency_wars_defeat import INTENTS as DEFEAT_INTENTS,feedback as defeat_feedback
    if choice.intent in DEFEAT_INTENTS:return session is not None and defeat_feedback(choice,scene,session,confidence)
    if choice.expected in ('standard_movement_star_selected','standard_movement_star_returned','standard_popup_unit_board'):
        from .currency_wars_standard_popup import feedback
        return session is not None and feedback(choice,scene,session,confidence)
    if choice.expected=='standard_supply_refreshed':
        from .currency_wars_standard_supply_refresh import feedback
        return before is not None and session is not None and feedback(choice,before,scene,session,confidence)
    if choice.expected in ('standard_consumable_applied','standard_consumable_returned'):
        from .currency_wars_standard_consumables import feedback
        return before is not None and session is not None and feedback(choice,before,scene,session,confidence)
    if choice.expected=='standard_consumable_board':
        from .currency_wars_standard_consumables import board_ready
        try:return session is not None and board_ready(scene,session['consumable'],confidence)
        except (AutomationError,KeyError):return False
    if choice.expected in ('standard_stale_unit_board','standard_collected_unit_board'):
        from .currency_wars_standard_collection import board_feedback
        return board_feedback(choice,scene,confidence,session=session)
    if choice.expected in ('standard_investment_selected','standard_investment_applied'):
        from .currency_wars_standard_investment import feedback
        return session is not None and feedback(choice,scene,session,confidence)
    if choice.expected == 'standard_investment_refreshed':
        from .currency_wars_standard_investment_refresh import feedback
        return session is not None and feedback(choice,before,scene,session,confidence) is not None
    if choice.expected == 'standard_investment_shop_closed':
        from .currency_wars_standard_investment import shop_return_feedback
        return session is not None and shop_return_feedback(choice, scene, session, confidence) is not None
    if choice.expected=='standard_reward_opened':
        from .currency_wars_standard_investment import box_opening_page
        from .currency_wars_standard_rewards import PAGES
        from .currency_wars_match import read_match
        box_page = box_opening_page(session, choice)
        state = read_match(scene,confidence,include_rewards=True)
        if state is None or state.node != choice.payload[0]:
            return False
        return state.page == box_page if box_page else state.page in PAGES-{'supply_selection'}
    if choice.expected in ('standard_reward_returned','standard_supply_selected'):
        from .currency_wars_standard_rewards import feedback
        return before is not None and session is not None and feedback(choice,before,scene,session,confidence)
    if choice.expected=='standard_reward_unit_board':
        from .currency_wars_standard_rewards import board_ready
        try:return session is not None and board_ready(scene,session['reward'],confidence)
        except AutomationError:return False
    if choice.expected == 'standard_equipment_inspectable':
        from .currency_wars_standard_equipment import inspectable
        return before is not None and inspectable(choice,before,scene,confidence)
    if choice.expected == 'standard_equipment_board':
        from .currency_wars_standard_equipment import _board
        try:
            return bool(session and _board(scene,session['equipment'],confidence))
        except (AutomationError,KeyError):
            return False
    if choice.expected == 'standard_equipment_recommendations':
        from .currency_wars_equipment_catalog import recommendation_visible
        from .currency_wars_collector import owned_profile
        try:
            profile = owned_profile(scene,(session or {}).get('inspecting'),confidence)
            return recommendation_visible(scene,confidence) and (profile.zone,profile.slot,profile.name)==choice.payload[:3]
        except AutomationError:
            return False
    if choice.expected in ('standard_sale_panel','standard_field_sale_panel'):
        from .currency_wars_standard_sale import panel_feedback
        return before is not None and panel_feedback(choice,before,scene,confidence)
    if choice.expected == 'standard_sale_cancelled':
        from .currency_wars_standard_sale import cancelled_feedback
        return session is not None and cancelled_feedback(scene,session,confidence)
    if choice.expected in ('standard_exchange_inspectable','standard_relocate_inspectable'):
        from .currency_wars_standard_exchange import inspectable
        return before is not None and inspectable(choice, before, scene, confidence)
    if choice.expected == 'standard_exchange_board':
        from .currency_wars_match import read_match
        state = read_match(scene,confidence)
        return bool(state and state.page == 'preparation'
                    and (state.node,state.gold,state.hp,state.level) == choice.payload[:4]
                    and state.deployment == choice.payload[4:6])
    from .currency_wars_standard_ledger import FINANCIAL_ACTIONS
    if choice.intent in FINANCIAL_ACTIONS:
        from .currency_wars_standard_trading import financial_feedback
        return before is not None and financial_feedback(choice, before, scene, confidence,session=session) is not None
    if choice.expected in ('standard_node_advanced', 'standard_boss_intro_closed'):
        from .currency_wars_standard_progress import node_progress_feedback
        return node_progress_feedback(choice, scene, confidence) is not None
    if choice.expected == 'standard_plane_entered':
        return observe(scene, confidence).page_kind in ('environment', 'investment_selection')
    if choice.expected == 'standard_arrival_shop_closed':
        from .currency_wars_match import read_match
        state = read_match(scene, confidence)
        return bool(state and state.page == 'preparation' and (state.node, state.gold, state.level) == choice.payload[:3]
                    and state.hp is not None and state.hp > 0)
    if choice.expected == 'standard_node_entered':
        from .currency_wars_standard_node import entry_feedback
        return entry_feedback(scene,choice.payload[0],confidence)
    if choice.expected == 'standard_owned_deployed':
        from .currency_wars_standard_deployment import deployment_feedback
        return bool(before is not None and deployment_feedback(before,scene,choice.target,confidence)['status']=='verified')
    if choice.expected == 'standard_shop_closed':
        from .currency_wars_match import read_match
        state = read_match(scene,confidence)
        return bool(state and state.page=='preparation'
                    and (state.node,state.gold,state.hp,state.level)==choice.payload[:4]
                    and (len(choice.payload)==4 or (state.experience or (0,0))==choice.payload[4:6]))
    if choice.expected == 'standard_shop_observe':
        from .currency_wars_match import read_match
        state = read_match(scene,confidence)
        node,gold,hp,level = choice.payload
        return bool(state and state.page=='shop' and (state.node,state.gold,state.level)==(node,gold,level)
                    and state.hp in (None,hp))
    if choice.expected == 'loot_collected':
        from .currency_wars_loot import loot_feedback
        result = loot_feedback(before,scene,choice.payload,confidence) if before is not None else None
        if result=='choice_opened' and session is not None:
            from .currency_wars_match import read_match
            source = session.get('actions',[{}])[-1].get('reward_basis')
            state = read_match(scene,confidence,include_rewards=True)
            if source and (not state or state.node!=source['node']):return False
        return result in ('disappeared','choice_opened')
    if choice.expected.startswith(ENVIRONMENT_SELECTED):
        slot = environment_selection_slot(choice.intent, choice.expected)
        if slot is None:
            return False
        try:
            picked = standard_environment_choice(scene, confidence, slot=slot)
            if not environment_decision_matches(environment_decision(choice.details), picked.details):
                return False
            standard_environment_confirm(scene, picked, confidence)
        except (AutomationError, TypeError, ValueError):
            return False
        return True
    if choice.expected == 'initial_board':
        from .currency_wars_match import read_match
        state = read_match(scene, confidence)
        expected_node = choice.payload[0] if choice.payload else '1-1'
        return bool(state and state.node == expected_node and state.page in ('shop','preparation'))
    return observe(scene, confidence).page_kind == choice.expected


def run_standard(c):
    from .currency_wars_defeat import INTENTS as DEFEAT_INTENTS
    from .currency_wars_standard_investment import (
        CLOSE_SHOP as INVESTMENT_SHOP_CLOSE, CONFIRM as INVESTMENT_CONFIRM,
        confirmation_board, observe_automatic_shop, shop_return_feedback,
    )
    from .currency_wars_standard_investment_refresh import ACTION as INVESTMENT_REFRESH, BINDING as INVESTMENT_REFRESH_BINDING
    from .currency_wars_standard_ledger import FINANCIAL_ACTIONS
    from .currency_wars_standard_progress import BOSS_INTRO_ACTION, boss_destination, node_progress_feedback
    from .currency_wars_standard_encounter import (
        INTENTS as ENCOUNTER_INTENTS, OFFER as ENCOUNTER_OFFER, bind_input as bind_encounter,
        commit_feedback as commit_encounter, continuation_feedback as encounter_after_continue,
        feedback as encounter_feedback, record_start as record_encounter_start,
    )
    from .currency_wars_standard_encounter_battle import bind_input as bind_encounter_followup, feedback as encounter_followup_feedback
    from .currency_wars_standard_encounter_notice import begin as watch_encounter_reward
    from .currency_wars_standard_double_supply import (
        INPUT as DOUBLE_SUPPLY_INPUT, commit_feedback as commit_double_supply, feedback_key as double_supply_key,
        hold_delivery_sources, same_journal as same_supply_journal,
    )
    if c.report.operation != 'currency_wars_standard':
        raise AutomationError('标准对局开发须使用独立入口。')
    # This initial path is intentionally not an acceptance counter. Any repair
    # or development continuation is recorded separately from ten frozen runs.
    store = StandardSession(Path(c.report.run_dir).parent/'currency-standard-session.json')
    c.currency_standard_session = store
    loop_guard = getattr(c.runner, 'currency_loop_guard', None)
    if loop_guard is not None:
        loop_guard.require_access(store.data,c.runner.currency_resume)
    else:
        require_session_access(store.data,c.runner.currency_resume)
    from .currency_wars_standard_policy import STRATEGIES
    from .currency_wars_names import resolve_name
    requested_strategy = getattr(c.runner, 'currency_strategy', None)
    strategy = (store.data or {}).get('strategy',requested_strategy or 'default')
    if strategy not in STRATEGIES or requested_strategy is not None and requested_strategy != strategy:
        raise AutomationError('本次策略与已记录对局不同，未中途改写策略。')
    remembrance_name=resolve_name(c.settings,getattr(c.runner,'currency_remembrance_name',None),store.data,resume=c.runner.currency_resume)
    from .currency_wars_equipment_mode import resolve_fast_mode,FAST_FIELD
    fast_mode=resolve_fast_mode(c.settings,getattr(c.runner,'currency_fast_mode',None),store.data,resume=c.runner.currency_resume)
    if c.runner.currency_resume:
        store.data.setdefault('continuations', []).append(str(c.report.run_dir))
        store.persist()
    else:
        result = locate(c)
        entry = c.report.currency_wars
        if not entry.get('rank_verified'):
            return result
        if store.data is None:
            store.begin(c.report.run_dir, entry)
    store.data['strategy'] = strategy
    store.data['remembrance_name']=remembrance_name
    store.data[FAST_FIELD]=fast_mode
    store.persist()
    if loop_guard is not None:
        loop_guard.bind(store)
    c.report.currency_wars = store.data
    guard = CurrencyWarsWorkflow(c)
    scene = c.snapshot()
    from .currency_wars_standard_budget import StandardBudget
    from .currency_wars_session import MAX_ACTIONS
    budget=StandardBudget(store.data)
    refresh_investment = False
    for _ in range(MAX_ACTIONS+1):
        c.checkpoint()
        if store.data['completion_verified'] or store.data.get('defeat_settlement_verified'):
            break
        guard._require_current_scene(scene)
        if (store.data.get('account_verified_run') != c.report.run_dir or
                store.data.get('account_verified_epoch') != c.runner.input_epoch):
            from .currency_wars_identity import bind_account, refresh_client
            bind_account(store,scene,c.report.run_dir,c.runner.input_epoch,max(.85,c.settings.ocr_confidence))
            refresh_client(store,getattr(getattr(c,'window',None),'path',None),c.report.run_dir,c.runner.input_epoch)
            c.log('标准对局来源：账号一致；客户端安装版本' +
                  store.data.get('client',{}).get('full_version','仍未知') + '。')
            guard._require_current_scene(scene)
        if store.data['actions'] and store.data['actions'][-1]['status'] != 'verified':
            # Only this read-only UI transition may be reconciled here. It
            # never resends the prior click and cannot settle a paid action.
            previous = store.data['actions'][-1]
            payload = tuple(previous.get('target',()))
            before = store.data.get('pre_shop_snapshot',{})
            if (previous['action'] != 'open_standard_shop' or previous.get('expected') != 'standard_shop_observe'
                    or payload != tuple(before.get(name) for name in ('node','gold','hp','level'))
                    or not transition_ready(StandardAction(previous['action'],previous['expected'],None,payload=payload),
                                            scene,c.settings.ocr_confidence)):
                raise AutomationError('上次标准动作尚未核实，未重放输入或继续交易。')
            previous.update(original_status=previous['status'],status='verified',
                            reconciliation='observed_shop_without_input',resolved_run=c.report.run_dir,
                            reconciled_after=evidence(c,scene,'currency_standard_shop_reconciled'))
            store.data.update(action_status='readonly_reconciled',screenshot=previous['reconciled_after'])
            store.persist()
            c.log('已观察核实上次打开标准商店，本次没有重发开店点击。')
        limited=budget.check(store.data)
        if limited:
            store.data.update(action_status='step_limit',reason=limited)
            store.persist();break
        kind = observe(scene,c.settings.ocr_confidence).page_kind
        if store.data.get('node_attempt', {}).get('status') == 'intro_pending' and kind != 'boss_intro':
            store.data.update(action_status='needs_observation', page_kind=kind,
                              reason='强敌介绍待关闭，当前画面未核实，已保留原节点。',
                              screenshot=evidence(c, scene, 'currency_standard_boss_intro_wait'))
            store.persist()
            break
        collection = store.data.get('collection',{})
        if collection.get('run_dir') != c.report.run_dir or collection.get('input_epoch') != c.runner.input_epoch:
            collection = dict(run_dir=c.report.run_dir,input_epoch=c.runner.input_epoch,units={},complete=False)
            store.data['collection'] = collection
            store.persist()
        # A resumed confirmation can briefly show the board before the shop opens.
        if store.data['actions'] and store.data['actions'][-1]['action'] == INVESTMENT_CONFIRM:
            scene = observe_automatic_shop(c, store, scene, refresh=refresh_investment)
            refresh_investment = False
            kind = observe(scene, c.settings.ocr_confidence).page_kind
        if kind=='shop':
            from .currency_wars_initial_shop_observation import ensure as observe_initial_shop
            scene=observe_initial_shop(c,store,scene)
            kind=observe(scene,c.settings.ocr_confidence).page_kind
        if kind in ('battle','node_result','node_loss','final_victory','match_defeat') and store.data.get('exchange',{}).get('status','verified') == 'verified':
            from .currency_wars_standard_node import observe_started_node
            scene, verified = observe_started_node(c,store,scene)
            if not verified:
                break
            kind = observe(scene,c.settings.ocr_confidence).page_kind
        if kind == 'preparation':
            try:
                collection['complete'] = _preparation_probe(scene,c.settings.ocr_confidence,collection['units'],store.data) is None
            except AutomationError:
                collection['complete'] = False
            store.persist()
            initial = store.data.get('initial_environment')
            if initial and initial.get('post_choice_observation') is None and collection['complete']:
                from .currency_wars_initial import capture_current
                observation = capture_current(store.data, scene,
                    evidence=evidence(c, scene, 'currency_standard_initial_post_choice'),
                    run_dir=c.report.run_dir, epoch=c.runner.input_epoch, confidence=c.settings.ocr_confidence)
                store.persist()
                if observation is not None:
                    c.log('初始环境：确认后当前阵容已留证；库存' +
                          ('完整' if observation['inventory_complete'] else '仍有未读格') +
                          '，环境声明交付仍未归因。')
            from .currency_wars_standard_rewards import verify_unit
            verifying_reward = store.data.get('reward',{}).get('status')=='unit_verifying'
            with hold_delivery_sources(store.data):
                problem = verify_unit(store.data,scene,c.runner.input_epoch,c.settings.ocr_confidence)
                store.persist()
            if problem:raise AutomationError(problem)
            if verifying_reward and store.data.get('reward',{}).get('status')=='verified':c.checkpoint()
            from .currency_wars_investment_units import verify as verify_investment_units
            verifying_investment=store.data.get('investment',{}).get('status')=='unit_verifying'
            problem=verify_investment_units(store.data,scene,c.runner.input_epoch,c.settings.ocr_confidence)
            store.persist()
            if problem:raise AutomationError(problem)
            if verifying_investment and store.data.get('investment',{}).get('status')=='verified':c.checkpoint()
            from .currency_wars_standard_consumables import verify as verify_consumable
            verifying_consumable=store.data.get('consumable',{}).get('status')=='verifying'
            problem=verify_consumable(store.data,scene,c.runner.input_epoch,c.settings.ocr_confidence)
            store.persist()
            if problem:raise AutomationError(problem)
            if verifying_consumable and store.data.get('consumable',{}).get('status')=='verified':c.checkpoint()
            from .currency_wars_standard_reorder import advance as advance_reorder
            if advance_reorder(store.data,scene,c.settings.ocr_confidence):
                store.persist();c.checkpoint()
        from .currency_wars_standard_exchange import panel_stale, record_profile
        from .currency_wars_standard_sale import stale as sale_stale
        from .currency_wars_standard_equipment import panel_stale as equipment_stale, record_profile as equipment_profile
        from .currency_wars_standard_rewards import panel_stale as reward_stale
        from .currency_wars_standard_consumables import panel_stale as consumable_stale
        from .currency_wars_standard_collection import stale as collection_stale,ordinary,profile as current_profile
        from .currency_wars_standard_popup import panel_stale as popup_stale,profile as popup_profile,require_panel_account
        if kind == 'character' and not panel_stale(store.data) and not sale_stale(store.data) and not equipment_stale(store.data) and not reward_stale(store.data) and not consumable_stale(store.data) and not collection_stale(store.data) and not popup_stale(store.data):
            require_panel_account(scene,store.data,c.settings.ocr_confidence)
            from .currency_wars_collector import owned_profile
            try:
                profile = (current_profile(scene,store.data,c.settings.ocr_confidence) if ordinary(store.data)
                    else owned_profile(scene,store.data.get('inspecting'),c.settings.ocr_confidence))
            except AutomationError:
                pass  # next_action records the exact missing field below.
            else:
                inspecting = store.data['inspecting']
                profile_source = evidence(c,scene,'currency_standard_owned_'+str(profile.slot))
                previous = collection['units'].get(profile.zone+':'+str(profile.slot),{})
                previous = previous if previous.get('signature')==inspecting['signature'] else {}
                collection['units'][profile.zone+':'+str(profile.slot)] = dict(previous,unit=asdict(profile),
                    signature=inspecting['signature'],node=inspecting['node'],
                    source=profile_source,input_epoch=c.runner.input_epoch,run_dir=c.report.run_dir,
                    inspection_action_id=inspecting.get('inspection_action_id'))
                problem = record_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch)
                problem = problem or equipment_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch)
                from .currency_wars_worn_reforge import record_profile as worn_reforge_profile
                problem = problem or worn_reforge_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch)
                problem = problem or popup_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch,scene,c.settings.ocr_confidence)
                store.persist()
                if problem:
                    raise AutomationError(problem)
                c.log(f'阵容采集：{profile.zone}:{profile.slot} {profile.name}，{profile.star}星、{profile.tier}费；已读{len(collection["units"])}张。')
        from .currency_wars_standard_investment import enter as investment_enter
        if kind=='investment_selection' and (not store.data.get('investment') or store.data['investment'].get('status')=='verified'):
            investment_enter(store.data,scene,c.settings.ocr_confidence)
            store.persist()
        try:
            choice = next_action(scene, c.settings.ocr_confidence,session=store.data)
        except AutomationError as error:
            from .currency_wars_collector import collected_snapshot
            if kind == 'preparation':
                try:
                    collection['complete'] = _preparation_probe(scene,c.settings.ocr_confidence,collection['units'],store.data) is None
                except AutomationError:
                    collection['complete'] = False
            current = collected_snapshot(scene,store.data,c.runner.input_epoch,'standard_current',c.settings.ocr_confidence)
            from .currency_wars_planner import OfflineProvider, candidates
            store.data.update(action_status='needs_observation', reason=str(error),
                              page_kind=observe(scene, c.settings.ocr_confidence).page_kind,
                              strategy_snapshot=asdict(current),
                              strategy_candidates=[asdict(candidate) for candidate in candidates(current)],
                              strategy_decision=asdict(OfflineProvider().decide(current)),
                              screenshot=evidence(c, scene, 'currency_standard_observe'))
            if current.roster_complete:
                c.log(f'完整阵容已核实：{len(current.roster)}张角色，备战{current.bench_occupied}/{current.bench_capacity}；缺失事实继续由离线决策要求补充。')
            store.persist()
            break
        if choice.intent == 'start_standard_a8_40' and (store.data['status'] != 'start_pending' or store.data['actions']):
            raise AutomationError('已有标准开局提交，未开始第二个对局。')
        if choice.intent == 'start_standard_a8_40' and getattr(c.runner, 'currency_loop_guard', None) is not None:
            c.runner.currency_loop_guard.require_start()
        if choice.intent == 'open_standard_shop':
            from .currency_wars_collector import collected_snapshot
            from .currency_wars_standard_trading import bench_signatures
            store.data['pre_shop_snapshot'] = asdict(collected_snapshot(scene,store.data,c.runner.input_epoch,
                                                       'before_standard_shop',c.settings.ocr_confidence))
            store.data['pre_shop_bench'] = bench_signatures(scene)
            store.persist()
        investment_shop = (store.data['investment']['shop_observations'][-1]
                           if choice.intent == INVESTMENT_SHOP_CLOSE else None)
        before_path = (investment_shop['frames'][-1]['evidence'] if investment_shop is not None
                       else evidence(c, scene, 'currency_standard_'+choice.intent))
        action = store.pending(choice.intent, c.runner.input_epoch, before_path, choice.expected)
        if choice.intent == 'deploy_standard_owned':
            action['decision'] = dict(name=choice.details[0],star=choice.details[1],tier=choice.details[2],
                                      zone=choice.details[3],score=choice.details[4],policy=choice.details[5])
            store.persist()
        elif choice.intent in FINANCIAL_ACTIONS or choice.intent in ('inspect_standard_sale_unit','inspect_standard_field_sale_unit'):
            action['decision'] = dict(strategy=choice.details[0], score=choice.details[1],
                                      reasons=list(choice.details[2]), policy=choice.details[3])
            store.persist()
        elif choice.intent in ('stage_standard_exchange','stage_standard_relocate'):
            action['decision'] = dict(source=choice.details[0],target=choice.details[1],
                                      improvement=choice.details[2],policy=choice.details[3])
            store.persist()
        elif choice.intent == 'stage_standard_equipment':
            action['decision'] = dict(name=choice.details[0],item=choice.details[1],expected=list(choice.details[2]),
                                      reason=choice.details[3],policy=choice.details[4])
            store.persist()
        elif choice.intent=='stage_standard_consumable':
            action['decision']=dict(item=choice.details[0],effect=choice.details[1],name=choice.details[2],policy=choice.details[3])
            store.persist()
        elif choice.intent=='refresh_standard_supply':
            need_kind, names = choice.details[2]
            action['decision']=dict(strategy=choice.details[0],remaining=choice.details[1],need=[need_kind,list(names)],policy=choice.details[3])
            store.persist()
        elif choice.intent in ('choose_standard_reward','select_standard_supply','confirm_standard_supply'):
            action['decision'] = dict(name=choice.details[0],item=choice.details[1],unit=choice.details[2],
                                      gold=choice.details[3],policy=choice.details[4])
            if len(choice.payload)==11:
                action['decision'].update(selection_count=choice.payload[9],expected_tier=choice.payload[10])
            store.persist()
        elif choice.intent in ('select_standard_investment','confirm_standard_investment'):
            action['decision']=dict(name=choice.details[0],kind=choice.details[1],parameters=dict(choice.details[2]),policy=choice.details[3])
            from .currency_wars_standard_investment import bind_selection
            bind_selection(store.data,choice,scene,c.runner.input_epoch,c.report.run_dir,c.settings.ocr_confidence)
            store.persist()
        elif choice.details:
            action['decision'] = environment_decision(choice.details[:7])
            store.persist()
        if choice.payload:
            action['target'] = list(choice.payload)
            store.persist()
        if investment_shop is not None:
            action['investment_shop_observation'] = deepcopy(investment_shop)
            store.persist()
        if choice.intent == INVESTMENT_REFRESH:
            from .currency_wars_standard_investment_refresh import bind_intent as bind_investment_refresh
            bind_investment_refresh(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent.startswith(ENVIRONMENT_CONFIRM) and choice.payload in ((), ('1-1',)):
            from .currency_wars_initial import begin as begin_initial
            begin_initial(store.data, action['id'], run_dir=c.report.run_dir, epoch=c.runner.input_epoch)
            store.persist()
        if choice.intent == 'close_standard_initial_shop':
            from .currency_wars_initial_shop import bind_intent as bind_initial_shop
            bind_initial_shop(store.data, choice, scene, c.settings.ocr_confidence)
            store.persist()
        if choice.intent=='inspect_standard_unit':
            from .currency_wars_standard_collection import bind_inspection
            bind_inspection(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        from .currency_wars_standard_popup import bind_move,bind_intent as bind_popup
        bind_move(store.data,choice,scene,c.settings.ocr_confidence)
        bind_popup(store.data,choice,scene,c.settings.ocr_confidence)
        if choice.intent in ('deploy_standard_owned','stage_standard_exchange','stage_standard_relocate','select_standard_movement_star','confirm_standard_movement_star','inspect_standard_popup_unit','close_standard_popup_unit','close_standard_popup_stale_panel'):
            store.persist()
        if choice.intent=='refresh_standard_supply':
            from .currency_wars_standard_supply_refresh import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent in ('select_standard_supply','confirm_standard_supply'):
            from .currency_wars_standard_supply_refresh import bind_choice
            bind_choice(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent in ('stage_standard_exchange','stage_standard_relocate','inspect_standard_exchange_unit'):
            from .currency_wars_standard_exchange import record_intent
            record_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent in ('inspect_standard_sale_unit','inspect_standard_field_sale_unit'):
            from .currency_wars_standard_sale import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            if choice.intent == 'inspect_standard_sale_unit':
                basis = _loot_sale_basis(scene, c.settings.ocr_confidence,
                                         dict(store.data, actions=store.data['actions'][:-1]))
                if basis is not None:
                    action['loot_sale_basis'] = basis
                    action['decision']['loot_sale_basis_sha256'] = _loot_sale_digest(basis)
            store.persist()
        if choice.intent == 'stage_standard_equipment':
            from .currency_wars_standard_equipment import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent=='stage_standard_consumable':
            from .currency_wars_standard_consumables import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent == 'inspect_standard_equipment_unit':
            store.data['equipment']['inspection_attempts'] += 1
            store.persist()
        if choice.intent == 'start_standard_node':
            store.data['node_attempt'] = dict(node=choice.payload[0],start_action_id=action['id'],
                                              status='start_pending',node_verified=False,battle_observed=False)
            record_encounter_start(store.data, action, scene, 'before', c.report.run_dir,
                                   c.runner.input_epoch, c.settings.ocr_confidence)
            store.persist()
        encounter_followup = choice.encounter_arrival is not None
        if encounter_followup:
            bind_encounter_followup(store.data, choice, scene, c.report.run_dir, c.runner.input_epoch)
        encounter_input = encounter_followup or bind_encounter(store.data, choice, scene, c.report.run_dir, c.runner.input_epoch)
        if encounter_input:
            store.persist()
        investment_box = False
        loot_click = choice.intent == 'collect_standard_loot'
        loot_crystals = loot_remaining = None
        loot_box = None
        if choice.intent in ('start_standard_node','collect_standard_loot','open_standard_bench_reward'):
            from .currency_wars_standard_rewards import bind_source
            from .currency_wars_standard_investment import bind_reward, box_opening_page
            bind_source(store.data,choice,scene,c.settings.ocr_confidence)
            bind_reward(store.data,choice)
            investment_box = box_opening_page(store.data,choice) is not None
            if loot_click:
                from .currency_wars_node import loot_centers
                loot_crystals = [list(center) for center in loot_centers(scene)]
                loot_remaining = _loot_remaining(loot_crystals, choice.payload)
                origin = _loot_pickup_origin(scene, dict(store.data, actions=store.data['actions'][:-1]),
                                             c.settings.ocr_confidence)
                if origin is not None:
                    action['loot_sale_action_id'] = origin
            elif choice.intent == _LOOT_BOX_OPEN:
                loot_box = _loot_waiting_box(store.data['actions'][:-1])
                if loot_box is not None:
                    action['loot_box_pickup_action_id'] = loot_box['id']
            store.persist()
        if choice.intent in ('close_standard_unit','close_standard_stale_unit'):
            from .currency_wars_standard_collection import bind_close
            bind_close(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        c.report.currency_wars = store.data
        c.log('标准A8-40开发：' + choice.intent)
        loot_pickup = 'loot_sale_action_id' in action
        loot_claim = _loot_reward_origin(store.data) if choice.intent == 'choose_standard_reward' else None
        defeat_step = choice.intent in DEFEAT_INTENTS
        closing_intro = choice.intent == BOSS_INTRO_ACTION
        node_progress = closing_intro or choice.intent == 'continue_standard_node'
        encounter_step = choice.intent in ENCOUNTER_INTENTS
        boss_progress = node_progress and boss_destination(choice.payload[0]) is not None
        loss_progress = choice.intent == 'continue_standard_node' and store.data['node_attempt'].get('node_loss_verified') is True
        investment_confirmation = choice.intent == INVESTMENT_CONFIRM
        closing_investment_shop = choice.intent == INVESTMENT_SHOP_CLOSE
        refreshing_investment = choice.intent == INVESTMENT_REFRESH
        investment_progress = investment_confirmation or closing_investment_shop or refreshing_investment
        double_supply_step = DOUBLE_SUPPLY_INPUT in action
        environment_step = choice.intent.startswith((ENVIRONMENT_SELECT, ENVIRONMENT_CONFIRM))
        later_environment_board = choice.expected == 'initial_board' and choice.payload not in ((), ('1-1',))
        strict_feedback = (defeat_step or investment_box or loot_click or loot_box is not None
                           or loot_claim is not None or boss_progress or loss_progress or investment_progress or encounter_input or double_supply_step
                           or INVESTMENT_REFRESH_BINDING in action
                           or environment_step)
        observed_at = scene.captured_at
        notice_watch = watch_encounter_reward(store.data, choice, scene, c.report.run_dir, c.runner.input_epoch)
        c.currency_standard_input(scene, choice)
        elapsed, after, stable, previous_popup = 0., None, 0, None
        previous_pickup = None
        overflow_frame = None
        previous_progress, progress_frames = None, []
        initial_return_frames, initial_return_paths = [], []
        while elapsed < 60:
            started, inactive = time.monotonic(), c.runner.inactive_duration
            try:
                after = c.snapshot()
            except EmptyCapture:
                after = None
                if notice_watch is not None:
                    notice_watch.observe(None, c.settings.ocr_confidence, elapsed)
                overflow_frame = None
                previous_progress = None
                progress_frames.clear()
                if strict_feedback:
                    stable = 0
            if strict_feedback and c.runner.input_epoch != action['input_epoch']:
                raise InputInterrupted('标准动作反馈的输入代次已变化，原意图保留待核对。')
            if after is not None:
                guard._require_current_scene(after)
                from .currency_wars_identity import AccountNotObserved, account_key, checked_account_key
                same_account = False
                progress = None
                try:
                    confidence = c.settings.ocr_confidence
                    observed_account = (checked_account_key(after, confidence) if environment_step else
                                        account_key(after, max(.85, confidence)))
                    if (encounter_input or double_supply_step) and account_key(after, min(.65, c.settings.ocr_confidence)) != observed_account:
                        raise AutomationError('标准动作反馈的账号字段有冲突。')
                    if loss_progress and account_key(after, c.settings.ocr_confidence) != observed_account:
                        raise AutomationError('失利后的到达画面有账号冲突。')
                except AccountNotObserved:
                    ready = False  # Animation may hide the UID; observe within this deadline.
                except AutomationError:
                    if environment_step:
                        raise
                    ready = False
                else:
                    if observed_account != store.data.get('account_key'):
                        raise AutomationError('标准动作反馈账号来源不一致，原意图保留待核对。')
                    same_account = True
                    from .currency_wars_standard_popup import arrival as popup_arrival
                    popup_stamp=popup_arrival(choice,after,store.data,c.settings.ocr_confidence)
                    if encounter_followup:
                        progress = encounter_followup_feedback(choice, after, c.settings.ocr_confidence)
                        ready = progress is not None
                    elif node_progress:
                        if not closing_intro:
                            progress = encounter_after_continue(choice, after, store.data, c.settings.ocr_confidence)
                        if progress is None:
                            progress = node_progress_feedback(choice, after, c.settings.ocr_confidence)
                        ready = progress is not None
                    elif encounter_step:
                        progress = encounter_feedback(choice, after, store.data, c.settings.ocr_confidence)
                        ready = progress is not None
                    elif refreshing_investment:
                        from .currency_wars_standard_investment_refresh import feedback as investment_refresh_feedback
                        progress = investment_refresh_feedback(choice, scene, after, store.data, c.settings.ocr_confidence)
                        ready = progress is not None
                    elif investment_progress:
                        investment_feedback = confirmation_board if investment_confirmation else shop_return_feedback
                        progress = investment_feedback(choice, after, store.data, c.settings.ocr_confidence)
                        ready = progress is not None
                    else:
                        ready = bool(popup_stamp) or transition_ready(choice, after, c.settings.ocr_confidence, before=scene,session=store.data)
                    if double_supply_step and ready:
                        try:
                            key = double_supply_key(choice, after, c.settings.ocr_confidence)
                            progress = dict(page_kind=key[0], supply_feedback=key)
                        except AutomationError:
                            ready = False
                    if popup_stamp!=previous_popup:stable=0
                    previous_popup=popup_stamp
                    initial = store.data.get('initial_environment', {})
                    if ready and choice.expected == 'initial_board' and initial.get('action_id') == action['id']:
                        from .currency_wars_initial import publish_acceptance, record_arrival
                        frames = initial['arrival_frames']
                        if after.captured_at <= observed_at or (frames and after.captured_at <= frames[-1]['captured_at']):
                            ready = False
                        else:
                            ready = record_arrival(store.data, after,
                                evidence=evidence(c, after, 'currency_standard_initial_arrival_'+str(len(frames)+1)),
                                run_dir=c.report.run_dir, epoch=c.runner.input_epoch, confidence=c.settings.ocr_confidence)
                            store.persist()
                            if ready:
                                publish_acceptance(c, store, guard, choice, after)
                                scene = after
                                break
                    if choice.expected == 'standard_initial_shop_closed':
                        if not ready:
                            initial_return_frames, initial_return_paths = [], []
                        elif initial_return_frames and after.captured_at <= initial_return_frames[-1].captured_at:
                            ready = False
                        else:
                            initial_return_frames.append(after)
                            initial_return_paths.append(evidence(c, after, 'currency_standard_initial_shop_return_'+str(len(initial_return_frames))))
                fresh = after.captured_at > observed_at
                if notice_watch is not None:
                    notice_watch.observe(after if fresh and same_account else None, c.settings.ocr_confidence, elapsed)
                    if (ready and progress and progress.get('page_kind') in ('preparation', 'shop')
                            and not notice_watch.ready(elapsed)):
                        ready = False
                if strict_feedback:
                    if fresh:
                        observed_at = after.captured_at
                    else:
                        ready = False
                paired_progress = (progress if ready and progress is not None
                                   and (investment_progress or closing_intro or loss_progress or encounter_step or encounter_followup or double_supply_step
                                        or notice_watch is not None and notice_watch.notice is not None
                                        or progress.get('page_kind') in ('boss_intro', ENCOUNTER_OFFER))
                                   else None)
                if ((encounter_followup or encounter_step or double_supply_step or paired_progress and paired_progress.get('page_kind') == ENCOUNTER_OFFER)
                        and progress_frames and progress_frames[-1][1] is after):
                    ready, paired_progress = False, None
                if paired_progress != previous_progress:
                    stable = 0
                    progress_frames.clear()
                if paired_progress is not None:
                    progress_frames.append((after.captured_at, after))
                previous_progress = paired_progress
                if loot_click:
                    overflow = (_loot_overflow_feedback(scene, after, choice.payload, loot_crystals,
                                                        loot_remaining, c.settings.ocr_confidence)
                                if fresh and same_account and not ready else None)
                    if overflow is not None and overflow_frame is not None and overflow == overflow_frame[0]:
                        _record_loot_overflow(c, store, action, overflow, overflow_frame[1], after)
                    overflow_frame = (overflow, after) if overflow is not None else None
                    if ready and action.get('loot_overflow_observations'):
                        ready = _loot_returned_after_overflow(scene, after, action, loot_remaining,
                                                              c.settings.ocr_confidence)
                pickup = None
                if ready and loot_pickup:
                    pickup = _loot_pickup_feedback(after, action, loot_remaining, c.settings.ocr_confidence)
                    if pickup is _UNRESOLVED_LOOT_BOX:
                        ready, pickup = False, None
                elif ready and loot_box is not None:
                    pickup = _loot_box_feedback(after, action, loot_box, c.settings.ocr_confidence)
                    ready = pickup is not None
                elif ready and loot_claim is not None:
                    pickup = _loot_reward_feedback(after, loot_claim, choice, c.settings.ocr_confidence)
                if pickup != previous_pickup:
                    stable = 0
                previous_pickup = pickup
                stable = (len(initial_return_frames) if choice.expected == 'standard_initial_shop_closed'
                          else stable+1) if ready else 0
                required = 2 if (paired_progress is not None or investment_box or loot_box is not None or defeat_step
                                 or later_environment_board or choice.expected in ('loot_collected','standard_owned_deployed','standard_exchange_inspectable','standard_relocate_inspectable',
                                                    'standard_offer_bought','standard_experience_bought','standard_shop_refreshed',
                                                    'standard_sale_panel','standard_owned_sold','standard_field_sale_panel','standard_field_owned_sold','standard_equipment_inspectable',
                                                    'standard_reward_returned','standard_supply_selected','standard_supply_refreshed',
                                                    'standard_investment_selected','standard_investment_applied',
                                                    'standard_stale_unit_board','standard_collected_unit_board',
                                                    'standard_movement_star_selected','standard_movement_star_returned','standard_popup_unit_board',
                                                    'standard_consumable_applied','standard_consumable_returned','standard_consumable_board',
                                                    'standard_initial_shop_closed')) else 1
                if stable >= required:
                    if double_supply_step:
                        commit_double_supply(c, store, guard, choice, scene, progress_frames,
                                             lambda frame, label: evidence(c, frame, label))
                        scene = after
                        break
                    if encounter_followup or encounter_step or paired_progress and paired_progress.get('page_kind') == ENCOUNTER_OFFER:
                        commit_encounter(c, store, guard, choice, progress_frames, paired_progress,
                                         lambda frame, label: evidence(c, frame, label))
                        scene = after
                        break
                    if notice_watch is not None and progress and progress.get('page_kind') in ('preparation', 'shop'):
                        receipt = notice_watch.receipt(c, store, choice, guard, after,
                                                       lambda frame, label: evidence(c, frame, label))
                        if receipt is not None:
                            commit_encounter(c, store, guard, choice, progress_frames, paired_progress,
                                             lambda frame, label: evidence(c, frame, label), reward_notice=receipt)
                            scene = after
                            break
                    after_path = evidence(c, after, 'currency_standard_after_'+choice.intent)
                    if paired_progress is not None:
                        captured_at, first = progress_frames[0]
                        first_path = evidence(c, first, 'currency_standard_first_'+choice.intent)
                        action['progress_frames'] = [
                            dict(captured_at=captured_at, input_epoch=action['input_epoch'], evidence=first_path),
                            dict(captured_at=after.captured_at, input_epoch=action['input_epoch'], evidence=after_path),
                        ]
                    if previous_popup:
                        action.update(status='verified',after=after_path)
                        from .currency_wars_standard_popup import opened
                        opened(store.data,choice,after,c.settings.ocr_confidence)
                        store.persist();scene=after
                        break
                    if choice.intent in FINANCIAL_ACTIONS:
                        from .currency_wars_standard_trading import financial_feedback
                        from .currency_wars_standard_ledger import valid_receipt
                        receipt = financial_feedback(choice, scene, after, c.settings.ocr_confidence,session=store.data)
                        if not valid_receipt(dict(action,status='verified',after=after_path,receipt=receipt)):
                            raise AutomationError('标准交易收据与原意图不符，保留待核对状态。')
                    action.update(status='verified', after=after_path)
                    if pickup is not None:
                        key = 'loot_pickup' if loot_pickup else 'loot_box_open' if loot_box is not None else 'loot_reward_return'
                        action[key] = pickup
                        if loot_pickup and 'bench_box' in pickup:
                            action['loot_pickup_kind'] = 'bench_box'
                    store.data.update(action_status='transition_verified', screenshot=action['after'])
                    if choice.intent in FINANCIAL_ACTIONS:
                        from .currency_wars_standard_trading import record_financial_feedback
                        record_financial_feedback(store.data, choice, receipt)
                    if choice.intent == 'start_standard_a8_40':
                        store.data['status'] = 'active'
                        store.data['start_verified'] = True
                    if choice.intent.startswith(ENVIRONMENT_CONFIRM):
                        store.data['environment'] = action['decision']
                        store.data.pop('expected_board', None)
                    if choice.intent == 'close_standard_initial_shop':
                        from .currency_wars_initial_shop import closed as initial_shop_closed
                        try:
                            initial_shop_closed(store.data, choice, scene, initial_return_frames, initial_return_paths,
                                                c.settings.ocr_confidence)
                        except AutomationError as error:
                            action['status'] = 'unknown'
                            store.data.update(action_status='unknown', reason=str(error))
                            store.persist()
                            raise
                    if choice.intent == 'start_standard_node':
                        store.data['node_attempt']['status']='observing'
                        record_encounter_start(store.data, action, after, 'after', c.report.run_dir,
                                               c.runner.input_epoch, c.settings.ocr_confidence)
                    if choice.intent in ('inspect_standard_unit','inspect_standard_exchange_unit','inspect_standard_equipment_unit','inspect_standard_reward_unit','inspect_standard_consumable_unit','inspect_standard_popup_unit'):
                        action['inspection_run_dir']=c.report.run_dir
                        store.data['inspecting'] = dict(zone=choice.payload[0],slot=choice.payload[1],
                                                        node=choice.payload[2],signature=choice.payload[3],
                                                        input_epoch=c.runner.input_epoch,
                                                        run_dir=c.report.run_dir,
                                                        before=action['before'],after=action['after'],inspection_action_id=action['id'])
                        if choice.intent == 'inspect_standard_exchange_unit':
                            store.data['inspecting']['exchange_id'] = choice.payload[4]
                        if choice.intent == 'inspect_standard_equipment_unit':
                            store.data['inspecting']['equipment_id'] = choice.payload[4]
                        if choice.intent=='inspect_standard_consumable_unit':
                            store.data['inspecting']['consumable_id']=choice.payload[4]
                    elif choice.intent in ('close_standard_unit','close_standard_stale_unit'):
                        from .currency_wars_standard_collection import closed
                        closed(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent == 'stage_standard_equipment':
                        from .currency_wars_standard_equipment import begin_verification
                        begin_verification(store.data,choice,scene,after,c.settings.ocr_confidence)
                        store.data['action_status'] = 'equipment_identity_pending'
                    elif choice.intent in ('close_standard_equipment_unit','close_standard_equipment_stale_panel'):
                        from .currency_wars_standard_equipment import after_close
                        after_close(store.data,choice,after,c.settings.ocr_confidence)
                        if store.data['equipment']['status']=='verified':
                            store.data['action_status'] = 'equipment_verified'
                    elif choice.intent in ('open_standard_equipment_recommendations','open_standard_consumable_recommendations'):
                        from .currency_wars_equipment_catalog import recommendation_facts
                        record = store.data['collection']['units'][choice.payload[0]+':'+str(choice.payload[1])]
                        names,recipes = recommendation_facts(after,c.settings.ocr_confidence)
                        record['recommendations'] = list(names)
                        record['equipment_recipes'] = list(recipes)
                        record['recommendations_source'] = after_path
                    elif choice.intent in ('close_standard_reward_unit','close_standard_reward_stale_panel'):
                        if choice.intent=='close_standard_reward_stale_panel':
                            store.data.pop('inspecting',None)
                            store.data.pop('collection',None)
                    elif choice.intent in ('stage_standard_consumable','choose_standard_consumable_gear'):
                        from .currency_wars_standard_consumables import applied
                        applied(store.data,choice,after,c.settings.ocr_confidence)
                        store.data['action_status']='consumable_identity_pending'
                    elif choice.intent=='refresh_standard_supply':
                        from .currency_wars_standard_supply_refresh import refreshed
                        refreshed(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent in ('close_standard_consumable_unit','close_standard_consumable_stale_panel'):
                        if choice.intent=='close_standard_consumable_stale_panel':
                            store.data.pop('inspecting',None);store.data.pop('collection',None)
                    elif choice.intent in ('confirm_standard_movement_star','close_standard_popup_unit','close_standard_popup_stale_panel'):
                        from .currency_wars_standard_popup import returned as popup_returned
                        popup_returned(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent in ('inspect_standard_sale_unit','inspect_standard_field_sale_unit'):
                        from .currency_wars_standard_sale import target_zone
                        store.data['inspecting'] = dict(zone=target_zone(choice.payload),slot=choice.payload[4],node=choice.payload[0],
                                                        signature=choice.payload[8],input_epoch=c.runner.input_epoch,
                                                        run_dir=c.report.run_dir,before=action['before'],after=action['after'])
                    elif choice.intent == 'close_standard_sale_stale_panel':
                        from .currency_wars_standard_sale import finish
                        finish(store.data,cancelled=True)
                    elif choice.intent in ('stage_standard_exchange','stage_standard_relocate'):
                        from .currency_wars_standard_exchange import begin_verification
                        begin_verification(store.data,choice,scene,after,c.settings.ocr_confidence)
                        store.data['action_status'] = 'exchange_identity_pending'
                    elif choice.intent in ('close_standard_exchange_unit','close_standard_exchange_stale_panel'):
                        from .currency_wars_standard_exchange import after_close
                        after_close(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent == 'deploy_standard_owned':
                        from .currency_wars_standard_deployment import transfer_collection, deployment_feedback
                        action['feedback'] = deployment_feedback(scene,after,choice.target,c.settings.ocr_confidence)
                        transfer_collection(store.data,scene,after,choice.target,action['after'],c.settings.ocr_confidence)
                    elif choice.intent not in ('close_standard_unit','open_standard_shop','close_standard_shop','select_standard_movement_star',
                                                'buy_standard_experience','refresh_standard_shop','sell_standard_owned','sell_standard_field_owned'):
                        store.data.pop('collection',None)
                    if choice.intent == 'close_standard_shop':
                        nodes = store.data.setdefault('shop_observed_nodes',[])
                        if len(choice.payload)==6 and choice.payload[0] in nodes:
                            nodes.remove(choice.payload[0])
                        elif len(choice.payload)==4 and choice.payload[0] not in nodes:
                            nodes.append(choice.payload[0])
                    from .currency_wars_standard_progress import progress_verified
                    progress_verified(store.data, choice, after, c.settings.ocr_confidence)
                    from .currency_wars_standard_investment import enter as investment_enter, confirmed, reward_completed
                    investment_enter(store.data,after,c.settings.ocr_confidence)
                    if investment_confirmation:
                        confirmed(store.data, choice, after, c.settings.ocr_confidence)
                        refresh_investment = True
                    elif closing_investment_shop:
                        from .currency_wars_standard_investment import record_shop_return
                        record_shop_return(action, store.data['actions'], paired_progress)
                    elif refreshing_investment:
                        from .currency_wars_standard_investment_refresh import record_feedback as record_investment_refresh
                        record_investment_refresh(action, store.data, paired_progress)
                    from .currency_wars_standard_rewards import enter, returned
                    enter(store.data,choice,after,c.settings.ocr_confidence)
                    if choice.intent in ('choose_standard_reward','confirm_standard_supply'):
                        returned(store.data,choice,after,c.settings.ocr_confidence)
                        reward_completed(store.data)
                    from .currency_wars_character_rewards import observe_shop
                    observe_shop(store.data,after,action,c.settings.ocr_confidence)
                    store.persist()
                    scene = after
                    break
            c.sleep(.5)
            elapsed += max(0., time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            if encounter_input or double_supply_step:
                pending = store.require_pending(choice.intent, action['input_epoch'])
                if not (same_supply_journal(pending, store.data) if double_supply_step else pending == store.data):
                    raise AutomationError('标准动作落盘意图已改变，保留原画面待核对。')
            action['status'] = 'unknown'
            if encounter_followup:
                reason = '遭遇收店或出战后的双帧反馈未核实，原意图保留待核对。'
            elif double_supply_step:
                reason = '双件补给的双帧反馈未核实，原意图保留待核对。'
            else:
                reason = ('遭遇选择或确认后的双帧反馈未核实，原意图保留待核对。'
                          if encounter_step else _loot_timeout_reason(action))
            store.data.update(action_status='unknown', reason=reason)
            if after is not None:
                store.data['screenshot'] = evidence(c, after, 'currency_standard_transition_unknown')
            store.persist()
            break
        if store.data['completion_verified'] or store.data.get('defeat_settlement_verified'):
            break
    else:
        store.data.update(action_status='step_limit', reason='本次标准观察达到本局动作上限对应的轮数，已停止并保留记录。')
        store.persist()
    c.report.currency_wars = store.data
    c.runner.emit(dict(type=TASK, data=store.data))
    if store.data['completion_verified']:
        c.report.safe_next = '本次为开发对局，结算完成不计作独立验收；原始证据已保留。'
        return TaskResult(TASK, 'success', store.data['reason'])
    if store.data.get('defeat_settlement_verified'):
        c.report.safe_next='本局失败且结算已核实；原报告保留，循环按冻结设置与原局数上限处理，不接续或重打这局。'
        return TaskResult(TASK,'partial',store.data['reason'])
    last_action = store.data['actions'][-1] if store.data['actions'] else {}
    if store.data.get('node_attempt', {}).get('status') == 'encounter_pending':
        c.report.safe_next = '请核对本次遭遇卡、选择和回到同节点的画面；原继续与待核对意图均保留。'
    elif last_action.get('status') == 'unknown' and last_action.get('loot_overflow_observations'):
        c.report.safe_next = '请先核对本次奖励与备战席状态，原领取待核对期间不可接续输入。'
    else:
        c.report.safe_next = '先读取标准对局当前局面，再接续已核实动作；不重开或重放未知交易。'
    return TaskResult(TASK, 'partial', store.data.get('reason', '标准对局开发未完成，已留证。'))
