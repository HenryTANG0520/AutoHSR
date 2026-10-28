"""The game's guide book, native page hierarchy and concise operational controls."""
from __future__ import annotations

from tkinter import ttk

from . import theme as t
from .game_widgets import ActivityStrip, Guide, Header, SummaryStrip, TaskBoard, TrainingMeter

PAGE_TITLES = {"home": "每日实训", "tasks": "生存索引", "differential_universe": "旷宇纷争",
               "currency_wars": "旷宇纷争", "logs": "运行记录", "settings": "设置"}


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
    width, height = min(d(1536), root.winfo_screenwidth()-d(32)), min(d(864), root.winfo_screenheight()-d(55))
    root.geometry(f"{width}x{height}")
    root.minsize(min(d(1100), width), min(d(800), height))
    root.title("AutoHSR · 开拓指南")
    root.configure(bg=t.BG)
    ui.style = t.apply_theme(root, s)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)
    ui.header = Header(root, s, ui)
    ui.header.grid(row=0, column=0, sticky="ew")
    ui.guide = Guide(root, s, ui)
    ui.guide.grid(row=1, column=0, sticky="nsew", padx=d(18))
    root.bind("<Configure>", lambda e: ui.guide.grid_configure(padx=max(d(18), round((e.width-d(1280))/2))) if e.widget is root else None, add="+")
    body = ui.guide.content
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    ui.nav_buttons = {key: ui.guide.buttons["universe" if key in ("differential_universe", "currency_wars") else key]
                      for key in PAGE_TITLES}
    ui.pages = {key: ttk.Frame(body) for key in PAGE_TITLES}
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
    ui.training_meter = TrainingMeter(page, s, ui.training_result)
    ui.training_meter.grid(row=0, column=0, sticky="ew", pady=(0, d(10)))
    ui.table = TaskBoard(page, s, ui, names)
    ui.table.grid(row=1, column=0, sticky="nsew")
    page.rowconfigure(1, weight=1, minsize=d(250))
    recovery = t.wrapped_label(page, textvariable=ui.recovery_hint, style="Hint.TLabel")
    recovery.grid(row=3, column=0, sticky="ew", pady=(d(8), 0))
    token = ui.recovery_hint.trace_add("write", lambda *_: recovery.grid() if ui.recovery_hint.get() else recovery.grid_remove())
    recovery.bind("<Destroy>", lambda event: ui.recovery_hint.trace_remove("write", token) if event.widget is recovery else None, add="+")
    recovery.grid_remove()


