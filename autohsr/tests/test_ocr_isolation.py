"""Real spawned subprocesses with deterministic OCR workers; no desktop APIs."""
from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from autohsr.models import AutomationError, Stopped
from autohsr.ocr_isolation import IsolatedVision, _tokens


def write_result(output_path, result):
    Path(output_path).write_text(json.dumps(result), encoding="utf-8")


def worker_ok(input_path, output_path, confidence):
    image = np.load(input_path, allow_pickle=False)
    assert image.shape == (20, 30, 3)
    write_result(output_path, dict(status="ok", tokens=[dict(text="货币战争", score=.99, box=[.1, .1, .8, .3])]))


def worker_hangs(*_):
    time.sleep(10)


def worker_crashes(*_):
    os._exit(23)


def worker_errors(input_path, output_path, confidence):
    write_result(output_path, dict(status="error", error="OCR runtime unavailable"))


def worker_invalid(input_path, output_path, confidence):
    Path(output_path).write_text("{broken", encoding="utf-8")


class IsolatedVisionTests(unittest.TestCase):
    def setUp(self):
        self.before_children = {child.pid for child in multiprocessing.active_children()}
        self.image = np.zeros((20, 30, 3), dtype=np.uint8)

    def tearDown(self):
        remaining = [child for child in multiprocessing.active_children() if child.pid not in self.before_children]
        self.assertEqual(remaining, [], "OCR child was not reaped")

    def test_success_returns_scene_and_reaps_process(self):
        with patch("autohsr.ocr_isolation._ocr_job", worker_ok):
            scene = IsolatedVision(timeout=5).read(self.image, geometry="offline")
        self.assertIs(scene.image, self.image)
        self.assertEqual(scene.geometry, "offline")
        self.assertEqual(scene.tokens[0].text, "货币战争")

    def test_hung_runtime_is_terminated_at_deadline(self):
        started = time.monotonic()
        with patch("autohsr.ocr_isolation._ocr_job", worker_hangs), self.assertRaisesRegex(AutomationError, "超时"):
            IsolatedVision(timeout=.7).read(self.image)
        self.assertLess(time.monotonic() - started, 4)

    def test_stop_interrupts_hung_runtime_without_waiting_for_deadline(self):
        started = time.monotonic()
        def checkpoint():
            if time.monotonic() - started > .3:
                raise Stopped("stop requested")
        with patch("autohsr.ocr_isolation._ocr_job", worker_hangs), self.assertRaises(Stopped):
            IsolatedVision(checkpoint=checkpoint, timeout=8).read(self.image)
        self.assertLess(time.monotonic() - started, 4)

    def test_process_crash_has_no_accepted_result(self):
        with patch("autohsr.ocr_isolation._ocr_job", worker_crashes), self.assertRaisesRegex(AutomationError, "23"):
            IsolatedVision(timeout=5).read(self.image)

    def test_runtime_error_is_reported(self):
        with patch("autohsr.ocr_isolation._ocr_job", worker_errors), self.assertRaisesRegex(AutomationError, "unavailable"):
            IsolatedVision(timeout=5).read(self.image)

    def test_corrupt_result_is_rejected(self):
        with patch("autohsr.ocr_isolation._ocr_job", worker_invalid), self.assertRaisesRegex(AutomationError, "无法读取"):
            IsolatedVision(timeout=5).read(self.image)

    def test_start_failure_closes_process_handle(self):
        process = Mock()
        process.start.side_effect = OSError("spawn denied")
        with patch("autohsr.ocr_isolation.multiprocessing.get_context", return_value=Mock(Process=Mock(return_value=process))):
            with self.assertRaisesRegex(OSError, "spawn denied"):
                IsolatedVision().read(self.image)
        process.close.assert_called_once()
        process.join.assert_not_called()

    def test_timeout_removes_private_image_and_result_directory(self):
        original = tempfile.TemporaryDirectory
        directories = []
        def tracked(*args, **kwargs):
            directory = original(*args, **kwargs)
            directories.append(Path(directory.name))
            return directory
        with patch("autohsr.ocr_isolation.tempfile.TemporaryDirectory", side_effect=tracked), \
                patch("autohsr.ocr_isolation._ocr_job", worker_hangs), self.assertRaises(AutomationError):
            IsolatedVision(timeout=.3).read(self.image)
        self.assertTrue(directories)
        self.assertTrue(all(not path.exists() for path in directories))

    def test_invalid_tokens_fail_closed(self):
        for entry in (dict(text="x", score=float("nan"), box=[0, 0, .5, .5]),
                      dict(text="x", score=.9, box=[1, 0, .5, .5]),
                      dict(text="x", score=.9, box=[0, 0, 2, .5])):
            with self.assertRaises(AutomationError):
                _tokens(dict(status="ok", tokens=[entry]))

    def test_actual_bundled_ocr_runs_in_child_on_generated_ascii_image(self):
        import cv2
        image = np.full((120, 600, 3), 255, dtype=np.uint8)
        cv2.putText(image, "AutoHSR 123", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
        scene = IsolatedVision(timeout=20).read(image)
        self.assertIn("123", scene.text)
