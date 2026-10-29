"""Game-sized settings choices over Tk's own selection and popup lifecycle."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from PIL import ImageTk

from . import theme as t


class SettingChoice(ttk.Combobox):
    """Keep the native listbox for input; paint its rows and selection markers."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._choice_job = None
        self._choice_key = None
        self._choice_photo = None
        self._choice_canvas = None
        self.configure(postcommand=self._prepare_choices)
        self.bind('<Destroy>', self._destroy_choices, add='+')
        self.bind('<Unmap>', self._unpost_choices, add='+')

    def _prepare_choices(self):
        scale = self.winfo_toplevel()._hsr_scale
        pop = str(self.tk.call('ttk::combobox::PopdownWindow', self))
        listing = pop+'.f.l'
        font = t.native_font(self, 12)
        linespace = int(self.tk.call('font', 'metrics', font, '-linespace'))
        pad = max(0, round((58*scale-linespace)/2))
        self.tk.call(listing, 'configure', '-font', font, '-selectborderwidth', pad,
                     '-borderwidth', 0, '-highlightthickness', 0)
        # A taller game row needs fewer visible items than a desktop listbox.
        # Keep Tk's scrolling and above/below placement; do not exceed the screen.
        row_height = linespace+2*pad
        from .desktop_dialogs import _work_area
        _, upper, _, bottom = _work_area(self)
        y, height = self.winfo_rooty(), self.winfo_height()
        available = max(y-upper, bottom-y-height)-8
        self.configure(height=max(1, min(7, int(available//row_height))))
        if self._choice_canvas is None:
            # The popup and listbox are Tcl-owned. This child canvas is only a
            # view: focus, grab, keyboard navigation and commit remain native.
            canvas = self._choice_canvas = listing+'.art'
            self.tk.call('canvas', canvas, '-borderwidth', 0, '-highlightthickness', 0,
                         '-background', '#ededed', '-takefocus', 0)
            self.tk.call('place', canvas, '-x', 0, '-y', 0, '-relwidth', 1, '-relheight', 1)
            self.tk.call('bindtags', canvas, (canvas,))
            redraw = self._register(self._queue_choices)
            self.tk.call('bind', pop, '<Map>', '+'+self._register(self._place_choices))
            for event in ('<Configure>', '<Map>', '<<ListboxSelect>>', '<KeyRelease>'):
                self.tk.call('bind', listing, event, '+'+redraw)
            self.tk.call(listing, 'configure', '-yscrollcommand',
                         (self._register(self._scroll_choices), pop+'.f.sb'))
            for event in ('<Motion>', '<ButtonPress-1>', '<ButtonRelease-1>', '<B1-Motion>'):
                script = f'event generate {listing} {event} -x %x -y %y\n{redraw}\nbreak'
                self.tk.call('bind', canvas, event, script)
            for event in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                delta = ' -delta %D' if event == '<MouseWheel>' else ''
                self.tk.call('bind', canvas, event,
                             f'event generate {listing} {event}{delta}\n{redraw}\nbreak')
        self._choice_key = None
        self._queue_choices()

    def _place_choices(self):
        from .desktop_dialogs import _work_area
        left, upper, right, bottom = _work_area(self)
        pop = str(self)+'.popdown'
        width = min(self.winfo_width(), right-left)
        height = min(int(self.tk.call('winfo', 'reqheight', pop)), bottom-upper)
        x = max(left, min(self.winfo_rootx(), right-width))
        below = self.winfo_rooty()+self.winfo_height()
        y = below if below+height <= bottom else self.winfo_rooty()-height
        y = max(upper, min(y, bottom-height))
        self.tk.call('wm', 'geometry', pop, f'{width}x{height}+{x}+{y}')

    def _unpost_choices(self, _):
        if self._choice_canvas is not None:
            self.tk.call('ttk::combobox::Unpost', self)

    def _scroll_choices(self, scrollbar, first, last):
        self.tk.call(scrollbar, 'set', first, last)
        self._queue_choices()

    def _queue_choices(self):
        if self._choice_job is None:
            self._choice_job = self.after_idle(self._paint_choices)

    def _paint_choices(self):
        self._choice_job = None
        canvas = self._choice_canvas
        if not canvas or not self.tk.getboolean(self.tk.call('winfo', 'exists', canvas)):
            return
        listing = canvas.rpartition('.')[0]
        width = int(self.tk.call('winfo', 'width', canvas))
        height = int(self.tk.call('winfo', 'height', canvas))
        if width < 2 or height < 2:
            return
        values = self.cget('values')
        if isinstance(values, str):
            values = self.tk.splitlist(values)
        selected = tuple(map(int, self.tk.splitlist(self.tk.call(listing, 'curselection'))))
        rows = []
        first = int(self.tk.call(listing, 'nearest', 0))
        last = int(self.tk.call(listing, 'nearest', height))
        scale = self.winfo_toplevel()._hsr_scale
        pad = int(self.tk.call(listing, 'cget', '-selectborderwidth'))
        for index in range(first, min(last+1, len(values))):
            box = self.tk.call(listing, 'bbox', index)
            if box:
                _, y, _, line_height = tuple(map(int, self.tk.splitlist(box)))
                rows.append((index, y-pad, line_height+2*pad))
        key = (width, height, tuple(values), self.current(), selected, tuple(rows), scale)
        if self._choice_key == key:
            return
        p = t.Painter(width, height, scale, '#ededed')
        for index, top, row_height in rows:
            y, h = top/scale, row_height/scale
            center = y+h/2
            if index in selected and index != self.current():
                p.box((0, y, p.width, y+h), '#e2e2e2', outline=t.GOLD)
            p.text((14, center), p.wrap(values[index], max(1, p.width-72), 16, 1), 16, t.TEXT, 'lm')
            chosen = index == self.current()
            x, radius = p.width-36.8, 11.8 if chosen else 10.8
            color = '#f19d38' if chosen else '#979797'
            p.ellipse((x-radius, center-radius, x+radius, center+radius), None, color, 2.6 if chosen else .7)
            if chosen:
                p.ellipse((x-6.8, center-6.8, x+6.8, center+6.8), color)
            if index < len(values)-1:
                p.line((14, y+h-1, p.width-14, y+h-1), '#d6d6d6', 1.6)
        photo = ImageTk.PhotoImage(p.finish(), master=self)
        if self.tk.call(canvas, 'find', 'withtag', 'art'):
            self.tk.call(canvas, 'itemconfigure', 'art', '-image', str(photo))
        else:
            self.tk.call(canvas, 'create', 'image', 0, 0, '-anchor', 'nw', '-image', str(photo), '-tags', 'art')
        self._choice_photo = photo
        self._choice_key = key

    def _destroy_choices(self, event):
        if event.widget is self:
            if self._choice_job is not None:
                self.after_cancel(self._choice_job)
                self._choice_job = None
            self._choice_photo = None
