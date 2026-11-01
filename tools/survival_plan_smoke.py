"""Select catalogue missions into a power draft without game or desktop input."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from autohsr.desktop_dialogs import DetailClose
from autohsr.power_plan_ui import rows

OUT=ROOT/'runs/survival-plan'
ITEM=dict(category='calyx_golden',target='回忆之蕾',location='城郊雪原',count=8)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    def check(name,value):assert value,(name,errors);checks.append(name)
    original=tk.Toplevel.__init__
    def transparent(window,*args,**kwargs):
        original(window,*args,**kwargs)
        window.withdraw();window.attributes('-alpha',0);window.attributes('-disabled',True)
    with tempfile.TemporaryDirectory() as folder,patch.object(tk.Toplevel,'__init__',transparent):
        local=Path(folder);config=local/'config.json'
        Settings(overlay_logs=False,battle=False,power_plan_enabled=True,power_plan=[ITEM],power_plan_fill=False).save(config)
        saved=config.read_bytes()
        with patch.object(module,'ROOT',local),patch.object(Window,'_start',side_effect=AssertionError('No game backend')):
            for scale in (1.,1.25,1.5,2.):
                root=tk.Tk();root.withdraw();root.attributes('-alpha',0);root.attributes('-disabled',True)
                root.tk.call('tk','scaling',scale*96/72)
                root.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
                ui=Window(root,config)
                try:
                    ui._show_page('tasks');root.deiconify();root.update()
                    board=ui.dungeon_list
                    default=(ui.dungeon_category.get(),ui.target_name.get(),ui.target_location.get(),ui.challenge_count.get())
                    for size,(w,h) in (('default',(1536,864)),('minimum',(1100,800))):
                        root.geometry(f'{round(w*scale)}x{round(h*scale)}');root.update()
                        check_layout(root)
                        check(f'{scale}_{size}_plan_controls_replace_single_target',ui.dungeon_plan_button.winfo_ismapped() and not ui.dungeon_count_controls.winfo_ismapped() and not ui.dungeon_manual_button.winfo_ismapped() and not ui.dungeon_advanced_button.winfo_ismapped() and ui.battle_checkbox.cget('text')=='执行体力计划')
                    existing=next(m for m in board.rows if m.name==ITEM['target'] and m.location==ITEM['location'])
                    candidate=next(m for m in board.rows if (m.name,m.location)!=(ITEM['target'],ITEM['location']))
                    check(f'{scale}_labels_follow_plan_membership',board.action_label(existing)=='编辑次数' and board.action_label(candidate)=='加入计划')
                    initial=ui._form_signature()
                    board.choose(board.rows.index(candidate));root.update()
                    dialog=ui.power_dialog
                    frame=next(w for w in dialog.winfo_children() if isinstance(w,ttk.Frame))
                    count=next(w for w in frame.winfo_children() if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox))
                    check(f'{scale}_catalogue_choice_opens_prefilled_plan',dialog.title()=='添加计划副本' and count.get()=='1' and ui._form_signature()==initial)
                    check(f'{scale}_selected_mission_focuses_count',str(root.tk.call('focus','-lastfor',dialog))==str(count) and count.selection_present())
                    cancel=next(w for w in dialog.winfo_children() if isinstance(w,DetailClose) and w.symbol=='cancel')
                    cancel.invoke();root.update()
                    check(f'{scale}_cancel_keeps_plan_and_disabled_task',ui.power_dialog is None and ui._form_signature()==initial and not ui.tasks['battle'].get())
                    board.choose(board.rows.index(candidate));root.update();dialog=ui.power_dialog
                    frame=next(w for w in dialog.winfo_children() if isinstance(w,ttk.Frame))
                    count=next(w for w in frame.winfo_children() if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox))
                    confirm=next(w for w in dialog.winfo_children() if isinstance(w,DetailClose) and w.symbol=='confirm')
                    count.delete(0,'end');count.insert(0,'0');confirm.invoke();root.update()
                    check(f'{scale}_invalid_count_keeps_dialog_and_original',ui.power_dialog is dialog and rows(ui)==[ITEM] and not ui.tasks['battle'].get())
                    count.delete(0,'end');count.insert(0,'3');confirm.invoke();root.update()
                    added=dict(category=candidate.category,target=candidate.name,location=candidate.location,count=3)
                    check(f'{scale}_apply_adds_selected_mission_once',ui.power_dialog is None and rows(ui)==[ITEM,added] and ui.tasks['battle'].get() and ui.power_mode.get()=='体力计划')
                    check(f'{scale}_default_fallback_is_untouched',default==(ui.dungeon_category.get(),ui.target_name.get(),ui.target_location.get(),ui.challenge_count.get()) and not ui.power_fill.get())
                    check(f'{scale}_summary_and_membership_follow_new_plan','2 项' in ui.dungeon_target_caption.get() and '共用上限' in ui.battle_cost.get() and board.action_label(candidate)=='编辑次数' and board.matches(candidate))
                    board.choose(board.rows.index(candidate));root.update();dialog=ui.power_dialog
                    frame=next(w for w in dialog.winfo_children() if isinstance(w,ttk.Frame))
                    count=next(w for w in frame.winfo_children() if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox))
                    check(f'{scale}_included_mission_reopens_its_original_count',dialog.title()=='编辑计划副本' and count.get()=='3')
                    count.delete(0,'end');count.insert(0,'5')
                    count.event_generate('<Return>');root.update()
                    check(f'{scale}_edit_updates_existing_row_without_duplicate',rows(ui)==[ITEM,dict(added,count=5)])
                    snapshot=ui._read_settings(operation='plan')
                    check(f'{scale}_runtime_snapshot_contains_catalogue_edits',snapshot is not None and snapshot.power_plan_enabled and snapshot.power_plan==[ITEM,dict(added,count=5)] and snapshot.battle and config.read_bytes()==saved)
                    ui.dungeon_plan_button.invoke();root.update()
                    check(f'{scale}_manage_plan_opens_shared_settings',ui.active_page=='settings' and ui.settings_tabs.select()==str(ui.settings_sections['power']))
                    ui._leave_settings();root.update()
                    check(f'{scale}_manage_plan_returns_to_catalogue',ui.active_page=='tasks' and str(root.tk.call('focus','-lastfor',root))==str(board))
                    ui.busy=True;ui._refresh_controls();board.choose(board.rows.index(candidate));root.update()
                    check(f'{scale}_running_plan_is_read_only',ui.power_dialog is None and board.action_label(candidate)=='已加入' and rows(ui)==[ITEM,dict(added,count=5)])
                    ui.busy=False;ui._refresh_controls();ui.tasks['battle'].set(False);root.update()
                    check(f'{scale}_disable_keeps_items_and_marks_not_executed',rows(ui)==[ITEM,dict(added,count=5)] and '未加入' in ui.dungeon_target_caption.get() and ui.battle_cost.get()=='本次不刷本')
                    ui.power_mode.set('单副本');root.update()
                    check(f'{scale}_single_mode_restores_original_controls',ui.dungeon_count_controls.winfo_ismapped() and ui.dungeon_manual_button.winfo_ismapped() and not ui.dungeon_plan_button.winfo_ismapped() and board.action_label(existing)=='加入计划')
                    check(f'{scale}_all_edits_remain_unsaved',config.read_bytes()==saved and ui.dirty)
                    check(f'{scale}_no_callback_errors',not errors)
                finally:
                    ui.closing=True
                    if getattr(ui,'power_dialog',None) is not None:ui.power_dialog.destroy()
                    for token in root.tk.splitlist(root.tk.call('after','info')):
                        if str(root.tk.call('after','info',token)[0]).endswith('_drain'):root.after_cancel(token)
                    root.destroy()
    result=dict(count=len(checks),checks=checks,game_started=False,os_input=False,desktop_capture=False,native_pixels_verified=False)
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(count=len(checks),game_started=False,os_input=False)))


if __name__=='__main__':main()
