"""Drawn guide furniture and live task cards; controls retain native focus."""
from __future__ import annotations

import tkinter as tk
from . import theme as t


class Surface(tk.Canvas):
    def __init__(self, parent, scale, **kwargs):
        super().__init__(parent, highlightthickness=0, borderwidth=0, **kwargs)
        self.scale = scale
        self._paint_job = None
        self.bind("<Configure>", self.redraw)
        self.bind("<Destroy>", self._destroy, add="+")

    def _destroy(self, event):
        if event.widget is self and self._paint_job:
            self.after_cancel(self._paint_job)
            self._paint_job = None

    def redraw(self, _event=None):
        if self._paint_job is None:
            self._paint_job = self.after_idle(self._render)

    def _render(self):
        self._paint_job = None
        if self.winfo_width() < 2:
            return
        self.delete("all")
        self.paint(self.winfo_width()/self.scale, self.winfo_height()/self.scale)

    def line(self, coords, color=t.LINE, width=1):
        return self.create_line(*(v*self.scale for v in coords), fill=color, width=width*self.scale)

    def box(self, coords, fill, outline="", width=1):
        return self.create_rectangle(*(v*self.scale for v in coords), fill=fill, outline=outline, width=width*self.scale)

    def text(self, x, y, text, size=10, color=t.TEXT, anchor="nw", **kwargs):
        return self.create_text(x*self.scale, y*self.scale, text=text, fill=color, anchor=anchor,
                                font=(t.FONT, size), **kwargs)

    def diamond(self, x, y, r, fill, outline=""):
        self.create_polygon(x*self.scale, (y-r)*self.scale, (x+r)*self.scale, y*self.scale,
                            x*self.scale, (y+r)*self.scale, (x-r)*self.scale, y*self.scale,
                            fill=fill, outline=outline, width=self.scale)


class Header(Surface):
    def __init__(self, parent, scale):
        super().__init__(parent, scale, bg=t.BG, height=round(76*scale))

    def paint(self, w, h):
        # An original compass/book mark, rather than a copied game emblem.
        self.diamond(39, 35, 20, "", t.LIGHT)
        self.line((28, 39, 28, 28, 39, 32, 50, 28, 50, 39, 39, 44, 28, 39), t.LIGHT)
        self.line((39, 32, 39, 44), t.LIGHT)
        self.text(77, 12, "星际和平指南", 20, t.LIGHT)
        self.text(79, 48, "AUTOHSR   /   开拓助手", 9, "#aeb8c7")
        self.line((w-260, 24, w-192, 24, w-164, 49, w-53, 49), "#3f4c60")
        for x, y in ((w-260, 24), (w-192, 24), (w-164, 49), (w-53, 49)):
            self.diamond(x, y, 3, t.GOLD)
        self.text(w-22, 20, "愿此行，终抵群星", 10, "#b8b5ac", anchor="ne")


class TrainingMeter(Surface):
    def __init__(self, parent, scale, variable):
        super().__init__(parent, scale, bg=t.PANEL, height=round(96*scale))
        self.variable = variable
        self._trace = variable.trace_add("write", lambda *_: self.redraw())
        self.bind("<Destroy>", self._untrace, add="+")

    def _untrace(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self._trace)

    @property
    def verified(self):
        return self.variable.get() == "verified"

    def paint(self, w, h):
        self.text(0, 2, "本次实训奖励", 10, t.MUTED)
        self.text(0, 25, "500" if self.verified else "—", 27)
        self.text(0, 77, "五档奖励已核实" if self.verified else "尚未核实 · 目标 500", 9, t.SUCCESS if self.verified else t.MUTED)
        start, end = 205, w-32
        self.line((start, 42, end, 42), "#bbae95" if self.verified else t.LINE, 3)
        for i in range(5):
            x = start+(end-start)*i/4
            self.diamond(x, 42, 17, t.GOLD if self.verified else t.CARD, t.GOLD)
            self.diamond(x, 42, 10, "", t.LIGHT if self.verified else "#c4b59c")
            if self.verified:
                self.line((x-6, 42, x-1, 47, x+7, 36), t.LIGHT, 2)
            self.text(x, 72, str((i+1)*100), 10, t.MUTED, anchor="n")


TASK_ICONS = {"assignments": "◇", "battle": "✦", "daily": "◎", "mail": "✉", "battlepass": "▤"}
TASK_DESCRIPTIONS = {"assignments": "领取现有委托奖励\n保留持续委托", "battle": "按本次计划挑战\n核对结算与消耗",
                     "daily": "领取实训奖励\n核实 500 与五档奖励", "mail": "领取现有邮件附件", "battlepass": "领取已有免费奖励"}


