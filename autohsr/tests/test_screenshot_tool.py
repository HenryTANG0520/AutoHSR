from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

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
        kernel.CreateMutexW.assert_called_once_with(None, False, 'Local\\AutoHSR.DailyRunner')
        kernel.CloseHandle.assert_called_once_with(17)
        find.assert_called_once()
        self.assertEqual([call[0] for call in window.mock_calls if call[0] != 'emergency_pressed'],
                         ['focus', 'guard', 'capture'])
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
