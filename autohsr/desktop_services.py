"""Paper panels for the explicit desktop redemption and notification tools."""

from dataclasses import replace
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, ttk
from uuid import uuid4

from . import theme
from .config import ROOT
from .notify_profiles import MAX_BYTES as PROFILE_MAX_BYTES
from .notify_profiles import PROVIDERS, NotifyCancelled, NotifyError, ProfileStore, alias, loads
from .notify_runtime import STATUSES, STATUS_LABELS, NotificationService
from .redemption_codes import MAX_ROWS, CatalogCancelled, fetch_catalog, from_file, from_values
from .redemption_report import report_summary
from .redemption_settings import validate_settings as validate_redemption


_SOURCES = {'online': '在线码表', 'manual': '手动输入', 'file': '本地码表'}
_SERVERS = {'cn': '国服', 'global': '国际服', 'auto': '由当前客户端识别'}
_PREVIEWS = {
    'online': ('联网预览码表', '联网码表', 'download'),
    'manual': ('预览手动批次', '手动批次', 'values'),
    'file': ('预览本地码表', '本地码表', 'file'),
}
_PREVIEW_UNSET = '尚无码表预览。'
_TEST_STATUS = {
    'accepted': '渠道已接收测试通知。',
    'partial': '测试通知部分完成，请核对所选渠道。',
    'rejected': '渠道拒绝测试通知。',
    'unknown': '测试通知结果待核对。',
    'cancelled': '测试通知已停止。',
    'profile_changed': '所选配置已改变，请刷新后重新核对。',
}


def _split(value):
    return [item for item in re.split(r'[\s,，]+', value) if item]


def _choice(values, label):
    return next((key for key, value in values.items() if value == label), label)


def _preview_summary(batch, source, server):
    _, label, kind = _PREVIEWS[source]
    summary = batch.public_summary()
    if summary['server'] != server or summary['source_kind'] != kind:
        raise ValueError('码表来源或服务器与预览请求不符。')
    reasons = summary['reasons']
    duplicate = reasons.get('duplicate', 0)
    prefix = f'{label} · {_SERVERS[server]}'
    if source == 'manual':
        invalid = reasons.get('invalid_code', 0)
        return (f'{prefix} · 格式适用 {summary["count"]} · 重复 {duplicate} · 格式无效 {invalid}。'
                '手动码的时效和服别待游戏核实。')
    expired = reasons.get('expired', 0)
    other_server = reasons.get('other_server', 0)
    invalid = summary['skipped'] - expired - other_server - duplicate
    return (f'{prefix} · 适用 {summary["count"]} · 已过期 {expired} · 其他服 {other_server}'
            f' · 重复 {duplicate} · 无效行 {invalid}')


def _draft(ui, name, values, *, view):
    attribute = '_' + name + '_desktop_draft'
    if not hasattr(ui, attribute):
        def variable(value):
            kind = tk.BooleanVar if type(value) is bool else tk.StringVar
            return kind(master=ui.root, value=value)

        draft = {key: variable(value) for key, value in values.items()}
        ui.form_variables.extend(draft.values())
        draft.update({key: variable(value) for key, value in view.items()})
        setattr(ui, attribute, draft)
    return getattr(ui, attribute)


def _complete_code_receipts(batch):
    if batch is None or 'pending_entry_id' in batch:
        return False
    codes, rows = batch.get('codes'), batch.get('results')
    return (type(codes) is list and type(rows) is list and bool(codes)
            and len(codes) == len(rows)
            and all(type(code) is str for code in codes) and len(set(codes)) == len(codes)
            and all(type(row) is dict and row.get('code') == code for code, row in zip(codes, rows)))


def _attachment_label(batch, *, state, code_complete, redeemed):
    if batch is None or 'mail' not in batch:
        return '状态未记录'
    mail = batch['mail']
    if mail == 'not_requested':
        return '本批未处理' if state in ('completed', 'empty') else '未记录核对结果'
    if not code_complete or not redeemed:
        return '待核对'
    if mail == 'deferred_to_daily_mail':
        return '交由日常邮件核对'
    if type(mail) is dict:
        status = mail.get('status')
        if status == 'ok':
            return '已核对'
        if status == 'failed':
            return '核对失败'
        if status == 'stopped':
            return '核对已停止'
    return '待核对'


