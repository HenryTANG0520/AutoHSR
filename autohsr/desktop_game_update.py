"""Game version checks and official launcher handoff in the desktop tools."""

from queue import SimpleQueue
from threading import Event, Thread
import tkinter as tk
from tkinter import ttk

from .desktop_services import _PaperPanel
from .game_update_launcher import handoff, prepare_launcher, track_installation, verify_installation
from .models import AutomationError


_CHANNELS = {'国服': 'cn', '国际服': 'global'}
_ACTIONS = {'游戏更新': 'update', '预下载': 'pre_download'}
_UPDATE = {'available': '有新版', 'current': '已是当前版本', 'local_ahead': '本机版本较新', 'unknown': '待核实'}
_PRELOAD = {'advertised': '官方已列出包', 'not_advertised': '官方尚未列出包',
            'local_at_or_ahead': '本机已达到版本', 'unknown': '待核实'}


class _GameUpdatePanel(_PaperPanel):
    def __init__(self, parent, ui):
        super().__init__(parent, ui, '游戏更新与预下载')
        self.channel = tk.StringVar(master=self, value='国服')
        self.action = tk.StringVar(master=self, value='游戏更新')
        self.feedback = tk.StringVar(master=self, value='按「游戏连接」中选择的星铁安装检查官方版本。')
        self.versions = tk.StringVar(master=self)
        self.offer = self.pending = None
        self.checked_scope = None
        self.tracking = self._tracking_after = None
        row = self._row(1, '渠道与操作')
        for variable, choices in ((self.channel, _CHANNELS), (self.action, _ACTIONS)):
            choice = self._control(ttk.Combobox(row, textvariable=variable, values=tuple(choices),
                                                width=10, state='readonly'), state='readonly')
            choice.pack(side='left', padx=(0, self.pad))
            self._watch(variable)
        self._note(2, variable=self.versions)
        self._note(3, variable=self.feedback)
        controls = self._row(4, '版本检查')
        self._control(ttk.Button(controls, text='重新检查', command=self._check)).pack(side='left')
        self.stop_tracking_button = self._control(ttk.Button(
            controls, text='停止跟踪', command=self._cancel_tracking))
        self.stop_tracking_button.pack(side='left', padx=(self.pad, 0))
        self.refresh_controls()

    def _scope(self):
        return self.ui.game_path.get().strip(), _CHANNELS[self.channel.get()], _ACTIONS[self.action.get()]

    def primary_action(self):
        path, _, _ = scope = self._scope()
        idle = bool(path) and not (self.ui.busy or self.ui.closing)
        if scope == self.checked_scope:
            if self.pending is not None:
                return '核对安装版本', self._verify, idle
            if self.offer is not None:
                return '打开官方启动器', self._handoff, idle
        return '检查游戏版本', self._check, idle

    def focus_entry(self):
        self.ui.footer_start_button.focus_set()

    def refresh_controls(self):
        if self.checked_scope is not None and self.checked_scope != self._scope():
            self._stop_tracking()
            self.checked_scope = self.offer = self.pending = None
            self.versions.set('')
            self.feedback.set('选择已变化，请检查本次游戏版本。')
        super().refresh_controls()
        if self.tracking is None:
            self.stop_tracking_button.state(('disabled',))

    def _destroyed(self, event):
        if event.widget is self:
            self._stop_tracking()
        super()._destroyed(event)

    def _stop_tracking(self):
        if self.tracking is not None:
            self.tracking[0].set()
            self.tracking = None
        if self._tracking_after is not None:
            self.after_cancel(self._tracking_after)
            self._tracking_after = None

    def _cancel_tracking(self):
        self._stop_tracking()
        self.feedback.set('已停止自动跟踪，可随时手动核对安装版本。')
        self._action_changed()

    def _start_tracking(self, offer):
        stop, updates = Event(), SimpleQueue()
        worker = Thread(target=track_installation, kwargs=dict(offer=offer, stop=stop, emit=updates.put),
                        name='autohsr-game-update-track', daemon=True)
        try:
            worker.start()
        except RuntimeError:
            return False
        self.tracking = stop, updates, worker
        self._tracking_after = self.after(500, self._poll_tracking)
        return True

    def _poll_tracking(self):
        self._tracking_after = None
        if self.tracking is None:
            return
        if self.ui.closing or self.checked_scope != self._scope():
            self._stop_tracking()
            return
        _, updates, worker = self.tracking
        latest = None
        while not updates.empty():
            latest = updates.get_nowait()
        if latest is not None:
            installed, target = latest.get('installed_version'), latest['target']
            if installed:
                self.versions.set(f'本机 {installed} · 本次目标 {target}')
            state = latest['tracking']
            if state == 'verified':
                self.pending = None
                self.feedback.set('已连续核实本机安装达到本次目标版本。')
                self._stop_tracking()
            elif state == 'source_changed':
                self.pending = None
                self.feedback.set('星铁安装来源已变化，请重新检查。')
                self._stop_tracking()
            elif state == 'timeout':
                self.feedback.set('跟踪时间已到，安装版本仍待核实。可继续在启动器中查看。')
                self._stop_tracking()
            elif state == 'confirming':
                self.feedback.set('已读到目标版本，正在复核。')
            elif state == 'version_unavailable':
                self.feedback.set('当前安装版本暂时无法读取，仍在跟踪。')
            else:
                self.feedback.set('正在跟踪安装版本。请在官方启动器确认更新及查看下载进度。')
            self._action_changed()
        elif not worker.is_alive():
            self.feedback.set('自动跟踪未完成，可手动核对安装版本。')
            self._stop_tracking()
            self._action_changed()
        if self.tracking is not None:
            self._tracking_after = self.after(500, self._poll_tracking)

    def _check(self):
        if self.ui.busy or self.ui.closing:
            return
        scope = self._scope()
        if not scope[0]:
            self.feedback.set('请先在「游戏连接」中选择 StarRail.exe。')
            return

        def work(cancel):
            return None if cancel.is_set() else prepare_launcher(*scope)

        def done(result):
            if result is None or self.ui.stop_requested.is_set():
                self.feedback.set('已停止检查。')
            elif self._scope() == scope:
                report, self.offer = result
                self.checked_scope = scope
                installed = report['installed_version'] or '待核实'
                release = report['release_version'] or '待核实'
                preload = report['pre_download_version'] or '—'
                self.versions.set(f'本机 {installed} · 官方发布 {release} · 预下载 {preload}')
                status = f'更新：{_UPDATE[report["update"]]}。预下载：{_PRELOAD[report["pre_download"]]}。'
                package = report.get(scope[2] + '_package')
                if package is not None:
                    kind = '差分包' if package['kind'] == 'patch' else '完整包'
                    size = package['download_bytes']
                    amount = f'{size / 1024 ** 3:.2f} GiB' if size >= 1024 ** 3 else f'{size / 1024 ** 2:.2f} MiB'
                    status += f'\n清单{kind}约 {amount}，语音包另计。'
                if self.offer is not None:
                    status += '可打开对应官方启动器继续。'
                elif 'launcher' in report:
                    status += '请核对游戏渠道和启动器安装来源。'
                self.feedback.set(status)
            self._action_changed()

        if self.ui._submit_tool_job('检查游戏版本', work, done, self._error):
            self._stop_tracking()
            self.offer = self.pending = None
            self.versions.set('')
            self.feedback.set('正在核对本机安装与官方包清单。')

    def _handoff(self):
        _, callback, ready = self.primary_action()
        if callback != self._handoff or not ready:
            return
        offer = self.offer

        def work(cancel):
            return handoff(offer, cancelled=cancel.is_set)

        def done(report):
            self.offer = None
            if report['status'] == 'stopped':
                self.feedback.set('已停止，未发送启动请求。')
            elif offer.action == 'update':
                self.pending = offer
                if self._start_tracking(offer):
                    self.feedback.set('已请求打开官方启动器。请在启动器确认更新，助手会跟踪安装版本。')
                else:
                    self.feedback.set('已请求打开官方启动器。更新后可手动核对安装版本。')
            else:
                self.feedback.set('已请求打开官方启动器。请在启动器中确认预下载和查看进度。')
            self._action_changed()

        if self.ui._submit_tool_job('打开官方启动器', work, done, self._error):
            self.feedback.set('正在复核版本、渠道和启动器签名。')

    def _verify(self):
        _, callback, ready = self.primary_action()
        if callback != self._verify or not ready:
            return
        offer = self.pending

        def work(cancel):
            return None if cancel.is_set() else verify_installation(offer)

        def done(report):
            if self.pending is not offer:
                return
            if report is None or self.ui.stop_requested.is_set():
                self.feedback.set('已停止核对。')
            else:
                installed, target = report['installed_version'], report['target']
                self.versions.set(f'本机 {installed} · 本次目标 {target}')
                if report['status'] == 'success':
                    self.pending = None
                    self._stop_tracking()
                    self.feedback.set('已核实本机安装达到本次目标版本。')
                else:
                    self.feedback.set('本机安装还未达到目标版本，可在官方启动器中查看进度。')
            self._action_changed()

        self.ui._submit_tool_job('核对安装版本', work, done, self._error)

    def _error(self, error):
        self.offer = None
        self.feedback.set(str(error) if isinstance(error, AutomationError) else '操作未完成，请重新检查。')
        self._action_changed()


def build_game_update_panel(parent, ui):
    return _GameUpdatePanel(parent, ui)
