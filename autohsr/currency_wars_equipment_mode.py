"""Optional generic-equipment schedule; named-core preparation stays separate.

Reference: pinned March7thAssistant equip_weapons/check_main_screen call graph.
Only the native standard entry is wired; other gameplay modes stay independent.
"""
from .models import AutomationError

FAST_FIELD = 'equipment_fast_mode'
STANDARD_BOSSES = frozenset(('1-9','2-7','3-7'))


def validate_fast_mode(value):
    if type(value) is not bool:raise ValueError('货币战争速通装备开关须为布尔值。')
    return value


def stored_fast_mode(session):
    try:return validate_fast_mode((session or {}).get(FAST_FIELD,False))
    except ValueError as exc:raise AutomationError('本局速通装备设置损坏，未推定或改写设置。') from exc


def resolve_fast_mode(settings,explicit=None,session=None,*,resume=False):
    requested=None if explicit is None else validate_fast_mode(explicit)
    if resume:
        saved=stored_fast_mode(session)
        if requested is not None and requested is not saved:
            raise AutomationError('本次速通装备设置与已记录对局不同，未中途改写。')
        return saved
    return validate_fast_mode(getattr(settings,'currency_fast_mode',False) if requested is None else requested)


def generic_allowed(snapshot,fast_mode=False):
    if not validate_fast_mode(fast_mode):return True
    return ((snapshot.mode,snapshot.game_version,snapshot.rules_version)==('standard','4.6','4.6')
            and snapshot.node in STANDARD_BOSSES)
