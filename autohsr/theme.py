"""Reference-matched Star Rail guide materials, private font and native controls."""
from __future__ import annotations

from functools import lru_cache
from contextlib import contextmanager
import ctypes
import sys
from tkinter import font as tkfont, ttk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from .config import RESOURCE_ROOT

BG = "#161621"
RAIL = "#242323"
PANEL = "#e1e1e1"
CARD = "#f4f4f4"
FIELD = "#ebebeb"
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


@lru_cache(maxsize=96)
def bitmap_font(size):
    return ImageFont.truetype(str(UI_ASSETS/"hsr-sc.ttf"), max(1, round(size)))


@lru_cache(maxsize=32)
def asset(name):
    with Image.open(UI_ASSETS/name) as im:
        return im.convert("RGBA")


class Painter:
    def __init__(self, width, height, scale, background=PANEL):
        self.factor = scale*2
        self.width, self.height = width/scale, height/scale
        self.image = Image.new("RGBA", (width*2, height*2), background or (0,0,0,0))
        self.draw = ImageDraw.Draw(self.image)

    def coords(self, values):
        return tuple(round(v*self.factor) for v in values)

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


def _button(root, style, scale, name, fill, ink, *, tab=False, option=False, background=PANEL):
    photos = []
    for state in ("normal","active","pressed","disabled"):
        p = Painter(round(84*scale),round((58 if tab else 38)*scale),scale,background)
        color = "#d3d3d3" if state=="disabled" else fill
        if tab:
            p.box((0,0,84,64), color, 7)
        elif option:
            p.box((0,0,84,38), color)
            p.box((0,0,4,38), GOLD if fill==RAIL else "#a9a9a9")
        else:
            p.box((1,1,83,37), color, 18, GOLD if state in ("active","pressed") else "#b4b4b4", 1.4)
            p.box((5,5,79,33), color, 14, "#d5d5d5" if fill!=RAIL else "#54504a", 1)
        photos.append(ImageTk.PhotoImage(p.finish(),master=root))
    root._hsr_images.extend(photos)
    element = name+".border"
    style.element_create(element,"image",photos[0],("disabled",photos[3]),("pressed",photos[2]),
                         ("active",photos[1]),("focus",photos[1]),
                         border=(round((8 if tab or option else 19)*scale),round((8 if tab else 1)*scale),round((8 if tab or option else 19)*scale),round(scale)),sticky="nsew")
    style.layout(name,[(element,{"sticky":"nsew","children":[("Button.padding",{"sticky":"nsew","children":[("Button.label",{"sticky":"nsew"})]})]})])
    style.configure(name,foreground=ink,background=fill,padding=(round(10*scale),round(7*scale)),font=(FONT,11),width=0,anchor="center",borderwidth=0)
    style.map(name,foreground=[("disabled","#8b8b8b"),("!disabled",ink)],background=[("disabled","#d3d3d3"),("!disabled",fill)])


