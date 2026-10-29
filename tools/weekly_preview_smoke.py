"""Keep the next-click preview current without scheduling or losing run evidence."""
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from autohsr import weekly_plan

OUT = ROOT/"runs/weekly-preview-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 10, 29, 10, 59, 59, tzinfo=weekly_plan.CHINA)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    checks, callbacks, starts = [], [], []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Preview checks cannot start a game backend")
    def report(week, status="complete", message="本周 1 局周期演算已完成；周积分奖励未核实。", *, saved=True):
        return dict(operation="plan", status="success" if status in ("complete", "already_complete", "not_due", "disabled") and saved else "partial",
            report_saved=saved, daily_verified=True, stamina_spent=120, stamina_limit=240, stamina_pending=0,
            battle_completed=12, battle_requested=12, results=[],
            weekly_plan=dict(week=week, status=status, message=message, score_rewards_verified=False))

    class Plan:
        def __init__(self, settings, emit, **kwargs):
            self.settings = replace(settings)
            self.slot = weekly_plan.weekly_slot(settings)
            self.emit = emit
            self.release = threading.Event()
            self.paused = False
            starts.append(self)
        def run(self):
            self.emit(dict(type="plan_phase", phase="weekly"))
            self.emit(dict(type="universe_progress", requested_runs=1, completed_runs=0, phase="weekly"))
            if not self.release.wait(10):
                raise AssertionError("Fake plan was not released")
            return report(self.slot.week)
        def toggle_pause(self):
            self.paused = not self.paused
            return self.paused
        def stop(self):
            self.release.set()

    fake_app = types.ModuleType("autohsr.app")
    fake_app.Runner = reject
    fake_plan = types.ModuleType("autohsr.plan_runner")
    fake_plan.PlanRunner = Plan
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.object(weekly_plan, "datetime", Clock), \
            patch.dict(sys.modules, {"autohsr.app": fake_app, "autohsr.plan_runner": fake_plan}):
        config = Path(folder)/"config.json"
        Settings(weekly_enabled=True, weekly_day=4, weekly_time="11:00").save(config)
        original = config.read_bytes()
        root = tk.Tk()
        root.report_callback_exception = lambda kind, value, trace: callbacks.append(str(value))
        ui = Window(root, config)
        def tick():
            deadline = time.monotonic()+.22
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
        def jump(value):
            nonlocal now
            now = datetime.fromisoformat(value).replace(tzinfo=weekly_plan.CHINA)
            tick()
        def finish(data):
            original_report = json.loads(json.dumps(data))
            ui.active_operation = "plan"
            ui._finish(data)
            tick()
            check("original_report_unchanged_"+str(len(checks)), data == original_report and json.loads(ui.report_text.get("1.0", "end-1c")) == original_report)
        try:
            tick()
            check("saved_plan_opens_with_upcoming_time", "周四 11:00 后" in ui.weekly_status.get() and ui.start_button.cget("text") == "开始计划")
            ImageGrab.grab(window=root.winfo_id()).save(OUT/"before-due.png")
            jump("2026-10-29T11:00:00")
            check("due_time_refreshes_without_edit_or_click", "到期，运行时核对" in ui.weekly_status.get())
            ImageGrab.grab(window=root.winfo_id()).save(OUT/"due.png")
            jump("2026-10-29T10:59:00")
            check("clock_rollback_restores_upcoming_time", "周四 11:00 后" in ui.weekly_status.get())
            ui.weekly_time.set("11:")
            jump("2026-10-29T11:01:00")
            check("unfinished_time_draft_survives_clock_refresh", ui.weekly_time.get() == "11:" and "待填写" in ui.weekly_status.get())
            ui.weekly_enabled.set(False)
            jump("2026-10-30T12:00:00")
            check("disabled_weekly_ignores_unfinished_time", ui.weekly_status.get() == "周常未加入")
            ui.weekly_time.set("02:00")
            ui.weekly_day.set("周一")
            ui.weekly_enabled.set(True)
            jump("2026-11-02T01:59:59")
            check("early_monday_still_upcoming", "周一 02:00 后" in ui.weekly_status.get())
            jump("2026-11-02T02:00:00")
            check("early_monday_becomes_due_in_ending_week", "到期" in ui.weekly_status.get())
            jump("2026-11-02T04:00:00")
            check("game_week_reset_restores_next_slot", "周一 02:00 后" in ui.weekly_status.get())
            check("clock_changes_never_start_a_plan", not starts and not ui.busy)

            ui.weekly_time.set("04:00")
            jump("2026-11-02T03:59:00")
            finish(report("2026-10-26"))
            check("current_week_result_is_preserved", "本周 1 局" in ui.weekly_status.get() and ui.training_meter.verified)
            jump("2026-11-02T03:59:59")
            check("current_week_result_survives_idle_ticks", "本周 1 局" in ui.weekly_status.get())
            jump("2026-11-02T04:00:00")
            check("new_week_replaces_old_completion_with_preview", "到期，运行时核对" in ui.weekly_status.get() and "已完成" not in ui.weekly_status.get())
            check("previous_result_keeps_its_frozen_week_and_daily_proof", ui.summary.get().startswith("上次计划 · ") and "2026-10-26 当周" in ui.summary.get() and ui.training_meter.verified and ui.confirmed_stamina == 120)
            ImageGrab.grab(window=root.winfo_id()).save(OUT/"new-week-after-result.png")
            finish(report("2026-11-02", "already_complete", "本周演算已完成，已跳过。"))
            jump("2026-11-03T04:00:00")
            check("same_week_deduplicated_result_is_preserved", "已跳过" in ui.weekly_status.get())
            ui.active_operation = "differential_universe"
            ui._finish(dict(operation="differential_universe", status="partial", report_saved=True,
                error="模拟独立演算停止", results=[], differential_universe=dict(requested_runs=3, completed_runs=1)))
            independent_summary = ui.summary.get()
            jump("2026-11-09T04:00:00")
            check("later_week_does_not_claim_previous_skip", "到期" in ui.weekly_status.get() and "已跳过" not in ui.weekly_status.get())
            check("weekly_refresh_does_not_relabel_a_newer_independent_result", ui.summary.get() == independent_summary)

            for status, saved, message in (
                ("needs_review", True, "周常记录待核对；未再开局。"),
                ("complete", False, "本周演算完成，但计划报告未保存。"),
                ("not_started", True, "计划已停止；未继续下一项。"),
            ):
                finish(report("2026-11-02", status, message, saved=saved))
                jump("2026-11-16T04:00:00")
                check("unresolved_result_survives_refresh_"+status, ui.weekly_status.get() == message)

            ui.weekly_day.set("周四")
            ui.weekly_time.set("11:00")
            jump("2026-11-19T10:59:00")
            finish(report("2026-11-16", "not_due", "周常未到计划时间。"))
            check("not_due_result_restores_time_preview", "周四 11:00 后" in ui.weekly_status.get())
            jump("2026-11-19T11:00:00")
            check("not_due_result_does_not_hide_later_eligibility", "到期" in ui.weekly_status.get())
            normal = root.geometry()
            root.state("zoomed")
            tick()
            jump("2026-11-19T10:59:00")
            root.state("normal")
            root.geometry(normal)
            tick()
            check("restored_layout_shows_current_schedule", "周四 11:00 后" in ui.weekly_status.get() and ui.weekly_button.winfo_ismapped())
            jump("2026-11-19T11:00:00")
            writes = []
            token = ui.weekly_status.trace_add("write", lambda *_: writes.append(True))
            for _ in range(4):
                now += timedelta(minutes=1)
                tick()
            ui.weekly_status.trace_remove("write", token)
            check("unchanged_caption_does_not_trigger_repaint", not writes)

            # The only start in this check comes from the existing main button.
            ui.weekly_day.set("周一")
            ui.weekly_time.set("04:00")
            jump("2026-11-23T03:59:00")
            ui._show_page("home")
            ui.start_button.invoke()
            tick()
            check("single_click_starts_one_frozen_plan", len(starts) == 1 and starts[0].slot.week == "2026-11-16" and starts[0].slot.due and ui.busy)
            progress = ui.weekly_status.get()
            jump("2026-11-23T04:00:00")
            check("active_progress_is_not_replaced_at_reset", ui.weekly_status.get() == progress and "0/1" in progress and ui.busy)
            ui.pause_button.invoke()
            jump("2026-11-23T04:01:00")
            check("paused_progress_and_controls_survive_refresh", ui.paused and ui.weekly_status.get() == progress and ui.stop_button.winfo_ismapped())
            ui.pause_button.invoke()
            starts[0].release.set()
            deadline = time.monotonic()+3
            while ui.busy and time.monotonic() < deadline:
                tick()
            check("finished_old_snapshot_shows_current_preview", not ui.busy and "到期" in ui.weekly_status.get() and "2026-11-16 当周" in ui.summary.get())
            check("no_extra_start_after_result_or_reset", len(starts) == 1 and not callbacks)
            check("preview_and_run_never_save_settings", config.read_bytes() == original)
        finally:
            for plan in starts:
                plan.release.set()
            if ui.worker:
                ui.worker.join(timeout=2)
            ui.closing = True
            root.destroy()
    result = dict(checks=checks, count=len(checks), game_started=False, real_backend_calls=0)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
