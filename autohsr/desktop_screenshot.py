"""Screenshot capture, region selection, OCR and crop export in the tools shelf."""
from dataclasses import dataclass, field
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from . import screenshot_tool, theme
from .models import AutomationError, Stopped
from .reward_guide_stitch import _MAX_PAGES


_SCREEN_MODE = '截图与识别'
_GUIDE_MODE = '奖励指南单屏导出'
_GUIDE_ACTION = '导出奖励指南单屏'
_GUIDE_UNKNOWN = '奖励指南单屏导出结果待核对。'
_STITCH_MODE = '本地奖励指南拼接'
_STITCH_ACTION = '拼接并导出奖励指南'
_STITCH_UNKNOWN = '奖励指南拼接结果待核对。'
_GUIDE_STATUS = {
    'invalid_target': '请选择新的本地 PNG 位置，已有文件保留。',
    'unverified': '当前奖励指南或内容框待核对。',
    'report_unverified': '匿名核对报告未发布，未导出图片。',
    'publish_failed': '无法发布 PNG，请核对输出位置。',
    'publish_unverified': 'PNG 发布结果待核对，请查看所选位置。',
    'limit': '当前裁片超过导出上限。',
    'stopped': '奖励指南单屏导出已停止。',
}
_STITCH_STATUS = {
    'invalid_target': _GUIDE_STATUS['invalid_target'],
    'invalid_source': '请核对所选本地 PNG。',
    'invalid': '所选裁片的尺寸或格式不一致。',
    'limit': '所选裁片超过拼接上限。',
    'source_changed': '源图片已变化，请重新选择。',
    'duplicate': '发现重复裁片，请移除后再导出。',
    'ambiguous': '裁片接缝待核对，请调整所选图片。',
    'no_overlap': '未核实相邻裁片的重叠区。',
    'wrong_direction': '裁片顺序相反，请按列表从上到下排列。',
    'inconsistent': '多张裁片的共有内容不一致。',
    'publish_failed': _GUIDE_STATUS['publish_failed'],
    'stopped': '奖励指南拼接已停止。',
}


def _local_png_selection(value):
    path = Path(value)
    if not path.is_absolute() or path.anchor.startswith('\\') or path.suffix.casefold() != '.png':
        return None
    return path


def _guide_feedback(receipt):
    if not isinstance(receipt, dict) or receipt.get('input_sent') is not False:
        return _GUIDE_UNKNOWN
    status = receipt.get('status')
    if status == 'ok':
        width, height = receipt.get('width'), receipt.get('height')
        if (receipt.get('visible_section') == 'ongoing' and type(width) is int and type(height) is int
                and width > 0 and height > 0):
            return f'已导出「进行中」内容 · {width} × {height} · 游戏输入 0 次。'
    return _GUIDE_STATUS.get(status, _GUIDE_UNKNOWN) if isinstance(status, str) else _GUIDE_UNKNOWN


def _stitch_feedback(receipt, pages):
    if not isinstance(receipt, dict):
        return _STITCH_UNKNOWN
    status = receipt.get('status')
    if status == 'ok':
        width, height = receipt.get('width'), receipt.get('height')
        overlaps = receipt.get('overlap_rows')
        if (type(width) is int and width > 0 and type(height) is int and height > 0
                and isinstance(overlaps, list) and len(overlaps) == pages - 1
                and all(type(rows) is int and rows > 0 for rows in overlaps)):
            detail = f'已导出拼图 · {pages} 张裁片 · {width} × {height}。'
            if overlaps:
                detail += '接缝重叠行数 ' + '／'.join(map(str, overlaps)) + '。'
            return detail
    return _STITCH_STATUS.get(status, _STITCH_UNKNOWN) if isinstance(status, str) else _STITCH_UNKNOWN


@dataclass
class _State:
    image: Image.Image | None = field(default=None, repr=False)
    box: tuple[int, int, int, int] | None = None
    text: str = field(default='', repr=False)
    message: str = '截取当前游戏窗口，或打开本地图片。拖动鼠标框选区域。'
    source: str = ''
    job: object | None = None
    mode: str = _SCREEN_MODE
    guide_destination: Path | None = None
    guide_message: str = '尚无奖励指南导出回执。'
    stitch_sources: tuple[Path, ...] = ()
    stitch_index: int | None = None
    stitch_destination: Path | None = None
    stitch_message: str = '尚无奖励指南拼接回执。'


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


