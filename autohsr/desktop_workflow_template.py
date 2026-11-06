"""Collect a local PNG template from an explicitly selected screenshot region."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from . import screenshot_tool, theme
from .desktop_dialogs import place_dialog
from .desktop_screenshot import SelectionCanvas
from .models import AutomationError, Stopped
from .screenshot_tool import TemplateCapture


class WorkflowTemplateDialog(tk.Toplevel):
    def __init__(self, ui, owner, *, base_dir, capture_current=None):
        super().__init__(owner)
        self.withdraw()
        self.transient(owner)
        self.title('AutoHSR · 采集模板')
        self.ui, self.base_dir = ui, Path(base_dir)
        self.capture_current = capture_current
        self.result = None
        self.image = self.box = self.job = None
        self.source = ''
        self.message = '打开本地图片，或手动切到游戏前台采集。拖动鼠标框选模板。'
        scale = ui.ui_scale
        pad = round(8 * scale)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        page = ttk.Frame(self, padding=pad, style='Card.TFrame')
        page.grid(row=0, column=0, sticky='nsew')
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text='采集模板', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
        actions = ttk.Frame(page, style='Card.TFrame')
        actions.grid(row=1, column=0, sticky='ew', pady=(pad, pad))
        self.local_button = ttk.Button(actions, text='打开本地图片…', command=self.open_image, style='Compact.TButton')
        self.game_button = ttk.Button(actions, text='等待游戏前台', command=self.capture, style='Compact.TButton')
        self.all_button = ttk.Button(actions, text='选中全图', command=self.select_all, style='Compact.TButton')
        for button in (self.local_button, self.game_button, self.all_button):
            button.pack(side='left', padx=(0, pad))

        self.canvas = SelectionCanvas(page, height=round(300 * scale),
                                      can_select=lambda: self._idle, on_select=self._select)
        self.canvas.grid(row=2, column=0, sticky='nsew')
        self.coordinates = theme.wrapped_label(page, style='CardHint.TLabel')
        self.coordinates.grid(row=3, column=0, sticky='ew', pady=(pad, 0))
        self.feedback = theme.wrapped_label(page, style='CardHint.TLabel')
        self.feedback.grid(row=4, column=0, sticky='ew', pady=(pad, 0))

        footer = ttk.Frame(self, padding=pad, style='Footer.TFrame')
        footer.grid(row=1, column=0, sticky='ew')
        self.cancel_button = ttk.Button(footer, command=self.cancel, style='Footer.TButton')
        self.cancel_button.pack(side='left')
        self.save_button = ttk.Button(footer, text='另存并绑定…', command=self.save, style='Primary.TButton')
        self.save_button.pack(side='right')
        self.bind('<Escape>', self.cancel)
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self._refresh()
        place_dialog(self, owner, (round(750 * scale), round(535 * scale)),
                     (round(500 * scale), round(410 * scale)))

    @property
    def _idle(self):
        return self.job is None and not self.ui.busy and not self.ui.closing

    def _refresh(self):
        idle = self._idle
        for button, enabled in ((self.local_button, idle), (self.game_button, idle),
                                (self.all_button, idle and self.image is not None),
                                (self.save_button, idle and self.box is not None)):
            button.state(('!disabled' if enabled else 'disabled',))
        self.cancel_button.configure(text='停止' if self.job is not None else '取消')
        coords = '尚无图片'
        if self.image is not None:
            coords = f'{self.source} · {self.image.width} × {self.image.height}'
            if self.box is not None:
                left, top, right, bottom = self.box
                coords += f' · 选区 {right - left} × {bottom - top} 像素'
        self.coordinates.configure(text=coords)
        self.feedback.configure(text=self.message)
        self.canvas.show(self.image, self.box)

    def _select(self, box):
        self.box = box
        self.message = '已框选区域。请选择新的 PNG 文件。' if box is not None else '请框选有面积的区域。'
        self._refresh()

    def select_all(self):
        if self._idle and self.image is not None:
            self._select((0, 0, *self.image.size))

    def _load_image(self, image, source):
        self.image, self.box, self.source = image, None, source
        self.message = '已读取画面。请切回此窗口，框选模板。' if source == '游戏截图' else '请拖动鼠标框选模板。'

    def open_image(self):
        if not self._idle:
            return
        path = filedialog.askopenfilename(parent=self, title='打开模板来源图片', initialdir=str(self.base_dir),
                                          filetypes=(('PNG 或 JPEG', '*.png *.jpg *.jpeg'),))
        if path and self._idle:
            self._submit('读取本地图片', lambda cancel: screenshot_tool.open_template_image(path, cancel),
                         lambda image: self._load_image(image, '本地图片'))

    def capture(self):
        if not self._idle:
            return
        settings = self.ui._read_settings(operation='check')
        if settings is None:
            self.message = '请核对游戏连接设置。'
            self._refresh()
            return
        self._submit('采集游戏客户区',
                     lambda cancel: screenshot_tool.capture_game(settings, cancel, foreground_only=True),
                     lambda image: self._load_image(image, '游戏截图'),
                     waiting=f'请在 {screenshot_tool.FOREGROUND_WAIT} 秒内手动切回游戏。')

    def save(self):
        if not self._idle or self.box is None:
            return
        image, box, base_dir = self.image, self.box, self.base_dir
        path = filedialog.asksaveasfilename(parent=self, title='在流程目录内另存新模板', initialdir=str(base_dir),
                                            defaultextension='.png', filetypes=(('PNG', '*.png'),),
                                            confirmoverwrite=False)
        if path and self._idle and self.image is image and self.box == box:
            if self.capture_current is not None and not self.capture_current():
                self.message = '当前流程另存位置或编辑状态已变化。请返回可视编辑核对后重新采集。'
                self._refresh()
                return
            self._submit('保存模板', lambda cancel: screenshot_tool.save_template(image, box, path, base_dir, cancel),
                         self._complete)

    def _complete(self, captured):
        self.result = captured
        self.destroy()

    def cancel(self, _event=None):
        if self.job is None:
            self.destroy()
        elif not self.ui.stop_requested.is_set():
            self.ui._stop()
            self.message = '正在停止…'
            self._refresh()
        return 'break'

    def _submit(self, title, work, present, *, waiting=None):
        if not self._idle:
            return
        ui = self.ui
        job = self.job = object()
        self.canvas.drag = None
        self.message = waiting or f'正在{title}…'
        self._refresh()

        def finish(value=None, *, error=None):
            if ui.closing or not self.winfo_exists() or self.job is not job:
                return
            self.job = None
            if isinstance(error, Stopped) or ui.stop_requested.is_set() and error is None:
                self.message = (f'PNG 已保存，已停止绑定 · {value.path}' if isinstance(value, TemplateCapture)
                                else '模板采集已停止。')
            elif error is not None:
                self.message = (str(error) if isinstance(error, (ValueError, AutomationError))
                                else '无法读取图片或写入模板，请核对所选文件和权限。')
            else:
                present(value)
            if self.winfo_exists():
                self._refresh()

        try:
            accepted = ui._submit_tool_job(title, lambda stop: work(stop.is_set), finish,
                                           lambda error: finish(error=error))
        except Exception as error:
            finish(error=error)
            return
        if not accepted:
            finish(error=AutomationError('当前有其他操作，请结束后重试。'))


def ask_workflow_template(ui, owner, *, base_dir, capture_current=None) -> TemplateCapture | None:
    """Return the verified PNG receipt only when the user completed the modal."""
    previous = owner.grab_current()
    if (base_dir is None or ui.busy or ui.closing
            or previous is not None and (previous is not owner or owner.grab_status() != 'local')):
        return None
    focus = owner.focus_get()
    dialog = WorkflowTemplateDialog(ui, owner, base_dir=base_dir, capture_current=capture_current)
    try:
        dialog.deiconify()
        dialog.wait_visibility()
        dialog.grab_set()
        dialog.local_button.focus_set()
        owner.wait_window(dialog)
    except tk.TclError:
        if not ui.closing and dialog.winfo_exists():
            raise
    finally:
        if not ui.closing and owner.winfo_exists():
            if previous is owner and owner.grab_current() is None:
                owner.grab_set()
            if focus is not None and focus.winfo_exists() and owner.focus_get() is not None:
                focus.focus_set()
    return dialog.result
