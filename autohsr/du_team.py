"""Select named preset teams; never build teams from individual character cards."""
from .models import AutomationError, Scene, Token, normalize


def selection_page(scene: Scene) -> bool:
    return (scene.has('下载角色',(0,0,.32,.13),exact=True)
            and scene.has('角色列表',(0,.09,.16,.16),exact=True)
            and scene.has('预设编队',(.15,.09,.30,.16),exact=True))


def setup_page(scene: Scene) -> bool:
    return (not selection_page(scene) and scene.has('差分宇宙')
            and scene.has(('进入星阶模式','启动「差分宇宙」','启动差分宇宙'),(.72,.82,1,.98),exact=True))


def entry(scene: Scene) -> Token:
    if not setup_page(scene) or scene.image is None:
        raise AutomationError('未核实差分宇宙备战页和出战头像，未打开选角。')
    # The first circular deployment portrait opens 下载角色 in all observed
    # normal/periodic setups. Reject an empty or faded loading placeholder.
    import cv2
    h,w=scene.image.shape[:2]
    patch=scene.image[round(.877*h):round(.922*h),round(.587*w):round(.612*w)]
    if not patch.size or patch.std()<18 or (cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)[:,:,1]>45).mean()<.12:
        raise AutomationError('备战页出战头像尚未就绪，未点击。')
    return Token('差分宇宙预设编队入口',.99,(.587,.877,.612,.922))


def preset(scene: Scene, name: str) -> Token | None:
    if not selection_page(scene):
        return None
    matches=[t for t in scene.tokens if normalize(t.text)==normalize(name)
             and t.within((.015,.15,.24,.91))]
    if len(matches)>1:
        raise AutomationError('可见预设编队名称重复，未选择不确定队伍。')
    return matches[0] if matches else None


def enabled(scene: Scene, name: str) -> bool:
    target=preset(scene,name)
    if target is None:
        return False
    x,y=target.center
    badge=scene.find('已启用',(.24,max(.15,y-.025),.295,min(.94,y+.025)),exact=True)
    # All four character level labels must be present under this team title.
    levels=[t for t in scene.tokens if normalize(t.text).startswith('等级')
            and t.within((.02,y+.08,.29,min(.96,y+.16)))]
    return badge is not None and len(levels)==4


def guard_click(scene: Scene, target: Token, intent: str, name: str) -> None:
    if intent=='du_team_open':
        valid=target==entry(scene)
    elif intent=='du_team_tab':
        valid=(selection_page(scene) and normalize(target.text)=='预设编队'
               and target.within((.15,.09,.30,.16)))
    elif intent=='du_team_select':
        valid=target==preset(scene,name)
    else:
        valid=False
    if not valid:
        raise AutomationError('未核实指定预设编队入口、页签或名称，未选角。')


def select(flow, scene: Scene):
    name=flow.settings.differential_universe_team
    if not selection_page(scene):
        # Mode headings can become readable before the sliding deployment
        # portraits/button finish fading in. Observe readiness without a click.
        def ready(page):
            try:
                entry(page)
            except AutomationError:
                return False
            return True
        if not ready(scene):
            scene=flow.ctx.wait(ready,timeout=12,description='等待备战页出战头像与启动按钮就绪')
        scene,kind=flow._click(scene,entry(scene),intent='du_team_open',label='preset_team_opened')
        if kind!='team_selection':
            raise AutomationError('出战头像未打开下载角色页面，未启动。')
    tab=scene.find('预设编队',(.15,.09,.30,.16),exact=True)
    scene,kind=flow._click(scene,tab,intent='du_team_tab',label='preset_team_tab')
    target=preset(scene,name)
    if target is None:
        raise AutomationError(f'预设编队列表未找到“{name}”，未改用其他队伍。')
    # Select even if it was already enabled, on every new launch.
    scene,kind=flow._click(scene,target,intent='du_team_select',label='preset_team_selected')
    scene=flow.ctx.wait(lambda page:enabled(page,name),timeout=12,description=f'核实预设编队 {name} 已启用且四人完整')
    evidence=flow.ctx.evidence(scene,f'du_{flow.report["current_run"]:02d}_preset_team_verified')
    record={'run':flow.report['current_run'],'preset':name,'verified':True,'evidence':str(evidence)}
    flow.report.setdefault('team_selections',[]).append(record)
    flow._persist_ledger()
    scene=flow.ctx.differential_universe_close_team(scene)
    from .differential_universe import classify_page
    if selection_page(scene):
        scene=flow.ctx.wait(setup_page,timeout=12,description='等待预设编队收起动画结束')
    kind=flow._observe(scene,'preset_team_closed')
    scene,kind=flow._wait_known(scene,kind,'preset_team_closed')
    if kind not in ('periodic_setup','difficulty_setup','star_rank_setup'):
        raise AutomationError('预设编队关闭后未返回备战页，未启动。')
    return scene,kind
