"""Support preferences as game-style local drafts; never inspect an account."""
from dataclasses import asdict,replace
import json
import tkinter as tk
from tkinter import ttk

from . import theme
from .config import SettingsError
from .setting_choices import SettingChoice
from .support_profiles import catalogue,preferences,validate

FALLBACKS={'停止挑战':'stop','另借其他好友':'friend','不借支援继续':'skip'}


def variables(ui):
    ui.support_rows=tk.StringVar(value=json.dumps(ui.settings.support_preferences,ensure_ascii=False))
    ui.support_pages=tk.StringVar(value=str(ui.settings.support_scroll_pages))
    ui.support_fallback=tk.StringVar(value=next((label for label,key in FALLBACKS.items() if key==ui.settings.support_fallback),str(ui.settings.support_fallback)))
    ui.support_summary=tk.StringVar()
    ui.form_variables.extend((ui.support_rows,ui.support_pages,ui.support_fallback))
    def refresh(*_):
        try:
            rows=preferences(json.loads(ui.support_rows.get()))
            first=rows[0] if rows else None
            title=(catalogue()[first.character]['name'] if first.character else first.friend) if first else '自动选择好友'
            ui.support_summary.set(title+(f' 等{len(rows)}项' if len(rows)>1 else ''))
        except (ValueError,TypeError):ui.support_summary.set('候选待检查')
    for variable in (ui.support_rows,):variable.trace_add('write',refresh)
    refresh()


def values(ui):
    try:raw=json.loads(ui.support_rows.get())
    except (ValueError,TypeError):raise SettingsError('support_preferences','支援候选格式无效，请重新选择。') from None
    rows=[asdict(item) for item in preferences(raw)]
    try:pages=int(ui.support_pages.get())
    except ValueError:raise SettingsError('support_scroll_pages','最多查找页数须为1～20的整数。') from None
    try:fallback=FALLBACKS[ui.support_fallback.get()]
    except KeyError:raise SettingsError('support_fallback','请选择未找到候选时的处理方式。') from None
    result=dict(support_preferences=rows,support_scroll_pages=pages,support_fallback=fallback)
    validate(replace(ui.settings,**result));return result


def show(ui):
    if ui.busy:return
    current=getattr(ui,'support_dialog',None)
    if current is not None and current.winfo_exists():current.lift();return
    SupportDialog(ui)


