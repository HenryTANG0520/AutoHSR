"""Choose a full named preset on the planar extraction preparation screen."""
from .models import AutomationError, Token, normalize


def preparation(scene):
    return (scene.has('位面饰品提取', (0, 0, .32, .13), exact=True)
            and scene.has('下载角色', (.30, .60, .55, .78), exact=True)
            and scene.has('开始挑战', (.72, .86, 1, .98), exact=True))


def selection(scene):
    return (scene.has('角色列表', (0, 0, .16, .11), exact=True)
            and scene.has('预设编队', (.15, 0, .30, .11), exact=True)
            and scene.has('下载角色', (.30, .60, .55, .78), exact=True)
            and scene.has('首领敌人', (.30, .17, .55, .25), exact=True)
            and scene.has('开始挑战', (.72, .86, 1, .98), exact=True))


def entry(scene):
    if not preparation(scene) or selection(scene) or scene.image is None:
        raise AutomationError('未核实饰品提取备战页，未打开编队。')
    import cv2
    h, w = scene.image.shape[:2]
    patch = scene.image[round(.72*h):round(.795*h), round(.32*w):round(.365*w)]
    if (not patch.size or patch.std() < 18
            or (cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 1] > 45).mean() < .12):
        raise AutomationError('饰品提取出战头像尚未就绪，未打开编队。')
    return Token('饰品提取预设编队入口', .99, (.32, .72, .365, .795))


def preset(scene, name):
    if not selection(scene):
        return None
    found = [t for t in scene.tokens if normalize(t.text) == normalize(name)
             and t.within((.015, .11, .24, .91))]
    if len(found) > 1:
        raise AutomationError('饰品提取预设编队名称重复，未选择。')
    return found[0] if found else None


def enabled(scene, name):
    target = preset(scene, name)
    if target is None:
        return False
    y = target.center[1]
    badge = scene.find('已启用', (.24, max(.11, y-.025), .295, min(.94, y+.025)), exact=True)
    levels = [t for t in scene.tokens if normalize(t.text).startswith('等级')
              and t.within((.02, y+.08, .29, min(.96, y+.16)))]
    return badge is not None and len(levels) == 4


def guard_click(scene, target, intent, name):
    if intent == 'planar_team_open':
        valid = target == entry(scene)
    elif intent == 'planar_team_tab':
        valid = (selection(scene) and normalize(target.text) == '预设编队'
                 and target.within((.15, 0, .30, .11)))
    elif intent == 'planar_team_select':
        valid = target == preset(scene, name) and target is not None
    else:
        valid = False
    if not valid:
        raise AutomationError('未核实饰品提取的指定预设编队控件，未选角。')


def select(workflow, scene):
    name = workflow.settings.differential_universe_team
    ctx = workflow.ctx
    def click(page, target, intent):
        ctx.click(page, target, du_intent=intent)
        return workflow._snapshot()
    if not selection(scene):
        scene = click(scene, entry(scene), 'planar_team_open')
        scene = workflow._wait(selection, timeout=12, description='等待饰品提取编队面板')
    scene = click(scene, scene.find('预设编队', (.15, 0, .30, .11), exact=True), 'planar_team_tab')
    scene = workflow._wait(lambda s: preset(s, name) is not None, timeout=12,
                           description=f'查找饰品提取预设编队 {name}')
    scene = click(scene, preset(scene, name), 'planar_team_select')
    scene = workflow._wait(lambda s: enabled(s, name), timeout=12,
                           description=f'核实饰品提取预设编队 {name} 四人完整且已启用')
    evidence = ctx.evidence(scene, 'planar_preset_team_verified')
    ctx.report.team_selections.append(dict(preset=name, verified=True, evidence=str(evidence), category='planar'))
    ctx.key('esc')
    return workflow._wait(lambda s: preparation(s) and not selection(s), timeout=12,
                          description='核实饰品提取预设编队收起')
