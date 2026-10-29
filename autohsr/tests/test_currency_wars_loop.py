"""Fake-window settlement integration and crash/ownership counterexamples."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid
from PIL import Image
import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings, SettingsError
from autohsr.currency_wars_identity import account_key
from autohsr.currency_wars_loop import CurrencyLoopRunner
from autohsr.currency_wars_loop_store import LoopStore, _write, loop_lock
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.models import AutomationError, RunReport, Stopped, TaskResult, Token, normalize
from autohsr.windows import Geometry
from autohsr.tests import test_currency_wars_standard_flow as flow_helpers
from autohsr.tests.test_currency_wars_node import screen
from autohsr.tests.test_currency_wars_standard_flow import ready
from autohsr.tests import test_currency_wars_standard_progress as progress_helpers


def options(runs=1):
    return dict(runs=runs, strategy='default', remembrance_name='', equipment_fast_mode=False)


GAP_CONTROLS = CurrencyLoopRunner._gap_controls


def seed_final_node(root, guard=None):
    """Existing start/node evidence is simulated; no game is accessed."""
    directory = root/('native_'+uuid.uuid4().hex[:8]); directory.mkdir()
    if guard is not None:
        guard.register_run(directory)
    store = progress_helpers.StandardProgressTests().store(root, '3-5', observed=False)
    store.data['run_dir'] = str(directory)
    policy = guard.store.data['options'] if guard is not None else options()
    store.data.update({key: policy[key] for key in ('strategy', 'remembrance_name', 'equipment_fast_mode')})
    before = directory/'simulated_start.png'; Image.new('RGB',(32,32),'gray').save(before)
    node_action=store.data['actions'][0]
    node_action.update(id=1,before=str(before), after=str(before))
    store.data['node_attempt']['start_action_id']=1
    store.data['actions']=[dict(id=0,action='start_standard_a8_40',expected='boss_preview',status='verified',
                                target=[],input_epoch=0,before=str(before),after=str(before)),node_action]
    store.persist()
    if guard is not None:
        actions = store.data['actions']
        store.data.update(status='start_pending',actions=[])
        store.persist()
        guard.bind(store)
        store.data.update(status='active',actions=actions)
        store.persist()
    return store,policy


def settled(root, guard=None):
    """Simulated final node, actual Context IO and Runner result dispatch."""
    store,policy=seed_final_node(root,guard)
    directory=Path(store.data['run_dir'])
    runner = Runner(Settings(), operation='currency_wars_standard', currency_resume=True,
                    currency_strategy=policy['strategy'], currency_remembrance_name=policy['remembrance_name'],
                    currency_fast_mode=policy['equipment_fast_mode'], currency_loop_guard=guard)
    runner.report = RunReport(operation='currency_wars_standard', run_dir=str(directory))
    c = Context(runner, Mock(), Mock()); c.checkpoint = Mock(); c.sleep = Mock(); c.log = Mock()
    states = [screen(k) for k in ('final_victory','match_rating','match_rating','match_summary','match_statistics','lobby')]
    def snapshot():
        state = states.pop(0) if states else c.last_scene
        if state.image is None:state.image=Image.new('RGB',(1920,1080),'gray')
        state.tokens = [t for t in state.tokens if not normalize(t.text).startswith('uid')]
        state.tokens.append(Token('UID:100000000', .99, (.01,.96,.10,.99)))
        state.captured_at = time.monotonic(); c.last_scene = state; c.scene_epoch = runner.input_epoch
        return state
    sequence = 0
    def evidence(state, label):
        nonlocal sequence
        sequence += 1
        path = directory/(str(sequence)+'_'+label+'.png'); state.image.save(path)
        return path
    c.snapshot = snapshot; c.evidence = evidence
    with patch('autohsr.currency_wars_replay.save_sample'):
        runner._inspect_currency_wars(c)
    if runner.report.status != 'success' or c.window.click.call_count != 4:
        raise AssertionError('native settlement did not complete')
    runner.report.report_saved = True
    _write(directory/'report.json', runner.report.to_dict())
    return runner.report


@contextmanager
def real_runtime(root):
    """Keep Runner.run/dispatch/report saving and Context IO; replace OS/vision."""
    game=root/'fake-game';game.mkdir(exist_ok=True)
    (game/'StarRail.exe').write_bytes(b'synthetic test marker; never executed')
    (game/'config.ini').write_text('[General]\ngame_version=4.6.0\n',encoding='utf-8')
    window=Mock();window.hwnd=44;window.path=str(game/'StarRail.exe')
    def snapshot(c):
        state=c.runner._loop_test_scenes.pop(0)
        state.tokens=[t for t in state.tokens if not normalize(t.text).startswith('uid')]
        state.tokens.append(Token('UID:100000000',.99,(.01,.96,.10,.99)))
        state.geometry=Geometry(0,0,1920,1080)
        state.image=np.full((1080,1920,3),80,dtype=np.uint8)
        state.captured_at=time.monotonic();c.last_scene=state;c.scene_epoch=c.runner.input_epoch
        return state
    with patch('autohsr.app.ROOT',root),patch('autohsr.windows.kernel32') as kernel, \
         patch('autohsr.app.C.get_last_error',return_value=0),patch('autohsr.app.find_game',return_value=window), \
         patch('autohsr.app.is_elevated',return_value=False),patch('autohsr.app.IsolatedVision'), \
         patch.object(Runner,'_prepare_daily_game'),patch.object(Runner,'_arm_hotkeys'), \
         patch.object(Runner,'_hotkeys'),patch.object(Runner,'checkpoint'), \
         patch.object(Context,'snapshot',snapshot),patch.object(Context,'sleep'), \
         patch('autohsr.currency_wars_replay.save_sample'):
        kernel.CreateMutexW.return_value=1
        yield window


class ActualRunnerFactory:
    def __init__(self,root):self.root=root;self.children=[]

    def __call__(self,settings,emit,**kwargs):
        # Enter a synthetic already-started final node. All subsequent native
        # dispatch, four Context inputs, report writing and archival are real.
        seed_final_node(self.root/'runs',kwargs['currency_loop_guard'])
        kwargs['currency_resume']=True
        runner=Runner(settings,emit,**kwargs)
        runner._loop_test_scenes=[screen(k) for k in
            ('final_victory','match_rating','match_rating','match_summary','match_statistics','lobby')]
        self.children.append(runner)
        return runner


class NativeFactory:
    def __init__(self, root, behavior=None):
        self.root, self.behavior, self.calls = root, behavior, []

    def __call__(self, settings, emit, **kwargs):
        self.calls.append(kwargs)
        child = Mock()
        child.toggle_pause.return_value = True
        def run():
            if self.behavior is not None:
                return self.behavior(kwargs)
            result = settled(self.root, kwargs['currency_loop_guard'])
            emit(dict(type='finished', report=result.to_dict()))
            return result
        child.run.side_effect = run
        return child


class CurrencyLoopTests(unittest.TestCase):
    def setUp(self):
        controls=patch.object(CurrencyLoopRunner,'_gap_controls')
        controls.start();self.addCleanup(controls.stop)

    def test_default_legacy_roundtrip_and_strict_run_count(self):
        self.assertEqual(Settings().currency_runs, 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.json'
            for value in (0, 1, 100):
                Settings(currency_runs=value).save(path)
                self.assertEqual(Settings.load(path).currency_runs, value)
            old = json.loads(path.read_text(encoding='utf-8')); old.pop('currency_runs')
            path.write_text(json.dumps(old), encoding='utf-8')
            self.assertEqual(Settings.load(path).currency_runs, 1)
        for value in (True, False, -1, 1.5, '2', None, 2147483648):
            with self.subTest(value=value), self.assertRaises(SettingsError) as caught:
                Settings(currency_runs=value).validate('currency_wars')
            self.assertEqual(caught.exception.field, 'currency_runs')

    def test_two_native_settlements_have_distinct_archives_and_one_parent_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); factory = NativeFactory(root); events = []
            report = CurrencyLoopRunner(Settings(), events.append, runs=2, root=root, runner_factory=factory).run()
            self.assertEqual(report.status, 'success', report.error)
            self.assertEqual(report.currency_wars['completed'], 2)
            self.assertEqual(report.currency_wars['acceptance_runs'], 0)
            self.assertFalse((root/'currency-standard-session.json').exists())
            store = LoopStore(root); store.load(); store.check_tail()
            archives = [StandardSession(store.path.parent/(str(n)+'.session.json')).data for n in (1,2)]
            self.assertNotEqual(archives[0]['match_id'], archives[1]['match_id'])
            self.assertEqual([a['loop_owner']['slot'] for a in archives], [1,2])
            self.assertEqual(sum(e['type']=='finished' for e in events), 1)
            self.assertEqual(len(factory.calls), 2)
            self.assertTrue(all(call['operation']=='currency_wars_standard' for call in factory.calls))

    def test_actual_runner_saves_success_and_loop_archives_two_separate_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=ActualRunnerFactory(root);events=[]
            with real_runtime(root) as window:
                result=CurrencyLoopRunner(Settings(overlay_logs=False),events.append,runs=2,root=root/'runs',runner_factory=factory).run()
            self.assertTrue(factory.children)
            self.assertTrue(all(child.report.currency_wars['completion_verified'] for child in factory.children))
            self.assertTrue(all(child.report.report_saved for child in factory.children))
            self.assertEqual(result.status,'success',result.error);self.assertEqual(result.currency_wars['completed'],2)
            self.assertEqual(window.click.call_count,8);self.assertEqual(len(factory.children),2)
            self.assertEqual(sum(e['type']=='finished' for e in events),1)
            for child in factory.children:
                saved=json.loads((Path(child.report.run_dir)/'report.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['status'],'success');self.assertIs(saved['report_saved'],True)
                self.assertEqual(saved['failure_task'],'');self.assertIs(saved['currency_wars']['settlement_verified'],True)
            store=LoopStore(root/'runs');store.load();store.check_tail()
            self.assertEqual(len(list(store.path.parent.glob('*.session.json'))),2)
            self.assertFalse(store.journal.exists());self.assertEqual(result.currency_wars['acceptance_runs'],0)

    def test_actual_runner_report_write_failure_keeps_completed_session_without_next_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=ActualRunnerFactory(root)
            with real_runtime(root) as window,patch('autohsr.app.replace_file',side_effect=OSError('report disk full')):
                result=CurrencyLoopRunner(Settings(overlay_logs=False),runs=2,root=root/'runs',runner_factory=factory).run()
            self.assertEqual(result.status,'partial');self.assertEqual(result.currency_wars['completed'],0)
            self.assertEqual(len(factory.children),1);self.assertEqual(window.click.call_count,4)
            self.assertFalse(factory.children[0].report.report_saved)
            store=LoopStore(root/'runs');store.load()
            self.assertEqual(StandardSession(store.journal).data['status'],'settled')
            self.assertFalse(list(store.path.parent.glob('*.session.receipt.json')))
            original_temp=Path(factory.children[0].report.run_dir)/'report.tmp';raw=original_temp.read_bytes()
            resumed_factory=ActualRunnerFactory(root)
            with real_runtime(root) as resumed_window:
                resumed=CurrencyLoopRunner(Settings(overlay_logs=False),resume=True,root=root/'runs',runner_factory=resumed_factory).run()
            self.assertEqual(resumed.status,'success',resumed.error);self.assertEqual(resumed.currency_wars['completed'],2)
            self.assertEqual(len(resumed_factory.children),1);self.assertEqual(resumed_window.click.call_count,4)
            self.assertEqual(original_temp.read_bytes(),raw)
            store.load();receipt=json.loads((store.path.parent/'1.session.receipt.json').read_text(encoding='utf-8'))
            self.assertIs(receipt['recovered'],True);store.check_tail()

    def test_partial_standard_and_observation_results_do_not_become_success_reports(self):
        full=dict(status='settled',completion_verified=True,settlement_verified=True)
        for task_status,data in (('partial',full),('success',{}),('success',dict(full,settlement_verified=False))):
            with self.subTest(task_status=task_status,data=data):
                runner=Runner(Settings(),operation='currency_wars_standard');runner.report.currency_wars=deepcopy(data)
                c=Mock(report=runner.report)
                with patch('autohsr.currency_wars_standard_flow.run_standard',return_value=TaskResult('currency_wars',task_status,'')):
                    runner._inspect_currency_wars(c)
                self.assertEqual(runner.report.status,'partial');self.assertEqual(runner.report.failure_task,'currency_wars')
        runner=Runner(Settings(),operation='currency_wars_prepare');runner.report.currency_wars=full
        with patch('autohsr.currency_wars_prepare.prepare',return_value=TaskResult('currency_wars','success','ready')):
            runner._inspect_currency_wars(Mock(report=runner.report))
        self.assertEqual(runner.report.status,'partial')

    def test_until_stopped_preserves_two_completed_matches_without_third_start(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); factory = NativeFactory(root)
            def emit(event):
                if event['type']=='currency_loop_progress' and event['data']['completed']==2:
                    runner.stop()
            runner = CurrencyLoopRunner(Settings(), emit, runs=0, root=root, runner_factory=factory)
            result = runner.run()
            self.assertEqual(result.status, 'stopped'); self.assertEqual(result.currency_wars['completed'], 2)
            self.assertEqual(result.currency_wars['requested_runs'], 0); self.assertEqual(len(factory.calls), 2)

    def test_resume_remaining_count_and_options_ignore_changed_saved_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); factory = NativeFactory(root)
            runner = CurrencyLoopRunner(Settings(), lambda event: runner.stop() if event['type']=='currency_loop_progress' else None,
                runs=2, currency_strategy='seele', currency_fast_mode=True, currency_remembrance_name=' 测试 ', root=root, runner_factory=factory)
            self.assertEqual(runner.run().currency_wars['completed'], 1)
            denied = NativeFactory(root)
            result = CurrencyLoopRunner(Settings(), root=root, runner_factory=denied).run()
            self.assertEqual(result.status, 'partial'); self.assertEqual(len(denied.calls), 0)
            second = NativeFactory(root)
            result = CurrencyLoopRunner(Settings(currency_runs=9,currency_fast_mode=False,currency_remembrance_name='新名字'), resume=True,
                                        currency_remembrance_name=' 测试 ',root=root, runner_factory=second).run()
            self.assertEqual(result.status, 'success', result.error)
            self.assertEqual(result.currency_wars['completed'], 2); self.assertEqual(len(second.calls), 1)
            self.assertEqual(second.calls[0]['currency_strategy'], 'seele'); self.assertIs(second.calls[0]['currency_fast_mode'], True)
            self.assertEqual(second.calls[0]['currency_remembrance_name'], '测试')

    def test_partial_unknown_and_missing_report_never_start_second_match(self):
        for case in ('partial', 'unknown', 'report'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                def behavior(kwargs):
                    report = settled(root, kwargs['currency_loop_guard'])
                    if case=='report':
                        (Path(report.run_dir)/'report.json').unlink(); report.report_saved=False
                    elif case=='unknown':
                        store = StandardSession(root/'currency-standard-session.json')
                        store.data['actions'][-1]['status']='unknown'; store.persist()
                    else:
                        report.status='partial'
                    return report
                factory = NativeFactory(root, behavior)
                result = CurrencyLoopRunner(Settings(), runs=2, root=root, runner_factory=factory).run()
                self.assertNotEqual(result.status, 'success'); self.assertEqual(len(factory.calls), 1)
                self.assertTrue((root/'currency-standard-session.json').exists())
                self.assertEqual(result.currency_wars['completed'], 0)

    def test_archive_crash_after_rename_is_recovered_read_only_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); factory = NativeFactory(root)
            with patch('autohsr.currency_wars_loop_store._immutable', side_effect=OSError('receipt write interrupted')):
                failed = CurrencyLoopRunner(Settings(), root=root, runner_factory=factory).run()
            self.assertEqual(failed.currency_wars['completed'], 0); self.assertFalse((root/'currency-standard-session.json').exists())
            forbidden = NativeFactory(root)
            resumed = CurrencyLoopRunner(Settings(), resume=True, root=root, runner_factory=forbidden).run()
            self.assertEqual(resumed.status, 'success', resumed.error); self.assertEqual(resumed.currency_wars['completed'], 1)
            self.assertEqual(len(forbidden.calls), 0)
            store = LoopStore(root); store.load(); store.check_tail()
            again = CurrencyLoopRunner(Settings(), resume=True, root=root, runner_factory=forbidden).run()
            self.assertEqual(again.status, 'partial'); self.assertEqual(len(forbidden.calls), 0)

    def test_explicit_resume_can_audit_saved_settlement_without_rewriting_failed_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def behavior(kwargs):
                result = settled(root, kwargs['currency_loop_guard'])
                result.report_saved=False; result.status='failed'; _write(Path(result.run_dir)/'report.json',result.to_dict())
                return result
            result = CurrencyLoopRunner(Settings(), root=root, runner_factory=NativeFactory(root,behavior)).run()
            store = LoopStore(root); store.load(); original = Path(store.data['active']['latest_run_dir'])/'report.json'
            raw = original.read_bytes(); forbidden = NativeFactory(root)
            resumed = CurrencyLoopRunner(Settings(), resume=True, root=root, runner_factory=forbidden).run()
            self.assertEqual(resumed.status,'success',resumed.error); self.assertEqual(original.read_bytes(), raw)
            self.assertEqual(len(forbidden.calls),0); self.assertEqual(resumed.currency_wars['completed'],1)
            store.load(); receipt=json.loads((store.path.parent/'1.session.receipt.json').read_text(encoding='utf-8'))
            self.assertIs(receipt['recovered'],True)

    def test_prior_single_match_archived_without_becoming_a_loop_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); old=settled(root)
            result=CurrencyLoopRunner(Settings(),root=root,runner_factory=NativeFactory(root)).run()
            self.assertEqual(result.status,'success',result.error); self.assertEqual(result.currency_wars['completed'],1)
            store=LoopStore(root);store.load()
            prior=list(store.path.parent.glob('prior-*.session.json')); self.assertEqual(len(prior),1)
            self.assertEqual(StandardSession(prior[0]).data['match_id'],old.currency_wars['match_id'])

    def test_existing_unowned_active_and_explicit_override_conflict_block_before_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); session=progress_helpers.StandardProgressTests().store(root)
            original=session.path.read_bytes(); factory=NativeFactory(root)
            result=CurrencyLoopRunner(Settings(),root=root,runner_factory=factory).run()
            self.assertEqual(result.status,'failed');self.assertEqual(session.path.read_bytes(),original);self.assertEqual(len(factory.calls),0)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=LoopStore(root);store.begin(options(2))
            for changes in (dict(runs=3),dict(currency_strategy='seele'),dict(currency_fast_mode=True),dict(currency_remembrance_name='测试')):
                with self.subTest(changes=changes):
                    factory=NativeFactory(root)
                    result=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=factory,**changes).run()
                    self.assertEqual(result.status,'failed');self.assertEqual(len(factory.calls),0)

    def test_flags_alone_broken_chain_missing_file_and_unknown_ledger_do_not_grant_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report=settled(root);store=LoopStore(root);store.begin(options())
            original=StandardSession(store.journal).data
            def missing_file(data):data['actions'][-1]['after']=str(root/'missing.png')
            def broken_chain(data):data['actions'][-2]['target']=['3-5',77]
            def unknown(data):data['actions'][0]['status']='unknown'
            def no_provenance(data):data['node_attempt']['node_verified']=False
            def no_start_source(data):data['actions'][0].update(action='advance_standard_preview',expected='plane_map')
            def pending_protocol(data):data['reward']=dict(status='unit_verifying')
            for change in (missing_file,broken_chain,unknown,no_provenance,no_start_source,pending_protocol):
                with self.subTest(change=change.__name__):
                    data=deepcopy(original);change(data)
                    journal=StandardSession(store.journal);journal.data=data;journal.persist()
                    report.currency_wars=data;_write(Path(report.run_dir)/'report.json',report.to_dict())
                    with self.assertRaises(AutomationError):store.archive(count=False)
                    self.assertTrue(store.journal.exists());self.assertEqual(store.data['completed'],0)

    def test_empty_owned_start_is_reidentified_but_unknown_start_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=LoopStore(root);store.begin(options());guard=store.reserve()
            directory=root/'child';directory.mkdir();guard.register_run(directory)
            journal=StandardSession(store.journal);journal.begin(directory,dict(rank_verified=True))
            journal.data.update(strategy='default',remembrance_name='',equipment_fast_mode=False);journal.persist()
            guard.require_access(journal.data);guard.bind(journal)
            self.assertEqual(StandardSession(store.journal).data['loop_owner'],guard.owner)
            journal.pending('start_standard_a8_40',0,str(directory/'before.png'),'boss_preview')
            with self.assertRaises(AutomationError):guard.require_access(journal.data)
            with self.assertRaises(AutomationError):guard.require_access(journal.data,resume=True)

    def test_input_binds_account_before_first_click_and_refuses_changed_account_next_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=LoopStore(root);store.begin(options(2));guard=store.reserve()
            directory=root/'child';directory.mkdir();guard.register_run(directory)
            journal=StandardSession(store.journal);journal.begin(directory,dict(rank_verified=True))
            journal.data.update(strategy='default',remembrance_name='',equipment_fast_mode=False,account_key=account_key(ready()));journal.persist();guard.bind(journal)
            state=ready();choice=next_action(state);journal.pending(choice.intent,0,str(directory/'before.png'),choice.expected)
            runner=Runner(Settings(),operation='currency_wars_standard',currency_loop_guard=guard)
            c=Context(runner,Mock(),Mock());c.currency_standard_session=journal;c.last_scene=state;c.sleep=Mock();c.checkpoint=Mock()
            c.window.click.side_effect=lambda *args: self.assertEqual(LoopStore(root).load()['account_key'],account_key(state))
            c.currency_standard_input(state,choice);c.window.click.assert_called_once()
            state.tokens=[t for t in state.tokens if not normalize(t.text).startswith('uid')]+[Token('UID:200000000',.99,(.01,.96,.10,.99))]
            # Simulate a newly bound native session for the other account. The
            # native per-session test passes, but the loop identity must refuse.
            journal.data['account_key']=account_key(state);journal.persist();c.last_scene=state;c.window.click.reset_mock()
            with self.assertRaisesRegex(AutomationError,'账号'):c.currency_standard_input(state,choice)
            c.window.click.assert_not_called()

    def test_changed_owner_or_manifest_does_not_authorize_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=LoopStore(root);store.begin(options());guard=store.reserve()
            directory=root/'child';directory.mkdir();guard.register_run(directory)
            journal=StandardSession(store.journal);journal.begin(directory,dict(rank_verified=True));guard.bind(journal)
            journal.pending('start_standard_a8_40',0,'before.png','boss_preview')
            altered=deepcopy(journal.data);altered['loop_owner']['reservation_id']='f'*32
            journal.path.write_text(json.dumps(altered),encoding='utf-8')
            with self.assertRaises(AutomationError):journal.require_pending('start_standard_a8_40',0)
            data=json.loads(store.path.read_text(encoding='utf-8'));data['options']['runs']=2;_write(store.path,data)
            with self.assertRaises(AutomationError):guard.authorize(ready(),journal.data,.85)

    def test_os_lock_is_exclusive_and_released_after_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaisesRegex(RuntimeError,'fixture'),loop_lock(root):
                with self.assertRaises(AutomationError),loop_lock(root):pass
                raise RuntimeError('fixture')
            with loop_lock(root):pass

    def test_new_native_start_freezes_loop_owner_before_first_proposal_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=LoopStore(root);policy=options();policy['equipment_fast_mode']=True
            store.begin(policy);guard=store.reserve();c=flow_helpers.StandardFlowTests().context(root,[ready()])
            guard.register_run(c.report.run_dir);c.runner.currency_loop_guard=guard;c.runner.currency_fast_mode=True
            def before_input(scene,choice):
                saved=c.currency_standard_session.require_pending(choice.intent,0)
                self.assertEqual(saved['loop_owner'],guard.owner);self.assertIs(saved['equipment_fast_mode'],True)
                guard.authorize(scene,saved,.85)
                raise Stopped('fixture stops before input')
            c.currency_standard_input.side_effect=before_input
            with patch('autohsr.currency_wars_standard_flow.locate',flow_helpers.StandardFlowTests().locate), \
                 patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            self.assertEqual(LoopStore(root).load()['active']['match_id'],c.currency_standard_session.data['match_id'])
            c.currency_standard_input.assert_called_once()

    def test_loop_preflight_denies_unowned_match_before_game_prepare_or_hotkeys(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runs=root/'runs';store=LoopStore(runs);store.begin(options());guard=store.reserve()
            progress_helpers.StandardProgressTests().store(runs)
            runner=Runner(Settings(),operation='currency_wars_standard',currency_resume=True,currency_loop_guard=guard)
            with patch('autohsr.app.ROOT',root),patch('autohsr.windows.kernel32') as kernel, \
                 patch('autohsr.app.C.get_last_error',return_value=0),patch.object(runner,'_prepare_daily_game') as prepare, \
                 patch.object(runner,'_arm_hotkeys') as hotkeys,patch('autohsr.app.find_game') as find:
                kernel.CreateMutexW.return_value=1;report=runner.run()
            self.assertEqual(report.status,'failed');prepare.assert_not_called();find.assert_not_called();hotkeys.assert_not_called()

    def test_account_binding_write_failure_prevents_formal_context_click(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=LoopStore(root);store.begin(options());guard=store.reserve()
            directory=root/'child';directory.mkdir();guard.register_run(directory)
            journal=StandardSession(store.journal);journal.begin(directory,dict(rank_verified=True))
            journal.data['account_key']=account_key(ready());journal.persist();guard.bind(journal)
            state=ready();choice=next_action(state);journal.pending(choice.intent,0,'before.png',choice.expected)
            c=Context(Runner(Settings(),operation='currency_wars_standard',currency_loop_guard=guard),Mock(),Mock())
            c.currency_standard_session=journal;c.last_scene=state;c.checkpoint=Mock();c.sleep=Mock()
            with patch('autohsr.currency_wars_loop_store._write',side_effect=OSError('disk full')),self.assertRaises(OSError):
                c.currency_standard_input(state,choice)
            c.window.click.assert_not_called();self.assertIsNone(LoopStore(root).load()['account_key'])
            self.assertEqual(StandardSession(store.journal).data['actions'][-1]['status'],'pending')

    def test_changed_archive_receipt_or_ending_evidence_blocks_next_match(self):
        for case in ('archive','receipt','evidence'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);factory=NativeFactory(root)
                runner=CurrencyLoopRunner(Settings(),lambda event: runner.stop() if event['type']=='currency_loop_progress' else None,
                                          runs=2,root=root,runner_factory=factory)
                self.assertEqual(runner.run().currency_wars['completed'],1)
                store=LoopStore(root);store.load();receipt_path=store.path.parent/'1.session.receipt.json'
                receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
                path=Path(receipt['archive']) if case=='archive' else receipt_path if case=='receipt' else Path(next(iter(receipt['ending_evidence'])))
                with path.open('ab') as stream:stream.write(b'changed')
                raw=path.read_bytes();forbidden=NativeFactory(root)
                result=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
                self.assertNotEqual(result.status,'success');self.assertEqual(len(forbidden.calls),0);self.assertEqual(path.read_bytes(),raw)

    def test_archive_recovery_refuses_ambiguous_sources_and_changed_destination_intent(self):
        for case in ('both','destination'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                with patch('autohsr.currency_wars_loop_store._immutable',side_effect=OSError('fixture')):
                    CurrencyLoopRunner(Settings(),root=root,runner_factory=NativeFactory(root)).run()
                store=LoopStore(root);store.load();archive=Path(store.data['archive_intent']['archive']);raw=archive.read_bytes()
                if case=='both':store.journal.write_bytes(raw)
                else:
                    store.data['archive_intent']['archive']=str(root/'unrelated.json');store.save()
                forbidden=NativeFactory(root);result=CurrencyLoopRunner(Settings(),resume=True,root=root,runner_factory=forbidden).run()
                self.assertNotEqual(result.status,'success');self.assertEqual(result.currency_wars['completed'],0)
                self.assertEqual(archive.read_bytes(),raw);self.assertEqual(len(forbidden.calls),0)
                if case=='both':self.assertEqual(store.journal.read_bytes(),raw)

    def test_gap_hotkeys_pause_only_foreground_game_and_forward_stop_to_child(self):
        for active,foreground in ((False,44),(False,45),(True,44)):
            with self.subTest(active=active,foreground=foreground):
                events=[];runner=CurrencyLoopRunner(Settings(),events.append);runner._control_hwnd=44
                child=Mock() if active else None;runner.child=child
                runner._monitor_end=Mock();runner._monitor_end.wait.side_effect=[False,False,True]
                with patch('autohsr.windows.user32') as user:
                    user.GetAsyncKeyState.side_effect=[0,0,0,1] if active else [0,0,0x8000,0,0,1]
                    user.GetForegroundWindow.return_value=foreground;GAP_CONTROLS(runner)
                self.assertTrue(runner._stop.is_set())
                self.assertEqual(runner._paused,not active and foreground==44)
                if active:
                    child.stop.assert_called_once();child.toggle_pause.assert_not_called()
                    self.assertEqual([call.args[0] for call in user.GetAsyncKeyState.call_args_list],[0x78,0x79,0x79,0x79])

    def test_pause_between_matches_and_stop_before_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=NativeFactory(root);runner=CurrencyLoopRunner(Settings(),root=root,runner_factory=factory)
            self.assertTrue(runner.toggle_pause());thread=threading.Thread(target=runner.run);thread.start()
            time.sleep(.05);self.assertEqual(len(factory.calls),0);runner.stop();thread.join(3)
            self.assertFalse(thread.is_alive());self.assertEqual(runner.report.status,'stopped');self.assertEqual(len(factory.calls),0)

    def test_cli_scope_dispatch_and_temporary_count_never_save_settings(self):
        from autohsr.__main__ import main
        for argv in (['--run','--currency-runs','2'],['--currency-wars-standard','--resume-currency-loop'],['--currency-wars-loop','--resume-active-currency']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(argv)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings().save(path);raw=path.read_bytes()
            with patch('autohsr.currency_wars_loop.CurrencyLoopRunner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value=dict(status='partial')
                main(['--currency-wars-loop','--currency-runs','0','--currency-strategy','seele','--currency-fast-mode','--config',str(path)])
            self.assertEqual(factory.call_args.kwargs['runs'],0);self.assertEqual(factory.call_args.kwargs['currency_strategy'],'seele')
            self.assertIs(factory.call_args.kwargs['currency_fast_mode'],True);self.assertEqual(path.read_bytes(),raw)


if __name__=='__main__':
    unittest.main()
