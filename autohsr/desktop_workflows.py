"""Task workflow and schedule content inside the settings guide."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import theme as t
from .models import Stopped
from .schedule_dispatch import validate_target
from .schedule_plan import (CHINA, ScheduleError, loads as load_schedule_json, preview as schedule_preview,
                            validate as validate_schedule)
from .storage import hold_read_sources
from .task_workflow import MAX_BYTES, TASKS, WorkflowError, loads as load_workflow_json
from .task_workflow_draft import WorkflowDraft, WorkflowSaveConflict


_JSON_FILES = (("JSON 文件", "*.json"),)
_YAML_FILES = (("三月七 YAML 流程", ("*.yaml", "*.yml")),)
_WORKFLOW_FILES = (*_JSON_FILES, *_YAML_FILES)
_ZIP_FILES = (("任务流素材包", "*.zip"),)
_WORKFLOW_SCOPE = "整棵流程"
_STEP_SCOPE = "指定步骤"
_RUN_STATES = {"success": "已完成", "ok": "已完成", "partial": "部分完成", "stopped": "已停止",
               "failed": "失败", "unknown": "待核对", "skipped": "已跳过"}
_SAVE_ERRORS = {"target_exists": "目标已存在", "source_path": "请选择新文件名",
                "source_changed": "来源已变化", "readback_changed": "另存结果待核对"}
_TASK_NAMES = {"daily": "每日任务", "plan": "日常与到期周常", "differential_universe": "差分宇宙",
               "du_rewards": "差分红点领奖", "warp_analysis": "跃迁记录分析", "warp_export": "跃迁记录导出",
               "currency_wars_loop": "货币战争循环", "currency_wars_points": "货币战争积分",
               "currency_wars_rewards": "货币战争积分领奖", "workflow_audio": "播放本地音频",
               "workflow_image": "从图片查找模板", "workflow_text": "从图片查找文字",
               "workflow_game_image": "从游戏画面查找模板", "workflow_game_text": "从游戏画面查找文字",
               "workflow_open_page": "切换到游戏页面",
               "workflow_notify": "发送主动通知"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)


def _set_enabled(control, enabled):
    control.state(("!disabled" if enabled else "disabled",))


def _report_value(report, key):
    return report.get(key) if isinstance(report, dict) else getattr(report, key, None)


class _Panel(ttk.Frame):
    def __init__(self, parent, ui):
        super().__init__(parent)
        self.ui = ui
        self.columnconfigure(0, weight=1)

    def _size(self, value):
        return round(value * self.ui.ui_scale)

    @property
    def _busy(self):
        return self.ui.busy

    def _changed(self):
        self.refresh()
        self.ui._workflow_action_changed()

    def _hint(self, variable, row):
        label = t.wrapped_label(self, textvariable=variable, style="Hint.TLabel")
        label.grid(row=row, column=0, sticky="ew", pady=(self._size(5), 0))

    def _button(self, parent, label, command, column):
        button = ttk.Button(parent, text=label, command=command, style="Panel.TButton")
        button.grid(row=0, column=column, sticky="w", padx=(0, self._size(7)))
        return button

    def _choose_file(self, title, *, save=False, initialdir=None, filetypes=_JSON_FILES,
                     extension=".json", initialfile=None):
        owner = self.winfo_toplevel()
        focused = self.focus_get()
        options = dict(parent=owner, title=title, filetypes=filetypes)
        if initialdir is not None:
            options["initialdir"] = str(initialdir)
        if save:
            if initialfile is not None:
                options["initialfile"] = initialfile
            result = filedialog.asksaveasfilename(defaultextension=extension, confirmoverwrite=False, **options)
        else:
            result = filedialog.askopenfilename(**options)
        if not result and focused is not None and focused.winfo_exists():
            focused.focus_set()
        return Path(result) if result else None

    def _can_replace_form(self, title, prompt):
        if self._busy:
            return False
        if self.dirty and not messagebox.askyesno(title, prompt, parent=self.winfo_toplevel(), default="no"):
            return False
        return not self._busy

    def _editor(self, parent, *, height):
        holder = ttk.Frame(parent)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        editor = tk.Text(holder, height=height, width=1, wrap="word", undo=True, relief="flat", bd=0,
                         padx=self._size(7), pady=self._size(5), background=t.FIELD,
                         foreground=t.TEXT, insertbackground=t.TEXT, font=t.native_font(self, 11))
        scroll = ttk.Scrollbar(holder, orient="vertical", command=editor.yview)
        editor.configure(yscrollcommand=scroll.set)
        editor.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return holder, editor

    @staticmethod
    def _replace_editor(editor, text):
        editor.configure(state="normal")
        editor.delete("1.0", "end")
        editor.insert("1.0", text)
        editor.edit_reset()
        editor.edit_modified(False)


class _WorkflowPanel(_Panel):
    def __init__(self, parent, ui):
        super().__init__(parent, ui)
        self.draft = None
        self.clean_text = ""
        self.editor_text = ""
        self._saved_target = None
        self._template_revision = 0
        self._template_bindings = {}
        self.loading = False
        self.reviewed_step = None
        self.bundle_job = None
        self.assignment_available = False
        self.assignment_enabled = tk.BooleanVar(self, value=False)
        self.assignment_status = tk.StringVar(self, value="仅单独持续委托步骤可用")
        self.scope = tk.StringVar(self, value=_WORKFLOW_SCOPE)
        self.step_path = tk.StringVar(self)
        self.source = tk.StringVar(self, value="请选择新建草稿或打开任务流")
        self.destination = tk.StringVar(self, value="保存时选择新文件")
        self.status = tk.StringVar(self, value="新建或打开任务流后可编辑和校验。")
        self.source_status = tk.StringVar(self)
        self.budget = tk.StringVar(self)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, self._size(8)))
        self.new_button = self._button(toolbar, "新建草稿", self.new, 0)
        self.open_button = self._button(toolbar, "打开任务流", self.open, 1)
        self.reload_button = self._button(toolbar, "重新加载", self.reload, 2)
        self.validate_button = self._button(toolbar, "校验草稿", self.validate, 3)
        self.run_button = self._button(toolbar, "运行已保存流程", self.run_saved, 4)

        for row, title, variable in ((1, "来源", self.source), (2, "另存位置", self.destination)):
            line = ttk.Frame(self)
            line.columnconfigure(1, weight=1)
            line.grid(row=row, column=0, sticky="ew", pady=(0, self._size(5)))
            ttk.Label(line, text=title, style="Settings.Note.TLabel", width=9).grid(row=0, column=0, sticky="w")
            field = ttk.Entry(line, textvariable=variable, state="readonly", width=1, style="Settings.TEntry")
            field.grid(row=0, column=1, sticky="ew")
            if row == 1:
                self.source_field = field
            if row == 2:
                self.target_button = self._button(line, "选择位置", self.select_destination, 2)

        bundle_line = ttk.Frame(self)
        bundle_line.grid(row=3, column=0, sticky="ew", pady=(0, self._size(5)))
        ttk.Label(bundle_line, text="导入导出", style="Settings.Note.TLabel", width=9).grid(row=0, column=0, sticky="w")
        self.import_bundle_button = self._button(bundle_line, "导入素材包…", self.import_bundle, 1)
        self.export_bundle_button = self._button(bundle_line, "导出素材包…", self.export_bundle, 2)
        self.import_native_yaml_button = self._button(bundle_line, "导入 YAML 图文…", self.import_native_yaml, 3)

        scope_line = ttk.Frame(self)
        scope_line.columnconfigure(3, weight=1)
        scope_line.grid(row=4, column=0, sticky="ew", pady=(0, self._size(5)))
        ttk.Label(scope_line, text="执行范围", style="Settings.Note.TLabel", width=9).grid(row=0, column=0, sticky="w")
        self.scope_field = ttk.Combobox(scope_line, textvariable=self.scope, values=(_WORKFLOW_SCOPE, _STEP_SCOPE),
                                        state="readonly", style="Settings.TCombobox", width=11)
        self.scope_field.grid(row=0, column=1, sticky="w", padx=(0, self._size(8)))
        ttk.Label(scope_line, text="步骤路径（从 0 开始）", style="Settings.Note.TLabel").grid(row=0, column=2, sticky="w")
        self.step_field = ttk.Entry(scope_line, textvariable=self.step_path, style="Settings.TEntry", width=10)
        self.step_field.grid(row=0, column=3, sticky="ew", padx=(self._size(5), 0))

        assignment_line = ttk.Frame(self)
        assignment_line.grid(row=5, column=0, sticky="ew", pady=(0, self._size(5)))
        assignment_line.columnconfigure(1, weight=1)
        self.assignment_toggle = ttk.Checkbutton(assignment_line, text="启用持续委托",
                                                  variable=self.assignment_enabled, command=self._toggle_assignment)
        self.assignment_toggle.grid(row=0, column=0, sticky="w", padx=(0, self._size(8)))
        ttk.Label(assignment_line, textvariable=self.assignment_status, style="Settings.Note.TLabel").grid(
            row=0, column=1, sticky="w")
        self.visual_button = ttk.Button(assignment_line, text="可视编辑…", command=self.edit_tree,
                                        style="Panel.TButton")
        self.visual_button.grid(row=0, column=2, sticky="e", padx=(self._size(8), 0))

        holder, self.editor = self._editor(self, height=11)
        holder.grid(row=6, column=0, sticky="nsew")
        self.rowconfigure(6, weight=1)
        self.editor.bind("<<Modified>>", self._edit)
        self._hint(self.status, 7)
        self._hint(self.budget, 8)
        self._hint(self.source_status, 9)
        self.scope.trace_add("write", self._scope_changed)
        self.step_path.trace_add("write", self._scope_changed)
        self.refresh()

    def _text(self):
        return self.editor.get("1.0", "end-1c")

    @property
    def dirty(self):
        return self.draft is not None and self._text() != self.clean_text

    @property
    def _source_file(self):
        return self.draft.source if self.draft is not None else None

    @property
    def saved_target(self):
        return self._saved_target

    @saved_target.setter
    def saved_target(self, target):
        if target != self._saved_target:
            self._template_revision += 1
        self._saved_target = target

    @property
    def _busy(self):
        return super()._busy or self.bundle_job is not None

    @property
    def _bundle_idle(self):
        return not self._busy and not getattr(self.ui, "closing", False)

    def primary_action(self):
        return "另存为", self.save_as, self.draft is not None and not self._busy

    def focus_entry(self):
        if self._busy:
            self.source_field.focus_set()
        else:
            (self.open_button if self.draft is None else self.editor).focus_set()

    def refresh(self):
        idle = not self._busy
        has_draft = self.draft is not None
        saved = self._source_file is not None
        _set_enabled(self.new_button, idle)
        _set_enabled(self.open_button, idle)
        _set_enabled(self.import_bundle_button, self._bundle_idle)
        _set_enabled(self.import_native_yaml_button, self._bundle_idle)
        _set_enabled(self.export_bundle_button, self._bundle_idle and saved and not self.dirty)
        for button in (self.validate_button, self.target_button, self.visual_button):
            _set_enabled(button, idle and has_draft)
        _set_enabled(self.reload_button, idle and saved)
        _set_enabled(self.scope_field, idle and has_draft)
        _set_enabled(self.step_field, idle and has_draft and self.scope.get() == _STEP_SCOPE)
        _set_enabled(self.assignment_toggle, idle and self.assignment_available)
        self.run_button.configure(text="运行已保存流程" if self.scope.get() == _WORKFLOW_SCOPE else "运行已保存单步")
        _set_enabled(self.run_button, self._can_run_saved())
        self.editor.configure(state="normal" if idle and has_draft else "disabled")

    def _selected_path(self):
        return None if self.scope.get() == _WORKFLOW_SCOPE else self.step_path.get().strip()

    def _can_run_saved(self):
        source = self._source_file
        if self._busy or source is None or self.dirty:
            return False
        path = self._selected_path()
        return path is None or self.reviewed_step == (path, source.parent)

    def _clear_profile(self):
        self.reviewed_step = None
        self.budget.set("")

    def _assignment_document(self, text):
        if self.draft is None:
            return None
        from .task_workflow import compile_recipe

        try:
            document = load_workflow_json(text)
            steps = document.get("steps") if isinstance(document, dict) else None
            if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
                return None
            step = steps[0]
            if (step.get("type") != "task" or step.get("task") != "daily"
                    or step.get("params") != {"tasks": ["assignments"]}):
                return None
            return compile_recipe(document).document
        except WorkflowError:
            return None

    def _sync_assignment(self, text):
        document = self._assignment_document(text)
        self.assignment_available = document is not None
        self.assignment_enabled.set(document is not None and document["steps"][0].get("enabled", True))
        self.assignment_status.set("仅持续委托 · 0 开拓力" if document is not None else "仅单独持续委托步骤可用")

    def _toggle_assignment(self):
        text = self._text()
        if self._busy or self.loading:
            self._sync_assignment(text)
            self.refresh()
            return
        if text != self.editor_text:
            # A queued Text edit must settle before the displayed checkbox can edit it.
            self.editor.edit_modified(True)
            self._edit()
            return
        document = self._assignment_document(text)
        if document is None:
            self._sync_assignment(text)
            self.refresh()
            return
        enabled = self.assignment_enabled.get()
        step = document["steps"][0]
        if enabled != step.get("enabled", True):
            step["enabled"] = enabled
            self._replace_draft_document(document)

    def _replace_draft_document(self, document):
        text = _json(document)
        if len(text.encode("utf8")) > MAX_BYTES:
            text = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        self.editor.edit_separator()
        self.editor.replace("1.0", "end-1c", text)
        self.editor.edit_separator()
        self.editor.edit_modified(True)
        self._edit()

    def _template_base(self):
        from .workflow_bundle import _path as bundle_path

        target = self.saved_target
        try:
            if target is not None:
                if target.suffix.casefold() == ".json":
                    destination = bundle_path(target, new=True)
                    if destination == self.draft.destination_path(target):
                        return destination.parent
            elif self._source_file is not None:
                return bundle_path(self._source_file).parent
        except (ValueError, OSError, RuntimeError):
            pass
        return None

    def edit_tree(self):
        if self._busy or self.ui.closing or self.draft is None:
            return
        from .desktop_workflow_tree import ask_workflow_tree

        draft, text = self.draft, self._text()
        revision = self._template_revision
        captures = {}

        def capture_current():
            try:
                return (getattr(self.ui, "workflow_panel", self) is self and not self.ui.closing and not self._busy
                        and self.draft is draft and self._template_revision == revision and self._text() == text
                        and self._template_base() == base_dir)
            except (WorkflowError, OSError, tk.TclError):
                return False

        try:
            base_dir = self._template_base()
            original = load_workflow_json(text)
            result = ask_workflow_tree(self.ui, original, base_dir=base_dir, task_names=_TASK_NAMES,
                                       capture_current=capture_current, template_bindings=captures)
        except (WorkflowError, OSError) as error:
            panel = getattr(self.ui, "workflow_panel", self)
            panel._error("无法打开可视编辑", error)
            panel._changed()
            return
        panel = getattr(self.ui, "workflow_panel", self)
        if (result is None or self.ui.closing or panel._busy or panel.draft is not draft
                or panel._text() != text or (captures and not capture_current())):
            return
        document, path = result
        panel._template_bindings.update(captures)
        if document != original:
            panel._replace_draft_document(document)
            if path is None and panel.scope.get() == _STEP_SCOPE:
                panel.step_path.set("")
                panel.status.set("草稿已更新 · 请重选单步")
        if path is not None:
            panel.scope.set(_STEP_SCOPE)
            panel.step_path.set(path)
            panel._clear_profile()
            panel.status.set("已选择步骤 · 请重新校验")
        panel._changed()
        panel.visual_button.focus_set()

    def _scope_changed(self, *_):
        if self.loading or self.draft is None:
            return
        self._clear_profile()
        if self.scope.get() == _STEP_SCOPE:
            self.status.set("填写从 0 开始的路径，例如 1/0，然后校验草稿。")
        else:
            self.status.set("执行范围已切回整棵流程 · 可重新校验预算")
        self._changed()

    def _edit(self, _=None):
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        text = self._text()
        if self.loading or self.draft is None or text == self.editor_text:
            return
        self._template_revision += 1
        self.editor_text = text
        self.status.set("草稿有编辑 · 请重新校验" if text != self.clean_text else "内容已恢复 · 可重新校验")
        self._clear_profile()
        self._sync_assignment(text)
        self._changed()

    def _install(self, draft, *, text=None, keep_scope=False):
        self.loading = True
        self._template_revision += 1
        if draft.source is None or draft.source != self._source_file:
            self._template_bindings = {}
        self.draft = draft
        self.clean_text = _json(draft.document) if text is None else text
        if len(self.clean_text.encode("utf8")) > MAX_BYTES:
            self.clean_text = json.dumps(draft.document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        self.editor_text = self.clean_text
        self._replace_editor(self.editor, self.clean_text)
        if not keep_scope:
            self.scope.set(_WORKFLOW_SCOPE)
            self.step_path.set("")
        self.loading = False
        if draft.source is not None:
            self.source.set(str(draft.source))
        elif original := getattr(draft, "original_source", None):
            self.source.set(f"三月七 YAML · {original}")
        else:
            self.source.set("新草稿 · 尚未保存")
        self.saved_target = None
        self.destination.set("保存时选择新文件")
        self.source_status.set("")
        self._clear_profile()
        self._sync_assignment(self.clean_text)

    def new(self):
        if not self._can_replace_form("新建草稿", "当前编辑尚未另存。放弃这些编辑？"):
            return
        self._install(WorkflowDraft.new())
        self.status.set("持续委托默认关闭。勾选后可校验并另存。")
        self._changed()
        self.assignment_toggle.focus_set()

    def _load(self, path):
        if not self._can_replace_form("替换草稿", "当前编辑尚未另存。放弃这些编辑？"):
            return
        try:
            draft = WorkflowDraft.load(path)
        except (WorkflowError, OSError) as error:
            self.status.set(f"打开失败 · {error}")
        else:
            self._install(draft)
            self.status.set("已打开任务流")
            self.editor.focus_set()
        self._changed()

    def _choose_workflow_file(self, title, *, save=False):
        source = self._source_file
        return self._choose_file(title, save=save, initialdir=source.parent if source is not None else None,
                                 filetypes=_JSON_FILES if save else _WORKFLOW_FILES)

    def open(self):
        if self._busy:
            return
        source = self._choose_workflow_file("打开任务流")
        if source is not None:
            if source.suffix.casefold() in (".yaml", ".yml"):
                panel = getattr(self.ui, "workflow_panel", self)
                panel._import_yaml(source)
            else:
                self._load(source)

    def import_native_yaml(self):
        if not self._bundle_idle:
            return
        source = self._choose_file("按 AutoHSR 图文规则导入三月七 YAML", filetypes=_YAML_FILES)
        if source is not None:
            panel = getattr(self.ui, "workflow_panel", self)
            panel._import_yaml(source, use_native_vision=True)

    def _import_yaml(self, source, *, use_native_vision=False):
        if not self._bundle_idle:
            return
        draft, text = self.draft, self._text()
        if not self._can_replace_form("导入三月七 YAML", "当前编辑尚未另存。转换成功后替换当前草稿？"):
            return
        panel = getattr(self.ui, "workflow_panel", self)
        if not panel._bundle_idle or panel.draft is not draft or panel._text() != text:
            return

        def work(checkpoint):
            from .workflow_yaml import load_march7th_yaml

            imported = load_march7th_yaml(source, use_native_vision=use_native_vision)
            checkpoint()
            return imported

        def present(current, imported):
            if current.ui.stop_requested.is_set():
                current.status.set("导入三月七 YAML 已停止")
                return
            if current.draft is not draft or current._text() != text:
                current.status.set("YAML 已转换 · 保留当前草稿")
                return
            current._install(imported)
            current.status.set("已按 AutoHSR 图文规则转换 · 另存 JSON 并校验后可运行" if use_native_vision
                               else "已转换为草稿 · 另存 JSON 并校验后可运行")
            if current.winfo_ismapped():
                current.editor.focus_set()

        panel._start_bundle_job("导入三月七 YAML", work, present)

    def reload(self):
        source = self._source_file
        if not self._busy and source is not None:
            self._load(source)

    def export_bundle(self):
        draft, source = self.draft, self._source_file
        if not self._bundle_idle or source is None or self.dirty:
            return
        target = self._choose_file("导出整个已保存流程的素材包", save=True, initialdir=source.parent,
                                   filetypes=_ZIP_FILES, extension=".zip", initialfile=source.stem + ".zip")
        panel = getattr(self.ui, "workflow_panel", self)
        if target is None or not panel._bundle_idle or panel.draft is not draft or panel.dirty:
            return

        def work(checkpoint):
            from .workflow_bundle import export_bundle

            with hold_read_sources((source,)):
                if not draft.source_is_current():
                    raise WorkflowError("已保存的流程已变化，请重新打开后导出。")
                return export_bundle(source, target, checkpoint=checkpoint)

        def present(current, path):
            current.status.set(f"已导出素材包 · {path}")

        panel._start_bundle_job("导出素材包", work, present)

    def import_bundle(self):
        if not self._bundle_idle:
            return
        source = self._source_file
        bundle = self._choose_file("选择任务流素材包", filetypes=_ZIP_FILES,
                                   initialdir=source.parent if source is not None else None)
        panel = getattr(self.ui, "workflow_panel", self)
        if bundle is None or not panel._bundle_idle:
            return
        target = panel._choose_file("选择导入位置并输入新的目录名", save=True, initialdir=bundle.parent,
                                    filetypes=(("新目录", "*"),), extension="", initialfile=bundle.stem)
        panel = getattr(self.ui, "workflow_panel", self)
        if target is None or not panel._bundle_idle:
            return
        draft, text = panel.draft, panel._text()
        if not panel._can_replace_form("导入素材包", "当前编辑尚未另存。导入成功后替换当前草稿？"):
            return
        panel = getattr(self.ui, "workflow_panel", self)
        if not panel._bundle_idle or panel.draft is not draft or panel._text() != text:
            return

        def work(checkpoint):
            from .workflow_bundle import import_bundle

            path = import_bundle(bundle, target, checkpoint=checkpoint)
            imported = None
            try:
                checkpoint()
                if path.name == "workflow.json" and path.parent.resolve(strict=True) == target.resolve(strict=True):
                    imported = WorkflowDraft.load(path)
            except (Stopped, WorkflowError, OSError):
                pass
            return path, imported

        def present(current, result):
            path, imported = result
            stop = current.ui.stop_requested
            current_source = not stop.is_set() and imported is not None and imported.source_is_current()
            if stop.is_set():
                current.status.set(f"素材包已解包，草稿加载已停止 · {path.parent}")
            elif not current_source:
                current.status.set(f"素材包已解包，草稿待核对 · {path}")
            elif current.draft is not draft or current._text() != text:
                current.status.set(f"素材包已解包，保留当前草稿 · {path}")
            else:
                current._install(imported)
                current.status.set("已导入素材包 · 已打开任务流草稿")
                if current.winfo_ismapped():
                    current.editor.focus_set()

        panel._start_bundle_job("导入素材包", work, present)

    def _start_bundle_job(self, title, work, present):
        if not self._bundle_idle:
            return
        ui = self.ui
        job, previous = object(), self.status.get()
        self.bundle_job = job
        self.status.set(f"正在{title}…")
        self._changed()

        def run(cancel):
            def checkpoint():
                if cancel.is_set():
                    raise Stopped("素材包操作已停止。")

            checkpoint()
            return work(checkpoint)

        def finish(value=None, *, error=None, declined=False):
            panel = getattr(ui, "workflow_panel", self)
            if getattr(ui, "closing", False) or panel.bundle_job is not job:
                return
            panel.bundle_job = None
            if declined:
                panel.status.set(previous)
            elif isinstance(error, Stopped):
                panel.status.set(f"{title}已停止")
            elif error is not None:
                detail = str(error) if isinstance(error, ValueError) else "请检查所选文件、目录及权限。"
                panel.status.set(f"{title}失败 · {detail}")
            else:
                present(panel, value)
            panel._changed()

        try:
            accepted = ui._submit_tool_job(title, run, finish, lambda error: finish(error=error))
        except Exception as error:
            finish(error=error)
            return
        if not accepted:
            finish(declined=True)

    def select_destination(self):
        if self._busy or self.draft is None:
            return
        target = self._choose_workflow_file("选择任务流另存位置", save=True)
        if target is not None and not self._busy:
            self.saved_target = target
            self.destination.set(str(target))
            self.validate()

    def _check_source(self):
        if self._source_file is None:
            return False
        current = self.draft.source_is_current()
        self.source_status.set("" if current else "来源已变化 · 可保留草稿另存，或重新加载。")
        return current

    def _draft_recipe(self, *, destination=None, selected_path=None):
        self.draft.document = load_workflow_json(self._text())
        return self.draft.validate(destination=destination, selected_path=selected_path)

    def _captured_scope(self, recipe):
        if not self._template_bindings:
            return nullcontext()
        from .desktop_workflow_tree import hold_template_bindings

        return hold_template_bindings(self._template_bindings, recipe.steps, recipe.base_dir)

    def _show_profile(self, recipe):
        fields = recipe.profile
        scope = _WORKFLOW_SCOPE
        if recipe.path:
            node = recipe.steps[0]
            path = "/".join(map(str, recipe.path))
            scope = f"步骤 {path} · {node.get('name', node['id'])}"
            if not node.get("enabled", True):
                scope += "（已禁用）"
        self.budget.set(f"{scope}\n最多 {fields['executions']} 步 · 日常预算 {fields['daily_calls']} 份 · "
                        f"差分预留 {fields['du_runs']} 局 · 货币预留 {fields['currency_games']} 局\n"
                        f"相对路径按 {recipe.base_dir} 解析"
                        + (f"\n主动通知最多 {fields['notification_calls']} 个步骤" if 'notification_calls' in fields else ""))

    def _error(self, label, error):
        self._clear_profile()
        cause = error.__cause__
        if isinstance(cause, json.JSONDecodeError):
            index = f"{cause.lineno}.{cause.colno - 1}"
            self.editor.mark_set("insert", index)
            self.editor.see(index)
            self.editor.focus_set()
            self.status.set(f"{label} · 第 {cause.lineno} 行，第 {cause.colno} 列")
        else:
            self.status.set(f"{label} · {error}")

    def validate(self):
        if self._busy or self.draft is None:
            return
        current = self._check_source()
        path = self._selected_path()
        try:
            recipe = self._draft_recipe(destination=self.saved_target, selected_path=path)
            with self._captured_scope(recipe):
                pass
        except (ValueError, OSError) as error:
            self._error("校验失败", error)
        else:
            status = "校验通过" + (" · 草稿有编辑" if self.dirty else "")
            source = self._source_file
            if (path is not None and self.saved_target is not None
                    and (source is None or recipe.base_dir != source.parent)):
                status += " · 另存目录预览 · 另存后请重新校验单步"
            self.status.set(status)
            self.reviewed_step = (path, recipe.base_dir) if current and path is not None else None
            self._show_profile(recipe)
        self._changed()

    def save_as(self):
        if self._busy or self.draft is None:
            return
        target = self.saved_target or self._choose_workflow_file("任务流另存为", save=True)
        if target is None or self._busy:
            return
        self.saved_target = target
        self.destination.set(str(target))
        self._check_source()
        try:
            recipe = self._draft_recipe(destination=target)
            with self._captured_scope(recipe):
                saved = self.draft.save_as(recipe.base_dir / target.name)
                fresh = self._read_saved(saved)
        except WorkflowSaveConflict as error:
            self._error(_SAVE_ERRORS.get(error.reason, "另存失败"), error)
        except (WorkflowError, OSError) as error:
            self._error("另存失败", error)
        else:
            captures = self._template_bindings
            self._install(fresh, text=self._text(), keep_scope=True)
            self._template_bindings = captures
            single = self._selected_path() is not None
            self.status.set(f"已另存 · {saved.path}" + (" · 请重新校验单步" if single else ""))
            if not single:
                self._show_profile(saved.recipe)
        self._changed()

    @staticmethod
    def _read_saved(saved):
        try:
            with hold_read_sources((saved.path,)):
                fresh = WorkflowDraft.load(saved.path)
                with saved.path.open("rb") as stream:
                    digest = sha256(stream.read(MAX_BYTES + 1)).hexdigest()
                if digest != saved.sha256:
                    raise WorkflowError("另存文件已变化。")
        except (WorkflowError, OSError) as error:
            raise WorkflowSaveConflict("readback_changed", "请检查目标文件，当前草稿已保留。") from error
        return fresh

    def run_saved(self):
        if not self._can_run_saved():
            return
        source = self._source_file
        path = self._selected_path()
        try:
            with hold_read_sources((source,)):
                if not self._check_source():
                    self._clear_profile()
                    self.status.set("运行前核验失败 · 请重新加载保存版本")
                else:
                    recipe = WorkflowDraft.load(source).validate(selected_path=path)
                    if path is not None and self.reviewed_step != (path, recipe.base_dir):
                        raise WorkflowError("保存来源目录已变化，请重新打开并校验单步。")
                    self._show_profile(recipe)
                    self.status.set("已提交已保存的单步" if recipe.path else "已提交已保存的任务流")
                    if not self.ui._start_task_workflow(recipe, on_report=self._deliver_report):
                        self.status.set("任务流未启动 · 当前执行权不可用")
        except (ValueError, OSError) as error:
            self._check_source()
            self._error("运行前核验失败", error)
        self._changed()

    def _deliver_report(self, report):
        self.ui.workflow_panel._finished(report)

    def _finished(self, report):
        state = _RUN_STATES.get(_report_value(report, "status"), "待核对")
        error = _report_value(report, "error")
        self.status.set(f"任务流{state}" + (f" · {error}" if error else ""))
        self._changed()

    def snapshot_draft(self):
        scope = self.scope.get(), self.step_path.get(), self.reviewed_step
        return (self.draft, self.clean_text, self.saved_target, self._text(), scope, self.bundle_job, dict(self._template_bindings),
                tuple(variable.get() for variable in self._draft_variables()))

    def restore_draft(self, snapshot):
        self.draft, self.clean_text, self.saved_target, text, scope, self.bundle_job, captures, labels = snapshot
        self._template_revision += 1
        self._template_bindings = dict(captures)
        self.loading = True
        self.editor_text = text
        self._replace_editor(self.editor, text)
        mode, path, self.reviewed_step = scope
        self.scope.set(mode)
        self.step_path.set(path)
        for variable, value in zip(self._draft_variables(), labels):
            variable.set(value)
        self.loading = False
        self._sync_assignment(text)
        self.refresh()

    def _draft_variables(self):
        return self.source, self.destination, self.status, self.source_status, self.budget


def build_workflow_panel(parent, ui):
    return _WorkflowPanel(parent, ui)


_TARGET_TYPES = {"正式任务": "task", "任务流": "workflow"}
_CONFLICTS = {"跳过本次": "skip", "停止定时任务": "stop_owned"}
_BUDGET_FIELDS = (("workflow_steps", "执行步数", "步"), ("daily_stamina_max", "开拓力", "点"),
                  ("du_runs_max", "差分局数", "局"))
_SCHEDULE_REASONS = {"plan_changed": "计划版本已变化", "timeout": "达到超时上限", "controller_stopped": "已停止计时",
                     "receipt_write_failed": "回执写入待核对", "report_unverified": "运行回执待核对",
                     "disabled_before_start": "启动前已停用", "cancelled_before_run": "启动前已停止"}


def _choice(mapping, value):
    return next(label for label, option in mapping.items() if option == value)


def _time_label(value):
    if value:
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is not None:
                return parsed.astimezone(CHINA).strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            pass
    return "待核对"


class _SchedulePanel(_Panel):
    def __init__(self, parent, ui):
        super().__init__(parent, ui)
        self.store = ui.schedule_store
        self.loading = False
        self.saved_id = self.saved_revision = None
        self.preview_stamp = None
        self.runtime = {}
        self.controls = {}
        self.saved_labels = {}
        self.values = {key: tk.StringVar(self) for key in ("id", "name", "time", "target_type", "task",
                       "path", "step_path", "count", "interval", "conflict", "timeout")}
        self.days = tuple(tk.BooleanVar(self, value=True) for _ in range(7))
        self.task_names = {_TASK_NAMES.get(task, task): task for task in sorted(TASKS)}
        self.selected = tk.StringVar(self)
        self.status = tk.StringVar(self)
        self.runtime_status = tk.StringVar(self)
        self.preview_status = tk.StringVar(self)
        self.budget = tk.StringVar(self)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, self._size(6)))
        toolbar.columnconfigure(0, weight=1)
        self.saved_choices = ttk.Combobox(toolbar, textvariable=self.selected, width=1, state="readonly",
                                          style="Settings.TCombobox", postcommand=self._load_choices)
        self.saved_choices.grid(row=0, column=0, sticky="ew", padx=(0, self._size(8)))
        self.open_button = self._button(toolbar, "打开计划", self.open, 1)
        self.new_button = self._button(toolbar, "新建计划", self.new, 2)
        self._hint(self.runtime_status, 1)

        definition = self._group(2, 3)
        self._field(definition, 0, 0, "name", "计划名称")
        self._field(definition, 0, 1, "id", "计划标识")
        self._field(definition, 0, 2, "time", "北京时间 HH:MM")
        days = self._group(3, 1)
        ttk.Label(days, text="星期", style="Settings.Note.TLabel").grid(row=0, column=0, sticky="w")
        self.day_buttons = []
        for index, (caption, variable) in enumerate(zip("一二三四五六日", self.days), 1):
            check = ttk.Checkbutton(days, text=caption, variable=variable)
            check.grid(row=0, column=index, sticky="w", padx=(self._size(5), 0))
            self.day_buttons.append(check)

        target = self._group(4, 3)
        self._field(target, 0, 0, "target_type", "执行目标", choices=tuple(_TARGET_TYPES))
        self.task_fields = ttk.Frame(target)
        self.task_fields.columnconfigure(0, weight=1)
        self.task_fields.grid(row=0, column=1, columnspan=2, sticky="nsew")
        self._field(self.task_fields, 0, 0, "task", "正式任务", choices=tuple(self.task_names))
        self.path_fields = ttk.Frame(target)
        self.path_fields.columnconfigure(0, weight=1)
        self.path_fields.grid(row=0, column=1, columnspan=2, sticky="nsew")
        self._field(self.path_fields, 0, 0, "path", "已保存的任务流")
        picker = ttk.Frame(self.path_fields)
        picker.grid(row=0, column=1, sticky="s")
        self.pick_button = self._button(picker, "选择文件", self.pick_workflow, 0)
        self._field(self.path_fields, 1, 0, "step_path", "步骤路径（可留空）")
        ttk.Label(self.task_fields, text="任务参数 JSON", style="Settings.Note.TLabel").grid(row=1, column=0, sticky="w")
        box, self.params = self._editor(self.task_fields, height=3)
        box.grid(row=2, column=0, sticky="nsew")
        self.params.bind("<<Modified>>", self._params_edited)

        repeat = self._group(5, 4)
        self._field(repeat, 0, 0, "count", "单次触发重复次数")
        self._field(repeat, 0, 1, "interval", "重复间隔（秒）")
        self._field(repeat, 0, 2, "timeout", "超时（秒，0 不限）")
        self._field(repeat, 0, 3, "conflict", "任务冲突", choices=tuple(_CONFLICTS))
        t.wrapped_label(repeat, text="冲突时仅可停止本调度器拥有的任务。", style="Settings.Note.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(self._size(3), 0))

        actions = self._group(6, 1)
        self.preview_button = self._button(actions, "预览预算", self.preview, 0)
        self.disable_button = self._button(actions, "停用计划", self.disable, 1)
        self.stop_button = self._button(actions, "停止定时", self.stop, 2)
        self._hint(self.status, 7)
        self._hint(self.preview_status, 8)
        self._hint(self.budget, 9)

        for variable in (*self.values.values(), *self.days):
            variable.trace_add("write", self._edit)
        self.selected.trace_add("write", lambda *_: self.refresh() if not self.loading else None)
        self._apply(None)
        self._load_choices()
        self.refresh()

    def _group(self, row, columns):
        group = ttk.Frame(self)
        group.grid(row=row, column=0, sticky="ew", pady=(self._size(5), 0))
        for column in range(columns):
            group.columnconfigure(column, weight=1)
        return group

    def _field(self, parent, row, column, key, label, *, choices=()):
        group = ttk.Frame(parent)
        group.columnconfigure(0, weight=1)
        group.grid(row=row, column=column, sticky="ew", padx=(0, self._size(7)))
        ttk.Label(group, text=label, style="Settings.Note.TLabel").grid(row=0, column=0, sticky="w")
        values = dict(textvariable=self.values[key], width=1)
        control = (ttk.Combobox(group, values=choices, state="readonly", style="Settings.TCombobox", **values) if choices
                   else ttk.Entry(group, style="Settings.TEntry", **values))
        control.grid(row=1, column=0, sticky="ew")
        self.controls[key] = control

    def _form_key(self):
        return (tuple(variable.get() for variable in self.values.values()),
                tuple(day.get() for day in self.days), self.params.get("1.0", "end-1c"))

    @property
    def dirty(self):
        return self._form_key() != self.baseline

    def _apply(self, plan, saved_revision=None):
        self.loading = True
        self.saved_id = plan["id"] if plan else None
        self.saved_revision = saved_revision
        values = plan or dict(id="", name="", time="", weekdays=list(range(1, 8)),
                              target=dict(type="task", task="daily", params={}),
                              repeat=dict(count=1, interval_seconds=0), conflict="skip", timeout_seconds=0)
        target = values["target"]
        fields = {key: values[key] for key in ("name", "id", "time")}
        fields.update(target_type=_choice(_TARGET_TYPES, target["type"]),
                      task=_choice(self.task_names, target.get("task", "daily")), path=target.get("path", ""),
                      step_path=target.get("step_path", ""), count=values["repeat"]["count"],
                      interval=values["repeat"]["interval_seconds"], timeout=values["timeout_seconds"],
                      conflict=_choice(_CONFLICTS, values["conflict"]))
        for key, value in fields.items():
            self.values[key].set(str(value))
        for index, variable in enumerate(self.days, 1):
            variable.set(index in values["weekdays"])
        self.params_text = _json(target.get("params", {}))
        self._replace_editor(self.params, self.params_text)
        self.baseline = self._form_key()
        self.loading = False
        self._show_target()

    def _show_target(self):
        is_task = self.values["target_type"].get() == "正式任务"
        shown, hidden = (self.task_fields, self.path_fields) if is_task else (self.path_fields, self.task_fields)
        hidden.grid_remove()
        shown.grid()

    def _params_edited(self, _=None):
        if not self.params.edit_modified():
            return
        self.params.edit_modified(False)
        text = self.params.get("1.0", "end-1c")
        if text != self.params_text:
            self.params_text = text
            self._edit()

    def _edit(self, *_):
        if self.loading:
            return
        self._show_target()
        self.status.set("计划有编辑" if self.dirty else "")
        self._forget_preview("表单已变化 · 请重新预览预算")
        self._changed()

    def _forget_preview(self, message=""):
        self.preview_stamp = None
        self.preview_status.set(message)
        self.budget.set("")

    def _load_choices(self, *, select_saved=False):
        try:
            items = self.store.list_public()
        except (ScheduleError, OSError) as error:
            self.status.set(f"计划列表待核对 · {error}")
            return
        self.saved_labels = {f"{row.get('name', '待核对')} · {row['id']}": row["id"] for row in items}
        self.saved_choices.configure(values=tuple(self.saved_labels))
        if select_saved or self.selected.get() not in self.saved_labels:
            label = next((label for label, key in self.saved_labels.items() if key == self.saved_id), "")
            self.selected.set(label)

    def new(self):
        if not self._can_replace_form("新建计划", "当前编辑尚未保存。放弃这些编辑？"):
            return
        self._apply(None)
        self.selected.set("")
        self._forget_preview()
        self.status.set("新计划尚未保存")
        self._changed()
        self.controls["name"].focus_set()

    def open(self):
        identifier = self.saved_labels.get(self.selected.get())
        if not identifier or not self._can_replace_form("打开计划", "当前编辑尚未保存。放弃这些编辑？"):
            return
        try:
            plan, revision = self.store.load(identifier)
            validate_target(plan["target"])
        except (ScheduleError, OSError) as error:
            self._error("打开计划失败", error)
        else:
            self._apply(plan, revision)
            self._forget_preview("已打开计划 · 可预览预算")
            self.status.set("已打开保存版本")
            self.controls["name"].focus_set()
        self._changed()

    def pick_workflow(self):
        if self._busy:
            return
        path = self._choose_file("选择已保存的任务流")
        if path is not None and not self._busy:
            self.values["path"].set(str(path))

    def _integer(self, key, label):
        try:
            return int(self.values[key].get())
        except ValueError:
            raise ScheduleError(f"{label}须为整数。", key) from None

    def _plan(self):
        values = {key: variable.get() for key, variable in self.values.items()}
        target_type = _TARGET_TYPES.get(values["target_type"])
        if target_type not in ("task", "workflow"):
            raise ScheduleError("请选择执行目标。", "target_type")
        if target_type == "task":
            task = self.task_names.get(values["task"])
            if task is None:
                raise ScheduleError("请选择正式任务。", "task")
            try:
                params = load_schedule_json(self.params.get("1.0", "end-1c"))
            except ScheduleError as error:
                raise ScheduleError(str(error), "params") from error
            target = dict(type="task", task=task, params=params)
        else:
            target = dict(type="workflow", path=values["path"])
            if values["step_path"]:
                target["step_path"] = values["step_path"]
        conflict = _CONFLICTS.get(values["conflict"])
        if conflict is None:
            raise ScheduleError("请选择任务冲突处理方式。", "conflict")
        plan = validate_schedule(dict(version=1, id=values["id"], name=values["name"], time=values["time"],
            weekdays=[index for index, day in enumerate(self.days, 1) if day.get()], target=target,
            repeat=dict(count=self._integer("count", "重复次数"), interval_seconds=self._integer("interval", "重复间隔")),
            conflict=conflict, timeout_seconds=self._integer("timeout", "超时")))
        validate_target(plan["target"])
        return plan

    def _error(self, label, error):
        self.status.set(f"{label} · {error}")
        key = getattr(error, "field", None)
        key = {"repeat.count": "count", "repeat.interval_seconds": "interval", "timeout_seconds": "timeout",
               "target": "target_type"}.get(key, key)
        control = self.controls.get(key)
        if key == "weekdays":
            control = self.day_buttons[0]
        if control is not None and not control.instate(("disabled",)):
            control.focus_set()
        if key == "params" and not self._busy:
            self.params.focus_set()

    def preview(self):
        if self._busy:
            return
        try:
            plan = self._plan()
            settings_key = self.ui._schedule_settings_key()
            result = self.ui._schedule_preview_budget(plan)
            now = getattr(self.ui, "_schedule_now", lambda: datetime.now(CHINA))()
            calendar = schedule_preview(plan, now, count=5)
            if (not isinstance(result, dict) or result.get("id") != calendar["id"]
                    or result.get("revision") != calendar["revision"]):
                raise ScheduleError("预算与当前计划版本不符，请重新预览。")
            maximum = result.get("whole_batch")
            if not isinstance(maximum, dict):
                maximum = {}
            fields = []
            complete = True
            for key, label, unit in _BUDGET_FIELDS:
                value = maximum.get(key)
                if type(value) is not int or value < 0:
                    complete = False
                    fields.append(f"{label} 待核对")
                else:
                    fields.append(f"{label} {value} {unit}")
            times = calendar["next_times"]
            status = f"预算预览 · 下一个计划点 {_time_label(times[0])}（北京时间）"
            if complete:
                dates = " · ".join(datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M") for value in times)
                status += f"\n未来五次计划点（北京时间）\n{dates}"
        except (OSError, ValueError, TypeError) as error:
            self._forget_preview()
            self._error("预算预览失败", error)
        else:
            self.budget.set("单次触发整批上限 · " + " · ".join(fields))
            self.preview_status.set(status)
            self.preview_stamp = (result["revision"], settings_key) if complete else None
            self.status.set("" if complete else "预算字段待核对")
        self._changed()

    def save(self):
        if self._busy:
            return
        try:
            plan = self._plan()
            outcome = self.store.save(plan, replace=self.saved_revision is not None,
                                      expected_revision=self.saved_revision)
        except (ScheduleError, OSError) as error:
            self._error("保存计划失败", error)
        else:
            self._apply(outcome["plan"], outcome["revision"])
            if self.preview_stamp and self.preview_stamp[0] != self.saved_revision:
                self._forget_preview("已保存新版本 · 请重新预览预算")
            self._load_choices(select_saved=True)
            self.status.set("已保存计划")
        self._changed()

    def _enabled_plan(self):
        return next((item for item in self.runtime.get("plans", ()) if item["id"] == self.saved_id), None)

    def _fresh_preview(self):
        return (self.preview_stamp is not None and self.preview_stamp[0] == self.saved_revision
                and self.preview_stamp[1] == self.ui._schedule_settings_key())

    def _may_enable(self):
        enabled = self._enabled_plan()
        running = self.runtime.get("running") and enabled and enabled.get("revision") == self.saved_revision
        return not self._busy and self.saved_revision is not None and not self.dirty and self._fresh_preview() and not running

    def enable(self):
        if not self._may_enable():
            return
        try:
            _, revision = self.store.load(self.saved_id)
            if revision != self.saved_revision:
                raise ScheduleError("保存版本已变化，请重新打开计划。")
            result = self.ui._schedule_enable(self.saved_id, self.saved_revision)
            self.status.set("启用请求未提交" if result is False else "已提交启用请求")
        except (ScheduleError, OSError) as error:
            self._forget_preview("请重新预览预算")
            self._error("启用计划失败", error)
        self._changed()

    def disable(self):
        if self._busy or not self._enabled_plan():
            return
        try:
            self.ui._schedule_disable(self.saved_id)
        except (ScheduleError, OSError) as error:
            self._error("停用计划失败", error)
        else:
            self.status.set("已请求停用计划")
        self._changed()

    def _may_stop(self):
        return not self.runtime.get("stopping") and bool(
            self.runtime.get("running") or self.runtime.get("active") or self.runtime.get("pending"))

    def stop(self):
        if not self._may_stop():
            return
        try:
            self.ui._schedule_stop()
        except (ScheduleError, OSError) as error:
            self._error("停止定时失败", error)
        else:
            self.status.set("已请求停止定时")
        self._changed()

    def _runtime_status(self):
        active, pending = self.runtime.get("active"), self.runtime.get("pending")
        enabled = self._enabled_plan()
        if self.saved_id is None:
            status = "新计划 · 尚未保存"
        elif active and active["id"] == self.saved_id:
            phase = "正在停止" if active.get("stopping") else "已暂停" if self.runtime.get("paused") else "执行中"
            if active.get("revision") != self.saved_revision:
                phase += "（旧版本）"
            status = f"{phase} · {active.get('completed', 0)} / {active.get('requested', 1)} 次"
        elif pending and pending["id"] == self.saved_id:
            status = "等待执行 · 已到计划点"
        elif not enabled:
            status = "已保存 · 未启用"
        elif enabled.get("revision") != self.saved_revision:
            status = "已保存新版本 · 需要重新启用"
        elif self.runtime.get("paused"):
            status = "已启用 · 计时暂停"
        elif self.runtime.get("running"):
            status = f"已启用 · 等待触发 · {_time_label(enabled.get('next_due'))}（北京时间）"
        else:
            status = "已启用 · 计时已停止"
        last = self.runtime.get("last")
        if self.saved_id is not None and last and last["id"] == self.saved_id:
            label = "最近触发" if last.get("revision") == self.saved_revision else "旧版本最近触发"
            result = _RUN_STATES.get(last.get("status"), "待核对")
            reason = _SCHEDULE_REASONS.get(last.get("reason"), "")
            status += f"\n{label} · {result}" + (f" · {reason}" if reason else "")
        return status

    def primary_action(self):
        if self.saved_revision is None or self.dirty:
            return "保存计划", self.save, not self._busy
        return "启用计划", self.enable, self._may_enable()

    def focus_entry(self):
        if not self._busy:
            self.controls["name"].focus_set()
        elif self._may_stop():
            self.stop_button.focus_set()

    def refresh(self):
        self.runtime = self.ui._schedule_snapshot() or {}
        idle = not self._busy
        for key, control in self.controls.items():
            _set_enabled(control, idle)
            if key == "id":
                control.state(("readonly" if self.saved_id is not None else "!readonly",))
        for control in (*self.day_buttons, self.saved_choices, self.new_button, self.pick_button, self.preview_button):
            _set_enabled(control, idle)
        _set_enabled(self.open_button, idle and self.selected.get() in self.saved_labels)
        _set_enabled(self.disable_button, idle and self._enabled_plan() is not None)
        _set_enabled(self.stop_button, self._may_stop())
        self.params.configure(state="normal" if idle else "disabled")
        if self.preview_stamp and self.preview_stamp[1] != self.ui._schedule_settings_key():
            self._forget_preview("设置已变化 · 请重新预览预算")
        self.runtime_status.set(self._runtime_status())

    def snapshot_draft(self):
        return dict(form=self._form_key(), baseline=self.baseline, saved_id=self.saved_id,
                    saved_revision=self.saved_revision, selection=self.selected.get(), labels=dict(self.saved_labels),
                    preview=self.preview_stamp, messages=tuple(variable.get() for variable in self._draft_variables()))

    def restore_draft(self, snapshot):
        self.loading = True
        self.saved_id = snapshot["saved_id"]
        self.saved_revision = snapshot["saved_revision"]
        self.baseline = snapshot["baseline"]
        self.preview_stamp = snapshot["preview"]
        values, weekdays, params = snapshot["form"]
        for variable, value in zip(self.values.values(), values):
            variable.set(value)
        for variable, value in zip(self.days, weekdays):
            variable.set(value)
        self.params_text = params
        self._replace_editor(self.params, params)
        self.saved_labels = dict(snapshot["labels"])
        self.saved_choices.configure(values=tuple(self.saved_labels))
        self.selected.set(snapshot["selection"])
        for variable, value in zip(self._draft_variables(), snapshot["messages"]):
            variable.set(value)
        self.loading = False
        self._show_target()
        self.refresh()

    def _draft_variables(self):
        return self.status, self.preview_status, self.budget


def build_schedule_panel(parent, ui):
    return _SchedulePanel(parent, ui)
