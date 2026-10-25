"""One explicitly authorized snack craft to fill a visible daily-training task."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from .config import ROOT, RESOURCE_ROOT
from .du_daily import account_key, game_day
from .models import AutomationError, Scene, Token, normalize
from .storage import replace_file

RECIPE = '奇巧零食'
TITLE = (0, 0, .32, .13)


def compact(text):
    return re.sub(r'[^\w\u3400-\u9fff/]', '', normalize(text))


def task_target(scene):
    if not (scene.has('星际和平指南', TITLE) and scene.has('每日实训', TITLE)):
        return None
    found = []
    for go in scene.tokens:
        if normalize(go.text) != '前往' or not go.within((.14, .68, .95, .88)):
            continue
        x = go.center[0]
        region = (x-.08, .38, x+.08, .70)
        content = compact(''.join(t.text for t in scene.tokens if t.within(region)))
        if ('使用1次万能合成机' in content and '进度0/1' in content
                and scene.has('+100', (x-.08, .60, x+.08, .71), exact=True)):
            found.append(go)
    return found[0] if len(found) == 1 else None


def recipe_shell(scene):
    return (scene.has('合成', (0, 0, .16, .065), exact=True)
            and scene.has('消耗品合成', TITLE, exact=True)
            and scene.has('所需材料', (.54, .50, .73, .59), exact=True)
            and scene.has('合成', (.50, .86, .75, .96), exact=True))


def selected(scene):
    return recipe_shell(scene) and scene.has(RECIPE, (.51, .12, .85, .23), exact=True)


def holding(scene):
    text = normalize(''.join(t.text for t in scene.tokens if t.within((.35, .44, .54, .51))))
    match = re.fullmatch(r'当前持有(\d{1,6})', text)
    return int(match[1]) if match else None


def quantity(scene):
    text = normalize(''.join(t.text for t in scene.tokens if t.within((.56, .75, .68, .80))))
    match = re.fullmatch(r'合成数量(\d{1,4})', text)
    return int(match[1]) if match else None


def materials(scene):
    amounts = []
    for token in sorted(scene.tokens, key=lambda t: t.center[0]):
        if token.within((.51, .65, .71, .72)):
            match = re.fullmatch(r'(\d{1,6})/(\d{1,3})', normalize(token.text))
            if match:
                amounts.append((int(match[1]), int(match[2])))
    return amounts


def ready(scene):
    resources = materials(scene)
    return (selected(scene) and holding(scene) is not None and quantity(scene) == 1
            and len(resources) == 2 and all(owned >= 1 and cost == 1 for owned, cost in resources)
            and not scene.has(('星琼', '燃料', '购买', '兑换', '支付', '确认合成', '材料不足')))


def recipe_target(scene):
    if not recipe_shell(scene) or scene.image is None:
        return None
    import cv2
    import numpy as np
    source = cv2.imdecode(np.fromfile(str(RESOURCE_ROOT/'assets/templates/daily_synthesis_snack.png'),
                                    dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = scene.image.shape[:2]
    baseline = cv2.resize(scene.image, (1920, round(height*1920/width)))
    h, w = baseline.shape[:2]
    left, top, right, bottom = round(.045*w), round(.11*h), round(.26*w), round(.90*h)
    area = baseline[top:bottom, left:right]
    hits = []
    for scale in np.linspace(.72, 1.28, 29):
        sample = cv2.resize(source, None, fx=scale, fy=scale)
        if sample.shape[0] > area.shape[0] or sample.shape[1] > area.shape[1]:
            continue
        scores = cv2.matchTemplate(area, sample, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(scores)
        if score >= .83:
            hits.append((score, (left+point[0]+sample.shape[1]/2)/w,
                         (top+point[1]+sample.shape[0]/2)/h))
    if not hits:
        return None
    score, x, y = max(hits)
    if any(abs(other_x-x) > .025 or abs(other_y-y) > .025 for _, other_x, other_y in hits):
        return None
    return Token(RECIPE+'配方', score, (x-.01, y-.01, x+.01, y+.01))


def reward_close(scene):
    if not (scene.has('获得物品', (.25, .04, .75, .40), exact=True)
            and scene.has(RECIPE, (.30, .45, .70, .65), exact=True)):
        return None
    return scene.find(('点击空白处关闭', '点击任意位置关闭'), (.25, .68, .75, .98), exact=True)


def confirmation(scene):
    if not scene.has('确认合成', (.35, .30, .65, .40), exact=True):
        return None
    prompt = ''.join(t.text for t in scene.tokens if t.within((.30, .54, .70, .60)))
    if not re.fullmatch(r'确认消耗以上物品进行合成奇巧零食[×x]1吗', normalize(prompt)):
        return None
    if scene.has(('购买', '兑换', '支付', '燃料', '星琼')):
        return None
    if not scene.has('取消', (.28, .62, .49, .68), exact=True):
        return None
    return scene.find('确认', (.51, .62, .71, .68), exact=True)


def guard_click(scene, target, intent, record):
    if not isinstance(target, Token) or record.get('task_verified') is not True:
        raise AutomationError('未核实每日实训合成任务，未操作合成。')
    if intent == 'daily_synthesis_open':
        valid = target == task_target(scene) and record.get('status') == 'selecting'
    elif intent == 'daily_synthesis_select':
        valid = target == recipe_target(scene) and record.get('status') == 'selecting'
    elif intent == 'daily_synthesis_commit':
        valid = (ready(scene) and record.get('status') == 'pending' and record.get('recipe') == RECIPE
                 and record.get('quantity') == 1 and record.get('before_holding') == holding(scene)
                 and record.get('before_materials') == materials(scene)
                 and target == scene.find('合成', (.50, .86, .75, .96), exact=True))
    elif intent == 'daily_synthesis_close':
        valid = (record.get('status') == 'pending' and target == reward_close(scene)
                 and not scene.has(('购买', '兑换', '支付', '燃料', '星琼')))
    elif intent == 'daily_synthesis_confirm':
        valid = (record.get('status') == 'pending' and record.get('recipe') == RECIPE
                 and record.get('quantity') == 1 and record.get('confirmation_sent') is True
                 and type(record.get('before_holding')) is int
                 and len(record.get('before_materials', [])) == 2
                 and all(owned >= 1 and cost == 1 for owned, cost in record['before_materials'])
                 and target == confirmation(scene))
    else:
        valid = False
    if not valid:
        raise AutomationError('合成目标、单件数量或任务证据不符，未发送点击。')


def _save(record, path):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
    replace_file(temporary, path)


def _finish(workflow, scene, record, path):
    ctx = workflow.ctx
    before = record['before_holding']

    def feedback(page):
        return (confirmation(page) is not None or reward_close(page) is not None
                or (selected(page) and holding(page) == before+1))

    if not feedback(scene):
        scene = workflow._wait(feedback, timeout=20, description='核实单件合成反馈')
    if account_key(scene) != record['account_key']:
        raise AutomationError('合成反馈账号不符，保留待核对记录。')
    target = confirmation(scene)
    if target is not None:
        if record.get('confirmation_sent'):
            raise AutomationError('此前已发送合成确认，保留待核对记录，不重复确认。')
        record.update(confirmation_sent=True,
                      confirmation_evidence=str(ctx.evidence(scene, 'daily_synthesis_confirmation')))
        _save(record, path)
        ctx.log('已核实确认弹窗为奇巧零食×1，发送一次合成确认。')
        ctx.click(scene, target, du_intent='daily_synthesis_confirm')
        scene = workflow._wait(lambda page: reward_close(page) is not None or
            (selected(page) and holding(page) == before+1), timeout=20, description='核实合成确认后的单件反馈')
    close = reward_close(scene)
    if close is not None:
        ctx.evidence(scene, 'daily_synthesis_received')
        ctx.click(scene, close, du_intent='daily_synthesis_close')
    expected = [(owned-1, 1) for owned, _ in record['before_materials']]
    scene = workflow._wait(lambda page: selected(page) and holding(page) == before+1
        and materials(page) == expected, timeout=15, description='核实零食增加1及两种材料各减少1')
    if account_key(scene) != record['account_key']:
        raise AutomationError('合成后账号变化，保留待核对记录。')
    record.update(status='complete', after_holding=holding(scene), after_materials=materials(scene),
                  after_evidence=str(ctx.evidence(scene, 'daily_synthesis_verified')),
                  finished_at=datetime.now().astimezone().isoformat())
    _save(record, path)
    ctx.log('已确认仅合成1个奇巧零食，返回每日实训领取活跃度和奖励。')


def resume_pending(workflow, scene):
    """Reconcile an interrupted craft before normal navigation can dismiss it."""
    key, day = account_key(scene), game_day()
    path = ROOT/'runs'/'daily-synthesis'/f'{day}-{key}.json'
    if not path.exists():
        return False
    record = json.loads(path.read_text('utf8'))
    if record.get('status') != 'pending':
        return False
    if (record.get('account_key') != key or record.get('game_day') != day
            or record.get('task_verified') is not True or record.get('recipe') != RECIPE
            or record.get('quantity') != 1 or type(record.get('before_holding')) is not int
            or len(record.get('before_materials', [])) != 2
            or not all(type(owned) is int and owned >= 1 and cost == 1
                       for owned, cost in record['before_materials'])):
        raise AutomationError('已有合成记录无法核实，未继续合成。')
    if not (confirmation(scene) is not None or reward_close(scene) is not None
            or (selected(scene) and holding(scene) == record['before_holding']+1)):
        raise AutomationError('已有合成记录待核对；当前未见原确认弹窗或单件结果，不重复合成。')
    workflow.ctx.report.daily_synthesis = record
    workflow.ctx.report.game_day = day
    workflow._daily_synthesis_attempted = True
    workflow.ctx.log('发现待核对的单件合成记录，接续原确认或核对结果。')
    _finish(workflow, scene, record, path)
    return True


def complete_once(workflow, scene):
    ctx = workflow.ctx
    key, day = account_key(scene), game_day()
    ctx.report.game_day = day
    folder = ROOT/'runs'/'daily-synthesis'
    path = folder/f'{day}-{key}.json'
    if path.exists():
        raise AutomationError('本游戏日已有合成记录，先核对原结果，不重复消耗材料。')
    record = dict(task_verified=True, status='selecting', recipe=RECIPE, quantity=1,
                  account_key=key, game_day=day, ledger=str(path))
    ctx.report.daily_synthesis = record
    ctx.log('每日实训不足500活跃：按合成任务，仅制作1个奇巧零食。')

    def click(page, target, intent):
        ctx.click(page, target, du_intent='daily_synthesis_'+intent)
        return workflow._snapshot()

    scene = click(scene, task_target(scene), 'open')
    scene = workflow._wait(recipe_shell, timeout=20, description='打开每日实训对应的消耗品合成页')
    for attempt in range(6):
        if selected(scene):
            break
        target = recipe_target(scene)
        if target is not None:
            scene = click(scene, target, 'select')
            scene = workflow._wait(selected, timeout=12, description='核实奇巧零食配方名称')
            break
        if attempt == 5:
            raise AutomationError('未找到奇巧零食配方，不合成其他物品。')
        ctx.move(scene, (.18, .65))
        ctx.scroll(-3)
        scene = workflow._snapshot()
        if not recipe_shell(scene):
            raise AutomationError('合成配方列表页面改变，未继续。')
    scene = workflow._wait(ready, timeout=12, description='核实仅合成1个奇巧零食及两种普通材料各1个')
    if account_key(scene) != key:
        raise AutomationError('合成页账号与每日实训不一致，未消耗材料。')
    record.update(status='pending', before_holding=holding(scene), before_materials=materials(scene),
                  before_evidence=str(ctx.evidence(scene, 'daily_synthesis_before')),
                  started_at=datetime.now().astimezone().isoformat())
    folder.mkdir(parents=True, exist_ok=True)
    # Exclusive durable intent before the only consuming click. Never replay it.
    with path.open('x', encoding='utf8') as handle:
        import os
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    ctx.log('已核实奇巧零食数量1，两种材料各消耗1个；开始合成。')
    scene = click(scene, scene.find('合成', (.50, .86, .75, .96), exact=True), 'commit')
    _finish(workflow, scene, record, path)
