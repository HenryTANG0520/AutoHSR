"""Read actual result widgets and own-run details with game access rejected."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from autohsr.desktop_modes import show_mode_view

OUT = ROOT/"runs/currency-feedback-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name)
    fake = types.ModuleType("autohsr.app")
    def reject(*args, **kwargs):
        raise AssertionError("This result check cannot access the game")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(__import__("sys").modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                ui._show_page("currency_wars")
                show_mode_view(ui, "currency_wars", "result")
                root.update()
                check(f"{scale}_no_stale_raw_record_at_start", str(ui.currency_record_button.cget("state")) == "disabled")
                report = dict(operation="currency_wars_standard", status="partial", report_saved=True,
                    error="补给角色交付尚未核实", safe_next="核对当前角色与原领取记录，未重复确认。",
                    currency_wars=dict(mode="standard_development", start_verified=True, action_status="transition_verified",
                        screenshot="C:/evidence/original-frame.png", reward=dict(status="unit_verifying"),
                        actions=[dict(status="verified", reward_verified=False)], raw_marker="own-currency-report"))
                ui._finish(report)
                root.update()
                visible = ui.currency_result_text.get("1.0", "end")
                check(f"{scale}_ended_run_is_pending_not_still_running", ui.currency_status.get() == "补给角色待核实"
                      and not ui.busy and "尚未核实" in visible and "未重复确认" in visible)
                check(f"{scale}_transition_is_not_delivery_or_match_completion", "补给角色待核实" in ui.currency_status.get()
                      and "整局未完成" in visible and "奖励交付已核实" not in visible and "核验补给角色" not in visible)
                check(f"{scale}_raw_paths_and_codes_are_not_in_readable_result", all(s not in visible for s in
                      ("C:/evidence", "transition_verified", "own-currency-report", "unit_verifying")))
                check(f"{scale}_screenshot_still_has_its_file_entry", ui.last_screenshot == Path("C:/evidence/original-frame.png"))
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"pending-delivery.png")
                report["currency_wars"]["raw_marker"] = "mutated-outside-ui"
                ui._finish(dict(operation="daily", status="success", daily_verified=True, report_saved=True, results=[]))
                ui.currency_record_button.invoke()
                root.update()
                text = next(w for frame in ui.summary_dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == "Text")
                check(f"{scale}_raw_record_is_immutable_and_keeps_its_own_operation", "own-currency-report" in text.get("1.0", "end")
                      and "mutated-outside-ui" not in text.get("1.0", "end") and "unit_verifying" in text.get("1.0", "end"))
                ui.summary_dialog.destroy()
                ui._finish(dict(operation="currency_wars", status="failed", report_saved=False,
                    error="报告未写入磁盘", safe_next="检查运行目录后重试识别。"))
                root.update()
                check(f"{scale}_missing_observation_does_not_leave_old_result", ui.currency_status.get() == "运行失败"
                      and "报告未保存" in ui.currency_result_text.get("1.0", "end")
                      and "本次未生成有效观察记录" in ui.currency_observation.get() and "补给角色" not in ui.currency_observation.get())
                ui._finish(dict(operation="currency_wars", status="partial", report_saved=True,
                    currency_wars=dict(page_kind="preparation", page_verified=True, match=dict(node="2-1", gold=0, level=None))))
                root.update()
                check(f"{scale}_readonly_success_has_a_specific_outcome", ui.currency_status.get() == "只读识别结束"
                      and "金币 0" in ui.currency_observation.get() and "等级 未识别" in ui.currency_observation.get()
                      and "全部完成" not in ui.summary.get() and "整局完成" not in ui.summary.get())
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"readonly-result.png")
                default_size = root.geometry()
                for size in (default_size, "%dx%d" % root.minsize()):
                    root.geometry(size)
                    for view in ("hero", "result", "editor"):
                        show_mode_view(ui, "currency_wars", view)
                        root.update()
                        check_layout(root)
                        check(f"{scale}_{size}_{view}_primary_reachable", ui.start_button.winfo_ismapped())
                check(f"{scale}_config_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    result = dict(game_started=False, config_unchanged=True, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
