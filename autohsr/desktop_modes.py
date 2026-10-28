"""Separate preparation, optional steps and developer operations in the guide."""
from __future__ import annotations

from tkinter import ttk

from . import theme as t
from .desktop import heading, note


def bound_text(ui, parent, variable, *, height=4):
    text = ui._text(parent)
    text.configure(height=height)
    token = variable.trace_add("write", lambda *_: ui._replace_text(text, variable.get()))
    text.bind("<Destroy>", lambda event: variable.trace_remove("write", token) if event.widget is text else None, add="+")
    ui._replace_text(text, variable.get())
    return text


def build_universe(ui):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["differential_universe"]
    heading(page, "差分宇宙", "周期演算 · 每局从指定预设编队出发；难度沿用游戏准备页已选值。", s)
    columns = ttk.Frame(page)
    columns.grid(row=1, column=0, sticky="ew")
    for col in range(2):
        columns.columnconfigure(col, weight=1, uniform="universe")
    setup = ttk.Frame(columns, style="Card.TFrame", padding=d(16))
    setup.grid(row=0, column=0, sticky="nsew", padx=(0, d(12)))
    setup.columnconfigure(1, weight=1)
    ttk.Label(setup, text="演算计划", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, d(14)))
    for row, label in enumerate(("运行局数", "演算模式", "预设编队"), 1):
        ttk.Label(setup, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, d(14)), pady=d(8))
    ui.du_runs_combo = ttk.Combobox(setup, textvariable=ui.differential_universe_runs, values=tuple(map(str, range(1, 11))), state="readonly", width=12)
    ui.du_mode_combo = ttk.Combobox(setup, textvariable=ui.du_mode, values=("周期演算", "常规演算"), state="readonly", width=12)
    ui.du_team_entry = ttk.Entry(setup, textvariable=ui.du_team, width=12)
    for row, widget in enumerate((ui.du_runs_combo, ui.du_mode_combo, ui.du_team_entry), 1):
        widget.grid(row=row, column=1, sticky="ew")
        ui.setting_controls.append(widget)
    ui.du_resume_check = ttk.Checkbutton(setup, text="接续当前进度", variable=ui.du_resume_active)
    ui.du_resume_check.grid(row=4, column=0, columnspan=2, sticky="w", pady=(d(12), 0))
    ui.du_resume_combo = ttk.Combobox(setup, textvariable=ui.du_resume_mode, values=("常规演算",)+tuple(f"周期难度 {n}" for n in range(1, 11)), state="readonly", width=12)
    ui.du_resume_combo.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(d(6), 0))
    ui.setting_controls.extend((ui.du_resume_check, ui.du_resume_combo))
    options = ttk.Frame(columns, style="Card.TFrame", padding=d(16))
    options.grid(row=0, column=1, sticky="nsew")
    options.columnconfigure(0, weight=1)
    ttk.Label(options, text="通关后", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, d(14)))
    for row, (attribute, text, variable) in enumerate((("du_save_check", "保存到空存档槽", ui.du_save),
        ("du_rewards_check", "领取红点奖励", ui.du_rewards), ("du_daily_check", "每日首次通关后执行日常", ui.du_daily)), 1):
        check = ttk.Checkbutton(options, text=text, variable=variable)
        check.grid(row=row, column=0, sticky="w", pady=d(8))
        setattr(ui, attribute, check)
        ui.setting_controls.append(check)
    note(options, "存档采用 AutoHSR 递增编号；红点奖励含已有卡带解锁。日常使用独立预算刷浴火钢心。", row=4, scale=s)
    status = ttk.Frame(page, style="Card.TFrame", padding=d(12))
    status.grid(row=2, column=0, sticky="ew", pady=(d(14), d(10)))
    status.columnconfigure(0, weight=1)
    note(status, variable=ui.du_status, row=0, style="Warning.TLabel", scale=s)
    page.rowconfigure(3, weight=1)
    bound_text(ui, page, ui.du_observation, height=3).grid(row=3, column=0, sticky="nsew")


