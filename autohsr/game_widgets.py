"""Live guide widgets reconstructed against the local 4.6 reference frames."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk

from . import theme as t


class Surface(tk.Canvas):
    def __init__(self,parent,scale,**kwargs):
        kwargs.setdefault("bg",t.PANEL)
        super().__init__(parent,highlightthickness=0,borderwidth=0,**kwargs)
        self.scale=scale
        self._paint_job=None
        self.bind("<Configure>",self.redraw)
        self.bind("<Destroy>",self._destroy,add="+")

    def _destroy(self,event):
        if event.widget is self and self._paint_job:
            self.after_cancel(self._paint_job)
            self._paint_job=None

    def watch(self,*variables):
        tokens=[(v,v.trace_add("write",lambda *_:self.redraw())) for v in variables]
        self.bind("<Destroy>",lambda e:[v.trace_remove("write",token) for v,token in tokens] if e.widget is self else None,add="+")

    def redraw(self,_event=None):
        if self._paint_job is None:
            self._paint_job=self.after_idle(self._render)

    def _render(self):
        self._paint_job=None
        w,h=self.winfo_width(),self.winfo_height()
        if w<2 or h<2:
            return
        p=t.Painter(w,h,self.scale,self.cget("bg"))
        self.paint(p)
        self._photo=ImageTk.PhotoImage(p.finish(),master=self)
        self.delete("art")
        self.create_image(0,0,image=self._photo,anchor="nw",tags="art")
        self.tag_lower("art")


class Header(Surface):
    def __init__(self,parent,scale,ui):
        super().__init__(parent,scale,bg=t.BG,height=round(76*scale))
        self.ui=ui
        self.watch(ui.page_title,ui.stamina,ui.elapsed)
        self.bind("<Button-1>",lambda e:ui._close() if e.x>self.winfo_width()-55*scale else None)
        self.plan = ttk.Frame(self, style="Footer.TFrame")
        self.plan.columnconfigure(0, weight=1)
        ui.plan_ribbon = PlanRibbon(self.plan, scale, ui, dark=True)
        ui.plan_ribbon.grid(row=0, column=0, sticky="ew")
        ui.weekly_button = ttk.Button(self.plan, text="周常计划", style="Footer.TButton", command=ui._show_weekly_plan)
        ui.weekly_button.grid(row=0, column=1, padx=(round(10*scale), 0))

    def position_plan(self):
        if getattr(self.ui, "action_page", "home") in ("home", "tasks"):
            d = lambda n: round(n*self.scale)
            self.plan.place(x=d(200), y=d(18), width=max(1, self.winfo_width()-d(550)), height=d(46))
        else:
            self.plan.place_forget()

    def paint(self,p):
        self.position_plan()
        p.asset("guide-mark.png",(24,23,62,59),t.GOLD)
        p.text((73,21),"星际和平指南",14,t.GOLD)
        p.text((73,43),self.ui.page_title.get(),17,t.LIGHT)
        p.text((p.width-295,29),"已确认开拓力  "+self.ui.stamina.get(),14,t.LIGHT)
        p.text((p.width-142,29),self.ui.elapsed.get(),14,t.LIGHT)
        x,y=p.width-33,36
        for sx,sy in ((-1,-1),(-1,1),(1,-1),(1,1)):
            p.line((x+sx*4,y+sy*4,x+sx*13,y+sy*13),t.LIGHT,2)


class Guide(Surface):
    """The black guide cover, five icon tabs, light paper and two charms."""
    def __init__(self,parent,scale,ui):
        super().__init__(parent,scale,bg=t.BG)
        self.ui=ui
        self.content=ttk.Frame(self)
        self.tabs=ttk.Frame(self,style="Rail.TFrame")
        self.buttons={}
        self.photos={}
        definitions=(("home","每日实训","tab-daily.png"),("tasks","生存索引","tab-survival.png"),
                     ("universe","差分宇宙 / 货币战争","tab-universe.png"),("logs","运行记录","tab-records.png"),
                     ("settings","设置","tab-settings.png"))
        for col,(key,label,filename) in enumerate(definitions):
            for selected in (False,True):
                p=t.Painter(round(42*scale),round(42*scale),scale,t.PANEL if selected else t.RAIL)
                if selected:
                    p.glow((21,21),10,(96,181,237,155),7)
                p.asset(filename,(1,1,41,41),"#111111" if selected else "#b6b6b6")
                self.photos[key,selected]=ImageTk.PhotoImage(p.finish(),master=self)
            command=lambda key=key:ui._show_page(getattr(ui,"last_universe_page","differential_universe") if key=="universe" else key)
            button=ttk.Button(self.tabs,text=label,image=self.photos[key,False],style="Nav.TButton",command=command)
            button.grid(row=0,column=col,padx=0)
            self.buttons[key]=button
            Tooltip(button,"旷宇纷争" if key=="universe" else label)
        self.bind("<Configure>",self._position,add="+")

    def select(self,page):
        group="universe" if page in ("differential_universe","currency_wars") else page
        for key,button in self.buttons.items():
            button.configure(style="Selected.Nav.TButton" if key==group else "Nav.TButton",image=self.photos[key,key==group])

    def _position(self,_event=None):
        d=lambda n:round(n*self.scale)
        w,h=self.winfo_width(),self.winfo_height()
        self.tabs.place(x=d(97),y=d(24))
        self.content.place(x=d(77),y=d(108),width=max(1,w-d(151)),height=max(1,h-d(148)))

    def paint(self,p):
        w,h=p.width,p.height
        p.box((38,12,w-38,h-12),"#101111",25,"#3a3a3c",2)
        p.box((51,25,w-51,h-25),t.PANEL,16)
        p.box((51,25,w-51,91),"#252525",15)
        p.box((51,53,w-51,91),"#252525")
        p.box((51,91,w-51,111),t.PANEL)
        # The static paper pattern is isolated from the reference's live text.
        with p.clip((51,91,w-51,h-25),16):
            p.asset("paper-pattern.png",(51,h-99,380,h-25))
            p.line((w-185,92,w-260,h-25),"#d1cec3")
        p.box((w-159,42,w-51,66),"#222222",12,"#6f654a")
        p.ellipse((w-150,52,w-147,55),t.GOLD)
        p.asset("guide-seal.png",(w-119,32,w-70,73),t.GOLD)
        p.asset("guide-charm-left.png",(1,114,83,273))
        p.asset("guide-charm-right.png",(w-112,h-255,w+1,h-66))


class Tooltip:
    def __init__(self,widget,text):
        self.widget,self.text,self.tip=widget,text,None
        widget.bind("<Enter>",self.show,add="+")
        widget.bind("<FocusIn>",self.show,add="+")
        for event in ("<Leave>","<FocusOut>","<ButtonPress>","<Destroy>"):
            widget.bind(event,self.hide,add="+")

    def show(self,_=None):
        if self.tip is not None:
            return
        self.tip=tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.geometry(f"+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty()+self.widget.winfo_height()+5}")
        tk.Label(self.tip,text=self.text,bg=t.RAIL,fg=t.LIGHT,font=(t.FONT,10),padx=12,pady=5).pack()

    def hide(self,_=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip=None


class TrainingMeter(Surface):
    def __init__(self,parent,scale,variable):
        super().__init__(parent,scale,height=round(112*scale))
        self.variable=variable
        self.watch(variable)

    @property
    def verified(self):
        return self.variable.get()=="verified"

    def paint(self,p):
        w=p.width
        p.box((39,12,w-1,98),"#e9e9e9",35,"#f7f7f7",2)
        p.box((78,62,w-1,98),"#e9e9e9")
        cx,cy,r=54,54,53
        p.ellipse((cx-r,cy-r,cx+r,cy+r),"#f8f8f5","#d2c9b5")
        for n in range(72):
            angle=n*math.pi/36
            p.line((cx+44*math.cos(angle),cy+44*math.sin(angle),cx+52*math.cos(angle),cy+52*math.sin(angle)),"#c6b994",.55)
        p.asset("activity.png",(cx-19,cy-43,cx+19,cy+17),"#ad9a70")
        p.text((cx,cy+23),"500" if self.verified else "—",23,"#101010","mt")
        start,end=120,w-34
        color=t.ORANGE if self.verified else "#a6a6a6"
        markers = [start+(end-start)*i/5 for i in range(6)]
        for index, (left, right) in enumerate(zip(markers, markers[1:])):
            left += 28 if index else 0
            right -= 32
            p.line((left,47,right,47),color,4)
            for x in (left, right):
                p.ellipse((x-4,43,x+4,51),color)
        p.text((start,75),"0",18,t.TEXT,"mt")
        for i in range(1,6):
            x=start+(end-start)*i/5
            if self.verified:
                p.asset("reward-check.png",(x-23,23,x+23,69),t.ORANGE)
            else:
                p.ellipse((x-21,26,x+21,68),"#e9e9e9","#bdbdbd",2)
                p.asset("reward-gift.png",(x-12,32,x+12,61),"#929292")
            p.text((x,75),str(i*100),18,t.TEXT,"mt")


TITLES={"assignments":"领取持续委托奖励","battle":"完成日常副本挑战","daily":"领取每日实训奖励",
        "mail":"领取现有邮件附件","battlepass":"领取无名勋礼奖励"}


class TaskBoard(Surface):
    """Live paper cards; every task remains accessible by pointer and keyboard."""
    def __init__(self,parent,scale,ui,names):
        super().__init__(parent,scale,height=round(350*scale),takefocus=True)
        self.ui,self.names=ui,names
        self.records={key:dict(values=(label,"等待",""),tags=(),has_result=False,metrics=None) for key,label in names.items()}
        self.offset,self.selected,self.hover=0,None,None
        self.hitboxes={}
        self.visible_count=4
        self.watch(ui.challenge_count,ui.battle_cost,*ui.tasks.values())
        self.bind("<Button-1>",self._click)
        self.bind("<Motion>",lambda e:self._set_hover(self._target(e)))
        self.bind("<Leave>",lambda _:self._set_hover(None))
        self.bind("<MouseWheel>",lambda e:self.move(1 if e.delta<0 else -1))
        for key,delta in (("Right",1),("Left",-1),("Home",-9),("End",9)):
            self.bind("<"+key+">",lambda _,delta=delta:self.move(delta))
        self.bind("<Return>",lambda _:self.activate())
        self.bind("<space>",lambda _:self.activate())
        self.bind("<FocusIn>",self.redraw,add="+")
        self.bind("<FocusOut>",self.redraw,add="+")

    def item(self,iid,option=None,**kwargs):
        if kwargs:
            self.records[iid].update(kwargs)
            if kwargs.get("values",("",""))[1]=="进行中":
                self._reveal(list(self.names).index(iid))
            self.redraw()
        return self.records[iid][option] if option else dict(self.records[iid])

    def selection(self):
        return (self.selected,) if self.selected else ()

    def selection_remove(self,*_):
        self.selected=None
        self.redraw()

    def _reveal(self,index):
        self.offset=max(0,min(len(self.names)-self.visible_count,
                             min(self.offset,index) if index<self.offset else max(self.offset,index-self.visible_count+1)))

    def move(self,delta):
        keys=list(self.names)
        index=max(0,min(len(keys)-1,(keys.index(self.selected) if self.selected else self.offset)+delta))
        self.selected=keys[index]
        self._reveal(index)
        self.redraw()
        return "break"

    def activate(self):
        self.selected=self.selected or list(self.names)[self.offset]
        if self.records[self.selected]["has_result"]:
            self.ui._show_task_detail()
        else:
            self.ui._show_task_setup(self.selected)
        self.redraw()
        return "break"

    def action_label(self, key):
        if self.records[key]["has_result"]:
            return "查看进度" if self.records[key]["values"][1] == "进行中" else "查看结果"
        return {"assignments":"委托设置", "battle":"副本设置", "daily":"实训设置",
                "mail":"邮件设置", "battlepass":"勋礼设置"}[key]

    def _target(self,e):
        x,y=e.x/self.scale,e.y/self.scale
        return next((key for key,(x1,y1,x2,y2) in self.hitboxes.items() if x1<=x<=x2 and y1<=y<=y2),None)

    def _set_hover(self,key):
        if key!=self.hover:
            self.hover=key
            self.configure(cursor="hand2" if key else "")
            self.redraw()

    def _click(self,e):
        key=self._target(e)
        self.focus_set()
        if key in ("previous","next"):
            self.offset=max(0,min(len(self.names)-self.visible_count,self.offset+(-1 if key=="previous" else 1)))
            self.selected=None
            self.redraw()
        elif key:
            self.selected=key
            self.activate()

    def paint(self,p):
        w,h=p.width,p.height
        self.visible_count=4 if w>=850 else 3
        self.offset=min(self.offset,len(self.names)-self.visible_count)
        self.hitboxes={}
        # Reference card: 290 x 480, a 372px paper section and 45px gaps.
        # Keep that aspect when space changes, and expose the next card's edge.
        width=min((w-10)/(self.visible_count*335/290+40/290), (h-32)*290/480)
        unit=width/290
        q=lambda value:value*unit
        gap=q(45)
        keys=list(self.names)[self.offset:self.offset+self.visible_count+1]
        for i,key in enumerate(keys):
            x=2+i*(width+gap)
            if x>=w:
                break
            right=x+width
            card_bottom=q(372)
            bottom=q(480)
            selected=key in (self.selected,self.hover)
            p.box((x+q(10),q(10),right+q(10),bottom+q(10)),"#c7c7c7",q(7))
            p.box((x,1,right,card_bottom),"#fbfaf7",q(7),t.GOLD if selected else "#eeede8",2 if selected else 1)
            for dx in (-40,20,90,160):
                p.line((max(x,x+q(dx)),2,min(right,x+q(dx+70)),q(60)),"#efede5",1)
            p.asset("card-watermark.png",(x+q(40),q(110),x+q(250),q(282)))
            for xx in range(round(x+q(14)),round(right-q(14)),max(3,round(q(4)))):
                for yy in (q(64),card_bottom-q(16)):
                    p.box((xx,yy,xx+1,yy+1),"#d4bc8b")
            for yy in range(round(q(64)),round(card_bottom-q(16)),max(3,round(q(4)))):
                for xx in (x+q(14),right-q(14)):
                    p.box((xx,yy,xx+1,yy+1),"#d4bc8b")
            _,state,_=self.records[key]["values"]
            p.box((x+1,q(16),x+q(162),q(47)),"#e9dbbd",0,"#d7bd8b")
            p.text((x+q(24),q(20)),state,q(23),"#6b624d")
            p.text((x+q(24),q(80)),p.wrap(TITLES[key],width-q(48),q(25),3),q(25),"#111111")
            resource_y=q(278)
            p.box((x+q(15),resource_y,right-q(15),card_bottom-q(17)),"#f4f4f4")
            if key=="daily":
                p.asset("activity.png",(x+q(60),q(265),x+q(117),q(351)),"#ad9a70")
            else:
                p.asset("stamina.png",(x+q(62),q(288),x+q(108),q(334)))
            if key=="battle":
                value=self.ui.challenge_count.get()+" 次" if self.ui.tasks[key].get() else "0 次"
                from .dungeon_ui import selected_category
                try:
                    sub=f"预计 {int(self.ui.challenge_count.get())*selected_category(self.ui).cost} 开拓力" if self.ui.tasks[key].get() else "未启用"
                except ValueError:
                    sub="次数待填写"
                if self.records[key]["metrics"] is not None:
                    value, sub = self.records[key]["metrics"]
            elif key=="daily":
                value="500"
                sub="活跃目标"
            else:
                value="0"
                sub="开拓力"
            p.text((x+q(126),q(286)),value,q(32),"#494442")
            p.text((x+q(126),q(326)),sub,q(16),t.MUTED)
            with p.clip((x,card_bottom,right,bottom),q(7)):
                p.asset("card-footer.png",(x,card_bottom,right,bottom))
            p.text((x+width/2,q(426)),self.action_label(key),q(25),"#d8ba78","mm")
            if selected:
                p.box((x-1,0,right+1,bottom),None,q(7),t.GOLD,2)
            self.hitboxes[key]=(x,0,min(right,w),bottom)
        visible_end=min(len(self.names),self.offset+self.visible_count)
        for key,x,symbol in (("previous",w-103,"‹"),("next",w-15,"›")):
            enabled=self.offset>0 if key=="previous" else self.offset<len(self.names)-self.visible_count
            p.text((x,h-13),symbol,24,t.TEXT if enabled else "#bcbcbc","mm")
            if enabled:
                self.hitboxes[key]=(x-16,h-29,x+16,h)
        p.text((w-59,h-12),f"{self.offset+1}–{visible_end} / {len(self.names)}",12,t.MUTED,"mm")


class PlanRibbon(Surface):
    def __init__(self, parent, scale, ui, *, dark=False):
        super().__init__(parent, scale, bg=t.BG if dark else t.PANEL, height=round(46*scale))
        self.ui = ui
        self.dark = dark
        self.watch(ui.daily_caption, ui.weekly_status)

    def paint(self, p):
        p.text((2, 3), p.wrap(self.ui.daily_caption.get(), p.width-6, 14, 1), 14, t.LIGHT if self.dark else t.TEXT)
        p.text((2, 26), p.wrap(self.ui.weekly_status.get(), p.width-6, 13, 1), 13, "#b8b8bc" if self.dark else t.MUTED)


class SummaryStrip(Surface):
    def __init__(self,parent,scale,ui):
        super().__init__(parent,scale,bg=t.BG,height=round(25*scale),takefocus=True)
        self.ui=ui
        self.watch(ui.summary, ui.input_error, ui.result_alert)
        self.bind("<Button-1>", self.activate)
        self.bind("<Return>", self.activate)
        self.bind("<space>", self.activate)
        self.bind("<FocusIn>", self.redraw, add="+")
        self.bind("<FocusOut>", self.redraw, add="+")

    def message(self):
        return self.ui.input_error.get() or self.ui.result_alert.get() or self.ui.summary.get()

    def activate(self, _=None):
        if self.ui.input_error.get():
            self.ui._focus_input_error()
        else:
            self.ui._show_summary()
        return "break"

    def paint(self,p):
        text=self.message()
        if text:
            p.text((0,4),p.wrap(text,p.width-65,13,1),13,t.GOLD if self.ui.input_error.get() or self.ui.result_alert.get() else t.LIGHT)
            p.text((p.width,4),"修改  ›" if self.ui.input_error.get() else "详情  ›",13,t.GOLD,"rt")
            if self.focus_get() is self:
                p.line((0,p.height-1,p.width,p.height-1),t.GOLD)
            self.configure(cursor="hand2", takefocus=True)
        else:
            self.configure(cursor="", takefocus=False)


class ActivityStrip(Surface):
    def __init__(self, parent, scale, variable):
        super().__init__(parent, scale, bg=t.BG, height=round(23*scale))
        self.variable = variable
        self.watch(variable)

    def paint(self, p):
        p.text((0, 2), p.wrap(self.variable.get(), p.width-2, 13, 1), 13, t.LIGHT)
