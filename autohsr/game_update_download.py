"""Guarded input for the selected Star Rail page of a verified launcher."""

from pathlib import Path
import time

from .game_update_launcher import _source, _target, _verify_publisher, check_game_update
from .models import AutomationError, Stopped, normalize
from .vision import Vision, helper_overlay
from .windows import GameWindow, geometry, process_path, user32
from .workflow_lease import native_idle_lease


_GAME = ('崩坏：星穹铁道', '崩坏: 星穹铁道', 'Honkai: Star Rail')
_OTHER_GAMES = ('原神', '绝区零', '崩坏3', 'Genshin Impact', 'Zenless Zone Zero', 'Honkai Impact 3rd')
_DETAIL = (.18, .12, .94, .75)
_BLOCKED = ('立即更新', '稍后更新', '空间不足', '磁盘空间不足', '重试', '下载失败', '安装目录',
            'Update Launcher', 'Insufficient Disk Space', 'Retry', 'Download Failed')
_BUTTONS = {'update': ('更新游戏', 'Update Game'),
            'pre_download': ('预下载', 'Pre-Download'),
            'confirm': ('确认下载', 'Confirm Download')}
_PRELOAD_DIALOG = ('预下载', '游戏预下载', '预下载游戏资源', 'Pre-Download', 'Game Pre-Download')
_PROGRESS = {
    'update': ('正在下载', '暂停下载', '下载中', '正在解压', '正在校验', 'Downloading', 'Pause Download', 'Verifying'),
    'pre_download': ('正在预下载', '预下载中', '暂停预下载', 'Pre-Downloading', 'Pause Pre-Download'),
}
_PROGRESS_REGION = (.33, .52, .99, .995)


def _exact(scene, labels):
    names = {normalize(label) for label in labels}
    return [token for token in scene.tokens if token.score >= .85 and normalize(token.text) in names]


def _page(scene):
    titles = [token for token in _exact(scene, _GAME)
              if token.within(_DETAIL) and token.box[3] - token.box[1] >= .025]
    return (len(titles) == 1 and not any(token.within(_DETAIL) for token in _exact(scene, _OTHER_GAMES))
            and not scene.has(_BLOCKED) and not helper_overlay(scene))


def _button(scene, phase):
    if not _page(scene) or any(_progress(scene, action) for action in _PROGRESS):
        return None
    if phase == 'confirm':
        if len(_exact(scene, _PRELOAD_DIALOG)) != 1:
            return None
    elif scene.has(_BUTTONS['confirm'], exact=True):
        return None
    region = (.26, .42, .86, .92) if phase == 'confirm' else (.45, .62, .99, .995)
    targets = _exact(scene, _BUTTONS[phase])
    if len(targets) == 1 and targets[0].within(region):
        return targets[0]
    return None


def _progress(scene, action):
    return any(token.within(_PROGRESS_REGION) for token in _exact(scene, _PROGRESS[action]))


class _LauncherWindow(GameWindow):
    def __init__(self, hwnd, source):
        super().__init__(hwnd)
        self.source = source

    def guard(self, expected=None):
        if not user32.IsWindow(self.hwnd) or user32.IsIconic(self.hwnd):
            raise AutomationError('请保持官方启动器窗口打开。')
        self.require_foreground()
        try:
            executable = Path(process_path(self.hwnd)).resolve(strict=True)
            stat = executable.stat()
        except (OSError, RuntimeError, ValueError):
            raise AutomationError('前台启动器的进程来源无法核实。') from None
        fingerprint = stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
        if executable != self.source.launcher or fingerprint != self.source.launcher_identity:
            raise AutomationError('请将对应渠道的官方启动器置于前台。')
        area = geometry(self.hwnd)
        left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        if (area.width < 640 or area.height < 400 or area.left < left or area.top < top
                or area.left + area.width > left + user32.GetSystemMetrics(78)
                or area.top + area.height > top + user32.GetSystemMetrics(79)):
            raise AutomationError('请将完整的官方启动器窗口置于屏幕内。')
        if expected is not None and area != expected:
            raise AutomationError('启动器窗口位置或尺寸已变化。')
        return area


