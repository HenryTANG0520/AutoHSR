"""Check reused layouts against current drafts, results and running controls."""
from pathlib import Path
import json
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageChops, ImageGrab, ImageTk
from ux_smoke import ROOT, Settings, Window, module
from autohsr import theme


def main():
    checks = []
    out = ROOT/"runs/layout-cache-ui"
    out.mkdir(parents=True, exist_ok=True)
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Layout checks cannot start a game backend")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        root = tk.Tk()
        root.tk.call("tk", "scaling", 1.5*96/72)
        errors = []
        root.report_callback_exception = lambda kind, value, tb: errors.append(repr(value))
        ui = Window(root, config)
        def settle():
            root.update()
            ui.responsive_layout.fit()
            root.update()
            assert not errors, errors
        def table_is_current(name):
            board = ui.table
            painter = theme.Painter(board.winfo_width(), board.winfo_height(), board.scale, board.cget("bg"))
            board.paint(painter)
            expected = painter.finish().convert("RGB")
            actual = ImageTk.getimage(board._photo).convert("RGB")
            check(name, actual.size == expected.size and ImageChops.difference(actual, expected).getbbox() is None)
        try:
            settle()
            normal = root.geometry()
            normal_size = root.winfo_width(), root.winfo_height()
            normal_shell = ui.shell
            root.state("zoomed")
            settle()
            maximum_size = root.winfo_width(), root.winfo_height()
            maximum_shell = ui.shell
            check("normal_layout_is_retained_and_hidden", normal_shell.winfo_exists() and not normal_shell.winfo_ismapped())
            ui.weekly_enabled.set(True)
            ui.weekly_time.set("06:45")
            ui.tasks["mail"].set(True)
            ui._show_weekly_plan()
            settle()
            root.focus_force()
            ui.weekly_time_entry.focus_set()
            ui.weekly_time_entry.icursor(3)
            ui.weekly_time_entry.selection_range(0, 2)
            ui._log("缓存期间新增的记录", "error")
            ui._task(dict(task="battle", status="running", detail="已完成1次"), log=False)
            ui.du_observation.set("本次结果已更新")
            root.update()
            check("editing_field_has_focus_before_resize", root.focus_get() is ui.weekly_time_entry)
            signature, events = ui._form_signature(), ui.events
            root.state("normal")
            root.geometry(normal)
            settle()
            check("restore_uses_original_widgets", ui.shell is normal_shell)
            check("latest_draft_and_selection_are_kept", ui._form_signature() == signature and ui.dirty
                  and ui.settings_shell.section == "weekly" and root.focus_get() is ui.weekly_time_entry
                  and ui.weekly_time_entry.index("insert") == 3 and ui.weekly_time_entry.index("sel.last") == 2)
            check("latest_log_and_result_are_kept", "缓存期间新增的记录" in ui.log.get("1.0", "end")
                  and bool(ui.log.tag_ranges("error")) and ui.du_result_text.get("1.0", "end-1c") == "本次结果已更新"
                  and ui.events is events)
            ui._show_page("home")
            settle()
            check("task_status_is_current", ui.table.item("battle", "values")[1] == "进行中")
            table_is_current("visible_card_pixels_match_current_state")
            ui._show_page("tasks")
            settle()
            ui.category_buttons["历战余响"].invoke()
            ui.dungeon_list.choose(0)
            settle()
            def dungeon_options():
                return (tuple(ui.dungeon_name_combo.cget("values")), tuple(ui.dungeon_location_combo.cget("values")),
                        float(ui.challenge_entry.cget("to")), float(ui.challenge_scale.cget("to")),
                        round(ui.challenge_scale.get()), ui.challenge_count.get())
            selected_options = dungeon_options()
            check("selected_category_has_its_own_limits", ui.dungeon_category.get() == "历战余响"
                  and selected_options[2:4] == (3, 3))
            root.state("zoomed")
            settle()
            check("cached_dungeon_choices_and_limits_are_current", dungeon_options() == selected_options)
            ui.category_buttons["拟造花萼（金）"].invoke()
            ui.dungeon_list.choose(0)
            ui.challenge_scale.set(7)
            settle()
            expanded_options = dungeon_options()
            check("category_can_expand_range_and_change_count", expanded_options[2:] == (24, 24, 7, "7"))
            root.state("normal")
            root.geometry(normal)
            settle()
            check("cached_expanded_range_and_slider_are_current", dungeon_options() == expanded_options)
            ui.challenge_count.set("abc")
            ui._show_weekly_plan()
            settle()
            ui.weekly_time_entry.selection_clear()
            signature = ui._form_signature()
            root.state("zoomed")
            settle()
            check("incomplete_draft_is_not_normalized_by_resize", ui._form_signature() == signature
                  and ui.challenge_count.get() == "abc" and round(ui.challenge_scale.get()) == 7)
            check("old_entry_selection_is_not_restored", not ui.weekly_time_entry.selection_present())
            ui.challenge_count.set("7")
            root.state("normal")
            root.geometry(normal)
            settle()
            ui._show_page("home")
            settle()
            class Runner:
                def __init__(self):
                    self.pauses = self.stops = 0
                def toggle_pause(self):
                    self.pauses += 1
                    return True
                def stop(self):
                    self.stops += 1
            runner = Runner()
            ui.runner = runner
            ui._has_run = True
            ui._set_busy(True, running=True)
            root.state("zoomed")
            settle()
            check("maximize_reuses_widgets_and_live_runner", ui.shell is maximum_shell and ui.runner is runner and ui.events is events)
            check("cached_controls_follow_run_lock", ui.start_button.instate(("disabled",)) and ui.weekly_time_entry.instate(("disabled",)))
            ui.pause_button.invoke()
            settle()
            root.state("normal")
            root.geometry(normal)
            settle()
            check("pause_state_survives_return", ui.paused and ui.pause_button.cget("text") == "继续 F9" and runner.pauses == 1)
            ui.stop_button.invoke()
            check("stop_reaches_same_runner_once", runner.stops == 1 and ui.stop_requested.is_set())
            ui.runner = None
            ui._set_busy(False)
            evicted = ui.responsive_layout.cached_view["fields"]["shell"]
            middle = "%dx%d" % tuple((a+b)//2 for a,b in zip(normal_size, maximum_size))
            root.geometry(middle)
            settle()
            check("third_size_releases_older_controls", not evicted.winfo_exists() and len(root.winfo_children()) == 2)
            shell_ids = {str(widget) for widget in root.winfo_children()}
            with patch.object(ui, "_build", side_effect=AssertionError("Warm layouts must not be rebuilt")):
                for _ in range(3):
                    for geometry in (normal, middle):
                        root.geometry(geometry)
                        settle()
            check("repeated_sizes_keep_exactly_two_layouts", {str(widget) for widget in root.winfo_children()} == shell_ids
                  and sum(bool(widget.winfo_ismapped()) for widget in root.winfo_children()) == 1)
            previous_shell, previous_geometry = ui.shell, root.geometry()
            root.geometry("%dx%d" % tuple((a+3*b)//4 for a,b in zip(normal_size, maximum_size)))
            root.update_idletasks()
            build = ui._build
            def failed_build(**kwargs):
                build(**kwargs)
                raise RuntimeError("simulated layout preparation failure")
            with patch.object(ui, "_build", side_effect=failed_build):
                try:
                    ui.responsive_layout.fit()
                except RuntimeError as error:
                    check("preparation_failure_is_reported", str(error) == "simulated layout preparation failure")
                else:
                    raise AssertionError("Expected preparation failure")
            root.geometry(previous_geometry)
            settle()
            check("failed_replacement_keeps_previous_interface", ui.shell is previous_shell and ui.start_button.winfo_ismapped()
                  and len(root.winfo_children()) == 1 and not ui._loading)
            check("failed_replacement_keeps_theme_images", all(root.tk.call("image", "type", str(photo)) == "photo"
                  for photo in root._hsr_images))
            table_is_current("recovered_card_pixels_match_current_state")
            ImageGrab.grab(window=root.winfo_id()).save(out/"recovered.png")
            check("config_is_unchanged", config.read_bytes() == original)
        finally:
            ui.closing = True
            for token in root.tk.splitlist(root.tk.call("after", "info")):
                root.after_cancel(token)
            root.destroy()
    result = dict(count=len(checks), checks=checks, game_started=False)
    (out/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
