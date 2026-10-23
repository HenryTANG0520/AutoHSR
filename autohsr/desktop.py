"""Common navigation and control structure; themes and game plans stay local."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def build_window(ui, task_names, server_names):
    root = ui.root
    hsr = ui.__class__.__name__ == "AutoHSRWindow"
    brand, subtitle = ("AutoHSR", "星穹铁道每日助手") if hsr else ("AutoZZZ", "绝区零每日助手")
    bg, panel, sidebar, text, muted, accent = (
        ("#0b1422", "#142237", "#101c2d", "#e5edf7", "#91a6bf", "#47d9ce") if hsr else
        ("#f5f5f5", "#ffffff", "#eeeeee", "#202020", "#686868", "#0067c0"))
    ui.ui_scale = max(1., float(root.tk.call("tk", "scaling")) / (96 / 72))
    d = lambda n: round(n * ui.ui_scale)
    width, height = min(d(1180), root.winfo_screenwidth() - 40), min(d(850), root.winfo_screenheight() - 70)
    root.geometry(f"{width}x{height}")
    root.minsize(min(d(1100), width), min(d(800), height))
    root.title(f"{brand} · {subtitle}")
    root.configure(bg=bg)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei UI", 10), background=bg, foreground=text)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=panel, foreground=text)
    style.configure("TButton", background="#253c56" if hsr else "white", foreground=text,
                    borderwidth=0, padding=(d(11), d(7)))
    style.map("TButton", background=[("active", "#345775" if hsr else "#e6edf3")],
              foreground=[("disabled", "#60758d" if hsr else "#969696")])
    style.configure("Accent.TButton", background=accent, foreground="#082829" if hsr else "white")
    style.map("Accent.TButton", background=[("disabled", "#23595d" if hsr else "#c8d7e5")])
    for name in ("Card.TFrame", "Panel.TFrame"):
        style.configure(name, background=panel)
    style.configure("Sidebar.TFrame", background=sidebar)
    style.configure("Sidebar.TLabel", background=sidebar, foreground=muted)
    style.configure("Brand.TLabel", background=sidebar, foreground=text, font=("Segoe UI", 18, "bold"))
    style.configure("Nav.TButton", background=sidebar, anchor="w", padding=(d(12), d(12)))
    style.configure("Selected.Nav.TButton", background="#253c56" if hsr else "#dceafb", foreground=accent)
    for name in ("Card.TLabel", "Section.TLabel", "Metric.TLabel"):
        style.configure(name, background=panel, foreground=text)
    style.configure("CardTitle.TLabel", background=panel, font=("Microsoft YaHei UI", 11, "bold"))
    for name in ("Hint.TLabel", "Subtitle.TLabel"):
        style.configure(name, background=bg, foreground=muted, font=("Microsoft YaHei UI", 9))
    for name in ("CardHint.TLabel", "Muted.TLabel"):
        style.configure(name, background=panel, foreground=muted, font=("Microsoft YaHei UI", 9))
    style.configure("Warning.TLabel", background=panel, foreground="#efc779" if hsr else "#986219")
    style.configure("PageTitle.TLabel", background=bg, font=("Microsoft YaHei UI", 24, "bold"))
    for name in ("TCheckbutton", "Card.TCheckbutton"):
        style.configure(name, background=panel, foreground=text, padding=(0, d(4)))
        style.map(name, background=[("active", panel)], foreground=[("disabled", muted)])
    if hsr:
        for name in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(name, fieldbackground="#1d2e46", foreground=text, insertcolor=text)
    style.configure("Treeview", background=panel, fieldbackground=panel, foreground=text, rowheight=d(29), borderwidth=0)
    style.configure("Treeview.Heading", background=sidebar, foreground=text, padding=d(6))
    style.configure("TNotebook", background=bg, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(d(15), d(8)))
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    shell = ttk.Frame(root)
    shell.grid(row=0, column=0, sticky="nsew")
    shell.columnconfigure(1, weight=1)
    shell.rowconfigure(0, weight=1)
    rail = ttk.Frame(shell, style="Sidebar.TFrame", width=d(185), padding=(d(12), d(22)))
    rail.grid(row=0, column=0, sticky="nsew")
    rail.grid_propagate(False)
    rail.columnconfigure(0, weight=1)
    rail.rowconfigure(8, weight=1)
    ttk.Label(rail, text=brand, style="Brand.TLabel").grid(row=0, column=0, sticky="w", padx=d(9))
    ttk.Label(rail, text=subtitle, style="Sidebar.TLabel").grid(row=1, column=0, sticky="w", padx=d(9), pady=(d(6), d(24)))
    ui.nav_buttons = {}
    navigation = [("home", "启动"), ("tasks", "每日任务")]
    if hsr:
        navigation.extend((("currency_wars", "货币战争"), ("differential_universe", "差分宇宙")))
    navigation.extend((("logs", "运行日志"), ("settings", "设置")))
    for row, (name, label) in enumerate(navigation, 2):
        button = ttk.Button(rail, text=label, style="Nav.TButton", command=lambda key=name: ui._show_page(key))
        button.grid(row=row, column=0, sticky="ew", pady=d(3))
        ui.nav_buttons[name] = button
    ttk.Label(rail, text="F9  暂停 / 继续\nF10  紧急停止", style="Sidebar.TLabel").grid(row=9, column=0, sticky="sw", pady=d(18))
    ttk.Label(rail, text="仅现有开拓力 · 每轮独立预算" if hsr else "非战斗每日 · 电量消耗 0",
              style="Sidebar.TLabel", font=("Microsoft YaHei UI", 8), wraplength=d(160)).grid(row=10, column=0, sticky="w")
    body = ttk.Frame(shell, padding=(d(24), d(17)))
    body.grid(row=0, column=1, sticky="nsew")
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    ui.pages = {name: ttk.Frame(body) for name in ui.nav_buttons}
    for page in ui.pages.values():
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)

    def heading(parent, title, hint):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, d(12)))
        ttk.Label(frame, text=title, style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=d(850)).pack(anchor="w", pady=(d(3), 0))

    def card(parent, row):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=d(12))
        frame.grid(row=row, column=0, sticky="ew", pady=(0, d(10)))
        return frame

    home = ui.pages["home"]
    home.rowconfigure(4, weight=1)
    heading(home, "启动", "核对本次计划后开始；检测和运行都不会自动保存设置。")
    game = card(home, 1)
    game.columnconfigure(1, weight=1)
    ui.server_combo = None
    if server_names:
        ttk.Label(game, text="区服", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, d(12)))
        ui.server_combo = ttk.Combobox(game, textvariable=ui.server, values=list(server_names.values()), state="readonly", width=10)
        ui.server_combo.grid(row=0, column=1, sticky="w")
        ui.server_combo.bind("<<ComboboxSelected>>", ui._select_server)
        ui.setting_controls.append(ui.server_combo)
    else:
        ttk.Label(game, text="账号以游戏中当前登录状态为准；不会自动填写登录信息。", style="CardHint.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(game, text="游戏路径", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, d(12)), pady=d(8))
    entry = ttk.Entry(game, textvariable=ui.game_path)
    entry.grid(row=1, column=1, sticky="ew", pady=d(8))
    browse = ttk.Button(game, text="浏览…", command=ui._choose_game)
    browse.grid(row=1, column=2, padx=(d(8), 0))
    auto = ttk.Checkbutton(game, text="开始每日前自动启动游戏", variable=ui.auto_launch, style="Card.TCheckbutton")
    auto.grid(row=2, column=0, columnspan=3, sticky="w")
    ui.setting_controls.extend((entry, browse, auto))
    ttk.Label(game, textvariable=ui.readiness, style="CardHint.TLabel", wraplength=d(830)).grid(row=3, column=0, columnspan=3, sticky="w", pady=(d(5), 0))
    ttk.Label(game, textvariable=ui.plan, style="CardHint.TLabel", wraplength=d(830)).grid(row=4, column=0, columnspan=3, sticky="w", pady=(d(7), 0))
    if hsr:
        ttk.Label(game, textvariable=ui.recovery_hint, style="Warning.TLabel", wraplength=d(830)).grid(row=5, column=0, columnspan=3, sticky="w", pady=(d(6), 0))
    metrics = ttk.Frame(home)
    metrics.grid(row=2, column=0, sticky="ew", pady=(0, d(10)))
    variables = (("任务状态", ui.status), ("本轮已确认开拓力", ui.stamina), ("运行时长", ui.elapsed)) if hsr else (("任务状态", ui.status), ("今日活跃度", ui.engagement), ("运行时长", ui.elapsed))
    for column, (label, variable) in enumerate(variables):
        metrics.columnconfigure(column, weight=1, uniform="metrics")
        panel_widget = ttk.Frame(metrics, style="Card.TFrame", padding=d(10))
        panel_widget.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else d(8), 0))
        ttk.Label(panel_widget, text=label, style="CardHint.TLabel").pack(anchor="w")
        ttk.Label(panel_widget, textvariable=variable, style="CardTitle.TLabel", wraplength=d(230)).pack(anchor="w", pady=(d(4), 0))
    ttk.Label(home, text="本次任务", style="Hint.TLabel").grid(row=3, column=0, sticky="w", pady=(0, d(7)))
    ui.table = ttk.Treeview(home, columns=("task", "status", "detail"), show="headings", height=6, selectmode="browse")
    for name, label, size in (("task", "任务", 210), ("status", "状态", 85), ("detail", "结果说明（点击查看）", 450)):
        ui.table.heading(name, text=label)
        ui.table.column(name, width=d(size), minwidth=d(60), stretch=name == "detail")
    ui.table.grid(row=4, column=0, sticky="nsew")
    for name, label in task_names.items():
        chosen = ui.tasks[name].get()
        ui.table.insert("", "end", iid=name, values=(label, "等待" if chosen else "跳过", "" if chosen else "未勾选"))
    for tag, color in (("ok", "#74d6b6" if hsr else "#14735d"), ("success", "#74d6b6"), ("failed", "#ffb6b6" if hsr else "#b33c40"), ("partial", "#efc779" if hsr else "#a5701c"), ("skipped", muted)):
        ui.table.tag_configure(tag, foreground=color)
    ui.table.bind("<<TreeviewSelect>>", ui._show_task_detail if hsr else ui._task_detail)

    tasks = ui.pages["tasks"]
    heading(tasks, "每日任务", "每次开始使用当前表单；仅补领奖不会刷本或改变已保存方案。")
    options = card(tasks, 1)
    for col in range(2):
        options.columnconfigure(col, weight=1)
    descriptions = ({"assignments": "领取奖励并保留原持续委托", "battle": "按明确地图和本次预算挑战", "daily": "核实500活跃与五档奖励", "mail": "核心领奖后领取已有附件", "battlepass": "领取已获得奖励，不购买等级"} if hsr else
                    {"scratch": "报刊亭刮卡或饼铺免费盲盒", "coffee": "仅领取每日免费饮品", "video": "按已拥有宣传员安排营业", "daily": "核实400活跃与四档奖励", "weekly": "领取已有任务和里程奖励", "city_fund": "领取成长任务及等级回馈"})
    for index, (name, label) in enumerate(task_names.items()):
        item = ttk.Frame(options, style="Card.TFrame")
        item.grid(row=index // 2, column=index % 2, sticky="ew", padx=d(6), pady=d(3))
        control = ttk.Checkbutton(item, text=label, variable=ui.tasks[name], style="Card.TCheckbutton")
        control.pack(anchor="w")
        ttk.Label(item, text=descriptions[name], style="CardHint.TLabel").pack(anchor="w", padx=d(22))
        ui.setting_controls.append(control)
        if name == "battle":
            ui.battle_checkbox = control
    specific = card(tasks, 2)
    if hsr:
        ui._build_battle_fields(specific)
    else:
        ttk.Label(specific, text="录像店宣传员（选填）", style="CardTitle.TLabel").pack(anchor="w")
        ui.promoter_entry = ttk.Entry(specific, textvariable=ui.promoter, width=28)
        ui.promoter_entry.pack(anchor="w", pady=d(9))
        ui.promoter_hint_label = ttk.Label(specific, textvariable=ui.promoter_hint, style="CardHint.TLabel", wraplength=d(800))
        ui.promoter_hint_label.pack(anchor="w")
        ui.setting_controls.append(ui.promoter_entry)
    if hsr:
        wars = ui.pages["currency_wars"]
        heading(wars, "货币战争", "局内决策 · 阵容、经济与装备；战斗使用游戏内自动战斗。")
        readiness = card(wars, 1)
        ttk.Label(readiness, text="决策算法 · 实机验证中", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(readiness, textvariable=ui.currency_status, style="Warning.TLabel", wraplength=d(810)).pack(anchor="w", pady=(d(6), 0))
        ttk.Label(readiness, text="整局验证会选择投资、购买角色、升级、部署和分配装备，再等待游戏自动战斗的结果。底部只读按钮只识别当前画面。",
                  style="CardHint.TLabel", wraplength=d(810)).pack(anchor="w", pady=(d(6), 0))
        drag_row = ttk.Frame(readiness, style="Card.TFrame")
        drag_row.pack(anchor="w", pady=(d(8), 0))
        ui.currency_drag_button = ttk.Button(drag_row, text="拖动验证：前台3→1（一次）", command=ui._currency_drag_test)
        ui.currency_drag_button.pack(side="left")
        ui.setting_controls.append(ui.currency_drag_button)
        ui.currency_deploy_button = ttk.Button(drag_row, text="部署验证：所选备战角色", command=ui._currency_deploy_test)
        ui.currency_deploy_button.pack(side="left", padx=(d(8), 0))
        ui.setting_controls.append(ui.currency_deploy_button)
        ui.currency_node_button = ttk.Button(drag_row, text="战斗验证：仅当前节点", command=ui._currency_node_test)
        ui.currency_node_button.pack(side="left", padx=(d(8), 0))
        ui.setting_controls.append(ui.currency_node_button)
        ui.currency_match_button=ttk.Button(drag_row,text='整局验证：超频A0',command=ui._currency_match_test)
        ui.currency_match_button.pack(side='left',padx=(d(8),0))
        ui.setting_controls.append(ui.currency_match_button)
        control_row = ttk.Frame(readiness, style='Card.TFrame')
        control_row.pack(anchor='w', pady=(d(6),0))
        for label, command in (('只读控制验收：截图后暂停', ui._currency_control_probe),
                               ('只读超时验收：0.05秒', ui._currency_timeout_probe)):
            button = ttk.Button(control_row, text=label, command=command)
            button.pack(side='left', padx=(0,d(8)))
            ui.setting_controls.append(button)
        placement_row=ttk.Frame(readiness,style='Card.TFrame')
        placement_row.pack(anchor='w',pady=(d(6),0))
        ttk.Label(placement_row,text='部署来源：备战区').pack(side='left')
        ui.currency_source_combo=ttk.Combobox(placement_row,textvariable=ui.currency_source_slot,values=tuple(map(str,range(1,10))),state='readonly',width=3)
        ui.currency_source_combo.pack(side='left',padx=d(6))
        ttk.Label(placement_row,text='目标：').pack(side='left')
        ui.currency_zone_combo=ttk.Combobox(placement_row,textvariable=ui.currency_zone,values=('后台','前台'),state='readonly',width=5)
        ui.currency_zone_combo.pack(side='left')
        ui.setting_controls.extend((ui.currency_source_combo,ui.currency_zone_combo))
        ui.currency_flow_button=ttk.Button(placement_row,text='流程验证：推进当前对局',command=ui._currency_flow_test)
        ui.currency_flow_button.pack(side='left',padx=(d(16),0))
        ui.setting_controls.append(ui.currency_flow_button)
        ttk.Label(placement_row,text='升级目标：').pack(side='left',padx=(d(10),0))
        ui.currency_level_combo=ttk.Combobox(placement_row,textvariable=ui.currency_target_level,
            values=('保持',)+tuple(map(str,range(1,11))),state='readonly',width=5)
        ui.currency_level_combo.pack(side='left')
        ui.setting_controls.append(ui.currency_level_combo)
        ttk.Label(readiness, text="流程验证会补位、领奖、整理备战副本，按已核实策略穿戴装备；结果不明即停。",
                  style="CardHint.TLabel", wraplength=d(810)).pack(anchor="w", pady=(d(5), 0))
        ttk.Label(readiness,text='整局验证：超频A0；按羁绊缺口和阵容评分购买，默认保留10金币。',
                  style='CardHint.TLabel',wraplength=d(810)).pack(anchor='w',pady=(d(4),0))
        strategy = card(wars, 2)
        ttk.Label(strategy, text="随机性与存钱策略", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(strategy, text="4.6 教程：标准博弈每持有10金币产生1利息，上限5；超频博弈不产生利息。\n部署容量以画面为准；Gemi 狸等特殊机制会改变槽位和代管行为。",
                  style="CardHint.TLabel", wraplength=d(810)).pack(anchor="w", pady=(d(5), 0))
        from .currency_wars import REVIEW_ITEMS
        ui.currency_review = ttk.Treeview(wars, columns=("item", "status"), show="headings", height=4, selectmode="none")
        ui.currency_review.heading("item", text="实机核实项目")
        ui.currency_review.heading("status", text="状态")
        ui.currency_review.column("item", width=d(490), stretch=True)
        ui.currency_review.column("status", width=d(150), stretch=False)
        ui.currency_review.grid(row=3, column=0, sticky="ew", pady=(0, d(10)))
        for key, label in REVIEW_ITEMS:
            ui.currency_review.insert("", "end", iid=key, values=(label, "部分验证" if key == "transitions" else "4.6 已采集"))
        ttk.Label(wars, textvariable=ui.currency_observation, style="Hint.TLabel", wraplength=d(830)).grid(row=4, column=0, sticky="ew")

        universe = ui.pages["differential_universe"]
        heading(universe, "差分宇宙", "独立运行模式 · 不读取或写入每日刷本预算 · 只在实机页面识别明确后推进。")
        setup = card(universe, 1)
        ttk.Label(setup, text="本次自动演算", style="CardTitle.TLabel").pack(anchor="w")
        run_row = ttk.Frame(setup, style="Card.TFrame")
        run_row.pack(anchor="w", pady=(d(8), d(4)))
        ttk.Label(run_row, text="局数（1–10）").pack(side="left")
        ui.du_runs_combo = ttk.Combobox(run_row, textvariable=ui.differential_universe_runs,
            values=tuple(map(str,range(1,11))), state="readonly", width=4)
        ui.du_runs_combo.pack(side="left", padx=(d(8), 0))
        ui.setting_controls.append(ui.du_runs_combo)
        team_row=ttk.Frame(setup,style="Card.TFrame")
        team_row.pack(anchor="w",pady=(d(4),d(4)))
        ttk.Label(team_row,text="模式").pack(side="left")
        ui.du_mode_combo=ttk.Combobox(team_row,textvariable=ui.du_mode,
            values=('周期演算','常规演算'),state="readonly",width=10)
        ui.du_mode_combo.pack(side="left",padx=(d(8),d(12)))
        ttk.Label(team_row,text="预设编队").pack(side="left")
        ui.du_team_entry=ttk.Entry(team_row,textvariable=ui.du_team,width=16)
        ui.du_team_entry.pack(side="left",padx=(d(8),0))
        ui.setting_controls.extend((ui.du_mode_combo,ui.du_team_entry))
        resume_row=ttk.Frame(setup,style="Card.TFrame")
        resume_row.pack(anchor="w",pady=(d(5),d(4)))
        ui.du_resume_check=ttk.Checkbutton(resume_row,text="接续当前进度",variable=ui.du_resume_active,style="Card.TCheckbutton")
        ui.du_resume_check.pack(side="left")
        ui.du_resume_combo=ttk.Combobox(resume_row,textvariable=ui.du_resume_mode,
            values=("常规演算",)+tuple(f"周期难度 {n}" for n in range(1,11)),state="readonly",width=12)
        ui.du_resume_combo.pack(side="left",padx=(d(8),0))
        ui.setting_controls.extend((ui.du_resume_check,ui.du_resume_combo))
        ui.du_save_check=ttk.Checkbutton(setup,text="保存通关存档（AutoHSR 编号）",variable=ui.du_save,style="Card.TCheckbutton")
        ui.du_save_check.pack(anchor="w",pady=(d(5),0))
        ui.setting_controls.append(ui.du_save_check)
        ui.du_rewards_check=ttk.Checkbutton(setup,text="领取红点奖励（含已有卡带解锁）",variable=ui.du_rewards,style="Card.TCheckbutton")
        ui.du_rewards_check.pack(anchor="w",pady=(d(5),0))
        ui.setting_controls.append(ui.du_rewards_check)
        ttk.Label(setup,text="每局从“预设编队”按名称选角，核实“已启用”和四人完整后启动。默认周期演算、哈哈哈哈；周期难度沿用游戏已选值。",
                  style="CardHint.TLabel",wraplength=d(810)).pack(anchor="w",pady=(d(5),0))
        ttk.Label(setup, text="优先战斗站点，自动处理奖励与随意门；周期演算沿用已选难度，常规演算使用难度 I。寻找目标超过 90 秒会停止。F9 暂停 / 继续，F10 停止。",
                  style="CardHint.TLabel", wraplength=d(810)).pack(anchor="w", pady=(d(5), 0))
        ttk.Label(setup, textvariable=ui.du_status, style="Warning.TLabel", wraplength=d(810)).pack(anchor="w", pady=(d(8), 0))
        ttk.Label(universe, textvariable=ui.du_observation, style="Hint.TLabel", wraplength=d(830)).grid(row=2, column=0, sticky="ew")

    logs = ui.pages["logs"]
    logs.rowconfigure(1, weight=1)
    heading(logs, "运行日志", "查看识别详情、结果与证据；下方注明历史报告的时间和来源。")
    ui.output_tabs = ttk.Notebook(logs)
    ui.output_tabs.grid(row=1, column=0, sticky="nsew")
    ui.log = ui._text_tab("运行日志")
    ui.inspection_text = ui._text_tab("窗口检测")
    ui.report_text = ui._text_tab("运行报告")
    for level, color in (("error", "#ff9f9f" if hsr else "#b33c40"), ("warning", "#efc779" if hsr else "#986219")):
        ui.log.tag_configure(level, foreground=color)
    settings = ui.pages["settings"]
    heading(settings, "设置", "保存不会执行任务；登录、更新与验证码需手动完成。")
    display = card(settings, 1)
    if hsr:
        ttk.Label(display, text="完成后保留游戏；本版本尚未提供自动退出。", style="CardHint.TLabel").pack(anchor="w")
    else:
        ui.close_game_control = ttk.Checkbutton(display, text="每日确认完成后关闭游戏", variable=ui.close_game_on_success, style="Card.TCheckbutton")
        ui.close_game_control.pack(anchor="w")
        ttk.Label(display, text="默认关闭；400活跃、四档奖励及已选收尾全部核实后正常退出。", style="CardHint.TLabel").pack(anchor="w", padx=d(23))
        ui.overlay_control = ttk.Checkbutton(display, text="在游戏左侧显示覆盖日志", variable=ui.overlay_logs, style="Card.TCheckbutton")
        ui.overlay_control.pack(anchor="w", pady=(d(10), 0))
        ui.setting_controls.extend((ui.close_game_control, ui.overlay_control))
    timing = card(settings, 2)
    fields = (("操作间隔（秒）", ui.action_delay), ("战斗超时（秒）", ui.battle_timeout), ("OCR阈值", ui.ocr_confidence)) if hsr else (("操作间隔（秒）", ui.action_delay), ("界面超时（秒）", ui.transition_timeout), ("OCR阈值", ui.ocr_confidence))
    for row, (label, variable) in enumerate(fields):
        ttk.Label(timing, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, d(24)), pady=d(6))
        field = ttk.Entry(timing, textvariable=variable, width=10)
        field.grid(row=row, column=1, sticky="w", pady=d(6))
        ui.setting_controls.append(field)
    ttk.Label(settings, text="配置位置：" + str(ui.config_path), style="Hint.TLabel", wraplength=d(850)).grid(row=3, column=0, sticky="w", pady=d(10))
    ttk.Label(settings, text="未知页面会停止；不购买、不补充体力、不使用稀有补充道具。", style="Hint.TLabel").grid(row=4, column=0, sticky="w")
    footer = ttk.Frame(root, padding=(d(18), d(9)))
    footer.grid(row=1, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    ui.summary_label = ttk.Label(footer, textvariable=ui.summary, style="Hint.TLabel", wraplength=d(1100))
    ui.summary_label.grid(row=0, column=0, sticky="ew")
    ttk.Label(footer, textvariable=ui.history_context, style="Hint.TLabel", wraplength=d(1100)).grid(row=1, column=0, sticky="ew", pady=(d(4), d(7)))
    actions = ttk.Frame(footer)
    actions.grid(row=2, column=0, sticky="ew")
    ui.save_button = ttk.Button(actions, text="保存设置", command=ui._save_settings)
    ui.check_button = ttk.Button(actions, text="检测窗口", command=ui._check)
    ui.launch_button = ttk.Button(actions, text="启动游戏", command=ui._launch)
    ui.start_button = ttk.Button(actions, text="开始每日", command=ui._start, style="Accent.TButton")
    ui.reward_button = ttk.Button(actions, text="仅补领奖", command=ui._reward_only)
    ui.pause_button = ttk.Button(actions, text="暂停", command=ui._pause)
    ui.stop_button = ttk.Button(actions, text="停止", command=ui._stop)
    for button in (ui.save_button, ui.check_button, ui.launch_button, ui.start_button, ui.reward_button, ui.pause_button, ui.stop_button):
        button.pack(side="left", padx=(0, d(7)))
    ui.setting_controls.append(ui.save_button)
    files = ttk.Frame(actions)
    files.pack(side="right")
    directory = lambda: ui.last_run_dir if hsr else ui.last_output_dir
    ui.report_button = ttk.Button(files, text="报告", command=lambda: ui._open_path(ui.last_report_file))
    ui.screenshot_button = ttk.Button(files, text="截图", command=lambda: ui._open_path(ui.last_screenshot))
    ui.directory_button = ttk.Button(files, text="目录", command=lambda: ui._open_path(directory()))
    for button in (ui.report_button, ui.screenshot_button, ui.directory_button):
        button.pack(side="left", padx=(d(5), 0))
    ui.save_label = ttk.Label(footer, textvariable=ui.save_status if hsr else ui.saved, style="Hint.TLabel", wraplength=d(1100))
    ui.save_label.grid(row=3, column=0, sticky="w", pady=(d(5), 0))
    if hsr:
        ui.details_button = ui.screenshot_button  # old refresh helper only; full details remain in Logs.
    ui._show_page("home")
