"""Star Rail's guide hierarchy adapted to AutoHSR's existing operations."""
from __future__ import annotations

from tkinter import ttk

from . import theme as t
from .game_widgets import Header, TaskBoard, TrainingMeter

NAVIGATION = (("home", "每日实训", "01"), ("tasks", "生存索引", "02"),
              ("differential_universe", "差分宇宙", "03"), ("currency_wars", "货币战争", "04"),
              ("logs", "运行记录", "05"), ("settings", "设置", "06"))


def heading(parent, title, subtitle, scale):
    d = lambda n: round(n*scale)
    box = ttk.Frame(parent)
    box.grid(row=0, column=0, sticky="ew", pady=(0, d(16)))
    box.columnconfigure(0, weight=1)
    ttk.Label(box, text=title, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
    t.wrapped_label(box, text=subtitle, style="Hint.TLabel").grid(row=1, column=0, sticky="ew", pady=(d(4), 0))


def card(parent, row, scale, *, column=0, title=None):
    d = lambda n: round(n*scale)
    frame = ttk.Frame(parent, style="Card.TFrame", padding=d(16))
    frame.grid(row=row, column=column, sticky="nsew", pady=(0, d(12)))
    frame.columnconfigure(0, weight=1)
    if title:
        ttk.Label(frame, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, d(10)))
    return frame


def note(parent, text=None, variable=None, *, row, style="CardHint.TLabel", scale=1):
    args = dict(textvariable=variable) if variable is not None else dict(text=text)
    label = t.wrapped_label(parent, style=style, **args)
    label.grid(row=row, column=0, sticky="ew", pady=(round(5*scale), 0))
    return label


def build_window(ui, task_names, server_names):
    root = ui.root
    ui.ui_scale = max(1., float(root.tk.call("tk", "scaling"))/(96/72))
    s = ui.ui_scale
    d = lambda n: round(n*s)
    width, height = min(d(1280), root.winfo_screenwidth()-d(32)), min(d(880), root.winfo_screenheight()-d(55))
    root.geometry(f"{width}x{height}")
    root.minsize(min(d(1100), width), min(d(800), height))
    root.title("AutoHSR · 开拓指南")
    root.configure(bg=t.BG)
    ui.style = t.apply_theme(root, s)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)
    Header(root, s).grid(row=0, column=0, sticky="ew")
    shell = ttk.Frame(root, style="Rail.TFrame")
    shell.grid(row=1, column=0, sticky="nsew", padx=d(18))
    shell.columnconfigure(1, weight=1)
    shell.rowconfigure(0, weight=1)
    rail = ttk.Frame(shell, style="Rail.TFrame", width=d(176), padding=(d(10), d(20)))
    rail.grid(row=0, column=0, sticky="ns")
    rail.grid_propagate(False)
    rail.columnconfigure(0, weight=1)
    rail.rowconfigure(7, weight=1)
    ttk.Label(rail, text="开 拓 指 南", style="Rail.TLabel").grid(row=0, column=0, sticky="w", padx=d(12), pady=(0, d(20)))
    ui.nav_buttons = {}
    for row, (key, label, number) in enumerate(NAVIGATION, 1):
        button = ttk.Button(rail, text=number+"   "+label, style="Nav.TButton", command=lambda key=key: ui._show_page(key))
        button.grid(row=row, column=0, sticky="ew", pady=d(4))
        ui.nav_buttons[key] = button
    ttk.Label(rail, text="F9   暂停 / 继续\nF10 停止", style="Rail.TLabel", justify="left").grid(row=8, column=0, sticky="sw", padx=d(12), pady=d(12))
    ttk.Label(rail, text="AutoHSR  /  0.1", style="Rail.TLabel").grid(row=9, column=0, sticky="w", padx=d(12))
    body = ttk.Frame(shell, padding=(d(26), d(21)))
    body.grid(row=0, column=1, sticky="nsew")
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    ui.pages = {key: ttk.Frame(body) for key in ui.nav_buttons}
    for page in ui.pages.values():
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
    ui.server_combo = None
    _home(ui, task_names)
    _tasks(ui, task_names)
    from .desktop_modes import build_currency, build_universe
    build_universe(ui)
    build_currency(ui)
    _logs(ui)
    _settings(ui)
    _footer(ui)
    ui._show_page("home")


