"""Check plan previews and unexecuted task results through real card activation."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module, pump

OUT = ROOT/"runs/task-card-state-ui"


def contained(widget):
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    right, bottom = x+widget.winfo_width(), y+widget.winfo_height()
    parent = widget.master
    while parent is not None:
        if not (x >= parent.winfo_rootx() and y >= parent.winfo_rooty() and
                right <= parent.winfo_rootx()+parent.winfo_width()+1 and
                bottom <= parent.winfo_rooty()+parent.winfo_height()+1):
            return False
        parent = parent.master
    return bool(widget.winfo_ismapped())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, starts, reports, errors = [], [], [], []
    outcome = "stopped"

    def check(name, value):
        assert value, name
        checks.append(name)

    class Plan:
        def __init__(self, settings, emit, **kwargs):
            self.settings, self.emit = replace(settings), emit
            self.release = threading.Event()
            starts.append(self)

        def run(self):
            if outcome in ("stopped", "exception"):
                self.emit(dict(type="task", task="assignments", status="running", detail="正在核对委托。"))
            assert self.release.wait(15), "Fake plan must be released"
            if outcome == "exception":
                raise RuntimeError("离线模拟：结果处理意外中断。")
            report = dict(operation="plan", status=outcome, report_saved=True, results=[],
                          error="离线模拟：窗口未能核实。" if outcome == "failed" else "",
                          stamina_pending=10 if outcome == "failed" else 0,
                          weekly_plan=dict(status=outcome, message="周常未执行。"))
            reports.append((report, json.dumps(report, ensure_ascii=False, sort_keys=True)))
            return report

        def stop(self):
            self.release.set()

    def reject(*args, **kwargs):
        raise AssertionError("Card checks cannot start a game backend")

    fake_app, fake_plan = types.ModuleType("autohsr.app"), types.ModuleType("autohsr.plan_runner")
    fake_app.Runner, fake_plan.PlanRunner = reject, Plan
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app":fake_app, "autohsr.plan_runner":fake_plan}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            for outcome in ("stopped", "failed", "exception"):
                prefix = f"{scale}_{outcome}_"
                root = tk.Tk()
                root.tk.call("tk", "scaling", scale*96/72)
                root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
                ui = Window(root, config)
                try:
                    root.update()
                    root.geometry("%dx%d" % root.minsize())
                    root.update()
                    check(prefix+"preview_is_not_an_execution_result", all(
                        ui.table.item(key,"values")[1] == ("待执行" if value.get() else "未加入")
                        and not ui.table.item(key,"has_result") for key, value in ui.tasks.items()))
                    check(prefix+"unselected_preview_has_no_cost", ui.table.resource_metrics("mail") is None)
                    ui._show_daily_tasks("battlepass")
                    root.update()
                    check(prefix+"all_target_choices_are_inside_the_viewport", all(contained(c) for c in ui.daily_task_controls.values()))
                    ui._leave_settings()
                    root.update()
                    if scale == 1.25 and outcome == "stopped":
                        ImageGrab.grab(window=root.winfo_id()).save(OUT/"preview.png")
                    before = len(starts)
                    selected = {key:value.get() for key,value in ui.tasks.items()}
                    ui.start_button.invoke()
                    pump(root, lambda: ui.runner is not None and (outcome == "failed" or
                        ui.table.item("assignments","values")[1] == "进行中"))
                    check(prefix+"one_click_starts_the_selected_plan", len(starts) == before+1
                          and all(getattr(starts[-1].settings,key) == value for key,value in selected.items())
                          and starts[-1].settings.challenge_count == 24 and starts[-1].settings.stamina_limit == 240)
                    ui._stop() if outcome == "stopped" else starts[-1].release.set()
                    pump(root, lambda: not ui.busy)
                    check(prefix+"unstarted_selected_tasks_own_a_terminal_result", all(
                        ui.table.item(key,"values")[1] == "未执行" and ui.table.item(key,"has_result")
                        and ui.table.action_label(key) == "查看结果" and ui.table.resource_metrics(key) is None
                        for key in ("battle", "daily")))
                    check(prefix+"interrupted_task_keeps_its_uncertainty_and_cause", outcome == "failed" or
                          ("未确认完成" in ui.table.item("assignments","values")[2]
                           and (outcome != "exception" or "结果处理意外中断" in ui.table.item("assignments","values")[2])))
                    summary, active_page = ui.summary.get(), ui.active_page
                    for key in ("battle", "daily"):
                        board = ui.table
                        board._reveal(list(board.names).index(key))
                        board.redraw()
                        root.update()
                        x1,y1,x2,y2 = board.hitboxes[key]
                        board.event_generate("<Button-1>", x=round((x1+x2)/2*ui.ui_scale), y=round((y1+y2)/2*ui.ui_scale))
                        root.update()
                        dialog = getattr(ui,"summary_dialog",None)
                        check(prefix+key+"_one_click_opens_this_result", dialog is not None and dialog.winfo_exists()
                              and dialog.title() == board.names[key] and ui.active_page == active_page)
                        text = next(w for frame in dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == "Text")
                        check(prefix+key+"_reason_and_overall_outcome_are_preserved", "未执行" in text.get("1.0","end")
                              and (outcome != "stopped" or "计划已停止" in text.get("1.0","end"))
                              and (outcome != "failed" or all(value in text.get("1.0","end") for value in ("窗口未能核实", "10 开拓力待核对")))
                              and (outcome != "exception" or "结果处理意外中断" in text.get("1.0","end"))
                              and text.get("1.0","end").count("未执行") == 1
                              and ui.summary.get() == summary and len(starts) == before+1)
                        if scale == 1.25 and key == "battle":
                            ImageGrab.grab(window=dialog.winfo_id()).save(OUT/(outcome+"-detail.png"))
                        dialog.destroy()
                    ui._task(dict(task="mail",status="skipped",detail="前一步页面未核实，未继续发送输入。"), log=False)
                    check(prefix+"actual_skip_remains_an_execution_result", ui.table.item("mail","values")[1] == "跳过"
                          and ui.table.action_label("mail") == "查看结果")
                    ui.overlay_logs.set(not ui.overlay_logs.get())
                    check(prefix+"display_changes_keep_the_task_result", ui.table.action_label("battle") == "查看结果")
                    ui.challenge_count.set("1")
                    root.update()
                    check(prefix+"new_plan_restores_its_setup_action", ui.table.action_label("battle") == "副本设置"
                          and ui.table.item("battle","values")[1] == "待执行" and not ui.table.item("battle","has_result")
                          and ui.summary.get() == summary)
                    check(prefix+"config_and_raw_reports_are_unchanged", config.read_bytes() == original
                          and all(json.dumps(report,ensure_ascii=False,sort_keys=True) == snapshot for report,snapshot in reports))
                finally:
                    if ui.busy:
                        ui._stop()
                        pump(root, lambda: not ui.busy)
                    ui.closing = True
                    for token in root.tk.splitlist(root.tk.call("after","info")):
                        root.after_cancel(token)
                    root.destroy()
    check("no_callback_errors", not errors)
    result = dict(count=len(checks),checks=checks,game_started=False,config_unchanged=True,starts=len(starts))
    (OUT/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
