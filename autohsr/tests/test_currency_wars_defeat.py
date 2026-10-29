"""Synthetic terminal defeat and native settlement/loop provenance checks."""
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
import io
from itertools import count
import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from PIL import Image

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars import observe
from autohsr.currency_wars_defeat import STEPS,INTENTS,attempt,payload,settled,feedback
from autohsr.currency_wars_loop import CurrencyLoopRunner
from autohsr.currency_wars_loop_store import LoopStore,_write
from autohsr.currency_wars_session import StandardSession,require_session_access
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.models import AutomationError,InputInterrupted,RunReport,Token,normalize
from autohsr.tests import test_currency_wars_loop as loops
from autohsr.tests.test_currency_wars_node import screen


def frame(kind,node='1-4'):
    original={'match_defeat':'final_victory','defeat_rating':'match_rating','defeat_summary':'match_summary'}.get(kind,kind)
    data=screen(original)
    result=[]
    for t in data.tokens:
        text=t.text
        if kind in ('match_defeat','defeat_rating') and normalize(text)=='挑战成功':text='挑战结束'
        if kind=='defeat_rating' and normalize(text).startswith('小队生命值'):text='小队生命值0'
        if kind=='defeat_summary' and normalize(text)=='对局胜利':text='对局失败'
        if re.fullmatch(r'[1-3]-[1-9][0-9]?首领',normalize(text)):text=node+'首领'
        result.append(Token(text,t.score,t.box))
    data.tokens=result
    return data


def seed(root,guard=None,node='1-4'):
    store,policy=loops.seed_final_node(root,guard)
    store.data['actions'][1]['target'][0]=node
    store.data['node_attempt']['node']=node
    store.persist();return store,policy


def finish(root,guard=None,*,node='1-4',scene_mutation=None):
    store,policy=seed(root,guard,node);directory=Path(store.data['run_dir'])
    runner=Runner(Settings(),operation='currency_wars_standard',currency_resume=True,
                  currency_strategy=policy['strategy'],currency_loop_guard=guard,
                  currency_remembrance_name=policy['remembrance_name'],currency_fast_mode=policy['equipment_fast_mode'])
    runner.report=RunReport(operation='currency_wars_standard',run_dir=str(directory))
    c=Context(runner,Mock(),Mock());c.checkpoint=Mock();c.sleep=Mock();c.log=Mock()
    states=[frame(k,node) for k in ('match_defeat','match_defeat','defeat_rating','defeat_rating',
                                  'defeat_summary','defeat_summary','match_statistics','match_statistics','lobby','lobby')]
    if scene_mutation:scene_mutation(states)
    def snapshot():
        page=states.pop(0) if states else c.last_scene
        if page.image is None:page.image=Image.new('RGB',(32,32),'gray')
        page.tokens=[t for t in page.tokens if not normalize(t.text).startswith('uid')]
        page.tokens.append(Token('UID:100000000',.99,(.01,.96,.1,.99)))
        page.captured_at=time.monotonic();c.last_scene=page;c.scene_epoch=runner.input_epoch;return page
    count=0
    def evidence(page,label):
        nonlocal count
        count+=1;path=directory/(str(count)+'_'+label+'.png');page.image.save(path);return path
    c.snapshot=snapshot;c.evidence=evidence
    with patch('autohsr.currency_wars_replay.save_sample'):runner._inspect_currency_wars(c)
    runner.report.report_saved=True;_write(directory/'report.json',runner.report.to_dict())
    return runner.report,c


class Factory:
    def __init__(self,root,outcomes):self.root=root;self.outcomes=list(outcomes);self.calls=[]
    def __call__(self,settings,emit,**kwargs):
        self.calls.append(kwargs);child=Mock()
        def run():
            outcome=self.outcomes.pop(0)
            result=finish(self.root,kwargs['currency_loop_guard'])[0] if outcome=='defeat' else loops.settled(self.root,kwargs['currency_loop_guard'])
            emit(dict(type='finished',report=result.to_dict()));return result
        child.run.side_effect=run;return child


