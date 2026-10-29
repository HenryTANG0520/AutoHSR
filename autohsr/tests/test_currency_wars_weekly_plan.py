"""Full plan composition with real native reports and a simulated final node."""
from contextlib import contextmanager,redirect_stdout,redirect_stderr
from dataclasses import replace
import io
import json
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import uuid

from autohsr.app import Runner
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.currency_wars_loop import CurrencyLoopRunner
from autohsr.currency_wars_loop_store import LoopStore,_write
from autohsr.currency_wars_weekly import check_complete
from autohsr.currency_wars_weekly_run import CurrencyWeekRunner
from autohsr.plan_runner import PlanRunner
from autohsr.tests import test_currency_wars_loop as loops
from autohsr.tests import test_currency_wars_points as points
from autohsr.tests import test_currency_wars_weekly_rewards as rewards


def settings(**changes):
    return replace(Settings(weekly_enabled=True,weekly_mode='currency_wars',weekly_runs=2,overlay_logs=False),**changes)


class Factory:
    def __init__(self,root,scores):
        self.root,self.scores,self.calls=root,list(scores),[]
        self.native=loops.ActualRunnerFactory(root)
        self.reward_score=18000;self.reward_available=True

    def __call__(self,config,emit,**options):
        operation=options['operation'];self.calls.append(operation)
        if operation=='daily':
            path=self.root/'runs'/('daily_'+uuid.uuid4().hex[:8]);path.mkdir(parents=True)
            report=dict(operation='daily',status='success',report_saved=True,run_dir=str(path),daily_verified=True,
                        stamina_spent=120,stamina_limit=240,stamina_pending=0,
                        results=[dict(task='daily',status='ok',detail='simulated daily preservation fixture')])
            _write(path/'report.json',report)
            child=Mock();child.run.return_value=report;return child
        if operation=='currency_wars_standard':return self.native(config,emit,**options)
        child=Runner(config,emit,**options)
        if operation=='currency_wars_points':
            score=self.scores.pop(0);child._loop_test_scenes=[points.lobby(score) for _ in range(3)]
            child._week_points_number=self.calls.count(operation)
        elif operation=='currency_wars_rewards':child._loop_test_scenes=rewards.stages(self.reward_score,self.reward_available)
        else:raise AssertionError(operation)
        return child


@contextmanager
def runtime(root):
    with rewards.runtime(root) as window, \
         patch.object(CurrencyLoopRunner,'_gap_controls'),patch.object(CurrencyWeekRunner,'_gap_controls'), \
         patch('autohsr.currency_wars_weekly.local_now',return_value=points.NOW), \
         patch('autohsr.currency_wars_points.local_now',return_value=points.NOW), \
         patch('autohsr.currency_wars_points_run.local_now',return_value=points.NOW), \
         patch('autohsr.currency_wars_points_goal.local_now',return_value=points.NOW), \
         patch('autohsr.currency_wars_weekly_run.local_now',return_value=points.NOW):
        yield window


