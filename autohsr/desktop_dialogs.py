"""Read-only details using the local 4.6 confirmation-panel reference."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import tkinter as tk
from tkinter import font as tkfont, ttk

from PIL import Image, ImageTk

from . import theme
from .game_widgets import Surface


PAPER = "#e2e5e6"
FOOTER = "#262626"
TRANSPARENT = "#e2e5e7"
# 1920px reference: 960×360 plate, 8px offset frame, 96px footer.
# The guide's logical drawing baseline is 80% of that reference.
FRAME = 6.4
FOOTER_HEIGHT = 76.8
NOTICE_SIZE = (774.4, 294.4)


class DetailClose(ttk.Button):
    """Native button behavior with a full-size pill, avoiding tiled end caps."""
    def __init__(self, parent, scale, command):
        self.scale, self._paint_job = scale, None
        self._photo = ImageTk.PhotoImage(Image.new("RGB", (round(288*scale), round(46.4*scale)), FOOTER), master=parent)
        style = ttk.Style(parent)
        style.layout("Dialog.TButton", [("Button.label", {"sticky":"nsew"})])
        style.configure("Dialog.TButton", padding=0)
        super().__init__(parent, text="关闭", image=self._photo, compound="image",
                         style="Dialog.TButton", command=command)
        for event in ("<Configure>", "<Map>", "<Enter>", "<Leave>", "<FocusIn>", "<FocusOut>",
                      "<ButtonPress-1>", "<ButtonRelease-1>", "<KeyPress-space>", "<KeyRelease-space>"):
            self.bind(event, self.redraw, add="+")
        self.bind("<Destroy>", self._destroy, add="+")

    def redraw(self, _=None):
        if self._paint_job is None:
            self._paint_job = self.after_idle(self._render)

    def _destroy(self, event):
        if event.widget is self and self._paint_job is not None:
            self.after_cancel(self._paint_job)
            self._paint_job = None

    def _render(self):
        self._paint_job = None
        if not self.winfo_ismapped():
            return
        p = theme.Painter(self.winfo_width(), self.winfo_height(), self.scale, FOOTER)
        w, h = p.width, p.height
        edge = theme.GOLD if any(self.instate((s,)) for s in ("active", "pressed", "focus")) else "#bcbcbc"
        fill = "#d5d5d5" if self.instate(("pressed",)) else "#e1e1e1"
        p.box((1, 1, w-1, h-1), fill, h/2-1, edge, 1.2)
        p.box((5, 5, w-5, h-5), None, h/2-5, "#cbcbcb")
        x, y = w/2-32, h/2
        p.ellipse((x-11, y-11, x+11, y+11), "#111111", theme.GOLD, 1.4)
        p.line((x-4, y-4, x+4, y+4), "#e8dfca", 1.7)
        p.line((x-4, y+4, x+4, y-4), "#e8dfca", 1.7)
        p.text((w/2+7, y), "关闭", 20, "#111111", "mm")
        photo = ImageTk.PhotoImage(p.finish(), master=self)
        self.configure(image=photo)
        self._photo = photo


class DetailSurface(Surface):
    """Paint the offset frame, single rounded corner and centered heading."""
    def __init__(self, parent, scale, title):
        super().__init__(parent, scale, bg=TRANSPARENT)
        self.title = title
        self.header = 82
        self.footer = FOOTER_HEIGHT

    def paint(self, p):
        w, h = p.width, p.height
        bottom, foot = h-FRAME, h-FRAME-self.footer
        p.line((1, FRAME, w-FRAME, FRAME, w-FRAME, h-1, 1, h-1, 1, FRAME), "#adb0b0")
        radius = min(32, self.header/2)
        p.box((FRAME, 0, w, bottom), PAPER, radius)
        p.box((FRAME, 0, w-radius, bottom), PAPER)
        p.box((FRAME, radius, w, bottom), PAPER)
        p.box((FRAME, foot, w, bottom), FOOTER)
        with p.clip((FRAME, foot, w, bottom)):
            cx = (w+FRAME)/2
            for radius in range(70, 125, 10):
                p.ellipse((cx-radius, foot-radius*1.45, cx+radius, foot+radius*.55),
                          outline="#39382e", width=1)
            p.ellipse((cx-62, foot-82, cx+62, foot+36), fill="#3f3c2d")
        center = (w+FRAME)/2
        title_width = theme.bitmap_font(26*p.factor).getlength(self.title)/p.factor
        title_size = min(26, 26*(w-86)/max(1,title_width))
        p.text((center, self.header*.53), self.title, title_size, "#101010", "mm")
        y = self.header*.84
        p.line((43, y, center-18, y), "#b4b8b9", 1.2)
        p.line((center+18, y, w-35, y), "#b4b8b9", 1.2)
        for x, radius in ((43, 1.6), (center-18, 1.5), (center-11, 2.2),
                          (center+11, 2.2), (center+18, 1.5), (w-35, 1.6)):
            p.ellipse((x-radius, y-radius, x+radius, y+radius), fill="#b4b8b9")
        p.ellipse((center-3, y-3, center+3, y+3), outline="#b4b8b9", width=1.2)


def arrange_details(dialog, owner, text, close, title, content, scale):
    """Keep native text/keyboard controls inside a game-shaped, nonmodal plate."""
    d = lambda value: round(value*scale)
    dialog._hsr_scale = scale
    dialog.overrideredirect(True)
    dialog.configure(background=TRANSPARENT)
    if sys.platform == "win32":
        dialog.wm_attributes("-transparentcolor", TRANSPARENT)
    surface = dialog.detail_surface = DetailSurface(dialog, scale, title)
    surface.place(x=0, y=0, relwidth=1, relheight=1)
    dialog.tk.call("lower", str(surface))
    dialog.columnconfigure(0, weight=1)
    dialog.rowconfigure(1, weight=1)
    text.configure(font=theme.native_font(dialog, 15), background=PAPER,
                   padx=0, pady=0, highlightthickness=0, spacing1=d(2), spacing3=d(2))
    text.frame.configure(background=PAPER)
    # Retain the real scrollbar for long reports; short notices have no empty rail.
    text.vbar.configure(background=PAPER, troughcolor=PAPER, relief="flat",
                        borderwidth=0, highlightthickness=0)
    text.grid(row=1, column=0, sticky="nsew", padx=(d(43), d(35)), pady=(d(8), d(12)))
    face = tkfont.Font(font=text.cget("font"), root=dialog)
    line_height = face.metrics("linespace")+d(4)
    rows = sum(max(1, (face.measure(line)+d(690)-1)//d(690)) for line in str(content).split("\n"))
    short = rows <= 5 and len(content) <= 240 and not content.lstrip().startswith(("{", "["))
    if short:
        text.tag_configure("notice", justify="center")
        text.tag_add("notice", "1.0", "end")
    def layout(event):
        if event.widget is not dialog:
            return
        height = event.height
        header = min(d(82), round(height*.28))
        footer = min(d(FOOTER_HEIGHT), round(height*.30))
        surface.header, surface.footer = header/scale, footer/scale
        surface.redraw()
        dialog.rowconfigure(0, minsize=header)
        dialog.rowconfigure(2, minsize=footer+d(FRAME))
        close.place(relx=.5, x=d(FRAME/2), y=height-d(FRAME)-footer//2,
                    anchor="center", width=min(d(288), event.width-d(86)),
                    height=min(d(46.4), footer-d(8)))
        body = max(1, height-header-footer-d(20+FRAME))
        visible_rows = sum(max(1, (face.measure(line)+max(1,event.width-d(100))-1)
                               //max(1,event.width-d(100))) for line in str(content).split("\n"))
        needed = visible_rows*line_height
        if needed > body:
            text.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        else:
            text.vbar.pack_forget()
        text.configure(pady=max(0, (body-needed)//2) if short else 0)

    dialog.bind("<Configure>", layout, add="+")
    height = max(d(NOTICE_SIZE[1]), min(d(560), d(82+FOOTER_HEIGHT+20+FRAME)+rows*line_height))
    place_dialog(dialog, owner, (d(NOTICE_SIZE[0]), height), (d(400), d(220)), padding=d(12))
    # The first Configure can occur while withdrawn and before the text is mapped.
    event = tk.Event()
    event.widget, event.width, event.height = dialog, dialog.winfo_width(), dialog.winfo_height()
    layout(event)


def _work_area(owner):
    if sys.platform == "win32":
        class MonitorInfo(ctypes.Structure):
            _fields_ = (("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD))
        user32 = ctypes.windll.user32
        nearest = user32.MonitorFromWindow
        nearest.argtypes, nearest.restype = (wintypes.HWND, wintypes.DWORD), wintypes.HANDLE
        info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        read = user32.GetMonitorInfoW
        read.argtypes, read.restype = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo)), wintypes.BOOL
        if read(nearest(owner.winfo_id(), 2), ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    # A missing monitor API must not send a secondary-window dialog to (0, 0).
    x, y = owner.winfo_rootx(), owner.winfo_rooty()
    return x, y, x+owner.winfo_width(), y+owner.winfo_height()


def place_dialog(dialog, owner, size, minimum, *, padding=12):
    """Measure the native frame while hidden, then position the visible content."""
    dialog.geometry(f"{size[0]}x{size[1]}")
    dialog.update_idletasks()
    side = max(0, dialog.winfo_rootx()-dialog.winfo_x())
    top = max(0, dialog.winfo_rooty()-dialog.winfo_y())
    left, upper, right, bottom = _work_area(owner)
    width = max(1, min(size[0], right-left-2*padding-2*side))
    height = max(1, min(size[1], bottom-upper-2*padding-top-side))
    dialog.minsize(min(minimum[0], width), min(minimum[1], height))
    x = owner.winfo_rootx()+(owner.winfo_width()-width)//2-side
    y = owner.winfo_rooty()+(owner.winfo_height()-height)//2-top
    x = max(left+padding, min(x, right-padding-width-2*side))
    y = max(upper+padding, min(y, bottom-padding-height-top-side))
    # "+-x" is Tk's absolute negative coordinate, unlike "-x" from the right.
    dialog.geometry(f"{width}x{height}+{x}+{y}")
