"""Settings rows follow the game's name/value layout and retain native editing."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import math
from PIL import ImageTk

from . import theme as t
from .game_widgets import PlanRibbon, Surface, paint_run_metrics
from .weekly_plan import DAYS, MODES
from .setting_choices import SettingChoice


SECTIONS = (("game", "游戏连接", "客户端", "guide-mark.png"),
            ("daily", "每日任务", "任务安排", "tab-daily.png"),
            ("power", "体力计划", "任务安排", "tab-survival.png"),
            ("weekly", "周常计划", "任务安排", "tab-universe.png"),
            ("run", "运行偏好", "运行功能", "tab-settings.png"),
            ("recognition", "识别与等待", "识别参数", "tab-survival.png"),
            ("admin", "管理员启动", "启动权限", "tab-records.png"))


class SettingsShell(Surface):
    """A separate settings surface, with the game's top navigation and return."""

    def __init__(self, parent, scale, ui):
        # The rings end at 126; leave room for the antialiasing filter below.
        super().__init__(parent, scale, bg=t.BG, paint_height=132)
        self.ui, self.section = ui, "game"
        self.watch(ui.stamina, ui.elapsed)
        d = lambda n: round(n*scale)
        self.menu = ttk.Frame(self, style="Footer.TFrame")
        self.menu.bind("<Configure>", self.redraw, add="+")
        self.content = ttk.Frame(self, style="Footer.TFrame")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.plan = PlanRibbon(self, scale, ui, dark=True)
        self.photos = {}
        self.buttons = {}
        for index, (key, name, _, asset) in enumerate(SECTIONS):
            for selected in (False, True):
                p = t.Painter(d(48), d(48), scale, t.BG)
                if selected:
                    p.ellipse((3, 3, 45, 45), t.LIGHT)
                    p.ellipse((0, 0, 48, 48), None, "#787c86", .8)
                p.asset(asset, (10, 10, 38, 38), t.BG if selected else "#aaadb5")
                self.photos[key, selected] = ImageTk.PhotoImage(p.finish(), master=self)
            button = ttk.Button(self.menu, text=name, image=self.photos[key, False],
                compound="top", style="Settings.Nav.TButton",
                command=lambda key=key: self.choose(key))
            button.grid(row=0, column=index, padx=d(8))
            button.bind("<Map>", self.redraw, add="+")
            button.bind("<Left>", lambda event, index=index: self.move(index, -1))
            button.bind("<Right>", lambda event, index=index: self.move(index, 1))
            self.buttons[key] = button
        p = t.Painter(d(36), d(36), scale, t.BG)
        p.asset("guide/close.png", (2, 2, 34, 34))
        self.close_photo = ImageTk.PhotoImage(p.finish(), master=self)
        self.back = ttk.Button(self, text="返回", image=self.close_photo, style="Settings.Close.TButton", command=ui._leave_settings)
        self.bind("<Configure>", self.position, add="+")

    def choose(self, key):
        if key == "weekly":
            self.ui._show_weekly_plan()
        elif key == "daily":
            self.ui._show_daily_tasks()
        elif key == "power":
            from .power_plan_ui import show
            show(self.ui)
        else:
            self.ui.settings_tabs.select(self.ui.settings_sections[key])
            self.ui.root.after_idle(self.ui._focus_settings_entry)

    def move(self, index, step):
        key = SECTIONS[(index+step) % len(SECTIONS)][0]
        self.choose(key)
        self.buttons[key].focus_set()
        return "break"

    def select(self, key):
        changed = self.section != key
        self.section = key
        for name, button in self.buttons.items():
            button.configure(image=self.photos[name, name == key],
                style="Settings.Selected.Nav.TButton" if name == key else "Settings.Nav.TButton")
        if changed:
            self.redraw()

    def position(self, _=None):
        d = lambda n: round(n*self.scale)
        w, h = self.winfo_width(), self.winfo_height()
        margin = max(d(36), round(w*.052))
        self.menu.place(x=(w-self.menu.winfo_reqwidth())//2, y=d(6))
        self.back.place(x=w-d(56), y=d(14), width=d(44), height=d(44))
        daily = getattr(self.ui, "action_page", "home") in ("home", "tasks")
        reserve = d(70 if daily else 20)
        self.content.place(x=margin, y=d(126), width=max(1, w-2*margin), height=max(1, h-d(126)-reserve))
        if daily:
            self.plan.place(x=margin, y=h-d(58), width=max(1, w-2*margin), height=d(46))
        else:
            self.plan.place_forget()

    def paint(self, p):
        self.position()
        # These are restrained code-drawn rings, not a fabricated game scene.
        for radius in (82, 112, 150):
            p.ellipse((35-radius, -24-radius, 35+radius, -24+radius), None, "#222936", .7)
        for x, y, radius, teeth in ((40, 34, 13, 8), (51, 43, 6, 6)):
            points = []
            for step in range(teeth*4):
                angle = step*math.tau/(teeth*4)
                r = radius if step % 4 in (1, 2) else radius*.74
                points.extend((x+r*math.cos(angle), y+r*math.sin(angle)))
            p.poly(points, t.GOLD)
            p.ellipse((x-radius*.42, y-radius*.42, x+radius*.42, y+radius*.42), t.BG)
        name, group = next((name, group) for key, name, group, _ in SECTIONS if key == self.section)
        p.text((70, 19), "设置", 14, t.GOLD)
        p.text((70, 41), name, 17, t.LIGHT)
        paint_run_metrics(p, self.ui)
        margin = max(36, p.width*.052)
        p.text((margin, 98), group, 17, t.LIGHT)
        p.line((margin, 120, p.width-margin, 120), "#4c505b", .8)
        button = self.buttons[self.section]
        if button.winfo_ismapped():
            x = (self.menu.winfo_x()+button.winfo_x())/self.scale
            width = button.winfo_width()/self.scale
            p.line((x+8, 84, x+width-8, 84), t.LIGHT, 2)


class BooleanSetting(SettingChoice):
    """Display an existing BooleanVar as a native, keyboard-accessible choice."""

    def __init__(self, parent, variable):
        self.value = tk.StringVar(parent)
        super().__init__(parent, textvariable=self.value, values=("开启", "关闭"),
                         state="readonly", style="Settings.TCombobox", justify="center", width=8, font=t.native_font(parent, 12))
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
        self.columnconfigure(0, weight=1 if wide else 3, uniform="setting")
        self.columnconfigure(1, weight=3 if wide else 1, minsize=d(240), uniform="setting")
        self.rowconfigure(0, minsize=d(58))
        caption = ttk.Frame(self, style="Settings.Row.TFrame", padding=(d(18), d(8)))
        caption.grid(row=0, column=0, sticky="ew")
        caption.columnconfigure(0, weight=1)
        self.caption = t.wrapped_label(caption, text=name, style="Settings.TLabel")
        self.caption.grid(row=0, column=0, sticky="ew")
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
    ui.settings_shell = SettingsShell(ui.shell, s, ui)
    page = ui.settings_shell.content
    ui.pages["settings"] = ui.settings_shell
    tabs = ttk.Notebook(page, style="Settings.TNotebook")
    tabs.grid(row=0, column=0, sticky="nsew")
    ui.settings_tabs = tabs
    ui.settings_sections = {}
    ui.settings_buttons = ui.settings_shell.buttons
    for key, name, _, _ in SECTIONS:
        section = ttk.Frame(tabs, style="Footer.TFrame")
        section.columnconfigure(0, weight=1)
        tabs.add(section, text=name)
        ui.settings_sections[key] = section

    def selected(_):
        if tabs is ui.settings_tabs:
            key = next((key for key, section in ui.settings_sections.items() if tabs.select() == str(section)), None)
            if key is not None:
                ui.settings_shell.select(key)
    tabs.bind("<<NotebookTabChanged>>", selected)

    def row(section, index, name, **kwargs):
        return SettingRow(ui.settings_sections[section], s, index, name, **kwargs)

    def entry(target, variable, name, **kwargs):
        field = ttk.Entry(target.value, textvariable=variable, style="Settings.TEntry",
                          width=10, font=t.native_font(target.value, 12), justify=kwargs.pop("justify", "center"), **kwargs)
        target.place_control(field)
        setattr(ui, name, field)
        ui.setting_controls.append(field)
        return field

    def combo(target, variable, values, name):
        field = SettingChoice(target.value, textvariable=variable, values=values,
            style="Settings.TCombobox", width=10, font=t.native_font(target.value, 12), justify="center", state="readonly")
        target.place_control(field)
        setattr(ui, name, field)
        ui.setting_controls.append(field)

    def toggle(target, variable, name):
        field = target.place_control(BooleanSetting(target.value, variable))
        setattr(ui, name, field)
        ui.setting_controls.append(field)
        return field

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
        label = t.wrapped_label(ui.settings_sections[section], style="Settings.Note.TLabel", **args)
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

    ui.daily_task_controls = {}
    index = 0
    for key, variable in ui.tasks.items():
        target = row("daily", index, ui.table.names[key],
                     hint="开拓力刷本未授权" if key == "battle" and not ui.settings.allow_stamina_spend else None)
        ui.daily_task_controls[key] = toggle(target, variable, "daily_"+key+"_combo")
        index += 1
        if key == 'battle':
            from .support_ui import show as show_support
            support = row('daily',index,'借用好友支援',variable=ui.support_summary,wide=True)
            control=BooleanSetting(support.value,ui.use_support);support.place_control(control)
            ui.support_toggle=control;ui.setting_controls.append(control)
            ui.support_config_button=ttk.Button(support.value,text='选择角色',command=lambda:show_support(ui),style='Settings.TButton')
            ui.support_config_button.grid(row=0,column=1,padx=d(8));ui.setting_controls.append(ui.support_config_button)
            index += 1
        if key == "daily":
            toggle(row("daily", index, "实训合成", hint="1 个奇巧零食 · 两种普通材料各 1 个"),
                   ui.daily_synthesis, "synthesis_control")
            index += 1
    note("daily", index, text="仅实训未完成时合成；仅补领奖时不合成。")

    from .power_plan_ui import PowerPlanEditor
    ui.settings_sections['power'].rowconfigure(0, weight=1)
    PowerPlanEditor(ui.settings_sections['power'], ui).grid(row=0,column=0,sticky='nsew')

    toggle(row("weekly", 0, "周常计划"), ui.weekly_enabled, "weekly_enabled_combo")
    combo(row("weekly", 1, "玩法"), ui.weekly_mode, tuple(MODES.values()), "weekly_mode_combo")
    combo(row("weekly", 2, "每周"), ui.weekly_day, DAYS, "weekly_day_combo")
    entry(row("weekly", 3, "时间（北京时间）", hint="HH:MM"), ui.weekly_time, "weekly_time_entry")
    runs = row("weekly", 4, "演算局数")
    ui.weekly_runs_row = runs
    combo(runs, ui.weekly_runs, tuple(str(n) for n in range(1, 11)), "weekly_runs_combo")
    team = row("weekly", 5, "预设编队")
    entry(team, ui.du_team, "weekly_team_entry")
    ui.weekly_run_controls = (team,)
    note("weekly", 6, text="到期后随“开始计划”执行；每周一 04:00 刷新。")
    note("weekly", 7, variable=ui.weekly_boundary)

    toggle(row("run", 0, "游戏内日志字幕"), ui.overlay_logs, "overlay_control")

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
