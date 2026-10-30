"""Mapped transparent, disabled test windows: geometry and local widget commands."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from ux_smoke import ROOT,Settings,Window,module
from ui_layout_smoke import check_layout
from autohsr.power_plan_ui import rows
from autohsr.desktop_dialogs import DetailClose

OUT=ROOT/'runs/power-plan-layout-ui'
ITEM=dict(category='calyx_golden',target='回忆之蕾',location='城郊雪原',count=8)


def main():
    OUT.mkdir(parents=True,exist_ok=True);checks=[];errors=[];geometry=[]
    def check(name,value):assert value,(name,errors);checks.append(name)
    original=tk.Toplevel.__init__
    def transparent(window,*args,**kwargs):
        original(window,*args,**kwargs);window.withdraw();window.attributes('-alpha',0);window.attributes('-disabled',True)
    with tempfile.TemporaryDirectory() as folder,patch.object(tk.Toplevel,'__init__',transparent):
        local=Path(folder);config=local/'config.json';Settings(overlay_logs=False,power_plan=[ITEM]).save(config);saved=config.read_bytes()
        with patch.object(module,'ROOT',local):
            for scale in (1.,1.25,1.5,2.):
                root=tk.Tk();root.withdraw();root.attributes('-alpha',0);root.attributes('-disabled',True)
                root.tk.call('tk','scaling',scale*96/72)
                root.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
                ui=Window(root,config)
                try:
                    root.deiconify();root.update();default=root.geometry().split('+')[0]
                    ui.power_mode.set('体力计划');ui.settings_shell.choose('power');root.update()
                    for size in ('default','minimum','default-again'):
                        root.geometry('%dx%d'%root.minsize() if size=='minimum' else default)
                        root.update();ui.responsive_layout.fit();root.update()
                        check_layout(root)
                        check(f'{scale}_{size}_plan_editor_mapped',ui.power_plan_list.winfo_ismapped() and ui.power_plan_list.winfo_height()>=round(90*ui.ui_scale))
                        check(f'{scale}_{size}_original_target_visible',ui.power_plan_list.item('0','values')[-1]=='8')
                        check(f'{scale}_{size}_seven_settings_entries_fit',all(button.winfo_rootx()>=root.winfo_rootx() and button.winfo_rootx()+button.winfo_width()<=root.winfo_rootx()+root.winfo_width() for button in ui.settings_shell.buttons.values()))
                        geometry.append(dict(scale=scale,size=size,window=[root.winfo_width(),root.winfo_height()],table=[ui.power_plan_list.winfo_width(),ui.power_plan_list.winfo_height()]))
                    ui.power_editor.replace([]);root.update();ui._refresh_controls();root.update()
                    check(f'{scale}_empty_list_only_allows_add',not ui.power_editor.buttons[0].instate(('disabled',)) and all(button.instate(('disabled',)) for button in ui.power_editor.buttons[1:]))
                    ui.power_editor.replace([ITEM]);root.update();ui._refresh_controls();root.update()
                    check(f'{scale}_unselected_list_does_not_offer_edit',all(button.instate(('disabled',)) for button in ui.power_editor.buttons[1:]))
                    ui.power_editor.buttons[0].invoke();root.update();dialog=ui.power_dialog
                    check(f'{scale}_add_uses_game_panel',dialog.overrideredirect() and dialog.grab_current() is dialog)
                    frame=next(widget for widget in dialog.winfo_children() if isinstance(widget,ttk.Frame))
                    choices=[widget for widget in frame.winfo_children() if isinstance(widget,ttk.Combobox)]
                    count=next(widget for widget in frame.winfo_children() if isinstance(widget,ttk.Entry) and not isinstance(widget,ttk.Combobox))
                    confirm=next(widget for widget in dialog.winfo_children() if isinstance(widget,DetailClose) and widget.symbol=='confirm')
                    choices[1].set('回忆之蕾');choices[1].event_generate('<<ComboboxSelected>>');root.update()
                    places=choices[2].cget('values');check(f'{scale}_same_name_exposes_locations',len(places)>1)
                    choices[2].set(places[-1]);count.delete(0,'end');count.insert(0,'0');confirm.invoke();root.update()
                    check(f'{scale}_invalid_count_keeps_dialog_and_target',dialog.winfo_exists() and rows(ui)==[ITEM])
                    check_layout(root)
                    count.delete(0,'end');count.insert(0,'3');confirm.invoke();root.update()
                    check(f'{scale}_add_commits_selected_location_once',len(rows(ui))==2 and rows(ui)[-1]['location']==places[-1] and rows(ui)[-1]['count']==3 and ui.power_dialog is None)
                    ui.power_plan_list.selection_set('0');root.update();ui._refresh_controls();root.update()
                    check(f'{scale}_first_row_only_moves_down',not ui.power_editor.buttons[1].instate(('disabled',)) and not ui.power_editor.buttons[2].instate(('disabled',)) and ui.power_editor.buttons[3].instate(('disabled',)) and not ui.power_editor.buttons[4].instate(('disabled',)))
                    ui.power_plan_list.selection_set('1');root.update();ui._refresh_controls();root.update()
                    check(f'{scale}_last_row_only_moves_up',not ui.power_editor.buttons[3].instate(('disabled',)) and ui.power_editor.buttons[4].instate(('disabled',)))
                    ui.busy=True;ui._refresh_controls();root.update()
                    check(f'{scale}_busy_disables_all_list_actions',all(button.instate(('disabled',)) for button in ui.power_editor.buttons))
                    ui.busy=False;ui._refresh_controls();root.update()
                    check(f'{scale}_idle_restores_only_available_actions',not ui.power_editor.buttons[0].instate(('disabled',)) and not ui.power_editor.buttons[3].instate(('disabled',)) and ui.power_editor.buttons[4].instate(('disabled',)))
                    ui.power_plan_list.selection_set('0');ui.power_editor.edit();root.update();dialog=ui.power_dialog
                    cancel=next(widget for widget in dialog.winfo_children() if isinstance(widget,DetailClose) and widget.symbol=='cancel')
                    cancel.invoke();root.update()
                    check(f'{scale}_cancel_preserves_targets',rows(ui)[0]==ITEM and ui.power_dialog is None)
                    ui.power_editor.edit_echo();root.update();dialog=ui.power_dialog
                    frame=next(widget for widget in dialog.winfo_children() if isinstance(widget,ttk.Frame))
                    choices=[widget for widget in frame.winfo_children() if isinstance(widget,ttk.Combobox)]
                    check(f'{scale}_echo_category_is_fixed',choices[0].instate(('disabled',)) and choices[0].get()=='历战余响')
                    choices[-1].set('周五')
                    confirm=next(widget for widget in dialog.winfo_children() if isinstance(widget,DetailClose) and widget.symbol=='confirm')
                    confirm.invoke();root.update()
                    check(f'{scale}_echo_preferences_do_not_enable_execution',ui.echo_day.get()=='周五' and not ui.echo_enabled.get() and ui.echo_target.get()=='毁灭的开端')
                    original_fallback=(ui.dungeon_category.get(),ui.target_name.get(),ui.target_location.get(),ui.challenge_count.get())
                    plan=ui.power_rows.get();ui.power_fill.set(False);ui.tasks['battle'].set(False)
                    ui.power_fill_config_button.invoke();root.update();dialog=ui.power_dialog
                    check(f'{scale}_fallback_has_direct_game_dialog',dialog.title()=='补刷副本' and dialog.grab_current() is dialog)
                    frame=next(widget for widget in dialog.winfo_children() if isinstance(widget,ttk.Frame))
                    choices=[widget for widget in frame.winfo_children() if isinstance(widget,ttk.Combobox)]
                    count=next(widget for widget in frame.winfo_children() if isinstance(widget,ttk.Entry) and not isinstance(widget,ttk.Combobox))
                    count.delete(0,'end');count.insert(0,'2')
                    cancel=next(widget for widget in dialog.winfo_children() if isinstance(widget,DetailClose) and widget.symbol=='cancel')
                    cancel.invoke();root.update()
                    check(f'{scale}_fallback_cancel_preserves_draft',ui.power_dialog is None and original_fallback==(ui.dungeon_category.get(),ui.target_name.get(),ui.target_location.get(),ui.challenge_count.get()))
                    ui.power_fill_config_button.invoke();root.update();dialog=ui.power_dialog
                    frame=next(widget for widget in dialog.winfo_children() if isinstance(widget,ttk.Frame))
                    choices=[widget for widget in frame.winfo_children() if isinstance(widget,ttk.Combobox)]
                    count=next(widget for widget in frame.winfo_children() if isinstance(widget,ttk.Entry) and not isinstance(widget,ttk.Combobox))
                    confirm=next(widget for widget in dialog.winfo_children() if isinstance(widget,DetailClose) and widget.symbol=='confirm')
                    for name,maximum in (('拟造花萼（金）',24),('拟造花萼（赤）',24),('凝滞虚影',8),('侵蚀隧洞',6),('历战余响',3),('饰品提取',6)):
                        choices[0].set(name);choices[0].event_generate('<<ComboboxSelected>>');root.update()
                        count.delete(0,'end');count.insert(0,str(maximum+1));confirm.invoke();root.update()
                        check(f'{scale}_fallback_limit_{name}',dialog.winfo_exists() and ui.power_rows.get()==plan and any(f'1～{maximum}' in str(widget.cget('text')) for widget in frame.winfo_children() if isinstance(widget,ttk.Label)))
                        check_layout(root)
                    choices[0].set('拟造花萼（金）');choices[0].event_generate('<<ComboboxSelected>>')
                    choices[1].set('回忆之蕾');choices[1].event_generate('<<ComboboxSelected>>');root.update()
                    choices[2].set(choices[2].cget('values')[-1]);count.delete(0,'end');count.insert(0,'2')
                    location=choices[2].get();confirm.invoke();root.update()
                    check(f'{scale}_fallback_updates_target_and_count',ui.power_dialog is None and ui.target_name.get()=='回忆之蕾' and ui.target_location.get()==location and ui.challenge_count.get()=='2')
                    check(f'{scale}_fallback_does_not_enable_or_change_plan',not ui.power_fill.get() and not ui.tasks['battle'].get() and ui.power_rows.get()==plan)
                    ui.power_fill.set(True);root.update()
                    check(f'{scale}_fallback_summary_uses_new_draft',location in ui.power_editor.caption.get() and '最多2次' in ui.power_editor.caption.get())
                    ui.busy=True;ui.power_fill_config_button.invoke();root.update()
                    check(f'{scale}_fallback_refuses_busy_edit',ui.power_dialog is None)
                    ui.busy=False
                    check(f'{scale}_controls_leave_saved_config',config.read_bytes()==saved)
                    check(f'{scale}_no_callback_errors',not errors)
                finally:
                    ui.closing=True
                    if getattr(ui,'power_dialog',None) is not None:ui.power_dialog.destroy()
                    for token in root.tk.splitlist(root.tk.call('after','info')):
                        if str(root.tk.call('after','info',token)[0]).endswith('_drain'):root.after_cancel(token)
                    root.destroy()
    (OUT/'result.json').write_text(json.dumps(dict(count=len(checks),checks=checks,geometry=geometry,
        transparent_disabled_windows=True,os_input=False,game_started=False,native_pixels_verified=False),ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(checks=len(checks),os_input=False,game_started=False)))


if __name__=='__main__':main()
