"""Exercise ordered plans through native battle accounting, with no game IO."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import numpy as np

from autohsr.config import Settings,SettingsError
from autohsr.dungeons import category_for
from autohsr.models import AutomationError,DungeonQuotaExhausted,RunReport,Scene,Stopped,Token
from autohsr.power_plan import plan_spec
from autohsr.power_plan_run import PowerRun,PowerWorkflow
from autohsr.power_plan_store import read,validate,write
from autohsr.recovery import BattleBudget
from autohsr.vision import save_scene
from autohsr.workflows import DailyWorkflow


def row(category='calyx_golden',count=2,target='回忆之蕾',location='城郊雪原'):
    return dict(category=category,count=count,target=target,location=location)


class World:
    def __init__(self,stamina=240,tokens=0):
        self.stamina=stamina;self.tokens=tokens;self.uid='123456789'
        self.mode='entry';self.count=1;self.paid=[];self.opened=[];self.evidence=0
        self.stopped=False;self.fail_target=None;self.after_payment=None
        self.payments=[];self.on_open=None
        self.epoch=0;self.weekly_left=3

    def scene(self,settings):
        category=category_for(settings)
        tokens=[Token('UID:'+self.uid,.99,(.01,.96,.25,.99)),
                Token(f'{self.stamina}/300',.99,(.72,.02,.83,.06)),
                Token(f'{self.tokens}/12',.99,(.87,.02,.93,.06)),
                Token(settings.target_name,.99,(.3,.2,.6,.24)),
                Token(f'挑战次数{self.count}',.99,(.72,.78,.86,.82)),
                Token('×'+str(self.count*category.cost),.99,(.65,.9,.74,.94)),
                Token('+',.99,(.95,.79,.97,.82)),
                Token('−',.99,(.75,.79,.78,.82) if category.key=='planar' else (.63,.79,.66,.82))]
        if self.mode=='entry':tokens.append(Token('挑战',.99,(.82,.9,.93,.95)))
        if self.mode=='team':tokens.append(Token('开始挑战',.99,(.82,.9,.95,.95)))
        if category.key=='planar' and self.mode=='team':
            tokens.extend([Token('位面饰品提取',.99,(.01,.02,.2,.08)),
                           Token('下载角色',.99,(.32,.67,.45,.72))])
        if self.mode=='success':
            tokens.extend([Token('挑战成功',.99,(.4,.2,.6,.3)),
                           Token(f'本次挑战波次{self.count}',.99,(.4,.41,.65,.45))])
        return Scene(tokens,np.zeros((36,64,3),dtype=np.uint8))


class FakeContext:
    def __init__(self,world,settings,report,budget):
        self.world=world;self.settings=settings;self.report=report;self.battle_budget=budget
        self.runner=SimpleNamespace(input_epoch=world.epoch)
        self.last_scene=None;self.scene_epoch=world.epoch

    def checkpoint(self):
        if self.world.stopped:raise Stopped('fixture stop')
        self.runner.input_epoch=self.world.epoch

    def snapshot(self):
        self.checkpoint();self.last_scene=self.world.scene(self.settings);self.last_scene.captured_at=time.monotonic()
        self.scene_epoch=self.runner.input_epoch
        return self.last_scene

    def item_view(self,settings):return FakeContext(self.world,settings,self.report,self.battle_budget)
    def log(self,*args):pass
    def sleep(self,*args):self.checkpoint()

    def evidence(self,scene,label):
        self.world.evidence+=1
        return save_scene(scene,Path(self.report.run_dir),f'{self.world.evidence}_{label}')

    def click(self,scene,target):
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch!=self.runner.input_epoch:
            raise AutomationError('stale fixture input')
        if target.text=='+':self.world.count+=1
        elif target.text=='−':self.world.count-=1
        elif target.text=='挑战':self.world.mode='team'
        elif target.text=='开始挑战':
            journal=read(self.battle_budget.path)
            # The fixture accepts input only after the real durable intent.
            if journal['pending']+40*journal['immersifiers_pending']!=self.world.count*category_for(self.settings).cost:
                raise AssertionError('start preceded durable payment')
            self.world.stamina-=journal['pending']
            self.world.tokens-=journal['immersifiers_pending']
            self.world.paid.append((self.settings.target_name,self.world.count,journal['pending']))
            self.world.payments.append((self.settings.target_name,self.world.count,journal['pending'],journal['immersifiers_pending']))
            if category_for(self.settings).weekly_limit:self.world.weekly_left-=self.world.count
            self.world.mode='success'
            if self.world.after_payment:self.world.after_payment(self.world)
        else:raise AssertionError('unexpected fixture click '+target.text)

    def wait(self,predicate,**kwargs):
        scene=self.snapshot()
        if not predicate(scene):raise AutomationError('fixture screen predicate did not match')
        return scene

    def planar_payment(self,scene):
        count=DailyWorkflow._round_count(scene)
        from autohsr.planar_resources import inventory
        owned=inventory(scene);used=min(count,owned)
        return dict(stamina=40*(count-used),immersifiers=used)


class Screens(DailyWorkflow):
    """Replace screen transitions, retain native cost/count/payment loop."""
    def _open_calyx(self):
        if self.settings.target_name==self.ctx.world.fail_target:raise AutomationError('fixture unavailable dungeon')
        self.ctx.world.mode='team' if category_for(self.settings).key=='planar' else 'entry'
        self.ctx.world.settings=self.settings
        self.ctx.world.opened.append(self.settings.target_name)
        if self.ctx.world.on_open:self.ctx.world.on_open(self.ctx.world)
        if category_for(self.settings).weekly_limit and self.ctx.world.weekly_left==0:
            raise DungeonQuotaExhausted(self.ctx.snapshot())
        return self.ctx.snapshot()

    def _calyx(self,scene):return self.ctx.world.mode in ('entry','team')
    def _team_page(self,scene):return self.ctx.world.mode=='team'
    def _disable_quick_refill(self,scene):return scene
    def _battle_result(self):return self.ctx.snapshot()
    def _exit_result(self,scene):self.ctx.world.mode='entry'
    def _enter_planar_battle(self):pass


class PowerPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def context(self,settings=None,world=None,**begin):
        settings=settings or Settings(power_plan=[row()],power_plan_fill=False,use_support=False)
        report=RunReport(run_dir=str(self.root/uuid.uuid4().hex))
        budget=BattleBudget(self.root,settings,report);budget.begin(protect_pending=True,**begin)
        return FakeContext(world or World(),settings,report,budget)

    def run_plan(self,ctx,**kwargs):
        # Preset selection already has independent native-layout tests; this
        # fixture drives resource allocation and payment after a selected team.
        with patch('autohsr.planar_team.select',side_effect=lambda flow,scene:scene):
            return PowerWorkflow(ctx,workflow_factory=Screens,**kwargs).run()

    def end(self,ctx,status='success'):
        ctx.report.status=status;ctx.battle_budget.finish()

    def test_ordered_categories_share_one_budget_and_global_completed_offset(self):
        settings=Settings(power_plan=[row(count=4),row('stagnant_shadow',3,'苦寒晶壳','残响回廊')],
                          power_plan_fill=False,stamina_limit=120,use_support=False)
        ctx=self.context(settings)
        result=self.run_plan(ctx)
        self.assertEqual(result.status,'ok')
        self.assertEqual(ctx.world.paid,[('回忆之蕾',4,40),('苦寒晶壳',2,60)])
        self.assertEqual((ctx.report.battle_completed,ctx.report.stamina_spent),(6,100))
        self.assertEqual(ctx.report.power_plan['done'],[4,2])
        self.assertFalse(ctx.report.power_plan['goal_complete'])
        self.assertEqual(read(ctx.battle_budget.path)['limit'],120)
        self.assertEqual(ctx.report.power_plan['effective_limit'],120)

    def test_frozen_initial_stamina_does_not_expand_to_later_regeneration(self):
        ctx=self.context(Settings(power_plan=[row(count=20)],power_plan_fill=False,use_support=False),World(65))
        ctx.world.after_payment=lambda world:setattr(world,'stamina',200)
        self.run_plan(ctx)
        self.assertEqual(ctx.report.stamina_spent,60)
        self.assertEqual(ctx.report.power_plan['done'],[6])
        self.assertEqual(ctx.report.power_plan['effective_limit'],60)

    def test_consumed_plan_retains_remaining_counts_on_next_budget(self):
        settings=Settings(power_plan=[row(count=8)],power_plan_fill=False,stamina_limit=60,use_support=False)
        first=self.context(settings);self.run_plan(first);self.end(first)
        second=self.context(settings);self.run_plan(second)
        self.assertEqual(first.report.power_plan['done'],[6])
        self.assertEqual(second.report.power_plan['before'],[6])
        self.assertEqual(second.report.power_plan['done'],[2])
        self.assertEqual(second.world.paid,[('回忆之蕾',2,20)])
        self.assertEqual(second.report.power_plan['sequence'],2)
        self.end(second)
        third=self.context(settings);self.run_plan(third)
        self.assertEqual(third.world.paid,[])
        self.assertEqual(third.report.power_plan['before'],[8])

    def test_keep_repeats_original_counts_and_explicit_new_goal_resets_only_counts(self):
        for keep,new_goal in ((True,False),(False,True)):
            with self.subTest(keep=keep,new_goal=new_goal),tempfile.TemporaryDirectory() as folder:
                self.root=Path(folder)
                settings=Settings(power_plan=[row()],power_plan_fill=False,power_plan_keep=keep,use_support=False)
                first=self.context(settings);self.run_plan(first);self.end(first)
                second=self.context(settings);self.run_plan(second,new_goal=new_goal)
                self.assertEqual(second.report.power_plan['before'],[0])
                self.assertEqual(second.report.power_plan['done'],[2])
                self.assertNotEqual(first.report.power_plan['goal'],second.report.power_plan['goal'])

    def test_reordering_identical_rows_preserves_consumed_goal(self):
        left=row(count=4);right=row('cavern',2,'侵蚀隧洞','残响回廊')
        settings=Settings(power_plan=[left,right],power_plan_fill=False,stamina_limit=60,use_support=False)
        first=self.context(settings);self.run_plan(first);self.end(first)
        second=self.context(replace(settings,power_plan=[right,left]));self.run_plan(second)
        self.assertEqual(second.report.power_plan['before'],[0,4])
        self.assertEqual(second.report.power_plan['done'],[1,0])
        self.assertEqual(second.world.paid,[('侵蚀隧洞',1,40)])

    def test_fallback_runs_after_planned_item_and_uses_remaining_global_budget(self):
        settings=Settings(power_plan=[row('stagnant_shadow',1,'苦寒晶壳','残响回廊')],
                          power_plan_fill=True,stamina_limit=80,use_support=False)
        ctx=self.context(settings);self.run_plan(ctx)
        self.assertEqual(ctx.world.paid,[('苦寒晶壳',1,30),('回忆之蕾',5,50)])
        self.assertEqual(ctx.report.power_plan['done'],[1])
        self.assertEqual(ctx.report.battle_completed,6)

    def test_later_unavailable_item_preserves_earlier_success(self):
        settings=Settings(power_plan=[row(),row('cavern',1,'侵蚀隧洞','残响回廊')],power_plan_fill=False,use_support=False)
        ctx=self.context(settings);ctx.world.fail_target='侵蚀隧洞'
        with self.assertRaisesRegex(AutomationError,'unavailable'):self.run_plan(ctx)
        self.assertEqual(ctx.report.power_plan['done'],[2,0])
        self.assertEqual((ctx.report.stamina_spent,ctx.report.stamina_pending),(20,0))
        self.end(ctx,'failed')
        second=self.context(settings,new_run=True);self.run_plan(second)
        self.assertEqual(second.report.power_plan['before'],[2,0])
        self.assertEqual(second.world.paid,[('侵蚀隧洞',1,40)])

    def test_unknown_payment_blocks_new_goal_new_budget_and_single_mode(self):
        ctx=self.context();ctx.world.after_payment=lambda world:setattr(world,'stopped',True)
        with self.assertRaises(Stopped):self.run_plan(ctx)
        self.assertEqual(ctx.report.stamina_pending,20)
        for settings in (ctx.settings,Settings()):
            budget=BattleBudget(self.root,settings,RunReport(run_dir=str(self.root/'next')))
            with self.assertRaises(AutomationError):budget.begin(new_run=True)
        self.assertEqual(len(ctx.world.paid),1)

    def test_changed_uid_after_payment_retains_pending_and_no_row_completion(self):
        ctx=self.context();ctx.world.after_payment=lambda world:setattr(world,'uid','987654321')
        with self.assertRaisesRegex(AutomationError,'账号'):self.run_plan(ctx)
        journal=read(ctx.battle_budget.path)
        self.assertEqual(journal['pending'],20)
        self.assertEqual(journal['power_plan']['done'],[0])
        self.assertEqual(ctx.report.battle_completed,0)
        self.assertEqual(len(ctx.world.paid),1)

    def test_initial_resource_evidence_or_archive_tamper_blocks_next_budget(self):
        ctx=self.context();self.run_plan(ctx);self.end(ctx)
        proof=Path(ctx.report.power_plan['resources_evidence']['path'])
        proof.write_bytes(b'changed evidence')
        with self.assertRaisesRegex(AutomationError,'证据'):self.context(ctx.settings,new_run=True)

    def test_durable_intent_write_failure_never_sends_start(self):
        ctx=self.context();original=ctx.battle_budget._write
        def failing(*args,**kwargs):
            if ctx.report.stamina_pending:raise OSError('fixture full disk')
            return original(*args,**kwargs)
        with patch.object(ctx.battle_budget,'_write',side_effect=failing):
            with self.assertRaisesRegex(OSError,'full disk'):self.run_plan(ctx)
        self.assertEqual(ctx.world.paid,[])
        self.assertEqual(ctx.report.power_plan['done'],[0])

    def test_settings_snapshot_and_unused_default_target_are_independent(self):
        settings=Settings(power_plan=[row()],power_plan_fill=False,target_name='',target_location='',use_support=False)
        settings.validate('power_plan')
        ctx=self.context(settings);state=PowerRun(ctx)
        settings.power_plan[0]['count']=99
        self.assertEqual(state.items[0].count,2)
        self.assertEqual(state.data['items'][0]['count'],2)
        self.run_plan(ctx)
        self.assertEqual(ctx.report.battle_completed,2)

    def test_malformed_rows_never_validate_or_save(self):
        for value in (None,{},[row(count=True)],[row(category='auto')],[row(location='')],
                      [dict(row(),extra=1)],[row(count=10000)]):
            with self.subTest(value=value):
                settings=Settings(power_plan=value)
                with self.assertRaises((SettingsError,ValueError)):settings.validate('power_plan')

    def test_corrupt_frozen_resource_or_row_payment_is_rejected(self):
        ctx=self.context();self.run_plan(ctx);data=read(ctx.battle_budget.path)
        for mutate in (lambda p:p.update(effective_limit=2400),
                       lambda p:p.update(immersifiers_limit=True),
                       lambda p:p['charges'][0].update(count=3),
                       lambda p:p['charges'][0].update(account='f'*64)):
            damaged=deepcopy(data);mutate(damaged['power_plan'])
            with self.assertRaises(AutomationError):validate(self.root,damaged,settled=True)

    def test_mixed_planar_item_retains_item_counts_after_prior_normal_challenges(self):
        settings=Settings(power_plan=[row(count=4),row('planar',5,'浴火钢心','永恒圣城')],
                          stamina_limit=120,power_plan_fill=False,use_support=False)
        ctx=self.context(settings,World(120,3));self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('回忆之蕾',4,40,0),('浴火钢心',5,80,3)])
        self.assertEqual((ctx.report.battle_completed,ctx.report.stamina_spent,ctx.report.immersifiers_spent),(9,120,3))
        self.assertEqual(ctx.report.power_plan['done'],[4,5])
        self.assertEqual(ctx.report.power_plan['immersifiers_initial'],3)
        self.assertEqual(ctx.world.opened[0],'浴火钢心')

    def test_token_only_plan_spans_multiple_batches_without_using_natural_stamina(self):
        settings=Settings(power_plan=[row('planar',8,'浴火钢心','永恒圣城')],
                          stamina_limit=10,power_plan_fill=False,use_support=False)
        ctx=self.context(settings,World(5,12));self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('浴火钢心',6,0,6),('浴火钢心',2,0,2)])
        self.assertEqual((ctx.report.stamina_spent,ctx.report.immersifiers_spent,ctx.report.battle_completed),(0,8,8))
        self.assertEqual(ctx.report.power_plan['effective_limit'],0)

    def test_smaller_owned_token_balance_shrinks_frozen_plan(self):
        settings=Settings(power_plan=[row(count=4),row('planar',4,'浴火钢心','永恒圣城')],
                          stamina_limit=80,power_plan_fill=False,use_support=False)
        ctx=self.context(settings,World(80,6))
        ctx.world.on_open=lambda world:setattr(world,'tokens',2) if len(world.opened)==2 else None
        self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('回忆之蕾',4,40,0),('浴火钢心',3,40,2)])
        self.assertEqual(ctx.report.power_plan['immersifiers_initial'],6)
        self.assertEqual(ctx.report.power_plan['immersifiers_limit'],2)

    def test_additional_tokens_after_initial_probe_never_expand_plan(self):
        settings=Settings(power_plan=[row(),row('planar',3,'浴火钢心','永恒圣城')],power_plan_fill=False,use_support=False)
        ctx=self.context(settings,World(240,1))
        ctx.world.after_payment=lambda world:setattr(world,'tokens',2)
        with self.assertRaisesRegex(AutomationError,'冻结'):self.run_plan(ctx)
        self.assertEqual(ctx.world.payments,[('回忆之蕾',2,20,0)])
        self.assertEqual(ctx.report.power_plan['done'],[2,0])

    def test_missing_anchored_history_stops_instead_of_repeating_finished_items(self):
        ctx=self.context();self.run_plan(ctx);self.end(ctx)
        second=self.context(ctx.settings);self.run_plan(second);self.end(second)
        original=Path(second.report.power_plan['previous']['path'])
        original.unlink()
        with self.assertRaises(AutomationError):self.context(ctx.settings,new_run=True)

    def test_duplicate_rows_keep_distinct_progress(self):
        settings=Settings(power_plan=[row(count=4),row(count=4)],power_plan_fill=False,stamina_limit=60,use_support=False)
        first=self.context(settings);self.run_plan(first);self.end(first)
        second=self.context(settings);self.run_plan(second)
        self.assertEqual(first.report.power_plan['done'],[4,2])
        self.assertEqual(second.report.power_plan['before'],[4,2])
        self.assertEqual(second.report.power_plan['done'],[0,2])

    def test_stale_epoch_before_reservation_cannot_pay(self):
        ctx=self.context();state=PowerRun(ctx)
        scene=ctx.snapshot();state.freeze_resources(ctx,scene,240,0)
        view,_=PowerWorkflow(ctx).view(state,state.items[0],2)
        view.snapshot();state.bind(view,0,2);ctx.world.epoch+=1
        with self.assertRaisesRegex(AutomationError,'代次'):ctx.battle_budget.reserve(20)
        self.assertEqual(ctx.world.paid,[])
        self.assertEqual(ctx.report.stamina_pending,0)

    def test_echo_long_term_goal_keeps_remaining_after_three_per_run_limit(self):
        settings=Settings(power_plan=[row('echo_of_war',8,'毁灭的开端','支援舱段')],power_plan_fill=False,use_support=False)
        settings.validate('power_plan')
        first=self.context(settings);self.run_plan(first);self.end(first)
        self.assertEqual(first.report.power_plan['done'],[3])
        self.assertEqual(first.world.paid,[('毁灭的开端',3,90)])
        second=self.context(settings);self.run_plan(second)
        self.assertEqual(second.report.power_plan['before'],[3])
        self.assertEqual(second.report.power_plan['done'],[3])
        self.assertFalse(second.report.power_plan['goal_complete'])

    def test_known_zero_weekly_allowance_defers_rows_and_can_fill_default(self):
        for fill in (False,True):
            with self.subTest(fill=fill),tempfile.TemporaryDirectory() as folder:
                self.root=Path(folder)
                settings=Settings(power_plan=[row('echo_of_war',8,'毁灭的开端','支援舱段')],
                                  power_plan_fill=fill,stamina_limit=80,use_support=False)
                world=World();world.weekly_left=0
                ctx=self.context(settings,world);result=self.run_plan(ctx)
                self.assertEqual(result.status,'ok')
                self.assertIn('本周额度',result.detail)
                self.assertEqual(ctx.report.power_plan['done'],[0])
                self.assertEqual(ctx.report.stamina_spent,80 if fill else 0)
                self.assertTrue(all(p[0]=='回忆之蕾' for p in world.paid))
                self.assertEqual(ctx.report.power_plan['results'][0]['reason'],'weekly_exhausted')

    def test_native_weekly_zero_is_distinct_from_unread_allowance(self):
        from autohsr.dungeon_workflow import open_dungeon
        from autohsr.tests.test_core import FakeContext as ExistingContext,token
        for remaining in (0,None):
            page=Scene([token('星际和平指南',.1,.05)])
            ctx=ExistingContext([page],Settings(dungeon_category='echo_of_war'))
            flow=DailyWorkflow(ctx)
            def category(flow,kind):flow._weekly_rewards=remaining;return page
            with self.subTest(remaining=remaining),patch('autohsr.dungeon_workflow.select_category',side_effect=category):
                if remaining==0:
                    with self.assertRaises(DungeonQuotaExhausted) as error:open_dungeon(flow)
                    self.assertIs(error.exception.scene,page)
                else:
                    with self.assertRaises(AutomationError) as error:open_dungeon(flow)
                    self.assertNotIsInstance(error.exception,DungeonQuotaExhausted)

    def test_unread_weekly_allowance_stops_before_default_fill(self):
        class Unread(Screens):
            def _open_calyx(self):
                if self.settings.dungeon_category=='echo_of_war':raise AutomationError('未核实本周次数')
                return super()._open_calyx()
        settings=Settings(power_plan=[row('echo_of_war',8,'毁灭的开端','支援舱段')],power_plan_fill=True,use_support=False)
        ctx=self.context(settings)
        with self.assertRaisesRegex(AutomationError,'未核实本周'):
            PowerWorkflow(ctx,workflow_factory=Unread).run()
        self.assertEqual(ctx.world.paid,[])


if __name__=='__main__':unittest.main()
