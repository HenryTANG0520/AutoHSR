"""App update actions in the existing desktop tools shelf."""

import sys
import tkinter as tk
from tkinter import ttk

from . import __version__
from .app_update import UpdateError
from .app_update_dispatch import begin, check_for_update, recent_result
from .app_update_handoff import cancel_job
from .app_update_install import maintenance
from .app_update_windows import handoff_lock
from .config import ROOT
from .desktop_services import _PaperPanel


def _history_message(report):
    if report is None:
        return '本机暂无自动更新记录。'
    version = report['version']
    if report['status'] == 'success':
        if report['desktop_restart'] == 'ready':
            return f'上次更新至 {version}，新版窗口已就绪。'
        return f'上次更新至 {version}，安装和运行时检查已完成。'
    if report['installation'] == 'original':
        return f'更新至 {version} 后启动核对失败，已恢复原运行文件。'
    if report['status'] == 'partial':
        return f'已安装 {version}，桌面就绪待核对，已保留旧运行文件。'
    if report['status'] == 'pending':
        return f'更新至 {version} 的回执尚未写入。'
    if report['status'] == 'stopped':
        return f'更新至 {version} 已停止。'
    return f'更新至 {version} 未完成，可核对上次运行记录。'


class _UpdatePanel(_PaperPanel):
    def __init__(self, parent, ui):
        super().__init__(parent, ui, '助手更新')
        self.checked = None
        self.can_accept = False
        self.queued = False
        self.version = tk.StringVar(master=self, value=f'当前版本 {__version__}')
        self.feedback = tk.StringVar(master=self, value='检查 GitHub 正式版。更新会保留配置和运行记录。')
        self.history = tk.StringVar(master=self, value='')
        self._note(1, variable=self.version)
        self._note(2, variable=self.feedback)
        controls = self._row(3, '更新记录')
        self.history_button = self._control(ttk.Button(controls, text='查看上次结果', command=self._show_history))
        self.history_button.pack(side='left')
        self.retry_button = ttk.Button(controls, text='重新检查', command=self._check)
        self.retry_button.pack(side='left', padx=self.pad)
        self.accept_button = ttk.Button(controls, text='清理更新备份', command=self._accept)
        self.accept_button.pack(side='left')
        self._note(4, variable=self.history)
        self.refresh_controls()

    def focus_entry(self):
        target = self.ui.footer_start_button if self.primary_action()[2] else self.history_button
        target.focus_set()

    def refresh_controls(self):
        super().refresh_controls()
        idle = not (self.ui.busy or self.ui.closing or self.queued)
        self.history_button.configure(state='normal' if idle else 'disabled')
        self.retry_button.configure(state='normal' if idle and self.checked is not None else 'disabled')
        self.accept_button.configure(state='normal' if idle and self.can_accept else 'disabled')

    def primary_action(self):
        idle = not (self.ui.busy or self.ui.closing or self.queued)
        result = self.checked
        if result is not None and result.relation == 'available' and result.can_install:
            return '更新并重启', self._update, idle and not result.previous_transaction
        return '检查更新', self._check, idle

    def _check(self):
        if self.ui.busy or self.ui.closing or self.queued:
            return

        def work(cancel):
            result = check_for_update(ROOT) if not cancel.is_set() else None
            return None if cancel.is_set() else result

        def finished(result):
            self.checked = result
            if result is None:
                self.feedback.set('已停止检查。')
            else:
                release = result.release.tag[1:]
                self.version.set(f'当前版本 {result.installed} · 正式版 {release}')
                if result.relation == 'current':
                    self.feedback.set('本机版本与正式版一致。')
                elif result.relation == 'local_ahead':
                    self.feedback.set('本机版本高于当前正式版。')
                elif not result.can_install:
                    self.feedback.set(f'正式版 {release} 可用。可从带独立更新器的便携包发起安装。')
                elif result.previous_transaction:
                    self.feedback.set('请先查看上次更新结果，再清理备份或回滚。')
                else:
                    self.feedback.set(f'正式版 {release} 可用。选择更新后，助手会退出并在核验后重开。')
            self._action_changed()

        self.checked = None
        if self.ui._submit_tool_job('检查助手更新', work, finished, self._error):
            self.feedback.set('正在核对正式版。')
            self._action_changed()

    def _idle_to_close(self):
        ui = self.ui
        return (not (ui.busy or ui.closing or ui.dirty or ui.book_editor is not None
                     or ui.desktop_schedule.owned) and ui.desktop_schedule.runtime.wait_idle(0))

    def _update(self):
        label, _, ready = self.primary_action()
        if label != '更新并重启' or not ready:
            return
        if not self._idle_to_close():
            self.feedback.set('请先保存或撤销设置修改，并等当前任务结束。')
            return
        release = self.checked.release

        def work(cancel):
            return begin(ROOT, expected_release=release, cancelled=cancel.is_set)

        def finished(result):
            self.checked = None
            if result.get('status') == 'queued':
                self.queued = True
                self.feedback.set('更新器已接管，助手即将退出。')
                self.ui.root.after_idle(lambda: self._close_for_update(result['job']))
            elif result.get('status') == 'stopped':
                self.feedback.set('已停止更新。')
            else:
                self.feedback.set('当前版本已符合正式版，更新器无需启动。')
            self._action_changed()

        if self.ui._submit_tool_job('交接助手更新', work, finished, self._error):
            self.feedback.set('正在确认所选版本并启动更新器。')

    def _close_for_update(self, job):
        if not self.ui.stop_requested.is_set() and self._idle_to_close():
            self.ui._close()
            return
        try:
            cancel_job(ROOT / 'runs' / 'app-update' / job)
        except (OSError, UpdateError):
            self.feedback.set('撤回回执未保存。请保持助手打开，等更新器结束。')
        else:
            self.feedback.set('已撤回本次更新交接。')
        self.queued = False
        self._action_changed()

    def _show_history(self):
        def work(cancel):
            report = recent_result(ROOT)
            state = maintenance(ROOT, 'status') if getattr(sys, 'frozen', False) else {}
            return None if cancel.is_set() else (report, state)

        def finished(result):
            if result is None:
                return
            report, state = result
            self.can_accept = (state.get('installation') in ('installed', 'original')
                               and state.get('backup_retained') is True)
            message = _history_message(report)
            if self.can_accept:
                message += ' 清理备份后将无法恢复旧运行文件。'
            self.history.set(message)
            self._action_changed()

        self.ui._submit_tool_job('读取上次更新结果', work, finished, self._error)

    def _accept(self):
        if not self.can_accept or self.ui.busy or self.ui.closing or self.queued:
            return

        def work(cancel):
            with handoff_lock(ROOT):
                return None if cancel.is_set() else maintenance(ROOT, 'accept')

        def finished(result):
            if result is None:
                return
            self.can_accept = False
            self.checked = None
            if result.get('installation') == 'no_transaction':
                self.history.set('当前没有待清理的更新备份。')
            elif result.get('cleanup_pending'):
                self.history.set('更新备份已移出事务，仍有文件待清理。')
            else:
                self.history.set('已清理更新备份。')
            self._action_changed()

        self.ui._submit_tool_job('清理更新备份', work, finished, self._error)

    def _error(self, error):
        self.checked = None
        if isinstance(error, UpdateError) and str(error) == 'release_changed_after_check':
            self.feedback.set('正式版已变化，请重新检查版本。')
        elif self.ui.stop_requested.is_set():
            self.feedback.set('本次操作已停止。')
        else:
            self.feedback.set('更新操作未完成，请检查网络或查看上次结果。')
        self._action_changed()


def build_update_panel(parent, ui):
    return _UpdatePanel(parent, ui)
