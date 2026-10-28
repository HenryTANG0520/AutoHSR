"""Standard-mode purchases with current prices and durable visual receipts."""
from dataclasses import replace
import hashlib
import json

import numpy as np

from .currency_wars_deployment import _crop, _texture, backend_layout, bench_face
from .currency_wars_match import unit_name
from .currency_wars_standard_ledger import ledger_status, valid_receipt
from .currency_wars_standard_policy import POLICY, can_buy_experience, growth_target, rank_standard_offers
from .currency_wars_state import FactEvidence, ShopOffer, StrategySnapshot
from .models import AutomationError, normalize


def read_match(scene, confidence=.65):
    from .currency_wars_match import read_match as read
    return read(scene, confidence)


def bench_signatures(scene):
    if scene.image is None:
        raise AutomationError('交易需要当前备战席图像。')
    result = {}
    for slot in range(1, 10):
        patch = _crop(scene.image, bench_face(slot))
        if 8 <= _texture(patch) < 15:
            raise AutomationError('交易前备战格状态不确定。')
        result[str(slot)] = hashlib.sha256(patch.tobytes()).hexdigest()
    return result


def bench_signature(scene):
    return hashlib.sha256(''.join(bench_signatures(scene).values()).encode('ascii')).hexdigest()


def _prior(session, own_intent):
    actions = session.get('actions', [])
    if actions and actions[-1].get('status') == 'pending' and actions[-1].get('action') == own_intent:
        return dict(session, actions=actions[:-1])
    return session


def _scope(session, own_intent):
    prior = _prior(session, own_intent)
    collection, client = prior.get('collection', {}), prior.get('client', {})
    if (prior.get('status') != 'active' or not prior.get('start_verified')
            or not prior.get('entry', {}).get('rank_verified') or not prior.get('account_key')
            or not collection.get('complete') or type(collection.get('input_epoch')) is not int
            or prior.get('account_verified_run') != collection.get('run_dir')
            or prior.get('account_verified_epoch') != collection['input_epoch']
            or client.get('verified_run') != collection.get('run_dir')
            or client.get('input_epoch') != collection['input_epoch']
            or client.get('version') != '4.6' or prior.get('rules_version') != '4.6'
            or ledger_status(prior.get('actions', [])) != 'clear'):
        raise AutomationError('标准交易缺少本局、账号、版本、完整阵容或清晰账本。')
    return prior


def _shop_balance(session, before):
    """Trace this opening's refresh receipts back to its unchanged roster."""
    from .currency_wars_standard_refresh import table_digest
    chain = []
    for action in reversed(session.get('actions',[])):
        if action.get('action') == 'open_standard_shop' and action.get('status') == 'verified':
            break
        if action.get('action') != 'refresh_standard_shop' or not valid_receipt(action):
            raise AutomationError('当前商店没有连续已核实的开店／刷新来源。')
        chain.append(action)
    else:
        raise AutomationError('商店刷新缺少已核实开店来源。')
    gold, table = before.get('gold'), None
    for action in reversed(chain):
        target,receipt = action['target'],action['receipt']
        if ((target[0],target[1],target[2],target[3]) != (before.get('node'),gold,before.get('hp'),before.get('level'))
                or target[6] != hashlib.sha256(''.join(session.get('pre_shop_bench',{}).values()).encode('ascii')).hexdigest()
                or table is not None and target[5] != table_digest(table,complete=True)):
            raise AutomationError('刷新账本的节点、余额或报价不连续。')
        gold,table = receipt['gold_after'],receipt['offers_after']
    return gold,table


def _shop_snapshot(scene, session, own_intent, confidence=.65):
    from .currency_wars_market import overclock_board
    from .currency_wars_standard_refresh import offer_table
    prior = _scope(session,own_intent)
    raw = session.get('pre_shop_snapshot', {})
    try:
        # asdict keeps tuples in the live process; a persisted/reloaded
        # session contains JSON arrays. Parse the same canonical shape in both.
        before = StrategySnapshot.from_dict(json.loads(json.dumps(raw, allow_nan=False)))
    except (ValueError, TypeError) as error:
        raise AutomationError('开店前完整局面记录无效，未交易。') from error
    state = read_match(scene, confidence)
    gold,table = _shop_balance(prior,raw)
    if (not state or state.page != 'shop' or before.transaction_status != 'clear'
            or before.mode != 'standard' or before.rank != 8 or before.wealth != 40
            or before.game_version != '4.6' or before.rules_version != '4.6'
            or before.input_epoch != prior['collection']['input_epoch']
            or not before.known('mode','rank','wealth','game_version','rules_version','transaction_status',
                                'node','gold','hp','level','roster','roster_complete','capacity','bench_capacity','bench_occupied')
            or (state.node, state.gold, state.level) != (before.node, gold, before.level)
            or state.hp not in (None, before.hp) or before.hp <= 0
            or backend_layout(scene.image)[0] != 6 or overclock_board(scene)
            or bench_signatures(scene) != session.get('pre_shop_bench')):
        raise AutomationError('商店或备战席与已核实开店来源不一致，未交易。')
    if table is not None:
        try:
            unchanged = offer_table(state) == table
        except ValueError:
            unchanged = False
        if not unchanged:
            raise AutomationError('当前五格报价与最近已核实刷新不一致。')
    offers = tuple(ShopOffer(offer.slot, offer.name, price=offer.cost) for offer in state.offers)
    source = 'shop_observation:'+str(scene.captured_at)
    evidence = tuple(e for e in before.evidence if e.field not in ('gold','offers','experience'))
    return replace(before,page='shop',gold=state.gold,offers=offers,experience=state.experience,
                   observed_at=scene.captured_at,evidence=evidence+tuple(
                       FactEvidence(field,source,before.input_epoch) for field in ('gold','offers','experience')
                       if getattr(state,field) is not None))