class SelectionCanvas(tk.Canvas):
    """Preview an image while keeping selections in its original pixel coordinates."""

    def __init__(self, parent, *, height, can_select, on_select):
        super().__init__(parent, height=height, width=1, highlightthickness=0, background=theme.CARD)
        self.can_select, self.on_select = can_select, on_select
        self.image = self.box = None
        self.preview = self.drag = self.preview_key = self.photo = None
        self.bind('<Configure>', self._draw)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<ButtonRelease-1>', self._release)

    def show(self, image, box):
        self.image, self.box = image, box
        self._draw()

    def _draw(self, _event=None):
        image = self.image
        width, height = self.winfo_width(), self.winfo_height()
        key = id(image), width, height
        if key != self.preview_key:
            self.preview_key = key
            self.drag = None
            self.preview = self.photo = None
            self.delete('all')
            if image is not None and width > 1 and height > 1:
                factor = min(width / image.width, height / image.height, 1)
                size = max(1, round(image.width * factor)), max(1, round(image.height * factor))
                left, top = (width - size[0]) // 2, (height - size[1]) // 2
                self.preview = left, top, *size
                self.photo = ImageTk.PhotoImage(image.resize(size, Image.Resampling.LANCZOS), master=self)
                self.create_image(left, top, anchor='nw', image=self.photo)
        self.delete('selection')
        if self.preview is not None and self.box is not None:
            left, top, width, height = self.preview
            x1, y1, x2, y2 = self.box
            sx, sy = width / image.width, height / image.height
            self.create_rectangle(left + x1 * sx, top + y1 * sy, left + x2 * sx, top + y2 * sy,
                                  outline=theme.GOLD, width=2, tags='selection')

    def _press(self, event):
        if self.can_select() and self.preview is not None:
            left, top, width, height = self.preview
            if left <= event.x < left + width and top <= event.y < top + height:
                self.drag = event.x, event.y

    def _drag(self, event):
        if self.drag is not None and self.can_select():
            self.delete('selection')
            self.create_rectangle(*self.drag, event.x, event.y, outline=theme.GOLD, width=2, tags='selection')

    def _release(self, event):
        start, self.drag = self.drag, None
        if start is not None and self.preview is not None and self.can_select():
            self.on_select(_image_box(start, (event.x, event.y), self.preview, self.image.size))


