import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autohsr.gui import AutoHSRWindow


class ClockUpdateTests(unittest.TestCase):
    def setUp(self):
        self.interpreter = tk.Tcl()
        self.elapsed = tk.StringVar(self.interpreter, value="00:00")
        self.writes = []
        self.elapsed.trace_add("write", lambda *_: self.writes.append(self.elapsed.get()))
        self.ui = SimpleNamespace(started_at=None, elapsed_seconds=0, elapsed=self.elapsed)
        self.ui._clock = lambda: AutoHSRWindow._clock(self.ui)

    def test_idle_polling_does_not_invalidate_the_window(self):
        for _ in range(20):
            self.ui._clock()
        self.assertEqual(self.writes, [])

    def test_running_clock_changes_once_per_displayed_second(self):
        self.ui.started_at = 100
        for now in (100, 100.1, 100.9, 101.01, 101.1, 101.9, 3701.2):
            with patch("autohsr.gui.time.monotonic", return_value=now):
                self.ui._clock()
        self.assertEqual(self.writes, ["00:01", "01:00:01"])

    def test_frozen_result_keeps_time_without_new_redraws(self):
        self.ui.started_at = 100
        with patch("autohsr.gui.time.monotonic", return_value=165.2):
            AutoHSRWindow._freeze_clock(self.ui)
        with patch("autohsr.gui.time.monotonic", return_value=900):
            for _ in range(10):
                self.ui._clock()
        self.assertIsNone(self.ui.started_at)
        self.assertEqual(self.ui.elapsed_seconds, 65)
        self.assertEqual(self.writes, ["01:05"])


if __name__ == "__main__":
    unittest.main()
