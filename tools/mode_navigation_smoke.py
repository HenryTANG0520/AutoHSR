"""Check visible mode navigation, nested Escape and unchanged drafts offline."""
from pathlib import Path
import json
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from autohsr.config import SettingsError
from autohsr.desktop_modes import show_mode_view

OUT = ROOT / "runs/mode-navigation-ui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    def click(widget):
        widget.event_generate("<ButtonPress-1>", x=widget.winfo_width()//2, y=widget.winfo_height()//2)
        widget.event_generate("<ButtonRelease-1>", x=widget.winfo_width()//2, y=widget.winfo_height()//2)

    def reject_runner(*args, **kwargs):
        raise AssertionError("Browsing mode settings must not call the game backend")

    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject_runner
    with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"autohsr.app": fake}), patch.object(module, "ROOT", Path(folder)):
        config = Path(folder) / "config.json"
        for scale in (1., 1.25, 1.5, 2.):
            Settings().save(config)
            original = config.read_bytes()
            root = tk.Tk()
            root.tk.call("tk", "scaling", scale*96/72)
            root.report_callback_exception = lambda kind, value, trace: (_ for _ in ()).throw(value.with_traceback(trace))
            ui = Window(root, config)
            try:
                root.update()
                root.focus_force()
                ui.du_team.set("临时编队")
                ui.differential_universe_runs.set("2")
                draft = ui._form_signature()
                for key in ui.mode_decks:
                    prefix = f"{scale}_{key}_"
                    ui._show_page(key)
                    root.update()
                    deck = ui.mode_decks[key]
                    click(deck["hero"].editor_button)
                    root.update()
                    entry = ui.du_runs_combo if key == "differential_universe" else ui.currency_tabs
                    check(prefix+"editor_focuses_visible_choice", deck["shown"] == "editor"
                          and root.focus_get() is entry and entry.winfo_viewable())
                    if key == "differential_universe":
                        entry.event_generate("<KeyPress-Down>")
                        root.update()
                        pop = str(root.tk.call("ttk::combobox::PopdownWindow", entry))
                        check(prefix+"choice_opens_without_tab", root.tk.call("winfo", "ismapped", pop))
                        root.tk.call("event", "generate", pop+".f.l", "<KeyPress-Escape>")
                        root.update()
                        check(prefix+"first_escape_only_closes_choice", deck["shown"] == "editor"
                              and not root.tk.call("winfo", "ismapped", pop) and ui._form_signature() == draft)
                        ui.du_team_entry.focus_set()
                        ui.du_team_entry.icursor(2)
                        ui.du_team_entry.selection_range(0, 2)
                    else:
                        ui.currency_tabs.select(ui.currency_sections["debug"])
                        root.update()
                    root.event_generate("<KeyPress-Escape>")
                    root.update()
                    check(prefix+"escape_returns_to_same_entry", deck["shown"] == "hero"
                          and root.focus_get() is deck["hero"].editor_button and ui._form_signature() == draft)
                    click(deck["hero"].editor_button)
                    root.update()
                    if key == "differential_universe":
                        check(prefix+"return_preserves_text_edit", ui.du_team_entry.index("insert") == 2
                              and ui.du_team_entry.selection_present()
                              and (ui.du_team_entry.index("sel.first"), ui.du_team_entry.index("sel.last")) == (0, 2))
                    else:
                        check(prefix+"return_preserves_developer_tab", ui.currency_tabs.select() == str(ui.currency_sections["debug"]))
                    click(deck["back_editor"])
                    root.update()
                    check(prefix+"mouse_back_restores_entry_focus", deck["shown"] == "hero"
                          and root.focus_get() is deck["hero"].editor_button)

                    observation = ui.du_observation if key == "differential_universe" else ui.currency_observation
                    observation.set("\n".join(f"核对记录 {n}" for n in range(60)))
                    click(deck["hero"].result_button)
                    root.update()
                    result = ui.du_result_text if key == "differential_universe" else ui.currency_result_text
                    check(prefix+"result_focuses_readable_record", deck["shown"] == "result"
                          and root.focus_get() is result and result.winfo_viewable())
                    result.event_generate("<KeyPress-Next>")
                    root.update()
                    position = result.yview()[0]
                    check(prefix+"result_pages_without_extra_click", position > 0)
                    root.event_generate("<KeyPress-Escape>")
                    root.update()
                    check(prefix+"result_escape_returns_to_result_entry", deck["shown"] == "hero"
                          and root.focus_get() is deck["hero"].result_button)
                    click(deck["hero"].result_button)
                    root.update()
                    check(prefix+"return_keeps_record_position", abs(result.yview()[0]-position) < .001)
                    click(deck["back_result"])
                    root.update()
                    check(prefix+"result_mouse_back_restores_entry", root.focus_get() is deck["hero"].result_button)

                    ui._set_busy(True)
                    click(deck["hero"].editor_button)
                    root.update()
                    check(prefix+"busy_editor_focuses_return", root.focus_get() is deck["back_editor"])
                    root.event_generate("<KeyPress-Escape>")
                    root.update()
                    check(prefix+"busy_return_does_not_stop_or_unlock", ui.busy and not ui.stopping
                          and deck["shown"] == "hero" and ui.start_button.instate(("disabled",)))
                    ui._set_busy(False)
                    root.event_generate("<KeyPress-Escape>")
                    root.update()
                    check(prefix+"escape_at_entrance_does_not_exit", not ui.closing and deck["shown"] == "hero")

                    # A queued navigation focus must yield to an explicit error or dialog.
                    deck["hero"].editor_button.invoke()
                    target = ui.du_team_entry if key == "differential_universe" else ui.currency_tabs
                    if key == "differential_universe":
                        ui._input_failed(SettingsError("differential_universe_team", "测试字段定位"))
                    else:
                        root.after_idle(target.focus_set)
                    root.update()
                    check(prefix+"explicit_field_focus_wins", root.focus_get() is target and target.winfo_viewable())
                    ui._clear_input_error()
                    click(deck["back_editor"])
                    root.update()
                    deck["hero"].editor_button.invoke()
                    dialog = tk.Toplevel(root)
                    field = tk.Entry(dialog)
                    field.pack()
                    root.after_idle(field.focus_set)
                    root.update()
                    check(prefix+"separate_dialog_keeps_focus", root.focus_get() is field)
                    check(prefix+"dialog_escape_does_not_navigate_parent", ui._page_escape(types.SimpleNamespace(widget=field)) is None
                          and deck["shown"] == "editor")
                    dialog.destroy()
                    root.focus_force()
                    show_mode_view(ui, key, "hero")
                    root.update()

                    deck["hero"].editor_button.invoke()
                    ui._show_page("home")
                    ui.table.focus_set()
                    root.update()
                    check(prefix+"quick_page_change_keeps_visible_focus", ui.active_page == "home"
                          and root.focus_get() is ui.table)
                    check(prefix+"draft_and_disk_unchanged", ui._form_signature() == draft and config.read_bytes() == original)

                ui._show_page("differential_universe")
                show_mode_view(ui, "differential_universe", "hero")
                root.update()
                click(ui.mode_decks["differential_universe"]["hero"].editor_button)
                root.update()
                if scale == 1.25:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT / "editor-focus.png")
                ui.guide.buttons["settings"].invoke()
                root.update()
                root.event_generate("<KeyPress-Escape>")
                root.update()
                check(f"{scale}_settings_returns_before_mode_return", ui.active_page == "differential_universe"
                      and ui.mode_decks["differential_universe"]["shown"] == "editor")
                root.event_generate("<KeyPress-Escape>")
                root.update()
                check(f"{scale}_next_escape_returns_to_entrance", ui.mode_decks["differential_universe"]["shown"] == "hero"
                      and root.focus_get() is ui.mode_decks["differential_universe"]["hero"].editor_button)
                check(f"{scale}_config_bytes_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    result = dict(count=len(checks), checks=checks, game_started=False, backend_calls=0, config_unchanged=True)
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
