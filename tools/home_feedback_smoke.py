"""Check the visible plan, actual costs and a single idle outcome with no game access."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from autohsr import theme
from autohsr.desktop_modes import show_mode_view

OUT = ROOT/"runs/home-feedback-ui"


def drawn_text(surface):
    values = []
    original = theme.Painter.text
    def text(painter, position, value, *args, **kwargs):
        values.append(str(value))
        return original(painter, position, value, *args, **kwargs)
    with patch.object(theme.Painter, "text", text):
        surface._render()
    return "\n".join(values)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name)
    fake = types.ModuleType("autohsr.app")
    def reject(*args, **kwargs):
        raise AssertionError("Offline UI check cannot start a game Runner")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app":fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.5, 2.):
            prefix = str(scale)+"_"
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                root.update()
                check(prefix+"idle_has_no_fake_resource_balance", ui.stamina.get() == "—" and "开拓力" not in drawn_text(ui.header))
                check(prefix+"free_tasks_have_no_repeated_zero_cost", all(ui.table.resource_metrics(key) is None for key in ("assignments", "mail", "battlepass")))
                check(prefix+"idle_has_no_redundant_ready_feedback", not ui.activity_label.winfo_ismapped() and not ui.summary_label.winfo_ismapped())
                check(prefix+"plan_start_remains_one_click", ui.start_button.winfo_ismapped() and ui.start_button.cget("text") == "开始计划")
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"home.png")
                ui.dungeon_category.set("饰品提取")
                ui.challenge_count.set("2")
                root.update()
                check(prefix+"planar_cost_has_the_same_meaning_on_home_and_form", "最多 80 开拓力" in ui.daily_caption.get()
                      and "沉浸器优先" in ui.daily_caption.get() and "最多 80 开拓力" in ui.battle_cost.get()
                      and "已有沉浸器优先" in drawn_text(ui.table))
                ui.challenge_count.set("-2")
                root.update()
                check(prefix+"invalid_count_does_not_advertise_a_negative_fee", "次数待填写" in ui.daily_caption.get()
                      and "-80" not in drawn_text(ui.table))
                ui.challenge_count.set("2")
                report = dict(operation="daily", status="partial", report_saved=True, battle_completed=2, battle_requested=2,
                    stamina_spent=40, stamina_pending=0, immersifiers_spent=1, immersifiers_pending=0, daily_verified=True,
                    error="邮箱入口未识别", safe_next="核对当前画面后重试邮件任务。",
                    results=[dict(task="battle", status="ok", detail="两次挑战结算已核实")])
                ui._finish(report)
                root.update()
                text = drawn_text(ui.table)
                check(prefix+"actual_mixed_resources_replace_the_estimate", "已用 40 开拓力" in text and "沉浸器 1" in text and "最多 80" not in text)
                check(prefix+"idle_result_does_not_repeat_status_in_two_footer_rows", ui.summary_label.winfo_ismapped() and not ui.activity_label.winfo_ismapped())
                check(prefix+"cost_header_is_spend_not_balance", "已用开拓力  40" in drawn_text(ui.header))
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"partial-daily.png")
                    full_size = root.geometry()
                    root.geometry("%dx%d" % root.minsize())
                    root.update()
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"partial-daily-minimum.png")
                    root.geometry(full_size)
                    root.update()
                ui.summary_label.activate()
                root.update()
                details = next(w for frame in ui.summary_dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == "Text")
                check(prefix+"full_cost_and_recovery_are_still_one_click_away", "下一步" in details.get("1.0", "end") and "40" in details.get("1.0", "end"))
                ui.summary_dialog.destroy()
                ui._set_busy(True, running=True)
                ui.current_task.set("周常 · 差分宇宙 · 已完成 0/2 局")
                root.update()
                check(prefix+"live_phase_is_kept_beside_a_previous_stage_result", ui.activity_label.winfo_ismapped() and "0/2" in ui.activity.get())
                ui._set_busy(False)
                ui._show_page("currency_wars")
                show_mode_view(ui, "currency_wars", "result")
                currency = dict(operation="currency_wars_standard", status="partial", report_saved=False,
                    error="补给角色交付尚未核实", safe_next="核对原领取记录。",
                    currency_wars=dict(mode="standard_development", start_verified=True, reward=dict(status="unit_verifying")))
                ui._finish(currency)
                root.update()
                check(prefix+"missing_spend_does_not_erase_confirmed_spend", ui.stamina.get() == "40")
                check(prefix+"open_result_owns_its_outcome_without_footer_duplicates", not ui.summary_label.winfo_ismapped() and not ui.activity_label.winfo_ismapped()
                      and "报告未保存" in ui.currency_observation.get() and "下一步" in ui.currency_observation.get())
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"result.png")
                show_mode_view(ui, "currency_wars", "hero")
                root.update()
                check(prefix+"leaving_result_restores_the_alert", ui.summary_label.winfo_ismapped() and "报告未保存" in ui.summary_label.message())
                show_mode_view(ui, "currency_wars", "result")
                ui.input_error.set("演算局数请填写整数。")
                root.update()
                check(prefix+"input_error_cannot_be_hidden_by_an_open_result", ui.summary_label.winfo_ismapped() and "整数" in ui.summary_label.message())
                ui.input_error.set("")
                ui._finish(dict(operation="daily", status="failed", report_saved=True, error="新的日常错误", results=[]))
                root.update()
                check(prefix+"old_result_does_not_hide_another_operation_failure", ui.summary_label.winfo_ismapped() and "新的日常错误" in ui.summary_label.message())
                ui._task(dict(task="battle", status="skipped", detail="未执行副本"), log=False)
                check(prefix+"skipped_battle_does_not_show_a_cost", ui.table.resource_metrics("battle") is None)
                for size in (root.geometry(), "%dx%d" % root.minsize()):
                    root.geometry(size)
                    for page in ("home", "currency_wars", "settings"):
                        ui._show_page(page)
                        root.update()
                        check_layout(root)
                    check(prefix+size+"_layout", True)
                check(prefix+"config_is_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    data = dict(game_started=False, config_unchanged=True, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
