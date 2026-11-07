import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch

from autohsr.gui import AutoHSRWindow


class ReportHistoryTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix='autohsr-report-history-')
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        root_patch = patch('autohsr.gui.ROOT', self.folder)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f'Tk 不可用：{error}')
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def report(self, directory, contents, modified):
        path = self.folder / 'runs' / directory / 'report.json'
        path.parent.mkdir(parents=True)
        path.write_text(contents, encoding='utf-8')
        timestamp = 1_700_000_000 + modified
        os.utime(path, (timestamp, timestamp))
        return path

    def window(self):
        ui = AutoHSRWindow(self.root, self.folder / 'config.json')
        self.root.update_idletasks()
        return ui

    def test_startup_skips_invalid_reports_and_uses_newest_valid_legacy_report(self):
        self.report('zzz-oldest', '{"status":"success"}', 100)
        legacy = {'status': 'failed', 'run_dir': 'original-location'}
        valid = self.report('aaa-legacy', json.dumps(legacy), 200)
        screenshot = valid.parent / '123456_000001_failure.png'
        screenshot.touch()
        invalid_reports = {}
        for index, raw in enumerate((
            '{"status":', '[]', '{"source":17}', '{"operation":[]}', '{"game_day":17}',
            '{"reset_day":[]}', '{"report_saved":"false"}',
            '{"results":' + '[' * 1200 + ']' * 1200 + '}',
        ), start=1):
            path = self.report(f'invalid-{index}', raw, 200 + index)
            invalid_reports[path] = path.read_bytes()

        ui = self.window()

        self.assertEqual(ui.last_report_file, valid)
        self.assertEqual(ui.last_run_dir, valid.parent)
        self.assertEqual(ui.last_screenshot, screenshot)
        self.assertEqual(json.loads(ui.report_text.get('1.0', 'end')), legacy)
        self.assertIn('已跳过 8 份无效报告', ui.history_context.get())
        self.assertIn('文件时间', ui.history_context.get())
        self.assertIn('游戏日未核实', ui.history_context.get())
        self.assertTrue(ui.report_button.instate(('!disabled',)))
        self.assertEqual({path: path.read_bytes() for path in invalid_reports}, invalid_reports)

    def test_only_invalid_history_is_distinct_from_no_history(self):
        ui = self.window()
        self.assertEqual(ui.history_context.get(), '暂无历史运行记录')
        self.report('invalid', '[]', 100)

        ui._discover_report()

        self.assertIn('已跳过 1 份无效报告', ui.history_context.get())
        self.assertIn('暂无可显示的历史记录', ui.history_context.get())
        self.assertIsNone(ui.last_report_file)
        self.assertTrue(ui.report_button.instate(('disabled',)))

    def test_unreadable_report_does_not_hide_older_valid_report(self):
        valid = self.report('legacy', '{"status":"success"}', 100)
        locked = self.report('locked', '{"status":"success"}', 200)
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if path == locked:
                raise PermissionError('synthetic file lock')
            return read_text(path, *args, **kwargs)

        with patch.object(type(locked), 'read_text', read):
            ui = self.window()

        self.assertEqual(ui.last_report_file, valid)
        self.assertIn('已跳过 1 份无效报告', ui.history_context.get())
        self.assertEqual(locked.read_text(encoding='utf-8'), '{"status":"success"}')

    def test_unsaved_run_does_not_open_same_path_report_or_show_old_detection_as_run_evidence(self):
        saved = self.report('saved', '{"status":"success"}', 100)
        ui = self.window()
        self.assertEqual(ui.last_report_file, saved)
        detection = self.folder / 'detection.png'
        detection.touch()
        ui.inspection_screenshot = detection
        ui.output_tabs.select(1)
        self.assertEqual(ui._record_screenshot(), detection)

        ui._record_run(dict(operation='daily', status='failed', report_saved=False, run_dir=str(saved.parent)))
        ui.output_tabs.select(2)
        ui._refresh_record_controls()

        self.assertIn('最终报告未保存', ui.history_context.get())
        self.assertIsNone(ui.last_report_file)
        self.assertIsNone(ui._record_screenshot())
        self.assertEqual(ui.inspection_screenshot, detection)
        self.assertTrue(ui.report_button.instate(('disabled',)))
        self.assertTrue(ui.screenshot_button.instate(('disabled',)))
        self.assertEqual(saved.read_text(encoding='utf-8'), '{"status":"success"}')

    def test_currency_observation_screenshot_survives_history_reload(self):
        ui = self.window()
        directory = self.folder / 'runs' / 'observation'
        screenshot = directory / '123456_000001_currency_wars_observation.png'
        report = dict(operation='currency_wars', status='success', report_saved=True, run_dir=str(directory),
                      currency_wars=dict(mode='read_only_calibration', screenshot=str(screenshot)))
        saved = self.report('observation', json.dumps(report), 100)
        screenshot.touch()
        ui.output_tabs.select(ui.report_text.frame.master)
        ui.active_operation = 'currency_wars'
        for load in (lambda: ui._finish(report), ui._discover_report):
            with self.subTest(load=load):
                load()
                ui._refresh_record_controls()
                self.assertEqual(ui.last_report_file, saved)
                self.assertEqual(ui._record_screenshot(), screenshot)
                self.assertTrue(ui.screenshot_button.instate(('!disabled',)))
                with patch('autohsr.gui.os.startfile') as open_file:
                    ui._open_record_screenshot()
                    open_file.assert_called_once_with(str(screenshot))

    def test_currency_history_does_not_bind_other_run_or_detection_images(self):
        ui = self.window()
        directory = self.folder / 'runs' / 'observation'
        report = dict(operation='currency_wars', status='success', report_saved=True, run_dir=str(directory),
                      currency_wars=dict(mode='read_only_calibration'))
        saved = self.report('observation', json.dumps(report), 100)
        other = self.report('older', '{"status":"success"}', 50).with_name('other.png')
        detection = self.folder / 'detection.png'
        non_png = directory / 'observation.txt'
        observation = directory / '123456_000001_currency_wars_observation.png'
        for path in (other, detection, non_png, observation):
            path.touch()
        ui.inspection_screenshot = detection
        ui.output_tabs.select(ui.report_text.frame.master)
        for image, claimed_run in (
            (other, directory), (detection, directory), (non_png, directory), ('relative.png', directory),
            (directory / 'missing.png', directory), (observation, other.parent),
        ):
            with self.subTest(image=image, claimed_run=claimed_run):
                report['currency_wars']['screenshot'] = str(image)
                report['run_dir'] = str(claimed_run)
                saved.write_text(json.dumps(report), encoding='utf-8')
                ui._discover_report()
                ui._refresh_record_controls()
                self.assertEqual(ui.last_report_file, saved)
                self.assertIsNone(ui._record_screenshot())
                self.assertEqual(ui.inspection_screenshot, detection)
                self.assertTrue(ui.screenshot_button.instate(('disabled',)))
