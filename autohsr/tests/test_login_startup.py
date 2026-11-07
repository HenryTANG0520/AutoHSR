from contextlib import redirect_stderr
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from autohsr import admin_launch as admin, login_startup
from autohsr.__main__ import main
from autohsr.config import CONFIG_PATH


class LoginStartupTests(TestCase):
    def setUp(self):
        root = Path("C:/isolated-autohsr-" + uuid4().hex)
        self.admin = admin.LaunchSpec(root, root / "AutoHSR.exe", (), "S-1-5-21-100")
        self.login = replace(self.admin, login=True)

    @staticmethod
    def state(spec, *, exists=False, valid=False, enabled=False):
        return dict(task_name=spec.task_name, account_is_admin=False, exists=exists, valid=valid, enabled=enabled)

    def test_login_has_an_independent_fixed_task(self):
        self.assertNotEqual(self.login.task_name, self.admin.task_name)
        self.assertNotEqual(self.login.description, self.admin.description)
        self.assertEqual(self.login.arguments, "--login-task")
        self.assertEqual(self.admin.arguments, "--admin-task")
        with self.assertRaises(ValueError):
            admin._task("run", self.login)

    def test_non_admin_can_enable_and_remove_after_readback(self):
        empty = self.state(self.login)
        enabled = self.state(self.login, exists=True, valid=True, enabled=True)
        for action, before, after in (("enable", empty, enabled), ("disable", enabled, empty)):
            with self.subTest(action=action), patch.object(login_startup, "launch_spec", return_value=self.login) as spec, \
                    patch.object(login_startup, "_task", side_effect=[before, after, after]) as task, \
                    patch.object(admin, "_elevated_manage") as elevate:
                self.assertEqual(login_startup.configure(action), after)
                self.assertEqual([call.args for call in task.call_args_list],
                                 [("status", self.login), (action, self.login), ("status", self.login)])
                spec.assert_called_once_with(login=True)
                elevate.assert_not_called()

    def test_no_success_if_scheduler_readback_disagrees(self):
        empty = self.state(self.login)
        with patch.object(login_startup, "launch_spec", return_value=self.login), \
                patch.object(login_startup, "_task", return_value=empty):
            with self.assertRaises(admin.AdminLaunchError):
                login_startup.configure("enable")

    def test_login_dispatches_only_the_fixed_desktop_entry(self):
        with patch.object(admin, "handoff", side_effect=[False, True]) as handoff, \
                patch("autohsr.gui.main") as gui, patch("autohsr.__main__.Settings.load") as load:
            self.assertEqual(main(["--login-task"]), 0)
            self.assertEqual(main(["--login-task"]), 0)
        self.assertEqual(handoff.call_count, 2)
        handoff.assert_called_with(login=True)
        gui.assert_called_once_with(CONFIG_PATH, start_in_tray=True, login_startup=True)
        load.assert_not_called()

    def test_login_entry_rejects_options(self):
        for option in ("--run", "--launch", "--start-in-tray", "--config=custom.json", "--login-task"):
            with self.subTest(option=option), patch("autohsr.gui.main") as gui, \
                    redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(["--login-task", option])
            gui.assert_not_called()

    def test_login_reuses_admin_gui_without_raising_it(self):
        enabled = self.state(self.admin, exists=True, valid=True, enabled=True)
        for ready in (True, False):
            with self.subTest(ready=ready), patch.object(admin, "is_admin", return_value=False), \
                    patch.object(admin, "launch_spec", return_value=self.admin), \
                    patch.object(admin, "_task", return_value=enabled) as task, patch.object(admin, "TaskSession") as session:
                current = session.return_value.__enter__.return_value
                current.wait_ready.side_effect = [ready, True]
                self.assertTrue(admin.handoff(login=True))
            self.assertEqual([call.args[0] for call in task.call_args_list], ["status"] if ready else ["status", "run"])
            self.assertEqual(current.request_login_tray.call_count, int(not ready))
            self.assertEqual(current.clear_login_tray.call_count, int(not ready))
            current.activate.assert_not_called()

    def test_login_handoff_failure_does_not_open_another_gui(self):
        with patch.object(admin, "handoff", side_effect=admin.AdminLaunchError("timeout")), \
                patch("autohsr.gui.main") as gui, redirect_stderr(StringIO()):
            self.assertEqual(main(["--login-task"]), 2)
        gui.assert_not_called()

    def test_real_win32_owner_and_tray_signal_lifetimes(self):
        spec = replace(self.admin, sid=admin.current_sid())
        with admin.TaskSession(spec) as login, admin.TaskSession(spec, desktop=True) as desktop, \
                admin.TaskSession(spec, desktop=True) as duplicate, admin.TaskSession(spec, desktop=True, ordinary=True) as ordinary:
            self.assertTrue(desktop.primary)
            self.assertFalse(duplicate.primary)
            self.assertTrue(ordinary.primary)
            login.request_login_tray()
            self.assertFalse(ordinary.consume_login_tray())
            self.assertTrue(desktop.consume_login_tray())
            self.assertFalse(desktop.consume_login_tray())
            login.request_login_tray()
            login.clear_login_tray()
            self.assertFalse(desktop.consume_login_tray())
        with admin.TaskSession(spec, desktop=True) as fresh:
            self.assertTrue(fresh.primary)
