"""Switch the saved desktop configuration after the current window is idle."""

import tkinter as tk
from tkinter import simpledialog

from .configuration_profiles import ConfigurationProfiles, ProfileError


class DesktopProfiles:
    def __init__(self, ui):
        self.ui = ui
        self.catalog = ConfigurationProfiles(ui.config_path)
        self.activate = None
        self.choice = tk.StringVar(master=ui.root, value=self.catalog.label_for(ui.config_path))
        self.feedback = tk.StringVar(master=ui.root, value=self._current_note())

    def _current_note(self):
        return f'当前方案 · {self.catalog.label_for(self.ui.config_path)}'

    def names(self):
        try:
            return self.catalog.names()
        except (OSError, ProfileError, RuntimeError):
            self.feedback.set('配置方案目录无法读取。')
            return (self.catalog.label_for(self.ui.config_path),)

    def connect(self, catalog, activate):
        self.catalog, self.activate = catalog, activate
        self.choice.set(catalog.label_for(self.ui.config_path))
        self.feedback.set(self._current_note())
        self.ui.configuration_profile_choice.configure(values=self.names())

    def _idle(self):
        ui = self.ui
        if ui.busy or ui.closing or (ui.worker is not None and ui.worker.is_alive()) or ui.book_editor is not None:
            self.feedback.set('请等当前任务或编辑结束。')
            return False
        return True

    def create(self):
        if not self._idle():
            return
        label = simpledialog.askstring('新建配置方案', '从当前已保存的配置复制一份。请输入方案名称。', parent=self.ui.root)
        if label is None or not self._idle():
            return
        try:
            self.catalog.copy(label, self.ui.config_path)
        except ProfileError as error:
            self.feedback.set(str(error))
        except (OSError, ValueError, RuntimeError):
            self.feedback.set('配置方案未保存。')
        else:
            self.ui.configuration_profile_choice.configure(values=self.names())
            self.choice.set(label)
            self.feedback.set(f'已保存「{label}」；当前仍使用「{self.catalog.label_for(self.ui.config_path)}」。')

    def switch(self):
        if not self._idle() or self.activate is None:
            return
        label = self.choice.get()
        if label == self.catalog.label_for(self.ui.config_path):
            self.feedback.set(self._current_note())
            return
        ui = self.ui
        if ui.dirty or ui.workflow_panel.dirty or ui.schedule_panel.dirty:
            self.feedback.set('请先保存当前设置及正在编辑的任务流或定时计划。')
            return
        state = ui.desktop_schedule.runtime.snapshot()
        if state['enabled_ids'] or not ui.desktop_schedule.runtime.wait_idle(0):
            self.feedback.set('请先停止或停用当前配置的定时计划。')
            return
        try:
            path, settings = self.catalog.read(label)
        except (OSError, ProfileError, RuntimeError):
            self.feedback.set('所选方案无法读取，请检查后重试。')
            return
        self.activate(path, settings)
