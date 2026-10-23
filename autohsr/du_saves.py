"""Visible save-slot and generated-name rules for optional DU archives."""
import re
from .models import AutomationError,normalize


def management(scene):
    return (scene.has('差分宇宙',(0,0,.32,.13)) and
            scene.has('存档管理',(0,0,.32,.13),exact=True))


def rename_dialog(scene):
    return (scene.has('更改存档名',(.30,.33,.70,.43),exact=True) and
            scene.has('取消',(.28,.58,.49,.67),exact=True) and
            scene.has('确认',(.51,.58,.72,.67),exact=True))


def next_name(scene):
    used=[]
    for token in scene.tokens:
        if token.within((.01,.14,.18,.65)):
            match=re.fullmatch(r'autohsr-(\d+)',normalize(token.text))
            if match:
                used.append(int(match.group(1)))
    number=max(used,default=0)+1
    return 'AutoHSR-1' if number==1 else f'AutoHSR - {number}'


def empty_slot(scene):
    if not management(scene):
        return None
    candidates=[t for t in scene.tokens if normalize(t.text)=='暂无存档'
                and t.within((.01,.14,.18,.65))]
    return min(candidates,key=lambda t:t.center[1],default=None)


def guard_name(scene,name):
    if not rename_dialog(scene) or re.fullmatch(r'AutoHSR(?: - |-)\d{1,6}',name) is None:
        raise AutomationError('未核实差分宇宙存档命名窗口或自动编号，未输入。')


def guard_save_click(scene,target,intent):
    """Save only into an empty slot; never select an existing archive to replace."""
    text=normalize(target.text)
    allowed=False
    if intent=='du_save_open':
        allowed=(scene.has('探索成功') and scene.has('分析报告') and
                 scene.has('差分宇宙构筑内容') and text=='记录本次存档'
                 and target.within((.50,.85,.75,.97)))
    elif intent=='du_save_slot':
        allowed=(management(scene) and text=='暂无存档' and target.within((.01,.14,.18,.65)))
    elif intent=='du_save_create':
        allowed=(management(scene) and scene.has('暂无存档',(.35,.45,.8,.60),exact=True)
                 and text=='保存本轮数据' and target.within((.46,.62,.70,.74)))
    elif intent=='du_save_focus':
        allowed=rename_dialog(scene) and text=='存档名输入框' and target.within((.30,.46,.70,.51))
    elif intent=='du_save_confirm':
        names=[t for t in scene.tokens if t.within((.30,.46,.70,.51))
               and re.fullmatch(r'autohsr-\d{1,6}',normalize(t.text))]
        allowed=rename_dialog(scene) and bool(names) and text=='确认' and target.within((.51,.58,.72,.67))
    if not allowed:
        raise AutomationError('差分宇宙存档步骤、空槽或名称未核实，未操作。')