def _tasks(ui, names):
    from .dungeons import CATEGORIES
    from .dungeon_ui import select_category
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["tasks"]
    page.rowconfigure(0, weight=1)
    page.columnconfigure(0, weight=0, minsize=d(232))
    page.columnconfigure(1, weight=1)
    menu = ttk.Frame(page)
    menu.grid(row=0, column=0, sticky="ns", padx=(0, d(24)))
    menu.columnconfigure(0, weight=1)
    ui.category_buttons = {}
    def choose(category):
        ui.dungeon_category.set(category.label)
        select_category(ui)
    def selected(*_):
        for label, button in ui.category_buttons.items():
            button.configure(style="Selected.Option.TButton" if label == ui.dungeon_category.get() else "Option.TButton")
    for row, category in enumerate(CATEGORIES):
        button = ttk.Button(menu, text=category.label, style="Option.TButton", command=lambda category=category: choose(category))
        button.grid(row=row, column=0, sticky="ew", pady=(0, d(10)))
        ui.category_buttons[category.label] = button
        ui.setting_controls.append(button)
        ui.stamina_controls.append(button)
    token = ui.dungeon_category.trace_add("write", selected)
    menu.bind("<Destroy>", lambda e: ui.dungeon_category.trace_remove("write", token) if e.widget is menu else None, add="+")
    selected()
    content = ttk.Frame(page, style="Card.TFrame", padding=d(18))
    content.grid(row=0, column=1, sticky="nsew")
    content.columnconfigure(0, weight=1)
    specific = ttk.Frame(content, style="Card.TFrame")
    specific.grid(row=0, column=0, sticky="ew")
    ui._build_battle_fields(specific)
    ttk.Separator(content).grid(row=1, column=0, sticky="ew", pady=d(10))
    tasks = ttk.Frame(content, style="Card.TFrame")
    tasks.grid(row=2, column=0, sticky="ew")
    ttk.Label(tasks, text="每日任务", style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, d(3)))
    ui.task_controls = {}
    for index, (key, label) in enumerate(names.items()):
        check = ttk.Checkbutton(tasks, text=label, variable=ui.tasks[key], style="Card.TCheckbutton")
        check.grid(row=1+index//3, column=index%3, sticky="w", padx=(0, d(14)))
        ui.task_controls[key] = check
        ui.setting_controls.append(check)
        if key == "battle":
            ui.battle_checkbox = check


def _logs(ui):
    s = ui.ui_scale
    page = ui.pages["logs"]
    page.rowconfigure(0, weight=1)
    ui.output_tabs = ttk.Notebook(page)
    ui.output_tabs.grid(row=0, column=0, sticky="nsew")
    ui.log = ui._text_tab("运行日志")
    ui.inspection_text = ui._text_tab("窗口检测")
    ui.report_text = ui._text_tab("运行报告")
    for level, color in (("error", t.ERROR), ("warning", t.WARNING), ("success", t.SUCCESS)):
        ui.log.tag_configure(level, foreground=color)
    files = ttk.Frame(page)
    files.grid(row=1, column=0, sticky="ew", pady=(round(10*s), 0))
    ui.report_button = ttk.Button(files, text="打开报告", command=lambda: ui._open_path(ui.last_report_file))
    ui.screenshot_button = ttk.Button(files, text="查看截图", command=lambda: ui._open_path(ui.last_screenshot))
    ui.directory_button = ttk.Button(files, text="运行目录", command=lambda: ui._open_path(ui.last_run_dir))
    for button in (ui.report_button, ui.screenshot_button, ui.directory_button):
        button.configure(style="Panel.TButton")
        button.pack(side="left", padx=(0, round(10*s)))
    ui.details_button = ui.screenshot_button
    note(page, variable=ui.history_context, row=2, style="Hint.TLabel", scale=s)


def _settings(ui):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["settings"]
    page.columnconfigure(0, weight=0)
    page.columnconfigure(1, weight=1)
    page.rowconfigure(0, weight=1)
    menu = ttk.Frame(page)
    menu.grid(row=0, column=0, sticky="ns", padx=(0, d(24)))
    tabs = ttk.Notebook(page, style="Hidden.TNotebook")
    tabs.grid(row=0, column=1, sticky="nsew")
    ui.settings_tabs = tabs
    ui.settings_sections = {}
    buttons = {}
    for row, (key, name) in enumerate((("game", "游戏连接"), ("weekly", "周常计划"), ("run", "运行偏好"), ("recognition", "识别与等待"), ("admin", "管理员启动"))):
        section = ttk.Frame(tabs, style="Card.TFrame", padding=d(20))
        section.columnconfigure(1, weight=1)
        tabs.add(section, text=name)
        ui.settings_sections[key] = section
        button = ttk.Button(menu, text=name, style="Option.TButton",
                            command=ui._show_weekly_plan if key == "weekly" else lambda section=section: tabs.select(section), width=13)
        button.grid(row=row, column=0, sticky="ew", pady=(0, d(10)))
        buttons[str(section)] = button
    tabs.bind("<<NotebookTabChanged>>", lambda _: [button.configure(style="Selected.Option.TButton" if str(tabs.select())==key else "Option.TButton") for key, button in buttons.items()])
    game = ui.settings_sections["game"]
    ttk.Label(game, text="StarRail.exe", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, d(14)))
    entry = ttk.Entry(game, textvariable=ui.game_path, width=15)
    ui.game_path_entry = entry
    entry.grid(row=0, column=1, sticky="ew")
    browse = ttk.Button(game, text="浏览…", command=ui._choose_game)
    browse.grid(row=0, column=2, padx=(d(10), 0))
    label = t.wrapped_label(game, textvariable=ui.readiness, style="CardHint.TLabel")
    label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(d(18), 0))
    label = t.wrapped_label(game, text="登录验证与更新需在游戏内完成。", style="CardHint.TLabel")
    label.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(d(10), 0))
    ui.setting_controls.extend((entry, browse))
    connection = ttk.Frame(game, style="Card.TFrame")
    connection.grid(row=3, column=0, columnspan=3, sticky="w", pady=d(18))
    ui.check_button = ttk.Button(connection, text="检测窗口", command=ui._check)
    ui.launch_button = ttk.Button(connection, text="进入游戏", command=ui._launch)
    for button in (ui.check_button, ui.launch_button):
        button.pack(side="left", padx=(0, d(10)))
        ui.setting_controls.append(button)
    weekly = ui.settings_sections["weekly"]
    enable = ttk.Checkbutton(weekly, text="启用周常", variable=ui.weekly_enabled)
    enable.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, d(14)))
    ui.setting_controls.append(enable)
    from .weekly_plan import DAYS, MODES
    for row, label, variable, choices, name in (
            (1, "玩法", ui.weekly_mode, tuple(MODES.values()), "weekly_mode_combo"),
            (2, "每周", ui.weekly_day, DAYS, "weekly_day_combo"),
            (4, "演算局数", ui.weekly_runs, tuple(str(n) for n in range(1, 11)), "weekly_runs_combo")):
        caption = ttk.Label(weekly, text=label)
        caption.grid(row=row, column=0, sticky="w", padx=(0, d(20)), pady=d(9))
        combo = ttk.Combobox(weekly, textvariable=variable, values=choices, width=15, state="readonly")
        combo.grid(row=row, column=1, sticky="w")
        setattr(ui, name, combo)
        ui.setting_controls.append(combo)
        if name == "weekly_runs_combo":
            ui.weekly_run_controls = (caption, combo)
    ttk.Label(weekly, text="时间").grid(row=3, column=0, sticky="w", pady=d(9))
    time_row = ttk.Frame(weekly, style="Card.TFrame")
    time_row.grid(row=3, column=1, columnspan=2, sticky="w")
    field = ttk.Entry(time_row, textvariable=ui.weekly_time, width=15)
    ui.weekly_time_entry = field
    field.pack(side="left")
    ttk.Label(time_row, text="HH:MM · 北京时间", style="Muted.TLabel").pack(side="left", padx=d(10))
    ui.setting_controls.append(field)
    team_label = ttk.Label(weekly, text="预设编队")
    team_label.grid(row=5, column=0, sticky="w", pady=d(9))
    ui.weekly_team_entry = ttk.Entry(weekly, textvariable=ui.du_team, width=15)
    ui.weekly_team_entry.grid(row=5, column=1, sticky="w")
    ui.weekly_run_controls += (team_label, ui.weekly_team_entry)
    ui.setting_controls.append(ui.weekly_team_entry)
    for row, text, variable in ((6, "到期后随“开始计划”执行；每周一 04:00 刷新。", None),
                                (7, None, ui.weekly_boundary)):
        label = t.wrapped_label(weekly, text=text, textvariable=variable, style="CardHint.TLabel")
        label.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(d(16), 0))
    run = ui.settings_sections["run"]
    ui.overlay_control = ttk.Checkbutton(run, text="游戏内日志字幕", variable=ui.overlay_logs)
    ui.overlay_control.grid(row=0, column=0, columnspan=2, sticky="w", pady=d(8))
    synthesis = ttk.Checkbutton(run, text="实训需要时合成 1 个奇巧零食", variable=ui.daily_synthesis)
    synthesis.grid(row=1, column=0, columnspan=2, sticky="w", pady=d(8))
    label = t.wrapped_label(run, text="消耗两种普通材料各 1 个；仅补领奖时不合成。", style="CardHint.TLabel")
    label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=d(6))
    ui.setting_controls.extend((ui.overlay_control, synthesis))
    recognition = ui.settings_sections["recognition"]
    for row, (label, variable, limits) in enumerate((("操作间隔（秒）", ui.action_delay, "0.3～5"), ("战斗超时（秒）", ui.battle_timeout, "60～3600"), ("OCR 阈值", ui.ocr_confidence, "0.4～0.99"))):
        ttk.Label(recognition, text=label).grid(row=row, column=0, sticky="w", pady=d(12), padx=(0, d(25)))
        field = ttk.Entry(recognition, textvariable=variable, width=10)
        setattr(ui, ("action_delay_entry", "battle_timeout_entry", "ocr_confidence_entry")[row], field)
        field.grid(row=row, column=1, sticky="w")
        ttk.Label(recognition, text=limits, style="Muted.TLabel").grid(row=row, column=2, sticky="w", padx=d(12))
        ui.setting_controls.append(field)
    admin = ui.settings_sections["admin"]
    label = t.wrapped_label(admin, textvariable=ui.admin_launch_status, style="CardHint.TLabel")
    label.grid(row=0, column=0, columnspan=2, sticky="ew")
    actions = ttk.Frame(admin, style="Card.TFrame")
    actions.grid(row=1, column=0, columnspan=2, sticky="w", pady=d(18))
    for label, action in (("启用授权", "enable"), ("移除授权", "disable"), ("刷新状态", "status")):
        button = ttk.Button(actions, text=label, command=lambda action=action: ui._admin_operation(action))
        button.pack(side="left", padx=(0, d(10)))
        ui.setting_controls.append(button)
    label = t.wrapped_label(admin, text="首次需 Windows 授权；仅绑定当前账户和目录，移动目录后需重新启用。", style="CardHint.TLabel")
    label.grid(row=2, column=0, columnspan=2, sticky="ew")
    location = t.wrapped_label(page, text="配置位置："+str(ui.config_path), style="Hint.TLabel")
    location.grid(row=1, column=1, sticky="ew", pady=(d(8), 0))


