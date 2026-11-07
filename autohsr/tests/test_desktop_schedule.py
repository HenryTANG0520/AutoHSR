"""Desktop polling with the scheduler's fake clock and Runner."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import desktop_schedule
from autohsr.config import Settings
from autohsr.schedule_plan import ScheduleError
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

    def logon_controller(self):
        self.enterContext(patch.object(desktop_schedule, 'CONFIG_PATH', self.ui.config_path))
        self.ui.dirty = self.ui._config_load_failed = False
        self.ui.settings.save(self.ui.config_path)
        controller = desktop_schedule.DesktopSchedule(self.ui)
        controller.runtime.clock = self.clock
        return controller

    def test_logon_restores_exact_authorization_and_skips_startup_minute(self):
        controller = self.logon_controller()
        path = self.ui.config_path.with_name('wait.json')
        path.write_text(json.dumps(dict(version=1, name='Offline fixture',
            steps=[dict(id='wait', type='wait', seconds=0)])), encoding='utf8')
        plan = definition(target=dict(type='workflow', path=str(path)))
        saved = controller.store.save(plan)
        _, manifest = controller.preview_logon(plan['id'], saved['revision'])
        controller.store.set_login_authorization(plan['id'], revision=saved['revision'], manifest=manifest)
        self.assertFalse(controller.runtime.snapshot()['running'])
        self.clock.set()
        controller.restore_on_logon()
        state = controller.runtime.tick()
        self.assertEqual(state['enabled_ids'], [plan['id']])
        self.assertTrue(state['running'])
        self.assertIsNone(state['active'])
        self.assertIsNone(state['last'])

    def test_logon_refuses_changed_source_definition_or_saved_settings(self):
        controller = self.logon_controller()
        path = self.ui.config_path.with_name('wait.json')
        path.write_text(json.dumps(dict(version=1, name='Offline fixture',
            steps=[dict(id='wait', type='wait', seconds=0)])), encoding='utf8')
        plan = definition(target=dict(type='workflow', path=str(path)))
        saved = controller.store.save(plan)
        _, manifest = controller.preview_logon(plan['id'], saved['revision'])
        controller.store.set_login_authorization(plan['id'], revision=saved['revision'], manifest=manifest)
        initial_workflow = path.read_bytes()
        path.write_bytes(initial_workflow.replace(b'Offline fixture', b'Changed fixture'))
        controller.restore_on_logon()
        self.assertFalse(controller.runtime.snapshot()['running'])
        path.write_bytes(initial_workflow)
        self.ui.settings = Settings(close_to_tray=True)
        self.ui.settings.save(self.ui.config_path)
        controller.restore_on_logon()
        self.assertFalse(controller.runtime.snapshot()['running'])
        self.assertIn(plan['id'], controller.login_results)
        self.ui.settings = Settings()
        self.ui.settings.save(self.ui.config_path)
        controller.store.save(dict(plan, name='Changed'), replace=True, expected_revision=saved['revision'])
        controller.restore_on_logon()
        self.assertFalse(controller.runtime.snapshot()['running'])
        self.assertIn(plan['id'], controller.store.login_authorizations())

    def test_logon_game_plan_requires_bound_account_and_revocation_persists(self):
        controller = self.logon_controller()
        plan = definition(target=dict(type='task', task='daily'))
        saved = controller.store.save(plan)
        with self.assertRaisesRegex(ScheduleError, '绑定账号'):
            controller.preview_logon(plan['id'], saved['revision'])
        self.ui.settings = Settings(profile_account_key='a' * 64)
        self.ui.settings.save(self.ui.config_path)
        _, manifest = controller.preview_logon(plan['id'], saved['revision'])
        controller.store.set_login_authorization(plan['id'], revision=saved['revision'], manifest=manifest)
        controller.store.set_login_authorization(plan['id'])
        controller.restore_on_logon()
        self.assertFalse(controller.runtime.snapshot()['running'])
        self.assertEqual(controller.store.login_authorizations(), {})

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
