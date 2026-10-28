"""Exercise the plan button and weekly editor against fake game Runners only."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from ux_smoke import FakeRunner, Settings, Window, module, pump, ROOT
from ui_layout_smoke import check_layout
from autohsr.weekly_plan import WeeklyReceipt
from autohsr.tests.test_weekly_plan import du_report
from PIL import ImageGrab

OUT = ROOT/"runs"/"plan-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name)
    with tempfile.TemporaryDirectory() as folder:
        run_root = Path(folder)/"runs"
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        class WeeklyFake(FakeRunner):
            def run(self):
                if self.kwargs.get("weekly_plan") is None:
                    report = super().run()
                    if self.kwargs.get("operation") == "daily":
                        report.update(stamina_spent=120, battle_completed=12, battle_requested=12,
                                      results=[dict(task="assignments", status="ok", detail="模拟完成委托"),
                                               dict(task="battle", status="ok", detail="模拟完成 12 次，120 开拓力")])
                    return report
                guard = self.kwargs["weekly_plan"]
                guard.receipt = WeeklyReceipt(run_root, "c"*24, guard.slot)
                guard.already_complete = not guard.receipt.begin(guard.settings)
                self.emit(dict(type="progress", stamina_spent=0))
                self.emit(dict(type="log", message="模拟周常：累计确认消耗 0 开拓力"))
                self.emit(dict(type="universe_progress", requested_runs=self.kwargs["du_runs"], completed_runs=0))
                self.release.wait(20)
                if guard.already_complete:
                    report = dict(status="success", operation="differential_universe", results=[])
                elif self.stopped:
                    report = dict(status="stopped", operation="differential_universe", results=[])
                else:
                    report = du_report(run_root, self.kwargs["du_runs"])
                self.emit(dict(type="finished", report=report))
                return report
        errors = []
        FakeRunner.instances.clear()
        with patch("autohsr.app.Runner", WeeklyFake), patch.object(module, "ROOT", Path(folder)), \
                patch.object(module.messagebox, "showerror", side_effect=lambda *a, **k: errors.append(a)):
            root = tk.Tk()
            ui = Window(root, config)
            try:
                root.update()
                ui.du_team.set("")
                ui.differential_universe_runs.set("")
                daily_settings = ui._read_settings(operation="plan")
                check("daily_start_ignores_unrelated_unfinished_du_fields", daily_settings is not None and not errors)
                ui.du_team.set("哈哈哈哈")
                ui.differential_universe_runs.set("3")
                ui.weekly_button.invoke()
                root.update()
                check("weekly_editor_one_click", ui.settings_tabs.select() == str(ui.settings_sections["weekly"]))
                ui.weekly_enabled.set(True)
                ui.weekly_runs.set("2")
                ui.weekly_time.set("24:00")
                ui.start_button.invoke()
                check("invalid_time_blocks_start_without_saving", ui.input_error_field == "weekly_time" and
                      "HH:MM" in ui.input_error.get() and not errors and not FakeRunner.instances and config.read_bytes() == original)
                ui.weekly_time.set("04:00")
                root.update()
                check_layout(root)
                ImageGrab.grab(window=root.winfo_id()).save(OUT/"weekly-settings.png")
                ui._show_page("home")
                root.update()
                ImageGrab.grab(window=root.winfo_id()).save(OUT/"home-plan.png")
                check("preview_names_task_count_cost_and_weekly", "240 开拓力" in ui.daily_caption.get() and "差分宇宙 · 2 局" in ui.weekly_status.get())
                ui.start_button.invoke()
                pump(root, lambda: len(FakeRunner.instances) == 1 and ui.runner is not None)
                ui.start_button.invoke()
                check("single_start_and_busy_weekly_controls", len(FakeRunner.instances) == 1 and
                      str(ui.weekly_mode_combo.cget("state")) == "disabled" and
                      ui.pause_button.winfo_manager() == "pack" and ui.stop_button.winfo_manager() == "pack")
                first = FakeRunner.instances[0]
                check("running_task_is_visible_and_card_opens_progress", "副本" in ui.activity.get() and
                      ui.table.action_label("battle") == "查看进度")
                first.release.set()
                pump(root, lambda: len(FakeRunner.instances) == 2 and ui.training_meter.verified and "0/2" in ui.activity.get())
                second = FakeRunner.instances[1]
                check("daily_automatically_advances_to_frozen_weekly", second.kwargs["operation"] == "differential_universe" and
                      second.kwargs["du_runs"] == 2 and not second.settings.differential_universe_daily)
                check("daily_proof_and_cost_visible_while_weekly_running", ui.busy and
                      ui.table.item("daily", "values")[1] == "完成" and ui.confirmed_stamina == 120 and
                      str(ui.save_button.cget("state")) == "disabled")
                check("completed_card_uses_actual_run_counts_and_cost", ui.table.item("battle", "metrics") == ("12/12 次", "已用 120 开拓力"))
                second.emit(dict(type="universe_progress", requested_runs=2, completed_runs=1))
                pump(root, lambda: "1/2" in ui.activity.get())
                ui._restore()
                root.update()
                check_layout(root)
                ImageGrab.grab(window=root.winfo_id()).save(OUT/"weekly-running.png")
                ui._pause()
                root.update()
                check("pause_keeps_stage_and_verified_count", "已暂停" in ui.activity.get() and "1/2" in ui.activity.get())
                ui._pause()
                root.update()
                check("resume_keeps_stage_and_verified_count", "正在运行" in ui.activity.get() and "1/2" in ui.activity.get())
                second.release.set()
                pump(root, lambda: not ui.busy)
                check("combined_result_keeps_daily_and_distinguishes_score_rewards", ui.training_meter.verified and
                      "周积分奖励未核实" in ui.weekly_status.get() and "全部完成" in ui.status.get())
                check("run_never_saves_form", config.read_bytes() == original)
                check("idle_controls_return", not ui.pause_button.winfo_ismapped() and str(ui.weekly_mode_combo.cget("state")) == "readonly")
                # A later full-plan click still checks the account, then skips the completed week.
                ui.start_button.invoke()
                pump(root, lambda: len(FakeRunner.instances) == 3)
                FakeRunner.instances[-1].release.set()
                pump(root, lambda: len(FakeRunner.instances) == 4)
                FakeRunner.instances[-1].release.set()
                pump(root, lambda: not ui.busy)
                check("same_week_skips_completed_runs", "已跳过" in ui.weekly_status.get())
                ui._show_weekly_plan()
                ui.weekly_mode.set("货币战争")
                check("currency_boundary_visible_before_start", "尚未接入" in ui.weekly_boundary.get())
                ui.start_button.invoke()
                pump(root, lambda: len(FakeRunner.instances) == 5)
                FakeRunner.instances[-1].release.set()
                pump(root, lambda: not ui.busy)
                check("unsupported_weekly_keeps_daily_without_development_run", len(FakeRunner.instances) == 5 and
                      ui.training_meter.verified and "部分完成" in ui.status.get())
                ui.weekly_mode.set("差分宇宙")
                ui._save_settings()
                saved = Settings.load(config)
                check("only_explicit_save_persists_weekly", saved.weekly_enabled and saved.weekly_runs == 2 and saved.weekly_time == "04:00")
                previous = {key: ui.table.item(key) for key in ui.tasks}
                ui._show_page("differential_universe")
                ui.start_button.invoke()
                pump(root, lambda: len(FakeRunner.instances) == 6 and ui.runner is not None)
                check("independent_run_preserves_daily_cards_at_start", previous == {key: ui.table.item(key) for key in ui.tasks})
                FakeRunner.instances[-1].release.set()
                pump(root, lambda: not ui.busy)
                check("independent_run_preserves_daily_cards_at_finish", previous == {key: ui.table.item(key) for key in ui.tasks})
                summary = ui.summary.get()
                ui._show_page("home")
                ui.table.selected = "battle"
                ui.table.activate()
                root.update()
                check("task_details_do_not_replace_overall_outcome", ui.summary_dialog.winfo_exists() and ui.summary.get() == summary)
                ui.summary_dialog.destroy()
                ui.overlay_logs.set(not ui.overlay_logs.get())
                check("display_preferences_keep_daily_results", ui.table.action_label("battle") == "查看结果")
                ui.challenge_count.set("1")
                check("changed_daily_plan_returns_to_settings_actions", ui.table.action_label("battle") == "副本设置" and
                      ui.table.item("battle", "values")[1] == "等待" and ui.table.item("battle", "metrics") is None and
                      ui.training_meter.verified and ui.summary.get() == summary)
                ui.table.activate()
                root.update()
                check("task_setup_opens_specific_control", ui.active_page == "tasks" and root.focus_get() == ui.dungeon_list)
            finally:
                if ui.busy:
                    ui._stop()
                    pump(root, lambda: not ui.busy)
                ui.closing = True
                root.destroy()
    result = dict(mock_backend=True, game_started=False, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