def _home(ui, names):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["home"]
    heading(page, "每日实训", "本次计划  /  持续委托 → 副本挑战 → 实训奖励 → 收尾奖励", s)
    ui.training_meter = TrainingMeter(page, s, ui.training_result)
    ui.training_meter.grid(row=1, column=0, sticky="ew", pady=(0, d(12)))
    ui.table = TaskBoard(page, s, ui, names)
    ui.table.grid(row=2, column=0, sticky="nsew", pady=(0, d(8)))
    page.rowconfigure(2, weight=1, minsize=d(200))
    plan = card(page, 4, s)
    plan.columnconfigure(1, weight=1)
    ttk.Label(plan, text="本次计划", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Button(plan, text="编辑计划  ›", command=lambda: ui._show_page("tasks")).grid(row=0, column=1, sticky="e")
    label = t.wrapped_label(plan, textvariable=ui.plan, style="CardHint.TLabel")
    label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(d(8), 0))
    recovery = t.wrapped_label(plan, textvariable=ui.recovery_hint, style="Warning.TLabel")
    recovery.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(d(6), 0))
    token = ui.recovery_hint.trace_add("write", lambda *_: recovery.grid() if ui.recovery_hint.get() else recovery.grid_remove())
    recovery.bind("<Destroy>", lambda event: ui.recovery_hint.trace_remove("write", token) if event.widget is recovery else None, add="+")
    recovery.grid_remove()


def _tasks(ui, names):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["tasks"]
    heading(page, "生存索引", "设置本次每日计划 · 临时修改可直接运行，点击「保存设置」后才会保存。", s)
    columns = ttk.Frame(page)
    columns.grid(row=1, column=0, sticky="nsew")
    page.rowconfigure(1, weight=1)
    columns.columnconfigure(0, weight=0, minsize=d(248))
    columns.columnconfigure(1, weight=1)
    columns.rowconfigure(0, weight=1)
    tasks = ttk.Frame(columns, style="Card.TFrame", padding=d(16))
    tasks.grid(row=0, column=0, sticky="nsew", padx=(0, d(16)))
    tasks.columnconfigure(0, weight=1)
    ttk.Label(tasks, text="执行任务", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, d(16)))
    ui.task_controls = {}
    for row, (key, label) in enumerate(names.items(), 1):
        if key == "mail":
            ttk.Separator(tasks).grid(row=5, column=0, sticky="ew", pady=d(14))
            ttk.Label(tasks, text="收尾奖励", style="Muted.TLabel").grid(row=6, column=0, sticky="w", pady=(0, d(8)))
        index = row if row < 4 else row+3
        check = ttk.Checkbutton(tasks, text=label, variable=ui.tasks[key], style="Card.TCheckbutton")
        check.grid(row=index, column=0, sticky="w", pady=d(9))
        ui.task_controls[key] = check
        ui.setting_controls.append(check)
        if key == "battle":
            ui.battle_checkbox = check
    tasks.rowconfigure(10, weight=1)
    note(tasks, "按所列顺序执行\n仅补领奖可从底部入口运行。", row=11, scale=s)
    specific = ttk.Frame(columns, style="Card.TFrame", padding=d(16))
    specific.grid(row=0, column=1, sticky="nsew")
    ui._build_battle_fields(specific)