def apply_theme(root, scale):
    load_font(root)
    d = lambda n: round(n*scale)
    style = ttk.Style(root)
    style.theme_use("clam")
    root._hsr_images=[]
    style.configure(".",font=(FONT,11),background=PANEL,foreground=TEXT)
    for name,color in (("TFrame",PANEL),("Card.TFrame",CARD),("Panel.TFrame",CARD),("Rail.TFrame",RAIL),("Footer.TFrame",BG)):
        style.configure(name,background=color)
    for name,color,ink in (("TLabel",CARD,TEXT),("Card.TLabel",CARD,TEXT),("Muted.TLabel",CARD,MUTED),
        ("CardHint.TLabel",CARD,MUTED),("Hint.TLabel",PANEL,MUTED),("Footer.TLabel",BG,"#b8b8bc"),
        ("FooterStatus.TLabel",BG,LIGHT),("Rail.TLabel",RAIL,LIGHT),("Warning.TLabel",CARD,WARNING)):
        style.configure(name,background=color,foreground=ink,font=(FONT,10))
    for name in ("Section.TLabel","CardTitle.TLabel"):
        style.configure(name,background=CARD,foreground=TEXT,font=(FONT,14))
    style.configure("PageTitle.TLabel",background=PANEL,foreground=TEXT,font=(FONT,17))
    for name in ("TCheckbutton","Card.TCheckbutton"):
        style.configure(name,background=CARD,foreground=TEXT,font=(FONT,11),padding=(0,d(4)))
        style.map(name,background=[("active",CARD)],foreground=[("disabled","#92918c")],indicatorbackground=[("selected",GOLD),("!selected",FIELD)])
    for name in ("TEntry","TSpinbox","TCombobox"):
        style.configure(name,fieldbackground=FIELD,background=FIELD,foreground=TEXT,insertcolor=TEXT,bordercolor=LINE,
                        lightcolor=LINE,darkcolor=LINE,arrowcolor=TEXT,padding=d(6),font=(FONT,11),borderwidth=0,
                        selectbackground="#d7cab0",selectforeground=TEXT)
        style.map(name,fieldbackground=[("disabled",PANEL),("readonly",FIELD)],foreground=[("disabled","#92918c"),("readonly",TEXT)],bordercolor=[("focus",GOLD)])
    root.option_add("*TCombobox*Listbox.font",(FONT,11))
    root.option_add("*TCombobox*Listbox.background",CARD)
    root.option_add("*TCombobox*Listbox.foreground",TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground","#d7cab0")
    root.option_add("*TCombobox*Listbox.selectForeground",TEXT)
    for name,fill,ink,tab,option,background in (
        ("TButton",CARD,TEXT,False,False,PANEL),("Accent.TButton",CARD,TEXT,False,False,BG),
        ("Primary.TButton",CARD,TEXT,False,False,BG),("Footer.TButton",CARD,TEXT,False,False,BG),
        ("Danger.TButton",CARD,"#9d4949",False,False,BG),("Nav.TButton",RAIL,"#b7b7b7",True,False,RAIL),
        ("Selected.Nav.TButton",PANEL,TEXT,True,False,RAIL),("Option.TButton",CARD,TEXT,False,True,PANEL),
        ("Selected.Option.TButton",RAIL,GOLD,False,True,PANEL)):
        _button(root,style,scale,name,fill,ink,tab=tab,option=option,background=background)
    style.configure("Nav.TButton",padding=(d(22),d(7)))
    style.configure("Selected.Nav.TButton",padding=(d(22),d(7)))
    style.configure("Option.TButton",anchor="w",padding=(d(22),d(17)),font=(FONT,13))
    style.configure("Selected.Option.TButton",anchor="w",padding=(d(22),d(17)),font=(FONT,13))
    style.configure("Compact.TButton",padding=(d(6),d(4)))
    style.configure("Treeview",background=CARD,fieldbackground=CARD,foreground=TEXT,rowheight=d(33),borderwidth=0,font=(FONT,10))
    style.configure("Treeview.Heading",background=PANEL,foreground=MUTED,padding=d(6),font=(FONT,10))
    style.map("Treeview",background=[("selected","#d7cab0")],foreground=[("selected",TEXT)])
    style.configure("TNotebook",background=PANEL,borderwidth=0,tabmargins=0)
    style.configure("TNotebook.Tab",background=PANEL,foreground=MUTED,padding=(d(16),d(8)),font=(FONT,11))
    style.map("TNotebook.Tab",background=[("selected",CARD)],foreground=[("selected",TEXT)])
    style.layout("Hidden.TNotebook.Tab", [])
    style.configure("Hidden.TNotebook", borderwidth=0, tabmargins=0)
    style.configure("Horizontal.TScale",background=CARD,troughcolor="#c1c1c1",sliderlength=d(18))
    style.configure("Vertical.TScrollbar",background="#b0b0b0",troughcolor=PANEL,borderwidth=0,arrowcolor=MUTED)
    return style
