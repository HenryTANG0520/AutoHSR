"""Exercise desktop tool actions with fake Tk controls and no game or desktop window."""
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from autohsr import desktop_workflows as tools
from autohsr.config import Settings
from autohsr.schedule_dispatch import NativeScheduleExecutor
from autohsr.schedule_plan import CHINA, ScheduleError
from autohsr.schedule_runtime import Scheduler
from autohsr.schedule_store import ScheduleStore
from autohsr.task_workflow import read
from autohsr.task_workflow_draft import WorkflowDraft


class Variable:
    def __init__(self, _parent=None, value=""):
        self.value = value
        self.callbacks = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in self.callbacks:
            callback()

    def trace_add(self, _mode, callback):
        self.callbacks.append(callback)


class Widget:
    def __init__(self, _parent=None, **options):
        self.options = options
        self.states = set()
        self.focused = False
        self.index = None
        self.modified = False
        self.content = ""
        self.callbacks = {}

    def _noop(self, *_args, **_kwargs):
        pass

    grid = grid_remove = columnconfigure = rowconfigure = edit_reset = see = yview = set = _noop

    def configure(self, **options):
        self.options.update(options)

    def state(self, states):
        for state in states:
            if state.startswith("!"):
                self.states.discard(state[1:])
            else:
                self.states.add(state)

    def instate(self, states):
        return self.states.issuperset(states)

    def bind(self, event, callback):
        self.callbacks[event] = callback

    def focus_set(self):
        self.focused = True

    def edit_modified(self, value=None):
        if value is not None:
            self.modified = value
        return self.modified

    def get(self, *_):
        return self.content

    def delete(self, *_):
        self.content = ""

    def insert(self, _index, value):
        self.content = value

    def mark_set(self, _name, index):
        self.index = index

    def user_text(self, value):
        self.content = value
        self.modified = True
        self.callbacks["<<Modified>>"]()


class FakeUI:
    busy = False
    ui_scale = 1

    def __init__(self, root):
        self.settings = Settings()
        self.settings_revision = 1
        self.now = datetime(2026, 11, 6, 8, 29, tzinfo=CHINA)
        self.factory = Mock(side_effect=AssertionError("The test must not create a runner"))
        self.executor = NativeScheduleExecutor(self.settings, base_dir=root, workflow_factory=self.factory,
                                               busy_probe=lambda: False)
        self.schedule_store = ScheduleStore(root / "schedules")
        self.scheduler = Scheduler(self.schedule_store, self.executor, clock=self._schedule_now)
        self.enabled = []
        self._workflow_action_changed = Mock()
        self._start_task_workflow = Mock(return_value=True)

    def _schedule_now(self):
        return self.now

    def _schedule_settings_key(self):
        return self.settings_revision

    def _schedule_snapshot(self):
        return self.scheduler.snapshot()

    def _schedule_preview_budget(self, plan):
        return self.executor.preview_budget(plan)

    def _schedule_enable(self, plan_id, expected_revision):
        self.enabled.append((plan_id, expected_revision))
        self.scheduler.enable(plan_id)
        self.scheduler.start()

    def _schedule_disable(self, plan_id):
        self.scheduler.disable(plan_id)

    def _schedule_stop(self):
        self.scheduler.stop()


