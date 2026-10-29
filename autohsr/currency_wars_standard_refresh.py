"""Bounded standard shop refreshes priced from the current visible button.

March7th's growth phases are adapted to one durable input and a visual receipt.
The upstream cached two-gold deduction and repeated D key loop are not used.
"""
import hashlib
import json
import math
import re

from .models import AutomationError, Scene, Token, normalize


PRICE_ROI = (.845, .477, .869, .509)
BUTTON_ROI = (.81, .42, .89, .48)
MAX_NODE_REFRESHES = 6
MAX_NODE_REFRESH_SPEND = 12


def refresh_price(scene, confidence=.65):
    tokens = [t for t in scene.tokens if math.isfinite(t.score) and confidence <= t.score <= 1
              and len(t.box) == 4 and all(math.isfinite(v) and 0 <= v <= 1 for v in t.box)
              and t.box[0] < t.box[2] and t.box[1] < t.box[3] and t.within(PRICE_ROI)]
    # A wider/negative/conflicting reading cannot be replaced by its last digit.
    if not tokens or any(not re.fullmatch(r'[0-9]{1,2}', normalize(t.text)) for t in tokens):
        raise AutomationError('刷新费用未在当前按钮独立核实，未刷新。')
    values = {int(normalize(t.text)) for t in tokens}
    if len(values) != 1:
        raise AutomationError('当前刷新费用存在冲突，未刷新。')
    return next(iter(values))


def supplement_refresh_price(scene, reader):
    from .currency_wars_pages import classify_page
    if scene.image is None or classify_page(scene.tokens) != 'shop' or not hasattr(reader, 'read_number'):
        return scene
    # Keep any existing reading, including conflicts or unsupported text.
    if any(t.within(PRICE_ROI) for t in scene.tokens):
        return scene
    import cv2
    from .currency_wars_deployment import _crop
    patch = _crop(scene.image, PRICE_ROI)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    parts = [reader.read_number(patch), reader.read_number(cv2.threshold(gray,180,255,cv2.THRESH_BINARY)[1])]
    if (any(t is None or not .9 <= t.score <= 1 or not re.fullmatch(r'[0-9]{1,2}',t.text) for t in parts)
            or len({t.text for t in parts}) != 1):
        return scene
    return Scene(scene.tokens+[Token(parts[0].text,min(t.score for t in parts),PRICE_ROI)],
                 scene.image,scene.geometry,scene.captured_at,scene.field_reads)


