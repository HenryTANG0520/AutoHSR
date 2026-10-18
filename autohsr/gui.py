"""Chinese desktop interface; worker threads only communicate through events."""
from __future__ import annotations

import os
import json
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
from .ux import report_context, recovery_text, exit_text

TASK_NAMES = {
    "assignments": "持续委托奖励", "battle": "拟造花萼挑战",
    "daily": "每日实训奖励", "mail": "邮件附件", "battlepass": "无名勋礼奖励",
}
STATUS_NAMES = {
    "pending": "等待", "running": "进行中", "success": "全部完成", "ok": "完成",
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
        self.focus_waiting = False
        self.active_operation = "daily"
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
        style.configure('TCombobox',fieldbackground='#1d2e46',background='#294461',foreground=self.TEXT,
                        arrowcolor=self.TEXT,font=('Microsoft YaHei UI',10))
        style.map('TCombobox',fieldbackground=[('disabled','#17263b'),('readonly','#1d2e46')],
                  foreground=[('disabled','#60758d'),('readonly',self.TEXT)],
                  selectbackground=[('readonly','#1d2e46')],selectforeground=[('readonly',self.TEXT)])
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
        self.plan = tk.StringVar()
        self.readiness = tk.StringVar(value="游戏窗口与输入条件：尚未检测")
        self.history_context = tk.StringVar(value="暂无历史运行记录")
        self.recovery_hint = tk.StringVar()
        self.action_delay = tk.StringVar(value=str(self.settings.action_delay))
        self.battle_timeout = tk.StringVar(value=str(self.settings.battle_timeout))
        self.ocr_confidence = tk.StringVar(value=str(self.settings.ocr_confidence))
        self.form_variables.extend((self.action_delay, self.battle_timeout, self.ocr_confidence))
        self.detect_title = tk.StringVar(value="尚未检测游戏窗口")
        self.detect_size = tk.StringVar(value="客户区尺寸：—")
        self.detect_permission = tk.StringVar(value="助手管理员权限：—")
        self.currency_status = tk.StringVar(value="已采集 4.6 教程与经济规则；提供只读识别、部署和节点验证，完整自动对局仍待验证。")
        self.currency_observation = tk.StringVar(value="尚无本次识别证据。报告与截图可从底部入口查看。")
        self.currency_source_slot = tk.StringVar(value='3')
        self.currency_zone = tk.StringVar(value='后台')
        self.currency_target_level = tk.StringVar(value='保持')

    def _build(self):
        from .desktop import build_window
        build_window(self, TASK_NAMES, {})

    def _show_page(self, name):
        self.active_page = name
        for key, page in self.pages.items():
            page.grid() if key == name else page.grid_remove()
            self.nav_buttons[key].configure(style="Selected.Nav.TButton" if key == name else "Nav.TButton")
        currency = name == "currency_wars"
        self.start_button.configure(text="只读识别当前画面" if currency else "开始每日",
                                    command=self._currency_wars if currency else self._start)
        self._refresh_controls()

    def _text_tab(self, title):
        frame = ttk.Frame(self.output_tabs)
        self.output_tabs.add(frame, text=title)
        text = self._text(frame)
        text.pack(fill="both", expand=True)
        return text

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

    def _build_battle_fields(self, parent):
        ttk.Label(parent, text="目标副本", style="Section.TLabel").pack(anchor="w", pady=(2, 0))
        fields = ttk.Frame(parent, style="Panel.TFrame")
        fields.pack(fill="x", pady=(5, 7))
        fields.columnconfigure((0, 1), weight=1, uniform="fields")
        for col, (label, variable) in enumerate((("花萼名称", self.target_name), ("地点（刷本必填）", self.target_location))):
            ttk.Label(fields, text=label, style="Muted.TLabel").grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 10, 0))
            widget = ttk.Entry(fields, textvariable=variable, width=12)
            widget.grid(row=1, column=col, sticky="ew", pady=(5, 0), padx=(0 if col == 0 else 10, 0))
            self.setting_controls.append(widget)
            self.stamina_controls.append(widget)
        numbers = ttk.Frame(parent, style="Panel.TFrame")
        numbers.pack(fill="x", pady=(0, 3))
        numbers.columnconfigure((0, 1), weight=1, uniform="numbers")
        for col, (label, variable, high, step) in enumerate((("本次运行最多消耗", self.stamina_limit, 240, 10), ("每次挑战轮数", self.rounds, 6, 1))):
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
        for col, (label, stamina, rounds) in enumerate((("本轮 240 / 每批6轮", 240, 6), ("测试 10 / 1 轮", 10, 1))):
            button = ttk.Button(presets, text=label, style="Compact.TButton", command=lambda s=stamina, r=rounds: self._preset(s, r))
            button.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
            self.setting_controls.append(button)
            self.stamina_controls.append(button)
        ttk.Label(parent, text="快捷模式只填写，不会自动运行。", style="Muted.TLabel").pack(anchor="w", pady=(3, 2))
        ttk.Label(parent, textvariable=self.battle_hint, style="Warning.TLabel", wraplength=355, justify="left").pack(anchor="w")

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
        selected = [label for key, label in TASK_NAMES.items() if self.tasks[key].get()]
        battle = f" · {self.target_name.get()} / {self.target_location.get() or '地点待填写'} · 本轮最多 {self.stamina_limit.get()} · 每批 {self.rounds.get()} 轮" if self.tasks["battle"].get() else " · 不刷本"
        self.plan.set(("自动启动游戏" if self.auto_launch.get() else "使用已打开的游戏") + battle + "\n" + "、".join(selected))
        self._refresh_controls()

    def _refresh_recovery(self):
        from .recovery import recovery_state
        state = recovery_state(ROOT / "runs")
        pending = state['pending'] if state['pending'] is not None else '未记录'
        self.recovery_hint.set((state.get("reason") if state["corrupt"] else
            f"上次刷本未完整结束：已确认 {state['spent']}，待核对 {pending}。可先仅补领奖；新刷本需确认新增预算。")
            if state["blocked"] else "本次运行使用独立预算；异常后保留已确认与待核对消耗。")

    def _refresh_controls(self) -> None:
        state = "disabled" if self.busy else "normal"
        for control in self.setting_controls:
            control.configure(state=state)
        for name in ('currency_source_combo','currency_zone_combo','currency_level_combo'):
            if hasattr(self,name):
                getattr(self,name).configure(state='disabled' if self.busy else 'readonly')
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
        currency_page = getattr(self, "active_page", "") == "currency_wars"
        self.start_button.configure(state="normal" if not self.busy and (currency_page or any(v.get() for v in self.tasks.values())) else "disabled")
        self.pause_button.configure(state="normal" if self.running and self.runner is not None and not self.stopping else "disabled", text="继续" if self.paused else "暂停")
        self.stop_button.configure(state="normal" if self.busy and not self.stopping else "disabled")
        self.reward_button.configure(state="normal" if not self.busy and not currency_page else "disabled")
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

    def _read_settings(self, save=False, operation="daily") -> Settings | None:
        try:
            values = dict(game_path=self.game_path.get().strip())
            if not save and operation.startswith("currency_wars"):
                values.update(auto_launch=False, assignments=False, battle=False, daily=False, mail=False, battlepass=False,
                              ocr_confidence=float(self.ocr_confidence.get()))
            elif save or operation not in ("check", "launch"):
                values.update(auto_launch=self.auto_launch.get(),
                              **{name: variable.get() if name != "battle" or self.settings.allow_stamina_spend else False for name, variable in self.tasks.items()})
                if operation == "reward_only":
                    values.update(assignments=False, battle=False, daily=True, mail=False, battlepass=False)
                if values["battle"] and self.settings.allow_stamina_spend:
                    values.update(target_name=self.target_name.get().strip(), target_location=self.target_location.get().strip(),
                                  stamina_limit=int(self.stamina_limit.get()), rounds=int(self.rounds.get()), use_support=self.use_support.get())
                values.update(action_delay=float(self.action_delay.get()), battle_timeout=int(self.battle_timeout.get()),
                              ocr_confidence=float(self.ocr_confidence.get()))
            elif operation == "check":
                values["ocr_confidence"] = float(self.ocr_confidence.get())
            settings = replace(self.settings, **values)
            settings.validate("save" if save else operation)
            if save:
                settings.save(self.config_path)
                self.settings = settings
                self._loading = True
                self.target_name.set(settings.target_name)
                self.target_location.set(settings.target_location)
                self.stamina_limit.set(str(settings.stamina_limit))
                self.rounds.set(str(settings.rounds))
                self._saved_signature = self._form_signature()
                self._loading = False
                self._form_changed()
            else:
                self.save_status.set("本次使用当前表单；未写入配置。")
            return settings
        except (ValueError, TypeError, OSError) as exc:
            self.save_status.set("输入未通过检查；配置未改变。")
            self._log(f"输入未通过检查：{exc}", "error")
            messagebox.showerror("请检查输入", str(exc), parent=self.root)
            return None

    def _save_settings(self) -> None:
        if not self.busy and self._read_settings(save=True, operation="save") is not None:
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
        if self.busy or self.closing or (self.worker is not None and self.worker.is_alive()):
            return
        settings = self._read_settings(operation=action)
        if settings is None:
            return
        self.stop_requested.clear()
        self._set_busy(True)
        self.status.set("● 正在检测" if action == "check" else "● 正在启动")
        self._log("检测游戏窗口与 OCR，请稍候……" if action == "check" else "正在发送游戏启动请求……")
        if action == "check":
            self.root.iconify()

        def work() -> None:
            try:
                if self.stop_requested.is_set():
                    self.emit({"type": "cancelled"})
                    return
                from .app import inspect_game, launch_game
                if action == "check":
                    data = inspect_game(settings)
                    self.emit({"type": "cancelled"} if self.stop_requested.is_set() else {"type": "checked", "data": data})
                else:
                    self.emit({"type": "launched", "message": launch_game(settings)})
            except Exception as exc:
                self.emit({"type": "operation_error", "message": str(exc)})
        self.worker = threading.Thread(target=work, name=f"autohsr-{action}", daemon=True)
        self.worker.start()

    def _reward_only(self):
        self._start(reward_only=True)

    def _currency_wars(self):
        self._start(currency_wars=True)

    def _currency_control_probe(self):
        self._start(currency_wars=True, currency_control_probe=True)

    def _currency_timeout_probe(self):
        self._start(currency_wars=True, currency_timeout_probe=True)

    def _currency_drag_test(self):
        self._start(currency_wars=True, drag_test=True)

    def _currency_deploy_test(self):
        self._start(currency_wars=True, deploy_test=True,
            currency_source_slot=int(self.currency_source_slot.get()),currency_zone='front' if self.currency_zone.get()=='前台' else 'back')

    def _currency_node_test(self):
        self._start(currency_wars=True, node_test=True)

    def _currency_flow_test(self):
        value=self.currency_target_level.get()
        self._start(currency_wars=True, flow_test=True,currency_target_level=0 if value=='保持' else int(value))

    def _currency_match_test(self):
        self._start(currency_wars=True,flow_test=True,currency_start_from_lobby=True)

    def _start(self, reward_only=False, *, currency_wars=False, drag_test=False, deploy_test=False, node_test=False, flow_test=False,
               currency_source_slot=3,currency_zone='back',currency_target_level=0,currency_start_from_lobby=False,
               currency_control_probe=False,currency_timeout_probe=False) -> None:
        if self.busy or self.closing or (self.worker is not None and self.worker.is_alive()):
            return
        currency_wars = currency_wars or drag_test or deploy_test or node_test or flow_test
        operation = "currency_wars_flow_test" if flow_test else "currency_wars_node_test" if node_test else "currency_wars_deploy_test" if deploy_test else "currency_wars_drag_test" if drag_test else "currency_wars" if currency_wars else "reward_only" if reward_only else "daily"
        settings = self._read_settings(operation=operation)
        if settings is None:
            return
        from .recovery import recovery_state, reward_only_settings
        new_battle_run = False
        if reward_only:
            settings = reward_only_settings(settings)
        elif not currency_wars and settings.battle and settings.allow_stamina_spend:
            state = recovery_state(ROOT / "runs")
            if state["blocked"]:
                if state["corrupt"]:
                    messagebox.showerror("刷本记录待核对", state["reason"], parent=self.root)
                    return
                pending = state['pending'] if state['pending'] is not None else '未记录'
                new_battle_run = messagebox.askyesno("确认新一轮刷本预算",
                    f"上次已确认 {state['spent']}，待核对 {pending} 开拓力。\n"
                    f"这不是续跑：本次会新增最多 {settings.stamina_limit} 开拓力预算。\n"
                    "如只需领取每日奖励，请选否，再点“仅补领奖”。\n确定已人工核对，仍要开始新一轮？", default="no", parent=self.root)
                if not new_battle_run:
                    return
        if not currency_wars and not any(getattr(settings, key) for key in TASK_NAMES):
            messagebox.showinfo("未选择任务", "请至少勾选一项每日任务。", parent=self.root)
            return
        self.runner = None
        self.active_operation = operation
        deployment_label=f"备战{currency_source_slot}→空"+('前台' if currency_zone=='front' else '后台')
        self.plan.set("货币战争 · 整局验证 · 超频A0" if flow_test and currency_start_from_lobby else ("货币战争 · 连续流程验证"+(f" · 升级至Lv{currency_target_level}" if currency_target_level else " · 不购买经验")) if flow_test else "货币战争 · 当前节点战斗验证" if node_test else f"货币战争 · 单次{deployment_label}部署" if deploy_test else "货币战争 · 单次前台3→1拖动验证" if drag_test else "货币战争 · 只读识别 · 自动玩法未开放" if currency_wars else
                      "仅补领奖 · 不刷本 · 不执行附加任务 · 本次不保存" if reward_only else
                      ("自动启动游戏" if settings.auto_launch else "使用已打开的游戏") +
                      (f" · {settings.target_name} / {settings.target_location} · 本轮最多 {settings.stamina_limit} · 每批 {settings.rounds} 轮" if settings.battle else " · 不刷本"))
        self._has_run = True
        self.paused = self.stopping = False
        self.focus_waiting = False
        self.stop_requested.clear()
        self.confirmed_stamina = self.elapsed_seconds = 0
        self.stamina.set("0")
        self.elapsed.set("00:00")
        self.current_task.set("货币战争连续流程验证" if flow_test else "货币战争节点战斗验证" if node_test else
                              "货币战争部署验证" if deploy_test else "货币战争拖动验证" if drag_test else
                              "货币战争只读识别" if currency_wars else "准备进入游戏")
        if currency_wars:
            self.currency_status.set("正在推进已校准战斗、选择、编队、奖励及装备；未知反馈停下留证。F9 暂停，F10 停止。" if flow_test else "正在验证当前节点出战与结算。F9 暂停，F10 停止。" if node_test else f"正在部署：{deployment_label}。F9 暂停，F10 停止。" if deploy_test else "正在验证一次前台3→1拖动。F9 暂停，F10 停止。" if drag_test else "正在只读识别，自动玩法保持关闭。F9 暂停，F10 停止。")
            self.currency_observation.set("正在生成本次证据；上次截图与报告保留在运行日志中。")
            self.last_screenshot = None
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
        self._log("开始货币战争流程推进验证。" if flow_test else "开始货币战争当前节点战斗验证。" if node_test else "开始货币战争单次部署验证。" if deploy_test else "开始货币战争单次拖动验证。" if drag_test else "开始货币战争只读识别。" if currency_wars else "开始执行每日任务。助手将最小化，让游戏保持前台。")
        self.root.iconify()

        def work() -> None:
            def send(event: dict[str, Any]) -> None:
                # Publish the terminal result only after run() returns. A backend
                # exception after its own finished event must remain a failure.
                if event_kind(event) != "finished":
                    self.emit(event)
            try:
                from .app import Runner
                runner = Runner(settings, send, new_battle_run=new_battle_run, operation=operation,
                    **(dict(currency_control_probe=True) if currency_control_probe else {}),
                    **(dict(currency_timeout_probe=True) if currency_timeout_probe else {}),
                    **(dict(currency_source_slot=currency_source_slot,currency_zone=currency_zone) if deploy_test else {}),
                    **(dict(currency_target_level=currency_target_level,currency_start_from_lobby=currency_start_from_lobby) if flow_test else {}))
                stop_applied = self.stop_requested.is_set()
                if stop_applied:
                    runner.stop()
                self.emit({"type": "runner_ready", "runner": runner, "stop_applied": stop_applied})
                report = runner.run()
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
        if not paused and self.focus_waiting:
            self.status.set("等待游戏回到前台")
            self.summary.set("输入已暂停；切回游戏后重新识别，F10可停止。")
        self._refresh_controls()
        if changed:
            self._log("已暂停。点击“继续”或按 F9 恢复。" if paused else "继续执行任务。", "warning" if paused else "info")
        if paused:
            self._restore()
        elif not self.closing:
            self.root.iconify()

    def _stop(self) -> None:
        if not self.busy or self.stopping:
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
        if task == "currency_wars":
            self.currency_status.set(detail)
            self.current_task.set("货币战争连续流程验证" if self.active_operation == "currency_wars_flow_test" else "货币战争节点战斗验证" if self.active_operation == "currency_wars_node_test" else "货币战争部署验证" if self.active_operation == "currency_wars_deploy_test" else "货币战争拖动验证" if self.active_operation == "currency_wars_drag_test" else "货币战争只读识别")
        if task in TASK_NAMES:
            tag = "success" if status in ("success", "ok", "completed", "done") else status
            self.table.item(task, values=(TASK_NAMES[task], STATUS_NAMES.get(status, status), detail), tags=(tag,))
            if status == "running":
                self.current_task.set(TASK_NAMES[task])
        if log:
            label = "货币战争" if task == "currency_wars" else TASK_NAMES.get(task, task)
            self._log(f"{label}：{STATUS_NAMES.get(status, status)} {detail}".strip(), "error" if status in ("failed", "error") else "info")

    def _currency_observed(self, data: dict) -> None:
        from .currency_wars_pages import PAGE_LABELS
        if data.get('mode') == 'flow_test':
            count = sum(a.get('node_verified') is True for a in data.get('actions',[]))
            purchases=[a for a in data.get('actions',[]) if a.get('decision')]
            choice=''
            if purchases:
                decision=purchases[-1]['decision']
                reasons='、'.join(label for label,points in decision['reasons'] if points>0)
                choice=f"\n最近决策：购买{decision['name']}，评分{decision['score']}；{reasons}。"
            self.currency_observation.set(f"流程推进：已验证 {count} 个节点；{data.get('action_status','待核对')}，整局尚未完成。"+choice+f"\n截图：{data.get('screenshot') or '未保存'}")
            if data.get('screenshot'):
                self.last_screenshot=Path(data['screenshot'])
            return
        if data.get('mode') == 'single_node_test':
            status = '节点胜利已验证' if data.get('node_verified') else '节点结果待核对'
            self.currency_observation.set(f"{data.get('origin_node', '')}：{status}；整局尚未完成。\n截图：{data.get('screenshot', '未保存')}")
            if data.get('screenshot'):
                self.last_screenshot = Path(data['screenshot'])
            return
        if data.get("mode") in ("single_drag_test", "single_deployment_test"):
            status = {"verified": "部署已确认" if data.get("mode") == "single_deployment_test" else "头像已互换", "unchanged": "卡位未改变", "pending": "动作结果待核对"}.get(data.get("action_status"), "结果尚未确认")
            self.currency_observation.set(f"单次拖动验证：{status}。\n前：{data.get('before', '未保存')}\n后：{data.get('after', '未保存')}")
            if data.get("screenshot"):
                self.last_screenshot = Path(data["screenshot"])
            return
        text = ("朝露公馆 · 货币战争交互入口，尚未打开玩法。" if data.get("page_kind") == "world_entry" else
                f"已识别{PAGE_LABELS[data['page_kind']]}；自动玩法及整局完成状态尚未验证。" if data.get("page_verified") and data.get("page_kind") in PAGE_LABELS else
                "已记录候选文字；当前页面仍未核实。" if data.get("mode_text_visible") else
                "未记录可信的完整玩法名称；当前页面未核实。")
        match = data.get("match")
        if isinstance(match, dict):
            fields = [("节点", match.get("node")), ("金币", match.get("gold")), ("等级", match.get("level"))]
            if match.get("deployment"):
                fields.append(("出战", "/".join(map(str, match["deployment"]))))
            text += "\n" + " · ".join(f"{label}：{value if value is not None else '未识别'}" for label, value in fields)
        self.currency_observation.set(text + "\n截图：" + (data.get("screenshot") or "未保存"))
        if data.get("screenshot"):
            self.last_screenshot = Path(data["screenshot"])

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
        currency = report.get("operation", self.active_operation).startswith("currency_wars")
        if not currency and report.get("daily_verified") is True:
            self._task(dict(task="daily", status="ok", detail="每日实训奖励已核实领取。"), log=False)
        self._finalize_task_rows(status)
        self._progress(report.get("stamina_spent", 0))
        self._freeze_clock()
        daily = "已验证" if report.get("daily_verified", False) else "未验证"
        pending = report.get("stamina_pending", 0)
        self.summary.set(f"{STATUS_NAMES.get(status, status)} · 本轮已确认 {self.confirmed_stamina} / 上限 {report.get('stamina_limit', '未记录')} · 待核对 {pending} · 每日奖励 {daily} · {exit_text(report)}" + ("\n" + recovery_text(report) if recovery_text(report) else ""))
        if currency:
            outcome = ("已停止" if status == "stopped" else "运行失败" if status == "failed" else
                       "只读识别结束" if report.get('operation', self.active_operation) == 'currency_wars' else
                       "连续流程验证结束" if report.get('operation', self.active_operation) == 'currency_wars_flow_test' else "单步验证结束")
            self.summary.set(f"货币战争 · {outcome} · 玩法未完成 · 自动玩法未开放" + ("\n" + recovery_text(report) if recovery_text(report) else ""))
            self.currency_status.set(self.summary.get())
            if report.get("currency_wars"):
                self._currency_observed(report["currency_wars"])
            else:
                self.currency_observation.set("本次未生成有效观察记录；请查看日志中的原因后重新识别。")
        self.history_context.set(report_context(report, Path(report["run_dir"]) / "report.json" if report.get("run_dir") else None))
        if report.get("report_saved") is False:
            self.history_context.set("本次报告未写入磁盘 · " + self.history_context.get())
        self._replace_text(self.report_text, json.dumps(report, ensure_ascii=False, indent=2))
        self.current_task.set(STATUS_NAMES.get(status, status))
        self._log(self.summary.get(), "success" if status in ("success", "completed", "done") else "warning")
        if report.get("run_dir"):
            self.last_run_dir = Path(report["run_dir"])
            self.last_report_file = self.last_run_dir / "report.json"
            self._log(("本次报告未保存；已保留的其他证据目录：" if report.get("report_saved") is False else "运行报告与截图：") + str(self.last_run_dir))
        self.runner = None
        self._set_busy(False)
        self.focus_waiting = False
        self._refresh_recovery()
        self.status.set(f"● {'玩法未完成' if currency and status not in ('failed', 'stopped') else STATUS_NAMES.get(status, status)}")
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
        self.readiness.set("输入条件：" + ("已核对权限匹配（输入效果未实测，仍需已登录）" if data.get("input_ready") is True else
                                           data.get("input_hint", "尚未核实游戏输入权限")))
        self._show_page("logs")
        self.output_tabs.select(1)
        self._restore()

    def _discover_report(self) -> None:
        self._refresh_recovery()
        try:
            reports = list((ROOT / "runs").glob("*/report.json"))
            if reports:
                self.last_report_file = max(reports, key=lambda p: p.stat().st_mtime)
                content = self.last_report_file.read_text(encoding="utf-8")
                self.history_context.set(report_context(json.loads(content), self.last_report_file))
                self._replace_text(self.report_text, content)
                self.last_run_dir = self.last_report_file.parent
        except (OSError, ValueError):
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
                if (kind in ("finished", "checked", "launched", "cancelled", "operation_error", "run_error")
                        and self.worker is not None and self.worker.is_alive()):
                    # Keep settings and new-run actions locked until the worker
                    # has actually exited, including the small emit/return gap.
                    self.events.put(event)
                    break
                if kind == "log":
                    self._log(event.get("message", ""), str(event.get("level", "info")))
                elif kind == "task":
                    self._task(event)
                elif kind == "currency_wars":
                    self._currency_observed(event.get("data", {}))
                elif kind == "progress":
                    self._progress(event.get("stamina_spent"))
                elif kind == "paused":
                    self._pause_state(bool(event.get("paused", False)))
                elif kind == "focus_wait":
                    self.focus_waiting = bool(event.get("waiting"))
                    if self.running and not self.paused and not self.stopping:
                        self.status.set("等待游戏回到前台" if self.focus_waiting else "正在运行")
                        self.summary.set("输入已暂停；切回游戏后重新识别，F10可停止。" if self.focus_waiting else "按当前画面继续，保留本轮预算。")
                elif kind == "cancelled":
                    self._set_busy(False)
                    self.status.set("已停止")
                    self.summary.set("检测已停止；未执行任务，配置未改变。")
                    self._restore()
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
                    if kind == "run_error" and self.active_operation.startswith("currency_wars"):
                        self.currency_status.set("只读识别失败：" + self.summary.get())
                        self.currency_observation.set("本次未生成有效观察记录；自动玩法仍未开放。")
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
            if choice is None or (choice and self._read_settings(save=True, operation="save") is None):
                return
        self.closing = True
        if self.busy:
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