def _footer(ui):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    footer = ttk.Frame(ui.root, style="Footer.TFrame", padding=(d(42), d(7), d(42), d(18)))
    footer.grid(row=2, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    ui.summary_label = SummaryStrip(footer, s, ui)
    ui.summary_label.grid(row=0, column=0, columnspan=2, sticky="ew")
    def summary_visibility(*_):
        ui.summary_label.grid() if ui.summary_label.message() else ui.summary_label.grid_remove()
    tokens = [(v, v.trace_add("write", summary_visibility)) for v in (ui.summary, ui.input_error, ui.result_alert)]
    footer.bind("<Destroy>", lambda e: [v.trace_remove("write", token) for v, token in tokens] if e.widget is footer else None, add="+")
    summary_visibility()
    metrics = ttk.Frame(footer, style="Footer.TFrame")
    metrics.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, d(9)))
    metrics.columnconfigure(0, weight=1)
    ui.activity_label = ActivityStrip(metrics, s, ui.activity)
    ui.activity_label.grid(row=0, column=0, sticky="ew", padx=(0, d(18)))
    ui.save_label = ttk.Label(metrics, textvariable=ui.save_status, style="Footer.TLabel")
    ui.save_label.grid(row=0, column=1, sticky="e")
    left = ttk.Frame(footer, style="Footer.TFrame")
    left.grid(row=2, column=0, sticky="w")
    ui.save_button = ttk.Button(left, text="保存设置", style="Footer.TButton", command=ui._save_settings)
    ui.reward_button = ttk.Button(left, text="仅补领奖", style="Footer.TButton", command=ui._reward_only)
    for button in (ui.save_button, ui.reward_button):
        button.pack(side="left", padx=(0, d(8)))
    ui.setting_controls.append(ui.save_button)
    right = ttk.Frame(footer, style="Footer.TFrame")
    right.grid(row=2, column=1, sticky="e")
    ui.pause_button = ttk.Button(right, text="暂停 F9", style="Footer.TButton", command=ui._pause)
    ui.stop_button = ttk.Button(right, text="停止 F10", style="Danger.TButton", command=ui._stop)
    ui.start_button = ttk.Button(right, text="开始计划", style="Accent.TButton", width=16, command=lambda: ui._start(run_plan=True))
    for button in (ui.pause_button, ui.stop_button, ui.start_button):
        button.pack(side="left", padx=(d(8), 0))
