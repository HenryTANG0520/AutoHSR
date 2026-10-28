"""Displayed run counts must be backed by the durable DU ledger."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.models import RunReport


class UniverseProgressTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)/"differential-universe-ledger.json"
        self.events = []
        def emit(event):
            ledger = json.loads(self.path.read_text("utf-8"))
            self.assertEqual(event["completed_runs"], ledger["completed_runs"])
            self.events.append(event)
        self.context = SimpleNamespace(settings=Settings(), report=RunReport(run_dir=directory.name),
                                       runner=SimpleNamespace(emit=emit))
        self.workflow = DifferentialUniverseWorkflow(self.context, 2)

    def test_attempts_do_not_increment_displayed_completion(self):
        self.workflow._persist_ledger()
        self.workflow.report["current_run"] = 1
        self.workflow.report["run_results"] = [dict(status="running", counted=False)]
        self.workflow._persist_ledger()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["completed_runs"], 0)
        self.workflow.report["run_results"][0].update(status="completed", counted=True)
        self.workflow.report["completed_runs"] = 1
        self.workflow._persist_ledger()
        self.assertEqual([e["completed_runs"] for e in self.events], [0, 1])
        self.assertEqual(self.events[-1]["requested_runs"], 2)

    def test_failed_ledger_write_does_not_publish_new_progress(self):
        self.workflow._persist_ledger()
        self.workflow.report["completed_runs"] = 1
        with patch("autohsr.differential_universe.replace_file", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                self.workflow._persist_ledger()
        self.assertEqual([e["completed_runs"] for e in self.events], [0])
        self.assertEqual(json.loads(self.path.read_text("utf-8"))["completed_runs"], 0)

    def test_missing_run_directory_has_no_verified_progress_event(self):
        self.workflow.report.pop("run_dir")
        self.workflow._persist_ledger()
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
