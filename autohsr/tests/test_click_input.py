"""Replay native click counts with fake Win32 calls."""
import ctypes as C
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import windows
from autohsr.models import AutomationError, FocusLost, Stopped


_CLICK = (0xC001, 0x0002, 0x0004)
_REJECTED = '模拟输入被 Windows 拒绝；请以管理员身份启动 AutoHSR。'


class NativeClickTests(unittest.TestCase):
    def setUp(self):
        self.geometry = windows.Geometry(0, 0, 1920, 1080)
        self.window = windows.GameWindow.__new__(windows.GameWindow)
        self.window.guard = Mock(return_value=self.geometry)
        self.native = SimpleNamespace(
            GetAsyncKeyState=Mock(return_value=0),
            GetSystemMetrics={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__,
            SendInput=Mock(),
        )
        self.enterContext(patch.object(windows, 'user32', self.native))

    def returns(self, accepted, release=1):
        batches = []

        def native_send(count, items, size):
            self.assertEqual(size, C.sizeof(windows.INPUT))
            events = C.cast(items, C.POINTER(windows.INPUT))
            batches.append(tuple(events[i].mi.dwFlags for i in range(count)))
            if len(batches) == 1:
                self.window.guard.side_effect = FocusLost('synthetic lost focus after native call')
                self.native.GetAsyncKeyState.return_value = 1
                return accepted
            if isinstance(release, Exception):
                raise release
            return release

        self.native.SendInput.side_effect = native_send
        return batches

    def test_native_counts_release_only_when_move_and_down_were_inserted(self):
        for accepted in range(4):
            with self.subTest(accepted=accepted):
                self.window.guard.side_effect = None
                self.native.GetAsyncKeyState.return_value = 0
                batches = self.returns(accepted)
                before_submit = Mock()
                if accepted == 3:
                    self.assertIsNone(self.window.click(.5, .5, self.geometry, before_submit=before_submit))
                else:
                    with self.assertRaises(AutomationError) as raised:
                        self.window.click(.5, .5, self.geometry, before_submit=before_submit)
                    self.assertEqual(str(raised.exception), _REJECTED)
                self.assertEqual(batches, [_CLICK, (0x0004,)] if accepted == 2 else [_CLICK])
                before_submit.assert_called_once_with()

    def test_failed_release_preserves_the_original_error_and_does_not_retry(self):
        for release in (0, OSError('synthetic cleanup failure')):
            with self.subTest(release=release):
                self.window.guard.side_effect = None
                self.native.GetAsyncKeyState.return_value = 0
                batches = self.returns(2, release)
                with self.assertRaises(AutomationError) as raised:
                    self.window.click(.5, .5, self.geometry)
                self.assertEqual(str(raised.exception), _REJECTED)
                self.assertEqual(batches, [_CLICK, (0x0004,)])

    def test_short_right_click_batch_does_not_synthesize_a_left_release(self):
        batches = self.returns(2)
        flags = (0xC001, 0x0008, 0x0010)
        events = [windows.INPUT(type=0, mi=windows.MOUSEINPUT(0, 0, 0, flag, 0, 0)) for flag in flags]
        with self.assertRaises(AutomationError):
            self.window.send(events, self.geometry)
        self.assertEqual(batches, [flags])

    def test_stop_at_submission_has_no_native_input(self):
        with self.assertRaises(Stopped):
            self.window.click(.5, .5, self.geometry, before_submit=Mock(side_effect=Stopped('stop')))
        self.native.SendInput.assert_not_called()


if __name__ == '__main__':
    unittest.main()
