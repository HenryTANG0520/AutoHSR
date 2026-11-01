"""Compare popup geometry to a source frame and exercise its real input surface."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageGrab, ImageTk
from ux_smoke import ROOT, Settings, Window, module
from autohsr.setting_choices import SettingChoice
from autohsr.desktop_dialogs import _work_area

OUT = ROOT/'runs/settings-popup-ui'
SOURCE_SHA256 = '2882740221aaa7033f6cf0d23f9b37dee7227ed270d61a1524cffc7b767c8df6'


def orange_geometry(image):
    pixels = np.asarray(image.convert('RGB')).astype(int)
    mask = (pixels[:,:,0] > 220) & (pixels[:,:,1] > 120) & (pixels[:,:,1] < 180) & (pixels[:,:,2] < 90)
    y, x = np.where(mask)
    assert len(x)
    row_height = image.height/2
    # A wider value column moves the marker without stretching it. Compare its
    # right inset and size in row heights, not in whole-popup width fractions.
    return ((image.width-(x.min()+x.max())/2)/row_height, (y.min()+y.max())/2/row_height,
            (x.max()-x.min()+1)/row_height, (y.max()-y.min()+1)/row_height)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.reference.read_bytes()).hexdigest() == SOURCE_SHA256
    # This local-only crop excludes the source frame's UID and all unrelated UI.
    reference = Image.open(args.reference).convert('RGB').crop((1406, 418, 1834, 567))
    expected = orange_geometry(reference)
    OUT.mkdir(parents=True, exist_ok=True)
    checks, errors, samples = [], [], []
    def check(name, condition):
        assert condition, (name, errors)
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError('Popup checks must not access a game backend')
    fake = types.ModuleType('autohsr.app')
    fake.Runner = fake.launch_game = fake.inspect_game = reject

    def open_choice(root, field):
        field.focus_force()
        field.event_generate('<Down>')
        root.update()
        pop = str(root.tk.call('ttk::combobox::PopdownWindow', field))
        assert root.tk.getboolean(root.tk.call('winfo', 'ismapped', pop))
        return pop, pop+'.f.l', pop+'.f.l.art'

    def key(root, listing, name):
        root.tk.call('event', 'generate', listing, '<'+name+'>')
        root.update()

    def click_row(root, listing, canvas, index, x=20):
        _, y, _, h = map(int, root.tk.splitlist(root.tk.call(listing, 'bbox', index)))
        for event in ('<Motion>', '<ButtonPress-1>', '<ButtonRelease-1>'):
            root.tk.call('event', 'generate', canvas, event, '-x', x, '-y', y+h//2)
        root.update()

    with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)), \
            patch.dict(sys.modules, {'autohsr.app': fake}):
        config = Path(folder)/'config.json'
        Settings().save(config)
        original = config.read_bytes()
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call('tk', 'scaling', scale*96/72)
            root.report_callback_exception = lambda kind, value, trace: errors.append(str(value))
            ui = Window(root, config)
            prefix = str(scale)+'_'
            try:
                root.update()
                ui._show_weekly_plan()
                root.update()
                mode = ui.weekly_mode_combo
                mode.current(1)
                mode.event_generate('<<ComboboxSelected>>')
                root.update()
                pop, listing, canvas = open_choice(root, mode)
                pixels = ImageTk.getimage(mode._choice_photo).convert('RGB')
                actual = orange_geometry(pixels)
                if not all(abs(a-b)<.05 for a,b in zip(actual, expected)):
                    pixels.save(OUT/(prefix+'marker-mismatch.png'))
                    print(json.dumps(dict(scale=scale, effective_scale=ui.ui_scale, size=pixels.size,
                                          actual=actual, expected=expected)),flush=True)
                check(prefix+'selected_marker_matches_source_geometry', all(abs(a-b)<.05 for a,b in zip(actual, expected)))
                check(prefix+'popup_paper_matches_source', pixels.getpixel((pixels.width//2, round(pixels.height*.2))) == reference.getpixel((reference.width//2, 30)))
                divider = np.asarray(pixels)[round(pixels.height*.46):round(pixels.height*.54), pixels.width//4:3*pixels.width//4]
                check(prefix+'divider_matches_source_color', np.any(np.all(np.abs(divider.astype(int)-(214,214,214))<=3,axis=2)))
                boxes = [tuple(map(int, root.tk.splitlist(root.tk.call(listing,'bbox',n)))) for n in (0,1)]
                check(prefix+'row_target_matches_settings_height', abs((boxes[1][1]-boxes[0][1])/ui.ui_scale-58)<2)
                check(prefix+'native_focus_is_preserved', str(root.tk.call('focus')) == listing)
                samples.append(dict(scale=scale, popup=pixels.size, selected_marker=actual))
                pixels.save(OUT/(prefix+'mode-popup.png'))
                if scale == 1.:
                    x,y=root.winfo_rootx(),root.winfo_rooty()
                    ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height())).save(OUT/'weekly-popup.png')
                events = []
                token = mode.bind('<<ComboboxSelected>>', lambda event:events.append(True), add='+')
                click_row(root,listing,canvas,0)
                check(prefix+'text_side_click_commits_once', mode.current()==0 and len(events)==1 and not root.tk.getboolean(root.tk.call('winfo','ismapped',pop)))
                pop,listing,canvas=open_choice(root,mode)
                events.clear()
                click_row(root,listing,canvas,1,int(root.tk.call('winfo','width',canvas))-36)
                check(prefix+'marker_side_click_commits_once', mode.current()==1 and len(events)==1)
                pop,listing,canvas=open_choice(root,mode)
                key(root,listing,'Home')
                check(prefix+'pending_navigation_keeps_committed_marker', mode.current()==1 and orange_geometry(ImageTk.getimage(mode._choice_photo))[1]>.6)
                key(root,listing,'Escape')
                check(prefix+'escape_cancels_without_leaving_settings', mode.current()==1 and ui.active_page=='settings')
                pop,listing,canvas=open_choice(root,mode)
                root.tk.call('event','generate',pop,'<ButtonPress-1>','-x',-20,'-y',-20)
                root.update()
                check(prefix+'outside_click_only_dismisses', mode.current()==1 and not root.tk.getboolean(root.tk.call('winfo','ismapped',pop)))
                mode.unbind('<<ComboboxSelected>>',token)
                commands=len(mode._tclCommands)
                for _ in range(3):
                    pop,listing,canvas=open_choice(root,mode)
                    key(root,listing,'Escape')
                check(prefix+'reopening_does_not_register_more_callbacks',len(mode._tclCommands)==commands)
                pop,listing,canvas=open_choice(root,mode)
                ui._leave_settings()
                root.update()
                check(prefix+'leaving_settings_releases_popup_and_grab',not root.tk.getboolean(root.tk.call('winfo','ismapped',pop)) and not root.tk.call('grab','current'))
                ui._show_weekly_plan()
                root.update()
                long=SettingChoice(ui.settings_sections['weekly'],values=tuple(str(n) for n in range(30)),state='readonly')
                long.grid(row=8,column=0,sticky='ew')
                long.current(0)
                root.update()
                pop,listing,canvas=open_choice(root,long)
                area=_work_area(root)
                rect=tuple(int(root.tk.call('winfo',name,pop)) for name in ('rootx','rooty','width','height'))
                check(prefix+'tall_popup_fits_monitor_work_area',rect[0]>=area[0] and rect[1]>=area[1] and rect[0]+rect[2]<=area[2] and rect[1]+rect[3]<=area[3])
                before=root.tk.call(listing,'yview')
                root.tk.call('event','generate',canvas,'<MouseWheel>','-delta',-120)
                root.update()
                check(prefix+'wheel_over_artwork_scrolls_native_rows',root.tk.call(listing,'yview')!=before and long.current()==0)
                key(root,listing,'End')
                click_row(root,listing,canvas,29)
                check(prefix+'scrolled_last_row_can_be_clicked',long.current()==29)
                long.destroy()
                for size in ('zoomed','normal','zoomed','normal'):
                    root.state(size)
                    root.update()
                    ui.responsive_layout.fit()
                    root.update()
                    field=ui.weekly_day_combo
                    pop,listing,canvas=open_choice(root,field)
                    key(root,listing,'End')
                    check(prefix+size+str(len(checks))+'_layout_keeps_art_and_native_focus',field._choice_photo is not None and str(root.tk.call('focus'))==listing)
                    key(root,listing,'Escape')
                check(prefix+'config_and_backend_unchanged',config.read_bytes()==original and ui.runner is None and ui.worker is None)
            finally:
                ui.closing=True
                for token in root.tk.splitlist(root.tk.call('after','info')):
                    if str(root.tk.call('after','info',token)[0]).endswith('_drain'):
                        root.after_cancel(token)
                root.destroy()
    check('no_callback_errors',not errors)
    result=dict(count=len(checks),checks=checks,samples=samples,reference_sha256=SOURCE_SHA256,game_started=False,config_unchanged=True)
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(count=len(checks),game_started=False)))


if __name__=='__main__':
    main()
