"""Reference-matched Star Rail guide materials, private font and native controls."""
from __future__ import annotations

from functools import lru_cache
from contextlib import contextmanager
import ctypes
import sys
from tkinter import font as tkfont, ttk
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk

from .config import RESOURCE_ROOT

BG = "#161621"
RAIL = "#242323"
PANEL = "#e1e1e1"
CARD = "#f4f4f4"
FIELD = "#ebebeb"
SETTING_ROW = "#c5c6c8"
SETTING_VALUE = "#d6d7d9"
TEXT = "#242424"
MUTED = "#757575"
GOLD = "#bca775"
LINE = "#cecece"
LIGHT = "#e1e1e4"
ORANGE = "#f49c2d"
SUCCESS = "#48765c"
WARNING = "#8c602b"
ERROR = "#ab4f4f"
FONT = "Microsoft YaHei UI"
UI_ASSETS = RESOURCE_ROOT/"assets"/"ui"
_registered = False


def load_font(root):
    global FONT, _registered
    if sys.platform == "win32" and not _registered:
        ctypes.windll.gdi32.AddFontResourceExW(str(UI_ASSETS/"hsr-sc.ttf"), 0x10, 0)
        _registered = True
    FONT = next((name for name in tkfont.families(root) if name == "SDK_SC_Web"), "Microsoft YaHei UI")


def native_font(widget, points):
    """An explicit pixel size avoids Tk reusing a previous scale's point font."""
    root = widget.winfo_toplevel()
    scale = getattr(root, "_hsr_scale", float(root.tk.call("tk", "scaling"))/(96/72))
    return FONT, -max(1, round(points*scale*96/72))


@lru_cache(maxsize=96)
def bitmap_font(size):
    return ImageFont.truetype(str(UI_ASSETS/"hsr-sc.ttf"), max(1, round(size)))


@lru_cache(maxsize=32)
def asset(name):
    with Image.open(UI_ASSETS/name) as im:
        return im.convert("RGBA")


@lru_cache(maxsize=1)
def scene_image(width, height):
    """Share one window-sized scene across adjacent surfaces without seams."""
    return ImageOps.fit(asset("guide/backdrop.png"), (width, height), Image.Resampling.LANCZOS)


class Painter:
    def __init__(self, width, height, scale, background=PANEL):
        self.factor = scale*2
        self.width, self.height = width/scale, height/scale
        self.origin = (0, 0)
        self.image = Image.new("RGBA", (width*2, height*2), background or (0,0,0,0))
        self.draw = ImageDraw.Draw(self.image)

    def coords(self, values):
        return tuple(round((v+self.origin[index % 2])*self.factor) for index,v in enumerate(values))

    @contextmanager
    def clip(self, rect, radius=0):
        base = self.image
        self.image = Image.new("RGBA", base.size)
        self.draw = ImageDraw.Draw(self.image)
        try:
            yield
        finally:
            bounds = self.coords(rect)
            layer = self.image.crop(bounds)
            mask = Image.new("L", layer.size)
            ImageDraw.Draw(mask).rounded_rectangle((0,0,layer.width-1,layer.height-1), radius=round(radius*self.factor), fill=255)
            from PIL import ImageChops
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
            base.alpha_composite(layer, bounds[:2])
            self.image, self.draw = base, ImageDraw.Draw(base)

    def box(self, rect, fill, radius=0, outline=None, width=1):
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            return
        self.draw.rounded_rectangle(self.coords(rect), radius=round(radius*self.factor), fill=fill,
                                    outline=outline, width=max(1, round(width*self.factor)))

    def ellipse(self, rect, fill=None, outline=None, width=1):
        self.draw.ellipse(self.coords(rect), fill=fill, outline=outline, width=max(1, round(width*self.factor)))

    def line(self, points, fill=LINE, width=1):
        self.draw.line(self.coords(points), fill=fill, width=max(1, round(width*self.factor)))

    def poly(self, points, fill=TEXT):
        self.draw.polygon(self.coords(points), fill=fill)

    def glow(self, center, radius, color, blur):
        layer = Image.new("RGBA", self.image.size)
        x, y = center
        ImageDraw.Draw(layer).ellipse(self.coords((x-radius,y-radius,x+radius,y+radius)), fill=color)
        self.image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur*self.factor)))

    def text(self, xy, text, size=16, fill=TEXT, anchor="lt"):
        if "\n" in str(text):
            for index, line in enumerate(str(text).splitlines()):
                self.text((xy[0],xy[1]+index*(size+5)), line, size, fill, anchor)
        else:
            self.draw.text(self.coords(xy), str(text), font=bitmap_font(size*self.factor), fill=fill, anchor=anchor)

    def wrap(self, text, width, size, lines=3):
        face = bitmap_font(size*self.factor)
        result, current = [], ""
        for char in str(text):
            if char == "\n" or (current and face.getlength(current+char)>width*self.factor):
                result.append(current)
                current = "" if char == "\n" else char
            else:
                current += char
        if current:
            result.append(current)
        if len(result)>lines:
            result = result[:lines]
            result[-1] = result[-1][:-1]+"…"
        return "\n".join(result)

    def asset(self, name, rect, tint=None):
        src = asset(name)
        if tint:
            painted = Image.new("RGBA", src.size, tint)
            painted.putalpha(src.getchannel("A"))
            src = painted
        x1,y1,x2,y2 = self.coords(rect)
        if x2>x1 and y2>y1:
            src = src.resize((x2-x1,y2-y1), Image.Resampling.LANCZOS)
            self.image.alpha_composite(src,(x1,y1))

    def finish(self):
        return self.image.resize((self.image.width//2,self.image.height//2), Image.Resampling.LANCZOS)


def wrapped_label(parent, **kwargs):
    kwargs.setdefault("width", 1)
    label = ttk.Label(parent, **kwargs)
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(1,e.width-2)))
    return label


