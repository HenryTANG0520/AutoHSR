"""Per-run desktop options for existing standard Currency Wars controllers."""
from tkinter import ttk

from .config import SettingsError
from .desktop import note

STRATEGIES = {'默认': 'default', '阿格莱雅': 'aglaea', '希儿': 'seele'}
CONTROL_OPERATIONS = ('currency_wars_loop', 'currency_wars_points', 'currency_wars_rewards')


def new_options(ui, *, loop=False):
    """Validate before starting a worker; continuations must not call this."""
    from .currency_wars_names import validate_name
    from .currency_wars_loop_store import runs_value
    strategy = STRATEGIES.get(ui.currency_strategy.get())
    if strategy is None:
        raise SettingsError('currency_strategy', '请选择默认、阿格莱雅或希儿策略。')
    try:
        name = validate_name(ui.currency_remembrance_name.get())
    except ValueError as error:
        raise SettingsError('currency_remembrance_name', str(error)) from error
    options = dict(currency_strategy=strategy, currency_remembrance_name=name,
                   currency_fast_mode=ui.currency_fast_mode.get())
    if loop:
        try:
            count = runs_value(ui._number('currency_runs', int))
        except ValueError as error:
            raise SettingsError('currency_runs', str(error)) from error
        options.update(runs=count, until_points=ui.currency_until_points.get(),
                       continue_after_defeat=ui.currency_continue_after_defeat.get())
    return options


def add_controls(ui, buttons):
    """Use the delivered developer tabs; no new top-level navigation or style."""
    s = ui.ui_scale
    d = lambda n: round(n*s)
    standard = ui.currency_sections['standard']
    fields = ttk.Frame(standard, style='Card.TFrame')
    fields.grid(row=2, column=0, sticky='ew', pady=(0, d(8)))
    fields.columnconfigure(1, weight=1)
    ttk.Label(fields, text='记忆开拓者名（仅本次）', style='Muted.TLabel').grid(row=0, column=0, sticky='w', padx=(0, d(12)))
    ui.currency_remembrance_entry = ttk.Entry(fields, textvariable=ui.currency_remembrance_name, width=18)
    ui.currency_remembrance_entry.grid(row=0, column=1, sticky='ew')
    ui.currency_fast_check = ttk.Checkbutton(fields, text='速通装备分配（仅本次）', variable=ui.currency_fast_mode)
    ui.currency_fast_check.grid(row=1, column=0, columnspan=2, sticky='w', pady=(d(8), 0))
    ui.setting_controls.extend((ui.currency_remembrance_entry, ui.currency_fast_check))

    loop = ui.currency_sections['loop']
    ttk.Label(loop, text='标准 A8-40 连续开发', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
    line = ttk.Frame(loop, style='Card.TFrame')
    line.grid(row=1, column=0, sticky='ew', pady=d(8))
    ttk.Label(line, text='结束局数上限', style='Muted.TLabel').grid(row=0, column=0, sticky='w', padx=(0, d(12)))
    ui.currency_runs_entry = ttk.Entry(line, textvariable=ui.currency_runs, width=12)
    ui.currency_runs_entry.grid(row=0, column=1, sticky='w')
    ui.currency_until_points_check = ttk.Checkbutton(loop, text='本周积分满后停止', variable=ui.currency_until_points)
    ui.currency_until_points_check.grid(row=2, column=0, sticky='w')
    ui.currency_continue_defeat_check = ttk.Checkbutton(loop, text='已核实失败结算后继续', variable=ui.currency_continue_after_defeat)
    ui.currency_continue_defeat_check.grid(row=3, column=0, sticky='w', pady=(d(8), 0))
    ui.setting_controls.extend((ui.currency_runs_entry, ui.currency_until_points_check, ui.currency_continue_defeat_check))
    note(loop, '0表示直到停止；失败局也占上限，积分达标不自动领奖。\n新循环沿用“标准开发”页本次选项，以上选择不保存。', row=4, scale=s)
    buttons(loop, 5, (('新建开发循环', ui._currency_loop, 'currency_loop_button'),
                     ('接续原循环', lambda: ui._currency_loop(resume=True), 'currency_loop_resume_button')))
    note(loop, '接续沿用原上限、策略及选项，不读取新草稿。未知记录保留。', row=6, scale=s)

    rewards = ui.currency_sections['rewards']
    ttk.Label(rewards, text='积分核对与普通领奖', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
    note(rewards, '准备并导航至货币主页；准备阶段可能领取已有登录补给。\n核对积分不新开局，也不领取积分奖励。', row=1, scale=s)
    buttons(rewards, 2, (('核对当前积分', ui._currency_points, 'currency_points_button'),
                        ('领取当前积分奖励', ui._currency_rewards, 'currency_rewards_button'),
                        ('接续原领奖记录', lambda: ui._currency_rewards(resume=True), 'currency_rewards_resume_button')))
    note(rewards, '领奖只处理当前可领奖励；助燃券满额会停止，不清理。\n接续按原记录核对；未知输入不重放，仅补存时不访问游戏。', row=3, scale=s)
