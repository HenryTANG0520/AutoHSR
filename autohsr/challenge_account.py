"""Account evidence shared by high-difficulty preparation and slot comparison."""
from .currency_wars_identity import UID_COUNTEREVIDENCE, AccountNotObserved, account_key
from .models import AutomationError, Scene


def verified_account(scene, confidence, *, expected=None, veto_floor=None):
    # A complete UID can veto at collection confidence. Binding still needs
    # the stricter positive threshold. A reader may retain veto-only tokens
    # separately when its configured collection threshold is higher.
    low = scene.field_reads.get(UID_COUNTEREVIDENCE, ()) if veto_floor is not None else ()
    candidates = Scene([*scene.tokens, *low]) if low else scene
    veto_confidence = min(veto_floor, confidence) if veto_floor is not None else confidence
    try:
        candidate = account_key(candidates, veto_confidence)
    except AccountNotObserved:
        raise
    except AutomationError:
        raise AutomationError('高难备战账号标识未完整核实，画面含多个完整候选。') from None
    if expected is not None and candidate != expected:
        raise AutomationError('高难备战账号改变，未继续选择。')
    return account_key(scene, max(.85, confidence))
