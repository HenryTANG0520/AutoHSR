"""Chinese desktop interface; worker threads only communicate through events."""
from __future__ import annotations

import os
import queue
import re
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from .config import CONFIG_PATH, ROOT, Settings

TASK_NAMES = {
    "assignments": "持续委托奖励", "battle": "拟造花萼挑战",
    "daily": "每日实训奖励", "mail": "邮件附件", "battlepass": "无名勋礼奖励",
}
STATUS_NAMES = {
    "pending": "等待", "running": "进行中", "success": "已完成", "ok": "已完成",
    "completed": "已完成", "done": "已完成", "failed": "失败", "error": "失败",
    "skipped": "跳过", "stopped": "已停止", "partial": "部分完成",
    "paused": "已暂停", "cancelled": "已停止",
}


def event_kind(event: dict[str, Any]) -> str:
    return str(event.get("type", event.get("event", event.get("kind", "log"))))


class AutoHSRWindow:
    BG, PANEL, INSET = "#0b1422", "#142237", "#101c2d"
    TEXT, MUTED, ACCENT = "#e5edf7", "#91a6bf", "#47d9ce"

    def __init__(self, root: tk.Tk, config_path: Path = CONFIG_PATH):
        self.root, self.config_path = root, Path(config_path)
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.runner: Any = None
        self.worker: threading.Thread | None = None
        self.busy = self.running = self.paused = self.stopping = self.closing = False
        self._has_run = False
        self._f9_local_pressed = False
        self.stop_requested = threading.Event()
        self.started_at: float | None = None
        self.elapsed_seconds = self.confirmed_stamina = 0
        self.last_run_dir: Path | None = None
        self.last_report_file: Path | None = None
        self.last_screenshot: Path | None = None
        self.setting_controls: list[tk.Widget] = []
        self.stamina_controls: list[tk.Widget] = []
        self._loading = True
        config_error = ""
        try:
            self.settings = Settings.load(self.config_path)
        except (OSError, ValueError, TypeError) as exc:
            self.settings = Settings()
            config_error = f"无法读取配置，已使用默认值。\n{exc}"
        root.title("AutoHSR · 星穹铁道每日助手")
        root.geometry("1180x820")
        root.minsize(1100, 760)
        root.configure(bg=self.BG)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._style()
        self._variables()
        self._build()
        self._saved_signature = self._form_signature()
        self._loading = False
        for variable in self.form_variables:
            variable.trace_add("write", self._form_changed)
        self._discover_report()
        self._form_changed()
        # Pair a local press/release: global F9 can restore this window while
        # the key is still held. That release must not toggle pause again.
        root.bind_all("<KeyPress-F9>", self._f9_press)
        root.bind_all("<KeyRelease-F9>", self._f9_release)
        root.bind_all("<FocusOut>", lambda _: setattr(self, "_f9_local_pressed", False), add="+")
        root.bind_all("<F10>", lambda _: self._stop())
        root.after(100, self._drain)
        self._log("准备就绪。选择任务与副本，然后检测窗口。")
        self._log("仅使用已有开拓力；首次验证建议采用“测试 10 / 1 轮”。")
        if not self.settings.allow_stamina_spend:
            self._log("开拓力刷本未授权，当前仅收取委托与奖励。", "warning")
        if config_error:
            root.after(200, lambda: messagebox.showwarning("配置读取失败", config_error, parent=root))

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.PANEL, foreground=self.TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", foreground=self.MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Warning.TLabel", foreground="#efc779", font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", background=self.BG, font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("Subtitle.TLabel", background=self.BG, foreground=self.MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Metric.TLabel", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("Status.TLabel", background=self.BG, foreground=self.ACCENT, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.TEXT, font=("Microsoft YaHei UI", 9), padding=(0, 0))
        style.map("TCheckbutton", background=[("active", self.PANEL)], foreground=[("disabled", "#60758d")])
        for name in ("TEntry", "TSpinbox"):
            style.configure(name, fieldbackground="#1d2e46", foreground=self.TEXT, insertcolor=self.TEXT, padding=4, font=("Microsoft YaHei UI", 10))
            style.map(name, fieldbackground=[("disabled", "#17263b")], foreground=[("disabled", "#60758d")])
        style.configure("TButton", background="#253c56", foreground=self.TEXT, font=("Microsoft YaHei UI", 9), padding=(12, 8), borderwidth=0)
        style.map("TButton", background=[("active", "#345775"), ("disabled", "#1b2c41")], foreground=[("disabled", "#60758d")])
        style.configure("Primary.TButton", background=self.ACCENT, foreground="#082829", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#78e9de"), ("disabled", "#23595d")], foreground=[("disabled", "#7fabad")])
        style.configure("Danger.TButton", foreground="#ffb6b6")
        style.configure("Compact.TButton", padding=(9, 3))
        style.configure("TNotebook", background=self.PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background="#1d3048", foreground=self.MUTED, font=("Microsoft YaHei UI", 9), padding=(15, 6))
        style.map("TNotebook.Tab", background=[("selected", self.PANEL)], foreground=[("selected", self.ACCENT)])
        style.configure("Treeview", background=self.INSET, fieldbackground=self.INSET, foreground=self.TEXT, rowheight=30, borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background="#20334d", foreground=self.MUTED, font=("Microsoft YaHei UI", 9), padding=6, relief="flat")
        style.map("Treeview", background=[("selected", "#24475b")])
        style.configure("Vertical.TScrollbar", background="#32475f", troughcolor=self.INSET, bordercolor=self.INSET, arrowcolor=self.MUTED)

    def _variables(self) -> None:
        self.game_path = tk.StringVar(value=self.settings.game_path)
        self.target_name = tk.StringVar(value=self.settings.target_name)
        self.target_location = tk.StringVar(value=self.settings.target_location)
        self.stamina_limit = tk.StringVar(value=str(self.settings.stamina_limit))
        self.rounds = tk.StringVar(value=str(self.settings.rounds))
        self.use_support = tk.BooleanVar(value=self.settings.use_support)
        self.auto_launch = tk.BooleanVar(value=self.settings.auto_launch)
        self.tasks = {name: tk.BooleanVar(value=getattr(self.settings, name)) for name in TASK_NAMES}
        if not self.settings.allow_stamina_spend:
            self.tasks["battle"].set(False)
        self.form_variables = [self.game_path, self.target_name, self.target_location, self.stamina_limit,
                               self.rounds, self.use_support, self.auto_launch, *self.tasks.values()]
        self.status = tk.StringVar(value="● 准备就绪")
        self.save_status = tk.StringVar()
        self.summary = tk.StringVar(value="请选择任务并检测窗口；运行结果会保留在这里。")
        self.current_task = tk.StringVar(value="等待开始")
        self.elapsed = tk.StringVar(value="00:00")
        self.stamina = tk.StringVar(value="0")
        self.battle_hint = tk.StringVar()
        self.detect_title = tk.StringVar(value="尚未检测游戏窗口")
        self.detect_size = tk.StringVar(value="客户区尺寸：—")
        self.detect_permission = tk.StringVar(value="助手管理员权限：—")

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=(24, 17, 24, 15))
        header.pack(fill="x")
        ttk.Label(header, text="AutoHSR", style="Title.TLabel").pack(side="left")
        title = ttk.Frame(header)
        title.pack(side="left", padx=18)
        ttk.Label(title, text="星穹铁道 · 每日助手  0.1", style="Subtitle.TLabel").pack(anchor="w")
        ttk.Label(title, text="指南 → 目标副本 → 好友支援 → 现有开拓力", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(header, textvariable=self.status, style="Status.TLabel").pack(side="right")

        footer = ttk.Frame(self.root, padding=(24, 12, 24, 16))
        footer.pack(side="bottom", fill="x")
        foot_info = ttk.Frame(footer)
        foot_info.pack(fill="x", pady=(0, 9))
        self.save_label = ttk.Label(foot_info, textvariable=self.save_status, style="Subtitle.TLabel")
        self.save_label.pack(side="left")
        ttk.Label(foot_info, text="F9  暂停 / 继续     F10  紧急停止", style="Subtitle.TLabel").pack(side="right")
        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        self.save_button = ttk.Button(actions, text="保存配置", command=self._save_settings)
        self.save_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="停止", style="Danger.TButton", command=self._stop, width=5)
        self.stop_button.pack(side="right", padx=(8, 0))
        self.pause_button = ttk.Button(actions, text="暂停", command=self._pause, width=5)
        self.pause_button.pack(side="right", padx=(8, 0))
        self.start_button = ttk.Button(actions, text="开始每日任务", style="Primary.TButton", command=self._start)
        self.start_button.pack(side="right", padx=(8, 0))
        self.launch_button = ttk.Button(actions, text="启动游戏", command=self._launch)
        self.launch_button.pack(side="right", padx=(8, 0))
        self.check_button = ttk.Button(actions, text="检测窗口", command=self._check)
        self.check_button.pack(side="right")

        body = ttk.Frame(self.root, padding=(24, 0))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, minsize=420)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, style="Panel.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.settings_tabs = ttk.Notebook(left)
        self.settings_tabs.grid(sticky="nsew")
        daily = ttk.Frame(self.settings_tabs, style="Panel.TFrame", padding=(9, 8))
        game = ttk.Frame(self.settings_tabs, style="Panel.TFrame", padding=(9, 8))
        self.settings_tabs.add(daily, text="每日配置")
        self.settings_tabs.add(game, text="游戏与设置")
        self._build_daily(daily)
        self._build_game(game)

        right = ttk.Frame(body, style="Panel.TFrame", padding=16)
        right.grid(row=0, column=1, sticky="nsew")
        row = ttk.Frame(right, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="执行状态", style="Section.TLabel").pack(side="left")
        self.directory_button = ttk.Button(row, text="运行目录", style="Compact.TButton", command=lambda: self._open_path(self.last_run_dir))
        self.directory_button.pack(side="right")
        self.report_button = ttk.Button(row, text="最后报告", style="Compact.TButton", command=lambda: self._open_path(self.last_report_file))
        self.report_button.pack(side="right", padx=(0, 7))
        metrics = ttk.Frame(right, style="Panel.TFrame")
        metrics.pack(fill="x", pady=(16, 10))
        metrics.columnconfigure((0, 1, 2), weight=1, uniform="metric")
        for column, (label, variable) in enumerate((("当前任务", self.current_task), ("本次耗时", self.elapsed), ("已确认开拓力", self.stamina))):
            card = ttk.Frame(metrics, style="Panel.TFrame")
            card.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            ttk.Label(card, text=label, style="Muted.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(3, 0))
        self.summary_label = ttk.Label(right, textvariable=self.summary, style="Muted.TLabel", wraplength=550, justify="left")
        self.summary_label.pack(fill="x", pady=(0, 11))
        right.bind("<Configure>", lambda e: self.summary_label.configure(wraplength=max(360, e.width - 32)))
        self.table = ttk.Treeview(right, columns=("task", "status", "detail"), show="headings", height=5, selectmode="browse")
        for key, label, width in (("task", "任务", 145), ("status", "状态", 72), ("detail", "说明（点击行查看）", 230)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=60, stretch=key == "detail")
        self.table.pack(fill="x", pady=(0, 14))
        for name, label in TASK_NAMES.items():
            self.table.insert("", "end", iid=name, values=(label, "等待", ""))
        for tag, color in (("success", "#74d6b6"), ("failed", "#ffb6b6"), ("skipped", self.MUTED), ("running", self.ACCENT), ("partial", "#efc779")):
            self.table.tag_configure(tag, foreground=color)
        self.table.bind("<<TreeviewSelect>>", self._show_task_detail)
        self.output_tabs = ttk.Notebook(right)
        self.output_tabs.pack(fill="both", expand=True)
        log_tab = ttk.Frame(self.output_tabs, style="Panel.TFrame", padding=(0, 7, 0, 0))
        detect_tab = ttk.Frame(self.output_tabs, style="Panel.TFrame", padding=(10, 10))
        self.output_tabs.add(log_tab, text="运行日志")
        self.output_tabs.add(detect_tab, text="窗口检测")
        self.log = self._text(log_tab)
        self.log.pack(fill="both", expand=True)
        for level, color in (("warning", "#efc779"), ("error", "#ff9f9f"), ("success", "#74d6b6")):
            self.log.tag_configure(level, foreground=color)
        detect_head = ttk.Frame(detect_tab, style="Panel.TFrame")
        detect_head.pack(fill="x")
        ttk.Label(detect_head, textvariable=self.detect_title, style="Muted.TLabel", wraplength=310).pack(side="left")
        self.screenshot_button = ttk.Button(detect_head, text="查看截图", style="Compact.TButton", width=6, command=lambda: self._open_path(self.last_screenshot))
        self.screenshot_button.pack(side="right")
        self.details_button = ttk.Button(detect_head, text="识别详情", style="Compact.TButton", width=6, command=self._show_inspection)
        self.details_button.pack(side="right", padx=(0, 6))
        detect_meta = ttk.Frame(detect_tab, style="Panel.TFrame")
        detect_meta.pack(fill="x", pady=(5, 7))
        ttk.Label(detect_meta, textvariable=self.detect_size, style="Muted.TLabel").pack(side="left")
        ttk.Label(detect_meta, textvariable=self.detect_permission, style="Muted.TLabel").pack(side="right")
        self.inspection_text = self._text(detect_tab)
        self.inspection_text.pack(fill="both", expand=True)
        detect_tab.bind("<Configure>", self._resize_detection)
        self._replace_text(self.inspection_text, "检测后在此查看识别文字与截图位置。\n检测只检查当前窗口，不执行每日任务。")

    def _text(self, parent: tk.Widget) -> ScrolledText:
        return ScrolledText(parent, wrap="char", font=("Microsoft YaHei UI", 9), background=self.INSET,
                            foreground=self.TEXT, insertbackground=self.TEXT, relief="flat", borderwidth=0,
                            padx=11, pady=9, height=6, state="disabled")

    def _resize_detection(self, event: tk.Event) -> None:
        # On short windows the summary and detail button are more useful than
        # a text preview squeezed down to a few pixels.
        if event.height < 140:
            self.inspection_text.pack_forget()
        elif not self.inspection_text.frame.winfo_manager():
            self.inspection_text.pack(fill="both", expand=True)

    @staticmethod
    def _replace_text(widget: ScrolledText, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _build_daily(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="任务范围", style="Section.TLabel").pack(anchor="w")
        choices = ttk.Frame(parent, style="Panel.TFrame")
        choices.pack(fill="x", pady=(6, 4))
        choices.columnconfigure((0, 1), weight=1, uniform="tasks")
        for index, (key, label) in enumerate(TASK_NAMES.items()):
            widget = ttk.Checkbutton(choices, text=label, variable=self.tasks[key])
            widget.grid(row=index // 2, column=index % 2, sticky="w")
            self.setting_controls.append(widget)
            if key == "battle":
                self.battle_checkbox = widget
        ttk.Label(parent, text="目标副本", style="Section.TLabel").pack(anchor="w", pady=(2, 0))
        fields = ttk.Frame(parent, style="Panel.TFrame")
        fields.pack(fill="x", pady=(5, 7))
        fields.columnconfigure((0, 1), weight=1, uniform="fields")
        for col, (label, variable) in enumerate((("花萼名称", self.target_name), ("地点（可选）", self.target_location))):
            ttk.Label(fields, text=label, style="Muted.TLabel").grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 10, 0))
            widget = ttk.Entry(fields, textvariable=variable, width=12)
            widget.grid(row=1, column=col, sticky="ew", pady=(5, 0), padx=(0 if col == 0 else 10, 0))
            self.setting_controls.append(widget)
            self.stamina_controls.append(widget)
        numbers = ttk.Frame(parent, style="Panel.TFrame")
        numbers.pack(fill="x", pady=(0, 3))
        numbers.columnconfigure((0, 1), weight=1, uniform="numbers")
        for col, (label, variable, high, step) in enumerate((("累计开拓力上限", self.stamina_limit, 240, 10), ("每次挑战轮数", self.rounds, 6, 1))):
            ttk.Label(numbers, text=label, style="Muted.TLabel").grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 10, 0))
            widget = ttk.Spinbox(numbers, from_=step, to=high, increment=step, textvariable=variable, width=10)
            widget.grid(row=1, column=col, sticky="ew", pady=(5, 0), padx=(0 if col == 0 else 10, 0))
            self.setting_controls.append(widget)
            self.stamina_controls.append(widget)
        support = ttk.Checkbutton(parent, text="借用好友支援角色", variable=self.use_support)
        support.pack(anchor="w", pady=(0, 5))
        self.setting_controls.append(support)
        self.stamina_controls.append(support)
        presets = ttk.Frame(parent, style="Panel.TFrame")
        presets.pack(fill="x")
        presets.columnconfigure((0, 1), weight=1, uniform="presets")
        for col, (label, stamina, rounds) in enumerate((("每日 240 / 6 轮", 240, 6), ("测试 10 / 1 轮", 10, 1))):
            button = ttk.Button(presets, text=label, style="Compact.TButton", command=lambda s=stamina, r=rounds: self._preset(s, r))
            button.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
            self.setting_controls.append(button)
            self.stamina_controls.append(button)
        ttk.Label(parent, text="快捷模式只填写，不会自动运行。", style="Muted.TLabel").pack(anchor="w", pady=(3, 2))
        ttk.Label(parent, textvariable=self.battle_hint, style="Warning.TLabel", wraplength=355, justify="left").pack(anchor="w")

    def _build_game(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="游戏程序 · StarRail.exe", style="Section.TLabel").pack(anchor="w", pady=(0, 5))
        path_row = ttk.Frame(parent, style="Panel.TFrame")
        path_row.pack(fill="x")
        entry = ttk.Entry(path_row, textvariable=self.game_path, width=15)
        entry.pack(side="left", fill="x", expand=True)
        choose = ttk.Button(path_row, text="选择", style="Compact.TButton", command=self._choose_game, width=4)
        choose.pack(side="left", padx=(6, 0))
        auto = ttk.Checkbutton(parent, text="未运行时自动启动游戏", variable=self.auto_launch)
        auto.pack(anchor="w", pady=(5, 8))
        self.setting_controls.extend((entry, choose, auto))
        ttk.Label(parent, text="配置位置", style="Section.TLabel").pack(anchor="w")
        config_entry = ttk.Entry(parent, width=15)
        config_entry.insert(0, str(self.config_path.resolve()))
        config_entry.configure(state="readonly")
        config_entry.pack(fill="x", pady=(5, 6))
        ttk.Label(parent, text="保存不执行任务；操作前也会自动保存。", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(parent, text="开始前", style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text="更新、登录、密码与验证码需手动完成。\n简中 16:9；4K / 缩放环境先检测。\n提前配好队伍并解锁自动战斗。\n持续委托只领取奖励，保留原委托。", style="Muted.TLabel", wraplength=350, justify="left").pack(anchor="w", pady=(5, 6))
        ttk.Label(parent, text="永久禁项", style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text="抽卡、养成、商店、合成、购买与兑换。\n仅用已有开拓力，不使用燃料或星琼。", style="Warning.TLabel", justify="left").pack(anchor="w", pady=(5, 0))

    def _form_signature(self) -> tuple[Any, ...]:
        return tuple(variable.get() for variable in self.form_variables)

    @property
    def dirty(self) -> bool:
        return self._form_signature() != self._saved_signature

    def _form_changed(self, *_: Any) -> None:
        if self._loading:
            return
        if not self.settings.allow_stamina_spend and self.tasks["battle"].get():
            self.tasks["battle"].set(False)
        self.save_status.set("● 有未保存的修改" if self.dirty else ("配置已保存" if self.config_path.exists() else "默认配置 · 尚未保存"))
        self.save_label.configure(foreground="#efc779" if self.dirty else self.MUTED)
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        state = "disabled" if self.busy else "normal"
        for control in self.setting_controls:
            control.configure(state=state)
        allowed = self.settings.allow_stamina_spend
        self.battle_checkbox.configure(state="normal" if allowed and not self.busy else "disabled")
        battle_enabled = allowed and self.tasks["battle"].get()
        for control in self.stamina_controls:
            control.configure(state="normal" if battle_enabled and not self.busy else "disabled")
        if not allowed:
            hint = "开拓力刷本未授权，当前仅收取委托与奖励"
        elif not battle_enabled:
            hint = "未勾选花萼挑战，副本设置暂不参与执行。"
        elif not self.use_support.get():
            hint = "好友支援已关闭；标准每日流程需勾选支援。"
        else:
            hint = "仅用现有开拓力；不会使用燃料或星琼。"
        self.battle_hint.set(hint)
        if not self._has_run:
            for name, label in TASK_NAMES.items():
                selected = self.tasks[name].get()
                detail = "开拓力刷本未授权" if name == "battle" and not allowed else ("" if selected else "未勾选")
                self.table.item(name, values=(label, "等待" if selected else "跳过", detail), tags=() if selected else ("skipped",))
        for button in (self.save_button, self.check_button, self.launch_button):
            button.configure(state=state)
        self.start_button.configure(state="normal" if not self.busy and any(v.get() for v in self.tasks.values()) else "disabled")
        self.pause_button.configure(state="normal" if self.running and self.runner is not None and not self.stopping else "disabled", text="继续" if self.paused else "暂停")
        self.stop_button.configure(state="normal" if self.running and not self.stopping else "disabled")
        can_open = not self.busy or self.paused
        self.details_button.configure(state="normal" if can_open else "disabled")
        for button, path, directory in ((self.report_button, self.last_report_file, False), (self.directory_button, self.last_run_dir, True), (self.screenshot_button, self.last_screenshot, False)):
            exists = path is not None and (path.is_dir() if directory else path.is_file())
            button.configure(state="normal" if can_open and exists else "disabled")

    def _preset(self, stamina: int, rounds: int) -> None:
        if self.busy or not self.settings.allow_stamina_spend or not self.tasks["battle"].get():
            return
        self.stamina_limit.set(str(stamina))
        self.rounds.set(str(rounds))
        self._log(f"已填写 {'每日' if stamina == 240 else '测试'}模式：上限 {stamina} 开拓力、每次 {rounds} 轮。尚未开始执行。")

    def _choose_game(self) -> None:
        path = filedialog.askopenfilename(title="选择 StarRail.exe", filetypes=[("星穹铁道程序", "StarRail.exe"), ("应用程序", "*.exe")], initialdir=str(Path(self.game_path.get()).parent), parent=self.root)
        if path:
            self.game_path.set(path)

    def _read_settings(self, save: bool = True) -> Settings | None:
        try:
            settings = replace(self.settings, game_path=self.game_path.get().strip(), target_name=self.target_name.get().strip(),
                               target_location=self.target_location.get().strip(), stamina_limit=int(self.stamina_limit.get()),
                               rounds=int(self.rounds.get()), use_support=self.use_support.get(), auto_launch=self.auto_launch.get(),
                               **{name: variable.get() if name != "battle" or self.settings.allow_stamina_spend else False for name, variable in self.tasks.items()})
            settings.validate()
            if save:
                settings.save(self.config_path)
                self._loading = True
                self.game_path.set(settings.game_path)
                self.target_name.set(settings.target_name)
                self.target_location.set(settings.target_location)
                self.stamina_limit.set(str(settings.stamina_limit))
                self.rounds.set(str(settings.rounds))
                self.tasks["battle"].set(settings.battle)
                self._saved_signature = self._form_signature()
                self._loading = False
            self.settings = settings
            self._form_changed()
            return settings
        except (ValueError, TypeError, OSError) as exc:
            self._loading = False
            self.save_status.set("● 设置未保存，请检查输入或目录权限")
            self._log(f"配置保存失败：{exc}", "error")
            messagebox.showerror("设置未保存", str(exc), parent=self.root)
            return None

    def _save_settings(self) -> None:
        if not self.busy and self._read_settings() is not None:
            self._log("配置已保存。")

    def emit(self, event: dict[str, Any]) -> None:
        self.events.put(event)

    def _set_busy(self, busy: bool, running: bool = False) -> None:
        self.busy, self.running = busy, running
        if not running:
            self.paused = self.stopping = False
        self._refresh_controls()

    def _check(self) -> None:
        self._operation("check")

    def _launch(self) -> None:
        self._operation("launch")

    def _operation(self, action: str) -> None:
        if self.busy:
            return
        settings = self._read_settings()
        if settings is None:
            return
        self._set_busy(True)
        self.status.set("● 正在检测" if action == "check" else "● 正在启动")
        self._log("检测游戏窗口与 OCR，请稍候……" if action == "check" else "正在发送游戏启动请求……")
        if action == "check":
            self.root.iconify()

        def work() -> None:
            try:
                from .app import inspect_game, launch_game
                if action == "check":
                    self.emit({"type": "checked", "data": inspect_game(settings)})
                else:
                    self.emit({"type": "launched", "message": launch_game(settings)})
            except Exception as exc:
                self.emit({"type": "operation_error", "message": str(exc)})
        self.worker = threading.Thread(target=work, name=f"autohsr-{action}", daemon=True)
        self.worker.start()

    def _start(self) -> None:
        if self.busy:
            return
        settings = self._read_settings()
        if settings is None:
            return
        if not any(getattr(settings, key) for key in TASK_NAMES):
            messagebox.showinfo("未选择任务", "请至少勾选一项每日任务。", parent=self.root)
            return
        self.runner = None
        self._has_run = True
        self.paused = self.stopping = False
        self.stop_requested.clear()
        self.confirmed_stamina = self.elapsed_seconds = 0
        self.stamina.set("0")
        self.elapsed.set("00:00")
        self.current_task.set("准备进入游戏")
        self.started_at = time.monotonic()
        self._set_busy(True, True)
        self.status.set("● 正在运行")
        self.summary.set("任务执行中；F9 暂停 / 继续，F10 紧急停止。")
        self.output_tabs.select(0)
        self.table.selection_remove(*self.table.selection())
        for name, label in TASK_NAMES.items():
            enabled = getattr(settings, name)
            detail = "开拓力刷本未授权" if name == "battle" and not settings.allow_stamina_spend else ("" if enabled else "未勾选")
            self.table.item(name, values=(label, "等待" if enabled else "跳过", detail), tags=() if enabled else ("skipped",))
        self._log("开始执行每日任务。助手将最小化，让游戏保持前台。")
        self.root.iconify()

        def work() -> None:
            finished = threading.Event()

            def send(event: dict[str, Any]) -> None:
                if event_kind(event) == "finished":
                    finished.set()
                self.emit(event)
            try:
                from .app import Runner
                runner = Runner(settings, send)
                stop_applied = self.stop_requested.is_set()
                if stop_applied:
                    runner.stop()
                self.emit({"type": "runner_ready", "runner": runner, "stop_applied": stop_applied})
                report = runner.run()
                if not finished.is_set():
                    self.emit({"type": "finished", "report": report.to_dict() if hasattr(report, "to_dict") else report})
            except Exception as exc:
                self.emit({"type": "run_error", "message": str(exc)})
        self.worker = threading.Thread(target=work, name="autohsr-run", daemon=True)
        self.worker.start()

    def _pause(self) -> None:
        if self.runner is None or not self.running or self.stopping:
            return
        try:
            if self.paused:
                self.root.iconify()
            self._pause_state(bool(self.runner.toggle_pause()))
        except Exception as exc:
            self._log(f"暂停操作失败：{exc}", "error")
            self._restore()

    def _f9_press(self, _: tk.Event) -> str:
        self._f9_local_pressed = True
        return "break"

    def _f9_release(self, _: tk.Event) -> str:
        pressed = self._f9_local_pressed
        self._f9_local_pressed = False
        if pressed:
            self._pause()
        return "break"

    def _pause_state(self, paused: bool) -> None:
        if not self.running or self.stopping:
            return
        changed = paused != self.paused
        self._f9_local_pressed = False
        self.paused = paused
        self.status.set("● 已暂停" if paused else "● 正在运行")
        self.summary.set("任务已暂停；设置保持锁定。点击“继续”或按 F9 恢复。" if paused else "任务执行中；F9 暂停 / 继续，F10 紧急停止。")
        self._refresh_controls()
        if changed:
            self._log("已暂停。点击“继续”或按 F9 恢复。" if paused else "继续执行任务。", "warning" if paused else "info")
        if paused:
            self._restore()
        elif not self.closing:
            self.root.iconify()

    def _stop(self) -> None:
        if not self.running or self.stopping:
            return
        self.stopping = True
        self.paused = False
        self.stop_requested.set()
        if self.runner is not None:
            self.runner.stop()
        self.status.set("● 正在停止")
        self.summary.set("停止请求已发送，正在结束当前操作并保存报告。")
        self._refresh_controls()
        self._log("停止请求已发送，正在结束当前操作。", "warning")

    def _progress(self, spent: Any) -> None:
        if type(spent) is int and spent >= 0:
            self.confirmed_stamina = spent
            self.stamina.set(str(spent))

    def _log(self, message: Any, level: str = "info") -> None:
        message = str(message)
        match = re.search(r"累计确认消耗\s*(\d+)\s*开拓力", message)
        if self.running and match:
            self._progress(int(match.group(1)))
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {message}\n", level)
        if int(self.log.index("end-1c").split(".")[0]) > 2500:
            self.log.delete("1.0", "501.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _task(self, event: dict[str, Any], log: bool = True) -> None:
        task = str(event.get("task", ""))
        task = next((key for key, label in TASK_NAMES.items() if task == label), task)
        status, detail = str(event.get("status", "pending")), str(event.get("detail", ""))
        if task in TASK_NAMES:
            tag = "success" if status in ("success", "ok", "completed", "done") else status
            self.table.item(task, values=(TASK_NAMES[task], STATUS_NAMES.get(status, status), detail), tags=(tag,))
            if status == "running":
                self.current_task.set(TASK_NAMES[task])
        if log:
            self._log(f"{TASK_NAMES.get(task, task)}：{STATUS_NAMES.get(status, status)} {detail}".strip(), "error" if status in ("failed", "error") else "info")

    def _show_task_detail(self, _: tk.Event | None = None) -> None:
        selected = self.table.selection()
        if selected and (not self.running or self.paused):
            label, status, detail = self.table.item(selected[0], "values")
            self.summary.set(f"{label} · {status}：{detail or '暂无详细说明'}")

    def _restore(self) -> None:
        if not self.closing:
            self.root.deiconify()
            self.root.lift()

    def _clock(self) -> None:
        seconds = int(time.monotonic() - self.started_at) if self.started_at is not None else self.elapsed_seconds
        minutes, seconds = divmod(max(0, seconds), 60)
        hours, minutes = divmod(minutes, 60)
        self.elapsed.set(f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}")

    def _freeze_clock(self) -> None:
        if self.started_at is not None:
            self.elapsed_seconds = int(time.monotonic() - self.started_at)
            self.started_at = None
        self._clock()

    def _finish(self, report: Any) -> None:
        if hasattr(report, "to_dict"):
            report = report.to_dict()
        report = report if isinstance(report, dict) else {}
        for result in report.get("results", []):
            if isinstance(result, dict):
                self._task(result, log=False)
        status = str(report.get("status", "partial"))
        self._finalize_task_rows(status)
        self._progress(report.get("stamina_spent", 0))
        self._freeze_clock()
        daily = "已验证" if report.get("daily_verified", False) else "未验证"
        self.summary.set(f"{STATUS_NAMES.get(status, status)} · 已确认消耗 {self.confirmed_stamina} 开拓力 · 每日奖励 {daily}")
        self.current_task.set(STATUS_NAMES.get(status, status))
        self._log(self.summary.get(), "success" if status in ("success", "completed", "done") else "warning")
        if report.get("run_dir"):
            self.last_run_dir = Path(report["run_dir"])
            self.last_report_file = self.last_run_dir / "report.json"
            self._log(f"运行报告与截图：{self.last_run_dir}")
        self.runner = None
        self._set_busy(False)
        self.status.set(f"● {STATUS_NAMES.get(status, status)}")
        self._restore()

    def _finalize_task_rows(self, status: str) -> None:
        for name in TASK_NAMES:
            label, previous, _ = self.table.item(name, "values")
            if previous == "进行中":
                final = "stopped" if status in ("stopped", "cancelled") else ("failed" if status in ("failed", "error") else "partial")
                self._task({"task": name, "status": final, "detail": "执行中断，未确认完成；请查看日志与报告。"}, log=False)
            elif previous == "等待":
                self.table.item(name, values=(label, "未执行", "流程已结束，此项未执行。"), tags=("skipped",))

    def _checked(self, data: dict[str, Any]) -> None:
        title = str(data.get("title") or "已找到游戏窗口")
        size = f"客户区尺寸：{data.get('width', '?')} × {data.get('height', '?')}"
        permission = f"助手管理员权限：{'是' if data.get('administrator') else '否'}"
        self.detect_title.set(title)
        self.detect_size.set(size)
        self.detect_permission.set(permission)
        self.last_screenshot = Path(data["screenshot"]) if data.get("screenshot") else None
        self._replace_text(self.inspection_text, f"窗口：{title}\n{size}\n{permission}\n截图：{self.last_screenshot or '未生成'}\n\nOCR 识别文字\n{data.get('ocr_text') or '未识别到文字'}")
        self._set_busy(False)
        self.status.set("● 检测完成")
        self._log(f"检测完成：{title}；{size}；{permission}。识别详情见“窗口检测”。")
        self.output_tabs.select(1)
        self._restore()

    def _discover_report(self) -> None:
        try:
            reports = list((ROOT / "runs").glob("*/report.json"))
            if reports:
                self.last_report_file = max(reports, key=lambda p: p.stat().st_mtime)
                self.last_run_dir = self.last_report_file.parent
        except OSError:
            pass

    def _open_path(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            if not path.exists():
                raise OSError("文件或目录已不存在，请查看运行日志。")
            os.startfile(str(path.resolve()))
        except OSError as exc:
            self._log(f"无法打开：{exc}", "error")
            messagebox.showerror("无法打开", str(exc), parent=self.root)

    def _show_inspection(self) -> None:
        if self.busy and not self.paused:
            return
        details = tk.Toplevel(self.root)
        details.title("AutoHSR · 窗口识别详情")
        details.geometry("760x520")
        details.minsize(580, 360)
        details.configure(bg=self.BG)
        details.transient(self.root)
        frame = ttk.Frame(details, style="Panel.TFrame", padding=14)
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(frame, text="窗口识别详情", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        text = self._text(frame)
        text.pack(fill="both", expand=True)
        self._replace_text(text, self.inspection_text.get("1.0", "end-1c"))
        ttk.Button(frame, text="关闭", command=details.destroy).pack(anchor="e", pady=(10, 0))

    def _drain(self) -> None:
        try:
            for _ in range(100):
                event = self.events.get_nowait()
                kind = event_kind(event)
                if kind == "log":
                    self._log(event.get("message", ""), str(event.get("level", "info")))
                elif kind == "task":
                    self._task(event)
                elif kind == "progress":
                    self._progress(event.get("stamina_spent"))
                elif kind == "paused":
                    self._pause_state(bool(event.get("paused", False)))
                elif kind == "runner_ready":
                    self.runner = event["runner"]
                    if self.stop_requested.is_set() and not event.get("stop_applied", False):
                        self.runner.stop()
                    self._refresh_controls()
                elif kind == "finished":
                    self._finish(event.get("report", {}))
                elif kind == "checked":
                    self._checked(event.get("data", {}))
                elif kind == "launched":
                    self._set_busy(False)
                    self.status.set("● 启动请求已发送")
                    self._log(event.get("message") or "启动请求已发送。请完成登录。")
                elif kind in ("operation_error", "run_error"):
                    self.runner = None
                    if kind == "run_error":
                        self._freeze_clock()
                        self._finalize_task_rows("failed")
                        self.current_task.set("执行失败")
                    self._set_busy(False)
                    self.status.set("● 执行失败")
                    self.summary.set(str(event.get("message", "未知错误")))
                    self._log(self.summary.get(), "error")
                    self.output_tabs.select(0)
                    self._restore()
        except queue.Empty:
            pass
        self._clock()
        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self.root.destroy()
            return
        self.root.after(100, self._drain)

    def _close(self) -> None:
        if self.closing:
            return
        if not self.busy and self.dirty:
            choice = messagebox.askyesnocancel("保存修改", "配置有未保存的修改，关闭前保存吗？", parent=self.root)
            if choice is None or (choice and self._read_settings() is None):
                return
        self.closing = True
        if self.running:
            self._stop()
        self.root.withdraw()
        if self.worker is None or not self.worker.is_alive():
            self.root.destroy()


def main(config_path: Path = CONFIG_PATH) -> None:
    # Establish DPI awareness before Tk creates a window.
    from . import windows  # noqa: F401
    root = tk.Tk()
    AutoHSRWindow(root, config_path)
    root.mainloop()