class TaskBoard(Surface):
    """Three live cards plus a carousel; same record API as the old task table."""
    def __init__(self, parent, scale, ui, names):
        super().__init__(parent, scale, bg=t.PANEL, height=round(240*scale), takefocus=True)
        self.ui, self.names = ui, names
        self.records = {key: dict(values=(label, "等待", ""), tags=()) for key, label in names.items()}
        self.offset, self.selected, self.hover = 0, None, None
        self.hitboxes = {}
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _: self._set_hover(None))
        self.bind("<MouseWheel>", lambda e: self.move(1 if e.delta < 0 else -1))
        for key, delta in (("Right", 1), ("Left", -1), ("Home", -9), ("End", 9)):
            self.bind("<"+key+">", lambda _, delta=delta: self.move(delta))
        self.bind("<Return>", lambda _: self.activate())
        self.bind("<space>", lambda _: self.activate())
        self.bind("<FocusIn>", self.redraw, add="+")
        self.bind("<FocusOut>", self.redraw, add="+")

    def item(self, iid, option=None, **kwargs):
        if kwargs:
            self.records[iid].update(kwargs)
            self.redraw()
        return self.records[iid][option] if option else dict(self.records[iid])

    def selection(self):
        return (self.selected,) if self.selected else ()

    def selection_remove(self, *_):
        self.selected = None
        self.redraw()

    def move(self, delta):
        keys = list(self.names)
        index = keys.index(self.selected) if self.selected else self.offset
        index = max(0, min(len(keys)-1, index+delta))
        self.selected = keys[index]
        self.offset = max(0, min(len(keys)-3, min(self.offset, index) if index < self.offset else max(self.offset, index-2)))
        self.redraw()
        return "break"

    def activate(self):
        self.selected = self.selected or list(self.names)[self.offset]
        self.ui._show_task_detail()
        self.redraw()
        return "break"

    def _target(self, event):
        x, y = event.x/self.scale, event.y/self.scale
        return next((key for key, (x1, y1, x2, y2) in self.hitboxes.items() if x1 <= x <= x2 and y1 <= y <= y2), None)

    def _set_hover(self, key):
        if key != self.hover:
            self.hover = key
            self.configure(cursor="hand2" if key else "")
            self.redraw()

    def _motion(self, event):
        self._set_hover(self._target(event))

    def _click(self, event):
        key = self._target(event)
        self.focus_set()
        if key in ("previous", "next"):
            self.offset = max(0, min(len(self.names)-3, self.offset+(-1 if key == "previous" else 1)))
            self.selected = None
            self.redraw()
        elif key:
            self.selected = key
            self.activate()

    def paint(self, w, h):
        self.hitboxes = {}
        keys = list(self.names)[self.offset:self.offset+3]
        card_width = (w-24)/3
        for i, key in enumerate(keys):
            x, right = i*(card_width+12), i*(card_width+12)+card_width
            chosen = key == self.selected or key == self.hover
            self.box((x+1, 1, right-1, h-37), t.CARD, t.GOLD if chosen else t.LINE, 2 if chosen else 1)
            self.box((x+1, 1, right-1, 5), t.GOLD if chosen else "#d2c8b5")
            self.text(x+18, 18, f"{list(self.names).index(key)+1:02d}  /  每日任务", 9, t.MUTED)
            self.text(x+18, 45, TASK_ICONS[key], 25, t.GOLD)
            label, state, detail = self.records[key]["values"]
            self.text(x+18, 95, label, 12, width=max(1, (card_width-30)*self.scale))
            if h >= 225:
                self.text(x+18, 128, TASK_DESCRIPTIONS[key], 9, t.MUTED, width=max(1, (card_width-30)*self.scale))
            color = t.SUCCESS if state in ("完成", "已完成", "全部完成") else t.ERROR if state == "失败" else t.GOLD if state == "进行中" else t.MUTED
            self.line((x+16, h-77, right-16, h-77), t.LINE)
            self.text(x+18, h-65, state, 10, color)
            self.text(right-16, h-64, "详情  ›", 9, t.MUTED, anchor="ne")
            self.hitboxes[key] = (x, 0, right, h-36)
        for key, x, symbol in (("previous", w-95, "‹"), ("next", w-27, "›")):
            enabled = self.offset > 0 if key == "previous" else self.offset < len(self.names)-3
            self.text(x, h-14, symbol, 18, t.TEXT if enabled else "#bcb9b2", anchor="center")
            if enabled:
                self.hitboxes[key] = (x-18, h-32, x+18, h)
        self.text(w-61, h-14, f"{self.offset+1}–{self.offset+len(keys)} / {len(self.names)}", 8, t.MUTED, anchor="center")
        self.text(1, h-16, "← → 切换任务     Enter 查看结果", 8, t.MUTED, anchor="w")
