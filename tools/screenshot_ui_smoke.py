"""Hidden Tk and local temporary screenshots for the tools shelf."""
from pathlib import Path
from queue import Queue
import sys
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autohsr import theme
from autohsr.config import Settings
from autohsr.daily_observe import SCREEN_OPERATION
from autohsr.desktop_jobs import NativeRunSlot
from autohsr.desktop_screenshot import _guide_feedback, _image_box, _stitch_feedback, build_screenshot_panel


class Host:
    def __init__(self, root):
        self.root, self.ui_scale = root, 1
        self.busy = self.closing = False
        self.stop_requested = Event()
        self.events = Queue()
        self._native_run = NativeRunSlot(self.events, self.stop_requested)
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

    def test_second_capture_discards_the_previous_export_selection(self):
        first = Image.new('RGB', (1440, 810), 'navy')
        second = Image.new('RGB', (1920, 1080), 'black')
        second.putpixel((123, 77), (218, 54, 12))
        with TemporaryDirectory() as temporary:
            first_path, second_path = (Path(temporary) / name for name in ('first.png', 'second.png'))
            with patch('autohsr.desktop_screenshot.screenshot_tool.capture_game', side_effect=(first, second)):
                self.panel.capture()
                self.host.complete()
                self.panel._select((11, 22, 51, 62))
                with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename', return_value=str(first_path)):
                    self.panel.save()
                self.host.complete()
                first_bytes = first_path.read_bytes()

                self.panel.capture()
                self.host.complete()
            self.assertIs(self.panel.model.image, second)
            self.assertIsNone(self.panel.model.box)
            with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename', return_value=str(second_path)) as dialog:
                self.panel.save()
                dialog.assert_not_called()
                self.panel._select((123, 77, 153, 117))
                self.panel.save()
            self.host.complete()
            self.assertEqual(first_path.read_bytes(), first_bytes)
            with Image.open(second_path) as exported:
                self.assertEqual(exported.size, (30, 40))
                self.assertEqual(exported.getpixel((0, 0)), (218, 54, 12))

    def test_replaced_panel_or_inactive_tool_cannot_begin_capture(self):
        self.host.screenshot_panel = build_screenshot_panel(self.host.root, self.host)
        self.panel.capture()
        self.assertIsNone(self.host.pending)
        self.host._selected_tool = 'warp'
        self.host.screenshot_panel.capture()
        self.assertIsNone(self.host.pending)

    def test_reward_guide_uses_explicit_output_and_keeps_anonymous_receipt_after_late_stop(self):
        before = Image.new('RGB', (90, 40))
        self.panel._set_image(before, '本地图片')
        self.panel.select_all()
        self.assertEqual(self.panel.primary_action()[0], '截取游戏窗口')
        self.panel.mode.set('奖励指南单屏导出')
        self.panel._mode_selected()
        self.assertEqual(self.panel.primary_action()[0], '导出奖励指南单屏')
        self.assertFalse(self.panel.primary_action()[2])
        self.panel.capture()
        self.assertIsNone(self.host.pending)
        with TemporaryDirectory() as temporary, patch('autohsr.app.Runner') as runner, patch(
                'autohsr.reward_guide_notify.send_reward_guide', side_effect=AssertionError('no notification')) as send:
            target = Path(temporary) / 'private-name.png'
            with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename') as picker:
                picker.return_value = ''
                self.assertFalse(self.panel.pick_guide_destination())
                for invalid in ('relative.png', r'\\server\share\capture.png', str(target.with_suffix('.jpeg'))):
                    picker.return_value = invalid
                    self.assertFalse(self.panel.pick_guide_destination())
                    self.assertFalse(self.panel.primary_action()[2])
                picker.return_value = str(target)
                self.assertTrue(self.panel.pick_guide_destination())
                self.assertIs(picker.call_args.kwargs['confirmoverwrite'], False)
            self.assertIsNone(self.host.pending)
            self.assertFalse(target.exists())
            runner.assert_not_called()
            self.host._read_settings.assert_not_called()
            self.assertTrue(self.panel.primary_action()[1]())
            self.assertTrue(self.host.pending[3])
            self.assertTrue(self.panel.guide_picker.instate(('disabled',)))
            self.assertTrue(self.panel.mode.instate(('disabled',)))
            self.assertFalse(self.panel.export_guide())

            def make(_settings, emit, **kwargs):
                self.assertEqual(kwargs['operation'], SCREEN_OPERATION)
                self.assertTrue(kwargs['observation_wait_for_foreground'])
                capture = kwargs['reward_guide_capture']
                self.assertEqual(capture._target[0], target)
                emit(dict(type='paused', paused=True))
                emit(dict(type='finished', private='private-name'))
                capture.receipt = dict(status='ok', input_sent=False, visible_section='ongoing', width=90, height=40,
                                       path='private-name')
                return SimpleNamespace(run=lambda: SimpleNamespace(status='stopped', report_saved=True))

            runner.side_effect = make
            current = self.host.screenshot_panel = build_screenshot_panel(self.host.root, self.host)
            self.host.complete(late_stop=True)
            runner.assert_called_once()
            self.assertEqual(self.host.events.get_nowait(), dict(type='paused', paused=True))
            self.assertEqual(self.host.events.get_nowait()['type'], 'runner_ready')
            self.assertTrue(self.host.events.empty())
            self.assertEqual(current.guide_feedback.cget('text'), '已导出「进行中」内容 · 90 × 40 · 游戏输入 0 次。')
            self.assertIsNone(current.model.guide_destination)
            self.assertFalse(current.primary_action()[2])
            send.assert_not_called()
        current.mode.set('截图与识别')
        current._mode_selected()
        self.assertIs(current.model.image, before)
        self.assertEqual(current.model.box, (0, 0, 90, 40))

    def test_reward_guide_rejects_existing_output_before_job_or_settings_read(self):
        self.panel.mode.set('奖励指南单屏导出')
        self.panel._mode_selected()
        with TemporaryDirectory() as temporary, patch('autohsr.app.Runner') as runner:
            target = Path(temporary) / 'original.png'
            target.write_bytes(b'original')
            with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename', return_value=str(target)):
                self.assertTrue(self.panel.pick_guide_destination())
            self.assertFalse(self.panel.export_guide())
            self.assertIn('已有文件保留', self.panel.guide_feedback.cget('text'))
            self.assertEqual(target.read_bytes(), b'original')
            self.assertIsNone(self.host.pending)
            self.assertFalse(self.panel.primary_action()[2])
            self.host._read_settings.assert_not_called()
            runner.assert_not_called()

    def test_reward_guide_only_renders_verified_zero_input_receipts(self):
        ready = dict(status='ok', input_sent=False, visible_section='ongoing', width=10, height=20)
        for receipt in (dict(ready, input_sent=True), dict(ready, width=True), dict(ready, visible_section='private')):
            self.assertEqual(_guide_feedback(receipt), '奖励指南单屏导出结果待核对。')
        self.assertIn('已停止', _guide_feedback(dict(status='stopped', input_sent=False)))
        self.assertIn('报告未发布', _guide_feedback(dict(status='report_unverified', input_sent=False)))

    def test_local_stitch_previews_explicit_order_and_runs_once_without_game_or_send(self):
        image = Image.new('RGB', (90, 40))
        self.panel._set_image(image, '本地图片')
        self.panel.select_all()
        with (TemporaryDirectory() as temporary, patch('autohsr.app.Runner') as runner,
              patch('autohsr.reward_guide_notify.send_reward_guide') as send,
              patch('autohsr.reward_guide_export.export_reward_guide') as export):
            root = Path(temporary)
            first, middle, last = (root / name for name in ('first.png', 'middle.PNG', 'last.png'))
            destination = root / 'private-output.png'
            self.panel.mode.set('奖励指南单屏导出')
            self.panel._mode_selected()
            with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename',
                       return_value=str(root / 'single.png')):
                self.assertTrue(self.panel.pick_guide_destination())
            self.panel.mode.set('本地奖励指南拼接')
            self.panel._mode_selected()
            self.assertFalse(self.panel.primary_action()[2])
            with patch('autohsr.desktop_screenshot.filedialog.askopenfilenames') as pick:
                pick.return_value = (str(last), str(first))
                self.assertTrue(self.panel.add_stitch_sources())
                self.assertEqual(self.panel.stitch_list.get(0, 'end'), ('1. last.png', '2. first.png'))
                self.panel.stitch_list.selection_clear(0, 'end')
                self.panel.stitch_list.selection_set(1)
                self.panel._stitch_selected()
                self.assertTrue(self.panel.move_stitch_source(-1))
                self.assertFalse(self.panel.move_stitch_source(-1))
                self.assertTrue(self.panel.move_stitch_source(1))
                self.assertTrue(self.panel.move_stitch_source(-1))
                for rejected in ((str(middle), str(root / 'extra.png')), (str(last),),
                                 (r'\\server\share\calendar.png',), (str(middle.with_suffix('.jpg')),)):
                    pick.return_value = rejected
                    self.assertFalse(self.panel.add_stitch_sources())
                    self.assertEqual(self.panel.model.stitch_sources, (first, last))
                pick.return_value = (str(middle),)
                self.assertTrue(self.panel.add_stitch_sources())
                self.assertTrue(self.panel.stitch_buttons[0].instate(('disabled',)))
                self.assertTrue(self.panel.move_stitch_source(-1))
                self.assertTrue(self.panel.remove_stitch_source())
                self.assertTrue(self.panel.add_stitch_sources())
                self.assertTrue(self.panel.move_stitch_source(-1))
            self.assertEqual(self.panel.stitch_list.get(0, 'end'), ('1. first.png', '2. middle.PNG', '3. last.png'))
            self.assertEqual(self.panel.stitch_source_path.cget('text'), str(middle))
            with patch('autohsr.desktop_screenshot.filedialog.asksaveasfilename') as pick:
                pick.return_value = ''
                self.assertFalse(self.panel.pick_stitch_destination())
                self.assertFalse(self.panel.primary_action()[2])
                pick.return_value = str(destination)
                self.assertTrue(self.panel.pick_stitch_destination())
                self.assertIs(pick.call_args.kwargs['confirmoverwrite'], False)
            self.assertIsNone(self.host.pending)
            self.assertFalse(destination.exists())
            export.assert_not_called()
            label, action, ready = self.panel.primary_action()
            self.assertEqual((label, ready), ('拼接并导出奖励指南', True))
            self.assertTrue(action())
            self.assertFalse(self.host.pending[3])
            self.assertTrue(all(button.instate(('disabled',)) for button in self.panel.stitch_buttons))
            self.assertFalse(self.panel.move_stitch_source(1))
            self.assertFalse(self.panel.export_stitch())
            export.return_value = dict(status='ok', overlap_rows=[115, 80], width=192, height=333, private='hidden')
            current = self.host.screenshot_panel = build_screenshot_panel(self.host.root, self.host)
            self.host.complete(late_stop=True)
            export.assert_called_once()
            self.assertEqual(export.call_args.args, ((first, middle, last), destination))
            self.assertEqual(current.stitch_feedback.cget('text'), '已导出拼图 · 3 张裁片 · 192 × 333。接缝重叠行数 115／80。')
            self.assertFalse(current.primary_action()[2])
            self.assertEqual(current.model.stitch_sources, (first, middle, last))
            self.assertEqual(current.model.guide_destination, root / 'single.png')
            self.assertIs(current.model.image, image)
            self.assertEqual(current.model.box, (0, 0, 90, 40))
            runner.assert_not_called()
            send.assert_not_called()
            self.host._read_settings.assert_not_called()

    def test_local_stitch_passes_shared_stop_and_exclusively_writes_new_local_png(self):
        self.panel.mode.set('本地奖励指南拼接')
        self.panel._mode_selected()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target, occupied = (root / name for name in ('crop.png', 'new.png', 'occupied.png'))
            Image.new('RGB', (96, 64), 'navy').save(source)
            source_bytes = source.read_bytes()
            occupied.write_bytes(b'original')
            with patch('autohsr.desktop_screenshot.filedialog.askopenfilenames', return_value=(str(source),)):
                self.assertTrue(self.panel.add_stitch_sources())
            for output, stopped, text in ((occupied, False, '已有文件保留'), (target, True, '已停止'),
                                          (target, False, '已导出拼图 · 1 张裁片 · 96 × 64')):
                with self.subTest(stopped=stopped, text=text), patch(
                        'autohsr.desktop_screenshot.filedialog.asksaveasfilename', return_value=str(output)):
                    self.assertTrue(self.panel.pick_stitch_destination())
                    self.assertFalse(target.exists())
                    self.assertTrue(self.panel.primary_action()[1]())
                    if stopped:
                        self.host.stop_requested.set()
                    self.host.complete()
                    self.assertIn(text, self.panel.stitch_feedback.cget('text'))
            self.assertEqual(occupied.read_bytes(), b'original')
            self.assertEqual(source.read_bytes(), source_bytes)
            with Image.open(target) as output:
                self.assertEqual((output.format, output.size), ('PNG', (96, 64)))

    def test_stitch_feedback_rejects_unverified_dimensions_or_seams(self):
        for receipt in (dict(status='ok', width=True, height=200, overlap_rows=[50]),
                        dict(status='ok', width=96, height=200, overlap_rows=[]),
                        dict(status='ok', width=96, height=200, overlap_rows=[False])):
            self.assertEqual(_stitch_feedback(receipt, 2), '奖励指南拼接结果待核对。')
        self.assertIn('顺序相反', _stitch_feedback(dict(status='wrong_direction'), 2))


if __name__ == '__main__':
    unittest.main()
