"""Weekly priority through native payment and plan storage; synthetic IO only."""
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from autohsr.config import Settings,SettingsError
from autohsr.echo_weekly import create,slot
from autohsr.models import AutomationError,InputInterrupted,RunReport
from autohsr.power_plan_run import PowerWorkflow
from autohsr.power_plan_store import read,validate,write
from autohsr.recovery import BattleBudget
from autohsr.weekly_plan import CHINA
from autohsr.tests import test_power_plan as screens
from autohsr.tests import test_power_plan_entry as entry


NOW=datetime(2026,10,30,12,tzinfo=CHINA)


def settings(**changes):
    return replace(Settings(assignments=False,daily=False,daily_synthesis=False,use_support=False,overlay_logs=False,
        echo_of_war_enabled=True,power_plan_fill=True),**changes)


class EchoWeeklyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'runs';self.now=NOW
        clock=patch('autohsr.echo_weekly.local_now',side_effect=lambda:self.now)
        clock.start();self.addCleanup(clock.stop)

    def context(self,config=None,world=None,*,root=None,new_run=False):
        config=config or settings();root=root or self.root
        report=RunReport(run_dir=str(root/uuid.uuid4().hex))
        budget=BattleBudget(root,config,report);budget.begin(protect_pending=True,new_run=new_run)
        return screens.FakeContext(world or screens.World(),config,report,budget)

    def run_plan(self,ctx):
        return PowerWorkflow(ctx,workflow_factory=screens.Screens).run()

    def finish(self,ctx):ctx.report.status='success';ctx.battle_budget.finish()

    def test_observed_one_to_three_rewards_run_first_then_fill_one_shared_budget(self):
        for quota in (1,2,3):
            with self.subTest(quota=quota):
                world=screens.World();world.weekly_left=quota
                ctx=self.context(world=world,root=self.root/str(quota))
                result=self.run_plan(ctx)
                self.assertEqual(result.status,'ok')
                self.assertEqual(world.payments[0],('毁灭的开端',quota,quota*30,0))
                self.assertEqual(ctx.report.stamina_spent,240)
                self.assertEqual(ctx.report.power_plan['weekly_echo']['completed'],quota)
                self.assertEqual(ctx.report.power_plan['weekly_echo']['state'],'complete')
                self.assertEqual(ctx.report.power_plan['weekly_echo']['observations'][-1]['remaining'],0)
                proof=Path(ctx.report.power_plan['weekly_echo']['observations'][0]['evidence']['path'])
                self.assertIn('本周可领取奖励次数',proof.with_suffix('.txt').read_text('utf8'))
                self.assertIn(f'{quota}/3',proof.with_suffix('.txt').read_text('utf8'))
                self.assertTrue(all(p[0]=='回忆之蕾' for p in world.payments[1:]))
                self.assertEqual(read(ctx.battle_budget.path)['limit'],240)

    def test_already_zero_is_verified_without_claiming_three_autohsr_victories(self):
        world=screens.World();world.weekly_left=0
        ctx=self.context(world=world);self.run_plan(ctx)
        echo=ctx.report.power_plan['weekly_echo']
        self.assertEqual((echo['state'],echo['completed']),('complete',0))
        self.assertEqual(echo['observations'][0]['remaining'],0)
        self.assertTrue(all(p[0]=='回忆之蕾' for p in world.payments))

    def test_small_budget_limits_echo_then_uses_only_remaining_budget_for_normal_rows(self):
        config=settings(stamina_limit=80,power_plan=[screens.row(count=8)],power_plan_fill=False)
        ctx=self.context(config);result=self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('毁灭的开端',2,60,0),('回忆之蕾',2,20,0)])
        echo=ctx.report.power_plan['weekly_echo']
        self.assertEqual((echo['state'],echo['completed']),('limited',2))
        self.assertEqual(echo['observations'][-1]['remaining'],1)
        self.assertEqual(ctx.report.power_plan['done'],[2])
        self.assertIn('目标周剩余1次',result.detail)

    def test_game_day_schedule_uses_four_am_and_never_creates_timer(self):
        config=settings(echo_of_war_start_day=5,power_plan_fill=False)
        for hour,due in ((3,False),(4,True)):
            self.now=NOW.replace(hour=hour)
            data=create(config)
            self.assertEqual(data['due'],due)
            ctx=self.context(config,root=self.root/str(hour));self.run_plan(ctx)
            self.assertEqual(bool(ctx.world.payments),due)
            self.assertEqual(ctx.report.power_plan['weekly_echo']['state'],'complete' if due else 'not_due')
        before=slot(1,datetime(2026,11,2,3,59,tzinfo=CHINA))
        after=slot(1,datetime(2026,11,2,4,0,tzinfo=CHINA))
        self.assertEqual((before.week,after.week),('2026-10-26','2026-11-02'))

    def test_not_due_still_runs_requested_normal_plan_and_does_not_probe_echo(self):
        config=settings(echo_of_war_start_day=7,power_plan=[screens.row()],power_plan_fill=False)
        ctx=self.context(config);self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('回忆之蕾',2,20,0)])
        self.assertNotIn('毁灭的开端',ctx.world.opened)

    def test_manual_progress_is_separate_from_weekly_priority_across_runs_and_weeks(self):
        config=settings(power_plan=[screens.row(count=4)],power_plan_fill=False,stamina_limit=100)
        first=self.context(config);self.run_plan(first);self.finish(first)
        self.assertEqual(first.report.power_plan['done'],[1])
        world=screens.World();world.weekly_left=0
        second=self.context(config,world);self.run_plan(second);self.finish(second)
        self.assertEqual(second.report.power_plan['before'],[1])
        self.assertEqual(second.report.power_plan['done'],[3])
        self.assertEqual(second.report.power_plan['weekly_echo']['completed'],0)
        self.now=datetime(2026,11,2,5,tzinfo=CHINA)
        third=self.context(config);self.run_plan(third)
        self.assertEqual(third.report.power_plan['before'],[4])
        self.assertEqual(third.report.power_plan['done'],[0])
        self.assertEqual(third.world.payments,[('毁灭的开端',3,90,0)])
        self.assertEqual(third.report.power_plan['weekly_echo']['week'],'2026-11-02')

    def test_pre_echo_schema_is_still_readable_and_preserves_consumed_counts(self):
        config=settings(echo_of_war_enabled=False,power_plan=[screens.row(count=4)],power_plan_fill=False,stamina_limit=20)
        first=self.context(config);self.run_plan(first);self.finish(first)
        old=read(first.battle_budget.path);old['power_plan'].pop('weekly_echo');write(first.battle_budget.path,old)
        world=screens.World();world.weekly_left=0
        second=self.context(replace(config,echo_of_war_enabled=True),world);self.run_plan(second)
        self.assertEqual(second.report.power_plan['before'],[2])
        self.assertEqual(second.report.power_plan['done'],[2])

    def test_unread_or_increased_quota_stops_without_default_fallback(self):
        for initial in (None,1):
            with self.subTest(initial=initial):
                world=screens.World();world.weekly_left=initial
                if initial is not None:world.after_payment=lambda w:setattr(w,'weekly_left',3)
                ctx=self.context(world=world,root=self.root/str(initial))
                with self.assertRaisesRegex(AutomationError,'周次数|周额度'):self.run_plan(ctx)
                self.assertFalse(any(p[0]=='回忆之蕾' for p in world.payments))
                self.assertEqual(ctx.report.stamina_spent,0 if initial is None else 30)

    def test_week_cross_after_paid_result_retains_old_week_and_stops_further_payments(self):
        world=screens.World();world.weekly_left=1
        world.after_payment=lambda w:setattr(self,'now',datetime(2026,11,2,5,tzinfo=CHINA))
        ctx=self.context(world=world)
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):self.run_plan(ctx)
        self.assertEqual(world.payments,[('毁灭的开端',1,30,0)])
        self.assertEqual(ctx.report.stamina_pending,0)
        self.assertEqual(ctx.report.power_plan['weekly_echo']['week'],'2026-10-26')
        self.assertEqual(ctx.report.power_plan['weekly_echo']['completed'],1)

    def test_receipt_failure_rolls_back_weekly_counter_and_cannot_replay(self):
        ctx=self.context();original=ctx.battle_budget._write
        def failed(*args,**kwargs):
            if ctx.report.stamina_spent:raise OSError('weekly receipt fixture failure')
            return original(*args,**kwargs)
        with patch.object(ctx.battle_budget,'_write',side_effect=failed):
            with self.assertRaises(OSError):self.run_plan(ctx)
        self.assertEqual((ctx.report.stamina_pending,ctx.report.battle_completed),(90,0))
        self.assertEqual(ctx.report.power_plan['weekly_echo']['completed'],0)
        with self.assertRaises(AutomationError):self.run_plan(ctx)
        with self.assertRaises(AutomationError):self.context(new_run=True)
        self.assertEqual(len(ctx.world.payments),1)

    def test_weekly_proof_or_paid_counter_tamper_is_rejected(self):
        ctx=self.context(settings(power_plan_fill=False));self.run_plan(ctx)
        original=read(ctx.battle_budget.path)
        for mutate in (lambda e:e.update(week='2026-11-02'),lambda e:e.update(completed=2),
                       lambda e:e.update(due=False),lambda e:e.update(maximum=4),
                       lambda e:e['observations'][-1].update(remaining=1),
                       lambda e:e['observations'][0].update(remaining=True)):
            data=deepcopy(original);mutate(data['power_plan']['weekly_echo'])
            with self.subTest(data=data['power_plan']['weekly_echo']),self.assertRaises((AutomationError,ValueError)):
                validate(self.root,data,settled=True)
        # An observed guide value cannot be reused after a pause generation,
        # even when the later challenge page belongs to the same account.
        isolated=self.context(settings(power_plan_fill=False),root=self.root/'stale')
        from autohsr.power_plan_run import PowerRun
        state=PowerRun(isolated)
        isolated.world.mode='quota';guide=isolated.snapshot()
        proof=state.quota_proof(isolated,guide,3)
        isolated.world.epoch+=1;isolated.world.mode='entry';current=isolated.snapshot()
        with self.assertRaises(InputInterrupted):state.observe_echo(isolated,current,3,proof=proof)
        self.assertEqual(isolated.report.stamina_pending,0)
        self.assertEqual(state.data['weekly_echo']['observations'],[])

    def test_only_power_plan_opt_in_uses_saved_weekly_preference(self):
        config=settings()
        root=self.root.parent
        with entry.runtime(root,config) as (window,_):
            runner=entry.Runner(config);window.owner=runner;report=runner.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(report.power_plan,{})
        self.assertTrue(all(p[0]=='回忆之蕾' for p in window.world.payments))

    def test_formal_runner_executes_weekly_prelude_under_same_input_owner(self):
        config=settings(power_plan=[screens.row()],power_plan_fill=False,stamina_limit=120)
        events=[]
        with entry.runtime(self.root.parent,config) as (window,_):
            runner=entry.Runner(config,events.append,use_power_plan=True);window.owner=runner;report=runner.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(window.world.payments,[('毁灭的开端',3,90,0),('回忆之蕾',2,20,0)])
        self.assertTrue(all(c.runner is runner and c.battle_budget is runner.battle_budget for c in window.contexts))
        self.assertEqual(report.power_plan['weekly_echo']['state'],'complete')
        self.assertTrue(any(e.get('type')=='power_plan_progress' and e['weekly_echo']['completed']==3 for e in events))

    def test_cli_weekly_only_and_temporary_schedule_do_not_save_config(self):
        from autohsr.__main__ import main
        path=self.root.parent/'config.json';Settings().save(path);before=path.read_bytes()
        with patch('autohsr.app.Runner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            factory.return_value.run.return_value=RunReport(status='success')
            self.assertEqual(main(['--run','--power-plan','--echo-of-war','--echo-start-day','5',
                                  '--echo-target','毁灭的开端','--echo-location','支援舱段',
                                  '--no-fill-power-plan','--config',str(path)]),0)
            config=factory.call_args.args[0]
            self.assertTrue(config.echo_of_war_enabled)
            self.assertEqual(config.echo_of_war_start_day,5)
            self.assertEqual(config.power_plan,[])
            self.assertTrue(factory.call_args.kwargs['use_power_plan'])
        self.assertEqual(path.read_bytes(),before)
        for args in (['--run','--echo-of-war'],['--plan','--echo-start-day','2'],['--run','--no-echo-of-war']):
            with self.subTest(args=args),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(args)

    def test_invalid_settings_reject_before_game_and_save_roundtrips_weekly_pref(self):
        for field,value in (('echo_of_war_enabled',1),('echo_of_war_start_day',True),('echo_of_war_start_day',0),
                            ('echo_of_war_start_day',8),('echo_of_war_target',''),('echo_of_war_location',None)):
            with self.subTest(field=field,value=value),self.assertRaises(SettingsError):settings(**{field:value}).validate('power_plan')
        config=settings(echo_of_war_start_day=7)
        path=self.root.parent/'config.json';config.save(path)
        self.assertEqual(Settings.load(path),config)

    def test_single_round_batches_do_not_refill_the_weekly_allowance(self):
        ctx=self.context(settings(rounds=1,power_plan_fill=False));self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('毁灭的开端',1,30,0)]*3)
        self.assertEqual(ctx.report.power_plan['weekly_echo']['completed'],3)
        self.assertEqual(ctx.report.power_plan['weekly_echo']['state'],'complete')

    def test_quota_decrease_between_entry_reads_does_not_inflate_confirmed_count(self):
        world=screens.World()
        world.on_open=lambda w:setattr(w,'weekly_left',1) if len(w.opened)==3 else None
        ctx=self.context(world=world);self.run_plan(ctx)
        self.assertEqual(world.payments[0],('毁灭的开端',1,30,0))
        echo=ctx.report.power_plan['weekly_echo']
        self.assertEqual((echo['completed'],echo['state']),(1,'complete'))
        self.assertEqual(echo['observations'][0]['remaining'],3)
        self.assertTrue(all(p[0]=='回忆之蕾' for p in world.payments[1:]))

    def test_manual_echo_row_also_allocates_only_observed_current_quota(self):
        world=screens.World();world.weekly_left=1
        config=settings(echo_of_war_enabled=False,power_plan=[screens.row('echo_of_war',8,'毁灭的开端','支援舱段')])
        ctx=self.context(config,world);result=self.run_plan(ctx)
        self.assertEqual(result.status,'ok')
        self.assertEqual(ctx.world.payments[0],('毁灭的开端',1,30,0))
        self.assertEqual(ctx.report.power_plan['done'],[1])
        self.assertEqual(ctx.report.stamina_spent,240)

    def test_new_archive_path_uses_short_keys_and_existing_full_keys_stay_in_place(self):
        from autohsr.config import ROOT
        from autohsr.power_plan import plan_spec
        from autohsr.power_plan_run import account
        from autohsr.power_plan_store import folder
        first=self.context(settings(power_plan_fill=False));self.run_plan(first);self.finish(first)
        self.context(settings(power_plan_fill=False))
        plan=first.report.power_plan;current=folder(self.root,plan['account'],plan['spec'])
        self.assertEqual((len(current.parent.name),len(current.name)),(32,32))
        # Extended IO spelling also lets TemporaryDirectory clean this legacy
        # layout in a long worktree, without changing machine-wide settings.
        import os
        from autohsr.power_plan_store import normal_path
        base=(ROOT/'runs').resolve()
        temporary_base=Path('\\\\?\\'+str(base)) if os.name=='nt' else base
        with tempfile.TemporaryDirectory(dir=temporary_base,prefix='echo-old-') as work:
            root=Path(work).resolve()
            self.assertTrue(normal_path(root).resolve().is_relative_to(base))
            config=settings(echo_of_war_enabled=False,power_plan=[screens.row(count=4)],stamina_limit=20,power_plan_fill=False)
            old=self.context(config,root=root)
            identity=account(old,old.snapshot());_,spec=plan_spec(config)
            legacy=root/'power-plans'/identity/spec
            write(legacy/'current.json',dict(schema=1,goal=uuid.uuid4().hex,head=None))
            self.run_plan(old);self.finish(old)
            next_run=self.context(config,root=root);self.run_plan(next_run)
            self.assertEqual(next_run.report.power_plan['before'],[2])
            self.assertFalse(next_run.report.power_plan['previous']['path'].startswith('\\\\?\\'))
            self.assertEqual(folder(root,identity,spec),legacy)
            self.assertFalse((root/'power-plans'/identity[:32]/spec[:32]).exists())

    def test_two_archive_layouts_stop_without_replacing_original_budget(self):
        ctx=self.context(settings(power_plan_fill=False));self.run_plan(ctx);self.finish(ctx)
        plan=ctx.report.power_plan
        (self.root/'power-plans'/plan['account']/plan['spec']).mkdir(parents=True)
        before=ctx.battle_budget.path.read_bytes()
        with self.assertRaisesRegex(AutomationError,'新旧目录'):self.context(new_run=True)
        self.assertEqual(ctx.battle_budget.path.read_bytes(),before)

    def test_weekly_then_planar_uses_original_owned_tokens_and_one_cash_budget(self):
        config=settings(stamina_limit=120,power_plan=[screens.row('planar',5,'浴火钢心','永恒圣城')])
        ctx=self.context(config,screens.World(120,3))
        with patch('autohsr.planar_team.select',side_effect=lambda flow,scene:scene):self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('毁灭的开端',3,90,0),('浴火钢心',3,0,3),('回忆之蕾',3,30,0)])
        self.assertEqual((ctx.report.stamina_spent,ctx.report.immersifiers_spent),(120,3))
        self.assertEqual(ctx.report.power_plan['weekly_echo']['completed'],3)
        self.assertEqual(ctx.report.power_plan['done'],[3])

    def test_later_unknown_payment_preserves_verified_weekly_count(self):
        config=settings(power_plan=[screens.row()],power_plan_fill=False)
        world=screens.World()
        world.after_payment=lambda w:setattr(w,'uid','987654321') if len(w.payments)==2 else None
        ctx=self.context(config,world)
        with self.assertRaisesRegex(AutomationError,'账号'):self.run_plan(ctx)
        self.assertEqual((ctx.report.stamina_spent,ctx.report.stamina_pending,ctx.report.battle_completed),(90,20,3))
        self.assertEqual(ctx.report.power_plan['weekly_echo']['completed'],3)
        self.assertEqual(ctx.report.power_plan['weekly_echo']['state'],'complete')
        self.assertEqual(ctx.report.power_plan['done'],[0])

    def test_parent_plan_keeps_weekly_prelude_in_original_daily_report(self):
        config=settings(power_plan_fill=False);root=self.root.parent
        with entry.runtime(root,config) as (window,_):
            def factory(config,emit,**options):
                child=entry.Runner(config,emit,**options);window.owner=child;return child
            parent=entry.PlanRunner(config,root=self.root,runner_factory=factory,use_power_plan=True)
            report=parent.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(report.power_plan['weekly_echo']['completed'],3)
        self.assertEqual(report.power_plan['weekly_echo']['state'],'complete')
        self.assertEqual(read(Path(report.run_dir)/'report.json')['power_plan'],report.power_plan)

    def test_daily_start_snapshot_does_not_become_due_during_earlier_tasks(self):
        ctx=self.context(settings(echo_of_war_start_day=5,power_plan_fill=False))
        ctx.report.started_at=NOW.replace(hour=3,minute=59).isoformat()
        self.now=NOW.replace(hour=4,minute=10)
        self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[])
        self.assertEqual(ctx.report.power_plan['weekly_echo']['state'],'not_due')

    def test_previous_week_daily_start_stops_before_resource_navigation(self):
        ctx=self.context();ctx.report.started_at=datetime(2026,11,1,23,59,tzinfo=CHINA).isoformat()
        self.now=datetime(2026,11,2,4,1,tzinfo=CHINA)
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):self.run_plan(ctx)
        self.assertEqual(ctx.world.opened,[])
        self.assertEqual(ctx.world.payments,[])
        self.assertEqual(ctx.report.power_plan['weekly_echo']['week'],'2026-10-26')

    def test_completed_priority_is_not_restarted_when_normal_plan_resumes_next_week(self):
        class InterruptNormal(screens.Screens):
            def _open_calyx(self):
                echo=self.ctx.report.power_plan.get('weekly_echo')
                if (echo and echo['state']=='complete' and self.settings.target_name=='回忆之蕾'
                        and not getattr(self.ctx.world,'interrupted_once',False)):
                    self.ctx.world.interrupted_once=True;raise InputInterrupted('fixture before normal entry')
                return super()._open_calyx()
        ctx=self.context(settings(power_plan=[screens.row()],power_plan_fill=False))
        flow=PowerWorkflow(ctx,workflow_factory=InterruptNormal)
        with self.assertRaises(InputInterrupted):flow.run()
        self.now=datetime(2026,11,2,4,1,tzinfo=CHINA)
        result=flow.run()
        self.assertEqual(result.status,'ok')
        self.assertEqual(ctx.world.payments,[('毁灭的开端',3,90,0),('回忆之蕾',2,20,0)])
        self.assertEqual(ctx.report.power_plan['weekly_echo']['week'],'2026-10-26')
        self.assertEqual(ctx.report.stamina_spent,110)


if __name__=='__main__':unittest.main()
