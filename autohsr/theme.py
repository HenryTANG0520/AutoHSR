"""Star Rail guide palette and DPI-aware native controls; no game artwork."""
from __future__ import annotations

from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

BG = "#151e2b"
RAIL = "#1c2736"
PANEL = "#e9e7e2"
CARD = "#f6f4ef"
FIELD = "#fffdf8"
TEXT = "#30343c"
MUTED = "#6c7078"
GOLD = "#a5834f"
LINE = "#ccc8bf"
LIGHT = "#ece8de"
SUCCESS = "#447c68"
WARNING = "#8c602b"
ERROR = "#ab4f4f"
FONT = "Microsoft YaHei UI"


def wrapped_label(parent, **kwargs):
    """Wrap to the actual column, including after DPI or window-size changes."""
    kwargs.setdefault("width", 1)
    label = ttk.Label(parent, **kwargs)
    label.bind("<Configure>", lambda event: label.configure(wraplength=max(1, event.width - 2)))
    return label


def _button(root, style, scale, name, fill, ink, *, rounded=False, background=PANEL):
    photos = []
    for state in ("normal", "active", "pressed", "disabled"):
        image = Image.new("RGB", (160, 88), background)
        draw = ImageDraw.Draw(image)
        color = "#d5d2cb" if state == "disabled" else fill
        edge = GOLD if state in ("active", "pressed") else RAIL if name == "Nav.TButton" else LINE
        draw.rounded_rectangle((2, 2, 157, 85), radius=40 if rounded else 4,
                               fill=color, outline=edge, width=2)
        if state == "pressed":
            draw.rounded_rectangle((7, 7, 152, 80), radius=36 if rounded else 2, outline=GOLD, width=2)
        photos.append(ImageTk.PhotoImage(image.resize((round(80*scale), round(44*scale)), Image.Resampling.LANCZOS), master=root))
    root._hsr_images.extend(photos)
    element = name + ".border"
    style.element_create(element, "image", photos[0], ("disabled", photos[3]),
                         ("pressed", photos[2]), ("active", photos[1]), ("focus", photos[1]),
                         border=(round((22 if rounded else 4)*scale), round(scale), round((22 if rounded else 4)*scale), round(scale)), sticky="nsew")
    style.layout(name, [(element, {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
    style.configure(name, foreground=ink, background=fill, padding=(round(12*scale), round(8*scale)),
                    font=(FONT, 10), anchor="center", borderwidth=0, width=0)
    style.map(name, foreground=[("disabled", "#92918c"), ("!disabled", ink)],
              background=[("disabled", "#d5d2cb"), ("!disabled", fill)])


def apply_theme(root, scale):
    d = lambda n: round(n*scale)
    style = ttk.Style(root)
    style.theme_use("clam")
    root._hsr_images = []
    style.configure(".", background=PANEL, foreground=TEXT, font=(FONT, 10))
    for name, color in (("TFrame", PANEL), ("Panel.TFrame", CARD), ("Card.TFrame", CARD),
                        ("Rail.TFrame", RAIL), ("Footer.TFrame", BG)):
        style.configure(name, background=color)
    for name, color, ink in (("TLabel", CARD, TEXT), ("Card.TLabel", CARD, TEXT),
                             ("Muted.TLabel", CARD, MUTED), ("CardHint.TLabel", CARD, MUTED),
                             ("Hint.TLabel", PANEL, MUTED), ("Footer.TLabel", BG, "#aeb8c7"),
                             ("FooterStatus.TLabel", BG, LIGHT), ("Rail.TLabel", RAIL, "#aeb8c7"),
                             ("Warning.TLabel", CARD, WARNING)):
        style.configure(name, background=color, foreground=ink, font=(FONT, 9))
    for name in ("Section.TLabel", "CardTitle.TLabel"):
        style.configure(name, background=CARD, foreground=TEXT, font=(FONT, 12, "bold"))
    style.configure("PageTitle.TLabel", background=PANEL, foreground=TEXT, font=(FONT, 21, "bold"))
    style.configure("Kicker.TLabel", background=PANEL, foreground=GOLD, font=("Segoe UI", 9))
    for name in ("TCheckbutton", "Card.TCheckbutton"):
        style.configure(name, background=CARD, foreground=TEXT, font=(FONT, 10), padding=(0, d(4)))
        style.map(name, background=[("active", CARD)], foreground=[("disabled", "#92918c")],
                  indicatorbackground=[("selected", GOLD), ("disabled", "#d5d2cb"), ("!selected", FIELD)])
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=FIELD, background=CARD, foreground=TEXT, insertcolor=TEXT,
                        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, arrowcolor=TEXT,
                        padding=d(5), borderwidth=1, font=(FONT, 10), selectbackground="#d9c9ac", selectforeground=TEXT)
        style.map(name, fieldbackground=[("disabled", "#e2dfd9"), ("readonly", FIELD)],
                  foreground=[("disabled", "#92918c"), ("readonly", TEXT)], bordercolor=[("focus", GOLD)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", "#d9c9ac")
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    for name, fill, ink, rounded, back in (
        ("TButton", CARD, TEXT, True, PANEL), ("Accent.TButton", LIGHT, TEXT, True, BG),
        ("Primary.TButton", LIGHT, TEXT, True, BG), ("Footer.TButton", RAIL, LIGHT, True, BG),
        ("Danger.TButton", RAIL, "#efb3a9", True, BG),
        ("Nav.TButton", RAIL, "#b9c0cb", False, RAIL),
        ("Selected.Nav.TButton", LIGHT, TEXT, False, RAIL)):
        _button(root, style, scale, name, fill, ink, rounded=rounded, background=back)
    style.configure("Nav.TButton", anchor="w", padding=(d(15), d(13)))
    style.configure("Selected.Nav.TButton", anchor="w", padding=(d(15), d(13)))
    style.configure("Compact.TButton", padding=(d(9), d(4)))
    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=d(33), borderwidth=0)
    style.configure("Treeview.Heading", background="#dedbd4", foreground=MUTED, padding=d(6))
    style.map("Treeview", background=[("selected", "#d9c9ac")], foreground=[("selected", TEXT)])
    style.configure("TNotebook", background=PANEL, borderwidth=0, tabmargins=0)
    style.configure("TNotebook.Tab", background="#dcd9d2", foreground=MUTED, padding=(d(17), d(8)), font=(FONT, 10))
    style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", TEXT)])
    style.configure("Horizontal.TScale", background=CARD, troughcolor="#d3cfc5", sliderlength=d(18))
    style.configure("Vertical.TScrollbar", background="#c1b9ab", troughcolor=PANEL, borderwidth=0, arrowcolor=MUTED)
    return style
