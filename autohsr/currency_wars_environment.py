"""Choose only environment effects read completely from local captures."""
import time
import re
from dataclasses import dataclass

import numpy as np

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_deployment import _crop
from .currency_wars_match import read_match
from .models import AutomationError,EmptyCapture,normalize


CENTERS=(.229,.50,.771)

ENVIRONMENT_POLICY = 'initial-strength-v1'


@dataclass(frozen=True)
class EnvironmentOption:
    slot: int
    name: object
    effect: str
    kind: str | None
    parameters: tuple[tuple[str, int], ...] = ()
    score: int | None = None
    reason: str = ''


def parse_environment_effect(effect):
    """Exact effect grammar; title, tier, star, count and gold stay separate."""
    value = normalize(effect)
    if match := re.fullmatch(r'获得([1-9])个随机([1-4])星([1-5])费角色进入新节点时这位角色永久获得随机属性加成', value):
        count, star, tier = map(int, match.groups())
        return 'growing_unit', (('count', count), ('star', star), ('tier', tier)), 16+4*(star-1)+2*tier+2*(count-1), '优先首战即有的高星角色与后续成长；分数为待校准基线'
    if match := re.fullmatch(r'本局在固定节点进行投资策略选择时左、中、右的选项分别为银金彩品质并且投资策略刷新次数\+([1-9])', value):
        refreshes = int(match[1])
        return 'fixed_investment_tiers', (('extra_refreshes', refreshes),), 12+2*refreshes, '固定品质与更多投资候选；尚不推算随机策略收益'
    if match := re.fullmatch(r'进入到一个随机投资环境中开局额外获得([1-9][0-9]?)金币', value):
        gold = int(match[1])
        return 'random_environment_gold', (('gold', gold),), gold//2-4, '额外金币已读，但随机环境结果未知，保守排序'
    if value == '所有首领节点前都加入一个额外补给阶段':
        return 'boss_supply', (('extra_stages_per_boss', 1),), 18, '增加首领前补给；不把未来随机物品视作已持有'
    return None, (), None, '效果未完整匹配已核验语法，不生成可执行候选'


def standard_environment_options(scene, confidence=.65):
    from .currency_wars_prepare import trusted
    clean = trusted(scene, confidence)
    if observe(clean, confidence).page_kind != 'environment':
        raise AutomationError('当前不是投资环境选择页。')
    options = []
    for slot, cx in enumerate(CENTERS):
        names = [t for t in clean.tokens if t.within((cx-.115,.34,cx+.115,.38))]
        if len(names) != 1:
            continue
        # Read the full body, including a possible fourth line or lower
        # condition. A known prefix must not hide an unread penalty below it.
        parts = sorted((t for t in clean.tokens if t.within((cx-.115,.38,cx+.115,.78))),
                       key=lambda t:(round(t.center[1],2), t.center[0]))
        effect = ''.join(t.text for t in parts)
        kind, parameters, score, reason = parse_environment_effect(effect)
        options.append(EnvironmentOption(slot, names[0], effect, kind, parameters, score, reason))
    if not options:
        raise AutomationError('未完整定位投资环境卡片。')
    return tuple(options)


def standard_environment_choice(scene, confidence=.65):
    choices = [choice for choice in standard_environment_options(scene, confidence) if choice.score is not None]
    if not choices:
        raise AutomationError('没有效果已核实的环境候选，未选择或刷新。')
    # Semantic tie-break, independent of left/middle/right placement.
    return min(choices, key=lambda choice:(-choice.score, choice.kind, normalize(choice.name.text)))


def standard_environment_confirm(scene, choice, confidence=.65):
    if standard_environment_choice(scene, confidence) != choice or scene.image is None:
        raise AutomationError('当前环境选择与本次候选不一致。')
    chosen = []
    for slot, center in enumerate(CENTERS):
        border = _crop(scene.image, (center-.123,.20,center-.121,.79))
        if border.size and np.mean(np.min(border,axis=2)>200) >= .5:
            chosen.append(slot)
    button = _crop(scene.image, (.50,.895,.62,.925))
    if chosen != [choice.slot] or not button.size or np.mean(np.min(button,axis=2)>180) < .5:
        raise AutomationError('环境选中边框或确认按钮未核实。')
    from .currency_wars_navigation import unique
    from .currency_wars_prepare import trusted
    return unique(trusted(scene, confidence), '确认', (.50,.87,.65,.95))


def environment_choice(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='environment':
        raise AutomationError('投资环境页未核实。')
    for cx in CENTERS:
        names=[t for t in scene.tokens if confidence<=t.score<=1 and
               t.within((cx-.11,.34,cx+.11,.38)) and normalize(t.text)=='人身意外险']
        effect=sorted((t for t in scene.tokens if confidence<=t.score<=1 and
                       t.within((cx-.11,.38,cx+.11,.47))),key=lambda t:(round(t.center[1],2),t.center[0]))
        if len(names)==1 and ''.join(normalize(t.text) for t in effect)=='所有首领节点前都加入一个额外补给阶段':
            return names[0],cx
    raise AutomationError('没有完整核实效果的投资环境，未刷新或选择。')


def environment_confirm(scene,confidence=.65):
    _,cx=environment_choice(scene,confidence)
    if scene.image is None:
        raise AutomationError('环境选择缺少选中反馈图像。')
    chosen=[]
    for center in CENTERS:
        border=_crop(scene.image,(center-.123,.20,center-.121,.79))
        if border.size and np.mean(np.min(border,axis=2)>200)>=.5:
            chosen.append(center)
    button=_crop(scene.image,(.50,.895,.62,.925))
    if chosen!=[cx] or button.size==0 or np.mean(np.min(button,axis=2)>180)<.5:
        raise AutomationError('环境卡片边框或确认按钮与本次选择不符。')
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='确认' and
             t.within((.50,.87,.65,.95))]
    if len(targets)!=1:
        raise AutomationError('投资环境确认按钮不唯一。')
    return targets[0]


def choose_environment(c,scene,data,persist):
    name,_=environment_choice(scene,c.settings.ocr_confidence)
    guard=CurrencyWarsWorkflow(c)
    try:
        environment_confirm(scene,c.settings.ocr_confidence)
        phases=('confirm',)
    except AutomationError:
        phases=('select','confirm')
    for phase in phases:
        guard._require_current_scene(scene)
        action=dict(action=phase+'_environment',name=name.text,status='pending',
                    before=str(c.evidence(scene,'currency_environment_'+phase)))
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        c.currency_select_environment(scene,confirm=phase=='confirm')
        elapsed=0.
        while elapsed<20:
            started=time.monotonic()
            inactive=c.runner.inactive_duration
            try:
                after=c.snapshot()
            except EmptyCapture:
                after=None
            if after is not None:
                guard._require_current_scene(after)
                current=read_match(after,c.settings.ocr_confidence)
                ready=bool(current and current.page in ('shop','preparation') and current.node=='1-1') if phase=='confirm' else False
                if phase=='select':
                    try:
                        environment_confirm(after,c.settings.ocr_confidence)
                        ready=True
                    except AutomationError:
                        pass
                if ready:
                    action.update(status='verified',after=str(c.evidence(after,'currency_environment_after_'+phase)))
                    data.update(action_status='environment_verified',screenshot=action['after'])
                    if phase=='confirm':
                        data['environment']='人身意外险'
                    persist()
                    scene=after
                    break
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status']='unknown'
            if c.last_scene is not None:
                action['after']=str(c.evidence(c.last_scene,'currency_environment_unknown'))
                data['screenshot']=action['after']
            data['action_status']='unknown'
            persist()
            return False
    return True
