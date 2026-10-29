"""Native coordinator and Context with synthetic windows; CLI stays transient."""
from contextlib import contextmanager,ExitStack,redirect_stdout,redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.models import AutomationError,FocusLost,RunReport
from autohsr.plan_runner import PlanRunner
from autohsr.power_plan_store import read
from autohsr.recovery import BattleBudget
from autohsr.tests.test_power_plan import FakeContext,Screens,World,row


class NativeContext(Context):
    def __init__(self,runner,window,vision):
        super().__init__(runner,window,vision)
        self.world=window.world;window.contexts.append(self)

    def sleep(self,seconds):self.checkpoint()


class NativeScreens(Screens):
    def ensure_main(self):return self.ctx.snapshot()


class Window:
    hwnd=1
    def __init__(self,world):
        self.world=world;self.contexts=[];self.owner=None;self.scene=None;self.interrupt_start=False
        self.geometry=SimpleNamespace(left=0,top=0,width=960,height=540)

    def capture(self):return self.world.scene(self.world.settings).image,self.geometry
    def guard(self,*args):pass
    def focus(self):pass
    def emergency_pressed(self):return False

    def click(self,x,y,geometry):
        target=next(t for t in self.scene.tokens if abs(t.center[0]-x)<1e-6 and abs(t.center[1]-y)<1e-6)
        driver=FakeContext(self.world,self.world.settings,self.owner.report,self.owner.battle_budget)
        driver.last_scene=self.scene;driver.click(self.scene,target)
        if self.interrupt_start and target.text=='开始挑战':
            self.interrupt_start=False;raise FocusLost('fixture focus changed after submission')


@contextmanager
def runtime(root,settings,world=None):
    world=world or World();world.settings=settings
    window=Window(world)
    def read_scene(image,geometry):
        window.scene=world.scene(world.settings);window.scene.geometry=geometry
        return window.scene
    vision=SimpleNamespace(read=read_scene,planar_payment=lambda scene:FakeContext.planar_payment(None,scene))
    with ExitStack() as stack:
        stack.enter_context(patch('autohsr.app.ROOT',root))
        stack.enter_context(patch('autohsr.app.C.get_last_error',return_value=0))
        stack.enter_context(patch('autohsr.app.threading.Thread'))
        stack.enter_context(patch('autohsr.app.is_elevated',return_value=False))
        stack.enter_context(patch('autohsr.app.Vision',return_value=vision))
        stack.enter_context(patch('autohsr.app.Context',NativeContext))
        stack.enter_context(patch('autohsr.workflows.DailyWorkflow',NativeScreens))
        stack.enter_context(patch('autohsr.planar_team.select',side_effect=lambda flow,scene:scene))
        stack.enter_context(patch.object(Runner,'_arm_hotkeys'))
        find=stack.enter_context(patch('autohsr.app.find_game',return_value=window))
        stack.enter_context(patch('autohsr.windows.kernel32',SimpleNamespace(
            CreateMutexW=Mock(return_value=1),CloseHandle=Mock(return_value=True))))
        yield window,find


class PowerEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.settings=Settings(assignments=False,daily=False,daily_synthesis=False,use_support=False,overlay_logs=False,
            power_plan=[row(count=4),row('cavern',1,'侵蚀隧洞','残响回廊')],power_plan_fill=False,stamina_limit=80)

    def native(self,settings=None,world=None,**options):
        config=settings or self.settings
        with runtime(self.root,config,world) as (window,find):
            runner=Runner(config,use_power_plan=True,**options);window.owner=runner
            return runner.run(),runner,window,find

    def test_formal_runner_keeps_one_input_owner_budget_and_native_report(self):
        report,runner,window,_=self.native()
        self.assertEqual(report.status,'success',report.error)
        self.assertTrue(report.report_saved)
        self.assertEqual(window.world.paid,[('回忆之蕾',4,40),('侵蚀隧洞',1,40)])
        self.assertTrue(all(c.runner is runner for c in window.contexts))
        self.assertTrue(all(c.battle_budget is runner.battle_budget for c in window.contexts))
        self.assertEqual(read(Path(report.run_dir)/'report.json')['power_plan']['done'],[4,1])
        self.assertEqual(read(self.root/'runs/battle-session.json')['completed'],5)

    def test_progress_only_publishes_confirmed_durable_counters(self):
        events=[]
        with runtime(self.root,self.settings) as (window,_):
            def emit(event):
                if event.get('type')=='power_plan_progress':
                    events.append(event)
                    ledger=read(window.owner.battle_budget.path)
                    self.assertEqual(event['battle_completed'],ledger['completed'])
                    self.assertEqual(event['stamina_spent'],ledger['spent'])
            runner=Runner(self.settings,emit,use_power_plan=True);window.owner=runner
            report=runner.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual([e['battle_completed'] for e in events if e['stage']=='confirmed'],[4,5])
        self.assertEqual(events[-1]['rows'][0]['remaining'],0)
        for event in events:
            self.assertNotIn('account',event);self.assertNotIn('UID',json.dumps(event))

    def test_native_plan_parent_passes_explicit_opt_in_and_preserves_daily_metadata(self):
        config=self.settings;calls=[]
        with runtime(self.root,config) as (window,_):
            def factory(settings,emit,**options):
                calls.append(options)
                child=Runner(settings,emit,**options);window.owner=child;return child
            runner=PlanRunner(config,root=self.root/'runs',runner_factory=factory,use_power_plan=True)
            report=runner.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(len(calls),1)
        self.assertTrue(calls[0]['use_power_plan'])
        self.assertEqual(report.power_plan['done'],[4,1])
        self.assertEqual((report.battle_completed,report.stamina_spent),(5,80))
        self.assertEqual(read(Path(report.run_dir)/'report.json')['power_plan'],report.power_plan)

    def test_native_failed_receipt_keeps_pending_and_blocks_before_next_game_access(self):
        original=BattleBudget._write
        def failed(budget,*args,**kwargs):
            if budget.power_plan is not None and budget.report.stamina_spent:
                raise OSError('fixture receipt disk failure')
            return original(budget,*args,**kwargs)
        with patch.object(BattleBudget,'_write',failed):report,_,window,_=self.native()
        self.assertEqual(report.status,'partial')
        self.assertTrue(report.report_saved)
        self.assertEqual((report.stamina_spent,report.stamina_pending,report.battle_completed),(0,40,0))
        self.assertEqual(report.power_plan['done'],[0,0])
        self.assertEqual(len(window.world.paid),1)
        next_report,_,next_window,find=self.native(new_battle_run=True,new_power_plan=True)
        self.assertEqual(next_report.status,'failed')
        find.assert_not_called();self.assertEqual(next_window.world.paid,[])
        self.assertEqual(read(self.root/'runs/battle-session.json')['pending'],40)

    def test_ordinary_mode_does_not_execute_dormant_saved_plan(self):
        with runtime(self.root,self.settings) as (window,_):
            runner=Runner(replace(self.settings,challenge_count=1,stamina_limit=10));window.owner=runner
            report=runner.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(window.world.paid,[('回忆之蕾',1,10)])
        self.assertEqual(report.power_plan,{})

    def test_invalid_or_incompatible_api_flags_stop_before_creating_runtime(self):
        for options in (dict(use_power_plan=True,operation='reward_only'),dict(new_power_plan=True),
                        dict(use_power_plan=1),dict(use_power_plan=True,new_power_plan=1)):
            with self.subTest(options=options),self.assertRaises(ValueError):Runner(self.settings,**options)
        with self.assertRaises(ValueError):PlanRunner(self.settings,use_power_plan=True,resume_weekly_currency=True)

    def test_cli_plan_file_and_overrides_only_apply_to_this_invocation(self):
        from autohsr.__main__ import main
        config=self.root/'config.json';self.settings.save(config)
        before=config.read_bytes();plan=self.root/'plan.json';rows=[row(count=9)]
        plan.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8-sig')
        for mode,name in (('--run','autohsr.app.Runner'),('--plan','autohsr.plan_runner.PlanRunner')):
            with self.subTest(mode=mode),patch(name) as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value=RunReport(status='success')
                result=main([mode,'--config',str(config),'--power-plan','--power-plan-file',str(plan),
                             '--keep-power-plan','--no-fill-power-plan','--new-power-plan','--stamina','60'])
                self.assertEqual(result,0)
                used=factory.call_args.args[0]
                self.assertEqual(used.power_plan,rows)
                self.assertTrue(used.power_plan_keep)
                self.assertFalse(used.power_plan_fill)
                self.assertEqual(used.stamina_limit,60)
                self.assertTrue(factory.call_args.kwargs['use_power_plan'])
                self.assertTrue(factory.call_args.kwargs['new_power_plan'])
            self.assertEqual(config.read_bytes(),before)

    def test_cli_wrong_scope_never_falls_through_to_gui_or_runner(self):
        from autohsr.__main__ import main
        cases=(['--power-plan'],['--check','--power-plan'],['--run','--new-power-plan'],
               ['--run','--power-plan','--reward-only'],['--plan','--power-plan','--resume-weekly-currency'],
               ['--run','--keep-power-plan'],['--run','--no-fill-power-plan'])
        for args in cases:
            with self.subTest(args=args),patch('autohsr.app.Runner') as native,patch('autohsr.gui.main') as gui,\
                 redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):main(args)
                native.assert_not_called();gui.assert_not_called()

    def test_cli_empty_or_invalid_rows_stop_before_runner_creation(self):
        from autohsr.__main__ import main
        config=self.root/'config.json';Settings().save(config);plan=self.root/'plan.json'
        for value in ([],{},[row(count=True)],None):
            plan.write_text(json.dumps(value),encoding='utf8')
            with self.subTest(value=value),patch('autohsr.app.Runner') as native,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--run','--config',str(config),'--power-plan','--power-plan-file',str(plan)]),2)
                native.assert_not_called()

    def test_native_planar_view_uses_shared_context_and_separate_resource_receipt(self):
        config=replace(self.settings,power_plan=[row(count=4),row('planar',3,'浴火钢心','永恒圣城')])
        report,_,window,_=self.native(config,World(80,2))
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(window.world.payments,[('回忆之蕾',4,40,0),('浴火钢心',3,40,2)])
        self.assertEqual((report.stamina_spent,report.immersifiers_spent,report.battle_completed),(80,2,7))
        self.assertTrue(all(c.battle_budget.path==self.root/'runs/battle-session.json' for c in window.contexts))

    def test_focus_interruption_after_submission_does_not_restart_item(self):
        with runtime(self.root,self.settings) as (window,_):
            runner=Runner(self.settings,use_power_plan=True);window.owner=runner;window.interrupt_start=True
            report=runner.run()
        self.assertEqual(report.status,'partial')
        self.assertIn('不重复',report.error)
        self.assertEqual(report.stamina_pending,40)
        self.assertEqual(len(window.world.paid),1)
        self.assertEqual(report.power_plan['done'],[0,0])


if __name__=='__main__':unittest.main()
