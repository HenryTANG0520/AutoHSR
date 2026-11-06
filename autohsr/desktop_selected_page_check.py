"""Selection, preview and anonymous rows for a desktop page-check sequence."""

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

from . import theme
from .task_workflow import ACTIVITY_WORKFLOW_PAGES, WORKFLOW_PAGES, Recipe, WorkflowError


MODE = 'selected_pages'
_PAGE_LABELS = {
    'phone': '手机', 'guide': '星际和平指南', 'daily_training': '每日实训', 'survival_index': '生存索引',
    'assignments': '委托', 'mail': '邮件', 'battlepass': '无名勋礼', 'odyssey': '巡星之礼', 'reward_guide': '奖励指南',
}
_TITLES = {'success': '所选页面已核实', 'partial': '所选页面核对未完整结束',
           'failed': '核对未完成', 'stopped': '已停止', 'unknown': '结果待核对'}
_ROW_STATUS = {'verified': '到页已核实', 'unknown': '到页待核对', 'not_run': '未执行'}
_UNKNOWN = ('结果待核对', '请查看本次运行记录。')


def _targets(recipe):
    return tuple(step['params']['target'] for step in recipe.steps)


def result_text(recipe, report):
    if not isinstance(report, dict):
        return _UNKNOWN
    from .selected_page_check import saved_result

    try:
        receipt = saved_result(recipe, report)
    except (OSError, ValueError):
        return _UNKNOWN
    if not isinstance(receipt, dict):
        return _UNKNOWN
    status, rows = receipt.get('status'), receipt.get('pages')
    targets = _targets(recipe)
    if (not isinstance(status, str) or status not in _TITLES
            or not isinstance(rows, list) or len(rows) != len(targets)):
        return _UNKNOWN
    lines = []
    for target, row in zip(targets, rows):
        state = row.get('status') if isinstance(row, dict) else None
        if not isinstance(state, str) or state not in _ROW_STATUS or row.get('target') != target:
            return _UNKNOWN
        if status == 'success' and state != 'verified':
            return _UNKNOWN
        text = f'{_PAGE_LABELS[target]} · {_ROW_STATUS[state]}'
        if state != 'not_run':
            sent, uncertain = row.get('actions_sent'), row.get('actions_unconfirmed')
            known = type(sent) is int and type(uncertain) is int and min(sent, uncertain) >= 0
            if state == 'verified' and (not known or uncertain != 0):
                return _UNKNOWN
            if known:
                text += f' · 已发送 {sent} 次，发送待核对 {uncertain} 次'
            else:
                text += ' · 动作记录待核对'
        lines.append(text)
    return _TITLES[status], '\n'.join(lines)


@dataclass
class PageCheckDraft:
    selected: tuple[str, ...] = ()
    preview: Recipe | None = None


class SelectedPageCheckFields(ttk.Frame):
    def __init__(self, parent, draft, *, scale, can_edit, changed):
        super().__init__(parent, style='Card.TFrame')
        self.draft, self.can_edit, self.changed = draft, can_edit, changed
        self.columnconfigure(1, weight=1)
        pad = round(8 * scale)
        self.variables = {}
        self.checks = {}
        targets = tuple(target for target in WORKFLOW_PAGES if target in _PAGE_LABELS)
        for index, target in enumerate(targets):
            variable = self.variables[target] = tk.BooleanVar(self)
            control = self.checks[target] = ttk.Checkbutton(
                self, text=_PAGE_LABELS[target], variable=variable, style='Card.TCheckbutton',
                command=lambda target=target: self._select(target))
            control.grid(row=index // 2, column=index % 2, sticky='w', padx=(0, pad))
        row = (len(targets) + 1) // 2
        self.preview_button = ttk.Button(self, text='预览顺序', style='Compact.TButton', command=self.preview)
        self.preview_button.grid(row=row, column=0, sticky='w', pady=(pad, 0))
        self.order = theme.wrapped_label(self, style='CardHint.TLabel')
        self.order.grid(row=row + 1, column=0, columnspan=2, sticky='ew', pady=(pad, 0))

    def _ordered_targets(self):
        ordinary = tuple(target for target in self.draft.selected if target not in ACTIVITY_WORKFLOW_PAGES)
        return ordinary + tuple(target for target in ACTIVITY_WORKFLOW_PAGES if target in self.draft.selected)

    @property
    def recipe(self):
        recipe = self.draft.preview
        return recipe if recipe is not None and _targets(recipe) == self._ordered_targets() else None

    def refresh(self):
        editable = self.can_edit()
        for target, control in self.checks.items():
            self.variables[target].set(target in self.draft.selected)
            control.state(('!disabled' if editable else 'disabled',))
        self.preview_button.state(('!disabled' if editable and self.draft.selected else 'disabled',))
        recipe = self.recipe
        if recipe is not None:
            text = '实际核对顺序 · ' + ' → '.join(_PAGE_LABELS[target] for target in _targets(recipe))
        else:
            text = '勾选后请预览实际顺序。'
        self.order.configure(text=text)

    def _select(self, target):
        if not self.can_edit():
            self.refresh()
            return
        selected = self.draft.selected
        if self.variables[target].get():
            if target not in selected:
                self.draft.selected = (*selected, target)
        else:
            self.draft.selected = tuple(value for value in selected if value != target)
        if self.draft.selected != selected:
            self.draft.preview = None
            self.changed(True)

    def preview(self):
        if not self.can_edit() or not self.draft.selected:
            return
        from .selected_page_check import build_recipe

        try:
            self.draft.preview = build_recipe(self._ordered_targets())
        except (OSError, WorkflowError):
            self.draft.preview = None
        self.changed(False)
        if self.draft.preview is None:
            self.order.configure(text='顺序预览待核对，请重新勾选。')
