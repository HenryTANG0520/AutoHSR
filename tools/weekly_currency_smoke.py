"""Click the plan UI through real local weekly composition with simulated IO."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import uuid
from unittest.mock import Mock, patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module, pump
from ui_layout_smoke import check_layout
from autohsr.plan_runner import PlanRunner as ActualPlanRunner
from autohsr.tests.test_currency_wars_weekly_plan import Factory, runtime, settings, points
from autohsr.currency_wars_loop_store import _write

OUT = ROOT/'runs/weekly-currency-ui'


class UIFactory(Factory):
    """A completed synthetic daily receipt, including its real resource owner."""
    def __call__(self,config,emit,**options):
        if options['operation']!='daily':
            return super().__call__(config,emit,**options)
        self.calls.append('daily')
        path=self.root/'runs'/('daily_'+uuid.uuid4().hex[:8]);path.mkdir(parents=True)
        results=[dict(task=name,status='ok',detail='合成日常回执，非实机验证')
                 for name in ('assignments','battle','daily','mail','battlepass') if getattr(config,name)]
        report=dict(operation='daily',status='success',report_saved=True,run_dir=str(path),daily_verified=True,
                    stamina_spent=120,stamina_limit=120,stamina_pending=0,battle_completed=12,battle_requested=12,results=results)
        _write(path/'report.json',report)
        _write(self.root/'runs/battle-session.json',dict(version=1,status='success',spent=120,pending=0,limit=120,run_dir=str(path)))
        child=Mock();child.run.return_value=report
        return child


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, callbacks, outcomes = [], [], []
    def check(name, value):
        assert value, (name, callbacks)
        checks.append(name)

    for scenario in ('fresh', 'exhausted', 'resume', 'audit'):
        with tempfile.TemporaryDirectory() as folder:
            root_path=Path(folder)
            original_daily = None
            if scenario in ('resume','audit'):
                seed=UIFactory(root_path,[18000,18000] if scenario=='audit' else [0,0,18000]);owner=None
                seed.reward_available=False if scenario=='audit' else True
                def emit(event):
                    if scenario=='resume' and event['type']=='currency_loop_progress':owner.stop()
                owner=ActualPlanRunner(settings(stamina_limit=120,challenge_count=12),emit,root=root_path/'runs',runner_factory=seed,now=points.NOW)
                with runtime(root_path):first=owner.run()
                assert first.status==('success' if scenario=='audit' else 'stopped'),first.error
                if scenario=='audit':
                    from autohsr.currency_wars_loop_store import LoopStore
                    store=LoopStore(root_path/'runs');store.load()
                    receipt=store.path.parent/'weekly.receipt.json'
                    receipt.rename(receipt.with_suffix('.original.json'))
                child=next(v for v in first.weekly_plan['children'] if v['operation']=='daily')
                original_daily=Path(child['run_dir'])/'report.json'
                original_hash=hashlib.sha256(original_daily.read_bytes()).hexdigest()
                failed_path=Path(first.run_dir)/'report.json'
                failed_hash=hashlib.sha256(failed_path.read_bytes()).hexdigest()
                config_settings=Settings(overlay_logs=False)
                factory=UIFactory(root_path,[] if scenario=='audit' else [18000]);factory.reward_available=False
            else:
                config_settings=settings(weekly_runs=1 if scenario=='exhausted' else 2,stamina_limit=120,challenge_count=12)
                factory=UIFactory(root_path,[0,0,4500 if scenario=='exhausted' else 18000])
                if scenario=='exhausted':factory.reward_score=4500
            config=root_path/'config.json';config_settings.save(config)
            saved=config.read_bytes()
            parents, snapshots = [], []
            gate, entered = threading.Event(), threading.Event()
            def child_factory(config,emit,**options):
                child=factory(config,emit,**options)
                if scenario=='fresh' and options['operation']=='currency_wars_standard':
                    run=child.run
                    def wait_then_run():
                        entered.set()
                        if not gate.wait(20):raise AssertionError('Synthetic stage was not released')
                        return run()
                    child.run=wait_then_run
                return child
            def build_plan(config,emit,**options):
                snapshots.append((config,options.copy()))
                parent=ActualPlanRunner(config,emit,runner_factory=child_factory,now=points.NOW,**options)
                parents.append(parent)
                return parent
            with runtime(root_path), patch.object(module,'ROOT',root_path), \
                    patch('autohsr.plan_runner.PlanRunner',new=build_plan), \
                    patch.object(module.messagebox,'showerror',side_effect=lambda *a,**k:callbacks.append(str(a))), \
                    patch.object(module.messagebox,'askyesno',side_effect=AssertionError('No new daily budget is allowed')):
                root=tk.Tk()
                root.report_callback_exception=lambda kind,value,trace:callbacks.append(str(value))
                ui=Window(root,config)
                minimized=[]
                root.iconify=lambda:minimized.append(True)
                try:
                    root.update()
                    check(scenario+'_primary_is_contextual',ui.start_button.cget('text')==('补存周常结果' if scenario=='audit' else '继续周常' if scenario=='resume' else '开始计划'))
                    if scenario in ('resume','audit'):
                        check('resume_header_uses_original_daily_and_limit','沿用原报告' in ui.daily_caption.get() and '上限 2 局' in ui.weekly_status.get())
                        ImageGrab.grab(window=root.winfo_id()).save(OUT/(scenario+'-ready.png'))
                        ui.weekly_enabled.set(False)
                        ui.weekly_mode.set('差分宇宙')
                        ui.weekly_runs.set('10');ui.weekly_time.set('bad')
                        ui.du_team.set('');ui.challenge_count.set('bad')
                        root.update()
                        check(scenario+'_invalid_unrelated_draft_keeps_original_continuation',ui.start_button.cget('text')==('补存周常结果' if scenario=='audit' else '继续周常') and '上限 2 局' in ui.weekly_status.get())
                    else:
                        ui.weekly_button.invoke();root.update()
                        check(scenario+'_currency_limit_visible_without_du_team',ui.weekly_runs_combo.winfo_ismapped() and
                              ui.weekly_runs_row.caption.cget('text')=='对局上限' and not ui.weekly_team_entry.winfo_ismapped())
                        ui._leave_settings();root.update()
                    ui.start_button.invoke()
                    if scenario=='fresh':
                        pump(root,entered.is_set,timeout=20)
                        pump(root,lambda:ui.plan_phase=='weekly' and ui.training_result.get()=='verified',timeout=4)
                        check('daily_result_is_visible_while_weekly_is_running',ui.busy and ui.stamina.get()=='120')
                        check('weekly_progress_uses_the_correct_mode','货币战争' in ui.current_task.get() and '演算' not in ui.current_task.get())
                        check('settings_and_second_start_stay_locked',ui.weekly_runs_combo.instate(('disabled',)) and ui.start_button.instate(('disabled',)))
                        ui._pause();pump(root,lambda:ui.paused)
                        ui._pause();pump(root,lambda:not ui.paused)
                        check('weekly_pause_and_continue_keep_the_parent',len(parents)==1 and ui.running)
                        gate.set()
                    pump(root,lambda:not ui.busy,timeout=30)
                    body=parents[-1].report.to_dict()
                    check(scenario+'_parent_report_saved',body['report_saved'] is True)
                    check(scenario+'_config_is_not_written',config.read_bytes()==saved)
                    check(scenario+'_one_click_one_parent',len(parents)==1)
                    if scenario in ('resume','audit'):
                        check('resume_does_not_run_daily_or_a_second_standard_match','daily' not in factory.calls and 'currency_wars_standard' not in factory.calls)
                        chosen,options=snapshots[0]
                        check('resume_uses_explicit_flag_and_original_limit',options.get('resume_weekly_currency') is True and not options['new_battle_run'] and
                              chosen.weekly_mode=='currency_wars' and chosen.weekly_enabled and chosen.weekly_runs==2 and not chosen.battle and not chosen.daily)
                        check('old_daily_and_failure_reports_are_immutable',hashlib.sha256(original_daily.read_bytes()).hexdigest()==original_hash and
                              hashlib.sha256(failed_path.read_bytes()).hexdigest()==failed_hash)
                        check('old_cost_is_explicitly_original','原日常已确认 120 开拓力' in ui.summary.get() and '原日常' in ui.table.item('daily','values')[1])
                        check('old_daily_does_not_light_current_training_or_current_spend',ui.training_result.get()=='unknown' and ui.stamina.get()=='—' and ui.confirmed_stamina==0)
                        check('finished_continuation_restores_primary',ui.start_button.cget('text')=='开始计划')
                        if scenario=='audit':
                            check('audit_has_no_children_or_minimization',factory.calls==[] and not minimized)
                            check('audit_result_uses_original_receipt_context','原周常结果已补存' in ui.summary.get() and '原周常回执已核对' in ui.summary.get())
                    else:
                        expected=['daily','currency_wars_points','currency_wars_points','currency_wars_standard','currency_wars_points','currency_wars_rewards']
                        check(scenario+'_formal_stage_order',factory.calls==expected)
                    if scenario=='exhausted':
                        check('exhaustion_is_partial_and_uses_frozen_cap',body['status']=='partial' and '原上限已用完' in ui.summary.get() and '上限 1 局' in ui.summary.get())
                        check('daily_success_survives_exhaustion',body['daily_verified'] is True and ui.training_result.get()=='verified' and ui.stamina.get()=='120')
                    elif scenario!='audit':
                        check(scenario+'_only_accepted_receipt_is_complete',body['status']=='success' and body['weekly_plan']['score_rewards_verified'] is True and '积分及奖励已核实' in ui.summary.get())
                    check_layout(root)
                    ImageGrab.grab(window=root.winfo_id()).save(OUT/(scenario+'-result.png'))
                    if scenario=='resume':
                        for size in ('zoomed','normal'):
                            root.state(size);root.update();ui.responsive_layout.fit();root.update()
                            check(size+'_resumed_result_survives_layout','原日常已确认 120 开拓力' in ui.summary.get() and ui.training_result.get()=='unknown')
                    outcomes.append(dict(scenario=scenario,calls=factory.calls,status=body['status'],weekly_status=body['weekly_plan']['status'],
                                         completed=body['weekly_plan'].get('completed_runs'),maximum=body['weekly_plan'].get('maximum_runs')))
                finally:
                    gate.set()
                    if ui.worker is not None and ui.worker.is_alive():
                        if ui.runner:ui.runner.stop()
                        ui.worker.join(timeout=10)
                    ui.closing=True
                    for token in root.tk.splitlist(root.tk.call('after','info')):
                        if str(root.tk.call('after','info',token)[0]).endswith('_drain'):root.after_cancel(token)
                    root.destroy()
    check('no_callback_errors',not callbacks)
    data=dict(count=len(checks),checks=checks,outcomes=outcomes,game_started=False,simulated_io=True,config_unchanged=True)
    (OUT/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(checks=len(checks),game_started=False,outcomes=outcomes),ensure_ascii=False))


if __name__=='__main__':
    main()
