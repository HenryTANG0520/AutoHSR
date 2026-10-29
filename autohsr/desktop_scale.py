"""Fit the game layout to a larger window without replacing application state."""
from __future__ import annotations

from copy import deepcopy
import tkinter as tk
from tkinter import ttk

from .theme import focus_widget


def _contains_widget(value):
    if isinstance(value, tk.Widget):
        return True
    if isinstance(value, dict):
        return any(_contains_widget(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_widget(item) for item in value)
    return False


def _view_fields(ui):
    """Keep presentation references separate from the live runner and model."""
    names = {"ui_scale", "style", "position_guide", "refresh_feedback",
             "dungeon_search", "dungeon_target_caption"}
    return {key: value for key, value in vars(ui).items()
            if key in names or _contains_widget(value)}


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
        self.view_size = self.root.winfo_width(), self.root.winfo_height()
        self.cached_view = None
        self.window_state = self.root.state()
        self.root.bind("<Configure>", self._changed, add="+")
        self.root.bind("<Destroy>", self._destroyed, add="+")

    def _destroyed(self, event):
        if event.widget is self.root:
            if self.pending is not None:
                self.root.after_cancel(self.pending)
                self.pending = None
            self.cached_view = None

    def _changed(self, event):
        if event.widget is not self.root or self.resizing:
            return
        size = event.width, event.height
        if size == self.size:
            return
        self.size = size
        scale = max(self.base_scale, round(min(size[0]/1536, size[1]/864), 2))
        if abs(scale-self.ui.ui_scale) < .009 and self.root.state() not in ("iconic", "withdrawn"):
            self.view_size = size
        if self.pending is not None:
            self.root.after_cancel(self.pending)
        # Maximize/restore already supplies a settled size; only dragging needs
        # the debounce delay.
        state = self.root.state()
        changed_state = state != self.window_state
        self.window_state = state
        self.pending = self.root.after(0 if changed_state else 180, self.fit)

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
            self.view_size = width, height
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
            # Freeze the previous surfaces before draining idle painting, so
            # they do not redraw at a size we are already replacing.
            self._rebuild(scale)
            self.view_size = width, height
        finally:
            self.resizing = False
        return True

    def _view(self):
        return dict(key=(self.ui.ui_scale, *self.view_size), fields=_view_fields(self.ui),
                    images=self.root._hsr_images, theme=self.ui.style.theme_use(),
                    styles={widget: str(widget.cget("style")) for _, widget in _widgets(self.ui.shell)
                            if isinstance(widget, ttk.Widget)})

    def _restore_view(self, view):
        ui, root = self.ui, self.root
        if getattr(ui, "_guide_position_binding", None):
            root.unbind("<Configure>", ui._guide_position_binding)
        for key, value in view["fields"].items():
            setattr(ui, key, value)
        root.tk.call("tk", "scaling", ui.ui_scale*96/72)
        root._hsr_images = view["images"]
        root._hsr_theme_name = view["theme"]
        root._hsr_scale = ui.ui_scale
        ui.style.theme_use(view["theme"])
        from .theme import native_font
        for name in ("TEntry", "TSpinbox", "TCombobox"):
            root.option_add("*"+name+".font", native_font(root, 11))
        root.option_add("*TCombobox*Listbox.font", native_font(root, 11))
        for widget, style in view["styles"].items():
            widget.configure(style=style)
        ui._guide_position_binding = root.bind("<Configure>", ui.position_guide, add="+")
        ui.shell.place(x=0, y=0, relwidth=1, relheight=1)

    def _retire_view(self, view):
        view["fields"]["shell"].place_forget()
        self.cached_view = view

    def _rebuild(self, scale):
        ui, root = self.ui, self.root
        old_view = self._view()
        key = scale, root.winfo_width(), root.winfo_height()
        cached = self.cached_view if self.cached_view and self.cached_view["key"] == key else None
        if self.cached_view and cached is None:
            self.cached_view["fields"]["shell"].destroy()
            self.cached_view["images"].clear()
        self.cached_view = None
        old_shell = ui.shell
        previous = dict(_widgets(old_shell))
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
        states, edits, texts, notebooks, options = {}, {}, {}, {}, {}
        for path, widget in previous.items():
            if isinstance(widget, ttk.Widget):
                states[path] = tuple(s for s in widget.state() if s not in ("focus", "active", "pressed", "hover"))
            for kind, names in ((ttk.Combobox, ("values",)),
                                (ttk.Spinbox, ("from", "to", "increment", "values")),
                                (ttk.Scale, ("from", "to", "value"))):
                if isinstance(widget, kind):
                    options[path] = {name: widget.cget(name) for name in names}
            if isinstance(widget, ttk.Entry):
                selection = (widget.index("sel.first"), widget.index("sel.last")) if widget.selection_present() else None
                edits[path] = widget.index("insert"), selection, widget.xview()[0]
            if isinstance(widget, tk.Text):
                texts[path] = (widget.get("1.0", "end-1c"), widget.yview()[0],
                    {tag: tuple(str(i) for i in widget.tag_ranges(tag)) for tag in widget.tag_names()})
            if isinstance(widget, ttk.Notebook) and widget.select():
                notebooks[path] = widget.index(widget.select())

        from .theme import preserve_widget_theme
        preserve_widget_theme(root, ui.style, previous.values(), scale)
        loading = ui._loading
        ui._loading = True
        # The retained layout owns its original theme bitmaps while hidden.
        try:
            # Worker, queue, variables, records on disk and timers retain identity.
            # Stage new display objects below the complete previous shell.
            from .game_widgets import Surface, SceneButton
            for widget in previous.values():
                if isinstance(widget, (Surface, SceneButton)):
                    widget._suspended = True
                    if widget._paint_job is not None:
                        widget.after_cancel(widget._paint_job)
                        widget._paint_job = None
            root.tk.call("tk", "scaling", scale*96/72)
            if cached:
                self._restore_view(cached)
            else:
                ui.setting_controls = []
                ui.stamina_controls = []
                ui._build(scale=scale)
            root.tk.call("raise", str(old_shell))
            current = dict(_widgets(ui.shell))
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
            if (ui.table.records, ui.table.offset, ui.table.selected) != cards:
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
            for path, values in options.items():
                # Copy the latest choices/ranges without invoking value callbacks
                # or normalizing an incomplete draft during a layout change.
                current[path].configure(**values)
            if cached:
                root.update_idletasks()
                for widget in current.values():
                    if isinstance(widget, (Surface, SceneButton)):
                        widget._suspended = False
                        if (not isinstance(widget, Surface) or widget._content_dirty or
                                widget._rendered_geometry != widget._geometry_key()):
                            widget.redraw(layout=True)
            root.update_idletasks()
            for path, (_, yview, _) in texts.items():
                current[path].yview_moveto(yview)
            for path, (cursor, selection, xview) in edits.items():
                widget = current[path]
                widget.icursor(cursor)
                widget.selection_clear()
                if selection:
                    widget.selection_range(*selection)
                widget.xview_moveto(xview)
            if focus in current and current[focus].winfo_ismapped():
                current[focus].focus_set()
        except Exception:
            # A failed replacement must not take away the previous controls.
            if ui.shell is not old_shell:
                ui.shell.destroy()
            if root._hsr_images is not old_view["images"]:
                root._hsr_images.clear()
            self._restore_view(old_view)
            for key, value in navigation.items():
                if value is not None:
                    setattr(ui, key, value)
            ui._show_page(navigation["active_page"])
            for widget in previous.values():
                if isinstance(widget, (Surface, SceneButton)):
                    widget._suspended = False
                    widget.redraw()
            raise
        else:
            self._retire_view(old_view)
        finally:
            ui._loading = loading
