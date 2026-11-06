"""Real temporary PNGs, a hidden modal and fake native foreground windows."""
from contextlib import ExitStack, nullcontext
from hashlib import sha256
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image, ImageDraw

from autohsr import desktop_workflow_template as desktop, screenshot_tool as screenshot
from autohsr.config import Settings
from autohsr.models import AutomationError, FocusLost, Stopped
from autohsr.workflow_vision import WorkflowVisionError, observe


def sample():
    picture = Image.new('RGB', (52, 36), 'navy')
    draw = ImageDraw.Draw(picture)
    draw.rectangle((12, 9, 25, 18), fill='gold')
    draw.rectangle((18, 14, 34, 24), fill='white')
    return picture


BOX = (7, 5, 40, 30)


class TemplateFileTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.base = self.root / 'workflow'
        self.base.mkdir()
        self.target = self.base / 'icons' / 'template.png'
        self.target.parent.mkdir()
        self.image = sample()

    def save(self, *, target=None, box=BOX, cancel=lambda: False):
        return screenshot.save_template(self.image, box, target or self.target, self.base, cancel)

    def test_template_source_rejects_unc_and_mapped_drive_before_any_path_access(self):
        if os.name != 'nt':
            self.skipTest('Windows network paths')
        with (patch('autohsr.workflow_bundle._local_drive', return_value=False) as drive,
              patch.object(Path, 'lstat') as metadata, patch.object(Path, 'resolve') as resolve,
              patch.object(Path, 'open') as open_file):
            for path in (r'\\synthetic.invalid\share\source.png', 'Z:/share/source.jpg'):
                with self.subTest(path=path), self.assertRaisesRegex(screenshot.ScreenshotError, '本地普通'):
                    screenshot.open_template_image(path, lambda: False)
        drive.assert_called_once_with('Z:\\')
        metadata.assert_not_called()
        resolve.assert_not_called()
        open_file.assert_not_called()

    def test_template_source_rejects_reparse_ancestor_or_offline_file_before_read(self):
        source = self.target.parent / 'source.png'
        self.image.save(source)
        lstat = Path.lstat
        for rejected, mode, attribute in ((source.parent, stat.S_IFDIR, stat.FILE_ATTRIBUTE_REPARSE_POINT),
                                          (source, stat.S_IFREG, stat.FILE_ATTRIBUTE_OFFLINE)):
            def observed(path):
                if path == rejected:
                    return SimpleNamespace(st_mode=mode, st_file_attributes=attribute)
                return lstat(path)

            with (self.subTest(attribute=attribute), patch.object(Path, 'lstat', observed),
                  patch.object(screenshot, 'hold_read_sources') as lock,
                  self.assertRaisesRegex(screenshot.ScreenshotError, '本地普通')):
                screenshot.open_template_image(source, lambda: False)
            lock.assert_not_called()

    def test_template_source_reads_under_a_stable_native_lock(self):
        if os.name != 'nt':
            self.skipTest('Windows native read sharing')
        source = self.base / 'original.PNG'
        replacement = self.base / 'replacement.png'
        self.image.save(source)
        Image.new('RGB', self.image.size, 'black').save(replacement)
        read_bytes = screenshot._read_image_bytes

        def attempt_replacement(path):
            self.assertEqual(path, source)
            with self.assertRaises(PermissionError):
                os.replace(replacement, path)
            return read_bytes(path)

        with patch.object(screenshot, '_read_image_bytes', side_effect=attempt_replacement) as read:
            image = screenshot.open_template_image(source, lambda: False)
        read.assert_called_once_with(source)
        self.assertEqual(image.tobytes(), self.image.tobytes())
        self.assertTrue(replacement.is_file())

    def test_published_receipt_has_relative_path_digest_and_exact_crop(self):
        self.image.info['icc_profile'] = b'private-fixture-data'
        result = self.save()
        self.assertEqual(result.path, self.target)
        self.assertEqual(result.relative_path, 'icons/template.png')
        self.assertEqual(result.sha256, sha256(self.target.read_bytes()).hexdigest())
        with Image.open(self.target) as actual:
            expected = self.image.crop(BOX)
            self.assertEqual(actual.size, expected.size)
            self.assertEqual(actual.tobytes(), expected.tobytes())
            self.assertNotIn('icc_profile', actual.info)
        self.assertEqual(self.image.info['icc_profile'], b'private-fixture-data')
        scene = self.base / 'scene.png'
        sample().save(scene)
        self.assertEqual(observe(scene, template=result.path, checkpoint=lambda: None),
                         {'status': 'success', 'image_found': True})

    def test_invalid_region_texture_location_or_collision_cannot_publish(self):
        with self.assertRaises(WorkflowVisionError):
            self.save(box=(0, 0, 7, 8))
        with self.assertRaises(WorkflowVisionError):
            self.save(box=(0, 0, 9, 8))
        with self.assertRaisesRegex(screenshot.ScreenshotError, '流程目录'):
            self.save(target=self.root / 'outside.png')
        self.assertFalse(self.target.exists())
        self.target.write_bytes(b'original')
        with self.assertRaisesRegex(screenshot.ScreenshotError, '已经存在'):
            self.save()
        self.assertEqual(self.target.read_bytes(), b'original')

    def test_publish_race_does_not_replace_foreign_destination(self):
        rename = os.rename

        def race(source, target):
            if Path(target) == self.target:
                self.target.write_bytes(b'competitor')
            return rename(source, target)

        with patch('autohsr.warp_service.os.rename', side_effect=race), self.assertRaises(screenshot.ScreenshotError):
            self.save()
        self.assertEqual(self.target.read_bytes(), b'competitor')
        self.assertEqual(tuple(self.target.parent.iterdir()), (self.target,))

    def test_stop_and_changed_publish_readback_return_no_binding(self):
        with self.assertRaises(Stopped):
            self.save(cancel=lambda: True)
        self.assertFalse(self.target.exists())
        publish = screenshot._save_png

        def changed(*args):
            digest = publish(*args)
            self.target.write_bytes(b'changed-after-publication')
            return digest

        with patch.object(screenshot, '_save_png', side_effect=changed), self.assertRaisesRegex(
                screenshot.ScreenshotError, '已发布.*待核对'):
            self.save()
        self.assertEqual(self.target.read_bytes(), b'changed-after-publication')

    def test_stop_during_last_destination_check_prevents_publication(self):
        from autohsr import workflow_bundle

        selected = workflow_bundle._path
        stop, checks = Event(), 0

        def late(path, **options):
            nonlocal checks
            result = selected(path, **options)
            if options.get('new'):
                checks += 1
                if checks == 4:  # Last check after the temporary PNG was hashed.
                    stop.set()
            return result

        with patch.object(workflow_bundle, '_path', side_effect=late), self.assertRaises(Stopped):
            self.save(cancel=stop.is_set)
        self.assertEqual(checks, 4)
        self.assertEqual(tuple(self.target.parent.iterdir()), ())


