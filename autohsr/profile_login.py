"""Enter an already authenticated Star Rail session for the current profile."""

from dataclasses import dataclass
import time

from .currency_wars_identity import account_key_from_uid
from .models import AutomationError, InputInterrupted, normalize
from .redemption_server import require_binding, resolve
from .workflow_identity import native_window


# These are the two Windows client keys, not HoYoPlay's shared account storage.
GAME_KEYS = {'cn': r'Software\miHoYo\崩坏：星穹铁道', 'global': r'Software\Cognosphere\Star Rail'}
LAST_UID = 'App_LastUserID_h2841727341'
ENTER_LABELS = ('点击进入', '点击进入游戏')
ENTER_REGION = (.32, .77, .68, .985)


def _cached_key(executable, configured):
    import winreg

    try:
        binding = resolve(executable)
        require_binding(configured, binding)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GAME_KEYS[binding.server], 0, winreg.KEY_READ) as key:
            uid, value_type = winreg.QueryValueEx(key, LAST_UID)
        if value_type != winreg.REG_DWORD or type(uid) is not int:
            raise ValueError()
        return account_key_from_uid(str(uid))
    except (OSError, ValueError, AutomationError):
        raise AutomationError('当前安装或游戏上次账号无法核实，请手动进入游戏。') from None


@dataclass(frozen=True)
class _EntryFrame:
    epoch: int
    sequence: int
    geometry: object
    center: tuple[float, float]
    captured_at: float
    window_key: str


class CachedProfileLogin:
    def __init__(self, context, workflow):
        self.context, self.workflow = context, workflow
        self.first = None
        self.status = context.report.profile_login = dict(enter_submitted=False, account_verified=False)

    def observe(self, scene):
        """Consume only the cached-session entry page during initial startup."""
        if self.status['account_verified']:
            return False
        workflow, context = self.workflow, self.context
        candidates = [token for token in scene.tokens if normalize(token.text) in ENTER_LABELS]
        if (not workflow._login(scene) or workflow._login_blocked(scene) or workflow._phone(scene)
                or workflow._world(scene) or len(candidates) != 1):
            self.first = None
            return False
        target = candidates[0]
        if not target.within(ENTER_REGION) or target.score < max(.85, context.settings.ocr_confidence):
            self.first = None
            return False
        if self.status['enter_submitted']:
            return True
        window = native_window(context)
        window_key = window.current_window_key()
        if not window_key:
            raise AutomationError('无法核实当前登录窗口，请手动进入游戏。')
        current = _EntryFrame(context.scene_epoch, context.capture_sequence, scene.geometry, target.center,
                              scene.captured_at, window_key)
        first, self.first = self.first, current
        if (first is None or first.epoch != current.epoch or first.sequence + 1 != current.sequence
                or first.geometry != current.geometry or first.window_key != current.window_key
                or not 0 <= current.captured_at - first.captured_at <= 5
                or any(abs(a - b) > .015 for a, b in zip(first.center, current.center))):
            return True

        def check_frame():
            context.checkpoint()
            window.guard(current.geometry)
            if (context.last_scene is not scene or context.runner.input_epoch != current.epoch
                    or context.capture_sequence != current.sequence or window.current_window_key() != current.window_key
                    or not 0 <= time.monotonic() - current.captured_at <= 5):
                raise InputInterrupted('登录画面或输入代次已改变，未继续使用旧目标。')

        def check_account():
            check_frame()
            if _cached_key(window.current_executable(), context.settings.game_path) != context.settings.profile_account_key:
                raise AutomationError('游戏上次账号与当前方案不符，请在游戏中手动切换。')

        def mark_submission():
            check_frame()
            self.status['enter_submitted'] = True

        window.click(*target.center, scene.geometry, before_send=check_account, before_submit=mark_submission)
        return True
