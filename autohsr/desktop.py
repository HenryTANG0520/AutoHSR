"""The game's guide book, native page hierarchy and concise operational controls."""
from __future__ import annotations

from tkinter import ttk

from . import theme as t
from .game_widgets import ActivityStrip, Backdrop, Guide, Header, SummaryStrip, TaskBoard, TrainingMeter

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
    ui.backdrop = Backdrop(root, s)
    ui.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
    root.tk.call("lower", str(ui.backdrop))
    ui.header = Header(root, s, ui)
    ui.header.grid(row=0, column=0, sticky="ew")
    ui.guide = Guide(root, s, ui)
    ui.guide.grid(row=1, column=0, sticky="ew", padx=d(18))
    def position_guide(event=None):
        if (event is None or event.widget is root) and getattr(ui, "active_page", "home") != "settings":
            top_gap = min(d(38), max(0, round((root.winfo_height()-d(800))*38/64)))
            margin = max(d(18), round((root.winfo_width()-d(1280))/2))
            ui.guide.art_left = min(d(8), max(0, margin-d(2)))
            ui.guide.art_right = min(d(44), max(0, margin-d(2)))
            ui.guide.grid_configure(padx=(margin-ui.guide.art_left, margin-ui.guide.art_right), pady=(top_gap, 0))
            ui.guide._position()
            ui.guide.redraw()
    ui.position_guide = position_guide
    root.bind("<Configure>", position_guide, add="+")
    body = ui.guide.content
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    ui.nav_buttons = {key: ui.guide.buttons["universe" if key in ("differential_universe", "currency_wars") else key]
                      for key in PAGE_TITLES}
    ui.pages = {key: ttk.Frame(body) for key in PAGE_TITLES if key != "settings"}
    for page in ui.pages.values():
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
    ui.server_combo = None
    _home(ui, task_names)
    _tasks(ui, task_names)
    ui.mode_decks = {}
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
    ui.training_meter.grid(row=0, column=0, sticky="ew", pady=(0, d(4)))
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
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["tasks"]
    page.rowconfigure(0, weight=1)
    page.columnconfigure(0, weight=3, minsize=d(232), uniform="survival")
    page.columnconfigure(1, weight=7, uniform="survival")
    menu = ttk.Frame(page)
    menu.grid(row=0, column=0, sticky="nsew", padx=(0, d(24)))
    menu.columnconfigure(0, weight=1)
    ui.category_buttons = {}
    def choose(category):
        ui.dungeon_search.set("")
        ui.dungeon_browse_category.set(category.label)
        from .dungeon_ui import show_browser
        show_browser(ui)
    def selected(*_):
        for label, button in ui.category_buttons.items():
            button.configure(style="Selected.Option.TButton" if label == ui.dungeon_browse_category.get() else "Option.TButton")
    for row, category in enumerate(CATEGORIES):
        button = ttk.Button(menu, text=category.label, style="Option.TButton", command=lambda category=category: choose(category))
        button.grid(row=row, column=0, sticky="ew", pady=(0, d(10)))
        ui.category_buttons[category.label] = button
        ui.setting_controls.append(button)
        ui.stamina_controls.append(button)
    token = ui.dungeon_browse_category.trace_add("write", selected)
    menu.bind("<Destroy>", lambda e: ui.dungeon_browse_category.trace_remove("write", token) if e.widget is menu else None, add="+")
    selected()
    content = ttk.Frame(page, style="Card.TFrame", padding=d(18))
    content.grid(row=0, column=1, sticky="nsew")
    content.columnconfigure(0, weight=1)
    content.rowconfigure(0, weight=1)
    specific = ttk.Frame(content, style="Card.TFrame")
    specific.grid(row=0, column=0, sticky="nsew")
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
    from .desktop_settings import build_settings
    build_settings(ui)


def _footer(ui):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    footer = ttk.Frame(ui.root, style="Footer.TFrame", padding=(d(42), d(7), d(42), d(18)))
    footer.grid(row=2, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    feedback = ttk.Frame(footer, style="Footer.TFrame")
    feedback.grid(row=0, column=0, sticky="ew", padx=(0, d(18)))
    feedback.columnconfigure(0, weight=1)
    ui.summary_label = SummaryStrip(feedback, s, ui)
    ui.summary_label.grid(row=0, column=0, sticky="ew")
    ui.activity_label = ActivityStrip(feedback, s, ui.activity)
    ui.activity_label.grid(row=1, column=0, sticky="ew")
    def refresh_feedback(*_):
        # The open result owns its outcome. A different report, new error,
        # or active operation must still have its own visible footer feedback.
        result = ui.feedback_result
        deck = ui.mode_decks.get(getattr(ui, "active_page", ""))
        in_result = bool(result and deck and deck["shown"] == "result" and not ui.busy
                         and not ui.input_error.get() and ui.active_page == result[0]
                         and result[1:] == (ui.summary.get(), ui.result_alert.get(), ui.status.get()))
        has_summary = bool(ui.summary_label.message())
        ui.summary_label.grid() if has_summary and not in_result else ui.summary_label.grid_remove()
        has_activity = ui.busy or ui.activity.get() not in ("", "● 准备就绪")
        ui.activity_label.grid() if not in_result and has_activity and (ui.busy or not has_summary) else ui.activity_label.grid_remove()
    ui.refresh_feedback = refresh_feedback
    tokens = [(v, v.trace_add("write", refresh_feedback)) for v in (ui.summary, ui.input_error, ui.result_alert, ui.activity)]
    footer.bind("<Destroy>", lambda e: [v.trace_remove("write", token) for v, token in tokens] if e.widget is footer else None, add="+")
    refresh_feedback()
    left = ttk.Frame(footer, style="Footer.TFrame")
    left.grid(row=1, column=0, sticky="w", pady=(d(9), 0))
    ui.save_button = ttk.Button(left, text="保存设置", style="Footer.TButton", command=ui._save_settings)
    ui.reward_button = ttk.Button(left, text="仅补领奖", style="Footer.TButton", command=ui._reward_only)
    ui.save_label = ttk.Label(left, textvariable=ui.save_status, style="Footer.TLabel")
    ui.setting_controls.append(ui.save_button)
    right = ttk.Frame(footer, style="Footer.TFrame")
    right.grid(row=1, column=1, sticky="e", pady=(d(9), 0))
    ui.pause_button = ttk.Button(right, text="暂停 F9", style="Footer.TButton", command=ui._pause)
    ui.stop_button = ttk.Button(right, text="停止 F10", style="Danger.TButton", command=ui._stop)
    ui.footer_start_button = ttk.Button(right, text="开始计划", style="Accent.TButton", width=16, command=lambda: ui._start(run_plan=True))
    ui.start_button = ui.footer_start_button
    for button in (ui.pause_button, ui.stop_button, ui.start_button):
        button.pack(side="left", padx=(d(8), 0))
