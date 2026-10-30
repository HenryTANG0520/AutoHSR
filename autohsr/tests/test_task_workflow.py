"""Task-tree contracts using fake game workers and real local record files."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, TaskResult, Scene, Token
import numpy as np
from autohsr.task_workflow import WorkflowError, compile_recipe, loads, task_spec
from autohsr.task_workflow_run import TaskWorkflowRunner
from autohsr.workflow_lease import require_workflow_access, workflow_lease


def identity_scene(identity='100000000'):
    captured = time.monotonic()
    while captured <= getattr(identity_scene, '_last_capture', -1):
        time.sleep(.001)
        captured = time.monotonic()
    identity_scene._last_capture = captured
    return Scene([Token('UID:' + identity, .99, (.01, .96, .15, .99))],
                 image=np.zeros((100, 200, 3), dtype=np.uint8), captured_at=captured)


def task(identity, operation='daily', **params):
    return dict(id=identity, type='task', task=operation, params=params)


def recipe(*steps):
    return dict(version=1, name='离线合成任务计划', steps=list(steps))


def condition(identity, field='status', value='success', op='eq'):
    return dict(step=identity, field=field, op=op, value=value)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.calls, self.events = [], []
        self.responses = []
        self.child_index = 0
        self.after_child = None
        self.owner = None
        self.accounts = []
        self.settings = Settings()
        self.hotkeys = patch.object(TaskWorkflowRunner, '_hotkeys', lambda runner: runner._end.wait())
        self.hotkeys.start()
        self.addCleanup(self.hotkeys.stop)

    def factory(self, settings, emit, **options):
        owner = self
        class Child:
            paused = False
            _control_hwnd = 1234
            stopped = False
            input_epoch = 0
            def stop(self):
                self.stopped = True
            def toggle_pause(self):
                self.paused = not self.paused
                emit(dict(type='paused', paused=self.paused))
                return self.paused
            def run(self):
                # Intent has reached disk before any game worker may act.
                log = Path(owner.owner.report.run_dir) / 'steps.jsonl'
                self_intent = json.loads(log.read_text('utf8').splitlines()[-1])
                owner.assertEqual(self_intent['event'], 'intent')
                require_workflow_access()
                operation = options.get('operation', 'currency_wars_loop')
                values = owner.responses.pop(0) if owner.responses else {}
                owner.child_index += 1
                folder = owner.root / ('child-' + str(owner.child_index))
                folder.mkdir()
                result = RunReport(operation=operation, status='success', report_saved=True, run_dir=str(folder)).to_dict()
                from autohsr.workflow_identity import _scope
                scope = _scope.get()
                fake = SimpleNamespace(runner=self, report=SimpleNamespace(run_dir=str(folder)),
                                       settings=settings, scene_epoch=0)
                identity = owner.accounts.pop(0) if owner.accounts else '100000000'
                scope.observe(fake, identity_scene(identity))
                time.sleep(.02)
                scope.observe(fake, identity_scene(identity))
                owner.calls.append((replace(settings), deepcopy(options)))
                if operation == 'daily':
                    result.update(stamina_spent=120, daily_verified=True, battle_completed=3)
                if operation == 'differential_universe':
                    result['differential_universe'] = dict(completed_runs=options['du_runs'])
                result.update(values)
                raw = json.dumps(result, ensure_ascii=False).encode('utf8')
                (folder / 'report.json').write_bytes(raw)
                emit(dict(type='finished', report=result))
                if owner.after_child:
                    owner.after_child(self, result)
                return result
        return Child()

    def runner(self, document, **options):
        self.owner = TaskWorkflowRunner(self.settings, document, self.events.append, root=self.root / 'runs',
                                        base_dir=self.root, runner_factory=self.factory,
                                        plan_factory=self.factory, currency_factory=self.factory, **options)
        return self.owner

    def test_daily_then_du_has_one_budget_and_one_parent_finished(self):
        document = recipe(task('daily', tasks=['battle', 'daily'], stamina_limit=120),
                          task('du', 'differential_universe', runs=2))
        original = deepcopy(document)
        runner = self.runner(document)
        document['steps'][0]['params']['stamina_limit'] = 240
        report = runner.run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(report.stamina_spent, 120)
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.differential_universe['completed_runs'], 2)
        self.assertEqual(self.calls[0][0].stamina_limit, 120)
        self.assertFalse(self.calls[0][0].assignments)
        self.assertFalse(self.calls[1][0].differential_universe_daily)
        self.assertFalse(self.calls[1][0].differential_universe_save)
        self.assertEqual(sum(event['type'] == 'finished' for event in self.events), 1)
        data = json.loads((Path(report.run_dir) / 'report.json').read_text('utf8'))
        self.assertEqual(data, report.to_dict())
        self.assertEqual(json.loads((Path(report.run_dir) / 'workflow.json').read_text('utf8')), original)
        for entry in report.workflow['steps']:
            raw = Path(entry['source']['path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['source']['sha256'])
        with self.assertRaises(WorkflowError):
            runner.run()

    def test_unsaved_stopped_child_halts_flow_before_source_validation_can_mask_stop(self):
        first=task('first',tasks=['daily']);first['on_failure']='continue'
        self.responses=[dict(status='stopped',report_saved=False)]
        runner=self.runner(recipe(first,dict(id='after',type='wait',seconds=0)))
        report=runner.run()
        self.assertTrue(runner.stop_requested)
        self.assertEqual(report.status,'stopped')
        self.assertTrue(report.report_saved)
        self.assertEqual(len(report.workflow['steps']),1)
        self.assertEqual(report.workflow['steps'][0]['status'],'partial')
        original=json.loads((self.root/'child-1'/'report.json').read_text('utf8'))
        self.assertEqual(original['status'],'stopped')
        self.assertFalse(original['report_saved'])

    def test_parent_save_failure_keeps_stop_control_intent_separate_from_partial_report(self):
        self.responses=[dict(status='stopped')]
        runner=self.runner(recipe(task('first',tasks=['daily'])))
        save=runner._save
        def fail_final_save():
            if runner.report.finished_at:
                raise OSError('synthetic final report write failure')
            save()
        with patch.object(runner,'_save',side_effect=fail_final_save):
            report=runner.run()
        self.assertTrue(runner.stop_requested)
        self.assertEqual(report.status,'partial')
        self.assertFalse(report.report_saved)
        self.assertEqual(json.loads((self.root/'child-1'/'report.json').read_text('utf8'))['status'],'stopped')

    def test_child_control_intent_survives_partial_unsaved_status(self):
        self.responses=[dict(status='partial',report_saved=False)]
        self.after_child=lambda child,result:setattr(child,'stop_requested',True)
        runner=self.runner(recipe(task('first',tasks=['daily']),dict(id='after',type='wait',seconds=0)))
        report=runner.run()
        self.assertTrue(runner.stop_requested)
        self.assertEqual(report.status,'partial')
        self.assertTrue(report.report_saved)
        self.assertEqual(len(report.workflow['steps']),1)
        self.assertEqual(report.workflow['steps'][0]['status'],'partial')
        self.assertTrue(report.workflow['steps'][0].get('error'))
        original=json.loads((self.root/'child-1'/'report.json').read_text('utf8'))
        self.assertEqual(original['status'],'partial')
        self.assertFalse(original['report_saved'])

    def test_budget_cannot_be_multiplied_by_repeated_or_nested_tasks(self):
        invalid = [recipe(task('a'), task('b')),
                   recipe(dict(id='loop', type='for', count=2, steps=[task('a')])),
                   recipe(task('plan', 'plan'), task('du', 'differential_universe')),
                   recipe(task('cw', 'currency_wars_loop'), task('cw2', 'currency_wars_loop'))]
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(WorkflowError):
                compile_recipe(document)
        self.assertEqual(self.calls, [])

    def test_exclusive_branches_reserve_maximum_not_two_daily_budgets(self):
        document = recipe(task('points', 'currency_wars_points'), dict(id='choose', type='if',
            condition=condition('points', 'points_verified', True), steps=[task('a')], else_steps=[task('b')]))
        self.responses = [dict(currency_wars=dict(points_verified=False))]
        runner = self.runner(document)
        self.assertEqual(runner.recipe.profile['daily_calls'], 1)
        report = runner.run()
        self.assertEqual(report.status, 'success')
        self.assertEqual([e['step'] for e in report.workflow['steps']], ['points', 'choose', 'b'])

    def test_unknown_or_skipped_condition_does_not_authorize_game(self):
        for first in (dict(id='skip', type='wait', seconds=0), dict(task('skip'), enabled=False)):
            self.calls.clear()
            report = self.runner(recipe(first, dict(id='choose', type='if',
                condition=condition('skip', 'daily_verified', True), steps=[task('never')]))).run()
            self.assertEqual(report.status, 'partial')
            self.assertEqual(self.calls, [])

    def test_unobserved_daily_default_is_not_a_condition_fact(self):
        runner = self.runner(recipe(dict(id='wait', type='wait', seconds=0)))
        for operation in ('currency_wars_points', 'differential_universe', 'daily'):
            report = RunReport(operation=operation).to_dict()
            self.assertNotIn('daily_verified', runner._facts(report))
        report = RunReport(operation='daily', results=[TaskResult('daily', 'partial', '合成未核实')]).to_dict()
        self.assertIs(runner._facts(report)['daily_verified'], False)
        report = RunReport(operation='plan', daily_verified=True).to_dict()
        self.assertIs(runner._facts(report)['daily_verified'], True)

    def test_game_partial_continues_local_steps_but_blocks_later_input(self):
        first = dict(task('daily'), on_failure='continue')
        self.responses = [dict(status='partial', daily_verified=True, stamina_pending=10)]
        report = self.runner(recipe(first, dict(id='wait', type='wait', seconds=0),
                                    task('du', 'differential_universe'))).run()
        self.assertEqual(report.status, 'partial')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_pending, 10)
        self.assertTrue(report.workflow['input_blocked'])
        self.assertEqual(report.workflow['steps'][1]['status'], 'success')

    def test_failure_default_stops_without_retry(self):
        self.responses = [dict(status='failed')]
        report = self.runner(recipe(task('daily'), dict(id='never', type='wait', seconds=0))).run()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(report.workflow['steps']), 1)
        self.assertEqual(report.status, 'partial')

    def test_changed_or_unsaved_child_report_cannot_advance(self):
        for issue in ('changed', 'unsaved'):
            self.calls.clear()
            if issue == 'unsaved':
                self.responses = [dict(report_saved=False)]
                self.after_child = None
            else:
                def change(child, result):
                    Path(result['run_dir'], 'report.json').write_text('{}', 'utf8')
                self.after_child = change
            report = self.runner(recipe(task('daily'), task('du', 'differential_universe'))).run()
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(report.status, 'partial')
            self.assertFalse(report.daily_verified)

    def test_stop_after_completed_child_preserves_daily_and_does_not_start_du(self):
        self.after_child = lambda child, result: self.owner.stop()
        report = self.runner(recipe(task('daily'), task('du', 'differential_universe'))).run()
        self.assertEqual(report.status, 'stopped')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_spent, 120)

    def test_pause_and_stop_are_transmitted_to_live_worker(self):
        observed = []
        def controls(child, result):
            observed.append(self.owner.toggle_pause())
            self.owner.stop()
            observed.append(child.stopped)
        self.after_child = controls
        report = self.runner(recipe(task('daily'))).run()
        self.assertEqual(report.status, 'stopped')
        self.assertEqual(observed, [True, True])

    def test_paused_gap_does_not_start_next_worker(self):
        paused = threading.Event()
        def pause_after(child, result):
            self.owner.toggle_pause()
            paused.set()
        self.after_child = pause_after
        runner = self.runner(recipe(task('daily'), task('du', 'differential_universe')))
        worker = threading.Thread(target=runner.run)
        worker.start()
        try:
            self.assertTrue(paused.wait(5))
            self.assertEqual(len(self.calls), 1)
            runner.stop()
        finally:
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(runner.report.status, 'stopped')

    def test_loop_continue_break_and_bound_are_distinct(self):
        loop = dict(id='loop', type='for', count=3, steps=[dict(id='again', type='continue'),
                    task('never', 'currency_wars_points')])
        report = self.runner(recipe(loop)).run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(len(self.calls), 0)
        self.assertEqual(report.workflow['steps'][0]['iterations'], 3)
        loop['steps'][0] = dict(id='breakHere', type='break')
        report = self.runner(recipe(loop)).run()
        self.assertEqual(report.workflow['steps'][0]['iterations'], 1)

    def test_while_observes_last_task_and_stops_when_condition_changes(self):
        self.responses = [dict(currency_wars=dict(points_verified=False)),
                          dict(currency_wars=dict(points_verified=True))]
        document = recipe(task('initial', 'currency_wars_points'), dict(id='poll', type='while', max_iterations=3,
            condition=condition('@last', 'points_verified', False), steps=[task('again', 'currency_wars_points')]))
        report = self.runner(document).run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(len(self.calls), 2)
        self.responses = [dict(currency_wars=dict(points_verified=False))] * 4
        self.calls.clear()
        report = self.runner(document).run()
        self.assertEqual(report.status, 'partial')
        self.assertEqual(len(self.calls), 4)
        self.assertIn('上限', report.error)

    def test_selected_step_does_not_run_ancestors_or_predecessors(self):
        document = recipe(task('daily'), dict(id='repeat', type='for', count=2,
            steps=[task('du', 'differential_universe', runs=2)]))
        report = self.runner(document, selected_path='1\\0').run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]['operation'], 'differential_universe')
        self.assertEqual(report.workflow['selected_path'], [1, 0])
        self.assertEqual(self.owner.recipe.profile['du_calls'], 1)

    def test_intent_write_failure_prevents_child_creation(self):
        runner = self.runner(recipe(task('daily')))
        with patch.object(runner, '_record', side_effect=OSError('合成磁盘失败')):
            report = runner.run()
        self.assertEqual(self.calls, [])
        self.assertEqual(report.status, 'partial')

    def test_parent_write_failure_prevents_later_input_and_preserves_child(self):
        def break_save(child, result):
            self.owner._save = Mock(side_effect=OSError('合成报告失败'))
        self.after_child = break_save
        report = self.runner(recipe(task('daily'), task('du', 'differential_universe'))).run()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(report.report_saved)
        self.assertEqual(report.status, 'partial')
        self.assertTrue(Path(self.root, 'child-1', 'report.json').exists())

    def test_currency_counts_survive_following_points_and_rewards(self):
        self.responses = [dict(currency_wars=dict(completed=2, victories=1, defeats=1)),
                          dict(currency_wars=dict(points_verified=True)),
                          dict(currency_wars=dict(rewards_verified=True))]
        report = self.runner(recipe(task('cw', 'currency_wars_loop', runs=2),
            task('points', 'currency_wars_points'), task('rewards', 'currency_wars_rewards'))).run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(report.workflow['currency_results'][0]['defeats'], 1)
        self.assertEqual(report.workflow['steps'][0]['facts']['completed_runs'], 2)
        self.assertEqual(self.calls[0][1]['runs'], 2)

    def test_plan_and_native_settings_overrides_are_transient(self):
        document = compile_recipe(recipe(task('daily', tasks=['daily']))).steps[0]
        before = deepcopy(self.settings)
        setting, options = task_spec(replace(self.settings, echo_of_war_enabled=True), document, self.root)
        self.assertFalse(setting.battle)
        self.assertEqual(self.settings, before)
        self.assertEqual(options['operation'], 'daily')
        document = compile_recipe(recipe(task('plan', 'plan', use_power_plan=True))).steps[0]
        setting, options = task_spec(replace(self.settings, echo_of_war_enabled=True), document, self.root)
        self.assertTrue(options['use_power_plan'])
        self.assertEqual(self.settings, before)

    def test_daily_without_task_overrides_keeps_current_disabled_battle(self):
        self.settings = Settings(assignments=False, battle=False, daily=True, mail=True)
        report = self.runner(recipe(task('daily'))).run()
        self.assertEqual(report.status, 'success')
        frozen = self.calls[0][0]
        self.assertFalse(frozen.battle)
        self.assertFalse(frozen.assignments)
        self.assertTrue(frozen.daily)
        self.assertTrue(frozen.mail)
        self.assertFalse(frozen.battlepass)

    def test_anonymous_identity_event_precedes_game_actions(self):
        owner = self
        class Actions(list):
            def append(self, value):
                owner.assertTrue(any(event.get('type') == 'workflow_identity' and event.get('verified') is True
                                     for event in owner.events))
                super().append(value)
        self.calls = Actions()
        report = self.runner(recipe(task('daily'))).run()
        self.assertEqual(report.status, 'success')
        private = json.loads(Path(report.run_dir, 'identity', 'state.json').read_text('utf8'))
        state_events = [event for event in self.events if event.get('type') == 'workflow_identity']
        self.assertNotIn(private['account_key'], json.dumps(state_events))
        self.assertNotIn('100000000', json.dumps(state_events))

    def test_real_local_warp_analysis_and_export_keep_sources_and_privacy(self):
        source = self.root / 'source.json'
        source.write_text(json.dumps(dict(info=dict(uid='100000000', lang='zh-cn', srgf_version='v1.0',
            region_time_zone=8), list=[dict(id='9007199254740993001', gacha_type='11',
            time='2026-10-29 12:34:56', name='虚构角色', rank_type='5', count='1',
            gacha_id='1001', item_id='1000')]), ensure_ascii=False), 'utf8')
        original = source.read_bytes()
        report = self.runner(recipe(task('analysis', 'warp_analysis', imports=['source.json']),
            task('export', 'warp_export', imports=['source.json'], output='new.json'))).run()
        self.assertEqual(report.status, 'success', report.error)
        self.assertEqual(source.read_bytes(), original)
        exported = json.loads((self.root / 'new.json').read_text('utf8'))
        self.assertEqual(exported['hkrpg'][0]['list'][0]['id'], '9007199254740993001')
        public = json.dumps(self.events, ensure_ascii=False)
        self.assertNotIn('100000000', public)
        self.assertNotIn('虚构角色', public)
        self.assertEqual(self.calls, [])

    def test_strict_json_schema_controls_and_size_limits(self):
        for raw in ('{"version":1,"version":1}', '{"value":NaN}', '[' * 2000, '\ud800'):
            with self.assertRaises(WorkflowError):
                loads(raw)
        with self.assertRaises(WorkflowError):
            loads(b'x' * (1024 * 1024 + 1))
        bad = [recipe(dict(id='x', type='click_crop', crop=[0, 0, 1, 1])),
               recipe(dict(id='x', type='break')), recipe(task('x', 'currency_wars_loop', runs=0)),
               recipe(dict(id='same', type='for', count=1, steps=[dict(id='same', type='wait', seconds=0)])),
               recipe(dict(id='x', type='for', count=True, steps=[dict(id='w', type='wait', seconds=0)])),
               recipe(task('x', tasks=[[]])), recipe(task('x', arbitrary_script='no'))]
        for document in bad:
            with self.subTest(document=document), self.assertRaises(WorkflowError):
                compile_recipe(document)

    def test_disabled_nodes_still_count_toward_expansion_limit(self):
        document = recipe(dict(id='loop', type='for', count=1000,
            steps=[dict(id='skip' + str(i), type='wait', enabled=False, seconds=0) for i in range(11)]))
        with self.assertRaises(WorkflowError):
            compile_recipe(document)

    def test_selected_control_with_missing_predecessor_fails_before_game(self):
        document = recipe(task('initial', 'currency_wars_points'), dict(id='gate', type='if',
            condition=condition('initial'), steps=[task('daily')]))
        report = self.runner(document, selected_path='1').run()
        self.assertEqual(report.status, 'partial')
        self.assertEqual(self.calls, [])

    def test_cli_validation_does_not_read_config_record_inputs_or_start_gui(self):
        from autohsr.__main__ import main
        source = self.root / 'recipe.json'
        source.write_text(json.dumps(recipe(task('records', 'warp_analysis', imports=['missing.json']))), 'utf8')
        with patch('autohsr.config.Settings.load') as load, patch('autohsr.app.Runner') as game, \
                patch('autohsr.gui.main') as gui, redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--task-workflow-check', str(source)]), 0)
            data = json.loads(output.getvalue())
            self.assertFalse(data['game_accessed'])
            self.assertFalse(data['configuration_loaded'])
            load.assert_not_called()
            game.assert_not_called()
            gui.assert_not_called()
        for argv in (['--workflow-step-path', '0'], ['--task-workflow-check', str(source), '--stamina', '240']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(argv)

    def test_sequence_lease_blocks_other_threads_and_releases_after_exit(self):
        failures = []
        def outsider():
            for action in (require_workflow_access, lambda: workflow_lease().__enter__()):
                try:
                    action()
                except AutomationError:
                    failures.append(True)
        with workflow_lease():
            require_workflow_access()
            other = threading.Thread(target=outsider)
            other.start()
            other.join(5)
        self.assertEqual(failures, [True, True])
        require_workflow_access()

    def test_native_game_entry_is_blocked_before_launch(self):
        from autohsr.app import launch_game
        outcome = []
        with workflow_lease(), patch('autohsr.app.launch') as launch:
            def outsider():
                try:
                    launch_game(Settings())
                except AutomationError:
                    outcome.append('blocked')
            other = threading.Thread(target=outsider)
            other.start()
            other.join(5)
            launch.assert_not_called()
        self.assertEqual(outcome, ['blocked'])

    def test_lease_is_visible_to_an_independent_process(self):
        code = ('from autohsr.workflow_lease import require_workflow_access\n'
                'from autohsr.models import AutomationError\n'
                'try: require_workflow_access()\n'
                'except AutomationError: print("blocked")\n'
                'else: print("available")\n')
        with workflow_lease():
            process = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.strip(), 'blocked')
        process = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.stdout.strip(), 'available')

    def test_real_daily_runner_works_inside_workflow_with_fake_context(self):
        from autohsr.app import Runner
        from autohsr.tests.test_runner_recovery import RunnerRecoveryTests
        workflow = SimpleNamespace(ensure_main=Mock())
        context, _ = RunnerRecoveryTests.fixture(self, self.root, workflow)
        def native_factory(settings, emit, **options):
            child = Runner(settings, emit, **options)
            context.runner, context.settings, context.report, context.scene_epoch = child, settings, child.report, 0
            context.snapshot.side_effect = identity_scene
            context.checkpoint, context.sleep = child.checkpoint, time.sleep
            def daily():
                child.report.daily_verified = True
                child.report.engagement = 500
                return TaskResult('daily', 'ok', '合成500活跃与五档已核实')
            workflow.daily = daily
            return child
        runner = TaskWorkflowRunner(Settings(), recipe(task('daily', tasks=['daily'])),
                                    root=self.root / 'runs', runner_factory=native_factory)
        report = runner.run()
        self.assertEqual(report.status, 'success', report.error)
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.engagement, 500)
        source = Path(report.workflow['steps'][0]['source']['path'])
        self.assertTrue(json.loads(source.read_text('utf8'))['daily_verified'])

    def test_native_runner_without_ownership_stops_before_game_access(self):
        from autohsr.app import Runner
        from autohsr.tests.test_runner_recovery import RunnerRecoveryTests
        thread_class = threading.Thread
        _, find = RunnerRecoveryTests.fixture(self, self.root, SimpleNamespace(ensure_main=Mock()))
        results = []
        finished = threading.Event()
        def outsider():
            try:
                results.append(Runner(Settings()).run())
            finally:
                finished.set()
        with workflow_lease():
            other = thread_class(target=outsider)
            other.start()
            self.assertTrue(finished.wait(5))
            other.join(5)
        self.assertEqual(results[0].status, 'failed')
        self.assertTrue(results[0].report_saved)
        find.assert_not_called()
