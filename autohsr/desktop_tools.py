"""Navigation and the shared primary action for the desktop tools."""
from tkinter import ttk


class ToolsShelf(ttk.Frame):
    def __init__(self, parent, ui):
        from .desktop_daily_observe import build_daily_observation_panel
        from .desktop_game_update import build_game_update_panel
        from .desktop_services import build_notifications_panel, build_redemption_panel
        from .desktop_screenshot import build_screenshot_panel
        from .desktop_update import build_update_panel
        from .desktop_warp import build_warp_panel
        from .desktop_workflows import build_schedule_panel, build_workflow_panel

        super().__init__(parent)
        self.ui = ui
        self.columnconfigure(0, weight=1)
        nav = self.nav = ui.settings_shell.tools_nav
        self.panels = {}
        self.buttons = {}
        self.selected = None
        for index, (key, title, build) in enumerate((
                ('warp', '跃迁记录', build_warp_panel),
                ('redemption', '兑换码', build_redemption_panel),
                ('notifications', '通知', build_notifications_panel),
                ('workflow', '任务流', build_workflow_panel),
                ('schedule', '应用内定时', build_schedule_panel),
                ('screenshot', '截图与识别', build_screenshot_panel),
                ('daily_observation', '日常页面核对', build_daily_observation_panel),
                ('app_update', '助手更新', build_update_panel),
                ('game_update', '游戏更新', build_game_update_panel))):
            nav.columnconfigure(index, weight=1)
            self.buttons[key] = ttk.Button(nav, text=title, style='Settings.Nav.TButton', takefocus=False,
                                           command=lambda key=key: self.select(key))
            self.buttons[key].grid(row=0, column=index, sticky='ew', padx=(0, round(4 * ui.ui_scale)))
            self.buttons[key].bind('<Left>', lambda _, index=index: self._move(index - 1))
            self.buttons[key].bind('<Right>', lambda _, index=index: self._move(index + 1))
            panel = build(self, ui)
            panel.bind('<Configure>', ui.settings_shell.queue_layout, add='+')
            panel.grid(row=0, column=0, sticky='new')
            panel.grid_remove()
            self.panels[key] = panel
            setattr(ui, key + '_panel', panel)
        self.current()

    def _move(self, index):
        keys = tuple(self.buttons)
        key = keys[index % len(keys)]
        self.select(key, focus_entry=False)
        self.buttons[key].focus_set()
        return 'break'

    def select(self, key, *, focus_entry=True):
        self.ui._selected_tool = key
        self._refresh_panel(key, self.current())
        self.ui.settings_shell.canvas.yview_moveto(0)
        self.ui._tool_action_changed()
        if focus_entry:
            self.ui.root.after_idle(self.focus_entry)

    def current(self):
        key = self.ui._selected_tool
        if self.selected != key:
            if self.selected is not None:
                self.panels[self.selected].grid_remove()
                self.buttons[self.selected].configure(style='Settings.Nav.TButton', takefocus=False)
            self.selected = key
            self.panels[key].grid()
            self.buttons[key].configure(style='Settings.Selected.Nav.TButton', takefocus=True)
            self.ui.settings_shell.queue_layout()
        return self.panels[key]

    def primary_action(self):
        return self.current().primary_action()

    def focus_entry(self):
        if not self.ui._in_tools() or self.ui.tools_shelf is not self:
            return
        panel = self.current()
        if self.ui.busy:
            self.buttons[self.selected].focus_set()
        elif self.selected == 'warp':
            panel.focus_initial()
        else:
            panel.focus_entry()

    def refresh(self):
        for key, panel in self.panels.items():
            self._refresh_panel(key, panel)

    @staticmethod
    def _refresh_panel(key, panel):
        if key == 'warp':
            panel.refresh_actions()
        else:
            panel.refresh()
