"""Plan boundaries use real Context identity checks and wholly synthetic IO."""
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.currency_wars_identity import UID_COUNTEREVIDENCE
from autohsr.models import AutomationError, RunReport, Stopped, Token
from autohsr.plan_runner import PlanRunner
from autohsr import workflow_identity, workflow_lease
from autohsr.tests import test_task_workflow as identity_fixtures
from autohsr.tests import test_weekly_plan as weekly_fixtures
from autohsr.weekly_plan import CHINA, WeeklyReceipt


class MemoryKernel:
    """Exercise the real lease protocol without any Windows execution marker."""

    def __init__(self):
        self.handles = set()
        self.next_handle = 0
        self.created = 0
        self.errors = threading.local()

    def set_error(self, value):
        self.errors.value = value

    def get_error(self):
        return getattr(self.errors, 'value', 0)

    def handle(self):
        self.next_handle += 1
        self.handles.add(self.next_handle)
        return self.next_handle

    def CreateMutexW(self, security, owner, name):
        self.set_error(183 if self.handles else 0)
        self.created += 1
        return self.handle()

    def OpenMutexW(self, access, inherit, name):
        self.set_error(0 if self.handles else 2)
        return self.handle() if self.handles else None

    def CloseHandle(self, handle):
        self.handles.remove(handle)


class PlanSequenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.kernel = MemoryKernel()
        for target, value in (('autohsr.workflow_lease._kernel', lambda: self.kernel),
                ('autohsr.workflow_lease.C.set_last_error', self.kernel.set_error),
                ('autohsr.workflow_lease.C.get_last_error', self.kernel.get_error)):
            mocked = patch(target, value, create=True)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.settings = Settings(weekly_enabled=True, daily_synthesis=False, overlay_logs=False)
        self.now = datetime.now(CHINA)
        self.accounts = ['100000000', '100000000']
        self.actions, self.children, self.events = [], [], []
        self.on_event = lambda event: None
        self.before_input = lambda child: None
        self.read_account = lambda child: identity_fixtures.identity_scene(child.account)

    def emit(self, event):
        self.events.append(event)
        self.on_event(event)

    def factory(self, settings, emit, **options):
        owner = self
        class Child:
            input_epoch = 0
            inactive_duration = 0.
            paused = False
            stopped = False

            def __init__(self):
                self.settings = settings
                self.operation = options['operation']
                self.account = owner.accounts.pop(0)
                folder = owner.root / ('child-' + str(len(owner.children)))
                folder.mkdir()
                if self.operation == 'differential_universe':
                    self.result = weekly_fixtures.du_report(folder, options['du_runs'])
                else:
                    self.result = dict(operation='daily', status='success', report_saved=True,
                        run_dir=str(folder), daily_verified=True, stamina_spent=120,
                        stamina_pending=0, results=[dict(task='daily', status='ok', detail='synthetic daily')])
                    (folder / 'report.json').write_text(json.dumps(self.result), encoding='utf-8')
                self.report = RunReport(operation=self.operation, run_dir=self.result['run_dir'])
                self.raw = Mock()
                self.raw.capture.return_value = (np.zeros((100, 200, 3), np.uint8), None)
                owner.children.append(self)

            def checkpoint(self):
                if self.stopped:
                    raise Stopped('synthetic stop')

            def log(self, *args):
                pass

            def stop(self):
                self.stopped = True

            def toggle_pause(self):
                self.paused = not self.paused
                return self.paused

            def run(self):
                workflow_lease.require_workflow_access()
                vision = Mock()
                vision.read.side_effect = lambda image, geometry: owner.read_account(self)
                context = Context(self, self.raw, vision)
                self.context = context
                context.sleep = lambda seconds: self.checkpoint()
                context.snapshot()
                owner.before_input(self)
                context.window.click(.1, .2, None)
                owner.actions.append(self.operation)
                if self.operation == 'differential_universe':
                    guard = options['weekly_plan']
                    guard.receipt = WeeklyReceipt(owner.root, 'a' * 24, guard.slot)
                    guard.already_complete = not guard.receipt.begin(guard.settings)
                emit(dict(type='finished', report=self.result))
                return self.result
        return Child()

    def runner(self):
        return PlanRunner(self.settings, self.emit, root=self.root, now=self.now,
                          runner_factory=self.factory)

    def outsider(self):
        result = []
        def attempt():
            try:
                workflow_lease.require_workflow_access()
                with workflow_lease.workflow_lease():
                    result.append('acquired')
            except AutomationError:
                result.append('blocked')
        worker = threading.Thread(target=attempt)
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        return result

    def assert_anonymous(self, value):
        raw = json.dumps(value)
        for secret in ('100000000', '200000000', 'account_key', 'run_dir', str(self.root)):
            self.assertNotIn(secret, raw)

    def test_same_account_contexts_share_proof_and_saved_parent_summary(self):
        report = self.runner().run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(self.actions, ['daily', 'differential_universe'])
        self.assertTrue(report.execution_identity['verified'])
        self.assertEqual(report.execution_identity['checked_contexts'], 2)
        self.assertTrue(all(child.raw.capture.call_count == 2 for child in self.children))
        self.assert_anonymous(report.execution_identity)
        saved = json.loads((Path(report.run_dir) / 'report.json').read_text('utf-8'))
        self.assertEqual(saved, report.to_dict())
        public = [event for event in self.events if event['type'] == 'execution_identity']
        self.assertTrue(public)
        for event in public:
            self.assert_anonymous(event)
        self.assertFalse(self.kernel.handles)

    def test_changed_account_blocks_second_input_and_keeps_original_daily(self):
        self.accounts[1] = '200000000'
        report = self.runner().run()
        self.assertEqual(report.status, 'partial')
        self.assertEqual(self.actions, ['daily'])
        self.children[1].raw.click.assert_not_called()
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_spent, 120)
        self.assertEqual(report.weekly_plan['status'], 'needs_review')
        self.assertTrue(report.execution_identity['account_changed'])
        original = json.loads((Path(self.children[0].result['run_dir']) / 'report.json').read_text('utf-8'))
        self.assertEqual(original, self.children[0].result)

    def test_weak_complete_other_account_prevents_weekly_identity_proof(self):
        def read(child):
            scene = identity_fixtures.identity_scene(child.account)
            if child.operation == 'differential_universe':
                scene.field_reads[UID_COUNTEREVIDENCE] = (Token('UID:200000000', .73, (.12, .96, .21, .99)),)
            return scene

        self.read_account = read
        report = self.runner().run()
        self.assertEqual(self.actions, ['daily'])
        self.children[1].raw.click.assert_not_called()
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.execution_identity['checked_contexts'], 1)
        self.assertEqual(report.weekly_plan['status'], 'needs_review')
        self.assertFalse(list(self.root.glob('weekly-plan/*/*.json')))

    def test_same_epoch_hidden_uid_preserves_verified_weekly_context(self):
        def hide_uid(child):
            if child.operation != 'differential_universe':
                return

            def read(owner):
                scene = identity_fixtures.identity_scene(owner.account)
                if owner is child:
                    scene.tokens.clear()
                return scene

            self.read_account = read
            child.context.snapshot()

        self.before_input = hide_uid
        report = self.runner().run()
        self.assertEqual(report.status, 'success', report.error)
        self.assertEqual(self.actions, ['daily', 'differential_universe'])
        self.assertEqual(report.execution_identity['checked_contexts'], 2)

    def test_lease_blocks_other_thread_in_child_gap_and_finished_callback(self):
        checkpoints = []
        def event(event):
            if event['type'] in ('plan_daily_result', 'finished'):
                checkpoints.append((event['type'], self.outsider()))
        self.on_event = event
        self.assertEqual(self.runner().run().status, 'success')
        self.assertEqual(checkpoints, [('plan_daily_result', ['blocked']), ('finished', ['blocked'])])
        self.assertEqual(self.outsider(), ['acquired'])

    def test_existing_outer_lease_and_identity_are_joined_and_not_replaced(self):
        public = []
        outer = workflow_identity.WorkflowIdentity(self.root / 'outer', required=True, publish=public.append)
        with workflow_lease.workflow_lease(), workflow_identity.account_scope(outer):
            report = self.runner().run()
            self.assertIs(workflow_identity._scope.get(), outer)
            self.assertEqual(self.kernel.created, 1)
            self.assertEqual(len(self.kernel.handles), 1)
            self.assertEqual(report.execution_identity, outer.public())
            self.assertEqual(report.execution_identity['checked_contexts'], 2)
            self.assertFalse((Path(report.run_dir) / 'identity').exists())
        self.assertTrue(public)
        self.assertFalse(self.kernel.handles)

    def test_changed_epoch_before_child_input_drops_the_old_target(self):
        self.before_input = lambda child: setattr(child, 'input_epoch', child.input_epoch + 1)
        report = self.runner().run()
        self.assertEqual(report.status, 'failed')
        self.assertEqual(self.actions, [])
        self.children[0].raw.click.assert_not_called()
        self.assertFalse(report.execution_identity['verified'])
        self.assertFalse(self.kernel.handles)

    def test_failed_report_write_keeps_lease_until_finished_then_releases(self):
        seen = []
        self.on_event = lambda event: seen.extend(self.outsider()) if event['type'] == 'finished' else None
        with patch('autohsr.plan_runner.replace_file', side_effect=OSError('synthetic locked report')):
            report = self.runner().run()
        self.assertFalse(report.report_saved)
        self.assertEqual(report.status, 'partial')
        self.assertTrue(report.daily_verified)
        self.assertEqual(seen, ['blocked'])
        self.assertFalse(self.kernel.handles)

    def test_finished_callback_failure_still_releases_both_scopes(self):
        def event(event):
            if event['type'] == 'finished':
                self.assertEqual(self.outsider(), ['blocked'])
                raise RuntimeError('synthetic observer failure')
        self.on_event = event
        with self.assertRaisesRegex(RuntimeError, 'observer failure'):
            self.runner().run()
        self.assertFalse(self.kernel.handles)
        self.assertIsNone(workflow_identity._scope.get())

    def test_identity_observer_failure_still_saves_the_original_failed_report(self):
        attempts = []
        def event(event):
            if event['type'] == 'execution_identity':
                attempts.append(event)
                raise RuntimeError('synthetic identity observer failure')
        self.on_event = event
        report = self.runner().run()
        self.assertEqual(report.status, 'failed')
        self.assertIn('identity observer failure', report.error)
        self.assertTrue(report.report_saved)
        self.assertEqual(self.children, [])
        self.assertEqual(len(attempts), 1)
        saved = json.loads((Path(report.run_dir) / 'report.json').read_text('utf-8'))
        self.assertEqual(saved, report.to_dict())
        self.assertFalse(report.execution_identity['verified'])
        self.assertFalse(self.kernel.handles)
        self.assertIsNone(workflow_identity._scope.get())

    def test_no_game_context_does_not_claim_verified_identity(self):
        self.settings = replace(self.settings, assignments=False, battle=False, daily=False,
                                mail=False, battlepass=False, weekly_day=7)
        self.now = datetime(2026, 10, 28, 12, tzinfo=CHINA)
        report = self.runner().run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(self.children, [])
        self.assertFalse(report.execution_identity['bound'])
        self.assertFalse(report.execution_identity['verified'])
        self.assertEqual(report.execution_identity['checked_contexts'], 0)
        self.assertFalse(self.kernel.handles)


if __name__ == '__main__':
    unittest.main()
