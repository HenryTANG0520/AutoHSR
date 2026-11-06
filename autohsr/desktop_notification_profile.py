"""Private, local form for creating a notification profile."""

import tkinter as tk
from tkinter import ttk

from . import theme
from .desktop_dialogs import place_dialog
from .notify_profiles import PROVIDERS, NotifyError, loads
from .notify_providers import BOOLEAN, INTEGER, OPTIONS, REQUIRED, URL_FIELDS


_JSON_FIELDS = {'headers', 'body', 'data'}
_MASKED = URL_FIELDS | _JSON_FIELDS | {
    'api_url', 'path', 'access_token', 'client_secret', 'corpsecret', 'password', 'token',
    'key', 'device_key', 'pushkey', 'sendkey', 'sctkey', 'sign', 'secret',
}
_TARGET_HINTS = {
    'onebot': '接收对象至少填一项 user_id / group_id。',
    'gocqhttp': '接收对象至少填一项 user_id / group_id。',
    'smtp': '发件与收件地址可分别填 From、To，或共用 user。认证还需 password。',
    'wechatworkbot': '至少填一项 key / webhook_url。',
    'bark': '至少填一项 key / device_key。',
    'pushdeer': '至少填一项 token / pushkey。',
    'qqbot': '接收对象至少填一项 openid / group_openid。',
}


def _parameter(name, value):
    if name in BOOLEAN or name in INTEGER or name in _JSON_FIELDS or (name == 'To' and value.lstrip().startswith('[')):
        try:
            return loads(value)
        except NotifyError:
            raise NotifyError(f'{name} 需要有效的 JSON 值。') from None
    return value


