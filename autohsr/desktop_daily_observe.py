"""Desktop entry and anonymous receipts for the four daily page observations."""

from dataclasses import dataclass, field
from tkinter import ttk

from . import theme


@dataclass(frozen=True)
class _Scope:
    label: str
    operation: str
    hint: str


_SCOPES = {
    'achievements': _Scope('成就总览', 'daily_reward_observe',
                           '先打开游戏手机菜单。开始核对后切回游戏，将核对并尝试打开成就入口一次。'),
    'support': _Scope('漫游签证', 'daily_reward_observe',
                      '先打开游戏手机菜单。开始核对后切回游戏，可依次核对并打开「更多」和「漫游签证」。'),
    'messages': _Scope('短信', 'daily_message_observe',
                       '先打开游戏手机菜单或新消息通知面板。开始核对后切回游戏，只读当前页面。'),
    'odyssey': _Scope('巡星之礼', 'daily_event_observe',
                      '先打开游戏手机菜单或巡星之礼活动页。开始核对后切回游戏，只读当前页面。'),
}
_BY_LABEL = {scope.label: mode for mode, scope in _SCOPES.items()}
_UNKNOWN = ('结果待核对', '请核对游戏前台和所选范围。')
_WAITING = ('等待核对', '')
_RUNNING = ('正在核对', '请切回已登录的游戏窗口并保持前台。')
_STOPPED = ('已停止', '本次核对已停止。')
_FAILED = ('核对未完成', '请核对游戏前台和所选范围。')


def _navigation_result(mode, value, status):
    title = _SCOPES[mode].label
    destination = value.get('destination_status')
    if (mode == 'achievements' and status == 'success' and value.get('page_verified') is True
            and destination == 'achievement_overview'):
        return title + '已核实', '奖励状态待核对。'
    if value.get('page_verified') is not False:
        return _UNKNOWN
    if mode == 'achievements' and destination == 'achievement_title_only' and value.get('entry_input') == 'sent':
        return '成就总览待核对', '已记录成就标题，页面与奖励状态待核对。'
    if mode == 'support':
        steps = value.get('steps')
        more = steps.get('open_more') if isinstance(steps, dict) else None
        support = steps.get('open_support') if isinstance(steps, dict) else None
        if (isinstance(more, dict) and more.get('entry_input') == 'sent'
                and more.get('destination_status') == 'more_menu_verified'):
            if (destination == 'support_title_only' and isinstance(support, dict)
                    and support.get('entry_input') == 'sent' and support.get('destination_status') == destination):
                return '漫游签证待核对', '已核实更多菜单，并记录漫游签证标题。页面与奖励状态待核对。'
            return '漫游签证待核对', '更多菜单已核实，签证页面与奖励状态待核对。'
    if value.get('entry_input') in ('sent', 'unconfirmed'):
        return title + '待核对', '入口提交已有记录，页面与奖励状态待核对。'
    return _UNKNOWN


def _message_result(value, status):
    captures = value.get('captures')
    if (status != 'success' or value.get('account_verified') is not True or value.get('input_sent') is not False
            or type(captures) is not int or captures < 2
            or value.get('unread_status') != 'unknown' or value.get('reward_status') != 'unknown'):
        return _UNKNOWN
    observed = value.get('phone_entry'), value.get('message_page')
    if observed == ('observed', 'unknown'):
        return '手机短信入口已核实', '未读状态和奖励状态待核对。'
    if observed == ('unknown', 'observed'):
        return '新消息通知面板已核实', '未读状态和奖励状态待核对。'
    return _UNKNOWN


def _days(value):
    if (type(value) is not list or len(value) > 7 or any(type(day) is not int or not 1 <= day <= 7 for day in value)
            or len(value) != len(set(value))):
        return None
    return tuple(sorted(value))


def _odyssey_result(value):
    page, state = value.get('page'), value.get('claimable_state')
    if value.get('page_verified') is not True or value.get('account_verified') is not True:
        return _UNKNOWN
    groups = tuple(_days(value.get(field)) for field in ('claimable_days', 'claimed_days', 'unknown_days'))
    if any(group is None for group in groups):
        return _UNKNOWN
    all_days = tuple(day for group in groups for day in group)
    available, claimed, unknown = groups
    if page == 'phone_entry' and state == 'not_observed' and not all_days:
        return '旅情事记入口已核实', '请在游戏中打开巡星之礼，再核对签到卡片。'
    if page != 'gift_of_odyssey' or sorted(all_days) != list(range(1, 8)):
        return _UNKNOWN
    if state == 'available' and available:
        title = '巡星之礼有可领奖励'
    elif state == 'none' and len(claimed) == 7 and not (available or unknown):
        title = '巡星之礼暂无可领奖励'
    elif state == 'unknown' and not available:
        title = '巡星之礼领取状态待核对'
    else:
        return _UNKNOWN
    details = [f'{label}：第 {"、".join(map(str, days))} 天' for label, days in
               (('可领取', available), ('已领取', claimed), ('待核对', unknown)) if days]
    return title, '\n'.join(details) or '签到卡片状态待核对。'


