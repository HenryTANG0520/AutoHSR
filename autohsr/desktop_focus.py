"""Deliver an input correction to the visible field, including after a rebuild."""
from __future__ import annotations

from .theme import focus_widget


class InputFocus:
    def __init__(self, ui):
        self.ui, self.root = ui, ui.root
        self.pending = self.job = self.mapping = None
        self.root.bind("<Destroy>", self._destroy, add="+")

    def _destroy(self, event):
        if event.widget is self.root:
            self.cancel()

    def cancel(self):
        self.pending = None
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None
        self._unbind()

    def _unbind(self):
        if self.mapping is not None:
            widget, binding = self.mapping
            self.mapping = None
            if widget.winfo_exists():
                widget.unbind("<Map>", binding)

    def request(self, field, page, section, control):
        self.cancel()
        # Logical names survive replacement of the widgets during scaling.
        self.pending = field, page, section, control
        self.queue()

    def queue(self):
        if self.pending is not None and self.job is None:
            self.job = self.root.after_idle(self._apply)

    def owns_current_page(self):
        if self.pending is None:
            return False
        field, page, section, _ = self.pending
        ui = self.ui
        return (not ui.closing and not ui.busy and ui.input_error_field == field
                and ui.active_page == page and (not section or
                    ui.settings_tabs.select() == str(ui.settings_sections[section])))

    def cancel_if_obsolete(self):
        if (not getattr(getattr(self.ui, "responsive_layout", None), "resizing", False)
                and not self.owns_current_page()):
            self.cancel()

    def _apply(self):
        self.job = None
        ui = self.ui
        # The replacement restores cursor/selection after draining idle events.
        # Apply once that transaction finishes, using its current widgets.
        if getattr(getattr(ui, "responsive_layout", None), "resizing", False):
            return
        if not self.owns_current_page():
            self.cancel()
            return
        current = focus_widget(self.root)
        if self.root.tk.call("grab", "current") or (current is not None and current.winfo_toplevel() is not self.root):
            self.cancel()
            return
        widget = getattr(ui, self.pending[3])
        if widget.instate(("disabled",)):
            self.cancel()
            return
        if not widget.winfo_ismapped():
            if self.mapping is None or self.mapping[0] is not widget:
                self._unbind()
                self.mapping = widget, widget.bind("<Map>", lambda _: self.queue(), add="+")
            return
        self.cancel()
        widget.focus_set()
        if hasattr(widget, "selection_range"):
            widget.selection_range(0, "end")