def _logs(ui):
    s = ui.ui_scale
    page = ui.pages["logs"]
    heading(page, "运行记录", "查看本次执行、窗口检测和原始报告；历史结果保留原始时间与来源。", s)
    page.rowconfigure(1, weight=1)
    ui.output_tabs = ttk.Notebook(page)
    ui.output_tabs.grid(row=1, column=0, sticky="nsew")
    ui.log = ui._text_tab("运行日志")
    ui.inspection_text = ui._text_tab("窗口检测")
    ui.report_text = ui._text_tab("运行报告")
    for level, color in (("error", t.ERROR), ("warning", t.WARNING), ("success", t.SUCCESS)):
        ui.log.tag_configure(level, foreground=color)
    files = ttk.Frame(page)
    files.grid(row=2, column=0, sticky="ew", pady=(round(10*s), 0))
    ui.report_button = ttk.Button(files, text="打开报告", command=lambda: ui._open_path(ui.last_report_file))
    ui.screenshot_button = ttk.Button(files, text="查看截图", command=lambda: ui._open_path(ui.last_screenshot))
    ui.directory_button = ttk.Button(files, text="运行目录", command=lambda: ui._open_path(ui.last_run_dir))
    for button in (ui.report_button, ui.screenshot_button, ui.directory_button):
        button.pack(side="left", padx=(0, round(10*s)))
    ui.details_button = ui.screenshot_button
    note(page, variable=ui.history_context, row=3, style="Hint.TLabel", scale=s)


def _settings(ui):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["settings"]
    heading(page, "设置", "连接游戏、调整运行偏好与识别参数。", s)
    tabs = ttk.Notebook(page)
    tabs.grid(row=1, column=0, sticky="nsew")
    page.rowconfigure(1, weight=1)
    ui.settings_tabs = tabs
    ui.settings_sections = {}
    for key, name in (("game", "游戏连接"), ("run", "运行偏好"), ("recognition", "识别与等待"), ("admin", "管理员启动")):
        section = ttk.Frame(tabs, style="Card.TFrame", padding=d(20))
        section.columnconfigure(1, weight=1)
        tabs.add(section, text=name)
        ui.settings_sections[key] = section
    game = ui.settings_sections["game"]
    ttk.Label(game, text="游戏程序", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, d(18)))
    ttk.Label(game, text="StarRail.exe", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, d(14)))
    entry = ttk.Entry(game, textvariable=ui.game_path, width=15)
    entry.grid(row=1, column=1, sticky="ew")
    browse = ttk.Button(game, text="浏览…", command=ui._choose_game)
    browse.grid(row=1, column=2, padx=(d(10), 0))
    for row, text, variable in ((2, "开始每日时自动检查游戏，并按需启动或返回主界面。", None),
                                (3, None, ui.readiness), (4, "使用游戏当前登录状态；登录验证与更新请在游戏中完成。", None)):
        label = t.wrapped_label(game, textvariable=variable, style="CardHint.TLabel") if variable else t.wrapped_label(game, text=text, style="CardHint.TLabel")
        label.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(d(18), 0))
    ui.setting_controls.extend((entry, browse))
    run = ui.settings_sections["run"]
    ttk.Label(run, text="运行偏好", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, d(16)))
    ui.overlay_control = ttk.Checkbutton(run, text="在游戏前台显示日志字幕", variable=ui.overlay_logs)
    ui.overlay_control.grid(row=1, column=0, columnspan=2, sticky="w", pady=d(8))
    synthesis = ttk.Checkbutton(run, text="实训需要时合成 1 个奇巧零食", variable=ui.daily_synthesis)
    synthesis.grid(row=2, column=0, columnspan=2, sticky="w", pady=d(8))
    label = t.wrapped_label(run, text="合成仅在明确未完成的实训任务下执行；仅补领奖时不合成。\n任务结束后保留游戏。", style="CardHint.TLabel")
    label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=d(16))
    ui.setting_controls.extend((ui.overlay_control, synthesis))
    recognition = ui.settings_sections["recognition"]
    ttk.Label(recognition, text="识别与等待", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, d(16)))
    for row, (label, variable) in enumerate((("操作间隔（秒）", ui.action_delay), ("战斗超时（秒）", ui.battle_timeout), ("OCR 阈值", ui.ocr_confidence)), 1):
        ttk.Label(recognition, text=label).grid(row=row, column=0, sticky="w", pady=d(12), padx=(0, d(25)))
        field = ttk.Entry(recognition, textvariable=variable, width=10)
        field.grid(row=row, column=1, sticky="w")
        ui.setting_controls.append(field)
    admin = ui.settings_sections["admin"]
    ttk.Label(admin, text="管理员免重复确认启动", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, d(16)))
    label = t.wrapped_label(admin, textvariable=ui.admin_launch_status, style="CardHint.TLabel")
    label.grid(row=1, column=0, columnspan=2, sticky="ew")
    actions = ttk.Frame(admin, style="Card.TFrame")
    actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=d(18))
    for label, action in (("启用（首次授权）", "enable"), ("移除授权", "disable"), ("刷新状态", "status")):
        button = ttk.Button(actions, text=label, command=lambda action=action: ui._admin_operation(action))
        button.pack(side="left", padx=(0, d(10)))
        ui.setting_controls.append(button)
    label = t.wrapped_label(admin, text="仅绑定当前账户和本软件目录；首次需 Windows 授权，移动目录后需重新启用。", style="CardHint.TLabel")
    label.grid(row=3, column=0, columnspan=2, sticky="ew")
    note(page, "配置位置："+str(ui.config_path), row=2, style="Hint.TLabel", scale=s)


