"""Exercise the visual assignment edit against the actual draft and budget paths."""

import json
from unittest import TestCase
from unittest.mock import patch

from autohsr import desktop_workflows as tools
from autohsr.config import Settings
from autohsr.schedule_dispatch import NativeScheduleExecutor
from autohsr.task_workflow import read, task_spec
from autohsr.tests import test_desktop_workflows as fixtures


class VisualWorkflowStepTests(TestCase):
    _init_fake_panel = staticmethod(fixtures.DesktopToolTests._init_fake_panel)

    def setUp(self):
        fixtures.DesktopToolTests.setUp(self)
        self.enterContext(patch.multiple(fixtures.Widget, create=True,
            replace=lambda widget, _first, _last, text: widget.insert(None, text), edit_separator=fixtures.Widget._noop))
        self.ui.workflow_panel = self.panel = tools.build_workflow_panel(None, self.ui)

    def _toggle(self, enabled):
        self.panel.assignment_toggle.options["variable"].set(enabled)
        self.panel.assignment_toggle.options["command"]()

    def test_new_assignment_toggle_invalidates_preview_and_keeps_zero_stamina_after_save(self):
        panel = self.panel
        self.assertTrue(panel.assignment_toggle.instate(("disabled",)))
        panel.new()
        self.assertFalse(panel.assignment_enabled.get())
        self.assertFalse(panel.assignment_toggle.instate(("disabled",)))
        self.assertTrue(panel.assignment_toggle.focused)
        self.assertIn("0 开拓力", panel.assignment_status.get())
        original = json.loads(panel._text())
        panel.validate()
        self.assertIn("日常预算 0 份", panel.budget.get())
        self._toggle(True)
        self.assertTrue(panel.dirty)
        self.assertEqual(panel.budget.get(), "")
        self.assertIn("重新校验", panel.status.get())
        panel.validate()
        self.assertIn("日常预算 1 份", panel.budget.get())
        edited = json.loads(panel._text())
        original["steps"][0]["enabled"] = True
        self.assertEqual(edited, original)

        panel.save_as()  # Cancel the native filename chooser.
        panel.run_saved()
        self.assertEqual(list(self.root.iterdir()), [self.source])
        self.assertEqual(json.loads(panel._text()), edited)
        self.ui._start_task_workflow.assert_not_called()
        panel.new()  # Decline discarding the unsaved draft.
        self.discard.assert_called_once()
        self.assertTrue(panel.assignment_enabled.get())

        target = self.root / "assignment.json"
        self.save_dialog.return_value = str(target)
        panel.save_as()
        self.assertEqual(read(target), edited)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.ui._start_task_workflow.assert_not_called()
        panel.run_saved()
        self.ui._start_task_workflow.assert_called_once()
        recipe = self.ui._start_task_workflow.call_args.args[0]
        self.assertEqual(recipe.document, edited)
        settings = Settings(allow_stamina_spend=True, battle=True, daily=True, redemption_enabled=True,
                            mail=True, battlepass=True)
        current, options = task_spec(settings, recipe.steps[0], recipe.base_dir)
        self.assertEqual(options, dict(operation="daily", assignments_only=True, use_power_plan=False))
        self.assertTrue(current.assignments)
        self.assertFalse(any((current.battle, current.daily, current.redemption_enabled, current.mail, current.battlepass)))
        budget = NativeScheduleExecutor(settings, workflow_factory=self.ui.factory).preview_budget(dict(
            version=1, id="assignment", name="委托", time="08:30", target=dict(type="workflow", path=str(target))))
        self.assertEqual(budget["whole_batch"]["daily_stamina_max"], 0)

    def test_old_single_assignment_can_be_disabled_and_requires_fresh_saved_step_review(self):
        panel = self.panel
        document = dict(version=1, name="旧任务流", steps=[dict(id="dispatch", type="task", name="自定义名称",
            task="daily", params=dict(tasks=["assignments"]), on_failure="continue")])
        original = json.dumps(document, ensure_ascii=False, indent=4).encode("utf8")
        self.source.write_bytes(original)
        self.open_dialog.return_value = str(self.source)
        panel.open()
        self.assertTrue(panel.assignment_enabled.get())  # Omitted enabled means true.
        panel.scope.set("指定步骤")
        panel.step_path.set("0")
        panel.validate()
        self.assertIsNotNone(panel.reviewed_step)
        self._toggle(False)
        self.assertFalse(panel.assignment_enabled.get())
        self.assertIsNone(panel.reviewed_step)
        self.assertEqual(panel.budget.get(), "")
        self.assertTrue(panel.run_button.instate(("disabled",)))
        panel.run_saved()
        self.ui._start_task_workflow.assert_not_called()
        document["steps"][0]["enabled"] = False
        self.assertEqual(json.loads(panel._text()), document)
        self.assertEqual(self.source.read_bytes(), original)

        self.ui.workflow_panel = rebuilt = tools.build_workflow_panel(None, self.ui)
        rebuilt.restore_draft(panel.snapshot_draft())
        self.assertFalse(rebuilt.assignment_enabled.get())
        self.assertFalse(rebuilt.assignment_toggle.instate(("disabled",)))
        self.assertTrue(rebuilt.dirty)
        self.assertIsNone(rebuilt.reviewed_step)
        rebuilt.validate()
        self.assertIn("已禁用", rebuilt.budget.get())
        self.ui.busy = True
        rebuilt.refresh()
        self.assertTrue(rebuilt.assignment_toggle.instate(("disabled",)))

    def test_other_or_invalid_documents_and_queued_text_edits_stay_in_text_editor(self):
        panel = self.panel
        panel.new()
        panel.validate()
        document = json.loads(panel._text())
        document["name"] = "刚从 JSON 编辑"
        edited = json.dumps(document, ensure_ascii=False)
        panel.editor.content = edited  # The Text widget's modified event is still queued.
        self._toggle(True)
        self.assertEqual(panel._text(), edited)
        self.assertFalse(panel.assignment_enabled.get())
        self.assertEqual(panel.budget.get(), "")

        assignment = document["steps"][0]
        for steps in (
            [dict(assignment, params={})],
            [dict(assignment, params=dict(tasks=["assignments", "battle"]))],
            [assignment, dict(type="wait", id="wait", seconds=1)],
            [dict(type="for", id="loop", count=1, steps=[assignment])],
            [dict(assignment, enabled="false")],
        ):
            with self.subTest(steps=steps):
                text = json.dumps(dict(document, steps=steps), ensure_ascii=False)
                panel.editor.user_text(text)
                self.assertTrue(panel.assignment_toggle.instate(("disabled",)))
                self._toggle(True)
                self.assertEqual(panel._text(), text)
        panel.editor.user_text('{"version": 1, "name": "坏 JSON",')
        self._toggle(True)
        self.assertTrue(panel.assignment_toggle.instate(("disabled",)))
        self.assertIn("坏 JSON", panel._text())
        document["steps"][0]["enabled"] = True
        panel.editor.user_text(json.dumps(document, ensure_ascii=False))
        self.assertFalse(panel.assignment_toggle.instate(("disabled",)))
        self.assertTrue(panel.assignment_enabled.get())
        self.assertEqual(list(self.root.iterdir()), [self.source])
        self.ui._start_task_workflow.assert_not_called()