def _redemption_feedback(report):
    if not isinstance(report, dict):
        return None
    summary = report_summary(report)
    if summary is None:
        return None
    historical = summary.get('reused_report') is True
    state = summary['state']
    raw = report.get('redemption')
    # A workflow's saved summary may be present without its original batch.
    batch = raw if type(raw) is dict and report.get('operation') != 'task_workflow' else None
    code_complete = state == 'completed' or state == 'needs_review' and _complete_code_receipts(batch)
    if state == 'needs_review':
        code_status = '逐码反馈已核实 · 批次待核对' if code_complete else '逐码反馈尚未齐全 · 待核对'
    else:
        code_status = {
            'completed': '逐码反馈已核实',
            'empty': '没有可处理的兑换码',
            'unverified': '兑换反馈未核实',
        }[state]
    lines = [('沿用日常记录 · ' if historical else '') + code_status]
    if state != 'unverified':
        success = '原批次成功' if historical else '本次成功'
        lines.append(
            f"{success} {summary['redeemed']} · 服务端过期 {summary['expired']}"
            f" · 已使用 {summary['already_used']} · 无效 {summary['invalid']}"
            f" · 旧回执复用 {summary['reused']}"
        )
        skipped = batch.get('skipped') if batch is not None else None
        if type(skipped) is list and len(skipped) <= MAX_ROWS:
            skipped_rows = {'expired': set(), 'duplicate': set()}
            for row in skipped:
                if type(row) is dict and type(row.get('row')) is int and 0 <= row['row'] < MAX_ROWS:
                    reason = row.get('reason')
                    if type(reason) is str and reason in skipped_rows:
                        skipped_rows[reason].add(row['row'])
            expired, duplicates = (len(skipped_rows[key]) for key in ('expired', 'duplicate'))
            if expired or duplicates:
                lines.append(f'码表跳过 · 已过期 {expired} · 批次重复 {duplicates}')
        attachment = _attachment_label(batch, state=state, code_complete=code_complete,
                                       redeemed=summary['redeemed'])
        lines.append('邮件附件 · ' + attachment)
    if report.get('report_saved') is False:
        lines.append('运行报告未保存。')
    return '\n'.join(lines)


def _run_notification_feedback(event):
    if type(event) is not dict or event.get('type') != 'notification_summary':
        return None
    prefix = '最近一次运行通知 · '
    status = event.get('status')
    if status == 'filtered':
        return prefix + '结果状态不在通知范围。'
    if status not in ('accepted', 'partial', 'cancelled'):
        return prefix + '回执待核对。'

    seen, requested, accepted = (event.get(key) for key in ('profiles', 'requested_profiles', 'accepted'))
    valid_counts = (all(type(value) is int for value in (seen, requested, accepted))
                    and 0 <= accepted <= seen <= requested <= 32)
    if status == 'accepted':
        valid_counts = valid_counts and 0 < accepted == seen == requested
    elif status == 'partial':
        valid_counts = valid_counts and seen == requested and (accepted < seen or seen == 0)
    if not valid_counts:
        return prefix + ('已停止 · 回执计数待核对。' if status == 'cancelled' else '回执待核对。')

    label = {'accepted': '渠道已受理', 'partial': '部分完成', 'cancelled': '已停止'}[status]
    return prefix + f'{label} · 已记录配置 {seen}/{requested} · 渠道受理 {accepted}'


class _PaperPanel(ttk.Frame):
    def __init__(self, parent, ui, title):
        self.ui = ui
        self.pad = round(10 * ui.ui_scale)
        super().__init__(parent, style='Card.TFrame', padding=round(16 * ui.ui_scale))
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=title, style='CardTitle.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        self.controls = []
        self.bind('<Destroy>', self._destroyed, add='+')
        self.traces = []

    def _destroyed(self, event):
        if event.widget is self:
            for var, handle in self.traces:
                var.trace_remove('write', handle)

    def _watch(self, variable):
        self.traces.append((variable, variable.trace_add('write', self._action_changed)))

    def _action_changed(self, *_):
        self.refresh_controls()
        refresh_footer = getattr(self.ui, '_tool_action_changed', None)
        if refresh_footer is not None:
            refresh_footer()

    def refresh(self):
        self.refresh_controls()

    def _row(self, index, name):
        ttk.Label(self, text=name, style='Card.TLabel').grid(
            row=index, column=0, sticky='w', padx=(0, self.pad), pady=(self.pad, 0))
        frame = ttk.Frame(self, style='Card.TFrame')
        frame.grid(row=index, column=1, sticky='ew', pady=(self.pad, 0))
        return frame

    def _note(self, index, *, text=None, variable=None):
        options = {'textvariable': variable} if variable is not None else {'text': text}
        theme.wrapped_label(self, style='CardHint.TLabel', **options).grid(
            row=index, column=0, columnspan=2, sticky='ew', pady=(self.pad, 0))

    def _control(self, widget, *, state='normal'):
        self.controls.append((widget, state))
        return widget

    def refresh_controls(self):
        for widget, state in self.controls:
            widget.configure(state='disabled' if self.ui.busy else state)


