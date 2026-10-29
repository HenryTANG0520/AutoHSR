"""Supply priorities adapted from March7th check_supply_phase.

Pinned source and GPL license: assets/upstream/March7thAssistant/source.json.
Only observed owned stars and equipment determine the remaining needs.
"""
from collections import Counter

from .currency_wars_character_rewards import require_roster
from .currency_wars_standard_policy import preferred_names


def groups(data,strategy):
    if strategy not in ('aglaea','seele'):return ()
    units=require_roster(data['basis']['snapshot'])
    from .currency_wars_names import basis_name
    preferences=preferred_names(strategy,basis_name(data))
    core='阿格莱雅' if strategy=='aglaea' else '希儿'
    highest=max((u['star'] for u in units if u['name']==core),default=0)
    owned={u['name'] for u in units}
    bank=Counter(data['basis']['inventory'])+Counter(g for u in units if u['name']==core for g in u['equipment'])
    result=[]
    if strategy=='aglaea':
        if bank['shoe']+2*bank['boots']<4:result.append(('item',('boots','shoe')))
        if highest<3:result.append(('unit',(core,)))
        if highest>=3:
            names=tuple(n for n in preferences[1:] if n not in owned)
            if names:result.append(('unit',names))
        if bank['propeller']<1:result.append(('item',('propeller',)))
    else:
        missing=[]
        for goal,amount,a,b in (('firestorm',2,'shoe','knife'),('chainsaw',1,'star','knife')):
            if bank[goal]<amount:
                if bank[a] and not bank[b]:missing.append(b)
                elif bank[b] and not bank[a]:missing.append(a)
        if missing:result.append(('item',tuple(dict.fromkeys(missing))))
        if highest<3:result.append(('unit',(core,)))
        advanced=tuple(n for n,amount in (('firestorm',2),('chainsaw',1)) if bank[n]<amount)
        if advanced:result.append(('item',advanced))
        names=tuple(n for n in preferences[1:] if n not in owned)
        if names:result.append(('unit',names))
        if advanced:
            basics=('knife',)+(('shoe',) if 'firestorm' in advanced else ())+(('star',) if 'chainsaw' in advanced else ())
            result.append(('item',basics))
    return tuple(result)


def matches(options,group):
    kind,names=group
    index=2 if kind=='item' else 3
    return sorted((o for o in options if o[2] is not None and o[3] is not None and o[index] in names),key=lambda o:(names.index(o[index]),o[0]))


def preferred(options,data,strategy):
    for group in groups(data,strategy):
        found=matches(options,group)
        if found:return found[0]
    return None
