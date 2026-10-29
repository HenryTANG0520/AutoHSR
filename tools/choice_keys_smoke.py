"""Exercise expanded choice navigation without changing text editing or starting a backend."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import types
from unittest.mock import patch

from ux_smoke import ROOT, Settings, Window, module
from ui_layout_smoke import check_layout
from autohsr.dungeon_ui import show_manual

OUT = ROOT/'runs/choice-keys-ui'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    def check(name, condition):
        assert condition, (name, errors)
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError('Choice navigation must not access a game backend')
    fake = types.ModuleType('autohsr.app')
    fake.Runner = fake.launch_game = fake.inspect_game = reject

    def open_choice(root, control):
        control.focus_force()
        control.event_generate('<KeyPress-Down>')
        root.update()
        pop = str(root.tk.call('ttk::combobox::PopdownWindow', control))
        assert root.tk.call('winfo', 'ismapped', pop)
        return pop, pop+'.f.l'

    def key(root, listing, name):
        root.tk.call('event', 'generate', listing, '<KeyPress-'+name+'>')
        root.update()

    def reset(root, control, index):
        control.current(index)
        control.event_generate('<<ComboboxSelected>>')
        root.update()

    with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)), \
            patch.dict(sys.modules, {'autohsr.app':fake}):
        config = Path(folder)/'config.json'
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1.,1.25,1.5,2.):
            prefix = str(scale)+'_'
            root = tk.Tk()
            root.tk.call('tk','scaling',scale*96/72)
            root.report_callback_exception = lambda kind,value,trace: errors.append(str(value))
            ui = Window(root, config)
            try:
                root.update()
                ui._show_weekly_plan()
                root.update()
                for name in ('weekly_enabled_combo','weekly_day_combo','weekly_runs_combo'):
                    control = getattr(ui,name)
                    initial = control.current()
                    count = len(control.cget('values'))
                    selected = []
                    token = control.bind('<<ComboboxSelected>>', lambda event: selected.append(True), add='+')
                    for action, expected in (('End',count-1),('Home',0)):
                        reset(root,control,initial)
                        selected.clear()
                        pop, listing = open_choice(root,control)
                        key(root,listing,action)
                        active = tuple(map(int,root.tk.splitlist(root.tk.call(listing,'curselection'))))
                        check(prefix+name+action+'_highlights_without_committing', active==(expected,) and
                              control.current()==initial and not selected and root.tk.call('winfo','ismapped',pop))
                        key(root,listing,'Return')
                        check(prefix+name+action+'_enter_commits_once', control.current()==expected and len(selected)==1 and
                              not root.tk.call('winfo','ismapped',pop))
                    control.unbind('<<ComboboxSelected>>',token)
                    reset(root,control,initial)

                control = ui.weekly_day_combo
                initial = control.current()
                pop, listing = open_choice(root,control)
                key(root,listing,'End')
                key(root,listing,'Escape')
                check(prefix+'escape_cancels_the_highlight_before_leaving_settings', control.current()==initial and
                      not root.tk.call('winfo','ismapped',pop) and ui.active_page=='settings')
                root.event_generate('<KeyPress-Escape>')
                root.update()
                check(prefix+'second_escape_returns_to_the_original_plan_entry', ui.active_page=='home' and ui.action_page=='home')
                ui._show_weekly_plan()
                root.update()

                long = ttk.Combobox(ui.settings_sections['weekly'], values=tuple('选项'+str(n) for n in range(30)),
                                    state='readonly', height=5)
                long.grid(row=8,column=0,sticky='ew')
                long.current(0)
                root.update()
                pop, listing = open_choice(root,long)
                key(root,listing,'End')
                check(prefix+'long_list_scrolls_to_the_last_row_without_committing',
                      int(root.tk.call(listing,'index','active'))==29 and float(root.tk.call(listing,'yview')[1])==1.0 and long.current()==0)
                key(root,listing,'Return')
                check(prefix+'long_list_enter_uses_the_visible_last_row', long.current()==29)
                pop, listing = open_choice(root,long)
                key(root,listing,'Home')
                check(prefix+'long_list_home_restores_the_first_visible_row',
                      int(root.tk.call(listing,'index','active'))==0 and float(root.tk.call(listing,'yview')[0])==0.0 and long.current()==29)
                key(root,listing,'Escape')
                long.destroy()

                for action, start, expected in (('Control-End',0,6),('Control-Home',6,0)):
                    control = ui.weekly_day_combo
                    reset(root,control,start)
                    pop, listing = open_choice(root,control)
                    root.tk.call('event','generate',listing,'<'+action+'>')
                    root.update()
                    pending = control.current()==start
                    key(root,listing,'Return')
                    check(prefix+action+'_keeps_the_existing_shortcut', pending and control.current()==expected)
                reset(root,ui.weekly_day_combo,0)

                plain = tk.Listbox(ui.settings_sections['weekly'],height=2,exportselection=False)
                plain.insert('end','第一项'*20,'第二项'*20,'第三项'*20)
                plain.grid(row=8,column=0,sticky='ew')
                plain.selection_set(1)
                plain.activate(1)
                root.update()
                plain.focus_force()
                for action in ('Home','End'):
                    plain.event_generate('<KeyPress-'+action+'>')
                    root.update()
                check(prefix+'ordinary_listbox_keeps_its_original_selection', plain.curselection()==(1,))
                plain.destroy()

                empty = ttk.Combobox(ui.settings_sections['weekly'],values=(),state='readonly')
                empty.set('保留文字')
                empty.grid(row=8,column=0,sticky='ew')
                root.update()
                pop, listing = open_choice(root,empty)
                key(root,listing,'End')
                key(root,listing,'Home')
                key(root,listing,'Return')
                check(prefix+'empty_choice_does_not_replace_an_existing_value', empty.get()=='保留文字')
                empty.destroy()

                for size in ('zoomed','normal','zoomed','normal'):
                    root.state(size)
                    root.update()
                    ui.responsive_layout.fit()
                    root.update()
                    control = ui.weekly_day_combo
                    initial = control.current()
                    selected = []
                    token = control.bind('<<ComboboxSelected>>',lambda event:selected.append(True),add='+')
                    pop, listing = open_choice(root,control)
                    key(root,listing,'End')
                    key(root,listing,'Return')
                    check(prefix+size+str(len(checks))+'_new_and_cached_layouts_commit_once',
                          control.current()==6 and len(selected)==1)
                    control.unbind('<<ComboboxSelected>>',token)
                    reset(root,control,initial)

                ui._show_page('settings')
                ui.settings_tabs.select(ui.settings_sections['game'])
                root.update()
                entry = ui.game_path_entry
                value = entry.get()
                entry.focus_force()
                entry.selection_clear()
                entry.icursor(len(value)//2)
                entry.event_generate('<KeyPress-Home>')
                root.update()
                check(prefix+'text_entry_home_keeps_text_and_moves_the_caret', entry.get()==value and entry.index('insert')==0)
                entry.event_generate('<KeyPress-End>')
                root.update()
                check(prefix+'text_entry_end_keeps_text_and_moves_the_caret', entry.get()==value and entry.index('insert')==len(value))
                ui._show_page('tasks')
                show_manual(ui)
                root.update()
                entry = ui.dungeon_name_combo
                value = entry.get()
                entry.focus_force()
                entry.selection_clear()
                entry.icursor(len(value)//2)
                entry.event_generate('<KeyPress-Home>')
                root.update()
                check(prefix+'closed_editable_combo_home_only_moves_the_caret', entry.get()==value and entry.index('insert')==0)
                entry.event_generate('<KeyPress-End>')
                root.update()
                check(prefix+'closed_editable_combo_end_only_moves_the_caret', entry.get()==value and entry.index('insert')==len(value))
                ui._show_weekly_plan()
                root.update()
                ui._set_busy(True,True)
                control = ui.weekly_day_combo
                before = control.get()
                control.event_generate('<KeyPress-Down>')
                root.update()
                pop = str(root.tk.call('ttk::combobox::PopdownWindow',control))
                check(prefix+'disabled_choice_does_not_open_or_edit', control.get()==before and
                      not root.tk.call('winfo','ismapped',pop))
                ui._set_busy(False)
                check(prefix+'no_autosave_or_backend', config.read_bytes()==original and ui.runner is None and ui.worker is None)
                check_layout(root)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call('after','info')):
                    if str(root.tk.call('after','info',token)[0]).endswith('_drain'):
                        root.after_cancel(token)
                root.destroy()
    check('no_callback_errors', not errors)
    result = dict(count=len(checks),checks=checks,game_started=False,config_unchanged=True)
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
