"""Exercise detail placement, return focus and long content without game access."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import types
from unittest.mock import patch

from PIL import Image, ImageGrab, ImageTk
from ux_smoke import ROOT, Settings, Window, module, pump
from autohsr import desktop_dialogs
from autohsr.desktop_modes import show_mode_view

OUT = ROOT/"runs/game-dialog-ui"


def content_widget(dialog):
    return next(w for frame in dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == "Text")


def close_button(dialog):
    return next(w for w in dialog.winfo_children() if isinstance(w,ttk.Button))


def center(widget):
    return widget.winfo_rootx()+widget.winfo_width()/2, widget.winfo_rooty()+widget.winfo_height()/2


def contained(widget):
    x,y = widget.winfo_rootx(),widget.winfo_rooty()
    right,bottom = x+widget.winfo_width(),y+widget.winfo_height()
    parent = widget.master
    while parent is not None:
        if not (x >= parent.winfo_rootx() and y >= parent.winfo_rooty()
                and right <= parent.winfo_rootx()+parent.winfo_width()+1
                and bottom <= parent.winfo_rooty()+parent.winfo_height()+1):
            return False
        # A transient Toplevel is owned by the root, not clipped by its client.
        if isinstance(parent,tk.Toplevel):
            break
        parent = parent.master
    return bool(widget.winfo_ismapped())


def in_work_area(dialog, area):
    side = dialog.winfo_rootx()-dialog.winfo_x()
    return (dialog.winfo_x() >= area[0] and dialog.winfo_y() >= area[1]
            and dialog.winfo_rootx()+dialog.winfo_width()+side <= area[2]
            and dialog.winfo_rooty()+dialog.winfo_height()+side <= area[3])


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    checks, errors = [], []
    def check(name,value):
        assert value,name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Detail checks cannot start a game backend")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module,"ROOT",Path(folder)), patch.dict(sys.modules,{"autohsr.app":fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1.,1.25,1.5,2.):
            prefix = f"{scale}_"
            root = tk.Tk()
            root.tk.call("tk","scaling",scale*96/72)
            root.report_callback_exception = lambda kind,value,tb: errors.append(str(value))
            ui = Window(root,config)
            try:
                root.update()
                root.geometry("+500+250")
                root.update()
                root.focus_force()
                area = desktop_dialogs._work_area(root)
                detail = "10 开拓力待核对 · 窗口未能核实。\n"+"\n".join(f"核对记录 {n}" for n in range(80))+"\n末尾记录保留。"
                ui.table.item("battle",values=("日常副本挑战","未执行",detail),has_result=True)
                ui.table.selected = "battle"
                ui.table.focus_set()
                ui.table.activate()
                root.update()
                dialog = ui.summary_dialog
                check(prefix+"detail_is_centered_on_current_owner", all(abs(a-b) <= 1 for a,b in zip(center(dialog),center(root))))
                check(prefix+"native_frame_is_inside_current_monitor_work_area", in_work_area(dialog,area))
                check(prefix+"does_not_grab_pause_or_stop_controls", root.grab_current() is None and str(dialog.transient()) == str(root))
                text = content_widget(dialog)
                check(prefix+"long_text_is_complete_and_readonly", text.cget("state") == "disabled"
                      and text.get("1.0","end-1c") == "未执行\n"+detail)
                text.yview_moveto(1)
                text.tag_add("sel","end-8c","end-1c")
                root.update()
                check(prefix+"end_of_report_is_scrollable_and_selectable", float(text.yview()[1]) >= .999 and text.tag_ranges("sel"))
                check(prefix+"close_stays_visible", contained(close_button(dialog)))
                if scale == 1.25:
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/"centered.png")
                    ImageGrab.grab(window=dialog.winfo_id()).save(OUT/"centered-detail.png")
                    (OUT/"centered-position.json").write_text(json.dumps(dict(owner_center=center(root),
                        dialog_center=center(dialog),work_area=area)),"utf-8")
                text.focus_force()
                text.event_generate("<KeyPress-Escape>")
                root.update()
                check(prefix+"escape_returns_to_the_original_card", not dialog.winfo_exists() and root.focus_get() is ui.table
                      and ui.table.selected == "battle" and ui.table.item("battle","values")[2] == detail)

                ui.summary.set("部分完成 · 10 开拓力待核对\n核对记录后再继续。")
                root.update()
                ui.summary_label.activate()
                root.update()
                dialog = ui.summary_dialog
                close_button(dialog).invoke()
                root.update()
                check(prefix+"close_button_returns_to_the_summary_entry", root.focus_get() is ui.summary_label and not dialog.winfo_exists())

                ui.summary_label.activate()
                root.update()
                previous = ui.summary_dialog
                content_widget(previous).focus_force()
                ui._show_summary("另一项完整结果",title="核对结果")
                root.update()
                dialog = ui.summary_dialog
                check(prefix+"replacement_keeps_one_dialog_and_the_original_entry", not previous.winfo_exists()
                      and dialog.return_focus is ui.summary_label and dialog.title() == "核对结果")
                root.tk.call(dialog.protocol("WM_DELETE_WINDOW"))
                root.update()
                check(prefix+"window_close_protocol_restores_entry_focus", root.focus_get() is ui.summary_label and not dialog.winfo_exists())

                notice = "10 开拓力待核对。\n窗口未能核实。"
                ui._show_summary(notice,title="提示",return_focus=ui.summary_label)
                root.update()
                dialog = ui.summary_dialog
                text = content_widget(dialog)
                check(prefix+"short_notice_uses_a_game_panel_without_os_chrome", bool(dialog.overrideredirect())
                      and abs(dialog.winfo_width()/scale-774.4) <= 1
                      and abs(dialog.winfo_height()/scale-294.4) <= 1)
                check(prefix+"short_notice_has_one_heading_and_no_empty_scroll_rail", text.get("1.0","end-1c") == notice
                      and text.tag_cget("notice","justify") == "center" and not text.master.children["!scrollbar"].winfo_ismapped())
                pixels = ImageTk.getimage(dialog.detail_surface._photo).convert("RGB")
                reference = Image.open(ROOT/"autohsr/tests/fixtures/du_runtime/last_area_confirm.png").convert("RGB")
                # Independent 4.6 source coordinates: plate y360..720, footer y624.
                paper = pixels.getpixel((round(70*scale),round(190*scale)))
                original_paper = reference.getpixel((570,598))
                check(prefix+"paper_matches_the_saved_reference_sample", max(abs(a-b) for a,b in zip(paper,original_paper)) < 12)
                edge = next(y for y in range(round(100*scale),pixels.height)
                            if max(pixels.getpixel((round(20*scale),y))) < 100)
                check(prefix+"footer_boundary_matches_the_reference_proportion", abs(edge-(624-360)*.8*scale) <= 2)
                button = close_button(dialog)
                check(prefix+"close_pill_keeps_the_reference_size", abs(button.winfo_width()-360*.8*scale) <= 1.01
                      and abs(button.winfo_height()-58*.8*scale) <= 1.01)
                if scale == 1.25:
                    ImageGrab.grab(window=dialog.winfo_id()).save(OUT/"short-detail.png")
                root.iconify()
                pump(root,lambda: not dialog.winfo_ismapped())
                check(prefix+"minimizing_owner_hides_the_detail", not dialog.winfo_ismapped())
                root.deiconify()
                pump(root,lambda: dialog.winfo_ismapped())
                check(prefix+"restoring_owner_restores_the_same_detail", dialog.winfo_ismapped() and text.get("1.0","end-1c") == notice)
                text.focus_force()
                text.event_generate("<Alt-F4>")
                root.update()
                check(prefix+"alt_f4_closes_only_detail_and_returns_to_entry", root.winfo_exists()
                      and not dialog.winfo_exists() and root.focus_get() is ui.summary_label)

                ui.table.selected = "battle"
                ui.table.activate()
                root.update()
                dialog = ui.summary_dialog
                ui._show_page("tasks")
                root.update()
                ui.dungeon_list.focus_force()
                close_button(dialog).invoke()
                root.update()
                check(prefix+"closing_does_not_focus_a_hidden_card", ui.active_page == "tasks" and root.focus_get() is ui.dungeon_list)

                for page,field,button_name in (("differential_universe","du_result_report","du_record_button"),
                                               ("currency_wars","currency_result_report","currency_record_button")):
                    report = dict(operation=page,status="partial",error="独立记录仍待核对。")
                    snapshot = json.dumps(report,ensure_ascii=False,indent=2)
                    setattr(ui,field,report)
                    ui._show_page(page)
                    show_mode_view(ui,page,"result")
                    button = getattr(ui,button_name)
                    button.configure(state="normal")
                    root.update()
                    ui.nav_buttons[page].focus_set()
                    button.invoke()
                    root.update()
                    dialog = ui.summary_dialog
                    content = content_widget(dialog).get("1.0","end-1c")
                    close_button(dialog).invoke()
                    root.update()
                    check(prefix+page+"_record_returns_to_its_own_button", root.focus_get() is button
                          and content == snapshot and json.dumps(report,ensure_ascii=False,indent=2) == snapshot)
                ui._show_page("tasks")
                root.update()

                root.geometry(f"+{area[2]-300}+{area[3]-300}")
                root.update()
                ui._show_summary("靠近屏幕边缘的结果。")
                root.update()
                dialog = ui.summary_dialog
                if not (in_work_area(dialog,area) and contained(close_button(dialog))):
                    print(json.dumps(dict(edge_before_area=area,edge_current_area=desktop_dialogs._work_area(root),
                        dialog=[dialog.winfo_x(),dialog.winfo_y(),dialog.winfo_rootx(),dialog.winfo_rooty(),dialog.winfo_width(),dialog.winfo_height()],
                        close_visible=contained(close_button(dialog)))),flush=True)
                check(prefix+"edge_owner_keeps_the_whole_dialog_on_screen", in_work_area(dialog,area) and contained(close_button(dialog)))
                close_button(dialog).invoke()
                root.update()

                small = (200,200,820,560)
                with patch.object(desktop_dialogs,"_work_area",return_value=small):
                    ui._show_summary(detail)
                root.update()
                dialog = ui.summary_dialog
                check(prefix+"small_work_area_caps_size_and_minimum", in_work_area(dialog,small)
                      and all(a <= b for a,b in zip(dialog.minsize(),(dialog.winfo_width(),dialog.winfo_height()))))
                check(prefix+"small_work_area_keeps_close_and_scroll", contained(close_button(dialog))
                      and contained(content_widget(dialog)) and content_widget(dialog).get("1.0","end-1c") == detail)
                close_button(dialog).invoke()
                root.update()
                check(prefix+"configuration_and_overall_result_unchanged", config.read_bytes() == original
                      and ui.summary.get() == "部分完成 · 10 开拓力待核对\n核对记录后再继续。")
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
