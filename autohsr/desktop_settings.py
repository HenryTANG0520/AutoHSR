"""Settings rows follow the game's name/value layout and retain native editing."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as t
from .weekly_plan import DAYS, MODES


class BooleanSetting(ttk.Combobox):
    """Display an existing BooleanVar as a native, keyboard-accessible choice."""

    def __init__(self, parent, variable):
        self.value = tk.StringVar(parent)
        super().__init__(parent, textvariable=self.value, values=("开启", "关闭"),
                         state="readonly", style="Settings.TCombobox", justify="center", width=8)
        self.variable = variable
        self.bind("<<ComboboxSelected>>", self._select)
        self.token = variable.trace_add("write", self._sync)
        self.bind("<Destroy>", self._destroy, add="+")
        self._sync()

    def _sync(self, *_):
        self.value.set("开启" if self.variable.get() else "关闭")

    def _select(self, _):
        self.variable.set(self.value.get() == "开启")

    def _destroy(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self.token)


class SettingRow(ttk.Frame):
    def __init__(self, parent, scale, index, name, *, hint=None, variable=None, wide=False):
        super().__init__(parent, style="Settings.Row.TFrame")
        d = lambda n: round(n*scale)
        self.grid(row=index, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=3 if wide else 0, minsize=d(240))
        self.rowconfigure(0, minsize=d(52))
        caption = ttk.Frame(self, style="Settings.Row.TFrame", padding=(d(18), d(8)))
        caption.grid(row=0, column=0, sticky="ew")
        caption.columnconfigure(0, weight=1)
        t.wrapped_label(caption, text=name, style="Settings.TLabel").grid(row=0, column=0, sticky="ew")
        if hint is not None or variable is not None:
            args = dict(textvariable=variable) if variable is not None else dict(text=hint)
            t.wrapped_label(caption, style="Settings.Hint.TLabel", **args).grid(
                row=1, column=0, sticky="ew", pady=(d(3), 0))
        self.value = ttk.Frame(self, style="Settings.Value.TFrame", width=d(240))
        self.value.grid(row=0, column=1, sticky="nsew")
        self.value.columnconfigure(0, weight=1)
        self.value.rowconfigure(0, weight=1)
        ttk.Frame(self, style="Settings.Line.TFrame", height=max(1, d(1))).grid(
            row=1, column=0, columnspan=2, sticky="ew")

    def place_control(self, control):
        control.grid(row=0, column=0, sticky="nsew")
        return control


def build_settings(ui):
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
    ui.settings_buttons = {}
    for index, (key, name) in enumerate((("game", "游戏连接"), ("weekly", "周常计划"),
            ("run", "运行偏好"), ("recognition", "识别与等待"), ("admin", "管理员启动"))):
        section = ttk.Frame(tabs)
        section.columnconfigure(0, weight=1)
        tabs.add(section, text=name)
        ui.settings_sections[key] = section
        button = ttk.Button(menu, text=name, style="Option.TButton", width=13,
            command=ui._show_weekly_plan if key == "weekly" else lambda section=section: tabs.select(section))
        button.grid(row=index, column=0, sticky="ew", pady=(0, d(10)))
        ui.settings_buttons[key] = button

    def selected(_):
        for key, button in ui.settings_buttons.items():
            button.configure(style="Selected.Option.TButton" if tabs.select() == str(ui.settings_sections[key]) else "Option.TButton")
    tabs.bind("<<NotebookTabChanged>>", selected)

    def row(section, index, name, **kwargs):
        return SettingRow(ui.settings_sections[section], s, index, name, **kwargs)

    def entry(target, variable, name, **kwargs):
        field = ttk.Entry(target.value, textvariable=variable, style="Settings.TEntry",
                          width=10, justify=kwargs.pop("justify", "center"), **kwargs)
        target.place_control(field)
        setattr(ui, name, field)
        ui.setting_controls.append(field)
        return field

    def combo(target, variable, values, name):
        field = ttk.Combobox(target.value, textvariable=variable, values=values,
            style="Settings.TCombobox", width=10, justify="center", state="readonly")
        target.place_control(field)
        setattr(ui, name, field)
        ui.setting_controls.append(field)

    def toggle(target, variable, name):
        field = target.place_control(BooleanSetting(target.value, variable))
        setattr(ui, name, field)
        ui.setting_controls.append(field)

    def buttons(target, actions):
        frame = ttk.Frame(target.value, style="Settings.Value.TFrame", padding=d(8))
        frame.grid(row=0, column=0)
        result = []
        for index, (name, command) in enumerate(actions):
            button = ttk.Button(frame, text=name, command=command, style="Settings.TButton")
            button.grid(row=0, column=index, padx=(d(8) if index else 0, 0))
            ui.setting_controls.append(button)
            result.append(button)
        return result

    def note(section, index, *, text=None, variable=None):
        args = dict(textvariable=variable) if variable is not None else dict(text=text)
        label = t.wrapped_label(ui.settings_sections[section], style="Hint.TLabel", **args)
        label.grid(row=index, column=0, sticky="ew", pady=(d(12), 0))

    game = row("game", 0, "游戏程序", hint="StarRail.exe", wide=True)
    entry(game, ui.game_path, "game_path_entry", justify="left")
    browse = ttk.Button(game.value, text="浏览…", command=ui._choose_game, style="Settings.TButton")
    browse.grid(row=0, column=1, padx=d(8), pady=d(8))
    ui.setting_controls.append(browse)
    connection = row("game", 1, "游戏窗口", variable=ui.readiness)
    ui.check_button, ui.launch_button = buttons(connection, (("检测窗口", ui._check), ("进入游戏", ui._launch)))
    note("game", 2, text="登录验证与更新需在游戏内完成。")
    note("game", 3, text="配置位置："+str(ui.config_path))

    toggle(row("weekly", 0, "周常计划"), ui.weekly_enabled, "weekly_enabled_combo")
    combo(row("weekly", 1, "玩法"), ui.weekly_mode, tuple(MODES.values()), "weekly_mode_combo")
    combo(row("weekly", 2, "每周"), ui.weekly_day, DAYS, "weekly_day_combo")
    entry(row("weekly", 3, "时间（北京时间）", hint="HH:MM"), ui.weekly_time, "weekly_time_entry")
    runs = row("weekly", 4, "演算局数")
    combo(runs, ui.weekly_runs, tuple(str(n) for n in range(1, 11)), "weekly_runs_combo")
    team = row("weekly", 5, "预设编队")
    entry(team, ui.du_team, "weekly_team_entry")
    ui.weekly_run_controls = (runs, team)
    note("weekly", 6, text="到期后随“开始计划”执行；每周一 04:00 刷新。")
    note("weekly", 7, variable=ui.weekly_boundary)

    toggle(row("run", 0, "游戏内日志字幕"), ui.overlay_logs, "overlay_control")
    toggle(row("run", 1, "实训合成", hint="1 个奇巧零食 · 两种普通材料各 1 个"),
           ui.daily_synthesis, "synthesis_control")
    note("run", 2, text="仅实训未完成时合成；仅补领奖时不合成。")

    for index, (name, variable, limits, control) in enumerate((
            ("操作间隔（秒）", ui.action_delay, "0.3～5", "action_delay_entry"),
            ("战斗超时（秒）", ui.battle_timeout, "60～3600", "battle_timeout_entry"),
            ("OCR 阈值", ui.ocr_confidence, "0.4～0.99", "ocr_confidence_entry"))):
        entry(row("recognition", index, name, hint=limits), variable, control)

    buttons(row("admin", 0, "管理员启动", variable=ui.admin_launch_status),
            (("刷新状态", lambda: ui._admin_operation("status")),))
    buttons(row("admin", 1, "启动授权"), (("启用授权", lambda: ui._admin_operation("enable")),
            ("移除授权", lambda: ui._admin_operation("disable"))))
    note("admin", 2, text="首次需 Windows 授权；仅绑定当前账户和目录，移动目录后需重新启用。")
