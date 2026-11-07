"""Desktop update controls with a hidden Tk root and a fake tool worker."""

import threading
import tkinter as tk
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import desktop_update as desktop
from autohsr.app_update import Release, UpdateError
from autohsr.app_update_dispatch import UpdateCheck


class DesktopUpdateTests(TestCase):
    def setUp(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        self.ui = SimpleNamespace(
            root=SimpleNamespace(after_idle=Mock()), ui_scale=1, busy=False, closing=False, dirty=False,
            book_editor=None, stop_requested=threading.Event(), _close=Mock(), _tool_action_changed=Mock(),
            desktop_schedule=SimpleNamespace(owned=False, runtime=SimpleNamespace(wait_idle=Mock(return_value=True))),
            _submit_tool_job=Mock(return_value=True),
        )
        self.panel = desktop.build_update_panel(root, self.ui)
        self.release = Release('v0.3.0', 'a' * 64)
        self.candidate = UpdateCheck('0.2.0', self.release, 'available', True, False)

    def callbacks(self):
        _, work, finish, error = self.ui._submit_tool_job.call_args.args
        return work, finish, error

    def test_check_only_offers_install_after_exact_candidate_is_confirmed(self):
        self.assertEqual(self.panel.primary_action()[0], '检查更新')
        self.panel._check()
        work, finish, _ = self.callbacks()
        with patch.object(desktop, 'check_for_update', return_value=self.candidate) as lookup:
            finish(work(self.ui.stop_requested))
        lookup.assert_called_once_with(desktop.ROOT)
        self.assertEqual(self.panel.primary_action()[0::2], ('更新并重启', True))
        self.ui._close.assert_not_called()

        self.panel._update()
        work, finish, _ = self.callbacks()
        with patch.object(desktop, 'begin', return_value={'status': 'queued', 'job': '1' * 32}) as handoff:
            finish(work(self.ui.stop_requested))
        self.assertEqual(handoff.call_args.kwargs['expected_release'], self.release)
        self.ui._close.assert_not_called()
        self.ui.root.after_idle.call_args.args[0]()
        self.ui._close.assert_called_once_with()

    def test_unsaved_settings_and_pending_scheduler_block_handoff(self):
        self.panel.checked = self.candidate
        self.ui.dirty = True
        self.panel._update()
        self.ui._submit_tool_job.assert_not_called()
        self.ui.dirty = False
        self.ui.desktop_schedule.runtime.wait_idle.return_value = False
        self.panel._update()
        self.ui._submit_tool_job.assert_not_called()

    def test_late_stop_withdraws_queued_job_and_keeps_window_open(self):
        self.panel.checked = self.candidate
        self.panel._update()
        _, finish, _ = self.callbacks()
        finish({'status': 'queued', 'job': '1' * 32})
        self.ui.stop_requested.set()
        with patch.object(desktop, 'cancel_job') as cancel:
            self.ui.root.after_idle.call_args.args[0]()
        cancel.assert_called_once_with(desktop.ROOT / 'runs' / 'app-update' / ('1' * 32))
        self.ui._close.assert_not_called()
        self.assertIn('撤回', self.panel.feedback.get())

    def test_source_checks_and_changed_release_offer_another_check(self):
        self.panel._check()
        _, finish, error = self.callbacks()
        finish(UpdateCheck('0.2.0', self.release, 'available', False, False))
        self.assertEqual(self.panel.primary_action()[0], '检查更新')
        error(UpdateError('release_changed_after_check'))
        self.assertIn('重新检查', self.panel.feedback.get())

    def test_history_and_explicit_backup_acceptance_are_separate(self):
        self.panel._show_history()
        _, finish, _ = self.callbacks()
        finish(({'version': '0.3.0', 'status': 'success', 'desktop_restart': 'ready', 'installation': 'installed'},
                {'installation': 'installed', 'backup_retained': True}))
        self.assertTrue(self.panel.can_accept)
        self.assertIn('窗口已就绪', self.panel.history.get())
        self.panel._accept()
        work, finish, _ = self.callbacks()
        with patch.object(desktop, 'maintenance', return_value={'backup_retained': False}) as accept:
            finish(work(self.ui.stop_requested))
        accept.assert_called_once_with(desktop.ROOT, 'accept')
        self.assertFalse(self.panel.can_accept)