class CurrencyWeeklyPlanTests(unittest.TestCase):
    def run_plan(self,root,factory,config=None,**kwargs):
        child=PlanRunner(config or settings(),root=root/'runs',runner_factory=factory,now=points.NOW,**kwargs)
        with runtime(root):report=child.run()
        return report

    def test_daily_then_one_native_match_points_and_rewards_commit_one_goal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,18000])
            report=self.run_plan(root,factory)
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            self.assertTrue(report.daily_verified);self.assertEqual(report.stamina_spent,120)
            self.assertTrue(report.weekly_plan['score_rewards_verified']);self.assertEqual(report.currency_wars['completed'],1)
            self.assertEqual(factory.calls,['daily','currency_wars_points','currency_wars_points','currency_wars_standard',
                                             'currency_wars_points','currency_wars_rewards'])
            store=LoopStore(root/'runs');store.load();check_complete(store)
            self.assertEqual(store.data['weekly_plan']['state'],'complete')
            self.assertEqual(report.currency_wars['acceptance_runs'],0)

    def test_already_full_still_checks_rewards_without_starting_any_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[18000,18000]);factory.reward_available=False
            report=self.run_plan(root,factory)
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            self.assertNotIn('currency_wars_standard',factory.calls);self.assertEqual(report.currency_wars['completed'],0)
            self.assertIn('currency_wars_rewards',factory.calls)

    def test_same_account_week_checks_current_points_and_does_not_add_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first=Factory(root,[18000,18000]);first.reward_available=False
            report=self.run_plan(root,first);self.assertEqual(report.status,'success',report.error)
            original=LoopStore(root/'runs');original.load();before=original.path.read_bytes()
            second=Factory(root,[18000]);report=self.run_plan(root,second,settings(weekly_runs=9))
            self.assertEqual(report.status,'success',report.error)
            self.assertEqual(second.calls,['daily','currency_wars_points'])
            self.assertTrue(report.currency_wars['already_complete']);self.assertEqual(report.currency_wars['maximum'],2)
            self.assertEqual(original.path.read_bytes(),before)

    def test_exhaustion_claims_partial_rewards_and_does_not_grow_new_game_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,4500]);factory.reward_score=4500
            report=self.run_plan(root,factory,settings(weekly_runs=1))
            self.assertEqual(report.status,'partial',report.error+' / '+report.safe_next)
            self.assertEqual(report.weekly_plan['status'],'exhausted');self.assertTrue(report.daily_verified)
            self.assertEqual(report.currency_wars['completed'],1);self.assertIn('currency_wars_rewards',factory.calls)
            second=Factory(root,[4500]);report=self.run_plan(root,second,settings(weekly_runs=10))
            self.assertEqual(report.status,'partial',report.error);self.assertEqual(second.calls,['daily','currency_wars_points'])
            self.assertEqual(report.currency_wars['maximum'],1)

    def test_explicit_resume_reuses_original_daily_without_running_it_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,18000]);owner=None
            def emit(event):
                if event['type']=='currency_loop_progress':owner.stop()
            owner=PlanRunner(settings(),emit,root=root/'runs',runner_factory=factory,now=points.NOW)
            with runtime(root):first=owner.run()
            self.assertEqual(first.status,'stopped',first.error)
            self.assertTrue(first.daily_verified);self.assertEqual(first.stamina_spent,120)
            other=Factory(root,[]);denied=self.run_plan(root,other)
            self.assertEqual(other.calls,[]);self.assertNotEqual(denied.status,'success')
            self.assertTrue(denied.daily_verified);self.assertEqual(denied.budget_scope,'original_daily_run')
            self.assertEqual(denied.currency_wars['completed'],1)
            self.assertEqual(denied.weekly_plan['completed_runs'],1)
            self.assertTrue(denied.currency_wars['reused_result'])
            self.assertFalse(denied.currency_wars['current_account_verified'])
            resumed=Factory(root,[18000]);resumed.reward_available=False
            report=self.run_plan(root,resumed,settings(weekly_runs=9),resume_weekly_currency=True)
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            self.assertNotIn('daily',resumed.calls);self.assertNotIn('currency_wars_standard',resumed.calls)
            self.assertTrue(report.daily_verified);self.assertEqual(report.stamina_spent,120)
            self.assertEqual(report.budget_scope,'original_daily_run')
            self.assertEqual(report.currency_wars['maximum'],2)

    def test_resume_flag_scope_does_not_start_gui_or_add_daily_budget(self):
        from autohsr.__main__ import main
        for args in (['--run','--resume-weekly-currency'],['--plan','--resume-weekly-currency','--new-battle-run']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(args)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';settings().save(path);before=path.read_bytes()
            with patch('autohsr.plan_runner.PlanRunner') as factory,patch('autohsr.gui.main',side_effect=AssertionError('GUI fallback')), \
                 redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value=dict(status='partial')
                main(['--plan','--resume-weekly-currency','--config',str(path)])
            self.assertIs(factory.call_args.kwargs['resume_weekly_currency'],True);self.assertEqual(path.read_bytes(),before)

    def test_loop_report_save_failure_recovers_terminal_loop_without_another_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,18000])
            from autohsr import currency_wars_loop as storage
            original=storage._write
            def blocked(path,data):
                if path.name=='report.json' and data.get('operation')=='currency_wars_loop':raise OSError('loop report blocked')
                return original(path,data)
            with runtime(root),patch.object(storage,'_write',side_effect=blocked):
                first=PlanRunner(settings(),root=root/'runs',runner_factory=factory,now=points.NOW).run()
            self.assertEqual(first.status,'partial');self.assertTrue(first.daily_verified)
            self.assertNotIn('currency_wars_rewards',factory.calls)
            resumed=Factory(root,[]);resumed.reward_available=False
            report=self.run_plan(root,resumed,resume_weekly_currency=True)
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            self.assertEqual(resumed.calls,['currency_wars_rewards'])
            self.assertEqual(report.currency_wars['completed'],1);self.assertEqual(report.stamina_spent,120)

    def test_week_report_save_failure_recovers_readonly_without_running_children(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[18000,18000]);factory.reward_available=False
            from autohsr import currency_wars_weekly_run as weekly
            original=weekly._write
            def blocked(path,data):
                if path.name=='report.json' and data.get('operation')=='currency_wars_weekly':raise OSError('weekly report blocked')
                return original(path,data)
            with runtime(root),patch.object(weekly,'_write',side_effect=blocked):
                first=PlanRunner(settings(),root=root/'runs',runner_factory=factory,now=points.NOW).run()
            self.assertEqual(first.status,'partial');self.assertFalse(first.weekly_plan['score_rewards_verified'])
            store=LoopStore(root/'runs');store.load();before=store.path.read_bytes()
            resumed=Factory(root,[]);report=self.run_plan(root,resumed,resume_weekly_currency=True)
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            self.assertEqual(resumed.calls,[]);self.assertTrue(report.currency_wars['read_only_recovery'])
            self.assertTrue(report.daily_verified);self.assertEqual(store.path.read_bytes(),before)
            store.load();check_complete(store)

    def test_combined_plan_report_failure_keeps_committed_week_and_daily(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[18000,18000]);factory.reward_available=False
            with runtime(root),patch('autohsr.plan_runner.replace_file',side_effect=OSError('combined report blocked')):
                first=PlanRunner(settings(),root=root/'runs',runner_factory=factory,now=points.NOW).run()
            self.assertFalse(first.report_saved);self.assertTrue(first.daily_verified)
            store=LoopStore(root/'runs');store.load();check_complete(store)
            resumed=Factory(root,[]);report=self.run_plan(root,resumed,resume_weekly_currency=True)
            self.assertEqual(report.status,'success',report.error);self.assertEqual(resumed.calls,[])
            self.assertTrue(report.daily_verified);self.assertEqual(report.stamina_spent,120)

    def test_later_observed_points_can_finish_rewards_without_growing_exhausted_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,4500]);factory.reward_score=4500
            first=self.run_plan(root,factory,settings(weekly_runs=1));self.assertEqual(first.status,'partial',first.error)
            later=Factory(root,[18000]);later.reward_score=18000
            report=self.run_plan(root,later,settings(weekly_runs=9))
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            self.assertEqual(later.calls,['daily','currency_wars_points','currency_wars_rewards'])
            self.assertEqual(report.currency_wars['maximum'],1);self.assertEqual(report.currency_wars['completed'],1)
            self.assertTrue(report.currency_wars['later_points_observed'])
            store=LoopStore(root/'runs');store.load();check_complete(store)
            self.assertEqual(len(store.data['weekly_plan']['reward_history']),1)

    def test_account_swap_between_initial_and_loop_points_never_starts_standard_game(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0])
            with runtime(root):
                original=Context.snapshot
                def snapshot(c):
                    scene=original(c)
                    if getattr(c.runner,'_week_points_number',0)==2:
                        scene.tokens=[loops.Token(t.text.replace('100000000','100000001'),t.score,t.box) for t in scene.tokens]
                    return scene
                with patch.object(Context,'snapshot',snapshot):
                    report=PlanRunner(settings(),root=root/'runs',runner_factory=factory,now=points.NOW).run()
            self.assertEqual(report.status,'partial');self.assertNotIn('currency_wars_standard',factory.calls)
            self.assertTrue(report.daily_verified);self.assertFalse(report.weekly_plan['score_rewards_verified'])

    def test_cross_week_after_daily_does_not_create_another_weeks_goal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[])
            with runtime(root),patch('autohsr.currency_wars_weekly_run.local_now',return_value=points.NOW+timedelta(days=7)):
                report=PlanRunner(settings(),root=root/'runs',runner_factory=factory,now=points.NOW).run()
            self.assertEqual(report.status,'partial');self.assertEqual(factory.calls,['daily'])
            self.assertTrue(report.daily_verified);self.assertFalse((root/'runs/currency-loop-current.json').exists())

    def test_all_completed_match_archives_are_checked_before_reusing_weekly_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,9000,18000])
            first=self.run_plan(root,factory,settings(weekly_runs=3));self.assertEqual(first.status,'success',first.error)
            store=LoopStore(root/'runs');store.load();archive=store.path.parent/'1.session.json'
            archive.write_bytes(archive.read_bytes()+b' ')
            denied=Factory(root,[]);report=self.run_plan(root,denied)
            self.assertEqual(report.status,'failed');self.assertEqual(denied.calls,[])

    def test_pending_week_blocks_unrelated_native_input_before_game_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,18000]);parent=None
            def emit(event):
                if event['type']=='currency_loop_progress':parent.stop()
            parent=PlanRunner(settings(),emit,root=root/'runs',runner_factory=factory,now=points.NOW)
            with runtime(root):first=parent.run()
            self.assertEqual(first.status,'stopped',first.error)
            for operation in ('daily','currency_wars_points','currency_wars_standard'):
                child=Runner(Settings(overlay_logs=False),operation=operation)
                with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:report=child.run()
                self.assertEqual(report.status,'failed');prepare.assert_not_called();window.focus.assert_not_called()

    def test_unowned_old_standard_session_blocks_before_any_new_daily(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);session=loops.StandardSession(root/'runs/currency-standard-session.json')
            session.begin(root/'old-trial',{});before=session.path.read_bytes()
            factory=Factory(root,[]);report=self.run_plan(root,factory)
            self.assertEqual(report.status,'failed');self.assertEqual(factory.calls,[])
            self.assertEqual(session.path.read_bytes(),before)

    def test_week_receipt_failure_preserves_failed_report_and_only_rebuilds_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[18000,18000]);factory.reward_available=False
            from autohsr import currency_wars_weekly_run as weekly
            original=weekly._immutable
            def blocked(path,data):
                if path.name=='weekly.receipt.json':raise OSError('weekly receipt blocked')
                return original(path,data)
            with runtime(root),patch.object(weekly,'_immutable',side_effect=blocked):
                first=PlanRunner(settings(),root=root/'runs',runner_factory=factory,now=points.NOW).run()
            self.assertEqual(first.status,'partial');self.assertFalse(first.weekly_plan['score_rewards_verified'])
            source=Path(first.weekly_plan['children'][-1]['run_dir'])/'report.json';before=source.read_bytes()
            self.assertEqual(json.loads(before)['status'],'partial')
            resumed=Factory(root,[]);report=self.run_plan(root,resumed,resume_weekly_currency=True)
            self.assertEqual(report.status,'success',report.error);self.assertEqual(resumed.calls,[])
            self.assertEqual(source.read_bytes(),before)
            store=LoopStore(root/'runs');store.load();check_complete(store)

    def test_completed_week_account_index_is_separate_after_current_account_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first=Factory(root,[18000,18000]);first.reward_available=False
            report=self.run_plan(root,first);self.assertEqual(report.status,'success',report.error)
            old=LoopStore(root/'runs');old.load();old_id=old.data['loop_id'];old_account=old.data['account_key']
            second=Factory(root,[18000,18000]);second.reward_available=False
            with runtime(root):
                original=Context.snapshot
                def changed(c):
                    state=original(c)
                    state.tokens=[loops.Token(t.text.replace('100000000','100000001'),t.score,t.box) for t in state.tokens]
                    return state
                with patch.object(Context,'snapshot',changed):
                    report=PlanRunner(settings(),root=root/'runs',runner_factory=second,now=points.NOW).run()
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            current=LoopStore(root/'runs');current.load();check_complete(current)
            self.assertNotEqual(current.data['loop_id'],old_id);self.assertNotEqual(current.data['account_key'],old_account)
            check_complete(old)


if __name__=='__main__':unittest.main()