class SupportDialog:
    def __init__(self,ui):
        from .desktop_dialogs import DetailClose,DetailSurface,FRAME,FOOTER_HEIGHT,PAPER,TRANSPARENT,place_dialog
        self.ui=ui;self.origin=theme.focus_widget(ui.root);self.photos={}
        initial_error=''
        try:self.rows=[asdict(item) for item in preferences(json.loads(ui.support_rows.get()))]
        except (ValueError,TypeError):
            self.rows=[];initial_error='原候选格式无效，请重新选择；取消保留原设置。'
        self.window=window=ui.support_dialog=tk.Toplevel(ui.root)
        window.withdraw();window.transient(ui.root);window.title('支援角色');window._hsr_scale=ui.ui_scale
        window.overrideredirect(True);window.configure(bg=TRANSPARENT)
        import sys
        if sys.platform=='win32':window.wm_attributes('-transparentcolor',TRANSPARENT)
        d=lambda n:round(n*ui.ui_scale)
        plate=DetailSurface(window,ui.ui_scale,'支援角色');plate.place(x=0,y=0,relwidth=1,relheight=1)
        window.tk.call('lower',str(plate))
        ui.style.configure('Support.Dialog.TFrame',background=PAPER)
        ui.style.configure('Support.Dialog.TLabel',background=PAPER,foreground=theme.TEXT,font=theme.native_font(window,12))
        ui.style.configure('Support.Treeview',background=theme.SETTING_VALUE,fieldbackground=theme.SETTING_VALUE,
            rowheight=d(46),font=theme.native_font(window,12))
        ui.style.configure('Support.Treeview.Heading',background=theme.SETTING_ROW,
            foreground=theme.TEXT,font=theme.native_font(window,11),padding=d(6))
        body=ttk.Frame(window,style='Support.Dialog.TFrame');body.grid(row=1,column=0,sticky='nsew',padx=d(34),pady=d(10))
        window.columnconfigure(0,weight=1);window.rowconfigure(0,minsize=d(82));window.rowconfigure(1,weight=1)
        window.rowconfigure(2,minsize=d(FRAME+FOOTER_HEIGHT));body.columnconfigure(1,weight=1);body.rowconfigure(1,weight=1)
        ttk.Label(body,text='候选角色 · 每页按顺序选择',style='Support.Dialog.TLabel').grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,d(6)))
        listing=ttk.Frame(body,style='Support.Dialog.TFrame');listing.grid(row=1,column=0,columnspan=2,sticky='nsew')
        listing.columnconfigure(0,weight=1);listing.rowconfigure(0,weight=1)
        self.table=ttk.Treeview(listing,columns=('role','friend'),show='tree headings',height=3,
            selectmode='browse',style='Support.Treeview')
        self.table.heading('#0',text='');self.table.column('#0',width=d(55),minwidth=d(55),stretch=False)
        for name,label in (('role','角色'),('friend','好友')):
            self.table.heading(name,text=label,anchor='w');self.table.column(name,width=d(240),minwidth=d(100))
        self.table.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(listing,orient='vertical',command=self.table.yview);scroll.grid(row=0,column=1,sticky='ns')
        self.table.configure(yscrollcommand=scroll.set);self.table.bind('<<TreeviewSelect>>',self.selected)
        self.character=tk.StringVar();self.friend=tk.StringVar();self.pages=tk.StringVar(value=ui.support_pages.get())
        self.fallback=tk.StringVar(value=ui.support_fallback.get());self.error=tk.StringVar(value=initial_error)
        self.labels={row['name']:key for key,row in catalogue().items()};self.form_snapshot=('','')
        self.role=self.field(body,2,'角色（可选）',self.character,tuple(self.labels),editable=True)
        self.character.trace_add('write',lambda *_:self.role.configure(values=tuple(name for name in self.labels if self.character.get().strip() in name)))
        self.field(body,3,'好友昵称（完整，可选）',self.friend)
        actions=ttk.Frame(body,style='Support.Dialog.TFrame');actions.grid(row=4,column=0,columnspan=2,sticky='w',pady=d(6))
        self.buttons={}
        for index,(label,command) in enumerate((('添加候选',self.add),('更新选中',self.update),('移除',self.remove),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1)))):
            button=ttk.Button(actions,text=label,command=command,style='Panel.TButton')
            button.grid(row=0,column=index,padx=(0,d(6)));self.buttons[label]=button
        self.field(body,5,'每轮查找页数（1～20）',self.pages)
        self.field(body,6,'未找到候选',self.fallback,tuple(FALLBACKS))
        error=theme.wrapped_label(body,textvariable=self.error,style='Support.Dialog.TLabel')
        error.grid(row=7,column=0,columnspan=2,sticky='ew',pady=(d(4),0))
        cancel=DetailClose(window,ui.ui_scale,self.close,text='取消')
        self.confirm=DetailClose(window,ui.ui_scale,self.apply,text='应用',symbol='confirm')
        def layout(event):
            if event.widget is not window:return
            width=min(d(288),(event.width-d(98))//2);center=(event.width+d(FRAME))/2;y=event.height-d(FRAME+FOOTER_HEIGHT/2)
            cancel.place(x=center-d(8)-width,y=y,width=width,height=d(46.4),anchor='w')
            self.confirm.place(x=center+d(8),y=y,width=width,height=d(46.4),anchor='w')
        window.bind('<Configure>',layout,add='+');window.bind('<Escape>',lambda _:self.close())
        window.protocol('WM_DELETE_WINDOW',self.close)
        ui.support_editor=self;self.refresh()
        window.update_idletasks()
        height=body.winfo_reqheight()+d(82+FRAME+FOOTER_HEIGHT+20)
        place_dialog(window,ui.root,(d(820),height),(d(690),d(520)),padding=d(12))
        window.deiconify();window.wait_visibility();window.grab_set();self.role.focus_force()

    def field(self,parent,row,label,variable,options=None,editable=False):
        d=lambda n:round(n*self.ui.ui_scale)
        ttk.Label(parent,text=label,style='Support.Dialog.TLabel').grid(row=row,column=0,sticky='w',padx=(0,d(14)),pady=d(5))
        field=(SettingChoice(parent,textvariable=variable,values=options,state='normal' if editable else 'readonly',width=10)
               if options is not None else ttk.Entry(parent,textvariable=variable,width=10))
        field.grid(row=row,column=1,sticky='ew',pady=d(5));return field

    def index(self):
        selected=self.table.selection();return int(selected[0]) if selected else None

    def selected(self,_=None):
        index=self.index()
        if index is not None:
            row=self.rows[index]
            self.character.set(catalogue()[row['character']]['name'] if row['character'] else '')
            self.friend.set(row['friend']);self.form_snapshot=(self.character.get(),self.friend.get());self.error.set('')
        self.update_buttons()

    def update_buttons(self):
        index=self.index()
        for label,enabled in (('更新选中',index is not None),('移除',index is not None),
                ('上移',index is not None and index>0),('下移',index is not None and index<len(self.rows)-1)):
            self.buttons[label].configure(state='normal' if enabled else 'disabled')

    def refresh(self,index=None):
        from PIL import Image,ImageTk
        from .config import RESOURCE_ROOT
        self.table.delete(*self.table.get_children())
        for position,row in enumerate(self.rows):
            key=row['character'];portrait=None
            if key:
                if key not in self.photos:
                    path=RESOURCE_ROOT/'assets/upstream/March7thAssistant/support'/catalogue()[key]['file']
                    with Image.open(path) as source:
                        self.photos[key]=ImageTk.PhotoImage(source.convert('RGBA').resize((round(38*self.ui.ui_scale),)*2,Image.Resampling.LANCZOS),master=self.window)
                portrait=self.photos[key]
            self.table.insert('','end',iid=str(position),image=portrait or '',
                values=(catalogue()[key]['name'] if key else '任意角色',row['friend'] or '任意好友'))
        if index is not None and self.table.exists(str(index)):
            self.table.selection_set(str(index));self.table.see(str(index))
        self.update_buttons()

    def candidate(self):
        name=self.character.get().strip()
        if name and name not in self.labels:raise ValueError('请从列表选择完整角色名；也可只填写好友昵称。')
        return asdict(preferences([dict(character=self.labels[name] if name else '',friend=self.friend.get())])[0])

    def change(self,update=False):
        try:
            index=self.index() if update else len(self.rows)
            if index is None:raise ValueError('请先选择要更新的候选。')
            candidate=self.candidate();changed=list(self.rows)
            if update:changed[index]=candidate
            else:changed.append(candidate)
            preferences(changed)
        except (ValueError,TypeError) as error:self.error.set(str(error));return
        self.rows=changed;self.error.set('');self.refresh(index)

    def add(self):self.change()
    def update(self):self.change(True)

    def remove(self):
        index=self.index()
        if index is not None:
            self.rows.pop(index);self.refresh(min(index,len(self.rows)-1));self.error.set('')
            if not self.rows:self.character.set('');self.friend.set('');self.form_snapshot=('','')

    def move(self,delta):
        index=self.index()
        if index is not None and 0<=index+delta<len(self.rows):
            self.rows[index],self.rows[index+delta]=self.rows[index+delta],self.rows[index]
            self.refresh(index+delta)

    def apply(self):
        try:
            changed=list(self.rows)
            if (self.character.get(),self.friend.get())!=self.form_snapshot:
                candidate=self.candidate();index=self.index()
                if index is None:changed.append(candidate)
                else:changed[index]=candidate
                preferences(changed)
            try:pages=int(self.pages.get())
            except ValueError:raise ValueError('最多查找页数须为1～20的整数。') from None
            if not changed and self.fallback.get()!='停止挑战':
                raise ValueError('未指定候选时，请选择“停止挑战”。')
            try:fallback=FALLBACKS[self.fallback.get()]
            except KeyError:raise ValueError('请选择未找到候选时的处理方式。') from None
            result=replace(self.ui.settings,support_preferences=changed,support_scroll_pages=pages,
                           support_fallback=fallback)
            validate(result)
        except (ValueError,TypeError,KeyError) as error:self.error.set(str(error));return
        ui=self.ui;loading=ui._loading;ui._loading=True
        try:
            ui.support_rows.set(json.dumps(changed,ensure_ascii=False));ui.support_pages.set(str(pages));ui.support_fallback.set(self.fallback.get())
        finally:ui._loading=loading
        if ui.input_error_field in ('support_preferences','support_scroll_pages','support_fallback'):ui._clear_input_error()
        ui._form_changed();self.close()

    def close(self):
        focused=theme.focus_widget(self.ui.root);owned=focused is not None and focused.winfo_toplevel() is self.window
        self.ui.support_dialog=None;self.window.destroy()
        if self.origin is not None and self.origin.winfo_exists() and self.origin.winfo_ismapped():
            (self.origin.focus_force if owned else self.origin.focus_set)()
        return 'break'
