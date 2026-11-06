"""Hidden Tk workflow bundle checks with explicit dialogs and a fake backend."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import desktop_workflows as tools


def workflow(name):
    return json.dumps(dict(version=1, name=name, steps=[dict(type="wait", id="wait", seconds=0)]),
                      ensure_ascii=False).encode("utf8")


class DesktopWorkflowBundleTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.source = self.directory / "existing.json"
        self.source.write_bytes(workflow("当前流程"))
        self.bundle = self.directory / "portable.zip"
        self.bundle.write_bytes(b"fixture")
        self.target = self.directory / "portable"
        self.exported = self.directory / "exported.zip"
        self.pending = None
        self.ui = SimpleNamespace(busy=False, closing=False, ui_scale=1, stop_requested=threading.Event(),
                                  _workflow_action_changed=Mock(), _start_task_workflow=Mock(),
                                  _submit_tool_job=Mock(side_effect=self.submit))
        self.panel = self.ui.workflow_panel = tools.build_workflow_panel(self.root, self.ui)
        self.open_dialog = self.enterContext(patch.object(tools.filedialog, "askopenfilename", return_value=""))
        self.save_dialog = self.enterContext(patch.object(tools.filedialog, "asksaveasfilename", return_value=""))
        self.confirm = self.enterContext(patch.object(tools.messagebox, "askyesno", return_value=False))
        backend = ModuleType("autohsr.workflow_bundle")
        backend.export_bundle = self.export_fake = Mock(side_effect=self.export_fixture)
        backend.import_bundle = self.import_fake = Mock(side_effect=self.import_fixture)
        self.enterContext(patch.dict(sys.modules, {"autohsr.workflow_bundle": backend}))
        self.addCleanup(self.ui._start_task_workflow.assert_not_called)

    def destroy_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def submit(self, title, work, done, failed):
        self.assertFalse(self.ui.busy)
        self.assertIsNone(self.pending)
        self.ui.busy = True
        self.ui.stop_requested.clear()
        self.pending = work, done, failed
        self.ui.workflow_panel.refresh()
        return True

    def execute(self, *, threaded=False):
        work, done, failed = self.pending
        if threaded:
            with ThreadPoolExecutor(max_workers=1) as pool:
                call = pool.submit(work, self.ui.stop_requested).result
        else:
            call = lambda: work(self.ui.stop_requested)
        try:
            result = call()
        except Exception as error:
            return failed, error
        return done, result

    def deliver(self, result):
        self.pending = None
        self.ui.busy = False
        self.ui.workflow_panel.refresh()
        self.assertTrue(self.ui.workflow_panel.open_button.instate(("disabled",)))
        callback, value = result
        callback(value)

    def import_fixture(self, bundle, destination, *, checkpoint):
        self.assertEqual(bundle, self.bundle)
        checkpoint()
        if destination.exists():
            raise ValueError("请选择尚未存在的目标目录。")
        destination.mkdir()
        path = destination / "workflow.json"
        path.write_bytes(workflow("素材包流程"))
        return path

    def export_fixture(self, source, target, *, checkpoint):
        self.assertEqual(source, self.source)
        self.assertEqual(target, self.exported)
        checkpoint()
        with self.assertRaises(PermissionError):
            with source.open("ab"):
                pass
        with target.open("xb") as stream:
            stream.write(b"export fixture")
        return target

    def load_original(self):
        self.panel._load(self.source)
        self.assertEqual(self.panel.draft.source, self.source)

    def select_import(self):
        self.open_dialog.return_value = str(self.bundle)
        self.save_dialog.return_value = str(self.target)
        self.panel.import_bundle()

    def test_import_and_export_availability_and_cancelled_choices(self):
        panel = self.panel
        self.assertTrue(panel.import_bundle_button.instate(("!disabled",)))
        self.assertTrue(panel.export_bundle_button.instate(("disabled",)))
        panel.import_bundle()
        self.save_dialog.assert_not_called()
        self.load_original()
        self.assertTrue(panel.export_bundle_button.instate(("!disabled",)))
        panel.export_bundle()
        self.assertEqual(self.save_dialog.call_args.kwargs["defaultextension"], ".zip")
        panel.editor.insert("end", "\n")
        panel._edit()
        self.assertTrue(panel.export_bundle_button.instate(("disabled",)))
        panel.export_bundle()
        self.save_dialog.assert_called_once()
        self.ui._submit_tool_job.assert_not_called()

    def test_open_yaml_converts_in_worker_to_an_unsaved_workflow(self):
        path = self.directory / "source.yml"
        raw = "name: 外部流程\nsteps:\n  - type: wait\n    seconds: 3\n".encode("utf8")
        path.write_bytes(raw)
        self.open_dialog.return_value = str(path)
        self.panel.open()
        self.assertIn(("三月七 YAML 流程", ("*.yaml", "*.yml")),
                      self.open_dialog.call_args.kwargs["filetypes"])
        self.deliver(self.execute(threaded=True))
        self.assertIsNone(self.panel.draft.source)
        self.assertEqual(self.panel.draft.original_source, path)
        self.assertEqual(self.panel.draft.document["steps"][0]["seconds"], 3)
        self.assertTrue(self.panel.run_button.instate(("disabled",)))
        self.assertEqual(path.read_bytes(), raw)

    def test_unsupported_yaml_keeps_the_current_draft(self):
        self.load_original()
        original = self.panel.draft
        path = self.directory / "unsupported.yaml"
        path.write_text("name: unsupported\nsteps:\n  - type: click_text\n", encoding="utf8")
        self.open_dialog.return_value = str(path)
        self.panel.open()
        self.deliver(self.execute(threaded=True))
        self.assertIs(self.panel.draft, original)
        self.assertIn("步骤 0", self.panel.status.get())

    def test_material_row_fits_within_existing_toolbar_width_at_both_scales(self):
        for scale in (1.0, 1.2):
            with self.subTest(scale=scale):
                self.ui.ui_scale = scale
                tools.t.apply_theme(self.root, scale)
                panel = tools.build_workflow_panel(self.root, self.ui)
                self.root.update_idletasks()
                row = panel.import_bundle_button.master
                self.assertIs(panel.export_bundle_button.master, row)
                self.assertLessEqual(row.winfo_reqwidth(), panel.new_button.master.winfo_reqwidth())
                panel.destroy()

    def test_export_holds_exact_saved_source_and_keeps_late_publication(self):
        self.load_original()
        original = self.panel.draft
        self.save_dialog.return_value = str(self.exported)
        self.panel.export_bundle_button.invoke()
        self.assertTrue(self.panel.import_bundle_button.instate(("disabled",)))
        self.assertTrue(self.panel.run_button.instate(("disabled",)))
        self.assertEqual(self.panel.editor.cget("state"), "disabled")
        result = self.execute(threaded=True)
        self.ui.stop_requested.set()
        self.deliver(result)
        self.assertEqual(self.panel.status.get(), f"已导出素材包 · {self.exported}")
        self.assertEqual(self.exported.read_bytes(), b"export fixture")
        self.assertEqual(self.source.read_bytes(), workflow("当前流程"))
        self.assertIs(self.panel.draft, original)
        self.assertTrue(self.panel.export_bundle_button.instate(("!disabled",)))
        self.export_fake.assert_called_once()

    def test_export_rejects_changed_saved_source_before_calling_backend(self):
        self.load_original()
        self.save_dialog.return_value = str(self.exported)
        self.panel.export_bundle()
        self.source.write_bytes(workflow("外部变更"))
        self.deliver(self.execute())
        self.assertIn("已保存的流程已变化", self.panel.status.get())
        self.assertEqual(self.source.read_bytes(), workflow("外部变更"))
        self.assertFalse(self.exported.exists())
        self.export_fake.assert_not_called()

    def test_import_dirty_decline_and_existing_directory_preserve_draft(self):
        self.load_original()
        self.panel.editor.insert("end", "\n")
        self.panel._edit()
        dirty_text = self.panel._text()
        self.select_import()
        self.confirm.assert_called_once()
        self.ui._submit_tool_job.assert_not_called()
        self.confirm.return_value = True
        self.target.mkdir()
        original_target = self.target / "workflow.json"
        original_target.write_bytes(workflow("目标原件"))
        self.select_import()
        self.deliver(self.execute())
        self.assertIn("尚未存在", self.panel.status.get())
        self.assertEqual(self.panel._text(), dirty_text)
        self.assertEqual(original_target.read_bytes(), workflow("目标原件"))
        self.assertEqual(self.source.read_bytes(), workflow("当前流程"))

    def test_import_gives_backend_the_original_selected_target_for_path_checks(self):
        chosen = self.directory / "selected-parent" / ".." / self.target.name
        self.open_dialog.return_value = str(self.bundle)
        self.save_dialog.return_value = str(chosen)
        self.import_fake.side_effect = ValueError("所选路径不可用。")
        self.panel.import_bundle()
        self.deliver(self.execute())
        self.assertEqual(self.import_fake.call_args.args, (self.bundle, chosen))
        self.assertIsNone(self.panel.draft)
        self.assertIn("所选路径不可用", self.panel.status.get())

    def test_import_updates_rebuilt_panel_and_resets_scope_without_execution(self):
        self.load_original()
        old = self.panel
        old.scope.set("指定步骤")
        old.step_path.set("0")
        old.validate()
        self.select_import()
        self.assertEqual(self.save_dialog.call_args.kwargs["initialfile"], self.bundle.stem)
        self.assertEqual(self.save_dialog.call_args.kwargs["defaultextension"], "")
        self.ui.ui_scale = 1.2
        self.panel = self.ui.workflow_panel = tools.build_workflow_panel(self.root, self.ui)
        self.panel.restore_draft(old.snapshot_draft())
        old.destroy()
        self.assertTrue(self.panel.import_bundle_button.instate(("disabled",)))
        result = self.execute(threaded=True)
        with patch.object(self.panel.editor, "focus_set", side_effect=AssertionError("hidden panel stole focus")):
            self.deliver(result)
        self.assertEqual(self.panel.scope.get(), "整棵流程")
        self.assertEqual(self.panel.step_path.get(), "")
        self.assertIsNone(self.panel.reviewed_step)
        self.assertEqual(self.panel.draft.source, self.target / "workflow.json")
        self.assertFalse(self.panel.dirty)
        self.assertIn("已打开任务流草稿", self.panel.status.get())
        self.assertEqual(self.source.read_bytes(), workflow("当前流程"))
        self.assertEqual(self.bundle.read_bytes(), b"fixture")

    def test_import_stop_before_worker_has_no_output(self):
        self.load_original()
        self.select_import()
        self.ui.stop_requested.set()
        self.deliver(self.execute())
        self.assertEqual(self.panel.status.get(), "导入素材包已停止")
        self.assertEqual(self.panel.draft.source, self.source)
        self.assertFalse(self.target.exists())
        self.import_fake.assert_not_called()

    def test_import_late_stop_preserves_published_directory_and_old_draft(self):
        self.load_original()
        self.select_import()
        result = self.execute()
        self.ui.stop_requested.set()
        self.deliver(result)
        self.assertEqual(self.panel.draft.source, self.source)
        self.assertIn("草稿加载已停止", self.panel.status.get())
        self.assertIn(str(self.target), self.panel.status.get())
        self.assertEqual((self.target / "workflow.json").read_bytes(), workflow("素材包流程"))

    def test_import_changed_readback_stays_unverified(self):
        self.load_original()
        self.select_import()
        result = self.execute()
        imported = self.target / "workflow.json"
        imported.write_bytes(workflow("发布后变更"))
        self.deliver(result)
        self.assertEqual(self.panel.draft.source, self.source)
        self.assertIn("草稿待核对", self.panel.status.get())
        self.assertEqual(imported.read_bytes(), workflow("发布后变更"))

    def test_stop_during_final_readback_preserves_old_draft(self):
        self.load_original()
        self.select_import()
        result = self.execute()
        imported = result[1][1]
        check = imported.source_is_current

        def stop_during_read():
            self.ui.stop_requested.set()
            return check()

        with patch.object(imported, "source_is_current", side_effect=stop_during_read):
            self.deliver(result)
        self.assertEqual(self.panel.draft.source, self.source)
        self.assertIn("草稿加载已停止", self.panel.status.get())

    def test_closing_or_declined_worker_does_not_install_or_leave_controls_locked(self):
        self.load_original()
        self.ui._submit_tool_job.side_effect = None
        self.ui._submit_tool_job.return_value = False
        self.select_import()
        self.assertIsNone(self.panel.bundle_job)
        self.assertTrue(self.panel.open_button.instate(("!disabled",)))
        self.assertFalse(self.target.exists())
        self.ui._submit_tool_job.side_effect = self.submit
        self.select_import()
        result = self.execute()
        self.ui.closing = True
        self.panel.destroy()
        callback, value = result
        callback(value)
        self.assertTrue(self.target.is_dir())


if __name__ == "__main__":
    unittest.main()
