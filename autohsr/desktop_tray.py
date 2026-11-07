"""Keep the desktop window and its tasks alive while it is in the tray."""

from .config import RESOURCE_ROOT


class DesktopTray:
    def __init__(self, ui):
        self.ui = ui
        self.parked = False
        self.native = None
        self._pending = None
        self._poll_job = None
        ui.root.bind('<Destroy>', self._destroyed, add='+')

    def park(self) -> bool:
        if self.parked:
            return True
        from .tray_native import NativeTray
        try:
            if self.native is None:
                self.native = NativeTray(RESOURCE_ROOT / 'assets' / 'ui' / 'autohsr.ico', self._post)
            if not self.native.show():
                return False
        except OSError:
            return False
        self.parked = True
        self.ui.root.withdraw()
        self._poll_job = self.ui.root.after(75, self._poll)
        return True

    def restore(self) -> None:
        if self.ui.closing:
            return
        self.parked = False
        self._cancel_poll()
        self.native.hide()
        self.ui._restore()

    def _post(self, action) -> None:
        # A native message can arrive while Tcl is dispatching Windows events.
        # Leave all calls into Tk to its own timer callback.
        if self._pending is None:
            self._pending = action

    def _poll(self) -> None:
        self._poll_job = None
        action, self._pending = self._pending, None
        if action is not None:
            self._act(action)
        if self.parked and not self.ui.closing:
            self._poll_job = self.ui.root.after(75, self._poll)

    def _cancel_poll(self) -> None:
        self._pending = None
        if self._poll_job is not None:
            self.ui.root.after_cancel(self._poll_job)
            self._poll_job = None

    def _act(self, action) -> None:
        if self.ui.closing or not self.parked:
            return
        self.restore()
        if action == 'exit':
            self.ui._close()
        elif action == 'unavailable':
            self.ui.result_alert.set("系统托盘暂不可用，已重新打开助手。")

    def _destroyed(self, event) -> None:
        if event.widget is self.ui.root and self.native is not None:
            self._cancel_poll()
            self.native.close()