class ForegroundTemplateTests(TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.geometry = SimpleNamespace(width=4, height=3)
        self.window = Mock()
        self.window.guard.return_value = self.geometry
        self.window.current_window_key.return_value = 'same-window'
        self.window.emergency_pressed.return_value = False
        self.window.capture.return_value = np.full((3, 4, 3), (20, 60, 100), dtype=np.uint8), self.geometry
        self.kernel = Mock()
        self.kernel.CreateMutexW.return_value = 17
        self.sequence = stack.enter_context(patch('autohsr.workflow_lease.workflow_lease', return_value=nullcontext()))
        stack.enter_context(patch('autohsr.workflow_lease._kernel', return_value=self.kernel))
        stack.enter_context(patch('autohsr.windows.find_game', return_value=self.window))
        stack.enter_context(patch.object(screenshot.C, 'get_last_error', return_value=0))
        self.sleep = stack.enter_context(patch.object(screenshot.time, 'sleep'))
        self.addCleanup(self.window.focus.assert_not_called)
        self.addCleanup(self.window.send.assert_not_called)
        self.addCleanup(self.window.click.assert_not_called)

    def capture(self):
        return screenshot.capture_game(Settings(), lambda: False, foreground_only=True)

    def test_waits_for_user_foreground_then_checks_same_window_and_geometry(self):
        self.window.guard.side_effect = [FocusLost('assistant front'), self.geometry, self.geometry, self.geometry]
        image = self.capture()
        self.assertEqual(image.getpixel((0, 0)), (100, 60, 20))
        self.assertEqual(self.window.current_window_key.call_count, 2)
        self.window.capture.assert_called_once()
        self.sequence.assert_called_once()
        self.sleep.assert_called_once()
        self.kernel.CloseHandle.assert_called_once_with(17)

    def test_timeout_or_f10_before_foreground_prevents_capture(self):
        self.window.guard.side_effect = FocusLost('not front')
        with patch.object(screenshot, 'FOREGROUND_WAIT', 0), self.assertRaisesRegex(AutomationError, '超时'):
            self.capture()
        self.window.capture.assert_not_called()
        self.window.emergency_pressed.side_effect = [False, False, True]
        with self.assertRaises(Stopped):
            self.capture()
        self.window.capture.assert_not_called()
        self.assertEqual(self.kernel.CloseHandle.call_count, 2)

    def test_foreground_observed_after_deadline_cannot_capture(self):
        self.window.guard.side_effect = [FocusLost('assistant front'), self.geometry]
        with patch.object(screenshot.time, 'monotonic', side_effect=(0., 7.9, 8.1)), self.assertRaisesRegex(
                AutomationError, '超时'):
            self.capture()
        self.window.capture.assert_not_called()

    def test_changed_identity_or_late_f10_cannot_return_a_snapshot(self):
        self.window.current_window_key.side_effect = ['original', 'new']
        with self.assertRaisesRegex(AutomationError, '来源已变化'):
            self.capture()
        self.window.current_window_key.side_effect = None
        self.window.emergency_pressed.side_effect = [False, False, False, True]
        with self.assertRaises(Stopped):
            self.capture()
        self.assertEqual(self.window.capture.call_count, 2)
        self.assertEqual(self.kernel.CloseHandle.call_count, 2)


class TemplateDialogTests(TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.base = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.target = self.base / 'template.png'
        self.source = self.base / 'original.jpg'
        sample().save(self.source)
        self.pending = None
        self.ui = SimpleNamespace(ui_scale=1, busy=False, closing=False, stop_requested=Event(),
                                  _read_settings=Mock(return_value=Settings()), _submit_tool_job=self.submit)
        self.ui._stop = Mock(side_effect=self.ui.stop_requested.set)
        self.dialog = desktop.WorkflowTemplateDialog(self.ui, self.root, base_dir=self.base)
        self.open_dialog = self.enterContext(patch.object(desktop.filedialog, 'askopenfilename',
                                                        return_value=str(self.source)))
        self.save_dialog = self.enterContext(patch.object(desktop.filedialog, 'asksaveasfilename',
                                                        return_value=str(self.target)))

    def destroy_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def submit(self, _title, work, done, failed):
        self.assertIsNone(self.pending)
        self.ui.busy = True
        self.ui.stop_requested.clear()
        self.pending = work, done, failed
        return True

    def finish(self, *, late_stop=False):
        work, done, failed = self.pending
        self.pending = None
        try:
            value = work(self.ui.stop_requested)
        except Exception as error:
            self.ui.busy = False
            failed(error)
        else:
            self.ui.busy = False
            if late_stop:
                self.ui.stop_requested.set()
            done(value)

    def choose_local(self):
        self.dialog.open_image()
        self.finish()
        self.dialog._select(BOX)

    def test_local_jpeg_to_verified_png_only_when_selected_and_explicit(self):
        original = self.source.read_bytes()
        self.assertTrue(self.dialog.save_button.instate(('disabled',)))
        self.choose_local()
        self.assertTrue(self.dialog.save_button.instate(('!disabled',)))
        self.save_dialog.return_value = ''
        self.dialog.save()
        self.assertIsNone(self.pending)
        self.save_dialog.return_value = str(self.target)
        self.dialog.save_button.invoke()
        self.assertTrue(self.dialog.local_button.instate(('disabled',)))
        self.assertTrue(self.dialog.save_button.instate(('disabled',)))
        self.finish()
        self.assertFalse(self.dialog.winfo_exists())
        self.assertEqual(self.dialog.result.relative_path, 'template.png')
        self.assertEqual(self.source.read_bytes(), original)
        with Image.open(self.target) as result, Image.open(self.source) as source:
            self.assertEqual(result.tobytes(), source.convert('RGB').crop(BOX).tobytes())

    def test_cancel_and_late_stop_keep_result_unbound(self):
        self.choose_local()
        self.dialog.save()
        self.dialog.cancel()
        self.ui._stop.assert_called_once()
        self.finish()
        self.assertIn('已停止', self.dialog.message)
        self.assertFalse(self.target.exists())
        self.assertIsNone(self.dialog.result)
        self.dialog.save()
        self.finish(late_stop=True)
        self.assertTrue(self.target.is_file())
        self.assertIsNone(self.dialog.result)
        self.assertIn('已停止绑定', self.dialog.message)
        self.dialog.cancel()
        self.assertFalse(self.dialog.winfo_exists())

    def test_game_button_requests_only_already_foreground_capture(self):
        with patch.object(screenshot, 'capture_game', return_value=sample()) as capture:
            self.dialog.game_button.invoke()
            self.assertIn('手动切回游戏', self.dialog.message)
            self.finish()
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs, {'foreground_only': True})
        self.assertEqual(self.dialog.source, '游戏截图')
        self.assertIsNone(self.dialog.box)

    def test_nested_modal_restores_owner_grab_and_keeps_external_focus(self):
        owner, focus, dialog = Mock(), Mock(), Mock()
        owner.grab_current.side_effect = [owner, None]
        owner.grab_status.return_value = 'local'
        owner.focus_get.side_effect = [focus, None]
        dialog.result = None
        with patch.object(desktop, 'WorkflowTemplateDialog', return_value=dialog):
            self.assertIsNone(desktop.ask_workflow_template(self.ui, owner, base_dir=self.base))
        owner.grab_set.assert_called_once()
        owner.wait_window.assert_called_once_with(dialog)
        focus.focus_set.assert_not_called()

    def test_closed_modal_does_not_receive_late_worker_result(self):
        self.choose_local()
        self.dialog.save()
        work, done, _failed = self.pending
        result = work(self.ui.stop_requested)
        self.ui.closing = True
        self.dialog.destroy()
        done(result)
        self.assertTrue(self.target.is_file())
        self.assertIsNone(self.dialog.result)

    def test_action_row_fits_the_hidden_dialog_at_minimum_width(self):
        desktop.theme.apply_theme(self.root, 1)
        self.root.update_idletasks()
        self.assertLess(self.dialog.local_button.master.winfo_reqwidth(), self.dialog.minsize()[0])
