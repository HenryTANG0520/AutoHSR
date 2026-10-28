"""Fit the game layout to a larger window without replacing application state."""
from __future__ import annotations

from copy import deepcopy
import tkinter as tk
from tkinter import ttk

from .theme import focus_widget


def _widgets(parent, path=()):
    """Stable construction paths, independent of Tk's increasing widget names."""
    # A posted ttk combobox adds Tcl-only children with no Python wrapper.
    children = [child for child in parent.children.values() if not isinstance(child, tk.Toplevel)]
    for index, child in enumerate(children):
        key = (*path, index)
        yield key, child
        yield from _widgets(child, key)


class ResponsiveLayout:
    def __init__(self, ui):
        self.ui, self.root = ui, ui.root
        self.base_scale = ui.ui_scale
        self.pending = None
        self.resizing = False
        self.size = None
        self.root.bind("<Configure>", self._changed, add="+")
        self.root.bind("<Destroy>", self._destroyed, add="+")

    def _destroyed(self, event):
        if event.widget is self.root and self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None

    def _changed(self, event):
        if event.widget is not self.root or self.resizing:
            return
        size = event.width, event.height
        if size == self.size:
            return
        self.size = size
        if self.pending is not None:
            self.root.after_cancel(self.pending)
        self.pending = self.root.after(180, self.fit)

    def fit(self):
        """Commit one settled resize; native dialogs and dropdowns keep ownership."""
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None
        if self.resizing or self.ui.closing or self.root.state() in ("iconic", "withdrawn"):
            return False
        width, height = self.root.winfo_width(), self.root.winfo_height()
        scale = max(self.base_scale, round(min(width/1536, height/864), 2))
        if abs(scale-self.ui.ui_scale) < .009:
            return False
        # Do not discard an open menu, pending file choice or unsaved-change dialog.
        if (self.root.tk.call("grab", "current") or
                any(isinstance(w, tk.Toplevel) and w.winfo_ismapped() and not w.overrideredirect()
                    for w in self.root.winfo_children()) or
                any(isinstance(w, ttk.Widget) and w.instate(("pressed",)) for _, w in _widgets(self.root))):
            self.pending = self.root.after(250, self.fit)
            return False
        self.resizing = True
        try:
            self._rebuild(scale)
        finally:
            self.resizing = False
        return True

    def _rebuild(self, scale):
        ui, root = self.ui, self.root
        previous = dict(_widgets(root))
        paths = {widget: path for path, widget in previous.items()}
        focus = paths.get(focus_widget(root))
        return_focus = paths.get(getattr(ui, "settings_return_focus", None))
        navigation = {key: getattr(ui, key, None) for key in
            ("active_page", "action_page", "last_universe_page", "settings_return_page")}
        mode_views = {key: deck["shown"] for key, deck in ui.mode_decks.items()}
        cards = deepcopy(ui.table.records), ui.table.offset, ui.table.selected
        browser = (ui.dungeon_search.get(), ui.dungeon_target_caption.get(),
                   ui.dungeon_manual_visible, ui.dungeon_advanced_visible,
                   ui.dungeon_list.offset, ui.dungeon_list.cursor, ui.dungeon_list._follow_cursor)
        save_visible = bool(ui.save_label.winfo_manager())
        states, edits, texts, notebooks = {}, {}, {}, {}
        for path, widget in previous.items():
            if isinstance(widget, ttk.Widget):
                states[path] = tuple(s for s in widget.state() if s not in ("focus", "active", "pressed", "hover"))
            if isinstance(widget, ttk.Entry):
                selection = (widget.index("sel.first"), widget.index("sel.last")) if widget.selection_present() else None
                edits[path] = widget.index("insert"), selection, widget.xview()[0]
            if isinstance(widget, tk.Text):
                texts[path] = (widget.get("1.0", "end-1c"), widget.yview()[0],
                    {tag: tuple(str(i) for i in widget.tag_ranges(tag)) for tag in widget.tag_names()})
            if isinstance(widget, ttk.Notebook) and widget.select():
                notebooks[path] = widget.index(widget.select())

        loading = ui._loading
        ui._loading = True
        try:
            # Worker, queue, variables, records on disk and timers retain identity.
            # Only display objects are replaced, synchronously on the Tk thread.
            for child in list(root.winfo_children()):
                if not isinstance(child, tk.Toplevel):
                    child.destroy()
            ui.setting_controls = []
            ui.stamina_controls = []
            root.tk.call("tk", "scaling", scale*96/72)
            ui._build(scale=scale)
            current = dict(_widgets(root))
            ui.dungeon_search.set(browser[0])
            ui.dungeon_target_caption.set(browser[1])
            from .dungeon_ui import _show_editor
            ui.dungeon_manual_visible, ui.dungeon_advanced_visible = browser[2:4]
            _show_editor(ui)
            ui.dungeon_list.offset, ui.dungeon_list.cursor, ui.dungeon_list._follow_cursor = browser[4:]
            from .desktop_modes import show_mode_view
            for key, view in mode_views.items():
                show_mode_view(ui, key, view)
            for key, value in navigation.items():
                if value is not None:
                    setattr(ui, key, value)
            ui._show_page(navigation["active_page"])
            ui.settings_return_focus = current.get(return_focus)
            ui.table.records, ui.table.offset, ui.table.selected = cards
            ui.table.redraw()
            ui.recovery_hint.set(ui.recovery_hint.get())
            if save_visible and not ui.busy:
                ui._show_save_feedback()
            for path, index in notebooks.items():
                current[path].select(index)
            for path, (value, _, tags) in texts.items():
                widget = current[path]
                ui._replace_text(widget, value)
                for tag, ranges in tags.items():
                    for start, end in zip(ranges[::2], ranges[1::2]):
                        widget.tag_add(tag, start, end)
            for path, state in states.items():
                widget = current[path]
                widget.state(tuple("!"+s for s in widget.state())+state)
            root.update_idletasks()
            for path, (_, yview, _) in texts.items():
                current[path].yview_moveto(yview)
            for path, (cursor, selection, xview) in edits.items():
                widget = current[path]
                widget.icursor(cursor)
                if selection:
                    widget.selection_range(*selection)
                widget.xview_moveto(xview)
            if focus in current and current[focus].winfo_ismapped():
                current[focus].focus_set()
            ui.position_guide()
        finally:
            ui._loading = loading