class ActualFactory:
    def __init__(self,root,outcomes):self.root=root;self.outcomes=list(outcomes);self.children=[]
    def __call__(self,settings,emit,**kwargs):
        outcome=self.outcomes.pop(0)
        if outcome=='victory':
            runner=loops.ActualRunnerFactory(self.root)(settings,emit,**kwargs)
        else:
            seed(self.root/'runs',kwargs['currency_loop_guard']);kwargs['currency_resume']=True
            runner=Runner(settings,emit,**kwargs)
            runner._loop_test_scenes=[frame(k) for k in ('match_defeat','match_defeat','match_defeat','defeat_rating','defeat_rating',
                'defeat_summary','defeat_summary','match_statistics','match_statistics','lobby','lobby')]
        self.children.append(runner);return runner


class DefeatTests(unittest.TestCase):
    def setUp(self):
        controls=patch.object(CurrencyLoopRunner,'_gap_controls');controls.start();self.addCleanup(controls.stop)

    def test_terminal_pages_require_distinct_controls_zero_hp_and_no_victory_conflict(self):
        for kind in ('match_defeat','defeat_rating','defeat_summary'):
            page=frame(kind);self.assertEqual(observe(page,.65).page_kind,kind)
            for text in ('挑战成功','对局胜利','继续挑战'):
                conflict=deepcopy(page);conflict.tokens.append(Token(text,.99,(.3,.1,.4,.15)))
                self.assertEqual(observe(conflict,.65).page_kind,'unknown')
        page=frame('defeat_rating')
        page.tokens=[Token('小队生命值1' if normalize(t.text)=='小队生命值0' else t.text,t.score,t.box) for t in page.tokens]
        self.assertEqual(observe(page,.65).page_kind,'unknown')
        page=frame('match_defeat');page.tokens=[t for t in page.tokens if normalize(t.text)!='前往结算']
        self.assertNotEqual(observe(page,.65).page_kind,'match_defeat')

    def test_visible_modal_blocks_terminal_background_and_sends_no_settlement(self):
        for kind in ('match_defeat','defeat_rating','defeat_summary'):
            for modal in ('star_selection','equipment_selection','character','tutorial'):
                page=frame(kind);page.tokens+=screen(modal).tokens
                self.assertEqual(observe(page,.65).page_kind,'unknown',(kind,modal))
        with tempfile.TemporaryDirectory() as folder:
            def conflict(states):
                for page in states[:2]:page.tokens+=screen('star_selection').tokens
            report,c=finish(Path(folder),scene_mutation=conflict)
            self.assertNotEqual(report.currency_wars.get('defeat_settlement_verified'),True)
            c.window.click.assert_not_called()

    def test_native_four_step_defeat_never_sets_victory_or_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            report,c=finish(Path(folder));data=report.currency_wars
            self.assertEqual(report.status,'partial');self.assertTrue(settled(data))
            self.assertFalse(data['completion_verified']);self.assertFalse(data['node_attempt']['node_verified'])
            self.assertNotIn('match_victory_observed',data);self.assertEqual(data['match_outcome'],'defeat')
            self.assertEqual(c.window.click.call_count,4)
            self.assertEqual(len(data['node_attempt']['defeat_frames']),2)
            self.assertEqual([a['action'] for a in data['actions'][-4:]],['settle_standard_defeat_'+k for k in STEPS])
            self.assertTrue(StandardSession(Path(folder)/'currency-standard-session.json').data['defeat_settlement_verified'])

    def test_upstream_unfinished_wording_follows_the_same_defeat_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            def wording(states):
                for page in states:
                    page.tokens=[Token('对局未完成' if normalize(t.text)=='对局失败' else t.text,t.score,t.box)
                                 for t in page.tokens]
            report,c=finish(Path(folder),scene_mutation=wording)
            self.assertTrue(settled(report.currency_wars));self.assertEqual(report.status,'partial')
            self.assertFalse(report.currency_wars['completion_verified']);self.assertEqual(c.window.click.call_count,4)

    def test_isolated_lobby_or_failure_text_cannot_supply_original_attempt(self):
        for kind in ('match_defeat','defeat_rating','defeat_summary'):
            with self.subTest(kind=kind),self.assertRaises(AutomationError):next_action(frame(kind),session={})
        self.assertFalse(settled(dict(status='settled',match_outcome='defeat',settlement_verified=True,
                                      defeat_settlement_verified=True,completion_verified=False)))

    def test_known_defeat_does_not_change_game_count_or_win_count_into_each_other(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,['defeat','victory'])
            result=CurrencyLoopRunner(Settings(currency_continue_after_defeat=True),runs=2,root=root,runner_factory=factory).run()
            self.assertEqual(result.status,'partial',result.error)
            self.assertEqual(len(factory.calls),2)
            self.assertEqual((result.currency_wars['settled_games'],result.currency_wars['victories'],result.currency_wars['defeats']),(2,1,1))
            store=LoopStore(root);store.load();store.check_tail()
            self.assertEqual(store.data['status'],'complete');self.assertEqual(store.data['completed'],2)
            for slot,outcome in ((1,'defeat'),(2,'victory')):
                receipt=json.loads((store.path.parent/(str(slot)+'.session.receipt.json')).read_text('utf8'))
                self.assertEqual(receipt.get('outcome','victory'),outcome)
                self.assertEqual(receipt['defeats_after'],1)

    def test_default_stops_and_explicit_resume_uses_only_original_remaining_games(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,['defeat'])
            result=CurrencyLoopRunner(Settings(),runs=3,root=root,runner_factory=factory).run()
            self.assertEqual((result.status,result.currency_wars['status']),('partial','defeated'),result.error)
            self.assertEqual(result.currency_wars['completed'],1);self.assertEqual(result.currency_wars['defeats'],1)
            second=Factory(root,['victory','victory'])
            resumed=CurrencyLoopRunner(Settings(currency_runs=99),resume=True,root=root,runner_factory=second).run()
            self.assertEqual(resumed.status,'partial',resumed.error);self.assertEqual(len(second.calls),2)
            self.assertEqual((resumed.currency_wars['requested_runs'],resumed.currency_wars['completed'],resumed.currency_wars['defeats']),(3,3,1))
            self.assertTrue(resumed.currency_wars['defeat_resumed'])

    def test_defeat_counts_towards_ceiling_even_when_every_game_loses(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,['defeat','defeat'])
            result=CurrencyLoopRunner(Settings(),runs=2,continue_after_defeat=True,root=root,runner_factory=factory).run()
            self.assertEqual(result.status,'partial',result.error);self.assertEqual(len(factory.calls),2)
            self.assertEqual((result.currency_wars['completed'],result.currency_wars['victories'],result.currency_wars['defeats']),(2,0,2))

    def test_corrupt_defeat_origin_or_chain_never_proves_a_finished_match(self):
        with tempfile.TemporaryDirectory() as folder:
            report,_=finish(Path(folder));original=report.currency_wars
        for name in ('result','node','start','frames','victory','missing','target','pending','hp_kind'):
            data=deepcopy(original)
            if name=='result':data['node_attempt']['result_kind']='node_result'
            elif name=='node':data['node_attempt']['node']='2-5'
            elif name=='start':data['defeat_start_action_id']=0
            elif name=='frames':data['node_attempt']['defeat_frames']*=2
            elif name=='victory':data['match_victory_observed']=True
            elif name=='missing':data['actions'].pop()
            elif name=='target':data['actions'][-1]['target'][2]='0'*64
            elif name=='pending':data['actions'][-1]['status']='pending'
            else:data['actions'][-3]['expected']='match_rating'
            with self.subTest(name=name):self.assertFalse(settled(data))

    def test_cli_scope_defaults_and_snapshot_do_not_save_settings(self):
        from autohsr.__main__ import main
        self.assertFalse(Settings().currency_continue_after_defeat)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings().save(path);before=path.read_bytes()
            with patch('autohsr.currency_wars_loop.CurrencyLoopRunner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value={'status':'partial'}
                self.assertEqual(main(['--currency-wars-loop','--config',str(path),'--currency-continue-after-defeat']),1)
                self.assertTrue(factory.call_args.kwargs['continue_after_defeat']);self.assertEqual(path.read_bytes(),before)
            for args in (['--check'],['--plan'],['--currency-wars-standard']):
                with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(args+['--currency-continue-after-defeat'])

    def test_real_runner_dispatch_report_saving_and_two_different_outcomes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runs').mkdir();factory=ActualFactory(root,['defeat','victory'])
            with loops.real_runtime(root):
                result=CurrencyLoopRunner(Settings(overlay_logs=False),runs=2,continue_after_defeat=True,
                    root=root/'runs',runner_factory=factory).run()
            self.assertEqual(result.status,'partial',result.error)
            self.assertEqual((result.currency_wars['completed'],result.currency_wars['victories'],result.currency_wars['defeats']),(2,1,1))
            self.assertEqual([r.report.status for r in factory.children],['partial','success'])
            self.assertTrue(all(r.report.report_saved for r in factory.children))

    def test_missing_child_report_recovers_read_only_without_rewriting_it_or_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,['defeat']);original=loops._write
            def failed(path,data):
                if Path(path).name=='report.json' and Path(path).parent.name.startswith('native_'):
                    raise OSError('fixture child report write failure')
                return original(path,data)
            # finish() uses this module's writer, while the parent uses its own.
            with patch(__name__+'._write',failed):
                result=CurrencyLoopRunner(Settings(),runs=3,root=root,runner_factory=factory).run()
            self.assertEqual(result.status,'failed')
            session=StandardSession(root/'currency-standard-session.json').data
            source=Path(session['run_dir'])/'report.json';self.assertFalse(source.exists())
            forbidden=Mock(side_effect=AssertionError('read-only recovery only'))
            resumed=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
            self.assertEqual(resumed.currency_wars['status'],'defeated',resumed.error);forbidden.assert_not_called()
            self.assertFalse(source.exists())
            store=LoopStore(root);store.load();audit=json.loads((store.path.parent/(session['match_id']+'.recovery.json')).read_text('utf8'))
            self.assertTrue(audit['read_only']);self.assertEqual(audit['status'],'partial')
            self.assertFalse(audit['currency_wars']['completion_verified'])

    def test_unknown_terminal_click_is_preserved_and_never_replayed(self):
        def mutation(states):
            for i in (2,3):
                states[i].tokens=[Token('小队生命值1' if normalize(t.text)=='小队生命值0' else t.text,t.score,t.box) for t in states[i].tokens]
            del states[4:]
        timer=count(0,80)
        with tempfile.TemporaryDirectory() as folder,patch('autohsr.currency_wars_standard_flow.time',Mock(monotonic=lambda:next(timer))):
            report,c=finish(Path(folder),scene_mutation=mutation)
            self.assertEqual(c.window.click.call_count,1)
            self.assertEqual(report.currency_wars['actions'][-1]['status'],'unknown')
            self.assertFalse(settled(report.currency_wars))
            with self.assertRaises(AutomationError):require_session_access(report.currency_wars,True)

    def test_stop_after_archive_keeps_counts_and_explicit_resume_stops_without_new_game(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,['defeat'])
            runner=CurrencyLoopRunner(Settings(),lambda event:runner.stop() if event['type']=='currency_loop_progress' else None,
                runs=3,root=root,runner_factory=factory)
            result=runner.run();self.assertEqual(result.status,'stopped',result.error)
            self.assertEqual((result.currency_wars['completed'],result.currency_wars['defeats']),(1,1))
            forbidden=Mock(side_effect=AssertionError('stopped budget'))
            resumed=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
            self.assertEqual(resumed.currency_wars['status'],'defeated',resumed.error);forbidden.assert_not_called()

    def test_counter_corruption_frozen_override_and_lost_evidence_block_next_start(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,['defeat'])
            runner=CurrencyLoopRunner(Settings(),lambda event:runner.stop() if event['type']=='currency_loop_progress' else None,
                runs=2,continue_after_defeat=True,root=root,runner_factory=factory);runner.run()
            forbidden=Mock(side_effect=AssertionError('no new IO'))
            changed=CurrencyLoopRunner(Settings(),resume=True,continue_after_defeat=False,root=root,runner_factory=forbidden).run()
            self.assertNotEqual(changed.status,'success');forbidden.assert_not_called()
            store=LoopStore(root);store.load();saved=deepcopy(store.data);store.data['defeats']=0;store.save()
            changed=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
            self.assertNotEqual(changed.status,'success');forbidden.assert_not_called()
            store.data=saved;store.save()
            receipt=json.loads((store.path.parent/'1.session.receipt.json').read_text('utf8'))
            evidence=Path(next(iter(receipt['ending_evidence'])));evidence.write_bytes(b'changed synthetic source')
            changed=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
            self.assertNotEqual(changed.status,'success');forbidden.assert_not_called()

    def test_setting_roundtrip_is_strict_and_old_files_keep_default_off(self):
        from autohsr.config import SettingsError
        for value in (0,1,'true',None,[]):
            with self.subTest(value=value),self.assertRaises(SettingsError):Settings(currency_continue_after_defeat=value).validate('currency_wars')
            if value is not None:
                with self.assertRaises(ValueError):CurrencyLoopRunner(Settings(),continue_after_defeat=value)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings(currency_continue_after_defeat=True).save(path)
            self.assertTrue(Settings.load(path).currency_continue_after_defeat)
            data=json.loads(path.read_text('utf8'));data.pop('currency_continue_after_defeat');path.write_text(json.dumps(data),encoding='utf8')
            self.assertFalse(Settings.load(path).currency_continue_after_defeat)

    def test_archive_rename_crash_finishes_once_without_repeating_settlement(self):
        from autohsr import currency_wars_loop_store as storage
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,['defeat']);original=storage._immutable
            def failed(path,data):
                if str(path).endswith('.session.receipt.json'):raise OSError('fixture receipt write failure after rename')
                return original(path,data)
            with patch.object(storage,'_immutable',failed):
                first=CurrencyLoopRunner(Settings(),runs=3,root=root,runner_factory=factory).run()
            self.assertEqual(first.status,'failed')
            store=LoopStore(root);store.load();self.assertIn('archive_intent',store.data)
            archive=Path(store.data['archive_intent']['archive']);before=archive.read_bytes()
            forbidden=Mock(side_effect=AssertionError('archive recovery cannot repeat game IO'))
            resumed=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
            self.assertEqual(resumed.currency_wars['status'],'defeated',resumed.error);forbidden.assert_not_called()
            self.assertEqual((resumed.currency_wars['completed'],resumed.currency_wars['defeats']),(1,1))
            self.assertEqual(archive.read_bytes(),before)

    def test_points_check_after_a_defeat_cannot_increase_the_requested_game_ceiling(self):
        from autohsr.tests import test_currency_wars_points_goal as goals
        from autohsr.tests import test_currency_wars_points as points
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runs').mkdir();factory=goals.MixedFactory(root,[0,4500]);factory.native=ActualFactory(root,['defeat'])
            with loops.real_runtime(root),patch('autohsr.currency_wars_points_goal.local_now',return_value=points.NOW), \
                 patch('autohsr.currency_wars_points_run.local_now',return_value=points.NOW):
                report=CurrencyLoopRunner(Settings(overlay_logs=False),runs=1,until_points=True,continue_after_defeat=True,
                    root=root/'runs',runner_factory=factory).run()
            self.assertEqual(report.status,'partial',report.error)
            self.assertEqual(report.currency_wars['status'],'exhausted')
            self.assertEqual((report.currency_wars['completed'],report.currency_wars['victories'],report.currency_wars['defeats']),(1,0,1))
            self.assertEqual(factory.calls,['currency_wars_points','currency_wars_standard','currency_wars_points'])

    def test_weekly_parent_retains_defeats_and_original_daily_after_points_and_rewards(self):
        from autohsr.tests import test_currency_wars_weekly_plan as weekly
        from autohsr.currency_wars_weekly import check_complete
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=weekly.Factory(root,[0,0,9000,18000]);factory.native=ActualFactory(root,['defeat','victory'])
            config=weekly.settings(currency_continue_after_defeat=True)
            report=weekly.CurrencyWeeklyPlanTests().run_plan(root,factory,config)
            self.assertEqual(report.status,'success',report.error+' / '+report.safe_next)
            self.assertTrue(report.daily_verified);self.assertEqual(report.stamina_spent,120)
            self.assertEqual((report.currency_wars['completed'],report.currency_wars['victories'],report.currency_wars['defeats']),(2,1,1))
            self.assertEqual(report.weekly_plan['victories'],1);self.assertEqual(report.weekly_plan['defeats'],1)
            store=LoopStore(root/'runs');store.load();check_complete(store)

    def test_default_weekly_stop_then_explicit_resume_never_repeats_daily_or_adds_games(self):
        from autohsr.tests import test_currency_wars_weekly_plan as weekly
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first=weekly.Factory(root,[0,0]);first.native=ActualFactory(root,['defeat'])
            report=weekly.CurrencyWeeklyPlanTests().run_plan(root,first)
            self.assertEqual(report.status,'partial',report.error)
            self.assertTrue(report.daily_verified);self.assertNotIn('currency_wars_rewards',first.calls)
            self.assertEqual(report.currency_wars['defeats'],1)
            second=weekly.Factory(root,[0,18000]);second.native=ActualFactory(root,['victory'])
            resumed=weekly.CurrencyWeeklyPlanTests().run_plan(root,second,weekly.settings(weekly_runs=9),resume_weekly_currency=True)
            self.assertEqual(resumed.status,'success',resumed.error+' / '+resumed.safe_next)
            self.assertNotIn('daily',second.calls);self.assertEqual(second.calls.count('currency_wars_standard'),1)
            self.assertEqual((resumed.currency_wars['maximum'],resumed.currency_wars['completed'],resumed.currency_wars['defeats']),(2,2,1))
            self.assertEqual(resumed.stamina_spent,120)

    def test_final_allowed_game_can_lose_without_reopening_an_exhausted_count_goal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first=CurrencyLoopRunner(Settings(),runs=1,root=root,runner_factory=Factory(root,['defeat'])).run()
            self.assertEqual((first.status,first.currency_wars['status']),('partial','complete'),first.error)
            self.assertEqual(first.currency_wars['defeats'],1)
            forbidden=Mock(side_effect=AssertionError('no remaining games'))
            second=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
            self.assertNotEqual(second.status,'success');forbidden.assert_not_called()

    def test_unknown_financial_action_cannot_be_cleared_by_a_defeat_page(self):
        with tempfile.TemporaryDirectory() as folder:
            report,_=finish(Path(folder));data=deepcopy(report.currency_wars)
        data.update(status='active',defeat_settlement_verified=False,settlement_verified=False)
        data['actions']=data['actions'][:2]+[dict(id=2,action='buy_standard_offer',status='unknown',input_epoch=0)]
        with self.assertRaises(AutomationError):next_action(frame('match_defeat'),session=data)

    def test_unfinished_special_protocol_cannot_be_skipped_to_settlement(self):
        with tempfile.TemporaryDirectory() as folder:
            report,_=finish(Path(folder));original=deepcopy(report.currency_wars)
        for name in ('exchange','equipment','reward','consumable','investment','movement_popup','popup','reorder','sale'):
            data=deepcopy(original);data.update(status='active',defeat_settlement_verified=False,settlement_verified=False)
            data['actions']=data['actions'][:2];data[name]=dict(status='pending')
            with self.subTest(protocol=name),self.assertRaises(AutomationError):next_action(frame('match_defeat'),session=data)

    def test_defeated_nonweekly_loop_blocks_a_new_plan_before_daily(self):
        from autohsr.tests import test_currency_wars_weekly_plan as weekly
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            first=CurrencyLoopRunner(Settings(),runs=3,root=root/'runs',runner_factory=Factory(root/'runs',['defeat'])).run()
            self.assertEqual(first.currency_wars['status'],'defeated',first.error)
            store=LoopStore(root/'runs');store.load();before=store.path.read_bytes()
            new=weekly.Factory(root,[0,0]);new.native=Mock(side_effect=AssertionError('original loop budget is waiting'))
            report=weekly.CurrencyWeeklyPlanTests().run_plan(root,new)
            self.assertEqual(report.status,'failed');self.assertEqual(new.calls,[])
            self.assertEqual(store.path.read_bytes(),before)

    def test_repeat_new_weekly_start_retains_defeat_and_daily_without_new_work(self):
        from autohsr.tests import test_currency_wars_weekly_plan as weekly
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first=weekly.Factory(root,[0,0]);first.native=ActualFactory(root,['defeat'])
            original=weekly.CurrencyWeeklyPlanTests().run_plan(root,first)
            self.assertEqual(original.currency_wars['defeats'],1,original.error)
            factory=weekly.Factory(root,[]);report=weekly.CurrencyWeeklyPlanTests().run_plan(root,factory)
            self.assertEqual(factory.calls,[]);self.assertTrue(report.daily_verified);self.assertEqual(report.stamina_spent,120)
            self.assertEqual(report.currency_wars.get('defeats'),1)
            self.assertEqual(report.currency_wars.get('victories'),0)
            self.assertEqual(report.currency_wars.get('settled_games'),1)
            self.assertEqual(report.weekly_plan.get('defeats'),1);self.assertEqual(report.weekly_plan.get('victories'),0)


if __name__=='__main__':unittest.main()
