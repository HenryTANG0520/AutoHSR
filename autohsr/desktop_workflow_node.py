"""Embedded properties editor for one task-tree node."""
import json
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk

from . import theme
from .task_workflow import (
    FIELDS, GAME_VISION_TASKS, MAX_WAIT_SECONDS, PAGE_TASK, TASKS, TEMPLATE_TASKS, WorkflowError,
    _condition, _integer, _params, _screen_condition, _text, _wait_seconds, loads,
)


_KINDS = {
    "task": "正式任务", "wait": "等待", "if": "条件分支", "for": "固定次数循环",
    "while": "条件循环", "break": "跳出循环", "continue": "继续下次循环", "stop": "停止任务流",
}
_FIELDS = {
    "status": "运行状态", "daily_verified": "日常已核实", "completed_runs": "完成局数",
    "victories": "胜利局数", "defeats": "失败局数", "points_verified": "积分已核实",
    "rewards_verified": "奖励已核实", "du_rewards_verified": "差分奖励已核实",
    "image_found": "图片已匹配", "text_found": "文字已匹配", "page_verified": "游戏页面已核实",
}
_OPERATORS = {"eq": "等于", "ne": "不等于", "lt": "小于", "le": "小于或等于", "gt": "大于", "ge": "大于或等于"}
_VALUE_LABELS = {
    str: {"success": "成功", "partial": "部分完成", "failed": "失败", "stopped": "已停止", "skipped": "已跳过"},
    bool: {True: "是", False: "否"},
}
_CONDITION_KINDS = ("if", "while")
_CONDITION_SOURCES = {"condition": "前序步骤结果", "workflow_game_image": "实时图像", "workflow_game_text": "实时文字"}
_SCREEN_VALUES = {True: "已匹配", False: "未匹配"}
_SCREEN_PARAMS = {"workflow_game_image": "条件 JSON · template", "workflow_game_text": "条件 JSON · text"}
_FAILURE = {"stop": "停止流程", "continue": "继续后续步骤"}
_PAGES = {
    "world": "大世界", "phone": "手机", "guide": "星际和平指南", "daily_training": "每日实训", "survival_index": "生存索引",
    "assignments": "委托", "mail": "邮件", "battlepass": "无名勋礼", "odyssey": "巡星之礼", "reward_guide": "奖励指南",
    "battlepass_rewards": "无名勋礼 · 奖励", "battlepass_tasks": "无名勋礼 · 任务",
    "difficulty_guide": "逐光捡金", "universe_guide": "旷宇纷争",
    "messages": "短信通知", "visa_characters": "漫游签证角色展示", "achievement_overview": "成就总览",
    "redemption_form": "兑换码表单",
}
_NUMBERS = {
    "wait": ("seconds", f"等待秒数（0～{MAX_WAIT_SECONDS}）", 0, MAX_WAIT_SECONDS),
    "for": ("count", "循环次数（1～1000）", 1, 1000),
    "while": ("max_iterations", "最大循环次数（1～1000）", 1, 1000),
}
_DECIMAL = re.compile(r"[0-9]{1,7}")


def _key(labels, selected):
    return next((key for key, label in labels.items() if label == selected), None)


def _label(labels, key):
    return labels.get(key, key) if isinstance(key, str) else str(key)


def _number(raw, low, high):
    if _DECIMAL.fullmatch(raw.strip()) is None:
        raise WorkflowError(f"请输入 {low}～{high} 的整数。")
    return _integer(int(raw), low, high)


def _default_params(task):
    return {
        "daily": {"tasks": ["assignments"]},
        "workflow_audio": {"path": "提示.wav"},
        "workflow_image": {"image": "截图.png", "template": "模板.png"},
        "workflow_game_image": {"template": "模板.png"},
        "workflow_game_text": {"text": "要查找的文字"},
        "workflow_open_page": {"target": "phone"},
        "workflow_text": {"image": "截图.png", "text": "要查找的文字"},
        "workflow_notify": {"profile": "default", "message": "本步骤已到达。"},
    }.get(task, {})


