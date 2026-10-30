"""Support editor: transparent disabled windows, local widget commands only."""
import copy
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch,Mock

from ux_smoke import ROOT,Settings,Window,module,pump
from ui_layout_smoke import check_layout
from autohsr.support_ui import show,values
from autohsr.plan_runner import PlanRunner

OUT=ROOT/'runs/support-ui'


def main():
    OUT.mkdir(parents=True,exist_ok=True);checks=[];errors=[];calls=[]
    def check(name,value):assert value,(name,errors);checks.append(name)
    original=tk.Toplevel.__init__
    def invisible(window,*args,**kwargs):
        original(window,*args,**kwargs);window.withdraw();window.attributes('-alpha',0);window.attributes('-disabled',True)
    with tempfile.TemporaryDirectory() as folder,patch.object(tk.Toplevel,'__init__',invisible):
        local=Path(folder)
        with patch.object(module,'ROOT',local):
            for scale in (1.,1.25,1.5,2.):
                config=local/f'{scale}.json';Settings(overlay_logs=False).save(config);original_config=config.read_bytes()
                root=tk.Tk();root.withdraw();root.attributes('-alpha',0);root.attributes('-disabled',True)
                root.tk.call('tk','scaling',scale*96/72);root.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
                ui=Window(root,config)
                try:
                    root.deiconify();root.update();ui._show_daily_tasks();root.update()
                    for size in ('default','minimum'):
                        if size=='minimum':root.geometry('%dx%d'%root.minsize());root.update();ui.responsive_layout.fit();root.update()
                        check_layout(root)
                        check(f'{scale}_{size}_support_entry_visible',ui.support_config_button.winfo_ismapped() and ui.support_toggle.winfo_ismapped())
                    ui.support_config_button.invoke();root.update();editor=ui.support_editor
                    check_layout(root);check_layout(editor.window)
                    check(f'{scale}_dialog_grab_and_chinese_roles',editor.window.grab_current() is editor.window and '黄泉' in editor.labels and len(editor.labels)==105)
                    check(f'{scale}_unselected_actions_are_disabled',all(editor.buttons[name].instate(('disabled',)) for name in ('更新选中','移除','上移','下移')))
                    editor.character.set('黄');root.update()
                    check(f'{scale}_role_search_filters_names',tuple(editor.role.cget('values'))==('黄泉',))
                    editor.character.set('黄泉');editor.friend.set('示例好友甲');editor.apply();root.update()
                    check(f'{scale}_one_apply_adds_unsubmitted_role',ui.support_dialog is None and values(ui)['support_preferences']==[dict(character='Acheron',friend='示例好友甲')])
                    check(f'{scale}_apply_keeps_task_switches_and_file',ui.use_support.get() and config.read_bytes()==original_config)
                    ui.use_support.set(False);show(ui);root.update();editor=ui.support_editor
                    editor.character.set('符玄');editor.friend.set('');editor.add();root.update()
                    check(f'{scale}_portrait_list_and_order',len(editor.photos)==2 and editor.table.item('1','values')[0]=='符玄')
                    check(f'{scale}_edge_move_actions_match_selection',not editor.buttons['上移'].instate(('disabled',)) and editor.buttons['下移'].instate(('disabled',)))
                    editor.buttons['上移'].invoke();root.update();check(f'{scale}_reorders_without_saving',editor.rows[0]['character']=='FuXuan' and config.read_bytes()==original_config)
                    editor.buttons['下移'].invoke();root.update();editor.buttons['更新选中'].invoke();root.update()
                    editor.character.set('黄泉');editor.friend.set('示例好友甲');editor.add();root.update()
                    check(f'{scale}_duplicate_rejected',len(editor.rows)==2 and '重复' in editor.error.get())
                    editor.selected();editor.pages.set('21');editor.apply();root.update()
                    check_layout(editor.window)
                    check(f'{scale}_page_limit_keeps_dialog',ui.support_dialog is editor.window and '1～20' in editor.error.get())
                    editor.pages.set('3');editor.fallback.set('另借其他好友');editor.selected();editor.apply();root.update()
                    check(f'{scale}_apply_keeps_support_off',not ui.use_support.get() and values(ui)['support_scroll_pages']==3 and values(ui)['support_fallback']=='friend')
                    draft=ui.support_rows.get();show(ui);root.update();editor=ui.support_editor
                    editor.character.set('不存在的角色');editor.apply();root.update()
                    check(f'{scale}_unknown_role_cannot_apply',ui.support_dialog is editor.window and ui.support_rows.get()==draft)
                    editor.close();root.update();check(f'{scale}_cancel_keeps_draft',ui.support_rows.get()==draft)
                    show(ui);root.update();editor=ui.support_editor
                    editor.friend.set('  示例好友乙  ');editor.add();root.update()
                    check(f'{scale}_friend_only_candidate_keeps_exact_nickname',editor.rows[-1]==dict(character='',friend='示例好友乙'))
                    editor.friend.set('名'*41);editor.add();root.update()
                    check(f'{scale}_long_nickname_is_rejected',len(editor.rows)==3 and '40' in editor.error.get())
                    while editor.rows:editor.table.selection_set('0');editor.remove();root.update()
                    editor.apply();root.update()
                    check(f'{scale}_empty_candidates_cannot_use_fallback',ui.support_dialog is editor.window and '未指定候选' in editor.error.get())
                    editor.close();root.update()
                    ui.use_support.set(True);frozen=ui._read_settings(operation='plan')
                    check(f'{scale}_daily_snapshot_uses_preferences',frozen.support_preferences==values(ui)['support_preferences'] and frozen.support_fallback=='friend')
                    ui.support_rows.set('invalid');ui.support_pages.set('bad')
                    check(f'{scale}_reward_only_ignores_unrelated_draft',ui._read_settings(operation='reward_only') is not None)
                    check(f'{scale}_check_ignores_unrelated_draft',ui._read_settings(operation='check') is not None)
                    ui._weekly_currency_recovery=dict(maximum=2,due_at='2026-10-26T04:00:00+08:00')
                    original_week=ui._read_settings(operation='plan',resume_weekly_currency=True)
                    check(f'{scale}_original_week_ignores_unrelated_draft',original_week is not None and not original_week.battle and original_week.support_preferences==ui.settings.support_preferences)
                    ui._weekly_currency_recovery=None
                    check(f'{scale}_support_error_returns_to_entry',ui._read_settings(operation='plan') is None and ui.input_error_field=='support_preferences' and ui.input_focus.pending[3]=='support_config_button')
                    show(ui);root.update();editor=ui.support_editor
                    check(f'{scale}_invalid_original_is_repairable',not editor.rows and '原候选格式无效' in editor.error.get())
                    editor.character.set('符玄');editor.pages.set('2');editor.apply();root.update()
                    check(f'{scale}_repair_requires_apply',ui.support_dialog is None and values(ui)['support_preferences']==[dict(character='FuXuan',friend='')])
                    parents=[]
                    def child_factory(settings,emit,**options):
                        calls.append(copy.deepcopy(settings));directory=local/'runs'/f'child-{len(calls)}';directory.mkdir(parents=True)
                        report=dict(operation='daily',status='success',report_saved=True,run_dir=str(directory),daily_verified=True,
                            results=[],stamina_spent=0,stamina_pending=0,stamina_limit=settings.stamina_limit,
                            support_selections=[dict(state='borrowed',selected=dict(character='FuXuan',friend='示例好友'))])
                        (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False),'utf-8')
                        runner=Mock();runner.run.return_value=report;return runner
                    def build(settings,emit,**options):
                        runner=PlanRunner(settings,emit,runner_factory=child_factory,**options);parents.append(runner);return runner
                    ui._restore=Mock();root.iconify=Mock()
                    with patch('autohsr.plan_runner.PlanRunner',side_effect=build),patch('autohsr.app.Runner',side_effect=AssertionError('No game runner allowed')):
                        ui._start(run_plan=True);pump(root,lambda:not ui.busy,timeout=10)
                    check(f'{scale}_formal_parent_and_daily_use_same_preferences',parents[-1].settings.support_preferences==calls[-1].support_preferences==values(ui)['support_preferences'] and calls[-1].support_fallback=='friend')
                    check(f'{scale}_run_does_not_save_preferences',config.read_bytes()==original_config)
                    check(f'{scale}_original_daily_support_is_in_parent_report',json.loads(ui.report_text.get('1.0','end'))['support_selections'][0]['selected']['character']=='FuXuan')
                    ui.use_support.set(False)
                    ui._save_settings();root.update();saved=Settings.load(config)
                    check(f'{scale}_explicit_save_persists',saved.support_preferences==[dict(character='FuXuan',friend='')] and saved.support_scroll_pages==2 and saved.support_fallback=='friend' and not saved.use_support and not ui.dirty)
                    ui.busy=True;show(ui);check(f'{scale}_busy_refuses_editor',ui.support_dialog is None);ui.busy=False
                    check(f'{scale}_no_callback_errors',not errors)
                finally:
                    ui.closing=True
                    if getattr(ui,'support_dialog',None) is not None:ui.support_dialog.destroy()
                    for token in root.tk.splitlist(root.tk.call('after','info')):
                        if str(root.tk.call('after','info',token)[0]).endswith('_drain'):root.after_cancel(token)
                    root.destroy()
                reopened=tk.Tk();reopened.withdraw();reopened.attributes('-alpha',0);reopened.attributes('-disabled',True)
                reopened.tk.call('tk','scaling',scale*96/72);next_ui=Window(reopened,config)
                reopened.update()
                try:
                    check(f'{scale}_reopen_preserves_candidates_and_off_switch',values(next_ui)['support_preferences']==[dict(character='FuXuan',friend='')] and next_ui.support_summary.get()=='符玄' and not next_ui.use_support.get())
                finally:
                    next_ui.closing=True
                    for token in reopened.tk.splitlist(reopened.tk.call('after','info')):
                        if str(reopened.tk.call('after','info',token)[0]).endswith('_drain'):reopened.after_cancel(token)
                    reopened.destroy()
    (OUT/'result.json').write_text(json.dumps(dict(count=len(checks),checks=checks,game_started=False,os_input=False,
        transparent_disabled_windows=True,native_pixels_verified=False),ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(checks=len(checks),game_started=False,os_input=False)))


if __name__=='__main__':main()
