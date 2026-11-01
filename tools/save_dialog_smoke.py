"""Exercise actual modal close choices using temporary settings and no game access."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from summary_dialog_smoke import center, contained, content_widget, in_work_area
from autohsr import desktop_dialogs

OUT = ROOT / "runs/save-dialog-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, callback_errors = [], []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    def reject(*args, **kwargs):
        raise AssertionError("Close dialog checks must not access the game")

    def exists(root):
        try:
            return bool(root.winfo_exists())
        except tk.TclError as exc:
            if "application has been destroyed" not in str(exc):
                raise
            return False

    fake = types.ModuleType("autohsr.app")
    fake.Runner = fake.launch_game = fake.inspect_game = reject

    def cancel_drain(root):
        for token in root.tk.splitlist(root.tk.call("after", "info")):
            if "_drain" in str(root.tk.call("after", "info", token)):
                root.after_cancel(token)

    def make_window(config, scale):
        root = tk.Tk()
        root.tk.call("tk", "scaling", scale*96/72)
        root.report_callback_exception = lambda kind, value, tb: callback_errors.append(str(value))
        # Several Tk applications share this test process; cancel only the root's
        # timer when it exits so its Tcl callback cannot leak into the next one.
        root.bind("<Destroy>", lambda event: cancel_drain(root) if event.widget is root else None, add="+")
        return root, Window(root, config)

    def close_with(ui, action):
        """Drive the nested Tk loop only after the real modal has acquired its grab."""
        root = ui.root
        failures, pending = [], []
        deadline = time.monotonic()+8
        def drive():
            dialog = getattr(ui, "save_changes_dialog", None)
            if dialog is None or not dialog.winfo_exists() or root.grab_current() is not dialog:
                if time.monotonic() < deadline:
                    pending.append(root.after(20, drive))
                    return
                failures.append(AssertionError("Close confirmation did not become modal"))
                if dialog is not None and dialog.winfo_exists():
                    dialog.destroy()
                return
            try:
                root.update()
                action(dialog)
            except BaseException as exc:
                failures.append(exc)
                if dialog.winfo_exists():
                    dialog.buttons["cancel"].invoke()
        pending.append(root.after(20, drive))
        ui._close()
        for token in pending:
            try:
                root.after_cancel(token)
            except tk.TclError:
                pass
        if failures:
            raise failures[0]

    def dispose(ui):
        try:
            if ui.root.winfo_exists():
                ui.closing = True
                # Child painters own their callbacks and cancel them on Destroy.
                cancel_drain(ui.root)
                ui.root.destroy()
        except tk.TclError:
            pass

    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        for scale in (1., 1.25, 1.5, 2.):
            prefix = f"{scale}_"
            Settings().save(config)
            original = config.read_bytes()
            root, ui = make_window(config, scale)
            try:
                ui._show_page("tasks")
                root.update()
                ui.dungeon_advanced_button.invoke()
                ui.auto_launch.set(not ui.auto_launch.get())
                root.update()
                origin = ui.stamina_limit_entry
                origin.focus_force()
                origin.selection_range(0, "end")
                origin.icursor(1)
                root.update()
                draft = ui._form_signature()
                area = desktop_dialogs._work_area(root)

                def escape(dialog):
                    check(prefix+"explicit_choice_labels", [b.cget("text") for b in dialog.buttons.values()]
                          == ["返回修改", "不保存退出", "保存并退出"])
                    check(prefix+"centered_game_plate_without_os_chrome", bool(dialog.overrideredirect())
                          and all(abs(a-b) <= 1 for a,b in zip(center(dialog), center(root))))
                    check(prefix+"all_choices_inside_current_work_area", in_work_area(dialog, area)
                          and all(contained(b) for b in dialog.buttons.values()))
                    check(prefix+"single_notice_and_save_has_default_focus", content_widget(dialog).get("1.0", "end-1c")
                          == "本次修改尚未保存。" and root.focus_get() is dialog.buttons["save"])
                    check(prefix+"modal_blocks_owner_actions", root.grab_current() is dialog)
                    ui._close()
                    check(prefix+"repeated_close_keeps_one_confirmation", ui.save_changes_dialog is dialog
                          and dialog.winfo_exists() and not ui.closing)
                    dialog.buttons["save"].event_generate("<Tab>")
                    root.update()
                    check(prefix+"tab_wraps_to_return_choice", root.focus_get() is dialog.buttons["cancel"])
                    if scale == 1.25:
                        ImageGrab.grab(window=root.winfo_id()).save(OUT/"owner.png")
                        ImageGrab.grab(window=dialog.winfo_id()).save(OUT/"confirmation.png")
                    dialog.buttons["cancel"].event_generate("<Escape>")
                close_with(ui, escape)
                root.update()
                check(prefix+"escape_preserves_draft_caret_and_focus", not ui.closing and root.grab_current() is None
                      and root.focus_get() is origin and origin.selection_present() and origin.index("insert") == 1
                      and ui._form_signature() == draft and config.read_bytes() == original)

                close_with(ui, lambda dialog: dialog.buttons["save"].event_generate("<Alt-F4>"))
                root.update()
                check(prefix+"alt_f4_returns_to_editing", not ui.closing and root.focus_get() is origin
                      and ui.dirty and config.read_bytes() == original)

                def return_key(dialog):
                    dialog.buttons["cancel"].focus_force()
                    root.update()
                    dialog.buttons["cancel"].event_generate("<Return>")
                close_with(ui, return_key)
                root.update()
                check(prefix+"enter_uses_focused_return_instead_of_saving", not ui.closing
                      and ui._form_signature() == draft and config.read_bytes() == original)

                small = (200, 200, 200+round(460*scale), 200+round(260*scale))
                def compact(dialog):
                    buttons = list(dialog.buttons.values())
                    text = content_widget(dialog)
                    if text.vbar.winfo_ismapped() or text.yview() != (0., 1.):
                        print(json.dumps(dict(stage="compact_notice", scale=scale, dialog_size=[dialog.winfo_width(),dialog.winfo_height()],
                            text_size=[text.winfo_width(),text.winfo_height()], view=text.yview(), line=text.dlineinfo("1.0"),
                            pady=text.cget("pady"), header=dialog.detail_surface.header, footer=dialog.detail_surface.footer)), flush=True)
                        ImageGrab.grab(window=dialog.winfo_id()).save(OUT/"compact-clipped.png")
                    check(prefix+"small_work_area_keeps_all_choices_and_notice", in_work_area(dialog, small)
                          and all(contained(b) for b in buttons) and contained(content_widget(dialog)))
                    check(prefix+"small_notice_is_fully_visible_without_scrolling", not content_widget(dialog).vbar.winfo_ismapped()
                          and content_widget(dialog).yview() == (0., 1.))
                    check(prefix+"small_work_area_stacks_choices_without_overlap", all(a.winfo_y()+a.winfo_height() < b.winfo_y()
                          for a,b in zip(buttons,buttons[1:])) and min(b.winfo_height()/scale for b in buttons) >= 25)
                    if scale == 1.25:
                        ImageGrab.grab(window=dialog.winfo_id()).save(OUT/"compact.png")
                    buttons[0].invoke()
                with patch.object(desktop_dialogs, "_work_area", return_value=small):
                    close_with(ui, compact)

                ui.stamina_limit.set("abc")
                root.update()
                close_with(ui, lambda dialog: dialog.buttons["save"].event_generate("<Return>"))
                root.update()
                check(prefix+"save_validation_keeps_window_and_selects_error", not ui.closing and ui.dirty
                      and root.focus_get() is ui.stamina_limit_entry and ui.stamina_limit_entry.selection_present()
                      and "整数" in ui.summary_label.message() and config.read_bytes() == original and root.grab_current() is None)
                ui.stamina_limit.set("240")
                root.update()
                errors = []
                with patch.object(Settings, "save", side_effect=PermissionError("配置文件不可写")), patch.object(module.messagebox, "showerror", side_effect=lambda *a,**kw: errors.append(a)):
                    close_with(ui, lambda dialog: dialog.buttons["save"].invoke())
                root.update()
                check(prefix+"save_failure_preserves_file_and_editable_window", not ui.closing and ui.dirty
                      and errors == [("保存失败", "配置文件不可写")] and "保存失败" in ui.save_status.get()
                      and config.read_bytes() == original and root.grab_current() is None)

                def discard(dialog):
                    dialog.buttons["discard"].focus_force()
                    root.update()
                    dialog.buttons["discard"].event_generate("<Return>")
                close_with(ui, discard)
                check(prefix+"discard_exits_without_saving", ui.closing and not exists(root) and config.read_bytes() == original)
            finally:
                dispose(ui)

            root, ui = make_window(config, scale)
            try:
                root.update()
                expected = not ui.auto_launch.get()
                ui.auto_launch.set(expected)
                close_with(ui, lambda dialog: dialog.buttons["save"].event_generate("<Return>"))
                saved = Settings.load(config)
                check(prefix+"default_enter_saves_draft_then_exits", ui.closing and not exists(root)
                      and saved.auto_launch is expected and config.read_bytes() != original)
            finally:
                dispose(ui)
    check("no_tk_callback_errors", not callback_errors)
    result = dict(count=len(checks), checks=checks, callback_errors=callback_errors, game_started=False)
    (OUT/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