class DesktopToolTests(unittest.TestCase):
    def setUp(self):
        contexts = ExitStack()
        self.addCleanup(contexts.close)
        self.root = Path(contexts.enter_context(TemporaryDirectory())).resolve()
        self.ui = FakeUI(self.root)
        self.source = self.root / "source.json"
        self.document = dict(version=1, name="原流程", steps=[
            dict(type="wait", id=f"step_{number}", seconds=0) for number in range(10)])
        self.original = json.dumps(self.document, ensure_ascii=False).encode("utf8")
        self.source.write_bytes(self.original)
        contexts.enter_context(patch.multiple(tools.ttk, **{
            name: Widget for name in ("Frame", "Button", "Combobox", "Entry", "Checkbutton", "Label", "Scrollbar")}))
        contexts.enter_context(patch.multiple(tools.tk, Text=Widget, StringVar=Variable, BooleanVar=Variable))
        contexts.enter_context(patch.multiple(tools.t, native_font=Mock(return_value=None), wrapped_label=Widget))
        contexts.enter_context(patch.multiple(tools._Panel, __init__=self._init_fake_panel,
            rowconfigure=Widget._noop, focus_get=lambda _: None, winfo_toplevel=lambda panel: panel))
        self.open_dialog = contexts.enter_context(patch.object(tools.filedialog, "askopenfilename", return_value=""))
        self.save_dialog = contexts.enter_context(patch.object(tools.filedialog, "asksaveasfilename", return_value=""))
        self.discard = contexts.enter_context(patch.object(tools.messagebox, "askyesno", return_value=False))
        self.addCleanup(self.ui.factory.assert_not_called)

    @staticmethod
    def _init_fake_panel(panel, _parent, ui):
        panel.ui = ui

    def open_workflow(self):
        self.ui.workflow_panel = panel = tools.build_workflow_panel(None, self.ui)
        self.assertFalse(panel.primary_action()[2])
        self.open_dialog.return_value = str(self.source)
        panel.open()
        return panel

    def new_schedule(self):
        self.ui.schedule_panel = panel = tools.build_schedule_panel(None, self.ui)
        for key, value in dict(id="morning", name="早间流程", time="08:30", target_type="任务流", count="3").items():
            panel.values[key].set(value)
        self.open_dialog.return_value = str(self.source)
        panel.pick_workflow()
        return panel

    def test_new_workflow_requires_verified_save_and_an_explicit_run(self):
        self.ui.workflow_panel = panel = tools.build_workflow_panel(None, self.ui)
        panel.new_button.options['command']()
        self.open_dialog.assert_not_called()
        self.save_dialog.assert_not_called()
        self.assertIsNone(panel.draft.source)
        self.assertIn("尚未保存", panel.source.get())
        self.assertTrue(panel.reload_button.instate(("disabled",)))
        self.assertTrue(panel.run_button.instate(("disabled",)))
        panel.validate()
        self.assertIn("日常预算 0 份", panel.budget.get())
        self.assertEqual(panel.source_status.get(), "")
        panel.run_saved()
        self.assertEqual(list(self.root.iterdir()), [self.source])

        edited = json.loads(panel.editor.content)
        edited['steps'][0]['enabled'] = True
        panel.editor.user_text(json.dumps(edited, ensure_ascii=False))
        panel.new()
        self.discard.assert_called_once()
        self.assertTrue(panel.dirty)
        panel.validate()
        self.assertIn("日常预算 1 份", panel.budget.get())
        self.ui.workflow_panel = current = tools.build_workflow_panel(None, self.ui)
        current.restore_draft(panel.snapshot_draft())
        self.assertIsNone(current.draft.source)
        self.assertTrue(current.dirty)
        self.assertIn("校验通过", current.status.get())

        self.save_dialog.return_value = str(self.source)
        current.save_as()
        self.assertIn("目标已存在", current.status.get())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertIsNone(current.draft.source)
        target = self.root / 'new-workflow.json'
        self.save_dialog.return_value = str(target)
        current.select_destination()
        current.primary_action()[1]()
        self.assertEqual(read(target), edited)
        self.assertEqual(current.draft.source, target)
        self.ui._start_task_workflow.assert_not_called()
        self.open_dialog.return_value = str(target)
        current.open()
        current.run_saved()
        self.ui._start_task_workflow.assert_called_once()
        self.assertEqual(self.ui._start_task_workflow.call_args.args[0].document, edited)

    def test_workflow_validate_and_exclusive_save_rebase_without_touching_original(self):
        panel = self.open_workflow()
        self.document["name"] = "审阅后的流程"
        panel.editor.user_text(json.dumps(self.document, ensure_ascii=False))
        self.assertTrue(panel.dirty)
        panel.validate()
        self.assertIn("校验通过", panel.status.get())
        self.assertIn("最多 10 步", panel.budget.get())
        sibling = self.root / "另存位置"
        sibling.mkdir()
        target = sibling / "copy.json"
        self.save_dialog.return_value = str(target)
        panel.select_destination()
        self.assertIn(str(sibling), panel.budget.get())
        self.assertFalse(target.exists())
        panel.primary_action()[1]()
        self.assertEqual(read(target), self.document)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertIn("已另存", panel.status.get())
        self.assertFalse(panel.dirty)

    def test_workflow_invalid_input_occupied_target_and_cancellation_keep_edits(self):
        panel = self.open_workflow()
        panel.editor.user_text('{\n"version":\n}')
        panel.validate()
        self.assertIn("第 3 行", panel.status.get())
        self.assertEqual(panel.editor.index, "3.0")
        panel.reload()
        self.discard.assert_called_once()
        self.assertTrue(panel.dirty)
        self.document["name"] = "草稿"
        panel.editor.user_text(json.dumps(self.document, ensure_ascii=False))
        target = self.root / "occupied.json"
        target.write_bytes(b"existing data")
        panel.save_as()
        self.assertTrue(panel.dirty)
        self.save_dialog.return_value = str(target)
        panel.save_as()
        self.assertIn("目标已存在", panel.status.get())
        self.assertTrue(panel.dirty)
        self.assertEqual(target.read_bytes(), b"existing data")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_workflow_post_publication_change_keeps_the_editor_and_original_source(self):
        panel = self.open_workflow()
        self.document["name"] = "草稿"
        panel.editor.user_text(json.dumps(self.document, ensure_ascii=False))
        target = self.root / "conflict.json"
        self.save_dialog.return_value = str(target)
        real_save = WorkflowDraft.save_as

        def save_and_replace(draft, path):
            saved = real_save(draft, path)
            saved.path.write_bytes(b'{"outside": true}')
            return saved

        with patch.object(WorkflowDraft, "save_as", save_and_replace):
            panel.save_as()
        self.assertIn("另存结果待核对", panel.status.get())
        self.assertTrue(panel.dirty)
        self.assertEqual(panel.draft.source, self.source)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(target.read_bytes(), b'{"outside": true}')

    def test_workflow_run_reloads_the_current_clean_file_and_delivers_to_new_layout(self):
        panel = self.open_workflow()
        panel.run_saved()
        self.ui._start_task_workflow.assert_called_once()
        call = self.ui._start_task_workflow.call_args
        self.assertEqual(call.args[0].document, self.document)
        self.assertEqual(call.args[0].base_dir, self.root)
        self.ui.workflow_panel = current = tools.build_workflow_panel(None, self.ui)
        current.restore_draft(panel.snapshot_draft())
        call.kwargs["on_report"](dict(status="partial"))
        self.assertIn("部分完成", current.status.get())
        self.assertNotIn("部分完成", panel.status.get())

    def test_workflow_never_runs_dirty_or_stale_source_but_can_clone_a_draft(self):
        panel = self.open_workflow()
        self.document["name"] = "编辑"
        panel.editor.user_text(json.dumps(self.document, ensure_ascii=False))
        panel.run_saved()
        self.ui._start_task_workflow.assert_not_called()
        panel.editor.user_text(panel.clean_text)
        self.source.write_text(json.dumps(dict(self.document, name="外部编辑")), encoding="utf8")
        panel.run_saved()
        self.assertIn("来源已变化", panel.source_status.get())
        self.ui._start_task_workflow.assert_not_called()
        panel.editor.user_text(json.dumps(self.document, ensure_ascii=False))
        target = self.root / "copy-after-source-change.json"
        self.save_dialog.return_value = str(target)
        panel.save_as()
        self.assertEqual(read(target), self.document)
        self.assertEqual(read(self.source)["name"], "外部编辑")

    def test_schedule_preview_save_enable_stop_are_separate_at_beijing_time(self):
        panel = self.new_schedule()
        panel.preview()
        self.assertIn("执行步数 30 步 · 开拓力 0 点 · 差分局数 0 局", panel.budget.get())
        self.assertIn("11-06 08:30", panel.preview_status.get())
        self.assertEqual(self.ui.schedule_store.list_public(), [])
        self.assertEqual(self.ui.enabled, [])
        self.assertEqual(panel.primary_action()[0], "保存计划")
        panel.primary_action()[1]()
        saved, revision = self.ui.schedule_store.load("morning")
        self.assertEqual(saved["target"]["path"], str(self.source))
        self.assertEqual(self.ui.enabled, [])
        self.assertIn("未启用", panel.runtime_status.get())
        label, command, enabled = panel.primary_action()
        self.assertEqual((label, enabled), ("启用计划", True))
        command()
        self.assertEqual(self.ui.enabled, [("morning", revision)])
        self.assertIn("等待触发", panel.runtime_status.get())
        self.ui.busy = True
        panel.refresh()
        self.assertFalse(panel.stop_button.instate(("disabled",)))
        panel.stop()
        self.assertIn("计时已停止", panel.runtime_status.get())
        self.assertFalse(self.ui.scheduler.snapshot()["running"])

    def test_schedule_settings_edit_and_incomplete_budget_require_a_new_preview(self):
        panel = self.new_schedule()
        panel.preview()
        panel.save()
        self.assertTrue(panel.primary_action()[2])
        self.ui.settings_revision += 1
        panel.refresh()
        self.assertIn("设置已变化", panel.preview_status.get())
        self.assertFalse(panel.primary_action()[2])
        good = self.ui._schedule_preview_budget(panel._plan())
        del good["whole_batch"]["du_runs_max"]
        with patch.object(self.ui, "_schedule_preview_budget", return_value=good):
            panel.preview()
        self.assertIn("差分局数 待核对", panel.budget.get())
        self.assertFalse(panel.primary_action()[2])
        panel.preview()
        panel.values["time"].set("08:35")
        self.assertTrue(panel.dirty)
        self.assertIn("重新预览", panel.preview_status.get())
        panel.save()
        panel.enable()
        self.assertEqual(self.ui.enabled, [])

    def test_schedule_changes_saved_version_and_refreshes_a_rebuilt_panel(self):
        panel = self.new_schedule()
        panel.preview()
        panel.save()
        panel.enable()
        prior = panel.saved_revision
        panel.values["name"].set("更新后的计划")
        panel.days[6].set(False)
        current = tools.build_schedule_panel(None, self.ui)
        current.restore_draft(panel.snapshot_draft())
        self.assertTrue(current.dirty)
        self.assertEqual(current.saved_revision, prior)
        self.assertEqual(current.values["name"].get(), "更新后的计划")
        self.assertFalse(current.days[6].get())
        current.preview()
        current.save()
        self.assertIn("需要重新启用", current.runtime_status.get())
        self.assertEqual(self.ui.scheduler.snapshot()["plans"][0]["revision"], prior)
        self.assertNotEqual(current.saved_revision, prior)
        current.enable()
        self.assertEqual(self.ui.scheduler.snapshot()["plans"][0]["revision"], current.saved_revision)
        self.ui.now += timedelta(minutes=1)
        current.refresh()
        self.assertIn("11-07 08:30", current.runtime_status.get())
        current.disable()
        self.assertIn("未启用", current.runtime_status.get())

    def test_schedule_rejects_repeat_for_game_and_a_concurrent_saved_revision(self):
        panel = self.new_schedule()
        panel.values["target_type"].set("正式任务")
        panel.preview()
        self.assertIn("游戏计划重复", panel.status.get())
        self.assertEqual(self.ui.enabled, [])
        panel.values["count"].set("1")
        panel.preview()
        panel.save()
        self.assertTrue(panel.primary_action()[2])
        saved, prior = self.ui.schedule_store.load("morning")
        self.ui.schedule_store.save(dict(saved, name="外部改动"), replace=True, expected_revision=prior)
        panel.enable()
        self.assertIn("保存版本已变化", panel.status.get())
        self.assertEqual(self.ui.enabled, [])
        self.assertFalse(panel.primary_action()[2])
        self.assertIn("重新预览", panel.preview_status.get())
        panel.values["name"].set("本地改动")
        panel.save()
        self.assertTrue(panel.dirty)
        self.assertIn("计划版本已改变", panel.status.get())
        self.assertEqual(self.ui.schedule_store.load("morning")[0]["name"], "外部改动")

    def test_schedule_open_is_explicit_and_bad_target_preserves_current_form(self):
        panel = self.new_schedule()
        panel.save()
        saved, _ = self.ui.schedule_store.load("morning")
        self.ui.schedule_store.save(dict(saved, id="bad", target=dict(type="task", task="unknown")))
        current = tools.build_schedule_panel(None, self.ui)
        label = next(label for label, identifier in current.saved_labels.items() if identifier == "morning")
        current.selected.set(label)
        self.assertIsNone(current.saved_id)
        current.open()
        self.assertEqual(current.saved_id, "morning")
        self.assertEqual(current.values["count"].get(), "3")
        bad = next(label for label, identifier in current.saved_labels.items() if identifier == "bad")
        current.selected.set(bad)
        current.open()
        self.assertEqual(current.saved_id, "morning")
        self.assertIn("打开计划失败", current.status.get())
        self.assertEqual(self.ui.enabled, [])

    def test_layout_reapplying_identical_text_preserves_reviewed_results(self):
        workflow = self.open_workflow()
        self.document["name"] = "保留校验"
        workflow.editor.user_text(json.dumps(self.document, ensure_ascii=False))
        workflow.validate()
        reviewed = tools.build_workflow_panel(None, self.ui)
        reviewed.restore_draft(workflow.snapshot_draft())
        reviewed.editor.user_text(reviewed.editor.content)
        self.assertIn("校验通过", reviewed.status.get())
        reviewed.editor.user_text(reviewed.editor.content + " ")
        self.assertIn("重新校验", reviewed.status.get())

        schedule = self.new_schedule()
        schedule.preview()
        schedule.save()
        previewed = tools.build_schedule_panel(None, self.ui)
        previewed.restore_draft(schedule.snapshot_draft())
        previewed.params.user_text(previewed.params.content)
        self.assertIn("执行步数 30 步", previewed.budget.get())
        self.assertTrue(previewed.primary_action()[2])
        previewed.params.user_text(previewed.params.content + " ")
        self.assertIn("重新预览", previewed.preview_status.get())


if __name__ == "__main__":
    unittest.main()
