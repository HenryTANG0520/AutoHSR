"""Embedded properties editor for one task-tree node."""
import json
import re
import tkinter as tk
from tkinter import ttk

from . import theme
from .task_workflow import FIELDS, TASKS, WorkflowError, _condition, _integer, _params, _text, loads


_KINDS = {
    "task": "正式任务", "wait": "等待", "if": "条件分支", "for": "固定次数循环",
    "while": "条件循环", "break": "跳出循环", "continue": "继续下次循环", "stop": "停止任务流",
}
_FIELDS = {
    "status": "运行状态", "daily_verified": "日常已核实", "completed_runs": "完成局数",
    "victories": "胜利局数", "defeats": "失败局数", "points_verified": "积分已核实",
    "rewards_verified": "奖励已核实", "du_rewards_verified": "差分奖励已核实",
    "image_found": "图片已匹配", "text_found": "文字已匹配",
}
_OPERATORS = {"eq": "等于", "ne": "不等于", "lt": "小于", "le": "小于或等于", "gt": "大于", "ge": "大于或等于"}
_VALUE_LABELS = {
    str: {"success": "成功", "partial": "部分完成", "failed": "失败", "stopped": "已停止", "skipped": "已跳过"},
    bool: {True: "是", False: "否"},
}
_FAILURE = {"stop": "停止流程", "continue": "继续后续步骤"}
_NUMBERS = {
    "wait": ("seconds", "等待秒数（0～3600）", 0, 3600),
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
        "workflow_text": {"image": "截图.png", "text": "要查找的文字"},
        "workflow_notify": {"profile": "default", "message": "本步骤已到达。"},
    }.get(task, {})