def _foreground(source, stop):
    for _ in range(30):
        if stop.is_set() or GameWindow.emergency_pressed():
            raise Stopped('启动器操作已停止。')
        hwnd = user32.GetForegroundWindow()
        if hwnd and Path(process_path(hwnd)) == source.launcher:
            return _LauncherWindow(hwnd, source)
        stop.wait(.15)
    raise AutomationError('请将对应渠道的官方启动器置于前台。')


class _Download:
    def __init__(self, offer, window, vision, stop, result):
        self.offer, self.window, self.vision, self.stop, self.result = offer, window, vision, stop, result
        self.window_key = window.current_window_key()
        if not self.window_key:
            raise AutomationError('前台启动器窗口身份无法核实。')

    def check(self, expected=None):
        if self.stop.is_set() or self.window.emergency_pressed():
            raise Stopped('启动器操作已停止。')
        self.window.guard(expected)
        if self.window.current_window_key() != self.window_key:
            raise AutomationError('启动器窗口身份已变化。')

    def capture(self):
        self.check()
        image, area = self.window.capture()
        captured_at = time.monotonic()
        scene = self.vision.read(image, area)
        self.check(area)
        return scene, captured_at

    def click(self, phase):
        first = None
        for _ in range(6):
            scene, captured_at = self.capture()
            target = _button(scene, phase)
            if target is not None and first is not None:
                previous, stamp, area = first
                if (area == scene.geometry and 0 <= captured_at - stamp <= 8
                        and all(abs(a - b) <= .015 for a, b in zip(previous.center, target.center))):
                    self._submit(phase, scene, target, captured_at)
                    return
            first = (target, captured_at, scene.geometry) if target is not None else None
            self.stop.wait(.20)
        raise AutomationError('未连续核实星铁页面及对应按钮，请在启动器中确认。')

    def _submit(self, phase, scene, target, captured_at):
        path = self.offer.source.client['executable']

        def recheck():
            self.check(scene.geometry)
            if _source(path, self.offer.channel) != self.offer.source:
                raise AutomationError('版本或启动器来源已变化，请重新检查。')

        def submit():
            self.check(scene.geometry)
            if not 0 <= time.monotonic() - captured_at <= 8:
                raise AutomationError('下载按钮画面已过期，请重新确认。')
            self.result['submissions'].append(phase)

        self.window.click(*target.center, scene.geometry, before_send=recheck, before_submit=submit)

    def observe_feedback(self):
        count = 0
        for _ in range(4):
            scene, captured_at = self.capture()
            current = (_page(scene) and _progress(scene, self.offer.action)
                       and time.monotonic() - captured_at <= 8)
            count = count + 1 if current else 0
            if count >= 2:
                return True
            self.stop.wait(.35)
        return False


def request_download(offer, *, stop):
    """Submit each explicitly requested launcher control at most once."""
    result = dict(status='failed', action=offer.action, target=offer.target, channel=offer.channel,
                  submissions=[], progress_observed=False)
    try:
        if offer.action not in ('update', 'pre_download') or not offer.target:
            raise AutomationError('请先核实对应渠道的官方目标版本。')
        path = offer.source.client['executable']
        if _target(check_game_update(path, offer.channel), offer.action) != offer.target:
            raise AutomationError('官方目标版本已变化，请重新检查。')
        if _source(path, offer.channel) != offer.source:
            raise AutomationError('游戏安装或启动器来源已变化，请重新检查。')
        _verify_publisher(offer.source.launcher, offer.channel)
        with native_idle_lease():
            window = _foreground(offer.source, stop)
            automation = _Download(offer, window, Vision(.65), stop, result)
            automation.click(offer.action)
            if offer.action == 'pre_download':
                automation.click('confirm')
            result['progress_observed'] = automation.observe_feedback()
            result['status'] = 'partial'
    except Stopped as error:
        result.update(status='stopped', message=str(error))
    except AutomationError as error:
        result.update(status='partial' if result['submissions'] else 'failed', message=str(error))
    except (OSError, ValueError, RuntimeError):
        result.update(status='partial' if result['submissions'] else 'failed',
                      message='启动器反馈无法核实，请在官方启动器中查看。')
    return result
