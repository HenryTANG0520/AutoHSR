"""Hidden Tk and local temporary screenshots for the tools shelf."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autohsr import theme
from autohsr.config import Settings
from autohsr.desktop_screenshot import _image_box, build_screenshot_panel


class Host:
    def __init__(self, root):
        self.root, self.ui_scale = root, 1
        self.busy = self.closing = False
        self.stop_requested = Event()
        self._selected_tool = 'screenshot'
        self._in_tools = lambda: True
        self.pending = None
        self._tool_action_changed = Mock()
        self._read_settings = Mock(return_value=Settings())

    def _start_desktop_job(self, _title, work, done, failed, *, game=False):
        if self.busy:
            return False
        self.pending = work, done, failed, game
        self.busy = True
        self.stop_requested.clear()
        return True

    _submit_tool_job = _start_desktop_job

    def complete(self, *, late_stop=False):
        work, done, failed, _game = self.pending
        self.busy, self.pending = False, None
        try:
            value = work(self.stop_requested)
        except Exception as error:
            failed(error)
        else:
            if late_stop:
                self.stop_requested.set()
            done(value)


class ScreenshotSmoke(unittest.TestCase):
    def setUp(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        theme.apply_theme(root, 1)
        self.host = Host(root)
        self.panel = self.host.screenshot_panel = build_screenshot_panel(root, self.host)

    def test_canvas_bounds_use_original_pixels_and_keep_reverse_drags(self):
        self.assertEqual(_image_box((38, 77), (15, 32), (20, 30, 50, 50), (200, 100)), (0, 4, 72, 94))
        self.assertIsNone(_image_box((38, 77), (38, 77), (20, 30, 50, 50), (200, 100)))

    def test_local_read_export_and_cancel_keep_the_original(self):
        with TemporaryDirectory() as temporary:
            source, target = (Path(temporary) / name for name in ('image.png', 'crop.png'))
            Image.new('RGB', (300, 150), 'navy').save(source)
            original = source.read_bytes()
            with patch('autohsr.desktop_screenshot.filedialog.askopenfilename', return_value=str(source)):
                self.panel.open_image()
            self.assertFalse(self.host.pending[3])
            self.host.complete()
            self.panel._select((21, 25, 61, 45))
            with patch('autohsr.desktop_screenshot.screenshot_tool.read_selection', return_value=(('虚构识别', .99),)):
                self.panel.read()
                self.host.complete()
            self.assertIn('虚构识别', self.panel.result.get('1.0', 'end-1c'))
            with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename', return_value=''):
                self.panel.save()
            self.assertIsNone(self.host.pending)
            with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename', return_value=str(target)):
                self.panel.save()
            self.host.complete(late_stop=True)
            self.assertIn('已导出', self.panel.feedback.cget('text'))
            self.assertEqual(source.read_bytes(), original)
            with Image.open(target) as cropped:
                self.assertEqual(cropped.size, (40, 20))

    def test_game_capture_uses_tool_job_and_keeps_snapshot_after_late_stop(self):
        before, captured = Image.new('RGB', (90, 40)), Image.new('RGB', (200, 140))
        self.panel._set_image(before, '本地图片')
        with patch('autohsr.desktop_screenshot.screenshot_tool.capture_game', return_value=captured) as capture:
            self.panel.capture()
            self.assertFalse(self.host.pending[3])
            self.host.complete(late_stop=True)
        capture.assert_called_once()
        self.assertIs(self.panel.model.image, before)
        self.assertIn('已停止', self.panel.feedback.cget('text'))

    def test_replaced_panel_or_inactive_tool_cannot_begin_capture(self):
        self.host.screenshot_panel = build_screenshot_panel(self.host.root, self.host)
        self.panel.capture()
        self.assertIsNone(self.host.pending)
        self.host._selected_tool = 'warp'
        self.host.screenshot_panel.capture()
        self.assertIsNone(self.host.pending)


if __name__ == '__main__':
    unittest.main()