def table_digest(table, *, complete=False):
    if (not isinstance(table, (list,tuple)) or len(table) != 5
            or complete and any(item is None for item in table)):
        raise ValueError('商店五格报价不完整')
    for item in table:
        if item is not None and (not isinstance(item,(list,tuple)) or len(item) != 2
                or not isinstance(item[0],str) or not 0 < len(item[0]) <= 80
                or type(item[1]) is not int or not 0 <= item[1] <= 99):
            raise ValueError('商店报价无效')
    return hashlib.sha256(json.dumps(table,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def offer_table(state, empty_slots=()):
    offers = {offer.slot: [offer.name,offer.cost] for offer in state.offers}
    if set(offers) | set(empty_slots) != set(range(5)) or set(offers) & set(empty_slots):
        raise ValueError('报价缺项没有已核实购买来源')
    result = [offers.get(slot) for slot in range(5)]
    table_digest(result)
    return result


def sold_slots(session, node):
    from .currency_wars_standard_ledger import valid_receipt
    result = set()
    for action in session.get('actions',[]):
        target = action.get('target',[])
        if not target or target[0] != node:
            continue
        if action.get('action') == 'refresh_standard_shop' and valid_receipt(action):
            result.clear()
        elif action.get('action') == 'buy_standard_offer' and valid_receipt(action):
            result.add(target[4])
    return result


def refresh_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_standard_trading import _shop_snapshot, _prior, bench_signature
    from .currency_wars_standard_policy import POLICY, refresh_reason
    from .currency_wars_standard_ledger import valid_receipt
    from .currency_wars_navigation import unique
    from .currency_wars_prepare import trusted
    prior = _prior(session, 'refresh_standard_shop')
    if not prior.get('strategy') or not prior.get('pre_shop_snapshot',{}).get('roster_complete'):
        return None
    if prior.get('actions') and prior['actions'][-1].get('action') == 'buy_standard_offer':
        return None  # Finish the purchase's recollection protocol first.
    snapshot = _shop_snapshot(scene, prior, 'refresh_standard_shop', confidence)
    history = [a for a in prior['actions'] if a.get('action') == 'refresh_standard_shop'
               and a.get('target',[None])[0] == snapshot.node and valid_receipt(a)]
    spent = sum(a['receipt']['price'] for a in history)
    # Ineligible phases should close the shop without requiring unused fields.
    if not refresh_reason(snapshot,prior['strategy'],0,len(history),spent):
        return None
    price = refresh_price(scene,confidence)
    reason = refresh_reason(snapshot,prior['strategy'],price,len(history),spent)
    if not reason:
        return None
    from .currency_wars_standard_trading import read_match
    state = read_match(scene,confidence)
    try:
        signature = table_digest(offer_table(state,sold_slots(prior,state.node)))
    except ValueError as error:
        raise AutomationError('刷新前五格报价缺失或价格不明，未刷新。') from error
    if state.probabilities is None or state.experience is None and state.level!=10:
        raise AutomationError('刷新前等级概率或经验字段不明，未刷新。')
    from .currency_wars_standard_investment import refresh_bonus
    amount,_,bonus_digest=refresh_bonus(prior,node=state.node)
    payload=(state.node,state.gold,snapshot.hp,state.level,price,signature,bench_signature(scene))
    if amount and price:
        payload+=(amount,*(state.experience or (0,0)),bonus_digest)
    target = unique(trusted(scene,confidence),'刷新',BUTTON_ROI)
    return StandardAction('refresh_standard_shop','standard_shop_refreshed',target,
                          details=(prior['strategy'],0.,(reason,),POLICY),
                          payload=payload)


def experience_gain(level, xp, after_level, after_xp, amount):
    if (type(amount) is not int or not 0<=amount<=99 or type(level) is not int or not 1<=level<=10
            or type(after_level) is not int or not 1<=after_level<=10):return False
    if level==10:return after_level==10 and xp is None and after_xp is None
    if (not isinstance(xp,(list,tuple)) or len(xp)!=2 or any(type(v) is not int for v in xp)
            or not 0<=xp[0]<xp[1]<=9999):return False
    if not amount:return after_level==level and after_xp==xp
    total=xp[0]+amount
    if total<xp[1]:return after_level==level and after_xp==(total,xp[1])
    if after_level!=level+1:return False
    if after_level==10:return after_xp is None
    return (isinstance(after_xp,(list,tuple)) and len(after_xp)==2 and all(type(v) is int for v in after_xp)
            and after_xp[0]==total-xp[1] and 0<=after_xp[0]<after_xp[1]<=9999)


def refresh_feedback(choice, before, after, confidence=.65, *, session=None):
    from .currency_wars_standard_trading import read_match, bench_signature
    first,last = read_match(before,confidence),read_match(after,confidence)
    if (not first or not last or first.page != 'shop' or last.page != 'shop'
            or (first.node,first.gold,first.level) != (choice.payload[0],choice.payload[1],choice.payload[3])
            or last.node != first.node or last.gold is None
            or first.gold-last.gold != choice.payload[4] or last.hp not in (None,choice.payload[2])
            or first.probabilities is None or last.probabilities is None
            or last.level==first.level and first.probabilities!=last.probabilities
            or before.image is None or after.image is None or before.image.shape != after.image.shape):
        return None
    bonus=0;sources=[];signature=None
    if session is not None:
        from .currency_wars_standard_investment import refresh_bonus
        from .currency_wars_standard_trading import _prior
        bonus,sources,signature=refresh_bonus(_prior(session,choice.intent),node=first.node)
        if choice.payload[4]==0:bonus=0
    if (len(choice.payload)==11 and (not bonus or choice.payload[7:]!=(bonus,*(first.experience or (0,0)),signature))
            or len(choice.payload)==7 and bonus or len(choice.payload) not in (7,11)
            or not experience_gain(first.level,first.experience,last.level,last.experience,bonus)):
        return None
    try:
        # Missing before slots must have been proved at proposal time. The exact
        # table hash is immutable in the persisted payload and re-derived by IO.
        old = [[offer.name,offer.cost] if (offer:=next((o for o in first.offers if o.slot==slot),None)) else None
               for slot in range(5)]
        new = offer_table(last)
        old_hash,new_hash = table_digest(old),table_digest(new,complete=True)
        if (refresh_price(before,confidence) != choice.payload[4] or old_hash != choice.payload[5]
                or new_hash == old_hash or bench_signature(before) != choice.payload[6]
                or bench_signature(after) != choice.payload[6]):
            return None
    except (ValueError,AutomationError):
        return None
    receipt=dict(schema=1,currency='match_gold',node=first.node,gold_before=first.gold,gold_after=last.gold,
                price=choice.payload[4],level_after=last.level,table_before=old_hash,table_after=new_hash,
                offers_before=old,offers_after=new,bench_before=choice.payload[6],bench_after=choice.payload[6])
    if bonus:
        receipt.update(bonus_xp=bonus,bonus_sources=sources,bonus_digest=signature,
            experience_before=list(first.experience) if first.experience else None,
            experience_after=list(last.experience) if last.experience else None)
    return receipt
