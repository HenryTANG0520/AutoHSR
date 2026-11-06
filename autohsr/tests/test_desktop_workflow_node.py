"""The node editor with withdrawn Tk controls and in-memory draft callbacks."""
from copy import deepcopy
import gc
import tkinter as tk
import unittest
from unittest.mock import Mock

from autohsr import theme
from autohsr.desktop_workflow_node import WorkflowNodeForm
from autohsr.task_workflow import TASKS, WorkflowError, compile_recipe


class WorkflowNodeFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:
            raise unittest.SkipTest("Tk 不可用") from error
        cls.root.withdraw()
        cls.addClassCleanup(cls.destroy_root)
        theme.apply_theme(cls.root, 1)

    @classmethod
    def destroy_root(cls):
        root, cls.root = cls.root, None
        root.destroy()
        del root
        gc.collect()

    def setUp(self):
        self.applied = Mock()
        self.cancelled = Mock()
        self.form = self.new_form(1)
        self.addCleanup(self.form.destroy)

    def new_form(self, scale):
        form = WorkflowNodeForm(self.root, scale=scale, task_names={"daily": "每日任务", "warp_export": "跃迁记录导出"},
                                on_apply=self.applied, on_cancel=self.cancelled)
        form.pack(fill="both", expand=True)
        return form

    def write_params(self, text):
        self.form.parameters.delete("1.0", "end")
        self.form.parameters.insert("1.0", text)

    def submitted(self):
        self.form.apply_button.invoke()
        self.assertEqual(self.form.error.get(), "")
        return self.applied.call_args.args[0]

    def test_new_task_defaults_to_disabled_and_explicit_assignments(self):
        form = self.form
        form.open()
        self.assertTrue(form.controls["type"].instate(("readonly",)))
        choices = form.controls["task"].cget("values")
        self.assertEqual(len(choices), len(TASKS))
        self.assertIn("每日任务", choices)
        self.assertIn("跃迁记录导出", choices)
        self.assertEqual(self.submitted(), dict(type="task", name=None, enabled=False, task="daily",
                                              params={"tasks": ["assignments"]}, on_failure="stop"))
        self.cancelled.assert_not_called()

    def test_edit_locks_node_type_and_can_clear_optional_values(self):
        node = dict(id="original", type="task", name="旧名称", enabled=True, task="daily",
                    params={"tasks": ["assignments"], "use_support": False}, on_failure="continue")
        original = deepcopy(node)
        self.form.open(node)
        self.assertTrue(self.form.controls["type"].instate(("disabled",)))
        self.assertEqual(self.submitted(), {key: value for key, value in node.items() if key != "id"})
        self.form.values["type"].set("等待")
        self.form.values["name"].set("")
        self.form.values["on_failure"].set("停止流程")
        self.write_params("")
        self.assertEqual(self.submitted(), dict(type="task", name=None, enabled=True, task="daily",
                                              params={}, on_failure="stop"))
        self.assertEqual(node, original)
        with self.assertRaises(WorkflowError):
            self.form.open({"type": []})

    def test_all_control_types_return_only_their_own_fields(self):
        for label, kind, expected in (
                ("等待", "wait", {"seconds": 0}),
                ("条件分支", "if", {"condition": dict(step="@last", field="status", op="eq", value="success")}),
                ("固定次数循环", "for", {"count": 1}),
                ("条件循环", "while", {"max_iterations": 1,
                                "condition": dict(step="@last", field="status", op="eq", value="success")}),
                ("跳出循环", "break", {}),
                ("继续下次循环", "continue", {}),
                ("停止任务流", "stop", {}),
        ):
            with self.subTest(kind=kind):
                self.form.open(step_ids=("prior",))
                self.form.values["type"].set(label)
                self.form.values["name"].set("示例")
                self.form.values["step"].set("@last")
                self.assertEqual(self.submitted(), dict(type=kind, enabled=True, name="示例", **expected))

    def test_condition_value_uses_backend_type_and_preceding_step_scope(self):
        node = dict(id="loop", type="while", max_iterations=2,
                    condition=dict(step="prior", field="daily_verified", op="ne", value=False),
                    steps=[dict(id="child", type="wait", seconds=0)])
        original = deepcopy(node)
        self.form.open(node, step_ids=("prior", "other"))
        self.assertEqual(self.form.controls["step"].cget("values"), ("@last", "prior", "other"))
        self.assertEqual(self.form.controls["operator"].cget("values"), ("等于", "不等于"))
        self.assertIs(self.submitted()["condition"]["value"], False)
        self.assertNotIn("steps", self.applied.call_args.args[0])
        self.form.values["field"].set("完成局数")
        self.assertIn("大于或等于", self.form.controls["operator"].cget("values"))
        self.form.values["operator"].set("大于或等于")
        self.form.values["value"].set("1000000")
        self.form.values["max_iterations"].set("1000")
        fields = self.submitted()
        self.assertEqual(fields["condition"], dict(step="prior", field="completed_runs", op="ge", value=1000000))
        self.assertEqual(fields["max_iterations"], 1000)
        compiled = compile_recipe(dict(version=1, name="fixture", steps=[
            dict(id="prior", type="wait", seconds=0),
            dict(node, **{key: value for key, value in fields.items() if value is not None}),
        ]))
        self.assertEqual(compiled.steps[1]["steps"], original["steps"])
        self.assertEqual(node, original)
        self.applied.reset_mock()
        self.form.values["value"].set("1000001")
        self.form.apply_button.invoke()
        self.assertIn("1000000", self.form.error.get())
        self.form.values["field"].set("日常已核实")
        self.assertEqual(self.form.values["operator"].get(), "等于")
        self.form.values["operator"].set("大于")
        self.form.apply_button.invoke()
        self.assertIn("计数字段", self.form.error.get())
        self.applied.assert_not_called()

    def test_missing_future_or_self_step_is_rejected(self):
        for prior, selected in (((), "@last"), (("prior",), "later"), (("prior",), "edited")):
            with self.subTest(prior=prior, selected=selected):
                self.form.open(dict(id="edited", type="if",
                    condition=dict(step=selected, field="status", op="eq", value="success")), step_ids=prior)
                if not prior:
                    self.assertFalse(self.form.controls["step"].cget("values"))
                self.form.apply_button.invoke()
                self.assertIn("前面步骤", self.form.error.get())
        self.applied.assert_not_called()

    def test_numeric_wait_loop_and_iteration_ranges(self):
        for label, key, valid, invalid in (
                ("等待", "seconds", (0, 3600), ("3601", "-1", "1.5")),
                ("固定次数循环", "count", (1, 1000), ("0", "1001", "nan")),
                ("条件循环", "max_iterations", (1, 1000), ("0", "1001", "")),
        ):
            with self.subTest(field=key):
                self.form.open(step_ids=("prior",))
                self.form.values["type"].set(label)
                self.form.values["step"].set("prior")
                for value in valid:
                    self.form.values[key].set(str(value))
                    self.assertEqual(self.submitted()[key], value)
                self.applied.reset_mock()
                for raw in invalid:
                    self.form.values[key].set(raw)
                    self.form.apply_button.invoke()
                    self.assertIn("整数", self.form.error.get())
                self.applied.assert_not_called()

    def test_advanced_parameters_are_validated_and_remembered_per_task(self):
        form = self.form
        form.open()
        for raw in ('{"tasks":[]}', '{"tasks":[],"tasks":["assignments"]}', '{"rounds":NaN}', '{"unknown":1}', '[]'):
            with self.subTest(raw=raw):
                self.write_params(raw)
                form.apply_button.invoke()
                self.assertTrue(form.error.get())
        self.applied.assert_not_called()
        daily = '{"tasks":["assignments"],"use_support":false}'
        self.write_params(daily)
        form.enabled.set(True)
        form.values["task"].set("跃迁记录导出")
        self.assertFalse(form.enabled.get())
        self.write_params('{"imports":["history.json"],"output":"copy.json","selected_uid":"invalid"}')
        form.apply_button.invoke()
        self.assertIn("UID", form.error.get())
        self.applied.assert_not_called()
        self.write_params('{"imports":["history.json"],"output":"copy.json"}')
        self.assertEqual(self.submitted()["params"], dict(imports=["history.json"], output="copy.json"))
        form.values["task"].set("每日任务")
        self.assertEqual(form.parameters.get("1.0", "end-1c"), daily)
        self.assertEqual(self.submitted()["params"], dict(tasks=["assignments"], use_support=False))

    def test_apply_error_stays_in_the_form_and_cancel_only_notifies_parent(self):
        self.form.on_apply = Mock(side_effect=WorkflowError("当前位置无法插入此步骤。"))
        self.form.open()
        self.form.values["type"].set("跳出循环")
        self.form.apply_button.invoke()
        self.form.on_apply.assert_called_once_with(dict(type="break", name=None, enabled=True))
        self.assertIn("当前位置", self.form.error.get())
        self.form.cancel_button.invoke()
        self.cancelled.assert_called_once_with()
        self.applied.assert_not_called()

    def test_theme_requests_fit_a_narrow_content_column_at_supported_scales(self):
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                theme.apply_theme(self.root, scale)
                form = self.new_form(scale)
                try:
                    form.open(step_ids=("earlier",))
                    for kind in ("正式任务", "条件循环"):
                        form.values["type"].set(kind)
                        self.root.update_idletasks()
                        self.assertLessEqual(form.winfo_reqwidth(), round(360 * scale))
                        self.assertEqual(self.root.state(), "withdrawn")
                finally:
                    form.destroy()
        theme.apply_theme(self.root, 1)


if __name__ == "__main__":
    unittest.main()
