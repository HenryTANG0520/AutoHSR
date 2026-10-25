"""BetterGI-style foreground logs; display only, never game input."""
from __future__ import annotations
import queue
import time
import ctypes as C
from .overlay_native import GameLogOverlay, NativePresentation, overlay_bounds

TASK_LABELS = {
    'assignments': '持续委托', 'battle': '副本挑战', 'daily': '每日实训',
    'mail': '邮件奖励', 'battlepass': '无名勋礼',
    'differential_universe': '差分宇宙', 'dungeon_catalogue': '副本目录',
}


def apply_event(overlay, event):
    """The same event stream feeds both file logs and the foreground display."""
    kind = event.get('type')
    if kind == 'log':
        overlay.append(str(event.get('message', '')), event.get('level', 'info'))
    elif kind == 'task':
        label = TASK_LABELS.get(event.get('task'), event.get('task', '任务'))
        overlay.set_status(str(label))
        overlay.append(f"{label}：{event.get('detail', '')}")
    elif kind == 'paused':
        overlay.set_status('已暂停' if event.get('paused') else '继续运行')
    elif kind == 'focus_wait':
        overlay.set_status('等待游戏回到前台' if event.get('waiting') else '正在运行')


def _serve(inbox, notices, game_handle):
    overlay = None
    try:
        presentation = NativePresentation()
        try:
            presentation.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        except AttributeError:
            pass
        overlay = GameLogOverlay(None, lambda: game_handle,
            lambda text, level: notices.put((text, level)), presentation=presentation)
        if overlay.handle is None:
            return
        overlay.begin('正在准备任务')
        notices.put(('前台日志字幕已启用；鼠标穿透、不抢焦点，并已从识别截图中排除。', 'info'))

        running = True
        while running:
            # Bounded draining prevents a log burst from blocking rendering.
            for _ in range(100):
                try:
                    event = inbox.get_nowait()
                except queue.Empty:
                    break
                if event.get('type') == 'close':
                    running = False
                    break
                apply_event(overlay, event)
            overlay._tick()
            presentation.pump()
            time.sleep(.1)
    except Exception as error:
        notices.put((f'前台日志字幕无法显示，文件日志继续保留：{error}', 'warning'))
    finally:
        if overlay is not None:
            overlay.close()


class OverlayService:
    """Optional display only; failure cannot interrupt or replay automation."""
    def __init__(self):
        self.process = self.inbox = self.notices = None

    def start(self, game_handle):
        if type(game_handle) is not int or game_handle <= 0:
            return
        import multiprocessing
        context = multiprocessing.get_context('spawn')
        self.inbox, self.notices = context.Queue(maxsize=256), context.Queue(maxsize=16)
        self.process = context.Process(target=_serve,
            args=(self.inbox, self.notices, game_handle), name='AutoHSR-log-subtitles', daemon=True)
        self.process.start()

    def publish(self, event):
        if self.inbox is not None and event.get('type') in ('log', 'task', 'paused', 'focus_wait'):
            try:
                self.inbox.put_nowait(dict(event))
            except (queue.Full, OSError, ValueError, EOFError):
                pass  # File logs remain complete even when display drops a burst.

    def drain_notices(self):
        while self.notices is not None:
            try:
                yield self.notices.get_nowait()
            except (queue.Empty, OSError, ValueError, EOFError):
                return

    def close(self):
        if self.process is not None and self.process.pid is not None:
            try:
                self.inbox.put_nowait(dict(type='close'))
            except (queue.Full, OSError, ValueError, EOFError):
                pass
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
            self.process.close()
        for channel in (self.inbox, self.notices):
            if channel is not None:
                channel.cancel_join_thread()
                channel.close()
        self.process = self.inbox = self.notices = None
