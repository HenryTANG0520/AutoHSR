"""Survival Index selectors and game-style integer challenge controls."""
from __future__ import annotations

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
    reload_catalogue(ui)
    ttk.Label(parent, text="目标副本", style="Section.TLabel").pack(anchor="w")
    fields = ttk.Frame(parent, style="Panel.TFrame")
    fields.pack(fill="x", pady=(5, 8))
    fields.columnconfigure(1, weight=1)
    for row, (label, variable, attribute) in enumerate((
        ("分类", ui.dungeon_category, "dungeon_category_combo"),
        ("副本", ui.target_name, "dungeon_name_combo"),
        ("地点", ui.target_location, "dungeon_location_combo"),
    )):
        if row:
            ttk.Label(fields, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        control = ttk.Combobox(fields, textvariable=variable, state="readonly" if row == 0 else "normal")
        if row:
            control.grid(row=row, column=1, sticky="ew", pady=3)
        setattr(ui, attribute, control)
        ui.setting_controls.append(control)
        ui.stamina_controls.append(control)
    ui.dungeon_category_combo.configure(values=[item.label for item in CATEGORIES])
    ui.dungeon_category_combo.bind("<<ComboboxSelected>>", lambda _: select_category(ui))
    ui.dungeon_name_combo.bind("<<ComboboxSelected>>", lambda _: select_name(ui))
    update_options(ui)
    numbers = ttk.Frame(parent, style="Panel.TFrame")
    numbers.pack(fill="x")
    numbers.columnconfigure(1, weight=1)
    ttk.Label(numbers, text="挑战次数", style="Muted.TLabel").grid(row=0, column=0, sticky="w", columnspan=5)
    for column, label, delta in ((0, "−", -1), (4, "+", 1)):
        button = ttk.Button(numbers, text=label, width=3, command=lambda step=delta: change_count(ui, step))
        button.grid(row=1, column=column, padx=(0, 6) if column == 0 else (6, 0))
        ui.setting_controls.append(button)
        ui.stamina_controls.append(button)
    ui.challenge_scale = ttk.Scale(numbers, from_=1, to=24, command=lambda value: set_count(ui, round(float(value))))
    ui.challenge_scale.grid(row=1, column=1, columnspan=2, sticky="ew")
    entry = ttk.Spinbox(numbers, from_=1, to=24, textvariable=ui.challenge_count, width=4)
    entry.grid(row=1, column=3, padx=(8, 0))
    ui.challenge_entry = entry
    ui.setting_controls.extend((ui.challenge_scale, entry))
    ui.stamina_controls.extend((ui.challenge_scale, entry))
    wrapped_label(parent, textvariable=ui.battle_cost, style="Muted.TLabel").pack(fill="x", pady=(4, 7))
    safety = ttk.Frame(parent, style="Panel.TFrame")
    safety.pack(fill="x")
    ttk.Label(safety, text="本次开拓力上限", style="Muted.TLabel").pack(side="left")
    budget = ttk.Spinbox(safety, from_=10, to=240, increment=10, textvariable=ui.stamina_limit, width=6)
    budget.pack(side="left", padx=(10, 20))
    support = ttk.Checkbutton(safety, text="借用好友支援", variable=ui.use_support)
    support.pack(side="left")
    ui.setting_controls.extend((budget, support))
    ui.stamina_controls.extend((budget, support))
    presets = ttk.Frame(parent, style="Panel.TFrame")
    presets.pack(fill="x", pady=(6, 0))
    for label, command in (("设为 1 次", lambda: ui._preset(selected_category(ui).cost, 1)),
                           ("填满预算", lambda: use_budget(ui)),
                           ("刷新副本目录", lambda: ui._start(catalogue=True))):
        button = ttk.Button(presets, text=label, style="Compact.TButton", command=command)
        button.pack(side="left", padx=(0, 7))
        ui.setting_controls.append(button)
        if label != "刷新副本目录":
            ui.stamina_controls.append(button)
    wrapped_label(parent, textvariable=ui.battle_hint, style="Warning.TLabel").pack(fill="x", pady=(5, 0))


def update_options(ui):
    category = selected_category(ui)
    missions = [item for item in ui.dungeon_catalogue if item.category == category.key]
    ui.dungeon_name_combo.configure(values=list(dict.fromkeys(item.name for item in missions)))
    ui.dungeon_location_combo.configure(values=list(dict.fromkeys(item.location for item in missions if item.name == ui.target_name.get())))


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
        ui.battle_cost.set(f"{count} 次 × {category.cost} 开拓力 = 预计 {cost} 开拓力" + suffix)
    except ValueError:
        ui.battle_cost.set(f"请输入 1～{maximum} 次；每次 {category.cost} 开拓力。")
