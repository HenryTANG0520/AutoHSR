"""Check task actions and the separate settings entry without a game backend."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module, pump
from home_feedback_smoke import drawn_text
from summary_dialog_smoke import contained, content_widget, close_button

OUT = ROOT/"runs/entry-clarity-ui"


def click_card(root, board, key):
    root.focus_force()
    board._reveal(board.card_keys.index(key))
    pump(root, lambda: board._slide_job is None)
    board.redraw()
    root.update()
    x1, y1, x2, y2 = board.hitboxes[key]
    x, y = round((x1+x2)/2*board.scale), round((y2-30)*board.scale)
    board.event_generate("<Button-1>", x=x, y=y)
    board.event_generate("<ButtonRelease-1>", x=x, y=y)
    root.update()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    def check(name, value):
        assert value, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Entry checks cannot start a game backend")
    fake_app, fake_plan = types.ModuleType("autohsr.app"), types.ModuleType("autohsr.plan_runner")
    fake_app.Runner, fake_plan.PlanRunner = reject, reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module,"ROOT",Path(folder)), \
            patch.dict(sys.modules,{"autohsr.app":fake_app,"autohsr.plan_runner":fake_plan}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.25, 1.5, 2.):
            prefix = f"{scale}_"
            root = tk.Tk()
            root.tk.call("tk","scaling",scale*96/72)
            root.report_callback_exception = lambda kind,value,tb: errors.append(str(value))
            ui = Window(root,config)
            try:
                root.update()
                root.focus_force()
                default_size = root.winfo_width(),root.winfo_height()
                for size_name, size in (("normal", default_size), ("minimum", root.minsize())):
                    root.geometry("%dx%d" % size)
                    root.update()
                    setting = ui.nav_buttons["settings"]
                    check(prefix+size_name+"_settings_is_named_and_in_guide_tabs", setting.cget("text") == "设置"
                          and setting.master is ui.guide.tabs and str(setting.cget("compound")) == "none"
                          and contained(setting) and setting.cget("image"))
                    text = drawn_text(ui.table)
                    check(prefix+size_name+"_cards_show_names_target_and_cost", all(x in text for x in
                          ("日常副本", "每日计划", ui.target_name.get(), ui.target_location.get(), "开拓力"))
                          and not any(x in text for x in ("持续委托", "邮件附件", "无名勋礼", "领取现有")))
                    if scale in (1., 1.25):
                        ImageGrab.grab(window=root.winfo_id()).save(OUT/f"{scale}-{size_name}-home.png")
                for page in ("home", "tasks", "differential_universe", "currency_wars", "logs"):
                    ui._show_page(page)
                    root.update()
                    setting = ui.nav_buttons["settings"]
                    check(prefix+page+"_settings_remains_visible", contained(setting))
                    root.focus_force()
                    setting.event_generate("<ButtonPress-1>",x=setting.winfo_width()//2,y=setting.winfo_height()//2)
                    setting.event_generate("<ButtonRelease-1>",x=setting.winfo_width()//2,y=setting.winfo_height()//2)
                    root.update()
                    check(prefix+page+"_one_click_opens_settings", ui.active_page == "settings" and ui.settings_shell.winfo_ismapped())
                    ui.settings_shell.back.invoke()
                    root.update()
                    check(prefix+page+"_return_keeps_context_and_focus", ui.active_page == page
                          and str(root.tk.call("focus","-lastfor",root)) == str(setting))
                ui._show_page("home")
                root.update()
                check(prefix+"mail_has_no_top_level_card", not ui.tasks["mail"].get() and "mail" not in ui.table.card_keys)
                click_card(root, ui.table, "daily")
                check(prefix+"daily_card_opens_task_choices_without_editing", ui.active_page == "settings"
                      and ui.settings_tabs.select() == str(ui.settings_sections["daily"])
                      and ui.daily_task_controls["mail"].winfo_ismapped() and not ui.dirty)
                ui._leave_settings()
                root.update()
                check(prefix+"return_retains_card_position", ui.table.selected == "daily" and root.focus_get() is ui.table)
                ui._set_busy(True)
                check(prefix+"running_card_explains_lock", ui.table.action_label("daily") == "设置已锁定")
                click_card(root, ui.table, "daily")
                check(prefix+"running_plan_cannot_be_changed_from_a_card", ui.active_page == "home"
                      and not ui.tasks["mail"].get() and ui.daily_task_controls["mail"].instate(("disabled",)))
                ui._set_busy(False)
                ui._leave_settings()
                ui.settings.allow_stamina_spend = False
                ui.tasks["battle"].set(False)
                root.update()
                check(prefix+"unapproved_spend_never_offers_join", ui.table.action_label("battle") == "查看限制")
                click_card(root,ui.table,"battle")
                check(prefix+"resource_gate_is_preserved", not ui.tasks["battle"].get()
                      and ui.daily_task_controls["battle"].instate(("disabled",)) and ui.active_page == "settings")
                ui.settings.allow_stamina_spend = True
                ui.tasks["battle"].set(True)
                ui._show_page("home")
                click_card(root,ui.table,"battle")
                check(prefix+"change_dungeon_opens_its_current_selection", ui.active_page == "tasks"
                      and root.focus_get() is ui.dungeon_list and ui.table.action_label("battle") == "更换副本")
                ui._show_page("home")
                ui.table.item("mail",values=("邮件附件","未执行","窗口未能核实。"),has_result=True)
                click_card(root, ui.table, "daily")
                dialog = ui.detail_view
                check(prefix+"finished_daily_card_preserves_secondary_result", not ui.tasks["mail"].get()
                      and ui.detail_title.cget("text") == "每日计划 · 任务结果"
                      and "窗口未能核实。" in content_widget(dialog).get("1.0", "end-1c"))
                close_button(dialog).invoke()
                root.update()
                check(prefix+"configuration_is_not_implicitly_saved", config.read_bytes() == original)
            finally:
                ui.closing = True
                root.update_idletasks()
                for token in root.tk.splitlist(root.tk.call("after","info")):
                    root.after_cancel(token)
                root.destroy()
    check("no_callback_errors",not errors)
    result = dict(count=len(checks),checks=checks,game_started=False,config_unchanged=True)
    (OUT/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
