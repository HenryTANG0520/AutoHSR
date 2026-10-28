"""Observed-price decisions adapted from March7th's named-core growth phases.

These are explicit engineering baselines, not validated winning compositions.
No static purchase prices, star levels, or equipment are inferred from names.
Pinned source and license: assets/upstream/March7thAssistant/source.json.
"""
from dataclasses import dataclass

from .currency_wars_economy import Mode, assess_spend


POLICY = 'standard-native-v1'
STRATEGIES = ('default', 'aglaea', 'seele')
PREFERRED = {
    'default': (),
    'aglaea': ('阿格莱雅', '风堇', '缇宝', '藿藿', '星期日', '符玄', '银狼', '花火'),
    'seele': ('希儿', '瓦尔特', '刻律德菈', '符玄', '花火', '佩拉', '风堇', '缇宝'),
}


@dataclass(frozen=True)
class PurchaseDecision:
    slot: int
    name: str
    price: int
    score: float
    reasons: tuple[str, ...]


def _strategy(value):
    if value not in STRATEGIES:
        raise ValueError('货币战争策略必须为 default、aglaea 或 seele。')
    return value


def rank_standard_offers(snapshot, strategy='default', *, traits=None, progress=None):
    strategy = _strategy(strategy)
    if (not snapshot.roster_complete or snapshot.bench_capacity is None or snapshot.bench_occupied is None
            or snapshot.capacity is None or snapshot.gold is None or snapshot.hp is None
            or snapshot.bench_occupied >= snapshot.bench_capacity):
        return ()
    names = {unit.name for unit in snapshot.roster}
    missing = max(0, snapshot.capacity-len(names))
    reserve = 0 if snapshot.hp <= 40 or snapshot.gold < 10 else 10
    result = []
    for offer in snapshot.offers:
        if type(offer.price) is not int or not 0 <= offer.price <= 99 or offer.price > snapshot.gold-reserve:
            continue
        owned = [unit for unit in snapshot.roster if unit.name == offer.name]
        highest = max((unit.star or 0 for unit in owned), default=0)
        reasons, benefit = [], 0.
        if not owned and missing:
            benefit += 60
            reasons.append('补足不同角色数量')
        if owned and highest and highest < 3:
            benefit += 25 if sum(unit.star == 1 for unit in owned) >= 2 else 18
            reasons.append('积累已持有角色；实际星级变化待重采')
        preferences = PREFERRED[strategy]
        if offer.name in preferences:
            index = preferences.index(offer.name)
            if index == 0 and highest < 3:
                benefit += 85
                reasons.append('优先取得并培养策略核心')
            elif not owned:
                benefit += max(8, 40-index*3)
                reasons.append('补入策略协同角色')
        if not owned:
            for trait in dict.fromkeys((traits or {}).get(offer.slot, ())):
                count, threshold = (progress or {}).get(trait, (None, None))
                if type(count) is int and type(threshold) is int and 0 <= count < threshold:
                    benefit += 30 if count+1 == threshold else 5
                    reasons.append('当前可见羁绊适配：'+trait)
        if benefit == 0:
            continue
        spending = assess_spend(Mode.STANDARD, snapshot.gold, offer.price)
        score = benefit-2*offer.price-25*spending.interest_lost
        if snapshot.bench_capacity-snapshot.bench_occupied <= 2:
            score -= 20
            reasons.append('备战空间紧张')
        if score > 0:
            result.append(PurchaseDecision(offer.slot, offer.name, offer.price, score, tuple(reasons)))
    return tuple(sorted(result, key=lambda decision: (-decision.score, decision.price, decision.slot)))


def growth_target(snapshot, strategy='default'):
    strategy = _strategy(strategy)
    if strategy == 'default':
        return 10
    core = PREFERRED[strategy][0]
    highest = max((unit.star or 0 for unit in snapshot.roster if unit.name == core), default=0)
    if strategy == 'seele':
        return 6 if highest == 0 else 7 if highest < 3 else 9
    names = {unit.name for unit in snapshot.roster}
    return 9 if highest >= 3 and {'风堇', '缇宝', '藿藿'} <= names else snapshot.level


def owned_team_preference(name, strategy='default'):
    preferences = PREFERRED[_strategy(strategy)]
    if name not in preferences:
        return 0
    index = preferences.index(name)
    return 180 if index == 0 else max(24,72-index*6)


def can_buy_experience(snapshot, strategy='default'):
    if (not snapshot.roster_complete or snapshot.level is None or snapshot.level >= 10
            or snapshot.experience is None or snapshot.gold is None or snapshot.hp is None
            or snapshot.hp <= 0 or snapshot.capacity is None
            or sum(unit.zone != 'bench' for unit in snapshot.roster) != snapshot.capacity
            or snapshot.level >= growth_target(snapshot, strategy)):
        return False
    # Learn the upstream whole-level affordability check, but send and verify
    # one purchase at a time. Recompute from the next observed balance/XP.
    remaining = snapshot.experience[1]-snapshot.experience[0]
    required = ((remaining+3)//4)*4
    reserve = 0 if snapshot.hp <= 40 or snapshot.gold < 10 else 10
    return snapshot.gold-reserve >= required