def purchase_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_market import shop_trait_facts
    prior = _prior(session, 'buy_standard_offer')
    actions = prior.get('actions', [])
    if actions and actions[-1].get('status') == 'pending' and actions[-1].get('action') in (
            'close_standard_shop', 'close_standard_shop_after_purchase'):
        prior = _prior(prior, actions[-1]['action'])
    if prior.get('actions') and prior['actions'][-1].get('action') == 'buy_standard_offer':
        return None  # Recollect after one purchase, before deciding another.
    if not session.get('pre_shop_snapshot', {}).get('roster_complete'):
        return None  # Legacy read-only shop observations keep their contract.
    snapshot = _shop_snapshot(scene,prior,'buy_standard_offer',confidence)
    discarded = {entry['name'] for entry in prior.get('discarded_units',[]) if entry.get('node') == snapshot.node}
    snapshot = replace(snapshot,offers=tuple(offer for offer in snapshot.offers if offer.name not in discarded))
    state = read_match(scene,confidence)
    traits, progress = shop_trait_facts(scene, confidence)
    ranking = rank_standard_offers(snapshot, session.get('strategy', 'default'), traits=traits, progress=progress)
    if not ranking:
        return None
    decision = ranking[0]
    left = .192+.14*decision.slot
    targets = [token for token in scene.tokens if confidence <= token.score <= 1
               and token.within((left,.265,left+.115,.305)) and unit_name(token.text) == decision.name]
    if len(targets) != 1:
        raise AutomationError('标准商店候选名称不唯一，未购买。')
    payload = (state.node, state.gold, snapshot.hp, state.level, decision.slot,
               decision.name, decision.price, bench_signature(scene))
    return StandardAction('buy_standard_offer', 'standard_offer_bought', targets[0],
                          details=(session.get('strategy','default'),decision.score,decision.reasons,POLICY), payload=payload)


def experience_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_collector import collected_snapshot
    from .currency_wars_experience import experience_target
    prior = _scope(_prior(session, 'start_standard_node'), 'buy_standard_experience')
    snapshot = collected_snapshot(scene, prior, prior['collection']['input_epoch'], 'standard_experience', confidence)
    if (snapshot.mode != 'standard' or snapshot.game_version != '4.6' or snapshot.rules_version != '4.6'
            or snapshot.transaction_status != 'clear'):
        raise AutomationError('购买经验的当前来源或版本未核实。')
    strategy = session.get('strategy', 'default')
    if not can_buy_experience(snapshot, strategy):
        return None
    target = experience_target(scene, confidence)
    payload = (snapshot.node, snapshot.gold, snapshot.hp, snapshot.level,
               snapshot.experience[0], snapshot.experience[1], growth_target(snapshot, strategy))
    return StandardAction('buy_standard_experience', 'standard_experience_bought', target,
                          details=(strategy,0.,('余额足以支付到下一级；逐笔核实',),POLICY), payload=payload)


