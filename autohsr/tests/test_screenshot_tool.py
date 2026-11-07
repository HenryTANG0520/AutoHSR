from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from autohsr import windows, workflow_lease
from autohsr.config import Settings
from autohsr.models import AutomationError, Stopped
from autohsr.screenshot_tool import (ScreenshotError, capture_game, open_image, read_selection, save_selection,
                                    selection)


class ScreenshotToolTests(TestCase):
    def test_open_and_export_snapshot_preserves_alpha_and_never_overwrites(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, target = folder / 'source.png', folder / 'crop.png'
            original = Image.new('RGBA', (64, 40), (25, 50, 100, 73))
            original.putpixel((9, 12), (200, 10, 20, 40))
            original.save(source, icc_profile=b'synthetic source metadata')
            before = source.read_bytes()
            picture = open_image(source, lambda: False)
            self.assertEqual(picture.info['icc_profile'], b'synthetic source metadata')
            box = (9, 12, 34, 30)
            digest = save_selection(picture, box, target, lambda: False)
            self.assertEqual(digest, sha256(target.read_bytes()).hexdigest())
            with Image.open(target) as exported:
                self.assertEqual((exported.size, exported.mode), ((25, 18), 'RGBA'))
                self.assertEqual(exported.getpixel((0, 0)), (200, 10, 20, 40))
                self.assertNotIn('icc_profile', exported.info)
            with self.assertRaisesRegex(ScreenshotError, '已存在'):
                save_selection(picture, box, source, lambda: False)
            self.assertEqual(source.read_bytes(), before)
            with self.assertRaises(Stopped):
                save_selection(picture, box, folder / 'stopped.png', lambda: True)
            self.assertFalse((folder / 'stopped.png').exists())

    def test_selection_ocr_only_receives_the_current_crop(self):
        image = Image.new('RGBA', (64, 40), (100, 60, 20, 50))
        vision = Mock()
        vision.return_value.read.return_value.tokens = [SimpleNamespace(text='虚构', score=.98)]
        with patch('autohsr.vision.Vision', vision):
            result = read_selection(image, (9, 4, 41, 22), .72, lambda: False)
            self.assertEqual(result, (('虚构', .98),))
            vision.assert_called_once_with(.72)
            pixels = vision.return_value.read.call_args.args[0]
            self.assertEqual(pixels.shape, (18, 32, 3))
            self.assertEqual(tuple(pixels[0, 0]), (20, 60, 100))
            with self.assertRaises(ScreenshotError):
                read_selection(image, (1, 1, 7, 7), .72, lambda: False)
            self.assertEqual(vision.call_count, 1)
        for box in ((-1, 0, 4, 4), (4, 0, 4, 6), (0, 1, 65, 3), (True, 0, 3, 3)):
            with self.subTest(box=box), self.assertRaises(ScreenshotError):
                selection(image, box)

    def test_capture_owns_both_slots_and_never_calls_game_input(self):
        geometry = SimpleNamespace(width=4, height=3)
        window = Mock()
        window.emergency_pressed.return_value = False
        window.current_window_key.return_value = 'same-window'
        window.guard.return_value = geometry
        window.capture.return_value = np.full((3, 4, 3), (20, 60, 100), dtype=np.uint8), geometry
        kernel = Mock()
        kernel.CreateMutexW.return_value = 17
        with (patch('autohsr.workflow_lease.workflow_lease', return_value=nullcontext()) as sequence,
              patch('autohsr.workflow_lease._kernel', return_value=kernel),
              patch('autohsr.screenshot_tool.C.get_last_error', return_value=0),
              patch('autohsr.windows.find_game', return_value=window) as find):
            image = capture_game(Settings(), lambda: False)
        sequence.assert_called_once_with()
        kernel.CreateMutexW.assert_called_once_with(None, False, workflow_lease.NATIVE_NAME)
        kernel.CloseHandle.assert_called_once_with(17)
        find.assert_called_once()
        self.assertEqual([call[0] for call in window.mock_calls if call[0] != 'emergency_pressed'],
                         ['focus', 'guard', 'current_window_key', 'guard', 'capture', 'current_window_key', 'guard'])
        self.assertEqual(image.getpixel((0, 0)), (100, 60, 20))

    def test_existing_native_runner_blocks_before_game_lookup(self):
        kernel = Mock()
        kernel.CreateMutexW.return_value = 19
        with (patch('autohsr.workflow_lease.workflow_lease', return_value=nullcontext()),
              patch('autohsr.workflow_lease._kernel', return_value=kernel),
              patch('autohsr.screenshot_tool.C.get_last_error', return_value=183),
              patch('autohsr.windows.find_game') as find,
              self.assertRaisesRegex(AutomationError, '执行权')):
            capture_game(Settings(), lambda: False)
        find.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(19)

    def test_capture_rejects_reused_handle_at_the_same_physical_client_rect(self):
        hwnd = 41
        geometry = windows.Geometry(-2070, 116, 1440, 810)
        pid = 101
        reuse_handle = False
        window = windows.GameWindow.__new__(windows.GameWindow)
        window.hwnd = hwnd
        window.focus = Mock()

        def client_rect(handle, result):
            self.assertEqual(handle, hwnd)
            result._obj.right, result._obj.bottom = geometry.width, geometry.height
            return 1

        def client_origin(handle, result):
            self.assertEqual(handle, hwnd)
            result._obj.x, result._obj.y = geometry.left, geometry.top
            return 1

        def thread_and_pid(handle, result):
            self.assertEqual(handle, hwnd)
            result._obj.value = pid
            return 91

        def process_times(process, created, *_):
            created._obj.dwLowDateTime = process * 100
            return 1

        def grab(rect):
            nonlocal pid
            self.assertEqual(rect, dict(left=-2070, top=116, width=1440, height=810))
            if reuse_handle:
                pid = 202
            return np.full((810, 1440, 4), (20, 60, 100, 255), dtype=np.uint8)

        user = SimpleNamespace(IsWindow=lambda _: True, IsIconic=lambda _: False,
                               GetForegroundWindow=lambda: hwnd, GetAsyncKeyState=lambda _: 0,
                               GetClientRect=client_rect, ClientToScreen=client_origin,
                               GetWindowThreadProcessId=thread_and_pid,
                               GetSystemMetrics={76: -2560, 77: 0, 78: 4480, 79: 1440}.__getitem__)
        native = SimpleNamespace(OpenProcess=Mock(side_effect=lambda _rights, _inherit, current_pid: current_pid),
                                 GetProcessTimes=process_times, CloseHandle=Mock())
        slot = SimpleNamespace(CreateMutexW=Mock(return_value=27), CloseHandle=Mock())
        with (patch('autohsr.workflow_lease.workflow_lease', return_value=nullcontext()),
              patch('autohsr.workflow_lease._kernel', return_value=slot),
              patch('autohsr.screenshot_tool.C.get_last_error', return_value=0),
              patch.object(windows, 'find_game', return_value=window), patch.object(windows, 'user32', user),
              patch.object(windows, 'kernel32', native),
              patch('mss.mss', return_value=nullcontext(SimpleNamespace(grab=grab)))):
            image = capture_game(Settings(), lambda: False)
            self.assertEqual((image.size, image.getpixel((0, 0))), ((1440, 810), (100, 60, 20)))
            reuse_handle = True
            with self.assertRaisesRegex(AutomationError, '来源已变化'):
                capture_game(Settings(), lambda: False)
        self.assertEqual(window.focus.call_count, 2)
        self.assertEqual(pid, 202)
        self.assertEqual([call.args for call in slot.CloseHandle.call_args_list], [(27,), (27,)])

    def test_capture_does_not_return_pixels_if_the_client_rect_changes_after_grab(self):
        geometry = windows.Geometry(-1920, 75, 1440, 810)
        moved = windows.Geometry(-1910, 75, 1440, 810)
        window = Mock()
        window.emergency_pressed.return_value = False
        window.current_window_key.return_value = 'same-window'
        window.guard.side_effect = (geometry, geometry, moved)
        window.capture.return_value = np.full((810, 1440, 3), 100, dtype=np.uint8), geometry
        slot = SimpleNamespace(CreateMutexW=Mock(return_value=29), CloseHandle=Mock())
        with (patch('autohsr.workflow_lease.workflow_lease', return_value=nullcontext()),
              patch('autohsr.workflow_lease._kernel', return_value=slot),
              patch('autohsr.screenshot_tool.C.get_last_error', return_value=0),
              patch.object(windows, 'find_game', return_value=window)):
            with self.assertRaisesRegex(AutomationError, '来源已变化'):
                capture_game(Settings(), lambda: False)
        window.capture.assert_called_once()
        slot.CloseHandle.assert_called_once_with(29)

    def test_stop_during_geometry_check_prevents_capture_and_releases_slot(self):
        geometry = SimpleNamespace(width=4, height=3)
        stopped = False

        def geometry_read():
            nonlocal stopped
            stopped = True
            return geometry

        window = Mock()
        window.emergency_pressed.return_value = False
        window.guard.side_effect = geometry_read
        kernel = Mock()
        kernel.CreateMutexW.return_value = 23
        with (patch('autohsr.workflow_lease.workflow_lease', return_value=nullcontext()),
              patch('autohsr.workflow_lease._kernel', return_value=kernel),
              patch('autohsr.screenshot_tool.C.get_last_error', return_value=0),
              patch('autohsr.windows.find_game', return_value=window), self.assertRaises(Stopped)):
            capture_game(Settings(), lambda: stopped)
        window.capture.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(23)
