"""Account evidence shared by high-difficulty preparation and slot comparison."""
from .currency_wars_identity import AccountNotObserved, account_key
from .models import AutomationError


def verified_account(scene, confidence, *, expected=None):
    # A complete UID can veto at collection confidence. Binding still needs
    # the stricter positive threshold used by the native account reader.
    try:
        candidate = account_key(scene, confidence)
    except AccountNotObserved:
        raise
    except AutomationError:
        raise AutomationError('高难备战账号标识未完整核实，画面含多个完整候选。') from None
    if expected is not None and candidate != expected:
        raise AutomationError('高难备战账号改变，未继续选择。')
    return account_key(scene, max(.85, confidence))
