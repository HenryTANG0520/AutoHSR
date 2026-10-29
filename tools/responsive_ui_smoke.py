"""Offline resize acceptance: geometry, drafts, navigation and active controls."""
from __future__ import annotations

import json
import gc
import sys
import tempfile
import time
import traceback
import tkinter as tk
import types
from unittest.mock import patch
from pathlib import Path

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from autohsr.desktop_modes import show_mode_view

OUT = ROOT/"runs/responsive-ui"


def tooltip_checks():
    """Keyboard focus hints must not postpone fitting a maximized window."""
    checks = []
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)):
        config = Path(folder)/"config.json"
        Settings().save(config)
        for dpi in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", dpi*96/72)
            ui = Window(root, config)
            try:
                root.update()
                root.focus_force()
                ui.nav_buttons["tasks"].focus_set()
                root.update()
                assert any(isinstance(w, tk.Toplevel) and w.winfo_ismapped()
                           for w in ui.nav_buttons["tasks"].winfo_children())
                root.state("zoomed")
                root.update()
                ui.responsive_layout.fit()
                root.update()
                assert abs(ui.ui_scale-min(root.winfo_width()/1536, root.winfo_height()/864)) <= .01
                assert root.focus_get() is ui.nav_buttons["tasks"]
                checks.append(str(dpi)+"_keyboard_hint_allows_resize")
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    return checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        if name not in checks:
            checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Resize checks must not start a game backend")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for dpi in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", dpi*96/72)
            errors = []
            def callback_error(kind, value, tb):
                errors.append(str(value))
                traceback.print_exception(kind, value, tb)
            root.report_callback_exception = callback_error
            ui = Window(root, config)
            prefix = str(dpi)+"_"
            def settle():
                root.update()
                ui.responsive_layout.fit()
                root.update()
                check(prefix+"callbacks", not errors)
            try:
                settle()
                normal = root.geometry()
                normal_size = root.winfo_width(), root.winfo_height()
                base = ui.ui_scale
                book = (ui.guide.winfo_width()/base, ui.guide.winfo_height()/base)
                text_width = int(root.tk.call("font", "measure", ui.style.lookup("Accent.TButton", "font"), "开始计划"))/base
                for page in ui.pages:
                    ui._show_page(page)
                    root.update()
                ui._show_page("home")
                root.update()
                normal_shell = ui.shell
                # Warm both retained layouts before measuring their resource bound.
                root.state("zoomed")
                settle()
                for page in ui.pages:
                    ui._show_page(page)
                    root.update()
                ui._show_page("home")
                root.state("normal")
                root.geometry(normal)
                settle()
                check(prefix+"return_reuses_previous_controls", ui.shell is normal_shell)
                gc.collect()
                image_count = len(root.tk.call("image", "names"))
                bindings = sum(bool(line.strip()) for line in root.bind("<Configure>").splitlines())
                ui.weekly_enabled.set(True)
                ui.weekly_time.set("05:30")
                ui._show_weekly_plan()
                root.focus_force()
                ui.weekly_time_entry.focus_set()
                ui.weekly_time_entry.icursor(3)
                ui.weekly_time_entry.selection_range(0, 2)
                root.update()
                ui._log("保留滚动与错误颜色", "error")
                signature, events = ui._form_signature(), ui.events
                log = ui.log.get("1.0", "end-1c")
                root.state("zoomed")
                settle()
                check(prefix+"maximized_uses_available_space", abs(ui.ui_scale-min(root.winfo_width()/1536, root.winfo_height()/864)) <= .01)
                maximum = ui.ui_scale
                large_size = root.winfo_width(), root.winfo_height()
                check(prefix+"draft_kept", ui._form_signature() == signature and ui.dirty)
                check(prefix+"weekly_page_kept", ui.active_page == "settings" and ui.settings_shell.section == "weekly")
                check(prefix+"editing_position_kept", root.focus_get() is ui.weekly_time_entry and ui.weekly_time_entry.index("insert") == 3 and ui.weekly_time_entry.index("sel.last") == 2)
                check(prefix+"log_and_queue_kept", ui.events is events and ui.log.get("1.0", "end-1c") == log and bool(ui.log.tag_ranges("error")))
                ui.settings_shell.back.invoke()
                settle()
                check(prefix+"settings_return_focus_kept", ui.active_page == "home" and root.focus_get() is ui.weekly_button)
                check(prefix+"book_scales_uniformly", all(abs(a-b) < 3 for a,b in zip(book, (ui.guide.winfo_width()/ui.ui_scale, ui.guide.winfo_height()/ui.ui_scale))))
                width = int(root.tk.call("font", "measure", ui.style.lookup("Accent.TButton", "font"), "开始计划"))/ui.ui_scale
                check(prefix+"button_text_scales_with_art", abs(width-text_width) < 2)
                check_layout(root)
                if dpi == 1.5:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"maximized-home.png")
                for page in ui.pages:
                    ui._show_page(page)
                    root.update()
                    check_layout(root)
                    check(prefix+page+"_reachable", ui.start_button.winfo_ismapped())
                ui._show_page("tasks")
                ui.dungeon_search.set("雪原")
                root.update()
                browser_selection = ui.dungeon_list.selection
                root.state("normal")
                root.geometry(normal)
                settle()
                check(prefix+"browser_kept", ui.dungeon_search.get() == "雪原" and ui.dungeon_list.selection == browser_selection)
                check(prefix+"restore_scale", abs(ui.ui_scale-base) < .001)
                ui._show_page("differential_universe")
                show_mode_view(ui, "differential_universe", "result")
                ui.du_observation.set("已核实结果保留")
                root.state("zoomed")
                settle()
                check(prefix+"mode_result_kept", ui.mode_decks["differential_universe"]["shown"] == "result" and ui.du_result_text.get("1.0", "end-1c") == "已核实结果保留")
                ui._show_page("home")
                class Runner:
                    def toggle_pause(self):
                        return True
                    def stop(self):
                        self.stopped = True
                runner = Runner()
                ui.runner = runner
                ui._has_run = True
                ui._set_busy(True, running=True)
                ui.started_at = time.monotonic()-20
                ui._progress(40)
                ui.table.item("battle", values=("日常副本挑战", "进行中", "已完成1次"), has_result=True)
                root.state("normal")
                root.geometry(normal)
                settle()
                check(prefix+"running_state_kept", ui.runner is runner and ui.busy and ui.running and ui.confirmed_stamina == 40 and ui.table.item("battle", "values")[1] == "进行中")
                check(prefix+"running_controls_locked", ui.weekly_time_entry.instate(("disabled",)) and ui.start_button.instate(("disabled",)))
                ui.pause_button.invoke()
                root.update()
                check(prefix+"pause_still_operates", ui.paused and ui.pause_button.cget("text") == "继续 F9")
                ui.stop_button.invoke()
                check(prefix+"stop_still_operates", runner.stopped and ui.stopping and ui.stop_requested.is_set())
                ui.runner = None
                ui._set_busy(False)
                ui._show_weekly_plan()
                root.update()
                dialog = tk.Toplevel(root)
                dialog.grab_set()
                root.update()
                old_shell = ui.settings_shell
                root.state("zoomed")
                root.update()
                check(prefix+"dialog_keeps_ownership", not ui.responsive_layout.fit() and ui.settings_shell is old_shell and root.grab_current() is dialog)
                dialog.destroy()
                settle()
                check(prefix+"resize_after_dialog", ui.settings_shell is not old_shell)
                combo = ui.weekly_mode_combo
                combo.tk.call("ttk::combobox::Post", str(combo))
                root.update()
                root.state("normal")
                root.geometry(normal)
                root.update()
                check(prefix+"open_dropdown_kept", not ui.responsive_layout.fit() and ui.weekly_mode_combo is combo)
                combo.tk.call("ttk::combobox::Unpost", str(combo))
                settle()
                check(prefix+"resize_after_dropdown", ui.weekly_mode_combo is not combo and ui.weekly_mode.get() == "差分宇宙")
                ui.table.selected = "battlepass"
                ui._show_daily_tasks("battlepass")
                root.update()
                preserved_elements = sum(len(values) for values in root._hsr_preserved_elements.values())
                for _ in range(2):
                    root.state("normal")
                    root.geometry(normal)
                    settle()
                    root.state("zoomed")
                    settle()
                check(prefix+"daily_task_choice_and_focus_survive_resize", ui.settings_shell.section == "daily"
                      and root.focus_get() is ui.daily_task_controls["battlepass"])
                check(prefix+"repeated_resizes_reuse_preserved_theme_elements", preserved_elements ==
                      sum(len(values) for values in root._hsr_preserved_elements.values()))
                root.state("normal")
                root.geometry("%dx%d" % tuple(round((a+b)/2) for a,b in zip(normal_size, large_size)))
                settle()
                check(prefix+"larger_normal_window_scales", base < ui.ui_scale < maximum)
                root.geometry(normal)
                settle()
                gc.collect()
                check(prefix+"repeated_resizes_keep_images_bounded", len(root.tk.call("image", "names")) <= image_count+2)
                check(prefix+"repeated_resizes_keep_bindings_bounded", sum(bool(line.strip()) for line in root.bind("<Configure>").splitlines()) == bindings)
                ui.settings_shell.back.invoke()
                root.update()
                check(prefix+"daily_task_return_survives_resize", ui.active_page == "home"
                      and ui.table.selected == "battlepass" and root.focus_get() is ui.table)
                check(prefix+"config_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    checks.extend(tooltip_checks())
    result = dict(checks=checks, count=len(checks), game_started=False)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