def build_currency(ui):
    s = ui.ui_scale
    d = lambda n: round(n*s)
    page = ui.pages["currency_wars"]
    heading(page, "货币战争", "开发验证中 · 标准 A8-40 独立整局尚未验收；主按钮只读识别当前画面。", s)
    tabs = ttk.Notebook(page)
    tabs.grid(row=1, column=0, sticky="nsew")
    page.rowconfigure(1, weight=1)
    ui.currency_tabs = tabs
    ui.currency_sections = {}
    for key, name in (("observe", "观察与准备"), ("standard", "标准开发"), ("debug", "单步调试")):
        frame = ttk.Frame(tabs, style="Card.TFrame", padding=d(16))
        frame.columnconfigure(0, weight=1)
        tabs.add(frame, text=name)
        ui.currency_sections[key] = frame

    def buttons(parent, row, actions):
        line = ttk.Frame(parent, style="Card.TFrame")
        line.grid(row=row, column=0, sticky="w", pady=(d(10), d(8)))
        for index, (label, command, attr) in enumerate(actions):
            button = ttk.Button(line, text=label, command=command)
            button.grid(row=index//2, column=index%2, sticky="w", padx=(0, d(10)), pady=d(4))
            ui.setting_controls.append(button)
            if attr:
                setattr(ui, attr, button)

    observe = ui.currency_sections["observe"]
    note(observe, variable=ui.currency_status, row=0, style="Warning.TLabel", scale=s)
    buttons(observe, 1, (("进入游戏（不开局）", ui._currency_prepare, None),
                         ("定位标准模式", ui._currency_locate, None),
                         ("配置 A8-40（不开局）", ui._currency_configure, None)))
    from .currency_wars import REVIEW_ITEMS
    ui.currency_review = ttk.Treeview(observe, columns=("item", "status"), show="headings", height=4, selectmode="none")
    ui.currency_review.heading("item", text="核实项目")
    ui.currency_review.heading("status", text="证据状态")
    ui.currency_review.column("item", width=d(430), stretch=True)
    ui.currency_review.column("status", width=d(140), stretch=False)
    ui.currency_review.grid(row=2, column=0, sticky="ew", pady=d(6))
    for key, label in REVIEW_ITEMS:
        ui.currency_review.insert("", "end", iid=key, values=(label, "部分验证" if key == "transitions" else "4.6 已采集"))
    observe.rowconfigure(3, weight=1)
    bound_text(ui, observe, ui.currency_observation, height=3).grid(row=3, column=0, sticky="nsew", pady=(d(8), 0))

    standard = ui.currency_sections["standard"]
    ttk.Label(standard, text="标准 A8 · 财富造物主 40", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, d(10)))
    note(standard, "新开局与接续已记录对局分别执行；未知开局、交易或反馈会停止并保留原始证据。", row=1, scale=s)
    buttons(standard, 2, (("新开 A8-40 开发局", ui._currency_standard, None), ("接续已记录开发局", ui._currency_resume, None)))
    note(standard, "规则参考：4.6 标准博弈每 10 金币产生 1 利息，上限 5；超频博弈不产生利息。部署容量以实际画面为准。", row=3, scale=s)
    note(standard, "最后节点实验仍未验收，旧十场目标未恢复。接续开发不计作独立通关。", row=4, style="Warning.TLabel", scale=s)

    debug = ui.currency_sections["debug"]
    ttk.Label(debug, text="显式运行单步实验", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
    buttons(debug, 1, (("拖动：前台 3→1（一次）", ui._currency_drag_test, "currency_drag_button"),
                       ("部署所选备战角色", ui._currency_deploy_test, "currency_deploy_button"),
                       ("战斗：仅当前节点", ui._currency_node_test, "currency_node_button"),
                       ("整局验证：超频 A0", ui._currency_match_test, "currency_match_button")))
    fields = ttk.Frame(debug, style="Card.TFrame")
    fields.grid(row=2, column=0, sticky="ew", pady=d(10))
    for column, (label, variable, values, attr) in enumerate((("备战来源", ui.currency_source_slot, tuple(map(str, range(1, 10))), "currency_source_combo"),
        ("部署到", ui.currency_zone, ("后台", "前台"), "currency_zone_combo"),
        ("升级目标", ui.currency_target_level, ("保持",)+tuple(map(str, range(1, 11))), "currency_level_combo"))):
        ttk.Label(fields, text=label, style="Muted.TLabel").grid(row=0, column=column*2, sticky="w", padx=(0, d(6)))
        combo = ttk.Combobox(fields, textvariable=variable, values=values, state="readonly", width=5)
        combo.grid(row=0, column=column*2+1, padx=(0, d(16)))
        setattr(ui, attr, combo)
        ui.setting_controls.append(combo)
    buttons(debug, 3, (("推进当前对局", ui._currency_flow_test, "currency_flow_button"),
                       ("只读控制：截图后暂停", ui._currency_control_probe, None),
                       ("只读超时：0.05 秒", ui._currency_timeout_probe, None)))
    note(debug, "流程验证可能进行局内购买、升级与装备分配。单步操作不会标记整局完成。", row=4, style="Warning.TLabel", scale=s)
