"""Weekly loop targets through actual Runner reports and simulated game IO."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Runner
from autohsr.config import Settings, SettingsError
from autohsr import currency_wars_points_goal as goal
from autohsr.currency_wars_loop import CurrencyLoopRunner
from autohsr.currency_wars_loop_store import LoopStore, _write
from autohsr.currency_wars_points_run import OPERATION
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import run_standard
from autohsr.models import AutomationError, Stopped
from autohsr.tests import test_currency_wars_loop as loops
from autohsr.tests import test_currency_wars_points as points
from autohsr.tests import test_currency_wars_standard_flow as flow


class MixedFactory:
    """The real native lifecycle, with fake OS/vision and a seeded final node."""
    def __init__(self, root, scores):
        self.root, self.scores, self.calls = root, list(scores), []
        self.native = loops.ActualRunnerFactory(root)

    def __call__(self, settings, emit, **kwargs):
        self.calls.append(kwargs['operation'])
        if kwargs['operation'] != OPERATION:
            return self.native(settings, emit, **kwargs)
        score = self.scores.pop(0)
        current, timer = score if isinstance(score,tuple) else (score, '6天18小时')
        child = Runner(settings,emit,**kwargs)
        child._loop_test_scenes = [points.lobby(current,timer) for _ in range(3)]
        return child


class PointsGoalTests(unittest.TestCase):
    def setUp(self):
        self.now = points.NOW
        for target, kwargs in (
            ('autohsr.currency_wars_points_goal.local_now',dict(side_effect=lambda:self.now)),
            ('autohsr.currency_wars_points_run.local_now',dict(side_effect=lambda:self.now)),
            ('autohsr.currency_wars_loop.CurrencyLoopRunner._gap_controls',{}),
        ):
            patched=patch(target,**kwargs);patched.start();self.addCleanup(patched.stop)

    def make_store(self,root,*,runs=3):
        store=LoopStore(root/'runs')
        store.begin(dict(loops.options(runs),until_points=True))
        return store

    def read_points(self,root,current=0,timer='6天18小时'):
        child=points.runner([points.lobby(current,timer) for _ in range(3)])
        with loops.real_runtime(root):report=child.run()
        self.assertEqual(report.status,'success',report.error)
        return report.to_dict()

    def unstarted(self,store):
        guard=store.reserve();directory=store.root/'empty-native';directory.mkdir(exist_ok=True)
        guard.register_run(directory)
        session=StandardSession(store.journal);session.begin(directory,dict(rank_verified=True));guard.bind(session)
        return guard,session

    def run_loop(self,root,scores,**kwargs):
        factory=MixedFactory(root,scores)
        runner=CurrencyLoopRunner(Settings(overlay_logs=False),root=root/'runs',runner_factory=factory,
                                  until_points=True,**kwargs)
        with loops.real_runtime(root):result=runner.run()
        return result,factory

    def test_setting_strict_default_roundtrip_and_temporary_override(self):
        self.assertIs(Settings().currency_until_points,False)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings(currency_until_points=True).save(path)
            self.assertIs(Settings.load(path).currency_until_points,True)
            old=json.loads(path.read_text(encoding='utf-8'));old.pop('currency_until_points')
            path.write_text(json.dumps(old),encoding='utf-8')
            self.assertIs(Settings.load(path).currency_until_points,False)
        for value in (0,1,'true',[],None):
            with self.subTest(value=value),self.assertRaises(SettingsError) as caught:
                Settings(currency_until_points=value).validate('currency_wars')
            self.assertEqual(caught.exception.field,'currency_until_points')
        for value in (0,1,'true',[]):
            with self.subTest(value=value),self.assertRaises(ValueError):
                CurrencyLoopRunner(Settings(),until_points=value)
        settings=Settings(currency_until_points=True)
        runner=CurrencyLoopRunner(settings,until_points=False)
        self.assertIs(runner.options['until_points'],False);self.assertIs(settings.currency_until_points,True)

    def test_full_points_finishes_zero_games_with_original_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report,factory=self.run_loop(root,[18000],runs=4)
            self.assertEqual(report.status,'success',report.error)
            self.assertEqual(factory.calls,[OPERATION]);self.assertEqual(report.currency_wars['completed'],0)
            self.assertIs(report.currency_wars['rewards_verified'],False)
            store=LoopStore(root/'runs');store.load()
            self.assertEqual(store.data['status'],'complete');self.assertIs(goal.observation(store)['score_complete'],True)
            self.assertFalse(store.journal.exists());self.assertEqual(report.currency_wars['acceptance_runs'],0)

    def test_two_actual_settlements_then_full_stop_early_below_ceiling(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report,factory=self.run_loop(root,[0,9000,18000],runs=5)
            self.assertEqual(report.status,'success',report.error)
            self.assertEqual(report.currency_wars['completed'],2)
            self.assertEqual(factory.calls,[OPERATION,'currency_wars_standard',OPERATION,'currency_wars_standard',OPERATION])
            store=LoopStore(root/'runs');store.load();store.check_tail()
            self.assertEqual(store.data['points_goal']['checked_completed'],2)
            self.assertTrue((store.path.parent/'1.session.json').exists())
            self.assertTrue((store.path.parent/'2.session.json').exists())
            self.assertFalse(store.journal.exists())

    def test_zero_count_has_no_count_ceiling_but_still_stops_at_full(self):
        with tempfile.TemporaryDirectory() as folder:
            report,factory=self.run_loop(Path(folder),[0,18000],runs=0)
            self.assertEqual(report.status,'success',report.error);self.assertEqual(report.currency_wars['completed'],1)
            self.assertEqual(len(factory.native.children),1)

    def test_unfilled_points_exhaust_count_without_budget_growth(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report,factory=self.run_loop(root,[0,4500],runs=1)
            self.assertEqual(report.status,'partial',report.error)
            self.assertEqual(report.currency_wars['status'],'exhausted');self.assertEqual(report.currency_wars['completed'],1)
            self.assertEqual(len(factory.native.children),1)
            denied=Mock();again=CurrencyLoopRunner(Settings(),root=root/'runs',resume=True,runner_factory=denied).run()
            self.assertNotEqual(again.status,'success');denied.assert_not_called()
            store=LoopStore(root/'runs');old=deepcopy(store.load());original=store.path
            report,factory=self.run_loop(root,[18000],runs=1)
            self.assertEqual(report.status,'success',report.error)
            self.assertEqual(json.loads(original.read_text(encoding='utf-8')),old)

    def test_period_unknown_preserves_score_but_does_not_start_even_if_full(self):
        for score in (0,18000):
            with self.subTest(score=score),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);report,factory=self.run_loop(root,[(score,'未知')],runs=2)
                self.assertEqual(report.status,'partial',report.error);self.assertEqual(factory.calls,[OPERATION])
                self.assertEqual(report.currency_wars['status'],'active')
                self.assertEqual(report.currency_wars['points_goal']['observation']['current'],score)
                self.assertIs(report.currency_wars['points_goal']['observation']['weekly_target_verified'],False)

    def test_resume_unknown_points_rechecks_and_ignores_changed_saved_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first,_=self.run_loop(root,[(0,'未知')],runs=2)
            loop_id=first.currency_wars['loop_id']
            factory=MixedFactory(root,[0,18000])
            runner=CurrencyLoopRunner(Settings(currency_runs=50,currency_until_points=False),resume=True,
                                      root=root/'runs',runner_factory=factory)
            with loops.real_runtime(root):report=runner.run()
            self.assertEqual(report.status,'success',report.error)
            self.assertEqual(report.currency_wars['loop_id'],loop_id)
            self.assertEqual(report.currency_wars['requested_runs'],2)
            self.assertIs(report.currency_wars['until_points'],True)
            self.assertEqual(len(factory.native.children),1)

    def test_resume_legacy_count_loop_does_not_gain_new_weekly_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=LoopStore(root);store.begin(loops.options())
            factory=loops.NativeFactory(root)
            report=CurrencyLoopRunner(Settings(currency_until_points=True),resume=True,root=root,runner_factory=factory).run()
            self.assertEqual(report.status,'success',report.error);self.assertEqual(len(factory.calls),1)
            self.assertNotIn('points_goal',report.currency_wars)

    def test_explicit_goal_change_cannot_retarget_existing_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root)
            denied=Mock()
            report=CurrencyLoopRunner(Settings(),until_points=False,resume=True,root=store.root,runner_factory=denied).run()
            self.assertNotEqual(report.status,'success');denied.assert_not_called()
            self.assertIn('冻结设置',report.error)

    def test_cross_week_expires_without_query_or_game_and_keeps_old_week(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);week=store.data['points_goal']['week']
            self.now+=timedelta(days=7)
            denied=Mock();report=CurrencyLoopRunner(Settings(),resume=True,root=store.root,runner_factory=denied).run()
            self.assertEqual(report.status,'partial',report.error);self.assertEqual(report.currency_wars['status'],'expired')
            self.assertEqual(report.currency_wars['points_goal']['week'],week);denied.assert_not_called()

    def test_week_changes_during_points_child_expires_before_game(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=MixedFactory(root,[0])
            def emit(event):
                if event['type']=='currency_loop_points':self.now+=timedelta(days=7)
            runner=CurrencyLoopRunner(Settings(overlay_logs=False),emit,until_points=True,runs=3,
                                      root=root/'runs',runner_factory=factory)
            with loops.real_runtime(root):report=runner.run()
            self.assertEqual(report.currency_wars['status'],'expired',report.error)
            self.assertEqual(factory.calls,[OPERATION]);self.assertEqual(report.currency_wars['completed'],0)

    def test_resuming_owned_active_game_does_not_navigate_for_points_first(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);guard=store.reserve()
            loops.seed_final_node(store.root,guard)
            factory=MixedFactory(root,[18000])
            runner=CurrencyLoopRunner(Settings(overlay_logs=False),resume=True,root=store.root,runner_factory=factory)
            # The existing owned game must be used, not the factory's new-game seed.
            def current_factory(settings,emit,**kwargs):
                if kwargs['operation']==OPERATION:return factory(settings,emit,**kwargs)
                factory.calls.append(kwargs['operation']);child=Runner(settings,emit,**kwargs)
                child._loop_test_scenes=[loops.screen(k) for k in
                    ('final_victory','match_rating','match_rating','match_summary','match_statistics','lobby')]
                return child
            runner.factory=current_factory
            with loops.real_runtime(root):report=runner.run()
            self.assertEqual(report.status,'success',report.error)
            self.assertEqual(factory.calls,['currency_wars_standard',OPERATION])
            self.assertEqual(report.currency_wars['completed'],1)

    def test_owned_game_can_finish_after_week_boundary_without_starting_another(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);guard=store.reserve();loops.seed_final_node(store.root,guard)
            old_week=store.data['points_goal']['week'];self.now+=timedelta(days=7)
            calls=[]
            def factory(settings,emit,**kwargs):
                calls.append(kwargs['operation']);self.assertEqual(kwargs['operation'],'currency_wars_standard')
                self.assertTrue(kwargs['currency_resume']);child=Runner(settings,emit,**kwargs)
                child._loop_test_scenes=[loops.screen(k) for k in
                    ('final_victory','match_rating','match_rating','match_summary','match_statistics','lobby')]
                return child
            runner=CurrencyLoopRunner(Settings(overlay_logs=False),resume=True,root=store.root,runner_factory=factory)
            with loops.real_runtime(root):report=runner.run()
            self.assertEqual(report.status,'partial',report.error)
            self.assertEqual(report.currency_wars['status'],'expired');self.assertEqual(report.currency_wars['completed'],1)
            self.assertEqual(report.currency_wars['points_goal']['week'],old_week)
            self.assertEqual(calls,['currency_wars_standard'])

    def test_unstarted_empty_session_is_preserved_before_query_and_zero_game_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);_,session=self.unstarted(store);before=session.path.read_bytes()
            factory=MixedFactory(root,[18000]);runner=CurrencyLoopRunner(Settings(overlay_logs=False),resume=True,
                                                                       root=store.root,runner_factory=factory)
            with loops.real_runtime(root):report=runner.run()
            self.assertEqual(report.status,'success',report.error);self.assertEqual(factory.calls,[OPERATION])
            archive=store.path.parent/('unstarted-'+session.data['match_id']+'.session.json')
            self.assertEqual(archive.read_bytes(),before);self.assertFalse(session.path.exists())
            self.assertTrue(archive.with_suffix('.receipt.json').exists())

    def test_empty_archive_rename_crash_recovers_readonly_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);_,session=self.unstarted(store);before=session.path.read_bytes()
            from autohsr import currency_wars_loop_store as storage
            original=storage._immutable
            def crash(path,value):
                if str(path).endswith('.session.receipt.json'):raise OSError('simulated receipt failure')
                return original(path,value)
            with patch.object(storage,'_immutable',side_effect=crash),self.assertRaises(OSError):store.archive_unstarted()
            self.assertFalse(store.journal.exists());self.assertIsNotNone(store.data['empty_archive_intent'])
            archive=Path(store.data['empty_archive_intent']['archive']);self.assertEqual(archive.read_bytes(),before)
            restarted=LoopStore(store.root);restarted.load();restarted.archive_unstarted()
            self.assertIsNone(restarted.data['active']);self.assertNotIn('empty_archive_intent',restarted.data)
            self.assertEqual(archive.read_bytes(),before);self.assertEqual(restarted.data['completed'],0)

    def test_reservation_without_session_is_closed_without_count_or_game(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);guard=store.reserve()
            owner=deepcopy(guard.owner);store.archive_unstarted()
            self.assertIsNone(store.data['active']);self.assertEqual(store.data['completed'],0)
            record=store.path.parent/('unstarted-reservation-'+owner['reservation_id']+'.json')
            self.assertEqual(json.loads(record.read_text(encoding='utf-8'))['owner'],owner)

    def test_changed_frozen_week_is_rejected_before_current_game_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);guard,_=self.unstarted(store)
            edited=deepcopy(store.data);edited['points_goal']['week']='2026-11-02';_write(store.path,edited)
            with self.assertRaisesRegex(AutomationError,'归属或冻结'):guard.current()

    def test_pending_unknown_start_cannot_be_archived_or_navigate_to_points(self):
        for status in ('pending','unknown'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);store=self.make_store(root);_,session=self.unstarted(store)
                session.pending('start_standard_a8_40',0,'unknown.png','boss_preview')
                session.data['actions'][-1]['status']=status;session.persist();before=session.path.read_bytes()
                with self.assertRaises(AutomationError):store.archive_unstarted()
                denied=Mock();report=CurrencyLoopRunner(Settings(),resume=True,root=store.root,runner_factory=denied).run()
                self.assertNotEqual(report.status,'success');denied.assert_not_called()
                self.assertEqual(session.path.read_bytes(),before)

    def test_exact_receipt_not_latest_pointer_controls_start_and_original_changes_stop(self):
        for case in ('latest','receipt','image','report','summary'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);store=self.make_store(root);child=self.read_points(root);goal.record(store,child)
                ref=store.data['points_goal']['latest'];observation=child['currency_wars']
                if case=='latest':Path(ref['receipt']).parent.joinpath('latest.json').write_text('{}',encoding='utf-8')
                elif case=='receipt':Path(ref['receipt']).write_text('{}',encoding='utf-8')
                elif case=='image':Path(observation['source']).write_bytes(b'changed')
                elif case=='report':Path(ref['report']).write_text('{}',encoding='utf-8')
                else:store.data['points_goal']['observation']['current']=1
                if case=='latest':goal.require_start(store)
                else:
                    with self.assertRaises(AutomationError):goal.require_start(store)

    def test_old_or_future_points_cannot_finish_or_authorize_game(self):
        for seconds in (-121,6):
            with self.subTest(seconds=seconds),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);store=self.make_store(root);child=self.read_points(root,18000)
                self.now-=timedelta(seconds=seconds)
                with self.assertRaises(AutomationError):goal.record(store,child)
                self.assertIsNone(store.data['points_goal']['latest'])
                self.now=points.NOW

    def test_full_missing_period_old_check_or_reached_ceiling_blocks_new_start(self):
        for case in ('full','period','stale','other_week','count','unchecked'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);store=self.make_store(root,runs=1)
                child=self.read_points(root,18000 if case=='full' else 0,'未知' if case=='period' else '6天18小时')
                goal.record(store,child)
                if case=='stale':self.now+=timedelta(seconds=121)
                elif case=='other_week':self.now+=timedelta(days=7)
                elif case in ('count','unchecked'):
                    store.data['completed']=1
                    if case=='count':store.data['points_goal']['checked_completed']=1
                with self.assertRaises(AutomationError):goal.require_start(store)
                self.now=points.NOW

    def test_other_account_points_cannot_overwrite_bound_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);store.data['account_key']='f'*64;store.save();before=store.path.read_bytes()
            child=self.read_points(root)
            with self.assertRaisesRegex(AutomationError,'账号'):goal.record(store,child)
            self.assertEqual(store.path.read_bytes(),before)

    def test_new_start_checks_score_before_pending_and_again_at_native_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);goal.record(store,self.read_points(root));guard=store.reserve()
            c=flow.StandardFlowTests().context(store.root,[flow.ready()]);guard.register_run(c.report.run_dir)
            c.runner.currency_loop_guard=guard
            def before_input(scene,choice):
                pending=c.currency_standard_session.require_pending(choice.intent,0)
                self.now+=timedelta(seconds=121)
                guard.authorize(scene,pending,.85)
                self.fail('expired points authorized a start')
            c.currency_standard_input.side_effect=before_input
            with patch('autohsr.currency_wars_standard_flow.locate',flow.StandardFlowTests().locate), \
                 patch('autohsr.currency_wars_replay.save_sample'),self.assertRaisesRegex(AutomationError,'过期'):
                run_standard(c)
            self.assertEqual(c.currency_standard_session.data['actions'][-1]['status'],'pending')
            self.assertEqual(c.currency_standard_session.data['actions'][-1]['action'],'start_standard_a8_40')

    def test_missing_points_stops_native_start_before_writing_any_action(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=self.make_store(root);guard=store.reserve()
            c=flow.StandardFlowTests().context(store.root,[flow.ready()]);guard.register_run(c.report.run_dir)
            c.runner.currency_loop_guard=guard
            with patch('autohsr.currency_wars_standard_flow.locate',flow.StandardFlowTests().locate), \
                 patch('autohsr.currency_wars_replay.save_sample'),self.assertRaisesRegex(AutomationError,'积分观察'):
                run_standard(c)
            c.currency_standard_input.assert_not_called()
            self.assertEqual(c.currency_standard_session.data['actions'],[])

    def test_points_child_failure_and_stop_never_dispatch_standard_child(self):
        for status,saved in (('partial',True),('success',False),('stopped',True)):
            with self.subTest(status=status,saved=saved),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);factory=Mock();factory.return_value.run.return_value={
                    'status':status,'report_saved':saved,'run_dir':'failed-points'}
                runner=CurrencyLoopRunner(Settings(),until_points=True,runs=2,root=root/'runs',runner_factory=factory)
                report=runner.run()
                self.assertEqual(report.status,'stopped' if status=='stopped' else 'partial',report.error)
                self.assertEqual(factory.call_count,1);self.assertEqual(factory.call_args.kwargs['operation'],OPERATION)
                self.assertEqual(report.currency_wars['completed'],0)
                self.assertEqual(report.currency_wars['last_points_child']['run_dir'],'failed-points')

    def test_stop_after_verified_match_keeps_count_without_next_points_or_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=MixedFactory(root,[0])
            def emit(event):
                if event['type']=='currency_loop_progress':runner.stop()
            runner=CurrencyLoopRunner(Settings(overlay_logs=False),emit,until_points=True,runs=3,
                                      root=root/'runs',runner_factory=factory)
            with loops.real_runtime(root):report=runner.run()
            self.assertEqual(report.status,'stopped',report.error);self.assertEqual(report.currency_wars['completed'],1)
            self.assertEqual(factory.calls,[OPERATION,'currency_wars_standard'])
            store=LoopStore(root/'runs');store.load();store.check_tail()

    def test_cli_scope_two_way_dispatch_and_no_config_save(self):
        from autohsr.__main__ import main
        for argv in (['--run','--currency-until-points'],['--currency-wars-points','--no-currency-until-points']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(argv)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings().save(path);before=path.read_bytes()
            for flag,value in (('--currency-until-points',True),('--no-currency-until-points',False)):
                with patch('autohsr.currency_wars_loop.CurrencyLoopRunner') as factory, \
                     redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                    factory.return_value.run.return_value=dict(status='partial')
                    main(['--currency-wars-loop',flag,'--currency-runs','2','--config',str(path)])
                self.assertIs(factory.call_args.kwargs['until_points'],value)
                self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