def financial_feedback(choice, before, after, confidence=.65, *, session=None):
    if choice.intent == 'sell_standard_owned':
        from .currency_wars_standard_sale import sale_feedback
        return sale_feedback(choice,before,after,session,confidence)
    if choice.intent == 'refresh_standard_shop':
        from .currency_wars_standard_refresh import refresh_feedback
        return refresh_feedback(choice,before,after,confidence,session=session)
    first, last = read_match(before, confidence), read_match(after, confidence)
    if (first is None or last is None or first.node != last.node or first.node != choice.payload[0]
            or first.gold != choice.payload[1] or first.level != choice.payload[3]
            or last.hp not in (None, choice.payload[2]) or last.gold is None
            or before.image is None or after.image is None or before.image.shape != after.image.shape):
        return None
    receipt = dict(schema=1, currency='match_gold', node=first.node,
                   gold_before=first.gold, gold_after=last.gold, level_after=last.level)
    try:
        first_bench, last_bench = bench_signatures(before), bench_signatures(after)
    except AutomationError:
        return None  # A fading/occluded portrait is an observation, not a retry.
    if choice.intent == 'buy_standard_offer':
        _, gold, _, level, slot, name, price, signature = choice.payload
        if (first.page != 'shop' or last.page != 'shop' or last.level != level or gold-last.gold != price
                or first.experience != last.experience or first.probabilities != last.probabilities
                or not any((offer.slot,offer.name,offer.cost) == (slot,name,price) for offer in first.offers)
                or any(offer.slot == slot for offer in last.offers)
                or tuple(offer for offer in first.offers if offer.slot != slot) != last.offers
                or hashlib.sha256(''.join(first_bench.values()).encode('ascii')).hexdigest() != signature):
            return None
        changed = [slot for slot in range(1,10) if np.mean(np.abs(
            _crop(before.image,bench_face(slot)).astype(float)-_crop(after.image,bench_face(slot)).astype(float))) >= 8]
        if not changed:
            return None
        receipt.update(price=price, slot=slot, name=name, bench_changed=True,
                       bench_before=signature, bench_after=hashlib.sha256(''.join(last_bench.values()).encode('ascii')).hexdigest(),
                       changed_slots=changed)
        return receipt
    if choice.intent != 'buy_standard_experience' or first.page != 'preparation' or last.page != first.page:
        return None
    if (first.experience != tuple(choice.payload[4:6]) or first.hp != choice.payload[2]
            or last.hp != first.hp or first.gold-last.gold != 4 or not first.deployment or not last.deployment
            or first.deployment[0] != last.deployment[0] or last.level not in (first.level, first.level+1)
            or last.deployment[1]-first.deployment[1] != last.level-first.level
            or first_bench != last_bench):
        return None
    maximum = (last.level == 10 and first.level == 9 and last.experience is None
               and 1 <= first.experience[1]-first.experience[0] <= 4
               and any(confidence <= token.score <= 1 and normalize(token.text) in ('满级','已满级')
                       and token.within((.1,.77,.2,.87)) for token in after.tokens))
    if not maximum:
        from .currency_wars_match import verify_experience
        if (verify_experience(first,last) != 'verified' or first.level == last.level
                and first.experience[1] != last.experience[1]):
            return None
    receipt.update(price=4, hp_after=last.hp, experience_after=list(last.experience) if last.experience else None,
                   max_level_verified=maximum)
    return receipt


def record_financial_feedback(session, choice, receipt):
    action = session['actions'][-1]
    if not valid_receipt(dict(action, receipt=receipt)):
        raise AutomationError('标准交易收据与已落盘意图不一致。')
    action['receipt'] = receipt
    if choice.intent == 'sell_standard_owned':
        from .currency_wars_standard_sale import finish
        finish(session)
    if choice.intent == 'buy_standard_experience' and receipt['level_after'] != choice.payload[3]:
        nodes = session.get('shop_observed_nodes', [])
        if choice.payload[0] in nodes:
            nodes.remove(choice.payload[0])  # New capacity may need different units.


def shop_return_values(scene, session, confidence=.65):
    """Carry a verified purchase balance back to the original board HP."""
    actions = session.get('actions', [])
    if actions and actions[-1].get('status') == 'pending' and actions[-1].get('action') in (
            'close_standard_shop', 'close_standard_shop_after_purchase'):
        actions = actions[:-1]
    before, state = session.get('pre_shop_snapshot', {}), read_match(scene, confidence)
    previous = actions[-1] if actions else {}
    purchased = previous.get('action') == 'buy_standard_offer'
    refreshed = previous.get('action') == 'refresh_standard_shop'
    bonus=previous.get('receipt',{}).get('bonus_xp',0) if refreshed else 0
    level=previous.get('receipt',{}).get('level_after') if bonus else before.get('level')
    gold = previous.get('receipt', {}).get('gold_after') if purchased else _shop_balance(dict(session,actions=actions),before)[0]
    if (not state or state.page != 'shop' or session.get('status') != 'active'
            or before.get('hp') is None or state.hp not in (None,before['hp'])
            or (state.node,state.gold,state.level) != (before.get('node'),gold,level)
            or previous.get('status') != 'verified'
            or (purchased and not valid_receipt(previous))
            or (refreshed and (not valid_receipt(previous) or bench_signatures(scene) != session.get('pre_shop_bench')))
            or (not purchased and not refreshed and previous.get('action') != 'open_standard_shop')):
        raise AutomationError('收起标准商店前缺少同节点、余额或已核实交易来源。')
    payload=(state.node,state.gold,before['hp'],state.level)
    if bonus:
        expected=previous['receipt'].get('experience_after')
        if (list(state.experience) if state.experience else None)!=expected:
            raise AutomationError('刷新赠经验后的当前读数与收据不同。')
        payload+=state.experience or (0,0)
    return payload,purchased
