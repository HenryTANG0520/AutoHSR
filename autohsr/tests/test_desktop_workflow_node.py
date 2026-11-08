"""The node editor with withdrawn Tk controls and in-memory draft callbacks."""
from copy import deepcopy
import gc
import json
import tkinter as tk
import unittest
from unittest.mock import Mock

from autohsr import theme
from autohsr.desktop_workflow_node import WorkflowNodeForm
from autohsr.desktop_workflows import _TASK_NAMES
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
        root.update_idletasks()
        root.destroy()
        del root
        gc.collect()

    def setUp(self):
        self.applied = Mock()
        self.cancelled = Mock()
        self.form = self.new_form(1)
        self.addCleanup(self.form.destroy)

    def new_form(self, scale):
        form = WorkflowNodeForm(self.root, scale=scale, task_names=_TASK_NAMES,
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

    def test_daily_scope_combines_tasks_and_keeps_advanced_parameters(self):
        self.form.open(dict(type="task", task="daily", params={"tasks": ["assignments"], "use_support": False}))
        self.form.daily_buttons["mail"].invoke()
        self.form.daily_buttons["battlepass"].invoke()
        self.assertEqual(self.submitted()["params"], {"tasks": ["assignments", "mail", "battlepass"],
                                                      "use_support": False})
        self.form.daily_config_button.invoke()
        self.assertTrue(self.form.daily_buttons["battle"].instate(("disabled",)))
        self.assertEqual(self.submitted()["params"], {"use_support": False})
        self.form.daily_config_button.invoke()
        self.applied.reset_mock()
        self.form.apply_button.invoke()
        self.assertIn("至少一项", self.form.error.get())
        self.applied.assert_not_called()
        self.form.daily_buttons["battlepass"].invoke()
        self.assertEqual(self.submitted()["params"], {"tasks": ["battlepass"], "use_support": False})

    def test_daily_scope_tracks_json_and_leaves_an_invalid_edit_intact(self):
        form = self.form
        form.open()
        self.write_params('{"tasks": ["daily", "mail"], "stamina_limit": 10}')
        form._sync_parameter_controls(None)
        self.assertTrue(form.daily_tasks["daily"].get())
        self.assertFalse(form.daily_tasks["assignments"].get())
        form.values["task"].set(_TASK_NAMES["workflow_open_page"])
        self.assertFalse(form.daily_scope.grid_info())
        form.values["task"].set(_TASK_NAMES["daily"])
        self.assertTrue(form.daily_tasks["mail"].get())
        self.assertEqual(self.submitted()["params"], {"tasks": ["daily", "mail"], "stamina_limit": 10})
        for invalid in ('{"tasks":', '{"tasks": ["mail", "mail"]}', '{"tasks": ["unknown"]}'):
            self.write_params(invalid)
            form._sync_parameter_controls(None)
            self.assertTrue(form.daily_config_button.instate(("disabled",)))
            form.daily_buttons["assignments"].invoke()
            self.assertEqual(form.parameters.get("1.0", "end-1c"), invalid)

    def test_plan_scope_accepts_weekly_only_and_preserves_advanced_parameters(self):
        self.form.open(dict(type="task", task="plan", params={"support_daily_only": True}))
        self.assertTrue(self.form.daily_scope.grid_info())
        self.assertTrue(self.form.daily_buttons["mail"].instate(("disabled",)))
        self.form.daily_config_button.invoke()
        self.assertEqual(self.submitted()["params"], {"tasks": [], "support_daily_only": True})
        self.form.daily_buttons["mail"].invoke()
        self.assertEqual(self.submitted()["params"], {"tasks": ["mail"], "support_daily_only": True})

    def test_page_picker_writes_the_selected_native_target(self):
        self.form.open()
        self.form.values["task"].set(_TASK_NAMES["workflow_open_page"])
        self.assertEqual(self.form.page_target.get(), "手机")
        self.form.page_target.set("生存索引")
        self.form._select_page(None)
        self.assertEqual(self.submitted()["params"], {"target": "survival_index"})
        self.write_params('{"target":"mail"}')
        self.form._show_page_picker()
        self.assertEqual(self.form.page_target.get(), "邮件")
        self.form.page_target.set("漫游签证角色展示")
        self.form._select_page(None)
        self.assertEqual(self.submitted()["params"], {"target": "visa_characters"})
        for label, target in (("漫游签证收集展示", "visa_collection"), ("大世界", "world"), ("普通相机", "camera"),
                              ("普通编队", "ordinary_team"),
                              ("逐光捡金", "difficulty_guide"), ("旷宇纷争", "universe_guide"),
                              ("无名勋礼", "battlepass"), ("无名勋礼 · 奖励", "battlepass_rewards"),
                              ("无名勋礼 · 任务", "battlepass_tasks")):
            self.assertIn(label, self.form.page_picker.cget("values"))
            self.form.page_target.set(label)
            self.form._select_page(None)
            self.assertEqual(self.submitted()["params"], {"target": target})

    def test_background_checkbox_only_changes_supported_navigation(self):
        form = self.form
        form.open(dict(type="task", task="workflow_open_page", params={"target": "guide"}))
        self.assertTrue(form.page_background_check.grid_info())
        self.assertFalse(form.page_background.get())
        form.page_background_check.invoke()
        self.assertEqual(self.submitted()["params"], {"target": "guide", "background": True})
        form.page_target.set("邮件")
        form._select_page(None)
        form._show_page_picker()
        self.assertFalse(form.page_background_check.grid_info())
        self.assertEqual(self.submitted()["params"], {"target": "mail"})

    def test_training_rewards_picker_saves_a_parameterless_native_step(self):
        self.form.open()
        self.assertIn("仅补领每日实训", self.form.controls["task"].cget("values"))
        self.form.values["task"].set("仅补领每日实训")
        self.assertEqual(self.submitted(), dict(type="task", name=None, enabled=False, task="daily_training_rewards",
                                                params={}, on_failure="stop"))

    def test_game_capture_requires_an_explicit_region(self):
        self.form.open()
        self.form.values["task"].set(_TASK_NAMES["workflow_game_capture"])
        self.form.apply_button.invoke()
        self.assertIn("region", self.form.error.get())
        self.applied.assert_not_called()
        self.write_params('{"region":[0.15,0.1,0.6,0.7]}')
        self.assertEqual(self.submitted()["params"], {"region": [0.15, 0.1, 0.6, 0.7]})

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

    def test_condition_source_switches_between_separate_explicit_parameter_drafts(self):
        self.form.open(step_ids=('prior',))
        values = self.form.values
        values['type'].set('条件循环')
        values['max_iterations'].set('3')
        values['step'].set('@last')
        values['condition_source'].set('实时图像')
        self.assertFalse(self.form._result_condition_frame.grid_info())
        self.assertTrue(self.form._parameters_frame.grid_info())
        self.assertTrue(self.form.template_button.grid_info())
        self.form.apply_button.invoke()
        self.assertTrue(self.form.error.get())
        self.applied.assert_not_called()
        image = dict(template='assets/button.png', region=[.1, .2, .5, .7], threshold=.92)
        self.write_params(json.dumps(image))
        values['screen_value'].set('未匹配')
        self.assertEqual(self.submitted(), dict(type='while', name=None, enabled=True, max_iterations=3,
            screen_condition=dict(task='workflow_game_image', params=image, value=False)))

        values['condition_source'].set('实时文字')
        self.assertFalse(self.form.template_button.grid_info())
        self.assertEqual(self.form._read_parameters(), {})
        self.applied.reset_mock()
        for raw in ('{"text":"已完成","contains":"false"}', '{"text":"x","image":"file.png"}', '[]'):
            self.write_params(raw)
            self.form.apply_button.invoke()
            self.assertTrue(self.form.error.get())
        self.applied.assert_not_called()
        text = dict(text='已完成', contains=False, threshold=.81)
        self.write_params(json.dumps(text))
        self.assertEqual(self.submitted()['screen_condition'], dict(task='workflow_game_text', params=text, value=False))

        values['condition_source'].set('实时图像')
        self.assertEqual(self.submitted()['screen_condition']['params'], image)
        values['condition_source'].set('前序步骤结果')
        self.assertTrue(self.form._result_condition_frame.grid_info())
        self.assertFalse(self.form._parameters_frame.grid_info())
        self.assertEqual(self.submitted(), dict(type='while', name=None, enabled=True, max_iterations=3,
            condition=dict(step='@last', field='status', op='eq', value='success')))

    def test_existing_live_query_opens_with_its_explicit_value_and_required_field(self):
        query = dict(task='workflow_game_text', params=dict(text='菜单', contains=True), value=False)
        self.form.open(dict(id='gate', type='if', screen_condition=query,
                            steps=[dict(id='child', type='wait', seconds=0)]))
        self.assertEqual(self.form.values['condition_source'].get(), '实时文字')
        self.assertEqual(self.form.values['screen_value'].get(), '未匹配')
        self.assertEqual(self.submitted()['screen_condition'], query)
        self.applied.reset_mock()
        self.form.values['screen_value'].set('')
        self.form.apply_button.invoke()
        self.assertIn('布尔值', self.form.error.get())
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
                ("等待", "seconds", (0, .25, 1e-6, 3600), ("3600.001", "-.5", "nan", "inf")),
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
                    self.assertIn("数字" if key == "seconds" else "整数", self.form.error.get())
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
                    for source in ('实时图像', '实时文字'):
                        form.values['condition_source'].set(source)
                        self.root.update_idletasks()
                        self.assertLessEqual(form.winfo_reqwidth(), round(360 * scale))
                finally:
                    form.destroy()
        theme.apply_theme(self.root, 1)


if __name__ == "__main__":
    unittest.main()