def focus_widget(root):
    """Return the Python owner when focus is inside a Tcl-created popdown."""
    name = str(root.tk.call("focus"))
    while name:
        try:
            return root.nametowidget(name)
        except KeyError:
            name = name.rpartition(".")[0]
    return None


def _theme_image(root, image):
    # Stable names let an inactive theme release its pixels and recreate them
    # when revisited. Only the current scale's bitmap objects stay resident.
    photo = ImageTk.PhotoImage(image, master=root,
        name=f"{root._hsr_theme_name}_{len(root._hsr_images)}")
    root._hsr_images.append(photo)
    return photo


def _button(root, style, scale, name, fill, ink, *, tab=False, option=False, background=PANEL):
    photos = []
    for state in ("normal","active","pressed","disabled"):
        p = Painter(round(84*scale),round((58 if tab else 38)*scale),scale,background)
        color = "#d3d3d3" if state=="disabled" else fill
        if tab:
            p.box((0,0,84,64), color, 7, None if fill==PANEL else "#54514e", 1.2)
        elif option:
            p.box((0,0,84,38), color)
            p.box((0,0,4,38), GOLD if fill==RAIL else "#a9a9a9")
        else:
            p.box((1,1,83,37), color, 18, GOLD if state in ("active","pressed") else "#b4b4b4", 1.4)
            p.box((5,5,79,33), color, 14, "#d5d5d5" if fill!=RAIL else "#54504a", 1)
        photos.append(_theme_image(root, p.finish()))
    element = name+".border"
    if element not in style.element_names():
        style.element_create(element,"image",photos[0],("disabled",photos[3]),("pressed",photos[2]),
                             ("active",photos[1]),("focus",photos[1]),
                             border=(round((8 if tab or option else 19)*scale),round((8 if tab else 1)*scale),round((8 if tab or option else 19)*scale),round(scale)),sticky="nsew")
    style.layout(name,[(element,{"sticky":"nsew","children":[("Button.padding",{"sticky":"nsew","children":[("Button.label",{"sticky":"nsew"})]})]})])
    style.configure(name,foreground=ink,background=fill,padding=(round(10*scale),round(7*scale)),font=native_font(root, 11),width=0,anchor="center",borderwidth=0)
    style.map(name,foreground=[("disabled","#8b8b8b"),("!disabled",ink)],background=[("disabled","#d3d3d3"),("!disabled",fill)])


