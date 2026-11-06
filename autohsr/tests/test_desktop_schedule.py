"""Desktop polling with the scheduler's fake clock and Runner."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import desktop_schedule
from autohsr.config import Settings
from autohsr.tests.test_schedule_core import Clock, FakeExecutor, FakeRunner, definition


class DesktopScheduleTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.clock = Clock()
        timer = patch.object(desktop_schedule, 'time', SimpleNamespace(monotonic=lambda: self.clock.seconds))
        timer.start()
        self.addCleanup(timer.stop)
        self.events = []
        self.ui = Mock(config_path=Path(temporary.name) / 'config.json', settings=Settings(),
                       emit=self.events.append, closing=False, busy=False, running=False)
        self.ui.root.tk.call.return_value = ''

    def build(self, executor):
        with patch.object(desktop_schedule, 'NativeScheduleExecutor', return_value=executor):
            controller = desktop_schedule.DesktopSchedule(self.ui)
        runtime = controller.runtime
        runtime.clock = self.clock
        runtime.monotonic = lambda: self.clock.seconds
        return controller

    def test_revision_removes_last_enabled_plan_but_old_runner_still_times_out(self):
        runner = FakeRunner(block=True, auto_release=False)
        executor = FakeExecutor(runner)
        controller = self.build(executor)
        runtime = controller.runtime
        self.addCleanup(runtime.stop, wait=True, timeout=3)
        self.addCleanup(runner.release.set)
        plan = definition(timeout_seconds=172800)
        saved = controller.store.save(plan)
        runtime.enable(plan['id'])
        runtime.start()

        self.clock.set()
        controller.tick()
        self.assertTrue(runner.started.wait(2))
        controller.store.save(dict(plan, name='新版本'), replace=True, expected_revision=saved['revision'])

        self.clock.set(days=1)
        self.clock.seconds = 86400
        controller.tick()
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot['enabled_ids'], [])
        self.assertEqual(snapshot['active']['revision'], saved['revision'])
        self.assertTrue(any(event.get('reason') == 'plan_changed' for event in self.events))
        self.assertFalse(runner.stopped.is_set())

        self.clock.seconds = 172800
        controller.tick()
        self.assertTrue(runner.stopped.is_set())
        self.assertTrue(runtime.snapshot()['active']['stopping'])
        runner.release.set()
        self.assertTrue(runtime.wait_idle(2))
        self.assertEqual(runtime.snapshot()['last']['reason'], 'timeout')
        self.assertEqual(executor.created, [runner])

    def test_polls_pending_and_skips_idle_with_no_armed_plans(self):
        controller = self.build(FakeExecutor())
        snapshot = dict(running=True, enabled_ids=[], active=None, pending={'id': 'queued'})
        runtime = Mock()
        controller.runtime = runtime
        runtime.snapshot.return_value = snapshot
        runtime.tick.return_value = snapshot
        controller.tick()
        runtime.tick.assert_called_once_with()

        for idle in (dict(snapshot, pending=None), dict(snapshot, running=False, enabled_ids=['saved'], pending=None)):
            with self.subTest(snapshot=idle):
                self.clock.seconds += 1
                runtime.snapshot.return_value = idle
                controller.tick()
        runtime.tick.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
