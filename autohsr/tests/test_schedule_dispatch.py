"""Schedule integration with fake task-tree Runners; never game or system input."""
from contextlib import nullcontext, redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta
import io
import json
import mmap
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from autohsr.config import Settings
from autohsr.schedule_dispatch import NativeScheduleExecutor, VerifiedScheduleRunner, validate_target
from autohsr.schedule_plan import CHINA, ScheduleError, ScheduleSourceUnverified, validate
from autohsr.schedule_runtime import Scheduler
from autohsr.schedule_store import ScheduleStore


class FakeWorkflow:
    def __init__(self, settings, document, emit, **options):
        self.settings, self.document, self.emit, self.options = settings, document, emit, options
        self.paused = self.stopped = False
        self.report = None
    def stop(self):
        self.stopped = True
    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused
    def run(self):
        directory = Path(self.options['root']) / uuid.uuid4().hex
        directory.mkdir(parents=True)
        self.report = dict(status='success', operation='task_workflow', report_saved=True,
                           run_dir=str(directory), started_at='fixture-start', finished_at='fixture-end',
                           daily_verified=True, private='synthetic-sensitive-not-real')
        (directory / 'report.json').write_text(json.dumps(self.report), 'utf8')
        self.emit(dict(type='finished', report=self.report))
        return self.report


class ScheduleDispatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(game_path=r'C:\fixture\StarRail.exe', assignments=False,
                                 battle=False, daily=True, mail=False, battlepass=False)
        self.factory = Mock(side_effect=FakeWorkflow)
        self.executor = NativeScheduleExecutor(self.settings, base_dir=self.root, run_root=self.root / 'runs',
                                               workflow_factory=self.factory, busy_probe=lambda: False)
        self.workflow = self.root / 'workflow.json'
        self.write_workflow()

    def write_workflow(self, **extra):
        value = dict(version=1, name='Offline fixture', steps=[dict(id='wait', type='wait', seconds=0)])
        value.update(extra)
        self.workflow.write_text(json.dumps(value), 'utf8')

    def write_records(self, name, *identities):
        from autohsr.tests.test_warp_records import group, row
        from autohsr.warp_records import export
        path = self.root / name
        path.write_text(json.dumps(export([group([row(identity) for identity in identities])])), 'utf8')
        return path

    def native_export(self, *imports):
        self.executor.workflow_factory = None
        self.write_workflow(steps=[dict(id='export', type='task', task='warp_export',
                                      params=dict(imports=list(imports), output='new.json'))])
        return self.plan()

    def plan(self, target=None, **extra):
        value = dict(version=1, id='offline-fixture', name='Offline fixture', time='08:30', weekdays=[1,2,3,4,5,6,7],
                     target=target or dict(type='workflow', path='workflow.json'))
        value.update(extra)
        return validate(value)

    def test_structure_check_does_not_read_target_or_settings(self):
        target = dict(type='workflow', path='missing.json', step_path='1/0')
        with patch('pathlib.Path.open', side_effect=AssertionError('no file reads')):
            self.assertEqual(validate_target(target), target)
        self.factory.assert_not_called()

    def test_target_rejects_commands_and_unknown_or_invalid_native_parameters(self):
        values = [dict(type='command', command='anything'), dict(type='workflow', path='a', script='x'),
                  dict(type='task', task='daily', params=dict(new_battle_run=True)),
                  dict(type='task', task='unknown'), dict(type='workflow', path='a', step_path='bad')]
        for value in values:
            with self.subTest(target=value), self.assertRaises(ScheduleError): validate_target(value)

    def test_frozen_workflow_and_parent_report_are_immutable_references(self):
        plan = self.plan()
        frozen = self.executor.freeze(plan)
        before = deepcopy(frozen)
        self.factory.assert_not_called()
        wrapped = self.executor.create(plan['target'], frozen, lambda event: None)
        self.factory.assert_called_once()
        result = wrapped.run()
        file = Path(result['run_dir']) / 'report.json'
        original = file.read_bytes()
        self.assertEqual(json.loads(original), result)
        self.assertIs(wrapped.runner.report, result)
        self.assertEqual(frozen, before)
        self.assertEqual(wrapped.schedule_source['size'], len(original))
        self.assertEqual(wrapped.schedule_source['operation'], 'task_workflow')
        self.assertEqual(file.read_bytes(), original)

    def test_changed_workflow_never_creates_runner(self):
        plan = self.plan(); frozen = self.executor.freeze(plan)
        self.write_workflow(name='Changed')
        for action in (lambda: self.executor.revalidate(frozen),
                       lambda: self.executor.create(plan['target'], frozen, lambda event: None)):
            with self.assertRaises(ScheduleError): action()
        self.factory.assert_not_called()

    def test_post_create_source_change_never_exports_or_starts_a_native_runner(self):
        for changed in ('workflow', 'import'):
            with self.subTest(changed=changed):
                source = self.write_records('records.json', '9')
                plan = self.native_export(source.name)
                frozen = self.executor.freeze(plan)
                wrapped = self.executor.create(plan['target'], frozen, lambda _: None)
                if changed == 'workflow':
                    self.write_workflow(name='Changed')
                else:
                    self.write_records(source.name, '9', '10')
                with self.assertRaises(ScheduleSourceUnverified):
                    wrapped.run()
                self.assertFalse((self.root / 'new.json').exists())
                self.assertFalse((self.root / 'runs').exists())
                self.assertIsNone(wrapped.schedule_source)

    def test_native_prepared_import_must_be_the_approved_path(self):
        from autohsr.task_workflow_run import task_spec
        source = self.write_records('records.json', '9')
        other = self.write_records('other.json', '9', '10')
        plan = self.native_export(source.name)
        frozen = self.executor.freeze(plan)

        def retarget(*args):
            settings, options = task_spec(*args)
            options['imports'] = [str(other)]
            return settings, options

        with patch('autohsr.task_workflow_run.task_spec', side_effect=retarget):
            wrapped = self.executor.create(plan['target'], frozen, lambda _: None)
        with self.assertRaises(ScheduleSourceUnverified):
            wrapped.run()
        self.assertFalse((self.root / 'new.json').exists())
        self.assertFalse((self.root / 'runs').exists())

    def test_daily_and_plan_use_their_native_local_catalog_paths(self):
        nested = self.root / 'nested'
        nested.mkdir()
        self.workflow = nested / 'workflow.json'
        self.executor.workflow_factory = None
        settings = self.executor.settings
        settings.redemption_enabled = True
        settings.redemption_source = 'file'
        settings.redemption_catalog = 'codes.json'
        for task, parent in (('daily', nested), ('plan', self.root)):
            with self.subTest(task=task):
                self.write_workflow(steps=[dict(id='catalog', type='task', task=task)])
                catalog = parent / 'codes.json'
                catalog.write_text('[]', 'utf8')
                plan = self.plan(dict(type='workflow', path='nested/workflow.json'))
                with patch('autohsr.task_workflow.ROOT', self.root):
                    frozen = self.executor.freeze(plan)
                    wrapped = self.executor.create(plan['target'], frozen, lambda _: None)
                self.assertEqual([entry['path'] for entry in frozen['dependencies']], [str(catalog.resolve())])
                self.assertEqual(wrapped.runner.specs['catalog'][0].redemption_catalog, str(catalog.resolve()))
                catalog.write_text('[{}]', 'utf8')
                with patch('autohsr.task_workflow_run.TaskWorkflowRunner.run') as native:
                    with self.assertRaises(ScheduleSourceUnverified):
                        wrapped.run()
                    native.assert_not_called()

    def test_post_create_conflict_finishes_slot_without_original_report_or_retry(self):
        source = self.write_records('records.json', '9')
        plan = self.native_export(source.name)
        store = ScheduleStore(self.root / 'late-schedules')
        store.save(plan)
        now = [datetime(2026, 10, 30, 8, 29, tzinfo=CHINA)]
        controller = Scheduler(store, self.executor, clock=lambda: now[0])
        controller.enable(plan['id'])
        controller.start()
        self.addCleanup(controller.stop)
        create = self.executor.create

        def drift(*args):
            wrapped = create(*args)
            self.write_records(source.name, '9', '10')
            return wrapped

        with patch.object(self.executor, 'create', side_effect=drift) as called:
            now[0] += timedelta(minutes=1)
            controller.tick()
            self.assertTrue(controller.wait_idle(5))
            controller.tick()
            called.assert_called_once()
        self.assertEqual(controller.snapshot()['last']['status'], 'failed')
        receipts = [path for path in store.root.rglob('*.json') if '"attempts"' in path.read_text('utf8')]
        self.assertEqual(len(receipts), 1)
        attempt, = json.loads(receipts[0].read_bytes())['attempts']
        self.assertEqual(attempt['result'], dict(status='failed', reason='target_unverified'))
        self.assertFalse((self.root / 'new.json').exists())
        self.assertFalse((self.root / 'runs').exists())

    @unittest.skipUnless(os.name == 'nt', 'requires Windows file sharing')
    def test_sources_are_readable_and_held_until_native_success_failure_or_stop(self):
        from autohsr.warp_service import run
        for outcome in ('success', 'partial', 'stopped'):
            with self.subTest(outcome=outcome):
                source = self.write_records('records.json', '9')
                plan = self.native_export(source.name)
                frozen = self.executor.freeze(plan)
                wrapped = self.executor.create(plan['target'], frozen, lambda _: None)
                originals = {path: path.read_bytes() for path in (self.workflow, source)}
                replacement = self.root / 'replacement.json'
                replacement.write_bytes(b'other content')
                checked = []

                def consume(**options):
                    for path, original in originals.items():
                        self.assertEqual(path.read_bytes(), original)
                        with self.assertRaises(OSError), path.open('r+b'):
                            self.fail('schedule source was writable during native execution')
                        with self.assertRaises(OSError):
                            replacement.replace(path)
                        checked.append(path)
                    if outcome == 'partial':
                        raise OSError('synthetic local read failure')
                    if outcome == 'stopped':
                        wrapped.stop()
                        options['cancel']()
                    return run(**options)

                with patch('autohsr.warp_service.run', side_effect=consume) as native:
                    result = wrapped.run()
                native.assert_called_once()
                self.assertEqual(checked, list(originals))
                self.assertEqual(result.status, outcome)
                original_report = Path(wrapped.schedule_source['report_path']).read_bytes()
                self.assertEqual(json.loads(original_report), result.to_dict())
                for path, original in originals.items():
                    self.assertEqual(path.read_bytes(), original)
                    with path.open('r+b'):
                        pass
                output = self.root / 'new.json'
                self.assertEqual(output.exists(), outcome == 'success')
                if output.exists():
                    output.unlink()

    @unittest.skipUnless(os.name == 'nt', 'requires Windows writable mappings')
    def test_existing_writer_rejects_entire_attempt_and_releases_earlier_handles(self):
        first = self.write_records('first.json', '9')
        second = self.write_records('second.json', '10')
        plan = self.native_export(first.name, second.name)
        frozen = self.executor.freeze(plan)
        wrapped = self.executor.create(plan['target'], frozen, lambda _: None)
        with second.open('r+b') as stream:
            mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_WRITE)
        with mapping:
            with self.assertRaises(ScheduleSourceUnverified):
                wrapped.run()
            for path in (self.workflow, first):
                with path.open('r+b'):
                    pass
        self.assertFalse((self.root / 'new.json').exists())
        self.assertFalse((self.root / 'runs').exists())

    def test_manifest_tampering_or_retargeting_is_rejected(self):
        plan = self.plan(); frozen = self.executor.freeze(plan)
        damaged = deepcopy(frozen); damaged['settings']['stamina_limit'] = 9999
        with self.assertRaises(ScheduleError): self.executor.revalidate(damaged)
        with self.assertRaises(ScheduleError):
            self.executor.create(dict(type='workflow', path='another.json'), frozen, lambda event: None)
        self.factory.assert_not_called()

    def test_game_repeat_and_automatic_resume_cannot_add_or_reuse_budget(self):
        for check in (self.executor.freeze, self.executor.preview_budget):
            for task in ('daily', 'du_rewards'):
                with self.subTest(check=check.__name__, task=task), self.assertRaises(ScheduleError):
                    check(self.plan(dict(type='task', task=task), repeat=dict(count=2)))
            for task, params in [('currency_wars_loop', dict(resume=True)),
                                 ('differential_universe', dict(resume_active=True)),
                                 ('plan', dict(resume_weekly_currency=True)),
                                 ('currency_wars_rewards', dict(resume=True))]:
                with self.subTest(check=check.__name__, task=task), self.assertRaises(ScheduleError):
                    check(self.plan(dict(type='task', task=task, params=params)))
        self.factory.assert_not_called()

    def test_preview_counts_the_whole_local_repeat_and_reads_no_dependencies(self):
        self.write_workflow(steps=[
            dict(id='loop', type='for', count=4, steps=[
                dict(id='wait', type='wait', seconds=0),
                dict(id='disabledDaily', type='task', task='daily', enabled=False),
            ]),
            dict(id='records', type='task', task='warp_analysis', params=dict(imports=['missing.json'])),
        ])
        store = ScheduleStore(self.root / 'test-schedules')
        plan = self.plan(repeat=dict(count=3))
        expected = store.save(plan)['revision']
        saved, _ = store.load(plan['id'])
        self.executor.settings.notification_enabled = True
        self.executor.busy_probe = Mock(side_effect=AssertionError('no execution marker'))
        with patch('autohsr.notify_runtime.NotificationService', side_effect=AssertionError('no credentials')):
            budget = self.executor.preview_budget(saved)
        self.assertEqual(budget, dict(id=plan['id'], revision=expected, repeat_count=3,
                                      contains_game_tasks=False, whole_batch=dict(
                                          workflow_steps=30, daily_stamina_max=0, du_runs_max=0)))
        self.assertFalse((store.root / 'slots').exists())
        self.assertFalse((self.root / 'runs').exists())
        self.executor.busy_probe.assert_not_called()
        self.factory.assert_not_called()

    def test_preview_applies_the_selected_tree_and_maximum_of_alternative_budgets(self):
        def branch(prefix, stamina, runs):
            return [
                dict(id=prefix+'daily', type='task', task='daily',
                     params=dict(tasks=['battle'], stamina_limit=stamina, challenge_count=1)),
                dict(id=prefix+'du', type='task', task='differential_universe',
                     params=dict(runs=runs, until_points=True)),
            ]

        self.write_workflow(steps=[
            dict(id='records', type='task', task='warp_analysis', params=dict(imports=['missing.json'])),
            dict(id='choose', type='if', condition=dict(step='records', field='status', op='eq', value='success'),
                 steps=branch('first', 80, 2), else_steps=branch('second', 140, 5)),
        ])
        budget = self.executor.preview_budget(self.plan())
        self.assertEqual(budget['whole_batch'], dict(workflow_steps=4, daily_stamina_max=140, du_runs_max=5))
        self.assertTrue(budget['contains_game_tasks'])
        self.assertEqual(budget['repeat_count'], 1)
        target = dict(type='workflow', path='workflow.json', step_path='1/0')
        selected = self.executor.preview_budget(self.plan(target))
        self.assertEqual(selected['whole_batch'], dict(workflow_steps=1, daily_stamina_max=80, du_runs_max=0))
        local = self.executor.preview_budget(self.plan(dict(target, step_path='0'), repeat=dict(count=3)))
        self.assertFalse(local['contains_game_tasks'])
        self.assertEqual(local['whole_batch'], dict(workflow_steps=3, daily_stamina_max=0, du_runs_max=0))
        self.factory.assert_not_called()

    def test_preview_weekly_plan_uses_configured_whole_du_batch_and_daily_cap(self):
        settings = self.executor.settings
        settings.battle = settings.weekly_enabled = True
        settings.stamina_limit, settings.weekly_runs = 120, 7
        plan = self.plan(dict(type='task', task='plan'))
        budget = self.executor.preview_budget(plan)
        self.assertEqual(budget['whole_batch'], dict(workflow_steps=1, daily_stamina_max=120, du_runs_max=7))
        self.assertEqual(self.executor.freeze(plan)['profile']['du_runs'], 10)
        settings.weekly_enabled = settings.allow_stamina_spend = False
        budget = self.executor.preview_budget(plan)
        self.assertEqual(budget['whole_batch'], dict(workflow_steps=1, daily_stamina_max=0, du_runs_max=0))
        self.factory.assert_not_called()

    def test_preview_refuses_a_saved_definition_with_a_now_invalid_target(self):
        plan = self.plan()
        self.assertEqual(self.executor.preview_budget(plan)['whole_batch']['workflow_steps'], 1)
        self.workflow.write_bytes(b'{ damaged workflow')
        with self.assertRaises(ScheduleError):
            self.executor.preview_budget(plan)
        self.assertEqual(self.workflow.read_bytes(), b'{ damaged workflow')
        self.factory.assert_not_called()

    def test_native_task_uses_frozen_settings_and_existing_workflow_adapter(self):
        plan = self.plan(dict(type='task', task='daily', params=dict(tasks=['daily'])))
        frozen = self.executor.freeze(plan)
        self.settings.stamina_limit = 0
        self.executor.settings.stamina_limit = 1
        wrapped = self.executor.create(plan['target'], frozen, lambda event: None)
        child = wrapped.runner
        self.assertEqual(child.settings.stamina_limit, frozen['settings']['stamina_limit'])
        self.assertEqual(child.document['steps'][0]['task'], 'daily')
        self.assertNotIn('new_battle_run', child.document['steps'][0]['params'])
        self.assertEqual(child.options['root'], self.root / 'runs')

    def test_local_repeat_and_import_versions_are_bound(self):
        source = self.root / 'records.json'; source.write_text('{}', 'utf8')
        plan = self.plan(dict(type='task', task='warp_analysis', params=dict(imports=['records.json'])), repeat=dict(count=3))
        frozen = self.executor.freeze(plan)
        self.assertFalse(frozen['game'])
        self.assertTrue(self.executor.revalidate(frozen))
        source.write_text('{"changed":true}', 'utf8')
        with self.assertRaises(ScheduleError): self.executor.revalidate(frozen)
        self.factory.assert_not_called()

    def test_busy_probe_is_strict_and_no_lock_is_acquired_on_enable(self):
        probe = Mock(return_value=False)
        self.executor.busy_probe = probe
        self.executor.freeze(self.plan())
        probe.assert_not_called()
        self.assertFalse(self.executor.busy())
        self.executor.busy_probe = lambda: None
        with self.assertRaises(ScheduleError): self.executor.busy()

    def test_saved_report_mismatch_preserves_original_without_claiming_success(self):
        inner = FakeWorkflow(self.settings, {}, lambda event: None, root=self.root / 'runs')
        original_run = inner.run
        def mismatch():
            report = original_run()
            (Path(report['run_dir']) / 'report.json').write_text('{"status":"failed"}', 'utf8')
            return report
        inner.run = mismatch
        wrapped = VerifiedScheduleRunner(inner)
        with self.assertRaises(ScheduleError): wrapped.run()
        self.assertEqual(inner.report['status'], 'success')
        self.assertEqual((Path(inner.report['run_dir']) / 'report.json').read_text('utf8'), '{"status":"failed"}')

    def test_real_controller_uses_frozen_native_factory_and_private_report_reference(self):
        store = ScheduleStore(self.root / 'schedules')
        plan = self.plan(); store.save(plan)
        now = [datetime(2026, 10, 30, 8, 29, tzinfo=CHINA)]
        events = []
        controller = Scheduler(store, self.executor, clock=lambda: now[0], emit=events.append)
        controller.enable(plan['id']); controller.start()
        self.factory.assert_not_called()
        now[0] += timedelta(minutes=1)
        controller.tick()
        self.assertTrue(controller.wait_idle(3))
        controller.stop()
        self.assertEqual(controller.snapshot()['last']['status'], 'success')
        self.assertNotIn('synthetic-sensitive-not-real', json.dumps(events))
        self.assertNotIn('report_path', json.dumps(events))
        # Store directory structure is an implementation detail; find the durable slot by schema content.
        receipts = [path for path in (self.root / 'schedules').rglob('*.json') if '"attempts"' in path.read_text('utf8')]
        self.assertEqual(len(receipts), 1)
        data = json.loads(receipts[0].read_text('utf8'))
        source = data['attempts'][0]['result']['source']
        self.assertTrue(Path(source['report_path']).is_file())

    def test_cli_save_check_list_preview_never_load_config_or_arm_runner(self):
        from autohsr.__main__ import main
        file = self.root / 'plan.json'; file.write_text(json.dumps(self.plan()), 'utf8')
        store = self.root / 'cli-store'
        commands = [['--schedule-check', str(file)], ['--schedule-save', str(file)], ['--schedule-list'],
                    ['--schedule-preview', 'offline-fixture', '--schedule-from', '2026-10-30T08:00:00+08:00']]
        with (patch('autohsr.config.Settings.load', side_effect=AssertionError('no config')),
              patch('autohsr.schedule_runtime.Scheduler', side_effect=AssertionError('no controller'))):
            for command in commands:
                output, error = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(main(command + ['--schedule-store-dir', str(store)]), 0, error.getvalue())
                self.assertIn('false', output.getvalue())

    def test_unverified_stopped_report_halts_real_adapter_controller_but_remains_unknown(self):
        def stopped_factory(*args, **kwargs):
            runner = FakeWorkflow(*args, **kwargs)
            original = runner.run
            def run():
                value = original()
                value.update(status='stopped', report_saved=False)
                return value
            runner.run = run
            return runner
        self.executor.workflow_factory = stopped_factory
        store = ScheduleStore(self.root / 'schedules'); plan = self.plan(); store.save(plan)
        now = [datetime(2026,10,30,8,29,tzinfo=CHINA)]
        controller = Scheduler(store, self.executor, clock=lambda:now[0])
        controller.enable(plan['id']); controller.start()
        now[0] += timedelta(minutes=1); controller.tick()
        self.assertTrue(controller.wait_idle(3))
        self.assertFalse(controller.snapshot()['running'])
        self.assertEqual(controller.snapshot()['last']['status'],'unknown')

    def test_cli_zero_limit_arms_only_this_process_and_never_creates_a_task_runner(self):
        from autohsr.__main__ import main
        store=self.root/'cli-zero'
        plan=self.plan(dict(type='workflow',path=str(self.workflow)))
        ScheduleStore(store).save(plan)
        output,error=io.StringIO(),io.StringIO()
        with (patch('autohsr.config.Settings.load',return_value=self.settings),
              patch('autohsr.schedule_cli._stop_pressed',side_effect=AssertionError('no keyboard')),
              patch('autohsr.task_workflow_run.TaskWorkflowRunner.run',side_effect=AssertionError('no execution')),
              redirect_stdout(output),redirect_stderr(error)):
            code=main(['--schedule-run',plan['id'],'--schedule-store-dir',str(store),
                       '--schedule-limit-seconds','0'])
        self.assertEqual(code,0,error.getvalue())
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['reason'],'monitor_limit')
        self.assertIsNone(result['snapshot']['last'])
        self.assertFalse(result['snapshot']['system_tasks_registered'])

    def test_cli_runs_only_next_due_native_workflow_after_clock_rollback(self):
        from autohsr.__main__ import main

        store = ScheduleStore(self.root / 'clock-cli')
        plan = self.plan(dict(type='workflow', path=str(self.workflow)))
        store.save(plan)
        first_due = datetime(2026, 10, 30, 8, 30, tzinfo=CHINA)
        next_due = first_due + timedelta(days=1)
        now = first_due - timedelta(minutes=1)
        times = iter((first_due + timedelta(minutes=5), first_due, next_due, next_due))
        controllers = []
        self.executor.workflow_factory = None  # Exercise the native wait step and saved report.

        def build(*args, **kwargs):
            controller = Scheduler(*args, **kwargs, clock=lambda: now)
            controllers.append(controller)
            return controller

        def advance(_):
            nonlocal now
            self.assertTrue(controllers[0].wait_idle(3))
            now = next(times)

        output, error = io.StringIO(), io.StringIO()
        with (patch('autohsr.config.Settings.load', return_value=self.settings),
              patch('autohsr.schedule_dispatch.NativeScheduleExecutor', return_value=self.executor),
              patch('autohsr.schedule_runtime.Scheduler', side_effect=build),
              patch('autohsr.schedule_cli.time', SimpleNamespace(monotonic=lambda: 0., sleep=advance)),
              patch('autohsr.schedule_cli._stop_pressed', side_effect=[False] * 4 + [True]),
              patch('autohsr.task_workflow_run.workflow_lease', side_effect=nullcontext),
              redirect_stdout(output), redirect_stderr(error)):
            code = main(['--schedule-run', plan['id'], '--schedule-store-dir', str(store.root)])
        self.assertEqual(code, 0, error.getvalue())
        self.assertEqual(json.loads(output.getvalue())['reason'], 'user_stop')
        receipts = store.receipts()
        self.assertEqual([(row['slot'], row['status']) for row in receipts], [(next_due.isoformat(), 'success')])
        report_path = receipts[0]['attempts'][0]['result']['source']['report_path']
        report = json.loads(Path(report_path).read_bytes())
        self.assertEqual([(step['step'], step['status']) for step in report['workflow']['steps']], [('wait', 'success')])

    def test_parent_stop_intent_survives_partial_unsaved_report_through_adapter(self):
        def factory(*args,**kwargs):
            runner=FakeWorkflow(*args,**kwargs)
            original=runner.run
            runner.stop_requested=True
            def run():
                value=original();value.update(status='partial',report_saved=False)
                return value
            runner.run=run
            return runner
        self.executor.workflow_factory=factory
        store=ScheduleStore(self.root/'stopped-parent');plan=self.plan();store.save(plan)
        now=[datetime(2026,10,30,8,29,tzinfo=CHINA)]
        controller=Scheduler(store,self.executor,clock=lambda:now[0])
        controller.enable(plan['id']);controller.start()
        now[0]+=timedelta(minutes=1);controller.tick()
        self.assertTrue(controller.wait_idle(3))
        self.assertFalse(controller.snapshot()['running'])
        self.assertEqual(controller.snapshot()['last']['status'],'unknown')

    def test_notification_stop_intent_halts_future_slots_while_game_success_stays_unchanged(self):
        from autohsr.notify_http import Reply
        from autohsr.notify_runtime import NotificationService
        started,release=threading.Event(),threading.Event()
        def request(call):
            started.set()
            self.assertTrue(release.wait(4))
            return Reply(200,b'{}')
        service=NotificationService(root=self.root/'notify',request=request)
        service.store.save(dict(id='offline-hook',provider='webhook',params=dict(url='https://example.test/notify')))
        self.executor.notification_service=service
        self.executor.settings.notification_enabled=True
        self.executor.settings.notification_profiles=['offline-hook']
        created=[];create=self.executor.create
        def capture(*args):
            runner=create(*args);created.append(runner)
            return runner
        self.executor.create=capture
        store=ScheduleStore(self.root/'notification-stage');first=self.plan();store.save(first)
        second=self.plan();second.update(id='later-slot',time='08:31');store.save(second)
        now=[datetime(2026,10,30,8,29,tzinfo=CHINA)]
        events=[];controller=Scheduler(store,self.executor,clock=lambda:now[0],emit=events.append)
        with patch('autohsr.notify_runtime._notification_key_state',return_value=(False,False,False)):
            try:
                controller.enable(first['id']);controller.enable(second['id']);controller.start()
                now[0]+=timedelta(minutes=1);controller.tick()
                self.assertTrue(started.wait(3))
                wrapped=created[0];notifier=wrapped.runner;game=notifier.runner
                file=Path(game.report['run_dir'])/'report.json';before=file.read_bytes()
                self.assertTrue(notifier.control.game_done)
                notifier.stop()  # The same public control used by notification F10.
                self.assertIs(wrapped.stop_requested,True)
                now[0]+=timedelta(minutes=1);controller.tick()
                self.assertFalse(controller.snapshot()['running'])
                release.set();self.assertTrue(controller.wait_idle(4))
                self.assertEqual(len(created),1)
                self.assertEqual(controller.snapshot()['last']['status'],'success')
                self.assertEqual(game.report['status'],'success')
                self.assertFalse(game.stopped)
                self.assertEqual(file.read_bytes(),before)
            finally:
                release.set();controller.stop(wait=True,timeout=4)


if __name__ == '__main__':
    unittest.main()