def _form_elements(root, style, scale):
    """Draw guide surfaces while retaining ttk editing and keyboard bindings."""
    d = lambda n: round(n*scale)

    def element(name, size, draw, states, *, border=0, sticky=""):
        photos = []
        for state in ((), *states):
            p = Painter(d(size[0]), d(size[1]), scale, None)
            draw(p, state)
            photos.append(_theme_image(root, p.finish()))
        if name not in style.element_names():
            style.element_create(name, "image", photos[0],
                *((*state, photo) for state, photo in zip(states, photos[1:])),
                border=d(border), padding=0, sticky=sticky)

    def check(p, state):
        disabled, selected = "disabled" in state, "selected" in state
        edge = "#bcbab5" if disabled else GOLD if "focus" in state or "active" in state else "#8e8980"
        p.box((2, 3, 22, 23), FIELD if disabled or not selected else RAIL, 1, edge, 1.2)
        if selected:
            p.line((6, 13, 10, 17, 18, 9), "#a7a49e" if disabled else "#f3e8cf", 2.4)
        elif "alternate" in state:
            p.line((7, 13, 17, 13), edge, 2)
        if "focus" in state and not disabled:
            p.box((0, 1, 24, 25), None, 2, GOLD)

    element("Guide.Checkbutton.indicator", (32, 26), check,
            (("disabled", "selected"), ("disabled",), ("focus", "selected"), ("focus",),
             ("active", "selected"), ("active",), ("selected",), ("alternate",)))
    layout = [("Checkbutton.padding", {"sticky": "nswe", "children": [
        ("Guide.Checkbutton.indicator", {"side": "left"}),
        ("Checkbutton.label", {"side": "left", "sticky": "nswe"})]})]
    for name in ("TCheckbutton", "Card.TCheckbutton"):
        style.layout(name, layout)

    def field(p, state):
        p.box((1, 1, 83, 35), PANEL if "disabled" in state else FIELD, 2,
              GOLD if "focus" in state else "#c2beb7", 1)
        if "focus" in state:
            p.line((7, 34, 77, 34), GOLD, 2)

    states = (("disabled",), ("focus",), ("active",))
    element("Guide.field", (84, 36), field, states, border=7, sticky="nsew")
    layouts = {}
    for widget in ("Entry", "Combobox", "Spinbox"):
        children = [(widget+".padding", {"sticky": "nswe", "children": [(widget+".textarea", {"sticky": "nswe"})]})]
        if widget == "Combobox":
            children.insert(0, ("Guide.Combobox.downarrow", {"side": "right", "sticky": "ns"}))
        if widget == "Spinbox":
            children.insert(0, ("null", {"side": "right", "children": [
                ("Guide.Spinbox.uparrow", {"side": "top"}),
                ("Guide.Spinbox.downarrow", {"side": "bottom"})]}))
        layouts["T"+widget] = [("Guide.field", {"sticky": "nswe", "children": children})]

    def arrow(up=False, compact=False):
        def draw(p, state):
            w, h = (24, 16) if compact else (30, 34)
            ink = "#aaa69e" if "disabled" in state else GOLD if "active" in state else TEXT
            cy, delta = h/2, -3 if up else 3
            p.line((w/2-4, cy-delta/2, w/2, cy+delta/2, w/2+4, cy-delta/2), ink, 1.8)
        return draw

    element("Guide.Combobox.downarrow", (30, 34), arrow(), states, sticky="")
    element("Guide.Spinbox.uparrow", (24, 16), arrow(True, True), states)
    element("Guide.Spinbox.downarrow", (24, 16), arrow(False, True), states)
    for name, layout in layouts.items():
        style.layout(name, layout)

    def setting_field(p, state):
        p.box((0, 0, 84, 58), SETTING_VALUE)
        if "focus" in state and "disabled" not in state:
            p.box((1, 1, 83, 57), None, 0, GOLD, 1.5)

    def setting_arrow(p, state):
        p.poly((10, 26, 20, 26, 15, 32), "#96979b" if "disabled" in state else "#44464b")

    element("Settings.field", (84, 58), setting_field, states, border=3, sticky="nsew")
    element("Settings.Combobox.downarrow", (30, 58), setting_arrow, states)
    for widget in ("Entry", "Combobox"):
        children = [(widget+".padding", {"sticky": "nswe", "children": [(widget+".textarea", {"sticky": "nswe"})]})]
        if widget == "Combobox":
            children.insert(0, ("Settings.Combobox.downarrow", {"side": "right", "sticky": "ns"}))
        style.layout("Settings.T"+widget, [("Settings.field", {"sticky": "nswe", "children": children})])
        style.configure("Settings.T"+widget, padding=(d(12), d(7)), fieldbackground=SETTING_VALUE,
                        background=SETTING_VALUE)
        style.map("Settings.T"+widget, fieldbackground=[("disabled", SETTING_VALUE), ("readonly", SETTING_VALUE)])

    def trough(p, state):
        p.box((0, 10, 96, 14), "#cecac3" if "disabled" in state else "#aaa59b", 2)
    def slider(p, state):
        p.ellipse((2, 2, 22, 22), "#d1cfca" if "disabled" in state else CARD,
                  GOLD if "focus" in state or "active" in state else "#8e8980", 1.5)
        p.ellipse((7, 7, 17, 17), "#b9b6af" if "disabled" in state else GOLD)
    element("Guide.Horizontal.Scale.trough", (96, 24), trough, states, border=4, sticky="ew")
    element("Guide.Horizontal.Scale.slider", (24, 24), slider, states)
    style.layout("Horizontal.TScale", [("Guide.Horizontal.Scale.trough", {"sticky": "nswe", "children": [
        ("Guide.Horizontal.Scale.slider", {"side": "left"})]})])


