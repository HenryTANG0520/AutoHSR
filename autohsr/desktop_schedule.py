"""Use the existing process-bound scheduler from the desktop event loop."""
from __future__ import annotations

import time

from .schedule_dispatch import NativeScheduleExecutor, _execution_busy
from .schedule_plan import ScheduleError
from .schedule_runtime import Scheduler
from .schedule_store import ScheduleStore


class DesktopSchedule:
    def __init__(self, ui):
        self.ui = ui
        self.store = ScheduleStore(ui.config_path.parent / 'schedules.local')
        self.executor = NativeScheduleExecutor(ui.settings, busy_probe=self._busy)
        self.runtime = Scheduler(self.store, self.executor, emit=ui.emit)
        self.owned = False
        self.modal_open = False
        self.manual_confirmation = False
        self.previewed = None
        self.next_tick = 0.0

    def _busy(self):
        ui = self.ui
        return (ui.closing or self.modal_open or self.manual_confirmation or (ui.busy and not self.owned)
                or (ui.worker is not None and ui.worker.is_alive()) or _execution_busy())

    def preview(self, plan):
        self.previewed = None
        settings = self.ui._read_settings(operation='plan', quiet=True)
        budget, manifest = NativeScheduleExecutor(settings).preview_activation(plan)
        self.previewed = budget['id'], budget['revision'], manifest
        return budget

    def enable(self, plan_id, expected_revision):
        if self.ui.busy or self.ui.closing:
            raise ScheduleError('当前已有操作，请在结束后启用定时。')
        if self.previewed is None or self.previewed[:2] != (plan_id, expected_revision):
            raise ScheduleError('请先预览准备启用的已保存计划。')
        self.executor.settings = self.ui._read_settings(operation='plan', quiet=True)
        self.runtime.enable(plan_id, expected_revision=expected_revision, expected_manifest=self.previewed[2])
        return self.runtime.start()

    def disable(self, plan_id):
        return self.runtime.disable(plan_id)

    def stop(self):
        snapshot = self.runtime.stop()
        for plan_id in snapshot['enabled_ids']:
            self.runtime.disable(plan_id)
        return self.runtime.snapshot()

    def toggle_pause(self):
        snapshot = self.runtime.snapshot()
        return (self.runtime.resume() if snapshot['paused'] else self.runtime.pause())['paused']

    def tick(self):
        if self.ui.closing or time.monotonic() < self.next_tick:
            return
        self.next_tick = time.monotonic() + 0.5
        snapshot = self.runtime.snapshot()
        # Revising the last armed plan can leave its current run active.
        has_work = snapshot['active'] is not None or snapshot['pending'] is not None
        if has_work or (snapshot['running'] and snapshot['enabled_ids']):
            self.modal_open = bool(self.ui.root.tk.call('grab', 'current'))
            snapshot = self.runtime.tick()
        self.sync(snapshot)

    def sync(self, snapshot):
        ui = self.ui
        if snapshot['active'] is not None and not self.owned:
            self.owned = True
            ui.stop_requested.clear()
            ui.runner = None
            ui.summary.set('')
            ui.result_alert.set('')
            ui.status.set('● 应用内定时执行中')
            ui.current_task.set('')
            ui.started_at = time.monotonic()
            ui._set_busy(True, snapshot['active_game'])
            if ui.running:
                ui.root.iconify()
        elif self.owned and snapshot['active'] is not None and ui.running != snapshot['active_game']:
            ui._set_busy(True, snapshot['active_game'])
            if ui.running:
                ui.root.iconify()
            else:
                ui._restore()
        elif self.owned and snapshot['active'] is None and snapshot['pending'] is None:
            restore = ui.running
            self.owned = False
            ui._freeze_clock()
            ui.summary.set('')
            ui._set_busy(False)
            ui.status.set('● 本次定时执行已结束')
            if restore:
                ui._restore()