class _NotificationProfileDialog(tk.Toplevel):
    def __init__(self, ui, store):
        super().__init__(ui.root)
        self.withdraw()
        self.transient(ui.root)
        self.title('AutoHSR · 通知')
        self.ui, self.store = ui, store
        self.saved_id = None
        self.active_provider = ''
        self.fields = {}
        self.pad = round(8 * ui.ui_scale)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body = ttk.Frame(self, style='Card.TFrame', padding=2 * self.pad)
        body.grid(row=0, column=0, sticky='nsew')
        body.columnconfigure(1, weight=1)
        body.rowconfigure(4, weight=1, minsize=4 * self.pad)
        ttk.Label(body, text='新建通知配置', style='CardTitle.TLabel').grid(row=0, columnspan=2, sticky='w')
        ttk.Label(body, text='配置名称 *', style='Card.TLabel').grid(row=1, sticky='w', pady=(self.pad, 0))
        self.identity = ttk.Entry(body, width=20, exportselection=False)
        self.identity.grid(row=1, column=1, sticky='ew', pady=(self.pad, 0))
        ttk.Label(body, text='通知渠道 *', style='Card.TLabel').grid(row=2, sticky='w', pady=(self.pad, 0))
        self.provider = ttk.Combobox(body, values=PROVIDERS, state='readonly', width=20)
        self.provider.grid(row=2, column=1, sticky='ew', pady=(self.pad, 0))
        self.provider.bind('<<ComboboxSelected>>', self._change_provider)
        self.provider.bind('<MouseWheel>', self._scroll)
        self.hint = theme.wrapped_label(body, style='CardHint.TLabel', text='请选择通知渠道。')
        self.hint.grid(row=3, columnspan=2, sticky='ew', pady=(self.pad, 0))

        viewport = ttk.Frame(body, style='Card.TFrame')
        viewport.grid(row=4, columnspan=2, sticky='nsew', pady=(self.pad, 0))
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, width=1, height=1, background=theme.CARD, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.form = ttk.Frame(self.canvas, style='Card.TFrame')
        self.form.columnconfigure(1, weight=1)
        window = self.canvas.create_window(0, 0, window=self.form, anchor='nw')
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.form.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox(window)))
        self.bind('<MouseWheel>', self._scroll)

        theme.wrapped_label(body, style='CardHint.TLabel', text=(
            '* 为必填，空白可选项沿用默认。凭据、网址及请求内容以掩码显示。'
            'JSON 请填单行，SMTP 的 To 可填地址或 JSON 数组。'
        )).grid(row=5, columnspan=2, sticky='ew', pady=(self.pad, 0))
        self.feedback = theme.wrapped_label(body, style='Warning.TLabel', text='')
        self.feedback.grid(row=6, columnspan=2, sticky='ew', pady=(self.pad, 0))

        footer = ttk.Frame(self, style='Footer.TFrame', padding=self.pad)
        footer.grid(row=1, column=0, sticky='ew')
        ttk.Button(footer, text='取消', style='Footer.TButton', command=self.destroy).pack(side='left')
        self.save_button = ttk.Button(footer, text='加密保存配置', style='Primary.TButton', command=self._save)
        self.save_button.pack(side='right')
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.bind('<Escape>', self._cancel)
        place_dialog(self, ui.root, (68 * self.pad, 76 * self.pad), (50 * self.pad, 51 * self.pad))

    def _cancel(self, _event):
        self.destroy()
        return 'break'

    def _change_provider(self, _event=None):
        provider = self.provider.get()
        if provider == self.active_provider or provider not in OPTIONS:
            return
        for widget in self.form.winfo_children():
            widget.destroy()
        self.fields.clear()
        self.active_provider = provider
        self.feedback.configure(text='')
        self.hint.configure(text=_TARGET_HINTS.get(provider, '请填写当前渠道的连接参数。'))
        required = REQUIRED.get(provider, '').split()
        for row, name in enumerate([*OPTIONS[provider].split(), 'allow_insecure']):
            label = name + (' *' if name in required else '')
            if name in _JSON_FIELDS:
                label += ' · JSON'
            elif name in INTEGER:
                label += ' · 整数'
            ttk.Label(self.form, text=label, style='Card.TLabel').grid(
                row=row, column=0, sticky='w', padx=(0, self.pad), pady=(0, self.pad))
            if name in BOOLEAN:
                field = ttk.Combobox(self.form, values=('', 'true', 'false'), state='readonly', width=16)
                field.bind('<MouseWheel>', self._scroll)
            else:
                field = ttk.Entry(self.form, show='•' if name in _MASKED else '', width=16, exportselection=False)
            field.grid(row=row, column=1, sticky='ew', pady=(0, self.pad))
            field.bind('<FocusIn>', self._reveal)
            self.fields[name] = field
        self.canvas.yview_moveto(0)

    def _scroll(self, event):
        if event.delta:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def _reveal(self, event):
        bounds = self.canvas.bbox('all')
        height = self.canvas.winfo_height()
        if not bounds or bounds[3] <= height:
            return
        top = event.widget.winfo_y()
        bottom = top + event.widget.winfo_height()
        offset = self.canvas.canvasy(0)
        if top < offset:
            self.canvas.yview_moveto(top / bounds[3])
        elif bottom > offset + height:
            self.canvas.yview_moveto((bottom - height) / bounds[3])

    def _save(self):
        if self.ui.busy or self.ui.closing:
            self.feedback.configure(text='请等当前操作结束后保存。')
            return
        provider = self.provider.get()
        if not provider or provider != self.active_provider:
            self.feedback.configure(text='请选择通知渠道。')
            return
        try:
            params = {}
            for name, field in self.fields.items():
                value = field.get()
                if value.strip():
                    params[name] = _parameter(name, value)
            saved = self.store.save(dict(id=self.identity.get(), provider=provider, params=params), replace=False)
        except NotifyError as error:
            self.feedback.configure(text=str(error))
            return
        except (OSError, ValueError):
            self.feedback.configure(text='配置未保存，请核对参数及本地存储。')
            return
        self.saved_id = saved['id']
        self.destroy()


def ask_new_profile(ui, store):
    """Return only the saved alias. All parameter widgets belong to this dialog."""
    if ui.root.tk.call('grab', 'current', str(ui.root)):
        return None
    dialog = _NotificationProfileDialog(ui, store)
    dialog.deiconify()
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.identity.focus_set()
    ui.root.wait_window(dialog)
    return dialog.saved_id
