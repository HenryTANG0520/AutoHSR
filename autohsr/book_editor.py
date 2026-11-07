"""In-book editing for forms with a local Apply and Cancel step."""
from tkinter import ttk

from . import theme


class BookEditor(ttk.Frame):
    def __init__(self, ui, title, *, origin=None):
        d = lambda n: round(n * ui.ui_scale)
        super().__init__(ui.guide.content, style="Card.TFrame", padding=d(16))
        self.ui = ui
        self.origin = origin or theme.focus_widget(ui.root)
        self.source = ui.daily_view if ui.daily_section is not None else ui.pages[ui.active_page]
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.heading = ttk.Label(self, text=title, style="CardTitle.TLabel")
        self.heading.grid(row=0, column=0, sticky="w", pady=(0, d(8)))
        self.body = ttk.Frame(self, style="Card.TFrame")
        self.body.grid(row=1, column=0, sticky="nsew")
        actions = ttk.Frame(self, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="e", pady=(d(8), 0))
        self.cancel = ttk.Button(actions, text="取消", command=self.close)
        self.cancel.grid(row=0, column=0, padx=(0, d(8)))
        self.confirm = ttk.Button(actions, style="CardConfirm.TButton")
        self.confirm.grid(row=0, column=1)

    def open(self, initial, apply, confirm_text="应用"):
        self.initial = initial
        self.confirm.configure(text=confirm_text, command=apply)
        self.ui.book_editor = self
        self.source.grid_remove()
        self.grid(row=0, column=0, sticky="nsew")
        self.ui._refresh_controls()
        self.update_idletasks()
        self.grab_set()
        initial.focus_set()

    def close(self):
        ui = self.ui
        ui.book_editor = None
        self.grab_release()
        self.destroy()
        self.source.grid()
        ui._refresh_controls()
        ui.root.update_idletasks()
        if self.origin is not None and self.origin.winfo_exists() and self.origin.winfo_ismapped():
            self.origin.focus_set()
        else:
            ui.nav_buttons[ui.active_page].focus_set()
        return "break"

    def traverse(self, event, *, backward=False):
        widget = event.widget
        visited = {widget}
        while widget is not None:
            widget = widget.tk_focusPrev() if backward else widget.tk_focusNext()
            if widget is None or widget in visited:
                break
            if str(widget).startswith(str(self) + "."):
                widget.focus_set()
                break
            visited.add(widget)
        return "break"
