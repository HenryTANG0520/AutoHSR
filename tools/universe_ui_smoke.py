"""Exercise entrance actions, view switching and hidden-field recovery offline."""
import hashlib
import json
from pathlib import Path
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module, FakeRunner, pump
from ui_layout_smoke import check_layout
from autohsr.desktop_modes import show_mode_view

OUT = ROOT / "runs/universe-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    def click(widget):
        widget.event_generate("<ButtonPress-1>", x=widget.winfo_width()//2, y=widget.winfo_height()//2)
        widget.event_generate("<ButtonRelease-1>", x=widget.winfo_width()//2, y=widget.winfo_height()//2)

    def one_primary(ui):
        return sum(w.winfo_ismapped() for w in [ui.footer_start_button, *(d["hero"].primary for d in ui.mode_decks.values())]) == 1

    sources = json.loads((ROOT/"assets/ui/universe/sources.json").read_text("utf-8"))["assets"]
    check("both_illustrations_match_provenance", len(sources) == 2 and all(
        hashlib.sha256((ROOT/"assets/ui/universe"/entry["file"]).read_bytes()).hexdigest() == entry["sha256"] for entry in sources))
    fake = types.ModuleType("autohsr.app")
    fake.Runner = FakeRunner
    errors = []
    with tempfile.TemporaryDirectory() as folder, patch.dict(__import__("sys").modules, {"autohsr.app": fake}), \
            patch.object(module, "ROOT", Path(folder)), \
            patch.object(module.messagebox, "showerror", side_effect=lambda *a, **k: errors.append(a)):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, traceback: (_ for _ in ()).throw(value.with_traceback(traceback))
            ui = Window(root, config)
            try:
                root.focus_force()
                root.update()
                initial = ui._form_signature()
                for page in ui.mode_decks:
                    ui._show_page(page)
                    root.update()
                    deck = ui.mode_decks[page]
                    check(f"{scale}_{page}_entrance_has_one_primary", one_primary(ui) and ui.start_button is deck["hero"].primary)
                    check(f"{scale}_{page}_no_idle_form_or_report", not deck["editor"].winfo_ismapped() and not deck["result"].winfo_ismapped())
                    click(deck["hero"].editor_button)
                    root.update()
                    check(f"{scale}_{page}_mouse_opens_editor", deck["shown"] == "editor" and one_primary(ui) and ui.start_button is ui.footer_start_button)
                    deck["back_editor"].focus_force()
                    deck["back_editor"].event_generate("<KeyPress-space>")
                    deck["back_editor"].event_generate("<KeyRelease-space>")
                    root.update()
                    check(f"{scale}_{page}_keyboard_returns_to_entrance", deck["shown"] == "hero" and one_primary(ui))
                    check(f"{scale}_{page}_empty_results_are_unavailable",deck['hero'].result_button.instate(('disabled',)))
                    report_attribute='du_result_report' if page=='differential_universe' else 'currency_result_report'
                    setattr(ui,report_attribute,dict(status='stopped'))
                    ui._refresh_controls()
                    click(deck["hero"].result_button)
                    root.update()
                    check(f"{scale}_{page}_results_open_without_running", deck["shown"] == "result" and not ui.busy)
                    deck["back_result"].invoke()
                    root.update()
                    setattr(ui,report_attribute,None)
                    ui._refresh_controls()
                check(f"{scale}_navigation_does_not_change_or_save_plan", initial == ui._form_signature() and config.read_bytes() == original)
                painted=[]
                draw_text=module.theme.Painter.text
                def record_text(painter,point,text,*args,**kwargs):
                    painted.append(str(text))
                    return draw_text(painter,point,text,*args,**kwargs)
                with patch.object(module.theme.Painter,'text',record_text):
                    ui.weekly_enabled.set(True);ui.weekly_mode.set('货币战争');ui.weekly_runs.set('7')
                    root.update();ui.mode_decks['currency_wars']['hero'].redraw();root.update()
                    text=''.join(painted).replace(' ','').replace('\n','')
                    check(f'{scale}_poster_renders_actual_currency_weekly_plan','周常计划' in text and '最多7局' in text and '尚未接入' not in text)
                    painted.clear();ui.weekly_enabled.set(False);root.update()
                    check(f'{scale}_poster_renders_disabled_weekly_plan','周常未加入' in ''.join(painted))
                    painted.clear();ui.weekly_enabled.set(True);ui.weekly_mode.set('差分宇宙');root.update()
                    check(f'{scale}_poster_identifies_other_weekly_mode','差分宇宙' in ''.join(painted))
                    painted.clear();ui._show_page('differential_universe');root.update()
                    check(f'{scale}_independent_runs_are_named_current','本次局数' in painted)
                ui.weekly_enabled.set(False);ui.weekly_mode.set('差分宇宙');ui.weekly_runs.set(str(ui.settings.weekly_runs))
                ui._show_page("differential_universe")
                ui.du_team.set("")
                before = len(FakeRunner.instances)
                ui.start_button.invoke()
                root.update()
                check(f"{scale}_missing_team_reveals_and_focuses_field", root.focus_get() == ui.du_team_entry
                      and ui.mode_decks["differential_universe"]["shown"] == "editor" and len(FakeRunner.instances) == before)
                ui.du_team.set("哈哈哈哈")
                ui.du_resume_active.set(True)
                ui.du_resume_mode.set("周期难度 5")
                ui.differential_universe_runs.set("2")
                show_mode_view(ui, "differential_universe", "hero")
                ui.start_button.invoke()
                root.update()
                check(f"{scale}_resume_count_error_is_inline", root.focus_get() == ui.du_runs_combo
                      and "当前 1 局" in ui.input_error.get() and not errors and len(FakeRunner.instances) == before)
                ui.du_resume_active.set(False)
                ui.differential_universe_runs.set("3")
                ui.du_team.set("编队"*16)
                ui.du_rewards.set(True)
                ui.du_daily.set(True)
                ui.du_save.set(True)
                show_mode_view(ui, "differential_universe", "hero")
                root.update()
                if scale == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"long-team-options.png")
                default_size = root.geometry()
                for size in (default_size, "%dx%d" % root.minsize()):
                    root.geometry(size)
                    for page in ui.mode_decks:
                        ui._show_page(page)
                        for view in ("hero", "editor", "result"):
                            show_mode_view(ui, page, view)
                            root.update()
                            check_layout(root)
                            check(f"{scale}_{size}_{page}_{view}_one_primary", one_primary(ui))
                root.geometry(default_size)
                ui.du_team.set("哈哈哈哈")
                ui.du_rewards.set(False)
                ui.du_daily.set(False)
                ui.du_save.set(False)
                for page in ui.mode_decks:
                    show_mode_view(ui, page, "hero")
                    ui._show_page(page)
                    root.update()
                    count = len(FakeRunner.instances)
                    click(ui.start_button)
                    pump(root, lambda: ui.runner is not None)
                    runner = ui.runner
                    expected = "differential_universe" if page == "differential_universe" else "currency_wars"
                    check(f"{scale}_{page}_single_click_starts_correct_operation", len(FakeRunner.instances) == count+1
                          and runner.kwargs["operation"] == expected and runner.kwargs.get("currency_standard") is not True)
                    # The real launch path minimizes the assistant for game focus.
                    # Restore this fake run before checking on-screen controls.
                    ui._restore()
                    root.update()
                    check(f"{scale}_{page}_running_controls_visible", ui.pause_button.winfo_ismapped() and ui.stop_button.winfo_ismapped()
                          and str(ui.start_button.cget("state")) == "disabled")
                    check(f'{scale}_{page}_running_link_names_progress',ui.mode_decks[page]['hero'].result_button.cget('text')=='查看进度' and not ui.mode_decks[page]['hero'].result_button.instate(('disabled',)))
                    click(ui.mode_decks[page]["hero"].editor_button)
                    root.update()
                    check(f"{scale}_{page}_busy_editor_remains_locked", ui.start_button is ui.footer_start_button
                          and str(ui.start_button.cget("state")) == "disabled" and all(str(w.cget("state")) == "disabled" for w in ui.setting_controls))
                    ui.pause_button.invoke()
                    pump(root, lambda: ui.paused)
                    ui._show_page("logs")
                    root.update()
                    check(f"{scale}_{page}_records_preserve_operation_and_stop", one_primary(ui) and ui.stop_button.winfo_ismapped()
                          and ("演算" if page == "differential_universe" else "只读") in ui.start_button.cget("text"))
                    ui.stop_button.invoke()
                    pump(root, lambda: not ui.busy)
                    check(f"{scale}_{page}_stop_finishes_fake_worker", runner.stopped and not ui.worker.is_alive())
                    check(f'{scale}_{page}_finished_link_names_result',ui.mode_decks[page]['hero'].result_button.cget('text')=='查看结果')
                for page in ui.mode_decks:
                    ui._show_page(page)
                    report_attribute='du_result_report' if page=='differential_universe' else 'currency_result_report'
                    setattr(ui,report_attribute,None)
                    ui.active_operation=page
                    ui._set_busy(True,True)
                    ui.events.put(dict(type='run_error',message='离线模拟：页面未核实'))
                    pump(root,lambda:not ui.busy)
                    root.update()
                    check(f'{scale}_{page}_failure_links_to_status',ui.mode_decks[page]['hero'].result_button.cget('text')=='查看状态' and '页面未核实' in (ui.du_observation.get() if page=='differential_universe' else ui.currency_observation.get()))
                    check(f'{scale}_{page}_failure_does_not_claim_running_or_report',getattr(ui,report_attribute) is None and (ui.du_status.get() if page=='differential_universe' else ui.currency_status.get()) in ('演算中断','只读识别失败'))
                    retained=dict(operation=page,status='partial',verified_count=2)
                    setattr(ui,report_attribute,retained)
                    status=ui.du_status if page=='differential_universe' else ui.currency_status
                    status.set('已核实部分结果')
                    ui._set_busy(True,True)
                    ui.events.put(dict(type='run_error',message='离线模拟：后续写盘失败'))
                    pump(root,lambda:not ui.busy);root.update()
                    check(f'{scale}_{page}_late_failure_preserves_known_report',getattr(ui,report_attribute)==retained and status.get()=='已核实部分结果' and ui.mode_decks[page]['hero'].result_button.cget('text')=='查看结果')
                    setattr(ui,report_attribute,None)
                    ui.active_operation='plan';ui.plan_phase='weekly';ui._active_weekly_mode=page
                    ui._set_busy(True,True)
                    ui.events.put(dict(type='run_error',message='离线模拟：周常反馈未核实'))
                    pump(root,lambda:not ui.busy);root.update()
                    ui._refresh_weekly_caption(force=True);root.update()
                    check(f'{scale}_{page}_weekly_failure_updates_frozen_mode',ui.weekly_status.get().startswith('周常中断') and status.get() in ('周常中断','演算中断') and '周常反馈未核实' in (ui.du_observation.get() if page=='differential_universe' else ui.currency_observation.get()))
                ui._show_page("differential_universe")
                show_mode_view(ui, "differential_universe", "hero")
                root.update()
                check(f"{scale}_stopped_run_is_not_full_completion", "3/3" not in ui.du_status.get())
                check(f"{scale}_config_bytes_unchanged", config.read_bytes() == original)
            finally:
                if ui.runner is not None and ui.busy:
                    ui.runner.stop()
                    if ui.worker:
                        ui.worker.join(2)
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    result = dict(game_started=False, config_unchanged=True, count=len(checks), checks=checks)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
