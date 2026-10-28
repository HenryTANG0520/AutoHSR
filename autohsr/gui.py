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

from .config import CONFIG_PATH, ROOT, Settings, SettingsError
from .ux import report_context, recovery_text, exit_text, immersifier_text, issue_text, standard_activity, standard_run_verified, universe_result
from . import theme

TASK_NAMES = {
    "assignments": "持续委托奖励", "battle": "日常副本挑战",
    "daily": "每日实训奖励", "mail": "邮件附件", "battlepass": "无名勋礼奖励",
}
STATUS_NAMES = {
    "pending": "等待", "running": "进行中", "success": "全部完成", "ok": "完成",
    "completed": "已完成", "done": "已完成", "failed": "失败", "error": "失败",
    "skipped": "跳过", "stopped": "已停止", "partial": "部分完成",
    "paused": "已暂停", "cancelled": "已停止",
}

# Backend field -> page, settings section, Tk variable, control, readable name.
INPUT_FIELDS = {
    "game_path": ("settings", "game", "game_path", "game_path_entry", "游戏路径"),
    "target_name": ("tasks", None, "target_name", "dungeon_name_combo", "副本名称"),
    "target_location": ("tasks", None, "target_location", "dungeon_location_combo", "副本地点"),
    "stamina_limit": ("tasks", None, "stamina_limit", "stamina_limit_entry", "开拓力上限"),
    "challenge_count": ("tasks", None, "challenge_count", "challenge_entry", "挑战次数"),
    "action_delay": ("settings", "recognition", "action_delay", "action_delay_entry", "操作间隔"),
    "battle_timeout": ("settings", "recognition", "battle_timeout", "battle_timeout_entry", "战斗超时"),
    "ocr_confidence": ("settings", "recognition", "ocr_confidence", "ocr_confidence_entry", "OCR 阈值"),
    "differential_universe_runs": ("differential_universe", None, "differential_universe_runs", "du_runs_combo", "演算局数"),
    "differential_universe_team": ("differential_universe", None, "du_team", "du_team_entry", "预设编队"),
    "differential_universe_mode": ("differential_universe", None, "du_mode", "du_mode_combo", "演算模式"),
    "weekly_mode": ("settings", "weekly", "weekly_mode", "weekly_mode_combo", "周常玩法"),
    "weekly_day": ("settings", "weekly", "weekly_day", "weekly_day_combo", "周常星期"),
    "weekly_time": ("settings", "weekly", "weekly_time", "weekly_time_entry", "周常时间"),
    "weekly_runs": ("settings", "weekly", "weekly_runs", "weekly_runs_combo", "周常局数"),
}


def event_kind(event: dict[str, Any]) -> str:
    return str(event.get("type", event.get("event", event.get("kind", "log"))))