def observation_result(mode, report):
    """Read only known scoped facts. Never retain the original report text or paths."""
    scope = _SCOPES.get(mode) if isinstance(mode, str) else None
    if (scope is None or not isinstance(report, dict) or report.get('operation') != scope.operation
            or report.get('report_saved') is not True):
        return _UNKNOWN
    value = report.get(scope.operation)
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('mode', None if scope.operation == 'daily_reward_observe' else mode) != mode):
        return _UNKNOWN
    status = report.get('status')
    if status == 'stopped':
        return _STOPPED
    if status == 'failed':
        return _FAILED
    if status not in ('success', 'partial'):
        return _UNKNOWN
    if mode == 'messages':
        return _message_result(value, status)
    if mode == 'odyssey':
        return _odyssey_result(value)
    return _navigation_result(mode, value, status)


@dataclass
class _State:
    mode: str = 'achievements'
    job: object = None
    results: dict = field(default_factory=dict)


class DailyObservationPanel(ttk.Frame):
    def __init__(self, parent, ui, model):
        self.ui, self.model = ui, model
        pad = round(10 * ui.ui_scale)
        super().__init__(parent, style='Card.TFrame', padding=round(16 * ui.ui_scale))
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text='日常页面核对', style='CardTitle.TLabel').grid(
            row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(self, text='核对范围', style='Card.TLabel').grid(
            row=1, column=0, sticky='w', padx=(0, pad), pady=(pad, 0))
        self.scope = ttk.Combobox(self, values=tuple(_BY_LABEL), state='readonly', width=14)
        self.scope.grid(row=1, column=1, sticky='w', pady=(pad, 0))
        self.scope.bind('<<ComboboxSelected>>', self._selected)
        self.hint = theme.wrapped_label(self, style='CardHint.TLabel')
        self.hint.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(pad, 0))
        theme.wrapped_label(self, text='领取操作由你在游戏内完成。', style='CardHint.TLabel').grid(
            row=3, column=0, columnspan=2, sticky='ew', pady=(round(pad / 2), 0))
        ttk.Separator(self).grid(row=4, column=0, columnspan=2, sticky='ew', pady=(pad, pad))
        self.result_title = theme.wrapped_label(self, style='Card.TLabel')
        self.result_title.grid(row=5, column=0, columnspan=2, sticky='ew')
        self.result_detail = theme.wrapped_label(self, style='CardHint.TLabel')
        self.result_detail.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(round(pad / 2), 0))
        self.refresh()

    @property
    def _idle(self):
        return not self.ui.busy and not self.ui.closing and self.model.job is None

    @property
    def _active(self):
        return (getattr(self.ui, 'daily_observation_panel', None) is self and self.ui._in_tools()
                and self.ui._selected_tool == 'daily_observation')

    def primary_action(self):
        return '核对页面', self.start, self._idle and self._active

    def focus_entry(self):
        if self._idle:
            self.scope.focus_set()

    def refresh(self):
        model = self.model
        scope = _SCOPES[model.mode]
        if self.scope.get() != scope.label:
            self.scope.set(scope.label)
        self.scope.configure(state='readonly' if self._idle else 'disabled')
        self.hint.configure(text=scope.hint)
        title, detail = _RUNNING if model.job is not None else model.results.get(model.mode, _WAITING)
        self.result_title.configure(text=title)
        self.result_detail.configure(text=detail)

    def _selected(self, _event=None):
        if self._idle and self._active and self.scope.get() in _BY_LABEL:
            self.model.mode = _BY_LABEL[self.scope.get()]
        self.refresh()
        self.ui._tool_action_changed()

    def start(self):
        if not self._idle or not self._active:
            return False
        ui, model, mode = self.ui, self.model, self.model.mode
        ticket = model.job = object()

        def update():
            panel = getattr(ui, 'daily_observation_panel', None)
            if not ui.closing and panel is not None and panel.winfo_exists():
                panel.refresh()
                ui._tool_action_changed()

        def complete(report):
            if model.job is ticket:
                model.job = None
                model.results[mode] = observation_result(mode, report)
                update()

        try:
            accepted = ui._start_daily_observation(mode, complete)
        except Exception:
            if model.job is ticket:
                model.job = None
                model.results[mode] = _FAILED
            update()
            return False
        if not accepted and model.job is ticket:
            model.job = None
        update()
        return bool(accepted)


def build_daily_observation_panel(parent, ui):
    if not hasattr(ui, '_daily_observation_state'):
        ui._daily_observation_state = _State()
    return DailyObservationPanel(parent, ui, ui._daily_observation_state)
