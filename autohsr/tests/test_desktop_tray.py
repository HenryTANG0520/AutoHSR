from contextlib import redirect_stderr
from io import StringIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr.__main__ import main
from autohsr.config import CONFIG_PATH, Settings
from autohsr.desktop_tray import DesktopTray
from autohsr.gui import AutoHSRWindow
from autohsr.tray_native import _CALLBACK, NativeTray


class DesktopTrayTests(TestCase):
    def setUp(self):
        self.root = Mock()
        self.ui = SimpleNamespace(root=self.root, closing=False, result_alert=Mock(), _close=Mock())
        self.tray = DesktopTray(self.ui)
        self.tray.native = Mock()
        self.ui._tray = self.tray
        self.ui._restore = AutoHSRWindow._restore.__get__(self.ui)

    def test_park_and_restore_keep_the_same_window_and_task(self):
        self.assertTrue(self.tray.park())
        self.root.withdraw.assert_called_once()
        self.ui._restore()
        self.root.deiconify.assert_not_called()

        self.root.reset_mock()
        self.tray._post('open')
        self.assertEqual(self.root.mock_calls, [])
        self.tray._poll()
        self.tray.native.hide.assert_called_once()
        self.root.deiconify.assert_called_once()
        self.ui._close.assert_not_called()
        self.assertFalse(self.tray.parked)

    def test_icon_registration_failure_keeps_window_available(self):
        self.tray.native.show.return_value = False
        AutoHSRWindow._park_in_tray(self.ui)
        self.root.withdraw.assert_not_called()
        self.root.deiconify.assert_called_once()
        self.ui.result_alert.set.assert_called_once()

    def test_taskbar_failure_reopens_window_and_explicit_exit_uses_close(self):
        self.tray.park()
        self.tray._post('unavailable')
        self.tray._poll()
        self.root.deiconify.assert_called_once()
        self.ui.result_alert.set.assert_called_once()
        self.ui._close.assert_not_called()

        self.tray.park()
        self.tray._post('exit')
        self.tray._poll()
        self.ui._close.assert_called_once()
        self.assertFalse(self.tray.parked)

    def test_destroy_releases_icon_only_for_root(self):
        self.tray._destroyed(SimpleNamespace(widget=Mock()))
        self.tray.native.close.assert_not_called()
        self.tray._destroyed(SimpleNamespace(widget=self.root))
        self.tray.native.close.assert_called_once()

    def test_window_close_uses_saved_preference(self):
        self.ui.book_editor = None
        self.ui.settings = Settings()
        self.ui.close_to_tray = Mock()
        self.ui.close_to_tray.get.return_value = True
        self.ui._park_in_tray = Mock()
        AutoHSRWindow._request_close(self.ui)
        self.ui._close.assert_called_once()
        self.ui._park_in_tray.assert_not_called()

        self.ui.settings = Settings(close_to_tray=True)
        AutoHSRWindow._request_close(self.ui)
        self.ui._park_in_tray.assert_called_once()
        self.ui._close.assert_called_once()

    def test_native_callback_filters_icon_id_and_recovers_taskbar(self):
        native = NativeTray.__new__(NativeTray)
        native.visible, native.modern = True, True
        native.dispatch = Mock()
        native._menu = Mock()
        native._shell_ready = 0xc000
        native.show = Mock(return_value=False)
        native._receive(None, _CALLBACK, 0, (2 << 16) | 0x400)
        native.dispatch.assert_not_called()
        native._receive(None, _CALLBACK, 0, (1 << 16) | 0x401)
        native.dispatch.assert_called_once_with('open')
        native._receive(None, _CALLBACK, 0, (1 << 16) | 0x7b)
        native._menu.assert_called_once()
        native._receive(None, native._shell_ready, 0, 0)
        native.show.assert_called_once()
        self.assertFalse(native.visible)
        native.dispatch.assert_called_with('unavailable')

    def test_start_in_tray_only_dispatches_desktop(self):
        with patch('autohsr.gui.main') as gui, patch('autohsr.admin_launch.handoff') as handoff:
            self.assertEqual(main(['--start-in-tray']), 0)
        gui.assert_called_once_with(CONFIG_PATH, start_in_tray=True)
        handoff.assert_not_called()

    def test_start_in_tray_rejects_other_modes(self):
        for option in ('--run', '--admin-task', '--launch', '--app-update-desktop'):
            with self.subTest(option=option), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as result:
                main(['--start-in-tray', option])
            self.assertEqual(result.exception.code, 2)
