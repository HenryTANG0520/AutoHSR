from __future__ import annotations

import base64
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

from autohsr import admin_launch as admin
from autohsr.__main__ import main


def state(spec, *, exists=False, valid=False, enabled=False, account=True):
    return dict(exists=exists, valid=valid, enabled=enabled, account_is_admin=account, task_name=spec.task_name)


class AdminLaunchTests(unittest.TestCase):
    def setUp(self):
        self.spec = admin.LaunchSpec(Path(r"D:\AutoHSR 空格\$`'&"), Path(r"D:\Python 空格\pythonw.exe"),
                                     ("-E", "-s", "-m", "autohsr"), "S-1-5-21-123-1001")

    def test_scope_separates_users_and_installations(self):
        self.assertNotEqual(self.spec.task_name, replace(self.spec, sid="S-1-5-21-123-1002").task_name)
        self.assertNotEqual(self.spec.task_name, replace(self.spec, root=self.spec.root / "dist").task_name)
        self.assertEqual(self.spec.task_name, replace(self.spec, root=Path(str(self.spec.root).upper())).task_name)

    def test_fixed_gui_arguments_do_not_forward_command_line(self):
        with patch.object(sys, "argv", ["AutoHSR.exe", "--run", "--stamina", "240"]):
            self.assertEqual(self.spec.arguments, "-E -s -m autohsr --admin-task")
            self.assertEqual(replace(self.spec, prefix=()).arguments, "--admin-task")

    def test_paths_are_data_in_encoded_powershell(self):
        with patch.object(admin.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(state(self.spec)), "")) as run:
            admin._task("status", self.spec)
        args = run.call_args.args[0]
        self.assertTrue(Path(args[0]).is_absolute())
        script = base64.b64decode(args[-1]).decode("utf-16le")
        encoded = re.search("FromBase64String\\('([^']+)'\\)", script)[1]
        payload = json.loads(base64.b64decode(encoded))
        self.assertEqual(payload["root"], str(self.spec.root))
        self.assertEqual(payload["arguments"], self.spec.arguments)
        self.assertNotIn(str(self.spec.root), script)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_unknown_or_inconsistent_backend_state_is_not_success(self):
        for output in ("invalid json", "{}", json.dumps(state(self.spec, enabled=True))):
            with self.subTest(output=output), patch.object(admin.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
                with self.assertRaises(admin.AdminLaunchError):
                    admin._task("status", self.spec)

    def test_query_timeout_and_access_denied_are_not_missing_task(self):
        with patch.object(admin.subprocess, "run", side_effect=subprocess.TimeoutExpired("powershell", 20)):
            with self.assertRaises(admin.AdminLaunchError):
                admin._task("status", self.spec)
        with patch.object(admin.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, '{"error":"Access denied"}', "")):
            with self.assertRaisesRegex(admin.AdminLaunchError, "Access denied"):
                admin._task("status", self.spec)

    def test_other_account_is_rejected_before_system_mutation(self):
        with patch.object(admin, "launch_spec", return_value=self.spec), patch.object(admin, "_task") as task:
            with self.assertRaises(admin.AdminLaunchError):
                admin.configure("enable", expected_sid="S-1-5-21-OTHER")
        task.assert_not_called()

    def test_standard_account_cannot_install_under_another_admin(self):
        with patch.object(admin, "launch_spec", return_value=self.spec), \
                patch.object(admin, "_task", return_value=state(self.spec, account=False)) as task, \
                patch.object(admin, "_elevated_manage") as elevate:
            with self.assertRaises(admin.AdminLaunchError):
                admin.configure("enable")
        self.assertEqual(task.call_count, 1)
        elevate.assert_not_called()

    def test_cancelling_uac_does_not_report_enabled_or_replay(self):
        with patch.object(admin, "launch_spec", return_value=self.spec), \
                patch.object(admin, "_task", return_value=state(self.spec)) as task, \
                patch.object(admin, "is_admin", return_value=False), \
                patch.object(admin, "_elevated_manage", side_effect=admin.AdminLaunchError("已取消")) as elevate:
            with self.assertRaisesRegex(admin.AdminLaunchError, "已取消"):
                admin.configure("enable")
        task.assert_called_once_with("status", self.spec)
        elevate.assert_called_once_with(self.spec, "enable")

    def test_install_and_remove_require_post_operation_verification(self):
        enabled = state(self.spec, exists=True, valid=True, enabled=True)
        for operation, before, after in (("enable", state(self.spec), enabled), ("disable", enabled, state(self.spec))):
            with self.subTest(operation=operation), patch.object(admin, "launch_spec", return_value=self.spec), \
                    patch.object(admin, "is_admin", return_value=True), \
                    patch.object(admin, "_task", side_effect=[before, after, after]) as task:
                self.assertEqual(admin.configure(operation), after)
                self.assertEqual([c.args[0] for c in task.call_args_list], ["status", operation, "status"])
        with patch.object(admin, "launch_spec", return_value=self.spec), patch.object(admin, "is_admin", return_value=True), \
                patch.object(admin, "_task", return_value=state(self.spec)):
            with self.assertRaises(admin.AdminLaunchError):
                admin.configure("enable")

    def test_missing_task_removal_is_idempotent(self):
        with patch.object(admin, "launch_spec", return_value=self.spec), patch.object(admin, "_task", return_value=state(self.spec)) as task:
            admin.configure("disable")
        task.assert_called_once_with("status", self.spec)

    def test_handoff_only_runs_verified_task_and_waits_for_gui(self):
        enabled = state(self.spec, exists=True, valid=True, enabled=True)
        for data, calls, raises in ((state(self.spec), 1, False), (state(self.spec, exists=True), 1, True), (enabled, 2, False)):
            with self.subTest(data=data), patch.object(admin, "is_admin", return_value=False), \
                    patch.object(admin, "launch_spec", return_value=self.spec), \
                    patch.object(admin, "_task", return_value=data) as task, patch.object(admin, "TaskSession") as sessions:
                session = sessions.return_value.__enter__.return_value
                session.wait_ready.side_effect = [False, True]
                if raises:
                    with self.assertRaises(admin.AdminLaunchError):
                        admin.handoff()
                else:
                    self.assertEqual(admin.handoff(), data["enabled"])
                self.assertEqual(task.call_count, calls)
                self.assertEqual(session.wait_ready.call_count, 2 * int(data["enabled"]))
                self.assertEqual(session.activate.call_count, int(data["enabled"]))

    def test_existing_gui_is_reused_even_after_task_reregistration(self):
        with patch.object(admin, "is_admin", return_value=False), patch.object(admin, "launch_spec", return_value=self.spec), \
                patch.object(admin, "_task", return_value=state(self.spec, exists=True, valid=True, enabled=True)) as task, \
                patch.object(admin, "TaskSession") as sessions:
            session = sessions.return_value.__enter__.return_value
            session.wait_ready.return_value = True
            self.assertTrue(admin.handoff())
        task.assert_called_once_with("status", self.spec)
        session.wait_ready.assert_called_once_with(0)
        session.activate.assert_called_once()

    def test_timeout_does_not_report_success_or_retry_task(self):
        with patch.object(admin, "is_admin", return_value=False), patch.object(admin, "launch_spec", return_value=self.spec), \
                patch.object(admin, "_task", return_value=state(self.spec, exists=True, valid=True, enabled=True)) as task, \
                patch.object(admin, "TaskSession") as sessions:
            session = sessions.return_value.__enter__.return_value
            session.wait_ready.return_value = False
            with self.assertRaises(admin.AdminLaunchError):
                admin.handoff()
        self.assertEqual(task.call_count, 2)
        session.activate.assert_not_called()

    def test_already_elevated_does_not_handoff_again(self):
        with patch.object(admin, "is_admin", return_value=True), patch.object(admin, "_task") as task:
            self.assertFalse(admin.handoff())
        task.assert_not_called()

    def test_gui_feedback_event_lifetime_and_activation(self):
        # Real Win32 events, with an isolated task identity; no task registration.
        spec = replace(self.spec, sid=admin.current_sid())
        with admin.TaskSession(spec) as receiver, admin.TaskSession(spec) as sender:
            self.assertFalse(sender.wait_ready(0))
            receiver.kernel.SetEvent(receiver.handles[0])
            self.assertTrue(sender.wait_ready(0))
            sender.activate()
            self.assertEqual(receiver.kernel.WaitForSingleObject(receiver.handles[1], 0), 0)
            self.assertEqual(receiver.kernel.WaitForSingleObject(receiver.handles[1], 0), 258)
        with admin.TaskSession(spec) as fresh:
            self.assertFalse(fresh.wait_ready(0))

    def test_admin_cli_does_not_load_settings_or_touch_game(self):
        with patch.object(admin, "status", return_value=state(self.spec)), \
                patch("autohsr.__main__.Settings.load") as load, patch("autohsr.gui.main") as gui, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--admin-launch", "status"]), 0)
        load.assert_not_called()
        gui.assert_not_called()

    def test_only_plain_default_gui_uses_handoff(self):
        with patch("autohsr.gui.main") as gui, patch.object(admin, "handoff", return_value=True) as handoff:
            self.assertEqual(main([]), 0)
            gui.assert_not_called()
            handoff.assert_called_once()
            handoff.reset_mock()
            self.assertEqual(main(["--no-admin-launch"]), 0)
            self.assertEqual(main(["--config", str(self.spec.root / "custom.json")]), 0)
            self.assertEqual(handoff.call_count, 0)
            self.assertEqual(gui.call_count, 2)

    def test_task_flag_cannot_forward_game_or_config_arguments(self):
        with patch("autohsr.gui.main") as gui, redirect_stderr(io.StringIO()):
            for extra in (["--run"], ["--config", "custom.json"], ["--game-path", "StarRail.exe"]):
                with self.subTest(extra=extra), self.assertRaises(SystemExit):
                    main(["--admin-task", *extra])
        gui.assert_not_called()

    def test_failed_handoff_and_unelevated_task_do_not_open_second_gui(self):
        with patch("autohsr.gui.main") as gui, redirect_stderr(io.StringIO()), \
                patch.object(admin, "handoff", side_effect=admin.AdminLaunchError("反馈超时")):
            self.assertEqual(main([]), 2)
        gui.assert_not_called()
        with patch("autohsr.gui.main") as gui, redirect_stderr(io.StringIO()), patch.object(admin, "is_admin", return_value=False):
            self.assertEqual(main(["--admin-task"]), 2)
        gui.assert_not_called()


if __name__ == "__main__":
    unittest.main()
