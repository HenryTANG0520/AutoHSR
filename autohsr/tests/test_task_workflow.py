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
from uuid import uuid4

import cv2
from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, TaskResult, Scene, Token
import numpy as np
from autohsr.task_workflow import ASSIGNMENT_REWARDS_TASK, WorkflowError, compile_recipe, loads, task_spec
from autohsr.task_workflow_run import TaskWorkflowRunner
from autohsr.tests.test_du_points_goal import NOW, RESET, WEEK
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
    def test_independent_synthesis_reserves_once_and_can_pair_with_reward_only(self):
        synthesize = task('craft', 'daily_training_synthesis')
        reward = task('reward', 'daily_training_rewards')
        compiled = compile_recipe(recipe(synthesize, reward))
        self.assertEqual(compiled.profile['synthesis_calls'], 1)
        self.assertEqual(compiled.profile['daily_calls'], 1)
        for steps in ((synthesize, task('repeat', 'daily_training_synthesis')),
                      (synthesize, task('normal', tasks=['daily']))):
            with self.subTest(steps=steps), self.assertRaisesRegex(WorkflowError, '单件合成'):
                compile_recipe(recipe(*steps))
        self.assertNotIn('synthesis_calls', compile_recipe(recipe(reward)).profile)

    def test_independent_synthesis_requires_and_exposes_anonymous_native_receipt(self):
        node = task('craft', 'daily_training_synthesis')
        record = dict(recipe='奇巧零食', status='complete', task_verified=True, quantity=1, account_key='private',
                      before_holding=5, after_holding=6, before_materials=[(2, 1), (5, 1)],
                      after_materials=[(1, 1), (4, 1)])
        self.responses = [dict(daily_synthesis=record)]
        report = self.runner(recipe(node)).run()
        self.assertEqual(report.status, 'success', report.error)
        self.assertFalse(report.daily_verified)
        self.assertEqual(report.stamina_spent, 0)
        step, = report.workflow['steps']
        self.assertEqual(step['synthesis'], dict(recipe='奇巧零食', quantity=1, material_units=[1, 1]))
        self.assertTrue(step['account_verified'])
        self.assertEqual(self.calls[0][1], dict(operation='daily', daily_synthesis_only=True))
        self.responses = [dict(daily_synthesis=dict(record, after_holding=5))]
        report = self.runner(recipe(node)).run()
        self.assertEqual(report.status, 'partial')
        self.assertNotIn('synthesis', report.workflow['steps'][0])

    def test_independent_synthesis_reaches_native_runner_without_daily_startup(self):
        from autohsr.app import Runner
        from autohsr.tests.test_runner_recovery import RunnerRecoveryTests
        from autohsr.workflow_identity import _scope

        workflow = SimpleNamespace(ensure_main=Mock(side_effect=AssertionError('no generic startup')))
        context, _ = RunnerRecoveryTests.fixture(self, self.root, workflow)

        def factory(settings, emit, **options):
            child = Runner(settings, emit, **options)
            context.runner, context.settings, context.report, context.scene_epoch = child, child.settings, child.report, 0
            context.snapshot.side_effect = identity_scene
            self.assertTrue(child.settings.daily_synthesis)
            self.assertFalse(child.settings.battle)
            return child

        def perform(_workflow, frame):
            self.assertIsInstance(frame, Scene)
            scope = _scope.get()
            scope.observe(context, identity_scene())
            time.sleep(.02)
            scope.observe(context, identity_scene())
            context.report.daily_synthesis = dict(
                recipe='奇巧零食', status='complete', task_verified=True, quantity=1,
                before_holding=5, after_holding=6, before_materials=[(2, 1), (5, 1)],
                after_materials=[(1, 1), (4, 1)])
            return TaskResult('daily_training_synthesis', 'ok', 'verified')

        node = task('craft', 'daily_training_synthesis')
        runner = TaskWorkflowRunner(Settings(), recipe(node), root=self.root / 'runs', runner_factory=factory)
        with patch('autohsr.daily_synthesis_search.run_independent', side_effect=perform) as craft, \
                patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no startup')) as startup:
            report = runner.run()
        self.assertEqual(report.status, 'success', report.workflow)
        self.assertIn('synthesis', report.workflow['steps'][0])
        craft.assert_called_once()
        startup.assert_not_called()
        workflow.ensure_main.assert_not_called()

    def test_independent_assignment_has_no_daily_budget_and_checks_overlaps(self):
        assignment = task('assignments', ASSIGNMENT_REWARDS_TASK)
        training = task('training', 'daily_training_rewards')
        mail = task('mail', 'daily_free_attachment', target='mail')
        battlepass = task('pass', 'daily_free_attachment', target='battlepass')
        self.assertEqual(compile_recipe(recipe(assignment)).profile['daily_calls'], 0)
        combined = compile_recipe(recipe(assignment, training, mail, battlepass))
        self.assertEqual(combined.profile['daily_calls'], 1)
        self.assertEqual(combined.profile['assignment_reward_calls'], 1)
        self.assertEqual(combined.profile['free_attachment_calls'], 2)
        for node in (task('other', ASSIGNMENT_REWARDS_TASK), task('legacy', tasks=['assignments']),
                     task('all'), task('plan', 'plan')):
            with self.subTest(node=node), self.assertRaises(WorkflowError):
                compile_recipe(recipe(assignment, node))
        with self.assertRaises(WorkflowError):
            compile_recipe(recipe(task('unsupported', ASSIGNMENT_REWARDS_TASK, tasks=['daily'])))

    def test_training_rewards_preserves_legacy_synthesis_and_reserves_one_daily_call(self):
        rewards = task('rewards', 'daily_training_rewards')
        legacy = task('legacy', tasks=['daily'])
        settings = Settings(daily=False, daily_synthesis=True, allow_stamina_spend=True,
                            assignments=True, battle=True, mail=True, battlepass=True, redemption_enabled=True)
        compiled = compile_recipe(recipe(rewards))
        self.assertEqual(compiled.profile['daily_calls'], 1)
        only, options = task_spec(settings, rewards, self.root)
        self.assertEqual(options, dict(operation='reward_only'))
        self.assertTrue(only.daily)
        self.assertFalse(any(getattr(only, name) for name in ('daily_synthesis', 'allow_stamina_spend', 'assignments',
                                                             'battle', 'mail', 'battlepass', 'redemption_enabled')))
        normal, options = task_spec(settings, legacy, self.root)
        self.assertEqual(options['operation'], 'daily')
        self.assertTrue(normal.daily_synthesis)
        self.assertFalse(settings.daily)
        self.assertTrue(settings.allow_stamina_spend)
        for conflicting in (legacy, task('plan', 'plan'), task('more', 'daily_training_rewards')):
            with self.subTest(conflicting=conflicting), self.assertRaises(WorkflowError):
                compile_recipe(recipe(rewards, conflicting))
        for params in (dict(daily_synthesis=True), dict(stamina_limit=0), dict(tasks=['daily']),
                       dict(reached_only=1), dict(reached_only='true')):
            with self.subTest(params=params), self.assertRaises(WorkflowError):
                compile_recipe(recipe(task('invalid', 'daily_training_rewards', **params)))

    def test_odyssey_is_one_explicit_day_per_workflow_path(self):
        from autohsr.daily_observe import EVENT_CLAIM_OPERATION

        signup = task('signup', EVENT_CLAIM_OPERATION, day=4)
        compiled = compile_recipe(recipe(signup, task('training', 'daily_training_rewards')))
        self.assertEqual(compiled.profile['odyssey_claim_calls'], 1)
        self.assertEqual(compiled.profile['daily_calls'], 1)
        for params in ({}, {'day': 2}, {'day': '4'}, {'day': True}, {'day': 4, 'navigate': 1}):
            with self.subTest(params=params), self.assertRaises(WorkflowError):
                compile_recipe(recipe(task('invalid', EVENT_CLAIM_OPERATION, **params)))
        with self.assertRaisesRegex(WorkflowError, '最多提交一个'):
            compile_recipe(recipe(signup, task('another', EVENT_CLAIM_OPERATION, day=5)))

    def setUp(self):
        self.lease_name = 'Local\\AutoHSR.TaskWorkflowQA.' + uuid4().hex
        self.enterContext(patch('autohsr.workflow_lease.NAME', self.lease_name))
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
        self.clock = NOW
        self.hotkeys = patch.object(TaskWorkflowRunner, '_hotkeys', lambda runner: runner._end.wait())
        self.hotkeys.start()
        self.addCleanup(self.hotkeys.stop)
        clock = patch('autohsr.du_periodic_points.local_now', lambda: self.clock)
        clock.start()
        self.addCleanup(clock.stop)

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
                if options.get('du_until_points'):
                    owner.write_du_sources(folder, result['differential_universe'])
                raw = json.dumps(result, ensure_ascii=False).encode('utf8')
                (folder / 'report.json').write_bytes(raw)
                if options.get('du_until_points'):
                    owner.seal_du_sources(folder)
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

    def test_current_account_page_receipt_drives_workflow_condition(self):
        self.responses.append(dict(workflow_navigation=dict(target='survival_index', page_verified=True,
                                                            actions=[])))
        document = recipe(task('page', 'workflow_open_page', target='survival_index'),
                          dict(id='check', type='if', condition=condition('page', 'page_verified', True),
                               steps=[dict(id='ready', type='wait', seconds=0)]))
        report = self.runner(document).run()
        self.assertEqual(report.status, 'success')
        self.assertEqual([row['step'] for row in report.workflow['steps']], ['page', 'check', 'ready'])
        self.assertEqual(report.workflow['steps'][0]['facts'], dict(status='success', page_verified=True))
        self.assertEqual(self.calls[0][1], dict(operation='workflow_open_page', workflow_page='survival_index'))
        self.assertEqual(report.workflow['reservations']['daily_calls'], 0)

    def test_daily_workflow_preserves_the_original_supply_receipt(self):
        supply = dict(claim='sent', reward_display='observed_after_claim', close='sent', return_status='after_close')
        self.responses.append(dict(train_supply=supply))
        report = self.runner(recipe(task('daily', tasks=['daily']))).run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(report.to_dict()['train_supply'], supply)

    def test_conflicting_or_missing_page_receipt_cannot_release_next_step(self):
        for invalid in (dict(target='guide', page_verified=True), dict(target='phone', page_verified=1),
                        dict(target='phone', page_verified=False)):
            with self.subTest(invalid=invalid):
                self.responses.append(dict(workflow_navigation=invalid))
                report = self.runner(recipe(task('page', 'workflow_open_page', target='phone'),
                                            task('daily'))).run()
                self.assertEqual(report.status, 'partial')
                page, = report.workflow['steps']
                self.assertNotIn('page_verified', page['facts'])
        with self.assertRaises(WorkflowError):
            compile_recipe(recipe(task('page', 'workflow_open_page', target='store')))

    def test_yaml_cli_conversion_is_exclusive_and_never_loads_settings(self):
        from autohsr.__main__ import main

        source, target = self.root / 'sample.yml', self.root / 'converted.json'
        raw = b'name: example\nsteps:\n  - type: wait\n    seconds: 0.25\n'
        source.write_bytes(raw)
        args = ['--task-workflow-convert-yaml', str(source), '--workflow-json-destination', str(target)]
        with patch.object(Settings, 'load', side_effect=AssertionError('offline conversion')):
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(args), 0)
            result = json.loads(out.getvalue())
            original = target.read_bytes()
            self.assertEqual(result['sha256'], hashlib.sha256(original).hexdigest())
            with redirect_stderr(io.StringIO()) as err:
                self.assertEqual(main(args), 2)
            self.assertEqual(json.loads(err.getvalue())['status'], 'failed')
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(target.read_bytes(), original)
        document = loads(original)
        self.assertEqual(compile_recipe(document).steps[0]['seconds'], .25)
        runner = self.runner(document)
        with patch.object(runner, '_wait', wraps=runner._wait) as wait:
            self.assertEqual(runner.run().status, 'success')
        wait.assert_called_once_with(.25)
        self.assertEqual(self.calls, [])

    def test_parent_reports_anonymous_redemption_feedback_from_verified_child(self):
        from autohsr.notify_runtime import report_message

        private_code = 'PrivateWorkflowCode26'
        batch = dict(schema=1, status='completed', codes=[private_code],
                     account_key='PrivateWorkflowAccount', submitted=1, redeemed=0, reused=0,
                     results=[dict(code=private_code, status='expired', reused=False, entry_id='1'*32)])
        self.responses.append(dict(stamina_spent=0, daily_verified=False, battle_completed=0, redemption=batch))
        report = self.runner(recipe(task('redeem', tasks=['redemption'], redemption_source='manual',
                                         redemption_codes=[private_code], redemption_claim_mail=False))).run()
        self.assertEqual(report.status, 'success')
        saved = json.loads((Path(report.run_dir) / 'report.json').read_text('utf8'))
        summary = saved['workflow']['redemption_summary']
        self.assertEqual((summary['redeemed'], summary['expired']), (0, 1))
        self.assertNotIn(private_code, json.dumps(summary))
        self.assertNotIn('PrivateWorkflowAccount', json.dumps(summary))
        entry, = saved['workflow']['steps']
        source = Path(entry['source']['path'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), entry['source']['sha256'])
        self.assertEqual(json.loads(source.read_text('utf8'))['redemption'], batch)
        _, body = report_message(self.settings, saved)
        self.assertIn('兑换新成功：0', body)
        self.assertIn('过期：1', body)

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

    def test_du_points_requires_a_new_periodic_run_and_an_explicit_limit(self):
        node = task('du', 'differential_universe', runs=3, until_points=True)
        self.assertEqual(compile_recipe(recipe(node)).profile['du_runs'], 3)
        _, options = task_spec(self.settings, node, self.root)
        self.assertEqual(options['du_runs'], 3)
        self.assertIs(options['du_until_points'], True)

        for params in ({}, {'until_points': False}):
            fixed = task('fixed', 'differential_universe', **params)
            self.assertEqual(compile_recipe(recipe(fixed)).profile['du_runs'], 1)
            _, options = task_spec(self.settings, fixed, self.root)
            self.assertEqual(options['du_runs'], 1)
            self.assertNotIn('du_until_points', options)

        for params in ({'until_points': True}, {'until_points': True, 'runs': 0},
                       {'until_points': True, 'runs': 11}, {'until_points': 1, 'runs': 1},
                       {'until_points': 'true', 'runs': 1}, {'until_points': True, 'runs': 1, 'mode': 'normal'},
                       {'until_points': True, 'runs': 1, 'resume_active': True, 'periodic_rank': 5}):
            with self.subTest(params=params), self.assertRaises(WorkflowError):
                compile_recipe(recipe(task('bad', 'differential_universe', **params)))

    @staticmethod
    def du_points_result(maximum, completed, goal_status):
        capped = goal_status == 'capped'
        return dict(mode='周期演算', requested_runs=maximum, completed_runs=completed,
            session_id='synthetic-session', current_run=completed,
            run_results=[dict(run=i, counted_run=i, run_id=f'synthetic-win-{i}', origin='fresh', status='completed', counted=True,
                              mode='周期演算', difficulty_verified=True, return_page='home')
                         for i in range(1, completed + 1)],
            periodic_points_goal=dict(source='du_home', maximum=maximum, status=goal_status,
                observations=[dict(current=18000 if i == completed and capped else 8000 + 1000*i,
                                   cap=18000, capped=i == completed and capped, observed_at=NOW.isoformat(),
                                   game_week=WEEK, completed_runs=i) for i in range(completed + 1)]))

    @staticmethod
    def write_du_ledger(folder, data):
        ledger = dict(schema_version=1, **{key: data[key] for key in
                      ('session_id', 'requested_runs', 'completed_runs', 'current_run', 'run_results',
                       'periodic_points_goal') if key in data})
        (folder / 'differential-universe-ledger.json').write_text(json.dumps(ledger), encoding='utf8')

    @staticmethod
    def write_du_sources(folder, data):
        from autohsr.currency_wars_initial import source_file_ref

        def image(label, value):
            path = folder / f'093000_000000_{label}.png'
            raw = cv2.imencode('.png', np.full((20, 30, 3), value, dtype=np.uint8))[1].tobytes()
            path.write_bytes(raw)
            return path

        data.update(run_dir=str(folder), ledger_path=str(folder / 'differential-universe-ledger.json'))
        for row in data['run_results']:
            row['victory_evidence'] = str(image(f"du_{row['run']:02d}_victory", 127))
            row['return_evidence'] = str(image(f"du_{row['run']:02d}_fresh_return", 190))
            sources = row['completion_evidence'] = dict(session_id=data['session_id'], run_id=row['run_id'])
            for role in ('victory', 'return'):
                path = Path(row[role + '_evidence'])
                sources[role] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for row in data.get('periodic_points_goal', {}).get('observations', []):
            row['evidence'] = [source_file_ref(image(f"du_points_after_{row['completed_runs']}_{i}", 24), folder)
                               for i in (1, 2)]
        WorkflowTests.write_du_ledger(folder, data)

    @staticmethod
    def seal_du_sources(folder):
        files = [dict(path=path.name, size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                 for path in folder.iterdir() if path.is_file() and not path.name.startswith('evidence_manifest.')]
        raw = json.dumps(dict(algorithm='sha256', files=files)).encode('utf8')
        (folder / 'evidence_manifest.json').write_bytes(raw)
        (folder / 'evidence_manifest.sha256').write_text(f'{hashlib.sha256(raw).hexdigest()}  evidence_manifest.json\n',
                                                        encoding='ascii')

    def test_du_points_projects_native_zero_early_cap_and_exhausted_results(self):
        for maximum, completed, goal_status, status in ((3, 0, 'capped', 'success'),
                (3, 1, 'capped', 'success'), (2, 2, 'exhausted', 'partial')):
            with self.subTest(maximum=maximum, completed=completed, status=status):
                native = self.du_points_result(maximum, completed, goal_status)
                self.responses = [dict(status=status, differential_universe=native)]
                duel = task('du', 'differential_universe', runs=maximum, until_points=True)
                following = [task('later', 'du_rewards')] if status == 'partial' else []
                report = self.runner(recipe(duel, *following)).run()
                entry = report.workflow['steps'][0]
                self.assertEqual((entry['status'], report.status), (status, status))
                self.assertEqual(entry['facts'], dict(status=status, completed_runs=completed))
                self.assertEqual(entry['periodic_points_goal'], native['periodic_points_goal'])
                self.assertEqual(report.differential_universe, native)
                self.assertEqual(report.du_rewards, {})
                self.assertEqual(len(report.workflow['steps']), 1)
                self.assertIs(report.workflow['input_blocked'], status == 'partial')
                self.assertTrue(entry['account_verified'])
                self.assertIs(self.calls[-1][1]['du_until_points'], True)

    def test_du_points_success_requires_matching_native_points_and_victories(self):
        for flaw in ('missing_goal', 'below_cap', 'count_without_win'):
            with self.subTest(flaw=flaw):
                native = self.du_points_result(3, 1, 'capped')
                if flaw == 'missing_goal':
                    del native['periodic_points_goal']
                    native['reward_collection'] = {'complete': True}
                elif flaw == 'below_cap':
                    native['periodic_points_goal']['observations'][-1]['current'] = 8000
                else:
                    native['run_results'] = []
                self.responses = [dict(differential_universe=native)]
                first = dict(task('du', 'differential_universe', runs=3, until_points=True), on_failure='continue')
                report = self.runner(recipe(first, task('later', 'du_rewards'))).run()
                entry, later = report.workflow['steps']
                self.assertEqual(entry['facts'], {'status': 'partial'})
                self.assertTrue(entry.get('source'))
                self.assertEqual(later['status'], 'partial')
                self.assertNotIn('source', later)
                self.assertEqual(report.differential_universe, {})

    def test_du_points_requires_intact_native_ledger_manifest_and_capture_roles(self):
        for flaw in ('missing_ledger', 'ledger_count', 'resealed_ledger_count', 'points_changed', 'victory_removed',
                     'return_changed', 'resealed_victory', 'resealed_return', 'missing_capture_source',
                     'different_run_source', 'duplicate_capture', 'foreign_capture', 'wrong_win_role', 'bad_manifest', 'other_run'):
            with self.subTest(flaw=flaw):
                def damage(child, result):
                    folder = Path(result['run_dir'])
                    native = result['differential_universe']
                    ledger_path = Path(native['ledger_path'])
                    win = native['run_results'][0]
                    sources = native['periodic_points_goal']['observations'][-1]['evidence']
                    if flaw == 'missing_ledger':
                        ledger_path.unlink()
                    elif flaw in ('ledger_count', 'resealed_ledger_count'):
                        ledger = json.loads(ledger_path.read_bytes())
                        ledger['completed_runs'] = 2
                        ledger_path.write_text(json.dumps(ledger), encoding='utf8')
                        if flaw == 'resealed_ledger_count':
                            self.seal_du_sources(folder)
                    elif flaw == 'points_changed':
                        Path(sources[0]['path']).write_bytes(Path(win['victory_evidence']).read_bytes())
                    elif flaw == 'victory_removed':
                        Path(win['victory_evidence']).unlink()
                    elif flaw == 'return_changed':
                        Path(win['return_evidence']).write_bytes(Path(win['victory_evidence']).read_bytes())
                    elif flaw in ('resealed_victory', 'resealed_return'):
                        target, replacement = 'victory_evidence', 'return_evidence'
                        if flaw == 'resealed_return':
                            target, replacement = replacement, target
                        Path(win[target]).write_bytes(Path(win[replacement]).read_bytes())
                        self.seal_du_sources(folder)
                    elif flaw == 'bad_manifest':
                        (folder / 'evidence_manifest.sha256').unlink()
                    else:
                        if flaw == 'duplicate_capture':
                            sources[0] = sources[1]
                        elif flaw == 'missing_capture_source':
                            del win['completion_evidence']
                        elif flaw == 'different_run_source':
                            win['completion_evidence']['run_id'] = 'other-win'
                        elif flaw == 'foreign_capture':
                            previous = Path(sources[0]['path'])
                            foreign = self.root / previous.name
                            foreign.write_bytes(previous.read_bytes())
                            sources[0]['path'] = str(foreign)
                        elif flaw == 'wrong_win_role':
                            win['victory_evidence'] = win['return_evidence']
                        elif flaw == 'other_run':
                            folder = self.root / 'other-child'
                            folder.mkdir()
                            result['run_dir'] = str(folder)
                            self.write_du_sources(folder, native)
                        self.write_du_ledger(folder, native)
                        (folder / 'report.json').write_text(json.dumps(result), encoding='utf8')
                        self.seal_du_sources(folder)

                self.after_child = damage
                self.responses = [dict(differential_universe=self.du_points_result(3, 1, 'capped'))]
                first = dict(task('du', 'differential_universe', runs=3, until_points=True), on_failure='continue')
                guard = dict(id='guard', type='if', condition=condition('du'), steps=[task('next', 'du_rewards')])
                report = self.runner(recipe(first, guard)).run()
                entry, branch = report.workflow['steps']
                self.assertEqual((report.status, entry['facts'], branch['condition']), ('partial', {'status': 'partial'}, False))
                self.assertTrue(report.workflow['input_blocked'])
                self.assertEqual(report.differential_universe, {})

    def test_du_points_partial_count_requires_native_report_and_ledger_agreement(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                def after_child(child, result):
                    if changed:
                        result['differential_universe']['completed_runs'] = 8
                        (Path(result['run_dir']) / 'report.json').write_text(json.dumps(result), encoding='utf8')

                self.after_child = after_child
                self.responses = [dict(status='partial', differential_universe=self.du_points_result(1, 1, 'exhausted'))]
                first = dict(task('du', 'differential_universe', runs=1, until_points=True), on_failure='continue')
                guard = dict(id='guard', type='if', condition=condition('du', 'completed_runs', 1),
                             steps=[dict(id='local', type='wait', seconds=0)])
                report = self.runner(recipe(first, guard)).run()
                entry, branch, *later = report.workflow['steps']
                self.assertEqual(report.status, 'partial')
                self.assertTrue(report.workflow['input_blocked'])
                if changed:
                    self.assertEqual(entry['facts'], {'status': 'partial'})
                    self.assertEqual(branch['status'], 'partial')
                    self.assertFalse(later)
                else:
                    self.assertEqual(entry['facts'], {'status': 'partial', 'completed_runs': 1})
                    self.assertEqual(later[0]['status'], 'success')

    def test_du_points_received_after_reset_preserves_native_week_and_win_only_as_history(self):
        original = {}

        def after_child(child, result):
            original['data'] = deepcopy(result['differential_universe'])
            original['ledger'] = Path(original['data']['ledger_path']).read_bytes()
            self.clock = RESET

        self.after_child = after_child
        self.responses = [dict(differential_universe=self.du_points_result(3, 1, 'capped'))]
        first = dict(task('du', 'differential_universe', runs=3, until_points=True), on_failure='continue')
        report = self.runner(recipe(first, task('later', 'du_rewards'))).run()
        entry, later = report.workflow['steps']
        self.assertEqual((report.status, entry['facts']), ('partial', {'status': 'partial', 'completed_runs': 1}))
        self.assertEqual((later['status'], self.child_index), ('partial', 1))
        goal = original['data']['periodic_points_goal']
        projected = dict(goal, status='unverified', reason='game_week_changed')
        self.assertEqual(entry['periodic_points_goal'], projected)
        self.assertEqual(report.differential_universe, dict(original['data'], periodic_points_goal=projected))
        self.assertEqual(json.loads(Path(entry['source']['path']).read_bytes())['differential_universe'], original['data'])
        self.assertEqual(Path(original['data']['ledger_path']).read_bytes(), original['ledger'])

    def test_du_points_wait_rechecks_the_game_week_before_conditions_and_game_tasks(self):
        for scenario in ('same_week', 'crossed_condition', 'crossed_direct', 'crossed_default_stop'):
            with self.subTest(scenario=scenario):
                self.clock = NOW
                count_before = self.child_index
                native = self.du_points_result(3, 1, 'capped')
                rewards = dict(schema=1, operation='du_rewards', status='complete', rewards_verified=True,
                               battle_started=False, use_cassettes=False,
                               requested_categories=['拟合等级', '稳态数组', '可能性画廊'])
                self.responses = [dict(differential_universe=native), dict(du_rewards=rewards)]
                first = task('du', 'differential_universe', runs=3, until_points=True)
                if scenario != 'crossed_default_stop':
                    first['on_failure'] = 'continue'
                later = task('rewards', 'du_rewards')
                if scenario in ('same_week', 'crossed_condition'):
                    later = dict(id='branch', type='if', condition=condition('@last'), steps=[later])
                runner = self.runner(recipe(first, dict(id='wait', type='wait', seconds=0), later))
                saved = {}
                original_wait = runner._wait

                def wait(seconds):
                    original_wait(seconds)
                    step = runner.report.workflow['steps'][0]
                    self.assertEqual(step['status'], 'success')
                    for name in (step['source']['path'], native['ledger_path']):
                        saved[Path(name)] = Path(name).read_bytes()
                    if scenario != 'same_week':
                        self.clock = RESET

                with patch.object(runner, '_wait', wait):
                    report = runner.run()
                self.assertTrue(all(path.read_bytes() == raw for path, raw in saved.items()))
                entry, waited, *tail = report.workflow['steps']
                self.assertEqual(waited['status'], 'success')
                history = [json.loads(line) for line in (Path(report.run_dir) / 'steps.jsonl').read_bytes().splitlines()]
                changes = [row for row in history if row['event'] == 'du_points_revalidation']
                if scenario == 'same_week':
                    self.assertEqual((report.status, tail[0]['condition'], self.child_index - count_before), ('success', True, 2))
                    self.assertTrue(report.du_rewards['rewards_verified'])
                    self.assertFalse(changes)
                    continue
                self.assertEqual((report.status, self.child_index - count_before), ('partial', 1))
                self.assertEqual(entry['facts'], {'status': 'partial', 'completed_runs': 1})
                self.assertTrue(report.workflow['input_blocked'])
                self.assertEqual(entry['periodic_points_goal'], dict(native['periodic_points_goal'],
                                 status='unverified', reason='game_week_changed'))
                self.assertEqual(report.differential_universe['run_results'], native['run_results'])
                self.assertEqual(report.differential_universe['periodic_points_goal'], entry['periodic_points_goal'])
                self.assertEqual([(row['step'], row['status']) for row in changes], [('du', 'partial')])
                self.assertTrue(any(row['event'] == 'result' and row['step'] == 'du' and row['status'] == 'success' for row in history))
                if scenario == 'crossed_condition':
                    self.assertEqual([(row['step'], row['condition']) for row in tail], [('branch', False)])
                elif scenario == 'crossed_direct':
                    self.assertEqual([(row['step'], row['status']) for row in tail], [('rewards', 'partial')])
                else:
                    self.assertFalse(tail)

    def test_du_followup_week_is_rechecked_at_native_send_and_scope_is_released(self):
        from autohsr import windows
        from autohsr.du_points_followup import FollowupWeek, followup_week_scope

        window = windows.GameWindow.__new__(windows.GameWindow)
        window.guard = Mock()
        user32 = Mock()
        user32.GetAsyncKeyState.return_value = 0
        user32.SendInput.return_value = 1
        permission = FollowupWeek(WEEK)
        events = [windows.INPUT(type=0)]

        def reset_at_send():
            self.clock = RESET

        with patch.object(windows, 'user32', user32):
            with followup_week_scope(permission):
                with self.assertRaisesRegex(AutomationError, '游戏周已切换'):
                    window.send(events, before_send=reset_at_send)
                self.assertTrue(permission.expired)
                self.clock = NOW
                with self.assertRaises(AutomationError):
                    window.send(events)
                user32.SendInput.assert_not_called()
            self.clock = RESET
            window.send(events)
            user32.SendInput.assert_called_once()

    def test_du_points_final_report_retry_refreshes_goal_without_rewriting_completed_rewards(self):
        for crossed in (False, True):
            with self.subTest(crossed=crossed):
                self.clock = NOW
                native = self.du_points_result(3, 1, 'capped')
                rewards = dict(schema=1, operation='du_rewards', status='complete', rewards_verified=True,
                               battle_started=False, use_cassettes=False,
                               requested_categories=['拟合等级', '稳态数组', '可能性画廊'])
                self.responses = [dict(differential_universe=native), dict(du_rewards=rewards)]
                runner = self.runner(recipe(task('du', 'differential_universe', runs=3, until_points=True),
                                            task('rewards', 'du_rewards')))
                attempts, child_files = [], {}
                replace_file = Path.replace

                def commit(source, destination):
                    if Path(destination).parent == Path(runner.report.run_dir) and Path(destination).name == 'report.json':
                        candidate = json.loads(source.read_bytes())
                        if candidate['finished_at']:
                            attempts.append(candidate)
                            if len(attempts) == 1:
                                for step in candidate['workflow']['steps']:
                                    path = Path(step['source']['path'])
                                    child_files[path] = path.read_bytes()
                                path = Path(native['ledger_path'])
                                child_files[path] = path.read_bytes()
                                if crossed:
                                    self.clock = RESET
                                raise PermissionError('synthetic parent report sharing lock')
                    return replace_file(source, destination)

                with patch.object(Path, 'replace', commit):
                    report = runner.run()
                status = 'partial' if crossed else 'success'
                self.assertEqual([candidate['status'] for candidate in attempts], ['success', status])
                self.assertEqual(report.to_dict(), attempts[-1])
                self.assertEqual(report.results[-1].status, 'partial' if crossed else 'ok')
                self.assertEqual(json.loads((Path(report.run_dir) / 'report.json').read_bytes()), report.to_dict())
                self.assertTrue(all(path.read_bytes() == raw for path, raw in child_files.items()))
                du, reward = report.workflow['steps']
                self.assertEqual(du['facts'], {'status': status, 'completed_runs': 1})
                self.assertEqual(du['periodic_points_goal']['status'], 'unverified' if crossed else 'capped')
                self.assertEqual(du['periodic_points_goal']['observations'], native['periodic_points_goal']['observations'])
                self.assertEqual(report.differential_universe['run_results'], native['run_results'])
                self.assertIs(report.workflow['input_blocked'], crossed)
                self.assertEqual(reward['facts'], {'status': 'success', 'du_rewards_verified': True})
                self.assertEqual(report.du_rewards, rewards)

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

    def test_only_explicit_complete_reached_scope_advances_to_the_next_reward(self):
        receipt = dict(activity=400, verified=[100, 200, 300, 400])
        for scope, native_receipt, error, should_continue in (
                (True, receipt, '', True), (False, receipt, '', False),
                (True, None, '', False), (True, dict(receipt, verified=[100, 200, 400]), '', False),
                (True, dict(receipt, activity=399), '', False), (True, receipt, '反馈待核对', False)):
            with self.subTest(scope=scope, receipt=native_receipt, error=error):
                self.calls.clear()
                self.responses = [
                    dict(status='partial', engagement=400, training_milestones=native_receipt,
                         results=[dict(task='daily', status='partial', detail='当前活跃度400')], error=error),
                    dict(stamina_spent=0, daily_verified=False, battle_completed=0,
                         assignment=dict(outcome='empty', submission='not_attempted')),
                ]
                training = task('training', 'daily_training_rewards', reached_only=scope)
                following = task('assignments', ASSIGNMENT_REWARDS_TASK)
                report = self.runner(recipe(training, following)).run()
                self.assertEqual(report.status, 'success' if should_continue else 'partial')
                self.assertFalse(report.daily_verified)
                self.assertEqual(report.engagement, 400)
                self.assertEqual(len(self.calls), 2 if should_continue else 1)
                self.assertEqual(report.workflow['input_blocked'], not should_continue)
                step = report.workflow['steps'][0]
                if should_continue:
                    self.assertEqual(step['native_status'], 'partial')
                    self.assertEqual(step['training_milestones'], receipt)
                    self.assertIs(step['facts']['daily_verified'], False)
                    self.assertEqual(report.workflow['steps'][1]['assignment']['outcome'], 'empty')

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

    def test_support_daily_only_accepts_only_booleans_for_daily_and_plan(self):
        for operation in ('daily', 'plan'):
            for value in (0, 1, 'true', None):
                with self.subTest(operation=operation, value=value):
                    with self.assertRaisesRegex(WorkflowError, '流程开关必须为布尔值'):
                        compile_recipe(recipe(task('support', operation, support_daily_only=value)))
        with self.assertRaisesRegex(WorkflowError, '流程包含未知字段'):
            compile_recipe(recipe(task('support', 'differential_universe', support_daily_only=True)))

    def test_support_daily_only_freezes_explicit_override_and_preserves_inheritance(self):
        for operation in ('daily', 'plan'):
            for inherited, override in ((False, None), (True, None), (True, False), (False, True)):
                with self.subTest(operation=operation, inherited=inherited, override=override):
                    settings = Settings(use_support=False, support_daily_only=inherited)
                    params = {} if override is None else {'support_daily_only': override}
                    step = compile_recipe(recipe(task('support', operation, **params))).steps[0]
                    frozen, options = task_spec(settings, step, self.root)
                    self.assertIs(frozen.support_daily_only, inherited if override is None else override)
                    self.assertIs(frozen.use_support, False)
                    self.assertIs(settings.support_daily_only, inherited)
                    self.assertEqual(step['params'], params)
                    self.assertNotIn('support_daily_only', options)
        settings = Settings(battle=False, support_daily_only=True, weekly_enabled=True, weekly_mode='currency_wars')
        for operation, extra in (('daily', {'tasks': ['assignments']}),
                                 ('plan', {'resume_weekly_currency': True})):
            for params, expected in ((extra, True), (dict(extra, support_daily_only=False), False)):
                with self.subTest(operation=operation, params=params):
                    step = compile_recipe(recipe(task('support', operation, **params))).steps[0]
                    self.assertIs(task_spec(settings, step, self.root)[0].support_daily_only, expected)

    def test_support_daily_only_rejects_disabled_battle_or_spending_and_weekly_resume_before_start(self):
        cases = (
            ('daily', Settings(), {'tasks': ['assignments']}),
            ('daily', Settings(battle=False), {}),
            ('daily', Settings(allow_stamina_spend=False), {}),
            ('plan', Settings(battle=False), {}),
            ('plan', Settings(allow_stamina_spend=False), {}),
            ('plan', Settings(weekly_enabled=True, weekly_mode='currency_wars'), {'resume_weekly_currency': True}),
        )
        factory = Mock()
        runs = self.root / 'runs'
        with patch('autohsr.app.find_game') as find, patch('autohsr.app.launch_game') as launch:
            for operation, settings, params in cases:
                with self.subTest(operation=operation, params=params):
                    document = recipe(task('support', operation, support_daily_only=True, **params))
                    with self.assertRaisesRegex(WorkflowError, '仅实训需要时借用'):
                        TaskWorkflowRunner(settings, document, root=runs, runner_factory=factory, plan_factory=factory)
        factory.assert_not_called()
        find.assert_not_called()
        launch.assert_not_called()
        self.assertFalse(runs.exists())

    def test_support_daily_only_reaches_native_battle_through_daily_and_plan(self):
        from autohsr.app import Runner
        from autohsr.plan_runner import PlanRunner
        from autohsr.tests.test_runner_recovery import RunnerRecoveryTests

        for operation in ('daily', 'plan'):
            with self.subTest(operation=operation):
                root = self.root / operation
                root.mkdir()
                config = root / 'settings.json'
                Settings(assignments=False, daily=False, overlay_logs=False, stamina_limit=10,
                         rounds=1, challenge_count=1).save(config)
                original = config.read_bytes()
                settings = Settings.load(config)
                workflow = SimpleNamespace(ensure_main=Mock())
                context, find = RunnerRecoveryTests.fixture(self, root, workflow)

                def battle():
                    self.assertIs(context.settings.support_daily_only, True)
                    self.assertIs(context.settings.use_support, True)
                    context.battle_budget.reserve(10)
                    context.battle_budget.confirm(10, completed=1)
                    return TaskResult('battle', 'ok', '模拟一轮确认')

                def native_factory(frozen, emit, **options):
                    child = Runner(frozen, emit, **options)
                    context.runner, context.settings, context.report, context.scene_epoch = child, frozen, child.report, 0
                    context.snapshot.side_effect = identity_scene
                    context.checkpoint, context.sleep = child.checkpoint, time.sleep
                    return child

                def plan_factory(frozen, emit, **options):
                    return PlanRunner(frozen, emit, runner_factory=native_factory, root=root / 'runs', **options)

                workflow.battle = Mock(side_effect=battle)
                document = recipe(task('support', operation, support_daily_only=True))
                runner = TaskWorkflowRunner(settings, document, root=root / 'runs', runner_factory=native_factory,
                                            plan_factory=plan_factory)
                document['steps'][0]['params']['support_daily_only'] = False
                with patch('autohsr.app.launch_game') as launch:
                    report = runner.run()
                self.assertEqual(report.status, 'success', report.error)
                self.assertEqual((report.stamina_spent, report.stamina_pending, report.battle_completed), (10, 0, 1))
                workflow.battle.assert_called_once()
                find.assert_called_once()
                launch.assert_not_called()
                self.assertIs(settings.support_daily_only, False)
                self.assertEqual(config.read_bytes(), original)

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

    def test_cli_missing_explicit_config_cannot_start_workflow_or_page_navigation(self):
        from autohsr.__main__ import main

        source = self.root / 'recipe.json'
        source.write_text(json.dumps(recipe(task('daily'))), 'utf8')
        missing = self.root / 'missing-config.json'
        for entry in (['--task-workflow', str(source)], ['--screen-check-pages', 'mail']):
            for config in (['--config', str(missing)], [f'--config={missing}']):
                with self.subTest(entry=entry, config=config), \
                        patch('autohsr.task_workflow_run.TaskWorkflowRunner') as runner, \
                        patch('autohsr.app.Runner') as native, redirect_stdout(io.StringIO()) as output, \
                        redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(main([*entry, *config]), 2)
                    self.assertEqual(output.getvalue(), '')
                    self.assertEqual(json.loads(errors.getvalue())['status'], 'failed')
                    runner.assert_not_called()
                    native.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_cli_workflow_loads_valid_explicit_config_and_preserves_omitted_default(self):
        from autohsr.__main__ import main

        source = self.root / 'recipe.json'
        source.write_text(json.dumps(recipe(task('daily'))), 'utf8')
        config = self.root / 'without-battle.json'
        Settings(battle=False, allow_stamina_spend=False).save(config)
        for flags, battle in ((['--config', str(config)], False), ([], True)):
            with self.subTest(flags=flags), patch('autohsr.__main__.CONFIG_PATH', self.root / 'missing-default.json'), \
                    patch('autohsr.task_workflow_run.TaskWorkflowRunner') as runner, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value.to_dict.return_value = {'status': 'success'}
                self.assertEqual(main(['--task-workflow', str(source), *flags]), 0)
                settings, document, _ = runner.call_args.args
                resolved, _ = task_spec(settings, document['steps'][0], self.root)
                self.assertIs(resolved.battle, battle)
                self.assertIs(resolved.allow_stamina_spend, battle)

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
        code = ('import sys\n'
                'from autohsr import workflow_lease\n'
                'from autohsr.models import AutomationError\n'
                'workflow_lease.NAME = sys.argv[1]\n'
                'try: workflow_lease.require_workflow_access()\n'
                'except AutomationError: print("blocked")\n'
                'else: print("available")\n')
        command = [sys.executable, '-c', code, self.lease_name]
        with workflow_lease():
            process = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.strip(), 'blocked')
        process = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.stdout.strip(), 'available')

    def test_source_self_test_scopes_both_native_lock_names(self):
        from autohsr import workflow_lease as locks
        from autohsr.__main__ import main

        original = locks.NAME, locks.NATIVE_NAME
        seen = []

        def probe():
            seen.append((locks.NAME, locks.NATIVE_NAME))
            self.assertTrue(locks.NAME.startswith('Local\\AutoHSR.SelfTest.'))
            self.assertEqual(locks.NAME.rsplit('.', 1)[0], locks.NATIVE_NAME.rsplit('.', 1)[0])
            self.assertNotEqual(locks.NAME, locks.NATIVE_NAME)

        for _ in range(2):
            suite = unittest.TestSuite((unittest.FunctionTestCase(probe),))
            with (patch.object(unittest.defaultTestLoader, 'discover', return_value=suite),
                  redirect_stderr(io.StringIO()) as output):
                self.assertEqual(main(['--self-test']), 0, output.getvalue())
            self.assertEqual((locks.NAME, locks.NATIVE_NAME), original)
        self.assertNotEqual(seen[0], seen[1])

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
