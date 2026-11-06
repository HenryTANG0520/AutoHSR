"""Daily guide content. The desktop shell owns routing and the run lifecycle."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from . import theme
from .dungeons import BY_KEY


ASSIGNMENTS = 'assignments_only'
OPEN_TARGET = 'build_target_read'
PREVIEW = 'build_target_preview'
DRAFT = 'build_target_plan'
ASSIGNMENT_STEP = 'assignments'
ASSIGNMENT_FLOW = '仅领取持续委托'


def assignment_runner(settings, emit, *, root=None):
    """Use the native single-step workflow to retain its account/input scope."""
    from .task_workflow_run import TaskWorkflowRunner

    document = dict(version=1, name=ASSIGNMENT_FLOW, steps=[
        dict(id=ASSIGNMENT_STEP, type='task', task='daily', params={'tasks': ['assignments']}),
    ])
    return TaskWorkflowRunner(settings, document, emit, root=root)


def _verified_file(path, digest, limit):
    if not isinstance(digest, str) or len(digest) != 64 or not path.is_absolute():
        raise ValueError('文件来源待核对。')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('文件内容已变化，待核对。')
    return raw


def assignment_result(report):
    """Show the child receipt, including the distinction between zero and a claim."""
    workflow = report.get('workflow') or {}
    steps = workflow.get('steps', [])
    if (report.get('operation') == 'task_workflow' and report.get('report_saved') is True
            and workflow.get('name') == ASSIGNMENT_FLOW and len(steps) == 1
            and steps[0].get('step') == ASSIGNMENT_STEP and steps[0].get('task') == 'daily'):
        step = steps[0]
        source = step.get('source') or {}
        try:
            path = Path(source.get('path', ''))
            child = json.loads(_verified_file(path, source.get('sha256'), 64 * 1024 * 1024))
            if child.get('operation') == 'daily' and child.get('report_saved') is True:
                rows = [row for row in child['results'] if row.get('task') == ASSIGNMENT_STEP]
                verified = (step.get('account_verified') is True and step.get('status') == 'success'
                            and child.get('status') == 'success')
                if verified and len(rows) == 1 and rows[0].get('status') == 'ok':
                    return '委托状态已核实', rows[0]['detail'], path
                incomplete = len(rows) == 1 and rows[0].get('status') in ('partial', 'failed', 'stopped')
                title = '已停止' if report.get('status') == 'stopped' else '委托结果待核对'
                detail = rows[0].get('detail') if incomplete else report.get('error')
                return title, detail or '请查看本次原始报告。', path
        except (KeyError, OSError, TypeError, ValueError):
            return '委托记录待核对', '请查看本次运行报告。', None
    title = '已停止' if report.get('status') == 'stopped' else '委托结果待核对'
    return title, report.get('error') or '查看本次运行报告。', None


def _preview_text(preview):
    """Project explicit observations. Numeric zero and missing values differ."""
    state = preview.get('state')
    labels = {
        'target_level_trace_complete': '等级与行迹已完成',
        'target_materials_sufficient': '等级与行迹材料已足够',
        'target_resources_needed': '已观察培养缺口',
        'panel_observed': '已核实培养目标页',
        'catalogue_candidates': '已核实培养材料来源',
        'material_observed': '已核实材料详情',
        'calyx_reward_preview': '已核实花萼费用与可能获取奖励',
        'calyx_result_shortfall': '已核实结算的培养剩余提示',
        'synthesis_preview': '已核实材料配方预览',
    }
    synthesis = preview.get('synthesis_preview') or {}
    material = preview.get('material') or synthesis.get('material')
    detail = []
    if isinstance(material, str) and material:
        detail.append(material)
        held = synthesis.get('held') if synthesis else preview.get('held')
        detail.append(f'当前持有 {held}' if type(held) is int else '当前持有待核对')
    observations = preview.get('shortfall_rows') or []
    settlement = preview.get('post_battle_shortfall') or {}
    if settlement:
        observations = [settlement]
    needed = ['／'.join(map(str, row['observed_needed'])) for row in observations if row.get('observed_needed')]
    if needed:
        detail.append('培养尚需（按画面顺序） ' + '、'.join(needed))
    calyx = preview.get('calyx_reward_preview') or {}
    if type(calyx.get('shown_total_stamina')) is int:
        detail.append(f"{calyx['target']} · 难度 {calyx['difficulty']} · {calyx['selected_rounds']} 轮")
        detail.append(f"画面费用 {calyx['shown_total_stamina']} 开拓力")
    if synthesis:
        detail.append(f"配方已选 {synthesis['selected_output']} 件 · 滑杆上限 {synthesis['slider_limit']} 件")
    if type(settlement.get('completed_rounds')) is int:
        detail.append(f"上轮完成 {settlement['completed_rounds']} 波")
    if state in ('panel_observed', 'target_resources_needed'):
        detail.append('打开同一材料的获得途径可预览副本来源。')
    return labels.get(state, '培养目标待核对'), ' · '.join(detail)


def _draft_data(report):
    from .build_target_draft import PLAN
    from .power_plan import items

    draft = report.get('build_target', {}).get('draft') or {}
    if (report.get('status') != 'success' or report.get('report_saved') is not True
            or draft.get('state') != 'prepared' or draft.get('file') != PLAN):
        raise ValueError('草稿发布待核对。')
    directory = Path(report.get('run_dir', ''))
    path = directory / PLAN
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError('草稿文件来源待核对。')
    raw = _verified_file(path, draft.get('sha256'), 64 * 1024)
    parsed = json.loads(raw)
    if parsed != draft.get('items') or not isinstance(parsed, list) or len(parsed) != 1:
        raise ValueError('草稿条目与本次回执不一致。')
    item, = items(parsed)
    return path, item


def _draft_key(report):
    draft = report.get('build_target', {}).get('draft') or {}
    directory, digest = report.get('run_dir'), draft.get('sha256')
    if isinstance(directory, str) and isinstance(digest, str):
        return directory, digest
    return None


def support_result_text(report):
    labels = {
        'needed': '实训需要借用支援', 'completed': '实训已完成支援要求',
        'activity_full': '实训活跃度已满',
        'borrowed': '已核实支援入队', 'skipped': '按偏好跳过借用',
        'unknown': '支援需求待核对', 'unverified': '支援入队待核对',
    }
    results = []
    for row in report.get('support_selections') or []:
        if not isinstance(row, dict) or row.get('state') not in labels:
            continue
        label = labels[row['state']]
        if row['state'] == 'borrowed':
            selected = row.get('selected') or {}
            character = selected.get('character')
            if character:
                from .support_profiles import catalogue

                name = catalogue().get(character, {}).get('name')
                if name:
                    label += ' · ' + name
            if row.get('fallback_used') is True:
                label += '（备用好友）'
        results.append(label)
    return ' · '.join(dict.fromkeys(results))


class DailyPanel(ttk.Frame):
    """Content for one existing first-level page at a time.

    The shell calls show(), uses primary_label/invoke_primary for its footer,
    and forwards set_busy() and the terminal present(operation, report).
    """

    def __init__(self, parent, ui, *, start):
        super().__init__(parent)
        self.ui, self.start = ui, start
        self.section = ASSIGNMENTS
        self.busy = False
        self.candidates = []
        self.material = None
        self.draft_report = None
        self._applied_drafts = set()
        self._assignment_report = None
        self.assignment_title = tk.StringVar(self, '等待领取')
        self.assignment_detail = tk.StringVar(self, '领取已有奖励，原委托继续累计。')
        self.build_title = tk.StringVar(self, '等待预览')
        self.build_detail = tk.StringVar(self, '在游戏中打开培养目标或材料获得途径。')
        self.entry_status = tk.StringVar(self, '从游戏的生存索引打开并核对培养目标页。')
        self.draft_detail = tk.StringVar(self)
        self.count = tk.StringVar(self)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        d = lambda n: round(n * ui.ui_scale)

        self.assignment = ttk.Frame(self, style='Card.TFrame', padding=d(20))
        self.assignment.columnconfigure(0, weight=1)
        self._heading(self.assignment, '持续委托', self.assignment_title, self.assignment_detail)
        self.assignment_record = ttk.Button(self.assignment, text='查看原始报告', style='Panel.TButton',
                                            state='disabled', command=self._open_assignment_report)
        self.assignment_record.grid(row=3, column=0, sticky='w', pady=(d(10), 0))

        self.build = ttk.Frame(self, style='Card.TFrame', padding=d(20))
        self.build.columnconfigure(0, weight=1)
        self._heading(self.build, '培养目标', self.build_title, self.build_detail)
        entry = ttk.Frame(self.build, style='Panel.TFrame')
        entry.grid(row=3, column=0, sticky='ew', pady=(d(8), 0))
        entry.columnconfigure(1, weight=1)
        self.open_target = ttk.Button(entry, text='打开培养目标', style='Panel.TButton', command=self._open_target)
        self.open_target.grid(row=0, column=0, sticky='w', padx=(0, d(10)))
        theme.wrapped_label(entry, textvariable=self.entry_status, style='Muted.TLabel').grid(row=0, column=1, sticky='ew')
        sources = ttk.Frame(self.build, style='Panel.TFrame')
        sources.grid(row=4, column=0, sticky='ew', pady=(d(12), d(8)))
        sources.columnconfigure(1, weight=1)
        ttk.Label(sources, text='副本来源', style='Muted.TLabel').grid(row=0, column=0, padx=(0, d(10)))
        self.source = ttk.Combobox(sources, state='disabled', width=24)
        self.source.grid(row=0, column=1, sticky='ew')
        self.source.bind('<<ComboboxSelected>>', lambda _: self._controls())
        ttk.Label(sources, text='次数（1～6）', style='Muted.TLabel').grid(row=0, column=2, padx=(d(12), d(6)))
        self.times = ttk.Spinbox(sources, from_=1, to=6, width=4, textvariable=self.count, state='disabled')
        self.times.grid(row=0, column=3)
        self.generate = ttk.Button(sources, text='生成体力草稿', style='Panel.TButton', command=self._generate)
        self.generate.grid(row=0, column=4, padx=(d(12), 0))
        theme.wrapped_label(self.build, textvariable=self.draft_detail, style='Muted.TLabel').grid(row=5, column=0, sticky='ew')
        self.add_draft = ttk.Button(self.build, text='加入体力计划', style='Panel.TButton', command=self._add_draft)
        self.add_draft.grid(row=6, column=0, sticky='w', pady=(d(6), 0))
        self.show(ASSIGNMENTS)

    def _heading(self, panel, title, status, detail):
        d = lambda n: round(n * self.ui.ui_scale)
        ttk.Label(panel, text=title, style='CardTitle.TLabel').grid(row=0, column=0, sticky='w', pady=(0, d(12)))
        ttk.Label(panel, textvariable=status, style='Section.TLabel').grid(row=1, column=0, sticky='w')
        theme.wrapped_label(panel, textvariable=detail, style='Muted.TLabel').grid(row=2, column=0, sticky='ew', pady=(d(6), 0))

    def show(self, section):
        panels = {ASSIGNMENTS: self.assignment, PREVIEW: self.build}
        panel = panels[section]
        for other in panels.values():
            other.grid_remove()
        self.section = section
        panel.grid(row=0, column=0, sticky='nsew')
        self._controls()

    @property
    def primary_label(self):
        return ASSIGNMENT_FLOW if self.section == ASSIGNMENTS else '预览材料'

    def invoke_primary(self):
        if not (self.busy or self.ui.busy):
            self.start(self.section)

    def set_busy(self, busy):
        self.busy = busy
        self._controls()

    def snapshot_draft(self):
        """Copy the panel state without keeping references to the old widgets."""
        return deepcopy(dict(
            section=self.section, assignment_report=self._assignment_report,
            build_title=self.build_title.get(), build_detail=self.build_detail.get(),
            entry_status=self.entry_status.get(),
            draft_detail=self.draft_detail.get(), draft_report=self.draft_report,
            applied_drafts=self._applied_drafts, material=self.material, candidates=self.candidates,
            selected=self.source.current(), source_text=self.source.get(), count=self.count.get(),
        ))

    def restore_draft(self, state):
        """Restore a snapshot taken from the outgoing view before a resize."""
        state = deepcopy(state)
        self._assignment_report = state['assignment_report']
        self._refresh_assignment()
        self.build_title.set(state['build_title'])
        self.build_detail.set(state['build_detail'])
        self.entry_status.set(state['entry_status'])
        self.material = state['material']
        self.candidates = state['candidates']
        self._show_sources(state['source_text'], selected=state['selected'])
        self.count.set(state['count'])
        self._applied_drafts = state['applied_drafts']
        self.draft_report = None
        self.draft_detail.set(state['draft_detail'])
        if state['draft_report'] is not None:
            self._present_draft(state['draft_report'])
            if self.draft_report is not None:
                self.draft_detail.set(state['draft_detail'])
        self.show(state['section'])

    def _controls(self):
        locked = self.busy or self.ui.busy
        self.open_target.configure(state='disabled' if locked else 'normal')
        self.source.configure(state='disabled' if locked or not self.candidates else 'readonly')
        selected = self.source.current() >= 0 and not locked
        self.times.configure(state='normal' if selected else 'disabled')
        self.generate.configure(state='normal' if selected else 'disabled')
        can_add = self.draft_report is not None and not locked and self.ui.settings.allow_stamina_spend
        self.add_draft.configure(state='normal' if can_add else 'disabled')

    def _open_target(self):
        if self.section != PREVIEW or self.busy or self.ui.busy:
            return
        previous = self.entry_status.get()
        self.entry_status.set('正在核对培养目标入口。')
        if not self.start(OPEN_TARGET):
            self.entry_status.set(previous)

    def _generate(self):
        from .build_target_preview import BuildTargetSelection

        index = self.source.current()
        if self.busy or self.ui.busy or index < 0:
            return
        source = self.candidates[index]
        try:
            count = int(self.count.get())
        except ValueError:
            self.draft_detail.set('次数须为 1～6 的整数。')
            self.times.focus_set()
            return
        try:
            selection = BuildTargetSelection(self.material, source['location'], count)
            if count > source['max_challenges_by_config']:
                raise ValueError('所选次数超过预览中的配置上限。')
        except ValueError as error:
            self.draft_detail.set(str(error))
            self.times.focus_set()
            return
        self.start(DRAFT, build_target_selection=selection)

    def _add_draft(self):
        from .power_plan_ui import rows

        if self.busy or self.ui.busy or self.draft_report is None or not self.ui.settings.allow_stamina_spend:
            return
        try:
            _, item = _draft_data(self.draft_report)
            entries = rows(self.ui)
        except (OSError, ValueError, TypeError) as error:
            self.draft_detail.set(f'无法加入体力计划：{error}')
            return
        if any(all(row[key] == getattr(item, key) for key in ('category', 'target', 'location')) for row in entries):
            self.draft_detail.set('该副本已在体力计划中，可在计划内调整次数。')
            return
        try:
            self.ui.power_editor.commit(item.to_dict(), None)
        except ValueError as error:
            self.draft_detail.set(f'无法加入体力计划：{error}')
            return
        self.draft_detail.set('已加入体力计划草稿。')
        self._applied_drafts.add(_draft_key(self.draft_report))
        self.draft_report = None
        self._controls()

    def _refresh_assignment(self):
        if self._assignment_report is None:
            title, detail, path = '等待领取', '领取已有奖励，原委托继续累计。', None
        else:
            title, detail, path = assignment_result(self._assignment_report)
        self.assignment_title.set(title)
        self.assignment_detail.set(detail)
        self.assignment_record.configure(state='normal' if path else 'disabled')
        return path

    def _open_assignment_report(self):
        path = self._refresh_assignment()
        if path is not None:
            self.ui._open_path(path)

    def present(self, operation, report):
        if operation == ASSIGNMENTS:
            self._assignment_report = deepcopy(report)
            self._refresh_assignment()
        elif operation == OPEN_TARGET:
            self._present_open_target(report)
        elif operation == PREVIEW:
            self._present_preview(report)
        elif operation == DRAFT:
            self._present_draft(report)
        self._controls()

    def _present_open_target(self, report):
        entry = report.get('build_target') or {}
        if report.get('status') == 'stopped':
            message = '已停止。请核对当前游戏画面。'
        elif (report.get('status') == 'success' and report.get('report_saved') is True
              and entry.get('page_verified') is True):
            message = '已核实培养目标页。可在游戏中选择材料，再预览。'
        elif entry.get('entry_input') in ('sent', 'unconfirmed'):
            message = '培养目标入口反馈待核对。请查看当前游戏和本次报告。'
        else:
            message = '培养目标页待核对。请在游戏中打开生存索引后重试。'
        self.entry_status.set(message)

    def _present_preview(self, report):
        preview = report.get('build_target', {}).get('preview') or {}
        if report.get('report_saved') is not True or report.get('status') in ('failed', 'stopped'):
            preview = {}
        title, detail = _preview_text(preview)
        self.build_title.set('已停止' if report.get('status') == 'stopped' else title)
        self.build_detail.set(report.get('error') or detail or '打开培养目标或材料获得途径后重试。')
        self.material = preview.get('material')
        self.candidates = [row for row in preview.get('candidates', [])
                           if row.get('category') in BY_KEY and row.get('location')
                           and type(row.get('max_challenges_by_config')) is int
                           and row['max_challenges_by_config'] > 0]
        self._show_sources('请选择副本来源' if self.candidates else '来源待核实')
        self.count.set('')
        self.draft_report = None
        self.draft_detail.set('')

    def _show_sources(self, placeholder, *, selected=-1):
        self.source.configure(values=[f"{row['target']} · {row['location']} · {row['stamina_cost']} 开拓力／次"
                                      for row in self.candidates])
        if 0 <= selected < len(self.candidates):
            self.source.current(selected)
        else:
            self.source.set(placeholder)

    def _present_draft(self, report):
        self.draft_report = None
        if _draft_key(report) in self._applied_drafts:
            self.draft_detail.set('已加入体力计划草稿。')
            return
        try:
            _, item = _draft_data(report)
        except (OSError, ValueError, TypeError):
            self.draft_detail.set(report.get('error') or '体力草稿发布待核对。')
            return
        self.draft_report = report
        self.draft_detail.set(f'草稿已生成 · {item.target} · {item.location} · {item.count} 次'
                              f' · 预计 {item.dungeon.cost * item.count} 开拓力')
