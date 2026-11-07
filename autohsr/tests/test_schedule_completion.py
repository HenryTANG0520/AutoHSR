from contextlib import nullcontext
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from autohsr import completion_runtime
from autohsr.config import Settings
from autohsr.models import RunReport, TaskResult
from autohsr.schedule_dispatch import NativeScheduleExecutor
from autohsr.schedule_plan import CHINA, ScheduleError, revision, validate
from autohsr.schedule_runtime import Scheduler
from autohsr.schedule_store import ScheduleStore


class _FixtureRunner:
    def __init__(self, settings, document, emit, *, root, **options):
        self.root, self.emit = root, emit
        self.stop_requested, self.paused = False, False

    def stop(self):
        self.stop_requested = True

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused

    def run(self):
        completion_runtime.bind_window(SimpleNamespace(hwnd=21))
        directory = self.root / uuid4().hex
        directory.mkdir(parents=True)
        report = RunReport(status='success', operation='task_workflow', report_saved=True,
                           run_dir=str(directory), started_at='fixture-start', finished_at='fixture-end',
                           results=[TaskResult('task_workflow', 'ok', 'fixture complete')])
        (directory / 'report.json').write_text(json.dumps(report.to_dict()), encoding='utf8')
        return report


class ScheduleCompletionTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.store = ScheduleStore(self.root / 'schedule')
        self.now = datetime(2026, 11, 8, 7, 59, tzinfo=CHINA)
        self.executor = NativeScheduleExecutor(
            Settings(game_path=r'C:\fixture\StarRail.exe', battle=False,
                     finish_sound=True, finish_close_game=True),
            base_dir=self.root, run_root=self.root / 'runs', workflow_factory=_FixtureRunner,
            busy_probe=lambda: False)
        (self.root / 'local.json').write_text(json.dumps(dict(
            version=1, name='Fixture', steps=[dict(id='wait', type='wait', seconds=0)])), encoding='utf8')
        self.scheduler = Scheduler(self.store, self.executor, clock=lambda: self.now)
        self.sound = self.enterContext(patch.object(completion_runtime, '_play'))
        self.close = self.enterContext(patch('autohsr.completion_window.CloseTarget'))
        self.target = self.close.return_value
        self.target.request.return_value = ('ok', 'fixture closed')
        self.enterContext(patch.object(completion_runtime, 'native_idle_lease', side_effect=nullcontext))
        self.addCleanup(self.scheduler.stop, wait=True, timeout=3)

    def plan(self, **extra):
        value = dict(version=1, id='finish-fixture', name='Fixture', time='08:00',
                     target=dict(type='workflow', path='local.json'))
        return validate(value | extra)

    def trigger(self, plan):
        self.store.save(plan)
        self.scheduler.enable(plan['id'])
        self.scheduler.start()
        self.now = self.now.replace(hour=8, minute=0)
        self.scheduler.tick()
        self.assertTrue(self.scheduler.wait_idle(3))
        return self.scheduler.snapshot()['last']

    def test_disabled_options_keep_previous_plan_revision(self):
        base = self.plan()
        self.assertEqual(revision(base), revision(base | {'completion': dict(sound=False, close_game=False)}))
        self.assertNotIn('completion', self.executor.freeze(base))
        self.assertNotEqual(revision(base), revision(base | {'completion': dict(sound=True)}))
        with self.assertRaises(ScheduleError):
            self.plan(completion={'sound': 1})
        with self.assertRaises(ScheduleError):
            self.executor.freeze(self.plan(completion={'close_game': True}))

    def test_repeated_local_schedule_plays_once_after_all_attempts(self):
        plan = self.plan(repeat=dict(count=2), completion=dict(sound=True))

        def verified_after_terminal():
            files = list(self.store.root.rglob('*.json'))
            slots = [json.loads(path.read_bytes()) for path in files]
            slot = next(value for value in slots if 'attempts' in value)
            self.assertEqual(slot['status'], 'success')
            self.assertEqual([attempt['status'] for attempt in slot['attempts']], ['success', 'success'])

        self.sound.side_effect = verified_after_terminal
        outcome = self.trigger(plan)
        self.assertEqual(outcome['completion']['sound'], 'requested')
        self.sound.assert_called_once()
        self.close.assert_not_called()
        self.assertEqual(len(list((self.root / 'runs').glob('*/completion.json'))), 1)

    def test_exit_reuses_bound_native_target_and_leaves_original_report(self):
        plan = self.plan(target=dict(type='task', task='daily'), completion=dict(close_game=True))
        outcome = self.trigger(plan)
        self.assertEqual(outcome['completion']['close_game'], 'ok')
        self.assertNotIn('close_detail', outcome['completion'])
        self.close.assert_called_once()
        self.target.request.assert_called_once()
        self.target.release.assert_called_once()
        self.sound.assert_not_called()
        saved = next((self.root / 'runs').glob('*/report.json'))
        self.assertEqual(json.loads(saved.read_bytes())['exit_status'], 'not_requested')

    def test_failed_slot_write_prevents_completion(self):
        with patch.object(self.store, 'finish', side_effect=OSError('fixture write failure')):
            outcome = self.trigger(self.plan(completion=dict(sound=True)))
        self.assertEqual(outcome['status'], 'unknown')
        self.sound.assert_not_called()

    def test_changed_original_bytes_prevent_completion(self):
        finish = self.store.finish

        def change_report(*args, **options):
            finish(*args, **options)
            saved = next((self.root / 'runs').glob('*/report.json'))
            saved.write_bytes(saved.read_bytes() + b'\n')

        with patch.object(self.store, 'finish', side_effect=change_report):
            outcome = self.trigger(self.plan(completion=dict(sound=True)))
        self.assertEqual(outcome['completion']['sound'], 'skipped')
        self.sound.assert_not_called()

    def test_new_plan_revision_invalidates_pending_completion_permission(self):
        plan = self.plan(completion=dict(sound=True))
        finish = self.store.finish

        def edit_plan(*args, **options):
            finish(*args, **options)
            self.store.save(plan | {'completion': {}}, replace=True, expected_revision=revision(plan))

        with patch.object(self.store, 'finish', side_effect=edit_plan):
            outcome = self.trigger(plan)
        self.assertEqual(outcome['status'], 'success')
        self.assertEqual(outcome['completion']['status'], 'skipped')
        self.sound.assert_not_called()

    def test_manual_preferences_do_not_authorize_scheduled_actions(self):
        outcome = self.trigger(self.plan(target=dict(type='task', task='daily')))
        self.assertEqual(outcome['status'], 'success')
        self.assertNotIn('completion', outcome)
        self.sound.assert_not_called()
        self.close.assert_not_called()
