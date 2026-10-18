"""Explainable decisions from observed resources, roster facts and trait gaps.

Weights are a baseline policy, not claims about optimal game balance. Missing
roster/star facts receive no upgrade bonus and never become invented facts.
"""
from dataclasses import dataclass

from .currency_wars_economy import Mode,assess_spend


@dataclass(frozen=True)
class PurchaseSituation:
    mode: Mode
    gold: int
    bench_free: int
    vacancies: int | None = None
    hp: int | None = None
    owned_names: frozenset[str] = frozenset()
    roster_complete: bool = False


@dataclass(frozen=True)
class ScoredPurchase:
    slot: int
    name: str
    cost: int
    score: float
    reasons: tuple[tuple[str,float], ...]


def score_purchase(offer,situation,*,traits=(),progress=None,same_star_copies=None,preference=0.):
    if (type(offer.cost) is not int or offer.cost not in (1,2,3,4,5) or
            situation.bench_free<1 or situation.gold<offer.cost):
        return None
    urgent=situation.hp is not None and situation.hp<=40
    reserve=0 if urgent or situation.gold<10 else 10
    spending=assess_spend(situation.mode,situation.gold,offer.cost)
    if spending.remaining<reserve:
        return None
    reasons=[('基础候选',12.),('费用',-2.*offer.cost)]
    if preference:
        reasons.append(('参考阵容',float(preference)))
    if situation.mode==Mode.STANDARD and spending.interest_lost:
        reasons.append(('利息损失',-25.*spending.interest_lost))
    if urgent:
        reasons.append(('低生命即时战力',15.))
    # Only known copies of the same star may predict the tutorial's 3-copy merge.
    if same_star_copies in (1,2):
        reasons.append(('即将升星' if same_star_copies==2 else '建立对子',70. if same_star_copies==2 else 18.))
    is_new=offer.name not in situation.owned_names
    if is_new and situation.roster_complete and situation.vacancies and situation.vacancies>0:
        reasons.append(('补足上阵人数',35.))
    # Duplicates do not add another unique trait member. With an incomplete
    # roster this is explicitly a candidate's trait fit, not a guaranteed gain.
    if is_new:
        for trait in dict.fromkeys(traits):
            current,threshold=(progress or {}).get(trait,(None,None))
            if type(current) is not int or type(threshold) is not int or not 0<=current<threshold:
                continue
            points=40. if current+1==threshold else round(12.*(current+1)/threshold,2)
            label=('完成羁绊' if situation.roster_complete else '羁绊适配候选')+':'+trait
            reasons.append((label,points))
    if situation.bench_free<=2 and not (same_star_copies==2):
        reasons.append(('备战空间紧张',-25.))
    score=round(sum(value for _,value in reasons),2)
    return ScoredPurchase(offer.slot,offer.name,offer.cost,score,tuple(reasons)) if score>0 else None


def rank_purchases(offers,situation,*,traits=None,progress=None,copies=None,preferences=None):
    result=[]
    for offer in offers:
        scored=score_purchase(offer,situation,traits=(traits or {}).get(offer.slot,()),progress=progress,
                              same_star_copies=(copies or {}).get(offer.name),preference=(preferences or {}).get(offer.name,0.))
        if scored is not None:
            result.append(scored)
    return tuple(sorted(result,key=lambda item:(-item.score,item.cost,item.slot)))
