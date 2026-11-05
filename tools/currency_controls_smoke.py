"""Currency desktop acceptance with temporary data and synthetic backends only."""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.gui_layout import check_layout

importlib.import_module('autohsr.windows')  # DPI setup only; no window/process probe.
from autohsr.config import Settings
from autohsr import gui
from PIL import ImageGrab

OUT = ROOT / 'runs' / 'currency-controls-smoke'
CHECKS = []
WEEK = '2026-11-02'


def check(name, value):
    assert value, name
    CHECKS.append(name)


def pump(root, predicate=lambda: True, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():return
        time.sleep(.02)
    raise AssertionError('currency GUI condition timed out')


def layout(root):
    check_layout(root, work_area=importlib.import_module('autohsr.desktop_dialogs')._work_area)


def points_observation(current=18000):
    complete=current==18000
    return dict(game_week=WEEK,current=current,limit=18000,score_complete=complete,period_verified=True,
                weekly_target_verified=complete,observed_at='2026-11-05T12:00:00+08:00')


def loop_summary(requested=3,completed=0,defeats=0,*,state='active',until_points=False):
    data=dict(mode='standard_loop',loop_id='1'*32,requested_runs=requested,completed=completed,
        settled_games=completed,victories=completed-defeats,defeats=defeats,status=state,active=None,
        development_only=True,acceptance_runs=0,until_points=until_points,rewards_verified=False,
        continue_after_defeat=False,strategy='default',remembrance_name='',equipment_fast_mode=False)
    if until_points:
        observation=points_observation(18000 if state=='complete' else 9000)
        data['points_goal']=dict(week=WEEK,observation=observation,latest=observation,checked_completed=completed)
    return data


class FakeBackend:
    instances=[]
    scenario='normal'
    operation=''

    def __init__(self,settings,emit,**kwargs):
        self.settings,self.emit,self.kwargs=settings,emit,kwargs
        self.operation=kwargs.get('operation',self.operation)
        self.report=types.SimpleNamespace(operation=self.operation)
        self.release=threading.Event();self.stopped=False;self.paused=False
        self._window=None;self._control_hwnd=None
        self.scenario=type(self).scenario
        self.instances.append(self)

    @property
    def stop_requested(self):return self.stopped

    def stop(self):self.stopped=True;self.release.set()

    def toggle_pause(self):
        self.paused=not self.paused
        self.emit(dict(type='paused',paused=self.paused))
        return self.paused


class FakeNativeRunner(FakeBackend):
    def run(self):
        self.emit(dict(type='task',task='currency_wars',status='running',detail='离线假后端，无游戏输入'))
        self.release.wait(6)
        if self.operation=='currency_wars_points':
            data=dict(schema=1,mode='weekly_points',points_verified=True,current=18000,limit=18000,
                score_complete=True,period=dict(verified=True),weekly_target_verified=True,
                rewards_verified=False,completion_verified=False,match_started=False,game_week=WEEK)
        elif self.operation=='currency_wars_rewards':
            blocked=self.scenario=='blocked' or self.stopped
            intents=['open_points_rewards','claim_weekly_rewards'] if blocked else [
                'open_points_rewards','claim_weekly_rewards','dismiss_weekly_rewards','return_weekly_lobby']
            expected = dict(open_points_rewards='points_rewards', claim_weekly_rewards='reward_overlay',
                            dismiss_weekly_rewards='points_rewards', return_weekly_lobby='lobby')
            actions=[dict(id=index,intent=intent,status='verified',result='fuel_ticket_limit' if blocked and index==1 else
                expected[intent]) for index,intent in enumerate(intents)]
            data=dict(schema=1,mode='weekly_rewards',status='active' if blocked else 'complete',
                phase='blocked' if blocked else 'returned',current=18000,game_week=WEEK,
                rewards_verified=not blocked,weekly_rewards_verified=not blocked,
                claimed_now=not blocked,actions=actions,completion_verified=False,match_started=False)
        else:
            data=dict(mode='standard_development',start_verified=True,rank=8,wealth=40,
                action_status='needs_observation',completion_verified=False)
        status='stopped' if self.stopped else 'partial' if self.operation=='currency_wars_standard' or self.scenario=='blocked' else 'success'
        report=dict(operation=self.operation,status=status,report_saved=True,currency_wars=data,
            daily_verified=False,stamina_spent=0,results=[])
        self.emit(dict(type='finished',report=report))
        return report


class FakeLoopRunner(FakeBackend):
    operation='currency_wars_loop'

    def terminal_report(self):
        requested=self.kwargs.get('runs',2)
        until=self.kwargs.get('until_points',True if self.kwargs.get('resume') else False)
        if self.stopped:
            completed,defeats,state,status=0,0,'cancelled','stopped'
        elif self.scenario=='defeat':
            completed,defeats,state,status=1,1,'defeated','partial'
        else:
            completed=requested if not until else min(2,requested)
            defeats,state,status=0,'complete','success'
        return dict(operation=self.operation,status=status,report_saved=True,results=[],
            daily_verified=False,stamina_spent=0,
            currency_wars=loop_summary(requested,completed,defeats,state=state,until_points=until))

    def run(self):
        self.emit(dict(type='currency_loop_progress',data=loop_summary(self.kwargs.get('runs',2),
            until_points=self.kwargs.get('until_points',True if self.kwargs.get('resume') else False))))
        self.release.wait(6)
        report=self.terminal_report()
        self.emit(dict(type='finished',report=report))
        return report


class LateLoopRunner(FakeLoopRunner):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.early=threading.Event();self.tail=threading.Event()

    def run(self):
        self.emit(dict(type='finished',report=self.terminal_report()))
        self.early.set()
        if not self.tail.wait(4):raise AssertionError('late currency worker release timed out')
        raise RuntimeError('模拟货币循环完成通知后的异常')


def main():
    from autohsr.desktop_modes import show_mode_view
    OUT.mkdir(parents=True,exist_ok=True)
    backend=types.ModuleType('autohsr.app');backend.Runner=FakeNativeRunner
    backend.inspect_game=lambda _:dict(title='mock only',width=1920,height=1080)
    backend.launch_game=lambda _:'mock only; never launches a process'
    loop_module=types.ModuleType('autohsr.currency_wars_loop');loop_module.CurrencyLoopRunner=FakeLoopRunner
    errors=[];screenshots=[]
    with tempfile.TemporaryDirectory() as temporary,ExitStack() as stack:
        folder=Path(temporary)
        stack.enter_context(patch.dict(sys.modules,{'autohsr.app':backend,'autohsr.currency_wars_loop':loop_module}))
        stack.enter_context(patch.object(gui,'ROOT',folder))
        stack.enter_context(patch.object(gui.messagebox,'showerror',side_effect=lambda *a,**k:errors.append(a)))
        stack.enter_context(patch.object(gui.messagebox,'showinfo'))
        stack.enter_context(patch.object(gui.messagebox,'askyesno',return_value=False))
        config=folder/'config.json';Settings().save(config);original=config.read_bytes()
        root=tk.Tk();ui=gui.AutoHSRWindow(root,config)
        callback_errors=[];root.report_callback_exception=lambda *args:callback_errors.append(args)
        delayed=None
        def select(tab):
            ui._show_page('currency_wars');show_mode_view(ui,'currency_wars','editor',focus=True)
            ui.currency_tabs.select(ui.currency_sections[tab]);pump(root)
        def capture(name):
            ui._restore();pump(root);layout(root)
            path=OUT/(name+'.png');ImageGrab.grab(window=root.winfo_id()).save(path);screenshots.append(path.name)
        def launch(callback):
            count=len(FakeBackend.instances);callback();pump(root,lambda:ui.runner is not None)
            check('backend_created_'+str(count),len(FakeBackend.instances)==count+1)
            return FakeBackend.instances[-1]
        def finish(runner):runner.release.set();pump(root,lambda:not ui.busy)
        def daily_state():
            return (ui.training_result.get(),ui.confirmed_stamina,ui.stamina.get(),
                tuple((name,value.get()) for name,value in ui.tasks.items()),
                tuple((name,deepcopy(ui.table.item(name))) for name in ui.tasks))
        try:
            pump(root);select('standard')
            names=('currency_remembrance_name','currency_fast_mode','currency_runs',
                   'currency_until_points','currency_continue_after_defeat')
            check('new_controls_default_to_saved_values',all(getattr(ui,name).get()==str(getattr(ui.settings,name))
                if name=='currency_runs' else getattr(ui,name).get()==getattr(ui.settings,name) for name in names))
            check('currency_runtime_controls_are_not_saved_variables',all(getattr(ui,name) not in ui.form_variables for name in names))
            clean=ui._form_signature();saved_dirty=ui.dirty
            ui.currency_remembrance_name.set('测试记忆');ui.currency_fast_mode.set(True);ui.currency_runs.set('3')
            ui.currency_until_points.set(True);ui.currency_continue_after_defeat.set(True)
            pump(root)
            check('only_currency_runtime_edits_do_not_dirty_or_save',ui._form_signature()==clean and ui.dirty==saved_dirty and config.read_bytes()==original)
            for name in names:getattr(ui,name).set(str(getattr(ui.settings,name)) if name=='currency_runs' else getattr(ui.settings,name))

            default=launch(ui._currency_standard)
            check('standard_defaults_are_explicit_and_scoped',default.kwargs.get('operation')=='currency_wars_standard'
                and default.kwargs.get('currency_remembrance_name')=='' and default.kwargs.get('currency_fast_mode') is False)
            finish(default)
            select('loop');default_loop=launch(ui._currency_loop)
            check('new_loop_defaults_match_the_saved_options',default_loop.kwargs==dict(root=folder/'runs',runs=1,
                currency_strategy='default',currency_remembrance_name='',currency_fast_mode=False,
                until_points=False,continue_after_defeat=False,resume=False))
            finish(default_loop);select('standard')
            ui.currency_remembrance_name.set('测试记忆');ui.currency_fast_mode.set(True)
            explicit=launch(ui._currency_standard)
            ui.currency_remembrance_name.set('另一名字');ui.currency_fast_mode.set(False)
            check('standard_name_and_fast_mode_are_frozen',explicit.kwargs.get('currency_remembrance_name')=='测试记忆'
                and explicit.kwargs.get('currency_fast_mode') is True)
            finish(explicit);select('standard');capture('currency-standard-settings')
            before=len(FakeBackend.instances);ui.currency_remembrance_name.set('名'*41)
            root.focus_force();ui._currency_standard();pump(root,lambda:root.focus_get() is ui.currency_remembrance_entry)
            check('invalid_standard_name_reveals_standard_field_without_starting',len(FakeBackend.instances)==before
                and ui.currency_tabs.select()==str(ui.currency_sections['standard'])
                and ui.currency_remembrance_entry.winfo_ismapped() and config.read_bytes()==original)
            ui.currency_remembrance_name.set('测试记忆');ui._clear_input_error()

            select('loop');before=len(FakeBackend.instances);ui.currency_runs.set('invalid count')
            root.focus_force();ui._currency_loop();pump(root,lambda:root.focus_get() is ui.currency_runs_entry)
            check('invalid_loop_count_reveals_loop_field_without_starting',len(FakeBackend.instances)==before
                and ui.currency_tabs.select()==str(ui.currency_sections['loop']) and ui.currency_runs_entry.winfo_ismapped())
            ui.currency_runs.set('3');ui._clear_input_error()
            ui.currency_strategy.set('希儿');ui.currency_fast_mode.set(True)
            ui.currency_until_points.set(True);ui.currency_continue_after_defeat.set(True)
            capture('currency-loop-settings')
            # Daily and DU drafts are deliberately invalid, including resume context.
            ui.stamina_limit.set('irrelevant daily budget');ui.rounds.set('irrelevant rounds')
            ui.differential_universe_runs.set('irrelevant DU runs');ui.du_team.set('')
            ui.du_resume_active.set(True);ui.du_resume_mode.set('周期难度 invalid')
            ui.training_result.set('verified');ui.confirmed_stamina=37;ui.stamina.set('37');baseline=daily_state()
            running=launch(ui._currency_loop)
            check('new_loop_passes_only_requested_native_options',running.kwargs==dict(root=folder/'runs',runs=3,
                currency_strategy='seele',currency_remembrance_name='测试记忆',currency_fast_mode=True,
                until_points=True,continue_after_defeat=True,resume=False))
            check('loop_and_native_settings_do_not_enable_daily',not any(getattr(running.settings,name) for name in ui.tasks)
                and not running.settings.auto_launch)
            check('running_currency_locks_all_controls',all(str(widget.cget('state'))=='disabled' for widget in ui.setting_controls)
                and all(str(getattr(ui,name).cget('state'))=='disabled' for name in ('currency_loop_button',
                    'currency_loop_resume_button','currency_points_button','currency_rewards_button','currency_rewards_resume_button')))
            snapshot=json.dumps(vars(running.settings),ensure_ascii=False,sort_keys=True)
            ui.currency_runs.set('9');ui.currency_fast_mode.set(False);ui.currency_until_points.set(False)
            ui.currency_continue_after_defeat.set(False);ui.currency_remembrance_name.set('运行后草稿')
            check('running_loop_snapshot_does_not_follow_new_drafts',running.kwargs['runs']==3
                and running.kwargs['currency_fast_mode'] is True and running.kwargs['until_points'] is True
                and running.kwargs['continue_after_defeat'] is True
                and json.dumps(vars(running.settings),ensure_ascii=False,sort_keys=True)==snapshot)
            ui.emit(dict(type='currency_loop_progress',data=loop_summary(3,2,1,until_points=True)))
            pump(root,lambda:ui.events.empty())
            displayed=ui.currency_status.get()+'\n'+ui.currency_observation.get()+'\n'+ui.current_task.get()
            check('legal_loop_progress_displays_settled_victories_and_defeats',
                  '已结束开发局 2 局' in displayed and '胜 1／负 1' in displayed)
            ui._pause();pump(root,lambda:ui.paused)
            check('loop_pause_keeps_stop_enabled',str(ui.stop_button.cget('state'))=='normal')
            ui._pause();pump(root,lambda:not ui.paused)
            finish(running)
            check('loop_score_success_does_not_become_reward_success',ui.currency_result_report['operation']=='currency_wars_loop'
                and ui.currency_result_report['currency_wars']['rewards_verified'] is False
                and '奖励' in ui.currency_observation.get() and '领奖完成' not in ui.summary.get()
                and daily_state()==baseline and config.read_bytes()==original)
            show_mode_view(ui,'currency_wars','result');capture('currency-loop-result')

            select('loop')
            ui.currency_runs.set('invalid ignored resume count');ui.currency_strategy.set('invalid ignored strategy')
            ui.currency_remembrance_name.set('名'*41);ui.currency_fast_mode.set(True)
            resumed=launch(lambda:ui._currency_loop(resume=True))
            check('loop_resume_has_no_new_or_none_overrides',resumed.kwargs==dict(root=folder/'runs',resume=True))
            ui._stop();pump(root,lambda:not ui.busy)
            check('loop_stopped_is_not_complete_or_rewarded',ui.currency_result_report['status']=='stopped'
                and ui.currency_result_report['currency_wars']['rewards_verified'] is False
                and daily_state()==baseline and config.read_bytes()==original)

            ui.currency_runs.set('3');ui.currency_strategy.set('默认');ui.currency_remembrance_name.set('')
            ui.currency_until_points.set(False);ui.currency_continue_after_defeat.set(False)
            FakeLoopRunner.scenario='defeat'
            failed=launch(ui._currency_loop);finish(failed);FakeLoopRunner.scenario='normal'
            check('verified_defeat_is_partial_and_keeps_outcomes_separate',ui.currency_result_report['status']=='partial'
                and ui.currency_result_report['currency_wars']['defeats']==1
                and ui.currency_result_report['currency_wars']['victories']==0
                and ui.currency_result_report['currency_wars']['rewards_verified'] is False)

            select('rewards');capture('currency-rewards-settings')
            ui.currency_runs.set('ignored points count');ui.currency_remembrance_name.set('名'*41)
            ui.currency_strategy.set('ignored points strategy')
            points=launch(ui._currency_points)
            check('points_ignore_all_unrelated_drafts_and_have_no_overrides',points.kwargs==dict(operation='currency_wars_points',new_battle_run=False))
            finish(points)
            check('full_points_are_not_rewards_or_match_success',ui.currency_result_report['currency_wars']['current']==18000
                and ui.currency_result_report['currency_wars']['rewards_verified'] is False
                and '奖励' in ui.currency_observation.get() and daily_state()==baseline)
            show_mode_view(ui,'currency_wars','result');capture('currency-points-result')
            rewards=launch(ui._currency_rewards)
            check('rewards_new_entry_has_only_explicit_resume_flag',rewards.kwargs==dict(operation='currency_wars_rewards',new_battle_run=False,currency_rewards_resume=False))
            finish(rewards)
            check('rewards_have_their_own_verified_receipt',ui.currency_result_report['operation']=='currency_wars_rewards'
                and ui.currency_result_report['currency_wars']['rewards_verified'] is True
                and daily_state()==baseline and config.read_bytes()==original)
            show_mode_view(ui,'currency_wars','result');capture('currency-rewards-result')
            resume_rewards=launch(lambda:ui._currency_rewards(resume=True))
            check('rewards_resume_ignores_new_standard_loop_drafts',resume_rewards.kwargs==dict(operation='currency_wars_rewards',new_battle_run=False,currency_rewards_resume=True))
            finish(resume_rewards)
            FakeNativeRunner.scenario='blocked'
            blocked=launch(ui._currency_rewards);finish(blocked);FakeNativeRunner.scenario='normal'
            check('blocked_reward_claim_is_not_presented_as_complete',ui.currency_result_report['status']=='partial'
                and ui.currency_result_report['currency_wars']['rewards_verified'] is False
                and ui.currency_result_report['currency_wars']['phase']=='blocked')

            ui.currency_runs.set('1');ui.currency_strategy.set('默认');ui.currency_remembrance_name.set('')
            loop_module.CurrencyLoopRunner=LateLoopRunner
            delayed=launch(ui._currency_loop);pump(root,lambda:delayed.early.is_set())
            check('early_loop_finished_keeps_worker_and_input_owner',ui.busy and ui.worker.is_alive())
            before=len(FakeBackend.instances);ui._currency_loop();ui._currency_points()
            check('early_loop_finished_cannot_start_another_backend',len(FakeBackend.instances)==before and ui.runner is delayed)
            delayed.tail.set();pump(root,lambda:not ui.busy)
            check('late_loop_exception_overrides_early_success','模拟货币循环完成通知后的异常' in ui.summary.get()
                and any(word in ui.currency_status.get() for word in ('失败','中断')) and daily_state()==baseline)
            loop_module.CurrencyLoopRunner=FakeLoopRunner

            select('loop')
            for page_name in ('settings','logs','currency_wars'):
                ui._show_page(page_name);pump(root)
                primaries=[ui.footer_start_button,*[deck['hero'].primary for deck in ui.mode_decks.values()]]
                check('one_primary_action_on_'+page_name,sum(bool(widget.winfo_ismapped()) for widget in primaries)==1
                    and ui.start_button.winfo_ismapped())
            root.geometry('1100x800')
            for tab in ui.currency_sections:
                select(tab);layout(root)
            show_mode_view(ui,'currency_wars','result');pump(root);layout(root)
            check('minimum_currency_editor_and_result_layout',True)
            check('all_currency_controls_leave_saved_config_and_daily_unchanged',config.read_bytes()==original
                and daily_state()==baseline and not errors and not callback_errors)
        finally:
            if delayed is not None:delayed.tail.set()
            if getattr(ui,'runner',None):ui.runner.stop()
            if getattr(ui,'worker',None):ui.worker.join(2)
            for task in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(task)
            if getattr(ui,'overlay',None):ui.overlay.close()
            root.destroy()
    result=dict(mock_backend=True,game_started=False,private_data_accessed=False,checks=CHECKS,count=len(CHECKS),screenshots=screenshots)
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