class WorkflowNodeForm(ttk.Frame):
    """Collect one node's fields and hand them to the enclosing draft editor."""

    def __init__(self, parent, *, scale, task_names, on_apply, on_cancel):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.on_apply = on_apply
        self._pad = round(6 * scale)
        self._tasks = {task: task_names.get(task, task) for task in sorted(TASKS)}
        self._edit_kind = None
        self._loading = False
        self._steps = ()
        self._current_task = None
        self._task_drafts = {}
        self.values = {key: tk.StringVar(self) for key in (
            "type", "name", "task", "on_failure", "step", "field", "operator", "value",
            "seconds", "count", "max_iterations",
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
        ttk.Label(self._task_frame, text="高级参数 JSON", style="Settings.Note.TLabel").grid(
            row=1, column=0, sticky="w", pady=(self._pad, 0))
        editor = ttk.Frame(self._task_frame)
        editor.columnconfigure(0, weight=1)
        editor.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.parameters = tk.Text(editor, width=1, height=4, wrap="word", undo=True, relief="flat", bd=0,
                                  padx=self._pad, pady=self._pad, background=theme.FIELD, foreground=theme.TEXT,
                                  insertbackground=theme.TEXT, font=theme.native_font(self, 11))
        scroll = ttk.Scrollbar(editor, orient="vertical", command=self.parameters.yview)
        self.parameters.configure(yscrollcommand=scroll.set)
        self.parameters.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")

        self._number_frames = {}
        for kind, (key, label, _, _) in _NUMBERS.items():
            group = self._section(4, columns=1)
            self._field(group, 0, 0, key, label)
            self._number_frames[kind] = group

        self._condition_frame = self._section(5)
        self._field(self._condition_frame, 0, 0, "step", "前序步骤", ())
        self._field(self._condition_frame, 0, 1, "field", "结果字段", tuple(_FIELDS.values()))
        self._field(self._condition_frame, 1, 0, "operator", "比较方式", ())
        value_holder = self._slot(self._condition_frame, 1, 1, "比较值")
        self.value_choice = ttk.Combobox(value_holder, textvariable=self.values["value"], width=1,
                                         state="readonly", style="Settings.TCombobox")
        self.value_number = ttk.Entry(value_holder, textvariable=self.values["value"], width=1, style="Settings.TEntry")
        self.value_choice.grid(row=1, column=0, sticky="ew")
        self.value_number.grid(row=1, column=0, sticky="ew")
        self.value_number.grid_remove()

        theme.wrapped_label(self, textvariable=self.error, style="Hint.TLabel").grid(
            row=6, column=0, sticky="ew", pady=(self._pad, 0))
        actions = ttk.Frame(self)
        actions.grid(row=7, column=0, sticky="e", pady=(self._pad, 0))
        self.cancel_button = ttk.Button(actions, text="取消", style="Panel.TButton", command=on_cancel)
        self.apply_button = ttk.Button(actions, text="应用属性", style="Panel.TButton", command=self.apply)
        self.cancel_button.grid(row=0, column=0, padx=(0, self._pad))
        self.apply_button.grid(row=0, column=1)

        self.values["type"].trace_add("write", self._kind_changed)
        self.values["task"].trace_add("write", self._task_changed)
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

    def open(self, node=None, *, step_ids=()):
        """Load a new node or edit the given type. The parent owns geometry."""
        edit_kind = node.get("type") if isinstance(node, dict) else None
        if node is not None and (not isinstance(edit_kind, str) or edit_kind not in _KINDS):
            raise WorkflowError("此步骤类型无法在属性面板中编辑。")
        data = node or {}
        self._edit_kind = edit_kind
        kind = edit_kind or "task"
        task = data.get("task", "daily")
        condition = data.get("condition")
        condition = condition if isinstance(condition, dict) else {}
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
            }
            for key, _, minimum, _ in _NUMBERS.values():
                initial[key] = str(data.get(key, minimum))
            for key, raw in initial.items():
                self.values[key].set(raw)
            self.enabled.set(data.get("enabled", True) if node is not None else False)
            self.controls["type"].configure(state="disabled" if node is not None else "readonly")
            self.controls["step"].configure(values=("@last", *self._steps) if self._steps else ())
            self._current_task = task if isinstance(task, str) else None
            self._task_drafts.clear()
            params = data.get("params", {}) if node is not None else _default_params(task)
            self._set_parameters(json.dumps(params, ensure_ascii=False, indent=2))
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
        if kind in ("if", "while"):
            self._condition_frame.grid()

    def _kind_changed(self, *_):
        if self._loading or self._edit_kind is not None:
            return
        self.enabled.set(self._kind() != "task")
        self.error.set("")
        self._show_kind()

    def _set_parameters(self, text):
        self.parameters.delete("1.0", "end")
        self.parameters.insert("1.0", text)
        self.parameters.edit_reset()

    def _task_changed(self, *_):
        if self._loading:
            return
        task = _key(self._tasks, self.values["task"].get())
        if task is None or task == self._current_task:
            return
        if self._current_task is not None:
            self._task_drafts[self._current_task] = self.parameters.get("1.0", "end-1c")
        self._current_task = task
        if self._edit_kind is None:
            self.enabled.set(False)
        text = self._task_drafts.get(task, json.dumps(_default_params(task), ensure_ascii=False, indent=2))
        self._set_parameters(text)
        self.error.set("")

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

    def _read_fields(self):
        kind = self._kind()
        if kind not in _KINDS:
            raise WorkflowError("请选择步骤类型。")
        name = self.values["name"].get()
        fields = dict(type=kind, name=_text(name) if name else None, enabled=self.enabled.get())
        if kind in _NUMBERS:
            key, _, low, high = _NUMBERS[kind]
            fields[key] = _number(self.values[key].get(), low, high)
        if kind in ("if", "while"):
            fields["condition"] = self._read_condition()
        if kind == "task":
            task = _key(self._tasks, self.values["task"].get())
            policy = _key(_FAILURE, self.values["on_failure"].get())
            if task is None or policy is None:
                raise WorkflowError("请选择正式任务和失败策略。")
            raw = self.parameters.get("1.0", "end-1c")
            params = loads(raw) if raw.strip() else {}
            _params(task, params)
            fields.update(task=task, params=params, on_failure=policy)
        return fields

    def apply(self):
        try:
            fields = self._read_fields()
            self.error.set("")
            self.on_apply(fields)
        except ValueError as error:
            self.error.set(str(error))
