"""Check rendered status ink against the paper tab, including reused results."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

import cv2
import numpy as np
from PIL import ImageTk
from ux_smoke import ROOT, Settings, Window, module

OUT = ROOT/'runs/card-status-ui'


def header_bounds(image, card_width, scale):
    pixels = np.asarray(image.convert('RGB'))
    unit = card_width/290*scale
    area = pixels[round(16*unit):round(48*unit), :round(card_width*scale)].astype(int)
    paper = (np.abs(area - (233,219,189)).max(2) < 4).astype('uint8')
    _,_,regions,_ = cv2.connectedComponentsWithStats(paper)
    x,_,width,_,_ = max(regions[1:], key=lambda region:region[4])
    ink = np.abs(area - (107,98,77)).max(2) < 24
    columns = np.flatnonzero(ink.any(0))
    assert len(columns), 'Status text is missing'
    return dict(tab_left=int(x), tab_right=int(x+width-1), ink_left=int(columns[0]), ink_right=int(columns[-1]), unit=unit)


def main(strict=True):
    OUT.mkdir(parents=True, exist_ok=True)
    checks, cases, errors = [], [], []
    def check(name, value):
        checks.append(dict(name=name, passed=bool(value)))
        if strict: assert value, (name, cases[-1] if cases else None, errors)
    with tempfile.TemporaryDirectory() as folder, patch.object(module,'ROOT',Path(folder)):
        config=Path(folder)/'config.json';Settings(overlay_logs=False).save(config)
        saved=config.read_bytes()
        for scale in (1.,1.5,2.):
            root=tk.Tk();root.tk.call('tk','scaling',scale*96/72)
            root.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
            ui=Window(root,config)
            try:
                root.update()
                for label in ('待执行','进行中','全部完成','部分完成','原日常全部完成','原日常部分完成','本次不执行'):
                    ui._has_run=True
                    ui.table.item('assignments', values=('持续委托奖励',label,''), has_result=True)
                    root.update()
                    image=ImageTk.getimage(ui.table._photo)
                    bounds=header_bounds(image,ui.table.card_width,ui.ui_scale)
                    left=bounds['ink_left']-bounds['tab_left']
                    right=bounds['tab_right']-bounds['ink_right']
                    cases.append(dict(scale=scale,status=label,left_padding=left,right_padding=right,**bounds))
                    check(str(scale)+'_'+label+'_text_stays_inside_status_tab', left>=18*bounds['unit'] and right>=18*bounds['unit'])
                    check(str(scale)+'_'+label+'_balanced_status_padding', abs(left-right)<=4*bounds['unit'])
                    image.save(OUT/(str(scale)+'_'+label+'.png'))
                check(str(scale)+'_config_unchanged',config.read_bytes()==saved)
            finally:
                ui.closing=True
                for token in root.tk.splitlist(root.tk.call('after','info')):
                    if str(root.tk.call('after','info',token)[0]).endswith('_drain'):root.after_cancel(token)
                root.destroy()
        check('no_callback_errors',not errors)
    data=dict(count=len(checks),checks=checks,cases=cases,passed=all(c['passed'] for c in checks),
              game_started=False,rendered_widget_bitmaps=True,native_interaction_verified=False)
    (OUT/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(checks=len(checks),failed=sum(not c['passed'] for c in checks),game_started=False)))


if __name__=='__main__':main()
