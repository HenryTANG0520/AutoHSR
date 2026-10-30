"""Schedule integration with fake task-tree Runners; never game or system input."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import uuid

from autohsr.config import Settings
from autohsr.schedule_dispatch import NativeScheduleExecutor, VerifiedScheduleRunner, validate_target
from autohsr.schedule_plan import CHINA, ScheduleError, validate
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

    def test_manifest_tampering_or_retargeting_is_rejected(self):
        plan = self.plan(); frozen = self.executor.freeze(plan)
        damaged = deepcopy(frozen); damaged['settings']['stamina_limit'] = 9999
        with self.assertRaises(ScheduleError): self.executor.revalidate(damaged)
        with self.assertRaises(ScheduleError):
            self.executor.create(dict(type='workflow', path='another.json'), frozen, lambda event: None)
        self.factory.assert_not_called()

    def test_game_repeat_and_automatic_resume_cannot_add_or_reuse_budget(self):
        target = dict(type='task', task='daily')
        with self.assertRaises(ScheduleError):
            self.executor.freeze(self.plan(target, repeat=dict(count=2)))
        for task, params in [('currency_wars_loop', dict(resume=True)),
                             ('differential_universe', dict(resume_active=True)),
                             ('plan', dict(resume_weekly_currency=True)),
                             ('currency_wars_rewards', dict(resume=True))]:
            with self.subTest(task=task), self.assertRaises(ScheduleError):
                self.executor.freeze(self.plan(dict(type='task', task=task, params=params)))
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