class WorkflowNodeForm(ttk.Frame):
    """Collect one node's fields and hand them to the enclosing draft editor."""

    def __init__(self, parent, *, scale, task_names, on_apply, on_cancel, on_capture_template=None):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.on_apply, self.on_cancel = on_apply, on_cancel
        self._on_capture_template = on_capture_template
        self._pad = round(6 * scale)
        self._tasks = {task: task_names.get(task, task) for task in sorted(TASKS)}
        self._edit_kind = None
        self._loading = False
        self._steps = ()
        self._parameter_key = None
        self._parameter_drafts = {}
        self._form_version = 0
        self._capture_pending = False
        self._captured_templates = {}
        self.values = {key: tk.StringVar(self) for key in (
            "type", "name", "task", "on_failure", "step", "field", "operator", "value",
            "seconds", "count", "max_iterations", "condition_source", "screen_value",
        )}
        self.controls = {}
        self.enabled = tk.BooleanVar(self)
        self.error = tk.StringVar(self)
        self.heading = tk.StringVar(self)
        ttk.Label(self, textvariable=self.heading, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")

        common = self._section(1)
        self._field(common, 0, 0, "type", "步骤类型", tuple(_KINDS.values()))
        self._field(common, 0, 1, "name", "名称（可留空）")
        ttk.Checkbutton(self, text="启用此步骤", variable=self.enabled).grid(
            row=2, column=0, sticky="w", pady=(self._pad, 0))

        self._task_frame = self._section(3)
        self._field(self._task_frame, 0, 0, "task", "正式任务", tuple(self._tasks.values()))
        self._field(self._task_frame, 0, 1, "on_failure", "失败时", tuple(_FAILURE.values()))

        self._parameters_frame = self._section(6)
        self._parameters_label = tk.StringVar(self)
        theme.wrapped_label(self._parameters_frame, textvariable=self._parameters_label, style="Settings.Note.TLabel").grid(
            row=0, column=0, sticky="ew")
        self.template_button = ttk.Button(self._parameters_frame, style="Compact.TButton", command=self.capture_template,
                                          text="采集模板…" if on_capture_template else "先选择另存位置")
        self.template_button.grid(row=0, column=1, sticky="e")
        self.page_target = tk.StringVar(self)
        self.page_picker = ttk.Combobox(self._parameters_frame, width=13, textvariable=self.page_target,
                                       values=tuple(_PAGES.values()), state="readonly", style="Settings.TCombobox")
        self.page_picker.grid(row=0, column=1, sticky="e")
        self.page_picker.bind("<<ComboboxSelected>>", self._select_page)
        editor = ttk.Frame(self._parameters_frame)
        editor.columnconfigure(0, weight=1)
        editor.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.parameters = tk.Text(editor, width=1, height=4, wrap="word", undo=True, relief="flat", bd=0,
                                  padx=self._pad, pady=self._pad, background=theme.FIELD, foreground=theme.TEXT,
                                  insertbackground=theme.TEXT, font=theme.native_font(self, 11))
        scroll = ttk.Scrollbar(editor, orient="vertical", command=self.parameters.yview)
        self.parameters.configure(yscrollcommand=scroll.set)
        self.parameters.grid(row=0, column=0, sticky="ew")
        self.parameters.bind("<<Modified>>", self._sync_page_json)
        scroll.grid(row=0, column=1, sticky="ns")

        self._number_frames = {}
        for kind, (key, label, _, _) in _NUMBERS.items():
            group = self._section(4, columns=1)
            self._field(group, 0, 0, key, label)
            self._number_frames[kind] = group

        self._condition_frame = self._section(5)
        self._field(self._condition_frame, 0, 0, "condition_source", "条件来源", tuple(_CONDITION_SOURCES.values()))
        self._screen_value_holder = self._field(self._condition_frame, 0, 1, "screen_value", "预期结果",
                                                tuple(_SCREEN_VALUES.values()))
        self._result_condition_frame = ttk.Frame(self._condition_frame)
        self._result_condition_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(self._pad, 0))
        for column in range(2):
            self._result_condition_frame.columnconfigure(column, weight=1, uniform="property")
        self._field(self._result_condition_frame, 0, 0, "step", "前序步骤", ())
        self._field(self._result_condition_frame, 0, 1, "field", "结果字段", tuple(_FIELDS.values()))
        self._field(self._result_condition_frame, 1, 0, "operator", "比较方式", ())
        value_holder = self._slot(self._result_condition_frame, 1, 1, "比较值")
        self.value_choice = ttk.Combobox(value_holder, textvariable=self.values["value"], width=1,
                                         state="readonly", style="Settings.TCombobox")
        self.value_number = ttk.Entry(value_holder, textvariable=self.values["value"], width=1, style="Settings.TEntry")
        self.value_choice.grid(row=1, column=0, sticky="ew")
        self.value_number.grid(row=1, column=0, sticky="ew")
        self.value_number.grid_remove()

        theme.wrapped_label(self, textvariable=self.error, style="Hint.TLabel").grid(
            row=7, column=0, sticky="ew", pady=(self._pad, 0))
        actions = ttk.Frame(self)
        actions.grid(row=8, column=0, sticky="e", pady=(self._pad, 0))
        self.cancel_button = ttk.Button(actions, text="取消", style="Panel.TButton", command=self.cancel)
        self.apply_button = ttk.Button(actions, text="应用属性", style="Panel.TButton", command=self.apply)
        self.cancel_button.grid(row=0, column=0, padx=(0, self._pad))
        self.apply_button.grid(row=0, column=1)

        self.values["type"].trace_add("write", self._kind_changed)
        self.values["task"].trace_add("write", self._task_changed)
        self.values["condition_source"].trace_add("write", self._condition_source_changed)
        self.values["field"].trace_add("write", self._field_changed)
        self._show_kind()

    def _section(self, row, columns=2):
        group = ttk.Frame(self)
        for column in range(columns):
            group.columnconfigure(column, weight=1, uniform="property")
        group.grid(row=row, column=0, sticky="ew", pady=(self._pad, 0))
        return group

    def _slot(self, parent, row, column, label):
        group = ttk.Frame(parent)
        group.columnconfigure(0, weight=1)
        group.grid(row=row, column=column, sticky="ew", padx=(0, self._pad) if column == 0 else 0,
                   pady=(self._pad, 0) if row else 0)
        theme.wrapped_label(group, text=label, style="Settings.Note.TLabel").grid(row=0, column=0, sticky="ew")
        return group

    def _field(self, parent, row, column, key, label, choices=None):
        group = self._slot(parent, row, column, label)
        options = dict(textvariable=self.values[key], width=1)
        if choices is None:
            widget = ttk.Entry(group, style="Settings.TEntry", **options)
        else:
            widget = ttk.Combobox(group, values=choices, state="readonly", style="Settings.TCombobox", **options)
        widget.grid(row=1, column=0, sticky="ew")
        self.controls[key] = widget
        return group

    def open(self, node=None, *, step_ids=()):
        """Load a new node or edit the given type. The parent owns geometry."""
        edit_kind = node.get("type") if isinstance(node, dict) else None
        if node is not None and (not isinstance(edit_kind, str) or edit_kind not in _KINDS):
            raise WorkflowError("此步骤类型无法在属性面板中编辑。")
        self._form_version += 1
        self._captured_templates.clear()
        data = node or {}
        self._edit_kind = edit_kind
        kind = edit_kind or "task"
        task = data.get("task", "daily")
        condition = data.get("condition")
        condition = condition if isinstance(condition, dict) else {}
        screen = data.get("screen_condition")
        screen = screen if isinstance(screen, dict) else {}
        screen_value = screen.get("value", True)
        field = str(condition.get("field", "status"))
        value = condition.get("value", "success")
        value_type = FIELDS.get(field)
        labels = _VALUE_LABELS.get(value_type, {})
        value_label = labels.get(value, str(value)) if type(value) is value_type else str(value)
        self._steps = tuple(dict.fromkeys(step for step in step_ids if isinstance(step, str) and step not in ("", "@last")))
        self._loading = True
        try:
            initial = {
                "type": _KINDS[kind], "name": data.get("name") or "", "task": _label(self._tasks, task),
                "on_failure": _label(_FAILURE, data.get("on_failure", "stop")),
                "step": condition.get("step", ""), "field": _FIELDS.get(field, field),
                "operator": _label(_OPERATORS, condition.get("op", "eq")),
                "value": value_label,
                "condition_source": _label(_CONDITION_SOURCES, screen.get("task", "condition")),
                "screen_value": _SCREEN_VALUES.get(screen_value, "") if type(screen_value) is bool else "",
            }
            for key, _, minimum, _ in _NUMBERS.values():
                initial[key] = str(data.get(key, minimum))
            for key, raw in initial.items():
                self.values[key].set(raw)
            self.enabled.set(data.get("enabled", True) if node is not None else False)
            self.controls["type"].configure(state="disabled" if node is not None else "readonly")
            self.controls["step"].configure(values=("@last", *self._steps) if self._steps else ())
            self._parameter_key = None
            self._parameter_drafts.clear()
            key = self._parameter_target()
            if node is not None and key is not None:
                source = data if key[0] == "task" else screen
                self._parameter_drafts[key] = json.dumps(source.get("params", {}), ensure_ascii=False, indent=2)
        finally:
            self._loading = False
        self.heading.set("编辑步骤属性" if node is not None else "新增步骤")
        self.error.set("")
        self._show_kind()
        self._show_condition(reset=False)
        self.controls["name"].focus_set()

    def _kind(self):
        return self._edit_kind or _key(_KINDS, self.values["type"].get())

    def _show_kind(self):
        kind = self._kind()
        for group in (self._task_frame, self._condition_frame, *self._number_frames.values()):
            group.grid_remove()
        if kind == "task":
            self._task_frame.grid()
        if kind in _NUMBERS:
            self._number_frames[kind].grid()
        if kind in _CONDITION_KINDS:
            self._condition_frame.grid()
            self._show_condition_source()
        self._show_parameters()

    def _kind_changed(self, *_):
        if self._loading or self._edit_kind is not None:
            return
        self._form_version += 1
        self.enabled.set(self._kind() != "task")
        self.error.set("")
        self._show_kind()

    def _set_parameters(self, text):
        self.parameters.delete("1.0", "end")
        self.parameters.insert("1.0", text)
        self.parameters.edit_reset()

    def _task_changed(self, *_):
        if self._loading or self._kind() != "task" or self._parameter_target() == self._parameter_key:
            return
        self._form_version += 1
        if self._edit_kind is None:
            self.enabled.set(False)
        self.error.set("")
        self._show_parameters()

    def _condition_source(self):
        return _key(_CONDITION_SOURCES, self.values["condition_source"].get())

    def _show_condition_source(self):
        if self._condition_source() in GAME_VISION_TASKS:
            self._result_condition_frame.grid_remove()
            self._screen_value_holder.grid()
        else:
            self._screen_value_holder.grid_remove()
            self._result_condition_frame.grid()

    def _condition_source_changed(self, *_):
        if not self._loading and self._kind() in _CONDITION_KINDS:
            self._form_version += 1
            self.error.set("")
            self._show_condition_source()
            self._show_parameters()

    def _parameter_target(self):
        kind = self._kind()
        if kind == "task":
            task = _key(self._tasks, self.values["task"].get())
            return ("task", task) if task is not None else None
        if kind in _CONDITION_KINDS:
            task = self._condition_source()
            if task in GAME_VISION_TASKS:
                return "screen_condition", task
        return None

    def _show_parameters(self):
        key = self._parameter_target()
        previous = self._parameter_key
        if key != previous:
            if previous is not None:
                self._parameter_drafts[previous] = self.parameters.get("1.0", "end-1c")
            self._parameter_key = key
            if key is not None:
                kind, task = key
                default = _default_params(task) if kind == "task" else {}
                self._set_parameters(self._parameter_drafts.get(key, json.dumps(default, ensure_ascii=False, indent=2)))
        if key is None:
            self._parameters_frame.grid_remove()
        else:
            kind, task = key
            self._parameters_label.set("高级参数 JSON" if kind == "task" else _SCREEN_PARAMS[task])
            self._parameters_frame.grid()
        self._show_template()
        self._show_page_picker()

    def _show_page_picker(self):
        if self._parameter_key != ("task", PAGE_TASK):
            self.page_picker.grid_remove()
            return
        self.page_picker.grid()
        try:
            params = loads(self.parameters.get("1.0", "end-1c"))
        except WorkflowError:
            params = {}
        target = params.get("target") if isinstance(params, dict) else None
        self.page_target.set(_PAGES.get(target, "") if isinstance(target, str) else "")

    def _sync_page_json(self, _event):
        if self.parameters.edit_modified():
            self.parameters.edit_modified(False)
            self._show_page_picker()

    def _select_page(self, _event):
        target = _key(_PAGES, self.page_target.get())
        if target is None or self._parameter_key != ("task", PAGE_TASK):
            return
        try:
            raw = self.parameters.get("1.0", "end-1c")
            params = loads(raw) if raw.strip() else {}
            if not isinstance(params, dict):
                raise WorkflowError("页面参数须为 JSON 对象。")
            params["target"] = target
            _params(PAGE_TASK, params)
        except WorkflowError as error:
            self.error.set(str(error))
            self._show_page_picker()
            return
        self._set_parameters(json.dumps(params, ensure_ascii=False, indent=2))
        self.error.set("")

    def _show_template(self):
        visible = self._parameter_key is not None and self._parameter_key[1] in TEMPLATE_TASKS
        if visible:
            self.template_button.grid()
        else:
            self.template_button.grid_remove()
        enabled = visible and self._on_capture_template is not None and not self._capture_pending
        self.template_button.state(("!disabled" if enabled else "disabled",))

    def cancel(self):
        self._form_version += 1
        self.on_cancel()

    def capture_template(self):
        key = self._parameter_key
        if (key is None or key[1] not in TEMPLATE_TASKS or self._capture_pending
                or self._on_capture_template is None):
            return
        raw = self.parameters.get("1.0", "end-1c")
        version = self._form_version
        try:
            params = loads(raw) if raw.strip() else {}
            if not isinstance(params, dict):
                raise WorkflowError("高级参数须为 JSON 对象。")
            self._capture_pending = True
            self._show_template()
            binding = self._on_capture_template()
            if (binding is None or not self.winfo_exists() or self._form_version != version
                    or self.parameters.get("1.0", "end-1c") != raw):
                return
            params["template"] = binding.relative_path
            self._captured_templates[key, Path(binding.relative_path)] = binding
            self.parameters.edit_separator()
            self.parameters.replace("1.0", "end-1c", json.dumps(params, ensure_ascii=False, indent=2))
            self.parameters.edit_separator()
            self.error.set("")
            self.parameters.focus_set()
        except tk.TclError:
            # The app or parent may have closed while the modal owned focus.
            return
        except (WorkflowError, OSError) as error:
            if self.winfo_exists() and self._form_version == version:
                self.error.set(str(error))
        finally:
            self._capture_pending = False
            try:
                if self.winfo_exists():
                    self._show_template()
            except tk.TclError:
                pass

    def template_binding(self, fields):
        kind = "screen_condition" if "screen_condition" in fields else "task"
        source = fields.get("screen_condition", fields)
        template = source.get("params", {}).get("template")
        key = kind, source.get("task")
        return self._captured_templates.get((key, Path(template))) if isinstance(template, str) else None

    def _field_changed(self, *_):
        if not self._loading:
            self.error.set("")
            self._show_condition(reset=True)

    def _show_condition(self, *, reset):
        value_type = FIELDS.get(_key(_FIELDS, self.values["field"].get()))
        numeric = value_type is int
        operators = tuple(_OPERATORS.values()) if numeric else (_OPERATORS["eq"], _OPERATORS["ne"])
        self.controls["operator"].configure(values=operators)
        choices = tuple(_VALUE_LABELS.get(value_type, {}).values())
        self.value_choice.configure(values=choices)
        visible, hidden = (self.value_number, self.value_choice) if numeric else (self.value_choice, self.value_number)
        hidden.grid_remove()
        visible.grid()
        if reset:
            if self.values["operator"].get() not in operators:
                self.values["operator"].set(operators[0])
            raw = self.values["value"].get()
            if numeric and _DECIMAL.fullmatch(raw.strip()) is None:
                self.values["value"].set("0")
            elif choices and raw not in choices:
                self.values["value"].set(choices[0])

    def _read_condition(self):
        field = _key(_FIELDS, self.values["field"].get())
        raw = self.values["value"].get()
        value_type = FIELDS.get(field)
        value = _number(raw, 0, 1000000) if value_type is int else _key(_VALUE_LABELS.get(value_type, {}), raw)
        condition = dict(step=self.values["step"].get(), field=field,
                         op=_key(_OPERATORS, self.values["operator"].get()), value=value)
        _condition(condition, self._steps)
        return condition

    def _read_parameters(self):
        raw = self.parameters.get("1.0", "end-1c")
        return loads(raw) if raw.strip() else {}

    def _read_fields(self):
        kind = self._kind()
        if kind not in _KINDS:
            raise WorkflowError("请选择步骤类型。")
        name = self.values["name"].get()
        fields = dict(type=kind, name=_text(name) if name else None, enabled=self.enabled.get())
        if kind in _NUMBERS:
            key, _, low, high = _NUMBERS[kind]
            raw = self.values[key].get()
            if kind == 'wait':
                try:
                    value = int(raw) if _DECIMAL.fullmatch(raw.strip()) else float(raw)
                except ValueError:
                    value = None
                fields[key] = _wait_seconds(value)
            else:
                fields[key] = _number(raw, low, high)
        if kind in _CONDITION_KINDS:
            source = self._condition_source()
            if source == "condition":
                fields["condition"] = self._read_condition()
            else:
                if source not in GAME_VISION_TASKS:
                    raise WorkflowError("请选择条件来源。")
                query = dict(task=source, params=self._read_parameters(),
                             value=_key(_SCREEN_VALUES, self.values["screen_value"].get()))
                _screen_condition(query)
                fields["screen_condition"] = query
        if kind == "task":
            task = _key(self._tasks, self.values["task"].get())
            policy = _key(_FAILURE, self.values["on_failure"].get())
            if task is None or policy is None:
                raise WorkflowError("请选择正式任务和失败策略。")
            params = self._read_parameters()
            _params(task, params)
            fields.update(task=task, params=params, on_failure=policy)
        return fields

    def apply(self):
        if self._capture_pending:
            return
        try:
            fields = self._read_fields()
            self.error.set("")
            self.on_apply(fields)
        except ValueError as error:
            self.error.set(str(error))
