"""Check task actions and the separate settings entry without a game backend."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from home_feedback_smoke import drawn_text
from summary_dialog_smoke import contained, content_widget, close_button

OUT = ROOT/"runs/entry-clarity-ui"


def click_card(root, board, key):
    root.focus_force()
    board._reveal(list(board.names).index(key))
    board.redraw()
    root.update()
    x1, y1, x2, y2 = board.hitboxes[key]
    board.event_generate("<Button-1>", x=round((x1+x2)/2*board.scale), y=round((y2-30)*board.scale))
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
                    check(prefix+size_name+"_settings_is_named_and_separate", setting.cget("text") == "设置"
                          and setting.master is ui.guide and str(setting.cget("compound")) == "left"
                          and contained(setting)
                          and setting.winfo_rootx() >= ui.guide.tabs.winfo_rootx()+ui.guide.tabs.winfo_width()+round(48*scale))
                    text = drawn_text(ui.table)
                    check(prefix+size_name+"_cards_show_names_target_and_cost", all(x in text for x in
                          ("持续委托", "日常副本", "每日实训", ui.target_name.get(), ui.target_location.get(), "开拓力"))
                          and not any(x in text for x in ("委托设置", "副本设置", "实训设置", "领取现有")))
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
                check(prefix+"unselected_task_offers_join", not ui.tasks["mail"].get() and ui.table.action_label("mail") == "加入计划")
                click_card(root,ui.table,"mail")
                check(prefix+"one_click_adds_only_this_task_to_the_draft", ui.tasks["mail"].get()
                      and not ui.tasks["battlepass"].get() and ui.active_page == "home" and ui.dirty
                      and ui.table.action_label("mail") == "调整任务" and ui.save_button.winfo_ismapped()
                      and not ui.busy and config.read_bytes() == original)
                click_card(root,ui.table,"mail")
                check(prefix+"adjust_opens_the_corresponding_choice", ui.active_page == "settings"
                      and ui.settings_tabs.select() == str(ui.settings_sections["daily"])
                      and root.focus_get() is ui.daily_task_controls["mail"])
                ui.tasks["mail"].set(False)
                ui._leave_settings()
                root.update()
                check(prefix+"return_retains_card_position", ui.table.selected == "mail" and root.focus_get() is ui.table)
                ui._set_busy(True)
                check(prefix+"running_cards_offer_inspection_instead_of_editing", ui.table.action_label("mail") == "查看安排")
                click_card(root,ui.table,"mail")
                check(prefix+"running_plan_cannot_be_changed_from_a_card", not ui.tasks["mail"].get()
                      and ui.daily_task_controls["mail"].instate(("disabled",)))
                ui._set_busy(False)
                ui._leave_settings()
                ui.settings.allow_stamina_spend = False
                ui.tasks["battle"].set(False)
                root.update()
                check(prefix+"unapproved_spend_never_offers_join", ui.table.action_label("battle") == "查看限制")
                click_card(root,ui.table,"battle")
                check(prefix+"resource_gate_is_preserved", not ui.tasks["battle"].get()
                      and ui.battle_checkbox.instate(("disabled",)) and ui.active_page == "tasks")
                ui.settings.allow_stamina_spend = True
                ui.tasks["battle"].set(True)
                ui._show_page("home")
                click_card(root,ui.table,"battle")
                check(prefix+"change_dungeon_opens_its_current_selection", ui.active_page == "tasks"
                      and root.focus_get() is ui.dungeon_list and ui.table.action_label("battle") == "更换副本")
                ui._show_page("home")
                ui.table.item("mail",values=("邮件附件","未执行","窗口未能核实。"),has_result=True)
                click_card(root,ui.table,"mail")
                dialog = ui.summary_dialog
                check(prefix+"finished_card_opens_its_result_without_changing_plan", not ui.tasks["mail"].get()
                      and dialog.title() == "邮件附件" and content_widget(dialog).get("1.0","end-1c") == "未执行\n窗口未能核实。")
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