class ScreenshotPanel(ttk.Frame):
    def __init__(self, parent, ui, state):
        super().__init__(parent)
        self.ui, self.model = ui, state
        pad = round(7 * ui.ui_scale)
        self.columnconfigure(0, weight=1)
        mode_row = ttk.Frame(self)
        mode_row.grid(row=0, column=0, sticky='ew', pady=(0, pad))
        ttk.Label(mode_row, text='本次操作', style='Card.TLabel').pack(side='left', padx=(0, pad))
        self.mode = ttk.Combobox(mode_row, values=(_SCREEN_MODE, _GUIDE_MODE, _STITCH_MODE), width=18, state='readonly')
        self.mode.pack(side='left')
        self.mode.bind('<<ComboboxSelected>>', self._mode_selected)

        self.screenshot_fields = ttk.Frame(self)
        self.screenshot_fields.columnconfigure(0, weight=1)
        self.screenshot_fields.grid(row=1, column=0, sticky='ew')
        actions = ttk.Frame(self.screenshot_fields)
        actions.grid(row=0, column=0, sticky='ew', pady=(0, pad))
        self.buttons = []
        for label, command in (('打开图片…', self.open_image), ('选中全图', self.select_all),
                               ('识别选区', self.read), ('导出选区…', self.save)):
            button = ttk.Button(actions, text=label, style='Compact.TButton', command=command)
            button.pack(side='left', padx=(0, pad))
            self.buttons.append(button)
        self.canvas = SelectionCanvas(self.screenshot_fields, height=round(292 * ui.ui_scale),
                                      can_select=lambda: self._can_screenshot, on_select=self._select)
        self.canvas.grid(row=1, column=0, sticky='ew')
        self.coordinates = theme.wrapped_label(self.screenshot_fields, style='Hint.TLabel')
        self.coordinates.grid(row=2, column=0, sticky='ew', pady=(pad, 0))
        self.feedback = theme.wrapped_label(self.screenshot_fields, style='Hint.TLabel')
        self.feedback.grid(row=3, column=0, sticky='ew', pady=(pad, 0))
        result = ttk.Frame(self.screenshot_fields)
        result.grid(row=4, column=0, sticky='ew', pady=(pad, 0))
        result.columnconfigure(0, weight=1)
        self.result = tk.Text(result, height=4, width=1, wrap='word', state='disabled', relief='flat',
                              background=theme.CARD, foreground=theme.TEXT, font=theme.native_font(self, 10))
        self.result.grid(row=0, column=0, sticky='ew')
        scroll = ttk.Scrollbar(result, orient='vertical', command=self.result.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.result.configure(yscrollcommand=scroll.set)

        self.guide_fields = ttk.Frame(self)
        self.guide_fields.columnconfigure(1, weight=1)
        self.guide_fields.grid(row=1, column=0, sticky='ew')
        hint = theme.wrapped_label(self.guide_fields, style='Hint.TLabel',
            text='请先在游戏手动打开奖励指南的「旅程热点」。选定新 PNG 位置并开始后，手动切回游戏前台。')
        hint.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, pad))
        self.guide_picker = ttk.Button(self.guide_fields, text='选择 PNG 位置…', style='Compact.TButton',
                                       command=self.pick_guide_destination)
        self.guide_picker.grid(row=1, column=0, sticky='nw', padx=(0, pad))
        self.guide_path = theme.wrapped_label(self.guide_fields, style='Hint.TLabel')
        self.guide_path.grid(row=1, column=1, sticky='ew')
        self.guide_feedback = theme.wrapped_label(self.guide_fields, style='Hint.TLabel')
        self.guide_feedback.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(pad, 0))
        self._build_stitch_fields(pad)
        self.refresh()

    def _build_stitch_fields(self, pad):
        self.stitch_fields = ttk.Frame(self)
        self.stitch_fields.columnconfigure(0, weight=1)
        self.stitch_fields.grid(row=1, column=0, sticky='ew')
        hint = theme.wrapped_label(self.stitch_fields, style='Hint.TLabel',
            text=f'添加 1～{_MAX_PAGES} 张尺寸一致的本地 PNG 裁片。按列表从上到下拼接，请保留相邻内容的重叠区。')
        hint.grid(row=0, column=0, sticky='ew', pady=(0, pad))
        actions = ttk.Frame(self.stitch_fields)
        actions.grid(row=1, column=0, sticky='ew')
        self.stitch_buttons = []
        for label, command in (('添加 PNG…', self.add_stitch_sources), ('上移', lambda: self.move_stitch_source(-1)),
                               ('下移', lambda: self.move_stitch_source(1)), ('移除', self.remove_stitch_source)):
            button = ttk.Button(actions, text=label, style='Compact.TButton', command=command)
            button.pack(side='left', padx=(0, pad))
            self.stitch_buttons.append(button)
        self.stitch_list = tk.Listbox(self.stitch_fields, width=1, height=_MAX_PAGES, selectmode='browse', exportselection=False,
                                     background=theme.CARD, foreground=theme.TEXT, font=theme.native_font(self, 10))
        self.stitch_list.grid(row=2, column=0, sticky='ew', pady=(pad, 0))
        self.stitch_list.bind('<<ListboxSelect>>', self._stitch_selected)
        self.stitch_source_path = theme.wrapped_label(self.stitch_fields, style='Hint.TLabel')
        self.stitch_source_path.grid(row=3, column=0, sticky='ew', pady=(pad, 0))
        output = ttk.Frame(self.stitch_fields)
        output.columnconfigure(1, weight=1)
        output.grid(row=4, column=0, sticky='ew', pady=(pad, 0))
        self.stitch_picker = ttk.Button(output, text='选择 PNG 位置…', style='Compact.TButton',
                                        command=self.pick_stitch_destination)
        self.stitch_picker.grid(row=0, column=0, sticky='nw', padx=(0, pad))
        self.stitch_path = theme.wrapped_label(output, style='Hint.TLabel')
        self.stitch_path.grid(row=0, column=1, sticky='ew')
        self.stitch_feedback = theme.wrapped_label(self.stitch_fields, style='Hint.TLabel')
        self.stitch_feedback.grid(row=5, column=0, sticky='ew', pady=(pad, 0))

    @property
    def _idle(self):
        return not self.ui.busy and not self.ui.closing and self.model.job is None

    @property
    def _active(self):
        return (self.ui.screenshot_panel is self and self.ui._in_tools()
                and self.ui._selected_tool == 'screenshot')

    @property
    def _can_screenshot(self):
        return self.model.mode == _SCREEN_MODE and self._idle and self._active

    @property
    def _can_guide(self):
        return self.model.mode == _GUIDE_MODE and self._idle and self._active

    @property
    def _can_stitch(self):
        return self.model.mode == _STITCH_MODE and self._idle and self._active

    def primary_action(self):
        if self.model.mode == _GUIDE_MODE:
            return _GUIDE_ACTION, self.export_guide, self._can_guide and self.model.guide_destination is not None
        if self.model.mode == _STITCH_MODE:
            ready = 1 <= len(self.model.stitch_sources) <= _MAX_PAGES and self.model.stitch_destination is not None
            return _STITCH_ACTION, self.export_stitch, self._can_stitch and ready
        return '截取游戏窗口', self.capture, self._can_screenshot

    def focus_entry(self):
        self.mode.focus_set()

    def _mode_selected(self, _event=None):
        selected = self.mode.get()
        if self._idle and self._active and selected in (_SCREEN_MODE, _GUIDE_MODE, _STITCH_MODE):
            self.model.mode = selected
        self.refresh()
        self.ui._tool_action_changed()

    def refresh(self):
        model = self.model
        idle = self._idle
        if self.mode.get() != model.mode:
            self.mode.set(model.mode)
        self.mode.configure(state='readonly' if idle else 'disabled')
        for mode, fields in ((_SCREEN_MODE, self.screenshot_fields), (_GUIDE_MODE, self.guide_fields),
                             (_STITCH_MODE, self.stitch_fields)):
            if model.mode == mode:
                fields.grid()
            else:
                fields.grid_remove()
        if model.mode == _STITCH_MODE:
            self._refresh_stitch(idle)
        self.guide_picker.state(('!disabled' if idle else 'disabled',))
        self.guide_path.configure(text=str(model.guide_destination) if model.guide_destination else '尚未选择输出位置。')
        self.guide_feedback.configure(text=model.guide_message)
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
        self.canvas.show(model.image, model.box)

    def _refresh_stitch(self, idle):
        model = self.model
        sources, index = model.stitch_sources, model.stitch_index
        self.stitch_list.configure(state='normal')
        labels = tuple(f'{number}. {path.name}' for number, path in enumerate(sources, 1))
        if self.stitch_list.get(0, 'end') != labels:
            self.stitch_list.delete(0, 'end')
            if labels:
                self.stitch_list.insert('end', *labels)
        selected = () if index is None else (index,)
        if self.stitch_list.curselection() != selected:
            self.stitch_list.selection_clear(0, 'end')
            if index is not None:
                self.stitch_list.selection_set(index)
                self.stitch_list.activate(index)
        if not idle:
            self.stitch_list.configure(state='disabled')
        states = (len(sources) < _MAX_PAGES, index is not None and index > 0,
                  index is not None and index + 1 < len(sources), index is not None)
        for button, enabled in zip(self.stitch_buttons, states):
            button.state(('!disabled' if idle and enabled else 'disabled',))
        self.stitch_picker.state(('!disabled' if idle else 'disabled',))
        self.stitch_source_path.configure(text=str(sources[index]) if index is not None else '')
        self.stitch_path.configure(text=str(model.stitch_destination) if model.stitch_destination else '尚未选择输出位置。')
        self.stitch_feedback.configure(text=model.stitch_message)

    def _select(self, box):
        if box != self.model.box:
            self.model.box, self.model.text = box, ''
            self.model.message = '已框选区域。' if box is not None else '请拖动鼠标框选区域。'
        self.refresh()

    def select_all(self):
        if self._can_screenshot and self.model.image is not None:
            self._select((0, 0, *self.model.image.size))

    def open_image(self):
        if not self._can_screenshot:
            return
        path = filedialog.askopenfilename(parent=self.ui.root, title='打开本地截图',
                                          filetypes=[('PNG 或 JPEG', '*.png *.jpg *.jpeg')])
        if path and self._can_screenshot:
            self._start('读取本地图片', lambda cancel: screenshot_tool.open_image(path, cancel),
                        lambda image: self._set_image(image, '本地图片'))

    def capture(self):
        if not self._can_screenshot:
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
        if not self._can_screenshot or model.box is None:
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
        if not self._can_screenshot or model.box is None:
            return
        image, box = model.image, model.box
        path = filedialog.asksaveasfilename(parent=self.ui.root, title='另存截图选区', defaultextension='.png',
                                            filetypes=[('PNG', '*.png')], confirmoverwrite=False)
        if path and self._can_screenshot and model.image is image and model.box == box:
            self._start('导出截图选区', lambda cancel: screenshot_tool.save_selection(image, box, path, cancel),
                        lambda _digest: setattr(model, 'message', f'已导出 · {Path(path).name}'), published=True)

    def pick_guide_destination(self):
        if not self._can_guide:
            return False
        value = filedialog.asksaveasfilename(parent=self.ui.root, title='保存奖励指南单屏', defaultextension='.png',
                                             filetypes=[('PNG', '*.png')], confirmoverwrite=False)
        if not value or not self._can_guide:
            return False
        path = _local_png_selection(value)
        self.model.guide_destination = path
        if path is None:
            self.model.guide_message = _GUIDE_STATUS['invalid_target']
        self.refresh()
        self.ui._tool_action_changed()
        return path is not None

    def _stitch_selected(self, _event=None):
        if self._can_stitch:
            selected = self.stitch_list.curselection()
            self.model.stitch_index = selected[0] if selected else None
        self.refresh()

    def _update_stitch_sources(self, sources, index):
        self.model.stitch_sources, self.model.stitch_index = sources, index
        self.model.stitch_message = '拼接顺序已更新。'
        self.refresh()
        self.ui._tool_action_changed()

    def add_stitch_sources(self):
        if not self._can_stitch or len(self.model.stitch_sources) >= _MAX_PAGES:
            return False
        values = filedialog.askopenfilenames(parent=self.ui.root, title='选择本地奖励指南 PNG 裁片',
                                             filetypes=[('PNG', '*.png')])
        if not values or not self._can_stitch:
            return False
        values = values if isinstance(values, (tuple, list)) else self.tk.splitlist(values)
        existing = self.model.stitch_sources
        if len(existing) + len(values) > _MAX_PAGES:
            self.model.stitch_message = f'每次最多选择 {_MAX_PAGES} 张裁片。'
            self.refresh()
            return False
        paths = tuple(_local_png_selection(value) for value in values)
        sources = (*existing, *paths)
        if None in paths:
            self.model.stitch_message = _STITCH_STATUS['invalid_source']
        elif len(set(sources)) != len(sources):
            self.model.stitch_message = '同一 PNG 已在列表中。'
        else:
            self._update_stitch_sources(sources, len(existing))
            return True
        self.refresh()
        return False

    def move_stitch_source(self, step):
        index = self.model.stitch_index
        sources = list(self.model.stitch_sources)
        if not self._can_stitch or index is None or not 0 <= index + step < len(sources):
            return False
        target = index + step
        sources[index], sources[target] = sources[target], sources[index]
        self._update_stitch_sources(tuple(sources), target)
        return True

    def remove_stitch_source(self):
        index = self.model.stitch_index
        if not self._can_stitch or index is None:
            return False
        sources = self.model.stitch_sources
        remaining = sources[:index] + sources[index + 1:]
        self._update_stitch_sources(remaining, min(index, len(remaining) - 1) if remaining else None)
        return True

    def pick_stitch_destination(self):
        if not self._can_stitch:
            return False
        value = filedialog.asksaveasfilename(parent=self.ui.root, title='保存拼接后的奖励指南', defaultextension='.png',
                                             filetypes=[('PNG', '*.png')], confirmoverwrite=False)
        if not value or not self._can_stitch:
            return False
        path = _local_png_selection(value)
        self.model.stitch_destination = path
        if path is None:
            self.model.stitch_message = _STITCH_STATUS['invalid_target']
        self.refresh()
        self.ui._tool_action_changed()
        return path is not None

    def export_stitch(self):
        model = self.model
        sources, destination = model.stitch_sources, model.stitch_destination
        if not self._can_stitch or not 1 <= len(sources) <= _MAX_PAGES or destination is None:
            return False

        def work(cancel):
            from .reward_guide_export import export_reward_guide

            return export_reward_guide(sources, destination, checkpoint=lambda: screenshot_tool._checkpoint(cancel))

        def present(receipt):
            model.stitch_message = _stitch_feedback(receipt, len(sources))
            model.stitch_destination = None

        def failed(error):
            present({'status': 'stopped'} if isinstance(error, Stopped) else None)

        return self._start(_STITCH_ACTION, work, present, published=True, message='stitch_message', on_error=failed)

    def export_guide(self):
        from .daily_observe import SCREEN_OPERATION
        from .reward_guide_capture import RewardGuideCapture, _receipt
        from .reward_guide_export import _Rejected

        model, ui = self.model, self.ui
        if not self._can_guide or model.guide_destination is None:
            return False
        try:
            capture = RewardGuideCapture(model.guide_destination)
        except _Rejected as error:
            model.guide_destination = None
            model.guide_message = _guide_feedback(_receipt(str(error)))
            self.refresh()
            ui._tool_action_changed()
            return False
        settings = ui._read_settings(operation='check')
        if settings is None:
            return False

        def work(_cancel):
            from .app import Runner

            def emit(event):
                if event.get('type') == 'paused':
                    ui.events.put(event)

            try:
                runner = Runner(settings, emit, operation=SCREEN_OPERATION, reward_guide_capture=capture,
                                observation_wait_for_foreground=True)
                return capture.result(ui._native_run.run(runner))
            except (Stopped, KeyboardInterrupt):
                return capture.receipt or _receipt('stopped')
            except (OSError, RuntimeError, ValueError):
                return capture.receipt or _receipt('unverified')

        def present(receipt):
            model.guide_message = _guide_feedback(receipt)
            model.guide_destination = None

        def failed(error):
            present(_receipt('stopped') if isinstance(error, Stopped) else None)

        return self._start(_GUIDE_ACTION, work, present, published=True, message='guide_message',
                           game=True, on_error=failed)

    def _start(self, title, work, present, *, published=False, message='message', game=False, on_error=None):
        if not self._idle or not self._active:
            return False
        ui, model = self.ui, self.model
        job, previous = object(), getattr(model, message)
        model.job = job
        setattr(model, message, f'正在{title}…')
        self.canvas.drag = None

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
                if on_error is not None:
                    on_error(error)
                else:
                    model.message = (str(error) if isinstance(error, (AutomationError, Stopped, screenshot_tool.ScreenshotError))
                                     else '未能读取或写入图片，请检查本地文件和窗口。')
                update()

        try:
            args = (title, lambda stop: work(stop.is_set), done, failed)
            accepted = ui._start_desktop_job(*args, game=True) if game else ui._submit_tool_job(*args)
        except Exception as error:
            failed(error)
            return False
        if not accepted:
            model.job = None
            setattr(model, message, previous)
        update()
        return bool(accepted)


def build_screenshot_panel(parent, ui):
    if not hasattr(ui, '_screenshot_tool_state'):
        ui._screenshot_tool_state = _State()
    return ScreenshotPanel(parent, ui, ui._screenshot_tool_state)