def _footer(ui):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    footer = ttk.Frame(ui.root, style="Footer.TFrame", padding=(d(28), d(12)))
    footer.grid(row=2, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    ui.summary_label = t.wrapped_label(footer, textvariable=ui.summary, style="FooterStatus.TLabel")
    ui.summary_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, d(8)))
    metrics = ttk.Frame(footer, style="Footer.TFrame")
    metrics.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, d(8)))
    for label, variable in (("状态", ui.status), ("已确认开拓力", ui.stamina), ("用时", ui.elapsed)):
        ttk.Label(metrics, text=label, style="Footer.TLabel").pack(side="left", padx=(0, d(8)))
        ttk.Label(metrics, textvariable=variable, style="FooterStatus.TLabel").pack(side="left", padx=(0, d(22)))
    ui.save_label = ttk.Label(metrics, textvariable=ui.save_status, style="Footer.TLabel")
    ui.save_label.pack(side="right")
    left = ttk.Frame(footer, style="Footer.TFrame")
    left.grid(row=2, column=0, sticky="w")
    ui.save_button = ttk.Button(left, text="保存设置", style="Footer.TButton", command=ui._save_settings)
    ui.check_button = ttk.Button(left, text="检测窗口", style="Footer.TButton", command=ui._check)
    ui.launch_button = ttk.Button(left, text="进入游戏", style="Footer.TButton", command=ui._launch)
    ui.reward_button = ttk.Button(left, text="仅补领奖", style="Footer.TButton", command=ui._reward_only)
    for button in (ui.save_button, ui.check_button, ui.launch_button, ui.reward_button):
        button.pack(side="left", padx=(0, d(8)))
    ui.setting_controls.append(ui.save_button)
    right = ttk.Frame(footer, style="Footer.TFrame")
    right.grid(row=2, column=1, sticky="e")
    ui.pause_button = ttk.Button(right, text="暂停 F9", style="Footer.TButton", command=ui._pause)
    ui.stop_button = ttk.Button(right, text="停止 F10", style="Danger.TButton", command=ui._stop)
    ui.start_button = ttk.Button(right, text="开始每日", style="Accent.TButton", command=ui._start)
    for button in (ui.pause_button, ui.stop_button, ui.start_button):
        button.pack(side="left", padx=(d(8), 0))
