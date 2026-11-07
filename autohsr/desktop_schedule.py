"""Use the existing process-bound scheduler from the desktop event loop."""
from __future__ import annotations

import time

from .config import CONFIG_PATH, Settings
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
        self.login_results = {}

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

    def can_restore_on_logon(self):
        return self.ui.config_path.resolve() == CONFIG_PATH.resolve()

    def preview_logon(self, plan_id, expected_revision):
        if not self.can_restore_on_logon():
            raise ScheduleError('Windows 登录自启使用默认配置。')
        if self.ui.dirty or self.ui._config_load_failed:
            raise ScheduleError('请先保存默认配置后再确认登录启用。')
        plan, revision = self.store.load(plan_id)
        if revision != expected_revision:
            raise ScheduleError('计划版本已变化，请重新打开计划。')
        settings = Settings.load(self.ui.config_path, require_existing=True)
        budget, manifest = NativeScheduleExecutor(settings).preview_activation(plan)
        if budget['contains_game_tasks'] and not settings.profile_account_key:
            raise ScheduleError('登录启用游戏计划前，请为默认配置绑定账号。')
        return budget, manifest

    def restore_on_logon(self):
        if not self.can_restore_on_logon() or self.ui._config_load_failed:
            return
        try:
            entries = self.store.login_authorizations()
        except (OSError, ScheduleError):
            self.ui._log('登录启用记录无法读取，未启用计划。', 'warning')
            return
        restored = 0
        for plan_id, entry in entries.items():
            try:
                budget, manifest = self.preview_logon(plan_id, entry['revision'])
                if manifest != entry['manifest']:
                    raise ScheduleError('计划设置或来源已变化，请重新确认登录启用。')
                self.runtime.enable(plan_id, expected_revision=budget['revision'], expected_manifest=manifest)
            except (OSError, ValueError, TypeError) as error:
                self.login_results[plan_id] = '登录时未启用，请重新核对授权和设置。'
                detail = str(error) if isinstance(error, ScheduleError) else '已保存配置无法重新核实。'
                self.ui._log(f'计划「{plan_id}」登录时未启用。{detail}', 'warning')
            else:
                restored += 1
        if restored:
            self.runtime.start()
            self.ui._log(f'已恢复 {restored} 条登录计划，等待后续计划点。')

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