class _RedemptionPanel(_PaperPanel):
    def __init__(self, parent, ui):
        super().__init__(parent, ui, '兑换码')
        saved = ui.settings
        self.draft = _draft(ui, 'redemption', dict(
            enabled=saved.redemption_enabled,
            source=_SOURCES.get(saved.redemption_source, saved.redemption_source),
            server=_SERVERS.get(saved.redemption_server, saved.redemption_server),
            codes='，'.join(saved.redemption_codes),
            catalog=saved.redemption_catalog,
            mail=saved.redemption_claim_mail,
        ), view=dict(result='尚无兑换结果。', preview_result=_PREVIEW_UNSET, preview_request=''))
        fields = self.draft
        row = self._row(1, '兑换来源')
        self.source = self._control(ttk.Combobox(row, textvariable=fields['source'], values=tuple(_SOURCES.values()),
                                                width=14, state='readonly'), state='readonly')
        self.source.pack(side='left')
        ttk.Label(row, text='服务器', style='Card.TLabel').pack(side='left', padx=(2 * self.pad, self.pad))
        self.server = self._control(ttk.Combobox(row, textvariable=fields['server'], values=tuple(_SERVERS.values()),
                                                width=17, state='readonly'), state='readonly')
        self.server.pack(side='left')
        row = self._row(2, '兑换内容')
        self.online_hint = theme.wrapped_label(row, text='运行时获取对应服务器码表。', style='CardHint.TLabel')
        self.manual = self._control(ttk.Entry(row, textvariable=fields['codes'], width=18))
        self.file = ttk.Frame(row, style='Card.TFrame')
        self._control(ttk.Button(self.file, text='选择码表', style='Compact.TButton',
                                 command=self._pick_file)).pack(side='right', padx=(self.pad, 0))
        self._control(ttk.Entry(self.file, textvariable=fields['catalog'], width=18)).pack(
            side='left', fill='x', expand=True)
        row.columnconfigure(0, weight=1)
        for field in (self.online_hint, self.manual, self.file):
            field.grid(row=0, column=0, sticky='ew')
        self.source_note = tk.StringVar(master=ui.root)
        self._note(3, variable=self.source_note)
        row = self._row(4, '码表预览')
        self.preview_button = self._control(ttk.Button(row, style='Compact.TButton', command=self.preview))
        self.preview_button.pack(side='left')
        self._note(5, variable=fields['preview_result'])
        row = self._row(6, '执行选项')
        self._control(ttk.Checkbutton(row, text='加入日常计划', variable=fields['enabled'])).pack(side='left')
        self._control(ttk.Checkbutton(row, text='成功后核对邮件附件', variable=fields['mail'])).pack(
            side='left', padx=(self.pad, 0))
        self._note(7, text='独立兑换使用当前游戏账号。保存偏好请用底栏「保存设置」。')
        self._note(8, variable=fields['result'])
        self._watch(fields['source'])
        for key in ('source', 'server', 'codes', 'catalog'):
            variable = fields[key]
            self.traces.append((variable, variable.trace_add('write', self._invalidate_preview)))
        self.refresh_controls()

    def refresh_controls(self):
        super().refresh_controls()
        source = _choice(_SOURCES, self.draft['source'].get())
        self.source_note.set({
            'manual': '多个兑换码可用空白或逗号分隔，保留原大小写。',
            'file': '选择本地 UTF-8 JSON 码表。',
        }.get(source, '实际兑换可在下载失败时使用随包码表。联网预览只报告下载结果。'))
        self.preview_button.configure(text=_PREVIEWS.get(source, ('预览码表',))[0])
        for field, kind in ((self.online_hint, 'online'), (self.manual, 'manual'), (self.file, 'file')):
            if kind == source:
                field.grid()
            else:
                field.grid_remove()

    def _pick_file(self):
        if self.ui.busy:
            return
        path = filedialog.askopenfilename(parent=self.ui.root, title='选择本地兑换码表',
                                          filetypes=(('JSON 码表', '*.json'), ('所有文件', '*.*')))
        if path:
            self.draft['catalog'].set(path)

    def _invalidate_preview(self, *_):
        fields = self.draft
        if fields['preview_result'].get() != _PREVIEW_UNSET:
            fields['preview_request'].set('')
            fields['preview_result'].set('草稿已变化，请重新预览。')

    def preview(self):
        if self.ui.busy or self.ui.closing:
            return False
        fields = self.draft
        source = _choice(_SOURCES, fields['source'].get())
        server = _choice(_SERVERS, fields['server'].get())
        result = fields['preview_result']
        if server not in ('cn', 'global'):
            result.set('预览请选择国服或国际服。')
            self.server.focus_set()
            return False
        if source not in _PREVIEWS:
            result.set('请选择一个码表来源。')
            self.source.focus_set()
            return False
        manual = fields['codes'].get() if source == 'manual' else ''
        path = fields['catalog'].get() if source == 'file' else ''
        if source == 'file' and not path.strip():
            result.set('请选择本地 JSON 码表。')
            return False

        request = fields['preview_request']
        previous = request.get(), result.get()
        ticket = uuid4().hex
        request.set(ticket)
        title, label, _ = _PREVIEWS[source]
        result.set(f'正在核对{label}。')

        def work(cancel):
            if cancel.is_set():
                raise CatalogCancelled()
            if source == 'manual':
                batch = from_values(_split(manual), server)
            elif source == 'file':
                batch = from_file(ROOT / Path(path), server)
            else:
                batch = fetch_catalog(server, cancel=cancel.is_set)
            if cancel.is_set():
                raise CatalogCancelled()
            return _preview_summary(batch, source, server)

        def finish(text):
            if not self.ui.closing and request.get() == ticket:
                if self.ui.stop_requested.is_set():
                    text = '码表预览已停止。'
                result.set(text)

        def failed(error):
            if isinstance(error, CatalogCancelled):
                finish('码表预览已停止。')
            else:
                finish(f'{label}预览失败，请核对来源后重试。')

        if self.ui._submit_tool_job(title, work, finish, failed):
            return True
        if request.get() == ticket:
            request.set(previous[0])
            result.set(previous[1])
        return False

    def settings_values(self):
        fields = self.draft
        return dict(
            redemption_enabled=fields['enabled'].get(),
            redemption_source=_choice(_SOURCES, fields['source'].get()),
            redemption_server=_choice(_SERVERS, fields['server'].get()),
            redemption_codes=_split(fields['codes'].get()),
            redemption_catalog=fields['catalog'].get(),
            redemption_claim_mail=fields['mail'].get(),
        )

    @property
    def daily_enabled(self):
        return bool(self.draft['enabled'].get())

    def runtime_values(self, *, standalone=False):
        if not standalone and not self.daily_enabled:
            return {'redemption_enabled': False}
        request = dict(self.settings_values(), redemption_enabled=True)
        source = request['redemption_source']
        if source != 'manual':
            request['redemption_codes'] = []
        if source != 'file':
            request['redemption_catalog'] = ''
        return request

    def focus_entry(self):
        self.source.focus_set()

    def primary_action(self):
        return '开始兑换', self.start, not self.ui.busy

    def start(self):
        if self.ui.busy:
            return False
        request = self.runtime_values(standalone=True)
        result = self.draft['result']
        try:
            validate_redemption(replace(self.ui.settings, **request), requested=True)
        except ValueError as error:
            result.set(str(error))
            return False
        previous = result.get()
        result.set('正在核对本次兑换。')
        if not self.ui._start_service_redemption(request, on_report=self.render_report):
            result.set(previous)
            return False
        return True

    def render_report(self, report):
        if callable(getattr(report, 'to_dict', None)):
            report = report.to_dict()
        feedback = _redemption_feedback(report)
        if feedback is not None:
            self.draft['result'].set(feedback)


