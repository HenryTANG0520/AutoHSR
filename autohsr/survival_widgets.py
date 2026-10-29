"""Survival Index rows: browsing never changes the selected daily target."""
from __future__ import annotations

from functools import lru_cache
import json
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from . import theme as t
from .dungeons import CATEGORIES
from .game_widgets import SceneButton, Surface
from .models import normalize


# The guide's display order is independent of workflow/catalogue scan order.
CATEGORY_NAVIGATION = (
    ("planar", "位面饰品"),
    ("calyx_golden", "经验材料/信用点"),
    ("calyx_crimson", "行迹材料"),
    ("stagnant_shadow", "角色晋阶材料"),
    ("cavern", "遗器"),
    ("echo_of_war", "行迹高级材料/光锥"),
)


class CategoryButton(SceneButton):
    """Two-line game category card, retaining the native button's input states."""

    def __init__(self, parent, scale, category, subtitle, command):
        self.category, self.subtitle = category, subtitle
        super().__init__(parent, scale, text=category.label, command=command)
        style = ttk.Style(parent)
        style.layout("Category.TButton", [("Button.label", {"sticky": "nsew"})])
        style.configure("Category.TButton", padding=0)
        self._photo = ImageTk.PhotoImage(Image.new("RGBA", (round(208*scale), round(64*scale)), t.CARD), master=self)
        self.configure(image=self._photo, compound="none", style="Category.TButton")

    def configure(self, cnf=None, **kwargs):
        changes_state = "state" in kwargs or isinstance(cnf, dict) and "state" in cnf
        previous = self.state() if changes_state else None
        result = super().configure(cnf, **kwargs)
        if changes_state and self.state() != previous:
            self.redraw()
        return result

    config = configure

    def _render(self):
        self._paint_job = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2 or not self.winfo_ismapped():
            return
        selected = self.instate(("selected",))
        disabled = self.instate(("disabled",))
        active = not disabled and self.instate(("active",))
        p = t.Painter(w, h, self.scale, t.RAIL if selected else t.CARD)
        rail = t.GOLD if selected else "#aaa9a9"
        title = t.GOLD if selected else t.TEXT
        subtitle = "#a18e62" if selected else "#555555"
        if disabled:
            title = subtitle = "#8c8c8c"
            rail = "#777777" if selected else "#bdbdbd"
        if not disabled and self.instate(("pressed",)):
            p.box((4, 0, p.width, p.height), "#31302e" if selected else "#e7e5df")
        if selected:
            p.asset("card-watermark.png", (p.width-99, p.height/2-47, p.width-3, p.height/2+59), "#302e2a")
        p.box((0, 0, 4, p.height), rail)
        # The side notch repeats the guide's dotted selection marker.
        for x, y in ((5, -5), (8, -3), (9, 0), (8, 3), (5, 5)):
            p.ellipse((x-1, p.height/2+y-1, x+1, p.height/2+y+1), rail)
        if active or not disabled and self.instate(("focus",)):
            p.box((1, 1, p.width-1, p.height-1), None, outline=t.GOLD, width=1.5)
        p.text((22, p.height/2-26), self.category.label, 24, title)
        p.text((22, p.height/2+8), self.subtitle, 16, subtitle)
        photo = ImageTk.PhotoImage(p.finish(), master=self)
        self.configure(image=photo)
        self._photo = photo


