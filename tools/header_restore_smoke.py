"""Keep plan actions inside the visible header after reusing a layout."""
from pathlib import Path
import json
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module


def contained(widget):
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    right, bottom = x+widget.winfo_width(), y+widget.winfo_height()
    parent = widget.master
    while parent is not None:
        if not (parent.winfo_rootx() <= x and parent.winfo_rooty() <= y
                and right <= parent.winfo_rootx()+parent.winfo_width()
                and bottom <= parent.winfo_rooty()+parent.winfo_height()):
            return False
        parent = parent.master
    return bool(widget.winfo_ismapped())


def main():
    checks = []
    out = ROOT/'runs/header-restore-ui'
    out.mkdir(parents=True, exist_ok=True)
    def check(name, value):
        assert value, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError('Header checks cannot start a game backend')
    fake = types.ModuleType('autohsr.app')
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)), \
            patch.dict(sys.modules, {'autohsr.app': fake}):
        config = Path(folder)/'config.json'
        Settings().save(config)
        original = config.read_bytes()
        for dpi in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call('tk', 'scaling', dpi*96/72)
            errors = []
            root.report_callback_exception = lambda kind, value, tb: errors.append(repr(value))
            ui = Window(root, config)
            def settle():
                root.update()
                ui.responsive_layout.fit()
                root.update()
                assert not errors, errors
            try:
                settle()
                normal, normal_shell = root.geometry(), ui.shell
                for page in ('home', 'tasks'):
                    ui._show_page(page)
                    settle()
                    for action in ('maximize', 'restore', 'maximize-again', 'restore-again'):
                        zoom = action.startswith('maximize')
                        root.state('zoomed' if zoom else 'normal')
                        if not zoom:
                            root.geometry(normal)
                        settle()
                        prefix = f'{dpi}_{page}_{action}'
                        if not zoom:
                            ImageGrab.grab(window=root.winfo_id()).save(out/f'{prefix}.png')
                        check(prefix+'_weekly_inside_viewport', contained(ui.weekly_button))
                        check(prefix+'_start_inside_viewport', contained(ui.start_button))
                        check(prefix+'_main_action_is_plan', ui.start_button.cget('text') == '开始计划')
                        if not zoom:
                            check(prefix+'_normal_layout_reused', ui.shell is normal_shell)
                    ui.weekly_button.invoke()
                    settle()
                    check(f'{dpi}_{page}_weekly_opens_correct_section', ui.active_page == 'settings'
                          and ui.settings_shell.section == 'weekly')
                    ui.settings_shell.back.invoke()
                    settle()
                    check(f'{dpi}_{page}_return_restores_visible_weekly', ui.active_page == 'home'
                          and contained(ui.weekly_button) and root.focus_get() is ui.weekly_button)
                check(f'{dpi}_config_unchanged', config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call('after', 'info')):
                    root.after_cancel(token)
                root.destroy()
    result = dict(count=len(checks), checks=checks, game_started=False)
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
