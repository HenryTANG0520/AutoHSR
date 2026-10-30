"""Withdrawn Tk controls, real PlanRunner, simulated children; no OS input."""
import copy
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import Mock,patch

from ux_smoke import ROOT,Settings,Window,module,pump
from autohsr.plan_runner import PlanRunner as ActualPlanRunner
from autohsr.power_plan_ui import rows

OUT=ROOT/'runs/power-plan-ui'
ITEM=dict(category='calyx_golden',target='回忆之蕾',location='城郊雪原',count=8)


def main():
    OUT.mkdir(parents=True,exist_ok=True);checks=[];errors=[];calls=[];parents=[]
    def check(name,value):assert value,(name,errors);checks.append(name)
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder);config=path/'config.json'
        Settings(overlay_logs=False,power_plan=[ITEM],power_plan_fill=False).save(config);saved=config.read_bytes()
        def child_factory(settings,emit,**options):
            calls.append((copy.deepcopy(settings),options.copy()))
            directory=path/'runs'/('daily_'+str(len(calls)));directory.mkdir(parents=True)
            report=dict(operation='daily',status='success',report_saved=True,run_dir=str(directory),daily_verified=True,
                stamina_spent=40,stamina_pending=0,stamina_limit=settings.stamina_limit,battle_completed=4,battle_requested=8,
                results=[dict(task=key,status='ok',detail='模拟回执') for key in ('assignments','battle','daily')])
            if options.get('use_power_plan'):
                plan=copy.deepcopy(settings.power_plan)
                report['power_plan']=dict(items=plan,before=[0]*len(plan),done=[4]+[0]*(len(plan)-1),goal_complete=False,run_status='complete')
                emit(dict(type='power_plan_progress',stage='confirmed',rows=[dict(ITEM,before=0,done=4,remaining=4)],
                          battle_completed=4,stamina_spent=40,stamina_pending=0,active_row=0))
            (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False),'utf-8')
            child=Mock();child.run.return_value=report;return child
        def build(settings,emit,**options):
            result=ActualPlanRunner(settings,emit,runner_factory=child_factory,**options);parents.append(result);return result
        with patch.object(module,'ROOT',path),patch('autohsr.plan_runner.PlanRunner',side_effect=build), \
             patch('autohsr.app.Runner',side_effect=AssertionError('No direct game runner allowed')):
            root=tk.Tk();root.withdraw();root.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
            root.deiconify=Mock();root.iconify=Mock();ui=Window(root,config);ui._restore=Mock()
            try:
                root.update_idletasks()
                check('stored_items_do_not_implicitly_enable_plan',ui.power_mode.get()=='单副本' and '更换副本'==ui.table.action_label('battle'))
                ui._start(run_plan=True);pump(root,lambda:not ui.busy,timeout=10)
                check('single_mode_reaches_formal_parent_without_power_flag',not calls[-1][1].get('use_power_plan',False) and not parents[-1].use_power_plan)
                check('running_does_not_save',config.read_bytes()==saved)
                ui.power_mode.set('体力计划');ui.challenge_count.set('invalid');root.update_idletasks()
                chosen=ui._read_settings(operation='plan')
                check('unused_single_count_does_not_block_plan_without_fill',chosen is not None and chosen.power_plan==[ITEM])
                check('home_previews_targets_and_shared_budget','体力计划 1 项' in ui.daily_caption.get() and '共用 240' in ui.daily_caption.get())
                check('battle_card_edits_plan',ui.table.action_label('battle')=='调整计划' and ui.table.resource_metrics('battle')[0]=='1 项')
                ui.settings_shell.choose('power');root.update_idletasks()
                check('power_settings_keeps_start_plan',ui.action_page=='home' and ui.start_button.cget('text')=='开始计划')
                check('editor_shows_original_targets',ui.power_plan_list.item('0','values')[-1]=='8')
                ui.power_editor.commit(dict(ITEM,target='丰饶之蕾',location='边缘通路',count=2),None)
                ui.power_plan_list.selection_set('1');ui.power_editor.buttons[3].invoke()
                check('up_button_moves_selected_item',rows(ui)[0]['target']=='丰饶之蕾')
                ui.power_editor.buttons[4].invoke()
                check('down_button_preserves_counts',rows(ui)[1]['count']==2 and rows(ui)[0]['count']==8)
                ui.power_editor.buttons[2].invoke()
                check('remove_does_not_mutate_saved_config',rows(ui)==[ITEM] and config.read_bytes()==saved)
                ui._start(run_plan=True);pump(root,lambda:not ui.busy,timeout=10)
                check('explicit_mode_reaches_formal_parent_and_daily',parents[-1].use_power_plan and calls[-1][1].get('use_power_plan') is True)
                check('parent_copies_power_report',parents[-1].report.power_plan['done']==[4])
                check('limited_goal_is_not_all_goals_complete','本次安排已结束' in ui.summary.get() or ui.status.get()=='● 本次安排已结束')
                check('result_detail_has_per_item_remaining','本目标剩余 4 次' in ui.table.item('battle','values')[2])
                check('confirmed_progress_does_not_decrement_preferences',rows(ui)==[ITEM] and ui.power_plan_list.item('0','values')[-1]=='8')
                check('both_runs_leave_original_configuration',config.read_bytes()==saved)
                ui.challenge_count.set('24');ui._read_settings(save=True,operation='save')
                written=Settings.load(config)
                check('explicit_save_persists_mode_and_original_counts',written.power_plan_enabled and written.power_plan==[ITEM] and not written.power_plan_fill)
                ui.power_mode.set('单副本');ui._start(run_plan=True);pump(root,lambda:not ui.busy,timeout=10)
                check('changing_back_to_single_ignores_saved_enabled_mode',not calls[-1][1].get('use_power_plan',False))
                ui.power_mode.set('体力计划');ui.power_rows.set('[]');root.update_idletasks()
                check('empty_plan_is_rejected_and_located',ui._read_settings(operation='plan') is None and ui.input_error_field=='power_plan' and ui.settings_tabs.select()==str(ui.settings_sections['power']))
                ui.echo_enabled.set(True)
                check('echo_only_plan_is_valid',ui._read_settings(operation='plan') is not None)
                ui.echo_enabled.set(False);ui.power_rows.set(json.dumps([ITEM]));ui.stamina_limit.set('bad')
                check('budget_error_uses_plan_budget_control',ui._read_settings(operation='plan') is None and ui.input_focus.pending[3]=='power_budget_entry')
                ui.power_rows.set('invalid');ui.challenge_count.set('bad');ui.echo_target.set('')
                check('reward_only_ignores_unrelated_plan_draft',ui._read_settings(operation='reward_only') is not None)
                previous=len(calls);captured=[]
                def original_week(settings,emit,**options):
                    captured.append((settings,options))
                    child=Mock();child.run.return_value=dict(operation='plan',status='stopped',report_saved=True,
                        results=[],weekly_plan=dict(status='needs_review',mode='currency_wars',daily_tasks=[]))
                    return child
                with patch.object(ui,'_refresh_recovery'),patch('autohsr.plan_runner.PlanRunner',side_effect=original_week):
                    ui._weekly_currency_recovery=dict(resume=True,daily_reused=True,maximum=2,
                        due_at='2026-10-26T04:00:00+08:00',caption='原周常 · 上限 2 局')
                    ui._start(run_plan=True,resume_weekly_currency=True);pump(root,lambda:not ui.busy,timeout=10)
                frozen,options=captured[0]
                check('original_week_resume_never_enables_new_power_plan',options.get('resume_weekly_currency') is True and not options.get('use_power_plan',False) and not frozen.battle and len(calls)==previous)
                ui._weekly_currency_recovery=None;ui._has_run=False;ui._daily_result_signature=None
                ui.stamina_limit.set('240');ui.challenge_count.set('24')
                ui.power_rows.set(json.dumps([dict(ITEM,category='planar',target='浴火钢心',location='永恒圣城')]))
                check('planar_preview_keeps_separate_existing_immersifier_hint','已有沉浸器另计' in ui.table.resource_metrics('battle')[1] and '已有沉浸器另计' in ui.power_editor.budget_note.get())
                ui.power_fill.set(True)
                check('fallback_preview_is_a_bounded_request','最多24次' in ui.power_editor.caption.get())
                check('no_callback_errors',not errors)
            finally:
                ui.closing=True
                if ui.worker and ui.worker.is_alive():ui.runner.stop();ui.worker.join(5)
                for token in root.tk.splitlist(root.tk.call('after','info')):
                    if str(root.tk.call('after','info',token)[0]).endswith('_drain'):root.after_cancel(token)
                root.destroy()
    result=dict(count=len(checks),checks=checks,game_started=False,os_input=False,withdrawn_tk=True,native_visual_verified=False)
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(checks=len(checks),game_started=False,os_input=False)))


if __name__=='__main__':main()
