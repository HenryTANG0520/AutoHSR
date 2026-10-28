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
                    return super().run()
                guard = self.kwargs["weekly_plan"]
                guard.receipt = WeeklyReceipt(run_root, "c"*24, guard.slot)
                guard.already_complete = not guard.receipt.begin(guard.settings)
                self.release.wait(5)
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
                ui.weekly_button.invoke()
                root.update()
                check("weekly_editor_one_click", ui.settings_tabs.select() == str(ui.settings_sections["weekly"]))
                ui.weekly_enabled.set(True)
                ui.weekly_runs.set("2")
                ui.weekly_time.set("24:00")
                ui.start_button.invoke()
                check("invalid_time_blocks_start_without_saving", bool(errors) and not FakeRunner.instances and config.read_bytes() == original)
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
                first.release.set()
                pump(root, lambda: len(FakeRunner.instances) == 2)
                second = FakeRunner.instances[1]
                check("daily_automatically_advances_to_frozen_weekly", second.kwargs["operation"] == "differential_universe" and
                      second.kwargs["du_runs"] == 2 and not second.settings.differential_universe_daily)
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