class AutoHSRWindow:
    BG, PANEL, INSET = theme.BG, theme.CARD, theme.CARD
    TEXT, MUTED, ACCENT = theme.TEXT, theme.MUTED, theme.GOLD

    def __init__(self, root: tk.Tk, config_path: Path = CONFIG_PATH):
        self.root, self.config_path = root, Path(config_path)
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.runner: Any = None
        self.worker: threading.Thread | None = None
        self.busy = self.running = self.paused = self.stopping = self.closing = False
        self._has_run = False
        self._daily_result_signature = None
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
        self._log("仅使用已有开拓力；首次验证建议选择“设为 1 次”，核对副本与预计消耗。")
        if not self.settings.allow_stamina_spend:
            self._log("开拓力刷本未授权，当前仅收取委托与奖励。", "warning")
        if config_error:
            root.after(200, lambda: messagebox.showwarning("配置读取失败", config_error, parent=root))

    def _variables(self) -> None:
        self.game_path = tk.StringVar(value=self.settings.game_path)
        self.target_name = tk.StringVar(value=self.settings.target_name)
        self.target_location = tk.StringVar(value=self.settings.target_location)
        self.stamina_limit = tk.StringVar(value=str(self.settings.stamina_limit))
        self.rounds = tk.StringVar(value=str(self.settings.rounds))
        from .dungeons import category_for, count_limit
        category = category_for(self.settings)
        self.dungeon_category = tk.StringVar(value=category.label)
        self.dungeon_browse_category = tk.StringVar(value=category.label)
        self.challenge_count = tk.StringVar(value=str(self.settings.challenge_count or count_limit(category, self.settings.stamina_limit)))
        self.battle_cost = tk.StringVar()
        self.use_support = tk.BooleanVar(value=self.settings.use_support)
        self.auto_launch = tk.BooleanVar(value=self.settings.auto_launch)
        self.overlay_logs = tk.BooleanVar(value=self.settings.overlay_logs)
        self.daily_synthesis = tk.BooleanVar(value=self.settings.daily_synthesis)
        self.tasks = {name: tk.BooleanVar(value=getattr(self.settings, name)) for name in TASK_NAMES}
        if not self.settings.allow_stamina_spend:
            self.tasks["battle"].set(False)
        self.form_variables = [self.game_path, self.target_name, self.target_location, self.stamina_limit,
                               self.rounds, self.dungeon_category, self.challenge_count, self.use_support, self.auto_launch, self.overlay_logs, self.daily_synthesis, *self.tasks.values()]
        self.status = tk.StringVar(value="● 准备就绪")
        self.save_status = tk.StringVar()
        self.summary = tk.StringVar()
        self.input_error = tk.StringVar()
        self.input_error_field = None
        self._input_error_status = None
        self.result_alert = tk.StringVar()
        self.page_title = tk.StringVar(value="每日实训")
        self.current_task = tk.StringVar(value="等待开始")
        self.activity = tk.StringVar(value=self.status.get())
        self.status.trace_add("write", self._refresh_activity)
        self.current_task.trace_add("write", self._refresh_activity)
        self.elapsed = tk.StringVar(value="00:00")
        self.stamina = tk.StringVar(value="0")
        self.battle_hint = tk.StringVar()
        self.plan = tk.StringVar()
        self.readiness = tk.StringVar(value="窗口：未检测")
        self.history_context = tk.StringVar(value="暂无历史运行记录")
        self.recovery_hint = tk.StringVar()
        self.action_delay = tk.StringVar(value=str(self.settings.action_delay))
        self.battle_timeout = tk.StringVar(value=str(self.settings.battle_timeout))
        self.ocr_confidence = tk.StringVar(value=str(self.settings.ocr_confidence))
        self.form_variables.extend((self.action_delay, self.battle_timeout, self.ocr_confidence))
        self.differential_universe_runs = tk.StringVar(value=str(self.settings.differential_universe_runs))
        self.form_variables.append(self.differential_universe_runs)
        self.du_team = tk.StringVar(value=self.settings.differential_universe_team)
        self.du_mode = tk.StringVar(value='周期演算' if self.settings.differential_universe_mode=='periodic' else '常规演算')
        self.form_variables.extend((self.du_team,self.du_mode))
        self.du_resume_active = tk.BooleanVar(value=False)
        self.du_save = tk.BooleanVar(value=self.settings.differential_universe_save)
        self.form_variables.append(self.du_save)
        self.du_rewards = tk.BooleanVar(value=self.settings.differential_universe_rewards)
        self.form_variables.append(self.du_rewards)
        self.du_daily = tk.BooleanVar(value=self.settings.differential_universe_daily)
        self.form_variables.append(self.du_daily)
        self.du_resume_mode = tk.StringVar(value="常规演算")
        self.detect_title = tk.StringVar(value="尚未检测游戏窗口")
        self.detect_size = tk.StringVar(value="客户区尺寸：—")
        self.detect_permission = tk.StringVar(value="助手管理员权限：—")
        self.admin_launch_status = tk.StringVar(value="授权状态：未查询")
        self.currency_status = tk.StringVar(value="开发中 · 整局未验收")
        self.currency_observation = tk.StringVar(value="暂无识别记录")
        self.currency_source_slot = tk.StringVar(value='3')
        self.currency_zone = tk.StringVar(value='后台')
        self.currency_target_level = tk.StringVar(value='保持')
        self.currency_strategy = tk.StringVar(value='默认')
        self.du_status = tk.StringVar(value="尚未运行")
        self.du_observation = tk.StringVar()
        self.du_result_report = None
        self.training_result = tk.StringVar(value="unknown")
        from .weekly_plan import DAYS, MODES
        self.weekly_enabled = tk.BooleanVar(value=self.settings.weekly_enabled)
        self.weekly_mode = tk.StringVar(value=MODES[self.settings.weekly_mode])
        self.weekly_day = tk.StringVar(value=DAYS[self.settings.weekly_day-1])
        self.weekly_time = tk.StringVar(value=self.settings.weekly_time)
        self.weekly_runs = tk.StringVar(value=str(self.settings.weekly_runs))
        self.weekly_status = tk.StringVar()
        self.weekly_boundary = tk.StringVar()
        self.daily_caption = tk.StringVar()
        self.form_variables.extend((self.weekly_enabled, self.weekly_mode, self.weekly_day,
                                    self.weekly_time, self.weekly_runs))

    def _build(self):
        from .desktop import build_window
        build_window(self, TASK_NAMES, {})

    def _show_page(self, name):
        from .desktop import PAGE_TITLES
        self.active_page = name
        self.page_title.set(PAGE_TITLES[name])
        for key, page in self.pages.items():
            page.grid() if key == name else page.grid_remove()
        self.guide.select(name)
        if name in ("differential_universe", "currency_wars"):
            self.last_universe_page = name
        if name not in ("logs", "settings"):
            self.action_page = name
        self._configure_primary_action()
        self._refresh_controls()

    def _configure_primary_action(self):
        currency = getattr(self, "action_page", "home") == "currency_wars"
        differential_universe = getattr(self, "action_page", "home") == "differential_universe"
        self.start_button.configure(
            text="只读识别当前画面" if currency else
                 f"开始 {self.differential_universe_runs.get()} 局自动演算" if differential_universe else "开始计划",
            command=self._currency_wars if currency else
                    (lambda: self._start(differential_universe=True)) if differential_universe else (lambda: self._start(run_plan=True)))
        self.header.position_plan()

    def _show_weekly_plan(self):
        self.action_page = "home"
        self._show_page("settings")
        self.settings_tabs.select(self.settings_sections["weekly"])

    def _weekly_values(self):
        from .weekly_plan import DAYS, MODES
        return dict(weekly_enabled=self.weekly_enabled.get(),
                    weekly_mode=next(key for key, label in MODES.items() if label == self.weekly_mode.get()),
                    weekly_day=DAYS.index(self.weekly_day.get())+1,
                    weekly_time=self.weekly_time.get().strip(), weekly_runs=self._number("weekly_runs", int))

    def _refresh_plan_caption(self):
        from .weekly_plan import plan_caption
        count = sum(variable.get() for variable in self.tasks.values())
        from .dungeon_ui import selected_category
        try:
            cost = f"{int(self.challenge_count.get())*selected_category(self).cost} 开拓力 · {self.target_name.get()}" if self.tasks["battle"].get() else "不刷本"
        except ValueError:
            cost = "次数待填写"
        self.daily_caption.set(f"日常 · {count} 项" + (f" · {cost}" if cost else ""))
        try:
            weekly = self._weekly_values() if self.weekly_enabled.get() else dict(weekly_enabled=False)
            self.weekly_status.set(plan_caption(replace(self.settings, **weekly)))
        except (ValueError, StopIteration):
            self.weekly_status.set("周常时间或局数待填写")
        self.weekly_boundary.set("周期演算按局数完成；周积分奖励尚未接入。" if self.weekly_mode.get() == "差分宇宙" else
                                 "周积分奖励尚未接入；到期时仅执行日常并保留未完成状态。")

    def _text_tab(self, title):
        frame = ttk.Frame(self.output_tabs)
        self.output_tabs.add(frame, text=title)
        text = self._text(frame)
        text.pack(fill="both", expand=True)
        return text

    def _text(self, parent: tk.Widget) -> ScrolledText:
        return ScrolledText(parent, wrap="char", font=(theme.FONT, 10), background=self.INSET,
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
        from .dungeon_ui import build_fields
        build_fields(self, parent)

    def _form_signature(self) -> tuple[Any, ...]:
        return tuple(variable.get() for variable in self.form_variables)

    def _daily_form_signature(self):
        return tuple(variable.get() for variable in (self.game_path, self.target_name, self.target_location,
            self.dungeon_category, self.challenge_count, self.stamina_limit, self.use_support,
            self.daily_synthesis, *self.tasks.values()))

    def _refresh_activity(self, *_):
        task = self.current_task.get() if self.running else ""
        self.activity.set(self.status.get()+(" · "+task if task else ""))

    @property
    def dirty(self) -> bool:
        return self._form_signature() != self._saved_signature

    def _form_changed(self, *_: Any) -> None:
        if self._loading:
            return
        if self.input_error_field in INPUT_FIELDS and _ and str(getattr(self, INPUT_FIELDS[self.input_error_field][2])) == str(_[0]):
            self._clear_input_error()
        if not self.settings.allow_stamina_spend and self.tasks["battle"].get():
            self.tasks["battle"].set(False)
        if not self.busy and self._has_run and self._daily_result_signature is not None and self._daily_form_signature() != self._daily_result_signature:
            self._has_run = False
            self._daily_result_signature = None
        self.save_status.set("未保存" if self.dirty else ("已保存" if self.config_path.exists() else "默认设置"))
        self.save_label.configure(foreground="#dcc391" if self.dirty else "#aeb8c7")
        selected = [label for key, label in TASK_NAMES.items() if self.tasks[key].get()]
        from .dungeon_ui import refresh_count
        refresh_count(self)
        battle = f" · {self.target_name.get()} / {self.target_location.get() or '地点待填写'} · {self.challenge_count.get()} 次 · 开拓力上限 {self.stamina_limit.get()}" if self.tasks["battle"].get() else " · 不刷本"
        self.plan.set("自动检查游戏并返回主界面" + battle + "\n" + "、".join(selected))
        if not self.busy:
            self._refresh_plan_caption()
        self._refresh_controls()

    def _refresh_recovery(self):
        from .recovery import recovery_state
        state = recovery_state(ROOT / "runs")
        pending = state['pending'] if state['pending'] is not None else '未记录'
        self.recovery_hint.set((state.get("reason") if state["corrupt"] else
            f"上次刷本未完整结束：已确认 {state['spent']}，待核对 {pending} 开拓力{immersifier_text(state)}。可先仅补领奖；新刷本需确认新增预算。")
            if state["blocked"] else "")

    def _refresh_controls(self) -> None:
        state = "disabled" if self.busy else "normal"
        for control in self.setting_controls:
            control.configure(state=state)
        for name in ('currency_source_combo','currency_zone_combo','currency_level_combo','du_runs_combo','du_resume_combo','du_mode_combo',
                     'weekly_mode_combo', 'weekly_day_combo', 'weekly_runs_combo', 'currency_strategy_combo'):
            if hasattr(self,name):
                getattr(self,name).configure(state='disabled' if self.busy else 'readonly')
        for control in self.weekly_run_controls:
            control.grid() if self.weekly_mode.get() == "差分宇宙" else control.grid_remove()
        allowed = self.settings.allow_stamina_spend
        self.battle_checkbox.configure(state="normal" if allowed and not self.busy else "disabled")
        battle_enabled = allowed and self.tasks["battle"].get()
        for control in self.stamina_controls:
            control.configure(state="normal" if battle_enabled and not self.busy else "disabled")
        self.dungeon_list.redraw()
        self.dungeon_category_combo.configure(state="readonly" if battle_enabled and not self.busy else "disabled")
        if not allowed:
            hint = "开拓力刷本未授权，当前仅收取委托与奖励"
        elif not battle_enabled:
            hint = "副本挑战未启用"
        elif not self.use_support.get():
            hint = "好友支援已关闭；标准每日流程需勾选支援。"
        elif self.dungeon_category.get() == "饰品提取":
            hint = "使用已有差分存档；已有沉浸器优先，余量使用开拓力。"
        else:
            hint = "仅用已有开拓力，不补充燃料或星琼。"
        self.battle_hint.set(hint)
        if not self._has_run:
            for name, label in TASK_NAMES.items():
                selected = self.tasks[name].get()
                detail = "开拓力刷本未授权" if name == "battle" and not allowed else ("" if selected else "未勾选")
                self.table.item(name, values=(label, "等待" if selected else "跳过", detail), tags=() if selected else ("skipped",), has_result=False, metrics=None)
        for button in (self.save_button, self.check_button, self.launch_button):
            button.configure(state=state)
        currency_page = getattr(self, "action_page", "") == "currency_wars"
        self.pause_button.configure(state="normal" if self.running and self.runner is not None and not self.stopping else "disabled", text="继续 F9" if self.paused else "暂停 F9")
        self.stop_button.configure(state="normal" if self.busy and not self.stopping else "disabled")
        for button in (self.pause_button, self.stop_button):
            if self.busy:
                button.pack(side="left", before=self.start_button, padx=(round(8*self.ui_scale), 0))
            else:
                button.pack_forget()
        independent_page = currency_page or getattr(self, "action_page", "") == "differential_universe"
        if getattr(self, "action_page", "") == "differential_universe":
            self.start_button.configure(text=f"开始演算 · {self.differential_universe_runs.get()} 局")
        self.start_button.configure(state="normal" if not self.busy and (independent_page or self.weekly_enabled.get() or any(v.get() for v in self.tasks.values())) else "disabled")
        self.reward_button.configure(state="normal" if not self.busy and not independent_page else "disabled")
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
        from .dungeon_ui import selected_category
        from .dungeons import count_limit
        self.challenge_count.set(str(count_limit(selected_category(self), stamina)))
        self._log(f"已填写：上限 {stamina} 开拓力、本次 {self.challenge_count.get()} 次。尚未开始执行。")

    def _choose_game(self) -> None:
        path = filedialog.askopenfilename(title="选择 StarRail.exe", filetypes=[("星穹铁道程序", "StarRail.exe"), ("应用程序", "*.exe")], initialdir=str(Path(self.game_path.get()).parent), parent=self.root)
        if path:
            self.game_path.set(path)

    def _number(self, field, convert):
        _, _, variable, _, title = INPUT_FIELDS[field]
        try:
            return convert(getattr(self, variable).get())
        except (ValueError, TypeError, OverflowError) as exc:
            raise SettingsError(field, title+("请填写整数。" if convert is int else "请填写有效数字。")) from exc

    def _clear_input_error(self):
        self.input_error.set("")
        self.input_error_field = None
        if self._input_error_status is not None and self.status.get() == "● 请检查输入":
            self.status.set(self._input_error_status)
        self._input_error_status = None

    def _focus_input_error(self):
        if self.input_error_field not in INPUT_FIELDS or self.busy:
            return
        page, section, _, control, _ = INPUT_FIELDS[self.input_error_field]
        operation_page = self.action_page
        if (self.input_error_field == "differential_universe_team" and self.weekly_enabled.get()
                and self.weekly_mode.get() == "差分宇宙" and operation_page in ("home", "tasks")):
            page, section, control = "settings", "weekly", "weekly_team_entry"
        self._show_page(page)
        if section:
            self.settings_tabs.select(self.settings_sections[section])
        self.action_page = operation_page
        self._configure_primary_action()
        self._refresh_controls()
        self._restore()
        widget = getattr(self, control)
        if self.input_error_field in ("target_name", "target_location"):
            from .dungeon_ui import show_manual
            show_manual(self)
        if self.input_error_field == "stamina_limit":
            from .dungeon_ui import show_advanced
            show_advanced(self)
        def focus():
            if widget.winfo_exists():
                widget.focus_set()
                if hasattr(widget, "selection_range"):
                    widget.selection_range(0, "end")
        self.root.after_idle(focus)

    def _input_failed(self, error):
        self.input_error_field = error.field
        self.input_error.set(str(error))
        if self._input_error_status is None:
            self._input_error_status = self.status.get()
        self.status.set("● 请检查输入")
        self._log(str(error), "error")
        self._focus_input_error()

    def _read_settings(self, save=False, operation="daily") -> Settings | None:
        try:
            values = dict(game_path=self.game_path.get().strip(), overlay_logs=self.overlay_logs.get(),
                          daily_synthesis=self.daily_synthesis.get())
            if not save and operation == "dungeon_catalogue":
                values.update(auto_launch=False, assignments=False, battle=False, daily=False, mail=False, battlepass=False,
                              dungeon_category="auto", ocr_confidence=self._number("ocr_confidence", float))
            elif not save and operation.startswith("currency_wars"):
                values.update(auto_launch=False, assignments=False, battle=False, daily=False, mail=False, battlepass=False,
                              ocr_confidence=self._number("ocr_confidence", float))
            elif not save and operation == "differential_universe":
                values.update(auto_launch=False, assignments=False, battle=False, daily=False, mail=False, battlepass=False,
                              differential_universe_runs=self._number("differential_universe_runs", int),
                              differential_universe_team=self.du_team.get().strip(),
                              differential_universe_mode='periodic' if self.du_mode.get()=='周期演算' else 'normal',
                              differential_universe_save=self.du_save.get(),
                              differential_universe_rewards=self.du_rewards.get(),
                              differential_universe_daily=self.du_daily.get(),
                              action_delay=self._number("action_delay", float), battle_timeout=self._number("battle_timeout", int),
                              ocr_confidence=self._number("ocr_confidence", float))
            elif save or operation not in ("check", "launch"):
                values.update(auto_launch=self.auto_launch.get(),
                              **{name: variable.get() if name != "battle" or self.settings.allow_stamina_spend else False for name, variable in self.tasks.items()})
                if save:
                    values.update(differential_universe_runs=self._number("differential_universe_runs", int),
                                  differential_universe_team=self.du_team.get().strip(),
                                  differential_universe_mode='periodic' if self.du_mode.get()=='周期演算' else 'normal',
                                  differential_universe_save=self.du_save.get(),
                                  differential_universe_rewards=self.du_rewards.get(),
                                  differential_universe_daily=self.du_daily.get())
                elif operation == "plan" and self.weekly_enabled.get() and self.weekly_mode.get() == "差分宇宙":
                    values["differential_universe_team"] = self.du_team.get().strip()
                if operation == "reward_only":
                    values.update(assignments=False, battle=False, daily=True, mail=False, battlepass=False)
                if values["battle"] and self.settings.allow_stamina_spend:
                    values.update(target_name=self.target_name.get().strip(), target_location=self.target_location.get().strip(),
                                  stamina_limit=self._number("stamina_limit", int), use_support=self.use_support.get())
                    from .dungeon_ui import selected_category
                    count = self._number("challenge_count", int)
                    values.update(dungeon_category=selected_category(self).key, challenge_count=count,
                                  rounds=max(1, min(count, selected_category(self).batch)))
                values.update(action_delay=self._number("action_delay", float), battle_timeout=self._number("battle_timeout", int),
                              ocr_confidence=self._number("ocr_confidence", float))
            elif operation == "check":
                values["ocr_confidence"] = self._number("ocr_confidence", float)
            settings = replace(self.settings, **values)
            if save:
                settings = replace(settings, **self._weekly_values())
            elif operation == "plan":
                weekly = self._weekly_values() if self.weekly_enabled.get() else dict(weekly_enabled=False)
                settings = replace(settings, **weekly)
            settings.validate("save" if save else operation)
            if save:
                settings.save(self.config_path)
                self.settings = settings
                self._loading = True
                self.target_name.set(settings.target_name)
                self.target_location.set(settings.target_location)
                self.stamina_limit.set(str(settings.stamina_limit))
                self.rounds.set(str(settings.rounds))
                self.differential_universe_runs.set(str(settings.differential_universe_runs))
                self._saved_signature = self._form_signature()
                self._loading = False
                self._form_changed()
            else:
                self.save_status.set("未保存" if self.dirty else ("已保存" if self.config_path.exists() else "默认设置"))
            self._clear_input_error()
            return settings
        except (ValueError, TypeError, OSError, StopIteration) as exc:
            if isinstance(exc, SettingsError) and exc.field in INPUT_FIELDS:
                self._input_failed(exc)
            else:
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
        self._refresh_activity()

    def _check(self) -> None:
        self._operation("check")

    def _launch(self) -> None:
        self._operation("launch")

    def _admin_operation(self, action: str) -> None:
        if self.busy or self.closing or (self.worker is not None and self.worker.is_alive()):
            return
        self._set_busy(True)
        self.admin_launch_status.set("正在查询……" if action == "status" else "等待 Windows 授权及结果核实……")

        def work() -> None:
            try:
                from .admin_launch import configure, status, status_text
                data = status() if action == "status" else configure(action)
                self.emit(dict(type="admin_launch_result", message=status_text(data), action=action))
            except Exception as error:
                self.emit(dict(type="admin_launch_result", message=str(error), error=True, action=action))
        self.worker = threading.Thread(target=work, name="autohsr-admin-launch", daemon=True)
        self.worker.start()

    def _operation(self, action: str) -> None:
        if self.busy or self.closing or (self.worker is not None and self.worker.is_alive()):
            return
        settings = self._read_settings(operation=action)
        if settings is None:
            return
        self.summary.set("")
        self.result_alert.set("")
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

    def _currency_prepare(self):
        self._start(currency_wars=True, currency_prepare=True)

    def _currency_locate(self):
        self._start(currency_wars=True, currency_prepare=True, currency_locate=True)

    def _currency_configure(self):
        self._start(currency_wars=True, currency_prepare=True, currency_locate=True, currency_configure=True)

    def _currency_standard(self):
        self._start(currency_wars=True, currency_standard=True)

    def _currency_resume(self):
        self._start(currency_wars=True, currency_standard=True, currency_resume=True)

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

    def _start(self, reward_only=False, *, run_plan=False, catalogue=False, currency_wars=False, differential_universe=False, drag_test=False, deploy_test=False, node_test=False, flow_test=False,
               currency_source_slot=3,currency_zone='back',currency_target_level=0,currency_start_from_lobby=False,
               currency_control_probe=False,currency_timeout_probe=False,currency_prepare=False,currency_locate=False,
               currency_configure=False,currency_standard=False,currency_resume=False) -> None:
        if self.busy or self.closing or (self.worker is not None and self.worker.is_alive()):
            return
        currency_locate = currency_locate or currency_configure
        currency_prepare = currency_prepare or currency_locate
        currency_wars = currency_wars or currency_standard or currency_prepare or drag_test or deploy_test or node_test or flow_test
        operation = "dungeon_catalogue" if catalogue else "currency_wars_standard" if currency_standard else "currency_wars_prepare" if currency_prepare else "currency_wars_flow_test" if flow_test else "currency_wars_node_test" if node_test else "currency_wars_deploy_test" if deploy_test else "currency_wars_drag_test" if drag_test else "currency_wars" if currency_wars else "differential_universe" if differential_universe else "reward_only" if reward_only else "daily"
        if run_plan and operation == "daily":
            operation = "plan"
        settings = self._read_settings(operation=operation)
        if settings is None:
            return
        du_options={}
        if differential_universe:
            resume=self.du_resume_active.get()
            mode=self.du_resume_mode.get()
            rank=int(mode.split()[-1]) if resume and mode.startswith("周期难度 ") else None
            if rank is not None and settings.differential_universe_runs != 1:
                messagebox.showerror("接续局数", "周期演算接续仅完成当前 1 局，请将局数设为 1。", parent=self.root)
                return
            du_options=dict(du_runs=settings.differential_universe_runs,
                            du_resume_active=resume,du_periodic_rank=rank)
        currency_options = {}
        if currency_standard:
            strategies = {'默认': 'default', '阿格莱雅': 'aglaea', '希儿': 'seele'}
            currency_options = dict(currency_resume=currency_resume,
                                    currency_strategy=None if currency_resume else strategies[self.currency_strategy.get()])
        from .recovery import recovery_state, reward_only_settings
        new_battle_run = False
        if reward_only:
            settings = reward_only_settings(settings)
        elif not currency_wars and not differential_universe and settings.battle and settings.allow_stamina_spend:
            state = recovery_state(ROOT / "runs")
            if state["blocked"]:
                if state["corrupt"]:
                    messagebox.showerror("刷本记录待核对", state["reason"], parent=self.root)
                    return
                pending = state['pending'] if state['pending'] is not None else '未记录'
                new_battle_run = messagebox.askyesno("确认新一轮刷本预算",
                    f"上次已确认 {state['spent']}，待核对 {pending} 开拓力{immersifier_text(state)}。\n"
                    f"这不是续跑：本次会新增最多 {settings.stamina_limit} 开拓力预算。\n"
                    "如只需领取每日奖励，请选否，再点“仅补领奖”。\n确定已人工核对，仍要开始新一轮？", default="no", parent=self.root)
                if not new_battle_run:
                    return
        if not catalogue and not currency_wars and not differential_universe and not any(getattr(settings, key) for key in TASK_NAMES) and not (operation == "plan" and settings.weekly_enabled):
            messagebox.showinfo("未选择任务", "请至少勾选一项每日任务。", parent=self.root)
            return
        self.runner = None
        self.active_operation = operation
        self.plan_phase = "daily" if operation == "plan" else ""
        deployment_label=f"备战{currency_source_slot}→空"+('前台' if currency_zone=='front' else '后台')
        self.plan.set("货币战争 · 整局验证 · 超频A0" if flow_test and currency_start_from_lobby else ("货币战争 · 连续流程验证"+(f" · 升级至Lv{currency_target_level}" if currency_target_level else " · 不购买经验")) if flow_test else "货币战争 · 当前节点战斗验证" if node_test else f"货币战争 · 单次{deployment_label}部署" if deploy_test else "货币战争 · 单次前台3→1拖动验证" if drag_test else "货币战争 · 只读识别 · 自动玩法未开放" if currency_wars else
                      f"差分宇宙 · {self.du_mode.get()} · {settings.differential_universe_runs} 局 · 预设编队 {settings.differential_universe_team} · 不消耗每日刷本预算" if differential_universe else
                      "仅补领奖 · 不刷本 · 不执行附加任务 · 本次不保存" if reward_only else
                      "自动检查游戏并返回主界面" +
                      (f" · {settings.target_name} / {settings.target_location} · {settings.challenge_count} 次 · 开拓力上限 {settings.stamina_limit}" if settings.battle else " · 不刷本"))
        if catalogue:
            self.plan.set("采集生存索引副本目录 · 不开始挑战 · 不消耗资源")
        if currency_prepare:
            self.plan.set('货币战争 · 配置标准A8-40 · 不开始对局' if currency_configure else
                          '货币战争 · 指南定位标准模式 · 不开始对局' if currency_locate else '货币战争 · 启动准备 · 不开始对局')
        if currency_standard:
            self.plan.set('货币战争 · 标准A8-40开发 · ' + ('接续已记录对局 · 沿用本局策略' if currency_resume else '新局策略：'+self.currency_strategy.get()))
        daily_operation = operation in ("daily", "plan", "reward_only")
        if daily_operation:
            self._has_run = True
            self._daily_result_signature = self._daily_form_signature()
        if operation == "plan":
            from .weekly_plan import plan_caption
            self.plan.set(self.plan.get()+"\n"+plan_caption(settings))
            self.weekly_status.set("等待日常结束" if settings.weekly_enabled else "周常未加入")
        if operation in ("daily", "plan", "reward_only"):
            self.training_result.set("unknown")
        self.paused = self.stopping = False
        self.focus_waiting = False
        self.stop_requested.clear()
        self.confirmed_stamina = self.elapsed_seconds = 0
        self.stamina.set("0")
        self.elapsed.set("00:00")
        self.current_task.set("差分宇宙自动演算" if differential_universe else "货币战争连续流程验证" if flow_test else "货币战争节点战斗验证" if node_test else
                              "货币战争部署验证" if deploy_test else "货币战争拖动验证" if drag_test else
                              "货币战争只读识别" if currency_wars else "准备进入游戏")
        if differential_universe:
            self.du_status.set(f"正在演算 · 共 {settings.differential_universe_runs} 局")
            self.du_observation.set("等待页面识别")
            self.du_result_report = None
            self.du_record_button.configure(state="disabled")
            self.last_screenshot = None
        if currency_wars:
            self.currency_status.set("正在推进对局" if flow_test else "正在验证当前节点" if node_test else f"正在部署：{deployment_label}" if deploy_test else "正在验证前台 3→1 拖动" if drag_test else "正在只读识别")
            self.currency_observation.set("正在生成本次证据；上次截图与报告保留在运行日志中。")
            self.last_screenshot = None
            if currency_standard:
                self.current_task.set('标准A8-40开发')
                self.currency_status.set('正在接续已记录标准对局，未知反馈停下留证。' if currency_resume else
                                         '正在核实标准A8-40并新开开发对局；尚未完成整局验收。')
            if currency_prepare:
                self.current_task.set('货币战争启动准备')
                self.currency_status.set('正在定位并配置标准A8财富造物主40；不开始对局。' if currency_configure else
                                         '正在启动准备并通过指南定位标准博弈；不开始对局。' if currency_locate else
                                         '正在启动或复用游戏，处理已有登录及免费登录奖励；不开始对局。')
        self.started_at = time.monotonic()
        self._set_busy(True, True)
        self.status.set("● 正在运行")
        self.summary.set("")
        self.result_alert.set("")
        self.output_tabs.select(0)
        self.table.selection_remove(*self.table.selection())
        if daily_operation:
            for name, label in TASK_NAMES.items():
                enabled = getattr(settings, name)
                detail = "开拓力刷本未授权" if name == "battle" and not settings.allow_stamina_spend else ("" if enabled else "未勾选")
                self.table.item(name, values=(label, "等待" if enabled else "跳过", detail), tags=() if enabled else ("skipped",), has_result=False, metrics=None)
        self._log("开始标准A8-40开发；未知页面和反馈停下留证。" if currency_standard else "开始货币战争启动准备，不开始对局。" if currency_prepare else "开始差分宇宙自动演算。助手将最小化，让游戏保持前台。" if differential_universe else "开始货币战争流程推进验证。" if flow_test else "开始货币战争当前节点战斗验证。" if node_test else "开始货币战争单次部署验证。" if deploy_test else "开始货币战争单次拖动验证。" if drag_test else "开始货币战争只读识别。" if currency_wars else "开始执行每日任务。助手将最小化，让游戏保持前台。")
        self.root.iconify()

        def work() -> None:
            def send(event: dict[str, Any]) -> None:
                # Publish the terminal result only after run() returns. A backend
                # exception after its own finished event must remain a failure.
                if event_kind(event) != "finished":
                    self.emit(event)
            try:
                from .app import Runner
                if operation == "plan":
                    from .plan_runner import PlanRunner
                    runner = PlanRunner(settings, send, new_battle_run=new_battle_run, root=ROOT/"runs")
                else:
                    runner = Runner(settings, send, new_battle_run=new_battle_run, operation=operation,
                        **du_options,
                        **(dict(currency_locate=True) if currency_locate else {}),
                        **(dict(currency_configure=True) if currency_configure else {}),
                        **currency_options,
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
        self.summary.set("")
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
        if self.running and match and not (self.active_operation == "plan" and getattr(self, "plan_phase", "") == "weekly"):
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
        if task == "weekly":
            self.weekly_status.set(detail)
            if status == "running":
                self.current_task.set("周常演算")
        if task == "currency_wars":
            self.currency_status.set(detail)
            self.current_task.set("标准A8-40开发" if self.active_operation == 'currency_wars_standard' else "货币战争启动准备" if self.active_operation == 'currency_wars_prepare' else "货币战争连续流程验证" if self.active_operation == "currency_wars_flow_test" else "货币战争节点战斗验证" if self.active_operation == "currency_wars_node_test" else "货币战争部署验证" if self.active_operation == "currency_wars_deploy_test" else "货币战争拖动验证" if self.active_operation == "currency_wars_drag_test" else "货币战争只读识别")
        if task in TASK_NAMES and not (self.active_operation == "plan" and event.get("phase") == "weekly"):
            self._has_run = True
            if self._daily_result_signature is None:
                self._daily_result_signature = self._daily_form_signature()
            tag = "success" if status in ("success", "ok", "completed", "done") else status
            self.table.item(task, values=(TASK_NAMES[task], STATUS_NAMES.get(status, status), detail), tags=(tag,), has_result=True)
            if status == "running":
                self.current_task.set(TASK_NAMES[task])
        if log:
            label = "周常" if task == "weekly" else "货币战争" if task == "currency_wars" else TASK_NAMES.get(task, task)
            self._log(f"{label}：{STATUS_NAMES.get(status, status)} {detail}".strip(), "error" if status in ("failed", "error") else "info")

    def _plan_daily_result(self, report):
        for result in report.get("results", []):
            if isinstance(result, dict):
                self._task(result, log=False)
        if report.get("daily_verified") is True:
            self._task(dict(task="daily", status="ok", detail="每日实训奖励已核实领取。"), log=False)
            self.training_result.set("verified")
        self._progress(report.get("stamina_spent"))
        self._battle_result(report)
        self._finalize_task_rows(str(report.get("status", "partial")))

    def _battle_result(self, report):
        completed, requested, spent = (report.get(name) for name in ("battle_completed", "battle_requested", "stamina_spent"))
        if (all(type(value) is int for value in (completed, requested, spent))
                and 0 <= completed <= requested and requested > 0 and spent >= 0):
            self.table.item("battle", metrics=(f"{completed}/{requested} 次", f"已确认 {spent} 开拓力"))

    def _universe_progress(self, event):
        requested, completed = event.get("requested_runs"), event.get("completed_runs")
        if type(requested) is not int or type(completed) is not int or not 1 <= requested <= 10 or not 0 <= completed <= requested:
            return
        progress = f"差分宇宙 · 已完成 {completed}/{requested} 局"
        self.du_status.set(progress)
        self.du_observation.set("")
        self.du_result_report = None
        self.du_record_button.configure(state="disabled")
        self.current_task.set(("周常 · " if self.active_operation == "plan" else "")+progress)
        if self.active_operation == "plan":
            self.weekly_status.set(progress)

    def _show_universe_record(self):
        if self.du_result_report is not None:
            self._show_summary(json.dumps(self.du_result_report, ensure_ascii=False, indent=2), title="差分宇宙 · 详细记录")

    def _currency_observed(self, data: dict) -> None:
        from .currency_wars_pages import PAGE_LABELS
        if data.get('mode') == 'standard_development':
            activity = standard_activity(data)
            completion = "开发局胜利及结算已核实，未计独立验收" if standard_run_verified(data) else "整局未完成"
            self.currency_observation.set(
                f"标准A8-40开发：{'已核实开局' if data.get('start_verified') else '开局待核实'} · {activity}；{completion}。"
                + (f"\n{data['reason']}" if data.get('reason') else '')
                + f"\n截图：{data.get('screenshot') or '未保存'}")
            if self.running and self.active_operation == "currency_wars_standard":
                self.current_task.set(activity)
            if data.get('screenshot'):
                self.last_screenshot = Path(data['screenshot'])
            return
        if data.get('mode') == 'entry_navigation':
            ready = ('标准A8财富造物主40已核实' if data.get('rank_verified') else
                     '标准模式已定位' if data.get('entry_ready') else data.get('action_status', '待处理'))
            self.currency_observation.set(
                f"入口导航：{ready}；未开始新对局。"
                + (f"\n{data['reason']}" if data.get('reason') else '')
                + f"\n截图：{data.get('screenshot') or '未保存'}")
            if data.get('screenshot'):
                self.last_screenshot = Path(data['screenshot'])
            return
        if data.get('mode') == 'startup_prepare':
            kind = data.get('page_kind', '未核实')
            label = {'phone': '手机菜单', 'world': '大世界'}.get(kind, PAGE_LABELS.get(kind, kind))
            self.currency_observation.set(
                f"启动准备：{'已核实' if data.get('game_ready') else '待处理'} · {label}；未开始新对局。"
                + (f"\n{data['reason']}" if data.get('reason') else '')
                + f"\n截图：{data.get('screenshot') or '未保存'}")
            if data.get('screenshot'):
                self.last_screenshot = Path(data['screenshot'])
            return
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

    def _show_task_setup(self, task):
        self._show_page("tasks")
        if task == "battle" and self.tasks[task].get():
            from .dungeon_ui import show_browser
            show_browser(self)
            self.dungeon_list.reveal_selection()
            control = self.dungeon_list
        else:
            control = self.task_controls[task]
        self.root.after_idle(control.focus_set)

    def _show_task_detail(self, _: tk.Event | None = None) -> None:
        selected = self.table.selection()
        if selected:
            label, status, detail = self.table.item(selected[0], "values")
            self._show_summary(f"{label} · {status}\n{detail or '暂无详细说明'}", title=label)

    def _show_summary(self, content=None, *, title="运行详情") -> None:
        content = self.summary.get() if content is None else content
        if not content:
            return
        previous = getattr(self, "summary_dialog", None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        dialog = self.summary_dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        d = lambda value: round(value*self.ui_scale)
        dialog.geometry(f"{d(680)}x{d(340)}")
        dialog.minsize(d(400), d(200))
        dialog.configure(background=theme.CARD)
        text = self._text(dialog)
        text.pack(fill="both", expand=True, padx=d(12), pady=d(12))
        self._replace_text(text, content)
        ttk.Button(dialog, text="关闭", command=dialog.destroy).pack(pady=(0, d(12)))
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        text.focus_set()

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
        standard_completed = (report.get("operation", self.active_operation) == "currency_wars_standard"
                              and standard_run_verified(report.get("currency_wars") or {}))
        differential_universe = report.get("operation", self.active_operation) == "differential_universe"
        if not currency and report.get("daily_verified") is True:
            self._task(dict(task="daily", status="ok", detail="每日实训奖励已核实领取。"), log=False)
            self.training_result.set("verified")
        if report.get("operation", self.active_operation) in ("daily", "plan", "reward_only"):
            self._finalize_task_rows(status)
            self._battle_result(report)
        self._progress(report.get("stamina_spent", 0))
        self._freeze_clock()
        daily = "已验证" if report.get("daily_verified", False) else "未验证"
        pending = report.get("stamina_pending", 0)
        self.summary.set(f"{STATUS_NAMES.get(status, status)} · 本轮已确认 {self.confirmed_stamina} / 上限 {report.get('stamina_limit', '未记录')} · 待核对 {pending}{immersifier_text(report)} · 每日奖励 {daily} · {exit_text(report)}" + ("\n" + recovery_text(report) if recovery_text(report) else ""))
        if report.get("operation", self.active_operation) == "dungeon_catalogue":
            data = report.get("dungeon_catalogue") or {}
            self.summary.set(f"副本采集 · {STATUS_NAMES.get(status, status)} · {data.get('count', 0)} 个入口 · 消耗 0 开拓力" + ("\n" + str(report.get("error")) if report.get("error") else ""))
            if status == "success":
                from .dungeon_ui import reload_catalogue, update_options
                reload_catalogue(self)
                update_options(self)
        elif report.get("battle_requested") is not None:
            self.summary.set(f"副本完成 {report.get('battle_completed', 0)} / {report['battle_requested']} 次 · " + self.summary.get())
        if currency:
            outcome = ("已停止" if status == "stopped" else "运行失败" if status == "failed" else
                       "标准开发结束" if report.get('operation', self.active_operation) == 'currency_wars_standard' else
                       "启动准备结束" if report.get('operation', self.active_operation) == 'currency_wars_prepare' else
                       "只读识别结束" if report.get('operation', self.active_operation) == 'currency_wars' else
                       "连续流程验证结束" if report.get('operation', self.active_operation) == 'currency_wars_flow_test' else "单步验证结束")
            completion = "开发局胜利及结算已核实 · 未计独立验收" if standard_completed else "玩法未完成 · 自动玩法未开放"
            self.summary.set(f"货币战争 · {outcome} · {completion}" + ("\n" + recovery_text(report) if recovery_text(report) else ""))
            self.currency_status.set(self.summary.get())
            if report.get("currency_wars"):
                self._currency_observed(report["currency_wars"])
            else:
                self.currency_observation.set("本次未生成有效观察记录；请查看日志中的原因后重新识别。")
        if differential_universe:
            title, detail = universe_result(report)
            self.summary.set("差分宇宙 · "+title+("\n"+detail if detail else ""))
            self.du_status.set(title)
            self.du_observation.set(detail)
            self.du_result_report = json.loads(json.dumps(report, ensure_ascii=False))
            self.du_record_button.configure(state="normal")
        if report.get("operation", self.active_operation) == "plan":
            weekly = report.get("weekly_plan") or {}
            message = weekly.get("message", "周常完成情况未核实")
            self.weekly_status.set(message)
            self.summary.set(self.summary.get()+"\n"+message)
        self.result_alert.set(issue_text(report))
        if report.get("report_saved") is False:
            self.summary.set("报告未保存\n"+self.summary.get())
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
        label = STATUS_NAMES.get(status, status)
        if standard_completed and status == "success":
            label = "开发局结算已核实"
        elif currency and not standard_completed and status not in ("failed", "stopped"):
            label = "玩法未完成"
        self.status.set("● "+label)
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
                if (kind in ("finished", "checked", "launched", "cancelled", "operation_error", "run_error", "admin_launch_result")
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
                elif kind == "plan_phase":
                    self.plan_phase = event.get("phase", "")
                    self.current_task.set("核对本周演算记录" if self.plan_phase == "weekly" else "准备日常")
                elif kind == "plan_daily_result":
                    self._plan_daily_result(event.get("report", {}))
                elif kind == "universe_progress":
                    self._universe_progress(event)
                elif kind == "progress":
                    if not (self.active_operation == "plan" and event.get("phase") == "weekly"):
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
                elif kind == "admin_launch_result":
                    self._set_busy(False)
                    self.admin_launch_status.set(event["message"])
                    self._log("管理员启动：" + event["message"], "warning" if event.get("error") else "info")
                elif kind in ("operation_error", "run_error"):
                    self.runner = None
                    if kind == "run_error":
                        self._freeze_clock()
                        if self.active_operation in ("daily", "plan", "reward_only"):
                            self._finalize_task_rows("failed")
                        self.current_task.set("执行失败")
                    self._set_busy(False)
                    self.status.set("● 执行失败")
                    self.summary.set(str(event.get("message", "未知错误")))
                    self.result_alert.set(self.summary.get())
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


def main(config_path: Path = CONFIG_PATH, *, admin_task: bool = False) -> None:
    # Establish DPI awareness before Tk creates a window.
    from . import windows  # noqa: F401
    from contextlib import nullcontext
    from .admin_launch import TaskSession
    with TaskSession() if admin_task else nullcontext() as session:
        root = tk.Tk()
        ui = AutoHSRWindow(root, config_path)
        if session is not None:
            session.attach(root, lambda: ui._restore() if not ui.busy or ui.paused else None)
        root.mainloop()
