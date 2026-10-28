"""Invalid forms and partial results must expose the correction in one place."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout

OUT = ROOT/"runs/input-feedback-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    with tempfile.TemporaryDirectory() as folder:
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        with patch.object(module, "ROOT", Path(folder)), patch.object(module.messagebox, "showerror") as modal:
            root = tk.Tk()
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                ui.summary.set("上次结果保留")
                cases = (("game_path", "wrong.exe", "game", "game_path_entry", "StarRail.exe"),
                    ("stamina_limit", "abc", None, "stamina_limit_entry", "整数"),
                    ("stamina_limit", "25", None, "stamina_limit_entry", "10 的倍数"),
                    ("challenge_count", "0", None, "challenge_entry", "挑战次数"),
                    ("challenge_count", "abc", None, "challenge_entry", "整数"),
                    ("target_location", "", None, "dungeon_location_combo", "地点"),
                    ("action_delay", "nan", "recognition", "action_delay_entry", "有限"),
                    ("battle_timeout", "50", "recognition", "battle_timeout_entry", "60～3600"),
                    ("ocr_confidence", "2", "recognition", "ocr_confidence_entry", "0.4～0.99"),
                    ("weekly_time", "24:00", "weekly", "weekly_time_entry", "HH:MM"))
                for field, value, section, control, fragment in cases:
                    if field == "weekly_time":
                        ui.weekly_enabled.set(True)
                    variable = getattr(ui, field)
                    before = variable.get()
                    ui._show_page("home")
                    variable.set(value)
                    check(field+"_rejected_"+value, ui._read_settings(operation="plan") is None)
                    root.update()
                    expected_page = "settings" if section else "tasks"
                    check(field+"_focus_"+value, ui.active_page == expected_page and root.focus_get() == getattr(ui, control)
                          and (not section or ui.settings_tabs.select() == str(ui.settings_sections[section]))
                          and ui.action_page == "home" and ui.start_button.cget("text") == "开始计划")
                    check(field+"_reason_"+value, fragment in ui.summary_label.message() and
                          ui.summary.get() == "上次结果保留" and config.read_bytes() == original and not ui.busy)
                    check_layout(root)
                    if field == "weekly_time":
                        ImageGrab.grab(window=root.winfo_id()).save(OUT/"weekly-time-error.png")
                    variable.set(before)
                    check(field+"_edit_clears_"+value, not ui.input_error.get())
                ui.weekly_enabled.set(True)
                ui.du_team.set("")
                ui._show_page("home")
                check("weekly_missing_team_rejected", ui._read_settings(operation="plan") is None)
                root.update()
                check("weekly_team_is_correctable_without_leaving_plan", root.focus_get() == ui.weekly_team_entry and
                      ui.settings_tabs.select() == str(ui.settings_sections["weekly"]) and ui.action_page == "home")
                ui.weekly_team_entry.insert(0, "哈哈哈哈")
                check("corrected_plan_ready_without_saving", ui._read_settings(operation="plan") is not None and
                      not ui.input_error.get() and config.read_bytes() == original)
                ui._show_page("differential_universe")
                ui.du_team.set("")
                check("independent_missing_team_rejected", ui._read_settings(operation="differential_universe") is None)
                root.update()
                check("independent_team_keeps_independent_action", root.focus_get() == ui.du_team_entry and
                      ui.action_page == "differential_universe" and "演算" in ui.start_button.cget("text"))
                ui.du_team.set("哈哈哈哈")
                ui.weekly_enabled.set(False)
                ui.weekly_time.set("unfinished")
                check("disabled_weekly_draft_does_not_block_daily_plan", ui._read_settings(operation="plan") is not None and
                      ui.weekly_status.get() == "周常未加入")
                check("saving_still_validates_disabled_weekly_fields", ui._read_settings(save=True, operation="save") is None and
                      ui.input_error_field == "weekly_time")
                ui.weekly_time.set("04:00")
                ui.weekly_enabled.set(True)
                ui.weekly_mode.set("货币战争")
                ui.du_team.set("")
                ui._show_page("home")
                check("save_reports_invalid_shared_team", ui._read_settings(save=True, operation="save") is None)
                root.update()
                check("hidden_weekly_team_error_opens_visible_independent_control", ui.active_page == "differential_universe" and
                      root.focus_get() == ui.du_team_entry and ui.action_page == "home")
                ui.du_team.set("哈哈哈哈")
                ui._show_page("home")
                ui.tasks["mail"].set(True)
                ui._finish(dict(operation="plan", status="partial", report_saved=True, daily_verified=True,
                    stamina_spent=120, stamina_limit=240, stamina_pending=0, error="未识别邮箱入口",
                    battle_completed=12, battle_requested=12, failure_task="mail",
                    safe_next="先核对本次截图，再处理当前页面。", results=[
                        dict(task="assignments", status="ok", detail="模拟完成委托"),
                        dict(task="battle", status="ok", detail="模拟完成 12 次"),
                        dict(task="mail", status="partial", detail="未识别邮箱入口")]))
                root.update()
                check("failure_reason_visible_without_opening_details", ui.summary_label.message() == "未识别邮箱入口" and ui.training_meter.verified)
                check_layout(root)
                ImageGrab.grab(window=root.winfo_id()).save(OUT/"failure-reason.png")
                ui.summary_label.activate()
                root.update()
                check("full_costs_and_next_step_still_available", ui.summary_dialog.winfo_exists() and
                      "120" in ui.summary.get() and "下一步" in ui.summary.get())
                ui.summary_dialog.destroy()
                exchange = dict(mode="standard_development", start_verified=True, action_status="transition_verified",
                                exchange=dict(status="verifying"), actions=[dict(status="verified", movement_verified=False)])
                ui._currency_observed(exchange)
                check("staged_exchange_shows_identity_check", "核验换人角色" in ui.currency_observation.get()
                      and "换人已核实" not in ui.currency_observation.get())
                exchange.update(action_status="exchange_verified", exchange=dict(status="verified"),
                                actions=[dict(status="verified", movement_verified=True)])
                ui._currency_observed(exchange)
                check("verified_exchange_is_distinct_from_match_completion", "换人已核实" in ui.currency_observation.get()
                      and "整局未完成" in ui.currency_observation.get())
                completed = dict(exchange, status="settled", action_status="settled", completion_verified=True, settlement_verified=True)
                ui._finish(dict(operation="currency_wars_standard", status="success", report_saved=True, currency_wars=completed))
                check("verified_development_result_is_retained_without_independent_acceptance", "开发局结算已核实" in ui.status.get()
                      and "未计独立验收" in ui.summary.get() and "玩法未完成" not in ui.summary.get() and ui.training_meter.verified)
                check("no_extra_error_modal_or_config_write", not modal.called and config.read_bytes() == original)
            finally:
                ui.closing = True
                root.destroy()
    result = dict(game_started=False, config_unchanged=True, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