@lru_cache(maxsize=1)
def artwork():
    path = t.UI_ASSETS/"survival/sources.json"
    try:
        data = json.loads(path.read_text("utf-8"))
        return {(a["category"], a["name"], a["location"]): "survival/"+a["file"] for a in data["assets"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


@lru_cache(maxsize=1)
def group_metadata():
    try:
        data = json.loads((t.UI_ASSETS/"survival/groups.json").read_text("utf-8"))
        groups = {g["id"]: g for g in data["groups"]}
        members = {(m["category"], m["name"], m["location"]): groups[m["group"]] for m in data["memberships"]}
        return groups, members
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {}


def display_group(mission):
    groups, members = group_metadata()
    group = members.get((mission.category, mission.name, mission.location))
    if group is None and any(g["category"] == mission.category for g in groups.values()):
        return dict(id="other", label="其他副本")
    return group


class DungeonList(Surface):
    ROW_HEIGHT = 100
    HEADER_HEIGHT = 40

    def __init__(self, parent, ui, scrollbar):
        super().__init__(parent, ui.ui_scale, bg="white", takefocus=True, height=round(220*ui.ui_scale))
        self.ui, self.scrollbar = ui, scrollbar
        self.offset, self.cursor, self.hover = 0., 0, None
        self.rows, self.hitboxes = [], {}
        self.row_tops, self.headers, self.header_hitboxes = [], [], {}
        self.total_height = 0
        self._selection = None
        self._category = None
        self._follow_cursor = True
        self.bind("<Button-1>", self._click)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _: self._hover(None))
        for event, delta in (("<Up>", -1), ("<Down>", 1), ("<Prior>", -3), ("<Next>", 3)):
            self.bind(event, lambda _, delta=delta: self.move(delta))
        self.bind("<Home>", lambda _: self.move(-len(self.rows)))
        self.bind("<End>", lambda _: self.move(len(self.rows)))
        self.bind("<Return>", lambda _: self.choose(self.cursor))
        self.bind("<space>", lambda _: self.choose(self.cursor))
        self.bind("<FocusIn>", self.redraw)
        self.bind("<FocusOut>", self.redraw)
        self.bind("<Configure>", self._resize, add="+")
        variables = (ui.dungeon_browse_category, ui.dungeon_search, ui.dungeon_category, ui.target_name, ui.target_location)
        tokens = [(v, v.trace_add("write", lambda *_: self.refresh())) for v in variables]
        self.bind("<Destroy>", lambda e: [v.trace_remove("write", token) for v, token in tokens] if e.widget is self else None, add="+")
        self.refresh()

    @property
    def locked(self):
        return self.ui.busy or not self.ui.settings.allow_stamina_spend

    def action_label(self, mission):
        if not self.ui.settings.allow_stamina_spend:
            return "未授权"
        if not self.ui.tasks["battle"].get():
            return "未加入" if self.ui.busy else "加入计划"
        return "已选" if self.matches(mission) else "选用"

    @property
    def selection(self):
        return self.ui.dungeon_category.get(), self.ui.target_name.get(), self.ui.target_location.get()

    def refresh(self):
        category = next(c for c in CATEGORIES if c.label == self.ui.dungeon_browse_category.get())
        query = normalize(self.ui.dungeon_search.get())
        previous = self.rows
        self.rows = [m for m in self.ui.dungeon_catalogue if m.category == category.key
                     and (not query or query in normalize(m.name+" "+m.location+" "+(display_group(m) or {}).get("label", "")))]
        self._layout_rows()
        changed = self._selection != self.selection
        if self.rows != previous or self._category != category.key:
            self.offset, self.cursor, self.hover = 0., 0, None
            changed = True
        self._category, self._selection = category.key, self.selection
        if changed:
            self._follow_cursor = True
            index = next((i for i, m in enumerate(self.rows) if self.matches(m)), None)
            if index is not None:
                self.cursor = index
                self._reveal()
        self.yview()

    def matches(self, mission):
        label = next(c.label for c in CATEGORIES if c.key == mission.category)
        return self.selection == (label, mission.name, mission.location)

    def _layout_rows(self):
        self.row_tops, self.headers = [], []
        self.total_height = 0
        previous = None
        for mission in self.rows:
            group = display_group(mission)
            key = group["id"] if group else None
            if group and key != previous:
                self.headers.append((self.total_height, group))
                self.total_height += self.HEADER_HEIGHT
            self.row_tops.append(self.total_height)
            self.total_height += self.ROW_HEIGHT
            previous = key

    def row_bounds(self, index):
        top = self.row_tops[index]
        return top, top+self.ROW_HEIGHT

    def reveal_selection(self):
        self._follow_cursor = True
        self.ui.dungeon_browse_category.set(self.ui.dungeon_category.get())
        self.ui.dungeon_search.set("")
        self.refresh()
        self._reveal()
        self.yview()

    def _reveal(self):
        if not self.rows:
            return
        top, bottom = self.row_bounds(self.cursor)
        height = self.winfo_height()/self.scale
        if height >= self.ROW_HEIGHT+self.HEADER_HEIGHT and any(y+self.HEADER_HEIGHT == top for y, _ in self.headers):
            top -= self.HEADER_HEIGHT
        if top < self.offset:
            self.offset = top
        elif bottom > self.offset+height:
            self.offset = max(0, bottom-height)

    def move(self, delta):
        if not self.locked:
            self._follow_cursor = True
            self.cursor = min(max(0, self.cursor+delta), max(0, len(self.rows)-1))
            self._reveal()
            self.yview()
        return "break"

    def choose(self, index):
        if not self.locked and 0 <= index < len(self.rows):
            from .dungeon_ui import select_mission
            select_mission(self.ui, self.rows[index])
            self.cursor = index
            self._follow_cursor = True
            self.redraw()
        return "break"

    def yview(self, *args):
        height = self.winfo_height()/self.scale
        total = self.total_height
        if args:
            self._follow_cursor = False
        if args and args[0] == "moveto":
            self.offset = float(args[1])*total
        elif args and args[0] == "scroll":
            self.offset += int(args[1])*(self.ROW_HEIGHT if args[2] == "units" else max(self.ROW_HEIGHT, height-self.ROW_HEIGHT))
        self.offset = max(0, min(self.offset, max(0, total-height)))
        self.scrollbar.set(self.offset/max(1, total), min(1., (self.offset+height)/max(1, total)))
        self.redraw()

    def _resize(self, _):
        if self._follow_cursor:
            self._reveal()
        self.yview()

    def _wheel(self, event):
        if event.delta:
            self.yview("scroll", -1 if event.delta > 0 else 1, "units")
        return "break"

    def _target(self, event):
        x, y = event.x/self.scale, event.y/self.scale
        return next((i for i, (a,b,c,d) in self.hitboxes.items() if a <= x <= c and b <= y <= d), None)

    def _click(self, event):
        self.focus_set()
        target = self._target(event)
        if target is not None and not self.locked:
            top, bottom = self.row_bounds(target)
            if top < self.offset-.5 or bottom > self.offset+self.winfo_height()/self.scale+.5:
                self.cursor, self._follow_cursor = target, True
                self._reveal()
                self.yview()
                return
            self.choose(target)

    def _hover(self, index):
        if index != self.hover:
            self.hover = index
            self.configure(cursor="hand2" if index is not None and not self.locked else "")
            self.redraw()

    def _motion(self, event):
        self._hover(self._target(event))

    def paint(self, p):
        w, h = p.width, p.height
        self.hitboxes, self.header_hitboxes = {}, {}
        if not self.rows:
            p.text((w/2, h/2), "没有匹配的副本", 17, t.MUTED, "mm")
            return
        ink = t.MUTED if self.locked else t.TEXT
        for top, group in self.headers:
            y = top-self.offset
            if y+self.HEADER_HEIGHT <= 0 or y >= h:
                continue
            self.header_hitboxes[group["id"]] = (0, max(0, y), w, min(h, y+self.HEADER_HEIGHT))
            with p.clip(self.header_hitboxes[group["id"]]):
                p.box((0, y, w, y+self.HEADER_HEIGHT), "#f1f1f1")
                if group.get("file"):
                    p.asset("survival/"+group["file"], (14, y+5, 42.5, y+35))
                p.text((54 if group.get("file") else 14, y+9), group["label"], 20, ink)
        for i, mission in enumerate(self.rows):
            y = self.row_tops[i]-self.offset
            if y+self.ROW_HEIGHT <= 0 or y >= h:
                continue
            selected = self.matches(mission) and self.ui.tasks["battle"].get() and self.ui.settings.allow_stamina_spend
            self.hitboxes[i] = (0, max(0, y), w, min(h, y+self.ROW_HEIGHT))
            with p.clip((0, max(0, y), w, min(h, y+self.ROW_HEIGHT))):
                p.box((0, y, w, y+self.ROW_HEIGHT), "white")
                art = artwork().get((mission.category, mission.name, mission.location))
                if art and (t.UI_ASSETS/art).is_file():
                    src = t.asset(art)
                    factor = min(94/src.width, 88/src.height)
                    aw, ah = src.width*factor, src.height*factor
                    p.asset(art, (8+(94-aw)/2, y+(100-ah)/2, 8+(94+aw)/2, y+(100+ah)/2))
                else:
                    p.asset("tab-survival.png", (28, y+29, 72, y+73), t.MUTED)
                p.text((110, y+23), p.wrap(mission.name, w-288, 20, 1), 20, ink)
                # Same position-marker relationship as the game's row.
                p.ellipse((111, y+55, 125, y+69), None, t.MUTED, 1.2)
                p.poly((113, y+64, 123, y+64, 118, y+75), t.MUTED)
                p.ellipse((116, y+59, 120, y+63), t.MUTED)
                p.text((134, y+55), p.wrap(mission.location, w-308, 14, 2), 14, t.MUTED)
                cost = next(c.cost for c in CATEGORIES if c.key == mission.category)
                p.box((w-170, y+32, w-10, y+70), "#f0f0f0", 19)
                p.asset("stamina.png", (w-163, y+39, w-138, y+64))
                p.text((w-130, y+51), cost, 18, ink, "lm")
                p.box((w-100, y+34, w-12, y+68), t.RAIL if selected else t.CARD, 17, t.GOLD if selected else t.LINE, 1.5)
                p.text((w-56, y+51), self.action_label(mission), 16, t.GOLD if selected else ink, "mm")
                if mission.category == "planar":
                    p.text((w-14, y+78), "已有沉浸器优先", 11, t.MUTED, "rt")
                p.line((12, y+99, w-12, y+99), "#e5e5e5", 1.3)
                if selected or (self.hover == i and not self.locked) or (self.tk.call("focus") == self._w and self.cursor == i):
                    p.box((1, y+1, w-1, y+99), None, 0, t.GOLD if selected else "#bab5a9", 1.5)
                if self.tk.call("focus") == self._w and self.cursor == i:
                    p.poly((2, y+44, 8, y+50, 2, y+56), t.GOLD)