def apply_theme(root, scale):
    load_font(root)
    root._hsr_scale = scale
    d = lambda n: round(n*scale)
    style = ttk.Style(root)
    root._hsr_theme_name = f"AutoHSR{round(scale*1000)}"
    if root._hsr_theme_name not in style.theme_names():
        style.theme_create(root._hsr_theme_name, parent="clam")
    style.theme_use(root._hsr_theme_name)
    root._hsr_images=[]
    style.configure(".",font=native_font(root, 11),background=PANEL,foreground=TEXT)
    for name,color in (("TFrame",PANEL),("Card.TFrame",CARD),("Panel.TFrame",CARD),("Rail.TFrame",RAIL),("Footer.TFrame",BG)):
        style.configure(name,background=color)
    style.configure("Settings.Row.TFrame", background=SETTING_ROW)
    style.configure("Settings.Value.TFrame", background=SETTING_VALUE)
    style.configure("Settings.Line.TFrame", background="#a5a7ab")
    style.configure("Settings.TLabel", background=SETTING_ROW, foreground=TEXT, font=native_font(root, 12))
    style.configure("Settings.Hint.TLabel", background=SETTING_ROW, foreground="#5d6065", font=native_font(root, 9))
    style.configure("Settings.Note.TLabel", background=BG, foreground="#bdc0c9", font=native_font(root, 10))
    for name,color,ink in (("TLabel",CARD,TEXT),("Card.TLabel",CARD,TEXT),("Muted.TLabel",CARD,MUTED),
        ("CardHint.TLabel",CARD,MUTED),("Hint.TLabel",PANEL,MUTED),("Footer.TLabel",BG,"#b8b8bc"),
        ("FooterStatus.TLabel",BG,LIGHT),("Rail.TLabel",RAIL,LIGHT),("Warning.TLabel",CARD,WARNING)):
        style.configure(name,background=color,foreground=ink,font=native_font(root, 10))
    for name in ("Section.TLabel","CardTitle.TLabel"):
        style.configure(name,background=CARD,foreground=TEXT,font=native_font(root, 14))
    style.configure("PageTitle.TLabel",background=PANEL,foreground=TEXT,font=native_font(root, 17))
    for name in ("TCheckbutton","Card.TCheckbutton"):
        style.configure(name,background=CARD,foreground=TEXT,font=native_font(root, 11),padding=(0,d(4)))
        style.map(name,background=[("active",CARD)],foreground=[("disabled","#92918c")],indicatorbackground=[("selected",GOLD),("!selected",FIELD)])
    for name in ("TEntry","TSpinbox","TCombobox"):
        style.configure(name,fieldbackground=FIELD,background=FIELD,foreground=TEXT,insertcolor=TEXT,bordercolor=LINE,
                        lightcolor=LINE,darkcolor=LINE,arrowcolor=TEXT,padding=d(6),font=native_font(root, 11),borderwidth=0,
                        selectbackground="#d7cab0",selectforeground=TEXT)
        style.map(name,fieldbackground=[("disabled",PANEL),("readonly",FIELD)],foreground=[("disabled","#92918c"),("readonly",TEXT)],bordercolor=[("focus",GOLD)])
        root.option_add("*"+name+".font", native_font(root, 11))
    _form_elements(root, style, scale)
    root.option_add("*TCombobox*Listbox.font",native_font(root, 11))
    root.option_add("*TCombobox*Listbox.background",CARD)
    root.option_add("*TCombobox*Listbox.foreground",TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground","#d7cab0")
    root.option_add("*TCombobox*Listbox.selectForeground",TEXT)
    for name,fill,ink,tab,option,background in (
        ("TButton",CARD,TEXT,False,False,CARD),("Panel.TButton",CARD,TEXT,False,False,PANEL),
        ("Compact.TButton",CARD,TEXT,False,False,CARD),("Accent.TButton",CARD,TEXT,False,False,BG),
        ("Settings.TButton",CARD,TEXT,False,False,SETTING_VALUE),
        ("Poster.TButton",CARD,TEXT,False,False,PANEL),
        ("Primary.TButton",CARD,TEXT,False,False,BG),("Footer.TButton",CARD,TEXT,False,False,BG),
        ("Danger.TButton",CARD,"#9d4949",False,False,BG),("Nav.TButton",RAIL,"#b7b7b7",True,False,RAIL),
        ("Selected.Nav.TButton",PANEL,TEXT,True,False,RAIL),("Option.TButton",CARD,TEXT,False,True,PANEL),
        ("Selected.Option.TButton",RAIL,GOLD,False,True,PANEL)):
        _button(root,style,scale,name,fill,ink,tab=tab,option=option,background=background)
    style.configure("Nav.TButton",padding=(d(19),d(6)),font=native_font(root, 14))
    style.configure("Selected.Nav.TButton",padding=(d(24),d(6)),font=native_font(root, 14))
    style.configure("Option.TButton",anchor="w",padding=(d(22),d(17)),font=native_font(root, 13))
    style.configure("Selected.Option.TButton",anchor="w",padding=(d(22),d(17)),font=native_font(root, 13))
    style.configure("Compact.TButton",padding=(d(6),d(4)))
    style.configure("Settings.TButton",padding=(d(4),d(7)))
    style.configure("Treeview",background=CARD,fieldbackground=CARD,foreground=TEXT,rowheight=d(33),borderwidth=0,font=native_font(root, 10))
    style.configure("Treeview.Heading",background=PANEL,foreground=MUTED,padding=d(6),font=native_font(root, 10))
    style.map("Treeview",background=[("selected","#d7cab0")],foreground=[("selected",TEXT)])
    style.configure("TNotebook",background=PANEL,borderwidth=0,tabmargins=0)
    style.configure("TNotebook.Tab",background=PANEL,foreground=MUTED,padding=(d(16),d(8)),font=native_font(root, 11))
    style.map("TNotebook.Tab",background=[("selected",CARD)],foreground=[("selected",TEXT)])
    style.layout("Hidden.TNotebook.Tab", [])
    style.configure("Hidden.TNotebook", borderwidth=0, tabmargins=0)
    style.layout("Settings.TNotebook", [])
    style.layout("Settings.TNotebook.Tab", [])
    style.configure("Settings.TNotebook", background=BG, borderwidth=0, tabmargins=0)
    for name in ("Settings.Nav.TButton", "Settings.Selected.Nav.TButton", "Settings.Close.TButton"):
        style.layout(name, [("Button.padding", {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]})])
        style.configure(name, background=BG, foreground=LIGHT, padding=d(3), borderwidth=0, font=native_font(root, 10), anchor="center")
        style.map(name, foreground=[("focus", GOLD), ("active", GOLD), ("!disabled", LIGHT)], background=[("active", BG), ("!disabled", BG)])
    style.configure("Horizontal.TScale",background=CARD,troughcolor="#c1c1c1",sliderlength=d(18))
    style.configure("Vertical.TScrollbar",background="#b0b0b0",troughcolor=PANEL,borderwidth=0,arrowcolor=MUTED)
    return style
