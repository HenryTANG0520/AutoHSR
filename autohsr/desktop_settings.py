"""Settings rows follow the game's name/value layout and retain native editing."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as t
from .weekly_plan import DAYS, MODES
from .setting_choices import SettingChoice


SECTIONS = (
    ("game", "游戏连接", "客户端"),
    ("daily", "每日任务", "任务安排"),
    ("power", "体力计划", "任务安排"),
    ("weekly", "周常计划", "任务安排"),
    ("run", "运行偏好", "运行功能"),
    ("recognition", "识别与等待", "识别参数"),
    ("admin", "管理员启动", "启动权限"),
    ("tools", "工具", "工具与任务编排"),
)


class SettingsShell(ttk.Frame):
    """Second-level navigation and a scrollable form inside the guide paper."""

    def __init__(self, parent, scale, ui):
        super().__init__(parent)
        self.ui, self.section = ui, "game"
        self.scroll_step = round(36 * scale)
        self._layout_job = None
        d = lambda n: round(n * scale)
        self.columnconfigure(0, weight=1)
        # A pending scale change can briefly leave less space than the menu
        # needs. Keep the viewport mapped so an open dropdown retains its grab.
        self.rowconfigure(3, weight=1, minsize=1)
        menu = ttk.Frame(self)
        menu.grid(row=0, column=0, sticky="ew", pady=(0, d(8)))
        self.buttons = {}
        for index, (key, name, _) in enumerate(SECTIONS):
            menu.columnconfigure(index, weight=1)
            button = ttk.Button(menu, text=name, style="Settings.Nav.TButton",
                                command=lambda key=key: self.choose(key))
            button.grid(row=0, column=index, sticky="ew", padx=(0, d(4)))
            button.bind("<Left>", lambda event, index=index: self.move(index, -1))
            button.bind("<Right>", lambda event, index=index: self.move(index, 1))
            self.buttons[key] = button
        self.back = ttk.Button(menu, text="返回", style="Panel.TButton", command=ui._leave_settings)
        self.back.grid(row=0, column=len(SECTIONS), padx=(d(8), 0))
        self.heading = ttk.Label(self, style="Settings.Heading.TLabel")
        self.heading.grid(row=1, column=0, sticky="ew", pady=(0, d(6)))

        self.tools_nav = ttk.Frame(self)
        self.tools_nav.grid(row=2, column=0, sticky="ew", pady=(0, d(10)))
        self.tools_nav.grid_remove()

        viewport = ttk.Frame(self)
        viewport.grid(row=3, column=0, sticky="nsew")
        viewport.columnconfigure(0, weight=1)
        viewport.columnconfigure(1, minsize=d(14))
        viewport.rowconfigure(0, weight=1, minsize=1)
        self.canvas = tk.Canvas(viewport, bg=t.PANEL, highlightthickness=0, borderwidth=0,
                                width=1, height=1, takefocus=False)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content = ttk.Notebook(self.canvas, style="Settings.TNotebook", takefocus=False)
        self.form_window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self.queue_layout, add="+")
        self.bind("<Map>", self.queue_layout, add="+")
        self._bindings = [(event, ui.root.bind(event, action, add="+")) for event, action in
                          (("<MouseWheel>", self._wheel), ("<FocusIn>", self._focus))]
        self.bind("<Destroy>", self._destroy, add="+")

    def choose(self, key):
        self.content.select(self.ui.settings_sections[key])
        self.ui.root.after_idle(self.ui._focus_settings_entry)

    def move(self, index, step):
        key = SECTIONS[(index + step) % len(SECTIONS)][0]
        self.choose(key)
        self.buttons[key].focus_set()
        return "break"

    def select(self, key):
        if self.section != key:
            self.canvas.yview_moveto(0)
        self.section = key
        tools = getattr(self.ui, 'tools_shelf', None)
        if tools is not None and tools.nav.master is self:
            tools.nav.grid() if key == 'tools' else tools.nav.grid_remove()
        self.heading.configure(text=next(group for name, _, group in SECTIONS if name == key))
        for name, button in self.buttons.items():
            button.configure(style="Settings.Selected.Nav.TButton" if name == key else "Settings.Nav.TButton")
        self.queue_layout()

    def queue_layout(self, _=None):
        if self._layout_job is None:
            self._layout_job = self.after_idle(self._layout_form)

    def _layout_form(self):
        self._layout_job = None
        selection = self.content.select()
        if not self.winfo_ismapped() or not selection:
            return
        section = self.nametowidget(selection)
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        extent = max(height, section.winfo_reqheight())
        self.canvas.itemconfigure(self.form_window, width=width, height=extent)
        self.canvas.configure(scrollregion=(0, 0, width, extent))
        self.scrollbar.state(("!disabled" if extent > height else "disabled",))

    def _wheel(self, event):
        widget = event.widget
        if self.ui.settings_shell is not self or not self.winfo_ismapped():
            return
        if widget is not self.canvas and not str(widget).startswith(str(self.canvas) + "."):
            return
        if isinstance(widget, (ttk.Treeview, tk.Text, tk.Listbox)):
            return
        bounds = self.canvas.bbox(self.form_window)
        if event.delta and bounds and bounds[3] > self.canvas.winfo_height():
            delta = -self.scroll_step if event.delta > 0 else self.scroll_step
            self.canvas.yview_moveto((self.canvas.canvasy(0) + delta) / bounds[3])
            return "break"

    def _focus(self, event):
        widget = event.widget
        # Tk also sends FocusIn to ancestors when a native dropdown opens.
        # Revealing an entire section would scroll away from its active field.
        if isinstance(widget, tk.Widget) and str(widget) == str(self.tk.call("focus")):
            self.see(widget)

    def see(self, widget):
        if not str(widget).startswith(str(self.content) + ".") or not widget.winfo_ismapped():
            return
        offset = self.canvas.canvasy(0)
        top = widget.winfo_rooty() - self.canvas.winfo_rooty() + offset
        bottom = top + widget.winfo_height()
        height = self.canvas.winfo_height()
        bounds = self.canvas.bbox(self.form_window)
        if not bounds or bounds[3] <= height:
            return
        extent = bounds[3]
        if top < offset:
            self.canvas.yview_moveto(top / extent)
        elif bottom > offset + height:
            self.canvas.yview_moveto((bottom - height) / extent)

    def _destroy(self, event):
        if event.widget is not self:
            return
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
        for sequence, binding in self._bindings:
            self.ui.root.unbind(sequence, binding)


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
    ui.settings_shell = SettingsShell(ui.guide.content, s, ui)
    ui.pages["settings"] = ui.settings_shell
    ui.settings_shell.grid(row=0, column=0, sticky="nsew")
    tabs = ui.settings_shell.content
    ui.settings_tabs = tabs
    ui.settings_sections = {}
    ui.settings_buttons = ui.settings_shell.buttons
    for key, name, _ in SECTIONS:
        section = ttk.Frame(tabs)
        section.bind("<Configure>", ui.settings_shell.queue_layout, add="+")
        section.columnconfigure(0, weight=1)
        tabs.add(section, text=name)
        ui.settings_sections[key] = section

    def selected(_):
        if tabs is ui.settings_tabs:
            key = next((key for key, section in ui.settings_sections.items() if tabs.select() == str(section)), None)
            if key is not None:
                if key != 'tools':
                    ui._tools_return_section = None
                ui.settings_shell.select(key)
                ui._tool_action_changed()
                if not ui._loading:
                    ui._refresh_controls()
    tabs.bind("<<NotebookTabChanged>>", selected)
    ui.settings_shell.select("game")

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

    def buttons(target, actions, *, editable=True):
        frame = ttk.Frame(target.value, style="Settings.Value.TFrame", padding=d(8))
        frame.grid(row=0, column=0)
        result = []
        for index, (name, command) in enumerate(actions):
            button = ttk.Button(frame, text=name, command=command, style="Settings.TButton")
            button.grid(row=0, column=index, padx=(d(8) if index else 0, 0))
            if editable:
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
    from .desktop_daily import ASSIGNMENTS, HOME_TITLES
    entries = buttons(row("daily", index + 1, "单项领取", wide=True), (
        (label, lambda section=section: ui._show_daily_panel(section))
        for section, label in HOME_TITLES.items()
    ), editable=False)
    ui.daily_entry_buttons = dict(zip(HOME_TITLES, entries))
    ui.assignment_button = ui.daily_entry_buttons[ASSIGNMENTS]
    training = row("daily", index + 2, "实训奖励", hint="本次不刷本、不合成")
    ui.training_rewards_button, = buttons(training, (("仅补领每日实训", ui._reward_only),))

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
    toggle(row("run", 1, "关闭窗口时驻留托盘"), ui.close_to_tray, "tray_control")
    note("run", 2, text="保存后生效。可从系统托盘重新打开或退出助手。")
    toggle(row("run", 3, "完成后播放提示音"), ui.finish_sound, "finish_sound_control")
    toggle(row("run", 4, "完成后退出游戏"), ui.finish_close_game, "finish_close_control")
    note("run", 5, text="保存后生效，仅用于手动开始的日常或计划，整轮成功并保存报告后执行。")

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
    buttons(row("admin", 3, "登录自启", variable=ui.login_startup_status),
            (("刷新状态", lambda: ui._admin_operation("status", login=True)),))
    buttons(row("admin", 4, "自启设置"),
            (("启用自启", lambda: ui._admin_operation("enable", login=True)),
             ("移除自启", lambda: ui._admin_operation("disable", login=True))))
    note("admin", 5, text="登录 Windows 后启动助手到托盘。应用内定时需在助手中另行启用。")

    from .desktop_tools import ToolsShelf
    ui.tools_shelf = ToolsShelf(ui.settings_sections['tools'], ui)
    ui.tools_shelf.grid(row=0, column=0, sticky='new')
