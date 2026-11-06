"""Edit a private copy of the formal workflow tree in the desktop guide."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from . import theme
from .desktop_dialogs import place_dialog
from .desktop_workflow_node import WorkflowNodeForm
from .screenshot_tool import MAX_BYTES as MAX_IMAGE_BYTES
from .storage import file_revision, hold_read_sources
from .task_workflow import TEMPLATE_TASKS, WorkflowError, execution_task
from .workflow_bundle import _path as _asset_path
from .workflow_tree_edit import WorkflowTreeDraft


_ROOT = 'flow'
_TYPES = {'task': '正式任务', 'wait': '等待', 'if': '条件', 'for': '固定循环',
          'while': '条件循环', 'break': '跳出循环', 'continue': '继续循环', 'stop': '停止流程'}


@dataclass(frozen=True)
class _TemplateBinding:
    base_dir: Path
    path: Path
    relative_path: str
    sha256: str
    revision: tuple

    @classmethod
    def accept(cls, base_dir, capture):
        try:
            relative = Path(capture.relative_path)
            path = Path(capture.path)
            digest = capture.sha256
            if (not path.is_absolute() or not path.is_relative_to(base_dir)
                    or relative.anchor or '..' in relative.parts or relative.suffix.lower() != '.png'
                    or not isinstance(digest, str) or len(digest) != 64):
                raise ValueError
            path = _asset_path(path)
            if path != base_dir / relative:
                raise ValueError
            revision = file_revision(path)
        except (AttributeError, OSError, TypeError, ValueError, RuntimeError):
            raise WorkflowError('采集模板未能绑定到当前流程目录。') from None
        binding = cls(base_dir, path, relative.as_posix(), digest, revision)
        with _hold_templates((binding,), base_dir):
            return binding

    def verify(self):
        if _asset_path(self.base_dir / self.relative_path) != self.path or file_revision(self.path) != self.revision:
            raise OSError
        with self.path.open('rb') as stream:
            raw = stream.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES or sha256(raw).hexdigest() != self.sha256:
            raise OSError


def _referenced_templates(nodes, bindings):
    for node in nodes:
        task = execution_task(node)
        if task is not None and task['task'] in TEMPLATE_TASKS:
            relative = task['params']['template']
            binding = bindings.get((node['id'], Path(relative)))
            if binding is not None:
                yield binding
        yield from _referenced_templates(node.get('steps', ()), bindings)
        yield from _referenced_templates(node.get('else_steps', ()), bindings)


@contextmanager
def _hold_templates(selected, base_dir):
    if any(binding.base_dir != base_dir for binding in selected):
        raise WorkflowError('采集模板绑定到原目录。请选回原目录，或在当前另存目录重新采集。')
    with ExitStack() as locks:
        if selected:
            try:
                locks.enter_context(hold_read_sources(binding.path for binding in selected))
                for binding in selected:
                    binding.verify()
            except (OSError, RuntimeError, ValueError):
                raise WorkflowError('已采集模板已变化或无法回读，请重新采集或手动选择模板。') from None
        yield


def hold_template_bindings(bindings, nodes, base_dir):
    return _hold_templates(tuple(_referenced_templates(nodes, bindings)), base_dir)


def _ask_template(ui, owner, *, base_dir, capture_current):
    from .desktop_workflow_template import ask_workflow_template

    return ask_workflow_template(ui, owner, base_dir=base_dir, capture_current=capture_current)


def _node_key(identity):
    return f'node:{identity}'


def _branch_key(identity, branch):
    return f'branch:{identity}:{branch}'


class WorkflowTreeDialog(tk.Toplevel):
    def __init__(self, ui, document, *, base_dir, task_names, capture_current=None):
        draft = WorkflowTreeDraft(document)
        base_dir = None if base_dir is None else Path(base_dir).resolve(strict=True)
        super().__init__(ui.root)
        self.withdraw()
        self.transient(ui.root)
        self.title('AutoHSR · 可视编辑任务流')
        self.ui, self.draft = ui, draft
        self.base_dir = base_dir
        self.capture_current = capture_current or (lambda: True)
        self.template_bindings = {}
        self._capture_selection = None
        self._selection_version = 0
        self.task_names = task_names
        self.result = None
        self.editing = None
        self.rows, self.branches = {}, {}
        self.name = tk.StringVar(self, value=draft.name)
        self.feedback = tk.StringVar(self)
        scale = ui.ui_scale
        pad = max(4, round(8 * scale))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        page = ttk.Frame(self, padding=pad, style='Card.TFrame')
        page.grid(row=0, column=0, sticky='nsew')
        page.columnconfigure(1, weight=1)
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text='可视编辑任务流', style='CardTitle.TLabel').grid(row=0, columnspan=2, sticky='w')
        ttk.Label(page, text='流程名称', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=pad)
        ttk.Entry(page, textvariable=self.name, style='Settings.TEntry').grid(row=1, column=1, sticky='ew', pady=pad)

        content = ttk.Frame(page, style='Card.TFrame')
        content.grid(row=2, columnspan=2, sticky='nsew')
        content.columnconfigure(0, weight=3, uniform='workflow')
        content.columnconfigure(1, weight=2, uniform='workflow')
        content.rowconfigure(0, weight=1)
        pane = ttk.Frame(content, style='Card.TFrame')
        pane.grid(row=0, column=0, sticky='nsew', padx=(0, pad))
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(pane, columns=('path',), selectmode='browse', height=7)
        self.tree.heading('#0', text='步骤与分支')
        self.tree.heading('path', text='路径')
        self.tree.column('#0', width=round(240 * scale), minwidth=round(88 * scale))
        self.tree.column('path', width=round(68 * scale), minwidth=round(48 * scale), stretch=False)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(pane, orient='vertical', command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        across = ttk.Scrollbar(pane, orient='horizontal', command=self.tree.xview)
        across.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        self.tree.bind('<<TreeviewSelect>>', self._refresh)
        self.tree.bind('<Double-1>', self._double_click)

        details = ttk.Frame(content, style='Card.TFrame')
        details.grid(row=0, column=1, sticky='nsew')
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        self.hint = theme.wrapped_label(details, style='CardHint.TLabel', text=(
            '选中步骤可编辑、移动或添加同级步骤。选中流程根或分支可在其中添加步骤。'
        ))
        self.hint.grid(row=0, column=0, sticky='new')

        self._property_view = ttk.Frame(details, style='Card.TFrame')
        self._property_view.columnconfigure(0, weight=1)
        self._property_view.rowconfigure(0, weight=1)
        self._property_view.grid(row=0, column=0, sticky='nsew')
        canvas = self._property_canvas = tk.Canvas(self._property_view, width=1, height=1, takefocus=False,
                                                   background=theme.CARD, highlightthickness=0, borderwidth=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self._property_view, orient='vertical', command=canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=scroll.set)
        self.form = WorkflowNodeForm(canvas, scale=scale, task_names=task_names,
                                     on_apply=self._store_node, on_cancel=self._close_form,
                                     on_capture_template=self._capture_template if self.base_dir is not None else None)
        window = canvas.create_window(0, 0, window=self.form, anchor='nw')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        self.form.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox(window)))
        self.bind('<MouseWheel>', self._scroll_properties)
        self.bind('<FocusIn>', self._reveal_property)
        for control in (*self.form.controls.values(), self.form.value_choice, self.form.page_picker):
            if isinstance(control, ttk.Combobox):
                control.bind('<MouseWheel>', self._scroll_properties)
        self._property_view.grid_remove()

        actions = ttk.Frame(page, style='Card.TFrame')
        actions.grid(row=3, columnspan=2, sticky='ew', pady=(pad, 0))
        definitions = (('添加步骤', self._add), ('编辑', self._edit), ('上移', lambda: self._move(-1)),
                       ('下移', lambda: self._move(1)), ('移除', self._remove))
        self.actions = []
        for text, command in definitions:
            button = ttk.Button(actions, text=text, command=command, style='Compact.TButton')
            button.pack(side='left', padx=(0, pad // 2))
            self.actions.append(button)
        theme.wrapped_label(page, textvariable=self.feedback, style='Warning.TLabel').grid(
            row=4, columnspan=2, sticky='ew', pady=(pad, 0))

        footer = ttk.Frame(self, padding=pad, style='Footer.TFrame')
        footer.grid(row=1, column=0, sticky='ew')
        ttk.Button(footer, text='取消', command=self.destroy, style='Footer.TButton').pack(side='left')
        self.select_button = ttk.Button(footer, text='应用并选中步骤', command=lambda: self._finish(True),
                                        style='Footer.TButton')
        self.select_button.pack(side='right', padx=(pad, 0))
        self.apply_button = ttk.Button(footer, text='应用到草稿', command=self._finish, style='Primary.TButton')
        self.apply_button.pack(side='right')
        self.bind('<Escape>', self._escape)
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self._rebuild()
        place_dialog(self, ui.root, (round(860 * scale), round(610 * scale)),
                     (round(630 * scale), round(490 * scale)))

    def _escape(self, _event):
        if self.editing is None:
            self.destroy()
        else:
            self._close_form()
        return 'break'

    def _selection(self):
        return next(iter(self.tree.selection()), _ROOT)

    def _node_title(self, node):
        label = self.task_names.get(node.get('task'), _TYPES[node['type']])
        name = node.get('name', label)
        return name if node.get('enabled', True) else f'{name}（已禁用）'

    def _rebuild(self, select=None):
        selected = select or self._selection()
        keys = (_ROOT, *self.rows, *self.branches)
        collapsed = {key for key in keys if self.tree.exists(key) and not self.tree.item(key, 'open')}
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.branches.clear()
        self.tree.insert('', 'end', _ROOT, text='流程根步骤', open=_ROOT not in collapsed)
        for row in self.draft.rows():
            key = _node_key(row.identity)
            parent = _ROOT if row.parent_id is None else _branch_key(row.parent_id, row.branch)
            self.rows[key] = row
            self.tree.insert(parent, 'end', key, text=self._node_title(row.node),
                             values=('/'.join(map(str, row.path)),), open=key not in collapsed)
            kind = row.node['type']
            groups = {'if': ('条件成立', '否则'), 'for': ('循环体',), 'while': ('循环体',)}.get(kind, ())
            for branch, label in zip(('steps', 'else_steps'), groups):
                branch_key = _branch_key(row.identity, branch)
                self.branches[branch_key] = row, branch
                self.tree.insert(key, 'end', branch_key, text=label, open=branch_key not in collapsed)
        if not self.tree.exists(selected):
            selected = _ROOT
        self.tree.selection_set(selected)
        self.tree.focus(selected)
        self.tree.see(selected)
        self._refresh()

    def _refresh(self, _event=None):
        key = self._selection()
        if key != self._capture_selection:
            self._capture_selection = key
            self._selection_version += 1
        row = self.rows.get(key)
        idle = self.editing is None and not self.ui.busy and not self.ui.closing
        selectable = row is not None and row.node['type'] not in ('break', 'continue')
        node_selected = row is not None
        for button, enabled in zip(self.actions, (True, node_selected, node_selected and bool(self.tree.prev(key)),
                                                  node_selected and bool(self.tree.next(key)), node_selected)):
            button.state(('!disabled' if idle and enabled else 'disabled',))
        self.apply_button.state(('!disabled' if idle else 'disabled',))
        self.select_button.state(('!disabled' if idle and selectable else 'disabled',))

    def _previous_ids(self, path):
        return tuple(row.identity for row in self.rows.values()
                     if row.path < path and path[:len(row.path)] != row.path)

    def _scroll_properties(self, event):
        if (event.delta and not isinstance(event.widget, tk.Text)
                and str(event.widget).startswith(f'{self._property_view}.')):
            self._property_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
            return 'break'

    def _reveal_property(self, event):
        widget = event.widget
        if (not isinstance(widget, tk.Widget) or not str(widget).startswith(f'{self.form}.')
                or str(widget) != str(self.tk.call('focus'))
                or not widget.winfo_ismapped()):
            return
        canvas = self._property_canvas
        extent = self.form.winfo_height()
        height = canvas.winfo_height()
        if extent <= height:
            return
        offset = canvas.canvasy(0)
        top = widget.winfo_rooty() - self.form.winfo_rooty()
        bottom = top + widget.winfo_height()
        if top < offset:
            canvas.yview_moveto(top / extent)
        elif bottom > offset + height:
            canvas.yview_moveto((bottom - height) / extent)

    def _open_form(self, location, path, node=None):
        if self.editing is not None or self.ui.busy or self.ui.closing:
            return
        self.editing = location
        self.hint.grid_remove()
        self._property_view.grid()
        self._property_canvas.yview_moveto(0)
        self.form.open(node, step_ids=self._previous_ids(path))
        self.feedback.set('')
        self._refresh()

    def _add(self):
        key = self._selection()
        row = self.rows.get(key)
        if row is not None:
            parent, branch, after = row.parent_id, row.branch, row.identity
            path = (*row.path[:-1], row.path[-1] + 1)
        elif key in self.branches:
            row, branch = self.branches[key]
            parent, after = row.identity, None
            offset = len(row.node['steps']) if branch == 'else_steps' else 0
            path = (*row.path, offset + len(row.node.get(branch, ())))
        else:
            parent, branch, after = None, 'steps', None
            path = (len(self.tree.get_children(_ROOT)),)
        self._open_form((None, parent, branch, after), path)

    def _edit(self):
        row = self.rows.get(self._selection())
        if row is not None:
            self._open_form((row.identity, None, None, None), row.path, row.node)

    def _double_click(self, event):
        if self.tree.identify_region(event.x, event.y) in ('tree', 'cell'):
            self._edit()

    def _can_capture_template(self, *, require_focus=True):
        try:
            if (not self.winfo_exists() or self.ui.busy or self.ui.closing or self.editing is None
                    or self.base_dir is None or not self.capture_current()):
                return False
            if require_focus and self.winfo_viewable():
                focus = theme.focus_widget(self)
                return focus is not None and focus.winfo_toplevel() is self
            return True
        except tk.TclError:
            return False

    def _capture_template(self):
        if not self._can_capture_template():
            return None
        selection = (self._selection(), self._selection_version)
        editing, base_dir = self.editing, self.base_dir

        def capture_current(*, require_focus=False):
            return (self._can_capture_template(require_focus=require_focus) and self.editing is editing
                    and self.base_dir == base_dir and (self._selection(), self._selection_version) == selection)

        capture = _ask_template(self.ui, self, base_dir=base_dir, capture_current=capture_current)
        if capture is None or not capture_current(require_focus=True):
            return None
        return _TemplateBinding.accept(base_dir, capture)

    def _store_node(self, fields):
        if self.editing is None or self.ui.busy or self.ui.closing:
            return
        identity, parent, branch, after = self.editing
        try:
            if identity is None:
                identity = self.draft.add(fields, parent_id=parent, branch=branch, after=after)
            else:
                self.draft.update(identity, fields)
        except WorkflowError as error:
            self.feedback.set(str(error))
            return
        binding = self.form.template_binding(fields)
        if binding is not None:
            self.template_bindings[identity, Path(binding.relative_path)] = binding
        self._close_form()
        self._rebuild(_node_key(identity))

    def _close_form(self):
        self.editing = None
        self._property_view.grid_remove()
        self.hint.grid()
        self.feedback.set('')
        self.tree.focus_set()
        self._refresh()

    def _move(self, delta):
        row = self.rows.get(self._selection())
        if row is not None and self.editing is None and not self.ui.busy and not self.ui.closing:
            if self.draft.move(row.identity, delta):
                self.feedback.set('')
                self._rebuild()

    def _remove(self):
        row = self.rows.get(self._selection())
        if row is None or self.editing is not None or self.ui.busy or self.ui.closing:
            return
        if 'steps' in row.node and not messagebox.askyesno(
                '移除控制步骤', '从草稿中移除此步骤及其子步骤？', parent=self, default='no'):
            return
        if self.ui.busy or self.ui.closing:
            return
        self.draft.remove(row.identity)
        target = _ROOT if row.parent_id is None else _branch_key(row.parent_id, row.branch)
        self.feedback.set('')
        self._rebuild(target)

    def _finish(self, select_step=False):
        if self.editing is not None or self.ui.busy or self.ui.closing:
            return
        row = self.rows.get(self._selection()) if select_step else None
        if select_step and (row is None or row.node['type'] in ('break', 'continue')):
            return
        try:
            self.draft.name = self.name.get()
            recipe = self.draft.validate(base_dir=self.base_dir)
            if self.template_bindings:
                if not self.capture_current():
                    raise WorkflowError('流程草稿或另存目录已变化，请重新打开可视编辑。')
                with hold_template_bindings(self.template_bindings, recipe.steps, recipe.base_dir):
                    pass
        except WorkflowError as error:
            self.feedback.set(f'请修正草稿 · {error}')
            return
        path = '/'.join(map(str, row.path)) if row is not None else None
        self.result = recipe.document, path
        self.destroy()


def ask_workflow_tree(ui, document, *, base_dir=None, task_names, capture_current=None, template_bindings=None):
    if ui.root.tk.call('grab', 'current', str(ui.root)):
        return None
    dialog = WorkflowTreeDialog(ui, document, base_dir=base_dir, task_names=task_names, capture_current=capture_current)
    dialog.deiconify()
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.tree.focus_set()
    ui.root.wait_window(dialog)
    if dialog.result is not None and template_bindings is not None:
        template_bindings.update(dialog.template_bindings)
    return dialog.result
