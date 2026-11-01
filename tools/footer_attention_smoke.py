"""Check contextual footer actions and durable save feedback without game access."""
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

OUT = ROOT/"runs/footer-attention-ui"


def close(root, ui):
    ui.closing = True
    for token in root.tk.splitlist(root.tk.call("after", "info")):
        root.after_cancel(token)
    root.destroy()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Footer checks cannot start a game backend")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app": fake}):
        for scale in (1., 1.5, 2.):
            config = Path(folder)/f"{scale}.json"
            Settings().save(config)
            original = config.read_bytes()
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            prefix = str(scale)+"_"
            try:
                root.update()
                check(prefix+"saved_plan_has_no_save_or_ready_prompt", not ui.save_button.winfo_ismapped()
                      and not ui.save_label.winfo_ismapped() and not ui.activity_label.winfo_ismapped())
                check(prefix+"daily_start_and_reward_are_reachable", ui.start_button.winfo_ismapped()
                      and ui.start_button.cget("text") == "开始计划" and ui.reward_button.winfo_ismapped())
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"home.png")
                ui.weekly_button.invoke()
                root.update()
                check(prefix+"weekly_has_its_start_without_reward_action", not ui.reward_button.winfo_ismapped()
                      and ui.start_button.winfo_ismapped() and ui.start_button.cget("text") == "开始计划")
                old_time = ui.weekly_time.get()
                ui.weekly_time.set("25:99")
                root.update()
                check(prefix+"draft_exposes_save_without_writing", ui.save_button.winfo_ismapped()
                      and not ui.save_label.winfo_ismapped() and config.read_bytes() == original)
                ui.save_button.invoke()
                root.update()
                check(prefix+"invalid_save_keeps_draft_and_points_to_field", ui.save_button.winfo_ismapped()
                      and ui.input_error.get() and root.focus_get() == ui.weekly_time_entry and config.read_bytes() == original)
                ui.weekly_time.set(old_time)
                root.update()
                check(prefix+"reverted_draft_removes_save", not ui.dirty and not ui.save_button.winfo_ismapped()
                      and not ui.input_error.get() and config.read_bytes() == original)
                ui.overlay_logs.set(not ui.overlay_logs.get())
                ui._show_page("home")
                root.update()
                check(prefix+"dirty_daily_groups_save_before_reward", ui.save_button.winfo_ismapped()
                      and ui.reward_button.winfo_ismapped() and ui.save_button.winfo_rootx() < ui.reward_button.winfo_rootx())
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"draft.png")
                ui._set_busy(True, running=True)
                root.update()
                check(prefix+"running_shows_controls_and_hides_idle_actions", ui.stop_button.winfo_ismapped()
                      and ui.activity_label.winfo_ismapped() and not ui.save_button.winfo_ismapped()
                      and not ui.reward_button.winfo_ismapped())
                ui._set_busy(False)
                root.update()
                check(prefix+"finished_restores_unsaved_actions", ui.save_button.winfo_ismapped()
                      and ui.reward_button.winfo_ismapped() and config.read_bytes() == original)
                with patch.object(Settings, "save", side_effect=OSError("模拟写入失败")), \
                        patch.object(module.messagebox, "showerror") as error:
                    ui.save_button.invoke()
                    root.update()
                    check(prefix+"write_failure_keeps_save_and_reason", ui.save_button.winfo_ismapped()
                          and ui.save_label.winfo_ismapped() and ui.save_status.get() == "保存失败 · 配置未改变"
                          and error.call_args.args[0] == "保存失败"
                          and "模拟写入失败" in error.call_args.args[1] and config.read_bytes() == original)
                ui.save_button.invoke()
                root.update()
                check(prefix+"explicit_save_acknowledges_actual_persistence", not ui.dirty and not ui.save_button.winfo_ismapped()
                      and ui.save_label.winfo_ismapped() and ui.save_status.get() == "已保存"
                      and Settings.load(config).overlay_logs == ui.overlay_logs.get())
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"saved.png")
                for page in ("tasks", "differential_universe", "currency_wars", "logs", "settings"):
                    ui._show_page(page)
                    root.update()
                    check(prefix+page+"_has_contextual_reward_and_clears_old_save_acknowledgement",
                          bool(ui.reward_button.winfo_ismapped()) == (page == "tasks") and not ui.save_label.winfo_ismapped())
                ui._show_page("home")
                ui.status.set("● 检测已停止")
                root.update()
                check(prefix+"meaningful_idle_status_is_retained", ui.activity_label.winfo_ismapped())
                ui.input_error.set("开拓力上限请填写整数。")
                root.update()
                check(prefix+"error_keeps_priority", ui.summary_label.winfo_ismapped()
                      and not ui.activity_label.winfo_ismapped() and "整数" in ui.summary_label.message())
                ui.input_error.set("")
                ui.status.set("● 准备就绪")
                saved = config.read_bytes()
                ui.overlay_logs.set(not ui.overlay_logs.get())
                for size in (root.geometry(), "%dx%d" % root.minsize()):
                    root.geometry(size)
                    for page in ("home", "settings", "currency_wars"):
                        ui._show_page(page)
                        root.update()
                        check_layout(root)
                    check(prefix+size+"_layout", True)
                check(prefix+"navigation_does_not_save_new_draft", ui.dirty and config.read_bytes() == saved)
            finally:
                close(root, ui)
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            fresh = Path(folder)/f"first-launch-{scale}.json"
            ui = Window(root, fresh)
            try:
                root.update()
                check(prefix+"first_launch_can_explicitly_save_defaults", not fresh.exists() and not ui.dirty
                      and ui.save_button.winfo_ismapped() and not ui.save_label.winfo_ismapped())
            finally:
                close(root, ui)
            damaged = Path(folder)/f"damaged-{scale}.json"
            damaged.write_text("invalid-json", "utf-8")
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            with patch.object(module.messagebox, "showwarning"):
                ui = Window(root, damaged)
                try:
                    root.update()
                    check(prefix+"unreadable_config_keeps_explicit_save", ui.save_button.winfo_ismapped()
                          and ui.save_status.get() == "默认设置" and damaged.read_text("utf-8") == "invalid-json")
                    ui.save_button.invoke()
                    root.update()
                    check(prefix+"explicit_default_save_repairs_configuration", not ui.save_button.winfo_ismapped()
                          and ui.save_label.winfo_ismapped() and ui.save_status.get() == "已保存"
                          and Settings.load(damaged) == ui.settings)
                finally:
                    close(root, ui)
    result = dict(game_started=False, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
