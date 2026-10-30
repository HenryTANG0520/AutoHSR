"""Saved power targets and explicit desktop mode; no account-history reads."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from . import theme
from .config import SettingsError
from .dungeons import BY_KEY, CATEGORIES
from .setting_choices import SettingChoice
from .weekly_plan import DAYS

MODES = ('单副本', '体力计划')
REPEATS = ('按剩余次数', '每次重复')


def variables(ui):
    ui.power_mode = tk.StringVar(value=MODES[bool(ui.settings.power_plan_enabled)])
    ui.power_rows = tk.StringVar(value=json.dumps(ui.settings.power_plan, ensure_ascii=False))
    ui.power_repeat = tk.StringVar(value=REPEATS[bool(ui.settings.power_plan_keep)])
    ui.power_fill = tk.BooleanVar(value=ui.settings.power_plan_fill)
    ui.echo_enabled = tk.BooleanVar(value=ui.settings.echo_of_war_enabled)
    ui.echo_day = tk.StringVar(value=DAYS[ui.settings.echo_of_war_start_day-1])
    ui.echo_target = tk.StringVar(value=ui.settings.echo_of_war_target)
    ui.echo_location = tk.StringVar(value=ui.settings.echo_of_war_location)
    ui.form_variables.extend((ui.power_mode, ui.power_rows, ui.power_repeat, ui.power_fill,
                             ui.echo_enabled, ui.echo_day, ui.echo_target, ui.echo_location))


def rows(ui):
    from .power_plan import items
    try:
        raw = json.loads(ui.power_rows.get())
    except (ValueError, TypeError) as error:
        raise SettingsError('power_plan', '体力计划格式无效，请重新编辑条目。') from error
    return [item.to_dict() for item in items(raw)]


def settings_values(ui):
    return dict(power_plan_enabled=ui.power_mode.get() == MODES[1], power_plan=rows(ui),
                power_plan_keep=ui.power_repeat.get() == REPEATS[1], power_plan_fill=ui.power_fill.get(),
                echo_of_war_enabled=ui.echo_enabled.get(), echo_of_war_start_day=DAYS.index(ui.echo_day.get())+1,
                echo_of_war_target=ui.echo_target.get(), echo_of_war_location=ui.echo_location.get())


def display_rows(ui):
    try:return rows(ui)
    except (ValueError,TypeError):return []


def preview(ui):
    count = len(display_rows(ui))
    return f'体力计划 {count} 项' if count else '历战优先' if ui.echo_enabled.get() else '体力计划待添加'


def has_planar(ui):
    return any(item['category']=='planar' for item in display_rows(ui)) or ui.power_fill.get() and ui.dungeon_category.get()=='饰品提取'


def show(ui):
    ui._show_daily_tasks()
    ui.settings_tabs.select(ui.settings_sections['power'])
    ui.root.after_idle(ui.power_plan_list.focus_set)


def progress(ui, event):
    count=event.get('battle_completed');spent=event.get('stamina_spent')
    if type(count) is not int or count<0 or type(spent) is not int or spent<0:return
    from .ux import reported_battle_metrics
    detail=progress_rows(event.get('rows'))
    label,status,_=ui.table.item('battle','values')
    ui.table.item('battle',values=(label,status,detail),metrics=reported_battle_metrics(event))
    ui._progress(spent)
    active=event.get('active_row');values=event.get('rows')
    if type(active) is int and isinstance(values,list):
        target = values[active].get('target') if 0<=active<len(values) and isinstance(values[active],dict) else None
        target = '默认补刷' if active==-1 else '历战优先' if active==-2 else target
        if target:ui.current_task.set('体力计划 · '+str(target))


def progress_rows(values):
    if not isinstance(values,list):return '条目进度待核对'
    lines=[]
    for index,item in enumerate(values):
        if not isinstance(item,dict):return '条目进度待核对'
        amounts=[item.get(k) for k in ('count','before','done','remaining')]
        if any(type(v) is not int or v<0 for v in amounts) or amounts[0]<1 or sum(amounts[1:])!=amounts[0]:return '条目进度待核对'
        lines.append(f"{index+1}. {item.get('target','副本未记录')} · {item.get('location','地点未记录')}\n"
                     f"目标 {amounts[0]} 次 · 此前 {amounts[1]} 次 · 本次 {amounts[2]} 次 · 本目标剩余 {amounts[3]} 次")
    return '\n\n'.join(lines)


def goals_pending(report):
    data=report.get('power_plan') or {}
    echo=data.get('weekly_echo') or {}
    return data.get('goal_complete') is False or echo.get('due') is True and echo.get('state') not in ('complete','not_due')


def result_text(report, *, reused=False):
    data=report.get('power_plan')
    if not isinstance(data,dict) or not data:return None
    prefix='原日常体力计划' if reused else '体力计划'
    valid = data.get('run_status')=='complete' and report.get('report_saved') is True
    values,before,done=data.get('items'),data.get('before'),data.get('done')
    if not all(isinstance(v,list) for v in (values,before,done)) or len(values)!=len(before) or len(values)!=len(done):
        return prefix+' · 次数待核对'
    remaining=[]
    for item,a,b in zip(values,before,done):
        if not isinstance(item,dict) or any(type(v) is not int or v<0 for v in (a,b,item.get('count'))) or item['count']<1:
            return prefix+' · 次数待核对'
        if a+b>item['count']:return prefix+' · 次数待核对'
        remaining.append(item['count']-a-b)
    finished=data.get('goal_complete') is True and not any(remaining)
    text=prefix+' · '+('本次已结束' if valid else '本次未完整结束')
    if values:text+=' · '+('目标已完成' if finished else f'剩余目标 {sum(remaining)} 次')
    echo=data.get('weekly_echo')
    if isinstance(echo,dict):
        state=echo.get('state');count=echo.get('completed')
        label='周额度已核实用尽' if state=='complete' else '未到期' if state=='not_due' else '本次预算不足' if state=='limited' else '额度待核对'
        text+=f"\n原周 {echo.get('week','未记录')} · 历战{label}"
        if type(count) is int and 0<=count<=3:text+=f' · 本次 {count} 次'
    return text


def present_result(ui, report, *, reused=False):
    text=result_text(report,reused=reused)
    if text is None:return None
    from .ux import reported_battle_metrics
    data=report['power_plan']
    ui._has_run=True
    if ui._daily_result_signature is None:ui._daily_result_signature=ui._daily_form_signature()
    status='本次结束' if data.get('run_status')=='complete' and report.get('report_saved') is True else '未完整结束'
    if reused:status='原日常'+status
    values,before,done=data.get('items'),data.get('before'),data.get('done')
    detail=text
    if all(isinstance(value,list) for value in (values,before,done)) and len(values)==len(before)==len(done):
        checked=[]
        for item,a,b in zip(values,before,done):
            if isinstance(item,dict) and all(type(n) is int for n in (a,b,item.get('count'))):
                checked.append(dict(item,before=a,done=b,remaining=item['count']-a-b))
        detail+='\n\n'+progress_rows(checked)
    ui.table.item('battle',values=('日常副本挑战',status,detail),has_result=True,metrics=reported_battle_metrics(report))
    return text


class PowerPlanEditor(ttk.Frame):
    def __init__(self, parent, ui):
        from .desktop_settings import SettingRow, BooleanSetting
        super().__init__(parent, style='Footer.TFrame')
        self.ui = ui
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1, minsize=round(96*ui.ui_scale))
        d = lambda n: round(n*ui.ui_scale)
        def choice(index, title, variable, values, attribute):
            line = SettingRow(self, ui.ui_scale, index, title)
            field = SettingChoice(line.value, textvariable=variable, values=values, state='readonly',
                                  style='Settings.TCombobox', width=10, justify='center', font=theme.native_font(self, 12))
            line.place_control(field); setattr(ui, attribute, field); ui.setting_controls.append(field)
        choice(0, '刷本模式', ui.power_mode, MODES, 'power_mode_combo')
        self.budget_note=tk.StringVar()
        budget = SettingRow(self, ui.ui_scale, 1, '本次开拓力上限', variable=self.budget_note)
        field = ttk.Entry(budget.value, textvariable=ui.stamina_limit, width=10, style='Settings.TEntry', justify='center')
        budget.place_control(field); ui.power_budget_entry = field; ui.setting_controls.append(field)
        choice(2, '次数处理', ui.power_repeat, REPEATS, 'power_repeat_combo')
        fill = SettingRow(self, ui.ui_scale, 3, '计划后补刷默认副本')
        field = BooleanSetting(fill.value, ui.power_fill); fill.place_control(field)
        ui.power_fill_combo = field; ui.setting_controls.append(field)
        body = ttk.Frame(self, style='Footer.TFrame'); body.grid(row=4, column=0, sticky='nsew', pady=d(8))
        body.columnconfigure(0, weight=1); body.rowconfigure(0, weight=1)
        ui.style.configure('Power.Treeview',background=theme.SETTING_VALUE,fieldbackground=theme.SETTING_VALUE,
            foreground=theme.TEXT,rowheight=d(44),font=theme.native_font(self,14))
        ui.style.configure('Power.Treeview.Heading',background=theme.SETTING_ROW,foreground=theme.TEXT,
            font=theme.native_font(self,12),padding=d(8))
        self.table = ui.power_plan_list = ttk.Treeview(body, columns=('category','target','location','count'),
            show='headings', selectmode='browse', height=4,style='Power.Treeview')
        for key, title, width in (('category','分类',170),('target','副本',210),('location','地点',230),('count','目标次数',100)):
            self.table.heading(key, text=title,anchor='center' if key=='count' else 'w')
            self.table.column(key, width=d(width), minwidth=d(65), stretch=True,anchor='center' if key=='count' else 'w')
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(body, orient='vertical', command=self.table.yview)
        scroll.grid(row=0, column=1, sticky='ns'); self.table.configure(yscrollcommand=scroll.set)
        self.table.bind('<Double-1>', lambda _: self.edit())
        self.table.bind('<Return>', lambda _: self.edit())
        actions = ttk.Frame(self, style='Footer.TFrame'); actions.grid(row=5, column=0, sticky='w')
        self.buttons = []
        for index, (title, command) in enumerate((('添加副本',lambda:self.edit(new=True)),('编辑',self.edit),
                ('移除',self.remove),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1)))):
            button = ttk.Button(actions, text=title, command=command, style='Panel.TButton')
            button.grid(row=0, column=index, padx=(0,d(8))); self.buttons.append(button); ui.setting_controls.append(button)
        echo = SettingRow(self, ui.ui_scale, 6, '历战优先',wide=True)
        field = BooleanSetting(echo.value, ui.echo_enabled); field.grid(row=0,column=0,sticky='nsew')
        ui.echo_enabled_combo = field; ui.setting_controls.append(field)
        button = ttk.Button(echo.value, text='选择副本与星期', command=self.edit_echo, style='Settings.TButton')
        button.grid(row=0,column=1,padx=d(8)); ui.setting_controls.append(button)
        ui.echo_config_button = button
        self.caption = tk.StringVar()
        hint = theme.wrapped_label(self, textvariable=self.caption, style='Settings.Note.TLabel')
        hint.grid(row=7,column=0,sticky='ew',pady=(d(8),0))
        self.tokens = [(variable, variable.trace_add('write', self.refresh)) for variable in
            (ui.power_rows, ui.power_fill, ui.target_name, ui.target_location, ui.challenge_count,ui.dungeon_category,
             ui.echo_enabled, ui.echo_day, ui.echo_target, ui.echo_location)]
        self.bind('<Destroy>',self.destroyed,add='+'); self.refresh()
        ui.power_editor = self

    def destroyed(self, event):
        if event.widget is self:
            for variable, token in self.tokens: variable.trace_remove('write',token)

    def refresh(self, *_):
        selection = self.table.selection()
        self.table.delete(*self.table.get_children())
        for index, item in enumerate(display_rows(self.ui)):
            self.table.insert('', 'end', iid=str(index), values=(BY_KEY[item['category']].label,item['target'],item['location'],item['count']))
        if selection and self.table.exists(selection[0]): self.table.selection_set(selection[0])
        info = []
        if self.ui.power_fill.get():info.append(f'默认补刷：{self.ui.target_name.get()} · {self.ui.target_location.get()} · 最多{self.ui.challenge_count.get()}次')
        if self.ui.echo_enabled.get():info.append(f'历战：{self.ui.echo_day.get()}04:00起 · {self.ui.echo_target.get()} · {self.ui.echo_location.get()}')
        self.caption.set('\n'.join(info))
        self.budget_note.set('所有条目共用 · 10～240，10的倍数'+(' · 已有沉浸器另计' if has_planar(self.ui) else ''))

    def selected(self):
        selection = self.table.selection()
        return int(selection[0]) if selection else None

    def replace(self, values, selected=None):
        self.ui.power_rows.set(json.dumps(values,ensure_ascii=False))
        if selected is not None and self.table.exists(str(selected)):
            self.table.selection_set(str(selected));self.table.see(str(selected))

    def remove(self):
        if self.ui.busy:return
        index = self.selected()
        if index is not None:
            values = rows(self.ui); values.pop(index); self.replace(values,min(index,len(values)-1))

    def move(self, delta):
        if self.ui.busy:return
        index = self.selected(); values = rows(self.ui)
        if index is not None and 0<=index+delta<len(values):
            values[index],values[index+delta] = values[index+delta],values[index]
            self.replace(values,index+delta)

    def edit(self, *, new=False):
        if self.ui.busy:return
        index = None if new else self.selected()
        if index is None and not new:return
        value = rows(self.ui)[index] if index is not None else None
        self.dialog(value, lambda item:self.commit(item,index))

    def commit(self, item, index):
        values=rows(self.ui)
        if index is None:values.append(item);index=len(values)-1
        else:values[index]=item
        from .power_plan import items
        items(values);self.replace(values,index)

    def edit_echo(self):
        if not self.ui.busy:
            value=dict(category='echo_of_war',target=self.ui.echo_target.get(),location=self.ui.echo_location.get(),count=3)
            self.dialog(value,self.commit_echo,echo=True)

    def commit_echo(self,item,day):
        self.ui.echo_target.set(item['target']);self.ui.echo_location.set(item['location']);self.ui.echo_day.set(day)

    def dialog(self, value, accept, *, echo=False):
        from .desktop_dialogs import DetailClose,DetailSurface,FRAME,FOOTER_HEIGHT,PAPER,TRANSPARENT,place_dialog
        ui=self.ui; window=ui.power_dialog=tk.Toplevel(ui.root); window.withdraw();window.transient(ui.root)
        title='历战优先' if echo else '编辑副本' if value else '添加副本';window.title(title)
        d=lambda n:round(n*ui.ui_scale)
        window._hsr_scale=ui.ui_scale;window.overrideredirect(True);window.configure(bg=TRANSPARENT)
        import sys
        if sys.platform=='win32':window.wm_attributes('-transparentcolor',TRANSPARENT)
        plate=DetailSurface(window,ui.ui_scale,title);plate.place(x=0,y=0,relwidth=1,relheight=1)
        window.tk.call('lower',str(plate))
        ui.style.configure('Power.Dialog.TFrame',background=PAPER)
        ui.style.configure('Power.Dialog.TLabel',background=PAPER,font=theme.native_font(window,12),foreground=theme.TEXT)
        frame=ttk.Frame(window,padding=(0,d(12)),style='Power.Dialog.TFrame')
        window.columnconfigure(0,weight=1);window.rowconfigure(0,minsize=d(82));window.rowconfigure(1,weight=1)
        window.rowconfigure(2,minsize=d(FOOTER_HEIGHT+FRAME))
        frame.grid(row=1,column=0,sticky='nsew',padx=(d(43),d(35)),pady=(d(8),d(12)))
        frame.columnconfigure(1,weight=1)
        category=tk.StringVar(value=BY_KEY[value['category']].label if value else CATEGORIES[0].label)
        target=tk.StringVar(value=value['target'] if value else '')
        location=tk.StringVar(value=value['location'] if value else '')
        count=tk.StringVar(value=str(value['count']) if value else '1');day=tk.StringVar(value=ui.echo_day.get())
        fields=[]
        for index,(name,variable) in enumerate((('分类',category),('副本',target),('地点',location),('开始星期（04:00）' if echo else '目标次数（1～9999）',day if echo else count))):
            ttk.Label(frame,text=name,style='Power.Dialog.TLabel').grid(row=index,column=0,sticky='w',padx=(0,d(16)),pady=d(8))
            field = ttk.Entry(frame,textvariable=variable) if index==3 and not echo else SettingChoice(frame,textvariable=variable,state='readonly')
            field.grid(row=index,column=1,sticky='ew',pady=d(8));fields.append(field)
        fields[0].configure(values=[c.label for c in CATEGORIES],state='disabled' if echo else 'readonly')
        if echo:fields[3].configure(values=DAYS)
        def locations(*_):
            key=next(c.key for c in CATEGORIES if c.label==category.get())
            available=[m.location for m in ui.dungeon_catalogue if m.category==key and m.name==target.get()]
            fields[2].configure(values=tuple(dict.fromkeys(available)))
            if location.get() not in available:location.set(available[0] if len(available)==1 else '')
        def targets(*_):
            key=next(c.key for c in CATEGORIES if c.label==category.get())
            available=list(dict.fromkeys(m.name for m in ui.dungeon_catalogue if m.category==key))
            fields[1].configure(values=available)
            if target.get() not in available:target.set('')
            locations()
        fields[0].bind('<<ComboboxSelected>>',targets);fields[1].bind('<<ComboboxSelected>>',locations);targets()
        error=tk.StringVar();theme.wrapped_label(frame,textvariable=error,style='Power.Dialog.TLabel').grid(row=4,column=0,columnspan=2,sticky='ew')
        def close():
            ui.power_dialog=None;window.destroy();self.table.focus_set()
        def apply():
            try:
                try:amount=3 if echo else int(count.get())
                except ValueError:raise ValueError('目标次数须为1～9999的整数。') from None
                if not 1<=amount<=9999:raise ValueError('目标次数须为1～9999的整数。')
                if not target.get() or not location.get():raise ValueError('请选择副本及明确地点。')
                item=dict(category=next(c.key for c in CATEGORIES if c.label==category.get()),target=target.get(),location=location.get(),count=amount)
                from .power_plan import items
                items([item])
                if not any(m.category==item['category'] and m.name==item['target'] and m.location==item['location'] for m in ui.dungeon_catalogue):
                    raise ValueError('请从目录选择副本及明确地点。')
                accept(item,day.get()) if echo else accept(item)
            except (ValueError,TypeError) as exc:error.set(str(exc));return
            close()
        cancel=DetailClose(window,ui.ui_scale,close,text='取消')
        confirm=DetailClose(window,ui.ui_scale,apply,text='加入计划' if value is None else '应用',symbol='confirm')
        def layout(event):
            if event.widget is not window:return
            available=event.width-d(98);width=min(d(288),available//2)
            center=(event.width+d(FRAME))/2;y=event.height-d(FRAME+FOOTER_HEIGHT/2)
            cancel.place(x=center-d(8)-width,y=y,width=width,height=d(46.4),anchor='w')
            confirm.place(x=center+d(8),y=y,width=width,height=d(46.4),anchor='w')
        window.bind('<Configure>',layout,add='+')
        window.protocol('WM_DELETE_WINDOW',close);window.bind('<Escape>',lambda _:close())
        window.update_idletasks()
        height=frame.winfo_reqheight()+d(82+FOOTER_HEIGHT+FRAME+20)
        place_dialog(window,ui.root,(d(774.4),height),(d(460),d(300)),padding=d(12))
        window.deiconify();window.grab_set();fields[1].focus_set()
