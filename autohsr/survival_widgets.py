"""Survival Index rows: browsing never changes the selected daily target."""
from __future__ import annotations

from functools import lru_cache
import json
import tkinter as tk

from . import theme as t
from .dungeons import CATEGORIES
from .game_widgets import Surface
from .models import normalize


@lru_cache(maxsize=1)
def artwork():
    path = t.UI_ASSETS/"survival/sources.json"
    try:
        data = json.loads(path.read_text("utf-8"))
        return {(a["category"], a["name"], a["location"]): "survival/"+a["file"] for a in data["assets"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


class DungeonList(Surface):
    ROW_HEIGHT = 100

    def __init__(self, parent, ui, scrollbar):
        super().__init__(parent, ui.ui_scale, bg="white", takefocus=True, height=round(220*ui.ui_scale))
        self.ui, self.scrollbar = ui, scrollbar
        self.offset, self.cursor, self.hover = 0., 0, None
        self.rows, self.hitboxes = [], {}
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
        return self.ui.busy or not self.ui.settings.allow_stamina_spend or not self.ui.tasks["battle"].get()

    @property
    def selection(self):
        return self.ui.dungeon_category.get(), self.ui.target_name.get(), self.ui.target_location.get()

    def refresh(self):
        category = next(c for c in CATEGORIES if c.label == self.ui.dungeon_browse_category.get())
        query = normalize(self.ui.dungeon_search.get())
        previous = self.rows
        self.rows = [m for m in self.ui.dungeon_catalogue if m.category == category.key
                     and (not query or query in normalize(m.name+" "+m.location))]
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

    def reveal_selection(self):
        self._follow_cursor = True
        self.ui.dungeon_browse_category.set(self.ui.dungeon_category.get())
        self.ui.dungeon_search.set("")
        self.refresh()
        self._reveal()
        self.yview()

    def _reveal(self):
        top, bottom = self.cursor*self.ROW_HEIGHT, (self.cursor+1)*self.ROW_HEIGHT
        height = self.winfo_height()/self.scale
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
        total = len(self.rows)*self.ROW_HEIGHT
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
        if target is not None:
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
        self.hitboxes = {}
        if not self.rows:
            p.text((w/2, h/2), "没有匹配的副本", 17, t.MUTED, "mm")
            return
        ink = t.MUTED if self.locked else t.TEXT
        for i, mission in enumerate(self.rows):
            y = i*self.ROW_HEIGHT-self.offset
            if y+self.ROW_HEIGHT <= 0 or y >= h:
                continue
            selected = self.matches(mission)
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
                p.text((w-56, y+51), "已选" if selected else "选用", 16, t.GOLD if selected else ink, "mm")
                if mission.category == "planar":
                    p.text((w-14, y+78), "已有沉浸器优先", 11, t.MUTED, "rt")
                p.line((12, y+99, w-12, y+99), "#e5e5e5", 1.3)
                if selected or (self.hover == i and not self.locked) or (self.focus_get() == self and self.cursor == i):
                    p.box((1, y+1, w-1, y+99), None, 0, t.GOLD if selected else "#bab5a9", 1.5)
                if self.focus_get() == self and self.cursor == i:
                    p.poly((2, y+44, 8, y+50, 2, y+56), t.GOLD)
