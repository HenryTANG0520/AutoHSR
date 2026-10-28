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
        for scale in (1., 1.5, 2.):
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
                    click(deck["hero"].result_button)
                    root.update()
                    check(f"{scale}_{page}_results_open_without_running", deck["shown"] == "result" and not ui.busy)
                    deck["back_result"].invoke()
                    root.update()
                check(f"{scale}_navigation_does_not_change_or_save_plan", initial == ui._form_signature() and config.read_bytes() == original)
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
