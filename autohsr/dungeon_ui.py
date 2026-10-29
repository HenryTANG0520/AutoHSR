"""Survival Index selectors and game-style integer challenge controls."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .config import RESOURCE_ROOT, ROOT
from .dungeons import CATEGORIES, BY_KEY, category_for, count_limit, load_catalogue
from .theme import wrapped_label


def reload_catalogue(ui):
    bundled = RESOURCE_ROOT / "assets" / "dungeons.json"
    try:
        ui.dungeon_catalogue = load_catalogue(bundled, ROOT / "dungeons.local.json")
    except (OSError, ValueError, TypeError):
        ui.dungeon_catalogue = load_catalogue(bundled)


def selected_category(ui):
    return next(item for item in CATEGORIES if item.label == ui.dungeon_category.get())


def build_fields(ui, parent):
    from .survival_widgets import DungeonList
    reload_catalogue(ui)
    d = lambda n: round(n*ui.ui_scale)
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(1, weight=1, minsize=d(100))
    ui.dungeon_search = tk.StringVar()
    ui.dungeon_target_caption = tk.StringVar()
    ui.dungeon_manual_visible = ui.dungeon_advanced_visible = False
    header = ttk.Frame(parent, style="Card.TFrame")
    header.grid(row=0, column=0, sticky="ew", pady=(0, d(8)))
    header.columnconfigure(1, weight=1)
    ttk.Label(header, text="搜索", style="Muted.TLabel").grid(row=0, column=0, padx=(0, d(8)))
    ui.dungeon_search_entry = ttk.Entry(header, textvariable=ui.dungeon_search, width=10)
    ui.dungeon_search_entry.grid(row=0, column=1, sticky="ew")
    ui.dungeon_search_entry.bind("<Escape>", lambda _: ui.dungeon_search.set(""))
    clear = ttk.Button(header, text="×", width=2, style="Compact.TButton", command=lambda: ui.dungeon_search.set(""))
    clear.grid(row=0, column=2, padx=(d(4), 0))
    ui.dungeon_manual_button = ttk.Button(header, text="手动填写", style="Compact.TButton", command=lambda: show_manual(ui, not ui.dungeon_manual_visible))
    ui.dungeon_manual_button.grid(row=0, column=3, padx=d(8))
    ui.dungeon_advanced_button = ttk.Button(header, text="挑战设置", style="Compact.TButton", command=lambda: show_advanced(ui, not ui.dungeon_advanced_visible))
    ui.dungeon_advanced_button.grid(row=0, column=4)
    ui.setting_controls.extend((ui.dungeon_search_entry, clear, ui.dungeon_manual_button, ui.dungeon_advanced_button))
    ui.stamina_controls.extend((ui.dungeon_manual_button, ui.dungeon_advanced_button))
    browser = ui.dungeon_browser = ttk.Frame(parent, style="Card.TFrame")
    browser.grid(row=1, column=0, sticky="nsew")
    browser.columnconfigure(0, weight=1)
    browser.rowconfigure(0, weight=1)
    scroll = ttk.Scrollbar(browser, orient="vertical")
    ui.dungeon_list = DungeonList(browser, ui, scroll)
    ui.dungeon_list.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    scroll.configure(command=ui.dungeon_list.yview)
    ui.setting_controls.append(ui.dungeon_list)
    ui.dungeon_browse_controls = (*ui.category_buttons.values(), ui.dungeon_search_entry, clear, ui.dungeon_list)
    fields = ttk.Frame(parent, style="Panel.TFrame")
    ui.dungeon_manual_fields = fields
    fields.grid(row=1, column=0, sticky="new")
    fields.columnconfigure(1, weight=1)
    for row, (label, variable, attribute) in enumerate((
        ("分类", ui.dungeon_category, "dungeon_category_combo"),
        ("副本", ui.target_name, "dungeon_name_combo"),
        ("地点", ui.target_location, "dungeon_location_combo"),
    )):
        ttk.Label(fields, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, d(12)), pady=d(3))
        control = ttk.Combobox(fields, textvariable=variable, state="readonly" if row == 0 else "normal")
        control.grid(row=row, column=1, sticky="ew", pady=d(3))
        setattr(ui, attribute, control)
        ui.setting_controls.append(control)
        ui.stamina_controls.append(control)
    ui.dungeon_category_combo.configure(values=[item.label for item in CATEGORIES])
    ui.dungeon_category_combo.bind("<<ComboboxSelected>>", lambda _: select_category(ui))
    ui.dungeon_name_combo.bind("<<ComboboxSelected>>", lambda _: select_name(ui))
    update_options(ui)
    target = ttk.Frame(parent, style="Card.TFrame")
    target.grid(row=2, column=0, sticky="ew", pady=(d(8), d(3)))
    target.columnconfigure(0, weight=1)
    caption = wrapped_label(target, textvariable=ui.dungeon_target_caption, style="Muted.TLabel")
    caption.grid(row=0, column=0, sticky="ew")
    ui.battle_checkbox = ttk.Checkbutton(target, text="加入计划", variable=ui.tasks["battle"], style="Card.TCheckbutton")
    ui.battle_checkbox.grid(row=0, column=1, padx=(d(12), 0))
    ui.task_controls = {"battle": ui.battle_checkbox}
    ui.setting_controls.append(ui.battle_checkbox)
    numbers = ttk.Frame(parent, style="Panel.TFrame")
    numbers.grid(row=3, column=0, sticky="ew")
    numbers.columnconfigure(2, weight=1)
    ttk.Label(numbers, text="次数", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, d(8)))
    for column, label, delta in ((1, "−", -1), (5, "+", 1)):
        button = ttk.Button(numbers, text=label, width=3, command=lambda step=delta: change_count(ui, step))
        button.grid(row=0, column=column, padx=(0, d(6)) if column == 1 else (d(6), 0))
        ui.setting_controls.append(button)
        ui.stamina_controls.append(button)
    ui.challenge_scale = ttk.Scale(numbers, from_=1, to=24, command=lambda value: set_count(ui, round(float(value))))
    ui.challenge_scale.grid(row=0, column=2, columnspan=2, sticky="ew")
    entry = ttk.Spinbox(numbers, from_=1, to=24, textvariable=ui.challenge_count, width=4)
    entry.grid(row=0, column=4, padx=(d(8), 0))
    ui.challenge_entry = entry
    ui.setting_controls.extend((ui.challenge_scale, entry))
    ui.stamina_controls.extend((ui.challenge_scale, entry))
    wrapped_label(parent, textvariable=ui.battle_cost, style="Muted.TLabel").grid(row=4, column=0, sticky="ew", pady=(d(4), d(5)))
    advanced = ui.dungeon_advanced_fields = ttk.Frame(parent, style="Panel.TFrame")
    advanced.grid(row=1, column=0, sticky="new")
    safety = ttk.Frame(advanced, style="Panel.TFrame")
    safety.pack(fill="x")
    ttk.Label(safety, text="本次开拓力上限", style="Muted.TLabel").pack(side="left")
    budget = ttk.Spinbox(safety, from_=10, to=240, increment=10, textvariable=ui.stamina_limit, width=6)
    ui.stamina_limit_entry = budget
    budget.pack(side="left", padx=(d(10), d(20)))
    support = ttk.Checkbutton(safety, text="借用好友支援", variable=ui.use_support)
    support.pack(side="left")
    ui.setting_controls.extend((budget, support))
    ui.stamina_controls.extend((budget, support))
    presets = ttk.Frame(advanced, style="Panel.TFrame")
    presets.pack(fill="x", pady=(d(6), 0))
    for label, command in (("设为 1 次", lambda: ui._preset(selected_category(ui).cost, 1)),
                           ("填满预算", lambda: use_budget(ui)),
                           ("刷新副本目录", lambda: ui._start(catalogue=True))):
        button = ttk.Button(presets, text=label, style="Compact.TButton", command=command)
        button.pack(side="left", padx=(0, d(7)))
        ui.setting_controls.append(button)
        if label != "刷新副本目录":
            ui.stamina_controls.append(button)
    wrapped_label(advanced, textvariable=ui.battle_hint, style="Warning.TLabel").pack(fill="x", pady=(d(5), 0))
    show_manual(ui, False)
    show_advanced(ui, False)
    def search_changed(*_):
        clear.grid() if ui.dungeon_search.get() else clear.grid_remove()
        if ui.dungeon_search.get() and not ui.busy:
            show_browser(ui)
    search_variable = ui.dungeon_search
    token = search_variable.trace_add("write", search_changed)
    parent.bind("<Destroy>", lambda event: search_variable.trace_remove("write", token) if event.widget is parent else None, add="+")
    search_changed()


def show_browser(ui):
    ui.dungeon_manual_visible = ui.dungeon_advanced_visible = False
    _show_editor(ui)


def show_manual(ui, visible=True):
    ui.dungeon_manual_visible = visible
    if visible:
        ui.dungeon_advanced_visible = False
    _show_editor(ui)


def show_advanced(ui, visible=True):
    ui.dungeon_advanced_visible = visible
    if visible:
        ui.dungeon_manual_visible = False
    _show_editor(ui)


def _show_editor(ui):
    ui.dungeon_manual_button.configure(text="返回列表" if ui.dungeon_manual_visible else "手动填写")
    ui.dungeon_advanced_button.configure(text="返回列表" if ui.dungeon_advanced_visible else "挑战设置")
    ui.dungeon_manual_fields.grid() if ui.dungeon_manual_visible else ui.dungeon_manual_fields.grid_remove()
    ui.dungeon_advanced_fields.grid() if ui.dungeon_advanced_visible else ui.dungeon_advanced_fields.grid_remove()
    ui.dungeon_browser.grid_remove() if ui.dungeon_manual_visible or ui.dungeon_advanced_visible else ui.dungeon_browser.grid()


def select_mission(ui, mission):
    if ui.busy or not ui.settings.allow_stamina_spend:
        return
    loading = ui._loading
    ui._loading = True
    try:
        ui.dungeon_category.set(BY_KEY[mission.category].label)
        ui.target_name.set(mission.name)
        ui.target_location.set(mission.location)
        ui.tasks["battle"].set(True)
        try:
            count = int(ui.challenge_count.get())
        except ValueError:
            count = 1
        set_count(ui, count)
        update_options(ui)
    finally:
        ui._loading = loading
    if ui.input_error_field in ("target_name", "target_location"):
        ui._clear_input_error()
    ui._form_changed()


def update_options(ui):
    category = selected_category(ui)
    missions = [item for item in ui.dungeon_catalogue if item.category == category.key]
    ui.dungeon_name_combo.configure(values=list(dict.fromkeys(item.name for item in missions)))
    ui.dungeon_location_combo.configure(values=list(dict.fromkeys(item.location for item in missions if item.name == ui.target_name.get())))
    if hasattr(ui, "dungeon_list"):
        ui.dungeon_list.refresh()


def use_budget(ui):
    try:
        budget = int(ui.stamina_limit.get())
        if not 10 <= budget <= 240 or budget % 10 or budget < selected_category(ui).cost:
            raise ValueError()
    except ValueError:
        ui.save_status.set("请先填写能支付单次挑战的开拓力上限（10～240，10的倍数）。")
        return
    ui._preset(budget, selected_category(ui).batch)


def select_category(ui):
    missions = [item for item in ui.dungeon_catalogue if item.category == selected_category(ui).key]
    if missions:
        ui.target_name.set(missions[0].name)
        ui.target_location.set(missions[0].location)
    else:
        ui.target_name.set("")
        ui.target_location.set("")
    try:
        count = int(ui.challenge_count.get())
    except ValueError:
        count = 1
    set_count(ui, count)
    update_options(ui)
    ui.dungeon_browse_category.set(ui.dungeon_category.get())


def select_name(ui):
    missions = [item for item in ui.dungeon_catalogue if item.category == selected_category(ui).key and item.name == ui.target_name.get()]
    if missions and ui.target_location.get() not in [item.location for item in missions]:
        ui.target_location.set(missions[0].location)
    update_options(ui)


def set_count(ui, count):
    if ui.busy or not ui.settings.allow_stamina_spend or not ui.tasks["battle"].get():
        return
    value = str(max(1, min(count_limit(selected_category(ui)), count)))
    if ui.challenge_count.get() != value:
        ui.challenge_count.set(value)


def change_count(ui, delta):
    try:
        count = int(ui.challenge_count.get())
    except ValueError:
        count = 1
    set_count(ui, count + delta)


def refresh_count(ui):
    category = selected_category(ui)
    maximum = count_limit(category)
    ui.challenge_scale.configure(to=maximum)
    ui.challenge_entry.configure(to=maximum)
    try:
        count = int(ui.challenge_count.get())
        if not 1 <= count <= maximum:
            raise ValueError()
        if round(ui.challenge_scale.get()) != count:
            ui.challenge_scale.set(count)
        cost = count * category.cost
        suffix = " · 每周最多领取 3 次，以游戏剩余次数为准" if category.weekly_limit else ""
        if category.key == "planar":
            ui.battle_cost.set(f"{count} 次 · 最多 {cost} 开拓力 · 已有沉浸器优先 · 上限 {ui.stamina_limit.get()}")
        else:
            ui.battle_cost.set(f"{count} 次 × {category.cost} 开拓力 = 预计 {cost} 开拓力 · 上限 {ui.stamina_limit.get()}" + suffix)
    except ValueError:
        ui.battle_cost.set(f"请输入 1～{maximum} 次；每次 {category.cost} 开拓力。")
    joined = ui.tasks["battle"].get() and ui.settings.allow_stamina_spend
    if not joined:
        ui.battle_cost.set("本次不刷本")
    ui.dungeon_target_caption.set(("已选 · " if joined else "未加入 · ")+(ui.target_name.get() or "名称待填写")+" · "+(ui.target_location.get() or "地点待填写"))