def _profile_catalog():
    catalog = {}
    for row in ProfileStore().list_public():
        try:
            identity = alias(row.get('id'))
        except NotifyError:
            continue
        provider = row.get('provider')
        catalog[identity] = provider if row.get('readable') is True and provider in PROVIDERS else None
    return catalog


class _NotificationsPanel(_PaperPanel):
    def __init__(self, parent, ui):
        super().__init__(parent, ui, '通知')
        saved = ui.settings
        self.draft = _draft(ui, 'notification', dict(
            enabled=saved.notification_enabled, profiles='，'.join(saved.notification_profiles),
            title=saved.notification_title, body=saved.notification_body,
            **{status: status in saved.notification_statuses for status in STATUSES},
        ), view=dict(selected='', result='尚无通知测试结果。',
                     run_result='尚无运行结束通知记录。', replace_existing=False))
        if not hasattr(ui, '_desktop_notify_catalog'):
            ui._desktop_notify_catalog = {}
            self._read_catalog()
        fields = self.draft
        self.replace_existing = fields['replace_existing']
        row = self._row(1, '已保存配置')
        self.profiles = self._control(ttk.Combobox(row, textvariable=fields['selected'],
                                                   width=18, state='readonly'), state='readonly')
        self.profiles.pack(side='left')
        self._control(ttk.Button(row, text='刷新', style='Compact.TButton',
                                 command=self.refresh_profiles)).pack(side='left', padx=(self.pad, 0))
        self.check_button = self._control(ttk.Button(row, text='核对配置', style='Compact.TButton', command=self.check))
        self.check_button.pack(side='left', padx=(self.pad, 0))
        self.add_button = self._control(ttk.Button(row, text='加入通知名单', style='Compact.TButton',
                                                   command=self._add_profile))
        self.add_button.pack(side='left', padx=(self.pad, 0))
        self.profile_detail = tk.StringVar(master=ui.root)
        self._note(2, variable=self.profile_detail)
        row = self._row(3, '凭据管理')
        self.new_button = self._control(ttk.Button(row, text='新建通知配置', style='Compact.TButton',
                                                   command=self.new_profile))
        self.new_button.pack(side='left')
        self._control(ttk.Button(row, text='导入并保存配置', style='Compact.TButton',
                                 command=self.import_profile)).pack(side='left', padx=(self.pad, 0))
        self._control(ttk.Checkbutton(row, text='导入时允许替换同名', variable=self.replace_existing)).pack(
            side='left', padx=(self.pad, 0))
        row = self._row(4, '运行结束通知')
        self._control(ttk.Checkbutton(row, text='启用', variable=fields['enabled'])).pack(side='left')
        for status in STATUSES:
            self._control(ttk.Checkbutton(row, text=STATUS_LABELS[status], variable=fields[status])).pack(
                side='left', padx=(self.pad, 0))
        for index, label, field in ((5, '通知名单', 'profiles'), (6, '标题模板', 'title'), (7, '正文模板', 'body')):
            row = self._row(index, label)
            self._control(ttk.Entry(row, textvariable=fields[field], width=18)).pack(fill='x', expand=True)
        self._note(8, text='通知名单用逗号分隔。模板可用 {operation}、{status}、{summary}。')
        self._note(9, variable=fields['result'])
        self._note(10, variable=fields['run_result'])
        self._watch(fields['selected'])
        self.refresh_controls()

    def _read_catalog(self):
        try:
            catalog = _profile_catalog()
        except (OSError, NotifyError):
            self.ui._desktop_notify_catalog = {}
            self.draft['result'].set('已保存的通知配置未能读取。')
            return False
        self.ui._desktop_notify_catalog = catalog
        return True

    def refresh_profiles(self):
        if self.ui.busy:
            return
        self._read_catalog()
        if self.draft['selected'].get() not in self.ui._desktop_notify_catalog:
            self.draft['selected'].set('')
        else:
            self._action_changed()

    def _selected(self):
        identity = self.draft['selected'].get()
        return identity, self.ui._desktop_notify_catalog.get(identity)

    def refresh_controls(self):
        super().refresh_controls()
        identity, provider = self._selected()
        catalog = self.ui._desktop_notify_catalog
        self.profiles.configure(values=tuple(catalog))
        state = 'normal' if provider and not self.ui.busy else 'disabled'
        for button in (self.check_button, self.add_button):
            button.configure(state=state)
        self.profile_detail.set(
            f'所选渠道 · {provider}' if provider else
            '所选配置无法由当前 Windows 用户读取。' if identity in catalog else
            '请选择已保存的配置。测试发送到所选渠道。'
        )

    def settings_values(self):
        fields = self.draft
        return dict(
            notification_enabled=fields['enabled'].get(),
            notification_profiles=_split(fields['profiles'].get()),
            notification_statuses=[status for status in STATUSES if fields[status].get()],
            notification_title=fields['title'].get(),
            notification_body=fields['body'].get(),
        )

    def _add_profile(self):
        identity, provider = self._selected()
        if self.ui.busy or not provider:
            return
        names = _split(self.draft['profiles'].get())
        if identity not in names:
            self.draft['profiles'].set('，'.join([*names, identity]))

    def check(self):
        identity, provider = self._selected()
        if self.ui.busy or not provider:
            return
        try:
            actual = ProfileStore().load_private(identity)
        except (OSError, NotifyError):
            self.draft['result'].set('本地配置无法核实。')
            return
        self.draft['result'].set(
            '本地配置可读取。远端凭据可另行测试。' if actual.get('provider') == provider
            else _TEST_STATUS['profile_changed']
        )

    def new_profile(self):
        if self.ui.busy or self.ui.closing:
            return False
        from .desktop_notification_profile import ask_new_profile

        identity = ask_new_profile(self.ui, ProfileStore())
        if self.ui.closing:
            return False
        panel = getattr(self.ui, 'notifications_panel', self)
        if identity is not None:
            panel._profile_saved(identity)
        panel.new_button.focus_set()
        return identity is not None

    def import_profile(self):
        if self.ui.busy:
            return
        path = filedialog.askopenfilename(parent=self.ui.root, title='导入通知配置',
                                          filetypes=(('JSON 通知配置', '*.json'), ('所有文件', '*.*')))
        if not path:
            return
        replace_existing = self.replace_existing.get()
        self.replace_existing.set(False)
        try:
            with Path(path).open('rb') as stream:
                value = loads(stream.read(PROFILE_MAX_BYTES + 1))
            saved = ProfileStore().save(value, replace=replace_existing)
        except NotifyError as error:
            self.draft['result'].set(str(error))
            return
        except OSError:
            self.draft['result'].set('通知配置导入失败，请核对文件和本地存储。')
            return
        self._profile_saved(saved['id'])

    def _profile_saved(self, identity):
        if self._read_catalog():
            self.draft['selected'].set(identity)
            self.draft['result'].set('凭据已由当前 Windows 用户加密保存。')
        else:
            self.draft['selected'].set('')
            self.draft['result'].set('凭据已加密保存。请刷新配置列表。')

    def render_run_result(self, event):
        feedback = _run_notification_feedback(event)
        if feedback is not None:
            self.draft['run_result'].set(feedback)

    def focus_entry(self):
        self.profiles.focus_set()

    def primary_action(self):
        _, provider = self._selected()
        return '发送测试通知', self.test, bool(provider) and not self.ui.busy

    def test(self):
        if self.ui.busy:
            return False
        identity, provider = self._selected()
        status = self.draft['result']
        if not provider:
            status.set('请先选择可读取的已保存通知配置。')
            return False
        try:
            frozen = ProfileStore().load_version(identity)
        except (OSError, NotifyError):
            status.set('本地配置无法核实。')
            return False
        if frozen[0].get('provider') != provider:
            status.set(_TEST_STATUS['profile_changed'])
            return False
        key = 'explicit-test-' + uuid4().hex
        caption = f'测试配置 {identity} · '

        def work(cancel_event):
            def check():
                if cancel_event.is_set():
                    raise NotifyCancelled('测试通知已停止。')

            try:
                check()
                service = NotificationService()
                receipt = service.deliver(
                    frozen, 'AutoHSR 通知测试', '这是用户明确请求的通知测试，不代表游戏任务已执行。',
                    key, checkpoint=check,
                )
                return receipt.get('status', 'unknown')
            except NotifyCancelled:
                return 'cancelled'
            except (OSError, NotifyError):
                return 'unknown'

        def done(outcome):
            feedback = _TEST_STATUS.get(outcome) if isinstance(outcome, str) else None
            status.set(caption + (feedback or _TEST_STATUS['unknown']))

        previous = status.get()
        status.set(caption + '正在发送测试通知。')
        if not self.ui._submit_tool_job('通知测试', work, done, on_error=lambda _: done('unknown')):
            status.set(previous)
            return False
        return True


def build_redemption_panel(parent, ui):
    """Build the redemption contents; the shared footer owns the start action."""
    return _RedemptionPanel(parent, ui)


def build_notifications_panel(parent, ui):
    """Build profile management and notification preferences in the paper page."""
    return _NotificationsPanel(parent, ui)
