"""Observed experience and the versioned level-ten maximum are distinct states."""
import re

from .currency_wars_prepare import trusted
from .models import normalize


def experience_observed(scene,state,confidence=.65):
    if state is None or type(state.level) is not int or not 1<=state.level<=10:return False
    tokens=trusted(scene,confidence).tokens
    maximum=any(normalize(t.text) in ('满级','已满级') and t.within((.1,.77,.2,.87)) for t in tokens)
    if state.level==10:
        fractions=any(t.within((.13,.865,.18,.9)) and re.fullmatch(r'[0-9]+/[0-9]+',normalize(t.text)) for t in tokens)
        return state.experience is None and maximum and not fractions
    return state.experience is not None and not maximum
