"""Sequence custody with synthetic accounts, real Context, and fake window IO.

No NativeRunner.run, game lookup, registry, hotkeys, or real mutex is used.
Fake execute bodies isolate controller lifetime from existing game receipts.
"""
import ctypes
from contextvars import copy_context
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.currency_wars_loop import CurrencyLoopRunner
from autohsr.currency_wars_weekly_run import CurrencyWeekRunner
from autohsr.models import AutomationError, InputInterrupted, RunReport
from autohsr import workflow_identity, workflow_lease
from autohsr.workflow_identity import WorkflowIdentity, account_scope
from autohsr.tests.test_task_workflow import identity_scene


class FakeKernel:
    def __init__(self):
        self.handles = set()
        self.counter = 0
        self.lock = threading.Lock()

    def _handle(self):
        self.counter += 1
        self.handles.add(self.counter)
        return self.counter

    def CreateMutexW(self, *_):
        with self.lock:
            duplicate = bool(self.handles)
            result = self._handle()
            ctypes.set_last_error(183 if duplicate else 0)
            return result

    def OpenMutexW(self, *_):
        with self.lock:
            ctypes.set_last_error(0 if self.handles else 2)
            return self._handle() if self.handles else None

    def CloseHandle(self, handle):
        with self.lock:
            self.handles.remove(handle)


class FakeNativeChild:
    """Use the production snapshot/input proxy without a native Runner."""
    def __init__(self, directory, *, identity='100000000', recheck=False):
        self.settings = Settings(daily_synthesis=False)
        self.report = RunReport(operation='currency_wars_points', run_dir=str(directory), report_saved=True)
        self.identity, self.recheck = identity, recheck
        self.input_epoch = 0
        self.checkpoint, self.log = Mock(), Mock()
        self.stop_requested = False
        self._window = Mock(hwnd=1234)
        self._window.capture.return_value = (np.zeros((100, 200, 3), dtype=np.uint8), None)
        self.context = None

    def stop(self): self.stop_requested = True
    def toggle_pause(self): return False

    def run(self):
        workflow_lease.require_workflow_access()
        vision = Mock()
        vision.read.side_effect = lambda *_: identity_scene(self.identity)
        self.context = Context(self, self._window, vision)
        self.context.snapshot()
        self.context.window.key('esc')
        if self.recheck:
            self.input_epoch += 1
            try:
                self.context.window.key('esc')
            except InputInterrupted:
                pass
            else:
                raise AssertionError('old epoch must not authorize input')
            self.context.snapshot()
            self.context.window.key('esc')
        self.report.status = 'success'
        return self.report


class CurrencySequenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.kernel = FakeKernel()
        kernel = patch('autohsr.workflow_lease._kernel', return_value=self.kernel)
        kernel.start();self.addCleanup(kernel.stop)
        for cls in (CurrencyLoopRunner, CurrencyWeekRunner):
            monitor = patch.object(cls, '_gap_controls', lambda owner: owner._monitor_end.wait())
            monitor.start();self.addCleanup(monitor.stop)
        self.serial = 0

    def child(self, **options):
        self.serial += 1
        return FakeNativeChild(self.root / ('fake-context-' + str(self.serial)), **options)

    def controller(self, kind='loop', emit=None):
        root = self.root / (kind + '-' + str(self.serial))
        if kind == 'loop':
            return CurrencyLoopRunner(Settings(), emit, runs=2, root=root)
        return CurrencyWeekRunner(Settings(), emit, slot=SimpleNamespace(), root=root)

    def assert_protected(self):
        self.assertTrue(workflow_identity.active())
        workflow_lease.require_workflow_access()
        with self.assertRaises(AutomationError):
            with workflow_lease.workflow_lease():
                self.fail('nested task workflow admitted')
        observed = []
        def outsider():
            try:workflow_lease.require_workflow_access()
            except Exception as error:observed.append(error)
            else:observed.append(None)
        thread = threading.Thread(target=outsider)
        thread.start();thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(observed), 1)
        self.assertIsInstance(observed[0], AutomationError)

    def assert_released(self):
        self.assertFalse(workflow_identity.active())
        self.assertEqual(self.kernel.handles, set())
        workflow_lease.require_workflow_access()

    def test_loop_custody_includes_child_gaps_summary_report_and_finished(self):
        events = []
        def emit(event):
            if event['type'] == 'finished':self.assert_protected()
            events.append(event)
        owner = self.controller(emit=emit)
        first, second = self.child(), self.child()
        scopes = []
        def execute(store):
            scopes.append(workflow_identity._scope.get())
            owner._run_bound_child(first)
            self.assert_protected()
            owner._run_bound_child(second)
            owner.report.status = 'success'
        owner._execute = execute
        summary = owner._summary
        owner._summary = lambda store: (self.assert_protected(), summary(store))[-1]
        from autohsr.currency_wars_loop import _write
        def write(path, value):
            self.assert_protected()
            _write(path, value)
        with patch('autohsr.currency_wars_loop._write', side_effect=write):
            report = owner.run()
        self.assertEqual(report.status, 'success')
        self.assertTrue(report.execution_identity['verified'])
        self.assertEqual(report.execution_identity['checked_contexts'], 2)
        self.assertEqual(first._window.capture.call_count, 2)
        self.assertEqual(second._window.capture.call_count, 2)
        self.assertEqual(scopes[0].public(), report.execution_identity)
        self.assertEqual(json.loads((Path(report.run_dir) / 'report.json').read_text('utf8')), report.to_dict())
        self.assertEqual(sum(event['type'] == 'finished' for event in events), 1)
        public = json.dumps([event for event in events if event['type'] == 'execution_identity'])
        self.assertNotIn('100000000', public)
        self.assertNotIn('account_key', public)
        self.assert_released()

    def test_week_points_nested_loop_rewards_share_one_binding_until_week_finished(self):
        scopes, nested_reports, children = [], [], []
        def factory(settings, emit, **options):
            child = self.child();children.append(child)
            return child
        def emit(event):
            if event['type'] == 'finished':self.assert_protected()
        owner = self.controller('week', emit)
        owner.factory = factory
        def execute():
            scopes.append(workflow_identity._scope.get())
            owner._child('points', operation='currency_wars_points')
            self.assert_protected()
            nested = self.controller()
            def loop_execute(store):
                scopes.append(workflow_identity._scope.get())
                child = self.child();children.append(child)
                nested._run_bound_child(child)
                nested.report.status = 'success'
            nested._execute = loop_execute
            result = owner._child('loop', factory=lambda *_, **__: nested)
            nested_reports.append(result)
            self.assert_protected()
            owner._child('rewards', operation='currency_wars_rewards')
            owner.report.status = 'success'
        owner._execute = execute
        report = owner.run()
        self.assertEqual(report.status, 'success')
        self.assertIs(scopes[0], scopes[1])
        self.assertEqual(nested_reports[0]['execution_identity']['checked_contexts'], 2)
        self.assertEqual(report.execution_identity['checked_contexts'], 3)
        self.assertTrue(report.execution_identity['verified'])
        self.assertTrue(all(child._window.key.call_count == 1 for child in children))
        self.assert_released()

    def test_context_switch_blocks_changed_account_before_the_second_child_input(self):
        for kind in ('loop', 'week'):
            with self.subTest(kind=kind):
                owner = self.controller(kind)
                first, second = self.child(), self.child(identity='200000000')
                def body():
                    owner._run_bound_child(first) if kind == 'loop' else owner._run(owner.settings, phase='points', factory=lambda *_args, **_kw: first)
                    self.assert_protected()
                    owner._run_bound_child(second) if kind == 'loop' else owner._run(owner.settings, phase='rewards', factory=lambda *_args, **_kw: second)
                owner._execute = (lambda store: body()) if kind == 'loop' else body
                report = owner.run()
                self.assertIn(report.status, ('failed', 'partial'))
                self.assertTrue(report.execution_identity['account_changed'])
                self.assertFalse(report.execution_identity['verified'])
                first._window.key.assert_called_once()
                second._window.key.assert_not_called()
                self.assert_released()

    def test_each_new_context_and_epoch_require_their_own_pair(self):
        owner = self.controller()
        first, second = self.child(recheck=True), self.child()
        def execute(store):
            owner._run_bound_child(first)
            owner._run_bound_child(second)
            owner.report.status = 'success'
        owner._execute = execute
        report = owner.run()
        self.assertEqual(report.status, 'success')
        self.assertEqual(first._window.capture.call_count, 4)
        self.assertEqual(first._window.key.call_count, 2)
        self.assertEqual(second._window.capture.call_count, 2)
        self.assertEqual(report.execution_identity['observations'], 3)
        self.assert_released()

    def test_children_reuse_outer_workflow_scope_without_replacing_publish_or_lease(self):
        published = []
        parent = WorkflowIdentity(self.root / 'parent', required=True, publish=published.append)
        owner = self.controller()
        child = self.child()
        def execute(store):
            self.assertIs(workflow_identity._scope.get(), parent)
            owner._run_bound_child(child)
            owner.report.status = 'success'
        owner._execute = execute
        with workflow_lease.workflow_lease(), account_scope(parent):
            handles = set(self.kernel.handles)
            report = owner.run()
            self.assertEqual(self.kernel.handles, handles)
            self.assertIs(workflow_identity._scope.get(), parent)
            self.assert_protected()
        self.assertTrue(published)
        self.assertTrue(report.execution_identity['verified'])
        self.assertFalse((Path(report.run_dir) / 'identity').exists())
        self.assert_released()

    def test_no_native_observations_do_not_claim_verified_identity(self):
        for kind in ('loop', 'week'):
            with self.subTest(kind=kind):
                owner = self.controller(kind)
                def body():
                    self.assert_protected()
                    owner.report.status = 'success'
                owner._execute = (lambda store: body()) if kind == 'loop' else body
                report = owner.run()
                self.assertEqual(report.execution_identity['status'], 'not_observed')
                self.assertFalse(report.execution_identity['bound'])
                self.assertFalse(report.execution_identity['verified'])
                self.assertEqual(report.execution_identity['checked_contexts'], 0)
                self.assert_released()

    def test_identity_storage_failure_blocks_input_and_releases_custody(self):
        owner = self.controller()
        child = self.child()
        owner._execute = lambda store: owner._run_bound_child(child)
        with patch.object(WorkflowIdentity, '_persist', side_effect=OSError('synthetic disk failure')):
            report = owner.run()
        self.assertEqual(report.status, 'failed')
        child._window.key.assert_not_called()
        self.assertEqual(report.execution_identity['status'], 'storage_failed')
        self.assertFalse(report.execution_identity['verified'])
        self.assert_released()

    def test_another_thread_cannot_start_a_controller_or_close_parent_custody(self):
        for copied in (False, True):
            with self.subTest(copied_context=copied):
                parent = WorkflowIdentity(self.root / 'parent', required=True)
                child = self.controller()
                child._execute = Mock()
                returned = []
                with workflow_lease.workflow_lease(), account_scope(parent):
                    handles = set(self.kernel.handles)
                    inherited = copy_context()
                    def other():returned.append(child.run())
                    thread = threading.Thread(target=lambda: inherited.run(other) if copied else other())
                    thread.start();thread.join(timeout=3)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(len(returned), 1)
                    self.assertEqual(returned[0].status, 'failed')
                    child._execute.assert_not_called()
                    self.assertEqual(self.kernel.handles, handles)
                    self.assertIs(workflow_identity._scope.get(), parent)
                self.assert_released()

    def test_report_failure_and_finished_callback_failure_always_release_both_scopes(self):
        for kind in ('loop', 'week'):
            for failure in ('write', 'finished'):
                with self.subTest(kind=kind, failure=failure):
                    def emit(event):
                        if event['type'] == 'finished':
                            self.assert_protected()
                            if failure == 'finished':raise RuntimeError('synthetic callback failure')
                    owner = self.controller(kind, emit)
                    def body():owner.report.status = 'success'
                    owner._execute = (lambda store: body()) if kind == 'loop' else body
                    if failure == 'write':
                        module = 'autohsr.currency_wars_loop' if kind == 'loop' else 'autohsr.currency_wars_weekly_run'
                        with patch(module + '._write', side_effect=OSError('synthetic report write failure')):
                            report = owner.run()
                        self.assertEqual(report.status, 'partial')
                        self.assertFalse(report.report_saved)
                    else:
                        with self.assertRaises(RuntimeError):owner.run()
                    self.assert_released()

    def test_identity_event_failure_still_saves_original_failure_before_finished(self):
        for kind in ('loop', 'week'):
            with self.subTest(kind=kind):
                finished = []
                def emit(event):
                    if event['type'] == 'execution_identity' and event['bound']:
                        raise RuntimeError('synthetic identity event failure')
                    if event['type'] == 'finished':
                        self.assert_protected()
                        finished.append(event['report'])
                owner = self.controller(kind, emit)
                child = self.child()
                def body():
                    if kind == 'loop':owner._run_bound_child(child)
                    else:owner._run(owner.settings, phase='points', factory=lambda *_args, **_kw: child)
                owner._execute = (lambda store: body()) if kind == 'loop' else body
                report = owner.run()
                self.assertIn(report.status, ('failed', 'partial'))
                self.assertIn('identity event failure', report.error)
                self.assertTrue(report.report_saved)
                child._window.key.assert_not_called()
                stored = json.loads((Path(report.run_dir) / 'report.json').read_text('utf8'))
                self.assertEqual(stored, report.to_dict())
                self.assertEqual(finished, [stored])
                self.assert_released()


if __name__ == '__main__':
    unittest.main()
