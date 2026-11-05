"""Keep downstream native input within the accepted DU points observation's week."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .models import AutomationError


_permission = ContextVar('autohsr_du_points_followup', default=None)


@dataclass
class FollowupWeek:
    week: str
    expired: bool = field(default=False, init=False)

    def require_current(self):
        from .du_periodic_points import game_week, local_now

        if self.expired or game_week(local_now()) != self.week:
            self.expired = True
            raise AutomationError('差分积分后续任务的游戏周已切换，原周输入权限失效。')


@contextmanager
def followup_week_scope(permission):
    if permission is None:
        yield
        return
    token = _permission.set(permission)
    try:
        permission.require_current()
        yield
    finally:
        _permission.reset(token)


def require_followup_week():
    permission = _permission.get()
    if permission is not None:
        permission.require_current()
