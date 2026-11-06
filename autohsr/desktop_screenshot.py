"""Screenshot capture, region selection, OCR and crop export in the tools shelf."""
from dataclasses import dataclass, field
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from . import screenshot_tool, theme
from .models import AutomationError, Stopped


@dataclass
class _State:
    image: Image.Image | None = field(default=None, repr=False)
    box: tuple[int, int, int, int] | None = None
    text: str = field(default='', repr=False)
    message: str = '截取当前游戏窗口，或打开本地图片。拖动鼠标框选区域。'
    source: str = ''
    job: object | None = None


def _image_box(start, end, preview, image_size):
    left, top, width, height = preview
    original_width, original_height = image_size
    x0, x1 = sorted((start[0], end[0]))
    y0, y1 = sorted((start[1], end[1]))
    if x0 == x1 or y0 == y1:
        return None
    sx, sy = original_width / width, original_height / height
    box = (max(0, math.floor((x0 - left) * sx)), max(0, math.floor((y0 - top) * sy)),
           min(original_width, math.ceil((x1 - left) * sx)), min(original_height, math.ceil((y1 - top) * sy)))
    return box if box[0] < box[2] and box[1] < box[3] else None


class ScreenshotPanel(ttk.Frame):
    def __init__(self, parent, ui, state):
        super().__init__(parent)
        self.ui, self.model = ui, state
        self.preview, self.drag, self.preview_key, self.photo = None, None, None, None
        pad = round(7 * ui.ui_scale)
        self.columnconfigure(0, weight=1)
        actions = ttk.Frame(self)
        actions.grid(row=0, column=0, sticky='ew', pady=(0, pad))
        self.buttons = []
        for label, command in (('打开图片…', self.open_image), ('选中全图', self.select_all),
                               ('识别选区', self.read), ('导出选区…', self.save)):
            button = ttk.Button(actions, text=label, style='Compact.TButton', command=command)
            button.pack(side='left', padx=(0, pad))
            self.buttons.append(button)
        self.canvas = tk.Canvas(self, height=round(292 * ui.ui_scale), width=1,
                                highlightthickness=0, background=theme.CARD)
        self.canvas.grid(row=1, column=0, sticky='ew')
        self.canvas.bind('<Configure>', self._draw)
        self.canvas.bind('<ButtonPress-1>', self._press)
        self.canvas.bind('<B1-Motion>', self._drag)
        self.canvas.bind('<ButtonRelease-1>', self._release)
        self.coordinates = theme.wrapped_label(self, style='Hint.TLabel')
        self.coordinates.grid(row=2, column=0, sticky='ew', pady=(pad, 0))
        self.feedback = theme.wrapped_label(self, style='Hint.TLabel')
        self.feedback.grid(row=3, column=0, sticky='ew', pady=(pad, 0))
        result = ttk.Frame(self)
        result.grid(row=4, column=0, sticky='ew', pady=(pad, 0))
        result.columnconfigure(0, weight=1)
        self.result = tk.Text(result, height=4, width=1, wrap='word', state='disabled', relief='flat',
                              background=theme.CARD, foreground=theme.TEXT, font=theme.native_font(self, 10))
        self.result.grid(row=0, column=0, sticky='ew')
        scroll = ttk.Scrollbar(result, orient='vertical', command=self.result.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.result.configure(yscrollcommand=scroll.set)
        self.refresh()

    @property
    def _idle(self):
        return not self.ui.busy and not self.ui.closing and self.model.job is None

    @property
    def _active(self):
        return (self.ui.screenshot_panel is self and self.ui._in_tools()
                and self.ui._selected_tool == 'screenshot')

    def primary_action(self):
        return '截取游戏窗口', self.capture, self._idle and self._active

    def focus_entry(self):
        self.buttons[0].focus_set()

    def refresh(self):
        model = self.model
        idle = self._idle
        have_image = model.image is not None
        for button, enabled in zip(self.buttons, (idle, idle and have_image, idle and model.box is not None,
                                                  idle and model.box is not None)):
            button.state(('!disabled' if enabled else 'disabled',))
        self.feedback.configure(text=model.message)
        coords = '尚无图片'
        if have_image:
            width, height = model.image.size
            coords = f'{model.source} · {width} × {height}'
            if model.box is not None:
                left, top, right, bottom = model.box
                normalized = ', '.join(f'{value:.4f}' for value in (left / width, top / height,
                                                                   right / width, bottom / height))
                coords += f' · 像素 ({left}, {top}) → ({right}, {bottom})\n归一化范围 ({normalized})'
        self.coordinates.configure(text=coords)
        if self.result.get('1.0', 'end-1c') != model.text:
            self.result.configure(state='normal')
            self.result.delete('1.0', 'end')
            self.result.insert('1.0', model.text)
            self.result.configure(state='disabled')
        self._draw()

    def _draw(self, _event=None):
        image = self.model.image
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        key = id(image), width, height
        if key != self.preview_key:
            self.preview_key = key
            self.drag = None
            self.preview = self.photo = None
            self.canvas.delete('all')
            if image is not None and width > 1 and height > 1:
                factor = min(width / image.width, height / image.height, 1)
                size = max(1, round(image.width * factor)), max(1, round(image.height * factor))
                left, top = (width - size[0]) // 2, (height - size[1]) // 2
                self.preview = left, top, *size
                self.photo = ImageTk.PhotoImage(image.resize(size, Image.Resampling.LANCZOS), master=self.canvas)
                self.canvas.create_image(left, top, anchor='nw', image=self.photo)
        self.canvas.delete('selection')
        if self.preview is not None and self.model.box is not None:
            left, top, width, height = self.preview
            x1, y1, x2, y2 = self.model.box
            sx, sy = width / image.width, height / image.height
            self.canvas.create_rectangle(left + x1 * sx, top + y1 * sy, left + x2 * sx, top + y2 * sy,
                                         outline=theme.GOLD, width=2, tags='selection')

    def _press(self, event):
        if self._idle and self._active and self.preview is not None:
            left, top, width, height = self.preview
            if left <= event.x < left + width and top <= event.y < top + height:
                self.drag = event.x, event.y

    def _drag(self, event):
        if self.drag is not None and self._idle and self._active:
            self.canvas.delete('selection')
            self.canvas.create_rectangle(*self.drag, event.x, event.y, outline=theme.GOLD,
                                         width=2, tags='selection')

    def _release(self, event):
        start, self.drag = self.drag, None
        if start is not None and self.preview is not None and self._idle and self._active:
            self._select(_image_box(start, (event.x, event.y), self.preview, self.model.image.size))

    def _select(self, box):
        if box != self.model.box:
            self.model.box, self.model.text = box, ''
            self.model.message = '已框选区域。' if box is not None else '请拖动鼠标框选区域。'
        self.refresh()

    def select_all(self):
        if self._idle and self._active and self.model.image is not None:
            self._select((0, 0, *self.model.image.size))

    def open_image(self):
        if not self._idle or not self._active:
            return
        path = filedialog.askopenfilename(parent=self.ui.root, title='打开本地截图',
                                          filetypes=[('PNG 或 JPEG', '*.png *.jpg *.jpeg')])
        if path and self._idle and self._active:
            self._start('读取本地图片', lambda cancel: screenshot_tool.open_image(path, cancel),
                        lambda image: self._set_image(image, '本地图片'))

    def capture(self):
        if not self._idle or not self._active:
            return
        settings = self.ui._read_settings(operation='check')
        if settings is not None:
            self._start('截取游戏窗口', lambda cancel: screenshot_tool.capture_game(settings, cancel),
                        lambda image: self._set_image(image, '游戏截图'))

    def _set_image(self, image, source):
        model = self.model
        model.image, model.source, model.box, model.text = image, source, None, ''
        model.message = '图片已读取。拖动鼠标框选区域。'

    def read(self):
        model = self.model
        if not self._idle or not self._active or model.box is None:
            return
        settings = self.ui._read_settings(operation='check')
        if settings is None:
            return
        image, box = model.image, model.box

        def present(rows):
            model.text = '\n'.join(f'{score:.0%}  {text}' for text, score in rows)
            model.message = f'识别到 {len(rows)} 条文字。' if rows else '选区内未识别到文字。'

        self._start('识别截图选区', lambda cancel: screenshot_tool.read_selection(image, box,
                                                                                  settings.ocr_confidence, cancel),
                    present)

    def save(self):
        model = self.model
        if not self._idle or not self._active or model.box is None:
            return
        image, box = model.image, model.box
        path = filedialog.asksaveasfilename(parent=self.ui.root, title='另存截图选区', defaultextension='.png',
                                            filetypes=[('PNG', '*.png')], confirmoverwrite=False)
        if path and self._idle and self._active and model.image is image and model.box == box:
            self._start('导出截图选区', lambda cancel: screenshot_tool.save_selection(image, box, path, cancel),
                        lambda _digest: setattr(model, 'message', f'已导出 · {Path(path).name}'), published=True)

    def _start(self, title, work, present, *, published=False):
        if not self._idle or not self._active:
            return
        ui, model = self.ui, self.model
        job, previous = object(), model.message
        model.job, model.message = job, f'正在{title}…'
        self.drag = None

        def update():
            panel = getattr(ui, 'screenshot_panel', self)
            if panel.winfo_exists():
                panel.refresh()
            ui._tool_action_changed()

        def done(value):
            if model.job is job:
                model.job = None
                if not published and ui.stop_requested.is_set():
                    model.message = '截图工具已停止。'
                else:
                    present(value)
                update()

        def failed(error):
            if model.job is job:
                model.job = None
                model.message = (str(error) if isinstance(error, (AutomationError, Stopped, screenshot_tool.ScreenshotError))
                                 else '未能读取或写入图片，请检查本地文件和窗口。')
                update()

        try:
            accepted = ui._submit_tool_job(title, lambda stop: work(stop.is_set), done, failed)
        except Exception as error:
            failed(error)
            return
        if not accepted:
            model.job, model.message = None, previous
        update()


def build_screenshot_panel(parent, ui):
    if not hasattr(ui, '_screenshot_tool_state'):
        ui._screenshot_tool_state = _State()
    return ScreenshotPanel(parent, ui, ui._screenshot_tool_state)
