"""Guide navigation checks using transparent, input-disabled Tk windows."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch
from PIL import Image,ImageTk
from ux_smoke import ROOT,Settings,Window,module

OUT=ROOT/'runs/guide-tabs'

def main():
    OUT.mkdir(parents=True,exist_ok=True);checks=[];errors=[]
    def check(name,value):assert value,(name,errors);checks.append(name)
    with tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),patch.object(Window,'_start',side_effect=AssertionError('No backend')):
        config=Path(folder)/'config.json';Settings(overlay_logs=False).save(config);saved=config.read_bytes()
        for scale in (1.,1.25,1.5,2.):
            root=tk.Tk();root.withdraw();root.attributes('-alpha',0);root.attributes('-disabled',True)
            root.tk.call('tk','scaling',scale*96/72)
            root.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
            ui=Window(root,config)
            try:
                for size,(w,h) in (('default',(1536,864)),('minimum',(1100,800))):
                    root.geometry(f'{round(w*scale)}x{round(h*scale)}');root.deiconify();root.update()
                    keys=('home','tasks','universe','logs','settings');buttons=[ui.guide.buttons[k] for k in keys]
                    check(f'{scale}_{size}_five_contiguous_tabs',all(b.master is ui.guide.tabs for b in buttons) and all(a.winfo_x()+a.winfo_width()==b.winfo_x() and a.winfo_y()==b.winfo_y() and a.winfo_height()==b.winfo_height() for a,b in zip(buttons,buttons[1:])))
                    check(f'{scale}_{size}_tabs_fit_before_seal',ui.guide.tabs.winfo_x()+ui.guide.tabs.winfo_width()<ui.guide.winfo_width()-ui.guide.art_right-round(140*scale))
                    check(f'{scale}_{size}_all_tabs_are_icons',all(str(b.cget('compound'))=='none' and b.cget('image') for b in buttons))
                    shortcut = ui.guide.tools_button
                    check(f'{scale}_{size}_tools_fits_between_tabs_and_seal',
                          ui.guide.tabs.winfo_x()+ui.guide.tabs.winfo_width() <= shortcut.winfo_x()
                          and shortcut.winfo_x()+shortcut.winfo_width() < ui.guide.winfo_width()-ui.guide.art_right-round(159*scale))
                root.focus_force()
                ui.guide.buttons['home'].focus_set()
                ui.guide.buttons['home'].event_generate('<Left>')
                check(f'{scale}_keyboard_moves_between_icons',root.focus_get() is ui.guide.buttons['settings']
                      and ui.active_page == 'home')
                ui.guide.buttons['logs'].invoke();root.update()
                check(f'{scale}_records_selects_its_tab',ui.active_page=='logs' and ui.guide.buttons['logs'].cget('style')=='Selected.Nav.TButton')
                ui.guide.buttons['settings'].invoke();root.update()
                check(f'{scale}_settings_opens_inside_same_guide',ui.active_page=='settings' and ui.guide.winfo_ismapped()
                      and ui.settings_shell.master is ui.guide.content and ui.guide.selected_page=='settings')
                ui._leave_settings();root.update()
                check(f'{scale}_settings_returns_to_records',ui.active_page=='logs' and str(root.tk.call('focus','-lastfor',root))==str(ui.guide.buttons['settings']))
                ui.guide.tools_button.invoke()
                root.update()
                check(f'{scale}_shortcut_opens_tools_under_settings',ui._in_tools()
                      and ui.guide.selected_page == 'settings'
                      and ui.start_button.cget('text') == ui.tools_shelf.primary_action()[0])
                first = ui.tools_shelf.buttons['warp']
                first.focus_set()
                first.event_generate('<Right>')
                root.update()
                check(f'{scale}_tool_keyboard_changes_selection_and_keeps_focus',
                      ui._selected_tool == 'redemption' and root.focus_get() is ui.tools_shelf.buttons['redemption'])
                next_focus = str(root.tk.call('tk_focusNext', ui.tools_shelf.buttons['redemption']))
                check(f'{scale}_tool_tab_reaches_selected_content',
                      next_focus.startswith(str(ui.redemption_panel) + '.'))
                ui.guide.tools_button.invoke()
                root.update()
                ui._leave_settings()
                root.update()
                check(f'{scale}_shortcut_returns_to_origin',ui.active_page == 'logs'
                      and root.focus_get() is ui.guide.tools_button)
                for key in ('logs','settings'):
                    variants=[ImageTk.getimage(ui.guide.photos[key,selected,hover]).tobytes() for selected,hover in ((False,False),(False,True),(True,False),(True,True))]
                    check(f'{scale}_{key}_distinct_hover_and_selection',len(set(variants))==4)
                check(f'{scale}_navigation_never_saves',config.read_bytes()==saved and not ui.dirty)
                check(f'{scale}_no_callback_errors',not errors)
                if scale==1.:
                    sheet=Image.new('RGB',(5*104,3*72),'#242424')
                    for row,state in enumerate(((False,False),(True,False),(False,True))):
                        for column,key in enumerate(('home','tasks','universe','logs','settings')):
                            pic=ImageTk.getimage(ui.guide.photos[key,*state]).convert('RGB')
                            sheet.paste(pic,(column*104+26,row*72+10))
                    sheet.save(OUT/'icons.png')
            finally:
                ui.closing=True
                for token in root.tk.splitlist(root.tk.call('after','info')):
                    if str(root.tk.call('after','info',token)[0]).endswith('_drain'):root.after_cancel(token)
                root.destroy()
    (OUT/'result.json').write_text(json.dumps(dict(count=len(checks),checks=checks,game_started=False,os_input=False),ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(count=len(checks),game_started=False)))

if __name__=='__main__':main()
