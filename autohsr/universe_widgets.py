"""Native guide entrance artwork with live plan fields and real ttk actions."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk
from io import BytesIO

from . import theme as t
from .game_widgets import Surface


class UniversePoster(Surface):
    """Keep the illustration's 966:639 geometry; never display reference counters."""

    def __init__(self, parent, scale, ui, key, show):
        super().__init__(parent, scale)
        self.ui, self.key = ui, key
        self.du = key == "differential_universe"
        self.primary = ttk.Button(self, style="Poster.TButton")
        self.editor_button = ttk.Button(self, text="演算设置" if self.du else "开发工具",
                                       style="Poster.TButton", command=lambda: show("editor"))
        self.result_button = ttk.Button(self, text="查看结果", style="Poster.TButton", command=lambda: show("result"))
        self._button_images = {}
        for button in (self.primary, self.editor_button, self.result_button):
            button.bind("<Configure>", self.redraw, add="+")
        self.bind("<Configure>", self.position, add="+")
        self.watch(ui.differential_universe_runs, ui.du_team, ui.du_mode, ui.du_resume_active,
                   ui.du_resume_mode, ui.du_save, ui.du_rewards, ui.du_daily, ui.du_status, ui.currency_status)

    def geometry(self):
        width, height = self.winfo_width()/self.scale, self.winfo_height()/self.scale
        ratio = min(width/966, height/639)
        return (width-966*ratio)/2, (height-639*ratio)/2, ratio

    def position(self, _event=None):
        x, y, ratio = self.geometry()
        d = lambda n: round(n*self.scale)
        # Native controls retain their font and hit target even at minimum size.
        for button, bx, by, anchor in ((self.editor_button, 15, 60, "nw"),
                                       (self.result_button, 598, 588, "e"),
                                       (self.primary, 939, 588, "e")):
            button.place(x=d(x+bx*ratio), y=d(y+by*ratio), anchor=anchor)

    def paint(self, outer):
        x, y, ratio = self.geometry()
        if ratio <= 0:
            return
        light = self.du
        bg, ink = ("#e6ead7", "#20231a") if light else ("#1a1843", "#eeedf5")
        p = t.Painter(max(1, round(966*ratio*self.scale)), max(1, round(639*ratio*self.scale)), ratio*self.scale, bg)
        p.asset("universe/du.png" if light else "universe/cw.png", (0, 0, 966, 639))
        if light:
            p.text((213, 209), self.ui.differential_universe_runs.get(), 66, "#e8f578", "mt")
            p.box((56, 347, 370, 387), "#20211a")
            p.text((213, 349), "计划局数", 29, "#b9c743", "mt")
            p.box((600, 101, 938, 134), "#1e211d")
            for dx, dy in ((610,110), (624,110), (610,124)):
                p.box((dx,dy,dx+8,dy+8), "#b53576")
            p.text((929, 103), "差分宇宙", 29, "#e3ed7b", "rt")
            mode = self.ui.du_resume_mode.get() if self.ui.du_resume_active.get() else self.ui.du_mode.get()
            p.box((688, 150, 938, 194), "#23241e")
            p.text((924, 156), mode, 29, "#ebd997", "rt")
            p.box((746, 58, 939, 91), "#1f211b", 17)
            p.text((842, 60), "接续当前进度" if self.ui.du_resume_active.get() else "新开演算", 23, "#ebd997", "mt")
            p.text((600, 217), "预设编队", 20, "#535a3c")
            p.text((600, 248), p.wrap(self.ui.du_team.get() or "待填写", 338, 23, 3), 23, ink)
            p.text((427, 375), "通关后", 25, ink)
            p.line((427, 409, 938, 409), "#777f5c", 1.5)
            options = [label for variable, label in ((self.ui.du_save, "保存到空槽"), (self.ui.du_rewards, "领取红点奖励"),
                                                     (self.ui.du_daily, "完成每日")) if variable.get()]
            p.text((427, 425), p.wrap(" · ".join(options) or "直接结束", 507, 23, 2), 23, ink)
            costs = []
            if self.ui.du_rewards.get():
                costs.append("使用已有卡带")
            if self.ui.du_daily.get():
                costs.append("每日按独立预算刷本")
            if costs:
                p.text((427, 488), " · ".join(costs), 19, "#73511d")
            status = self.ui.du_status.get()
        else:
            p.box((0, 0, 966, 40), "#28264e")
            p.text((20, 8), "开发中 · 整局未验收", 23, "#ead58e")
            p.text((220, 185), "只读", 61, "#f3f1ff", "mt")
            p.poly((57,264,382,264,382,293,361,313,78,313,57,293), "#cfbc73")
            p.poly((61,267,378,267,378,288,358,308,81,308,61,288), "#28274d")
            p.text((220, 272), "当前画面", 30, "#f2f1fc", "mt")
            p.box((647, 101, 938, 134), "#516be4")
            p.text((929, 103), "货币战争", 29, "#ffffff", "rt")
            p.box((662, 157, 938, 197), "#151631")
            p.text((924, 161), "只读观察", 29, "#a1d5e9", "rt")
            p.box((423, 257, 940, 366), "#171631")
            p.text((440, 274), "周常自动运行尚未接入", 27, "#ebd997")
            p.text((427, 379), "最近结果", 25, ink)
            p.line((427, 410, 938, 410), "#8888ad", 1.5)
            status_text = self.ui.currency_status.get()
            if status_text == "开发中 · 整局未验收":
                status_text = "尚未识别"
            p.text((427, 428), p.wrap(status_text, 507, 24, 3), 24, ink)
            status = ""
        if status:
            p.text((427, 518), p.wrap(status, 507, 18, 2), 18, ink)
        outer.image.alpha_composite(p.image, outer.coords((x, y)))
        self.position()
        self._blend_buttons(outer)

    def _blend_buttons(self, outer):
        """Native ttk hit/keyboard states with the actual artwork behind corners."""
        for button in (self.primary, self.editor_button, self.result_button):
            width, height = button.winfo_reqwidth(), button.winfo_reqheight()
            if width < 2 or height < 2:
                continue
            left, top = button.winfo_x(), button.winfo_y()
            background = outer.image.crop((left*2, top*2, (left+width)*2, (top+height)*2))
            if button not in self._button_images:
                style_name = f"Poster{self.winfo_id()}_{len(self._button_images)}.TButton"
                images = [tk.PhotoImage(master=self) for _ in range(4)]
                self._button_images[button] = images
                element = style_name+".surface"
                style = self.ui.style
                style.element_create(element, "image", images[0], ("disabled", images[3]),
                                     ("pressed", images[2]), ("active", images[1]), ("focus", images[1]), sticky="nsew")
                style.layout(style_name, [(element, {"sticky":"nsew", "children":[("Button.padding", {"sticky":"nsew",
                    "children":[("Button.label", {"sticky":"nsew"})]})]})])
                style.configure(style_name, font=(t.FONT, 11), padding=(round(10*self.scale), round(7*self.scale)),
                                foreground=t.TEXT, borderwidth=0, anchor="center")
                style.map(style_name, foreground=[("disabled", "#8b8b8b"), ("!disabled", t.TEXT)])
                button.configure(style=style_name)
            for index, photo in enumerate(self._button_images[button]):
                face = t.Painter(width, height, self.scale, None)
                face.image = background.copy()
                from PIL import ImageDraw
                face.draw = ImageDraw.Draw(face.image)
                w, h = width/self.scale, height/self.scale
                fill = "#d3d3d3" if index == 3 else t.CARD
                face.box((1, 1, w-1, h-1), fill, h/2, t.GOLD if index in (1, 2) else "#b4b4b4", 1.4)
                face.box((5, 5, w-5, h-5), fill, h/2-4, "#d5d5d5", 1)
                output = BytesIO()
                face.finish().save(output, format="PNG")
                photo.configure(data=output.getvalue(), format="png")
